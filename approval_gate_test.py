"""
NetworkPay — User Approval Gate flow + extra docs end-to-end test.

Covers scenarios A–T from review request and core regressions:
- super-password / wipe-users / dashboard analytics smoke
- KYC text-only submit
- admin-management contract spot-check
"""
import os
import sys
import time
import uuid
import json
import requests

BACKEND_URL = "https://slangcart-tracking.preview.emergentagent.com"
API = f"{BACKEND_URL}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# 1x1 transparent PNG (base64) — small valid image for image upload checks
TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
TINY_PNG_DATA_URL = f"data:image/png;base64,{TINY_PNG}"

results = []


def record(name: str, ok: bool, info: str = ""):
    results.append((name, ok, info))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}{(' — ' + info) if info else ''}")
    if not ok:
        # Continue but flag — will be summarized
        pass


def hdr(token: str):
    return {"Authorization": f"Bearer {token}"}


def post(path: str, token: str = None, json_body=None, expect=None, name: str = ""):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = requests.post(f"{API}{path}", json=json_body or {}, headers=h, timeout=60)
    if expect is not None:
        record(name or f"POST {path}", r.status_code == expect, f"got {r.status_code} body={r.text[:300]}")
    return r


def get(path: str, token: str = None, params=None, expect=None, name: str = ""):
    h = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = requests.get(f"{API}{path}", headers=h, params=params, timeout=60)
    if expect is not None:
        record(name or f"GET {path}", r.status_code == expect, f"got {r.status_code} body={r.text[:200]}")
    return r


def admin_login() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=60)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def register_user(name: str, email: str, password: str = "Pass@1234", referral_code: str = None) -> dict:
    body = {"name": name, "email": email, "password": password}
    if referral_code:
        body["referral_code"] = referral_code
    r = requests.post(f"{API}/auth/register", json=body, timeout=60)
    assert r.status_code == 200, f"register {email} failed: {r.status_code} {r.text}"
    return r.json()


def login(email: str, password: str = "Pass@1234") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def find_admin_user(token: str, user_id: str) -> dict:
    r = get("/admin/users", token=token)
    assert r.status_code == 200
    for u in r.json():
        if u.get("id") == user_id:
            return u
    return {}


def main():
    # === A. Admin login ===
    T_admin = admin_login()
    record("A. Admin login", True)

    # Use unique emails per run
    suffix = uuid.uuid4().hex[:8]
    s_email = f"sponsor_{suffix}@example.com"
    c_email = f"child_{suffix}@example.com"
    c2_email = f"child2_{suffix}@example.com"

    # === B. Register sponsor S, pay registration, admin approves S, confirm direct=0 ===
    s_reg = register_user("Aarav Sharma", s_email)
    s_id = s_reg["user"]["id"]
    s_referral = s_reg["user"]["referral_code"]
    T_s = s_reg["token"]
    record("B1. Sponsor registered", "user" in s_reg and s_reg["user"]["approval_status"] == "pending",
           f"approval_status={s_reg['user'].get('approval_status')}")

    # Sponsor pays registration fee (no upline so commissions don't matter, but tests register-fee)
    r = post("/payment/register-fee", token=T_s)
    record("B2. Sponsor pays /payment/register-fee → 200",
           r.status_code == 200 and r.json().get("approval_status") == "pending",
           f"status={r.status_code} body={r.text[:200]}")

    # Admin approves sponsor
    r = post(f"/admin/approvals/{s_id}/approve", token=T_admin)
    record("B3. Admin approves sponsor → 200", r.status_code == 200, r.text[:200])

    s_doc = find_admin_user(T_admin, s_id)
    record("B4. Sponsor approval_status=approved & direct_referrals_count=0 (self-approve no commission)",
           s_doc.get("approval_status") == "approved" and s_doc.get("direct_referrals_count", 0) == 0,
           f"approval={s_doc.get('approval_status')} direct={s_doc.get('direct_referrals_count')}")

    # === C. Register child C using S.referral_code ===
    c_reg = register_user("Diya Patel", c_email, referral_code=s_referral)
    c_id = c_reg["user"]["id"]
    T_c = c_reg["token"]
    record("C1. Child registered with sponsor referral",
           c_reg["user"].get("sponsor_id") == s_id,
           f"sponsor_id={c_reg['user'].get('sponsor_id')}")

    r = get(f"/admin/approvals/{c_id}", token=T_admin)
    record("C2. Admin GET /admin/approvals/{C} returns C with approval_status=pending & commission_triggered=False",
           r.status_code == 200 and r.json().get("approval_status") == "pending" and r.json().get("commission_triggered") is False,
           f"status={r.status_code} approval={r.json().get('approval_status') if r.status_code==200 else r.text[:120]} commission_triggered={r.json().get('commission_triggered') if r.status_code==200 else 'n/a'}")

    # === D. C pays /payment/register-fee → 200 with approval_status:pending. S direct still 0 ===
    r = post("/payment/register-fee", token=T_c)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    record("D1. C /payment/register-fee → 200 with approval_status=pending",
           r.status_code == 200 and body.get("approval_status") == "pending",
           f"status={r.status_code} body={r.text[:200]}")

    s_doc = find_admin_user(T_admin, s_id)
    record("D2. After child pays — sponsor direct_referrals_count still 0 (commission gated)",
           s_doc.get("direct_referrals_count", 0) == 0,
           f"direct={s_doc.get('direct_referrals_count')}")

    # === E. Admin /admin/approvals?status=pending — C present, extra_docs absent, sponsor_email=S.email ===
    r = get("/admin/approvals", token=T_admin, params={"status": "pending"})
    if r.status_code != 200:
        record("E. /admin/approvals?status=pending → 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        items = r.json()
        c_in_list = next((i for i in items if i.get("id") == c_id), None)
        ok = (c_in_list is not None
              and "extra_docs" not in c_in_list
              and c_in_list.get("sponsor_email") == s_email)
        record("E. /admin/approvals?status=pending — C present, no extra_docs, sponsor_email correct",
               ok,
               f"present={c_in_list is not None} extra_docs_in={('extra_docs' in (c_in_list or {}))} sponsor_email={(c_in_list or {}).get('sponsor_email')}")

    # === F. /admin/approvals/today contains C ===
    r = get("/admin/approvals/today", token=T_admin)
    if r.status_code != 200:
        record("F. /admin/approvals/today → 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        ids_today = [i.get("id") for i in r.json()]
        record("F. /admin/approvals/today contains C", c_id in ids_today,
               f"count={len(ids_today)} c_in={c_id in ids_today}")

    # === G. C tries POST /withdrawals amount=100 → 403 with detail mentioning 'awaiting admin approval' ===
    # Need bank/upi for withdrawal — but approval check happens before those checks.
    r = post("/withdrawals", token=T_c, json_body={"amount": 100})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    record("G. C /withdrawals → 403 with 'awaiting admin approval'",
           r.status_code == 403 and "awaiting admin approval" in detail,
           f"status={r.status_code} detail={detail}")

    # === H. Admin approves C ===
    r = post(f"/admin/approvals/{c_id}/approve", token=T_admin)
    record("H1. Admin approve C → 200", r.status_code == 200, r.text[:200])

    c_doc = find_admin_user(T_admin, c_id)
    record("H2. C.approval_status=approved & commission_triggered=true",
           c_doc.get("approval_status") == "approved" and c_doc.get("commission_triggered") is True,
           f"approval={c_doc.get('approval_status')} ct={c_doc.get('commission_triggered')}")

    s_doc = find_admin_user(T_admin, s_id)
    record("H3. After approving C — S.direct_referrals_count == 1",
           s_doc.get("direct_referrals_count", 0) == 1,
           f"direct={s_doc.get('direct_referrals_count')}")

    # === I. Idempotent approve ===
    r = post(f"/admin/approvals/{c_id}/approve", token=T_admin)
    body = r.json() if r.status_code == 200 else {}
    record("I1. Re-approve C → 200 already_approved:true",
           r.status_code == 200 and body.get("already_approved") is True,
           f"status={r.status_code} body={r.text[:200]}")
    s_doc = find_admin_user(T_admin, s_id)
    record("I2. S.direct_referrals_count still 1 (idempotent)",
           s_doc.get("direct_referrals_count", 0) == 1,
           f"direct={s_doc.get('direct_referrals_count')}")

    # === J. Reject path: register C2 under S, pay fee, admin reject {category:'cibil_score'} ===
    c2_reg = register_user("Rohan Mehta", c2_email, referral_code=s_referral)
    c2_id = c2_reg["user"]["id"]
    T_c2 = c2_reg["token"]
    r = post("/payment/register-fee", token=T_c2)
    record("J1. C2 paid registration fee", r.status_code == 200, r.text[:200])

    r = post(f"/admin/approvals/{c2_id}/reject", token=T_admin, json_body={"category": "cibil_score"})
    record("J2. Reject C2 with cibil_score → 200", r.status_code == 200, r.text[:200])

    c2_doc = find_admin_user(T_admin, c2_id)
    rj_reason = (c2_doc.get("approval_reject_reason") or "").lower()
    record("J3. C2.approval_status=rejected and reason mentions CIBIL",
           c2_doc.get("approval_status") == "rejected" and "cibil" in rj_reason,
           f"approval={c2_doc.get('approval_status')} reason={c2_doc.get('approval_reject_reason')}")

    # === K. Reject with category=custom but no reason → 400 'Custom reason text is required' ===
    # Need a fresh user not yet rejected — create one; use S sponsor.
    custom_email = f"customreject_{suffix}@example.com"
    custom_reg = register_user("Asha Iyer", custom_email, referral_code=s_referral)
    custom_id = custom_reg["user"]["id"]
    r = post(f"/admin/approvals/{custom_id}/reject", token=T_admin, json_body={"category": "custom"})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    record("K. Reject custom without reason → 400 'Custom reason text is required'",
           r.status_code == 400 and "Custom reason text is required" in detail,
           f"status={r.status_code} detail={detail}")

    # === L. Reject with category=invalid → 400 'Invalid rejection category' ===
    r = post(f"/admin/approvals/{custom_id}/reject", token=T_admin, json_body={"category": "invalid"})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    record("L. Reject invalid category → 400 'Invalid rejection category'",
           r.status_code == 400 and "Invalid rejection category" in detail,
           f"status={r.status_code} detail={detail}")

    # === M. C2 GET /users/me/additional-docs → status:rejected, reject_category:cibil_score, reason mentions CIBIL ===
    r = get("/users/me/additional-docs", token=T_c2)
    if r.status_code != 200:
        record("M. C2 GET /users/me/additional-docs → 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        body = r.json()
        ok = (body.get("approval_status") == "rejected"
              and body.get("reject_category") == "cibil_score"
              and "cibil" in (body.get("reject_reason") or "").lower())
        record("M. /users/me/additional-docs returns rejected+cibil_score+CIBIL reason",
               ok, f"body={body}")

    # === N. C2 POST /users/me/additional-docs empty → 400 'At least one document must be provided' ===
    r = post("/users/me/additional-docs", token=T_c2, json_body={})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    record("N. POST /users/me/additional-docs empty → 400 'At least one document must be provided'",
           r.status_code == 400 and "At least one document must be provided" in detail,
           f"status={r.status_code} detail={detail}")

    # === O. C2 POST /users/me/additional-docs with cibil_report=tiny PNG → 200; status moves back to pending ===
    r = post("/users/me/additional-docs", token=T_c2, json_body={"cibil_report": TINY_PNG_DATA_URL})
    record("O1. C2 upload cibil_report (small valid PNG) → 200",
           r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    c2_doc = find_admin_user(T_admin, c2_id)
    record("O2. After upload — C2.approval_status reverts to 'pending'",
           c2_doc.get("approval_status") == "pending",
           f"approval={c2_doc.get('approval_status')}")

    # === P. C2 POST with cibil_report='notadataurl' → 400 mentioning cibil_report ===
    r = post("/users/me/additional-docs", token=T_c2, json_body={"cibil_report": "notadataurl"})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    record("P. cibil_report='notadataurl' → 400 mentioning 'cibil_report'",
           r.status_code == 400 and "cibil_report" in detail,
           f"status={r.status_code} detail={detail}")

    # === Q. Admin GET /admin/approvals/{C2}/additional-docs returns extra_docs.cibil_report data URL ===
    r = get(f"/admin/approvals/{c2_id}/additional-docs", token=T_admin)
    if r.status_code != 200:
        record("Q. Admin GET extras → 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        body = r.json()
        cibil = (body.get("extra_docs") or {}).get("cibil_report") or ""
        record("Q. extra_docs.cibil_report present as data:image/* URL",
               cibil.startswith("data:image/"),
               f"cibil_prefix={cibil[:30]}")

    # === R. Admin GET /admin/approvals/{C2} → full detail; extra_docs.cibil_report present ===
    r = get(f"/admin/approvals/{c2_id}", token=T_admin)
    if r.status_code != 200:
        record("R. Admin GET /admin/approvals/{C2} → 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        body = r.json()
        cibil = ((body.get("extra_docs") or {}).get("cibil_report") or "")
        record("R. Detail contains extra_docs.cibil_report data URL",
               cibil.startswith("data:image/") and "sponsor" in body,
               f"cibil_prefix={cibil[:30]} sponsor_in={'sponsor' in body}")

    # === S. Admin approves C2 → S.direct_referrals_count == 2; no double-trigger for C ===
    r = post(f"/admin/approvals/{c2_id}/approve", token=T_admin)
    record("S1. Admin approves C2 → 200", r.status_code == 200, r.text[:200])
    s_doc = find_admin_user(T_admin, s_id)
    record("S2. After approving C2 — S.direct_referrals_count == 2",
           s_doc.get("direct_referrals_count", 0) == 2,
           f"direct={s_doc.get('direct_referrals_count')}")
    # Re-approve C — confirm direct still 2 (no double-count for C)
    r = post(f"/admin/approvals/{c_id}/approve", token=T_admin)
    s_doc = find_admin_user(T_admin, s_id)
    record("S3. Re-approve C — direct stays 2 (commission_triggered prevents double)",
           s_doc.get("direct_referrals_count", 0) == 2,
           f"direct={s_doc.get('direct_referrals_count')}")

    # === T. C2 makes /withdrawals — should NOT be 403 anymore (approval gate passed). Without bank/upi or balance, expect 400 ===
    r = post("/withdrawals", token=T_c2, json_body={"amount": 100000})
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    # We expect either Insufficient balance or Add UPI/bank — but NOT 403 awaiting admin approval.
    ok = r.status_code == 400 and "awaiting admin approval" not in detail
    record("T. After approval, /withdrawals not blocked by approval gate (got 400 not 403)",
           ok,
           f"status={r.status_code} detail={detail}")

    # === REGRESSION 1: Super-password status & wipe-users gate (no destructive call here) ===
    r = get("/admin/super-password", token=T_admin)
    record("REG1a. GET /admin/super-password (super_admin) → 200",
           r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    # Wipe-users without confirm → 400
    r = post("/admin/system/wipe-users", token=T_admin, json_body={"confirm": "WRONG", "super_password": "x", "keep_admins": True})
    record("REG1b. /admin/system/wipe-users with bad confirm → 400",
           r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")

    # === REGRESSION 2: dashboard analytics, admin stats, audit logs ===
    r = get("/admin/analytics", token=T_admin, params={"days": 7})
    record("REG2a. GET /admin/analytics?days=7 → 200", r.status_code == 200,
           f"status={r.status_code}")
    r = get("/admin/stats", token=T_admin)
    record("REG2b. GET /admin/stats → 200", r.status_code == 200,
           f"status={r.status_code}")
    r = get("/admin/audit-logs", token=T_admin, params={"limit": 10})
    if r.status_code == 200:
        actions = [e.get("action") for e in r.json()]
        record("REG2c. /admin/audit-logs has user.approve and user.reject entries",
               any("user.approve" == a for a in actions) and any("user.reject" == a for a in actions),
               f"actions_sample={actions[:8]}")
    else:
        record("REG2c. /admin/audit-logs → 200", False, f"status={r.status_code} body={r.text[:200]}")

    # === REGRESSION 3: KYC text-only submission preserved ===
    kyc_email = f"kyc_text_{suffix}@example.com"
    kyc_reg = register_user("Mohit KYC", kyc_email)
    kyc_token = kyc_reg["token"]
    r = post("/users/me/kyc", token=kyc_token,
             json_body={"full_name": "Mohit KYC", "aadhaar": "111122223333", "pan": "ABCDE1234F"})
    record("REG3a. KYC text-only submit → 200 pending",
           r.status_code == 200 and r.json().get("status") == "pending",
           f"status={r.status_code} body={r.text[:200]}")
    r = get("/users/me/kyc", token=kyc_token)
    record("REG3b. GET /users/me/kyc shows pending and has_*=False (text-only)",
           r.status_code == 200 and r.json().get("status") == "pending"
           and not r.json().get("has_aadhaar_front") and not r.json().get("has_pan_image"),
           f"status={r.status_code} body={r.text[:200]}")

    # === REGRESSION 4: Admin management spot-check (GET /admin/admins; PATCH role gated) ===
    r = get("/admin/admins", token=T_admin)
    if r.status_code != 200:
        record("REG4. GET /admin/admins → 200", False, f"status={r.status_code} body={r.text[:200]}")
    else:
        admins = r.json()
        first = admins[0] if admins else {}
        no_pwd = "password_hash" not in first
        no_kyc_imgs = all(k not in first for k in ("kyc_aadhaar_front", "kyc_aadhaar_back", "kyc_pan_image", "kyc_selfie"))
        record("REG4. GET /admin/admins lightweight (no password_hash / kyc images)",
               no_pwd and no_kyc_imgs and any(a.get("email") == ADMIN_EMAIL for a in admins),
               f"count={len(admins)} no_pwd={no_pwd} no_kyc_imgs={no_kyc_imgs}")

    # === REGRESSION 5: status filter validations on /admin/approvals ===
    r = get("/admin/approvals", token=T_admin, params={"status": "garbage"})
    record("REG5. /admin/approvals?status=garbage → 400 'Invalid status'",
           r.status_code == 400 and "Invalid status" in (r.json().get("detail") or ""),
           f"status={r.status_code} body={r.text[:200]}")

    r = get("/admin/approvals", token=T_admin, params={"status": "approved"})
    record("REG6. /admin/approvals?status=approved returns S and C",
           r.status_code == 200 and any(i.get("id") == s_id for i in r.json())
           and any(i.get("id") == c_id for i in r.json()),
           f"status={r.status_code}")

    # ---- summary ----
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"TOTAL: {passed}/{total} passed")
    fails = [r for r in results if not r[1]]
    if fails:
        print("\nFAILURES:")
        for n, _, info in fails:
            print(f" - {n} :: {info}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
