"""
NetworkPay backend test — Withdrawal Settlement Enhancements.

Covers scenarios A–J from the review request:
  A. SETUP 4 users, credit wallets, submit withdrawals
  B. Digest endpoint shows pending counts
  C. Reject w1 with reason → refund + notification
  D. Approve w2 → complete w2 with UTR
  E. approve-and-complete w3 with UTR (instant)
  F. Batch settle with reference_prefix
  G. RBAC (finance/manager allowed, regular 403, no-auth 401)
  H. Edge cases: empty ids, complete on pending, nonexistent wid
  I. Regression
  J. Cleanup
"""
import os
import uuid
import requests

BASE = os.environ.get("BACKEND_URL") or "https://slangcart-tracking.preview.emergentagent.com"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

PASSED = []
FAILED = []


def _log(name, ok, detail=""):
    (PASSED if ok else FAILED).append((name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"{mark}  {name}" + (f"  -- {detail[:200]}" if (not ok and detail) else ""))


def _h(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def post(path, token=None, body=None):
    return requests.post(API + path, headers=_h(token), json=body or {}, timeout=30)

def get(path, token=None, params=None):
    return requests.get(API + path, headers=_h(token), params=params, timeout=30)

def patch(path, token=None, body=None):
    return requests.patch(API + path, headers=_h(token), json=body or {}, timeout=30)

def delete(path, token=None):
    return requests.delete(API + path, headers=_h(token), timeout=30)


def login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    if r.status_code != 200:
        return None, None
    j = r.json()
    return j.get("token"), j.get("user")


ADMIN_REF = None

def register(name, email, pw, referral=None):
    body = {"name": name, "email": email, "password": pw}
    ref = referral if referral is not None else ADMIN_REF
    if ref:
        body["referral_code"] = ref
    r = requests.post(f"{API}/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        return None, None, r
    j = r.json()
    return j.get("token"), j.get("user"), r


def credit_wallet(admin_token, uid, amount, reason="Test top-up"):
    # Endpoint expects {amount, type:"credit"|"debit", reason}
    return post(f"/admin/users/{uid}/wallet", admin_token,
                {"amount": amount, "type": "credit", "reason": reason})


def submit_withdrawal(user_token, amount, upi_id):
    # First set UPI id on user
    rb = post("/users/me/bank", user_token, {"upi_id": upi_id})
    if rb.status_code != 200:
        return rb
    return post("/withdrawals", user_token, {"amount": amount})


def make_approved_user(admin_token, name, email, pw):
    """Create user, pay reg fee, approve via super_admin."""
    t, u, r = register(name, email, pw)
    if not t:
        return None, None, r
    rp = post("/payment/register-fee", t)
    if rp.status_code != 200:
        return t, u, rp
    rapp = post(f"/admin/approvals/{u['id']}/approve", admin_token)
    if rapp.status_code != 200:
        return t, u, rapp
    # refresh
    t2, u2 = login(email, pw)
    return t2 or t, u2 or u, rapp


def summary():
    print("\n========== RESULT ==========")
    print(f"PASSED: {len(PASSED)}")
    print(f"FAILED: {len(FAILED)}")
    for n, d in FAILED:
        print(f"  FAIL  {n}  -- {d[:300]}")
    return 0 if not FAILED else 1


def main():
    rand = uuid.uuid4().hex[:8]
    print(f"Testing against: {API}\n")

    # -------- A. SETUP --------
    t_super, u_super = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    _log("A0. Super admin login", t_super is not None)
    if not t_super:
        return summary()
    global ADMIN_REF
    ADMIN_REF = u_super.get("referral_code")

    # Digest baseline (before we add anything)
    r = get("/admin/withdrawals/digest", t_super)
    _log("A1. GET /admin/withdrawals/digest baseline -> 200", r.status_code == 200, r.text[:200])
    baseline = r.json() if r.status_code == 200 else {}
    base_pending = int(baseline.get("pending", 0) or 0)
    base_processing = int(baseline.get("processing", 0) or 0)
    base_pending_amt = float(baseline.get("pending_amount", 0) or 0)
    base_settled_today = int(baseline.get("settled_today", 0) or 0)

    # Create 4 throwaway users
    users = []
    for i in range(1, 5):
        email = f"wsu{i}_{rand}@test.com"
        pw = "User@12345"
        name = ["Aarav Sharma", "Priya Iyer", "Rohit Verma", "Neha Kapoor"][i - 1]
        t, u, resp = make_approved_user(t_super, name, email, pw)
        if not t:
            _log(f"A{i}. Setup user {i}", False, f"status={getattr(resp, 'status_code', '?')} {getattr(resp, 'text', '')[:200]}")
            return summary()
        # Credit wallet 1000
        rc = credit_wallet(t_super, u["id"], 1000, "Test credit")
        ok_credit = rc.status_code == 200
        _log(f"A{i}a. Credit ₹1000 to U{i}", ok_credit, rc.text[:200])
        if not ok_credit:
            return summary()
        users.append({"token": t, "user": u, "email": email, "password": pw})

    # Submit ₹200 withdrawal from each
    wids = []
    for i, ud in enumerate(users, 1):
        rw = submit_withdrawal(ud["token"], 200, f"u{i}_{rand}@upi")
        ok = rw.status_code == 200
        _log(f"A{i}b. U{i} submit ₹200 withdrawal -> 200", ok, rw.text[:200])
        if not ok:
            return summary()
        j = rw.json()
        wids.append(j.get("id"))
        _log(f"A{i}c. Withdrawal status=pending", j.get("status") == "pending", str(j.get("status")))

    w1, w2, w3, w4 = wids

    # -------- B. DIGEST --------
    r = get("/admin/withdrawals/digest", t_super)
    _log("B1. GET /admin/withdrawals/digest after 4 submits -> 200", r.status_code == 200, r.text[:200])
    d = r.json() if r.status_code == 200 else {}
    _log("B2. digest.pending >= baseline+4",
         int(d.get("pending", 0)) >= base_pending + 4, f"got {d.get('pending')} base={base_pending}")
    _log("B3. digest.pending_amount >= baseline+800",
         float(d.get("pending_amount", 0)) >= base_pending_amt + 800 - 0.001,
         f"got {d.get('pending_amount')} base={base_pending_amt}")
    _log("B4. digest.processing == baseline (unchanged)",
         int(d.get("processing", 0)) == base_processing, f"got {d.get('processing')} base={base_processing}")
    _log("B5. digest has all keys",
         all(k in d for k in ("pending", "processing", "pending_amount", "processing_amount",
                              "settled_today", "settled_today_amount", "oldest_pending_age_hours")),
         f"keys={sorted(d.keys())}")
    opah = d.get("oldest_pending_age_hours")
    _log("B6. oldest_pending_age_hours is number >= 0",
         isinstance(opah, (int, float)) and opah >= 0, f"got {opah!r}")

    # -------- C. REJECT WITH REASON (w1) --------
    # U1 wallet should currently be 800 (credited 1000, locked 200 for withdrawal)
    r = get("/auth/me", users[0]["token"]).json()
    _log("C0. U1 wallet == 800 before reject", r.get("wallet_balance") == 800, f"got {r.get('wallet_balance')}")

    rj = post(f"/admin/withdrawals/{w1}/reject", t_super, {"reason": "Invalid UPI"})
    _log("C1. POST /admin/withdrawals/{w1}/reject {reason} -> 200",
         rj.status_code == 200, rj.text[:200])
    _log("C2. reject response carries rejection_reason=='Invalid UPI'",
         rj.status_code == 200 and rj.json().get("rejection_reason") == "Invalid UPI",
         rj.text[:200])

    # Wallet refunded to 1000
    r = get("/auth/me", users[0]["token"]).json()
    _log("C3. U1 wallet refunded to 1000", r.get("wallet_balance") == 1000, f"got {r.get('wallet_balance')}")

    # Persist check via admin list
    rlist = get("/admin/withdrawals", t_super, params={"status": "rejected"})
    if rlist.status_code == 200:
        entry = next((x for x in rlist.json() if x.get("id") == w1), None)
        _log("C4. withdrawal doc has status=rejected + rejection_reason",
             bool(entry) and entry.get("status") == "rejected"
             and entry.get("rejection_reason") == "Invalid UPI",
             str(entry)[:250])
    else:
        _log("C4. GET /admin/withdrawals?status=rejected", False, rlist.text[:200])

    # Notification body contains reason
    rn = get("/notifications/me", users[0]["token"])
    if rn.status_code == 200:
        items = rn.json() if isinstance(rn.json(), list) else rn.json().get("items", [])
        body_ok = any(
            (it.get("title") == "Withdrawal rejected") and ("Invalid UPI" in (it.get("body") or ""))
            for it in items
        )
        _log("C5. Notification 'Withdrawal rejected' body contains reason",
             body_ok, f"items={len(items)}")
    else:
        _log("C5. GET /notifications/me", False, rn.text[:200])

    # Re-reject → 400
    rj2 = post(f"/admin/withdrawals/{w1}/reject", t_super, {"reason": "Again"})
    _log("C6. Re-POST reject on already rejected -> 400",
         rj2.status_code == 400, f"{rj2.status_code} {rj2.text[:200]}")

    # -------- D. COMPLETE WITH UTR (w2) --------
    ra = post(f"/admin/withdrawals/{w2}/approve", t_super)
    _log("D1. POST /admin/withdrawals/{w2}/approve -> 200", ra.status_code == 200, ra.text[:200])

    rc = post(f"/admin/withdrawals/{w2}/complete", t_super, {"reference_number": "UTR12345"})
    _log("D2. POST /admin/withdrawals/{w2}/complete {UTR12345} -> 200",
         rc.status_code == 200, rc.text[:200])
    if rc.status_code == 200:
        _log("D3. complete response reference_number=='UTR12345'",
             rc.json().get("reference_number") == "UTR12345", rc.text[:200])

    # Verify withdrawal doc
    rlist = get("/admin/withdrawals", t_super, params={"status": "success"})
    entry = None
    if rlist.status_code == 200:
        entry = next((x for x in rlist.json() if x.get("id") == w2), None)
    _log("D4. withdrawal w2 status=success + reference_number=UTR12345",
         bool(entry) and entry.get("status") == "success" and entry.get("reference_number") == "UTR12345",
         str(entry)[:250])

    # Verify transaction has UTR and description contains ref
    rt = get("/transactions/me", users[1]["token"])
    tx_match = None
    if rt.status_code == 200:
        txs = rt.json()
        for t in txs:
            if t.get("type") == "withdrawal" and t.get("status") == "success" and t.get("amount") == -200:
                if t.get("reference_number") == "UTR12345" or "UTR12345" in (t.get("description") or ""):
                    tx_match = t
                    break
    _log("D5. U2 transaction has success status + reference_number=UTR12345",
         bool(tx_match) and tx_match.get("reference_number") == "UTR12345",
         str(tx_match)[:250])
    _log("D6. U2 transaction description mentions 'UTR12345'",
         bool(tx_match) and "UTR12345" in (tx_match.get("description") or ""),
         str(tx_match)[:250] if tx_match else "none")

    # Notification body contains UTR UTR12345
    rn = get("/notifications/me", users[1]["token"])
    body_ok = False
    if rn.status_code == 200:
        items = rn.json() if isinstance(rn.json(), list) else rn.json().get("items", [])
        body_ok = any(
            (it.get("title") == "Withdrawal successful") and ("UTR12345" in (it.get("body") or ""))
            for it in items
        )
    _log("D7. U2 notification 'Withdrawal successful' body mentions 'UTR12345'",
         body_ok, "")

    # -------- E. INSTANT APPROVE+COMPLETE (w3) --------
    re_ = post(f"/admin/withdrawals/{w3}/approve-and-complete", t_super,
               {"reference_number": "INST-001"})
    _log("E1. POST /admin/withdrawals/{w3}/approve-and-complete -> 200",
         re_.status_code == 200, re_.text[:200])

    # Re-call → 400
    re2 = post(f"/admin/withdrawals/{w3}/approve-and-complete", t_super,
               {"reference_number": "INST-002"})
    _log("E2. Re-POST approve-and-complete -> 400",
         re2.status_code == 400, f"{re2.status_code} {re2.text[:200]}")

    # Verify via admin list
    rlist = get("/admin/withdrawals", t_super, params={"status": "success"})
    entry3 = None
    if rlist.status_code == 200:
        entry3 = next((x for x in rlist.json() if x.get("id") == w3), None)
    _log("E3. withdrawal w3 status=success + instant_settle=true + reference_number=INST-001",
         bool(entry3) and entry3.get("status") == "success"
         and entry3.get("instant_settle") is True
         and entry3.get("reference_number") == "INST-001",
         str(entry3)[:250])

    # U3 txs: exactly one withdrawal tx for -200 with status=success and reference
    rt = get("/transactions/me", users[2]["token"])
    count_success = 0
    count_processing = 0
    tx_inst = None
    if rt.status_code == 200:
        for t in rt.json():
            if t.get("type") == "withdrawal" and t.get("amount") == -200:
                if t.get("status") == "success":
                    count_success += 1
                    if "INST-001" in (t.get("description") or "") or t.get("reference_number") == "INST-001":
                        tx_inst = t
                elif t.get("status") == "processing":
                    count_processing += 1
    _log("E4. U3 has exactly 1 withdrawal success tx with INST-001",
         count_success == 1 and tx_inst is not None, f"success={count_success} tx={tx_inst}")
    _log("E5. U3 has NO processing withdrawal tx remaining",
         count_processing == 0, f"processing={count_processing}")

    # -------- F. BATCH SETTLE --------
    # U1 has refunded 1000, U4 has 800. Submit new withdrawals from U1 and U4.
    rwb1 = submit_withdrawal(users[0]["token"], 150, f"u1b_{rand}@upi")
    rwb2 = submit_withdrawal(users[3]["token"], 150, f"u4b_{rand}@upi")
    _log("F1. U1 new withdrawal -> 200", rwb1.status_code == 200, rwb1.text[:200])
    _log("F2. U4 new withdrawal -> 200", rwb2.status_code == 200, rwb2.text[:200])
    wb1 = rwb1.json().get("id") if rwb1.status_code == 200 else None
    wb2 = rwb2.json().get("id") if rwb2.status_code == 200 else None

    rbatch = post("/admin/withdrawals/batch/complete", t_super,
                  {"ids": [wb1, wb2, "fake-id-xxx"], "reference_prefix": "BATCH-2025-04"})
    _log("F3. POST /admin/withdrawals/batch/complete -> 200",
         rbatch.status_code == 200, rbatch.text[:200])
    if rbatch.status_code == 200:
        jb = rbatch.json()
        _log("F4. settled_count == 2", jb.get("settled_count") == 2, str(jb))
        _log("F5. skipped_count == 1", jb.get("skipped_count") == 1, str(jb))
        _log("F6. skipped includes fake-id with reason 'not_found'",
             any(s.get("id") == "fake-id-xxx" and s.get("reason") == "not_found"
                 for s in (jb.get("skipped") or [])),
             str(jb.get("skipped")))
        _log("F7. settled list contains both batch wids",
             set(jb.get("settled") or []) == {wb1, wb2}, str(jb.get("settled")))

    # Verify reference_number prefix and batch_settled/instant_settle flags
    rlist = get("/admin/withdrawals", t_super, params={"status": "success"})
    items = rlist.json() if rlist.status_code == 200 else []
    for tag, wid in (("wb1", wb1), ("wb2", wb2)):
        e = next((x for x in items if x.get("id") == wid), None)
        ok = bool(e) and e.get("status") == "success" \
            and isinstance(e.get("reference_number"), str) \
            and e.get("reference_number").startswith("BATCH-2025-04-") \
            and e.get("batch_settled") is True \
            and e.get("instant_settle") is True
        _log(f"F8. {tag} settled: status=success, ref prefix BATCH-2025-04-, batch_settled+instant_settle",
             ok, str(e)[:300])
        # ref length is prefix + "-" + 8 chars
        if e and e.get("reference_number"):
            expected = f"BATCH-2025-04-{wid[:8]}"
            _log(f"F9. {tag} reference_number == 'BATCH-2025-04-{{wid[:8]}}'",
                 e.get("reference_number") == expected,
                 f"got {e.get('reference_number')} expected {expected}")

    # Each user should have a new success tx
    for idx, (tag, uref) in enumerate((("U1", users[0]), ("U4", users[3]))):
        rt = get("/transactions/me", uref["token"])
        ok_tx = False
        if rt.status_code == 200:
            for t in rt.json():
                if (t.get("type") == "withdrawal" and t.get("status") == "success"
                        and t.get("amount") == -150
                        and isinstance(t.get("reference_number"), str)
                        and t.get("reference_number").startswith("BATCH-2025-04-")):
                    ok_tx = True
                    break
        _log(f"F10. {tag} has new success withdrawal tx with BATCH-2025-04- ref", ok_tx, "")

    # Digest after all settlements
    r = get("/admin/withdrawals/digest", t_super)
    if r.status_code == 200:
        d2 = r.json()
        _log("F11. digest.settled_today >= baseline + 4 (w2, w3, wb1, wb2)",
             int(d2.get("settled_today", 0)) >= base_settled_today + 4,
             f"got {d2.get('settled_today')} base={base_settled_today}")

    # -------- G. RBAC --------
    # Promote a fresh user to finance
    fin_email = f"fin_{rand}@test.com"
    fin_pw = "Fin@12345"
    rr = post("/admin/admins", t_super,
              {"name": "Finance Helper", "email": fin_email, "password": fin_pw,
               "admin_role": "finance"})
    _log("G1. Create finance admin via /admin/admins -> 200", rr.status_code == 200, rr.text[:200])
    fin_id = rr.json().get("id") if rr.status_code == 200 else None
    t_fin, _ = login(fin_email, fin_pw)
    _log("G2. Finance login", t_fin is not None)

    # Create a manager admin
    mgr_email = f"mgr_{rand}@test.com"
    mgr_pw = "Mgr@12345"
    rr = post("/admin/admins", t_super,
              {"name": "Manager Helper", "email": mgr_email, "password": mgr_pw,
               "admin_role": "manager"})
    _log("G3. Create manager admin -> 200", rr.status_code == 200, rr.text[:200])
    mgr_id = rr.json().get("id") if rr.status_code == 200 else None
    t_mgr, _ = login(mgr_email, mgr_pw)
    _log("G4. Manager login", t_mgr is not None)

    # Make another user + submit withdrawals for finance/manager to settle
    email_g1 = f"usg1_{rand}@test.com"
    email_g2 = f"usg2_{rand}@test.com"
    t_g1, u_g1, _ = make_approved_user(t_super, "Gita RBAC", email_g1, "User@12345")
    t_g2, u_g2, _ = make_approved_user(t_super, "Harsh RBAC", email_g2, "User@12345")
    credit_wallet(t_super, u_g1["id"], 500)
    credit_wallet(t_super, u_g2["id"], 500)
    rw_g1 = submit_withdrawal(t_g1, 100, f"ug1_{rand}@upi")
    rw_g2 = submit_withdrawal(t_g2, 100, f"ug2_{rand}@upi")
    wg1 = rw_g1.json().get("id") if rw_g1.status_code == 200 else None
    wg2 = rw_g2.json().get("id") if rw_g2.status_code == 200 else None
    _log("G5a. Setup G1 withdrawal ok", bool(wg1))
    _log("G5b. Setup G2 withdrawal ok", bool(wg2))

    # Finance approve-and-complete wg1
    r = post(f"/admin/withdrawals/{wg1}/approve-and-complete", t_fin,
             {"reference_number": "FIN-REF"})
    _log("G6. Finance approve-and-complete -> 200", r.status_code == 200, r.text[:200])

    # Manager approve + complete wg2
    ra = post(f"/admin/withdrawals/{wg2}/approve", t_mgr)
    _log("G7. Manager approve -> 200", ra.status_code == 200, ra.text[:200])
    rc = post(f"/admin/withdrawals/{wg2}/complete", t_mgr, {"reference_number": "MGR-REF"})
    _log("G8. Manager complete -> 200", rc.status_code == 200, rc.text[:200])

    # Regular user → 403 on all 5 endpoints
    reg = users[0]["token"]  # U1
    # Need a pending withdrawal id. Use a non-critical one — create a dummy pending but skip cleanup.
    # Just test 403 on any id (auth-check happens before data lookup).
    dummy_wid = str(uuid.uuid4())
    r = post(f"/admin/withdrawals/{dummy_wid}/reject", reg, {"reason": "x"})
    _log("G9. Regular user /reject -> 403", r.status_code == 403, f"{r.status_code} {r.text[:150]}")
    r = post(f"/admin/withdrawals/{dummy_wid}/complete", reg, {"reference_number": "x"})
    _log("G10. Regular user /complete -> 403", r.status_code == 403, f"{r.status_code} {r.text[:150]}")
    r = post(f"/admin/withdrawals/{dummy_wid}/approve-and-complete", reg, {"reference_number": "x"})
    _log("G11. Regular user /approve-and-complete -> 403", r.status_code == 403, f"{r.status_code} {r.text[:150]}")
    r = post("/admin/withdrawals/batch/complete", reg, {"ids": ["x"], "reference_prefix": "Z"})
    _log("G12. Regular user /batch/complete -> 403", r.status_code == 403, f"{r.status_code} {r.text[:150]}")
    r = get("/admin/withdrawals/digest", reg)
    _log("G13. Regular user /digest -> 403", r.status_code == 403, f"{r.status_code} {r.text[:150]}")

    # No-auth → 401 (or 403 for unauthenticated depending on framework)
    r = requests.post(f"{API}/admin/withdrawals/{dummy_wid}/reject", json={"reason": "x"}, timeout=30)
    _log("G14. No-auth /reject -> 401/403", r.status_code in (401, 403), f"{r.status_code} {r.text[:150]}")
    r = requests.post(f"{API}/admin/withdrawals/{dummy_wid}/complete", json={"reference_number": "x"}, timeout=30)
    _log("G15. No-auth /complete -> 401/403", r.status_code in (401, 403), f"{r.status_code}")
    r = requests.post(f"{API}/admin/withdrawals/{dummy_wid}/approve-and-complete", json={"reference_number": "x"}, timeout=30)
    _log("G16. No-auth /approve-and-complete -> 401/403", r.status_code in (401, 403), f"{r.status_code}")
    r = requests.post(f"{API}/admin/withdrawals/batch/complete", json={"ids": ["x"]}, timeout=30)
    _log("G17. No-auth /batch/complete -> 401/403", r.status_code in (401, 403), f"{r.status_code}")
    r = requests.get(f"{API}/admin/withdrawals/digest", timeout=30)
    _log("G18. No-auth /digest -> 401/403", r.status_code in (401, 403), f"{r.status_code}")

    # -------- H. EDGE CASES --------
    # Empty ids
    r = post("/admin/withdrawals/batch/complete", t_super, {"ids": []})
    _log("H1. batch/complete with empty ids -> 400",
         r.status_code == 400, f"{r.status_code} {r.text[:200]}")
    # complete on pending → 400 (w4 still pending)
    r = post(f"/admin/withdrawals/{w4}/complete", t_super, {"reference_number": "X"})
    _log("H2. complete on pending withdrawal -> 400 'not in processing'",
         r.status_code == 400 and "processing" in (r.text or "").lower(),
         f"{r.status_code} {r.text[:200]}")
    # nonexistent wid → 404 on all 4
    fake = "nonexistent-wid-" + rand
    r = post(f"/admin/withdrawals/{fake}/approve", t_super)
    _log("H3. /approve nonexistent -> 404", r.status_code == 404, f"{r.status_code} {r.text[:150]}")
    r = post(f"/admin/withdrawals/{fake}/complete", t_super, {"reference_number": "X"})
    _log("H4. /complete nonexistent -> 404", r.status_code == 404, f"{r.status_code} {r.text[:150]}")
    r = post(f"/admin/withdrawals/{fake}/reject", t_super, {"reason": "x"})
    _log("H5. /reject nonexistent -> 404", r.status_code == 404, f"{r.status_code} {r.text[:150]}")
    r = post(f"/admin/withdrawals/{fake}/approve-and-complete", t_super, {"reference_number": "X"})
    _log("H6. /approve-and-complete nonexistent -> 404", r.status_code == 404, f"{r.status_code} {r.text[:150]}")

    # -------- I. REGRESSION --------
    r = get("/admin/withdrawals", t_super, params={"status": "pending"})
    _log("I1. GET /admin/withdrawals?status=pending -> 200", r.status_code == 200, r.text[:150])

    # U2 is approved; still has wallet 1000 - 200 (but w2 was settled so wallet debited).
    # Actually after complete, wallet is not re-debited (was already debited at request).
    # Just submit fresh withdrawal from U2 to verify regression works.
    r = submit_withdrawal(users[1]["token"], 50, f"u2reg_{rand}@upi")
    _log("I2. POST /withdrawals (user) works -> 200", r.status_code == 200, r.text[:200])

    r = get("/admin/approvals", t_super, params={"status": "pending"})
    _log("I3. GET /admin/approvals?status=pending -> 200", r.status_code == 200, r.text[:150])

    r = requests.get(f"{API}/branding", timeout=30)
    _log("I4. GET /branding (no auth) -> 200", r.status_code == 200, r.text[:150])

    t_re, _ = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    _log("I5. admin@app.com login still works", t_re is not None)

    # -------- J. CLEANUP --------
    cleanup_errors = 0
    for ud in users:
        r = delete(f"/admin/users/{ud['user']['id']}", t_super)
        if r.status_code != 200:
            cleanup_errors += 1
            print(f"    cleanup: user {ud['email']} -> {r.status_code} {r.text[:150]}")
    if fin_id:
        r = delete(f"/admin/users/{fin_id}", t_super)
        if r.status_code != 200:
            cleanup_errors += 1
    if mgr_id:
        r = delete(f"/admin/users/{mgr_id}", t_super)
        if r.status_code != 200:
            cleanup_errors += 1
    for uid in [u_g1["id"] if u_g1 else None, u_g2["id"] if u_g2 else None]:
        if not uid:
            continue
        r = delete(f"/admin/users/{uid}", t_super)
        if r.status_code != 200:
            cleanup_errors += 1

    _log("J1. Cleanup: all throwaway users deleted", cleanup_errors == 0, f"errors={cleanup_errors}")
    t_again, _ = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    _log("J2. admin@app.com login still works after cleanup", t_again is not None)

    return summary()


if __name__ == "__main__":
    raise SystemExit(main())
