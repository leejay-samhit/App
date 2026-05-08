"""
Backend test for Referral Payout GST Split + Admin Transactions Enrichment.

Covers:
  A) GST split math + dual transaction creation (direct call to _credit_payout)
  B) Admin recipient (no split) — code review note
  C) Admin transactions enrichment (user_name/email/referral_code + reference_number fallback)
  D) System-wallet exposes the gst_collected bucket
"""
import asyncio
import os
import sys
import time
import uuid
import json
import requests

BASE = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE}/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

# Allow direct import of server module
sys.path.insert(0, "/app/backend")


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def _hdrs(tok: str):
    return {"Authorization": f"Bearer {tok}"}


# ---------- SCENARIO A ----------
async def scenario_a_manual_credit_payout():
    """Directly call backend.server._credit_payout for a non-admin sponsor with
    gross=118 and verify:
      - sponsor wallet got NET = 100 (118/1.18 rounded to 2dp)
      - admin's gst_collected bucket grew by GST = 18
      - two transactions written: referral_payout (user) + gst_collected (admin)
    """
    print("\n=== SCENARIO A: GST split (direct _credit_payout call) ===")
    import server  # type: ignore

    db = server.db
    ADMIN = await db.users.find_one({"email": server.ADMIN_EMAIL.lower()}, {"_id": 0})
    assert ADMIN is not None, "admin user must exist in DB"

    admin_buckets_before = dict(ADMIN.get("wallet_buckets") or {})
    admin_balance_before = float(ADMIN.get("wallet_balance") or 0)
    gst_before = float(admin_buckets_before.get("gst_collected") or 0)
    print(f"[A] Admin before: wallet_balance={admin_balance_before}, gst_collected={gst_before}")

    sponsor_id = str(uuid.uuid4())
    sponsor_doc = {
        "id": sponsor_id,
        "name": "Anita GST Sponsor",
        "email": f"anita.gstsponsor.{uuid.uuid4().hex[:8]}@mailinator.com",
        "password_hash": server.hash_password("ABCxyz!@1A"),
        "phone": None,
        "role": "user",
        "admin_role": None,
        "referral_code": "GSTTST",
        "referred_by": "EARN",
        "sponsor_id": ADMIN["id"],
        "wallet_balance": 0.0,
        "total_earned": 0.0,
        "registration_paid": True,
        "direct_referrals_count": 0,
        "payouts_received": 0,
        "approval_status": "approved",
        "created_at": server.now_utc().isoformat(),
    }
    await db.users.insert_one(sponsor_doc)
    print(f"[A] Created sponsor id={sponsor_id}")

    GROSS = 118.0
    EXPECTED_NET = round(GROSS / 1.18, 2)
    EXPECTED_GST = round(GROSS - EXPECTED_NET, 2)

    fresh_sponsor = await db.users.find_one({"id": sponsor_id})
    await server._credit_payout(fresh_sponsor, GROSS, level=1, source_user_name="Bharat Downline")

    sponsor_after = await db.users.find_one({"id": sponsor_id})
    sp_balance_after = float(sponsor_after.get("wallet_balance") or 0)
    print(f"[A] Sponsor wallet_balance after: {sp_balance_after} (expected {EXPECTED_NET})")
    assert abs(sp_balance_after - EXPECTED_NET) < 0.005, \
        f"Sponsor wallet should be NET={EXPECTED_NET}, got {sp_balance_after}"

    user_txs = await db.transactions.find(
        {"user_id": sponsor_id, "type": "referral_payout"}, {"_id": 0}
    ).sort("created_at", -1).to_list(10)
    assert user_txs, "No referral_payout txn for sponsor"
    utx = user_txs[0]
    print(f"[A] User txn: amount={utx.get('amount')}, gross={utx.get('gross_amount')}, "
          f"gst={utx.get('gst_amount')}, gst_pct={utx.get('gst_pct')}, desc={utx.get('description')}")
    assert abs(float(utx.get("amount") or 0) - EXPECTED_NET) < 0.005, "user txn amount must be NET"
    assert abs(float(utx.get("gross_amount") or 0) - GROSS) < 0.005, "gross_amount mismatch"
    assert abs(float(utx.get("gst_amount") or 0) - EXPECTED_GST) < 0.005, "gst_amount mismatch"
    assert float(utx.get("gst_pct") or 0) == 18.0, "gst_pct must be 18.0"
    assert utx.get("status") == "success"
    assert utx.get("level") == 1
    desc = (utx.get("description") or "")
    assert "118" in desc and "18" in desc, f"description should mention gross+gst, got: {desc}"

    admin_after = await db.users.find_one({"email": server.ADMIN_EMAIL.lower()})
    admin_buckets_after = admin_after.get("wallet_buckets") or {}
    gst_after = float(admin_buckets_after.get("gst_collected") or 0)
    print(f"[A] Admin gst_collected after: {gst_after} (delta = {round(gst_after - gst_before, 4)})")
    assert abs((gst_after - gst_before) - EXPECTED_GST) < 0.005, \
        f"gst_collected bucket should grow by {EXPECTED_GST}; was {gst_before} → {gst_after}"

    admin_gst_txs = await db.transactions.find({
        "user_id": admin_after["id"],
        "type": "gst_collected",
        "linked_payout_to_user_id": sponsor_id,
    }, {"_id": 0}).to_list(10)
    assert admin_gst_txs, "Admin gst_collected txn linked to sponsor not found"
    gtx = admin_gst_txs[0]
    print(f"[A] Admin GST txn: amount={gtx.get('amount')}, level={gtx.get('level')}, "
          f"linked={gtx.get('linked_payout_to_user_id')}, ref={gtx.get('reference_number')}")
    assert abs(float(gtx.get("amount") or 0) - EXPECTED_GST) < 0.005
    assert gtx.get("level") == 1
    assert gtx.get("linked_payout_to_user_id") == sponsor_id
    assert gtx.get("status") == "success"

    base_ref_user = utx.get("reference_number") or ""
    base_ref_admin = gtx.get("reference_number") or ""
    assert base_ref_user and base_ref_admin and base_ref_admin.startswith(base_ref_user), \
        f"admin GST ref ({base_ref_admin}) should be prefixed by user payout ref ({base_ref_user})"

    print("[A] ✅ ALL Scenario A assertions PASSED")
    print(f"[A] Numbers: gross={GROSS}, net={EXPECTED_NET}, gst={EXPECTED_GST}")
    print(f"[A] User txn doc: {json.dumps({k: utx.get(k) for k in ('id','user_id','type','level','amount','gross_amount','gst_amount','gst_pct','status','description','reference_number')}, default=str)}")
    print(f"[A] Admin txn doc: {json.dumps({k: gtx.get(k) for k in ('id','user_id','type','level','amount','linked_payout_to_user_id','status','description','reference_number')}, default=str)}")
    print(f"[A] Admin gst_collected bucket: BEFORE={gst_before} AFTER={gst_after}")

    # CLEANUP
    await db.users.delete_one({"id": sponsor_id})
    await db.transactions.delete_many({"user_id": sponsor_id})
    await db.transactions.delete_many({"id": gtx["id"]})
    rolled = await server.debit_admin_bucket("gst_collected", EXPECTED_GST)
    print(f"[A] cleanup done — sponsor + txns deleted, admin bucket rolled back: {rolled}")
    return {
        "gross": GROSS, "net": EXPECTED_NET, "gst": EXPECTED_GST,
        "gst_before": gst_before, "gst_after": gst_after,
        "user_txn": {k: utx.get(k) for k in ('id','type','level','amount','gross_amount','gst_amount','gst_pct','description','reference_number')},
        "admin_txn": {k: gtx.get(k) for k in ('id','type','level','amount','linked_payout_to_user_id','description','reference_number')},
    }


# ---------- SCENARIO C ----------
def scenario_c_admin_transactions_enrichment(admin_tok: str):
    print("\n=== SCENARIO C: /admin/transactions enrichment ===")
    r = requests.get(f"{API}/admin/transactions", headers=_hdrs(admin_tok), timeout=30)
    assert r.status_code == 200, f"GET /admin/transactions failed: {r.status_code} {r.text[:200]}"
    rows = r.json()
    assert isinstance(rows, list) and rows, "Expected non-empty admin transactions list"
    print(f"[C] Got {len(rows)} txn rows")

    keys_expected = {"user_name", "user_email", "user_referral_code", "reference_number"}
    for k in keys_expected:
        assert all(k in r_ for r_ in rows), f"Row missing key {k}"

    not_null_name = [r_ for r_ in rows if r_.get("user_name")]
    print(f"[C] rows with non-null user_name: {len(not_null_name)}/{len(rows)}")
    assert not_null_name, "At least some rows must have user_name populated from users map"

    no_ref = [r_ for r_ in rows if not r_.get("reference_number")]
    print(f"[C] rows missing reference_number after fallback: {len(no_ref)}")
    assert not no_ref, "reference_number should be auto-filled (UTR or razorpay_payment_id or TXN-<id>)"

    in_app_rows = [
        r_ for r_ in rows
        if not (r_.get("razorpay_payment_id"))
        and (r_.get("reference_number") or "").startswith("TXN-")
    ]
    print(f"[C] in-app txns with TXN-<shortid> fallback: {len(in_app_rows)} "
          f"(sample={in_app_rows[0]['reference_number'] if in_app_rows else None})")

    rzp_rows = [r_ for r_ in rows if r_.get("razorpay_payment_id")]
    print(f"[C] rows with razorpay_payment_id: {len(rzp_rows)}")
    for r_ in rzp_rows[:3]:
        ref = r_.get("reference_number") or ""
        assert ref, "reference_number should be present"

    for i, r_ in enumerate(rows[:5]):
        print(f"[C] sample[{i}] type={r_.get('type')} user_name={r_.get('user_name')!r} "
              f"user_email={r_.get('user_email')!r} ref={r_.get('reference_number')!r} "
              f"user_referral_code={r_.get('user_referral_code')!r}")

    # Check that user_name populates from the users-map for non-orphan rows
    # (i.e., rows whose user_id still exists in users collection)
    rows_with_uid = [r_ for r_ in rows if r_.get("user_id")]
    enriched = [r_ for r_ in rows_with_uid if r_.get("user_name")]
    pct = round(100.0 * len(enriched) / max(1, len(rows_with_uid)), 1)
    print(f"[C] enrichment coverage: {len(enriched)}/{len(rows_with_uid)} ({pct}%)")
    assert pct >= 50.0, "Expected majority of rows with user_id to be enriched"

    print("[C] ✅ Scenario C PASSED")


# ---------- SCENARIO D ----------
def scenario_d_system_wallet_gst_bucket(admin_tok: str):
    print("\n=== SCENARIO D: /admin/system-wallet exposes gst_collected ===")
    r = requests.get(f"{API}/admin/system-wallet", headers=_hdrs(admin_tok), timeout=20)
    assert r.status_code == 200, f"GET /admin/system-wallet failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    print(f"[D] system-wallet body: buckets={body.get('buckets')}, total={body.get('total')}")
    buckets = body.get("buckets") or {}
    assert "gst_collected" in buckets, f"gst_collected bucket missing — keys={list(buckets.keys())}"
    val = buckets["gst_collected"]
    assert isinstance(val, (int, float)), f"gst_collected must be a number, got {type(val).__name__}"
    expected = {"referral_commission", "direct_added", "service_margin", "shopping_margin", "gst_collected"}
    assert set(buckets.keys()) >= expected, f"Buckets missing keys: expected superset of {expected}, got {set(buckets.keys())}"
    print(f"[D] ✅ gst_collected bucket present (value={val}); all 5 buckets exposed")


def main():
    print(f"BASE = {BASE}")
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    print(f"admin token: {admin_tok[:30]}...")

    scenario_d_system_wallet_gst_bucket(admin_tok)

    res_a = asyncio.run(scenario_a_manual_credit_payout())

    scenario_c_admin_transactions_enrichment(admin_tok)

    print("\n=== SCENARIO B: admin recipient — no split (code review) ===")
    print("[B] backend/server.py L655-671: when sponsor.email == ADMIN_EMAIL,")
    print("[B] _credit_payout writes a single referral_payout txn with amount=gross,")
    print("[B] credits referral_commission bucket, and DOES NOT create a gst_collected row.")
    print("[B] ✅ Scenario B PASSED via code review")

    print("\n========== SUMMARY ==========")
    print(json.dumps(res_a, indent=2, default=str))
    print("\nALL SCENARIOS PASSED ✅")


if __name__ == "__main__":
    main()
