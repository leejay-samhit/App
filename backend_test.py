"""
Backend test — Service Application Management & Service Categories.

Covers all scenarios from review request:
  1. GET /admin/service-categories returns 13 seeded categories
  2. POST creates a category
  3. Duplicate POST → 400
  4. PATCH sort_order + active
  5. /services/categories filters out inactive
  6. PATCH active=true → reappears
  7. DELETE hard-deletes when no providers linked
  8. POST /service/apply with category_id + languages
  9. Admin approves the application
 10. GET /services returns category_id + service_languages
 11. GET /services?category_id=...
 12. GET /services?language=te
 13. RBAC — finance cannot create category (403); super_admin can
 14. Validation — name too short → 422
 15. Auth — missing token → 401
"""
import json
import time
import uuid
import requests

BASE = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
FINANCE_EMAIL = "finance@app.com"
FINANCE_PASSWORD = "Finance@123"


# ---------- helpers ----------

def login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def H(token: str):
    return {"Authorization": f"Bearer {token}"}


def register_user(name: str, email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/register", json={
        "name": name, "email": email, "password": password,
    }, timeout=20)
    r.raise_for_status()
    return r.json()


# ---------- counters ----------
PASS = 0
FAIL = 0
FAILURES = []


def check(cond, label, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        FAILURES.append(f"{label} :: {extra}")
        print(f"  ❌ {label}  -- {extra}")


# ---------- main ----------

def main():
    print("=" * 80)
    print("Service Categories + Applications backend test")
    print(f"Base: {API}")
    print("=" * 80)

    # Login admin
    print("\n[Setup] Login admin & finance")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    finance_token = None
    try:
        finance_token = login(FINANCE_EMAIL, FINANCE_PASSWORD)
    except Exception as e:
        print(f"  ⚠ finance login failed (will skip 13b): {e}")

    # ------------------------------------------------------------
    # 15. GET /admin/service-categories without auth → 401
    # ------------------------------------------------------------
    print("\n[15] GET /admin/service-categories without auth → 401")
    r = requests.get(f"{API}/admin/service-categories", timeout=20)
    check(r.status_code in (401, 403), f"unauth → 401/403", f"got {r.status_code} {r.text[:120]}")

    # ------------------------------------------------------------
    # 1. Seeded categories — at least 13 default ones
    # ------------------------------------------------------------
    print("\n[1] GET /admin/service-categories → expect ≥13 default categories")
    r = requests.get(f"{API}/admin/service-categories", headers=H(admin_token), timeout=20)
    check(r.status_code == 200, "GET /admin/service-categories 200", f"{r.status_code} {r.text[:120]}")
    cats = r.json().get("categories", [])
    names = [c["name"] for c in cats]
    expected_names = [
        "Plumber", "Electrician", "AC Repair", "Painter", "Carpenter",
        "CCTV Technician", "Cleaning", "Water Tank Cleaning",
        "Toilet Cleaner", "Construction Labour", "Internet Installation",
        "House Construction Labour", "Mobile Repair",
    ]
    missing = [n for n in expected_names if n not in names]
    check(not missing, f"all 13 default categories present (have {len(cats)})", f"missing={missing}")
    # Each row has provider_count
    has_pc = all("provider_count" in c for c in cats)
    check(has_pc, "every category has provider_count field")

    # Capture a default cat_id for scenario 8
    plumber = next((c for c in cats if c["name"] == "Plumber"), None)
    check(plumber is not None, "Plumber category found")
    plumber_id = plumber["id"] if plumber else None

    # ------------------------------------------------------------
    # 2. POST a new category
    # ------------------------------------------------------------
    print("\n[2] POST /admin/service-categories — create 'Test Category XYZ'")
    new_cat_payload = {
        "name": "Test Category XYZ",
        "icon": "star",
        "color": "#FF0000",
    }
    r = requests.post(f"{API}/admin/service-categories", headers=H(admin_token),
                      json=new_cat_payload, timeout=20)
    check(r.status_code == 200, "POST create 200", f"{r.status_code} {r.text[:200]}")
    body = r.json()
    new_cat = body.get("category", {})
    new_cat_id = new_cat.get("id")
    check(bool(new_cat_id), "new category has id")
    check(new_cat.get("slug") == "test-category-xyz", "slug auto-generated",
          f"slug={new_cat.get('slug')}")
    check(new_cat.get("icon") == "star", "icon stored")
    check(new_cat.get("color") == "#FF0000", "color stored")
    check(new_cat.get("active") is True, "default active=true")

    # ------------------------------------------------------------
    # 3. Duplicate POST → 400
    # ------------------------------------------------------------
    print("\n[3] POST same payload again → 400 (duplicate)")
    r = requests.post(f"{API}/admin/service-categories", headers=H(admin_token),
                      json=new_cat_payload, timeout=20)
    check(r.status_code == 400, "duplicate → 400", f"got {r.status_code}: {r.text[:200]}")

    # ------------------------------------------------------------
    # 4. PATCH sort_order + active=false
    # ------------------------------------------------------------
    print("\n[4] PATCH sort_order=555, active=false")
    r = requests.patch(f"{API}/admin/service-categories/{new_cat_id}",
                       headers=H(admin_token),
                       json={"sort_order": 555, "active": False}, timeout=20)
    check(r.status_code == 200, "PATCH 200", f"{r.status_code} {r.text[:200]}")
    upd = r.json().get("category", {})
    check(upd.get("sort_order") == 555, "sort_order=555")
    check(upd.get("active") is False, "active=false")

    # ------------------------------------------------------------
    # 5. /services/categories — inactive should NOT appear
    # ------------------------------------------------------------
    print("\n[5] GET /services/categories — 'Test Category XYZ' must NOT appear (inactive)")
    r = requests.get(f"{API}/services/categories", headers=H(admin_token), timeout=20)
    check(r.status_code == 200, "GET /services/categories 200")
    pub_cats = r.json().get("categories", [])
    pub_names = [c["name"] for c in pub_cats]
    check("Test Category XYZ" not in pub_names,
          "inactive category hidden from public listing",
          f"public names: {pub_names}")
    has_pc_pub = all("provider_count" in c for c in pub_cats)
    check(has_pc_pub, "public listing rows include provider_count")

    # ------------------------------------------------------------
    # 6. PATCH active=true → reappears
    # ------------------------------------------------------------
    print("\n[6] PATCH active=true → reappears in /services/categories")
    r = requests.patch(f"{API}/admin/service-categories/{new_cat_id}",
                       headers=H(admin_token),
                       json={"active": True}, timeout=20)
    check(r.status_code == 200, "PATCH active=true 200")
    r = requests.get(f"{API}/services/categories", headers=H(admin_token), timeout=20)
    pub_names_after = [c["name"] for c in r.json().get("categories", [])]
    check("Test Category XYZ" in pub_names_after, "category re-appears when active",
          f"names: {pub_names_after}")

    # ------------------------------------------------------------
    # 7. DELETE → no providers linked → hard-delete 200 deleted=true
    # ------------------------------------------------------------
    print("\n[7] DELETE — no providers link → hard delete 200 deleted=true")
    r = requests.delete(f"{API}/admin/service-categories/{new_cat_id}",
                        headers=H(admin_token), timeout=20)
    check(r.status_code == 200, "DELETE 200", f"{r.status_code} {r.text[:200]}")
    body = r.json()
    check(body.get("deleted") is True, "deleted: true",
          f"body={body}")
    # Verify gone
    r = requests.get(f"{API}/admin/service-categories", headers=H(admin_token), timeout=20)
    after_names = [c["name"] for c in r.json().get("categories", [])]
    check("Test Category XYZ" not in after_names, "category removed from admin list")

    # ------------------------------------------------------------
    # 13. RBAC POST: super_admin 200, finance 403
    # ------------------------------------------------------------
    print("\n[13] RBAC: super_admin 200, finance 403")
    rbac_payload = {"name": f"RBAC Test {uuid.uuid4().hex[:6]}", "icon": "tag", "color": "#123456"}
    r = requests.post(f"{API}/admin/service-categories", headers=H(admin_token),
                      json=rbac_payload, timeout=20)
    check(r.status_code == 200, "super_admin POST 200", f"{r.status_code} {r.text[:200]}")
    rbac_cat_id = (r.json() or {}).get("category", {}).get("id")

    if finance_token:
        r2 = requests.post(f"{API}/admin/service-categories", headers=H(finance_token),
                           json={"name": f"Finance Try {uuid.uuid4().hex[:6]}"}, timeout=20)
        check(r2.status_code == 403, "finance POST 403", f"got {r2.status_code} {r2.text[:200]}")

    # Cleanup the RBAC test cat
    if rbac_cat_id:
        requests.delete(f"{API}/admin/service-categories/{rbac_cat_id}", headers=H(admin_token), timeout=20)

    # ------------------------------------------------------------
    # 14. Validation — bad input
    # ------------------------------------------------------------
    print("\n[14] POST with name='X' (too short) → 422")
    r = requests.post(f"{API}/admin/service-categories", headers=H(admin_token),
                      json={"name": "X"}, timeout=20)
    check(r.status_code == 422, "name too short → 422", f"got {r.status_code} {r.text[:200]}")

    # ------------------------------------------------------------
    # 8. /service/apply with category_id + languages
    # ------------------------------------------------------------
    print("\n[8] /service/apply with category_id + languages: ['en','te']")
    # Create a fresh user
    suffix = uuid.uuid4().hex[:8]
    user_email = f"svc_apply_{suffix}@example.com"
    reg = register_user("Ravi Kumar", user_email, "User@1234")
    user_token = reg["token"]
    user_id = reg["user"]["id"]

    # Pay registration fee (legacy mock — marks user as paid; commissions don't fire here)
    rp = requests.post(f"{API}/payment/register-fee", headers=H(user_token), timeout=20)
    check(rp.status_code == 200, "user registration paid (legacy)",
          f"{rp.status_code} {rp.text[:200]}")

    apply_payload = {
        "service_name": "Same-day Plumbing",
        "service_category": "Plumber",   # required by model min_length=2
        "category_id": plumber_id,
        "pincode": "560001",
        "charge": 750,
        "languages": ["en", "te"],
        "description": "Quick response leak fixes",
    }
    r = requests.post(f"{API}/service/apply", headers=H(user_token),
                      json=apply_payload, timeout=20)
    check(r.status_code == 200, "POST /service/apply 200",
          f"{r.status_code} {r.text[:300]}")
    app_doc = r.json().get("application", {})
    app_id = app_doc.get("id")
    check(app_doc.get("category_id") == plumber_id, "category_id stored on application")
    check(app_doc.get("languages") == ["en", "te"], "languages stored on application",
          f"got={app_doc.get('languages')}")

    # ------------------------------------------------------------
    # 9. Approve as admin
    # ------------------------------------------------------------
    print("\n[9] Approve service-application as admin")
    r = requests.post(f"{API}/admin/service-applications/{app_id}/approve",
                      headers=H(admin_token), timeout=20)
    check(r.status_code == 200, "approve 200",
          f"{r.status_code} {r.text[:200]}")

    # ------------------------------------------------------------
    # 10. GET /services as any user → shows the provider w/ category_id + service_languages
    # ------------------------------------------------------------
    print("\n[10] GET /services — provider visible with category_id + service_languages")
    r = requests.get(f"{API}/services", headers=H(user_token), timeout=20)
    check(r.status_code == 200, "GET /services 200")
    items = r.json().get("items", [])
    me_row = next((it for it in items if it.get("id") == user_id), None)
    check(me_row is not None, "approved provider in /services")
    if me_row:
        check(me_row.get("category_id") == plumber_id,
              "row has category_id == plumber_id",
              f"got={me_row.get('category_id')}")
        check(sorted(me_row.get("service_languages") or []) == ["en", "te"],
              "row has service_languages == ['en','te']",
              f"got={me_row.get('service_languages')}")

    # ------------------------------------------------------------
    # 11. GET /services?category_id=<plumber_id>
    # ------------------------------------------------------------
    print("\n[11] GET /services?category_id=<plumber_id>")
    r = requests.get(f"{API}/services", headers=H(user_token),
                     params={"category_id": plumber_id}, timeout=20)
    check(r.status_code == 200, "filter category_id 200")
    items = r.json().get("items", [])
    check(any(it.get("id") == user_id for it in items),
          "provider returned in category filter")
    check(all(it.get("category_id") == plumber_id for it in items),
          "all returned rows have category_id==plumber_id",
          f"got={[it.get('category_id') for it in items]}")

    # ------------------------------------------------------------
    # 12. GET /services?language=te
    # ------------------------------------------------------------
    print("\n[12] GET /services?language=te — must include only Telugu speakers")
    r = requests.get(f"{API}/services", headers=H(user_token),
                     params={"language": "te"}, timeout=20)
    check(r.status_code == 200, "filter language=te 200")
    items = r.json().get("items", [])
    check(any(it.get("id") == user_id for it in items),
          "provider returned for language=te")
    check(all("te" in (it.get("service_languages") or []) for it in items),
          "all returned rows include 'te' in service_languages")

    # Sanity: language=hi should NOT include this provider (only en+te)
    r = requests.get(f"{API}/services", headers=H(user_token),
                     params={"language": "hi"}, timeout=20)
    items_hi = r.json().get("items", [])
    check(not any(it.get("id") == user_id for it in items_hi),
          "provider NOT returned for language=hi (only en+te selected)")

    # ------------------------------------------------------------
    # Bonus: provider_count on Plumber category should be > 0 now
    # ------------------------------------------------------------
    print("\n[bonus] provider_count on Plumber should be ≥ 1 after approval")
    r = requests.get(f"{API}/admin/service-categories", headers=H(admin_token), timeout=20)
    cats_after = r.json().get("categories", [])
    pl = next((c for c in cats_after if c["id"] == plumber_id), None)
    check(pl and pl.get("provider_count", 0) >= 1,
          f"Plumber.provider_count >= 1 (got {pl and pl.get('provider_count')})")

    # ------------------------------------------------------------
    # Edge: DELETE category that has providers → soft-deactivate
    # ------------------------------------------------------------
    print("\n[edge] DELETE category with linked provider → soft-deactivate")
    r = requests.delete(f"{API}/admin/service-categories/{plumber_id}",
                        headers=H(admin_token), timeout=20)
    if r.status_code == 200 and r.json().get("deactivated"):
        check(True, "soft-deactivated when in use")
        # Restore active
        requests.patch(f"{API}/admin/service-categories/{plumber_id}",
                       headers=H(admin_token), json={"active": True}, timeout=20)
    else:
        # If somehow deleted (shouldn't happen since we created a provider), restore
        check(False, "expected soft-deactivate", f"got {r.status_code} {r.text[:200]}")

    # ------------------------------------------------------------
    # CLEANUP — remove the throwaway user
    # ------------------------------------------------------------
    print("\n[cleanup] DELETE throwaway user")
    r = requests.delete(f"{API}/admin/users/{user_id}", headers=H(admin_token), timeout=20)
    print(f"  cleanup user: {r.status_code}")

    # Summary
    print("\n" + "=" * 80)
    print(f"PASS: {PASS}    FAIL: {FAIL}")
    if FAILURES:
        print("\nFailures:")
        for f in FAILURES:
            print(f"  - {f}")
    print("=" * 80)
    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    raise SystemExit(0 if ok else 1)
