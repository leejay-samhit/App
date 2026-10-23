# Iter98 — final owner batch: FIX A (receivables only for company-funded rows),
# FIX D (notify only on real status change, ⚡/📦 push), FIX E (one nudge per
# return; DTH-only rider cannot keep a mobile operator), FIX C (fee bucket).
import os
import time
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


def nw(A):
    return requests.get(f"{BASE}/admin/finance/net-worth", headers=A, timeout=60).json()


@pytest.fixture(scope="module")
def seeded():
    tag = uuid.uuid4().hex[:6]
    vid, cid, dpid = f"TEST_v_{tag}", f"TEST_c_{tag}", f"TEST_dp_{tag}"
    mdb.users.insert_many([
        {"id": vid, "email": f"TEST_v_{tag}@x.com", "name": "TEST vendor", "is_vendor": True,
         "is_vendor_approved": True, "vendor_earnings": 0.0, "wallet_balance": 0.0, "referral_code": f"TESTV{tag}"},
        {"id": cid, "email": f"TEST_c_{tag}@x.com", "name": "TEST cust", "wallet_balance": 0.0, "referral_code": f"TESTC{tag}"},
        {"id": dpid, "email": f"TEST_dp_{tag}@x.com", "name": "TEST rider", "is_delivery_partner": True,
         "wallet_balance": 0.0, "referral_code": f"TESTD{tag}"},
    ])
    rids, oids = [], []

    def mk_return(amount):
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

    def mk_order(is_recharge):
        oid = f"TEST_o_{uuid.uuid4().hex[:8]}"
        doc = {"id": oid, "order_number": f"TEST-{oid[-5:]}", "user_id": cid, "vendor_id": vid,
               "status": "placed", "total": 10.0, "paid_via": "wallet", "items": [],
               "status_history": [], "created_at": "2026-01-01T00:00:00+00:00"}
        if is_recharge:
            doc.update({"is_recharge": True, "recharge_account": "9876500000"})
        mdb.orders.insert_one(doc)
        oids.append(oid)
        return oid

    yield {"vid": vid, "cid": cid, "dpid": dpid, "mk_return": mk_return, "mk_order": mk_order}
    mdb.users.delete_many({"id": {"$in": [vid, cid, dpid]}})
    mdb.returns.delete_many({"id": {"$in": rids}})
    mdb.orders.delete_many({"id": {"$in": oids}})
    mdb.vendor_outstanding.delete_many({"return_id": {"$in": rids}})
    mdb.notifications.delete_many({"user_id": {"$in": [vid, cid, dpid]}})
    mdb.dp_vendor_map.delete_many({"dp_id": dpid})
    mdb.transactions.delete_many({"$or": [{"user_id": {"$in": [vid, cid]}}, {"vendor_id": vid}]})
    if "financial_errors" in mdb.list_collection_names():
        mdb.financial_errors.delete_many({"vendor_id": vid})


class TestFixA:
    # FIX A + FIX E(1): parked refund is not a receivable; one nudge per return
    def test_parked_refund_not_receivable_and_one_nudge(self, A, seeded):
        rid = seeded["mk_return"](250)
        m0 = nw(A)["master"]
        for _ in range(3):
            r = requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
            assert r.status_code == 409, r.text
        m1 = nw(A)["master"]
        print("parked: d_rec", round(m1["receivables_total"] - m0["receivables_total"], 2),
              "d_nw", round(m1["net_worth"] - m0["net_worth"], 2))
        assert round(m1["receivables_total"] - m0["receivables_total"], 2) == 0
        assert round(m1["vendor_receivable"] - m0["vendor_receivable"], 2) == 0
        assert round(m1["net_worth"] - m0["net_worth"], 2) == 0
        n = mdb.notifications.count_documents({"user_id": seeded["vid"], "title": "Refund blocked — add money"})
        assert n == 1, f"{n} nudges for one return"

    def test_company_funded_raises_receivable(self, A, seeded):
        mdb.users.update_one({"id": seeded["vid"]}, {"$set": {"vendor_earnings": 50.0}})
        rid = seeded["mk_return"](200)
        requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
        d0 = nw(A)
        m0 = d0["master"]
        r = requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=A, json={}, timeout=60)
        assert r.status_code == 200, r.text
        d1 = nw(A)
        m1 = d1["master"]
        d_rec = round(m1["receivables_total"] - m0["receivables_total"], 2)
        d_nw = round(m1["net_worth"] - m0["net_worth"], 2)
        print("company funded 150: d_rec", d_rec, "d_vendor_rec", round(m1["vendor_receivable"] - m0["vendor_receivable"], 2), "d_nw", d_nw)
        for k in m1:
            if isinstance(m1.get(k), (int, float)) and isinstance(m0.get(k), (int, float)) and abs(m1[k] - m0[k]) > 0.009:
                print("   master delta", k, round(m1[k] - m0[k], 2))
        assert d_rec == 150
        assert mdb.vendor_outstanding.count_documents({"return_id": rid, "status": "open"}) == 1
        assert mdb.transactions.count_documents({"type": "refund_company_funded", "return_id": rid}) == 1
        # replay -> nothing changes
        requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=A, json={}, timeout=60)
        m2 = nw(A)["master"]
        assert round(m2["receivables_total"] - m1["receivables_total"], 2) == 0
        assert mdb.transactions.count_documents({"type": "refund_company_funded", "return_id": rid}) == 1
        seeded["company_rid"] = rid

    def test_company_funded_receivable_is_recoverable(self, A, seeded):
        # The seller now has money; can the admin's ONE recovery process pull it back?
        rid = seeded.get("company_rid")
        if not rid:
            pytest.skip("no company-funded row")
        mdb.users.update_one({"id": seeded["vid"]}, {"$set": {"vendor_earnings": 500.0}})
        m0 = nw(A)["master"]
        r = requests.post(f"{BASE}/admin/cashback/outstanding/{seeded['vid']}/recover", headers=A,
                          json={"amount": 150, "note": "TEST_iter98"}, timeout=60)
        print("recover", r.status_code, r.text[:300])
        m1 = nw(A)["master"]
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"}, {"_id": 0})
        v = mdb.users.find_one({"id": seeded["vid"]}, {"_id": 0, "vendor_earnings": 1})
        print("row after recover", row.get("status"), row.get("recovered"), "vendor_earnings", v,
              "d_rec", round(m1["receivables_total"] - m0["receivables_total"], 2))
        assert row["status"] != "open", "company-funded refund receivable has no recovery path"


class TestFixD:
    # FIX D: one buyer + one seller notice per real transition; replay silent; ⚡ vs 📦
    def _move(self, A, oid, status):
        r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=A, json={"status": status}, timeout=60)
        assert r.status_code == 200, r.text

    def _counts(self, seeded):
        b = list(mdb.notifications.find({"user_id": seeded["cid"]}, {"_id": 0, "title": 1, "body": 1}))
        s = list(mdb.notifications.find({"user_id": seeded["vid"]}, {"_id": 0, "title": 1, "body": 1}))
        return b, s

    @pytest.mark.parametrize("is_recharge", [False, True])
    def test_notify_once_per_transition(self, A, seeded, is_recharge):
        mdb.notifications.delete_many({"user_id": {"$in": [seeded["cid"], seeded["vid"]]}})
        oid = seeded["mk_order"](is_recharge)
        self._move(A, oid, "confirmed")
        b1, s1 = self._counts(seeded)
        print("recharge" if is_recharge else "parcel", "after confirm buyer", b1, "seller", s1)
        assert len(b1) == 1 and len(s1) == 1
        self._move(A, oid, "confirmed")
        self._move(A, oid, "confirmed")
        b2, s2 = self._counts(seeded)
        assert len(b2) == 1 and len(s2) == 1, f"replay re-notified buyer={b2} seller={s2}"
        self._move(A, oid, "shipped")
        b3, s3 = self._counts(seeded)
        assert len(b3) == 2 and len(s3) == 2
        text = " ".join((n.get("title") or "") + " " + (n.get("body") or "") for n in b3).lower()
        if is_recharge:
            assert all(n["title"] == "Recharge update" for n in b3), b3
            assert "parcel" not in text
        pushes = list(mdb.push_log.find({"idempotency_key": {"$regex": f"^order-status-{oid}-"}},
                                        {"_id": 0, "title": 1, "idempotency_key": 1}))
        print("push", pushes)
        titles = {p["title"] for p in pushes}
        assert titles, "no push logged"
        mark = "⚡" if is_recharge else "📦"
        assert all(t.startswith(mark) for t in titles), titles
        keys = [p["idempotency_key"] for p in pushes]
        assert len(keys) == len(set(keys)), f"duplicate pushes {keys}"


class TestFixE:
    # FIX E(2): DTH-only scope drops a mobile operator
    def test_dth_scope_drops_mobile_operator(self, A, seeded):
        opts = {o["slug"]: o.get("kind") for o in mdb.recharge_options.find({"group": "network"}, {"_id": 0, "slug": 1, "kind": 1})}
        print("operators", opts)
        vid = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
        r = requests.put(f"{BASE}/admin/delivery-partners/{seeded['dpid']}/vendors", headers=A, json={
            "vendor_ids": [vid],
            "recharge_scopes": {vid: {"kinds": ["dth"], "networks": ["airtel", "tata-play"]}}}, timeout=60)
        assert r.status_code == 200, r.text
        row = mdb.dp_vendor_map.find_one({"dp_id": seeded["dpid"], "vendor_id": vid}, {"_id": 0})
        print("saved", row.get("recharge_kinds"), row.get("recharge_networks"))
        assert row["recharge_kinds"] == ["dth"]
        assert row["recharge_networks"] == ["tata-play"]
        # networks without any kind ticked
        r = requests.put(f"{BASE}/admin/delivery-partners/{seeded['dpid']}/vendors", headers=A, json={
            "vendor_ids": [vid], "recharge_scopes": {vid: {"kinds": [], "networks": ["airtel", "tata-play"]}}}, timeout=60)
        row = mdb.dp_vendor_map.find_one({"dp_id": seeded["dpid"], "vendor_id": vid}, {"_id": 0})
        print("no-kind save ->", row.get("recharge_kinds"), row.get("recharge_networks"))


class TestFixC:
    # FIX C: revenue bucket ties to rows (fee collected − |fee reversals|)
    def test_platform_fee_bucket_ties_to_rows(self, A):
        d = nw(A)
        g1 = d.get("group_1_revenue") or d.get("groups", {}).get("group_1_revenue") or {}
        pf = g1.get("platform_fee")
        coll = sum(t["amount"] for t in mdb.transactions.find({"type": "platform_fee_collected", "status": {"$in": ["success", "paid", "completed"]}}, {"amount": 1}))
        rev = sum(abs(t["amount"]) for t in mdb.transactions.find({"type": "reversal", "original_type": "platform_fee_collected", "status": "success"}, {"amount": 1}))
        print("platform_fee", pf, "rows", round(coll - rev, 2))
        assert pf is not None and round(pf, 2) == round(coll - rev, 2)
