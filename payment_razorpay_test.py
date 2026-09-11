#!/usr/bin/env python3
"""Tests for Razorpay-compatible mock payment flow (Phase A) on NetworkPay backend."""
import os
import sys
import time
import uuid
import json
import requests

BASE = "https://slangcart-tracking.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

passed = []
failed = []


def check(label, cond, info=""):
    if cond:
        passed.append(label)
        print(f"PASS  {label}")
    else:
        failed.append(f"{label} -- {info}")
        print(f"FAIL  {label} :: {info}")


def post(path, json_body=None, token=None, expect=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.post(BASE + path, json=json_body, headers=headers, timeout=30)
    return r


def get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(BASE + path, headers=headers, timeout=30)


def delete(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.delete(BASE + path, headers=headers, timeout=30)


def register_user(prefix):
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}_{suffix}@netpaytest.com"
    password = "Test@1234"
    name = f"Test {prefix.upper()} {suffix[:4]}"
    body = {"name": name, "email": email, "password": password, "phone": "9876543210"}
    r = requests.post(BASE + "/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"register failed for {email}: {r.status_code} {r.text}")
    data = r.json()
    return {"email": email, "password": password, "name": name, "token": data["token"], "id": data["user"]["id"]}


def login_user(email, password):
    r = requests.post(BASE + "/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


def main():
    # Admin login (for cleanup + regression)
    r = login_user(ADMIN_EMAIL, ADMIN_PASSWORD)
    check("Admin login admin@app.com → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        print("FATAL: cannot continue without admin login")
        sys.exit(1)
    admin_token = r.json()["token"]

    created_user_ids = []

    # ==================== A. SUCCESS PATH ====================
    print("\n==== A. SUCCESS PATH ====")
    u1 = register_user("u1")
    created_user_ids.append(u1["id"])
    # Re-login to capture token
    r = login_user(u1["email"], u1["password"])
    check("A1. U1 login → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    u1_token = r.json()["token"] if r.status_code == 200 else u1["token"]

    # A2. GET /payment/config
    r = get("/payment/config", token=u1_token)
    check("A2a. GET /payment/config → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        cfg = r.json()
        check("A2b. is_mock=true", cfg.get("is_mock") is True, f"got {cfg.get('is_mock')}")
        check("A2c. max_attempts=3", cfg.get("max_attempts") == 3, f"got {cfg.get('max_attempts')}")
        check("A2d. attempts_remaining=3", cfg.get("attempts_remaining") == 3, f"got {cfg.get('attempts_remaining')}")
        check("A2e. registration_paid=false", cfg.get("registration_paid") is False, f"got {cfg.get('registration_paid')}")
        check("A2f. amount_paise=10000", cfg.get("amount_paise") == 10000, f"got {cfg.get('amount_paise')}")
        check("A2g. key_id present", bool(cfg.get("key_id")), f"got {cfg.get('key_id')}")

    # A3. POST /payment/create-order
    r = post("/payment/create-order", token=u1_token)
    check("A3a. create-order → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    order_id = None
    if r.status_code == 200:
        body = r.json()
        order_id = body.get("order_id")
        check("A3b. order_id starts with 'order_MOCK_'", isinstance(order_id, str) and order_id.startswith("order_MOCK_"), f"got {order_id}")
        check("A3c. amount_paise=10000", body.get("amount_paise") == 10000, f"got {body.get('amount_paise')}")
        check("A3d. key_id present", bool(body.get("key_id")), f"got {body.get('key_id')}")

    # A4. Repeat create-order (idempotent - still 200)
    r = post("/payment/create-order", token=u1_token)
    check("A4. Repeat create-order → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # A5. /payment/verify with empty signature → 400
    r = post("/payment/verify", json_body={
        "razorpay_order_id": order_id or "order_MOCK_test",
        "razorpay_payment_id": "pay_MOCK_xyz",
        "razorpay_signature": "",
    }, token=u1_token)
    check("A5. /payment/verify empty sig → 400", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")

    # A6. /payment/verify with valid mock sig → 200
    r = post("/payment/verify", json_body={
        "razorpay_order_id": order_id or "order_MOCK_test",
        "razorpay_payment_id": "pay_MOCK_xyz",
        "razorpay_signature": "sig_MOCK_abc",
    }, token=u1_token)
    check("A6a. /payment/verify valid mock sig → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("A6b. ok=true", body.get("ok") is True, f"got {body}")

    # A7. /auth/me → registration_paid=true, approval_status=pending
    r = get("/auth/me", token=u1_token)
    check("A7a. /auth/me → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        me = r.json()
        check("A7b. registration_paid=true", me.get("registration_paid") is True, f"got {me.get('registration_paid')}")
        check("A7c. approval_status=pending", me.get("approval_status") == "pending", f"got {me.get('approval_status')}")

    # A8. Second /payment/verify → 400 already paid
    r = post("/payment/verify", json_body={
        "razorpay_order_id": order_id or "order_MOCK_test",
        "razorpay_payment_id": "pay_MOCK_xyz2",
        "razorpay_signature": "sig_MOCK_abc2",
    }, token=u1_token)
    check("A8a. second /payment/verify → 400", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 400:
        check("A8b. detail mentions 'already paid'", "already paid" in r.text.lower(), f"detail: {r.text[:200]}")

    # A9. legacy /payment/register-fee → 400
    r = post("/payment/register-fee", token=u1_token)
    check("A9a. legacy /payment/register-fee on paid user → 400", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 400:
        check("A9b. legacy detail mentions 'already paid'", "already paid" in r.text.lower(), f"detail: {r.text[:200]}")

    # ==================== B. FAILURE / AUTO-ARCHIVE ====================
    print("\n==== B. FAILURE / AUTO-ARCHIVE ====")
    u2 = register_user("u2")
    created_user_ids.append(u2["id"])
    r = login_user(u2["email"], u2["password"])
    check("B0. U2 login → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    u2_token = r.json()["token"] if r.status_code == 200 else u2["token"]

    # B1. /payment/failure #1
    r = post("/payment/failure", json_body={"reason": "Card declined"}, token=u2_token)
    check("B1a. 1st /payment/failure → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("B1b. attempts_used=1", body.get("attempts_used") == 1, f"got {body}")
        check("B1c. archived=false", body.get("archived") is False, f"got {body}")
        check("B1d. attempts_remaining=2", body.get("attempts_remaining") == 2, f"got {body}")

    # B2. /payment/failure #2
    r = post("/payment/failure", json_body={"reason": "Card declined"}, token=u2_token)
    check("B2a. 2nd /payment/failure → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("B2b. attempts_used=2", body.get("attempts_used") == 2, f"got {body}")
        check("B2c. attempts_remaining=1", body.get("attempts_remaining") == 1, f"got {body}")
        check("B2d. archived=false", body.get("archived") is False, f"got {body}")

    # B3. /payment/failure #3 → archived
    r = post("/payment/failure", json_body={"reason": "Insufficient funds"}, token=u2_token)
    check("B3a. 3rd /payment/failure → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        body = r.json()
        check("B3b. attempts_used=3", body.get("attempts_used") == 3, f"got {body}")
        check("B3c. archived=true", body.get("archived") is True, f"got {body}")
        check("B3d. category=payment_unsuccessful", body.get("category") == "payment_unsuccessful", f"got {body}")

    # B4. /auth/me — approval_status=rejected, category set
    r = get("/auth/me", token=u2_token)
    check("B4a. U2 /auth/me → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        me = r.json()
        check("B4b. approval_status=rejected", me.get("approval_status") == "rejected", f"got {me.get('approval_status')}")
        check("B4c. reject category=payment_unsuccessful", me.get("approval_reject_category") == "payment_unsuccessful", f"got {me.get('approval_reject_category')}")

    # B5. login U2 → 403 with payment-related message
    r = login_user(u2["email"], u2["password"])
    check("B5a. U2 login → 403", r.status_code == 403, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 403:
        text = r.text.lower()
        check("B5b. detail mentions payment unsuccessful",
              "payment" in text and ("unsuccessful" in text or "fail" in text),
              f"detail: {r.text[:200]}")

    # B6. /payment/create-order → 400 max attempts (still uses old token)
    r = post("/payment/create-order", token=u2_token)
    check("B6a. create-order after archive → 400", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 400:
        text = r.text.lower()
        check("B6b. detail mentions max attempts",
              "attempt" in text or "maximum" in text,
              f"detail: {r.text[:200]}")

    # ==================== C. MIXED PATH ====================
    print("\n==== C. MIXED PATH (failures then success) ====")
    u3 = register_user("u3")
    created_user_ids.append(u3["id"])
    r = login_user(u3["email"], u3["password"])
    check("C0. U3 login → 200", r.status_code == 200, f"got {r.status_code}")
    u3_token = r.json()["token"] if r.status_code == 200 else u3["token"]

    # C1. /payment/failure x2
    r = post("/payment/failure", json_body={"reason": "test"}, token=u3_token)
    check("C1a. U3 failure #1 → 200", r.status_code == 200, f"got {r.status_code}")
    r = post("/payment/failure", json_body={"reason": "test"}, token=u3_token)
    check("C1b. U3 failure #2 → 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        body = r.json()
        check("C1c. attempts_remaining=1", body.get("attempts_remaining") == 1, f"got {body}")
        check("C1d. archived=false", body.get("archived") is False, f"got {body}")

    # C2. create-order + verify
    r = post("/payment/create-order", token=u3_token)
    check("C2a. U3 create-order after 2 failures → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    order_id_3 = r.json().get("order_id") if r.status_code == 200 else "order_MOCK_x"
    r = post("/payment/verify", json_body={
        "razorpay_order_id": order_id_3,
        "razorpay_payment_id": "pay_MOCK_u3",
        "razorpay_signature": "sig_MOCK_u3",
    }, token=u3_token)
    check("C2b. U3 /payment/verify → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # C3. /auth/me registration_paid=true
    r = get("/auth/me", token=u3_token)
    if r.status_code == 200:
        me = r.json()
        check("C3. U3 registration_paid=true after success-after-failures",
              me.get("registration_paid") is True, f"got {me.get('registration_paid')}")
    else:
        check("C3. U3 /auth/me → 200", False, f"got {r.status_code}")

    # ==================== D. LEGACY COMPAT ====================
    print("\n==== D. LEGACY COMPAT ====")
    u4 = register_user("u4")
    created_user_ids.append(u4["id"])
    r = login_user(u4["email"], u4["password"])
    check("D0. U4 login → 200", r.status_code == 200, f"got {r.status_code}")
    u4_token = r.json()["token"] if r.status_code == 200 else u4["token"]

    r = post("/payment/register-fee", token=u4_token)
    check("D1a. legacy /payment/register-fee → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        # Verify registration_paid via /auth/me
        rme = get("/auth/me", token=u4_token)
        if rme.status_code == 200:
            check("D1b. registration_paid=true after legacy", rme.json().get("registration_paid") is True, f"got {rme.json().get('registration_paid')}")

    r = post("/payment/register-fee", token=u4_token)
    check("D2a. legacy /payment/register-fee 2nd call → 400", r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 400:
        check("D2b. detail mentions 'already paid'", "already paid" in r.text.lower(), f"detail: {r.text[:200]}")

    # ==================== E. UNAUTHENTICATED ====================
    print("\n==== E. UNAUTHENTICATED ====")
    r = requests.get(BASE + "/payment/config", timeout=30)
    check("E1. /payment/config no token → 401", r.status_code == 401, f"got {r.status_code}: {r.text[:200]}")

    r = requests.post(BASE + "/payment/verify", json={
        "razorpay_order_id": "x", "razorpay_payment_id": "y", "razorpay_signature": "z"
    }, timeout=30)
    check("E2. /payment/verify no token → 401", r.status_code == 401, f"got {r.status_code}: {r.text[:200]}")

    # ==================== F. CLEANUP ====================
    print("\n==== F. CLEANUP ====")
    for uid in created_user_ids:
        r = delete(f"/admin/users/{uid}", token=admin_token)
        check(f"F. DELETE user {uid[:8]} → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # ==================== G. REGRESSION ====================
    print("\n==== G. REGRESSION ====")
    r = get("/auth/me", token=admin_token)
    check("G1. admin /auth/me → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    r = get("/admin/users", token=admin_token)
    check("G2. admin /admin/users → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")

    # ==================== Summary ====================
    print("\n========== SUMMARY ==========")
    print(f"PASSED: {len(passed)}")
    print(f"FAILED: {len(failed)}")
    if failed:
        print("\nFAILURES:")
        for f in failed:
            print(f"  - {f}")
    print("=============================")
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
