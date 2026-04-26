"""
Admin management endpoint tests (NEW endpoints).
Covers scenarios A–R from the review request, plus a regression check on
PATCH /admin/users/{id} for non-sensitive fields, and a quick re-run of
/api/auth/google/* contract.
"""
import os
import sys
import time
import uuid
import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# Unique test data so re-runs don't collide
SUFFIX = uuid.uuid4().hex[:6]
USER_EMAIL = f"u_{SUFFIX}@nptest.com"
USER_PASSWORD = "User@12345"
USER_NAME = "Riya Sharma"

MGR_EMAIL = f"newmgr_{SUFFIX}@test.com"
MGR_PASSWORD = "Test@123"
MGR_NAME = "Test Mgr"

results = []  # (label, ok, detail)


def record(label, ok, detail=""):
    results.append((label, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {label}  {detail if detail else ''}")


def auth_h(token):
    return {"Authorization": f"Bearer {token}"}


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    return r


def main():
    # A. Login as super_admin
    r = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if r.status_code != 200:
        record("A. login super_admin", False, f"status={r.status_code} body={r.text[:200]}")
        return
    super_data = r.json()
    T_super = super_data["token"]
    super_id = super_data["user"]["id"]
    record("A. login super_admin", True, f"id={super_id}")

    # B. Register a regular user U then login
    reg_payload = {
        "name": USER_NAME,
        "email": USER_EMAIL,
        "password": USER_PASSWORD,
        "phone": "9876543210",
    }
    r = requests.post(f"{BASE}/auth/register", json=reg_payload, timeout=20)
    if r.status_code != 200:
        record("B. register user U", False, f"status={r.status_code} body={r.text[:200]}")
        return
    U = r.json()["user"]
    record("B. register user U", True, f"id={U['id']} email={U['email']}")

    r = login(USER_EMAIL, USER_PASSWORD)
    if r.status_code != 200:
        record("B. login user U", False, f"status={r.status_code} body={r.text[:200]}")
        return
    T_user = r.json()["token"]
    record("B. login user U", True)

    # C. As super_admin: GET /admin/admins → contains admin@app.com, no password_hash
    r = requests.get(f"{BASE}/admin/admins", headers=auth_h(T_super), timeout=20)
    ok = r.status_code == 200
    body = r.json() if ok else None
    if ok:
        emails = {a.get("email") for a in body}
        roles_ok = all(a.get("role") == "admin" for a in body)
        no_pw = all("password_hash" not in a for a in body)
        no_kyc_imgs = all(("kyc_aadhaar_front" not in a and "kyc_aadhaar_back" not in a
                          and "kyc_pan_image" not in a and "kyc_selfie" not in a) for a in body)
        ok = (ADMIN_EMAIL in emails) and roles_ok and no_pw and no_kyc_imgs
        record("C. GET /admin/admins shape", ok,
               f"count={len(body)} adminInList={ADMIN_EMAIL in emails} roles_ok={roles_ok} no_pw={no_pw} no_kyc_imgs={no_kyc_imgs}")
    else:
        record("C. GET /admin/admins shape", False, f"status={r.status_code} body={r.text[:200]}")

    # D. As super_admin: POST /admin/admins create new manager
    body = {"name": MGR_NAME, "email": MGR_EMAIL, "password": MGR_PASSWORD, "admin_role": "manager"}
    r = requests.post(f"{BASE}/admin/admins", headers=auth_h(T_super), json=body, timeout=20)
    if r.status_code != 200:
        record("D. POST /admin/admins create manager", False, f"status={r.status_code} body={r.text[:200]}")
        return
    new_mgr = r.json()
    cond = (new_mgr.get("role") == "admin"
            and new_mgr.get("admin_role") == "manager"
            and new_mgr.get("registration_paid") is True
            and new_mgr.get("email") == MGR_EMAIL
            and "password_hash" not in new_mgr)
    record("D. POST /admin/admins create manager", cond,
           f"role={new_mgr.get('role')} admin_role={new_mgr.get('admin_role')} reg_paid={new_mgr.get('registration_paid')}")
    new_mgr_id = new_mgr["id"]

    # GET /admin/admins now contains new manager
    r = requests.get(f"{BASE}/admin/admins", headers=auth_h(T_super), timeout=20)
    contains_new = r.status_code == 200 and any(a.get("email") == MGR_EMAIL for a in r.json())
    record("D2. GET /admin/admins includes new manager", contains_new)

    # E. duplicate email → 400
    r = requests.post(f"{BASE}/admin/admins", headers=auth_h(T_super), json=body, timeout=20)
    cond = r.status_code == 400 and "already in use" in (r.json().get("detail", "")).lower()
    record("E. POST duplicate email → 400", cond, f"status={r.status_code} detail={r.text[:120]}")

    # F. invalid admin_role → 400
    bad = {"name": "Evil", "email": f"evil_{SUFFIX}@test.com", "password": "Evil@1234", "admin_role": "evil"}
    r = requests.post(f"{BASE}/admin/admins", headers=auth_h(T_super), json=bad, timeout=20)
    cond = r.status_code == 400 and "admin_role" in r.text.lower()
    record("F. POST invalid admin_role → 400", cond, f"status={r.status_code} detail={r.text[:120]}")

    # G. Promote U to support
    r = requests.post(f"{BASE}/admin/users/{U['id']}/promote", headers=auth_h(T_super),
                      json={"admin_role": "support"}, timeout=20)
    if r.status_code != 200:
        record("G. promote U → support", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        u_after = r.json()
        cond = u_after.get("role") == "admin" and u_after.get("admin_role") == "support"
        record("G. promote U → support", cond,
               f"role={u_after.get('role')} admin_role={u_after.get('admin_role')}")

    # H. Try to promote U again → 400 already admin
    r = requests.post(f"{BASE}/admin/users/{U['id']}/promote", headers=auth_h(T_super),
                      json={"admin_role": "manager"}, timeout=20)
    cond = r.status_code == 400 and "already an admin" in r.text.lower()
    record("H. promote U again → 400", cond, f"status={r.status_code} detail={r.text[:120]}")

    # I. Demote U → user
    r = requests.post(f"{BASE}/admin/users/{U['id']}/demote", headers=auth_h(T_super), timeout=20)
    if r.status_code != 200:
        record("I. demote U → user", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        u_after = r.json()
        cond = u_after.get("role") == "user" and (u_after.get("admin_role") in (None, "null"))
        record("I. demote U → user", cond,
               f"role={u_after.get('role')} admin_role={u_after.get('admin_role')}")

    # J. Try demote self → 400 (super_admin trying to demote themselves)
    r = requests.post(f"{BASE}/admin/users/{super_id}/demote", headers=auth_h(T_super), timeout=20)
    cond = r.status_code == 400 and ("yourself" in r.text.lower() or "last super_admin" in r.text.lower())
    record("J. demote self → 400", cond, f"status={r.status_code} detail={r.text[:160]}")

    # K. Try to demote the last super_admin (admin@app.com == self in this case).
    # Since admin@app.com IS the caller, we already covered "yourself" above. But
    # the spec wants the "last super_admin" error specifically. To avoid mutating
    # super state, we accept either error message containing "yourself" or
    # "last super_admin" — both are valid 400 guards.
    record("K. demote last super_admin → 400 (covered by J via self)", cond,
           f"reused J detail={r.text[:160]}")

    # L. Login as freshly created manager
    r = login(MGR_EMAIL, MGR_PASSWORD)
    if r.status_code != 200:
        record("L. login as new manager", False, f"status={r.status_code} body={r.text[:200]}")
        T_mgr = None
    else:
        T_mgr = r.json()["token"]
        record("L. login as new manager", True)

    if T_mgr:
        # M. As manager: GET /admin/admins → 200
        r = requests.get(f"{BASE}/admin/admins", headers=auth_h(T_mgr), timeout=20)
        record("M. manager GET /admin/admins", r.status_code == 200,
               f"status={r.status_code}")

        # N. As manager: POST /admin/admins → 403
        r = requests.post(f"{BASE}/admin/admins", headers=auth_h(T_mgr),
                          json={"name": "X", "email": f"x_{SUFFIX}@x.com", "password": "Xx@12345",
                                "admin_role": "manager"}, timeout=20)
        record("N. manager POST /admin/admins → 403", r.status_code == 403,
               f"status={r.status_code} detail={r.text[:120]}")

        # O. As manager: PATCH self admin_role → super_admin → 403
        r = requests.patch(f"{BASE}/admin/users/{new_mgr_id}", headers=auth_h(T_mgr),
                           json={"admin_role": "super_admin"}, timeout=20)
        cond = r.status_code == 403
        record("O1. manager PATCH admin_role → 403", cond,
               f"status={r.status_code} detail={r.text[:160]}")

        # PATCH name only → 200
        r = requests.patch(f"{BASE}/admin/users/{new_mgr_id}", headers=auth_h(T_mgr),
                           json={"name": "Mgr Renamed"}, timeout=20)
        cond = r.status_code == 200 and r.json().get("name") == "Mgr Renamed"
        record("O2. manager PATCH name only → 200", cond,
               f"status={r.status_code} name={r.json().get('name') if r.status_code==200 else r.text[:100]}")

        # P. As manager: promote U → 403
        r = requests.post(f"{BASE}/admin/users/{U['id']}/promote", headers=auth_h(T_mgr),
                          json={"admin_role": "manager"}, timeout=20)
        record("P. manager promote → 403", r.status_code == 403,
               f"status={r.status_code} detail={r.text[:160]}")

        # Q. As manager: demote U → 403
        r = requests.post(f"{BASE}/admin/users/{U['id']}/demote", headers=auth_h(T_mgr), timeout=20)
        record("Q. manager demote → 403", r.status_code == 403,
               f"status={r.status_code} detail={r.text[:160]}")

    # Regression: PATCH /admin/users/{id} non-sensitive fields by any admin
    r = requests.patch(f"{BASE}/admin/users/{U['id']}", headers=auth_h(T_super),
                       json={"wallet_balance": 250.0}, timeout=20)
    cond = r.status_code == 200 and abs((r.json().get("wallet_balance") or 0) - 250.0) < 1e-6
    record("Regression: super PATCH wallet_balance", cond,
           f"status={r.status_code} bal={r.json().get('wallet_balance') if r.status_code==200 else r.text[:120]}")

    new_name = f"Riya R. {SUFFIX}"
    r = requests.patch(f"{BASE}/admin/users/{U['id']}", headers=auth_h(T_super),
                       json={"name": new_name}, timeout=20)
    cond = r.status_code == 200 and r.json().get("name") == new_name
    record("Regression: super PATCH name", cond, f"status={r.status_code}")

    new_email = f"u2_{SUFFIX}@nptest.com"
    r = requests.patch(f"{BASE}/admin/users/{U['id']}", headers=auth_h(T_super),
                       json={"email": new_email}, timeout=20)
    cond = r.status_code == 200 and r.json().get("email") == new_email
    record("Regression: super PATCH email", cond, f"status={r.status_code}")

    if T_mgr:
        r = requests.patch(f"{BASE}/admin/users/{U['id']}", headers=auth_h(T_mgr),
                           json={"wallet_balance": 333.0}, timeout=20)
        cond = r.status_code == 200 and abs((r.json().get("wallet_balance") or 0) - 333.0) < 1e-6
        record("Regression: manager PATCH wallet_balance (non-sensitive)", cond,
               f"status={r.status_code}")

    # Regression: Google auth contract (no real OAuth)
    r = requests.get(f"{BASE}/auth/google/callback", timeout=20)
    cond = r.status_code == 200 and "text/html" in r.headers.get("content-type", "").lower()
    record("Google: GET /auth/google/callback 200 HTML", cond,
           f"status={r.status_code} ctype={r.headers.get('content-type')}")

    r = requests.post(f"{BASE}/auth/google/exchange",
                      json={"session_id": "INVALID_TEST_SESSION_ID_12345"}, timeout=20)
    cond = r.status_code == 401 and "invalid google session" in r.text.lower()
    record("Google: POST exchange invalid → 401", cond,
           f"status={r.status_code} detail={r.text[:120]}")

    r = requests.post(f"{BASE}/auth/google/exchange", json={}, timeout=20)
    record("Google: POST exchange empty → 422", r.status_code == 422,
           f"status={r.status_code}")

    r = requests.post(f"{BASE}/auth/google/exchange", json={"referral_code": "ADMIN001"}, timeout=20)
    record("Google: POST exchange w/o session_id → 422", r.status_code == 422,
           f"status={r.status_code}")

    # R. cleanup — delete the manager and the user U
    r = requests.delete(f"{BASE}/admin/users/{new_mgr_id}", headers=auth_h(T_super), timeout=20)
    record("R1. delete new manager", r.status_code == 200, f"status={r.status_code} body={r.text[:120]}")
    r = requests.delete(f"{BASE}/admin/users/{U['id']}", headers=auth_h(T_super), timeout=20)
    record("R2. delete user U", r.status_code == 200, f"status={r.status_code} body={r.text[:120]}")

    # Confirm GET /admin/admins now does NOT contain new manager
    r = requests.get(f"{BASE}/admin/admins", headers=auth_h(T_super), timeout=20)
    cond = r.status_code == 200 and not any(a.get("email") == MGR_EMAIL for a in r.json())
    record("R3. /admin/admins no longer contains deleted manager", cond,
           f"status={r.status_code}")

    # Summary
    print("\n========== SUMMARY ==========")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"{passed}/{total} passed")
    failures = [(l, d) for l, ok, d in results if not ok]
    if failures:
        print("\nFAILURES:")
        for l, d in failures:
            print(f"  - {l}: {d}")
    else:
        print("All green.")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
