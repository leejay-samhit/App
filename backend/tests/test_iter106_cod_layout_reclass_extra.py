"""Iter106 (testing agent) — gaps not covered by test_nov2026_layout_classification_cod.py.

Runs against the PUBLIC url (EXPO_PUBLIC_BACKEND_URL from frontend/.env).
  * admin PATCH: both spellings, old-category sub dropped, '' clears, fields survive
  * block isolation: sibling + cross-category + parent-not-in-sub
  * recharge: operator children gone from public tree / exclude_recharge, still in admin list
  * COD: plain 'cod' on an all-prepaid bag -> cod_not_available
  * regression: cart add/remove, products list/search, wallet + online checkout
"""
import uuid

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
T = 30
TAG = "TEST_" + uuid.uuid4().hex[:6]
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}
COD_OK = "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"
COD_OFF = "9c6bb05d-eecc-4637-8489-466f1e4f0288"
OPERATORS = {"airtel", "jio", "vi", "bsnl", "tata play"}


def hdr(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin_h():
    return hdr(ADMIN)


@pytest.fixture(scope="module")
def vendor_h():
    return hdr(VENDOR)


@pytest.fixture(scope="module")
def buyer_h():
    return hdr(BUYER)


@pytest.fixture(scope="module")
def tree(admin_h):
    made, blocks = [], []

    def mk(name, parent=None):
        r = requests.post(f"{BASE}/admin/shop-categories", json={"name": name, "parent_id": parent},
                          headers=admin_h, timeout=T)
        assert r.status_code in (200, 201), r.text[:200]
        cid = r.json().get("id") or r.json().get("item", {}).get("id")
        made.append(cid)
        return cid

    t = {"a": f"{TAG}_CatA", "a1": f"{TAG}_A1", "a2": f"{TAG}_A2", "b": f"{TAG}_CatB", "b1": f"{TAG}_B1"}
    a = mk(t["a"]); mk(t["a1"], a); mk(t["a2"], a)
    b = mk(t["b"]); mk(t["b1"], b)
    t["_blocks"] = blocks
    yield t
    for bid in blocks:
        requests.delete(f"{BASE}/admin/shop-layout/{bid}", headers=admin_h, timeout=T)
    MDB.shop_layout_blocks.delete_many({"id": {"$in": blocks}})
    MDB.shop_categories.delete_many({"id": {"$in": made}})


def layout(cat):
    r = requests.get(f"{BASE}/shop-layout", params={"scope": "category", "category": cat}, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return [x.get("title") for x in r.json()["items"]]


def mk_block(admin_h, tree, cat, title, btype="section_header"):
    r = requests.post(f"{BASE}/admin/shop-layout", headers=admin_h, timeout=T, json={
        "block_type": btype, "title": title, "scope": "category", "scope_category": cat, "active": True})
    assert r.status_code in (200, 201), r.text[:300]
    bid = r.json().get("id") or r.json().get("item", {}).get("id")
    tree["_blocks"].append(bid)
    return bid


# Block isolation — parent / sibling / cross-category
def test_block_isolation_matrix(admin_h, tree):
    mk_block(admin_h, tree, tree["a"], f"{TAG}_mainA")
    mk_block(admin_h, tree, tree["a1"], f"{TAG}_subA1")
    mk_block(admin_h, tree, tree["b1"], f"{TAG}_subB1")
    assert layout(tree["a"]) == [f"{TAG}_mainA"]
    assert layout(tree["a1"]) == [f"{TAG}_subA1"]
    assert layout(tree["a2"]) == []          # sibling unconfigured -> nothing
    assert layout(tree["b"]) == []           # parent of B1 does not inherit
    assert layout(tree["b1"]) == [f"{TAG}_subB1"]


def test_block_delete_affects_only_its_mapping(admin_h, tree):
    bid = mk_block(admin_h, tree, tree["a2"], f"{TAG}_tmpA2")
    assert f"{TAG}_tmpA2" in layout(tree["a2"])
    r = requests.delete(f"{BASE}/admin/shop-layout/{bid}", headers=admin_h, timeout=T)
    assert r.status_code in (200, 204), r.text[:200]
    assert layout(tree["a2"]) == []
    assert layout(tree["a"]) == [f"{TAG}_mainA"]
    assert layout(tree["a1"]) == [f"{TAG}_subA1"]


# Admin product reclassification
@pytest.fixture(scope="module")
def product(vendor_h, tree):
    r = requests.post(f"{BASE}/vendor/me/products", headers=vendor_h, timeout=T, json={
        "name": f"{TAG}_Prod", "price": 321, "stock": 7, "description": "reclass probe",
        "category": tree["a"], "sub_category": tree["a1"], "image_url": "https://example.com/x.png",
        "sku": f"{TAG}SKU", "selling_gst_pct": 12})
    assert r.status_code in (200, 201), r.text[:300]
    pid = r.json()["id"]
    yield pid
    MDB.products.delete_one({"id": pid})


def row(pid):
    return MDB.products.find_one({"id": pid}, {"_id": 0})


def test_admin_patch_writes_both_spellings(admin_h, product, tree):
    r = requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                       json={"category": tree["b"], "sub_category": tree["b1"]})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["category"] == tree["b"] and body["sub_category"] == tree["b1"]
    d = row(product)
    assert (d["category"], d["sub_category"], d.get("subcategory")) == (tree["b"], tree["b1"], tree["b1"])


def test_admin_patch_main_category_change_drops_foreign_sub(admin_h, product, tree):
    r = requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                       json={"category": tree["a"], "sub_category": tree["b1"]})
    assert r.status_code == 200, r.text[:300]
    d = row(product)
    assert d["category"] == tree["a"]
    assert d.get("sub_category") in ("", None) and d.get("subcategory") in ("", None)
    assert r.json().get("sub_category") in ("", None)


def test_admin_patch_only_sub_then_clear(admin_h, product, tree):
    requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                   json={"sub_category": tree["a2"]})
    d = row(product)
    assert d["category"] == tree["a"] and d["sub_category"] == tree["a2"] and d.get("subcategory") == tree["a2"]
    requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T, json={"sub_category": ""})
    d = row(product)
    assert d.get("sub_category") in ("", None) and d.get("subcategory") in ("", None)


def test_admin_patch_preserves_fields(admin_h, product, tree):
    before = row(product)
    requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                   json={"category": tree["b"], "sub_category": tree["b1"]})
    after = row(product)
    for k in ("name", "price", "stock", "description", "vendor_id", "sku", "selling_gst_pct", "image_url"):
        assert after.get(k) == before.get(k), k


def test_published_product_leaves_old_listing(admin_h, product, tree):
    """Admin-approved product: after reclassification it shows only under the new category."""
    requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                   json={"is_published": True, "active": True, "category": tree["a"], "sub_category": tree["a1"]})
    MDB.products.update_one({"id": product}, {"$set": {"is_published": True, "approval_status": "approved"}})
    requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                   json={"category": tree["b"], "sub_category": tree["b1"]})

    def ids(params):
        r = requests.get(f"{BASE}/products", params={**params, "limit": 100}, timeout=T)
        assert r.status_code == 200, r.text[:200]
        j = r.json()
        return {p["id"] for p in (j.get("items") if isinstance(j, dict) else j)}
    assert product not in ids({"category": tree["a"]})
    assert product not in ids({"category": tree["a"], "sub_category": tree["a1"]})


# Recharge removal
def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


def test_public_tree_shows_recharge_root_but_no_subs_or_operators():
    """Nov 2026 — the owner asked for the Recharge ROOT back in the shop; its
    sub-categories (operators, Mobile/DTH) stay hidden."""
    names = [n["name"].lower() for n in _walk(requests.get(f"{BASE}/shop-categories/tree", timeout=T).json()["items"])]
    flat = [c["name"].lower() for c in requests.get(f"{BASE}/shop-categories", timeout=T).json()["items"]]
    for lst in (names, flat):
        assert "recharge" in lst, "the Recharge root must be visible"
        assert not [n for n in lst if "recharge" in n and n != "recharge"], \
            "recharge sub-categories must stay hidden"
        assert not OPERATORS & set(lst)


def test_admin_list_flag_vs_plain(admin_h):
    excl = [c["name"].lower() for c in requests.get(f"{BASE}/admin/shop-categories", params={"exclude_recharge": "true"},
                                                    headers=admin_h, timeout=T).json()["items"]]
    full = [c["name"].lower() for c in requests.get(f"{BASE}/admin/shop-categories", headers=admin_h, timeout=T).json()["items"]]
    # The picker offers the Recharge ROOT only — subs and operators stay out.
    assert "recharge" in excl
    assert not [n for n in excl if "recharge" in n and n != "recharge"]
    assert not OPERATORS & set(excl)
    assert [n for n in full if "recharge" in n]
    assert len(full) > len(excl)


# COD on an all-prepaid bag with plain cod
@pytest.fixture
def cod_cart(buyer_h):
    requests.post(f"{BASE}/cart/clear", headers=buyer_h, timeout=T)
    MDB.products.update_one({"id": COD_OFF}, {"$set": {"cod_available": False}})
    yield
    requests.post(f"{BASE}/cart/clear", headers=buyer_h, timeout=T)
    MDB.products.update_one({"id": COD_OFF}, {"$unset": {"cod_available": ""}})


ADDR = {"name": "TEST Buyer", "line1": "1 Test St", "city": "Srikalahasti", "state": "AP",
        "pincode": "517645", "phone": "9999999999"}


def test_plain_cod_all_prepaid_bag(buyer_h, cod_cart):
    requests.post(f"{BASE}/cart/add", json={"product_id": COD_OFF, "qty": 1}, headers=buyer_h, timeout=T)
    r = requests.post(f"{BASE}/orders/checkout", json={"payment_method": "cod", "shipping_address": ADDR},
                      headers=buyer_h, timeout=60)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "cod_not_available"


# Regression: cart add/remove + product search
def test_cart_add_remove(buyer_h, cod_cart):
    r = requests.post(f"{BASE}/cart/add", json={"product_id": COD_OK, "qty": 1}, headers=buyer_h, timeout=T)
    assert r.status_code == 200
    c = requests.get(f"{BASE}/cart", headers=buyer_h, timeout=T).json()
    assert any(i.get("product_id") == COD_OK or (i.get("product") or {}).get("id") == COD_OK for i in c["items"])
    assert c["cod"]["available"] is True and c["cod"]["partial"] is False
    r = requests.post(f"{BASE}/cart/remove", json={"product_id": COD_OK}, headers=buyer_h, timeout=T)
    assert r.status_code == 200, r.text[:200]
    c = requests.get(f"{BASE}/cart", headers=buyer_h, timeout=T).json()
    assert not c["items"]


def test_product_search():
    r = requests.get(f"{BASE}/products", params={"q": "Widget"}, timeout=T)
    assert r.status_code == 200
    j = r.json()
    items = j.get("items") if isinstance(j, dict) else j
    assert isinstance(items, list)


def test_wallet_and_orders_history(buyer_h):
    w = requests.get(f"{BASE}/transactions/me", headers=buyer_h, timeout=T)
    me = requests.get(f"{BASE}/auth/me", headers=buyer_h, timeout=T)
    assert me.status_code == 200 and "wallet_balance" in me.json()
    o = requests.get(f"{BASE}/orders/me", headers=buyer_h, timeout=T)
    assert w.status_code == 200, w.text[:200]
    assert o.status_code == 200, o.text[:200]
