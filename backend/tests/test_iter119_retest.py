# Iteration 119 — retest: denormalised interested_count (POST /interested -> list / ids / detail),
# backfill consistency, no interested_users leak, subcategory-counts with NUMERIC sub_category.
import os
import uuid
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
ADMIN = ("support@slangcart.com", "3)Ywxtic")
BUYER = ("testbuyer@test.com", "Test@1234")


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _login(s, cred):
    r = s.post(f"{BASE}/api/auth/login", json={"email": cred[0], "password": cred[1]}, timeout=20)
    if r.status_code != 200:
        pytest.skip(f"login failed {cred[0]}: {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def admin_h(s):
    return _login(s, ADMIN)


@pytest.fixture(scope="module")
def buyer_h(s):
    return _login(s, BUYER)


# --- Interested flow: real POST by 2 users, then every read path must say 2 ---
@pytest.fixture(scope="module")
def interest_product(s, admin_h, buyer_h):
    tag = uuid.uuid4().hex[:6]
    pid = f"TEST_ic_{tag}"
    name = f"TEST_ interest badge {tag}"
    v = DB.users.find_one({"email": "testvendor@test.com"}, {"id": 1})
    DB.products.insert_one({"id": pid, "name": name, "category": "Beauty", "is_published": True,
                            "price": 1, "stock": 0, "vendor_id": (v or {}).get("id")})
    r1 = s.post(f"{BASE}/api/products/{pid}/interested", headers=buyer_h, timeout=20)
    r2 = s.post(f"{BASE}/api/products/{pid}/interested", headers=admin_h, timeout=20)
    r3 = s.post(f"{BASE}/api/products/{pid}/interested", headers=buyer_h, timeout=20)  # idempotent
    yield {"pid": pid, "name": name, "posts": [r1, r2, r3]}
    DB.products.delete_one({"id": pid})
    DB.notifications.delete_many({"product_id": pid, "kind": "stock_interest"})


class TestInterestedCount:
    def test_post_counts(self, interest_product):
        r1, r2, r3 = interest_product["posts"]
        assert r1.status_code == 200 and r1.json()["interested_count"] == 1, r1.text
        assert r2.json()["interested_count"] == 2, r2.text
        assert r3.json()["interested_count"] == 2 and r3.json()["already_registered"] is True

    def test_doc_counter_stored(self, interest_product):
        d = DB.products.find_one({"id": interest_product["pid"]})
        assert d["interested_count"] == 2 and len(d["interested_users"]) == 2

    def test_ids_lookup(self, s, interest_product):
        it = s.get(f"{BASE}/api/products", params={"ids": interest_product["pid"]}, timeout=20).json()["items"]
        assert it and it[0]["interested_count"] == 2, it
        assert "interested_users" not in it[0]

    def test_plain_list_search(self, s, interest_product):
        it = s.get(f"{BASE}/api/products", params={"q": interest_product["name"], "limit": 5}, timeout=20).json()["items"]
        hit = [p for p in it if p["id"] == interest_product["pid"]]
        assert hit and hit[0]["interested_count"] == 2, it
        assert all("interested_users" not in p for p in it)

    def test_detail(self, s, interest_product):
        p = s.get(f"{BASE}/api/products/{interest_product['pid']}", timeout=20).json()
        assert p["interested_count"] == 2 and "interested_users" not in p

    def test_admin_list_carries_count(self, s, admin_h, interest_product):
        r = s.get(f"{BASE}/api/admin/products", params={"ids": interest_product["pid"]}, headers=admin_h, timeout=20)
        assert r.status_code == 200, r.text[:200]
        it = r.json()["items"]
        assert it and it[0].get("interested_count") == 2, it
        assert "interested_users" not in it[0]

    def test_owner_interested_endpoint(self, s, admin_h, interest_product):
        r = s.get(f"{BASE}/api/products/{interest_product['pid']}/interested", headers=admin_h, timeout=20).json()
        assert r["interested_count"] == 2 and len(r["users"]) == 2


def test_backfill_consistent_across_db():
    """Every product with a non-empty interested_users must carry a matching interested_count."""
    bad = list(DB.products.aggregate([
        {"$match": {"interested_users": {"$exists": True, "$ne": []}}},
        {"$project": {"_id": 0, "id": 1, "ic": "$interested_count",
                      "n": {"$size": {"$ifNull": ["$interested_users", []]}}}},
        {"$match": {"$expr": {"$ne": ["$ic", "$n"]}}},
    ]))
    assert not [b for b in bad if not str(b["id"]).startswith("TEST_")], bad[:5]


def test_no_leak_plain_list_pages(s):
    for off in (0, 250, 5000):
        body = s.get(f"{BASE}/api/products", params={"limit": 60, "offset": off}, timeout=30).json()
        it = body if isinstance(body, list) else body["items"]
        assert it and all("interested_users" not in p for p in it)
        assert all(isinstance(p.get("interested_count"), int) for p in it)


def test_no_leak_by_source(s):
    for src in ("trending", "new", "best"):
        r = s.get(f"{BASE}/api/products/by-source", params={"source": src, "limit": 10}, timeout=20)
        assert r.status_code == 200, (src, r.text[:200])
        body = r.json()
        items = body if isinstance(body, list) else body.get("items", [])
        assert all("interested_users" not in p for p in items), src


# --- subcategory-counts with a NUMBER sub_category inside a real category (Men) ---
def test_subcat_numeric_in_real_category(s):
    before = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Men"}, timeout=30)
    assert before.status_code == 200
    pid = "TEST_num_" + uuid.uuid4().hex[:6]
    DB.products.insert_one({"id": pid, "name": "TEST_ numeric sub", "category": "Men", "sub_category": 987654,
                            "is_published": True, "price": 1})
    try:
        after = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Men"}, timeout=30)
        assert after.status_code == 200, after.text[:200]
        b, a = before.json(), after.json()
        assert a["total"] == b["total"] + 1
        assert a["counts"].get("987654") == 1, a["counts"]
        for k, v in b["counts"].items():
            assert a["counts"].get(k) == v, (k, v, a["counts"].get(k))
        # numeric float/bool/obj variants must not 500 either
        DB.products.update_one({"id": pid}, {"$set": {"sub_category": 12.5}})
        assert s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Men"}, timeout=30).status_code == 200
        DB.products.update_one({"id": pid}, {"$set": {"sub_category": ["x"]}})
        r = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Men"}, timeout=30)
        assert r.status_code == 200, f"array sub_category -> {r.status_code}"
    finally:
        DB.products.delete_one({"id": pid})


def test_subcat_numeric_server_filter(s):
    pid = "TEST_numf_" + uuid.uuid4().hex[:6]
    DB.products.insert_one({"id": pid, "name": "TEST_ numeric filter", "category": "Men", "sub_category": 424242,
                            "is_published": True, "price": 1})
    try:
        r = s.get(f"{BASE}/api/products", params={"category": "Men", "subcategory": "424242", "limit": 5}, timeout=20)
        assert r.status_code == 200, r.text[:200]
        print("numeric sub filter total:", r.json().get("total"))
    finally:
        DB.products.delete_one({"id": pid})
