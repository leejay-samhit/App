# Iteration 114 — retest of iter113 fixes: curated-ids scope (H3), server search (H2), subcategory server filter (M5),
# 60/page deep walk (H4/M3 backend side), p95 latency, recharge category filters, admin/vendor pagers.
import os
import time
import statistics
import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
LAT, LNG = 13.7484, 79.7027
GEO = {"strict_location": "true", "lat": LAT, "lng": LNG}
PIN = "517644"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_h(s):
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=20)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def blocks(s, admin_h):
    d = s.get(f"{BASE}/api/admin/shop-layout", headers=admin_h, timeout=20).json()
    return d.get("items", d)


def _ids_of(blks):
    out = set()
    for b in blks:
        out |= set(b.get("product_ids") or [])
        if b.get("product_id"):
            out.add(b["product_id"])
    return out


def _is_global(b):
    return not (b.get("scope_pincodes") or []) and not (b.get("scope_pincode") or "")


# --- H3 curated ids scoping ---
class TestCuratedIds:
    def test_no_pincode_only_global(self, s, blocks):
        exp = _ids_of([b for b in blocks if b.get("active") and _is_global(b)])
        got = set(s.get(f"{BASE}/api/shop-layout/curated-product-ids", timeout=20).json()["items"])
        assert got == exp, f"got {len(got)} expected {len(exp)}"

    def test_matching_pincode_global_plus_pin(self, s, blocks):
        exp = _ids_of([b for b in blocks if b.get("active") and (
            _is_global(b) or PIN in (b.get("scope_pincodes") or []) or b.get("scope_pincode") == PIN)])
        got = set(s.get(f"{BASE}/api/shop-layout/curated-product-ids", params={"pincode": PIN}, timeout=20).json()["items"])
        assert got == exp and len(got) > 0

    def test_other_pincode_excludes_targeted(self, s, blocks):
        exp = _ids_of([b for b in blocks if b.get("active") and _is_global(b)])
        got = set(s.get(f"{BASE}/api/shop-layout/curated-product-ids", params={"pincode": "999999"}, timeout=20).json()["items"])
        assert got == exp


# --- H2 server-side search ---
class TestSearch:
    def test_search_mobiles_returns_items(self, s):
        d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "q": "Mobiles"}, timeout=20).json()
        print(f"q=Mobiles total={d['total']} items={len(d['items'])}")
        assert d["total"] > 0 and len(d["items"]) == min(60, d["total"])

    def test_search_brand(self, s):
        page = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60}, timeout=20).json()["items"]
        brand = next((p["brand"] for p in page if p.get("brand")), None)
        if not brand:
            pytest.skip("no brand on products")
        d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "q": brand}, timeout=20).json()
        print(f"brand={brand} total={d['total']}")
        assert d["total"] > 0 and len(d["items"]) > 0

    def test_search_finds_curated_product(self, s):
        cur = s.get(f"{BASE}/api/shop-layout/curated-product-ids", params={"pincode": PIN}).json()["items"]
        if not cur:
            pytest.skip("no curated ids")
        p = s.get(f"{BASE}/api/products", params={"ids": cur[0]}).json()["items"][0]
        d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "q": p["name"]}).json()
        assert cur[0] in [x["id"] for x in d["items"]]


# --- M5 subcategory server filter ---
class TestSubcategory:
    def test_subcategory_total_and_walk(self, s):
        page = s.get(f"{BASE}/api/products", params={**GEO, "limit": 200, "category": "Men"}, timeout=20).json()["items"]
        subs = [p.get("sub_category") or p.get("subcategory") for p in page]
        sub = next((x for x in subs if x), None)
        if not sub:
            pytest.skip("no sub_category under Men")
        p = {**GEO, "limit": 60, "category": "Men", "subcategory": sub}
        first = s.get(f"{BASE}/api/products", params=p).json()
        total, seen, off = first["total"], [x["id"] for x in first["items"]], 60
        cat_total = s.get(f"{BASE}/api/products", params={**GEO, "limit": 1, "category": "Men"}).json()["total"]
        while off < total:
            seen += [x["id"] for x in s.get(f"{BASE}/api/products", params={**p, "offset": off}).json()["items"]]
            off += 60
        print(f"Men/{sub} total={total} (Men={cat_total}) walked={len(seen)}")
        assert 0 < total < cat_total
        assert len(seen) == total == len(set(seen))
        for x in first["items"]:
            assert sub in ((x.get("sub_category") or ""), (x.get("subcategory") or ""))


# --- H4/M3 backend: 60-per-page walk like the app ---
class TestWalk60:
    def test_walk_60_no_dupes(self, s):
        first = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60}).json()
        total, seen, off = first["total"], [x["id"] for x in first["items"]], 60
        while off < total:
            d = s.get(f"{BASE}/api/products", params={**GEO, "limit": 60, "offset": off}, timeout=30).json()
            seen += [x["id"] for x in d["items"]]
            off += 60
        assert d["has_more"] is False
        assert len(seen) == total == len(set(seen)), f"{len(seen)} vs {total} uniq {len(set(seen))}"


# --- Performance p95 ---
def _p95(s, url, n=15, **kw):
    ts = []
    for _ in range(n):
        t = time.time()
        r = s.get(url, timeout=30, **kw)
        ts.append(time.time() - t)
        assert r.status_code == 200
    ts.sort()
    return ts[int(0.95 * (n - 1))], statistics.median(ts)


class TestPerf:
    def test_p95_all(self, s, admin_h):
        some_ids = ",".join(x["id"] for x in s.get(f"{BASE}/api/admin/products", params={"limit": 100}, headers=admin_h).json()["items"])
        cases = {
            "products p1": (f"{BASE}/api/products", {"params": {**GEO, "limit": 60}}),
            "products off3000": (f"{BASE}/api/products", {"params": {**GEO, "limit": 60, "offset": 3000}}),
            "products cat": (f"{BASE}/api/products", {"params": {**GEO, "limit": 60, "category": "Electronics"}}),
            "products q": (f"{BASE}/api/products", {"params": {**GEO, "limit": 60, "q": "PERFTEST Product 0599"}}),
            "admin 250 p1": (f"{BASE}/api/admin/products", {"params": {"limit": 250}, "headers": admin_h}),
            "admin 250 off2500": (f"{BASE}/api/admin/products", {"params": {"limit": 250, "offset": 2500}, "headers": admin_h}),
            "admin q": (f"{BASE}/api/admin/products", {"params": {"limit": 100, "q": "PERFTEST Product 05999"}, "headers": admin_h}),
            "admin ids100": (f"{BASE}/api/admin/products", {"params": {"ids": some_ids}, "headers": admin_h}),
            "shop-layout": (f"{BASE}/api/shop-layout", {"params": {"scope": "home", "pincode": PIN}}),
            "curated": (f"{BASE}/api/shop-layout/curated-product-ids", {"params": {"pincode": PIN}}),
        }
        slow = []
        for name, (url, kw) in cases.items():
            p95, med = _p95(s, url, **kw)
            print(f"PERF {name}: p95={p95:.3f}s median={med:.3f}s")
            if p95 > 1.0:
                slow.append((name, round(p95, 2)))
        assert not slow, f"slow endpoints: {slow}"


# --- Regression: category pickers + pagers ---
class TestRegression:
    def test_exclude_recharge_keeps_root_hides_children(self, s, admin_h):
        full = s.get(f"{BASE}/api/admin/shop-categories", headers=admin_h).json()["items"]
        root = next(c for c in full if c["name"].lower() == "recharge" and not c.get("parent_id"))
        kids = {c["id"] for c in full if c.get("parent_id") == root["id"]}
        ex = {c["id"] for c in s.get(f"{BASE}/api/admin/shop-categories", params={"exclude_recharge": "true"}, headers=admin_h).json()["items"]}
        assert root["id"] in ex and not (kids & ex)

    def test_exclude_recharge_root_hides_all(self, s, admin_h):
        items = s.get(f"{BASE}/api/admin/shop-categories", params={"exclude_recharge_root": "true"}, headers=admin_h).json()["items"]
        assert not any(c["name"].lower() == "recharge" for c in items)

    def test_bulk_category_rejects_unknown_and_recharge(self, s, admin_h):
        pid = s.get(f"{BASE}/api/admin/products", params={"limit": 1}, headers=admin_h).json()["items"][0]["id"]
        r1 = s.post(f"{BASE}/api/admin/products/bulk-category", json={"product_ids": [pid], "category": "TEST_nope_xyz"}, headers=admin_h)
        r2 = s.post(f"{BASE}/api/admin/products/bulk-category", json={"product_ids": [pid], "category": "Recharge"}, headers=admin_h)
        assert r1.status_code == 400 and r2.status_code == 400, (r1.text, r2.text)

    def test_admin_ids_order(self, s, admin_h):
        page = s.get(f"{BASE}/api/admin/products", params={"limit": 5, "offset": 3000}, headers=admin_h).json()["items"]
        ids = [x["id"] for x in page][::-1]
        got = [x["id"] for x in s.get(f"{BASE}/api/admin/products", params={"ids": ",".join(ids)}, headers=admin_h).json()["items"]]
        assert got == ids
