# Iteration 113 — scale/perf: /products?ids, /admin/products?ids, deep paging stability, timings
import os
import time
import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
LAT, LNG = 13.7484, 79.7027


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_h(s):
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"admin login failed {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _timed(s, url, **kw):
    t = time.time()
    r = s.get(url, timeout=30, **kw)
    return r, time.time() - t


# --- public /products paging + totals ---
class TestPublicPaging:
    def test_page1_total_is_full_catalogue(self, s):
        r, dt = _timed(s, f"{BASE}/api/products", params={"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 60})
        assert r.status_code == 200
        d = r.json()
        print(f"page1 total={d['total']} dt={dt:.2f}s")
        assert d["total"] > 6000
        assert len(d["items"]) == 60 and d["has_more"] is True
        assert dt < 1.5

    def test_deep_offset_3000(self, s):
        r, dt = _timed(s, f"{BASE}/api/products", params={"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 60, "offset": 3000})
        assert r.status_code == 200 and len(r.json()["items"]) == 60
        print(f"offset3000 dt={dt:.2f}s")
        assert dt < 1.5

    def test_category_mobiles_true_total(self, s):
        r, dt = _timed(s, f"{BASE}/api/products", params={"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 60, "category": "Mobiles"})
        d = r.json()
        print(f"Mobiles total={d['total']} dt={dt:.2f}s")
        assert d["total"] > 500 and dt < 1.5

    def test_public_walk_no_dupes_no_gaps(self, s):
        p = {"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 500}
        first = s.get(f"{BASE}/api/products", params=p, timeout=30).json()
        total = first["total"]
        seen = [x["id"] for x in first["items"]]
        off = 500
        while off < total:
            d = s.get(f"{BASE}/api/products", params={**p, "offset": off}, timeout=30).json()
            seen += [x["id"] for x in d["items"]]
            off += 500
        assert len(seen) == total, f"walked {len(seen)} vs total {total}"
        assert len(set(seen)) == total, f"dupes: {len(seen) - len(set(seen))}"


# --- /products?ids short-circuit ---
class TestIds:
    def test_ids_order_and_shape(self, s):
        page = s.get(f"{BASE}/api/products", params={"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 5, "offset": 4000}).json()["items"]
        ids = [x["id"] for x in page][::-1] + ["nonexistent-id-xyz"]
        r, dt = _timed(s, f"{BASE}/api/products", params={"ids": ",".join(ids)})
        d = r.json()
        assert [x["id"] for x in d["items"]] == ids[:5]
        assert d["total"] == 5 and d["has_more"] is False
        assert dt < 1.0

    def test_ids_ignores_location_gate(self, s):
        page = s.get(f"{BASE}/api/products", params={"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 3}).json()["items"]
        ids = [x["id"] for x in page]
        d = s.get(f"{BASE}/api/products", params={"ids": ",".join(ids), "strict_location": "true"}).json()
        assert len(d["items"]) == 3

    def test_ids_cap_300(self, s):
        page = s.get(f"{BASE}/api/products", params={"strict_location": "true", "lat": LAT, "lng": LNG, "limit": 350}).json()["items"]
        ids = [x["id"] for x in page]
        assert len(ids) == 350
        d = s.get(f"{BASE}/api/products", params={"ids": ",".join(ids)}).json()
        assert len(d["items"]) == 300

    def test_admin_ids_order(self, s, admin_h):
        page = s.get(f"{BASE}/api/admin/products", params={"limit": 5, "offset": 3000}, headers=admin_h).json()["items"]
        ids = [x["id"] for x in page][::-1]
        d = s.get(f"{BASE}/api/admin/products", params={"ids": ",".join(ids)}, headers=admin_h).json()
        got = [x["id"] for x in d["items"]]
        assert set(got) == set(ids) and d["has_more"] is False
        print(f"admin ids order preserved: {got == ids}")
        assert got == ids, "admin ?ids does not preserve requested order"


# --- admin deep paging stability + timings ---
class TestAdminPaging:
    def test_admin_walk_250_no_dupes_no_gaps(self, s, admin_h):
        first = s.get(f"{BASE}/api/admin/products", params={"limit": 250}, headers=admin_h, timeout=30).json()
        total = first["total"]
        seen = [x["id"] for x in first["items"]]
        off = 250
        while off < total:
            d = s.get(f"{BASE}/api/admin/products", params={"limit": 250, "offset": off}, headers=admin_h, timeout=30).json()
            seen += [x["id"] for x in d["items"]]
            off += 250
        print(f"admin total={total} walked={len(seen)} unique={len(set(seen))}")
        assert total >= 6303
        assert len(seen) == total and len(set(seen)) == total

    def test_admin_timings(self, s, admin_h):
        r1, t1 = _timed(s, f"{BASE}/api/admin/products", params={"limit": 250, "offset": 2500}, headers=admin_h)
        r2, t2 = _timed(s, f"{BASE}/api/admin/products", params={"limit": 100, "q": "PERFTEST Product 05999"}, headers=admin_h)
        r3, t3 = _timed(s, f"{BASE}/api/shop-layout/curated-product-ids")
        print(f"admin offset2500={t1:.2f}s search={t2:.2f}s curated={t3:.2f}s")
        assert r1.status_code == r2.status_code == r3.status_code == 200
        names = [x["name"] for x in r2.json()["items"]]
        assert "PERFTEST Product 05999" in names
        assert isinstance(r3.json().get("items"), list)
        assert max(t1, t2, t3) < 1.5
