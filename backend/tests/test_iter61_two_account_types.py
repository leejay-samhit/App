"""Iteration 61 · Aug-2026 Phase-1 two-account-type business rules.

Verifies:
  * POST /api/admin/users/{id}/referral-approval (note required, ON cascade
    only if paid subscriber, OFF claws back).
  * Referral commissions never fire while referral_enabled is False.
  * PATCH /api/admin/users/{id} — registration_paid is IMMUTABLE.
  * POST /api/admin/users/create — always creates a non-subscriber, no
    registration_fee / gst / system_wallet_deposits rows are written.
  * two_account_types_migration_2026_08 already ran on the target DB.
  * GET /api/admin/export/users has the new columns and no literal 'None'.
"""

import os
import time
import uuid
from typing import Dict, Any

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@slangcart.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "3)Ywxtic")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "referral_ecom_db")

_CLIENT = MongoClient(MONGO_URL)
DB = _CLIENT[DB_NAME]

_TAG = uuid.uuid4().hex[:8]

UA = {"User-Agent": "Mozilla/5.0 curl-tester"}


def _admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, headers=UA)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", **UA}


@pytest.fixture(scope="module")
def admin_tok():
    return _admin_token()


@pytest.fixture(scope="module")
def admin_hdr(admin_tok):
    return _headers(admin_tok)


# ────────────────────────── Migration verification ──────────────────────────

def test_two_account_types_migration_state():
    """No legacy paid user (upi_manual / offline_cash) should remain."""
    leftover = DB.users.count_documents({
        "role": "user",
        "registration_paid": True,
        "registration_source": {"$in": ["upi_manual", "offline_cash"]},
    })
    assert leftover == 0, f"{leftover} legacy paid users still upi_manual/offline_cash — migration incomplete"


def test_migration_kept_historical_registration_fee_txns():
    total = DB.transactions.count_documents({"type": "registration_fee"})
    # >=1 — historical rows were KEPT per the spec.
    assert total >= 1, "historical registration_fee txns should be preserved"


def test_source_counts_new_keys(admin_hdr):
    r = requests.get(f"{API}/admin/users/source-counts", headers=admin_hdr)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("subscriber", "non_subscriber", "legacy", "all"):
        assert k in data, f"missing key {k}: {data}"
    assert isinstance(data["subscriber"], int) and data["subscriber"] >= 0
    assert isinstance(data["non_subscriber"], int) and data["non_subscriber"] >= 0
    assert isinstance(data["legacy"], int) and data["legacy"] >= 0


# ────────────────── admin_create_user: always non-subscriber ─────────────────

def _reg_fee_summary(admin_hdr, source: str = "all"):
    r = requests.get(f"{API}/admin/transactions/summary", params={"type": "registration_fee"}, headers=admin_hdr)
    assert r.status_code == 200, r.text
    d = r.json()
    return d


def _networth(admin_hdr):
    r = requests.get(f"{API}/admin/finance/net-worth", headers=admin_hdr)
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_create_user_is_always_non_subscriber(admin_hdr):
    """Create a user via admin, verify:
       - registration_paid=False, registration_source=None, paid_at=None,
         subscription_skipped=True, referral_enabled=False
       - NO registration_fee txn, NO gst_collected txn, NO system_wallet_deposits row
       - sponsor placement still works (sponsor_id/referred_by set)
       - registration_fee summary + net-worth unchanged
    """
    # 1) fetch sponsor for a valid referral_code (use admin EARN)
    sponsor = DB.users.find_one({"email": ADMIN_EMAIL.lower()})
    assert sponsor and sponsor.get("referral_code"), "admin sponsor not seeded"
    sponsor_code = sponsor["referral_code"]

    # 2) capture summaries BEFORE
    summary_before = _reg_fee_summary(admin_hdr)
    nw_before = _networth(admin_hdr)

    email = f"test_iter61_ac_{_TAG}@example.com"
    body = {
        "name": "TEST_iter61 AC",
        "email": email,
        "password": "Passw0rd!",
        "phone": "+911234500061",
        "referral_code": sponsor_code,
        # frontend now always sends mark_paid_offline=False; test both flags to
        # ensure the endpoint ignores them and always creates a non-subscriber.
        "mark_paid_offline": True,
        "registration_source": "razorpay",
        "utr": "TESTUTR61",
    }
    r = requests.post(f"{API}/admin/users/create", json=body, headers=admin_hdr)
    assert r.status_code == 200, r.text
    created = r.json().get("user") or {}
    uid = created["id"]

    # 3) DB-level verification (server contract)
    doc = DB.users.find_one({"id": uid})
    assert doc is not None
    assert doc.get("registration_paid") is False, doc.get("registration_paid")
    assert doc.get("registration_source") is None, doc.get("registration_source")
    assert doc.get("paid_at") is None
    assert doc.get("subscription_skipped") is True
    assert doc.get("referral_enabled") is False
    assert doc.get("sponsor_id") == sponsor["id"]
    assert (doc.get("referred_by") or "").upper() == sponsor_code.upper()

    # 4) NO ledger side-effects
    assert DB.transactions.count_documents({"user_id": uid, "type": "registration_fee"}) == 0
    assert DB.transactions.count_documents({"user_id": uid, "type": "gst_collected"}) == 0
    assert DB.system_wallet_deposits.count_documents({"user_id": uid}) == 0

    # 5) Summaries UNCHANGED
    summary_after = _reg_fee_summary(admin_hdr)
    assert summary_before.get("total_count") == summary_after.get("total_count"), (
        f"registration_fee total_count changed: {summary_before} → {summary_after}"
    )
    assert round(float(summary_before.get("total_amount") or 0), 2) == round(float(summary_after.get("total_amount") or 0), 2)

    nw_after = _networth(admin_hdr)
    g1_b = ((nw_before.get("group_1_revenue") or {}).get("total") or 0)
    g1_a = ((nw_after.get("group_1_revenue") or {}).get("total") or 0)
    assert round(float(g1_b), 2) == round(float(g1_a), 2), f"group_1_revenue changed: {g1_b} → {g1_a}"
    g3_b = ((nw_before.get("group_3_gst") or {}).get("total") or 0)
    g3_a = ((nw_after.get("group_3_gst") or {}).get("total") or 0)
    assert round(float(g3_b), 2) == round(float(g3_a), 2), f"group_3_gst changed: {g3_b} → {g3_a}"


# ─────────────────────── PATCH /admin/users/{id} immutable ────────────────────

def test_patch_admin_users_registration_paid_is_immutable(admin_hdr):
    """Create a throwaway razorpay-paid user directly in Mongo, then attempt to
    flip registration_paid via PATCH. Must be immutable per Aug-2026 spec."""
    uid = str(uuid.uuid4())
    email = f"test_iter61_imm_{_TAG}@example.com"
    DB.users.insert_one({
        "id": uid, "email": email, "name": "TEST_iter61 IMM",
        "password_hash": "x", "phone": "+919000610011",
        "role": "user", "admin_role": None,
        "referral_code": "IMMTST" + _TAG[:2].upper(),
        "referred_by": None, "sponsor_id": None,
        "registration_paid": True,
        "registration_source": "razorpay",
        "paid_at": "2026-01-15T00:00:00",
        "approval_status": "approved",
        "referral_enabled": False,
        "commission_triggered": False,
        "wallet_balance": 0.0, "total_earned": 0.0,
        "created_at": "2026-01-15T00:00:00",
    })
    try:
        # A) sending only registration_paid=false must return 400 'No fields provided'
        r = requests.patch(f"{API}/admin/users/{uid}",
                           json={"registration_paid": False}, headers=admin_hdr)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
        assert "no fields" in r.text.lower(), r.text

        doc = DB.users.find_one({"id": uid})
        assert doc.get("registration_paid") is True, "registration_paid was flipped after solo-field PATCH"

        # B) registration_paid=false alongside a real field must ignore the immutable field
        r2 = requests.patch(f"{API}/admin/users/{uid}",
                            json={"registration_paid": False, "phone": "+919000610099"},
                            headers=admin_hdr)
        assert r2.status_code == 200, r2.text
        doc2 = DB.users.find_one({"id": uid})
        assert doc2.get("registration_paid") is True, (
            "registration_paid was flipped when sent alongside phone — spec violation"
        )
    finally:
        DB.users.delete_one({"id": uid})


# ─────────────────────── referral-approval note validation ────────────────────

def test_referral_approval_note_required(admin_hdr):
    # Any user works — pick a non-subscriber recent one to avoid side effects on
    # legitimate users.
    target = DB.users.find_one({"role": "user"}, sort=[("created_at", -1)])
    assert target
    uid = target["id"]

    # missing note → 422
    r = requests.post(f"{API}/admin/users/{uid}/referral-approval",
                      json={"enabled": True}, headers=admin_hdr)
    assert r.status_code == 422, r.text

    # 2-char note → 422
    r = requests.post(f"{API}/admin/users/{uid}/referral-approval",
                      json={"enabled": True, "note": "ab"}, headers=admin_hdr)
    assert r.status_code == 422, r.text


# ──────────────── Full cascade + clawback arithmetic scenario ─────────────────

def _register_user(name, email, password, phone, sponsor_code) -> Dict[str, Any]:
    r = requests.post(f"{API}/auth/register", json={
        "name": name, "email": email, "password": password,
        "phone": phone, "referral_code": sponsor_code,
    }, headers=UA)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_sponsor_paid_and_enabled(user_id):
    """Bypass immutability by writing directly to Mongo — the review request
    permits DB access to set up the payout scenario."""
    DB.users.update_one({"id": user_id}, {"$set": {
        "registration_paid": True,
        "registration_source": "razorpay",
        "paid_at": "2026-01-15T00:00:00",
        "approval_status": "approved",
        "referral_enabled": True,
        "commission_triggered": True,
        "subscription_skipped": False,
    }})


def _make_member_paid_only(user_id):
    """Member paid but referral OFF — commissions must NOT fire yet."""
    DB.users.update_one({"id": user_id}, {"$set": {
        "registration_paid": True,
        "registration_source": "razorpay",
        "paid_at": "2026-01-15T00:00:00",
        "approval_status": "approved",
        "referral_enabled": False,
        "commission_triggered": False,
        "subscription_skipped": False,
    }})


def _wallet_and_earned(uid):
    u = DB.users.find_one({"id": uid}) or {}
    return round(float(u.get("wallet_balance") or 0), 2), round(float(u.get("total_earned") or 0), 2)


@pytest.fixture(scope="module")
def scenario(admin_hdr):
    """Sponsor + a paid member, referral OFF on both.

    Steps
    -----
      1. register sponsor via /auth/register with admin (EARN) as upline
      2. DB-flip sponsor paid+approved+referral_enabled ON so it can be an
         L1 recipient
      3. register member with sponsor's code
      4. DB-flip member registration_paid=true + registration_enabled=false
         (no commission yet)
    """
    admin = DB.users.find_one({"email": ADMIN_EMAIL.lower()})
    admin_code = admin["referral_code"]

    sp_email = f"test_iter61_sp_{_TAG}@example.com"
    _register_user("TEST Sponsor 61", sp_email, "Passw0rd!", "+919090610001", admin_code)
    sp = DB.users.find_one({"email": sp_email})
    assert sp, f"sponsor {sp_email} not found after register"
    _make_sponsor_paid_and_enabled(sp["id"])

    mem_email = f"test_iter61_mem_{_TAG}@example.com"
    _register_user("TEST Member 61", mem_email, "Passw0rd!", "+919090610002", sp["referral_code"])
    mem = DB.users.find_one({"email": mem_email})
    assert mem, f"member {mem_email} not found after register"
    _make_member_paid_only(mem["id"])

    # baseline wallet/earned snapshot for the sponsor + all uplines
    uplines = []
    cur = sp
    for _ in range(10):
        if not cur:
            break
        uplines.append({"id": cur["id"], "email": cur["email"],
                        "wallet_before": round(float(cur.get("wallet_balance") or 0), 2),
                        "earned_before": round(float(cur.get("total_earned") or 0), 2)})
        parent_code = cur.get("referred_by")
        if not parent_code:
            break
        cur = DB.users.find_one({"referral_code": parent_code})
    return {
        "sponsor_id": sp["id"], "sponsor_email": sp_email,
        "member_id": mem["id"], "member_email": mem_email,
        "uplines": uplines,
    }


def test_commissions_do_NOT_fire_while_referral_disabled(scenario, admin_hdr):
    """Baseline: member is paid but referral_enabled=false → NO payouts."""
    mid = scenario["member_id"]
    n_payouts = DB.transactions.count_documents({"related_signup_id": mid, "type": "referral_payout"})
    n_direct = DB.transactions.count_documents({"related_signup_id": mid, "type": "direct_signup_credit"})
    assert n_payouts == 0, f"referral_payout leaked: {n_payouts}"
    assert n_direct == 0, f"direct_signup_credit leaked: {n_direct}"


def test_referral_approval_on_triggers_cascade(scenario, admin_hdr):
    mid = scenario["member_id"]
    # Snapshot sponsor wallet/earned BEFORE
    sp_wallet_before, sp_earned_before = _wallet_and_earned(scenario["sponsor_id"])

    r = requests.post(f"{API}/admin/users/{mid}/referral-approval",
                      json={"enabled": True, "note": "Enabling for iter61 scenario test"},
                      headers=admin_hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["referral_enabled"] is True
    assert body["commissions_triggered"] is True, body

    # confirm at least one referral_payout row was created for this signup
    payouts = list(DB.transactions.find({"related_signup_id": mid, "type": "referral_payout", "status": "success"}))
    assert len(payouts) >= 1, "expected at least L1 referral_payout after ON"

    # user doc flags
    u = DB.users.find_one({"id": mid})
    assert u.get("referral_enabled") is True
    assert (u.get("referral_switch_note") or "").startswith("Enabling for iter61")
    assert u.get("referral_switch_at")
    assert u.get("referral_switch_by")
    assert isinstance(u.get("referral_switch_history"), list) and len(u["referral_switch_history"]) >= 1

    # Sponsor wallet MOVED (or at least a pending_directs counter/completion
    # counter moved). We assert at least one recipient wallet + total_earned
    # increased by the sum of their payouts.
    recipient_ids = {p["user_id"] for p in payouts}
    for rid in recipient_ids:
        gained = round(sum(float(p.get("amount") or 0) for p in payouts if p["user_id"] == rid), 2)
        u2 = DB.users.find_one({"id": rid}) or {}
        # can't compare pre/post here for arbitrary uplines but at minimum
        # wallet_balance should be >= gained
        assert float(u2.get("total_earned") or 0) >= gained - 0.01, (
            f"recipient {rid} total_earned lower than payout sum {gained}"
        )


def test_referral_approval_off_claws_back_exactly(scenario, admin_hdr):
    mid = scenario["member_id"]
    payouts = list(DB.transactions.find({"related_signup_id": mid, "type": "referral_payout", "status": "success"}))
    assert payouts, "test_referral_approval_on_triggers_cascade must run first"

    # capture per-recipient pre-OFF wallet + earned
    per_recip: Dict[str, Dict[str, float]] = {}
    total_net = 0.0
    total_pf = 0.0
    for p in payouts:
        rid = p["user_id"]
        amt = round(float(p.get("amount") or 0), 2)
        pf = round(float(p.get("platform_fee_amount") or 0), 2)
        agg = per_recip.setdefault(rid, {"net": 0.0, "pf": 0.0, "wallet_before": 0.0, "earned_before": 0.0})
        agg["net"] += amt
        agg["pf"] += pf
        total_net += amt
        total_pf += pf
    for rid in per_recip:
        u = DB.users.find_one({"id": rid}) or {}
        per_recip[rid]["wallet_before"] = round(float(u.get("wallet_balance") or 0), 2)
        per_recip[rid]["earned_before"] = round(float(u.get("total_earned") or 0), 2)

    # capture admin platform_fee_collected bucket before
    admin_doc = DB.users.find_one({"email": ADMIN_EMAIL.lower()}) or {}
    pf_before = round(float((admin_doc.get("wallet_buckets") or {}).get("platform_fee_collected") or 0), 2)

    r = requests.post(f"{API}/admin/users/{mid}/referral-approval",
                      json={"enabled": False, "note": "Refund done · iter61 clawback scenario"},
                      headers=admin_hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["referral_enabled"] is False
    cb = body.get("clawback") or {}
    assert cb.get("clawed_back_count") == len(payouts), f"clawback count mismatch: {cb} vs {len(payouts)} payouts"
    assert round(float(cb.get("clawed_back_amount") or 0), 2) == round(total_net, 2), (
        f"clawback amount mismatch: {cb.get('clawed_back_amount')} vs {total_net}"
    )
    assert round(float(cb.get("platform_fee_reversed") or 0), 2) == round(total_pf, 2), cb

    # Every original payout row is now status='reversed'
    reversed_rows = DB.transactions.count_documents({
        "related_signup_id": mid, "type": "referral_payout", "status": "reversed",
    })
    assert reversed_rows == len(payouts)

    # Per-recipient invariants: wallet_balance -= net, total_earned -= net
    for rid, agg in per_recip.items():
        u = DB.users.find_one({"id": rid}) or {}
        wallet_after = round(float(u.get("wallet_balance") or 0), 2)
        earned_after = round(float(u.get("total_earned") or 0), 2)
        expected_wallet = round(agg["wallet_before"] - agg["net"], 2)
        expected_earned = round(agg["earned_before"] - agg["net"], 2)
        assert wallet_after == expected_wallet, (
            f"{rid}: wallet {agg['wallet_before']}→{wallet_after}, expected {expected_wallet}"
        )
        assert earned_after == expected_earned, (
            f"{rid}: earned {agg['earned_before']}→{earned_after}, expected {expected_earned}"
        )
        # A refund_clawback txn per payout for this recipient
        cb_rows = DB.transactions.count_documents({
            "related_signup_id": mid, "type": "refund_clawback", "user_id": rid,
        })
        expected_cb_rows = sum(1 for p in payouts if p["user_id"] == rid)
        assert cb_rows == expected_cb_rows, f"{rid}: refund_clawback rows {cb_rows}, expected {expected_cb_rows}"
        # refund_debt bookkeeping: if wallet went negative, refund_debt should
        # cover the magnitude.
        if wallet_after < 0:
            assert float(u.get("refund_debt") or 0) >= abs(wallet_after) - 0.01

    # platform_fee_reversal ledger + admin bucket
    if total_pf > 0:
        pfr_rows = DB.transactions.count_documents({
            "related_signup_id": mid, "type": "platform_fee_reversal", "status": "success",
        })
        assert pfr_rows == sum(1 for p in payouts if float(p.get("platform_fee_amount") or 0) > 0)
        admin_doc2 = DB.users.find_one({"email": ADMIN_EMAIL.lower()}) or {}
        pf_after = round(float((admin_doc2.get("wallet_buckets") or {}).get("platform_fee_collected") or 0), 2)
        assert round(pf_before - pf_after, 2) == round(total_pf, 2), (
            f"platform_fee_collected {pf_before}→{pf_after}, expected -₹{total_pf}"
        )


# ────────────────── Users CSV export shape + note propagation ─────────────────

def test_admin_export_users_csv_shape(admin_hdr, scenario):
    """CSV must contain the new columns and must show the note we wrote on the
    scenario member during test_referral_approval_off_claws_back_exactly."""
    r = requests.get(f"{API}/admin/export/users", headers=admin_hdr)
    assert r.status_code == 200, r.text
    body = r.text
    header = body.splitlines()[0]
    for col in ("account_type", "paid_status", "join_source",
                "admin_approved", "admin_approved_note", "admin_approved_on", "admin_approved_by"):
        assert col in header, f"missing column {col} in CSV header: {header}"

    # Find the scenario member's row + note
    mem_email = scenario["member_email"].lower()
    lines = [ln for ln in body.splitlines()[1:] if mem_email in ln.lower()]
    assert lines, f"member row not found in CSV for {mem_email}"
    row = lines[0]
    # last note applied was the OFF note "Refund done · iter61 clawback scenario"
    assert "iter61 clawback" in row, f"expected note not in row: {row}"

    # No literal 'None' values (each field is either empty or a real value)
    # simple check: no lone 'None' surrounded by commas
    assert ",None," not in body and not body.startswith("None,") and not any(
        ln.strip().endswith(",None") for ln in body.splitlines()
    ), "literal 'None' present in CSV export"


# ─────────────────────────── teardown after the module ───────────────────────

def teardown_module(module):
    """Best-effort cleanup of the TEST_iter61_* rows we wrote."""
    try:
        emails = [u["email"] for u in DB.users.find({"email": {"$regex": "^test_iter61_"}}, {"email": 1})]
        if not emails:
            return
        ids = [u["id"] for u in DB.users.find({"email": {"$in": emails}}, {"id": 1})]
        DB.users.delete_many({"id": {"$in": ids}})
        DB.transactions.delete_many({"$or": [{"user_id": {"$in": ids}}, {"related_signup_id": {"$in": ids}}]})
        DB.notifications.delete_many({"user_id": {"$in": ids}})
        DB.audit_logs.delete_many({"target_id": {"$in": ids}})
    except Exception as e:  # noqa
        print(f"teardown skipped: {e}")
