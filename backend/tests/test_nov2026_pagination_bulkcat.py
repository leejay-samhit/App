# Nov 2026 — pagination (admin/vendor/public), exclude_recharge, bulk-category
import os
import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
OPERATORS = ["vi", "jio", "airtel", "bsnl", "dish tv", "tata play", "sun direct",
             "airtel digital tv", "mobile recharge", "dth tv recharge"]


def _login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed {email}: {r.status_code}")
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def admin():
    return _login("support@slangcart.com", "3)Ywxtic")


def _walk(url, headers, page, params=None):
    ids, pages, total = [], [], None
    off = 0
    while True:
        r = requests.get(url, headers=headers, params={**(params or {}), "limit": page, "offset": off}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        items = d.get("items") if isinstance(d, dict) else d
        total = d.get("total")
        ids += [i["id"] for i in items]
        pages.append((off, len(items), d.get("has_more")))
        if not d.get("has_more"):
            break
        off += page
        assert off < 200000
    return ids, pages, total


# --- BUG 1a: admin paging
class TestAdminPaging:
    def test_limit_500_accepted(self, admin):
        r = requests.get(f"{BASE}/admin/products", headers=admin, params={"limit": 500}, timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert len(d["items"]) == min(500, d["total"])

    def test_walk_250_all_unique(self, admin):
        ids, pages, total = _walk(f"{BASE}/admin/products", admin, 250)
        print(pages, total)
        assert len(ids) == len(set(ids)) == total == db.products.count_documents({})
        for off, n, hm in pages:
            assert hm == (off + n < total)

    def test_walk_60_all_unique(self, admin):
        ids, _, total = _walk(f"{BASE}/admin/products", admin, 60)
        assert len(ids) == len(set(ids)) == total


# --- BUG 1d: public paging
class TestPublicPaging:
    def test_limit_500_accepted(self):
        r = requests.get(f"{BASE}/products", params={"limit": 500}, timeout=60)
        assert r.status_code == 200

    def test_limit_501_rejected(self):
        r = requests.get(f"{BASE}/products", params={"limit": 501}, timeout=60)
        assert r.status_code == 422

    def test_walk_public_unique(self):
        ids, pages, total = _walk(f"{BASE}/products", {}, 250)
        print(pages, total)
        assert len(ids) == len(set(ids)) == total


# --- BUG 2: exclude_recharge
class TestShopCategories:
    def _flat(self, d):
        items = d.get("items", d) if isinstance(d, dict) else d
        out = []

        def rec(xs):
            for x in xs:
                out.append(x)
                rec(x.get("children") or x.get("subcategories") or [])
        rec(items)
        return out

    def test_exclude_recharge(self, admin):
        r = requests.get(f"{BASE}/admin/shop-categories", headers=admin, params={"exclude_recharge": "true"}, timeout=30)
        assert r.status_code == 200
        names = [(c.get("name") or "").strip().lower() for c in self._flat(r.json())]
        assert "recharge" in names
        leaked = [n for n in names if n in OPERATORS]
        assert not leaked, leaked

    def test_plain_has_all(self, admin):
        r = requests.get(f"{BASE}/admin/shop-categories", headers=admin, timeout=30)
        names = [(c.get("name") or "").strip().lower() for c in self._flat(r.json())]
        assert "recharge" in names
        present = [n for n in OPERATORS if n in names]
        print("operators present:", present)
        assert len(present) >= 5


# --- BUG 4a: bulk-category
class TestBulkCategory:
    def test_validation(self, admin):
        u = f"{BASE}/admin/products/bulk-category"
        assert requests.post(u, headers=admin, json={"product_ids": [], "category": "X"}).status_code == 400
        assert requests.post(u, headers=admin, json={"product_ids": ["a"]}).status_code == 400
        assert requests.post(u, headers=admin, json={"product_ids": ["a"], "category": "   "}).status_code == 400
        assert requests.post(u, headers=admin, json={"product_ids": [f"x{i}" for i in range(2001)], "category": "X"}).status_code == 400

    def test_requires_admin(self):
        r = requests.post(f"{BASE}/admin/products/bulk-category", json={"product_ids": ["a"], "category": "X"})
        assert r.status_code in (401, 403)

    def test_rejects_unknown_category(self, admin):
        r = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                          json={"product_ids": ["a"], "category": "NO_SUCH_SHELF_XYZ"})
        assert r.status_code == 400, r.text

    def test_apply_and_restore(self, admin):
        db.shop_categories.update_one(
            {"name": "TEST_Cat"},
            {"$setOnInsert": {"id": "test-cat-nov2026", "name": "TEST_Cat", "parent_id": None,
                              "active": True, "sort_order": 999}},
            upsert=True,
        )
        docs = list(db.products.find({"sub_category": {"$exists": True}}, {"_id": 0, "images": 0, "description": 0}).limit(2))
        assert len(docs) == 2
        ids = [d["id"] for d in docs]
        snap = {d["id"]: d for d in docs}
        try:
            r = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                              json={"product_ids": ids, "category": "TEST_Cat", "subcategory": "TEST_Sub"})
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["ok"] and d["updated"] == 2 and d["requested"] == 2
            assert d["category"] == "TEST_Cat" and d["subcategory"] == "TEST_Sub"
            for pid in ids:
                now = db.products.find_one({"id": pid}, {"_id": 0, "images": 0, "description": 0})
                assert now["category"] == "TEST_Cat" and now["subcategory"] == "TEST_Sub"
                for k in ("price", "stock", "vendor_id", "image_url", "mrp", "is_published"):
                    assert now.get(k) == snap[pid].get(k), k
            # Stale `sub_category` would keep product on its OLD shelf
            stale = [db.products.find_one({"id": p}).get("sub_category") for p in ids]
            print("sub_category after mapping:", stale)
            r2 = requests.get(f"{BASE}/products", params={"category": "TEST_Cat", "subcategory": "TEST_Sub", "limit": 50})
            got = {i["id"] for i in r2.json().get("items", [])}
            print("public filter TEST_Cat/TEST_Sub returns", len(got & set(ids)))
            assert all(s in (None, "", "TEST_Sub") for s in stale), f"stale sub_category left: {stale}"
        finally:
            for pid, d in snap.items():
                restore = {k: d.get(k) for k in ("category", "subcategory", "sub_category", "updated_at") if k in d}
                unset = {k: "" for k in ("category", "subcategory", "sub_category", "updated_at") if k not in d}
                op = {"$set": restore}
                if unset:
                    op["$unset"] = unset
                db.products.update_one({"id": pid}, op)
            db.shop_categories.delete_one({"id": "test-cat-nov2026"})


# --- BUG 1c: vendor paging (runs last: vendor login)
class TestVendorPaging:
    def test_vendor_walk(self):
        h = _login("testvendor@test.com", "Test@1234")
        ids, pages, total = _walk(f"{BASE}/vendor/me/products", h, 250)
        print(pages, total)
        assert len(ids) == len(set(ids)) == total
        r = requests.get(f"{BASE}/vendor/me/products", headers=h, params={"limit": 500})
        assert r.status_code == 200
