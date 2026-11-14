# Iteration 116 — retest of iter115 items: legacy subcategory counts (E), text-index search
# correctness (F), ?ids interest counts (B), dead-product ids (D), regression sweep.
import os
import re
import asyncio
import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
LAT, LNG = 13.7484, 79.7027
GEO = {"strict_location": "true", "lat": LAT, "lng": LNG}
PUB = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _regex_count(q):
    n = re.escape(q)
    flt = {"$and": [PUB, {"$or": [{f: {"$regex": n, "$options": "i"}} for f in
                                  ("name", "description", "brand", "category", "sub_category", "subcategory", "tags")]}]}
    from pymongo import MongoClient
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]].products.count_documents(flt)


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_h(s):
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=20)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _q(s, q, **extra):
    d = s.get(f"{BASE}/api/products", params={"q": q, "limit": 60, **extra}, timeout=30).json()
    return d


# --- E: legacy `subcategory` rows counted ---
class TestLegacyCounts:
    def test_legacy_only_rows_counted(self, s):
        async def agg():
            db = _db()
            rows = await db.products.aggregate([
                {"$match": {"$and": [PUB, {"category": "Electronics"}, {"sub_category": {"$exists": False}},
                                     {"subcategory": {"$exists": True, "$ne": ""}}]}},
                {"$group": {"_id": {"$toLower": "$subcategory"}, "n": {"$sum": 1}}}]).to_list(50)
            return {r["_id"]: r["n"] for r in rows}
        legacy = asyncio.run(agg())
        if not legacy:
            pytest.skip("no legacy-only rows")
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Electronics"}, timeout=20).json()
        for k, n in legacy.items():
            assert c["counts"].get(k.strip(), 0) >= n, (k, n, c["counts"])

    def test_counts_total_matches_list_total_geo(self, s):
        for cat in ("Electronics", "Men", "Beauty"):
            c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": cat, "lat": LAT, "lng": LNG}, timeout=20).json()
            lst = s.get(f"{BASE}/api/products", params={**GEO, "category": cat, "limit": 1}, timeout=20).json()
            assert c["total"] == lst["total"], (cat, c["total"], lst["total"])


# --- F: search correctness with the text index ---
class TestSearch:
    def test_widget(self, s):
        assert _q(s, "Widget")["total"] == 2

    def test_exact_multiword(self, s):
        d = _q(s, "PERFTEST Product 00500")
        assert d["total"] == 1 and d["items"][0]["name"] == "PERFTEST Product 00500"

    def test_mobile_category_rows(self, s):
        d = _q(s, "mobile")
        assert d["total"] == _regex_count("mobile") and d["total"] > 0
        assert all(i.get("category") == "Mobiles" for i in d["items"])

    def test_partial(self, s):
        assert _q(s, "Produ")["total"] == _regex_count("Produ") > 0

    def test_nonsense(self, s):
        assert _q(s, "zzqxv_nonsense_9")["total"] == 0

    # Text index only covers name/brand/tags; a category word that also appears in ONE product
    # name must still return the whole category (regex behaviour before the change).
    @pytest.mark.parametrize("word", ["beauty", "Shoes", "Laptop", "test"])
    def test_single_word_matches_regex_semantics(self, s, word):
        assert _q(s, word)["total"] == _regex_count(word), word


# --- B: ?ids carries interested_count and drops unknown ids ---
class TestIds:
    def test_ids_have_interest_and_order(self, s, admin_h):
        page = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 250, "offset": 250}, timeout=30).json()["items"]
        ids = [p["id"] for p in page]
        d = s.get(f"{BASE}/api/products", params={"ids": ",".join(ids)}, timeout=30).json()
        assert all("interested_count" in i for i in d["items"])
        got = [i["id"] for i in d["items"]]
        assert got == [i for i in ids if i in set(got)]

    def test_unknown_ids_empty(self, s):
        d = s.get(f"{BASE}/api/products", params={"ids": "TEST_deleted_zz1,TEST_deleted_zz2"}, timeout=20).json()
        assert d["items"] == [] and d["total"] == 0


# --- Regression: paging, curated ids, bulk guards ---
class TestRegression:
    def test_deep_paging_no_dupes(self, s):
        seen = []
        for off in range(0, 600, 60):
            d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "offset": off,
                                                     "with_total": "false" if off else "true"}, timeout=30).json()
            seen += [i["id"] for i in d["items"]]
        assert len(seen) == len(set(seen)) == 600

    def test_curated_ids(self, s):
        r = s.get(f"{BASE}/api/shop-layout/curated-product-ids", params={"pincode": "517644"}, timeout=20)
        assert r.status_code == 200

    def test_bulk_recharge_rejected(self, s, admin_h):
        r = s.post(f"{BASE}/api/admin/products/bulk-category", headers=admin_h,
                   json={"product_ids": ["x"], "category": "Recharge"}, timeout=20)
        assert r.status_code == 400
