"""
Backend test for the new Danger PIN unified gate (Wipe + Restore).
Tests against the public preview URL, using admin@app.com / Admin@123.

Leaves the Danger PIN set to "654321" at the end so frontend can use it.
"""
from __future__ import annotations

import json
import secrets
import string
import sys
import time
from typing import Any, Dict, Optional

import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def _hdr(token: Optional[str]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def step(name: str, expected: int, actual: int, body: Any = None, extra_check: Optional[bool] = None, extra_msg: str = ""):
    global PASS, FAIL
    ok = (actual == expected) and (extra_check is None or extra_check)
    if ok:
        PASS += 1
        print(f"  PASS  {name} -> {actual}")
    else:
        FAIL += 1
        msg = f"  FAIL  {name} -> got {actual}, expected {expected}"
        if extra_msg:
            msg += f" | {extra_msg}"
        if body is not None:
            try:
                snippet = json.dumps(body)[:300]
            except Exception:
                snippet = str(body)[:300]
            msg += f" | body={snippet}"
        FAILURES.append(msg)
        print(msg)


def login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def rand_email(prefix="dpin") -> str:
    s = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f"{prefix}_{s}@test.com"


def main():
    print(f"Testing against {BASE}")
    # 1) Login as super admin
    print("\n[1] Login as super admin")
    t_super = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"    super token acquired (len={len(t_super)})")

    # 2) GET /api/admin/danger-pin status
    print("\n[2] GET /admin/danger-pin")
    r = requests.get(f"{BASE}/admin/danger-pin", headers=_hdr(t_super), timeout=20)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    is_set_initial = bool(body.get("is_set")) if isinstance(body, dict) else False
    has_format = isinstance(body, dict) and isinstance(body.get("format"), str)
    step("GET danger-pin returns 200 with is_set+format",
         200, r.status_code, body=body, extra_check=has_format)
    print(f"    initial is_set={is_set_initial}, format={(body or {}).get('format') if isinstance(body, dict) else None}")

    # 3) Format validation: invalid PINs should 400 (regardless of is_set state, but
    #    when is_set=true and current_pin is also missing/wrong, server may 401 first.
    #    We deliberately include current_pin to isolate format errors when is_set=true.
    print("\n[3] POST /admin/danger-pin format validation (400 on bad new_pin)")
    if is_set_initial:
        # We don't yet know the current PIN. Try first with no current_pin → may 401.
        # In any case the bad-format cases should be 400 if format check happens before
        # current_pin verification. The implementation actually checks current_pin first
        # if existing; so to test format validation cleanly we will delay format tests
        # until after we successfully set a known PIN. We'll still attempt one to record
        # the actual behavior.
        for bad in ("12345", "abcdef", "1234567"):
            r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                              json={"new_pin": bad}, timeout=20)
            # When PIN is already set and current_pin missing, server returns 401
            # before reaching format check. That's acceptable security-wise.
            print(f"    [pre-set] new_pin={bad!r} -> {r.status_code} {r.text[:120]}")
        # Try to reset with brute attempts of common PINs from prior runs
        candidates = ["654321", "111111", "123456", "000000", "999999"]
        unlocked = False
        current_pin = None
        for cand in candidates:
            r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                              json={"new_pin": "111111", "current_pin": cand}, timeout=20)
            if r.status_code == 200:
                current_pin = "111111"
                unlocked = True
                print(f"    Successfully rotated using current_pin={cand!r}; PIN now '111111'")
                break
        if not unlocked:
            print("    Could not unlock with common PIN candidates; clearing via direct DB workaround NOT permitted in test.")
            print("    This is a TEST environment limitation only — flagging.")
            FAILURES.append(
                "Pre-existing Danger PIN not in known candidate set; cannot proceed with rotation tests. "
                "Main agent may need to reset settings.danger_pin_hash."
            )
            FAIL += 1
            print_summary()
            return
    else:
        current_pin = None  # nothing set yet

    # If we reach here, PIN is either unset OR currently '111111'
    # 4) If currently unset → set first PIN to '111111' (no current_pin)
    if not is_set_initial:
        print("\n[4] First-time POST /admin/danger-pin with new_pin='111111' (no current_pin)")
        r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                          json={"new_pin": "111111"}, timeout=20)
        step("First-time set with valid 6-digit PIN -> 200",
             200, r.status_code, body=r.text)
        current_pin = "111111"

        # Subsequent GET should return is_set=true
        r = requests.get(f"{BASE}/admin/danger-pin", headers=_hdr(t_super), timeout=20)
        body = r.json()
        step("GET after set -> is_set=true",
             200, r.status_code, body=body,
             extra_check=bool(body.get("is_set")) is True)

    # 5) Now PIN is set. Test format validation (with correct current_pin).
    print("\n[5] Format validation with correct current_pin")
    for bad, label in [("12345", "too short"), ("abcdef", "non-digit"), ("1234567", "too long")]:
        r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                          json={"new_pin": bad, "current_pin": current_pin}, timeout=20)
        step(f"new_pin={bad!r} ({label}) -> 400",
             400, r.status_code, body=r.text)

    # 6) POST without current_pin when set → 401
    print("\n[6] POST without current_pin when set -> 401")
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                      json={"new_pin": "222222"}, timeout=20)
    step("Missing current_pin -> 401", 401, r.status_code, body=r.text)

    # 7) POST with wrong current_pin → 401
    print("\n[7] POST with wrong current_pin -> 401")
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                      json={"new_pin": "222222", "current_pin": "999999"}, timeout=20)
    step("Wrong current_pin -> 401", 401, r.status_code, body=r.text)

    # 8) Successful rotation: current_pin → new valid PIN
    print("\n[8] Rotation 111111 -> 222222")
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                      json={"new_pin": "222222", "current_pin": current_pin}, timeout=20)
    step("Rotation with correct current_pin -> 200", 200, r.status_code, body=r.text)
    current_pin = "222222"

    # Old pin should no longer work
    print("\n[8b] Old PIN rejected after rotation")
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                      json={"new_pin": "333333", "current_pin": "111111"}, timeout=20)
    step("Old PIN -> 401 after rotation", 401, r.status_code, body=r.text)

    # 9) Rotate to "654321" (final state)
    print("\n[9] Rotate to final PIN '654321'")
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                      json={"new_pin": "654321", "current_pin": current_pin}, timeout=20)
    step("Rotation to '654321' -> 200", 200, r.status_code, body=r.text)
    DANGER_PIN = "654321"

    # 10) Register a throwaway user so wipe deletes something
    print("\n[10] Register throwaway non-admin user")
    email_throw = rand_email("throw")
    r = requests.post(f"{BASE}/auth/register", json={
        "name": "Throwaway User",
        "email": email_throw,
        "password": "Throw@123",
    }, timeout=20)
    step("Register throwaway -> 200", 200, r.status_code, body=r.text)

    # Count non-admin users for sanity
    r = requests.get(f"{BASE}/admin/users", headers=_hdr(t_super), timeout=20)
    users_before = r.json() if r.status_code == 200 else []
    n_non_admin_before = sum(1 for u in users_before if u.get("role") != "admin")
    print(f"    non-admin users before wipe: {n_non_admin_before}")

    # 11) Wipe with wrong danger_pin → 401
    print("\n[11] POST /admin/system/wipe-users with WRONG pin -> 401")
    r = requests.post(f"{BASE}/admin/system/wipe-users", headers=_hdr(t_super),
                      json={"keep_admins": True, "danger_pin": "000000"}, timeout=20)
    body = r.text
    step("Wipe wrong pin -> 401", 401, r.status_code, body=body,
         extra_check=("Invalid Danger PIN" in body))

    # 12) Wipe with correct danger_pin → 200
    print("\n[12] POST /admin/system/wipe-users with CORRECT pin (keep_admins=true) -> 200")
    r = requests.post(f"{BASE}/admin/system/wipe-users", headers=_hdr(t_super),
                      json={"keep_admins": True, "danger_pin": DANGER_PIN}, timeout=20)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    has_counts = isinstance(body, dict) and all(k in body for k in (
        "users_deleted", "transactions_deleted", "withdrawals_deleted",
        "orders_deleted", "cart_items_deleted", "notifications_deleted"))
    step("Wipe correct pin -> 200 with counts", 200, r.status_code, body=body,
         extra_check=has_counts)

    # Verify admin still works (login + me)
    print("\n[12b] Verify admin login still works post-wipe")
    try:
        t_super = login(ADMIN_EMAIL, ADMIN_PASSWORD)
        r = requests.get(f"{BASE}/auth/me", headers=_hdr(t_super), timeout=20)
        step("Admin /auth/me after wipe -> 200", 200, r.status_code, body=r.text)
    except Exception as e:
        FAIL += 1
        FAILURES.append(f"Admin login broke after wipe: {e}")
        print(f"  FAIL  admin login broke after wipe: {e}")

    # 13) Take a manual snapshot
    print("\n[13] POST /admin/backups note='danger-pin-test'")
    r = requests.post(f"{BASE}/admin/backups", headers=_hdr(t_super),
                      json={"note": "danger-pin-test"}, timeout=20)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    snap_id = (body or {}).get("id") if isinstance(body, dict) else None
    step("Take backup -> 200 with id", 200, r.status_code, body=body,
         extra_check=bool(snap_id))
    print(f"    snap_id = {snap_id}")

    # 14) Restore with wrong pin → 401
    print("\n[14] POST /admin/backups/{id}/restore with WRONG pin -> 401")
    r = requests.post(f"{BASE}/admin/backups/{snap_id}/restore", headers=_hdr(t_super),
                      json={"danger_pin": "111111"}, timeout=20)
    step("Restore wrong pin -> 401", 401, r.status_code, body=r.text,
         extra_check=("Invalid Danger PIN" in r.text))

    # 15) Restore with correct pin → 200
    print("\n[15] POST /admin/backups/{id}/restore with CORRECT pin -> 200")
    r = requests.post(f"{BASE}/admin/backups/{snap_id}/restore", headers=_hdr(t_super),
                      json={"danger_pin": DANGER_PIN}, timeout=20)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    step("Restore correct pin -> 200 with restored", 200, r.status_code, body=body,
         extra_check=isinstance(body, dict) and body.get("ok") is True and "restored" in body)

    # Re-login after restore (snapshot might have a different password_hash than
    # current admin, depending on timing). seed_admin reseeds env values on startup.
    try:
        t_super = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    except Exception:
        time.sleep(2)
        t_super = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    # 16) RBAC tests with manager admin
    print("\n[16] Create a manager admin and test RBAC 403s")
    mgr_email = rand_email("mgr")
    r = requests.post(f"{BASE}/admin/admins", headers=_hdr(t_super),
                      json={"name": "Test Manager", "email": mgr_email,
                            "password": "Mgr@1234", "admin_role": "manager"}, timeout=20)
    step("Create manager admin -> 200", 200, r.status_code, body=r.text)
    mgr_data = r.json() if r.status_code == 200 else {}
    mgr_id = mgr_data.get("id")

    t_mgr = login(mgr_email, "Mgr@1234")

    # GET danger-pin → 403
    r = requests.get(f"{BASE}/admin/danger-pin", headers=_hdr(t_mgr), timeout=20)
    step("Manager GET /admin/danger-pin -> 403", 403, r.status_code, body=r.text)

    # POST danger-pin → 403
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_mgr),
                      json={"new_pin": "999999", "current_pin": DANGER_PIN}, timeout=20)
    step("Manager POST /admin/danger-pin -> 403", 403, r.status_code, body=r.text)

    # POST wipe-users → 403
    r = requests.post(f"{BASE}/admin/system/wipe-users", headers=_hdr(t_mgr),
                      json={"keep_admins": True, "danger_pin": DANGER_PIN}, timeout=20)
    step("Manager POST /admin/system/wipe-users -> 403", 403, r.status_code, body=r.text)

    # POST backups (super_admin only) → 403
    r = requests.post(f"{BASE}/admin/backups", headers=_hdr(t_mgr),
                      json={"note": "mgr"}, timeout=20)
    step("Manager POST /admin/backups -> 403", 403, r.status_code, body=r.text)

    # Need a snap id for the restore RBAC test. Take one as super.
    r = requests.post(f"{BASE}/admin/backups", headers=_hdr(t_super),
                      json={"note": "danger-pin-rbac"}, timeout=20)
    rbac_snap = (r.json() or {}).get("id") if r.status_code == 200 else None

    if rbac_snap:
        r = requests.post(f"{BASE}/admin/backups/{rbac_snap}/restore", headers=_hdr(t_mgr),
                          json={"danger_pin": DANGER_PIN}, timeout=20)
        step("Manager POST /admin/backups/{id}/restore -> 403", 403, r.status_code, body=r.text)

    # Cleanup: delete manager
    if mgr_id:
        # super may need re-login if restore wiped state mid-flight
        try:
            r = requests.delete(f"{BASE}/admin/users/{mgr_id}", headers=_hdr(t_super), timeout=20)
            step("DELETE manager -> 200", 200, r.status_code, body=r.text)
        except Exception as e:
            FAIL += 1
            FAILURES.append(f"Cleanup delete manager failed: {e}")

    # 17) Regression: misc admin endpoints still 200
    print("\n[17] Regression on neighbouring admin endpoints")
    for path in ("/admin/admins", "/admin/users", "/admin/approvals?status=pending", "/admin/backups"):
        r = requests.get(f"{BASE}{path}", headers=_hdr(t_super), timeout=20)
        step(f"GET {path} -> 200", 200, r.status_code, body=r.text[:200])

    # Final sanity: PIN still '654321'
    r = requests.get(f"{BASE}/admin/danger-pin", headers=_hdr(t_super), timeout=20)
    body = r.json() if r.status_code == 200 else {}
    step("Final state: GET danger-pin is_set=true",
         200, r.status_code, body=body,
         extra_check=bool(body.get("is_set")) is True)
    # confirm the PIN is exactly '654321' by attempting a no-op rotation back to itself
    r = requests.post(f"{BASE}/admin/danger-pin", headers=_hdr(t_super),
                      json={"new_pin": "654321", "current_pin": "654321"}, timeout=20)
    step("Confirm PIN is '654321' (rotate to same value -> 200)",
         200, r.status_code, body=r.text)

    print_summary()


def print_summary():
    print("\n========================================")
    print(f"PASSED: {PASS}")
    print(f"FAILED: {FAIL}")
    if FAILURES:
        print("\nFailures:")
        for f in FAILURES:
            print(f"  - {f}")
    print("========================================")


if __name__ == "__main__":
    main()
    sys.exit(0 if FAIL == 0 else 1)
