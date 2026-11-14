# Iteration 118 — retest: search regex-vs-text-index threshold (F), exact search counts,
# subcategory-counts '' fallback (E), ids lookup (vendor interest badges), text index v2 presence.
import os
import re
import uuid
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
PUB = {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]}
FIELDS = ["name", "description", "brand", "category", "sub_category", "subcategory", "tags"]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _regex_count(word):
    rx = {"$regex": re.escape(word), "$options": "i"}
    return DB.products.count_documents({"$and": [PUB, {"$or": [{f: rx} for f in FIELDS]}]})


def _api_total(s, q):
    r = s.get(f"{BASE}/api/products", params={"q": q, "limit": 5}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["total"]


# --- F: below 50k the API must equal the regex substring search exactly ---
class TestSearchConsistency:
    @pytest.mark.parametrize("word", ["test", "beauty", "Widget", "PERFTEST Product 00500", "Produ", "mobile", "shoes"])
    def test_api_equals_regex(self, s, word):
        assert _api_total(s, word) == _regex_count(word), word

    def test_nonsense_zero(self, s):
        assert _api_total(s, "zzqxnonsenseqq") == 0

    def test_exact_one(self, s):
        assert _api_total(s, "PERFTEST Product 00500") == 1

    def test_text_index_v2_fields(self):
        idx = DB.products.index_information()
        assert "ix_prod_text_v2" in idx, list(idx)
        assert "ix_prod_text" not in idx
        keys = {k for k, _ in idx["ix_prod_text_v2"]["key"]}
        assert "_fts" in keys
        w = set(idx["ix_prod_text_v2"].get("weights", {}).keys())
        for f in ["name", "brand", "tags", "category", "sub_category", "subcategory", "description"]:
            assert f in w, (f, w)


# --- E: sub_category '' falls back to legacy subcategory ---
@pytest.fixture(scope="module")
def legacy():
    tag = uuid.uuid4().hex[:6]
    sub = f"test_legacy_{tag}"
    ids = [f"TEST_{tag}_a", f"TEST_{tag}_b", f"TEST_{tag}_c"]
    DB.products.insert_many([
        {"id": ids[0], "name": f"TEST_ A {tag}", "category": "Beauty", "sub_category": "", "subcategory": sub, "is_published": True, "price": 1},
        {"id": ids[1], "name": f"TEST_ B {tag}", "category": "Beauty", "sub_category": None, "subcategory": sub, "is_published": True, "price": 1},
        {"id": ids[2], "name": f"TEST_ C {tag}", "category": "Beauty", "subcategory": sub, "is_published": True, "price": 1},
    ])
    yield sub, ids
    DB.products.delete_many({"id": {"$in": ids}})


class TestSubcatCounts:
    def test_empty_string_counted(self, s, legacy):
        sub, _ = legacy
        c = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "Beauty"}, timeout=20).json()
        assert c["counts"].get(sub) == 3, c["counts"].get(sub)

    def test_list_matches_badge(self, s, legacy):
        sub, _ = legacy
        lst = s.get(f"{BASE}/api/products", params={"category": "Beauty", "subcategory": sub, "limit": 10}, timeout=20).json()
        assert lst["total"] == 3

    def test_ids_lookup_keeps_order(self, s, legacy):
        _, ids = legacy
        rev = list(reversed(ids)) + ["nope_unknown"]
        r = s.get(f"{BASE}/api/products", params={"ids": ",".join(rev)}, timeout=20).json()
        assert [p["id"] for p in r["items"]] == rev[:3]


# --- Vendor interest badges: list / ids endpoint must carry the real interested_count ---
def test_ids_interested_count_real(s):
    pid = "TEST_int_" + uuid.uuid4().hex[:6]
    DB.products.insert_one({"id": pid, "name": "TEST_ interest", "category": "Beauty", "is_published": True,
                            "price": 1, "stock": 0, "interested_users": ["u1", "u2", "u3"],
                            # iter119: list/ids read the denormalised counter (written by POST /interested
                            # or the startup backfill); a raw DB insert must carry it too.
                            "interested_count": 3})
    try:
        items = s.get(f"{BASE}/api/products", params={"ids": pid}, timeout=20).json()["items"]
        assert items and items[0].get("interested_count") == 3, items
    finally:
        DB.products.delete_one({"id": pid})


# --- subcategory-counts must not 500 when an imported row has a non-string sub_category ---
def test_subcat_counts_non_string_sub(s):
    pid = "TEST_nonstr_" + uuid.uuid4().hex[:6]
    DB.products.insert_one({"id": pid, "name": "TEST_ nonstr", "category": "TEST_cat_nonstr", "sub_category": 123,
                            "is_published": True, "price": 1})
    try:
        r = s.get(f"{BASE}/api/products/subcategory-counts", params={"category": "TEST_cat_nonstr"}, timeout=20)
        assert r.status_code == 200, r.text[:200]
    finally:
        DB.products.delete_one({"id": pid})
