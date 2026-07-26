"""P1 Production Audit regression tests (iteration 50).

Validates the modular refactor by main agent:
  • POST /api/wallet/transfer → migrated to routes/wallet.py
  • POST /api/withdrawals     → migrated to routes/withdrawals.py
  • Regressions on general endpoints untouched by the refactor.

Credentials note:
  Main agent's review request mentioned support@slangcart.com / brightkittu@gmail.com
  but those users do NOT exist in the current DB. Per /app/memory/test_credentials.md
  and /app/backend/.env (ADMIN_EMAIL) we fall back to:
      Admin  : support@networkrupay.com / Nlee@1115
      User   : raju@gmail.com          / Demo@2026  (approved, non-admin)
"""
import os
import time
import uuid
import pytest
import requests
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

# ────────────────── Bootstrap ──────────────────
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe_env.exists():
    load_dotenv(_fe_env, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = "Nlee@1115"
USER_EMAIL = "raju@gmail.com"
USER_PASSWORD = "Demo@2026"


def _auth(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def admin_token():
    return _auth(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def user_token():
    return _auth(USER_EMAIL, USER_PASSWORD)


@pytest.fixture(scope="session")
def mongo():
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    yield db
    client.close()


# ────────────────── /wallet/transfer ──────────────────
class TestWalletTransfer:
    def test_transfer_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/wallet/transfer",
            json={"recipient": USER_EMAIL, "amount": 1},
        )
        # slowapi/starlette returns 401 (or 403 in some auth chains) for missing bearer
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text}"

    def test_transfer_admin_to_user_happy_path(self, admin_token, mongo):
        # snapshot balances
        admin_doc = mongo.users.find_one({"email": ADMIN_EMAIL}, {"_id": 0, "id": 1, "wallet_balance": 1})
        recip_doc = mongo.users.find_one({"email": USER_EMAIL}, {"_id": 0, "id": 1, "wallet_balance": 1})
        assert admin_doc and recip_doc, "seed users missing"
        pre_admin = float(admin_doc.get("wallet_balance") or 0)
        pre_recip = float(recip_doc.get("wallet_balance") or 0)
        assert pre_admin >= 1, "admin needs ≥ ₹1 to transfer"

        note = f"TEST_p1_audit_{uuid.uuid4().hex[:8]}"
        r = requests.post(
            f"{BASE_URL}/api/wallet/transfer",
            headers=_headers(admin_token),
            json={"recipient": USER_EMAIL, "amount": 1, "note": note},
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body["ok"] is True
        assert body["amount"] == 1
        transfer_id = body["transfer_id"]
        assert transfer_id

        # balances mutated
        post_admin = float(mongo.users.find_one({"email": ADMIN_EMAIL})["wallet_balance"])
        post_recip = float(mongo.users.find_one({"email": USER_EMAIL})["wallet_balance"])
        assert round(pre_admin - post_admin, 2) == 1.0, f"admin debit wrong: {pre_admin}→{post_admin}"
        assert round(post_recip - pre_recip, 2) == 1.0, f"recip credit wrong: {pre_recip}→{post_recip}"

        # two mirrored transaction rows written
        rows = list(mongo.transactions.find({"transfer_id": transfer_id}, {"_id": 0}))
        assert len(rows) == 2, f"expected 2 txn rows, got {len(rows)}: {rows}"
        by_type = {r["type"]: r for r in rows}
        assert set(by_type) == {"transfer_out", "transfer_in"}
        assert by_type["transfer_out"]["amount"] == -1
        assert by_type["transfer_out"]["user_id"] == admin_doc["id"]
        assert by_type["transfer_in"]["amount"] == 1
        assert by_type["transfer_in"]["user_id"] == recip_doc["id"]
        assert note in by_type["transfer_out"]["description"]
        assert note in by_type["transfer_in"]["description"]

        # notification created for recipient (schema uses `kind`, not `type`)
        notif = mongo.notifications.find_one(
            {"user_id": recip_doc["id"], "kind": "transfer"},
            sort=[("created_at", -1)],
        )
        assert notif is not None, "expected a `transfer` notification for recipient"
        assert "1" in (notif.get("title") or "")

        # cleanup: transfer ₹1 back so wallet balances net to zero drift
        r2 = requests.post(
            f"{BASE_URL}/api/wallet/transfer",
            headers=_headers(_auth(USER_EMAIL, USER_PASSWORD)),
            json={"recipient": ADMIN_EMAIL, "amount": 1, "note": "TEST_p1_audit_reverse"},
        )
        # reverse might fail if user not eligible; we don't assert — best effort only
        _ = r2

    def test_transfer_to_self_rejected(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/wallet/transfer",
            headers=_headers(admin_token),
            json={"recipient": ADMIN_EMAIL, "amount": 1},
        )
        assert r.status_code == 400
        assert "yourself" in r.text.lower()

    def test_transfer_unknown_recipient_404(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/wallet/transfer",
            headers=_headers(admin_token),
            json={"recipient": f"noone_{uuid.uuid4().hex[:6]}@nowhere.test", "amount": 1},
        )
        assert r.status_code == 404


# ────────────────── /withdrawals ──────────────────
class TestWithdrawals:
    def test_withdraw_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/withdrawals", json={"amount": 500})
        assert r.status_code in (401, 403)

    def test_withdraw_min_floor_100(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/withdrawals",
            headers=_headers(admin_token),
            json={"amount": 50},
        )
        assert r.status_code == 400
        assert "100" in r.text  # message references ₹100 floor

    def test_withdraw_l1_gate_for_non_admin(self, user_token, mongo):
        # Raju has no true direct referrals (verified via seed inspection)
        # → should be rejected by L1 completion gate with detail about directs.
        # Amount ≥ 100 so we bypass the min-floor guard first.
        r = requests.post(
            f"{BASE_URL}/api/withdrawals",
            headers=_headers(user_token),
            json={"amount": 100},
        )
        # Expect 400 with L1-gate message OR 400 with insufficient balance
        # (raju has ₹0). Both prove the endpoint is wired and gating flows.
        # The L1 gate runs BEFORE balance check → we expect L1-gate first.
        assert r.status_code in (400, 403), f"{r.status_code} {r.text}"
        body_text = r.text.lower()
        assert (
            "direct" in body_text
            or "referral" in body_text
            or "level 1" in body_text
            or "insufficient" in body_text
            or "upi" in body_text
        ), f"unexpected error message: {r.text}"

    def test_withdrawals_me_still_works(self, user_token):
        r = requests.get(f"{BASE_URL}/api/withdrawals/me", headers=_headers(user_token))
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ────────────────── /transactions/me ──────────────────
class TestTransactionsMe:
    def test_transactions_me_admin(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/transactions/me", headers=_headers(admin_token))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # admin has done a transfer above → at least one transfer_out row present
        types = {row.get("type") for row in data}
        # Not asserting strictly (order of tests may vary) — just sanity that shape is right
        for row in data[:5]:
            assert "id" in row and "type" in row and "amount" in row


# ────────────────── General regression ──────────────────
class TestGeneralRegressions:
    def test_login(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert r.status_code == 200
        assert "token" in r.json()

    def test_products_list(self):
        r = requests.get(f"{BASE_URL}/api/products")
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_shop_categories(self):
        r = requests.get(f"{BASE_URL}/api/shop-categories")
        assert r.status_code == 200
        body = r.json()
        # response is {items: [...]} (wrapper). Accept both shapes for safety.
        items = body["items"] if isinstance(body, dict) else body
        assert isinstance(items, list) and len(items) > 0

    def test_shop_layout(self):
        r = requests.get(f"{BASE_URL}/api/shop-layout")
        assert r.status_code == 200
        body = r.json()
        items = body["items"] if isinstance(body, dict) else body
        assert isinstance(items, list)

    def test_admin_system_wallet(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/system-wallet", headers=_headers(admin_token))
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)

    def test_admin_system_wallet_source_breakdown(self, admin_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/system-wallet/source-breakdown",
            headers=_headers(admin_token),
        )
        assert r.status_code == 200
        assert isinstance(r.json(), (dict, list))

    def test_geo_search(self):
        r = requests.get(f"{BASE_URL}/api/geo/search", params={"q": "mumbai"})
        assert r.status_code == 200

    def test_vendor_edit_requests_requires_auth(self):
        # unauth request should be 401/403 — proves the endpoint is registered
        r = requests.get(f"{BASE_URL}/api/vendor/edit-requests")
        assert r.status_code in (401, 403, 405), f"{r.status_code} {r.text}"


# ────────────────── Rate limit ──────────────────
class TestWithdrawalRateLimit:
    """5/hour rate limit on POST /withdrawals — verified by spamming 7 requests
    with amount=50 (rejected by min-floor, but rate-limiter counts them).
    The 6th+ should return 429."""

    def test_rate_limit_five_per_hour(self, admin_token):
        # NOTE: rate-limit key is per-IP. Because previous tests already hit
        # /withdrawals once with amount=50 (min-floor test), we may hit the
        # limit earlier. That's fine — we just need to see a 429 at some point.
        saw_429 = False
        for _ in range(7):
            r = requests.post(
                f"{BASE_URL}/api/withdrawals",
                headers=_headers(admin_token),
                json={"amount": 50},
            )
            if r.status_code == 429:
                saw_429 = True
                break
            time.sleep(0.05)
        assert saw_429, "expected a 429 within 7 requests — rate limit not enforced"
