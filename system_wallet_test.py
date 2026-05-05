"""
Phase 1 — System Wallet test suite.

Covers scenarios A-K from /app/test_result.md for the Phase 1 wallet rework:
  - Admin's wallet broken into 4 buckets (referral_commission, direct_added,
    service_margin, shopping_margin) which roll up into wallet_balance.
  - GET /admin/system-wallet & POST /admin/system-wallet/deposit (UTR idempotent).
  - POST /admin/users/{id}/wallet — gated by direct_added bucket; reason required.
  - Service-booking 30% admin fee → service_margin.
  - Shop checkout platform_share total → shopping_margin.
  - Referral cascade L2-L10 to admin → referral_commission.
  - Status fixes (admin_credit/admin_debit/system_deposit/etc → "success").
  - RBAC: super_admin + finance only on system-wallet/deposit; manager/support 403.

Auth: admin@app.com / Admin@123 (super_admin).
"""
import os
import hmac
import hashlib
import secrets
import time
import json
import sys
from typing import Any, Dict, Optional, Tuple, List

import httpx

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# Razorpay creds (test) used by backend; signature_only branch is fine
RAZORPAY_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

results: List[Tuple[str, bool, str]] = []
created_user_ids: List[str] = []
TEST_START_ISO = ""  # set in main()


def record(name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login(email: str, password: str) -> Optional[str]:
    r = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("token")


def register_user(name: str, email: str, password: str, referral_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    body = {"name": name, "email": email, "password": password}
    if referral_code is not None:
        body["referral_code"] = referral_code
    r = httpx.post(f"{BASE}/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def auto_approve_user(token: str) -> Optional[Dict[str, Any]]:
    """Run create-order + verify with valid HMAC signature (signature_only branch)."""
    h = auth_headers(token)
    r1 = httpx.post(f"{BASE}/payment/create-order", headers=h, timeout=30)
    if r1.status_code != 200:
        print(f"create-order failed: {r1.status_code} {r1.text}")
        return None
    o = r1.json()
    order_id = o["order_id"]
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
        print(f"verify failed: {r2.status_code} {r2.text}")
        return None
    return r2.json()


def create_throwaway(prefix: str, password: str = "Pass@1234") -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Register + auto-approve a fresh user. Returns (token, user_doc) or (None, None)."""
    rand = secrets.token_hex(4)
    email = f"{prefix}.{rand}@swtest.io"
    name = f"{prefix.title()} {rand[:4].upper()}"
    reg = register_user(name, email, password)
    if not reg:
        return None, None
    token = reg["token"]
    user = reg["user"]
    apr = auto_approve_user(token)
    if not apr:
        return None, None
    # Refresh user doc
    me = httpx.get(f"{BASE}/auth/me", headers=auth_headers(token), timeout=30)
    if me.status_code == 200:
        user = me.json()
    if user and user.get("id"):
        created_user_ids.append(user["id"])
    return token, user


def get_admin_user(admin_token: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/admin/users", headers=auth_headers(admin_token), timeout=30)
    if r.status_code != 200:
        return None
    for u in r.json():
        if (u.get("email") or "").lower() == ADMIN_EMAIL:
            return u
    return None


def get_settings(admin_token: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/admin/settings", headers=auth_headers(admin_token), timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


def get_system_wallet(admin_token: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(admin_token), timeout=30)
    if r.status_code != 200:
        print(f"system-wallet GET {r.status_code}: {r.text}")
        return None
    return r.json()


def get_user_doc(admin_token: str, uid: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(f"{BASE}/admin/users", headers=auth_headers(admin_token), timeout=30)
    if r.status_code != 200:
        return None
    for u in r.json():
        if u.get("id") == uid:
            return u
    return None


def almost(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) < tol


# =========================================================================
# Test main
# =========================================================================
def main():
    print(f"\n=== Phase 1 System Wallet Test === BASE={BASE}\n")
    global TEST_START_ISO
    from datetime import datetime, timezone
    TEST_START_ISO = datetime.now(timezone.utc).isoformat()
    print(f"TEST_START_ISO={TEST_START_ISO}")

    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        print("FATAL: cannot login admin")
        sys.exit(2)
    print("Admin login OK")

    settings = get_settings(admin_token)
    if not settings:
        print("FATAL: cannot fetch settings")
        sys.exit(2)
    print(f"Settings: directs_required={settings.get('directs_required')}, "
          f"payout_l1={settings.get('payout_l1')}, payout_l2={settings.get('payout_l2')}, "
          f"vendor_commission_pct={settings.get('vendor_commission_pct')}, "
          f"registration_fee={settings.get('registration_fee')}")

    # ---------------- A. SYSTEM WALLET INITIAL STATE ----------------
    print("\n--- Scenario A: GET /admin/system-wallet initial state ---")
    sw = get_system_wallet(admin_token)
    if sw is None:
        record("A.0 GET /admin/system-wallet 200", False, "endpoint did not return 200")
        return
    record("A.0 GET /admin/system-wallet 200", True)

    buckets = sw.get("buckets") or {}
    expected_keys = {"referral_commission", "direct_added", "service_margin", "shopping_margin"}
    record("A.1 buckets has 4 keys", set(buckets.keys()) == expected_keys,
           f"got {sorted(buckets.keys())}")
    total = sw.get("total")
    bucket_sum = round(sum(float(buckets.get(k) or 0) for k in expected_keys), 2)
    record("A.2 total == sum(buckets)", almost(float(total or 0), bucket_sum),
           f"total={total} sum={bucket_sum}")

    admin_doc = get_admin_user(admin_token)
    record("A.3 total == admin.wallet_balance",
           admin_doc is not None and almost(float(total or 0), float(admin_doc.get("wallet_balance") or 0)),
           f"total={total} admin.wallet_balance={admin_doc.get('wallet_balance') if admin_doc else None}")

    initial_buckets = {k: float(buckets.get(k) or 0) for k in expected_keys}
    print(f"Initial buckets: {initial_buckets}")

    # ---------------- B. DEPOSIT ----------------
    print("\n--- Scenario B: POST /admin/system-wallet/deposit ---")
    dep_utr = f"UTR-DEP-{secrets.token_hex(4).upper()}"
    r = httpx.post(
        f"{BASE}/admin/system-wallet/deposit",
        headers=auth_headers(admin_token),
        json={"amount": 1000, "utr": dep_utr, "remarks": "HDFC IMPS"},
        timeout=30,
    )
    record("B.1 deposit 1000 UTR-DEP-* → 200", r.status_code == 200,
           f"{r.status_code} {r.text[:150]}")
    deposit_id = r.json().get("deposit_id") if r.status_code == 200 else None

    # Idempotency
    r2 = httpx.post(
        f"{BASE}/admin/system-wallet/deposit",
        headers=auth_headers(admin_token),
        json={"amount": 1000, "utr": dep_utr, "remarks": "HDFC IMPS"},
        timeout=30,
    )
    record("B.2 same UTR re-deposit → 400", r2.status_code == 400,
           f"{r2.status_code} {r2.text[:120]}")

    sw2 = get_system_wallet(admin_token)
    da_after = float((sw2 or {}).get("buckets", {}).get("direct_added") or 0)
    record("B.3 direct_added increased by 1000",
           almost(da_after - initial_buckets["direct_added"], 1000.0),
           f"before={initial_buckets['direct_added']} after={da_after}")
    deposits_list = (sw2 or {}).get("deposits", [])
    has_dep = any(d.get("utr") == dep_utr for d in deposits_list)
    record("B.4 deposits[] contains the UTR row", has_dep,
           f"first_few_utrs={[d.get('utr') for d in deposits_list[:3]]}")

    # transactions/me has system_deposit row with status=success and UTR
    rt = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(admin_token), timeout=30)
    if rt.status_code != 200:
        record("B.5 transactions/me 200", False, f"{rt.status_code}")
    else:
        txs = rt.json()
        sys_dep = [t for t in txs if t.get("type") == "system_deposit" and t.get("reference_number") == dep_utr]
        record("B.5 system_deposit transaction exists with UTR", len(sys_dep) >= 1,
               f"matching={len(sys_dep)}")
        if sys_dep:
            record("B.6 system_deposit.status == success", sys_dep[0].get("status") == "success",
                   f"status={sys_dep[0].get('status')}")
            record("B.7 system_deposit.amount == 1000", almost(float(sys_dep[0].get("amount") or 0), 1000.0))

    # Refresh state
    sw_after_dep = get_system_wallet(admin_token)
    bucket_after_dep = {k: float(sw_after_dep["buckets"].get(k) or 0) for k in expected_keys}

    # ---------------- C. ADMIN CREDITS USER WALLET ----------------
    print("\n--- Scenario C: admin credits user wallet (gated) ---")
    u_x_token, u_x = create_throwaway("ux", )
    if not u_x_token:
        record("C.0 throwaway U_x created", False, "register/auto-approve failed")
    else:
        record("C.0 throwaway U_x created", True, f"id={u_x['id']}")

    if u_x_token:
        r = httpx.post(
            f"{BASE}/admin/users/{u_x['id']}/wallet",
            headers=auth_headers(admin_token),
            json={"amount": 200, "type": "credit", "reason": "Test bonus"},
            timeout=30,
        )
        record("C.1 admin credit U_x ₹200 → 200", r.status_code == 200,
               f"{r.status_code} {r.text[:160]}")

        u_x_fresh = get_user_doc(admin_token, u_x["id"])
        if u_x_fresh:
            record("C.2 U_x.wallet_balance == 200",
                   almost(float(u_x_fresh.get("wallet_balance") or 0), 200.0),
                   f"got {u_x_fresh.get('wallet_balance')}")
            record("C.3 U_x.total_earned == 200",
                   almost(float(u_x_fresh.get("total_earned") or 0), 200.0),
                   f"got {u_x_fresh.get('total_earned')}")

        # Check transaction on U_x
        rt = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(u_x_token), timeout=30)
        if rt.status_code == 200:
            txs = rt.json()
            ac = [t for t in txs if t.get("type") == "admin_credit"]
            record("C.4 U_x has admin_credit transaction", len(ac) >= 1, f"matching={len(ac)}")
            if ac:
                t0 = ac[0]
                record("C.5 admin_credit.status == success", t0.get("status") == "success",
                       f"status={t0.get('status')}")
                record("C.6 admin_credit.amount == +200",
                       almost(float(t0.get("amount") or 0), 200.0),
                       f"amount={t0.get('amount')}")
                record("C.7 admin_credit.remarks == 'Test bonus'",
                       (t0.get("remarks") or "") == "Test bonus",
                       f"remarks={t0.get('remarks')}")
                ref = t0.get("reference_number") or ""
                record("C.8 reference_number length 8", len(ref) == 8, f"ref={ref}")
                record("C.9 from_admin_email == admin@app.com",
                       (t0.get("from_admin_email") or "").lower() == ADMIN_EMAIL,
                       f"from_admin_email={t0.get('from_admin_email')}")

        # Bucket should drop by 200
        sw_c = get_system_wallet(admin_token)
        b_c = {k: float(sw_c["buckets"].get(k) or 0) for k in expected_keys}
        record("C.10 direct_added decreased by 200",
               almost(bucket_after_dep["direct_added"] - b_c["direct_added"], 200.0),
               f"before={bucket_after_dep['direct_added']} after={b_c['direct_added']}")

        # Empty reason rejects
        r_empty = httpx.post(
            f"{BASE}/admin/users/{u_x['id']}/wallet",
            headers=auth_headers(admin_token),
            json={"amount": 50, "type": "credit", "reason": "   "},
            timeout=30,
        )
        record("C.11 empty reason → 400", r_empty.status_code == 400,
               f"{r_empty.status_code} {r_empty.text[:160]}")

    # ---------------- D. INSUFFICIENT FUNDS GATE ----------------
    print("\n--- Scenario D: insufficient direct_added ---")
    if u_x_token:
        sw_d_pre = get_system_wallet(admin_token)
        b_d_pre = float(sw_d_pre["buckets"]["direct_added"])
        u_x_pre = get_user_doc(admin_token, u_x["id"])
        wb_pre = float(u_x_pre.get("wallet_balance") or 0) if u_x_pre else 0

        r = httpx.post(
            f"{BASE}/admin/users/{u_x['id']}/wallet",
            headers=auth_headers(admin_token),
            json={"amount": 1_000_000, "type": "credit", "reason": "too much"},
            timeout=30,
        )
        record("D.1 huge credit → 400", r.status_code == 400,
               f"{r.status_code} {r.text[:200]}")
        try:
            detail = r.json().get("detail", "")
        except Exception:
            detail = ""
        record("D.2 error message mentions Insufficient/Direct-Added",
               ("insufficient" in detail.lower() and "direct" in detail.lower()),
               f"detail={detail!r}")

        sw_d_post = get_system_wallet(admin_token)
        b_d_post = float(sw_d_post["buckets"]["direct_added"])
        record("D.3 direct_added unchanged", almost(b_d_pre, b_d_post),
               f"pre={b_d_pre} post={b_d_post}")

        u_x_post = get_user_doc(admin_token, u_x["id"])
        wb_post = float(u_x_post.get("wallet_balance") or 0) if u_x_post else -1
        record("D.4 U_x.wallet_balance unchanged", almost(wb_pre, wb_post),
               f"pre={wb_pre} post={wb_post}")

    # ---------------- E. DEBIT PATH RESTORES BUCKET ----------------
    print("\n--- Scenario E: debit returns funds to direct_added ---")
    if u_x_token:
        sw_e_pre = get_system_wallet(admin_token)
        b_e_pre = float(sw_e_pre["buckets"]["direct_added"])

        r = httpx.post(
            f"{BASE}/admin/users/{u_x['id']}/wallet",
            headers=auth_headers(admin_token),
            json={"amount": 50, "type": "debit", "reason": "correction"},
            timeout=30,
        )
        record("E.1 debit U_x ₹50 → 200", r.status_code == 200,
               f"{r.status_code} {r.text[:160]}")

        u_x_after = get_user_doc(admin_token, u_x["id"])
        record("E.2 U_x.wallet_balance == 150",
               almost(float(u_x_after.get("wallet_balance") or 0), 150.0),
               f"got {u_x_after.get('wallet_balance')}")

        sw_e_post = get_system_wallet(admin_token)
        b_e_post = float(sw_e_post["buckets"]["direct_added"])
        record("E.3 direct_added grew by 50",
               almost(b_e_post - b_e_pre, 50.0),
               f"pre={b_e_pre} post={b_e_post}")

        # admin_debit transaction
        rt = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(u_x_token), timeout=30)
        if rt.status_code == 200:
            ad = [t for t in rt.json() if t.get("type") == "admin_debit"]
            record("E.4 admin_debit transaction exists", len(ad) >= 1, f"count={len(ad)}")
            if ad:
                record("E.5 admin_debit.status == success",
                       ad[0].get("status") == "success",
                       f"status={ad[0].get('status')}")
                record("E.6 admin_debit.amount == -50",
                       almost(float(ad[0].get("amount") or 0), -50.0),
                       f"amount={ad[0].get('amount')}")

    # ---------------- F. SERVICE BOOKING ROUTES TO service_margin ----------------
    print("\n--- Scenario F: service booking → service_margin ---")
    # Create provider U_p
    u_p_token, u_p = create_throwaway("upf")
    if not u_p_token:
        record("F.0 U_p (provider) created", False)
    else:
        record("F.0 U_p (provider) created", True, f"id={u_p['id']}")

    # Create customer U_c with sufficient wallet (need 500 minimum)
    u_c_token, u_c = create_throwaway("ucf")
    if not u_c_token:
        record("F.0b U_c (customer) created", False)
    else:
        record("F.0b U_c (customer) created", True, f"id={u_c['id']}")

    # Top up customer wallet by 600 from admin direct_added
    if u_c_token:
        # Make sure system has enough — add a deposit if needed
        sw_pre = get_system_wallet(admin_token)
        if float(sw_pre["buckets"]["direct_added"]) < 600:
            top = httpx.post(
                f"{BASE}/admin/system-wallet/deposit",
                headers=auth_headers(admin_token),
                json={"amount": 2000, "utr": f"UTR-DEP-{secrets.token_hex(4).upper()}"},
                timeout=30,
            )
            record("F.0c top-up deposit for credits", top.status_code == 200,
                   f"{top.status_code}")
        # Credit customer 600
        r = httpx.post(
            f"{BASE}/admin/users/{u_c['id']}/wallet",
            headers=auth_headers(admin_token),
            json={"amount": 600, "type": "credit", "reason": "Booking funding"},
            timeout=30,
        )
        record("F.0d credit U_c ₹600 → 200", r.status_code == 200,
               f"{r.status_code} {r.text[:160]}")

    # Provider applies + admin approves @ ₹500
    if u_p_token:
        r = httpx.post(
            f"{BASE}/service/apply",
            headers=auth_headers(u_p_token),
            json={
                "service_name": "AC Repair",
                "service_category": "Electrician",
                "pincode": "560001",
                "charge": 500,
                "description": "Same-day service",
            },
            timeout=30,
        )
        record("F.1 U_p apply → 200", r.status_code == 200,
               f"{r.status_code} {r.text[:140]}")
        aid = (r.json().get("application") or {}).get("id") if r.status_code == 200 else None

        if aid:
            ra = httpx.post(
                f"{BASE}/admin/service-applications/{aid}/approve",
                headers=auth_headers(admin_token),
                timeout=30,
            )
            record("F.2 admin approve service → 200", ra.status_code == 200,
                   f"{ra.status_code} {ra.text[:120]}")

    # Snapshot before booking
    sw_pre_book = get_system_wallet(admin_token)
    bp = {k: float(sw_pre_book["buckets"].get(k) or 0) for k in expected_keys}

    if u_c_token and u_p_token:
        rb = httpx.post(
            f"{BASE}/services/{u_p['id']}/book",
            headers=auth_headers(u_c_token),
            json={"notes": "Please come morning"},
            timeout=30,
        )
        record("F.3 U_c books U_p service → 200", rb.status_code == 200,
               f"{rb.status_code} {rb.text[:160]}")

    sw_post_book = get_system_wallet(admin_token)
    bpost = {k: float(sw_post_book["buckets"].get(k) or 0) for k in expected_keys}

    # vendor_commission_pct default 70 → admin_share = 500 - 350 = 150
    expected_admin_share = 500 - round(500 * float(settings.get("vendor_commission_pct", 70)) / 100.0, 2)
    record("F.4 service_margin += admin_share",
           almost(bpost["service_margin"] - bp["service_margin"], expected_admin_share),
           f"delta={bpost['service_margin'] - bp['service_margin']} expected={expected_admin_share}")
    record("F.5 referral_commission unchanged after booking",
           almost(bp["referral_commission"], bpost["referral_commission"]),
           f"pre={bp['referral_commission']} post={bpost['referral_commission']}")
    record("F.6 direct_added unchanged after booking",
           almost(bp["direct_added"], bpost["direct_added"]),
           f"pre={bp['direct_added']} post={bpost['direct_added']}")
    record("F.7 shopping_margin unchanged after booking",
           almost(bp["shopping_margin"], bpost["shopping_margin"]),
           f"pre={bp['shopping_margin']} post={bpost['shopping_margin']}")

    # Total = sum of buckets
    record("F.8 total == sum(buckets)",
           almost(float(sw_post_book["total"]),
                  sum(bpost[k] for k in expected_keys)),
           f"total={sw_post_book['total']} sum={sum(bpost[k] for k in expected_keys)}")

    # ---------------- G. SHOP CHECKOUT ROUTES TO shopping_margin ----------------
    print("\n--- Scenario G: shop checkout → shopping_margin ---")
    # Admin creates a non-vendor product (₹100)
    pname = f"TestNoVendorProduct-{secrets.token_hex(3)}"
    rp = httpx.post(
        f"{BASE}/admin/products",
        headers=auth_headers(admin_token),
        json={
            "name": pname,
            "price": 100,
            "image_url": "https://example.com/p.png",
            "description": "test",
            "stock": 10,
            "category": "test",
            "is_published": True,
            # vendor_id null
        },
        timeout=30,
    )
    record("G.1 admin creates non-vendor product → 200", rp.status_code == 200,
           f"{rp.status_code} {rp.text[:200]}")
    product_id = rp.json().get("id") if rp.status_code == 200 else None

    # Use U_c (whose wallet should be 600 - 500 = 100 now). Verify, top up if needed.
    if u_c_token:
        u_c_fresh = get_user_doc(admin_token, u_c["id"])
        wb = float(u_c_fresh.get("wallet_balance") or 0) if u_c_fresh else 0
        if wb < 100:
            r = httpx.post(
                f"{BASE}/admin/users/{u_c['id']}/wallet",
                headers=auth_headers(admin_token),
                json={"amount": 200, "type": "credit", "reason": "shop top-up"},
                timeout=30,
            )

    sw_pre_shop = get_system_wallet(admin_token)
    bshop_pre = {k: float(sw_pre_shop["buckets"].get(k) or 0) for k in expected_keys}

    if u_c_token and product_id:
        # add to cart, checkout
        ra = httpx.post(
            f"{BASE}/cart/add",
            headers=auth_headers(u_c_token),
            json={"product_id": product_id, "qty": 1},
            timeout=30,
        )
        record("G.2 cart/add → 200", ra.status_code == 200, f"{ra.status_code}")
        rco = httpx.post(
            f"{BASE}/orders/checkout",
            headers=auth_headers(u_c_token),
            timeout=30,
        )
        record("G.3 checkout → 200", rco.status_code == 200,
               f"{rco.status_code} {rco.text[:200]}")

    sw_post_shop = get_system_wallet(admin_token)
    bshop_post = {k: float(sw_post_shop["buckets"].get(k) or 0) for k in expected_keys}

    record("G.4 shopping_margin += 100",
           almost(bshop_post["shopping_margin"] - bshop_pre["shopping_margin"], 100.0),
           f"delta={bshop_post['shopping_margin'] - bshop_pre['shopping_margin']}")
    record("G.5 service_margin unchanged after shop",
           almost(bshop_post["service_margin"], bshop_pre["service_margin"]))
    record("G.6 referral_commission unchanged after shop",
           almost(bshop_post["referral_commission"], bshop_pre["referral_commission"]))
    record("G.7 direct_added unchanged after shop",
           almost(bshop_post["direct_added"], bshop_pre["direct_added"]))

    # Verify shop_commission tx exists for admin with status=success
    rta = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(admin_token), timeout=30)
    if rta.status_code == 200:
        sc = [t for t in rta.json() if t.get("type") == "shop_commission"]
        record("G.8 admin shop_commission transaction exists", len(sc) >= 1,
               f"count={len(sc)}")
        if sc:
            record("G.9 shop_commission.status == success",
                   sc[0].get("status") == "success",
                   f"status={sc[0].get('status')}")

    # ---------------- H. REFERRAL CASCADE → referral_commission ----------------
    print("\n--- Scenario H: referral cascade L_K to admin → referral_commission ---")
    sw_pre_ref = get_system_wallet(admin_token)
    bref_pre = {k: float(sw_pre_ref["buckets"].get(k) or 0) for k in expected_keys}

    # Register a brand new user with no referral. They will be placed via spillover BFS.
    u_h_token, u_h = create_throwaway("uhref")
    if not u_h_token:
        record("H.0 U_h registered+approved", False)
    else:
        record("H.0 U_h registered+approved", True, f"id={u_h['id']}")

    # Walk the upline chain from U_h to admin to determine admin's level
    admin_level = -1
    sponsor_id = u_h.get("sponsor_id") if u_h else None
    admin_id = admin_doc["id"] if admin_doc else None
    chain = []
    level = 1
    cur = sponsor_id
    while cur and level <= 12:
        if cur == admin_id:
            admin_level = level
            chain.append((level, cur, "ADMIN"))
            break
        u = get_user_doc(admin_token, cur)
        if not u:
            chain.append((level, cur, "?"))
            break
        chain.append((level, cur, u.get("email")))
        cur = u.get("sponsor_id")
        level += 1
    print(f"   spillover chain (U_h→up): {chain}; admin_level={admin_level}")

    sw_post_ref = get_system_wallet(admin_token)
    bref_post = {k: float(sw_post_ref["buckets"].get(k) or 0) for k in expected_keys}

    if admin_level == 1:
        # Admin is direct sponsor — count increments. L1 fires only on Nth direct.
        # We don't strictly know N alignment, but referral_commission delta should be either
        # 0 or payout_l1 (when at Nth boundary).
        delta = bref_post["referral_commission"] - bref_pre["referral_commission"]
        possible = [0.0, float(settings.get("payout_l1") or 0)]
        record("H.1 referral_commission delta is 0 or payout_l1 (admin is direct)",
               any(almost(delta, p) for p in possible),
               f"delta={delta} possibilities={possible}")
    elif 2 <= admin_level <= 10:
        expected_lk = float(settings.get(f"payout_l{admin_level}") or 0)
        delta = bref_post["referral_commission"] - bref_pre["referral_commission"]
        # Note: L1 cascade for the spillover sponsor may also fire if Nth boundary —
        # but that goes to U_d, NOT admin. The cascade UP to admin uses L=admin_level
        # payout. Admin won't get the L1 (since L1 sponsor is U_d, not admin).
        record(f"H.1 referral_commission += payout_l{admin_level} ({expected_lk})",
               almost(delta, expected_lk),
               f"delta={delta} expected={expected_lk}")
    else:
        record("H.1 admin reachable in upline chain (≤10 levels)", False,
               f"admin_level={admin_level}")

    # Other buckets unchanged
    record("H.2 direct_added unchanged after referral",
           almost(bref_pre["direct_added"], bref_post["direct_added"]),
           f"pre={bref_pre['direct_added']} post={bref_post['direct_added']}")
    record("H.3 service_margin unchanged after referral",
           almost(bref_pre["service_margin"], bref_post["service_margin"]))
    record("H.4 shopping_margin unchanged after referral",
           almost(bref_pre["shopping_margin"], bref_post["shopping_margin"]))

    # ---------------- I. STATUS CONSISTENCY ----------------
    print("\n--- Scenario I: status consistency on all newly-created tx ---")
    # Sweep transactions for all users we created, plus admin — only check
    # transactions newly created during this test (created_at >= TEST_START_ISO).
    bad = []
    legacy_statuses = {"credited", "debited", "paid"}

    def is_recent(t: Dict[str, Any]) -> bool:
        return (t.get("created_at") or "") >= TEST_START_ISO

    # admin txs
    rta = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(admin_token), timeout=30)
    if rta.status_code == 200:
        for t in rta.json():
            if not is_recent(t):
                continue
            if t.get("status") in legacy_statuses:
                bad.append(("admin", t.get("type"), t.get("status"), t.get("id")))

    for tok, label in [(u_x_token, "U_x"), (u_p_token, "U_p"), (u_c_token, "U_c"), (u_h_token, "U_h")]:
        if not tok:
            continue
        rr = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(tok), timeout=30)
        if rr.status_code == 200:
            for t in rr.json():
                if not is_recent(t):
                    continue
                if t.get("status") in legacy_statuses:
                    bad.append((label, t.get("type"), t.get("status"), t.get("id")))

    # registration_fee handler still uses status="paid" — that flow is outside the
    # Phase 1 wallet rework. Don't flag it here.
    real_bad = [b for b in bad if not (b[1] == "registration_fee" and b[2] == "paid")]
    record("I.1 No legacy 'credited'/'debited'/'paid' status on rework flows (post-test-start)",
           len(real_bad) == 0,
           f"violations={real_bad[:5]}")

    # Specific check for known types must be success (post-test-start)
    for typ in ("admin_credit", "admin_debit", "system_deposit", "service_commission",
                "shop_commission", "service_booking", "service_earning",
                "vendor_sale", "order", "referral_payout"):
        seen = []
        for tok in [admin_token, u_x_token, u_p_token, u_c_token, u_h_token]:
            if not tok:
                continue
            rr = httpx.get(f"{BASE}/transactions/me", headers=auth_headers(tok), timeout=30)
            if rr.status_code == 200:
                for t in rr.json():
                    if not is_recent(t):
                        continue
                    if t.get("type") == typ:
                        seen.append(t)
        if seen:
            non_success = [t for t in seen if t.get("status") != "success"]
            record(f"I.2 all {typ} have status=success (sampled {len(seen)})",
                   len(non_success) == 0,
                   f"non_success={[t.get('status') for t in non_success[:3]]}")

    # ---------------- J. RBAC ----------------
    print("\n--- Scenario J: RBAC on system-wallet ---")
    if u_x_token:
        r = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(u_x_token), timeout=30)
        record("J.1 non-admin GET /admin/system-wallet → 403", r.status_code == 403,
               f"{r.status_code} {r.text[:120]}")
        r = httpx.post(
            f"{BASE}/admin/system-wallet/deposit",
            headers=auth_headers(u_x_token),
            json={"amount": 100, "utr": "BAD-UTR"},
            timeout=30,
        )
        record("J.2 non-admin POST deposit → 403", r.status_code == 403,
               f"{r.status_code} {r.text[:120]}")

    # Create a finance admin and a manager admin
    fin_email = f"finance.{secrets.token_hex(3)}@swtest.io"
    mgr_email = f"manager.{secrets.token_hex(3)}@swtest.io"
    sup_email = f"support.{secrets.token_hex(3)}@swtest.io"

    fin_resp = httpx.post(
        f"{BASE}/admin/admins",
        headers=auth_headers(admin_token),
        json={"name": "Fin Test", "email": fin_email, "password": "Pass@1234",
              "admin_role": "finance"},
        timeout=30,
    )
    mgr_resp = httpx.post(
        f"{BASE}/admin/admins",
        headers=auth_headers(admin_token),
        json={"name": "Mgr Test", "email": mgr_email, "password": "Pass@1234",
              "admin_role": "manager"},
        timeout=30,
    )
    sup_resp = httpx.post(
        f"{BASE}/admin/admins",
        headers=auth_headers(admin_token),
        json={"name": "Sup Test", "email": sup_email, "password": "Pass@1234",
              "admin_role": "support"},
        timeout=30,
    )

    fin_id = fin_resp.json().get("id") if fin_resp.status_code == 200 else None
    mgr_id = mgr_resp.json().get("id") if mgr_resp.status_code == 200 else None
    sup_id = sup_resp.json().get("id") if sup_resp.status_code == 200 else None
    if fin_id:
        created_user_ids.append(fin_id)
    if mgr_id:
        created_user_ids.append(mgr_id)
    if sup_id:
        created_user_ids.append(sup_id)

    fin_token = login(fin_email, "Pass@1234")
    mgr_token = login(mgr_email, "Pass@1234")
    sup_token = login(sup_email, "Pass@1234")
    record("J.3 finance/manager/support admins created+login",
           bool(fin_token and mgr_token and sup_token),
           f"finance={bool(fin_token)} manager={bool(mgr_token)} support={bool(sup_token)}")

    if fin_token:
        r = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(fin_token), timeout=30)
        record("J.4 finance GET /admin/system-wallet → 200", r.status_code == 200,
               f"{r.status_code}")
        r = httpx.post(
            f"{BASE}/admin/system-wallet/deposit",
            headers=auth_headers(fin_token),
            json={"amount": 50, "utr": f"UTR-FIN-{secrets.token_hex(3).upper()}"},
            timeout=30,
        )
        record("J.5 finance POST deposit → 200", r.status_code == 200,
               f"{r.status_code} {r.text[:140]}")

    if mgr_token:
        r = httpx.get(f"{BASE}/admin/system-wallet", headers=auth_headers(mgr_token), timeout=30)
        record("J.6 manager GET /admin/system-wallet → 200", r.status_code == 200,
               f"{r.status_code}")
        r = httpx.post(
            f"{BASE}/admin/system-wallet/deposit",
            headers=auth_headers(mgr_token),
            json={"amount": 50, "utr": f"UTR-MGR-{secrets.token_hex(3).upper()}"},
            timeout=30,
        )
        record("J.7 manager POST deposit → 403", r.status_code == 403,
               f"{r.status_code} {r.text[:140]}")

    if sup_token:
        r = httpx.post(
            f"{BASE}/admin/system-wallet/deposit",
            headers=auth_headers(sup_token),
            json={"amount": 50, "utr": f"UTR-SUP-{secrets.token_hex(3).upper()}"},
            timeout=30,
        )
        record("J.8 support POST deposit → 403", r.status_code == 403,
               f"{r.status_code} {r.text[:140]}")

    # ---------------- K. CLEANUP ----------------
    print("\n--- Scenario K: cleanup throwaway users + product ---")
    deleted = 0
    failed_delete = []
    for uid in set(created_user_ids):
        rd = httpx.delete(
            f"{BASE}/admin/users/{uid}",
            headers=auth_headers(admin_token),
            timeout=30,
        )
        if rd.status_code in (200, 204):
            deleted += 1
        else:
            failed_delete.append((uid, rd.status_code, rd.text[:80]))
    record("K.1 throwaway users deleted",
           len(failed_delete) == 0,
           f"deleted={deleted} failed={failed_delete[:3]}")

    if product_id:
        rd = httpx.delete(
            f"{BASE}/admin/products/{product_id}",
            headers=auth_headers(admin_token),
            timeout=30,
        )
        record("K.2 throwaway product deleted",
               rd.status_code in (200, 204),
               f"{rd.status_code}")

    # ---------------- SUMMARY ----------------
    print("\n========== SUMMARY ==========")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"PASSED: {passed}")
    print(f"FAILED: {failed}")
    if failed:
        print("\nFAILED CHECKS:")
        for n, ok, d in results:
            if not ok:
                print(f"  - {n}  {d}")
    return failed


if __name__ == "__main__":
    rc = main() or 0
    sys.exit(0 if rc == 0 else 1)
