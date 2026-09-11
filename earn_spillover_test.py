"""
EARN spillover (forced-matrix BFS) regression test.
Tests get_admin_sponsor() spillover behavior in /auth/register and
/auth/google/exchange flows.

Scenarios A–I per review request. Run with:
    python3 /app/earn_spillover_test.py
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
RZP_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

results = []          # (label, ok, detail)
created_user_ids = [] # for cleanup
ORIGINAL_DIRECTS = None  # to restore at end


def log(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
    results.append((label, ok, detail))


def post(url, **kw):
    return requests.post(BASE + url, timeout=30, **kw)


def get(url, **kw):
    return requests.get(BASE + url, timeout=30, **kw)


def put(url, **kw):
    return requests.put(BASE + url, timeout=30, **kw)


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


def find_user_by_email(admin_token, email):
    for u in list_users(admin_token):
        if u.get("email") == email.lower():
            return u
    return None


def find_user_by_id(admin_token, uid):
    for u in list_users(admin_token):
        if u.get("id") == uid:
            return u
    return None


def fresh_email(prefix="sp"):
    return f"{prefix}.{int(time.time())}.{secrets.token_hex(3)}@example.com"


def register(name, email, password="StrongP@ss1", referral_code=None, omit=False):
    body = {"name": name, "email": email, "password": password}
    if not omit:
        if referral_code is not None:
            body["referral_code"] = referral_code
    return post("/auth/register", json=body)


def pay_via_razorpay(user_token):
    """Create live order, fake a payment_id, sign with our HMAC secret, verify."""
    r = post("/payment/create-order", headers=headers(user_token))
    if r.status_code != 200:
        return False, f"create-order failed {r.status_code} {r.text}", None
    order = r.json()
    if order.get("is_mock"):
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


def register_and_approve(name, email, referral_code=None, omit=False):
    """Register + /payment/verify (auto-approve) → return (user_obj, token) or (None, None)."""
    rr = register(name, email, referral_code=referral_code, omit=omit)
    if rr.status_code != 200:
        return None, None, rr
    body = rr.json()
    u = body["user"]; tok = body["token"]
    created_user_ids.append(u["id"])
    ok_p, err, vr = pay_via_razorpay(tok)
    if not ok_p:
        return u, tok, vr
    return u, tok, vr


def predict_spillover_sponsor(admin_token, admin_id, n):
    """Mimic backend BFS: returns the user that get_admin_sponsor() would pick."""
    users = list_users(admin_token)
    admin = next((u for u in users if u.get("id") == admin_id), None)
    if not admin:
        return None
    if int(admin.get("direct_referrals_count") or 0) < n:
        return admin
    # BFS
    frontier = [admin_id]
    visited = {admin_id}
    for _ in range(12):
        if not frontier:
            break
        children = [u for u in users
                    if u.get("sponsor_id") in frontier and u.get("role") == "user"]
        children.sort(key=lambda u: u.get("created_at", ""))
        if not children:
            break
        for c in children:
            if int(c.get("direct_referrals_count") or 0) < n:
                return c
        frontier = [c["id"] for c in children if c["id"] not in visited]
        visited.update(frontier)
    return admin


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
    print("EARN spillover (forced-matrix BFS) regression test")
    print("=" * 70)

    admin_token, admin_user = admin_login()
    log("admin@app.com login (super_admin)", admin_user.get("role") == "admin",
        f"id={admin_user['id'][:8]}")

    # ---------------- PRECONDITION: read settings + admin snapshot ----------------
    print("\n--- PRECONDITION: snapshot admin + settings ---")
    rs = get("/admin/settings", headers=headers(admin_token))
    settings = rs.json() if rs.status_code == 200 else {}
    global ORIGINAL_DIRECTS
    ORIGINAL_DIRECTS = int(settings.get("directs_required", 5))
    payout_l1 = float(settings.get("payout_l1", 300))
    payout_l2 = float(settings.get("payout_l2", 100))
    print(f"original settings: directs_required={ORIGINAL_DIRECTS}, payout_l1={payout_l1}, "
          f"payout_l2={payout_l2}, registration_fee={settings.get('registration_fee')}")

    # Force directs_required=5 for clean math
    N = 5
    rput = put("/admin/settings", headers=headers(admin_token),
               json={"directs_required": N})
    log(f"PRECONDITION PUT directs_required={N}", rput.status_code == 200,
        f"status={rput.status_code} body={rput.text[:120]}")

    admin_row = find_user_by_email(admin_token, ADMIN_EMAIL)
    admin_id = admin_row["id"]
    D = int(admin_row.get("direct_referrals_count") or 0)
    admin_wallet_start = float(admin_row.get("wallet_balance") or 0.0)
    slots_to_fill = (N - (D % N)) % N
    print(f"admin: id={admin_id[:8]} direct_referrals_count={D} wallet={admin_wallet_start} "
          f"slots_to_fill={slots_to_fill}")
    log("admin.referral_code == 'EARN'", admin_row.get("referral_code") == "EARN",
        f"got={admin_row.get('referral_code')}")

    # ---------------- A. PHASE 1 — Pre-fill until admin reaches/exceeds N ----------------
    # NOTE: Implementation checks admin.direct_referrals_count < N (absolute
    # threshold), not (count % N). If admin's count is already >= N at test
    # start (e.g., from prior test runs), Phase 1 has 0 slots; BFS triggers
    # from the first registration. We dynamically predict each expected sponsor
    # using the same BFS algorithm the backend uses and verify every signup
    # lands on the predicted sponsor.
    print(f"\n--- A. PHASE 1 — pre-fill (D={D}, N={N}) ---")
    if D < N:
        slots_phase1 = N - D
        print(f"Phase 1 active: {slots_phase1} signups will go to admin until count reaches N")
    else:
        slots_phase1 = 0
        print(f"Phase 1 already complete (D={D} >= N={N}); BFS will fire from first signup")

    # Register up to max(slots_phase1, 3) signups so we have substrate for
    # later phases in either case. Use prediction for verification.
    a_signups_target = max(slots_phase1, 1)
    phase1_users = []
    for i in range(a_signups_target):
        predicted = predict_spillover_sponsor(admin_token, admin_id, N)
        em = fresh_email(f"p1u{i}")
        u, tok, vr = register_and_approve(f"PhaseA U{i}", em, omit=True)
        if not u:
            log(f"A.{i+1} register+verify PhaseA U{i}", False, str(vr)[:200])
            continue
        # Expected: sponsor_id == predicted; if predicted is admin, referred_by == EARN
        log(f"A.{i+1} U{i} sponsor_id matches BFS prediction",
            u.get("sponsor_id") == predicted.get("id"),
            f"got={(u.get('sponsor_id') or '')[:8]} predicted={(predicted.get('id') or '')[:8]}")
        if predicted.get("id") == admin_id:
            log(f"A.{i+1} U{i} referred_by == 'EARN' (predicted admin)",
                u.get("referred_by") == "EARN",
                f"got={u.get('referred_by')}")
        else:
            log(f"A.{i+1} U{i} referred_by == predicted.referral_code",
                u.get("referred_by") == predicted.get("referral_code"),
                f"got={u.get('referred_by')} expected={predicted.get('referral_code')}")
        phase1_users.append(u)

    admin_after_p1 = find_user_by_email(admin_token, ADMIN_EMAIL)
    admin_directs_p1 = int(admin_after_p1.get("direct_referrals_count") or 0)
    log("A.cnt admin.direct_referrals_count >= N (Phase 2 active)",
        admin_directs_p1 >= N,
        f"got={admin_directs_p1}, N={N}")

    # ---------------- B. PHASE 2 — first spillover wave (under U1) ----------------
    print("\n--- B. PHASE 2 — first spillover wave ---")
    # Predict sponsor (U1)
    u1 = predict_spillover_sponsor(admin_token, admin_id, N)
    if not u1 or u1.get("id") == admin_id:
        log("B.predict U1 (earliest L1 with open slot)", False,
            f"got={u1.get('id') if u1 else None} (admin still has slots?)")
        cleanup(admin_token)
        return False
    print(f"predicted U1: id={u1['id'][:8]} email={u1.get('email')} "
          f"directs={u1.get('direct_referrals_count')}")
    u1_directs_before = int(u1.get("direct_referrals_count") or 0)

    em_n = fresh_email("p2new")
    u_new, tok_new, vr_new = register_and_approve("U_new spillover", em_n, omit=True)
    if not u_new:
        log("B.1 register U_new spillover", False, str(vr_new)[:200])
    else:
        log("B.1 register U_new spillover → 200", True)
        log("B.2 U_new.sponsor_id == U1.id (NOT admin)",
            u_new.get("sponsor_id") == u1["id"] and u_new.get("sponsor_id") != admin_id,
            f"got={(u_new.get('sponsor_id') or '')[:8]} u1={u1['id'][:8]} admin={admin_id[:8]}")
        log("B.3 U_new.referred_by == U1.referral_code (NOT 'EARN')",
            u_new.get("referred_by") == u1.get("referral_code")
            and u_new.get("referred_by") != "EARN",
            f"got={u_new.get('referred_by')} u1_code={u1.get('referral_code')}")

        # U1 direct count incremented; admin's unchanged
        u1_after = find_user_by_id(admin_token, u1["id"])
        admin_after_b = find_user_by_email(admin_token, ADMIN_EMAIL)
        log("B.4 U1.direct_referrals_count incremented by 1",
            int(u1_after.get("direct_referrals_count") or 0) == u1_directs_before + 1,
            f"got={u1_after.get('direct_referrals_count')} expected={u1_directs_before+1}")
        log("B.5 admin.direct_referrals_count unchanged",
            int(admin_after_b.get("direct_referrals_count") or 0) == admin_directs_p1,
            f"got={admin_after_b.get('direct_referrals_count')} expected={admin_directs_p1}")

        # U1 received "New referral" notification: log in as U1? We don't have U1's token.
        # Check via /admin/users notifications? notifications/me requires auth as that user.
        # Skip notification check here OR query db directly is not allowed; use admin endpoint.
        # We'll attempt /admin/notifications? endpoint may not exist. Use /admin/users count or skip.
        # Try /notifications/me as super_admin token won't return U1 notifs. Skip.

    # ---------------- C. CONTINUE FILLING U1 ----------------
    print("\n--- C. CONTINUE FILLING U1 (4 more) ---")
    u1_wallet_before_c = float(find_user_by_id(admin_token, u1["id"]).get("wallet_balance") or 0.0)
    admin_wallet_before_c = float(find_user_by_email(admin_token, ADMIN_EMAIL).get("wallet_balance") or 0.0)

    fills_to_complete_u1 = N - (u1_directs_before + 1)  # U1 already has +1 from B
    print(f"need {fills_to_complete_u1} more to complete U1's L1 cycle")
    c_users = []
    for i in range(fills_to_complete_u1):
        em = fresh_email(f"p2c{i}")
        u, tok, vr = register_and_approve(f"PhaseC U{i}", em, omit=True)
        if not u:
            log(f"C.{i+1} register+verify", False, str(vr)[:200])
            continue
        c_users.append(u)
        log(f"C.{i+1} sponsor_id == U1.id",
            u.get("sponsor_id") == u1["id"],
            f"got={(u.get('sponsor_id') or '')[:8]} expected={u1['id'][:8]}")

    # Verify U1 reached N directs and earned L1
    u1_after_c = find_user_by_id(admin_token, u1["id"])
    u1_directs_c = int(u1_after_c.get("direct_referrals_count") or 0)
    u1_wallet_after_c = float(u1_after_c.get("wallet_balance") or 0.0)
    log("C.cnt U1.direct_referrals_count == N",
        u1_directs_c == N,
        f"got={u1_directs_c} expected={N}")
    if fills_to_complete_u1 > 0:
        # U1 should have earned at least payout_l1 (one cycle crossed)
        delta_u1 = u1_wallet_after_c - u1_wallet_before_c
        log(f"C.payout U1 wallet credited by ≥ {payout_l1}",
            delta_u1 >= payout_l1 - 0.01,
            f"got_delta={delta_u1} expected≥{payout_l1}")

        # Admin should have received L2 commission for each of the C signups
        admin_after_c = find_user_by_email(admin_token, ADMIN_EMAIL)
        admin_wallet_after_c = float(admin_after_c.get("wallet_balance") or 0.0)
        delta_admin = admin_wallet_after_c - admin_wallet_before_c
        if payout_l2 > 0:
            expected_admin_l2 = payout_l2 * fills_to_complete_u1
            log(f"C.cascade admin wallet credited L2 ≥ {expected_admin_l2}",
                delta_admin >= expected_admin_l2 - 0.01,
                f"got_delta={delta_admin} expected≥{expected_admin_l2}")

        # Verify U1 has a referral_payout transaction
        rt = get("/admin/transactions", headers=headers(admin_token))
        if rt.status_code == 200:
            txs = rt.json() if isinstance(rt.json(), list) else rt.json().get("items", [])
            u1_l1_txs = [t for t in txs if t.get("user_id") == u1["id"]
                         and t.get("type") == "referral_payout"
                         and (t.get("level") == 1 or "Level 1" in str(t.get("description", "")))]
            log("C.tx referral_payout L1 transaction exists for U1",
                len(u1_l1_txs) >= 1,
                f"found={len(u1_l1_txs)}")

    # ---------------- D. SECOND SPILLOVER → U2 ----------------
    print("\n--- D. SECOND SPILLOVER → U2 ---")
    # Now U1 is full → next spillover should pick the next earliest admin direct
    u2 = predict_spillover_sponsor(admin_token, admin_id, N)
    if not u2 or u2.get("id") == admin_id or u2.get("id") == u1["id"]:
        log("D.predict U2 (next earliest L1 with open slot)", False,
            f"got={u2.get('id') if u2 else None}")
    else:
        print(f"predicted U2: id={u2['id'][:8]} email={u2.get('email')} "
              f"directs={u2.get('direct_referrals_count')}")
        u2_directs_before = int(u2.get("direct_referrals_count") or 0)

        em_n2 = fresh_email("p2new2")
        u_new2, tok_new2, vr_new2 = register_and_approve("U_new2 spillover", em_n2, omit=True)
        if not u_new2:
            log("D.1 register U_new2", False, str(vr_new2)[:200])
        else:
            log("D.1 register U_new2 → 200", True)
            log("D.2 U_new2.sponsor_id == U2.id",
                u_new2.get("sponsor_id") == u2["id"],
                f"got={(u_new2.get('sponsor_id') or '')[:8]} expected_u2={u2['id'][:8]}")
            u2_after = find_user_by_id(admin_token, u2["id"])
            log("D.3 U2.direct_referrals_count incremented by 1",
                int(u2_after.get("direct_referrals_count") or 0) == u2_directs_before + 1,
                f"got={u2_after.get('direct_referrals_count')} expected={u2_directs_before+1}")

    # ---------------- E. EXPLICIT EARN CODE → STILL SPILLOVER ----------------
    print("\n--- E. EXPLICIT 'EARN' CODE → STILL SPILLOVER (NOT admin) ---")
    # Predict sponsor: should still be U2 (or whoever has open slot)
    expected_e_sponsor = predict_spillover_sponsor(admin_token, admin_id, N)
    em_n3 = fresh_email("eearn")
    u_new3, tok_new3, vr_new3 = register_and_approve("U_new3 EARN", em_n3,
                                                     referral_code="EARN")
    if not u_new3:
        log("E.1 register U_new3 with referral_code='EARN'", False, str(vr_new3)[:200])
    else:
        log("E.1 register U_new3 with referral_code='EARN' → 200", True)
        log("E.2 U_new3.sponsor_id != admin.id (spillover applied)",
            u_new3.get("sponsor_id") != admin_id,
            f"got={(u_new3.get('sponsor_id') or '')[:8]} admin={admin_id[:8]}")
        if expected_e_sponsor:
            log("E.3 U_new3.sponsor_id == predicted (earliest with open slot)",
                u_new3.get("sponsor_id") == expected_e_sponsor.get("id"),
                f"got={(u_new3.get('sponsor_id') or '')[:8]} predicted={expected_e_sponsor['id'][:8]}")

    # ---------------- F. EXPLICIT NON-EARN CODE → CLASSIC PATH ----------------
    print("\n--- F. EXPLICIT NON-EARN CODE → CLASSIC PATH (NO SPILLOVER) ---")
    # Pick a spilled-over descendant with direct_referrals_count = 0
    # (e.g., one of U1's downline c_users)
    candidate = None
    for cu in c_users:
        cu_full = find_user_by_id(admin_token, cu["id"])
        if cu_full and int(cu_full.get("direct_referrals_count") or 0) == 0:
            candidate = cu_full
            break
    if not candidate and u_new:
        # Fallback: u_new from B (also under U1, direct_count=0)
        candidate = find_user_by_id(admin_token, u_new["id"])
    if not candidate:
        log("F.find descendant with direct_referrals_count=0", False, "no candidate")
    else:
        cand_code = candidate.get("referral_code")
        cand_id = candidate.get("id")
        cand_directs_before = int(candidate.get("direct_referrals_count") or 0)
        print(f"F candidate: id={cand_id[:8]} code={cand_code} directs={cand_directs_before}")
        em_n4 = fresh_email("fclass")
        u_new4, tok_new4, vr_new4 = register_and_approve("U_new4 classic", em_n4,
                                                         referral_code=cand_code)
        if not u_new4:
            log(f"F.1 register U_new4 with code={cand_code}", False, str(vr_new4)[:200])
        else:
            log("F.1 register U_new4 with non-EARN valid code → 200", True)
            log("F.2 U_new4.sponsor_id == candidate.id (DIRECT, not BFS-replaced)",
                u_new4.get("sponsor_id") == cand_id,
                f"got={(u_new4.get('sponsor_id') or '')[:8]} expected={cand_id[:8]}")
            log("F.3 U_new4.referred_by == candidate.referral_code",
                u_new4.get("referred_by") == cand_code,
                f"got={u_new4.get('referred_by')} expected={cand_code}")
            cand_after = find_user_by_id(admin_token, cand_id)
            log("F.4 candidate.direct_referrals_count incremented by 1",
                int(cand_after.get("direct_referrals_count") or 0) == cand_directs_before + 1,
                f"got={cand_after.get('direct_referrals_count')} expected={cand_directs_before+1}")

    # ---------------- G. INVALID CODE → 400 ----------------
    print("\n--- G. INVALID CODE → 400 ---")
    em_g = fresh_email("ginv")
    rg = register("BogusCarol", em_g, referral_code="BOGUS_CODE_12345")
    log("G.1 register with invalid code → 400", rg.status_code == 400,
        f"status={rg.status_code} body={rg.text[:120]}")
    if rg.status_code == 400:
        det = rg.json().get("detail", "")
        log("G.2 detail contains 'Invalid referral code'",
            "Invalid referral code" in det, f"detail={det}")

    # ---------------- H. REGRESSION ----------------
    print("\n--- H. REGRESSION ---")
    rd1 = get("/admin/withdrawals/digest", headers=headers(admin_token))
    log("H.1 GET /admin/withdrawals/digest → 200", rd1.status_code == 200,
        f"status={rd1.status_code}")
    rb1 = get("/branding")
    log("H.2 GET /branding (no auth) → 200", rb1.status_code == 200,
        f"status={rb1.status_code}")
    rl1 = post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    log("H.3 admin@app.com login → 200", rl1.status_code == 200, f"status={rl1.status_code}")

    # ---------------- I. CLEANUP ----------------
    print("\n--- I. CLEANUP ---")
    cleanup(admin_token)
    # Reset directs_required back to original (5 anyway)
    rrst = put("/admin/settings", headers=headers(admin_token),
               json={"directs_required": ORIGINAL_DIRECTS})
    log(f"I.1 reset directs_required={ORIGINAL_DIRECTS}", rrst.status_code == 200,
        f"status={rrst.status_code}")

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
