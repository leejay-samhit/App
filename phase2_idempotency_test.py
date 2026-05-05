"""
Phase 2 — Transaction Detail endpoint + Transaction Idempotency safety net tests.

Covers:
  A) GET /api/transactions/{txn_id} — owner / admin / 403 / 404 / counter-party / utr / auto_remarks.
  B) Idempotency: rapid double-click on
        - POST /orders/checkout
        - POST /services/book/{provider_id}
        - POST /payment/verify
        - POST /wallet/transfer
        - POST /admin/system-wallet/deposit
     For each: exactly one tx row of each expected type per id; balances change exactly once;
     parallel duplicate attempt returns 400 / "already paid" / "insufficient".
  C) Smoke test: /admin/system-wallet still works.
"""
import os
import asyncio
import hmac
import hashlib
import secrets
import sys
import json
from typing import Any, Dict, Optional, Tuple, List

import httpx

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
RAZORPAY_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

results: List[Tuple[str, bool, str]] = []
created_user_ids: List[str] = []
created_product_ids: List[str] = []


def record(name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login(email: str, password: str) -> Optional[str]:
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        print(f"login failed: {r.status_code} {r.text}")
        return None
    return r.json().get("token")


def register_user(name: str, email: str, password: str, referral_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    body = {"name": name, "email": email, "password": password}
    if referral_code is not None:
        body["referral_code"] = referral_code
    r = httpx.post(f"{BASE}/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        print(f"register failed: {r.status_code} {r.text}")
        return None
    return r.json()


def auto_approve_user(token: str) -> Optional[Dict[str, Any]]:
    h = auth_headers(token)
    r1 = httpx.post(f"{BASE}/payment/create-order", headers=h, timeout=30)
    if r1.status_code != 200:
        return None
    order_id = r1.json()["order_id"]
    payment_id = f"pay_test_{secrets.token_hex(8)}"
    msg = f"{order_id}|{payment_id}".encode()
    sig = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    r2 = httpx.post(
        f"{BASE}/payment/verify",
        headers=h,
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sig,
        },
        timeout=30,
    )
    if r2.status_code != 200:
        return None
    return r2.json()


def create_throwaway(prefix: str, approve: bool = True, password: str = "Pass@1234") -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    rand = secrets.token_hex(4)
    email = f"{prefix}.{rand}@p2test.io"
    name = f"{prefix.title()} {rand[:4].upper()}"
    reg = register_user(name, email, password)
    if not reg:
        return None, None
    token = reg["token"]
    user = reg["user"]
    if approve:
        apr = auto_approve_user(token)
        if not apr:
            return None, None
        me = httpx.get(f"{BASE}/auth/me", headers=auth_headers(token), timeout=30)
        if me.status_code == 200:
            user = me.json()
    if user and user.get("id"):
        created_user_ids.append(user["id"])
    return token, user


def get_user_via_admin(admin_token: str, uid: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/admin/users", headers=auth_headers(admin_token), timeout=30)
    if r.status_code != 200:
        return None
    for u in r.json():
        if u.get("id") == uid:
            return u
    return None


def admin_credit_user(admin_token: str, uid: str, amount: float, reason: str = "test seed") -> bool:
    r = httpx.post(
        f"{BASE}/admin/users/{uid}/wallet",
        headers=auth_headers(admin_token),
        json={"amount": amount, "type": "credit", "reason": reason},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"admin_credit_user({uid}, {amount}) failed: {r.status_code} {r.text}")
        return False
    return True


def admin_deposit_direct(admin_token: str, amount: float) -> bool:
    """Top up admin's direct_added bucket."""
    utr = f"UTR-P2T-{secrets.token_hex(4)}"
    r = httpx.post(
        f"{BASE}/admin/system-wallet/deposit",
        headers=auth_headers(admin_token),
        json={"amount": amount, "utr": utr, "remarks": "phase2 test deposit"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"admin_deposit_direct({amount}) failed: {r.status_code} {r.text}")
        return False
    return True


def get_my_transactions(token: str) -> List[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(token), timeout=30)
    if r.status_code != 200:
        return []
    return r.json()


def get_admin_transactions_filter(admin_token: str, **filters) -> List[Dict[str, Any]]:
    """GET /admin/transactions/filter with arbitrary query params."""
    r = httpx.get(f"{BASE}/admin/transactions/filter", headers=auth_headers(admin_token), params=filters, timeout=30)
    if r.status_code != 200:
        return []
    j = r.json()
    if isinstance(j, dict):
        return j.get("items") or j.get("transactions") or []
    if isinstance(j, list):
        return j
    return []


def get_admin_transactions(admin_token: str) -> List[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/admin/transactions", headers=auth_headers(admin_token), timeout=30)
    if r.status_code != 200:
        return []
    j = r.json()
    if isinstance(j, dict):
        return j.get("items") or j.get("transactions") or []
    return j or []


# ============================================================
# Test: GET /api/transactions/{txn_id}
# ============================================================
def test_transaction_detail(admin_token: str):
    print("\n--- A) Transaction Detail Endpoint ---")
    # Register two fresh users
    u_a_token, u_a = create_throwaway("alice")
    u_b_token, u_b = create_throwaway("bob")
    if not u_a or not u_b:
        record("A.SETUP create users", False, "register failed")
        return

    # Top up admin's direct_added so we can credit U_a
    admin_deposit_direct(admin_token, 2000)

    # Credit U_a wallet (creates an admin_credit transaction on U_a)
    ok = admin_credit_user(admin_token, u_a["id"], 800, "phase2 credit")
    record("A.SETUP admin_credit U_a 800", ok)
    if not ok:
        return

    # Fetch the admin_credit transaction
    txs_a = get_my_transactions(u_a_token)
    ac_tx = next((t for t in txs_a if t.get("type") == "admin_credit"), None)
    if not ac_tx:
        record("A.SETUP find admin_credit tx", False)
        return
    txn_id = ac_tx["id"]

    # A.1 200 by owner
    r = httpx.get(f"{BASE}/transactions/{txn_id}", headers=auth_headers(u_a_token), timeout=30)
    record("A.1 owner GET 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        # Shape
        keys = set(body.keys())
        expected_keys = {"transaction", "owner", "counter_party", "counter_role", "auto_remarks", "utr"}
        record("A.2 response shape has all keys", expected_keys.issubset(keys), f"missing={expected_keys - keys}")
        # counter_party should be admin
        cp = body.get("counter_party") or {}
        record("A.3 admin_credit counter_role==admin", body.get("counter_role") == "admin", f"got {body.get('counter_role')}")
        record("A.4 counter_party has admin email", (cp.get("email") or "").lower() == ADMIN_EMAIL, f"got {cp.get('email')}")
        record("A.5 counter_party has name", bool(cp.get("name")))
        # utr mirrors reference_number
        rn = (body.get("transaction") or {}).get("reference_number")
        record("A.6 utr == reference_number", body.get("utr") == rn, f"utr={body.get('utr')} ref={rn}")
        # auto_remarks non-empty
        ar = body.get("auto_remarks") or ""
        record("A.7 auto_remarks non-empty", isinstance(ar, str) and len(ar) > 0, f"len={len(ar) if isinstance(ar,str) else 'n/a'}")

    # A.8 403 from a different user
    r403 = httpx.get(f"{BASE}/transactions/{txn_id}", headers=auth_headers(u_b_token), timeout=30)
    record("A.8 other-user GET 403", r403.status_code == 403, f"status={r403.status_code}")

    # A.9 admin can view any txn
    r_admin = httpx.get(f"{BASE}/transactions/{txn_id}", headers=auth_headers(admin_token), timeout=30)
    record("A.9 admin (super_admin) GET 200", r_admin.status_code == 200, f"status={r_admin.status_code}")

    # A.10 404 on missing
    r404 = httpx.get(f"{BASE}/transactions/does-not-exist-{secrets.token_hex(4)}", headers=auth_headers(u_a_token), timeout=30)
    record("A.10 non-existent GET 404", r404.status_code == 404, f"status={r404.status_code}")

    # A.11 service_booking & service_earning detail (build a booking)
    # U_b becomes provider; U_a books.
    # 1) U_b applies as provider
    r_apply = httpx.post(
        f"{BASE}/service/apply",
        headers=auth_headers(u_b_token),
        json={
            "service_name": "Test Service",
            "service_category": "Plumber",
            "pincode": "560001",
            "charge": 200,
            "description": "phase2 test service",
        },
        timeout=30,
    )
    if r_apply.status_code != 200:
        record("A.SETUP U_b service apply", False, f"{r_apply.status_code} {r_apply.text}")
    else:
        aid = r_apply.json().get("application", {}).get("id") or r_apply.json().get("id")
        # admin approve
        r_appr = httpx.post(f"{BASE}/admin/service-applications/{aid}/approve", headers=auth_headers(admin_token), timeout=30)
        record("A.SETUP service apply+approve", r_appr.status_code == 200)

        # U_a books U_b
        r_book = httpx.post(
            f"{BASE}/services/{u_b['id']}/book",
            headers=auth_headers(u_a_token),
            json={"notes": "phase2 booking"},
            timeout=30,
        )
        if r_book.status_code != 200:
            record("A.SETUP booking", False, f"{r_book.status_code} {r_book.text}")
        else:
            booking_id = r_book.json()["booking"]["id"]
            # Get service_booking tx on U_a
            txs_a2 = get_my_transactions(u_a_token)
            sb_tx = next((t for t in txs_a2 if t.get("type") == "service_booking" and t.get("booking_id") == booking_id), None)
            se_tx_provider = None
            txs_b = get_my_transactions(u_b_token)
            se_tx_provider = next((t for t in txs_b if t.get("type") == "service_earning" and t.get("booking_id") == booking_id), None)

            if sb_tx:
                rd = httpx.get(f"{BASE}/transactions/{sb_tx['id']}", headers=auth_headers(u_a_token), timeout=30)
                if rd.status_code == 200:
                    bd = rd.json()
                    record("A.11 service_booking counter_role==provider", bd.get("counter_role") == "provider", f"got {bd.get('counter_role')}")
                    cp = bd.get("counter_party") or {}
                    record("A.12 service_booking counter_party has phone field", "phone" in cp, f"keys={list(cp.keys())}")
                    record("A.13 service_booking counter_party id == provider", cp.get("id") == u_b["id"])
                else:
                    record("A.11 service_booking detail GET", False, f"status={rd.status_code}")
            else:
                record("A.11 find service_booking tx", False)

            if se_tx_provider:
                rd2 = httpx.get(f"{BASE}/transactions/{se_tx_provider['id']}", headers=auth_headers(u_b_token), timeout=30)
                if rd2.status_code == 200:
                    bd = rd2.json()
                    record("A.14 service_earning counter_role==customer", bd.get("counter_role") == "customer", f"got {bd.get('counter_role')}")
                    cp = bd.get("counter_party") or {}
                    record("A.15 service_earning counter_party id == customer", cp.get("id") == u_a["id"])
                else:
                    record("A.14 service_earning detail GET", False, f"status={rd2.status_code}")
            else:
                record("A.14 find service_earning tx", False)


# ============================================================
# Idempotency tests
# ============================================================
async def fire_two_concurrent(method: str, url: str, headers: Dict[str, str], json_body: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> List[httpx.Response]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def _one():
            if method.upper() == "POST":
                return await client.post(url, headers=headers, json=json_body)
            elif method.upper() == "GET":
                return await client.get(url, headers=headers)
            else:
                raise ValueError(method)
        return await asyncio.gather(_one(), _one(), return_exceptions=False)


def test_payment_verify_idempotency():
    print("\n--- B1) /payment/verify idempotency ---")
    token, user = create_throwaway("payver", approve=False)
    if not user:
        record("B1.SETUP user", False)
        return
    # Create order
    r = httpx.post(f"{BASE}/payment/create-order", headers=auth_headers(token), timeout=30)
    if r.status_code != 200:
        record("B1.SETUP create-order", False, f"{r.status_code}: {r.text}")
        return
    order_id = r.json()["order_id"]
    payment_id = f"pay_test_{secrets.token_hex(8)}"
    sig = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    body = {"razorpay_order_id": order_id, "razorpay_payment_id": payment_id, "razorpay_signature": sig}

    responses = asyncio.run(fire_two_concurrent("POST", f"{BASE}/payment/verify", auth_headers(token), body))
    statuses = sorted([r.status_code for r in responses])
    record("B1.1 one 200 + one 4xx", statuses[0] == 200 and statuses[1] in (400, 401), f"statuses={statuses}")
    # Already-paid message check
    if statuses[0] == 200 and statuses[1] == 400:
        bodies = [r.json() for r in responses]
        bad = next((b for b in bodies if "already paid" in str(b).lower()), None)
        record("B1.2 second response 'already paid'", bad is not None, f"detail={bad}")

    # Verify only ONE registration_fee tx exists
    txs = get_my_transactions(token)
    rf = [t for t in txs if t.get("razorpay_payment_id") == payment_id and t.get("type") == "registration_fee"]
    record("B1.3 exactly one registration_fee tx", len(rf) == 1, f"count={len(rf)}")
    # Verify registration_paid is True
    me = httpx.get(f"{BASE}/auth/me", headers=auth_headers(token), timeout=30)
    if me.status_code == 200:
        u = me.json()
        record("B1.4 registration_paid==True", bool(u.get("registration_paid")), f"got {u.get('registration_paid')}")


def test_wallet_transfer_idempotency(admin_token: str):
    print("\n--- B2) /wallet/transfer idempotency ---")
    a_token, a_user = create_throwaway("trfA")
    b_token, b_user = create_throwaway("trfB")
    if not a_user or not b_user:
        record("B2.SETUP users", False)
        return
    # Top up admin direct_added then credit user A with EXACTLY 100
    admin_deposit_direct(admin_token, 500)
    if not admin_credit_user(admin_token, a_user["id"], 100, "trf seed"):
        record("B2.SETUP credit A", False)
        return

    # Confirm balances
    a_doc = get_user_via_admin(admin_token, a_user["id"])
    b_doc = get_user_via_admin(admin_token, b_user["id"])
    a_bal_before = float(a_doc.get("wallet_balance") or 0)
    b_bal_before = float(b_doc.get("wallet_balance") or 0)
    record("B2.SETUP A balance 100", abs(a_bal_before - 100) < 0.01, f"a_bal={a_bal_before}")

    body = {"recipient": b_user["email"], "amount": 100, "note": "concurrent test"}
    responses = asyncio.run(fire_two_concurrent("POST", f"{BASE}/wallet/transfer", auth_headers(a_token), body))
    statuses = sorted([r.status_code for r in responses])
    record("B2.1 one 200 + one 400", statuses == [200, 400], f"statuses={statuses}")

    # Check balances
    a_doc2 = get_user_via_admin(admin_token, a_user["id"])
    b_doc2 = get_user_via_admin(admin_token, b_user["id"])
    a_bal2 = float(a_doc2.get("wallet_balance") or 0)
    b_bal2 = float(b_doc2.get("wallet_balance") or 0)
    record("B2.2 A balance == 0 (one debit)", abs(a_bal2 - 0) < 0.01, f"a_bal={a_bal2}")
    record("B2.3 B balance == before+100 (one credit)", abs(b_bal2 - (b_bal_before + 100)) < 0.01, f"b_bal={b_bal2} expected={b_bal_before + 100}")

    # Check transactions count
    txs_a = get_my_transactions(a_token)
    out_txs = [t for t in txs_a if t.get("type") == "transfer_out"]
    txs_b = get_my_transactions(b_token)
    in_txs = [t for t in txs_b if t.get("type") == "transfer_in"]
    record("B2.4 exactly one transfer_out tx", len(out_txs) == 1, f"count={len(out_txs)}")
    record("B2.5 exactly one transfer_in tx", len(in_txs) == 1, f"count={len(in_txs)}")


def test_checkout_idempotency(admin_token: str):
    print("\n--- B3) /orders/checkout idempotency ---")
    # Create a non-vendor product priced at 100
    r = httpx.post(
        f"{BASE}/admin/products",
        headers=auth_headers(admin_token),
        json={
            "name": f"P2 Test Product {secrets.token_hex(3)}",
            "description": "phase2",
            "price": 100,
            "image_url": "https://via.placeholder.com/100",
            "stock": 1000,
        },
        timeout=30,
    )
    if r.status_code != 200:
        record("B3.SETUP create product", False, f"{r.status_code}: {r.text}")
        return
    pdata = r.json()
    pid = pdata.get("id") or pdata.get("product", {}).get("id")
    if not pid:
        record("B3.SETUP get product id", False, f"resp={pdata}")
        return
    created_product_ids.append(pid)

    # Buyer with EXACTLY ₹100 wallet
    token, user = create_throwaway("buyer")
    if not user:
        record("B3.SETUP buyer", False)
        return
    admin_deposit_direct(admin_token, 500)
    if not admin_credit_user(admin_token, user["id"], 100, "checkout seed"):
        record("B3.SETUP credit buyer", False)
        return
    # Add to cart
    r_add = httpx.post(f"{BASE}/cart/add", headers=auth_headers(token), json={"product_id": pid, "qty": 1}, timeout=30)
    record("B3.SETUP cart/add", r_add.status_code == 200, f"{r_add.status_code}")

    # Snapshot balances
    buyer_before = get_user_via_admin(admin_token, user["id"])
    bal_before = float(buyer_before.get("wallet_balance") or 0)

    # Concurrent checkout
    responses = asyncio.run(fire_two_concurrent("POST", f"{BASE}/orders/checkout", auth_headers(token), None))
    statuses = sorted([r.status_code for r in responses])
    record("B3.1 one 200 + one 400", statuses == [200, 400], f"statuses={statuses}")

    # Wallet should be 0 — not -100
    buyer_after = get_user_via_admin(admin_token, user["id"])
    bal_after = float(buyer_after.get("wallet_balance") or 0)
    record("B3.2 buyer wallet == 0 (one debit, no double)", abs(bal_after - 0) < 0.01, f"bal={bal_after}")

    # Find the order_id from the 200 response
    ok_resp = next((r for r in responses if r.status_code == 200), None)
    if ok_resp:
        order_id = ok_resp.json().get("id")
        record("B3.3 order_id returned", bool(order_id), f"order_id={order_id}")
        # Exactly one 'order' tx for this order_id on buyer
        txs = get_my_transactions(token)
        order_txs = [t for t in txs if t.get("type") == "order" and t.get("order_id") == order_id]
        record("B3.4 exactly one 'order' tx", len(order_txs) == 1, f"count={len(order_txs)}")
        # Exactly one shop_commission tx on admin for this order
        admin_txs = get_admin_transactions_filter(admin_token, type="shop_commission")
        sc_txs = [t for t in admin_txs if t.get("order_id") == order_id]
        record("B3.5 exactly one shop_commission tx for order", len(sc_txs) == 1, f"count={len(sc_txs)}")


def test_service_booking_idempotency(admin_token: str):
    print("\n--- B4) /services/{provider_id}/book idempotency ---")
    # Provider applies + approved
    p_token, p_user = create_throwaway("provR")
    c_token, c_user = create_throwaway("custR")
    if not p_user or not c_user:
        record("B4.SETUP users", False)
        return
    r_apply = httpx.post(
        f"{BASE}/service/apply",
        headers=auth_headers(p_token),
        json={
            "service_name": "Idempot Service",
            "service_category": "Plumber",
            "pincode": "560002",
            "charge": 100,
            "description": "idempotency test",
        },
        timeout=30,
    )
    if r_apply.status_code != 200:
        record("B4.SETUP apply", False, f"{r_apply.status_code}: {r_apply.text}")
        return
    aid = r_apply.json().get("application", {}).get("id") or r_apply.json().get("id")
    r_appr = httpx.post(f"{BASE}/admin/service-applications/{aid}/approve", headers=auth_headers(admin_token), timeout=30)
    record("B4.SETUP approve", r_appr.status_code == 200, f"{r_appr.status_code}")
    if r_appr.status_code != 200:
        return

    # Customer wallet exactly 100
    admin_deposit_direct(admin_token, 500)
    if not admin_credit_user(admin_token, c_user["id"], 100, "book seed"):
        record("B4.SETUP credit customer", False)
        return
    p_doc_before = get_user_via_admin(admin_token, p_user["id"])
    p_bal_before = float(p_doc_before.get("wallet_balance") or 0)

    # Concurrent book
    body = {"notes": "concurrent book"}
    responses = asyncio.run(fire_two_concurrent("POST", f"{BASE}/services/{p_user['id']}/book", auth_headers(c_token), body))
    statuses = sorted([r.status_code for r in responses])
    record("B4.1 one 200 + one 400", statuses == [200, 400], f"statuses={statuses}")

    # Customer balance 0
    c_doc_after = get_user_via_admin(admin_token, c_user["id"])
    c_bal_after = float(c_doc_after.get("wallet_balance") or 0)
    record("B4.2 customer wallet == 0", abs(c_bal_after - 0) < 0.01, f"bal={c_bal_after}")
    # Provider balance increased exactly by 70
    p_doc_after = get_user_via_admin(admin_token, p_user["id"])
    p_bal_after = float(p_doc_after.get("wallet_balance") or 0)
    record("B4.3 provider wallet += 70 only", abs(p_bal_after - (p_bal_before + 70)) < 0.01, f"before={p_bal_before} after={p_bal_after}")

    # Find booking id
    ok_resp = next((r for r in responses if r.status_code == 200), None)
    if ok_resp:
        booking_id = ok_resp.json()["booking"]["id"]
        # exactly one service_booking on customer
        txs_c = get_my_transactions(c_token)
        sb = [t for t in txs_c if t.get("type") == "service_booking" and t.get("booking_id") == booking_id]
        record("B4.4 exactly one service_booking tx", len(sb) == 1, f"count={len(sb)}")
        # exactly one service_earning on provider
        txs_p = get_my_transactions(p_token)
        se = [t for t in txs_p if t.get("type") == "service_earning" and t.get("booking_id") == booking_id]
        record("B4.5 exactly one service_earning tx", len(se) == 1, f"count={len(se)}")
        # exactly one service_commission on admin (filter by booking_id)
        adm_txs = get_admin_transactions_filter(admin_token, type="service_commission")
        sc = [t for t in adm_txs if t.get("booking_id") == booking_id]
        record("B4.6 exactly one service_commission tx", len(sc) == 1, f"count={len(sc)}")


def test_system_wallet_deposit_idempotency(admin_token: str):
    print("\n--- B5) /admin/system-wallet/deposit idempotency (same UTR) ---")
    utr = f"UTR-IDEM-{secrets.token_hex(4)}"
    body = {"amount": 250, "utr": utr, "remarks": "idempotency test"}

    # Snapshot direct_added bucket
    r_pre = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(admin_token), timeout=30)
    if r_pre.status_code != 200:
        record("B5.SETUP system-wallet GET", False)
        return
    direct_before = float(r_pre.json()["buckets"].get("direct_added") or 0)

    responses = asyncio.run(fire_two_concurrent("POST", f"{BASE}/admin/system-wallet/deposit", auth_headers(admin_token), body))
    statuses = sorted([r.status_code for r in responses])
    record("B5.1 one 200 + one 400 (UTR-dup)", statuses == [200, 400], f"statuses={statuses}")

    # direct_added bucket increased by exactly 250
    r_post = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(admin_token), timeout=30)
    if r_post.status_code == 200:
        direct_after = float(r_post.json()["buckets"].get("direct_added") or 0)
        record("B5.2 direct_added += 250 (one deposit)", abs((direct_after - direct_before) - 250) < 0.01, f"delta={direct_after - direct_before}")

        # Only one deposit row for this UTR
        deposits = r_post.json().get("deposits") or []
        dep_match = [d for d in deposits if d.get("utr") == utr]
        record("B5.3 exactly one deposit row for UTR", len(dep_match) == 1, f"count={len(dep_match)}")


def smoke_test_system_wallet(admin_token: str):
    print("\n--- C) Smoke: /admin/system-wallet still works ---")
    r = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(admin_token), timeout=30)
    record("C.1 GET /admin/system-wallet 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return
    body = r.json()
    record("C.2 has 4 buckets", set(body.get("buckets", {}).keys()) == {"referral_commission", "direct_added", "service_margin", "shopping_margin"}, f"got {list(body.get('buckets', {}).keys())}")
    total = float(body.get("total") or 0)
    sum_buckets = sum(float(v or 0) for v in (body.get("buckets") or {}).values())
    record("C.3 total == sum(buckets)", abs(total - sum_buckets) < 0.01, f"total={total} sum={sum_buckets}")
    # deposit a fresh UTR + check it's recorded
    utr = f"UTR-SMOKE-{secrets.token_hex(3)}"
    rd = httpx.post(f"{BASE}/admin/system-wallet/deposit", headers=auth_headers(admin_token), json={"amount": 50, "utr": utr}, timeout=30)
    record("C.4 fresh UTR deposit 200", rd.status_code == 200, f"status={rd.status_code}")
    # Re-deposit same UTR sequentially → 400
    rd2 = httpx.post(f"{BASE}/admin/system-wallet/deposit", headers=auth_headers(admin_token), json={"amount": 50, "utr": utr}, timeout=30)
    record("C.5 re-deposit same UTR 400", rd2.status_code == 400, f"status={rd2.status_code}")


def cleanup(admin_token: str):
    print("\n--- Cleanup ---")
    deleted = 0
    for uid in created_user_ids:
        r = httpx.delete(f"{BASE}/admin/users/{uid}", headers=auth_headers(admin_token), timeout=30)
        if r.status_code == 200:
            deleted += 1
    record(f"CLEAN users {deleted}/{len(created_user_ids)}", deleted == len(created_user_ids))

    pdel = 0
    for pid in created_product_ids:
        r = httpx.delete(f"{BASE}/admin/products/{pid}", headers=auth_headers(admin_token), timeout=30)
        if r.status_code == 200:
            pdel += 1
    record(f"CLEAN products {pdel}/{len(created_product_ids)}", pdel == len(created_product_ids))


def main():
    print(f"\n=== Phase 2 Test (Transaction Detail + Idempotency) === BASE={BASE}\n")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        print("FATAL: cannot login admin")
        sys.exit(2)
    print("Admin login OK")

    smoke_test_system_wallet(admin_token)
    test_transaction_detail(admin_token)
    test_payment_verify_idempotency()
    test_wallet_transfer_idempotency(admin_token)
    test_checkout_idempotency(admin_token)
    test_service_booking_idempotency(admin_token)
    test_system_wallet_deposit_idempotency(admin_token)

    cleanup(admin_token)

    print("\n=== SUMMARY ===")
    p = sum(1 for _, ok, _ in results if ok)
    f = len(results) - p
    print(f"PASS: {p}  FAIL: {f}  TOTAL: {len(results)}")
    if f:
        print("\nFAILURES:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}{(': ' + detail) if detail else ''}")
    sys.exit(0 if f == 0 else 1)


if __name__ == "__main__":
    main()
