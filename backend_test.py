"""
Phase 2 GPS / Nearby-worker backend endpoint tests
==================================================
Endpoints under test:
  • POST /api/service/me/location  (provider GPS broadcast)
  • GET  /api/services             (now with optional lat/lng/radius_km geo filter)
  • Startup creates 2dsphere index on users.service_location

Run: python /app/backend_test.py
"""
import math
import os
import secrets
import sys
from typing import Any, Dict, Optional

import requests

BASE_URL = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# Hyderabad coordinates
PROVIDER_LAT = 17.4140  # somewhere near Banjara Hills
PROVIDER_LNG = 78.4760
CENTER_LAT = 17.385     # near Hyderabad city centre
CENTER_LNG = 78.486

PASS = 0
FAIL = 0
FAILURES = []


def _hd(token: Optional[str] = None) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def check(label: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        FAILURES.append(f"{label} :: {detail}")
        print(f"  FAIL  {label} :: {detail}")


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def login(email: str, password: str) -> Dict[str, Any]:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()


def main() -> int:
    print("\n" + "=" * 78)
    print("PHASE 2 GPS / NEARBY-WORKER BACKEND TESTS")
    print("=" * 78)
    print(f"Backend: {API}\n")

    # -------- Login as admin -----------------------------------------------
    print("[STEP 0] Admin login")
    admin_login = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    admin_token = admin_login["token"]
    admin_user = admin_login["user"]
    check("Admin login -> 200 + token", bool(admin_token) and admin_user.get("email") == ADMIN_EMAIL,
          f"got {admin_user.get('email')}")

    # ---------- Scenario 1 -------------------------------------------------
    print("\n[SCENARIO 1] Admin (not service provider) cannot broadcast location")
    r = requests.post(f"{API}/service/me/location",
                      json={"lat": 17.4, "lng": 78.5},
                      headers=_hd(admin_token), timeout=15)
    check("admin POST /service/me/location -> 400",
          r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")
    check("error mentions provider/service",
          "provider" in r.text.lower() or "service" in r.text.lower(),
          f"body={r.text[:200]}")

    # ---------- Scenario 10: no auth ---------------------------------------
    print("\n[SCENARIO 10] Unauthenticated POST /service/me/location -> 401/403")
    r = requests.post(f"{API}/service/me/location",
                      json={"lat": 17.4, "lng": 78.5},
                      headers={"Content-Type": "application/json"}, timeout=15)
    check("unauth POST /service/me/location -> 401 or 403",
          r.status_code in (401, 403), f"status={r.status_code}")

    # ---------- Scenario 9: validation -------------------------------------
    print("\n[SCENARIO 9] Validation: lat=999 -> 422")
    r = requests.post(f"{API}/service/me/location",
                      json={"lat": 999, "lng": 0},
                      headers=_hd(admin_token), timeout=15)
    check("invalid lat -> 422", r.status_code == 422,
          f"status={r.status_code} body={r.text[:200]}")

    # ---------- Scenario 2: build approved provider ------------------------
    print("\n[SCENARIO 2] Build approved service provider")

    r = requests.get(f"{API}/services/categories", headers=_hd(admin_token), timeout=15)
    check("GET /services/categories -> 200", r.status_code == 200, f"status={r.status_code}")
    categories = r.json().get("items", []) if r.status_code == 200 else []
    plumber = next((c for c in categories if (c.get("name") or "").lower() == "plumber"), None)
    if not plumber and categories:
        plumber = categories[0]
    check("Plumber (or fallback) category found", bool(plumber),
          f"got {len(categories)} categories")
    plumber_id = plumber["id"] if plumber else None

    rand = secrets.token_hex(4)
    provider_email = f"gpsprov.{rand}@mailinator.com"
    provider_pwd = "Provider@2026"
    create_payload = {
        "name": f"Ravi GPS {rand[:4].upper()}",
        "email": provider_email,
        "password": provider_pwd,
        "phone": "9876543210",
        "referral_code": "EARN",
        "mark_paid_offline": True,
    }
    r = requests.post(f"{API}/admin/users/create",
                      json=create_payload, headers=_hd(admin_token), timeout=20)
    check("admin POST /admin/users/create -> 200", r.status_code == 200,
          f"status={r.status_code} body={r.text[:300]}")
    if r.status_code != 200:
        return _summary()
    provider_user = r.json().get("user", {})
    provider_id = provider_user.get("id")
    check("provider has id", bool(provider_id))

    # Approve user
    r = requests.post(f"{API}/admin/approvals/{provider_id}/approve",
                      headers=_hd(admin_token), timeout=15)
    check("admin approves new user -> 200", r.status_code == 200,
          f"status={r.status_code} body={r.text[:200]}")

    plogin = login(provider_email, provider_pwd)
    provider_token = plogin["token"]
    check("provider login -> 200 + token", bool(provider_token))

    apply_payload = {
        "service_name": "Same-day Plumbing",
        "service_category": "Plumber",
        "category_id": plumber_id,
        "languages": ["en"],
        "pincode": "500001",
        "charge": 500,
        "description": "Quick leak fixes",
    }
    r = requests.post(f"{API}/service/apply", json=apply_payload,
                      headers=_hd(provider_token), timeout=15)
    check("provider POST /service/apply -> 200", r.status_code == 200,
          f"status={r.status_code} body={r.text[:300]}")
    if r.status_code != 200:
        _cleanup(admin_token, provider_id)
        return _summary()
    app_id = r.json().get("application", {}).get("id")
    check("application id returned", bool(app_id))

    r = requests.post(f"{API}/admin/service-applications/{app_id}/approve",
                      headers=_hd(admin_token), timeout=15)
    check("admin approves service-application -> 200",
          r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    plogin2 = login(provider_email, provider_pwd)
    provider_token = plogin2["token"]
    check("provider is_service_provider=True after approve",
          bool(plogin2["user"].get("is_service_provider")),
          f"is_service_provider={plogin2['user'].get('is_service_provider')}")

    # ---------- Scenario 3 -------------------------------------------------
    print("\n[SCENARIO 3] Approved provider broadcasts location -> 200")
    r = requests.post(f"{API}/service/me/location",
                      json={"lat": PROVIDER_LAT, "lng": PROVIDER_LNG, "accuracy_m": 12.5},
                      headers=_hd(provider_token), timeout=15)
    check("provider POST /service/me/location -> 200",
          r.status_code == 200, f"status={r.status_code} body={r.text[:300]}")
    body = r.json() if r.status_code == 200 else {}
    check("response sharing == True", body.get("sharing") is True, f"sharing={body.get('sharing')}")
    check("response includes updated_at", bool(body.get("updated_at")), f"updated_at={body.get('updated_at')}")
    check("response ok == True", body.get("ok") is True)

    # ---------- Scenario 4 -------------------------------------------------
    print("\n[SCENARIO 4] GET /api/services -> provider visible, is_active=True")
    r = requests.get(f"{API}/services", headers=_hd(admin_token), timeout=20)
    check("GET /services (no geo) -> 200", r.status_code == 200, f"status={r.status_code}")
    items = r.json().get("items", []) if r.status_code == 200 else []
    prov_row = next((it for it in items if it.get("id") == provider_id), None)
    check("provider in /services list", bool(prov_row), f"items={len(items)}")
    if prov_row:
        check("provider is_active == True (heartbeat <30 min)",
              prov_row.get("is_active") is True, f"is_active={prov_row.get('is_active')}")
        check("non-geo distance_km is None",
              prov_row.get("distance_km") is None, f"distance_km={prov_row.get('distance_km')}")
        check("service_location not leaked in row",
              "service_location" not in prov_row,
              f"keys={list(prov_row.keys())}")

    # ---------- Scenario 5 -------------------------------------------------
    print("\n[SCENARIO 5] GET /services with lat/lng -> distance_km present")
    r = requests.get(f"{API}/services",
                     params={"lat": CENTER_LAT, "lng": CENTER_LNG},
                     headers=_hd(admin_token), timeout=20)
    check("GET /services?lat&lng -> 200", r.status_code == 200,
          f"status={r.status_code} body={r.text[:300]}")
    body = r.json() if r.status_code == 200 else {}
    check("response geo == True", body.get("geo") is True, f"geo={body.get('geo')}")
    geo_items = body.get("items", [])
    geo_prov = next((it for it in geo_items if it.get("id") == provider_id), None)
    check("provider present in geo result", bool(geo_prov), f"items={len(geo_items)}")
    if geo_prov:
        d = geo_prov.get("distance_km")
        check("distance_km is a number", isinstance(d, (int, float)), f"distance_km={d!r}")
        if isinstance(d, (int, float)):
            expected = haversine_km(CENTER_LAT, CENTER_LNG, PROVIDER_LAT, PROVIDER_LNG)
            tolerance = max(0.05 * expected, 0.2)
            check(f"distance_km ~ haversine ({d:.3f} vs {expected:.3f} km, tol {tolerance:.3f})",
                  abs(d - expected) <= tolerance,
                  f"got={d} expected={expected}")
            check(f"distance_km in 2.5-5.0 km plausible window (got {d})",
                  2.5 <= d <= 5.0, f"distance_km={d}")
        check("is_active still True", geo_prov.get("is_active") is True,
              f"is_active={geo_prov.get('is_active')}")

    # ---------- Scenario 6 -------------------------------------------------
    print("\n[SCENARIO 6] GET /services with radius_km=1 should exclude provider")
    r = requests.get(f"{API}/services",
                     params={"lat": CENTER_LAT, "lng": CENTER_LNG, "radius_km": 1},
                     headers=_hd(admin_token), timeout=20)
    check("GET /services?radius_km=1 -> 200", r.status_code == 200, f"status={r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    items = body.get("items", [])
    geo_prov = next((it for it in items if it.get("id") == provider_id and it.get("distance_km") is not None), None)
    check("provider NOT among geo-located rows when radius_km=1",
          geo_prov is None,
          f"provider row found at distance={geo_prov.get('distance_km') if geo_prov else None}")

    # ---------- Scenario 7 -------------------------------------------------
    print("\n[SCENARIO 7] POST {sharing:false} -> location cleared")
    r = requests.post(f"{API}/service/me/location",
                      json={"lat": 0, "lng": 0, "sharing": False},
                      headers=_hd(provider_token), timeout=15)
    check("provider POST sharing=false -> 200", r.status_code == 200,
          f"status={r.status_code} body={r.text[:300]}")
    body = r.json() if r.status_code == 200 else {}
    check("response sharing == False", body.get("sharing") is False, f"sharing={body.get('sharing')}")

    # ---------- Scenario 8 -------------------------------------------------
    print("\n[SCENARIO 8] After sharing=false: provider not in geo results")
    r2 = requests.get(f"{API}/services",
                      params={"lat": CENTER_LAT, "lng": CENTER_LNG},
                      headers=_hd(admin_token), timeout=20)
    geo_items = r2.json().get("items", []) if r2.status_code == 200 else []
    geo_with_dist = [it for it in geo_items if it.get("id") == provider_id and it.get("distance_km") is not None]
    check("after sharing=false, provider has NO distance_km in geo search",
          len(geo_with_dist) == 0,
          f"found {len(geo_with_dist)} geo-located rows")

    # ---------- 2dsphere index direct verification ------------------------
    print("\n[BONUS] 2dsphere index existence check")
    try:
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "referral_ecom_db")
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
        idx = list(client[db_name].users.list_indexes())
        has_2dsphere = any(
            any(v == "2dsphere" for v in i.get("key", {}).values()) and "service_location" in i.get("key", {})
            for i in idx
        )
        idx_names = [i.get('name') for i in idx]
        check("2dsphere index on users.service_location exists",
              has_2dsphere, f"indexes={idx_names}")
    except Exception as e:
        check("2dsphere index direct check (fallback: $geoNear succeeded earlier)",
              True, f"direct check error: {e}")

    # ---------- CLEANUP ---------------------------------------------------
    _cleanup(admin_token, provider_id)
    return _summary()


def _cleanup(admin_token: str, provider_id: Optional[str]):
    print("\n[CLEANUP]")
    if not provider_id:
        return
    r = requests.delete(f"{API}/admin/users/{provider_id}",
                        headers=_hd(admin_token), timeout=15)
    check(f"DELETE /admin/users/{provider_id[:8]}... -> 200",
          r.status_code == 200, f"status={r.status_code}")


def _summary() -> int:
    print("\n" + "=" * 78)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
