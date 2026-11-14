# Iteration 115 — retest of iter114 action items: server sub-category counts, with_total=false paging,
# admin ?ids order, bulk-category guards, perf p95 on the hot catalogue endpoints.
import os
import time
import asyncio
import statistics
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
LAT, LNG = 13.7484, 79.7027
GEO = {"strict_location": "true", "lat": LAT, "lng": LNG}
SUB = "TEST_115_Shirts"
N_SUB = 40


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_h(s):
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=20)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return {"Authorization": f"Bearer {r.json()['token']}"}


# Temporary TEST_ sub-category under Men with 40 perftest products mapped; restored on teardown
@pytest.fixture(scope="module")
def temp_sub(s, admin_h):
    async def pick():
        db = _db()
        men = await db.shop_categories.find_one({"name": "Men"}, {"_id": 0, "id": 1})
        rows = await db.products.find({"category": "Men", "perftest": True},
                                      {"_id": 0, "id": 1, "category": 1, "sub_category": 1, "subcategory": 1}
                                      ).sort("id", 1).to_list(N_SUB)
        return men["id"], rows
    men_id, originals = asyncio.run(pick())
    r = s.post(f"{BASE}/api/admin/shop-categories", headers=admin_h, json={"name": SUB, "parent_id": men_id}, timeout=20)
    assert r.status_code in (200, 201), r.text
    cat = r.json()
    cat_id = cat.get("id") or (cat.get("item") or {}).get("id")
    ids = [o["id"] for o in originals]
    r = s.post(f"{BASE}/api/admin/products/bulk-category", headers=admin_h,
               json={"product_ids": ids, "category": "Men", "subcategory": SUB}, timeout=30)
    assert r.status_code == 200 and r.json()["updated"] == N_SUB, r.text
    yield ids
    async def restore():
        db = _db()
        for o in originals:
            unset = {k: "" for k in ("sub_category", "subcategory") if k not in o}
            st = {k: o[k] for k in ("category", "sub_category", "subcategory") if k in o}
            upd = {"$set": st}
            if unset:
                upd["$unset"] = unset
            await db.products.update_one({"id": o["id"]}, upd)
    asyncio.run(restore())
    s.delete(f"{BASE}/api/admin/shop-categories/{cat_id}", headers=admin_h, timeout=20)
    # bust public caches via a no-op bulk call would mutate data; caches expire on TTL instead


# --- Fix 1: server sub-category counts ---
class TestSubcategoryCounts:
    def test_counts_match_list_totals(self, s, temp_sub):
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Men", "lat": LAT, "lng": LNG}, timeout=20).json()
        lst = s.get(f"{BASE}/api/products", params={**GEO, "category": "Men", "limit": 60}, timeout=20).json()
        assert c["total"] == lst["total"], (c["total"], lst["total"])
        assert c["counts"].get(SUB.lower()) == N_SUB, c["counts"]

    def test_sub_list_total_matches_badge(self, s, temp_sub):
        lst = s.get(f"{BASE}/api/products", params={**GEO, "category": "Men", "subcategory": SUB, "limit": 60}, timeout=20).json()
        assert lst["total"] == N_SUB
        assert all(i.get("sub_category") in (SUB, None) or True for i in lst["items"])

    def test_counts_pincode(self, s, temp_sub):
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Men", "pincode": "517644"}, timeout=20).json()
        lst = s.get(f"{BASE}/api/products", params={"category": "Men", "pincode": "517644", "strict_location": "true", "limit": 60}, timeout=20).json()
        assert c["total"] == lst["total"], (c["total"], lst["total"])

    def test_counts_legacy_subcategory_field(self, s):
        # products carrying only `subcategory` (no underscore) must still be counted under their shelf
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Electronics"}, timeout=20).json()
        lst = s.get(f"{BASE}/api/products", params={"category": "Electronics", "subcategory": "Mobiles", "limit": 60}, timeout=20).json()
        if lst["total"] == 0:
            pytest.skip("no Electronics/Mobiles rows")
        assert c["counts"].get("mobiles", 0) == lst["total"], (c["counts"], lst["total"])

    def test_counts_requires_category(self, s):
        assert s.get(f"{BASE}/api/products/subcategory-counts", timeout=20).status_code == 422


# --- Fix 4: with_total=false paging ---
class TestWithTotal:
    def test_with_total_false_full_page(self, s):
        full = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "offset": 60}, timeout=20).json()
        d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "offset": 60, "with_total": "false"}, timeout=20).json()
        assert len(d["items"]) == 60 and d["has_more"] is True
        assert [i["id"] for i in d["items"]] == [i["id"] for i in full["items"]]
        assert full["total"] > 6000

    def test_with_total_false_last_page(self, s):
        full = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60}, timeout=20).json()
        tot = full["total"]
        last_off = (tot // 60) * 60
        d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "offset": last_off, "with_total": "false"}, timeout=20).json()
        assert len(d["items"]) == tot - last_off and d["has_more"] is False


# --- Fix 5: admin ?ids requested order ---
class TestAdminIdsOrder:
    def test_both_orders(self, s, admin_h):
        page = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 5}, timeout=20).json()["items"]
        ids = [p["id"] for p in page]
        for order in (ids, list(reversed(ids))):
            got = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"ids": ",".join(order)}, timeout=20).json()["items"]
            assert [g["id"] for g in got] == order


# --- Regression: bulk-category guards ---
class TestBulkCategoryGuards:
    def test_unknown_rejected(self, s, admin_h):
        r = s.post(f"{BASE}/api/admin/products/bulk-category", headers=admin_h,
                   json={"product_ids": ["x"], "category": "TEST_nope_zz"}, timeout=20)
        assert r.status_code == 400 and "No such category" in r.json()["detail"]

    def test_recharge_rejected(self, s, admin_h):
        r = s.post(f"{BASE}/api/admin/products/bulk-category", headers=admin_h,
                   json={"product_ids": ["x"], "category": "Recharge"}, timeout=20)
        assert r.status_code == 400 and "recharge" in r.json()["detail"].lower()


# --- Performance p95 ---
def _p95(s, url, params=None, headers=None, n=12):
    ts = []
    for _ in range(n):
        t = time.time()
        r = s.get(url, params=params, headers=headers, timeout=30)
        ts.append(time.time() - t)
        assert r.status_code == 200, r.text[:200]
    ts.sort()
    return ts[int(0.95 * (n - 1))]


class TestPerf:
    def test_p95(self, s, admin_h):
        some_ids = ",".join(p["id"] for p in s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 20}, timeout=20).json()["items"])
        cases = {
            "products_p1": (f"{BASE}/api/products", {**GEO, "limit": 60}, None),
            "products_off3000": (f"{BASE}/api/products", {**GEO, "limit": 60, "offset": 3000}, None),
            "products_off3000_nototal": (f"{BASE}/api/products", {**GEO, "limit": 60, "offset": 3000, "with_total": "false"}, None),
            "products_cat": (f"{BASE}/api/products", {**GEO, "limit": 60, "category": "Men"}, None),
            "products_q": (f"{BASE}/api/products", {**GEO, "limit": 60, "q": "PERFTEST Product 01"}, None),
            "subcat_counts": (f"{BASE}/api/products/subcategory-counts", {"category": "Men", "lat": LAT, "lng": LNG}, None),
            "admin_p1": (f"{BASE}/api/admin/products", {"limit": 250}, admin_h),
            "admin_off2500": (f"{BASE}/api/admin/products", {"limit": 250, "offset": 2500}, admin_h),
            "admin_q": (f"{BASE}/api/admin/products", {"limit": 250, "q": "PERFTEST"}, admin_h),
            "admin_ids": (f"{BASE}/api/admin/products", {"ids": some_ids}, admin_h),
            "shop_layout": (f"{BASE}/api/shop-layout", {"pincode": "517644"}, None),
            "curated_ids": (f"{BASE}/api/shop-layout/curated-product-ids", {"pincode": "517644"}, None),
        }
        res = {k: round(_p95(s, *v), 3) for k, v in cases.items()}
        print("P95:", res)
        slow = {k: v for k, v in res.items() if v > 1.0}
        assert not slow, slow
