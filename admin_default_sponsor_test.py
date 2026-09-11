"""
Focused regression test for the "Default sponsor = admin when no referral code"
+ "Admin referral_code = EARN" feature.

Scenarios A–I per review request. Run with:
    python3 /app/admin_default_sponsor_test.py
"""
import os
import sys
import time
import hmac
import hashlib
import secrets
import json
import requests

BASE = "https://slangcart-tracking.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# Razorpay test creds (must match backend/.env)
RZP_KEY_ID = "rzp_test_SjgtHA4CxiFyTK"
RZP_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

results = []   # (label, ok, detail)
created_user_ids = []  # for cleanup


def log(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    results.append((label, ok, detail))


def post(url, **kw):
    return requests.post(BASE + url, timeout=30, **kw)


def get(url, **kw):
    return requests.get(BASE + url, timeout=30, **kw)


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def admin_login():
    r = post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


def list_users(admin_token):
    r = get("/admin/users", headers=headers(admin_token))
    assert r.status_code == 200, f"/admin/users failed: {r.status_code}"
    return r.json()


def find_user(admin_token, email):
    users = list_users(admin_token)
    for u in users:
        if u.get("email") == email.lower():
            return u
    return None


def fresh_email(prefix="ds"):
    return f"{prefix}.{int(time.time())}.{secrets.token_hex(3)}@example.com"


def register(name, email, password="StrongP@ss1", referral_code=None, omit=False):
    body = {"name": name, "email": email, "password": password}
    if not omit:
        body["referral_code"] = referral_code if referral_code is not None else ""
    elif referral_code is not None:
        body["referral_code"] = referral_code
    return post("/auth/register", json=body)


def pay_via_razorpay(user_token):
    """Create live order, fake a payment_id, sign with our HMAC secret, verify."""
    r = post("/payment/create-order", headers=headers(user_token))
    if r.status_code != 200:
        return False, f"create-order failed {r.status_code} {r.text}", None
    order = r.json()
    if order.get("is_mock"):
        # Mock mode — any non-empty signature works
        body = {
            "razorpay_order_id": order["order_id"],
            "razorpay_payment_id": f"pay_mock_{secrets.token_hex(6)}",
            "razorpay_signature": "mock_sig",
        }
    else:
        order_id = order["order_id"]
        payment_id = f"pay_test_{secrets.token_hex(8)}"
        sig = hmac.new(
            RZP_KEY_SECRET.encode(),
            f"{order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        body = {
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sig,
        }
    vr = post("/payment/verify", headers=headers(user_token), json=body)
    if vr.status_code != 200:
        return False, f"verify failed {vr.status_code} {vr.text}", None
    return True, "", vr.json()


def cleanup(admin_token):
    deleted = 0
    for uid in created_user_ids:
        try:
            r = requests.delete(f"{BASE}/admin/users/{uid}", headers=headers(admin_token), timeout=15)
            if r.status_code == 200:
                deleted += 1
        except Exception:
            pass
    print(f"\nCleanup: deleted {deleted}/{len(created_user_ids)} throwaway users")


def main():
    print("=" * 70)
    print("Default-sponsor + EARN code regression test")
    print("=" * 70)

    admin_token, admin_user = admin_login()
    log("admin@app.com login (super_admin)", admin_user.get("role") == "admin",
        f"id={admin_user['id'][:8]} role={admin_user.get('role')}")

    # ---------------- A. ADMIN CODE MIGRATION ----------------
    print("\n--- A. ADMIN CODE MIGRATION ---")
    admin_row = find_user(admin_token, ADMIN_EMAIL)
    if not admin_row:
        log("A.1 admin row in /admin/users", False, "admin not found")
        return
    log("A.1 admin row in /admin/users", True, f"id={admin_row['id'][:8]}")
    log("A.2 admin.referral_code == 'EARN'", admin_row.get("referral_code") == "EARN",
        f"got={admin_row.get('referral_code')}")
    admin_id = admin_row["id"]
    start_directs = int(admin_row.get("direct_referrals_count") or 0)
    start_wallet = float(admin_row.get("wallet_balance") or 0.0)

    # Get current settings
    r = get("/admin/settings", headers=headers(admin_token))
    settings = r.json() if r.status_code == 200 else {}
    directs_required = int(settings.get("directs_required", 5))
    payout_l1 = float(settings.get("payout_l1", 200))
    print(f"settings: directs_required={directs_required}, payout_l1={payout_l1}, "
          f"registration_fee={settings.get('registration_fee')}")
    print(f"admin baseline: direct_referrals_count={start_directs}, wallet_balance={start_wallet}")

    # ---------------- B. NO-REFERRAL REGISTRATION (no field) ----------------
    print("\n--- B. NO-REFERRAL REGISTRATION (key omitted) ---")
    eb = fresh_email("nob")
    rb = register("No Field Bob", eb, omit=True)
    log("B.1 POST /auth/register (no referral_code key) → 200", rb.status_code == 200,
        f"status={rb.status_code} body={rb.text[:200]}")
    if rb.status_code == 200:
        ub = rb.json()["user"]
        created_user_ids.append(ub["id"])
        log("B.2 returned user.referred_by == 'EARN'", ub.get("referred_by") == "EARN",
            f"got={ub.get('referred_by')}")
        log("B.3 returned user.sponsor_id == admin.id", ub.get("sponsor_id") == admin_id,
            f"got={ub.get('sponsor_id')[:8] if ub.get('sponsor_id') else None}, expected={admin_id[:8]}")
        # Verify via /admin/users
        ub_full = find_user(admin_token, eb)
        log("B.4 /admin/users shows sponsor_id == admin.id",
            ub_full and ub_full.get("sponsor_id") == admin_id,
            f"got={ub_full.get('sponsor_id') if ub_full else None}")
        log("B.5 /admin/users shows referred_by == 'EARN'",
            ub_full and ub_full.get("referred_by") == "EARN",
            f"got={ub_full.get('referred_by') if ub_full else None}")

    # ---------------- C. EMPTY-STRING REFERRAL ----------------
    print("\n--- C. EMPTY-STRING REFERRAL ---")
    ec = fresh_email("emp")
    rc = register("Empty Str Carol", ec, referral_code="")
    log("C.1 POST /auth/register {referral_code:''} → 200", rc.status_code == 200,
        f"status={rc.status_code} body={rc.text[:200]}")
    if rc.status_code == 200:
        uc = rc.json()["user"]
        created_user_ids.append(uc["id"])
        log("C.2 user.referred_by == 'EARN'", uc.get("referred_by") == "EARN",
            f"got={uc.get('referred_by')}")
        log("C.3 user.sponsor_id == admin.id", uc.get("sponsor_id") == admin_id,
            f"got={(uc.get('sponsor_id') or '')[:8]}")

    # ---------------- D. INVALID REFERRAL → 400 ----------------
    print("\n--- D. INVALID REFERRAL ---")
    ed = fresh_email("inv")
    rd = register("Invalid Dave", ed, referral_code="BOGUS_CODE_XYZ")
    log("D.1 POST /auth/register {referral_code:'BOGUS_CODE_XYZ'} → 400", rd.status_code == 400,
        f"status={rd.status_code}")
    if rd.status_code == 400:
        det = rd.json().get("detail", "")
        log("D.2 detail contains 'Invalid referral code'", "Invalid referral code" in det,
            f"detail={det}")
    else:
        # If by chance it created, capture for cleanup
        if rd.status_code == 200:
            try:
                created_user_ids.append(rd.json()["user"]["id"])
            except Exception:
                pass

    # ---------------- E. EXPLICIT VALID REFERRAL ----------------
    print("\n--- E. EXPLICIT VALID REFERRAL ---")
    # Create U_a via no-referral (admin sponsor)
    e_a_email = fresh_email("ua")
    ra = register("Anchor Alice", e_a_email, omit=True)
    log("E.1 register U_a no-referral → 200", ra.status_code == 200, f"status={ra.status_code}")
    if ra.status_code == 200:
        ua = ra.json()["user"]
        created_user_ids.append(ua["id"])
        ua_full = find_user(admin_token, e_a_email)
        ua_code = ua_full.get("referral_code") if ua_full else None
        log("E.2 U_a has a referral_code", bool(ua_code), f"code={ua_code}")
        log("E.3 U_a.sponsor_id == admin (default)", ua_full and ua_full.get("sponsor_id") == admin_id)

        # Now register U_b with U_a's code
        e_b_email = fresh_email("ub")
        rb = register("Branch Bob", e_b_email, referral_code=ua_code)
        log("E.4 register U_b with U_a.referral_code → 200", rb.status_code == 200,
            f"status={rb.status_code} body={rb.text[:200]}")
        if rb.status_code == 200:
            ub = rb.json()["user"]
            created_user_ids.append(ub["id"])
            log("E.5 U_b.referred_by == U_a.referral_code",
                ub.get("referred_by") == ua_code,
                f"got={ub.get('referred_by')} expected={ua_code}")
            log("E.6 U_b.sponsor_id == U_a.id (NOT admin)",
                ub.get("sponsor_id") == ua["id"] and ub.get("sponsor_id") != admin_id,
                f"got={(ub.get('sponsor_id') or '')[:8]} ua={ua['id'][:8]} admin={admin_id[:8]}")

    # ---------------- F. ADMIN EARNS COMMISSION (chain of N) ----------------
    print(f"\n--- F. ADMIN EARNS COMMISSION (N={directs_required}) ---")
    # Refresh start counts (we just added some users to admin's directs in B/C, so recompute)
    admin_now = find_user(admin_token, ADMIN_EMAIL)
    f_start_directs = int(admin_now.get("direct_referrals_count") or 0)
    f_start_wallet = float(admin_now.get("wallet_balance") or 0.0)
    print(f"F baseline (post B/C/E): direct_referrals_count={f_start_directs}, wallet={f_start_wallet}")

    f_users = []
    for i in range(directs_required):
        em = fresh_email(f"fch{i}")
        rr = register(f"FChain{i}", em, omit=True)
        ok = rr.status_code == 200
        log(f"F.reg{i+1} register no-referral → 200", ok, f"status={rr.status_code}")
        if not ok:
            continue
        body = rr.json()
        u = body["user"]; tok = body["token"]
        created_user_ids.append(u["id"])
        f_users.append((u, tok, em))

        # Pay registration fee via /payment/verify with valid HMAC
        ok_pay, err, vr = pay_via_razorpay(tok)
        log(f"F.pay{i+1} /payment/verify (auto-approve) → 200", ok_pay, err)
        if ok_pay:
            log(f"F.pay{i+1} approval_status='approved'",
                vr.get("approval_status") == "approved",
                f"got={vr.get('approval_status')}")
            log(f"F.pay{i+1} auto_approved=True", vr.get("auto_approved") is True,
                f"got={vr.get('auto_approved')}")

    # After N, admin.direct_referrals_count should be f_start_directs + N
    admin_after = find_user(admin_token, ADMIN_EMAIL)
    end_directs = int(admin_after.get("direct_referrals_count") or 0)
    end_wallet = float(admin_after.get("wallet_balance") or 0.0)
    expected_directs = f_start_directs + len(f_users)
    log("F.cnt admin.direct_referrals_count incremented by N",
        end_directs == expected_directs,
        f"got={end_directs}, expected={expected_directs} (start={f_start_directs}+{len(f_users)})")

    # If the cycle aligned, payout_l1 should have been credited at least once
    cycle_count = 0
    # how many full cycles crossed
    s, e = f_start_directs, end_directs
    cycle_count = (e // directs_required) - (s // directs_required)
    print(f"cycle_count (full payouts crossed): {cycle_count}")
    if cycle_count > 0:
        expected_credit = cycle_count * payout_l1
        actual_credit = end_wallet - f_start_wallet
        log(f"F.payout admin wallet credited by ≥ {expected_credit} (cycle*payout_l1)",
            actual_credit >= expected_credit - 0.01,
            f"got_delta={actual_credit}, expected≥{expected_credit}")

        # Verify referral_payout transaction exists for admin with L1
        rt = get(f"/admin/transactions?user_id={admin_id}", headers=headers(admin_token))
        # try /admin/transactions — depending on impl. fallback to /transactions/me-style filter
        # We don't have a per-user tx admin endpoint guaranteed; use /admin/transactions
        if rt.status_code != 200:
            rt = get("/admin/transactions", headers=headers(admin_token))
        if rt.status_code == 200:
            txs = rt.json() if isinstance(rt.json(), list) else rt.json().get("items", [])
            l1_txs = [t for t in txs if t.get("user_id") == admin_id
                      and t.get("type") == "referral_payout"
                      and (t.get("level") == 1 or "L1" in str(t.get("description", "")) or "Level 1" in str(t.get("description", "")))]
            log("F.tx referral_payout L1 transaction exists for admin",
                len(l1_txs) >= cycle_count,
                f"found={len(l1_txs)} cycles={cycle_count}")
        else:
            log("F.tx /admin/transactions reachable", False, f"status={rt.status_code}")
    else:
        print("F.payout: cycle did not align — skipping payout assertion (per spec).")

    # ---------------- G. REGRESSION ----------------
    print("\n--- G. REGRESSION ---")
    rd1 = get("/admin/withdrawals/digest", headers=headers(admin_token))
    log("G.1 GET /admin/withdrawals/digest → 200", rd1.status_code == 200, f"status={rd1.status_code}")

    rb1 = get("/branding")
    log("G.2 GET /branding (no auth) → 200", rb1.status_code == 200, f"status={rb1.status_code}")

    rl1 = post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    log("G.3 admin@app.com login still 200", rl1.status_code == 200, f"status={rl1.status_code}")

    # G.4 Manual approval path: register a fresh user, toggle auto-approve OFF,
    # pay (no auto-approve), then super_admin manual approve.
    # Toggle off
    rt_off = requests.put(f"{BASE}/admin/settings",
                          headers=headers(admin_token),
                          json={"auto_approve_on_payment": False}, timeout=15)
    if rt_off.status_code == 200:
        em_g = fresh_email("gma")
        rg = register("Manual Mike", em_g, omit=True)
        if rg.status_code == 200:
            ug = rg.json()["user"]; tg = rg.json()["token"]
            created_user_ids.append(ug["id"])
            ok_p, _, vr_g = pay_via_razorpay(tg)
            if ok_p:
                # pending now
                rapp = post(f"/admin/approvals/{ug['id']}/approve", headers=headers(admin_token), json={})
                log("G.4 manual /admin/approvals/{id}/approve → 200", rapp.status_code == 200,
                    f"status={rapp.status_code} body={rapp.text[:120]}")
            else:
                log("G.4 manual approval (pay step failed)", False)
        else:
            log("G.4 register for manual path", False, f"status={rg.status_code}")
        # toggle back on
        requests.put(f"{BASE}/admin/settings",
                     headers=headers(admin_token),
                     json={"auto_approve_on_payment": True}, timeout=15)
    else:
        log("G.4 toggle auto_approve OFF prereq", False, f"status={rt_off.status_code} body={rt_off.text[:200]}")

    # ---------------- H. CLEANUP ----------------
    print("\n--- H. CLEANUP ---")
    cleanup(admin_token)

    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"RESULT: {passed}/{total} checks passed")
    print("=" * 70)
    fails = [(l, d) for l, ok, d in results if not ok]
    if fails:
        print("\nFAILURES:")
        for l, d in fails:
            print(f"  - {l}: {d}")
    return passed == total


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
