"""
Test the TWO new Distributor Area-Mapping admin endpoints:
  1) POST /api/admin/distributors/{user_id}/areas/bulk-unassign
  2) GET  /api/admin/pincodes/in-region

Run against the public preview URL (no localhost).
"""
import os
import sys
import time
import uuid
import json
import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
FIN_EMAIL = "finance@app.com"
FIN_PASS = "Finance@123"

PASS = []
FAIL = []


def rec(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    sym = "✅" if ok else "❌"
    print(f"  {sym} {name}" + (f" — {detail}" if detail and not ok else ""))


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        return None, r
    return r.json().get("access_token") or r.json().get("token"), r


def main():
    print("=== STEP a — login admin ===")
    tok_a, r = login(ADMIN_EMAIL, ADMIN_PASS)
    rec("admin login → 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    if not tok_a:
        print("FATAL: cannot login admin. Aborting.")
        return summarise()
    H_A = {"Authorization": f"Bearer {tok_a}"}

    print("\n=== STEP b — login finance (create if missing) ===")
    tok_f, r = login(FIN_EMAIL, FIN_PASS)
    if r.status_code != 200:
        print(f"  finance login failed ({r.status_code}); creating finance@app.com via /admin/admins")
        cr = requests.post(
            f"{BASE}/admin/admins",
            headers=H_A,
            json={"email": FIN_EMAIL, "password": FIN_PASS, "name": "Finance Admin", "admin_role": "finance"},
            timeout=20,
        )
        rec("create finance admin → 200/201/409 ok", cr.status_code in (200, 201, 409),
            f"got {cr.status_code} {cr.text[:200]}")
        tok_f, r = login(FIN_EMAIL, FIN_PASS)
    rec("finance login → 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    H_F = {"Authorization": f"Bearer {tok_f}"} if tok_f else None

    print("\n=== STEP c — register fresh user + promote distributor ===")
    rand = uuid.uuid4().hex[:8]
    email = f"distbulk.{rand}@mailinator.com"
    rr = requests.post(
        f"{BASE}/auth/register",
        json={"name": f"DistBulk {rand}", "email": email, "password": "Test@12345", "phone": f"99999{rand[:5]}"},
        timeout=20,
    )
    rec("register fresh user → 200", rr.status_code == 200, f"got {rr.status_code} {rr.text[:200]}")
    if rr.status_code != 200:
        return summarise()
    user_id = rr.json().get("user", {}).get("id") or rr.json().get("id")
    rec("user_id present", bool(user_id), str(rr.json())[:200])
    print(f"  user_id={user_id}, email={email}")

    promo = requests.post(
        f"{BASE}/admin/users/{user_id}/distributor",
        headers=H_A,
        json={"is_distributor": True},
        timeout=20,
    )
    rec("promote to distributor → 200", promo.status_code == 200,
        f"got {promo.status_code} {promo.text[:200]}")

    print("\n=== STEP d — assign 500001/500003/500004 ===")
    asn = requests.post(
        f"{BASE}/admin/distributors/{user_id}/areas",
        headers=H_A,
        json={"pincodes": ["500001", "500003", "500004"]},
        timeout=20,
    )
    rec("assign 3 pincodes → 200", asn.status_code == 200,
        f"got {asn.status_code} {asn.text[:200]}")
    print(f"  assign body: {asn.text[:200]}")

    # Verify all 3 are present
    g0 = requests.get(f"{BASE}/admin/distributors/{user_id}/areas", headers=H_A, timeout=20)
    pins0 = sorted([it["pincode"] for it in g0.json().get("items", [])]) if g0.status_code == 200 else []
    rec("3 pincodes appear in areas", set(pins0) >= {"500001", "500003", "500004"},
        f"got {pins0}")

    print("\n=== STEP e — bulk-unassign ['500001','500003'] → expect removed=2,requested=2 ===")
    bu = requests.post(
        f"{BASE}/admin/distributors/{user_id}/areas/bulk-unassign",
        headers=H_A,
        json={"pincodes": ["500001", "500003"]},
        timeout=20,
    )
    rec("bulk-unassign status 200", bu.status_code == 200, f"got {bu.status_code} {bu.text[:200]}")
    if bu.status_code == 200:
        body = bu.json()
        rec("response.ok == True", body.get("ok") is True, str(body))
        rec("response.removed == 2", body.get("removed") == 2, str(body))
        rec("response.requested == 2", body.get("requested") == 2, str(body))

    print("\n=== STEP f — GET areas → only 500004 remains ===")
    g1 = requests.get(f"{BASE}/admin/distributors/{user_id}/areas", headers=H_A, timeout=20)
    pins1 = sorted([it["pincode"] for it in g1.json().get("items", [])]) if g1.status_code == 200 else []
    rec("only 500004 remains", pins1 == ["500004"], f"got {pins1}")

    print("\n=== STEP g — bulk-unassign [] → 400 ===")
    bu_empty = requests.post(
        f"{BASE}/admin/distributors/{user_id}/areas/bulk-unassign",
        headers=H_A,
        json={"pincodes": []},
        timeout=20,
    )
    # NOTE: DistributorAreaAssign may reject [] at Pydantic level (422). Per spec, expect 400.
    rec("bulk-unassign empty list → 400", bu_empty.status_code == 400,
        f"got {bu_empty.status_code} {bu_empty.text[:200]}")
    if bu_empty.status_code == 400:
        rec("error detail mentions 'No pincodes provided'",
            "no pincodes" in bu_empty.text.lower(), bu_empty.text[:200])

    print("\n=== STEP h — bulk-unassign as finance → 403 ===")
    if H_F:
        bu_fin = requests.post(
            f"{BASE}/admin/distributors/{user_id}/areas/bulk-unassign",
            headers=H_F,
            json={"pincodes": ["500004"]},
            timeout=20,
        )
        rec("finance bulk-unassign → 403", bu_fin.status_code == 403,
            f"got {bu_fin.status_code} {bu_fin.text[:200]}")
    else:
        rec("finance bulk-unassign → 403 (skipped: no finance token)", False, "finance login failed")

    print("\n=== STEP i — GET in-region?state=Telangana&district=Hyderabad ===")
    rr = requests.get(
        f"{BASE}/admin/pincodes/in-region",
        params={"state": "Telangana", "district": "Hyderabad"},
        headers=H_A,
        timeout=30,
    )
    rec("in-region status 200", rr.status_code == 200, f"got {rr.status_code} {rr.text[:200]}")
    if rr.status_code == 200:
        body = rr.json()
        items = body.get("items", [])
        total = body.get("total")
        rec("items length ≥ 1", len(items) >= 1, f"len={len(items)}")
        rec("total present and == len(items)", total == len(items), f"total={total} len={len(items)}")
        # Check fields on first
        if items:
            sample = items[0]
            rec("row has pincode field", "pincode" in sample, str(sample)[:200])
            rec("row has state field", "state" in sample, str(sample)[:200])
            rec("row has district field", "district" in sample, str(sample)[:200])
            rec("row has office field", "office" in sample, str(sample)[:200])
            rec("row has assigned_to key", "assigned_to" in sample, str(sample)[:200])
        # Find 500004 row — should be assigned_to populated
        row_500004 = next((it for it in items if it.get("pincode") == "500004"), None)
        if row_500004:
            at = row_500004.get("assigned_to")
            rec("500004.assigned_to populated (non-null)", bool(at), str(row_500004)[:300])
            if at:
                rec("500004.assigned_to.distributor_id matches user_id",
                    at.get("distributor_id") == user_id, str(at))
                rec("500004.assigned_to.distributor_name present", bool(at.get("distributor_name")), str(at))
                rec("500004.assigned_to.distributor_email present", bool(at.get("distributor_email")), str(at))
        else:
            rec("500004 in items", False, "500004 not found in results — may not be in district Hyderabad")
        # Find at least one row that's null (others not assigned)
        null_rows = [it for it in items if it.get("pincode") != "500004" and it.get("assigned_to") is None]
        rec("other rows have assigned_to == null (sample)", len(null_rows) >= 1,
            f"non-500004 rows total={len(items)-1}, null={len(null_rows)}")

    print("\n=== STEP j — GET in-region (no params) → 400 ===")
    np = requests.get(f"{BASE}/admin/pincodes/in-region", headers=H_A, timeout=20)
    rec("no params → 400", np.status_code == 400, f"got {np.status_code} {np.text[:200]}")

    print("\n=== STEP k — GET in-region?district=NonExistentDistrictXyz → 200 [] ===")
    nx = requests.get(
        f"{BASE}/admin/pincodes/in-region",
        params={"district": "NonExistentDistrictXyz"},
        headers=H_A,
        timeout=20,
    )
    rec("nonexistent district → 200", nx.status_code == 200,
        f"got {nx.status_code} {nx.text[:200]}")
    if nx.status_code == 200:
        body = nx.json()
        rec("items == []", body.get("items") == [], str(body)[:200])
        rec("total == 0", body.get("total") == 0, str(body)[:200])

    print("\n=== STEP l — anon GET in-region → 401/403 ===")
    an = requests.get(
        f"{BASE}/admin/pincodes/in-region",
        params={"state": "Telangana"},
        timeout=20,
    )
    rec("anon → 401 or 403", an.status_code in (401, 403),
        f"got {an.status_code} {an.text[:200]}")

    # Bonus: anon bulk-unassign too
    an2 = requests.post(
        f"{BASE}/admin/distributors/{user_id}/areas/bulk-unassign",
        json={"pincodes": ["500004"]},
        timeout=20,
    )
    rec("anon bulk-unassign → 401/403", an2.status_code in (401, 403),
        f"got {an2.status_code} {an2.text[:200]}")

    print("\n=== CLEANUP ===")
    # Bulk-unassign 500004
    cu = requests.post(
        f"{BASE}/admin/distributors/{user_id}/areas/bulk-unassign",
        headers=H_A,
        json={"pincodes": ["500004"]},
        timeout=20,
    )
    print(f"  cleanup bulk-unassign 500004: {cu.status_code} {cu.text[:120]}")

    # Demote
    dem = requests.post(
        f"{BASE}/admin/users/{user_id}/distributor",
        headers=H_A,
        json={"is_distributor": False},
        timeout=20,
    )
    print(f"  demote distributor: {dem.status_code} {dem.text[:120]}")

    # Delete user
    du = requests.delete(f"{BASE}/admin/users/{user_id}", headers=H_A, timeout=20)
    print(f"  delete user: {du.status_code} {du.text[:120]}")

    return summarise()


def summarise():
    print("\n" + "=" * 70)
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFAILED:")
        for n, d in FAIL:
            print(f"  - {n}: {d}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
