"""
Ledger Drift Fix Regression Tests (2026-05-19)
Scenarios: A (cleanup idempotency), B (fee residual), C (order cancel reverse),
           D (COD commission deferred), E (drift snapshot), F (no regression)
Runner: python /app/backend_test.py
"""
import os
import sys
import time
import uuid
import json
import requests
from typing import Optional, Dict, Any, List

# ---- Config ----
FRONTEND_ENV_PATH = "/app/frontend/.env"
BASE_URL = None
for line in open(FRONTEND_ENV_PATH).read().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().strip('"') + "/api"
if not BASE_URL:
    BASE_URL = "https://vendor-network-app-1.preview.emergentagent.com/api"
print(f"BASE_URL: {BASE_URL}")

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
TESTUSER_EMAIL = "testuser@app.com"
TESTUSER_PASSWORD = "Test@123"
FINANCE_EMAIL = "finance@app.com"
FINANCE_PASSWORD = "Finance@123"

PASSES: List[str] = []
FAILURES: List[str] = []


def _record(name: str, ok: bool, detail: str = ""):
    bar = "PASS" if ok else "FAIL"
    line = f"[{bar}] {name}" + (f"  --  {detail}" if detail else "")
    print(line)
    (PASSES if ok else FAILURES).append(line)


def _req(method: str, path: str, *, token: Optional[str] = None, json_body: Any = None,
         params: Any = None, expect: Optional[int] = None) -> requests.Response:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}{path}"
    r = requests.request(method, url, headers=headers, json=json_body, params=params, timeout=120)
    return r


def login(email: str, password: str) -> Optional[Dict[str, Any]]:
    r = _req("POST", "/auth/login", json_body={"email": email, "password": password})
    if r.status_code != 200:
        return None
    return r.json()


# ---------- shared state ----------
admin_login = login(ADMIN_EMAIL, ADMIN_PASSWORD)
if not admin_login:
    print("CRITICAL: admin login failed")
    sys.exit(2)
ADMIN_TOK = admin_login["token"]
ADMIN_ID = admin_login["user"]["id"]
print(f"Admin id: {ADMIN_ID}")


# ============================================================
# SCENARIO A — Cleanup endpoint idempotency & auth gating
# ============================================================
def scenario_A():
    print("\n=== SCENARIO A: cleanup-legacy-refunds idempotency & auth ===")
    # A.1 — anonymous → 401
    r = _req("POST", "/admin/system-wallet/cleanup-legacy-refunds")
    _record("A.1 anon → 401/403", r.status_code in (401, 403),
            f"got {r.status_code}: {r.text[:120]}")

    # A.2 — regular user → 403
    # Use existing testuser if available, else register fresh
    user_tok = None
    tul = login(TESTUSER_EMAIL, TESTUSER_PASSWORD)
    if tul:
        user_tok = tul["token"]
    else:
        # register a fresh customer
        uniq = uuid.uuid4().hex[:8]
        reg = _req("POST", "/auth/register", json_body={
            "name": f"ScenA User {uniq}",
            "email": f"scen_a_{uniq}@test.app",
            "password": "Pass@123",
            "phone": f"99{uniq[:8]}",
        })
        if reg.status_code == 200:
            user_tok = reg.json().get("token")
    if user_tok:
        r = _req("POST", "/admin/system-wallet/cleanup-legacy-refunds", token=user_tok)
        _record("A.2 regular user → 403", r.status_code == 403,
                f"got {r.status_code}: {r.text[:120]}")
    else:
        _record("A.2 regular user → 403", False, "could not get a user token")

    # A.3 — admin call #1
    r1 = _req("POST", "/admin/system-wallet/cleanup-legacy-refunds", token=ADMIN_TOK)
    if r1.status_code != 200:
        _record("A.3 admin call#1 200", False, f"got {r1.status_code}: {r1.text[:200]}")
        return
    body1 = r1.json()
    op1 = body1.get("orders_processed")
    fr1 = body1.get("fee_residuals_backfilled")
    _record("A.3 admin call#1 → 200", True,
            f"orders_processed={op1} fee_residuals_backfilled={fr1}")

    # A.4 — admin call #2 (idempotent)
    r2 = _req("POST", "/admin/system-wallet/cleanup-legacy-refunds", token=ADMIN_TOK)
    if r2.status_code != 200:
        _record("A.4 admin call#2 200", False, f"got {r2.status_code}")
        return
    body2 = r2.json()
    op2 = body2.get("orders_processed")
    fr2 = body2.get("fee_residuals_backfilled")
    ok = (op2 == 0 and fr2 == 0)
    _record("A.4 idempotent (op=0, fr=0)", ok,
            f"second call: orders_processed={op2} fee_residuals_backfilled={fr2}")


# ============================================================
# SCENARIO B — Fee residual safety net for with-ref signup
# ============================================================
def scenario_B():
    print("\n=== SCENARIO B: fee residual safety net ===")
    # Find a referrer with non_admin user — try testuser, else use AARAV01 (Aarav)
    referrer_code = None
    referrer_id = None
    # Find via /admin/users
    r = _req("GET", "/admin/users", token=ADMIN_TOK)
    if r.status_code == 200:
        users = r.json()
        # Prefer testuser if present
        for u in users:
            if (u.get("email") or "").lower() == TESTUSER_EMAIL:
                referrer_code = u.get("referral_code")
                referrer_id = u.get("id")
                break
        if not referrer_code:
            # fallback to AARAV01
            for u in users:
                if (u.get("referral_code") or "").upper() == "AARAV01":
                    referrer_code = u.get("referral_code")
                    referrer_id = u.get("id")
                    break
    if not referrer_code:
        _record("B.pre find referrer", False, "no referrer found")
        return
    print(f"  Using referrer: code={referrer_code} id={referrer_id}")

    # B.1 Register fresh user
    uniq = uuid.uuid4().hex[:8]
    new_email = f"scen_b_{uniq}@test.app"
    reg = _req("POST", "/auth/register", json_body={
        "name": f"ScenB Joiner {uniq}",
        "email": new_email,
        "password": "Pass@123",
        "phone": f"77{uniq[:8]}",
        "referral_code": referrer_code,
    })
    if reg.status_code != 200:
        _record("B.1 register w/ referral", False, f"{reg.status_code}: {reg.text[:200]}")
        return
    new_token = reg.json().get("token")
    new_user_id = reg.json().get("user", {}).get("id")
    _record("B.1 register with referral", True, f"id={new_user_id}")

    # B.2 Pay fee
    p = _req("POST", "/payment/register-fee", token=new_token)
    if p.status_code != 200:
        _record("B.2 pay registration fee", False, f"{p.status_code}: {p.text[:200]}")
        return
    _record("B.2 pay registration fee", True, "ok")

    # B.3 Admin approve
    a = _req("POST", f"/admin/approvals/{new_user_id}/approve", token=ADMIN_TOK)
    if a.status_code != 200:
        _record("B.3 admin approve", False, f"{a.status_code}: {a.text[:200]}")
        return
    _record("B.3 admin approve", True, "ok")

    # B.4 Check direct_signup_credit txn with related_signup_id and "Fee residual" desc
    time.sleep(1)
    # Use admin/transactions filter to find direct_signup_credit txns
    r = _req("GET", "/admin/transactions", token=ADMIN_TOK,
             params={"type": "direct_signup_credit"})
    found_residual = None
    if r.status_code == 200:
        rows = r.json() if isinstance(r.json(), list) else (r.json().get("items") or [])
        for tx in rows:
            if tx.get("related_signup_id") == new_user_id:
                desc = tx.get("description") or ""
                if "Fee residual" in desc or "residual" in desc.lower():
                    found_residual = tx
                    break
    if found_residual:
        _record("B.4 direct_signup_credit (fee residual) txn written", True,
                f"amount=₹{found_residual.get('amount')} desc='{found_residual.get('description')[:80]}'")
    else:
        # Maybe cascade fully consumed the fee (no residual). That's also acceptable per spec
        # ("when ... total LESS than the registration fee"). Confirm via breakdown.
        _record("B.4 direct_signup_credit (fee residual) txn written",
                False,
                "No fee-residual txn for this signup; could be cascade fully consumed (acceptable only if cascade==fee)")

    # B.5 Breakdown inflow.total should equal sum(reg_fee txns) + utr_deposits + service/shop_margin
    bk = _req("GET", "/admin/system-wallet/breakdown", token=ADMIN_TOK)
    if bk.status_code == 200:
        body = bk.json()
        inflow = body.get("inflow", {})
        reg_fee_total = inflow.get("registration_fee_total")
        utr = inflow.get("utr_deposits", 0)
        svc = inflow.get("service_margin", 0)
        shp = inflow.get("shop_margin", 0)
        total = inflow.get("total", 0)
        expected = round((reg_fee_total or 0) + (utr or 0) + (svc or 0) + (shp or 0), 2)
        ok = abs((total or 0) - expected) < 0.5
        _record("B.5 inflow.total == reg_fee + utr + svc + shop", ok,
                f"reg_fee={reg_fee_total} utr={utr} svc={svc} shop={shp} total={total} expected={expected}")

        # Also: reg_fee_total should NOT equal user_count × fee for paid users
        users_resp = _req("GET", "/admin/users", token=ADMIN_TOK)
        if users_resp.status_code == 200:
            paid_count = sum(1 for u in users_resp.json()
                             if u.get("registration_paid") and u.get("role") == "user")
            fee = body.get("settings", {}).get("registration_fee") or 118
            naive = paid_count * fee
            # We expect reg_fee_total <= naive (because some seeded users have no txn)
            ok2 = (reg_fee_total or 0) <= naive + 1
            _record("B.5b reg_fee_total <= paid_users × fee (i.e. uses actual txn sum)", ok2,
                    f"actual_txn_sum={reg_fee_total}, naive={naive}, paid_users={paid_count}")
    else:
        _record("B.5 breakdown call", False, f"{bk.status_code}")

    # Store new_user_id for cleanup later
    return new_user_id


# ============================================================
# SCENARIO C — Order cancellation reverses commission + vendor
# ============================================================
def scenario_C():
    print("\n=== SCENARIO C: wallet order cancellation ledger reversal ===")
    # find a wallet-payable user with sufficient balance; if not, top up via admin
    # Use admin's wallet to fund a buyer
    # First find/register a buyer
    uniq = uuid.uuid4().hex[:8]
    buyer_email = f"scen_c_buyer_{uniq}@test.app"
    reg = _req("POST", "/auth/register", json_body={
        "name": f"ScenC Buyer {uniq}",
        "email": buyer_email,
        "password": "Pass@123",
        "phone": f"71{uniq[:8]}",
    })
    if reg.status_code != 200:
        _record("C.1 register buyer", False, f"{reg.status_code}: {reg.text[:200]}")
        return
    buyer_tok = reg.json()["token"]
    buyer_id = reg.json()["user"]["id"]
    _record("C.1 register buyer", True, f"id={buyer_id}")

    # Pay fee + approve so they can use full features
    _req("POST", "/payment/register-fee", token=buyer_tok)
    _req("POST", f"/admin/approvals/{buyer_id}/approve", token=ADMIN_TOK)

    # Top up wallet via admin (direct_added must have funds — use system deposit first)
    # Easier: use Mongo via direct admin endpoint? Use admin POST /admin/users/{id}/wallet
    # That requires direct_added funds. Alternative: system deposit
    # Make a system deposit then admin credit user wallet
    dep_utr = f"TESTUTR-C-{uniq}"
    dep = _req("POST", "/admin/system-wallet/deposit", token=ADMIN_TOK,
               json_body={"amount": 5000, "utr": dep_utr, "note": "scenario C top-up"})
    if dep.status_code != 200:
        # finance may be needed; try finance
        fl = login(FINANCE_EMAIL, FINANCE_PASSWORD)
        if fl:
            dep = _req("POST", "/admin/system-wallet/deposit", token=fl["token"],
                       json_body={"amount": 5000, "utr": dep_utr, "note": "scenario C top-up"})
    print(f"  deposit {dep.status_code}: {dep.text[:150]}")

    # Credit buyer wallet
    cred = _req("POST", f"/admin/users/{buyer_id}/wallet", token=ADMIN_TOK,
                json_body={"amount": 3000, "type": "credit",
                           "reason": "scenario C funding for ledger test"})
    print(f"  buyer wallet credit {cred.status_code}: {cred.text[:200]}")

    # Get first available product
    p = _req("GET", "/products")
    products = p.json() if isinstance(p.json(), list) else p.json().get("items", [])
    # pick a low-priced in-stock product
    pick = None
    for prod in products:
        price = float(prod.get("price") or 0)
        stock = int(prod.get("stock") or 0)
        if 0 < price <= 500 and stock > 0:
            pick = prod
            break
    if not pick and products:
        # any with stock
        for prod in products:
            if int(prod.get("stock") or 0) > 0:
                pick = prod
                break
    if not pick:
        _record("C.pre find product", False, "no in-stock product")
        return
    prod_id = pick["id"]
    prod_price = float(pick["price"])
    print(f"  Picked product: {pick.get('name')} ₹{prod_price}")

    # Add to cart
    ac = _req("POST", "/cart/add", token=buyer_tok,
              json_body={"product_id": prod_id, "qty": 1})
    if ac.status_code != 200:
        _record("C.2 add to cart", False, f"{ac.status_code}: {ac.text[:200]}")
        return
    _record("C.2 add to cart", True, "")

    # Checkout (wallet)
    co = _req("POST", "/orders/checkout", token=buyer_tok,
              json_body={"payment_method": "wallet",
                         "shipping_address": {
                             "name": "Test Buyer", "phone": "9999900000",
                             "line1": "12 Test Lane", "line2": "",
                             "city": "Hyderabad", "state": "Telangana",
                             "pincode": "500001",
                         }})
    if co.status_code != 200:
        _record("C.3 checkout wallet", False, f"{co.status_code}: {co.text[:300]}")
        return
    order = co.json()
    order_id = order.get("id")
    has_vendor_items = any(it.get("vendor_id") for it in order.get("items", []))
    _record("C.3 checkout wallet", True, f"order_id={order_id} has_vendor={has_vendor_items}")

    # Capture buyer wallet pre-cancel
    me = _req("GET", "/auth/me", token=buyer_tok).json()
    bal_before_cancel = float(me.get("wallet_balance") or 0)

    # Capture admin shopping_margin bucket pre-cancel
    sw1 = _req("GET", "/admin/system-wallet", token=ADMIN_TOK).json()
    shop_margin_before = float(((sw1.get("buckets") or {}).get("shopping_margin") or 0))

    # Cancel
    pa = _req("PATCH", f"/admin/orders/{order_id}/status", token=ADMIN_TOK,
              json_body={"status": "cancelled"})
    if pa.status_code != 200:
        _record("C.4 cancel order", False, f"{pa.status_code}: {pa.text[:200]}")
        return
    _record("C.4 cancel order", True, "")

    # Verify wallet refunded
    me2 = _req("GET", "/auth/me", token=buyer_tok).json()
    bal_after_cancel = float(me2.get("wallet_balance") or 0)
    refunded = round(bal_after_cancel - bal_before_cancel, 2)
    _record("C.5 buyer wallet refunded", abs(refunded - order["total"]) < 0.01,
            f"delta=₹{refunded} expected=₹{order['total']}")

    # Look for txns: refund, shop_commission_reversal, vendor_sale_reversal
    txs = _req("GET", "/admin/transactions", token=ADMIN_TOK,
               params={"limit": 500}).json()
    txs_list = txs if isinstance(txs, list) else txs.get("items", [])
    has_refund = any(t.get("type") == "refund" and t.get("order_id") == order_id for t in txs_list)
    has_shop_rev = any(t.get("type") == "shop_commission_reversal"
                       and t.get("order_id") == order_id
                       and float(t.get("amount") or 0) < 0 for t in txs_list)
    has_vendor_rev = any(t.get("type") == "vendor_sale_reversal"
                         and t.get("order_id") == order_id
                         and float(t.get("amount") or 0) < 0 for t in txs_list)
    _record("C.6 refund txn with order_id present", has_refund, "")
    # shop_commission_reversal should exist only if there was a platform_share
    platform_share_total = sum(float(it.get("platform_share") or 0) for it in order.get("items", []))
    if platform_share_total > 0:
        _record("C.7 shop_commission_reversal (amount<0) present", has_shop_rev,
                f"platform_share_total=₹{platform_share_total}")
    else:
        _record("C.7 shop_commission_reversal (skipped — no platform_share)", True, "")
    if has_vendor_items:
        _record("C.8 vendor_sale_reversal (amount<0) present", has_vendor_rev, "")
    else:
        _record("C.8 vendor_sale_reversal (n/a — no vendor items)", True, "")

    # Admin shopping_margin bucket DECREASED (or stayed 0)
    sw2 = _req("GET", "/admin/system-wallet", token=ADMIN_TOK).json()
    shop_margin_after = float(((sw2.get("buckets") or {}).get("shopping_margin") or 0))
    delta_margin = round(shop_margin_after - shop_margin_before, 2)
    ok = (delta_margin <= 0.0)
    _record("C.9 admin shopping_margin DECREASED (or stayed)", ok,
            f"before=₹{shop_margin_before} after=₹{shop_margin_after} delta=₹{delta_margin}")


# ============================================================
# SCENARIO D — COD commission deferred
# ============================================================
def scenario_D():
    print("\n=== SCENARIO D: COD commission deferred until delivery ===")
    # register a buyer
    uniq = uuid.uuid4().hex[:8]
    reg = _req("POST", "/auth/register", json_body={
        "name": f"ScenD COD Buyer {uniq}",
        "email": f"scen_d_buyer_{uniq}@test.app",
        "password": "Pass@123",
        "phone": f"72{uniq[:8]}",
    })
    if reg.status_code != 200:
        _record("D.1 register buyer", False, f"{reg.status_code}")
        return
    buyer_tok = reg.json()["token"]
    buyer_id = reg.json()["user"]["id"]
    _req("POST", "/payment/register-fee", token=buyer_tok)
    _req("POST", f"/admin/approvals/{buyer_id}/approve", token=ADMIN_TOK)

    # pick product
    p = _req("GET", "/products")
    products = p.json() if isinstance(p.json(), list) else p.json().get("items", [])
    pick = None
    for prod in products:
        if int(prod.get("stock") or 0) > 0 and float(prod.get("price") or 0) > 0:
            pick = prod
            break
    if not pick:
        _record("D.pre find product", False, "no in-stock product")
        return
    prod_id = pick["id"]
    print(f"  Picked product: {pick.get('name')} ₹{pick.get('price')}")

    ac = _req("POST", "/cart/add", token=buyer_tok,
              json_body={"product_id": prod_id, "qty": 1})
    if ac.status_code != 200:
        _record("D.2 add to cart", False, f"{ac.status_code}: {ac.text[:200]}")
        return

    # COD checkout
    co = _req("POST", "/orders/checkout", token=buyer_tok,
              json_body={"payment_method": "cod",
                         "shipping_address": {
                             "name": "COD Buyer", "phone": "9999800000",
                             "line1": "44 COD St", "line2": "",
                             "city": "Hyderabad", "state": "Telangana",
                             "pincode": "500004",
                         }})
    if co.status_code != 200:
        _record("D.3 COD checkout", False, f"{co.status_code}: {co.text[:300]}")
        return
    order = co.json()
    order_id = order.get("id")
    _record("D.3 COD checkout", True, f"order_id={order_id} paid_via={order.get('paid_via')}")

    # Verify NO shop_commission txn at placement
    time.sleep(0.5)
    txs = _req("GET", "/admin/transactions", token=ADMIN_TOK,
               params={"limit": 500}).json()
    txs_list = txs if isinstance(txs, list) else txs.get("items", [])
    shop_at_placement = [t for t in txs_list
                         if t.get("type") == "shop_commission"
                         and t.get("order_id") == order_id]
    _record("D.4 NO shop_commission at COD placement", len(shop_at_placement) == 0,
            f"found={len(shop_at_placement)}")

    # PATCH to delivered
    pa = _req("PATCH", f"/admin/orders/{order_id}/status", token=ADMIN_TOK,
              json_body={"status": "delivered"})
    if pa.status_code != 200:
        _record("D.5 PATCH delivered", False, f"{pa.status_code}: {pa.text[:200]}")
        return
    _record("D.5 PATCH delivered", True, "")

    # Now verify shop_commission txn IS written and description mentions "COD" + "settled on delivery"
    time.sleep(0.5)
    txs = _req("GET", "/admin/transactions", token=ADMIN_TOK,
               params={"limit": 500}).json()
    txs_list = txs if isinstance(txs, list) else txs.get("items", [])
    shop_at_delivery = [t for t in txs_list
                        if t.get("type") == "shop_commission"
                        and t.get("order_id") == order_id]
    platform_share_total = sum(float(it.get("platform_share") or 0)
                               for it in order.get("items", []))
    if platform_share_total > 0:
        if len(shop_at_delivery) >= 1:
            desc = shop_at_delivery[0].get("description") or ""
            has_keywords = ("COD" in desc.upper() or "cod" in desc) and "settled" in desc.lower() and "delivery" in desc.lower()
            _record("D.6 shop_commission written on delivery", True,
                    f"amount=₹{shop_at_delivery[0].get('amount')} desc='{desc[:100]}'")
            _record("D.7 description mentions 'COD ... settled on delivery'", has_keywords, f"desc='{desc[:100]}'")
        else:
            _record("D.6 shop_commission written on delivery", False,
                    f"NO shop_commission found; platform_share_total=₹{platform_share_total}")
    else:
        _record("D.6 shop_commission (n/a — platform_share=0)", True, "")


# ============================================================
# SCENARIO E — Drift snapshot stays at 0
# ============================================================
def scenario_E():
    print("\n=== SCENARIO E: ledger-alerts drift snapshot ===")
    r = _req("GET", "/admin/ledger-alerts", token=ADMIN_TOK)
    if r.status_code != 200:
        _record("E.1 GET /admin/ledger-alerts", False, f"{r.status_code}")
        return
    body = r.json()
    snap = body.get("current") or {}
    drift = float(snap.get("drift") or 0)
    inflow = float(snap.get("inflow") or 0)
    withdrawals = float(snap.get("withdrawals_out") or 0)
    expected_held = float(snap.get("expected_held") or 0)
    held = float(snap.get("held") or 0)
    print(f"  drift={drift} inflow={inflow} wd={withdrawals} exp_held={expected_held} held={held}")
    ok = abs(drift) <= 1.0
    _record("E.1 drift within ±₹1 of zero", ok, f"drift=₹{drift}")

    # Cross-check inflow ≈ reg_fee_txn_total + utr + svc + shop
    bk = _req("GET", "/admin/system-wallet/breakdown", token=ADMIN_TOK).json()
    inflow_bd = float(((bk.get("inflow") or {}).get("total") or 0))
    diff = abs(inflow - inflow_bd)
    _record("E.2 ledger-alerts.inflow ≈ breakdown.inflow.total", diff < 1.0,
            f"alerts.inflow=₹{inflow} breakdown.inflow.total=₹{inflow_bd} diff=₹{diff}")


# ============================================================
# SCENARIO F — No regression on existing endpoints
# ============================================================
def scenario_F():
    print("\n=== SCENARIO F: no regression on existing endpoints ===")
    # F.1
    r = _req("GET", "/admin/system-wallet/breakdown", token=ADMIN_TOK)
    _record("F.1 GET /admin/system-wallet/breakdown 200", r.status_code == 200,
            f"got {r.status_code}")
    # F.2
    r = _req("POST", "/admin/system-wallet/reconcile", token=ADMIN_TOK)
    _record("F.2 POST /admin/system-wallet/reconcile 200", r.status_code == 200,
            f"got {r.status_code}")
    # F.3
    r = _req("GET", "/admin/users", token=ADMIN_TOK)
    _record("F.3 GET /admin/users 200", r.status_code == 200, f"got {r.status_code}")
    # F.4 — admin approvals: register fresh user → approve
    uniq = uuid.uuid4().hex[:8]
    reg = _req("POST", "/auth/register", json_body={
        "name": f"ScenF approval {uniq}",
        "email": f"scen_f_{uniq}@test.app",
        "password": "Pass@123",
        "phone": f"66{uniq[:8]}",
    })
    if reg.status_code == 200:
        nid = reg.json()["user"]["id"]
        ntok = reg.json()["token"]
        _req("POST", "/payment/register-fee", token=ntok)
        ap = _req("POST", f"/admin/approvals/{nid}/approve", token=ADMIN_TOK)
        _record("F.4 POST /admin/approvals/{id}/approve 200", ap.status_code == 200,
                f"got {ap.status_code}: {ap.text[:150]}")
    else:
        _record("F.4 setup for approval", False, f"register fail {reg.status_code}")


# ---------- run ----------
if __name__ == "__main__":
    scenario_A()
    scenario_B()
    scenario_C()
    scenario_D()
    scenario_E()
    scenario_F()

    print("\n" + "=" * 60)
    print(f"PASSED: {len(PASSES)}")
    print(f"FAILED: {len(FAILURES)}")
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  {f}")
    sys.exit(0 if not FAILURES else 1)
