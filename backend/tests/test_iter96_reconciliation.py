# Iter96 — reconciliation / double-entry audit of the Jun-2026 owner batch
# (recharge completion, seller settlement fee+cashback, wallet recovery,
#  return refund guard, DP recharge scopes, Excel export debit sign)
import io
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
RIDER_ID = "a0bf6822-59fa-4b18-bc53-381229a1f30c"


def tok(e, p):
    r = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=60)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def H():
    return {
        "admin": tok("support@slangcart.com", "3)Ywxtic"),
        "vendor": tok("testvendor@test.com", "Test@1234"),
        "buyer": tok("testbuyer@test.com", "Test@1234"),
        "rider": tok("rider_test@test.com", "Test@1234"),
    }


def nw(H):
    return requests.get(f"{BASE}/admin/finance/net-worth", headers=H["admin"], timeout=60).json()


def close_open_withdrawals(H):
    for w in db.withdrawals.find({"user_id": VID, "status": "pending"}):
        requests.post(f"{BASE}/admin/withdrawals/{w['id']}/reject", headers=H["admin"],
                      json={"reason": "TEST_iter96 cleanup"}, timeout=60)


def seed_outstanding(amount):
    rid = "TEST_iter96_" + uuid.uuid4().hex[:8]
    db.vendor_outstanding.insert_one({"id": rid, "vendor_id": VID, "kind": "cashback", "status": "open",
                                      "amount": amount, "recovered": 0,
                                      "created_at": datetime.now(timezone.utc).isoformat()})
    db.users.update_one({"id": VID}, {"$inc": {"cashback_outstanding": amount}})
    return rid


# ── Settlement: fee + cashback, then REJECT → is the fee returned? ─────────
class TestSettlementReconciliation:
    def test_settlement_net_worth_and_reject(self, H):
        close_open_withdrawals(H)
        v = db.users.find_one({"id": VID})
        if float(v.get("vendor_earnings") or 0) < 5200:
            db.users.update_one({"id": VID}, {"$inc": {"vendor_earnings": 6000}})
            pytest.skip("vendor wallet too low; topped — rerun")
        rid = seed_outstanding(100)
        try:
            n0 = nw(H)
            w0 = float(db.users.find_one({"id": VID})["vendor_earnings"])
            r = requests.post(f"{BASE}/withdrawals", headers=H["vendor"], json={"amount": 5000}, timeout=60)
            assert r.status_code == 200, r.text
            d = r.json()
            wid = d["id"]
            assert d["cashback_adjusted"] == 100 and d["transaction_fee"] == 128.0 and d["amount"] == 4772.0
            w1 = float(db.users.find_one({"id": VID})["vendor_earnings"])
            assert round(w0 - w1, 2) == 5000
            # ledger rows: exactly one of each
            fee_rows = list(db.transactions.find({"idempotency_key": {"$in": [f"WDLFEE:{wid}", f"WDLFEEREV:{wid}", f"WDL:{wid}"]}}))
            assert len(fee_rows) == 3, [x.get("idempotency_key") for x in fee_rows]
            ts = datetime.now(timezone.utc).isoformat()[:13]
            cb = list(db.transactions.find({"user_id": VID, "type": "cashback_recovery", "created_at": {"$regex": f"^{ts}"}}))
            assert len(cb) >= 1
            assert db.vendor_outstanding.find_one({"id": rid})["status"] == "settled"
            n1 = nw(H)
            m0, m1 = n0["master"], n1["master"]
            print("receivables", m0["receivables_total"], "->", m1["receivables_total"],
                  "net_worth", m0["net_worth"], "->", m1["net_worth"])
            assert round(m0["cashback_receivable"] - m1["cashback_receivable"], 2) == 100
            # net worth must rise by exactly the fee (128) — nothing else
            assert abs(round(m1["net_worth"] - m0["net_worth"], 2) - 128.0) < 0.05
            # reject → what comes back?
            rr = requests.post(f"{BASE}/admin/withdrawals/{wid}/reject", headers=H["admin"],
                               json={"reason": "TEST_iter96"}, timeout=60)
            assert rr.status_code == 200
            w2 = float(db.users.find_one({"id": VID})["vendor_earnings"])
            n2 = nw(H)
            print("after reject wallet", w1, "->", w2, " revenue fee", n1["group_1_revenue"]["platform_fee"],
                  "->", n2["group_1_revenue"]["platform_fee"])
            # Expect the 2.56% fee to be returned when the settlement never happens
            assert round(w2 - w1, 2) == 4900.0, f"rejected settlement returned only {round(w2 - w1, 2)} (fee 128 kept)"
        finally:
            db.vendor_outstanding.delete_one({"id": rid})


# ── Admin wallet recovery: one process, no bank leg, no double entry ──────
class TestWalletRecovery:
    def test_recovery(self, H):
        a = H["admin"]
        u = f"{BASE}/admin/cashback/outstanding/{VID}/recover"
        assert requests.post(u, headers=a, json={"amount": 0}, timeout=60).status_code == 400
        rid = seed_outstanding(60)
        try:
            lst = requests.get(f"{BASE}/admin/cashback/outstanding", headers=a, timeout=60).json()
            rows = lst.get("vendors") or []
            me = next((x for x in rows if (x.get("vendor_id") or x.get("id")) == VID), None)
            print("outstanding seller row", me)
            assert me and "wallet_balance" in me and "recoverable_now" in me, str(me)[:300]
            bl0 = db.bank_ledger.count_documents({})
            w0 = float(db.users.find_one({"id": VID})["vendor_earnings"])
            n0 = nw(H)
            r = requests.post(u, headers=a, json={"amount": 60, "method": "bank", "reference": "UTR123"}, timeout=60)
            assert r.status_code == 200, r.text
            assert r.json().get("applied") == 60
            assert db.bank_ledger.count_documents({}) == bl0, "bank_ledger row created"
            assert round(w0 - float(db.users.find_one({"id": VID})["vendor_earnings"]), 2) == 60
            n1 = nw(H)
            assert abs(n1["master"]["net_worth"] - n0["master"]["net_worth"]) < 0.05, "net worth drifted on recovery"
            assert db.vendor_outstanding.find_one({"id": rid})["status"] == "settled"
            # empty wallet → 400
            seed_outstanding(10)
            saved = db.users.find_one({"id": VID})["vendor_earnings"]
            db.users.update_one({"id": VID}, {"$set": {"vendor_earnings": 0}})
            try:
                r2 = requests.post(u, headers=a, json={"amount": 10}, timeout=60)
                assert r2.status_code == 400 and "wallet" in r2.text.lower()
            finally:
                db.users.update_one({"id": VID}, {"$set": {"vendor_earnings": saved}})
        finally:
            db.vendor_outstanding.delete_many({"id": {"$regex": "^TEST_iter96_"}})
            db.users.update_one({"id": VID, "cashback_outstanding": {"$gt": 0}},
                                {"$set": {"cashback_outstanding": 0}})


# ── Recharge completion: no extra money rows, no duplicate notification ───
class TestRechargeCompletion:
    def test_completion_no_ledger_and_replay(self, H):
        opts = requests.get(f"{BASE}/recharge/options", timeout=60).json()["mobile"]
        st, net = opts["states"][0]["slug"], opts["networks"][0]["slug"]
        prods = requests.get(f"{BASE}/recharge/products", params={"kind": "mobile", "state": st, "network": net,
                                                                  "pincode": "517644"}, timeout=60).json()
        plan = next(p for g in prods["groups"] for p in g["products"])
        pay = requests.post(f"{BASE}/recharge/pay/wallet", headers=H["buyer"], json={
            "product_id": plan["id"], "kind": "mobile", "account": "9876509999", "state": st, "network": net},
            timeout=60)
        assert pay.status_code == 200, pay.text
        rid, oid = pay.json()["recharge_id"], pay.json()["order_id"]
        try:
            buyer_id = db.recharges.find_one({"id": rid})["user_id"]
            q = {"$or": [{"order_id": oid}, {"user_id": {"$in": [buyer_id, VID]}}]}
            t0 = db.transactions.count_documents(q)
            n0 = db.notifications.count_documents({"user_id": buyer_id})
            for _ in range(2):
                r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=H["admin"],
                                   json={"status": "delivered"}, timeout=60)
                assert r.status_code in (200, 400), r.text
            rc = db.recharges.find_one({"id": rid})
            assert rc["status"] == "success" and rc.get("completed_at")
            t1 = db.transactions.count_documents(q)
            n1 = db.notifications.count_documents({"user_id": buyer_id})
            print("txn rows", t0, "->", t1, "notifs", n0, "->", n1)
            assert t1 == t0, "completion wrote extra money rows"
            assert n1 - n0 <= 1, f"completion+replay created {n1-n0} notifications (expected 1 'Recharge successful')"
        finally:
            db.recharges.update_one({"id": rid}, {"$set": {"account": "TEST_iter96"}})


# ── Return refund-from-company guard ──────────────────────────────────────
class TestReturnGuard:
    def test_company_refund_blocked_when_seller_can_pay(self, H):
        rid = "TEST_iter96_ret_" + uuid.uuid4().hex[:6]
        db.returns.insert_one({"id": rid, "vendor_id": VID, "order_id": "TEST_iter96_order", "user_id": "x",
                               "refund_amount": 10, "status": "approved",
                               "created_at": datetime.now(timezone.utc).isoformat()})
        try:
            r = requests.post(f"{BASE}/admin/returns/{rid}/refund-from-company", headers=H["admin"], json={}, timeout=60)
            assert r.status_code == 400 and "shop wallet can cover" in r.text, r.text
        finally:
            db.returns.delete_one({"id": rid})


# ── DP scopes: rider must not see out-of-scope recharge orders ────────────
class TestDPScopes:
    def test_scope_enforced(self, H):
        a = H["admin"]
        cur = requests.get(f"{BASE}/admin/delivery-partners/{RIDER_ID}/vendors", headers=a, timeout=60).json()
        mapped = [x.get("id") or x.get("vendor_id") for x in (cur.get("vendors") or cur.get("items") or []) if x.get("mapped")]
        orig_scopes = cur.get("mapped_scopes") or {}
        ids = list(set(mapped + [VID]))
        oid = "TEST_iter96_dth_" + uuid.uuid4().hex[:6]
        db.orders.insert_one({"id": oid, "order_number": oid, "vendor_id": VID, "user_id": "x", "is_recharge": True,
                              "order_kind": "recharge", "recharge_kind": "dth", "recharge_network": "tatasky",
                              "status": "placed", "total": 1, "items": [], "pincode": "517644",
                              "created_at": datetime.now(timezone.utc).isoformat()})
        try:
            r = requests.put(f"{BASE}/admin/delivery-partners/{RIDER_ID}/vendors", headers=a, json={
                "vendor_ids": ids, "recharge_scopes": {VID: {"kinds": ["mobile"], "networks": ["airtel"]}}}, timeout=60)
            assert r.status_code == 200, r.text
            orders = requests.get(f"{BASE}/delivery-partner/me/orders", headers=H["rider"], timeout=60).json()
            lst = orders if isinstance(orders, list) else (orders.get("items") or orders.get("orders") or [])
            assert not any(o.get("id") == oid for o in lst), "out-of-scope DTH order visible"
            p = requests.patch(f"{BASE}/delivery-partner/orders/{oid}/status", headers=H["rider"],
                               json={"status": "out_for_delivery"}, timeout=60)
            assert p.status_code == 403, p.text
            # empty scope → visible
            requests.put(f"{BASE}/admin/delivery-partners/{RIDER_ID}/vendors", headers=a, json={
                "vendor_ids": ids, "recharge_scopes": {}}, timeout=60)
            orders = requests.get(f"{BASE}/delivery-partner/me/orders", headers=H["rider"], timeout=60).json()
            lst = orders if isinstance(orders, list) else (orders.get("items") or orders.get("orders") or [])
            assert any(o.get("id") == oid for o in lst), "empty scope hid shop's recharge order"
        finally:
            db.orders.delete_one({"id": oid})
            requests.put(f"{BASE}/admin/delivery-partners/{RIDER_ID}/vendors", headers=a, json={
                "vendor_ids": mapped, "recharge_scopes": orig_scopes}, timeout=60)


# ── Excel export: Recharge sheet + shop_money debits are negative ────────
class TestExcelExport:
    def test_export(self, H):
        import openpyxl
        r = requests.get(f"{BASE}/admin/wallet/export/groupwise", headers=H["admin"], timeout=120)
        assert r.status_code == 200, r.text[:200]
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True)
        print("sheets", wb.sheetnames)
        assert "Recharge" in wb.sheetnames
        debit_types = {"delivery_charge_paid", "cashback_recovery", "withdrawal_hold",
                       "withdrawal_transaction_fee", "return_refund_debit"}
        bad, seen, no_remark = [], 0, 0
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            hdr = None
            for row in it:
                if row and "Transaction Type" in row:
                    hdr = list(row)
                    break
            if not hdr:
                continue
            ti, di, ci, ai, ri = (hdr.index(k) for k in ("Transaction Type", "Debit", "Credit", "Amount", "Remarks"))
            for row in it:
                t = str(row[ti] or "").lower().replace(" ", "_")
                if t in debit_types:
                    seen += 1
                    amt = float(row[ai] or 0)
                    if amt > 0 or not row[di]:
                        bad.append((ws.title, t, row[di], row[ci], amt))
                    if not row[ri]:
                        no_remark += 1
        print("debit rows checked", seen, "bad", len(bad), bad[:5], "no remarks", no_remark)
        assert seen > 0 and not bad


# ── Concurrency: double-tap must not create 2 settlements / 2 recoveries ──
class TestConcurrency:
    def test_parallel_settlements_and_recoveries(self, H):
        from concurrent.futures import ThreadPoolExecutor
        close_open_withdrawals(H)
        rid = seed_outstanding(60)
        try:
            def rec(_):
                return requests.post(f"{BASE}/admin/cashback/outstanding/{VID}/recover",
                                     headers=H["admin"], json={"amount": 60}, timeout=60)
            with ThreadPoolExecutor(3) as ex:
                rs = list(ex.map(rec, range(3)))
            applied = sum(float(r.json().get("applied") or 0) for r in rs if r.status_code == 200)
            out = float(db.users.find_one({"id": VID}).get("cashback_outstanding") or 0)
            print("parallel recover applied", applied, "outstanding", out)
            assert applied <= 60.0 and out >= 0, f"over-recovered {applied} (outstanding {out})"
        finally:
            db.vendor_outstanding.delete_one({"id": rid})
            db.users.update_one({"id": VID}, {"$set": {"cashback_outstanding": 0}})
