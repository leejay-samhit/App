# Iteration 117 — retest of iter115/116 open items: legacy subcategory counts incl. '' sub_category (E),
# text-index search semantics (F), admin pager + ids interest lookup (B), dead-product ids (D).
import os
import re
import uuid
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
PUB = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_h(s):
    r = s.post(f"{BASE}/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]}, timeout=20)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return {"Authorization": f"Bearer {r.json()['token']}"}


# --- E: legacy-only rows (missing sub_category AND empty-string sub_category) ---
@pytest.fixture(scope="module")
def legacy_rows():
    tag = uuid.uuid4().hex[:6]
    sub = f"test_legacy_{tag}"
    ids = [f"TEST_{tag}_a", f"TEST_{tag}_b"]
    DB.products.insert_many([
        {"id": ids[0], "name": f"TEST_ legacy A {tag}", "category": "Electronics", "subcategory": sub,
         "is_published": True, "price": 1},
        {"id": ids[1], "name": f"TEST_ legacy B {tag}", "category": "Electronics", "sub_category": "",
         "subcategory": sub, "is_published": True, "price": 1},
    ])
    yield sub
    DB.products.delete_many({"id": {"$in": ids}})


class TestLegacyCounts:
    def test_missing_sub_category_counted(self, s, legacy_rows):
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Electronics"}, timeout=20).json()
        assert c["counts"].get(legacy_rows, 0) >= 1, c["counts"]

    def test_empty_sub_category_counted(self, s, legacy_rows):
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Electronics"}, timeout=20).json()
        assert c["counts"].get(legacy_rows, 0) == 2, c["counts"].get(legacy_rows)

    def test_badge_matches_sub_filter_list(self, s, legacy_rows):
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Electronics"}, timeout=20).json()
        lst = s.get(f"{BASE}/api/products", params={"category": "Electronics", "subcategory": legacy_rows, "limit": 5}, timeout=20).json()
        assert lst["total"] == c["counts"].get(legacy_rows, 0), (lst["total"], c["counts"].get(legacy_rows))


# --- F: requested search checks ---
def _q(s, q):
    return s.get(f"{BASE}/api/products", params={"q": q, "limit": 60}, timeout=30).json()


def _regex_count(q):
    n = re.escape(q)
    return DB.products.count_documents({"$and": [PUB, {"$or": [{f: {"$regex": n, "$options": "i"}} for f in
                                        ("name", "description", "brand", "category", "sub_category", "subcategory", "tags")]}]})


class TestSearch:
    def test_widget(self, s):
        assert _q(s, "Widget")["total"] == 2

    def test_exact_multiword(self, s):
        d = _q(s, "PERFTEST Product 00500")
        assert d["total"] == 1 and d["items"][0]["name"] == "PERFTEST Product 00500"

    def test_mobile(self, s):
        d = _q(s, "mobile")
        assert d["total"] > 0 and all(i.get("category") == "Mobiles" for i in d["items"])

    def test_partial(self, s):
        assert _q(s, "Produ")["total"] >= 6000

    def test_nonsense(self, s):
        assert _q(s, "zzqxv_nonsense_9")["total"] == 0

    @pytest.mark.parametrize("word", ["beauty", "test", "Shoes"])
    def test_same_as_regex(self, s, word):
        assert _q(s, word)["total"] == _regex_count(word), word


# --- B/regression: admin 250-per-page pager + ids lookup through ingress ---
class TestAdminPager:
    def test_pages_disjoint(self, s, admin_h):
        p0 = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 250, "offset": 0}, timeout=30).json()
        p2 = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 250, "offset": 500}, timeout=30).json()
        assert len(p0["items"]) == 250 and len(p2["items"]) == 250 and p0["total"] >= 6000
        assert not ({i["id"] for i in p0["items"]} & {i["id"] for i in p2["items"]})

    def test_search_resets(self, s, admin_h):
        d = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 250, "offset": 0, "q": "PERFTEST Product 0050"}, timeout=30).json()
        assert d["total"] == 10, d["total"]

    def test_ids_250_through_ingress(self, s, admin_h):
        page = s.get(f"{BASE}/api/admin/products", headers=admin_h, params={"limit": 250, "offset": 750}, timeout=30).json()["items"]
        ids = [p["id"] for p in page]
        r = s.get(f"{BASE}/api/products", params={"ids": ",".join(ids)}, timeout=30)
        assert r.status_code == 200
        pub = {p["id"] for p in page if p.get("is_published", True)}
        assert {i["id"] for i in r.json()["items"]} == pub

    def test_ids_unknown_dropped(self, s):
        real = s.get(f"{BASE}/api/products", params={"limit": 1}, timeout=20).json()["items"][0]["id"]
        d = s.get(f"{BASE}/api/products", params={"ids": f"TEST_gone_1,{real},TEST_gone_2"}, timeout=20).json()
        assert [i["id"] for i in d["items"]] == [real]
