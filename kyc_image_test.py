"""
Focused tests for the new KYC image upload endpoints in NetworkPay.

Endpoints covered:
- POST /api/users/me/kyc with optional aadhaar_front/aadhaar_back/pan_image/selfie
- GET  /api/users/me/kyc (full data URLs + has_* booleans)
- GET  /api/admin/kyc (lightweight list, has_* flags, NO heavy image fields)
- GET  /api/admin/kyc/{user_id} (NEW - returns image data URLs)
- POST /api/admin/kyc/{user_id}/approve (existing) + audit log entry
"""
import os
import uuid
import sys
import requests

BACKEND_URL = "https://slangcart-tracking.preview.emergentagent.com"
API = f"{BACKEND_URL}/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# A minimal valid 1x1 PNG, base64 encoded
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg"
    "YGD4DwABBAEAfbLI3wAAAABJRU5ErkJggg=="
)
TINY_PNG_DATAURL = f"data:image/png;base64,{TINY_PNG_B64}"

results = []

def log(name, ok, info=""):
    results.append((name, ok, info))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {info}")


def H(token):
    return {"Authorization": f"Bearer {token}"}


def unique_email(prefix="userA"):
    return f"{prefix}_{uuid.uuid4().hex[:10]}@networkpay-test.com"


def main():
    # 0a. Login admin
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    admin_token = r.json()["token"]
    log("Admin login", True, f"status={r.status_code}")

    # 0b. Register a fresh user A
    email = unique_email("aadhaar_kyc")
    name = "Riya Sharma"
    r = requests.post(f"{API}/auth/register",
                      json={"name": name, "email": email, "password": "Pass@12345",
                            "phone": "9123456780", "referral_code": "ADMIN001"})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    a = r.json()
    a_token = a["token"]
    a_id = a["user"]["id"]
    log("Register user A", True, f"id={a_id} email={email}")

    # 0c. Pay registration fee for A
    r = requests.post(f"{API}/payment/register-fee", headers=H(a_token))
    log("A pays registration fee", r.status_code == 200, f"status={r.status_code}")

    # ----------------------------------------------------------------
    # 1) POST /users/me/kyc with valid text + 3 images (front/pan/selfie)
    # ----------------------------------------------------------------
    body = {
        "full_name": "Riya Sharma",
        "aadhaar": "123456789012",
        "pan": "ABCDE1234F",
        "aadhaar_front": TINY_PNG_DATAURL,
        "pan_image": TINY_PNG_DATAURL,
        "selfie": TINY_PNG_DATAURL,
    }
    r = requests.post(f"{API}/users/me/kyc", headers=H(a_token), json=body)
    ok = r.status_code == 200 and r.json().get("status") == "pending"
    log("1) POST /users/me/kyc with 3 images -> 200 pending", ok,
        f"status={r.status_code} body={r.text[:200]}")

    # ----------------------------------------------------------------
    # 2) GET /users/me/kyc → status pending, has_* flags, image URLs present
    # ----------------------------------------------------------------
    r = requests.get(f"{API}/users/me/kyc", headers=H(a_token))
    j = r.json() if r.status_code == 200 else {}
    cond = (
        r.status_code == 200
        and j.get("status") == "pending"
        and j.get("has_aadhaar_front") is True
        and j.get("has_pan_image") is True
        and j.get("has_selfie") is True
        and j.get("has_aadhaar_back") is False
        and isinstance(j.get("aadhaar_front"), str)
        and j.get("aadhaar_front", "").startswith("data:image/")
        and isinstance(j.get("pan_image"), str)
        and j.get("pan_image", "").startswith("data:image/")
        and isinstance(j.get("selfie"), str)
        and j.get("selfie", "").startswith("data:image/")
        and (j.get("aadhaar_back") is None)
    )
    log("2) GET /users/me/kyc - flags + data URLs", cond,
        f"status={r.status_code} has_af={j.get('has_aadhaar_front')} "
        f"has_ab={j.get('has_aadhaar_back')} has_pi={j.get('has_pan_image')} "
        f"has_sf={j.get('has_selfie')} ab_is_none={j.get('aadhaar_back') is None}")

    # ----------------------------------------------------------------
    # 3) Admin GET /admin/kyc?status=pending → A in list, has_* correct, NO heavy fields
    # ----------------------------------------------------------------
    r = requests.get(f"{API}/admin/kyc?status=pending", headers=H(admin_token))
    arr = r.json() if r.status_code == 200 else []
    a_record = next((x for x in arr if x.get("id") == a_id), None)
    heavy_keys = {"aadhaar_front", "aadhaar_back", "pan_image", "selfie",
                  "kyc_aadhaar_front", "kyc_aadhaar_back", "kyc_pan_image", "kyc_selfie"}
    if a_record is None:
        log("3) Admin GET /admin/kyc?status=pending - A present", False,
            f"A not in list of {len(arr)}")
    else:
        present_heavy = heavy_keys & set(a_record.keys())
        cond = (
            a_record.get("has_aadhaar_front") is True
            and a_record.get("has_pan_image") is True
            and a_record.get("has_selfie") is True
            and a_record.get("has_aadhaar_back") is False
            and not present_heavy
        )
        log("3) Admin GET /admin/kyc - flags + no heavy fields", cond,
            f"present_heavy={present_heavy} has_af={a_record.get('has_aadhaar_front')} "
            f"has_ab={a_record.get('has_aadhaar_back')} has_pi={a_record.get('has_pan_image')} "
            f"has_sf={a_record.get('has_selfie')}")

    # ----------------------------------------------------------------
    # 4) Admin GET /admin/kyc/{A.id} → returns 3 images, aadhaar_back null
    # ----------------------------------------------------------------
    r = requests.get(f"{API}/admin/kyc/{a_id}", headers=H(admin_token))
    j = r.json() if r.status_code == 200 else {}
    cond = (
        r.status_code == 200
        and isinstance(j.get("aadhaar_front"), str) and j["aadhaar_front"].startswith("data:image/")
        and isinstance(j.get("pan_image"), str) and j["pan_image"].startswith("data:image/")
        and isinstance(j.get("selfie"), str) and j["selfie"].startswith("data:image/")
        and j.get("aadhaar_back") is None
        and j.get("kyc_status") == "pending"
        and j.get("kyc_full_name") == "Riya Sharma"
        and j.get("kyc_aadhaar") == "123456789012"
        and j.get("kyc_pan") == "ABCDE1234F"
    )
    log("4) Admin GET /admin/kyc/{A.id} - 3 images present, back null", cond,
        f"status={r.status_code} ab_none={j.get('aadhaar_back') is None}")

    # ----------------------------------------------------------------
    # 5) Resubmit with ONLY aadhaar_back filled — others must be preserved
    # ----------------------------------------------------------------
    body = {
        "full_name": "Riya Sharma",
        "aadhaar": "123456789012",
        "pan": "ABCDE1234F",
        "aadhaar_back": TINY_PNG_DATAURL,
    }
    r = requests.post(f"{API}/users/me/kyc", headers=H(a_token), json=body)
    ok_resub = r.status_code == 200
    log("5a) Resubmit only aadhaar_back -> 200", ok_resub, f"status={r.status_code} body={r.text[:200]}")

    r = requests.get(f"{API}/admin/kyc/{a_id}", headers=H(admin_token))
    j = r.json() if r.status_code == 200 else {}
    all_four = (
        isinstance(j.get("aadhaar_front"), str) and j["aadhaar_front"].startswith("data:image/")
        and isinstance(j.get("aadhaar_back"), str) and j["aadhaar_back"].startswith("data:image/")
        and isinstance(j.get("pan_image"), str) and j["pan_image"].startswith("data:image/")
        and isinstance(j.get("selfie"), str) and j["selfie"].startswith("data:image/")
    )
    log("5b) Admin detail after resubmit - ALL 4 images present (preservation)", all_four,
        f"af={bool(j.get('aadhaar_front'))} ab={bool(j.get('aadhaar_back'))} "
        f"pi={bool(j.get('pan_image'))} sf={bool(j.get('selfie'))}")

    # ----------------------------------------------------------------
    # 6) aadhaar_front="notadataurl" → 400 with detail mentioning aadhaar_front
    # ----------------------------------------------------------------
    body = {
        "full_name": "Riya Sharma",
        "aadhaar": "123456789012",
        "pan": "ABCDE1234F",
        "aadhaar_front": "notadataurl",
    }
    r = requests.post(f"{API}/users/me/kyc", headers=H(a_token), json=body)
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 400 and "aadhaar_front" in str(detail)
    log("6) Bad data URL -> 400 with field name", ok,
        f"status={r.status_code} detail={detail}")

    # ----------------------------------------------------------------
    # 7) oversize image -> 400 "image too large" mentioning aadhaar_front
    # ----------------------------------------------------------------
    big = "data:image/png;base64," + ("A" * 2_500_000)
    body = {
        "full_name": "Riya Sharma",
        "aadhaar": "123456789012",
        "pan": "ABCDE1234F",
        "aadhaar_front": big,
    }
    r = requests.post(f"{API}/users/me/kyc", headers=H(a_token), json=body)
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    ok = r.status_code == 400 and "aadhaar_front" in str(detail) and "image too large" in str(detail).lower()
    log("7) Oversize image -> 400 'image too large'", ok,
        f"status={r.status_code} detail={detail[:200]}")

    # ----------------------------------------------------------------
    # 8) Admin approves A -> 200; A's GET /users/me/kyc shows approved
    # ----------------------------------------------------------------
    r = requests.post(f"{API}/admin/kyc/{a_id}/approve", headers=H(admin_token))
    log("8a) Admin approves A's KYC -> 200", r.status_code == 200, f"status={r.status_code}")

    r = requests.get(f"{API}/users/me/kyc", headers=H(a_token))
    j = r.json() if r.status_code == 200 else {}
    log("8b) A GET /users/me/kyc shows status=approved", j.get("status") == "approved",
        f"status={j.get('status')}")

    # ----------------------------------------------------------------
    # 9) Audit logs include kyc.approve for A.id
    # ----------------------------------------------------------------
    r = requests.get(f"{API}/admin/audit-logs?limit=200", headers=H(admin_token))
    logs = r.json() if r.status_code == 200 else []
    found = any(l.get("action") == "kyc.approve" and l.get("target_id") == a_id for l in logs)
    log("9) Audit log has kyc.approve for A.id", found,
        f"http={r.status_code} match_found={found} total_logs={len(logs)}")

    # ----------------------------------------------------------------
    # 10) Backwards compatibility: TEXT-ONLY KYC submission still works (new user B)
    # ----------------------------------------------------------------
    email_b = unique_email("textonly_kyc")
    r = requests.post(f"{API}/auth/register",
                      json={"name": "Vikram Singh", "email": email_b, "password": "Pass@12345"})
    assert r.status_code == 200, f"register B failed: {r.status_code} {r.text}"
    b_token = r.json()["token"]
    b_id = r.json()["user"]["id"]
    requests.post(f"{API}/payment/register-fee", headers=H(b_token))
    body = {"full_name": "Vikram Singh", "aadhaar": "987654321098", "pan": "ZYXWV9876K"}
    r = requests.post(f"{API}/users/me/kyc", headers=H(b_token), json=body)
    log("10a) Text-only KYC submit still works -> 200 pending",
        r.status_code == 200 and r.json().get("status") == "pending",
        f"status={r.status_code} body={r.text[:200]}")
    r = requests.get(f"{API}/users/me/kyc", headers=H(b_token))
    j = r.json() if r.status_code == 200 else {}
    cond = (
        j.get("status") == "pending"
        and j.get("has_aadhaar_front") is False and j.get("has_aadhaar_back") is False
        and j.get("has_pan_image") is False and j.get("has_selfie") is False
        and j.get("aadhaar_front") is None and j.get("aadhaar_back") is None
        and j.get("pan_image") is None and j.get("selfie") is None
    )
    log("10b) Text-only KYC GET shows no images", cond, f"flags={ {k:j.get(k) for k in ('has_aadhaar_front','has_aadhaar_back','has_pan_image','has_selfie')} }")

    # Bad aadhaar still 400
    body = {"full_name": "Vikram Singh", "aadhaar": "12345", "pan": "ZYXWV9876K"}
    r = requests.post(f"{API}/users/me/kyc", headers=H(b_token), json=body)
    log("10c) Bad aadhaar still returns 400", r.status_code == 400, f"status={r.status_code}")

    # ----------------------------------------------------------------
    # 11) aadhaar_back="data:text/plain;base64,..." -> 400 (must be image/*)
    # ----------------------------------------------------------------
    body = {
        "full_name": "Vikram Singh",
        "aadhaar": "987654321098",
        "pan": "ZYXWV9876K",
        "aadhaar_back": "data:text/plain;base64,SGVsbG8=",
    }
    r = requests.post(f"{API}/users/me/kyc", headers=H(b_token), json=body)
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    ok = r.status_code == 400 and "aadhaar_back" in str(detail)
    log("11) Non-image data URL -> 400 with aadhaar_back name", ok,
        f"status={r.status_code} detail={detail}")

    # ===== Summary =====
    print("\n========== SUMMARY ==========")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [n for n, ok, _ in results if not ok]
    print(f"Passed: {passed}/{len(results)}")
    if failed:
        print("Failed:")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL KYC IMAGE TESTS PASSED")


if __name__ == "__main__":
    main()
