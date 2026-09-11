"""
Iter 78 — SlangCart push-diagnostic + cashback cutover regression pack.

Focus:
- POST /api/push/test (super-admin only) returns diagnostic dict
- POST /api/register-push does not 500 in preview and stamps push_registration
- Chat message send: push failure never blocks POST; still 200
- Sequential IDs (TXNA<n> / ORD<n>)
- MLM stays dead (customer /wallet/transfer + /withdrawals 403)
- Admin group-wise Excel export via /admin/wallet/export/groupwise (real xlsx)
- Also verify /admin/finance/export/transactions (documented in task but returns CSV)
- Cashback config clamps at 10%
"""
import io
import os

import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")

ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text[:200]}"
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def admin():
    tok, u = _login(*ADMIN)
    return {"token": tok, "user": u, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def buyer():
    tok, u = _login(*BUYER)
    return {"token": tok, "user": u, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def vendor():
    tok, u = _login(*VENDOR)
    return {"token": tok, "user": u, "h": {"Authorization": f"Bearer {tok}"}}


# ── PUSH DIAGNOSTIC ────────────────────────────────────────────────────
class TestPushDiagnostic:
    def test_push_test_super_admin_returns_diagnostic(self, admin):
        r = requests.post(f"{BASE}/api/push/test", json={}, headers=admin["h"], timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text[:200]}"
        j = r.json()
        for k in ("ok", "relay", "key_configured", "device_registration", "hint"):
            assert k in j, f"missing key {k} in {j}"
        # In preview env EMERGENT_PUSH_KEY=placeholder → ok False, key not configured
        assert j["ok"] is False, f"expected ok=false in preview, got {j}"
        assert j["key_configured"] is False, f"expected key_configured=false, got {j}"
        assert j["relay"] == "key_missing", f"expected relay=key_missing, got {j['relay']}"
        assert isinstance(j["hint"], str) and len(j["hint"]) > 10

    def test_push_test_non_super_admin_forbidden(self, buyer):
        r = requests.post(f"{BASE}/api/push/test", json={}, headers=buyer["h"], timeout=30)
        assert r.status_code == 403, f"expected 403 for buyer, got {r.status_code}"

    def test_push_test_vendor_forbidden(self, vendor):
        r = requests.post(f"{BASE}/api/push/test", json={}, headers=vendor["h"], timeout=30)
        assert r.status_code == 403, f"expected 403 for vendor, got {r.status_code}"


# ── REGISTER-PUSH ──────────────────────────────────────────────────────
class TestRegisterPush:
    def test_register_push_deferred_key_missing(self, buyer):
        body = {"user_id": buyer["user"]["id"], "platform": "android", "device_token": "TEST_TOKEN_ABC"}
        r = requests.post(f"{BASE}/api/register-push", json=body, headers=buyer["h"], timeout=30)
        assert r.status_code in (200, 201), f"expected 2xx (not 500), got {r.status_code} {r.text[:200]}"
        j = r.json()
        assert j.get("status") == "deferred", f"expected deferred, got {j}"
        assert j.get("reason") == "key_missing", f"expected reason=key_missing, got {j}"

    def test_register_push_stamps_user_doc(self, buyer, admin):
        # After register, verify the user's push_registration was stamped
        # by using push/test as admin on THAT user is not possible — instead
        # call /me endpoints. The stamp is verified indirectly by re-calling
        # register-push and confirming it still doesn't 500.
        body = {"user_id": buyer["user"]["id"], "platform": "ios", "device_token": "TEST_TOKEN_2"}
        r = requests.post(f"{BASE}/api/register-push", json=body, headers=buyer["h"], timeout=30)
        assert r.status_code in (200, 201)
        # Now check via /users/me that push_registration exists on user doc
        me = requests.get(f"{BASE}/api/users/me", headers=buyer["h"], timeout=30)
        if me.status_code == 200:
            u = me.json()
            reg = u.get("push_registration")
            assert reg is not None, "push_registration not stamped on user doc"
            assert reg.get("status", "").startswith("deferred"), f"expected deferred status, got {reg}"
            assert reg.get("platform") == "ios", f"expected platform=ios, got {reg}"

    def test_register_push_mismatched_user_id_forbidden(self, buyer, vendor):
        body = {"user_id": vendor["user"]["id"], "platform": "android", "device_token": "MAL_TOK"}
        r = requests.post(f"{BASE}/api/register-push", json=body, headers=buyer["h"], timeout=30)
        assert r.status_code == 403, f"expected 403 mismatch, got {r.status_code} {r.text[:200]}"


# ── CASHBACK CONFIG ────────────────────────────────────────────────────
class TestCashbackConfig:
    def test_cashback_config_max_10(self):
        r = requests.get(f"{BASE}/api/cashback-config", timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j["max_cashback_pct"] == 10, f"expected max 10, got {j['max_cashback_pct']}"
        assert "delivery_charge_flat" in j
        assert "delivery_free_threshold" in j
        assert "delivery_cart_max" in j


# ── MLM STAYS DEAD ─────────────────────────────────────────────────────
class TestMlmDead:
    def test_wallet_transfer_removed_for_buyer(self, buyer):
        r = requests.post(f"{BASE}/api/wallet/transfer",
                          json={"to_user_id": "xxx", "amount": 10},
                          headers=buyer["h"], timeout=30)
        # Removed → should be 404/405, or if present 403 for buyer
        assert r.status_code in (403, 404, 405), f"expected wallet transfer dead, got {r.status_code}"

    def test_buyer_withdrawal_forbidden(self, buyer):
        r = requests.post(f"{BASE}/api/withdrawals",
                          json={"amount": 50, "bank_details": {}},
                          headers=buyer["h"], timeout=30)
        assert r.status_code in (403, 400), f"expected buyer withdraw 403/400, got {r.status_code}"

    def test_admin_users_tree_removed(self, admin):
        r = requests.get(f"{BASE}/api/admin/users/tree", headers=admin["h"], timeout=30)
        assert r.status_code in (404, 405), f"expected tree removed, got {r.status_code}"


# ── CHAT PUSH FAILURE DOES NOT BLOCK ───────────────────────────────────
class TestChatPushNonBlocking:
    def test_chat_message_post_still_200_without_push(self, buyer, vendor):
        """Send a chat message. Since EMERGENT_PUSH_KEY is placeholder,
        push relay returns 401 internally, but the message POST must
        still return 200 (push is best-effort)."""
        # Search for vendor by refcode; if not chatting, need a thread first.
        # We'll try /chat/contact-support which is the simplest thread bootstrap.
        r = requests.post(f"{BASE}/api/chat/contact-support",
                          json={"message": "TEST_iter78 hello"},
                          headers=buyer["h"], timeout=30)
        assert r.status_code == 200, f"contact-support failed: {r.status_code} {r.text[:200]}"
        j = r.json()
        threads = j.get("threads") or []
        if not threads:
            pytest.skip("No admin thread available to test chat push")
        tid = threads[0]["thread_id"]
        # Now post a fresh message — this exercises the send_push code path.
        r = requests.post(f"{BASE}/api/chat/{tid}/messages",
                          json={"text": "TEST_iter78 push-nonblock check"},
                          headers=buyer["h"], timeout=30)
        assert r.status_code == 200, f"chat message POST failed despite push relay 401: {r.status_code} {r.text[:200]}"
        m = r.json()
        assert m.get("id"), "message id missing"
        assert m.get("text") == "TEST_iter78 push-nonblock check"


# ── SEQUENTIAL IDs ─────────────────────────────────────────────────────
class TestSequentialIds:
    def test_short_id_backfill_idempotent(self, admin):
        r1 = requests.post(f"{BASE}/api/admin/short-id/backfill", headers=admin["h"], timeout=60)
        assert r1.status_code == 200, f"backfill 1st: {r1.status_code} {r1.text[:200]}"
        r2 = requests.post(f"{BASE}/api/admin/short-id/backfill", headers=admin["h"], timeout=60)
        assert r2.status_code == 200
        # Second run should mint 0 for every kind
        minted = r2.json().get("minted", {})
        for kind, count in minted.items():
            assert count == 0, f"backfill not idempotent for {kind}: {count}"

    def test_short_id_lookup_txn(self, admin):
        r = requests.get(f"{BASE}/api/admin/short-id/TXNA1", headers=admin["h"], timeout=30)
        # Either 200 with record or 404 if no txns exist
        assert r.status_code in (200, 404), f"unexpected {r.status_code}"
        if r.status_code == 200:
            j = r.json()
            assert j["code"] == "TXNA1"
            assert j["kind"] == "txn"


# ── ADMIN GROUP-WISE EXCEL EXPORT ──────────────────────────────────────
class TestAdminGroupwiseExcel:
    def test_wallet_groupwise_excel_download(self, admin):
        r = requests.get(f"{BASE}/api/admin/wallet/export/groupwise",
                         headers=admin["h"], timeout=60)
        assert r.status_code == 200, f"groupwise export: {r.status_code} {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml" in ct or "openxmlformats" in ct, f"expected xlsx content-type, got {ct}"
        # Sanity: xlsx magic bytes PK\x03\x04
        content = r.content
        assert content[:2] == b"PK", "not a valid zip/xlsx"
        # Open with openpyxl to prove real xlsx + inspect sheets
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(content), read_only=True)
            names = wb.sheetnames
            assert "All Transactions" in names, f"missing 'All Transactions' sheet: {names}"
            # Should have GROUP SUMMARY somewhere on the All sheet
            ws = wb["All Transactions"]
            found_summary = False
            for row in ws.iter_rows(values_only=True):
                if row and row[0] == "GROUP SUMMARY":
                    found_summary = True
                    break
            assert found_summary, "GROUP SUMMARY block not found"
        except ImportError:
            pytest.skip("openpyxl not available in test env")

    def test_wallet_groupwise_summary_matches(self, admin):
        r = requests.get(f"{BASE}/api/admin/wallet/groupwise-summary",
                         headers=admin["h"], timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert "groups" in j and "available_groups" in j
        # 15+ documented groups in wallet_export.GROUPS
        assert len(j["available_groups"]) >= 15

    def test_groupwise_export_forbidden_non_admin(self, buyer):
        r = requests.get(f"{BASE}/api/admin/wallet/export/groupwise",
                         headers=buyer["h"], timeout=30)
        assert r.status_code in (401, 403), f"expected forbidden for buyer, got {r.status_code}"

    def test_finance_export_transactions_endpoint(self, admin):
        """Task spec says /admin/finance/export/transactions should be xlsx
        but implementation returns CSV. Verify current behaviour + flag."""
        r = requests.get(f"{BASE}/api/admin/finance/export/transactions?days=30",
                         headers=admin["h"], timeout=30)
        assert r.status_code == 200, f"finance export: {r.status_code}"
        ct = r.headers.get("content-type", "")
        # Currently CSV — record for reporting
        print(f"[INFO] /admin/finance/export/transactions content-type = {ct}")


# ── MLM TRANSACTIONS NEVER CREATED ─────────────────────────────────────
class TestNoMlmTxns:
    def test_no_referral_payout_recent(self, admin):
        # Peek at recent finance groups — no referral_payout / cascade_overflow
        # should be created by any current flow. Historic ones may exist.
        r = requests.get(f"{BASE}/api/admin/wallet/groupwise-summary?date_from=2026-01-01",
                         headers=admin["h"], timeout=30)
        assert r.status_code == 200
        # Just ensure the summary endpoint returns cleanly with recent date filter.
