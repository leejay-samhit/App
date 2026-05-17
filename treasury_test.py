#!/usr/bin/env python3
"""
Treasury / Admin Stats / GST txn enrichment / System wallet regression test
Review request: treasury-accounting fixes.
"""
import os
import sys
import time
import uuid
import json
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
AARAV_EMAIL = "aarav@demo.app"
AARAV_PASSWORD = "Demo@123"
AARAV_REF_CODE = "AARAV01"

results = []  # list of (name, ok, detail)


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {name}  {detail[:300]}")


def post(path, token=None, **kwargs):
    h = kwargs.pop("headers", {}) or {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.post(BASE + path, headers=h, timeout=30, **kwargs)


def get(path, token=None, **kwargs):
    h = kwargs.pop("headers", {}) or {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.get(BASE + path, headers=h, timeout=30, **kwargs)


def login(email, password):
    r = requests.post(BASE + "/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("access_token") or r.json().get("token")


def main():
    print(f"Base: {BASE}\n")

    # ===== Setup: admin token =====
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    record("Admin login", admin_token is not None, "got token" if admin_token else "FAILED")
    if not admin_token:
        print("Cannot proceed without admin"); return

    # ===== A) /admin/stats =====
    print("\n=== A) GET /admin/stats ===")
    r = get("/admin/stats", admin_token)
    record("A.1 GET /admin/stats returns 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        data = r.json()
        required = [
            "total_users", "paid_users", "pending_payouts", "total_revenue",
            "total_referral_payouts", "total_pending_withdrawals_amount",
            "total_completed_withdrawals_amount",
        ]
        missing = [k for k in required if k not in data]
        record("A.2 All required fields present", not missing, f"missing={missing} present_keys={list(data.keys())}")

        # Numeric & non-negative
        bad = []
        for k in required:
            v = data.get(k)
            if not isinstance(v, (int, float)):
                bad.append(f"{k}=({type(v).__name__}){v}")
            elif v < 0:
                bad.append(f"{k}={v} (negative)")
        record("A.3 All fields numeric & non-negative", not bad, f"issues={bad}")

        # total_revenue > 0 (assuming registered txns exist)
        tr = data.get("total_revenue", 0)
        record("A.4 total_revenue > 0", tr > 0, f"total_revenue={tr}")

        print(f"  total_users={data.get('total_users')}  paid_users={data.get('paid_users')}")
        print(f"  total_revenue={data.get('total_revenue')}")
        print(f"  total_referral_payouts={data.get('total_referral_payouts')}")
        print(f"  pending_payouts={data.get('pending_payouts')}")
        print(f"  pending_wd_amt={data.get('total_pending_withdrawals_amount')}  "
              f"completed_wd_amt={data.get('total_completed_withdrawals_amount')}")

    # ===== A.3) Test withdrawal endpoint sanity (optional) =====
    aarav_token = login(AARAV_EMAIL, AARAV_PASSWORD)
    if aarav_token:
        # try ₹100 withdrawal (should fail due to insufficient balance,
        # but endpoint must not crash)
        wr = post("/withdrawals", aarav_token, json={"amount": 100})
        # endpoint must respond — ANY non-5xx is fine
        record("A.5 Withdrawal endpoint doesn't crash (5xx)",
               wr.status_code < 500,
               f"status={wr.status_code} body={wr.text[:200]}")
        # Re-poll stats — should still be 200
        r2 = get("/admin/stats", admin_token)
        record("A.6 /admin/stats stable after withdrawal attempt", r2.status_code == 200,
               f"status={r2.status_code}")

    # ===== B) GST txn enrichment =====
    print("\n=== B) GST txn enrichment ===")
    # IMPORTANT: enriched gst_collected fields are only created in _credit_payout
    # when the PAYOUT RECIPIENT is NOT admin (admin path returns early without
    # creating a gst_collected txn). So we must build a chain:
    #   admin → Aarav → User_A → User_B
    # When User_B is approved, L2 payout goes to User_A (non-admin) which
    # triggers the enriched gst_collected creation with sponsor_name=User_A
    # and source_user_name=User_B.
    cleanup_ids = []
    uniq_a = uuid.uuid4().hex[:8]
    name_a = f"ChainUserA {uniq_a.upper()}"
    email_a = f"chain_a_{uniq_a}@test.app"

    # 1) Register A under AARAV01
    rA = post("/auth/register", json={
        "name": name_a, "email": email_a, "password": "ChainA@2026",
        "phone": f"98{uniq_a[:8]}", "referral_code": AARAV_REF_CODE,
    })
    record("B.1a Register chain user A under AARAV01", rA.status_code == 200,
           f"status={rA.status_code} body={rA.text[:200]}")
    if rA.status_code != 200:
        print("Cannot continue Test B"); return
    token_a = rA.json().get("access_token") or rA.json().get("token")
    me_a = get("/auth/me", token_a).json()
    user_a_id = me_a.get("id")
    ref_code_a = me_a.get("referral_code")
    cleanup_ids.append(user_a_id)
    record("B.1b A has referral_code", bool(ref_code_a), f"ref={ref_code_a}")

    # Pay & approve A
    post("/payment/register-fee", token_a, json={"amount": 118})
    apA = post(f"/admin/approvals/{user_a_id}/approve", admin_token)
    record("B.1c Approve user A", apA.status_code == 200, f"status={apA.status_code}")
    time.sleep(0.3)

    # 2) Register B under A's referral code  → on approval, L2 fires to Aarav (non-admin)
    uniq_b = uuid.uuid4().hex[:8]
    new_name = f"ChainUserB {uniq_b.upper()}"
    email_b = f"chain_b_{uniq_b}@test.app"
    rB = post("/auth/register", json={
        "name": new_name, "email": email_b, "password": "ChainB@2026",
        "phone": f"97{uniq_b[:8]}", "referral_code": ref_code_a,
    })
    record("B.1 Register joiner under non-admin upline (A→Aarav→admin)",
           rB.status_code == 200, f"status={rB.status_code} body={rB.text[:200]}")
    if rB.status_code != 200:
        # cleanup A
        for uid in cleanup_ids:
            requests.delete(BASE + f"/admin/users/{uid}",
                            headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        return
    token_b = rB.json().get("access_token") or rB.json().get("token")
    me_b = get("/auth/me", token_b).json()
    new_user_id = me_b.get("id")
    cleanup_ids.append(new_user_id)

    pr = post("/payment/register-fee", token_b, json={"amount": 118})
    record("B.2 Pay registration fee (B)", pr.status_code == 200,
           f"status={pr.status_code} body={pr.text[:200]}")

    record("B.3 /auth/me returns user id (B)", bool(new_user_id), f"id={new_user_id}")

    ap = post(f"/admin/approvals/{new_user_id}/approve", admin_token)
    record("B.4 Admin approve joiner B", ap.status_code == 200,
           f"status={ap.status_code} body={ap.text[:200]}")
    time.sleep(0.7)

    # Pull gst_collected transactions
    gst_r = get("/admin/system-wallet/transactions?bucket=gst_collected&limit=200", admin_token)
    record("B.5 GET gst_collected txns 200", gst_r.status_code == 200,
           f"status={gst_r.status_code}")
    if gst_r.status_code == 200:
        payload = gst_r.json()
        items = payload.get("items", [])
        print(f"  Total gst_collected rows fetched: {len(items)}  bucket subtotal={payload.get('subtotal')}")

        # Find rows for our joiner B
        rows_for_joiner = [it for it in items
                           if it.get("source_user_name") == new_name
                           or new_name in (it.get("description") or "")]
        print(f"  Rows for joiner '{new_name}': {len(rows_for_joiner)}")
        record("B.5a gst_collected rows created for joiner",
               len(rows_for_joiner) >= 1,
               f"found={len(rows_for_joiner)} (expected ≥1 from L2 payout to user A)")

        if rows_for_joiner:
            sample = rows_for_joiner[0]
            print(f"  Sample row keys: {sorted(sample.keys())}")
            print(f"  Sample row: {json.dumps(sample, default=str)[:800]}")

            record("B.6 gst_collected row has gross_amount (numeric)",
                   isinstance(sample.get("gross_amount"), (int, float)),
                   f"gross_amount={sample.get('gross_amount')}")
            record("B.7 gst_collected row has gst_pct == 18.0",
                   float(sample.get("gst_pct") or 0) == 18.0,
                   f"gst_pct={sample.get('gst_pct')}")
            record("B.8 gst_collected row has sponsor_name",
                   bool(sample.get("sponsor_name")),
                   f"sponsor_name={sample.get('sponsor_name')}")
            record("B.8b sponsor_name == user A name",
                   sample.get("sponsor_name") == name_a,
                   f"got={sample.get('sponsor_name')} expected={name_a}")
            record("B.9 gst_collected row has source_user_name (joiner)",
                   bool(sample.get("source_user_name")),
                   f"source_user_name={sample.get('source_user_name')}")
            record("B.9b source_user_name == joiner B name",
                   sample.get("source_user_name") == new_name[:30],
                   f"got={sample.get('source_user_name')} expected={new_name[:30]}")
            desc = sample.get("description") or ""
            has_gst_phrase = ("GST 18% on L" in desc) and ("payout to" in desc) and ("triggered by" in desc)
            record("B.10 description format 'GST 18% on L<lvl> payout to <sponsor> ... triggered by <joiner>'",
                   has_gst_phrase,
                   f"desc={desc!r}")
            record("B.10b description mentions sponsor (user A)",
                   name_a in desc,
                   f"desc={desc!r}")
            record("B.10c description mentions joiner (user B)",
                   new_name[:30] in desc,
                   f"desc={desc!r}")

            # All rows for joiner should have enriched fields
            missing_fields_per_row = []
            for row in rows_for_joiner:
                miss = []
                if not isinstance(row.get("gross_amount"), (int, float)):
                    miss.append("gross_amount")
                if float(row.get("gst_pct") or 0) != 18.0:
                    miss.append("gst_pct")
                if not row.get("sponsor_name"):
                    miss.append("sponsor_name")
                if not row.get("source_user_name"):
                    miss.append("source_user_name")
                if miss:
                    missing_fields_per_row.append(f"L{row.get('level')}: missing {miss}")
            record(f"B.11 All {len(rows_for_joiner)} rows for joiner have enriched fields",
                   not missing_fields_per_row,
                   f"issues={missing_fields_per_row[:5]}")

    # Cleanup
    for uid in cleanup_ids:
        requests.delete(BASE + f"/admin/users/{uid}",
                        headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)

    # ===== C) System wallet buckets API =====
    print("\n=== C) System Wallet API ===")
    sw_r = get("/admin/system-wallet", admin_token)
    record("C.1 GET /admin/system-wallet returns 200", sw_r.status_code == 200,
           f"status={sw_r.status_code}")
    if sw_r.status_code == 200:
        sw = sw_r.json()
        record("C.2 Response has 'buckets' dict", isinstance(sw.get("buckets"), dict),
               f"type={type(sw.get('buckets')).__name__}")
        record("C.3 Response has 'total' key", "total" in sw,
               f"total={sw.get('total')}")

        expected_buckets = {"referral_commission", "direct_signup", "direct_added",
                            "service_margin", "shopping_margin", "gst_collected"}
        actual_buckets = set((sw.get("buckets") or {}).keys())
        missing = expected_buckets - actual_buckets
        record(f"C.4 All 6 bucket keys present", not missing,
               f"missing={missing} actual={actual_buckets}")
        print(f"  buckets={sw.get('buckets')}")
        print(f"  total={sw.get('total')}")

    # ===== Summary =====
    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"RESULT: {passed}/{total} PASSED")
    fails = [(n, d) for (n, ok, d) in results if not ok]
    if fails:
        print("\nFAILURES:")
        for n, d in fails:
            print(f"  - {n}: {d}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
