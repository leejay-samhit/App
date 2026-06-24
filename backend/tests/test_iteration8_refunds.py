"""Iteration 8 — Group 8 Refund Flow backend tests.

Covers:
  * GET /api/admin/finance/net-worth       → group_8_refunds object & keys
  * GET /api/admin/expenses/categories     → "refunds" REMOVED from defaults
  * GET /api/admin/refunds/search          → search by name/email/referral_id/phone
  * GET /api/admin/refunds/preview/{uid}   → gst_breakdown + clawback rows
  * POST /api/admin/refunds                → cascade clawback / bank ledger / final action
       - validation: 400 / 404 / 409 paths
       - soft_delete vs remove_referral re-parenting
  * GET /api/admin/refunds                 → list + totals
  * GET /api/admin/refunds/{id}            → detail
  * GET /api/admin/finance/groups/group_8_refunds/transactions  → drilldown
  * Refund-debt absorption in _credit_payout (direct asyncio invocation)

Uses Mongo-direct seeding for the upline chain (Admin → A → B → C → D) so
the clawback math is deterministic.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pymongo
import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Make `server` importable for the debt-absorption test
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import auth_headers  # type: ignore  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

# A unique tag per test session
TEST_TAG = f"TEST_I8_{uuid.uuid4().hex[:8]}"

NET_PAYOUT = 328.0       # 400 gross − 72 platform-fee = 328 net
PLATFORM_FEE = 72.0
GROSS_PAYOUT = 400.0
REGISTRATION_FEE = 118.0  # default joining fee
NET_REG = round(REGISTRATION_FEE - (REGISTRATION_FEE - REGISTRATION_FEE / 1.18), 2)
GST_REG = round(REGISTRATION_FEE - REGISTRATION_FEE / 1.18, 2)


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def mongo_db():
    client = pymongo.MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    yield db
    # Teardown — cleanup all TEST_TAG-prefixed records and any refund rows
    db.users.delete_many({"name": {"$regex": f"^{TEST_TAG}"}})
    db.transactions.delete_many({"description": {"$regex": TEST_TAG}})
    db.transactions.delete_many({"source_user_name": {"$regex": TEST_TAG}})
    db.transactions.delete_many({"related_signup_id": {"$regex": f"^TEST_I8_"}})
    user_ids = [u["id"] for u in db.users.find({"name": {"$regex": f"^{TEST_TAG}"}}, {"id": 1})]
    if user_ids:
        db.transactions.delete_many({"user_id": {"$in": user_ids}})
        db.refunds.delete_many({"target_user_id": {"$in": user_ids}})
        db.bank_ledger.delete_many({"related_user_id": {"$in": user_ids}})
    # Final sweep — refund rows from this session
    db.refunds.delete_many({"target_name": {"$regex": f"^{TEST_TAG}"}})
    db.bank_ledger.delete_many({"description": {"$regex": TEST_TAG}})
    client.close()


def _mk_user(name: str, sponsor_id: str | None, wallet: float = 0.0,
             refund_debt: float = 0.0, registration_paid: bool = True) -> Dict[str, Any]:
    uid = f"TEST_I8_{uuid.uuid4().hex[:12]}"
    short = uid[-8:].upper()
    return {
        "id": uid,
        "name": f"{TEST_TAG}_{name}",
        "email": f"{uid.lower()}@test.local",
        "phone": f"+91-9999{uuid.uuid4().hex[:6]}",
        "role": "user",
        "sponsor_id": sponsor_id,
        "referral_id": f"REF_{short}",
        "referral_code": f"RC_{short}",
        "my_referral_code": f"REF_{short}",
        "wallet_balance": wallet,
        "registration_paid": registration_paid,
        "registration_amount": REGISTRATION_FEE,
        "refund_debt": refund_debt,
        "total_earned": 0.0,
        "direct_referrals_count": 0,
        "is_blocked": False,
        "status": "active",
        "commission_triggered": True,
        "created_at": "2026-01-01T00:00:00",
    }


@pytest.fixture(scope="module")
def seed_chain(mongo_db):
    """Create A → B → C → D chain. Admin already exists in DB.
    D's signup triggered referral_payout to C (L1), B (L2), A (L3).
    """
    admin_doc = mongo_db.users.find_one({"role": "super_admin"}) or mongo_db.users.find_one({"role": "admin"})
    assert admin_doc, "Admin doc not found in DB"

    A = _mk_user("A", admin_doc["id"], wallet=500.0)
    B = _mk_user("B", A["id"], wallet=500.0)
    C = _mk_user("C", B["id"], wallet=500.0)
    D = _mk_user("D", C["id"], wallet=0.0)
    mongo_db.users.insert_many([A, B, C, D])

    ts = "2026-01-01T00:00:00"

    # D's registration_inflow (paid)
    reg_inflow_id = str(uuid.uuid4())
    mongo_db.transactions.insert_one({
        "id": reg_inflow_id,
        "user_id": D["id"],
        "type": "registration_inflow",
        "amount": REGISTRATION_FEE,
        "status": "paid",
        "description": f"{TEST_TAG}_D_reg_inflow",
        "created_at": ts,
    })

    # Referral payouts triggered by D's signup
    payouts: List[str] = []
    for recipient, level in [(C, 1), (B, 2), (A, 3)]:
        pid = str(uuid.uuid4())
        mongo_db.transactions.insert_one({
            "id": pid,
            "user_id": recipient["id"],
            "type": "referral_payout",
            "level": level,
            "amount": NET_PAYOUT,
            "gross_amount": GROSS_PAYOUT,
            "platform_fee_amount": PLATFORM_FEE,
            "platform_fee_pct": 18,
            "status": "success",
            "description": f"{TEST_TAG}_L{level}_payout",
            "source_user_name": f"{TEST_TAG}_D",
            "related_signup_id": D["id"],
            "related_payout_recipient": recipient["id"],
            "created_at": ts,
        })
        payouts.append(pid)

    return {"A": A, "B": B, "C": C, "D": D, "admin_id": admin_doc["id"], "payout_ids": payouts}


# ---------------------------------------------------------------- tests

class TestGroup8NetWorthShape:
    """1. GET /api/admin/finance/net-worth — verify group_8_refunds keys."""

    def test_net_worth_contains_group_8(self, base_url, api, admin_token):
        r = api.get(f"{base_url}/api/admin/finance/net-worth", headers=auth_headers(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "group_8_refunds" in body, "group_8_refunds object missing"
        g8 = body["group_8_refunds"]
        for k in ("total", "count", "clawback_total", "platform_fee_reversed",
                  "outstanding_debt", "outstanding_debt_users"):
            assert k in g8, f"missing key: {k}"
        for k in ("total", "clawback_total", "platform_fee_reversed", "outstanding_debt"):
            assert isinstance(g8[k], (int, float)), f"{k} should be numeric"


class TestExpenseCategoriesRemovedRefunds:
    """2. GET /api/admin/expenses/categories — 'refunds' must not be in defaults."""

    def test_refunds_removed_from_default_categories(self, base_url, api, admin_token):
        r = api.get(f"{base_url}/api/admin/expenses/categories", headers=auth_headers(admin_token))
        assert r.status_code == 200, r.text
        items = r.json().get("items") or []
        default_slugs = [c["slug"] for c in items if c.get("default")]
        assert "refunds" not in default_slugs, f"'refunds' still in defaults: {default_slugs}"
        # Both neighbours should still be present
        assert "payment_gateway" in default_slugs
        assert "gst_paid" in default_slugs


class TestRefundSearch:
    """3. GET /api/admin/refunds/search."""

    def test_search_finds_seeded_user(self, base_url, api, admin_token, seed_chain):
        D = seed_chain["D"]
        r = api.get(
            f"{base_url}/api/admin/refunds/search",
            params={"q": D["name"][:18]},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        items = r.json().get("items") or []
        ids = [u["id"] for u in items]
        assert D["id"] in ids, "D should be found by name search"
        # Excludes admins — admin email substring should not return admin
        rad = api.get(
            f"{base_url}/api/admin/refunds/search",
            params={"q": "networkrupay"},
            headers=auth_headers(admin_token),
        )
        assert rad.status_code == 200
        for u in rad.json().get("items") or []:
            assert "admin" not in (u.get("email") or "").lower() or u.get("id") != seed_chain["admin_id"]

    def test_search_by_referral_id(self, base_url, api, admin_token, seed_chain):
        D = seed_chain["D"]
        r = api.get(
            f"{base_url}/api/admin/refunds/search",
            params={"q": D["referral_id"]},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200
        ids = [u["id"] for u in (r.json().get("items") or [])]
        assert D["id"] in ids


class TestRefundPreview:
    """4. GET /api/admin/refunds/preview/{user_id}."""

    def test_preview_net_only(self, base_url, api, admin_token, seed_chain):
        D = seed_chain["D"]
        r = api.get(
            f"{base_url}/api/admin/refunds/preview/{D['id']}",
            params={"gst_refund": "false"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["gross_paid"] == REGISTRATION_FEE
        gb = body["gst_breakdown"]
        assert gb["gross"] == REGISTRATION_FEE
        assert abs(gb["net"] + gb["gst"] - REGISTRATION_FEE) < 0.05
        # refund_amount must equal NET when gst_refund=false
        assert abs(body["refund_amount"] - gb["net"]) < 0.05, body
        rows = body["clawback"]["rows"]
        assert len(rows) == 3, f"expected 3 upline rows, got {len(rows)}"
        # Each amount should be the NET payout (328)
        for row in rows:
            assert row["amount"] == NET_PAYOUT
            # wallet_before − amount = wallet_after
            assert abs(row["wallet_after"] - (row["current_wallet"] - NET_PAYOUT)) < 0.01
        assert body["clawback"]["total"] == round(3 * NET_PAYOUT, 2)
        # All three uplines have wallet 500 → 500-328=172, none going negative
        assert body["clawback"]["going_negative_total"] == 0

    def test_preview_with_gst_refund(self, base_url, api, admin_token, seed_chain):
        D = seed_chain["D"]
        r = api.get(
            f"{base_url}/api/admin/refunds/preview/{D['id']}",
            params={"gst_refund": "true"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["refund_amount"] == REGISTRATION_FEE  # gross

    def test_preview_404_on_unknown_user(self, base_url, api, admin_token):
        r = api.get(
            f"{base_url}/api/admin/refunds/preview/no-such-user-xyz",
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 404


class TestRefundCreateValidation:
    """5a. POST /api/admin/refunds — validation paths."""

    def test_invalid_final_action(self, base_url, api, admin_token, seed_chain):
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={"target_user_id": seed_chain["D"]["id"], "final_action": "blow_up"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 400, r.text

    def test_unknown_user(self, base_url, api, admin_token):
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={"target_user_id": "ghost-user", "final_action": "soft_delete"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 404, r.text

    def test_unpaid_user(self, base_url, api, admin_token, mongo_db):
        # Create a brand new unpaid user
        unpaid = _mk_user("unpaid", None, registration_paid=False)
        mongo_db.users.insert_one(unpaid)
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={"target_user_id": unpaid["id"], "final_action": "soft_delete"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 400, r.text


class TestRefundFlowSoftDelete:
    """5b. POST /api/admin/refunds — full clawback cascade + soft_delete."""

    @pytest.fixture(scope="class")
    def refund_result(self, base_url, api, admin_token, seed_chain, mongo_db):
        D = seed_chain["D"]
        # Snapshot upline wallets before
        before = {u: mongo_db.users.find_one({"id": seed_chain[u]["id"]})["wallet_balance"]
                  for u in ("A", "B", "C")}
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={
                "target_user_id": D["id"],
                "gst_refund": False,
                "comments": f"{TEST_TAG}_refund_D",
                "final_action": "soft_delete",
            },
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        return {"resp": r.json(), "before": before}

    def test_clawback_amounts(self, refund_result, seed_chain, mongo_db):
        refund = refund_result["resp"]["refund"]
        assert refund["clawback_total"] == round(3 * NET_PAYOUT, 2)
        assert len(refund["clawback_rows"]) == 3
        # All three uplines should go from 500 → 172 (500-328), none negative
        for u in ("A", "B", "C"):
            fresh = mongo_db.users.find_one({"id": seed_chain[u]["id"]})
            assert abs(fresh["wallet_balance"] - (refund_result["before"][u] - NET_PAYOUT)) < 0.01, \
                f"{u} wallet expected {refund_result['before'][u] - NET_PAYOUT}, got {fresh['wallet_balance']}"
            # No debt because wallets stayed positive
            assert (fresh.get("refund_debt") or 0) == 0

    def test_clawback_txns_created(self, refund_result, seed_chain, mongo_db):
        refund_id = refund_result["resp"]["refund"]["id"]
        for u in ("A", "B", "C"):
            txn = mongo_db.transactions.find_one({
                "user_id": seed_chain[u]["id"],
                "type": "refund_clawback",
                "related_refund_id": refund_id,
            })
            assert txn, f"clawback txn missing for {u}"
            assert txn["amount"] == -NET_PAYOUT
            assert txn["status"] == "success"

    def test_original_payouts_marked_reversed(self, refund_result, seed_chain, mongo_db):
        for pid in seed_chain["payout_ids"]:
            t = mongo_db.transactions.find_one({"id": pid})
            assert t["status"] == "reversed"
            assert t.get("reversed_by")
            assert t.get("reversed_at")

    def test_bank_ledger_debit(self, refund_result, mongo_db):
        refund = refund_result["resp"]["refund"]
        bl = mongo_db.bank_ledger.find_one({"id": refund["bank_ledger_id"]})
        assert bl, "bank_ledger entry missing"
        assert bl["kind"] == "debit"
        assert bl["purpose"] == "refund"
        # Refund is NET only (gst_refund=False)
        assert abs(bl["amount"] - refund["refund_amount"]) < 0.01
        assert bl["related_refund_id"] == refund["id"]

    def test_registration_inflow_marked_refunded(self, refund_result, seed_chain, mongo_db):
        D = seed_chain["D"]
        reg = mongo_db.transactions.find_one({
            "user_id": D["id"], "type": "registration_inflow",
        })
        assert reg.get("refunded") is True
        assert reg.get("related_refund_id") == refund_result["resp"]["refund"]["id"]

    def test_admin_revenue_reversal_created(self, refund_result, seed_chain, mongo_db):
        refund_id = refund_result["resp"]["refund"]["id"]
        rev = mongo_db.transactions.find_one({
            "type": "refund_revenue_reversal",
            "related_refund_id": refund_id,
        })
        assert rev, "refund_revenue_reversal txn missing"
        assert rev["amount"] < 0
        assert rev["source_bucket"] == "direct_signup"

    def test_admin_funding_reversal_created_if_funding_existed(self, refund_result, mongo_db, seed_chain):
        # We didn't seed funding rows in this test, so just assert NO crash and
        # if any present they are negative-only on admin
        refund_id = refund_result["resp"]["refund"]["id"]
        rows = list(mongo_db.transactions.find({"type": "refund_funding_reversal", "related_refund_id": refund_id}))
        # Always positive amount per the code (abs(amt))
        for row in rows:
            assert row["amount"] >= 0

    def test_platform_fee_reversal_created(self, refund_result, seed_chain, mongo_db):
        refund_id = refund_result["resp"]["refund"]["id"]
        rows = list(mongo_db.transactions.find({"type": "platform_fee_reversal", "related_refund_id": refund_id}))
        # 3 payouts × ₹72 platform fee each → 3 reversal rows
        assert len(rows) == 3, f"expected 3 platform_fee_reversal rows, got {len(rows)}"
        for r in rows:
            assert r["amount"] == -PLATFORM_FEE

    def test_user_soft_deleted(self, refund_result, seed_chain, mongo_db):
        D = mongo_db.users.find_one({"id": seed_chain["D"]["id"]})
        assert D["status"] == "deleted_refund"
        assert D["is_blocked"] is True
        assert D["registration_paid"] is False
        assert D.get("refund_id") == refund_result["resp"]["refund"]["id"]

    def test_idempotency_409(self, refund_result, base_url, api, admin_token, seed_chain):
        # Second call must 409
        D = seed_chain["D"]
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={"target_user_id": D["id"], "final_action": "soft_delete"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 409, r.text


class TestRefundListAndDetail:
    """6. + 7.  GET /api/admin/refunds + GET /api/admin/refunds/{id}."""

    def test_list_includes_refund(self, base_url, api, admin_token, seed_chain):
        r = api.get(f"{base_url}/api/admin/refunds", headers=auth_headers(admin_token))
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "total_count" in body and "total_amount" in body
        ids = [i["id"] for i in body["items"]]
        # The previous class created a refund for D
        D = seed_chain["D"]
        target_refund = next((i for i in body["items"] if i.get("target_user_id") == D["id"]), None)
        assert target_refund, "Refund for D not in list"

    def test_detail_returns_refund(self, base_url, api, admin_token, seed_chain, mongo_db):
        # Look up the refund_id from Mongo
        D = seed_chain["D"]
        rd = mongo_db.refunds.find_one({"target_user_id": D["id"]}, {"_id": 0})
        assert rd
        r = api.get(f"{base_url}/api/admin/refunds/{rd['id']}", headers=auth_headers(admin_token))
        assert r.status_code == 200
        assert r.json()["id"] == rd["id"]

    def test_detail_404(self, base_url, api, admin_token):
        r = api.get(f"{base_url}/api/admin/refunds/no-such-id", headers=auth_headers(admin_token))
        assert r.status_code == 404


class TestGroup8Drilldown:
    """8. GET /api/admin/finance/groups/group_8_refunds/transactions."""

    def test_drilldown_returns_refund(self, base_url, api, admin_token, seed_chain, mongo_db):
        r = api.get(
            f"{base_url}/api/admin/finance/groups/group_8_refunds/transactions",
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "subtotal" in body
        D = seed_chain["D"]
        target_item = next((i for i in body["items"] if i.get("target_user_id") == D["id"]), None)
        assert target_item, "Refund row missing in Group 8 drilldown"
        # Amount must be negative refund_amount
        rd = mongo_db.refunds.find_one({"target_user_id": D["id"]})
        assert abs(target_item["amount"] - (-float(rd["refund_amount"]))) < 0.01


class TestRefundFlowRemoveReferral:
    """5c. POST /api/admin/refunds with final_action=remove_referral."""

    def test_remove_referral_reparents_downline(self, base_url, api, admin_token, mongo_db):
        # Build a fresh chain: AA → BB → CC; refund BB → CC should be re-parented to AA
        AA = _mk_user("AA", None, wallet=200)
        BB = _mk_user("BB", AA["id"], wallet=200)
        CC = _mk_user("CC", BB["id"], wallet=0)
        # Bump AA's direct_referrals_count manually
        AA["direct_referrals_count"] = 1
        mongo_db.users.insert_many([AA, BB, CC])
        # BB's registration_inflow
        mongo_db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": BB["id"],
            "type": "registration_inflow",
            "amount": REGISTRATION_FEE,
            "status": "paid",
            "description": f"{TEST_TAG}_BB_reg",
            "created_at": "2026-01-01T00:00:00",
        })
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={
                "target_user_id": BB["id"],
                "gst_refund": True,
                "comments": f"{TEST_TAG}_refund_BB",
                "final_action": "remove_referral",
            },
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        # BB.sponsor_id None, status=referral_removed
        bbf = mongo_db.users.find_one({"id": BB["id"]})
        assert bbf["sponsor_id"] is None
        assert bbf["status"] == "referral_removed"
        # CC.sponsor_id now AA.id (grandparent)
        ccf = mongo_db.users.find_one({"id": CC["id"]})
        assert ccf["sponsor_id"] == AA["id"], f"CC sponsor expected {AA['id']} got {ccf['sponsor_id']}"
        # AA.direct_referrals_count decremented by 1
        aaf = mongo_db.users.find_one({"id": AA["id"]})
        assert aaf["direct_referrals_count"] == 0
        # Refund amount must be GROSS (gst_refund=true)
        rj = r.json()["refund"]
        assert rj["refund_amount"] == REGISTRATION_FEE
        # GST reversal txn present
        gst_rev = mongo_db.transactions.find_one({
            "type": "refund_gst_reversal",
            "related_refund_id": rj["id"],
        })
        assert gst_rev, "refund_gst_reversal missing for gst_refund=true"
        assert gst_rev["amount"] < 0


class TestEmptyDownlineRefund:
    """Edge: refunding a user with NO downline payouts still creates bank-debit."""

    def test_no_downline_still_refunds(self, base_url, api, admin_token, mongo_db):
        solo = _mk_user("solo", None, wallet=0)
        mongo_db.users.insert_one(solo)
        mongo_db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": solo["id"],
            "type": "registration_inflow",
            "amount": REGISTRATION_FEE,
            "status": "paid",
            "description": f"{TEST_TAG}_solo_reg",
            "created_at": "2026-01-01T00:00:00",
        })
        r = api.post(
            f"{base_url}/api/admin/refunds",
            json={"target_user_id": solo["id"], "final_action": "soft_delete"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200
        rj = r.json()["refund"]
        assert rj["clawback_total"] == 0
        assert len(rj["clawback_rows"]) == 0
        # Bank ledger entry exists
        bl = mongo_db.bank_ledger.find_one({"id": rj["bank_ledger_id"]})
        assert bl and bl["kind"] == "debit"


class TestRefundDebtAbsorption:
    """9. _credit_payout — refund_debt absorption.

    Uses direct asyncio invocation since we need precise amounts.
    """

    def test_debt_absorbed_then_remainder_credited(self, mongo_db):
        from server import _credit_payout  # local import after sys.path setup

        # Recipient with refund_debt=100, wallet=0
        recipient = _mk_user("debtor", None, wallet=0, refund_debt=100.0)
        mongo_db.users.insert_one(recipient)

        async def run():
            # Step 1: gross 50/0.82 ≈ 60.98 to get NET≈50. To make math clean we
            # call with a `gross` that yields net 50: gross/1.0... wait, math:
            # gross × (1 - 0.18) = net  →  gross = net / 0.82
            # NET = gross - gst, gst = gross * 0.18  →  net = gross * 0.82
            # For NET=50: gross = 50 / 0.82 = 60.9756 — but float-rounded.
            # Simpler: pass gross so that resulting NET equals 50 after the
            # internal `gst = round(gross * 0.18, 2)` calc. We'll use
            # gross = 60.97 → gst = 10.97 → net = 50.00.
            await _credit_payout(
                sponsor_user=dict(recipient),
                amount=60.97,
                level=1,
                source_user_name=f"{TEST_TAG}_test_debt",
                signup_id=None,
            )
            # Refresh recipient
            fresh1 = mongo_db.users.find_one({"id": recipient["id"]})
            # Net should be 50.00; all 50 absorbed (debt was 100 → 50 remaining)
            assert fresh1["wallet_balance"] == 0, f"wallet expected 0 got {fresh1['wallet_balance']}"
            assert abs(fresh1["refund_debt"] - 50.0) < 0.01, fresh1["refund_debt"]

            # Step 2: NET=80 → gross=80/0.82=97.56 → gst=17.56 → net=80
            await _credit_payout(
                sponsor_user=dict(fresh1),
                amount=97.56,
                level=1,
                source_user_name=f"{TEST_TAG}_test_debt2",
                signup_id=None,
            )
            fresh2 = mongo_db.users.find_one({"id": recipient["id"]})
            # debt should drop from 50 → 0, wallet rises by 30 (80-50)
            assert abs(fresh2["refund_debt"]) < 0.01, fresh2["refund_debt"]
            assert abs(fresh2["wallet_balance"] - 30.0) < 0.05, fresh2["wallet_balance"]

            # refund_debt_collection txn exists with negative amount
            collections = list(mongo_db.transactions.find({
                "user_id": recipient["id"],
                "type": "refund_debt_collection",
            }))
            assert len(collections) >= 1
            for c in collections:
                assert c["amount"] < 0

        asyncio.run(run())
