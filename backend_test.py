"""Phase-2 backend refactor regression test (2026-05-28).

Tests routes/service_admin.py and routes/service_provider.py endpoints.
"""
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN = {"email": "admin@app.com", "password": "Admin@123"}
USER = {"email": "testuser@app.com", "password": "Test@123"}


def login(creds):
    r = requests.post(f"{BASE}/auth/login", json=creds, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


results = []


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" -- {detail}"
    print(line)
    results.append((name, ok, detail))
    return ok


def main():
    print("==== Logging in ====")
    admin_tok = login(ADMIN)
    print(f"Admin token len={len(admin_tok)}")
    try:
        user_tok = login(USER)
        print(f"User token len={len(user_tok)}")
    except Exception as e:
        print(f"User login failed: {e}")
        user_tok = None

    # 1. GET admin/service-categories
    r = requests.get(f"{BASE}/admin/service-categories", headers=H(admin_tok), timeout=30)
    ok = r.status_code == 200 and "categories" in r.json()
    cats = r.json().get("categories", []) if ok else []
    has_provider_count = all("provider_count" in c for c in cats) if cats else False
    check("1. GET /admin/service-categories", ok and has_provider_count,
          f"status={r.status_code}, n_cats={len(cats)}, all have provider_count={has_provider_count}")

    # 2. POST create category
    body = {"name": "RefactorTest", "icon": "box", "color": "#999999"}
    r = requests.post(f"{BASE}/admin/service-categories", json=body, headers=H(admin_tok), timeout=30)
    new_id = None
    if r.status_code == 200 and r.json().get("ok") and "category" in r.json():
        new_id = r.json()["category"].get("id")
    elif r.status_code == 400 and "already exists" in r.text:
        r2 = requests.get(f"{BASE}/admin/service-categories", headers=H(admin_tok), timeout=30)
        for c in r2.json().get("categories", []):
            if c.get("name") == "RefactorTest":
                new_id = c.get("id")
                break
    check("2. POST /admin/service-categories", new_id is not None,
          f"status={r.status_code}, new_id={new_id}, body={r.text[:200]}")

    # 3. PATCH update
    if new_id:
        r = requests.patch(f"{BASE}/admin/service-categories/{new_id}",
                           json={"color": "#000000"}, headers=H(admin_tok), timeout=30)
        ok = r.status_code == 200 and r.json().get("ok") is True
        new_color = (r.json().get("category") or {}).get("color")
        check("3. PATCH /admin/service-categories/{id}", ok and new_color == "#000000",
              f"status={r.status_code}, color={new_color}")
    else:
        check("3. PATCH /admin/service-categories/{id}", False, "no id from step 2")

    # 4. DELETE cleanup
    if new_id:
        r = requests.delete(f"{BASE}/admin/service-categories/{new_id}",
                            headers=H(admin_tok), timeout=30)
        ok = r.status_code == 200 and r.json().get("ok") is True
        check("4. DELETE /admin/service-categories/{id}", ok,
              f"status={r.status_code}, body={r.text[:200]}")
    else:
        check("4. DELETE /admin/service-categories/{id}", False, "no id from step 2")

    # 5. GET service-analytics
    r = requests.get(f"{BASE}/admin/service-analytics", headers=H(admin_tok), timeout=30)
    if r.status_code == 200:
        j = r.json()
        keys_ok = all(k in j for k in ["availability", "categories", "reveal_stats", "applications"])
        check("5. GET /admin/service-analytics", keys_ok,
              f"status=200, keys={list(j.keys())[:6]}")
    else:
        check("5. GET /admin/service-analytics", False,
              f"status={r.status_code}, body={r.text[:200]}")

    # 6. GET service-analytics with pincode filter
    r = requests.get(f"{BASE}/admin/service-analytics?pincode=110001",
                     headers=H(admin_tok), timeout=30)
    check("6. GET /admin/service-analytics?pincode=110001",
          r.status_code == 200,
          f"status={r.status_code}, keys={list(r.json().keys()) if r.status_code==200 else r.text[:200]}")

    # 7. PATCH /services/me/availability — testuser is not provider → 403
    if user_tok:
        r = requests.patch(f"{BASE}/services/me/availability",
                           json={"status": "available"}, headers=H(user_tok), timeout=30)
        msg = ""
        try:
            msg = r.json().get("detail", "")
        except Exception:
            msg = r.text
        check("7. PATCH /services/me/availability (non-provider → 403)",
              r.status_code == 403 and "Only service providers can set availability" in msg,
              f"status={r.status_code}, detail={msg}")
    else:
        check("7. PATCH /services/me/availability", False, "user_tok unavailable")

    # 8. POST /users/me/location valid
    if user_tok:
        r = requests.post(f"{BASE}/users/me/location",
                          json={"latitude": 28.6, "longitude": 77.2, "pincode": "110001"},
                          headers=H(user_tok), timeout=30)
        if r.status_code == 200:
            j = r.json()
            ok = j.get("ok") is True and "location" in j
            check("8. POST /users/me/location (valid)", ok,
                  f"status=200, loc={j.get('location')}")
        else:
            check("8. POST /users/me/location (valid)", False,
                  f"status={r.status_code}, body={r.text[:200]}")
    else:
        check("8. POST /users/me/location", False, "user_tok unavailable")

    # 9. POST /users/me/location invalid (latitude out of range) → 400
    if user_tok:
        r = requests.post(f"{BASE}/users/me/location",
                          json={"latitude": 999, "longitude": 77.2},
                          headers=H(user_tok), timeout=30)
        check("9. POST /users/me/location (lat=999 → 400)",
              r.status_code == 400,
              f"status={r.status_code}, body={r.text[:200]}")
    else:
        check("9. POST /users/me/location invalid", False, "user_tok unavailable")

    # 10. GET /services/reveals/me
    if user_tok:
        r = requests.get(f"{BASE}/services/reveals/me", headers=H(user_tok), timeout=30)
        if r.status_code == 200:
            j = r.json()
            ok = "items" in j and "total" in j
            check("10. GET /services/reveals/me", ok,
                  f"status=200, total={j.get('total')}, items_n={len(j.get('items', []))}")
        else:
            check("10. GET /services/reveals/me", False,
                  f"status={r.status_code}, body={r.text[:200]}")
    else:
        check("10. GET /services/reveals/me", False, "user_tok unavailable")

    print("\n==== SUMMARY ====")
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} PASS")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED: {name} -- {detail}")


if __name__ == "__main__":
    main()
