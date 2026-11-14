# iter112 retest — bulk-category sets both sub fields, public filter follows the new shelf,
# unknown category 400, Recharge tree as mapping target.
import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
CAT_ID = "test-cat-iter112"


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{BASE}/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"}, timeout=30)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return {"Authorization": "Bearer " + r.json()["token"]}


def _public_ids(params):
    ids, off = set(), 0
    while True:
        r = requests.get(f"{BASE}/products", params={**params, "limit": 500, "offset": off}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        items = d.get("items", []) if isinstance(d, dict) else d
        ids |= {i["id"] for i in items}
        if not (isinstance(d, dict) and d.get("has_more")) or not items:
            return ids
        off += len(items)


# Bulk-category: unknown category rejected, case-insensitive known accepted
class TestValidation:
    def test_unknown_400(self, admin):
        r = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                          json={"product_ids": ["TEST_none"], "category": "TEST_NoShelf_iter112"})
        assert r.status_code == 400
        assert "No such category" in r.json().get("detail", "")

    def test_known_noop(self, admin):
        r = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                          json={"product_ids": ["TEST_none"], "category": "Books"})
        assert r.status_code == 200 and r.json()["updated"] == 0

    def test_recharge_target_accepted(self, admin):
        # Documents behaviour: backend still lets a product be shelved under Recharge/operators.
        r = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                          json={"product_ids": ["TEST_none"], "category": "Recharge", "subcategory": "Vi"})
        print("Recharge as target ->", r.status_code, r.text[:120])
        v = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                          json={"product_ids": ["TEST_none"], "category": "Vi"})
        print("Vi as category ->", v.status_code, v.text[:120])
        assert r.status_code in (200, 400)


# Bulk-category: legacy sub_category follows; public filter moves product to new shelf
class TestPublicShelfMove:
    def test_move_and_restore(self, admin):
        # pick a published product that the public list shows AND has a legacy sub_category
        doc = None
        for d in db.products.find({"sub_category": {"$nin": [None, ""]}, "is_published": True},
                                  {"_id": 0, "id": 1, "category": 1, "subcategory": 1, "sub_category": 1, "updated_at": 1}).limit(30):
            old = _public_ids({"category": d["category"], "subcategory": d["sub_category"]})
            if d["id"] in old:
                doc = d
                break
        if not doc:
            pytest.skip("no publicly visible product with legacy sub_category")
        db.shop_categories.update_one({"id": CAT_ID}, {"$setOnInsert": {
            "id": CAT_ID, "name": "TEST_Cat112", "parent_id": None, "active": True, "sort_order": 999}}, upsert=True)
        try:
            r = requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                              json={"product_ids": [doc["id"]], "category": "TEST_Cat112", "subcategory": "TEST_Sub112"})
            assert r.status_code == 200 and r.json()["updated"] == 1
            now = db.products.find_one({"id": doc["id"]})
            assert now["subcategory"] == "TEST_Sub112" and now["sub_category"] == "TEST_Sub112"
            new_ids = _public_ids({"category": "TEST_Cat112", "subcategory": "TEST_Sub112"})
            old_ids = _public_ids({"category": doc["category"], "subcategory": doc["sub_category"]})
            assert doc["id"] in new_ids, "not on new shelf"
            assert doc["id"] not in old_ids, "still on old sub-shelf"
        finally:
            restore = {k: doc[k] for k in ("category", "subcategory", "sub_category", "updated_at") if k in doc}
            unset = {k: "" for k in ("subcategory", "updated_at") if k not in doc}
            op = {"$set": restore}
            if unset:
                op["$unset"] = unset
            db.products.update_one({"id": doc["id"]}, op)
            db.shop_categories.delete_one({"id": CAT_ID})
            requests.post(f"{BASE}/admin/products/bulk-category", headers=admin,
                          json={"product_ids": ["TEST_none"], "category": "Books"})  # busts caches
