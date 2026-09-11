"""
Phase B backend tests for NetworkPay:
- POST /api/admin/users/create
- POST /api/admin/approvals/{user_id}/reject (extended categories)
- POST /api/payment/failure (3rd strike auto-archive)
- GET /api/admin/rejected-registrations
- GET /api/admin/rejected-registrations/export
- DELETE /api/admin/rejected-registrations/{id}

Runs against the public preview URL.
"""

import os
import sys
import time
import uuid
import requests

BASE = os.environ.get("BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

SUPER_EMAIL = "admin@app.com"
SUPER_PASS = "Admin@123"

SESS = requests.Session()
SESS.headers.update({"Content-Type": "application/json"})

PASS = []
FAIL = []
THROWAWAY_USERS = []  # list of user ids to delete at end (still in users collection)
ARCHIVE_RECORDS = []  # list of archive ids to delete at end
THROWAWAY_ADMINS = []  # admin user ids to delete at end


def log_pass(label):
    PASS.append(label)
    print(f"  PASS  {label}")


def log_fail(label, info=""):
    FAIL.append(f"{label} :: {info}")
    print(f"  FAIL  {label} :: {info}")


def call(method, path, token=None, json=None, params=None, expected=None, label=""):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = path if path.startswith("http") else f"{API}{path}"
    r = SESS.request(method, url, json=json, params=params, headers=headers, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = r.text
    if expected is not None:
        if isinstance(expected, (list, tuple)):
            ok = r.status_code in expected
        else:
            ok = r.status_code == expected
        if ok:
            log_pass(f"{label} → {r.status_code}")
        else:
            log_fail(label, f"expected {expected}, got {r.status_code}, body={body!r}")
    return r, body


def section(name):
    print(f"\n=== {name} ===")


def login(email, password, label):
    r, body = call("POST", "/auth/login", json={"email": email, "password": password},
                   expected=200, label=f"login {label}")
    if r.status_code == 200 and isinstance(body, dict):
        return body.get("token"), body.get("user")
    return None, None


def rand_email(prefix):
    return f"phb.{prefix}.{uuid.uuid4().hex[:10]}@example.com"


# ------------- main -------------
def main():
    print(f"BASE = {BASE}")

    # --- 0. Login super_admin ---
    section("0. Login super_admin")
    super_tok, super_user = login(SUPER_EMAIL, SUPER_PASS, "super_admin")
    if not super_tok:
        log_fail("super_admin login", "no token; cannot proceed")
        return
    super_user_id = super_user["id"]

    # Create helper admins for RBAC tests: manager, support, finance
    def create_admin(role):
        email = rand_email(f"adm_{role}")
        r, body = call(
            "POST", "/admin/admins", token=super_tok,
            json={"name": f"Test {role}", "email": email, "password": "Adm1n@123", "admin_role": role},
            expected=200, label=f"super create admin {role}",
        )
        if r.status_code == 200 and isinstance(body, dict):
            uid = (body.get("user") or {}).get("id") or body.get("id")
            if not uid:
                # body shape may differ; fetch by email
                r2, b2 = call("GET", "/admin/admins", token=super_tok, expected=200,
                              label=f"GET /admin/admins after creating {role}")
                if isinstance(b2, list):
                    for a in b2:
                        if a.get("email") == email:
                            uid = a.get("id")
                            break
            tok, _ = login(email, "Adm1n@123", f"{role}-admin")
            if uid:
                THROWAWAY_ADMINS.append(uid)
            return tok, uid, email
        return None, None, email

    section("0b. Create RBAC helper admins (manager, support, finance)")
    mgr_tok, mgr_id, mgr_email = create_admin("manager")
    sup_tok, sup_id, sup_email = create_admin("support")
    fin_tok, fin_id, fin_email = create_admin("finance")

    if not (mgr_tok and sup_tok and fin_tok):
        log_fail("RBAC admin setup", "could not create one or more helper admins")
        # we'll still try to continue best-effort

    # ============================================================
    # SCENARIO A: Admin user-create
    # ============================================================
    section("A. Admin user-create")

    # A.1 super_admin creates a user with mark_paid_offline=true
    a1_email = rand_email("a1_paid")
    r, body = call(
        "POST", "/admin/users/create", token=super_tok,
        json={"name": "A1 Paid User", "email": a1_email, "password": "Test@123", "mark_paid_offline": True},
        expected=200, label="A.1 super create user (mark_paid_offline=true)",
    )
    a1_uid = None
    if r.status_code == 200 and isinstance(body, dict):
        u = body.get("user") or {}
        a1_uid = u.get("id")
        if a1_uid:
            THROWAWAY_USERS.append(a1_uid)
        # Verify fields directly via /admin/users (since serialize_user may not show all)
        r2, b2 = call("GET", "/admin/users", token=super_tok, expected=200, label="A.1 verify GET /admin/users")
        if isinstance(b2, list):
            found = next((x for x in b2 if x.get("email") == a1_email), None)
            if found:
                if found.get("registration_paid") is True:
                    log_pass("A.1 registration_paid=true")
                else:
                    log_fail("A.1 registration_paid", f"got {found.get('registration_paid')}")
                if found.get("payment_method") == "admin_offline":
                    log_pass("A.1 payment_method=admin_offline")
                else:
                    log_fail("A.1 payment_method", f"got {found.get('payment_method')}")
                if found.get("approval_status") == "pending":
                    log_pass("A.1 approval_status=pending")
                else:
                    log_fail("A.1 approval_status", f"got {found.get('approval_status')}")
            else:
                log_fail("A.1 verify user appears in /admin/users", "not found")

    # A.2 Duplicate email
    call(
        "POST", "/admin/users/create", token=super_tok,
        json={"name": "Dup", "email": a1_email, "password": "Test@123"},
        expected=400, label="A.2 duplicate email → 400",
    )

    # A.3 Invalid referral code
    call(
        "POST", "/admin/users/create", token=super_tok,
        json={"name": "BadRef", "email": rand_email("badref"), "password": "Test@123",
              "referral_code": "ZZZZNOPE9999"},
        expected=400, label="A.3 invalid referral_code → 400",
    )

    # A.4 mark_paid_offline=false
    a4_email = rand_email("a4_unpaid")
    r, body = call(
        "POST", "/admin/users/create", token=super_tok,
        json={"name": "A4 Unpaid", "email": a4_email, "password": "Test@123", "mark_paid_offline": False},
        expected=200, label="A.4 super create user (mark_paid_offline=false)",
    )
    if r.status_code == 200 and isinstance(body, dict):
        u = (body.get("user") or {})
        if u.get("id"):
            THROWAWAY_USERS.append(u["id"])
        r2, b2 = call("GET", "/admin/users", token=super_tok, expected=200, label="A.4 verify GET /admin/users")
        if isinstance(b2, list):
            found = next((x for x in b2 if x.get("email") == a4_email), None)
            if found and found.get("registration_paid") is False:
                log_pass("A.4 registration_paid=false")
            else:
                log_fail("A.4 registration_paid=false",
                         f"got {found.get('registration_paid') if found else 'not found'}")

    # A.5 manager creates → 200, support creates → 200, finance creates → 403
    if mgr_tok:
        a5m_email = rand_email("a5_mgr")
        r, body = call(
            "POST", "/admin/users/create", token=mgr_tok,
            json={"name": "By Mgr", "email": a5m_email, "password": "Test@123", "mark_paid_offline": True},
            expected=200, label="A.5 manager create user → 200",
        )
        if r.status_code == 200 and isinstance(body, dict):
            uid = (body.get("user") or {}).get("id")
            if uid:
                THROWAWAY_USERS.append(uid)

    if sup_tok:
        a5s_email = rand_email("a5_sup")
        r, body = call(
            "POST", "/admin/users/create", token=sup_tok,
            json={"name": "By Support", "email": a5s_email, "password": "Test@123", "mark_paid_offline": True},
            expected=200, label="A.5 support create user → 200",
        )
        if r.status_code == 200 and isinstance(body, dict):
            uid = (body.get("user") or {}).get("id")
            if uid:
                THROWAWAY_USERS.append(uid)

    if fin_tok:
        call(
            "POST", "/admin/users/create", token=fin_tok,
            json={"name": "By Finance", "email": rand_email("a5_fin"), "password": "Test@123"},
            expected=403, label="A.5 finance create user → 403",
        )

    # ============================================================
    # SCENARIO B: Reject + archive flow
    # ============================================================
    section("B. Reject + archive flow")

    def register_throwaway(prefix):
        email = rand_email(prefix)
        r, body = call("POST", "/auth/register",
                       json={"name": f"T {prefix}", "email": email, "password": "Test@123"},
                       expected=200, label=f"register throwaway {prefix}")
        if r.status_code == 200 and isinstance(body, dict):
            uid = (body.get("user") or {}).get("id")
            tok = body.get("token")
            return uid, tok, email
        return None, None, email

    # B.1 Create T → reject with payment_unsuccessful
    t_uid, _, t_email = register_throwaway("B1_pu")
    if t_uid:
        r, body = call(
            "POST", f"/admin/approvals/{t_uid}/reject", token=super_tok,
            json={"category": "payment_unsuccessful"},
            expected=200, label="B.1 reject payment_unsuccessful → 200",
        )
        if r.status_code == 200 and isinstance(body, dict):
            if body.get("archived") is True and body.get("archive_id"):
                log_pass("B.1 returned archived=true with archive_id")
                ARCHIVE_RECORDS.append(body["archive_id"])
                t_archive_id = body["archive_id"]
            else:
                log_fail("B.1 archived flag", f"body={body!r}")
                t_archive_id = None
        else:
            t_archive_id = None

        # B.2 GET /admin/users — T should NOT be present
        r2, b2 = call("GET", "/admin/users", token=super_tok, expected=200, label="B.2 GET /admin/users (after archive)")
        if isinstance(b2, list):
            still = any(x.get("id") == t_uid or x.get("email") == t_email for x in b2)
            if not still:
                log_pass("B.2 T no longer in /admin/users")
            else:
                log_fail("B.2 T no longer in /admin/users", "still present!")

        # B.3 GET /admin/rejected-registrations?category=payment_unsuccessful — T present
        r3, b3 = call(
            "GET", "/admin/rejected-registrations", token=super_tok,
            params={"category": "payment_unsuccessful"},
            expected=200, label="B.3 GET rejected-registrations?category=payment_unsuccessful",
        )
        if isinstance(b3, dict):
            items = b3.get("items") or []
            counts = b3.get("counts") or {}
            found = next((x for x in items if (x.get("email") or "").lower() == t_email.lower()), None)
            if found and found.get("category") == "payment_unsuccessful":
                log_pass("B.3 T present in archive list with correct category")
                # spot-check fields
                for f in ("id", "original_user_id", "name", "email", "rejected_at", "remarks"):
                    if f in found:
                        pass
                if found.get("original_user_id") == t_uid:
                    log_pass("B.3 archive original_user_id matches")
                else:
                    log_fail("B.3 original_user_id", f"got {found.get('original_user_id')}")
            else:
                log_fail("B.3 T found in archive", f"items count={len(items)}, counts={counts}")

    # B.4 reject category="other" with empty reason → 400
    t2_uid, _, t2_email = register_throwaway("B4_other_empty")
    if t2_uid:
        call(
            "POST", f"/admin/approvals/{t2_uid}/reject", token=super_tok,
            json={"category": "other", "reason": ""},
            expected=400, label="B.4 reject other empty reason → 400",
        )
        # also try whitespace-only
        call(
            "POST", f"/admin/approvals/{t2_uid}/reject", token=super_tok,
            json={"category": "other", "reason": "   "},
            expected=400, label="B.4b reject other whitespace reason → 400",
        )

        # B.5 reject "other" with reason="test" → 200, archived
        r, body = call(
            "POST", f"/admin/approvals/{t2_uid}/reject", token=super_tok,
            json={"category": "other", "reason": "test"},
            expected=200, label="B.5 reject other reason=test → 200",
        )
        if r.status_code == 200 and isinstance(body, dict) and body.get("archived") is True and body.get("archive_id"):
            log_pass("B.5 archived=true returned with archive_id")
            ARCHIVE_RECORDS.append(body["archive_id"])
        else:
            log_fail("B.5 archived flag", f"body={body!r}")

    # B.6 Reject legacy category "cibil_score" → 200 archived=false
    t3_uid, _, t3_email = register_throwaway("B6_legacy")
    if t3_uid:
        THROWAWAY_USERS.append(t3_uid)
        r, body = call(
            "POST", f"/admin/approvals/{t3_uid}/reject", token=super_tok,
            json={"category": "cibil_score"},
            expected=200, label="B.6 reject cibil_score → 200",
        )
        if r.status_code == 200 and isinstance(body, dict):
            if body.get("archived") is False:
                log_pass("B.6 archived=false (legacy in-place flip)")
            else:
                log_fail("B.6 archived flag", f"body={body!r}")
        # confirm user still in users with rejected status
        r2, b2 = call("GET", "/admin/users", token=super_tok, expected=200, label="B.6 verify user still present")
        if isinstance(b2, list):
            found = next((x for x in b2 if x.get("id") == t3_uid), None)
            if found and found.get("approval_status") == "rejected":
                log_pass("B.6 user still in users with approval_status=rejected")
            else:
                log_fail("B.6 user/approval_status after legacy reject",
                         f"found={bool(found)}, status={found.get('approval_status') if found else None}")

    # ============================================================
    # SCENARIO C: Auto-archive after 3 payment failures
    # ============================================================
    section("C. Auto-archive after 3 payment failures")

    p_uid, p_tok, p_email = register_throwaway("C_pay")
    if p_uid and p_tok:
        # 1st failure
        r1, b1 = call("POST", "/payment/failure", token=p_tok,
                      json={"reason": "Card declined #1"},
                      expected=200, label="C.1a /payment/failure 1st")
        if isinstance(b1, dict):
            if b1.get("archived") is False and b1.get("attempts_remaining") == 2:
                log_pass("C.1a 1st failure: attempts_remaining=2, archived=false")
            else:
                log_fail("C.1a 1st failure", f"body={b1!r}")
        # 2nd failure
        r2, b2 = call("POST", "/payment/failure", token=p_tok,
                      json={"reason": "Card declined #2"},
                      expected=200, label="C.1b /payment/failure 2nd")
        if isinstance(b2, dict):
            if b2.get("archived") is False and b2.get("attempts_remaining") == 1:
                log_pass("C.1b 2nd failure: attempts_remaining=1, archived=false")
            else:
                log_fail("C.1b 2nd failure", f"body={b2!r}")
        # 3rd failure → archived
        r3, b3 = call("POST", "/payment/failure", token=p_tok,
                      json={"reason": "Card declined #3"},
                      expected=200, label="C.2 /payment/failure 3rd")
        p_archive_id = None
        if isinstance(b3, dict):
            if b3.get("archived") is True and b3.get("archive_id"):
                log_pass("C.2 3rd failure archived=true with archive_id")
                p_archive_id = b3["archive_id"]
                ARCHIVE_RECORDS.append(p_archive_id)
            else:
                log_fail("C.2 3rd failure archive", f"body={b3!r}")

        # C.3 user gone from /admin/users
        r4, b4 = call("GET", "/admin/users", token=super_tok, expected=200, label="C.3 GET /admin/users after archive")
        if isinstance(b4, list):
            still = any(x.get("id") == p_uid for x in b4)
            if not still:
                log_pass("C.3 user removed from /admin/users")
            else:
                log_fail("C.3 user removed from /admin/users", "still present")

        # C.4 archive list shows P with auto-reject remarks
        r5, b5 = call("GET", "/admin/rejected-registrations", token=super_tok,
                      params={"category": "payment_unsuccessful"},
                      expected=200, label="C.4 GET archive after auto-reject")
        if isinstance(b5, dict):
            items = b5.get("items") or []
            found = next((x for x in items if (x.get("email") or "").lower() == p_email.lower()), None)
            if found:
                if "Auto-rejected after 3 failed payment attempts" in (found.get("remarks") or ""):
                    log_pass("C.4 P appears with auto-reject remarks")
                else:
                    log_fail("C.4 auto-reject remarks", f"remarks={found.get('remarks')!r}")
            else:
                log_fail("C.4 P appears in archive", f"items count={len(items)}")

    # ============================================================
    # SCENARIO D: List / export / delete
    # ============================================================
    section("D. List / export / delete")

    # D.1 counts present
    r, body = call("GET", "/admin/rejected-registrations", token=super_tok,
                   expected=200, label="D.1 GET /admin/rejected-registrations (no filter)")
    if isinstance(body, dict):
        counts = body.get("counts") or {}
        if "all" in counts and isinstance(counts["all"], int):
            log_pass(f"D.1 counts.all = {counts['all']} (counts={counts})")
        else:
            log_fail("D.1 counts shape", f"counts={counts}")

    # D.1b filtered counts
    r, body = call("GET", "/admin/rejected-registrations", token=super_tok,
                   params={"category": "payment_unsuccessful"},
                   expected=200, label="D.1b GET ?category=payment_unsuccessful")
    if isinstance(body, dict):
        items = body.get("items") or []
        # ALL items must have category=payment_unsuccessful
        bad = [x for x in items if x.get("category") != "payment_unsuccessful"]
        if not bad:
            log_pass(f"D.1b filter category=payment_unsuccessful — {len(items)} items, all match")
        else:
            log_fail("D.1b category filter integrity", f"{len(bad)} items mismatched")

    # D.2 export CSV
    r = SESS.get(
        f"{API}/admin/rejected-registrations/export",
        headers={"Authorization": f"Bearer {super_tok}"}, timeout=30,
    )
    if r.status_code == 200:
        ct = r.headers.get("content-type", "")
        if "text/csv" in ct:
            log_pass(f"D.2 export 200 with text/csv (content-type={ct})")
        else:
            log_fail("D.2 export content-type", f"got {ct}")
        text = r.text
        lines = text.split("\n")
        header = lines[0] if lines else ""
        if "id" in header and "email" in header and "category" in header and "rejected_at" in header:
            log_pass(f"D.2 export header looks right ({len(lines)} lines)")
        else:
            log_fail("D.2 export header", f"got header={header!r}")
    else:
        log_fail("D.2 export 200", f"status={r.status_code}, body={r.text[:200]}")

    # D.2b filtered export
    r = SESS.get(
        f"{API}/admin/rejected-registrations/export",
        params={"category": "payment_unsuccessful"},
        headers={"Authorization": f"Bearer {super_tok}"}, timeout=30,
    )
    if r.status_code == 200 and "text/csv" in r.headers.get("content-type", ""):
        log_pass("D.2b export ?category=payment_unsuccessful → 200 text/csv")
    else:
        log_fail("D.2b export filter", f"status={r.status_code} ct={r.headers.get('content-type')}")

    # D.3 finance role: list 200, export 200
    if fin_tok:
        call("GET", "/admin/rejected-registrations", token=fin_tok,
             expected=200, label="D.3a finance GET /admin/rejected-registrations → 200")
        rfin = SESS.get(
            f"{API}/admin/rejected-registrations/export",
            headers={"Authorization": f"Bearer {fin_tok}"}, timeout=30,
        )
        if rfin.status_code == 200 and "text/csv" in rfin.headers.get("content-type", ""):
            log_pass("D.3b finance export → 200 text/csv")
        else:
            log_fail("D.3b finance export", f"status={rfin.status_code}")

    # D.4 super_admin DELETE archive record (delete first archive id we have, if any)
    if ARCHIVE_RECORDS:
        del_id = ARCHIVE_RECORDS[0]
        r, body = call("DELETE", f"/admin/rejected-registrations/{del_id}", token=super_tok,
                       expected=200, label="D.4 super DELETE /admin/rejected-registrations/{id} → 200")
        if r.status_code == 200:
            ARCHIVE_RECORDS.pop(0)

        # Subsequent DELETE on same id → 404
        call("DELETE", f"/admin/rejected-registrations/{del_id}", token=super_tok,
             expected=404, label="D.4b second DELETE same id → 404")

    # D.5 finance DELETE → 403
    if fin_tok and ARCHIVE_RECORDS:
        any_id = ARCHIVE_RECORDS[0]
        call("DELETE", f"/admin/rejected-registrations/{any_id}", token=fin_tok,
             expected=403, label="D.5 finance DELETE → 403")

    # ============================================================
    # SCENARIO E: RBAC manager/support
    # ============================================================
    section("E. RBAC manager/support")
    if mgr_tok:
        call("GET", "/admin/rejected-registrations", token=mgr_tok,
             expected=200, label="E.1a manager GET list → 200")
        rm = SESS.get(
            f"{API}/admin/rejected-registrations/export",
            headers={"Authorization": f"Bearer {mgr_tok}"}, timeout=30,
        )
        if rm.status_code == 403:
            log_pass("E.1b manager export → 403")
        else:
            log_fail("E.1b manager export → 403", f"got {rm.status_code}")
        if ARCHIVE_RECORDS:
            call("DELETE", f"/admin/rejected-registrations/{ARCHIVE_RECORDS[0]}", token=mgr_tok,
                 expected=403, label="E.1c manager DELETE → 403")

    if sup_tok:
        call("GET", "/admin/rejected-registrations", token=sup_tok,
             expected=200, label="E.2a support GET list → 200")
        rs = SESS.get(
            f"{API}/admin/rejected-registrations/export",
            headers={"Authorization": f"Bearer {sup_tok}"}, timeout=30,
        )
        if rs.status_code == 403:
            log_pass("E.2b support export → 403")
        else:
            log_fail("E.2b support export → 403", f"got {rs.status_code}")
        if ARCHIVE_RECORDS:
            call("DELETE", f"/admin/rejected-registrations/{ARCHIVE_RECORDS[0]}", token=sup_tok,
                 expected=403, label="E.2c support DELETE → 403")

    # ============================================================
    # SCENARIO F: Regression
    # ============================================================
    section("F. Regression")
    call("GET", "/admin/users", token=super_tok, expected=200, label="F.1 GET /admin/users → 200")
    call("POST", "/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASS},
         expected=200, label="F.2 super_admin login still works")
    # Skip Danger PIN re-test per request

    # ============================================================
    # SCENARIO G: Cleanup
    # ============================================================
    section("G. Cleanup")

    # Delete remaining archive records
    for aid in list(ARCHIVE_RECORDS):
        r, _ = call("DELETE", f"/admin/rejected-registrations/{aid}", token=super_tok,
                    expected=(200, 404), label=f"G cleanup archive {aid[:8]}")
        ARCHIVE_RECORDS.remove(aid)

    # Delete throwaway users (the ones still in users collection)
    for uid in set(THROWAWAY_USERS):
        call("DELETE", f"/admin/users/{uid}", token=super_tok,
             expected=(200, 404), label=f"G cleanup user {uid[:8]}")

    # Delete throwaway admins
    for uid in set(THROWAWAY_ADMINS):
        call("DELETE", f"/admin/users/{uid}", token=super_tok,
             expected=(200, 404), label=f"G cleanup admin {uid[:8]}")

    # Verify admin@app.com still works
    r, body = call("POST", "/auth/login", json={"email": SUPER_EMAIL, "password": SUPER_PASS},
                   expected=200, label="G admin@app.com login still works")

    # Also confirm there are no leftover archive items with our test email patterns
    r, body = call("GET", "/admin/rejected-registrations", token=super_tok,
                   params={"search": "phaseb.test"},
                   expected=200, label="G search archive for phaseb.test")
    if isinstance(body, dict):
        items = body.get("items") or []
        # cleanup any leftover from this run
        for it in items:
            iid = it.get("id")
            if iid:
                call("DELETE", f"/admin/rejected-registrations/{iid}", token=super_tok,
                     expected=(200, 404), label=f"G cleanup leftover archive {iid[:8]}")

    # ============================================================
    # SUMMARY
    # ============================================================
    print()
    print("=" * 70)
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFAILED CHECKS:")
        for f in FAIL:
            print(f"  - {f}")
    print("=" * 70)
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
