"""
Test: registration-fee duplicate-entry fix verification
Covers scenarios A (E2E no-duplicate), B (backfill verification), C (code review)
"""
import os
import sys
import hmac
import hashlib
import secrets
import time
import requests

BASE = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE}/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
RAZORPAY_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

results = []

def log(tag, ok, msg=""):
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {tag}: {msg}"
    print(line)
    results.append((tag, ok, msg))


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    return body.get("token") or body.get("access_token")


def auth_headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def scenario_C_code_review():
    print("\n=== SCENARIO C: Code review ===")
    src = open("/app/backend/server.py").read()

    c1 = ("await db.transactions.update_one(" in src
          and '"status": "created"' in src
          and '"razorpay_order_id": payload.razorpay_order_id' in src
          and "pending_res.modified_count" in src)
    log("C.1 payment_verify update-first logic", c1,
        "update_one pending row -> paid before insert_one fallback")

    c2 = ("Reg-fee duplicate backfill" in src
          and 'created_ids = [x["id"] for x in grp["ids"] if x["status"] == "created"]' in src
          and 'delete_many({"id": {"$in": created_ids}})' in src)
    log("C.2 on_startup backfill deletes created rows when paid exists", c2,
        "backfill block present in startup")


def scenario_A_e2e():
    print("\n=== SCENARIO A: End-to-end no-duplicate ===")
    admin_tok = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    suffix = secrets.token_hex(4)
    email = f"dupebug.{suffix}@mailinator.com"
    password = "Test@1234"

    r = requests.post(
        f"{API}/auth/register",
        json={
            "name": f"Dupe Test {suffix}",
            "email": email,
            "password": password,
            "phone": f"9{secrets.randbelow(10**9):09d}",
            "referral_code": "EARN",
        },
        timeout=20,
    )
    if r.status_code != 200:
        log("A.register", False, f"{r.status_code} {r.text[:200]}")
        return
    user_data = r.json()
    user_id = user_data.get("user", {}).get("id") or user_data.get("id")
    log("A.register", bool(user_id), f"user_id={user_id}")

    user_tok = login(email, password)

    r = requests.post(f"{API}/payment/create-order", headers=auth_headers(user_tok), timeout=20)
    if r.status_code != 200:
        log("A.create-order", False, f"{r.status_code} {r.text[:300]}")
        return
    body = r.json()
    order_id = body.get("order_id")
    log("A.create-order", bool(order_id), f"order_id={order_id}, amount_paise={body.get('amount_paise')}")

    def list_user_reg_fee_txns():
        r = requests.get(f"{API}/admin/transactions",
                         headers=auth_headers(admin_tok),
                         params={"limit": 200}, timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        items = payload.get("items") if isinstance(payload, dict) else payload
        if items is None:
            items = payload
        txns = [t for t in items
                if t.get("user_id") == user_id and t.get("type") == "registration_fee"]
        return txns

    before = list_user_reg_fee_txns()
    print(f"  [DB snapshot BEFORE verify] {len(before)} registration_fee row(s):")
    for t in before:
        print(f"    - id={t.get('id')} status={t.get('status')} "
              f"order_id={t.get('razorpay_order_id')} desc={t.get('description')!r}")
    created_rows = [t for t in before if t.get("status") == "created"
                    and t.get("razorpay_order_id") == order_id]
    log("A.before: exactly one 'created' reg_fee row", len(created_rows) == 1,
        f"found={len(created_rows)}")

    payment_id = "pay_NONEXISTENT_FOR_DUPE_TEST"
    msg = f"{order_id}|{payment_id}".encode()
    signature = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()

    r = requests.post(
        f"{API}/payment/verify",
        headers=auth_headers(user_tok),
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        },
        timeout=30,
    )
    if r.status_code != 200:
        log("A.verify", False, f"{r.status_code} {r.text[:300]}")
        requests.delete(f"{API}/admin/users/{user_id}", headers=auth_headers(admin_tok), timeout=20)
        return
    vbody = r.json()
    log("A.verify 200", True,
        f"rzp_status={vbody.get('rzp_status')} auto_approved={vbody.get('auto_approved')} "
        f"approval_status={vbody.get('approval_status')} utr={vbody.get('utr')!r}")

    time.sleep(0.5)

    after = list_user_reg_fee_txns()
    print(f"  [DB snapshot AFTER verify] {len(after)} registration_fee row(s):")
    for t in after:
        print(f"    - id={t.get('id')} status={t.get('status')} "
              f"order_id={t.get('razorpay_order_id')} "
              f"pay_id={t.get('razorpay_payment_id')} "
              f"desc={t.get('description')!r}")

    reg_rows_for_order = [t for t in after if t.get("razorpay_order_id") == order_id]
    log("A.1 exactly ONE reg_fee row for this order_id", len(reg_rows_for_order) == 1,
        f"count={len(reg_rows_for_order)}")

    log("A.2 exactly ONE reg_fee row for this user (across all)", len(after) == 1,
        f"count={len(after)}")

    if reg_rows_for_order:
        row = reg_rows_for_order[0]
        log("A.3 status == 'paid'", row.get("status") == "paid",
            f"actual={row.get('status')}")
        log("A.4 razorpay_payment_id matches", row.get("razorpay_payment_id") == payment_id,
            f"actual={row.get('razorpay_payment_id')}")
        desc = row.get("description") or ""
        log("A.5 description starts with 'Registration fee via Razorpay'",
            desc.startswith("Registration fee via Razorpay"),
            f"actual={desc!r}")
        log("A.6 description is NOT 'Razorpay order created'",
            not desc.startswith("Razorpay order created"),
            f"actual={desc!r}")

    r = requests.delete(f"{API}/admin/users/{user_id}", headers=auth_headers(admin_tok), timeout=20)
    log("A.cleanup DELETE user", r.status_code == 200, f"{r.status_code}")


def scenario_B_backfill_verification():
    print("\n=== SCENARIO B: Backfill verification (read-only) ===")
    admin_tok = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    r = requests.get(f"{API}/admin/transactions",
                     headers=auth_headers(admin_tok),
                     params={"limit": 500}, timeout=30)
    if r.status_code != 200:
        log("B.list", False, f"{r.status_code} {r.text[:300]}")
        return
    payload = r.json()
    items = payload.get("items") if isinstance(payload, dict) else payload
    if items is None:
        items = payload

    groups = {}
    for t in items:
        if t.get("type") != "registration_fee":
            continue
        oid = t.get("razorpay_order_id")
        if not oid:
            continue
        groups.setdefault(oid, []).append(t)

    duplicates = []
    for oid, rows in groups.items():
        statuses = {r.get("status") for r in rows}
        if "paid" in statuses and "created" in statuses:
            duplicates.append((oid, rows))

    print(f"  Total reg_fee order groups examined: {len(groups)}")
    print(f"  Groups with both 'paid' AND 'created' (duplicates remaining): {len(duplicates)}")
    for oid, rows in duplicates[:5]:
        print(f"    - order_id={oid}: statuses={[r.get('status') for r in rows]}")

    log("B.1 no order_id has both 'paid' and 'created' rows (duplicates collapsed)",
        len(duplicates) == 0,
        f"remaining_duplicate_order_ids={len(duplicates)}")


if __name__ == "__main__":
    try:
        scenario_C_code_review()
        scenario_A_e2e()
        scenario_B_backfill_verification()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for tag, ok, msg in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {tag}")
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if passed == total else 2)
