"""iter-95 (Jan 2026) — money-critical recharge bugs 3a-3g + regression.

Owner reported: a recharge used to take the customer's money but write ONLY
a `recharges` row and ONE transaction — no order, no vendor credit, no bank
ledger row, no vendor shop-wallet credit, and paying from the Slangcart
WALLET wasn't offered for recharges at all.

This file verifies the fix end-to-end against the preview backend:
    3a — verify also creates a real order (RC-xxxxxx)
    3b — /vendor/me/sales shows the recharge order + vendor_sales row
    3c — vendor shop wallet credited exactly once (VENDORSALE:{order_id})
    3d — bank_ledger CREDIT with RCHGPAY:{attempt_id}, treasury invariant
    3e — POST /recharge/pay/wallet (full-wallet, no gateway)
    3f — POST /recharge/payment/start wallet+UPI split
    3g — idempotency on replayed verify
    Regression — /recharge/history still enriched, /recharge/products /options unchanged.

All seed data (plans, recharges, orders, vendor_sales, shop_money,
bank_ledger, transactions, recharge_payments) is cleaned up module-scope.
"""
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"
API = BASE_URL + "/api"
UA = {"User-Agent": "curl/8.5.0"}

ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
VENDOR = {"email": "testvendor@test.com", "password": "Test@1234"}
BUYER = {"email": "testbuyer@test.com", "password": "Test@1234"}

VENDOR_ID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"

# Direct DB only for cleanup + ledger invariant assertions. NEVER used to
# write balances; those move only through the endpoints under test.
MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("DB_NAME") or "test_database"
_mongo = MongoClient(MONGO_URL)
db = _mongo[DB_NAME]


# ─── helpers ───────────────────────────────────────────────────────────────

def _login(creds: Dict[str, str]) -> str:
    r = requests.post(f"{API}/auth/login", json=creds, headers=UA, timeout=15)
    assert r.status_code == 200, f"login {creds['email']} → {r.status_code} {r.text[:200]}"
    tok = r.json().get("token")
    assert tok, f"no token for {creds['email']}: {r.json()}"
    return tok


def _hdr(tok: str) -> Dict[str, str]:
    return {**UA, "Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _me(tok: str) -> Dict[str, Any]:
    r = requests.get(f"{API}/auth/me", headers=_hdr(tok), timeout=10)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def _wallet_balance(tok: str) -> float:
    me = _me(tok)
    return round(float(me.get("wallet_balance") or 0), 2)


def _vendor_earnings(vendor_id: str) -> float:
    row = db.users.find_one({"id": vendor_id}, {"vendor_earnings": 1})
    return round(float((row or {}).get("vendor_earnings") or 0), 2)


# ─── module-level fixtures ─────────────────────────────────────────────────

CLEANUP: Dict[str, List[str]] = {
    "product_ids": [],
    "recharge_payment_ids": [],
    "recharge_ids": [],
    "order_ids": [],
}


@pytest.fixture(scope="module")
def admin_tok() -> str:
    return _login(ADMIN)


@pytest.fixture(scope="module")
def vendor_tok() -> str:
    return _login(VENDOR)


@pytest.fixture(scope="module")
def buyer_tok() -> str:
    return _login(BUYER)


@pytest.fixture(scope="module")
def buyer_id(buyer_tok) -> str:
    return _me(buyer_tok)["id"]


@pytest.fixture(scope="module")
def cheap_plan(admin_tok) -> Dict[str, Any]:
    """Create a disposable Airtel plan priced at ₹19 owned by testvendor."""
    pid = str(uuid.uuid4())
    payload = {
        "id": pid,
        "name": f"ITER95 Recharge {pid[:6]}",
        "price": 19.0,
        "stock": 999999,
        "vendor_id": VENDOR_ID,
        "category": "Recharge",
        "subcategory": "Mobile Recharge",
        "recharge_kind": "mobile",
        "recharge_network": "airtel",
        "recharge_state": "andhra-pradesh-telangana-ap-tg",
        "recharge_data": "1GB",
        "recharge_validity": "1 day",
        "recharge_calls": "",
        "is_published": True,
        "active": True,
        "free_delivery": True,
        "image_url": "",
    }
    r = requests.post(f"{API}/admin/products", json=payload, headers=_hdr(admin_tok), timeout=15)
    assert r.status_code in (200, 201), f"create plan: {r.status_code} {r.text[:300]}"
    plan = r.json()
    pid = plan.get("id") or pid
    CLEANUP["product_ids"].append(pid)
    plan["id"] = pid
    plan["price"] = 19.0
    return plan


@pytest.fixture(scope="module", autouse=True)
def _cleanup_at_end(admin_tok):
    yield
    # delete products via admin endpoint
    for pid in CLEANUP["product_ids"]:
        try:
            requests.delete(f"{API}/admin/products/{pid}", headers=_hdr(admin_tok), timeout=10)
        except Exception:
            pass
    # scrub rows the suite created
    if CLEANUP["recharge_payment_ids"]:
        db.recharge_payments.delete_many({"id": {"$in": CLEANUP["recharge_payment_ids"]}})
    if CLEANUP["recharge_ids"]:
        db.recharges.delete_many({"id": {"$in": CLEANUP["recharge_ids"]}})
    if CLEANUP["order_ids"]:
        ids = CLEANUP["order_ids"]
        db.orders.delete_many({"id": {"$in": ids}})
        db.vendor_sales.delete_many({"order_id": {"$in": ids}})
        db.transactions.delete_many({"order_id": {"$in": ids}})
        db.transactions.delete_many({
            "idempotency_key": {"$in": [f"VENDORSALE:{o}" for o in ids]},
        })
    if CLEANUP["recharge_payment_ids"]:
        db.bank_ledger.delete_many({
            "ref_key": {"$in": [f"RCHGPAY:{p}" for p in CLEANUP["recharge_payment_ids"]]},
        })


# ─── BUG 3a / 3b / 3c / 3d — online pay creates order+money rows ────────────

@pytest.fixture(scope="module")
def online_recharge(buyer_tok, cheap_plan, admin_tok) -> Dict[str, Any]:
    """Pay the cheap plan ONLINE (full 19 UPI, 0 wallet). Returns verify payload
    enriched with the stored attempt and a snapshot of pre/post treasury."""
    account = "9000000111"
    # finance snapshot BEFORE
    nw_before = requests.get(
        f"{API}/admin/finance/net-worth", headers=_hdr(admin_tok), timeout=20,
    ).json()
    assert "master" in nw_before, nw_before
    bank_before = round(float(nw_before["master"]["components"]["bank_tally_net"]), 2)
    vp_before = round(float(nw_before["master"]["components"]["vendor_payable"]), 2)
    nw_before_total = round(float(nw_before["master"]["net_worth"]), 2)
    ve_before = _vendor_earnings(VENDOR_ID)

    start = requests.post(
        f"{API}/recharge/payment/start",
        json={"kind": "mobile", "product_id": cheap_plan["id"], "account": account, "wallet_amount": 0},
        headers=_hdr(buyer_tok), timeout=15,
    )
    assert start.status_code == 200, f"start: {start.status_code} {start.text[:300]}"
    s = start.json()
    assert s["amount"] == 19.0 and s["online_amount"] == 19.0 and s["wallet_amount"] == 0.0
    CLEANUP["recharge_payment_ids"].append(s["payment_id"])

    verify = requests.post(
        f"{API}/recharge/payment/verify",
        json={
            "payment_id": s["payment_id"],
            "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": "sig_MOCK",
        },
        headers=_hdr(buyer_tok), timeout=20,
    )
    assert verify.status_code == 200, f"verify: {verify.status_code} {verify.text[:300]}"
    v = verify.json()
    CLEANUP["recharge_ids"].append(v["recharge_id"])
    assert v.get("order_id"), v
    CLEANUP["order_ids"].append(v["order_id"])

    time.sleep(0.5)  # let any async writes settle (there shouldn't be any)
    nw_after = requests.get(
        f"{API}/admin/finance/net-worth", headers=_hdr(admin_tok), timeout=20,
    ).json()
    return {
        "account": account,
        "start": s,
        "verify": v,
        "attempt_id": s["payment_id"],
        "bank_before": bank_before,
        "bank_after": round(float(nw_after["master"]["components"]["bank_tally_net"]), 2),
        "vp_before": vp_before,
        "vp_after": round(float(nw_after["master"]["components"]["vendor_payable"]), 2),
        "nw_before": nw_before_total,
        "nw_after": round(float(nw_after["master"]["net_worth"]), 2),
        "ve_before": ve_before,
        "ve_after": _vendor_earnings(VENDOR_ID),
    }


class TestBug3a_OrderCreatedByVerify:
    def test_order_row_exists_with_recharge_fields(self, online_recharge):
        v = online_recharge["verify"]
        assert v["order_id"] and v.get("order_number", "").startswith("RC-"), v
        order = db.orders.find_one({"id": v["order_id"]}, {"_id": 0})
        assert order is not None, "order not persisted"
        assert order["recharge_id"] == v["recharge_id"]
        assert order["order_kind"] == "recharge"
        assert order["is_recharge"] is True
        assert order["recharge_account"] == online_recharge["account"]
        assert order["recharge_kind"] == "mobile"
        assert order["vendor_id"] == VENDOR_ID
        assert round(float(order["total"]), 2) == 19.0
        assert round(float(order.get("cod_due") or 0), 2) == 0.0
        assert round(float(order.get("delivery_charge") or 0), 2) == 0.0
        assert order["status"] == "placed"
        assert order["paid_via"] == "online"
        assert order["payment_status"] == "paid"


class TestBug3b_VendorVisibility:
    def test_vendor_sales_endpoint_shows_recharge(self, vendor_tok, online_recharge):
        r = requests.get(f"{API}/vendor/me/sales", headers=_hdr(vendor_tok), timeout=15)
        assert r.status_code == 200, r.text[:200]
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("sales") or []
        oid = online_recharge["verify"]["order_id"]
        match = [row for row in rows if row.get("order_id") == oid or row.get("id") == oid]
        assert match, f"vendor /sales missing order {oid}"
        row = match[0]
        assert row.get("is_recharge") is True
        assert row.get("order_kind") == "recharge"
        assert row.get("recharge_account") == online_recharge["account"]

    def test_vendor_sales_db_row(self, online_recharge):
        vs = db.vendor_sales.find_one(
            {"order_id": online_recharge["verify"]["order_id"]}, {"_id": 0},
        )
        assert vs, "vendor_sales row missing"
        assert vs["order_kind"] == "recharge"
        assert round(float(vs["line_total"]), 2) == 19.0
        assert vs["vendor_id"] == VENDOR_ID


class TestBug3c_VendorShopWalletCredited:
    def test_vendor_earnings_increased_by_price(self, online_recharge):
        assert round(online_recharge["ve_after"] - online_recharge["ve_before"], 2) == 19.0

    # FIX(1): shop_money.credit() writes into `transactions`, not a `shop_money` collection
    def test_vendor_credit_txn_row_with_idempotency_key(self, online_recharge):
        oid = online_recharge["verify"]["order_id"]
        rows = list(db.transactions.find({"idempotency_key": f"VENDORSALE:{oid}"}, {"_id": 0}))
        assert len(rows) == 1, f"expected exactly 1 VENDORSALE:{oid} txn row, got {len(rows)}"
        sm = rows[0]
        assert sm.get("type") == "vendor_sale"
        assert sm.get("user_id") == VENDOR_ID
        assert sm.get("order_id") == oid
        assert round(float(sm.get("amount") or 0), 2) == 19.0
        assert sm.get("txn_group") == "vendor_payable"


class TestBug3d_BankLedgerAndTreasury:
    def test_bank_credit_row_with_online_slice(self, online_recharge):
        aid = online_recharge["attempt_id"]
        row = db.bank_ledger.find_one({"ref_key": f"RCHGPAY:{aid}"}, {"_id": 0})
        assert row, f"bank_ledger RCHGPAY:{aid} missing"
        assert (row.get("kind") or row.get("type") or "").lower() == "credit"
        assert row.get("category") == "recharge_online"
        assert round(float(row["amount"]), 2) == 19.0  # pure online slice

    def test_treasury_invariant(self, online_recharge):
        # bank rises by online slice (19), vendor_payable rises by full price (19)
        d_bank = round(online_recharge["bank_after"] - online_recharge["bank_before"], 2)
        d_vp = round(online_recharge["vp_after"] - online_recharge["vp_before"], 2)
        d_nw = round(online_recharge["nw_after"] - online_recharge["nw_before"], 2)
        assert d_bank == 19.0, f"bank_tally_net Δ={d_bank}, expected 19"
        assert d_vp == 19.0, f"vendor_payable Δ={d_vp}, expected 19"
        # Net worth: bank_balance +19, vendor_payable (liability) +19 → net 0 (± rounding)
        assert abs(d_nw) < 0.05, f"net_worth drifted by Δ={d_nw}"


# ─── BUG 3g — idempotency on replayed verify ──────────────────────────────

class TestBug3g_Idempotency:
    def test_replayed_verify_is_noop(self, buyer_tok, online_recharge, admin_tok):
        aid = online_recharge["attempt_id"]
        rid = online_recharge["verify"]["recharge_id"]
        oid = online_recharge["verify"]["order_id"]
        orders_before = db.orders.count_documents({"recharge_id": rid})
        recharges_before = db.recharges.count_documents({"id": rid})
        bank_before = db.bank_ledger.count_documents({"ref_key": f"RCHGPAY:{aid}"})
        sm_before = db.transactions.count_documents({"idempotency_key": f"VENDORSALE:{oid}"})
        assert sm_before == 1, f"expected 1 vendor credit before replay, got {sm_before}"
        wb_before = _wallet_balance(buyer_tok)
        ve_before = _vendor_earnings(VENDOR_ID)

        verify2 = requests.post(
            f"{API}/recharge/payment/verify",
            json={
                "payment_id": aid,
                "razorpay_order_id": online_recharge["start"]["razorpay_order_id"],
                "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
                "razorpay_signature": "sig_MOCK2",
            },
            headers=_hdr(buyer_tok), timeout=15,
        )
        assert verify2.status_code == 200, verify2.text[:200]
        body = verify2.json()
        assert body.get("already_verified") is True, body

        assert db.orders.count_documents({"recharge_id": rid}) == orders_before
        assert db.recharges.count_documents({"id": rid}) == recharges_before
        assert db.bank_ledger.count_documents({"ref_key": f"RCHGPAY:{aid}"}) == bank_before
        assert db.transactions.count_documents({"idempotency_key": f"VENDORSALE:{oid}"}) == sm_before
        assert _wallet_balance(buyer_tok) == wb_before
        assert _vendor_earnings(VENDOR_ID) == ve_before


# ─── BUG 3e — pay from wallet (no gateway) ─────────────────────────────────

class TestBug3e_WalletOnly:
    def test_wallet_pay_books_order_and_credits_vendor(self, buyer_tok, buyer_id, cheap_plan, admin_tok):
        account = "9000000222"
        wb_before = _wallet_balance(buyer_tok)
        ve_before = _vendor_earnings(VENDOR_ID)
        if wb_before < 19.0:
            pytest.skip(f"buyer wallet too low ({wb_before}) to run wallet-only test")

        nw_before = requests.get(
            f"{API}/admin/finance/net-worth", headers=_hdr(admin_tok), timeout=20,
        ).json()["master"]["components"]
        bank_before = round(float(nw_before["bank_tally_net"]), 2)

        r = requests.post(
            f"{API}/recharge/pay/wallet",
            json={"kind": "mobile", "product_id": cheap_plan["id"], "account": account},
            headers=_hdr(buyer_tok), timeout=20,
        )
        assert r.status_code == 200, f"wallet pay: {r.status_code} {r.text[:300]}"
        v = r.json()
        assert v.get("ok") and v.get("paid_via") == "wallet"
        assert v.get("order_id") and v.get("order_number", "").startswith("RC-")
        CLEANUP["recharge_ids"].append(v["recharge_id"])
        CLEANUP["order_ids"].append(v["order_id"])
        rp = db.recharges.find_one({"id": v["recharge_id"]}, {"payment_id": 1})
        if rp and rp.get("payment_id"):
            CLEANUP["recharge_payment_ids"].append(rp["payment_id"])

        # wallet debited by exactly price
        wb_after = _wallet_balance(buyer_tok)
        assert round(wb_before - wb_after, 2) == 19.0, f"wallet Δ={wb_before - wb_after}"

        # order shape
        order = db.orders.find_one({"id": v["order_id"]}, {"_id": 0})
        assert order["paid_via"] == "wallet"
        assert round(float(order.get("wallet_paid") or 0), 2) == 19.0
        assert round(float(order.get("online_paid") or 0), 2) == 0.0

        # vendor credited
        assert round(_vendor_earnings(VENDOR_ID) - ve_before, 2) == 19.0

        # NO bank ledger row for wallet-only payment
        if rp and rp.get("payment_id"):
            bank_row = db.bank_ledger.find_one({"ref_key": f"RCHGPAY:{rp['payment_id']}"})
            assert bank_row is None, "wallet-only must NOT write a bank row"

        # bank_tally_net unchanged
        nw_after = requests.get(
            f"{API}/admin/finance/net-worth", headers=_hdr(admin_tok), timeout=20,
        ).json()["master"]["components"]
        bank_after = round(float(nw_after["bank_tally_net"]), 2)
        assert abs(bank_after - bank_before) < 0.05, f"bank moved on wallet-only: Δ={bank_after - bank_before}"

        # FIX(2): exactly ONE buyer transaction (scoped to buyer) with payment_leg='wallet'
        txns = list(db.transactions.find({"order_id": v["order_id"], "user_id": buyer_id}, {"_id": 0}))
        assert len(txns) == 1, f"expected 1 buyer txn, got {len(txns)}"
        assert txns[0].get("payment_leg") == "wallet"
        assert round(float(txns[0]["amount"]), 2) == -19.0
        # plus exactly ONE vendor credit row
        vrows = list(db.transactions.find({"order_id": v["order_id"], "user_id": VENDOR_ID}, {"_id": 0}))
        assert len(vrows) == 1, f"expected 1 vendor txn, got {len(vrows)}"
        assert vrows[0].get("type") == "vendor_sale"
        assert vrows[0].get("idempotency_key") == f"VENDORSALE:{v['order_id']}"
        assert round(float(vrows[0]["amount"]), 2) == 19.0

    def test_wallet_pay_insufficient_rejected(self, cheap_plan):
        # fresh buyer with no balance — register one so we don't tamper with testbuyer
        email = f"TEST_poor_{uuid.uuid4().hex[:8]}@test.com"
        reg = requests.post(
            f"{API}/auth/register",
            json={"email": email, "password": "Test@1234", "name": "Poor Buyer", "phone": "9999999999"},
            headers=UA, timeout=15,
        )
        if reg.status_code not in (200, 201):
            pytest.skip(f"could not register poor buyer: {reg.status_code} {reg.text[:200]}")
        try:
            tok = _login({"email": email, "password": "Test@1234"})
        except AssertionError:
            tok = reg.json().get("token")
            if not tok:
                pytest.skip("no token after register")
        wb_before = _wallet_balance(tok)
        r = requests.post(
            f"{API}/recharge/pay/wallet",
            json={"kind": "mobile", "product_id": cheap_plan["id"], "account": "9000000333"},
            headers=_hdr(tok), timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"
        assert _wallet_balance(tok) == wb_before, "wallet moved on insufficient"
        # cleanup fresh user
        uid_doc = db.users.find_one({"email": email}, {"id": 1})
        if uid_doc:
            db.users.delete_one({"id": uid_doc["id"]})

    def test_wallet_pay_anonymous_401(self, cheap_plan):
        r = requests.post(
            f"{API}/recharge/pay/wallet",
            json={"kind": "mobile", "product_id": cheap_plan["id"], "account": "9000000444"},
            headers=UA, timeout=15,
        )
        assert r.status_code in (401, 403), f"anon → {r.status_code}"


# ─── BUG 3f — wallet + UPI split ───────────────────────────────────────────

class TestBug3f_WalletOnlineSplit:
    def test_split_books_two_legs_and_only_online_hits_bank(
        self, buyer_tok, buyer_id, cheap_plan, admin_tok,
    ):
        price = 19.0
        wallet_slice = 5.0
        online_slice = round(price - wallet_slice, 2)
        account = "9000000555"
        wb_before = _wallet_balance(buyer_tok)
        if wb_before < wallet_slice:
            pytest.skip("buyer wallet too low for split")
        ve_before = _vendor_earnings(VENDOR_ID)
        bank_before = round(float(requests.get(
            f"{API}/admin/finance/net-worth", headers=_hdr(admin_tok), timeout=20,
        ).json()["master"]["components"]["bank_tally_net"]), 2)

        start = requests.post(
            f"{API}/recharge/payment/start",
            json={"kind": "mobile", "product_id": cheap_plan["id"],
                  "account": account, "wallet_amount": wallet_slice},
            headers=_hdr(buyer_tok), timeout=15,
        )
        assert start.status_code == 200, start.text[:200]
        s = start.json()
        CLEANUP["recharge_payment_ids"].append(s["payment_id"])
        assert s["wallet_amount"] == wallet_slice
        assert s["online_amount"] == online_slice
        assert s["amount"] == price

        verify = requests.post(
            f"{API}/recharge/payment/verify",
            json={
                "payment_id": s["payment_id"],
                "razorpay_order_id": s["razorpay_order_id"],
                "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
                "razorpay_signature": "sig_MOCK",
            },
            headers=_hdr(buyer_tok), timeout=20,
        )
        assert verify.status_code == 200, verify.text[:200]
        v = verify.json()
        CLEANUP["recharge_ids"].append(v["recharge_id"])
        CLEANUP["order_ids"].append(v["order_id"])

        # wallet debited by exactly the slice
        wb_after = _wallet_balance(buyer_tok)
        assert round(wb_before - wb_after, 2) == wallet_slice, f"wallet Δ={wb_before - wb_after}"

        # order shape
        order = db.orders.find_one({"id": v["order_id"]}, {"_id": 0})
        assert round(float(order["wallet_paid"]), 2) == wallet_slice
        assert round(float(order["online_paid"]), 2) == online_slice
        assert round(float(order["wallet_paid"]) + float(order["online_paid"]), 2) == price
        assert order["paid_via"] == "wallet_online"

        # bank row equals ONLY the online slice
        bank_row = db.bank_ledger.find_one({"ref_key": f"RCHGPAY:{s['payment_id']}"}, {"_id": 0})
        assert bank_row, "split: bank_ledger row missing"
        assert round(float(bank_row["amount"]), 2) == online_slice

        bank_after = round(float(requests.get(
            f"{API}/admin/finance/net-worth", headers=_hdr(admin_tok), timeout=20,
        ).json()["master"]["components"]["bank_tally_net"]), 2)
        assert round(bank_after - bank_before, 2) == online_slice

        # vendor credited for FULL price
        assert round(_vendor_earnings(VENDOR_ID) - ve_before, 2) == price

        # TWO buyer transactions: wallet leg (type recharge) + online leg (recharge_payment_upi)
        # FIX(3): scope to buyer rows only
        txns = list(db.transactions.find({"order_id": v["order_id"], "user_id": buyer_id}, {"_id": 0}))
        assert len(txns) == 2, f"expected 2 buyer legs, got {len(txns)}: {[t.get('payment_leg') for t in txns]}"
        legs = {t["payment_leg"]: t for t in txns}
        assert "wallet" in legs and "online" in legs
        assert legs["wallet"]["type"] == "recharge"
        assert round(float(legs["wallet"]["amount"]), 2) == -wallet_slice
        assert legs["online"]["type"] == "recharge_payment_upi"
        assert round(float(legs["online"]["amount"]), 2) == -online_slice
        # plus exactly ONE vendor credit row for full price
        vrows = list(db.transactions.find({"order_id": v["order_id"], "user_id": VENDOR_ID}, {"_id": 0}))
        assert len(vrows) == 1, f"expected 1 vendor txn, got {len(vrows)}"
        assert vrows[0].get("type") == "vendor_sale"
        assert vrows[0].get("idempotency_key") == f"VENDORSALE:{v['order_id']}"
        assert round(float(vrows[0]["amount"]), 2) == price

    def test_split_wallet_ge_price_rejected(self, buyer_tok, cheap_plan):
        r = requests.post(
            f"{API}/recharge/payment/start",
            json={"kind": "mobile", "product_id": cheap_plan["id"],
                  "account": "9000000666", "wallet_amount": 19.0},
            headers=_hdr(buyer_tok), timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:200]}"
        msg = (r.json().get("detail") or "").lower()
        assert "wallet" in msg

    def test_split_wallet_over_balance_clamps(self, buyer_tok, cheap_plan):
        wb = _wallet_balance(buyer_tok)
        # Ask for far more than balance: must clamp, never go negative online
        r = requests.post(
            f"{API}/recharge/payment/start",
            json={"kind": "mobile", "product_id": cheap_plan["id"],
                  "account": "9000000777", "wallet_amount": wb + 1_000_000},
            headers=_hdr(buyer_tok), timeout=15,
        )
        # Could 200 with clamped slice OR 400 if wallet now exceeds price.
        # The owner-asked invariant is ONLY "never below 0 online".
        if r.status_code == 200:
            s = r.json()
            CLEANUP["recharge_payment_ids"].append(s["payment_id"])
            assert s["online_amount"] >= 0, s
            assert s["wallet_amount"] <= wb + 0.01
            assert s["wallet_amount"] + s["online_amount"] == s["amount"]
        else:
            assert r.status_code == 400


# ─── Regression ─────────────────────────────────────────────────────────────

class TestRegression:
    def test_recharge_history_still_enriched(self, buyer_tok, online_recharge):
        r = requests.get(f"{API}/recharge/history", headers=_hdr(buyer_tok), timeout=15)
        assert r.status_code == 200
        rows = r.json().get("items") or []
        rid = online_recharge["verify"]["recharge_id"]
        match = [row for row in rows if row.get("id") == rid]
        assert match, f"recharge {rid} missing from history"
        row = match[0]
        for key in ("can_repeat", "current_price", "highlights"):
            assert key in row, f"missing {key} in history row"
        # NEW: order_id/order_number now present
        assert row.get("order_id") == online_recharge["verify"]["order_id"]
        assert row.get("order_number", "").startswith("RC-")

    def test_recharge_products_endpoint_ok(self):
        r = requests.get(
            f"{API}/recharge/products",
            params={"kind": "mobile", "state": "andhra-pradesh-telangana-ap-tg", "network": "airtel"},
            headers=UA, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        # FIX(4): response shape is {count, groups:[{name, products:[...]}]}
        assert isinstance(body, dict), body
        assert isinstance(body.get("count"), int), body
        assert isinstance(body.get("groups"), list), body
        total = 0
        for g in body["groups"]:
            assert "name" in g and isinstance(g.get("products"), list), g
            total += len(g["products"])
        assert total == body["count"], f"count={body['count']} vs products={total}"

    def test_recharge_options_endpoint_ok(self):
        r = requests.get(f"{API}/recharge/options", headers=UA, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "mobile" in body and "dth" in body
