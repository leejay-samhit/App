"""Nov-2026 — Shop layout isolation, product reclassification, COD rules.

Covers the owner's mandatory scenarios that are verifiable server-side:
  A/B/G  block isolation between a category and its sub-categories
  C/D/E/F product category + sub-category editing (vendor and admin)
  I      Recharge removal and regression of unrelated data
  plus   the Cash-on-Delivery availability / partial-prepay rules
"""
import os
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ.get("PROBE_BASE", "http://localhost:8001/api")
T = 30

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


MDB = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
TAG = uuid.uuid4().hex[:6]


def tok(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {tok(ADMIN)}"}


@pytest.fixture(scope="module")
def vendor_h():
    return {"Authorization": f"Bearer {tok(VENDOR)}"}


@pytest.fixture(scope="module")
def buyer_h():
    return {"Authorization": f"Bearer {tok(BUYER)}"}


@pytest.fixture(scope="module")
def tree(admin_h):
    """A throwaway Cat-A (A1, A2) + Cat-B (B1) tree, removed afterwards."""
    made = []

    def mk(name, parent=None):
        r = requests.post(f"{BASE}/admin/shop-categories",
                          json={"name": name, "parent_id": parent},
                          headers=admin_h, timeout=T)
        assert r.status_code in (200, 201), r.text[:200]
        cid = r.json().get("id") or r.json().get("item", {}).get("id")
        made.append(cid)
        return cid, name

    a_id, a = mk(f"ZCatA_{TAG}")
    a1_id, a1 = mk(f"ZSubA1_{TAG}", a_id)
    a2_id, a2 = mk(f"ZSubA2_{TAG}", a_id)
    b_id, b = mk(f"ZCatB_{TAG}")
    b1_id, b1 = mk(f"ZSubB1_{TAG}", b_id)
    yield {"a": a, "a1": a1, "a2": a2, "b": b, "b1": b1,
           "a_id": a_id, "a1_id": a1_id, "b_id": b_id, "b1_id": b1_id}
    MDB.shop_categories.delete_many({"id": {"$in": made}})
    MDB.shop_layout_blocks.delete_many({"scope_category": {"$in": [a, a1, a2, b, b1]}})
    MDB.products.delete_many({"name": {"$regex": f"^ZProd_{TAG}"}})


def mk_block(admin_h, category, title):
    r = requests.post(f"{BASE}/admin/shop-layout", headers=admin_h, timeout=T, json={
        "block_type": "section_header", "title": title,
        "scope": "category", "scope_category": category, "active": True,
    })
    assert r.status_code in (200, 201), r.text[:300]
    return r.json().get("id") or r.json().get("item", {}).get("id")


def layout(category):
    r = requests.get(f"{BASE}/shop-layout", params={"scope": "category", "category": category}, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return [b.get("title") for b in r.json()["items"]]


# ───────────────────── Test A / B / G — block isolation ─────────────────────

def test_A_main_category_block_stays_in_the_main_category(admin_h, tree):
    title = f"A-only {TAG}"
    mk_block(admin_h, tree["a"], title)
    assert title in layout(tree["a"]), "the block must show in its own category"
    assert title not in layout(tree["a1"]), "a main-category block must NOT leak into a sub-category"
    assert title not in layout(tree["a2"])
    assert title not in layout(tree["b"])


def test_B_subcategory_block_stays_in_that_subcategory(admin_h, tree):
    title = f"A1-only {TAG}"
    mk_block(admin_h, tree["a1"], title)
    assert title in layout(tree["a1"])
    assert title not in layout(tree["a"]), "a sub-category block must NOT appear in the parent"
    assert title not in layout(tree["a2"]), "...nor in a sibling sub-category"
    assert title not in layout(tree["b1"])


def test_G_a_subcategory_without_blocks_inherits_nothing(admin_h, tree):
    mk_block(admin_h, tree["a"], f"A-parent {TAG}")
    assert layout(tree["a2"]) == [], "an unconfigured sub-category must show NO blocks"


def test_editing_a_block_moves_only_that_block(admin_h, tree):
    title = f"movable {TAG}"
    bid = mk_block(admin_h, tree["a1"], title)
    r = requests.patch(f"{BASE}/admin/shop-layout/{bid}",
                       json={"scope_category": tree["a2"]}, headers=admin_h, timeout=T)
    assert r.status_code == 200, r.text[:200]
    assert title in layout(tree["a2"])
    assert title not in layout(tree["a1"])


# ───────────── Test C / D / E / F — product reclassification ─────────────

@pytest.fixture
def product(vendor_h, tree):
    r = requests.post(f"{BASE}/vendor/me/products", headers=vendor_h, timeout=T, json={
        "name": f"ZProd_{TAG}_{uuid.uuid4().hex[:4]}", "price": 499, "stock": 5,
        "description": "classification probe", "category": tree["a"], "sub_category": tree["a1"],
        "image_url": "", "sku": f"ZSKU{TAG}", "selling_gst_pct": 5,
    })
    assert r.status_code in (200, 201), r.text[:300]
    pid = r.json()["id"]
    yield pid
    MDB.products.delete_one({"id": pid})


def stored(pid):
    return MDB.products.find_one({"id": pid}, {"_id": 0, "category": 1, "sub_category": 1, "subcategory": 1})


def test_C_vendor_moves_a_product_to_another_category(vendor_h, product, tree):
    r = requests.patch(f"{BASE}/vendor/me/products/{product}", headers=vendor_h, timeout=T,
                       json={"category": tree["b"], "sub_category": tree["b1"]})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    # 6 — the API returns what was saved
    assert body["category"] == tree["b"]
    assert body["sub_category"] == tree["b1"]
    # 5 — and the database really holds it
    db_row = stored(product)
    assert db_row["category"] == tree["b"]
    assert db_row["sub_category"] == tree["b1"]
    assert db_row.get("subcategory") == tree["b1"], "both spellings must agree"
    # 7/11 — reopening the product in vendor product management (where the
    # editor loads from) shows the new classification. The PUBLIC product page
    # is not checked here: a vendor edit sends the item back to the admin
    # review queue, so it is intentionally hidden from the shop until approved.
    mine = requests.get(f"{BASE}/vendor/me/products", headers=vendor_h, timeout=T).json()
    rows = mine.get("items") if isinstance(mine, dict) else mine
    row = next(p for p in rows if p["id"] == product)
    assert row["category"] == tree["b"]
    assert row["sub_category"] == tree["b1"]


def test_D_admin_moves_a_product_to_another_category(admin_h, product, tree):
    r = requests.patch(f"{BASE}/admin/products/{product}", headers=admin_h, timeout=T,
                       json={"category": tree["b"], "sub_category": tree["b1"]})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["sub_category"] == tree["b1"]
    assert stored(product)["category"] == tree["b"]


def test_E_changing_only_the_subcategory_moves_the_product(vendor_h, product, tree):
    r = requests.patch(f"{BASE}/vendor/me/products/{product}", headers=vendor_h, timeout=T,
                       json={"sub_category": tree["a2"]})
    assert r.status_code == 200, r.text[:300]
    row = stored(product)
    assert row["sub_category"] == tree["a2"], "must move to the new sub-category"
    assert row.get("subcategory") == tree["a2"]
    assert row["category"] == tree["a"], "the main category must be untouched"


def test_F_a_subcategory_from_the_old_category_is_not_kept(vendor_h, product, tree):
    """THE reported bug: change the main category, leave the old sub-category
    behind, and the product used to stay listed under it forever."""
    r = requests.patch(f"{BASE}/vendor/me/products/{product}", headers=vendor_h, timeout=T,
                       json={"category": tree["b"], "sub_category": tree["a1"]})
    assert r.status_code == 200, r.text[:300]
    row = stored(product)
    assert row["category"] == tree["b"]
    assert row["sub_category"] in ("", None), \
        f"A1 does not belong to Cat-B, so it must be dropped (got {row['sub_category']!r})"
    assert row.get("subcategory") in ("", None)


def test_clearing_the_subcategory_actually_clears_it(vendor_h, product):
    r = requests.patch(f"{BASE}/vendor/me/products/{product}", headers=vendor_h, timeout=T,
                       json={"sub_category": ""})
    assert r.status_code == 200, r.text[:300]
    row = stored(product)
    assert row["sub_category"] in ("", None)
    assert row.get("subcategory") in ("", None)


def test_reclassification_preserves_everything_else(vendor_h, product, tree):
    before = MDB.products.find_one({"id": product}, {"_id": 0})
    requests.patch(f"{BASE}/vendor/me/products/{product}", headers=vendor_h, timeout=T,
                   json={"category": tree["b"], "sub_category": tree["b1"]})
    after = MDB.products.find_one({"id": product}, {"_id": 0})
    for key in ("id", "name", "price", "stock", "description", "vendor_id",
                "sku", "selling_gst_pct", "image_url"):
        assert after.get(key) == before.get(key), f"{key} must survive a reclassification"


# ───────────────────── Test I — Recharge removal ─────────────────────

def test_recharge_root_shown_subs_hidden_in_customer_category_lists():
    """Owner's rule (Nov 2026): the Recharge ROOT appears as a top category
    (tapping it opens the recharge flow); its sub-categories stay hidden."""
    flat = requests.get(f"{BASE}/shop-categories", timeout=T).json()["items"]
    names = [(c["name"] or "").lower() for c in flat]
    assert "recharge" in names, "the Recharge root must be visible to shoppers"
    assert not [n for n in names if "recharge" in n and n != "recharge"], \
        "only the bare 'Recharge' root is allowed, not its sub-categories"

    def walk(nodes):
        for n in nodes:
            yield n
            yield from walk(n.get("children") or [])

    tree_items = requests.get(f"{BASE}/shop-categories/tree", timeout=T).json()["items"]
    tnames = [n["name"].lower() for n in walk(tree_items)]
    assert "recharge" in tnames
    assert not [n for n in tnames if "recharge" in n and n != "recharge"]
    assert "airtel" not in tnames and "jio" not in tnames, "operator sub-categories must stay hidden"


def test_shop_layout_picker_offers_recharge_root_but_not_subs(admin_h):
    items = requests.get(f"{BASE}/admin/shop-categories?exclude_recharge=true",
                         headers=admin_h, timeout=T).json()["items"]
    names = [(c["name"] or "").lower() for c in items]
    assert "recharge" in names, "the Recharge root must be placeable in Shop Layout"
    assert not [n for n in names if "recharge" in n and n != "recharge"], \
        "recharge sub-categories must not be offered"
    assert not [n for n in names if n in ("airtel", "jio", "vi", "bsnl")]


def test_recharge_categories_and_services_still_exist_in_the_database(admin_h):
    """Removal is a VISIBILITY change — nothing is deleted."""
    assert MDB.shop_categories.count_documents({"name": {"$regex": "recharge", "$options": "i"}}) > 0
    full = requests.get(f"{BASE}/admin/shop-categories", headers=admin_h, timeout=T).json()["items"]
    assert [c for c in full if "recharge" in (c["name"] or "").lower()], \
        "category management must still see recharge"


def test_other_categories_are_untouched():
    names = [c["name"] for c in requests.get(f"{BASE}/shop-categories", timeout=T).json()["items"]]
    for expected in ("Men", "Women", "Electronics", "Clothes"):
        assert expected in names


# ───────────────────── Cash on Delivery rules ─────────────────────

def cart_cod(buyer_h):
    r = requests.get(f"{BASE}/cart", params={"pincode": "517645"}, headers=buyer_h, timeout=T)
    assert r.status_code == 200, r.text[:200]
    return r.json().get("cod")


def place(buyer_h, method, wallet_amount=None):
    body = {
        "payment_method": method,
        "shipping_address": {"name": "Test Buyer", "line1": "1 Test St", "city": "Srikalahasti",
                             "state": "AP", "pincode": "517645", "phone": "9999999999"},
    }
    if wallet_amount is not None:
        body["wallet_amount"] = wallet_amount
    return requests.post(f"{BASE}/orders/checkout", json=body, headers=buyer_h, timeout=60)


COD_OK = "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"      # Test Widget, ₹100
COD_OFF = "9c6bb05d-eecc-4637-8489-466f1e4f0288"     # Vendor One Widget, ₹100


@pytest.fixture
def clean_cart(buyer_h):
    requests.post(f"{BASE}/cart/clear", headers=buyer_h, timeout=T)
    MDB.products.update_one({"id": COD_OFF}, {"$set": {"cod_available": False}})
    yield
    requests.post(f"{BASE}/cart/clear", headers=buyer_h, timeout=T)
    MDB.products.update_one({"id": COD_OFF}, {"$unset": {"cod_available": ""}})


def add(buyer_h, pid, qty=1):
    r = requests.post(f"{BASE}/cart/add", json={"product_id": pid, "qty": qty},
                      headers=buyer_h, timeout=T)
    assert r.status_code == 200, r.text[:200]


def test_cod_hidden_when_no_item_in_the_bag_accepts_cash(buyer_h, clean_cart):
    add(buyer_h, COD_OFF)
    cod = cart_cod(buyer_h)
    assert cod["available"] is False, "the app must not offer COD at all"
    assert cod["partial"] is False
    assert cod["blocked_count"] == 1
    assert cod["blocked_items"][0]["vendor_name"], "name the seller in the explainer"

    r = place(buyer_h, "wallet_cod", wallet_amount=500)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "cod_not_available"


def test_cod_offered_when_every_item_accepts_cash(buyer_h, clean_cart):
    add(buyer_h, COD_OK)
    cod = cart_cod(buyer_h)
    assert cod["available"] is True
    assert cod["partial"] is False
    assert cod["prepay_due"] == 0


def test_mixed_bag_reports_the_exact_prepaid_amount(buyer_h, clean_cart):
    add(buyer_h, COD_OK)
    add(buyer_h, COD_OFF, qty=2)
    cod = cart_cod(buyer_h)
    assert cod["available"] is True
    assert cod["partial"] is True, "the app must show the prepaid-part popup"
    assert cod["prepay_due"] == 200.0, "2 × ₹100 of prepaid-only goods"
    assert cod["cod_item_count"] == 1
    assert cod["blocked_items"][0]["qty"] == 2


def test_mixed_bag_refuses_plain_cod_and_names_the_amount(buyer_h, clean_cart):
    add(buyer_h, COD_OK)
    add(buyer_h, COD_OFF, qty=2)
    r = place(buyer_h, "cod")
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "cod_partial_prepay_required"
    assert d["prepay_due"] == 200.0
    assert "200" in d["message"]


def test_mixed_bag_refuses_a_short_prepayment(buyer_h, clean_cart):
    add(buyer_h, COD_OK)
    add(buyer_h, COD_OFF, qty=2)
    r = place(buyer_h, "wallet_cod", wallet_amount=100)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "cod_partial_prepay_required"


def test_mixed_bag_goes_through_once_the_prepaid_part_is_covered(buyer_h, clean_cart):
    add(buyer_h, COD_OK)
    add(buyer_h, COD_OFF, qty=2)
    r = place(buyer_h, "wallet_cod", wallet_amount=200)
    assert r.status_code == 200, r.text[:300]
    orders = r.json()["orders"]
    assert orders, "the whole order must be placed in one go"
    for o in orders:
        MDB.orders.delete_one({"id": o["id"]})
