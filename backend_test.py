"""Backend test for Distributor Network / Area Mapping feature.

Tests 7 endpoints + 19,300 India pincodes seed against:
  https://network-pay-1.preview.emergentagent.com
"""
import sys
import uuid
import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
FINANCE_EMAIL = "finance@app.com"
FINANCE_PASSWORD = "Finance@123"

PASS = []
FAIL = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        PASS.append(label)
        print(f"  PASS {label}")
    else:
        FAIL.append((label, detail))
        print(f"  FAIL {label}  ::  {detail}")


def H(token):
    return {"Authorization": f"Bearer {token}"}


def login(email: str, password: str):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        return None, r
    j = r.json()
    return j["token"], r


def register(name, email, password, ref_code=None):
    body = {"name": name, "email": email, "password": password}
    if ref_code:
        body["referral_code"] = ref_code
    r = requests.post(f"{BASE}/auth/register", json=body, timeout=20)
    return r


def main():
    print("\n=== Login as super_admin ===")
    admin_tok, r = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    check("admin login -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if not admin_tok:
        print("FATAL: cannot login admin")
        return False

    r = requests.get(f"{BASE}/auth/me", headers=H(admin_tok), timeout=20)
    admin_id = r.json()["id"]
    print(f"  admin_id={admin_id}")

    # Ensure finance admin exists (seed if needed)
    fin_tok, r = login(FINANCE_EMAIL, FINANCE_PASSWORD)
    if not fin_tok:
        print("  finance login failed, creating finance admin via /admin/admins")
        rc = requests.post(
            f"{BASE}/admin/admins",
            headers=H(admin_tok),
            json={"name": "Finance Admin", "email": FINANCE_EMAIL,
                  "password": FINANCE_PASSWORD, "phone": "9999000001",
                  "admin_role": "finance"},
            timeout=20,
        )
        print(f"  /admin/admins create -> {rc.status_code} {rc.text[:200]}")
        fin_tok, r = login(FINANCE_EMAIL, FINANCE_PASSWORD)
    check("finance login -> 200", bool(fin_tok), f"{r.status_code} {r.text[:200]}")

    # ========== SCENARIO 1: search by digit prefix ==========
    print("\n=== S1: GET /admin/pincodes/search?q=500001 ===")
    r = requests.get(f"{BASE}/admin/pincodes/search", headers=H(admin_tok),
                     params={"q": "500001"}, timeout=20)
    check("S1.1 status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        check("S1.2 at least 1 row", len(items) >= 1, f"got {len(items)}")
        if items:
            row = next((x for x in items if x.get("pincode") == "500001"), items[0])
            check("S1.3 district == Hyderabad",
                  (row.get("district") or "").lower() == "hyderabad",
                  f"district={row.get('district')}")
            check("S1.4 state == Telangana",
                  (row.get("state") or "").lower() == "telangana",
                  f"state={row.get('state')}")

    # ========== SCENARIO 2: text search ==========
    print("\n=== S2: GET /admin/pincodes/search?q=Bangalore ===")
    r = requests.get(f"{BASE}/admin/pincodes/search", headers=H(admin_tok),
                     params={"q": "Bangalore"}, timeout=20)
    check("S2.1 status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        check("S2.2 at least 1 row", len(items) >= 1, f"got {len(items)}")
        karnataka_rows = [x for x in items if (x.get("state") or "").lower() == "karnataka"]
        check("S2.3 has rows with state=Karnataka",
              len(karnataka_rows) >= 1,
              f"karnataka_count={len(karnataka_rows)}, sample={items[:2]}")

    # ========== SCENARIO 3: 404 on non-existent pincode ==========
    print("\n=== S3: GET /admin/pincodes/000000 -> 404 ===")
    r = requests.get(f"{BASE}/admin/pincodes/000000", headers=H(admin_tok), timeout=20)
    check("S3.1 status 404", r.status_code == 404, f"{r.status_code} {r.text[:200]}")

    # ========== SCENARIO 4: register two non-admin users + promote ==========
    print("\n=== S4: register two users + promote first ===")
    rand_a = uuid.uuid4().hex[:8]
    rand_b = uuid.uuid4().hex[:8]
    email_a = f"distb1.{rand_a}@mailinator.com"
    email_b = f"distb2.{rand_b}@mailinator.com"

    ra = register("Ravi Distributor", email_a, "Pass@1234")
    check("S4.0a register user A", ra.status_code == 200, f"{ra.status_code} {ra.text[:200]}")
    if ra.status_code != 200:
        return False
    user_a_id = ra.json()["user"]["id"]

    rb = register("Sneha Distributor", email_b, "Pass@1234")
    check("S4.0b register user B", rb.status_code == 200, f"{rb.status_code} {rb.text[:200]}")
    if rb.status_code != 200:
        return False
    user_b_id = rb.json()["user"]["id"]

    r = requests.post(f"{BASE}/admin/users/{user_a_id}/distributor",
                      headers=H(admin_tok), json={"is_distributor": True}, timeout=20)
    check("S4.1 promote A -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        check("S4.2 is_distributor=true",
              r.json().get("is_distributor") is True, f"resp={r.json()}")

    # ========== SCENARIO 5: list distributors ==========
    print("\n=== S5: GET /admin/distributors ===")
    r = requests.get(f"{BASE}/admin/distributors", headers=H(admin_tok), timeout=20)
    check("S5.1 status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        items = r.json().get("items", [])
        a_row = next((x for x in items if x.get("id") == user_a_id), None)
        check("S5.2 user A in distributors list", a_row is not None,
              f"items_emails={[x.get('email') for x in items]}")
        if a_row:
            check("S5.3 pincode_count == 0",
                  a_row.get("pincode_count") == 0, f"count={a_row.get('pincode_count')}")

    # ========== SCENARIO 6: assign with one invalid pincode -> 400 ==========
    print("\n=== S6: POST areas with bad pincode -> 400 ===")
    r = requests.post(
        f"{BASE}/admin/distributors/{user_a_id}/areas",
        headers=H(admin_tok),
        json={"pincodes": ["500001", "500003", "999999"]},
        timeout=20,
    )
    check("S6.1 status 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 400:
        detail = r.json().get("detail", "")
        check("S6.2 detail mentions 999999 / not in master",
              "999999" in detail or "not in master" in detail.lower(),
              f"detail={detail}")

    # ========== SCENARIO 7: assign 2 valid pincodes -> 200 ==========
    print("\n=== S7: POST areas {500001, 500003} ===")
    r = requests.post(
        f"{BASE}/admin/distributors/{user_a_id}/areas",
        headers=H(admin_tok),
        json={"pincodes": ["500001", "500003"]},
        timeout=20,
    )
    check("S7.1 status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("S7.2 new_assignments == 2",
              body.get("new_assignments") == 2, f"resp={body}")

    # ========== SCENARIO 8: GET areas -> 2 items with district/state ==========
    print("\n=== S8: GET /admin/distributors/{a}/areas ===")
    r = requests.get(f"{BASE}/admin/distributors/{user_a_id}/areas",
                     headers=H(admin_tok), timeout=20)
    check("S8.1 status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        items = body.get("items", [])
        check("S8.2 total=2", body.get("total") == 2 and len(items) == 2,
              f"total={body.get('total')}, items={items}")
        for it in items:
            check(f"S8.3[{it.get('pincode')}] district filled",
                  bool(it.get("district")), f"row={it}")
            check(f"S8.4[{it.get('pincode')}] state filled",
                  bool(it.get("state")), f"row={it}")
        r1 = next((x for x in items if x.get("pincode") == "500001"), None)
        if r1:
            check("S8.5 500001 -> Hyderabad/Telangana",
                  (r1.get("district") or "").lower() == "hyderabad" and
                  (r1.get("state") or "").lower() == "telangana",
                  f"row={r1}")

    # ========== SCENARIO 9: promote B + assign 500001 -> reassigned=1 ==========
    print("\n=== S9: promote B + assign 500001 -> reassigned=1 ===")
    r = requests.post(f"{BASE}/admin/users/{user_b_id}/distributor",
                      headers=H(admin_tok), json={"is_distributor": True}, timeout=20)
    check("S9.0 promote B -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    r = requests.post(
        f"{BASE}/admin/distributors/{user_b_id}/areas",
        headers=H(admin_tok),
        json={"pincodes": ["500001"]},
        timeout=20,
    )
    check("S9.1 status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("S9.2 reassigned == 1",
              body.get("reassigned") == 1, f"resp={body}")

    # ========== SCENARIO 10: A no longer has 500001; B has it ==========
    print("\n=== S10: exclusivity check ===")
    r = requests.get(f"{BASE}/admin/distributors/{user_a_id}/areas",
                     headers=H(admin_tok), timeout=20)
    if r.status_code == 200:
        a_pins = [x.get("pincode") for x in r.json().get("items", [])]
        check("S10.1 A no longer has 500001",
              "500001" not in a_pins, f"A pins={a_pins}")
        check("S10.2 A still has 500003",
              "500003" in a_pins, f"A pins={a_pins}")

    r = requests.get(f"{BASE}/admin/distributors/{user_b_id}/areas",
                     headers=H(admin_tok), timeout=20)
    if r.status_code == 200:
        b_pins = [x.get("pincode") for x in r.json().get("items", [])]
        check("S10.3 B has 500001",
              "500001" in b_pins, f"B pins={b_pins}")

    # Verify via single-pincode lookup
    r = requests.get(f"{BASE}/admin/pincodes/500001", headers=H(admin_tok), timeout=20)
    if r.status_code == 200:
        a = r.json().get("assigned_to") or {}
        check("S10.4 /pincodes/500001 assigned_to.distributor_id == B",
              a.get("distributor_id") == user_b_id, f"assigned_to={a}")

    # ========== SCENARIO 11: DELETE B's mapping for 500001 ==========
    print("\n=== S11: DELETE /distributors/B/areas/500001 ===")
    r = requests.delete(f"{BASE}/admin/distributors/{user_b_id}/areas/500001",
                        headers=H(admin_tok), timeout=20)
    check("S11.1 DELETE -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    r = requests.get(f"{BASE}/admin/distributors/{user_b_id}/areas",
                     headers=H(admin_tok), timeout=20)
    if r.status_code == 200:
        items = r.json().get("items", [])
        check("S11.2 B's areas now empty",
              len(items) == 0, f"items={items}")

    # ========== SCENARIO 12: cannot promote admin ==========
    print("\n=== S12: promote admin user -> 400 ===")
    r = requests.post(f"{BASE}/admin/users/{admin_id}/distributor",
                      headers=H(admin_tok), json={"is_distributor": True}, timeout=20)
    check("S12.1 status 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
    if r.status_code == 400:
        check("S12.2 detail mentions admins",
              "admin" in r.json().get("detail", "").lower(),
              f"detail={r.json().get('detail')}")

    # ========== SCENARIO 13: demote A -> mappings dropped ==========
    print("\n=== S13: demote A -> mappings dropped ===")
    r = requests.get(f"{BASE}/admin/distributors/{user_a_id}/areas",
                     headers=H(admin_tok), timeout=20)
    pre_count = len(r.json().get("items", [])) if r.status_code == 200 else 0
    check("S13.0 A had >=1 mapping pre-demote", pre_count >= 1, f"pre_count={pre_count}")

    r = requests.post(f"{BASE}/admin/users/{user_a_id}/distributor",
                      headers=H(admin_tok), json={"is_distributor": False}, timeout=20)
    check("S13.1 demote A -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    r = requests.get(f"{BASE}/admin/distributors/{user_a_id}/areas",
                     headers=H(admin_tok), timeout=20)
    if r.status_code == 200:
        items = r.json().get("items", [])
        check("S13.2 A's mappings dropped",
              len(items) == 0, f"items={items}")

    r = requests.get(f"{BASE}/admin/distributors", headers=H(admin_tok), timeout=20)
    if r.status_code == 200:
        ids = [x.get("id") for x in r.json().get("items", [])]
        check("S13.3 A not in distributors list anymore",
              user_a_id not in ids, f"A_in_list={user_a_id in ids}")

    # ========== SCENARIO 14: no auth -> 401 ==========
    print("\n=== S14: anon -> 401 ===")
    r = requests.get(f"{BASE}/admin/pincodes/search?q=500001", timeout=20)
    check("S14.1 search anon -> 401",
          r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}")
    r = requests.get(f"{BASE}/admin/distributors", timeout=20)
    check("S14.2 list anon -> 401",
          r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}")
    r = requests.post(f"{BASE}/admin/distributors/{user_b_id}/areas",
                      json={"pincodes": ["500001"]}, timeout=20)
    check("S14.3 assign anon -> 401",
          r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}")

    # ========== SCENARIO 15: finance -> 403 on POST/DELETE ==========
    print("\n=== S15: finance role -> 403 on mutations ===")
    if fin_tok:
        r = requests.get(f"{BASE}/admin/pincodes/search?q=500001",
                         headers=H(fin_tok), timeout=20)
        check("S15.0 finance GET search -> 200", r.status_code == 200,
              f"{r.status_code} {r.text[:200]}")

        r = requests.post(f"{BASE}/admin/users/{user_b_id}/distributor",
                          headers=H(fin_tok),
                          json={"is_distributor": False}, timeout=20)
        check("S15.1 finance promote -> 403", r.status_code == 403,
              f"{r.status_code} {r.text[:200]}")

        r = requests.post(f"{BASE}/admin/distributors/{user_b_id}/areas",
                          headers=H(fin_tok),
                          json={"pincodes": ["500001"]}, timeout=20)
        check("S15.2 finance assign -> 403", r.status_code == 403,
              f"{r.status_code} {r.text[:200]}")

        r = requests.delete(f"{BASE}/admin/distributors/{user_b_id}/areas/500001",
                            headers=H(fin_tok), timeout=20)
        check("S15.3 finance unassign -> 403", r.status_code == 403,
              f"{r.status_code} {r.text[:200]}")
    else:
        print("  WARNING: skipping finance tests -- login failed")

    # ========== Cleanup ==========
    print("\n=== Cleanup ===")
    requests.post(f"{BASE}/admin/users/{user_b_id}/distributor",
                  headers=H(admin_tok), json={"is_distributor": False}, timeout=20)
    for uid in (user_a_id, user_b_id):
        rd = requests.delete(f"{BASE}/admin/users/{uid}", headers=H(admin_tok), timeout=20)
        print(f"  delete {uid[:8]} -> {rd.status_code}")

    print("\n" + "=" * 70)
    print(f"TOTAL: PASS={len(PASS)}  FAIL={len(FAIL)}")
    if FAIL:
        print("\nFAILURES:")
        for label, detail in FAIL:
            print(f"  FAIL {label} :: {detail}")
    print("=" * 70)
    return len(FAIL) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
