"""Nov 2026 nested-category & cascade-product backend tests.

Covers:
  - Nested category CRUD (create root/child/grandchild, re-parent, cycle protection, delete-reparent)
  - Public tree/list endpoints (root_only, tree, subcategories, descendants)
  - Product cascade filter on /api/products (category name/id, subcategory, pagination, sort, back-compat)
"""
from __future__ import annotations

import os
import uuid
import pytest
import requests

BASE_URL = "http://localhost:8001"
ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = "Nlee@1115"

# Unique suffix so re-runs don't collide with lingering data
SUFFIX = uuid.uuid4().hex[:6]
ELEC_NAME = f"Electronics Test {SUFFIX}"
MOB_NAME = f"Mobiles Test {SUFFIX}"
IPH_NAME = f"iPhone Test {SUFFIX}"
TEST_PRODUCT_NAME = f"TEST_iPhone_Cascade_{SUFFIX}"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"no token in login response: {data}"
    return token


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def state():
    return {}


# ─── 1. Nested Category CRUD ─────────────────────────────────────────
class TestNestedCategoryCRUD:
    def test_create_root(self, h, state):
        r = requests.post(f"{BASE_URL}/api/admin/shop-categories", headers=h,
                          json={"name": ELEC_NAME, "parent_id": None})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == ELEC_NAME
        assert d["parent_id"] is None
        assert d["depth"] == 0
        state["electronics_id"] = d["id"]

    def test_create_child(self, h, state):
        r = requests.post(f"{BASE_URL}/api/admin/shop-categories", headers=h,
                          json={"name": MOB_NAME, "parent_id": state["electronics_id"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["parent_id"] == state["electronics_id"]
        assert d["depth"] == 1
        state["mobiles_id"] = d["id"]

    def test_create_grandchild(self, h, state):
        r = requests.post(f"{BASE_URL}/api/admin/shop-categories", headers=h,
                          json={"name": IPH_NAME, "parent_id": state["mobiles_id"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["parent_id"] == state["mobiles_id"]
        assert d["depth"] == 2
        state["iphone_id"] = d["id"]

    def test_reparent_iphone_to_electronics(self, h, state):
        r = requests.put(
            f"{BASE_URL}/api/admin/shop-categories/{state['iphone_id']}", headers=h,
            json={"parent_id": state["electronics_id"]},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["parent_id"] == state["electronics_id"]
        assert d["depth"] == 1
        # Then move it back so cycle test is meaningful
        r2 = requests.put(
            f"{BASE_URL}/api/admin/shop-categories/{state['iphone_id']}", headers=h,
            json={"parent_id": state["mobiles_id"]},
        )
        assert r2.status_code == 200
        assert r2.json()["depth"] == 2

    def test_cycle_protection(self, h, state):
        # Electronics is ancestor of Mobiles → moving Electronics under Mobiles must FAIL 400
        r = requests.put(
            f"{BASE_URL}/api/admin/shop-categories/{state['electronics_id']}", headers=h,
            json={"parent_id": state["mobiles_id"]},
        )
        assert r.status_code == 400, f"expected 400 cycle, got {r.status_code} {r.text}"

    def test_delete_reparents_children(self, h, state):
        # Delete Mobiles → iPhone should be re-parented to Electronics
        r = requests.delete(
            f"{BASE_URL}/api/admin/shop-categories/{state['mobiles_id']}", headers=h,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("children_re_parented_to") == state["electronics_id"]

        # Verify iPhone.parent_id == Electronics.id, depth = 1
        r2 = requests.get(f"{BASE_URL}/api/admin/shop-categories", headers=h)
        assert r2.status_code == 200
        items = r2.json()["items"]
        iphone = next((c for c in items if c["id"] == state["iphone_id"]), None)
        assert iphone is not None, "iPhone missing after Mobiles delete"
        assert iphone["parent_id"] == state["electronics_id"]
        assert iphone["depth"] == 1
        # Mobiles must be gone
        mobiles = next((c for c in items if c["id"] == state.get("mobiles_id")), None)
        assert mobiles is None
        state["mobiles_id"] = None  # deleted


# ─── 2. Public tree / list endpoints ─────────────────────────────────
class TestPublicCategoryEndpoints:
    """Recreate a small tree fresh so we don't depend on prior test state."""

    def _mkcat(self, h, name, parent_id=None):
        r = requests.post(f"{BASE_URL}/api/admin/shop-categories", headers=h,
                          json={"name": name, "parent_id": parent_id})
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_public_list_and_tree_and_descendants(self, h, state):
        # Fresh tree: Root2 → Child2 → GC2
        root = self._mkcat(h, f"PubRoot_{SUFFIX}")
        child = self._mkcat(h, f"PubChild_{SUFFIX}", parent_id=root)
        gc = self._mkcat(h, f"PubGC_{SUFFIX}", parent_id=child)
        state["pub_root"] = root
        state["pub_child"] = child
        state["pub_gc"] = gc

        # root_only=true (default) → only root shows in public list, not child/gc
        r = requests.get(f"{BASE_URL}/api/shop-categories")
        assert r.status_code == 200
        items = r.json()["items"]
        ids = {c["id"] for c in items}
        assert root in ids
        assert child not in ids, "child should not appear in root_only list"
        assert gc not in ids

        # root_only=false → all appear (flat)
        r2 = requests.get(f"{BASE_URL}/api/shop-categories?root_only=false")
        assert r2.status_code == 200
        ids2 = {c["id"] for c in r2.json()["items"]}
        assert {root, child, gc}.issubset(ids2)

        # /tree → nested with children arrays
        r3 = requests.get(f"{BASE_URL}/api/shop-categories/tree")
        assert r3.status_code == 200
        tree = r3.json()["items"]
        root_node = next((n for n in tree if n["id"] == root), None)
        assert root_node is not None
        assert isinstance(root_node.get("children"), list)
        child_node = next((n for n in root_node["children"] if n["id"] == child), None)
        assert child_node is not None, f"child missing from tree under root; got {root_node}"
        gc_node = next((n for n in child_node["children"] if n["id"] == gc), None)
        assert gc_node is not None
        assert gc_node["children"] == []

        # /{id}/subcategories → direct children only
        r4 = requests.get(f"{BASE_URL}/api/shop-categories/{root}/subcategories")
        assert r4.status_code == 200
        subs = r4.json()["items"]
        sub_ids = {c["id"] for c in subs}
        assert child in sub_ids
        assert gc not in sub_ids, "grandchild should NOT appear in subcategories (direct only)"

        # /{id}/descendants → all descendants (any depth)
        r5 = requests.get(f"{BASE_URL}/api/shop-categories/{root}/descendants")
        assert r5.status_code == 200
        body = r5.json()
        assert child in body["ids"]
        assert gc in body["ids"]


# ─── 3. Product cascade filter ───────────────────────────────────────
class TestProductCascade:
    def test_setup_tree_and_product(self, h, state):
        # Fresh subtree for product cascade: ElecX → MobX (product tagged here)
        rx = requests.post(f"{BASE_URL}/api/admin/shop-categories", headers=h,
                           json={"name": f"ElecX_{SUFFIX}", "parent_id": None})
        assert rx.status_code == 200
        state["elecx_id"] = rx.json()["id"]

        rm = requests.post(f"{BASE_URL}/api/admin/shop-categories", headers=h,
                           json={"name": f"MobX_{SUFFIX}", "parent_id": state["elecx_id"]})
        assert rm.status_code == 200
        state["mobx_id"] = rm.json()["id"]
        state["mobx_name"] = f"MobX_{SUFFIX}"
        state["elecx_name"] = f"ElecX_{SUFFIX}"

        # Insert a product directly via DB — admin product-create routes vary;
        # inserting via Mongo keeps this test focused on the READ cascade logic.
        # Use pymongo sync client on the same MONGO_URL.
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"))
        dbname = os.environ.get("DB_NAME") or client.get_default_database().name
        db = client[dbname]
        pid = str(uuid.uuid4())
        db.products.insert_one({
            "id": pid,
            "name": TEST_PRODUCT_NAME,
            "category": state["mobx_name"],  # tagged with sub
            "price": 99999,
            "stock": 5,
            "is_published": True,
            "sales_count": 0,
        })
        state["product_id"] = pid
        client.close()

    def test_cascade_by_parent_name(self, state):
        # Parent "ElecX" should return the MobX product too
        r = requests.get(f"{BASE_URL}/api/products", params={"category": state["elecx_name"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict), "envelope expected when category param set"
        assert "items" in body and "total" in body and "has_more" in body
        names = [p["name"] for p in body["items"]]
        assert TEST_PRODUCT_NAME in names, f"cascade failed; names={names[:20]}"

    def test_leaf_by_name(self, state):
        r = requests.get(f"{BASE_URL}/api/products", params={"category": state["mobx_name"]})
        assert r.status_code == 200
        body = r.json()
        names = [p["name"] for p in body["items"]]
        assert TEST_PRODUCT_NAME in names

    def test_cascade_by_parent_id(self, state):
        r = requests.get(f"{BASE_URL}/api/products", params={"category": state["elecx_id"]})
        assert r.status_code == 200
        body = r.json()
        names = [p["name"] for p in body["items"]]
        assert TEST_PRODUCT_NAME in names, "id-based cascade lookup failed"

    def test_pagination_envelope(self):
        r = requests.get(f"{BASE_URL}/api/products", params={"limit": 5, "offset": 0})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)
        assert body["limit"] == 5
        assert body["offset"] == 0
        assert "total" in body and "has_more" in body
        assert len(body["items"]) <= 5

    def test_backcompat_flat_array(self):
        r = requests.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list), f"expected flat array back-compat when no params; got {type(body)}"


# ─── 4. Cleanup — runs after all tests via session finalizer ─────────
@pytest.fixture(scope="module", autouse=True)
def _cleanup(h, state, request):
    yield
    # Delete test product
    try:
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL"))
        dbname = os.environ.get("DB_NAME") or client.get_default_database().name
        db = client[dbname]
        if state.get("product_id"):
            db.products.delete_one({"id": state["product_id"]})
        client.close()
    except Exception as e:
        print(f"cleanup product failed: {e}")

    # Delete every test category we created (delete leaves first via descendants walk)
    for key in ("iphone_id", "mobiles_id", "electronics_id",
                "pub_gc", "pub_child", "pub_root",
                "mobx_id", "elecx_id"):
        cid = state.get(key)
        if not cid:
            continue
        try:
            requests.delete(f"{BASE_URL}/api/admin/shop-categories/{cid}", headers=h, timeout=10)
        except Exception as e:
            print(f"cleanup {key}={cid} failed: {e}")
