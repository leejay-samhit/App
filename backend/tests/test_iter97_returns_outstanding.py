# Iter97 — FIX 6: return refund outstanding (one row per return, close on pay,
# supersede on company funding) and its effect on receivables / net worth.
import os
import uuid
import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
mdb = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]


def tok(e, p):
    r = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


@pytest.fixture(scope="module")
def A():
    return tok("support@slangcart.com", "3)Ywxtic")


def master(A):
    return requests.get(f"{BASE}/admin/finance/net-worth", headers=A, timeout=60).json()["master"]


@pytest.fixture(scope="module")
def seeded():
    tag = uuid.uuid4().hex[:6]
    vid, cid = f"TEST_v_{tag}", f"TEST_c_{tag}"
    mdb.users.insert_many([
        {"id": vid, "email": f"TEST_v_{tag}@x.com", "name": "TEST vendor", "is_vendor": True,
         "vendor_earnings": 0.0, "wallet_balance": 0.0, "referral_code": f"TESTV{tag}"},
        {"id": cid, "email": f"TEST_c_{tag}@x.com", "name": "TEST cust", "wallet_balance": 0.0, "referral_code": f"TESTC{tag}"},
    ])
    rids = []

    def mk(amount):
        rid = f"TEST_r_{uuid.uuid4().hex[:8]}"
        mdb.returns.insert_one({
            "id": rid, "return_number": f"TREF-{rid[-4:]}", "order_id": f"TEST_o_{rid[-6:]}",
            "order_number": "TEST-ORD", "user_id": cid, "vendor_id": vid, "vendor_name": "TEST vendor",
            "items": [], "refund_amount": amount, "cashback_reversal_expected": 0,
            "cashback_status": "handled", "cashback_netted_off_refund": 0,
            "status": "returned", "refund_status": "pending", "timeline": [],
        })
        rids.append(rid)
        return rid

    yield {"vid": vid, "cid": cid, "mk": mk}
    mdb.users.delete_many({"id": {"$in": [vid, cid]}})
    mdb.returns.delete_many({"id": {"$in": rids}})
    mdb.vendor_outstanding.delete_many({"return_id": {"$in": rids}})
    mdb.transactions.delete_many({"$or": [{"user_id": {"$in": [vid, cid]}}, {"vendor_id": vid}]})
    mdb.financial_errors.delete_many({"vendor_id": vid}) if "financial_errors" in mdb.list_collection_names() else None


class TestReturnOutstanding:
    def test_short_seller_parks_once_then_closes(self, A, seeded):
        rid = seeded["mk"](300)
        m0 = master(A)
        for _ in range(3):
            r = requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
            assert r.status_code == 409, r.text
        rows = list(mdb.vendor_outstanding.find({"return_id": rid}, {"_id": 0}))
        print("parked rows", rows)
        assert len(rows) == 1 and rows[0]["status"] == "open" and rows[0]["amount"] == 300
        m1 = master(A)
        print("PARKED delta receivable", round(m1["vendor_receivable"] - m0["vendor_receivable"], 2),
              "net_worth", round(m1["net_worth"] - m0["net_worth"], 2))
        # nothing was advanced by the company while the refund is parked, so
        # this must NOT be a receivable / raise net worth
        phantom = round(m1["net_worth"] - m0["net_worth"], 2)
        # seller funds -> refund goes through, vendor wallet -> customer wallet
        mdb.users.update_one({"id": seeded["vid"]}, {"$set": {"vendor_earnings": 500.0}})
        r = requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
        assert r.status_code == 200, r.text
        row = mdb.vendor_outstanding.find_one({"return_id": rid}, {"_id": 0})
        assert row["status"] == "settled"
        v = mdb.users.find_one({"id": seeded["vid"]})
        c = mdb.users.find_one({"id": seeded["cid"]})
        assert round(v["vendor_earnings"], 2) == 200 and round(c["wallet_balance"], 2) == 300
        assert mdb.transactions.count_documents({"type": "refund_company_funded", "vendor_id": seeded["vid"]}) == 0
        assert mdb.transactions.count_documents({"return_id": rid}) == 2
        # replay is a no-op
        r = requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
        assert r.status_code == 200 and r.json().get("already")
        assert mdb.transactions.count_documents({"return_id": rid}) == 2
        assert phantom == 0, f"parked (unfunded) refund raised net worth by {phantom}"

    def test_company_funded_one_open_row(self, A, seeded):
        mdb.users.update_one({"id": seeded["vid"]}, {"$set": {"vendor_earnings": 100.0}})
        rid = seeded["mk"](400)
        m_pre = master(A)
        r = requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
        assert r.status_code == 409
        m0 = master(A)
        r = requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=A, json={}, timeout=60)
        assert r.status_code == 200, r.text
        rows = list(mdb.vendor_outstanding.find({"return_id": rid}, {"_id": 0}))
        print("rows", [(x["kind"], x["status"], x["amount"]) for x in rows])
        opn = [x for x in rows if x["status"] == "open"]
        assert len(opn) == 1 and opn[0]["kind"] == "return_refund_company_funded" and opn[0]["amount"] == 300
        m1 = master(A)
        d_rec = round(m1["vendor_receivable"] - m0["vendor_receivable"], 2)
        d_nw = round(m1["net_worth"] - m0["net_worth"], 2)
        print("COMPANY delta receivable", d_rec, "receivables_total",
              round(m1["receivables_total"] - m0["receivables_total"], 2), "net_worth", d_nw)
        v = mdb.users.find_one({"id": seeded["vid"]})
        c = mdb.users.find_one({"id": seeded["cid"]})
        print("vendor", v["vendor_earnings"], "cust", c["wallet_balance"])
        assert round(v["vendor_earnings"], 2) == 0 
        assert d_rec == 300 or round(m1["vendor_receivable"] - m_pre["vendor_receivable"], 2) == 300
        # replay company refund -> nothing changes
        r2 = requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=A, json={}, timeout=60)
        print("replay", r2.status_code, r2.text[:150])
        assert mdb.vendor_outstanding.count_documents({"return_id": rid, "status": "open"}) == 1
        assert mdb.transactions.count_documents({"type": "refund_company_funded", "return_id": rid}) == 1
