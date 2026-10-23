# Iter99 — closing round: FIX 1 (company-funded refund advance recovery, real flow +
# parallel claims + next-sale auto recovery), FIX 2 (parked-refund cleanup script),
# FIX 3 (rejected-fee refunds), FIX 4 (vendor net-worth breakdown ties), FIX 5.
import asyncio
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOOP = asyncio.new_event_loop()  # one loop for every in-process motor call


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
mdb = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
TV = "1115f762-0a4f-474e-bbdb-6227a06f08b1"


def tok(e, p):
    r = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


@pytest.fixture(scope="module")
def A():
    return tok("support@slangcart.com", "3)Ywxtic")


@pytest.fixture(scope="module")
def V():
    return tok("testvendor@test.com", "Test@1234")


def master(A):
    return requests.get(f"{BASE}/admin/finance/net-worth", headers=A, timeout=60).json()["master"]


def wallet(vid):
    return round(float(mdb.users.find_one({"id": vid}, {"_id": 0, "vendor_earnings": 1})["vendor_earnings"] or 0), 2)


@pytest.fixture(scope="module")
def S():
    tag = uuid.uuid4().hex[:6]
    vid, cid, dpid = f"TEST_v99_{tag}", f"TEST_c99_{tag}", f"TEST_dp99_{tag}"
    mdb.users.insert_many([
        {"id": vid, "email": f"{vid}@x.com", "name": "TEST v99", "vendor_business_name": "TEST Shop99",
         "is_vendor": True, "is_vendor_approved": True, "vendor_earnings": 0.0, "wallet_balance": 0.0,
         "referral_code": f"TV99{tag}"},
        {"id": cid, "email": f"{cid}@x.com", "name": "TEST c99", "wallet_balance": 0.0, "referral_code": f"TC99{tag}"},
        {"id": dpid, "email": f"{dpid}@x.com", "name": "TEST dp99", "is_delivery_partner": True,
         "wallet_balance": 0.0, "referral_code": f"TD99{tag}"},
    ])
    rids, extra_rows = [], []

    def mk_return(amount):
        rid = f"TEST_r99_{uuid.uuid4().hex[:8]}"
        mdb.returns.insert_one({
            "id": rid, "return_number": f"TR99-{rid[-4:]}", "order_id": f"TEST_o_{rid[-6:]}",
            "order_number": "TEST-ORD99", "user_id": cid, "vendor_id": vid, "vendor_name": "TEST Shop99",
            "items": [], "refund_amount": amount, "cashback_reversal_expected": 0,
            "cashback_status": "handled", "cashback_netted_off_refund": 0,
            "status": "returned", "refund_status": "pending", "timeline": [],
        })
        rids.append(rid)
        return rid

    def company_fund(A, amount, seller_has):
        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": float(seller_has)}})
        rid = mk_return(amount)
        requests.post(f"{BASE}/admin/returns/{rid}/refund", headers=A, json={}, timeout=60)
        r = requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=A, json={}, timeout=60)
        assert r.status_code == 200, r.text
        return rid

    yield {"vid": vid, "cid": cid, "dpid": dpid, "mk_return": mk_return,
           "company_fund": company_fund, "extra_rows": extra_rows}
    mdb.users.delete_many({"id": {"$in": [vid, cid, dpid]}})
    mdb.returns.delete_many({"id": {"$in": rids}})
    mdb.vendor_outstanding.delete_many({"$or": [{"vendor_id": vid}, {"id": {"$in": extra_rows}}]})
    mdb.notifications.delete_many({"user_id": {"$in": [vid, cid, dpid]}})
    mdb.dp_vendor_map.delete_many({"dp_id": dpid})
    mdb.transactions.delete_many({"$or": [{"user_id": {"$in": [vid, cid]}}, {"vendor_id": vid}]})
    if "financial_errors" in mdb.list_collection_names():
        mdb.financial_errors.delete_many({"vendor_id": vid})


# FIX 1 — real short-seller company-funded refund → admin one-tap recovery
class TestAdvanceRecovery:
    def test_real_company_funded_refund_full_cycle(self, A, S):
        vid = S["vid"]
        m0 = master(A)
        rid = S["company_fund"](A, 200, 50)
        m1 = master(A)
        assert round(m1["vendor_receivable"] - m0["vendor_receivable"], 2) == 150
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"})
        assert row["status"] == "open" and row["amount"] == 150

        lst = requests.get(f"{BASE}/admin/cashback/outstanding", headers=A, timeout=60).json()
        slot = next(v for v in lst["vendors"] if v["vendor_id"] == vid)
        assert slot["advance_outstanding"] == 150 and slot["cashback_outstanding"] == 0

        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 500.0}})
        r = requests.post(f"{BASE}/admin/cashback/outstanding/{vid}/recover", headers=A,
                          json={"amount": 1000, "note": "TEST_iter99"}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        print("recover:", d)
        assert d["advance_applied"] == 150 and d["cashback_applied"] == 0 and d["applied"] == 150
        assert wallet(vid) == 350
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"})
        assert row["status"] == "settled" and row["recovered"] == 150
        m2 = master(A)
        assert round(m2["vendor_receivable"] - m1["vendor_receivable"], 2) == -150
        txns = list(mdb.transactions.find({"user_id": vid, "type": "advance_recovery"}, {"_id": 0}))
        assert len(txns) == 1 and txns[0]["debit"] == 150 and txns[0].get("credit", 0) in (0, 0.0)
        assert txns[0].get("description") and txns[0].get("wallet_impact") == "vendor_earnings_only"

        # replay the recovery → 400 and nothing taken
        r2 = requests.post(f"{BASE}/admin/cashback/outstanding/{vid}/recover", headers=A,
                           json={"amount": 150}, timeout=60)
        assert r2.status_code == 400, r2.text
        assert wallet(vid) == 350
        # replay the company funding after it was recovered → row must NOT reopen
        requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=A, json={}, timeout=60)
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"})
        m3 = master(A)
        print("after funding replay:", row["status"], row["recovered"], m3["vendor_receivable"] - m2["vendor_receivable"])
        assert row["status"] == "settled"
        assert round(m3["vendor_receivable"] - m2["vendor_receivable"], 2) == 0
        assert mdb.transactions.count_documents({"type": "refund_company_funded", "return_id": rid}) == 1

    def test_parallel_recoveries_debit_once(self, A, S):
        vid = S["vid"]
        rid = S["company_fund"](A, 200, 0)
        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 1000.0}})
        n_before = mdb.transactions.count_documents({"user_id": vid, "type": "advance_recovery"})

        def go(_):
            return requests.post(f"{BASE}/admin/cashback/outstanding/{vid}/recover", headers=A,
                                 json={"amount": 200, "note": "TEST_iter99 parallel"}, timeout=60)
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(go, range(4)))
        codes = [r.status_code for r in res]
        applied = [r.json().get("applied", 0) if r.status_code == 200 else 0 for r in res]
        print("parallel codes", codes, "applied", applied)
        assert round(sum(applied), 2) == 200
        assert wallet(vid) == 800
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"})
        assert row["recovered"] == 200 and row["status"] == "settled"
        assert mdb.transactions.count_documents({"user_id": vid, "type": "advance_recovery"}) == n_before + 1
        assert mdb.vendor_outstanding.count_documents({"vendor_id": vid, "$expr": {"$gt": ["$recovered", "$amount"]}}) == 0

    def test_inprocess_race_8_way(self, S):
        """8 coroutines on the same open rows — claims must be atomic."""
        vid = S["vid"]
        ts = datetime.now(timezone.utc).isoformat()
        ids = [str(uuid.uuid4()) for _ in range(3)]
        for i, amt in zip(ids, (40.0, 60.0, 100.0)):
            mdb.vendor_outstanding.insert_one({"id": i, "vendor_id": vid, "vendor_name": "TEST Shop99",
                                               "kind": "return_refund_company_funded", "amount": amt,
                                               "recovered": 0.0, "status": "open", "created_at": ts})
        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 1000.0}})
        calls = []

        async def bucket(name, amt, also_total_earned=False):
            calls.append((name, amt))

        async def run():
            from core import vendor_advances
            return await asyncio.gather(*[vendor_advances.recover_from_wallet(
                vid, 150, credit_admin_bucket=bucket, note="TEST_iter99 race") for _ in range(8)])
        out = LOOP.run_until_complete(run())
        total = round(sum(float(o.get("applied") or 0) for o in out), 2)
        print("race applied", [o.get("applied") for o in out], "bucket", calls)
        rows = list(mdb.vendor_outstanding.find({"id": {"$in": ids}}, {"_id": 0}))
        rec = round(sum(r["recovered"] for r in rows), 2)
        assert all(r["recovered"] <= r["amount"] + 0.001 for r in rows)
        assert rec == total, f"rows recovered {rec} but wallet debited {total}"
        assert round(1000 - wallet(vid), 2) == total
        assert round(sum(a for _, a in calls), 2) == total
        assert total <= 200  # 8×150 asked, only 200 owed — never more
        # a losing racer skips rather than re-reads; a plain follow-up call takes the rest exactly once
        async def rest():
            from core import vendor_advances
            return await vendor_advances.recover_from_wallet(vid, 500, credit_admin_bucket=bucket, note="TEST_iter99 rest")
        more = LOOP.run_until_complete(rest())
        print("follow-up applied", more.get("applied"))
        assert round(total + float(more.get("applied") or 0), 2) == 200
        assert round(1000 - wallet(vid), 2) == 200
        assert mdb.vendor_outstanding.count_documents({"id": {"$in": ids}, "status": "open"}) == 0

    def test_partial_then_next_sale_auto_recovery(self, A, S):
        vid = S["vid"]
        rid = S["company_fund"](A, 300, 0)
        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 100.0}})
        m0 = master(A)
        r = requests.post(f"{BASE}/admin/cashback/outstanding/{vid}/recover", headers=A,
                          json={"amount": 300}, timeout=60)
        assert r.status_code == 200 and r.json()["advance_applied"] == 100, r.text
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"})
        assert row["status"] == "open" and row["recovered"] == 100
        m1 = master(A)
        assert round(m1["vendor_receivable"] - m0["vendor_receivable"], 2) == -100
        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 500.0}})

        async def run(oid):
            from server import credit_admin_bucket
            from core.cashback import auto_recover_from_vendor_credit
            return await auto_recover_from_vendor_credit(
                vid, {"id": oid, "order_number": "TEST99", "vendor_name": "TEST Shop99"},
                credit_admin_bucket=credit_admin_bucket)
        oid = f"TEST_o99_{uuid.uuid4().hex[:6]}"
        out = LOOP.run_until_complete(run(oid))
        print("auto:", out)
        assert out["advance_recovered"] == 200
        assert wallet(vid) == 300
        out2 = LOOP.run_until_complete(run(oid))  # replay of the same sale
        assert float(out2.get("advance_recovered") or 0) == 0 and wallet(vid) == 300
        row = mdb.vendor_outstanding.find_one({"return_id": rid, "kind": "return_refund_company_funded"})
        assert row["status"] == "settled" and row["recovered"] == 300
        assert mdb.transactions.count_documents({"idempotency_key": f"ADVRECOVER:{oid}"}) == 1

    def test_cashback_cleared_first_then_advance(self, A, S):
        vid = S["vid"]
        ts = datetime.now(timezone.utc).isoformat()
        cb_id = str(uuid.uuid4())
        mdb.vendor_outstanding.insert_one({"id": cb_id, "vendor_id": vid, "kind": "cashback", "amount": 40.0,
                                           "recovered": 0.0, "status": "open", "created_at": ts,
                                           "order_id": f"TEST_cb_{cb_id[:6]}"})
        mdb.users.update_one({"id": vid}, {"$set": {"cashback_outstanding": 40.0, "vendor_earnings": 0.0}})
        S["company_fund"](A, 60, 0)
        mdb.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 70.0}})
        r = requests.post(f"{BASE}/admin/cashback/outstanding/{vid}/recover", headers=A,
                          json={"amount": 100}, timeout=60)
        d = r.json()
        print("mixed:", r.status_code, d)
        assert r.status_code == 200
        assert d["cashback_applied"] == 40 and d["advance_applied"] == 30 and d["applied"] == 70
        assert wallet(vid) == 0
        u = mdb.users.find_one({"id": vid}, {"_id": 0, "cashback_outstanding": 1})
        assert round(float(u.get("cashback_outstanding") or 0), 2) == 0


# FIX 5 — delivery_fee receivable + rider kinds derived from operators
class TestFix5:
    def test_open_delivery_fee_is_receivable(self, A, S):
        m0 = master(A)
        rid = str(uuid.uuid4())
        S["extra_rows"].append(rid)
        mdb.vendor_outstanding.insert_one({"id": rid, "vendor_id": S["vid"], "kind": "delivery_fee",
                                           "amount": 33.0, "recovered": 0.0, "status": "open",
                                           "created_at": datetime.now(timezone.utc).isoformat()})
        m1 = master(A)
        assert round(m1["vendor_receivable"] - m0["vendor_receivable"], 2) == 33
        mdb.vendor_outstanding.delete_one({"id": rid})

    def test_rider_kinds_derived_from_operators(self, A, S):
        r = requests.put(f"{BASE}/admin/delivery-partners/{S['dpid']}/vendors", headers=A, json={
            "vendor_ids": [S["vid"]],
            "recharge_scopes": {S["vid"]: {"kinds": [], "networks": ["airtel", "tata-play"]}}}, timeout=60)
        assert r.status_code == 200, r.text
        m = mdb.dp_vendor_map.find_one({"dp_id": S["dpid"], "vendor_id": S["vid"], "active": {"$ne": False}}, {"_id": 0})
        print("map:", m.get("recharge_kinds"), m.get("recharge_networks"))
        assert sorted(m["recharge_kinds"]) == ["dth", "mobile"]
        assert sorted(m["recharge_networks"]) == ["airtel", "tata-play"]

    def test_seller_recharge_notice_wording(self, A, S):
        oid = f"TEST_o99rc_{uuid.uuid4().hex[:6]}"
        mdb.orders.insert_one({"id": oid, "order_number": f"TEST-{oid[-5:]}", "user_id": S["cid"],
                               "vendor_id": S["vid"], "status": "placed", "total": 10.0, "paid_via": "wallet",
                               "items": [], "status_history": [], "is_recharge": True,
                               "recharge_account": "9876500099", "created_at": "2026-01-01T00:00:00+00:00"})
        try:
            bodies = []
            for st in ("shipped", "delivered"):
                r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=A, json={"status": st}, timeout=60)
                assert r.status_code == 200, r.text
            bodies = [n.get("body") or "" for n in mdb.notifications.find({"user_id": S["vid"]}, {"_id": 0, "body": 1})]
            print("seller notices:", bodies)
            assert bodies and not any("shipped" in b for b in bodies)
            assert any("recharge of 9876500099 is in progress" in b for b in bodies)
            assert any("recharge of 9876500099 is done" in b for b in bodies)
        finally:
            mdb.orders.delete_one({"id": oid})


# FIX 2 — cleanup script is a no-op and keeps genuinely parked / orphan rows
class TestFix2:
    def test_cleanup_script_keeps_parked(self, S):
        rid = S["mk_return"](90)
        keep1, keep2 = str(uuid.uuid4()), str(uuid.uuid4())
        S["extra_rows"].extend([keep1, keep2])
        ts = datetime.now(timezone.utc).isoformat()
        mdb.vendor_outstanding.insert_many([
            {"id": keep1, "vendor_id": S["vid"], "kind": "return_refund", "amount": 90.0, "recovered": 0.0,
             "status": "open", "return_id": rid, "created_at": ts},
            {"id": keep2, "vendor_id": S["vid"], "kind": "return_refund", "amount": 10.0, "recovered": 0.0,
             "status": "open", "return_id": "TEST_missing_return", "created_at": ts},
        ])
        out = subprocess.run([sys.executable, "scripts/close_stale_parked_refunds.py"], cwd="/app/backend",
                             capture_output=True, text=True, timeout=120)
        print(out.stdout[-600:], out.stderr[-300:])
        assert "closed 0" in out.stdout
        assert mdb.vendor_outstanding.find_one({"id": keep1})["status"] == "open"
        assert mdb.vendor_outstanding.find_one({"id": keep2})["status"] == "open"


# FIX 3 — every rejected withdrawal with a fee: one FEEBACK + one reversal
class TestFix3:
    def test_rejected_fee_refunds_exactly_once(self):
        bad = []
        n = 0
        for w in mdb.withdrawals.find({"status": "rejected", "transaction_fee": {"$gt": 0.009}}, {"_id": 0}):
            n += 1
            wid = w["id"]
            fb = mdb.transactions.count_documents({"idempotency_key": f"WDL_FEEBACK:{wid}"})
            fb_any = mdb.transactions.count_documents({"type": "withdrawal_transaction_fee_refund", "withdrawal_id": wid})
            rv = mdb.transactions.count_documents({"idempotency_key": f"WDLFEEREV_REJECT:{wid}"})
            rv_any = mdb.transactions.count_documents({"type": "reversal", "withdrawal_id": wid})
            coll = mdb.transactions.count_documents({"type": "platform_fee_collected", "withdrawal_id": wid})
            if fb != 1 or fb_any != 1 or rv != 1 or rv_any != 1 or coll > 1:
                bad.append((wid[:8], fb, fb_any, rv, rv_any, coll))
        print("rejected-with-fee:", n, "bad:", bad)
        assert not bad


# FIX 4 — testvendor net-worth breakdown sums to ledger balance; LEDGERFIX visible
class TestFix4:
    def test_breakdown_ties(self, V):
        d = requests.get(f"{BASE}/vendor/me/net-worth", headers=V, timeout=60).json()
        b = d["breakdown"]
        plus = ["opening", "sales", "withdrawal_reversals", "delivery_charge_reversals",
                "cashback_funding_returned", "transaction_fee_refunds", "adjustments", "other"]
        minus = ["sale_reversals", "delivery_charges", "refunds", "withdrawals", "cashback_funded",
                 "recoveries", "transaction_fees"]
        s = round(sum(b[k] for k in plus) - sum(b[k] for k in minus), 2)
        print("breakdown", b, "sum", s, "ledger", d["ledger_balance"], "avail", d["available_balance"])
        assert s == round(d["ledger_balance"], 2)
        assert round(d["ledger_balance"], 2) == round(d["available_balance"], 2)
        assert d["in_sync"] is True and d["reconciliation"]["balanced"] is True

    def test_ledgerfix_row_and_export(self, V):
        row = mdb.transactions.find_one({"idempotency_key": f"LEDGERFIX:{TV}"}, {"_id": 0})
        assert row and row.get("description") and "reconciliation" in row["description"].lower()
        r = requests.get(f"{BASE}/vendor/me/net-worth/export", headers=V, timeout=120)
        assert r.status_code == 200
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        print("vendor sheets:", wb.sheetnames)
        found = any(row["reference_number"] in [str(c) for c in rr if c is not None] or
                    any("Ledger reconciliation" in str(c) for c in rr if c)
                    for ws in wb.worksheets for rr in ws.iter_rows(values_only=True))
        assert found, "LEDGERFIX row not in vendor export"
        rec = wb["Reconciliation"]
        items = {str(a): b for a, b in rec.iter_rows(values_only=True) if a}
        print("recon sheet:", items)
        lines = [v for k, v in items.items() if k not in ("Item", "= Ledger balance", "Stored available balance",
                                                          "Difference", "Pending withdrawals",
                                                          "COD cash to collect", "Balanced")]
        assert items.get("Balanced") == "YES"
        assert round(sum(float(x or 0) for x in lines), 2) == round(float(items["= Ledger balance"]), 2), \
            "Reconciliation sheet lines do not sum to the ledger balance"


# Leave testvendor clean
class TestTestvendorClean:
    def test_testvendor_clean(self):
        assert mdb.vendor_outstanding.count_documents({"vendor_id": TV, "status": "open"}) == 0
        u = mdb.users.find_one({"id": TV}, {"_id": 0, "cashback_outstanding": 1})
        assert round(float(u.get("cashback_outstanding") or 0), 2) == 0
        assert mdb.withdrawals.count_documents({"user_id": TV, "status": {"$in": ["pending", "processing", "approved"]}}) == 0
