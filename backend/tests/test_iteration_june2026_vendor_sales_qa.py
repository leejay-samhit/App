"""Iteration June-2026 — backend regression for the four backend changes:

- Issue #3: POST /api/products/{pid}/questions now creates a chat_thread +
  chat_message mirror between the asker and the vendor. Response includes
  `thread_id`.
- Issue #6/#7: GET /api/vendor/me/sales groups line-items by order_id and
  supports ?status=placed|shipped|delivered|cancelled|all. Returns the
  buyer, shipping address, paid_via, total.
- Issue #6: PATCH /api/vendor/orders/{order_id}/status — vendor updates
  the status of their own order (delegates to admin handler). 403 if not
  owned; 400 for invalid status.
- Issue #10: GET /api/shop-categories returns admin-managed shop
  categories.

These tests self-seed a fresh vendor user, a fresh buyer user, a product,
an order, and vendor_sales rows directly in Mongo so we don't depend on
the checkout flow. Everything is prefixed TEST_I26J_ for later cleanup.
"""

from __future__ import annotations

import os
import uuid
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import requests
from dotenv import load_dotenv

# Load env from /app/backend/.env
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_frontend_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _frontend_env.exists():
    load_dotenv(_frontend_env, override=False)

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "http://localhost:8001").rstrip("/")
if BASE_URL.endswith("/api"):
    BASE_URL = BASE_URL[:-4]

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TAG = f"TEST_I26J_{uuid.uuid4().hex[:8]}"

# --------------------------------------------------------------------
# Async DB helper — small motor client, session-scoped
# --------------------------------------------------------------------
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except Exception:  # pragma: no cover
    pytest.skip("motor not installed", allow_module_level=True)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def db():
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


def _auth(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --------------------------------------------------------------------
# Fixtures: seed vendor + buyer + product + order + vendor_sales
# --------------------------------------------------------------------
@pytest.fixture(scope="module")
def seeded(db):
    """Register vendor + buyer through /auth/register (so passwords are
    hashed by the app), then promote vendor directly in Mongo, and seed
    an order + 3 vendor_sales line-items so /vendor/me/sales can group."""
    vendor_email = f"{TAG.lower()}_vendor@test.com"
    buyer_email = f"{TAG.lower()}_buyer@test.com"
    password = "Passw0rd!"

    def _register(email: str, name: str) -> str:
        r = requests.post(
            f"{BASE_URL}/api/auth/register",
            json={"email": email, "password": password, "name": name},
            timeout=15,
        )
        assert r.status_code in (200, 201), f"register {email}: {r.status_code} {r.text}"
        body = r.json()
        return body.get("token") or body.get("access_token") or body["user"]["id"]

    _register(vendor_email, f"{TAG} Vendor")
    _register(buyer_email, f"{TAG} Buyer")

    # Promote vendor in Mongo
    async def _promote():
        v = await db.users.find_one({"email": vendor_email})
        b = await db.users.find_one({"email": buyer_email})
        assert v and b, "seed users must exist"
        await db.users.update_one(
            {"id": v["id"]},
            {"$set": {
                "role": "vendor",
                "is_vendor": True,
                "vendor_status": "approved",
                "approval_status": "approved",
                "registration_paid": True,
            }},
        )
        await db.users.update_one(
            {"id": b["id"]},
            {"$set": {"approval_status": "approved", "registration_paid": True}},
        )
        # Seed one product owned by the vendor
        product_id = str(uuid.uuid4())
        await db.products.insert_one({
            "id": product_id,
            "name": f"{TAG} Widget",
            "price": 250,
            "vendor_id": v["id"],
            "image_url": "",
            "images": [],
            "status": "published",
            "created_at": "2026-06-01T00:00:00Z",
        })
        # Seed an order with 3 line items → 3 vendor_sales for same order
        order_id = str(uuid.uuid4())
        addr = {"name": f"{TAG} Buyer", "phone": "9999999999",
                "line1": "1 Test", "line2": "", "city": "TestCity",
                "state": "TS", "pincode": "560001"}
        await db.orders.insert_one({
            "id": order_id,
            "user_id": b["id"],
            "status": "placed",
            "paid_via": "wallet",
            "shipping_address": addr,
            "items": [
                {"product_id": product_id, "name": f"{TAG} Widget",
                 "vendor_id": v["id"], "vendor_share": 175.0,
                 "platform_share": 75.0, "qty": 1, "line_total": 250.0}
            ] * 3,
            "created_at": "2026-06-10T00:00:00Z",
        })
        for i in range(3):
            await db.vendor_sales.insert_one({
                "id": str(uuid.uuid4()),
                "vendor_id": v["id"],
                "order_id": order_id,
                "buyer_id": b["id"],
                "buyer_email": buyer_email,
                "product_id": product_id,
                "product_name": f"{TAG} Widget #{i+1}",
                "qty": 1,
                "line_total": 250.0,
                "vendor_share": 175.0,
                "platform_share": 75.0,
                "created_at": f"2026-06-10T00:00:0{i}Z",
            })
        # Seed a second order already-shipped so status filter can be tested
        shipped_id = str(uuid.uuid4())
        await db.orders.insert_one({
            "id": shipped_id,
            "user_id": b["id"],
            "status": "shipped",
            "paid_via": "cod",
            "shipping_address": addr,
            "items": [{"product_id": product_id, "vendor_id": v["id"],
                       "vendor_share": 175.0, "platform_share": 75.0,
                       "qty": 1, "line_total": 250.0}],
            "created_at": "2026-06-11T00:00:00Z",
        })
        await db.vendor_sales.insert_one({
            "id": str(uuid.uuid4()),
            "vendor_id": v["id"],
            "order_id": shipped_id,
            "buyer_id": b["id"],
            "buyer_email": buyer_email,
            "product_id": product_id,
            "product_name": f"{TAG} Widget shipped",
            "qty": 1,
            "line_total": 250.0,
            "vendor_share": 175.0,
            "platform_share": 75.0,
            "created_at": "2026-06-11T00:00:00Z",
        })
        return {
            "vendor_id": v["id"],
            "buyer_id": b["id"],
            "product_id": product_id,
            "order_placed_id": order_id,
            "order_shipped_id": shipped_id,
        }

    ids = _run(_promote())

    # Login both users (fresh tokens after Mongo mutation)
    def _login(email: str) -> str:
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": email, "password": password}, timeout=15)
        assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
        return r.json()["token"]

    vendor_token = _login(vendor_email)
    buyer_token = _login(buyer_email)

    yield {
        **ids,
        "vendor_email": vendor_email,
        "buyer_email": buyer_email,
        "vendor_token": vendor_token,
        "buyer_token": buyer_token,
    }

    # Teardown — drop everything we created
    async def _cleanup():
        await db.users.delete_many({"email": {"$regex": f"^{TAG.lower()}_"}})
        await db.products.delete_many({"name": {"$regex": f"^{TAG}"}})
        await db.orders.delete_many({"id": {"$in": [ids["order_placed_id"], ids["order_shipped_id"]]}})
        await db.vendor_sales.delete_many({"vendor_id": ids["vendor_id"]})
        await db.product_questions.delete_many({"vendor_id": ids["vendor_id"]})
        await db.chat_threads.delete_many({"participants": {"$all": [ids["vendor_id"], ids["buyer_id"]]}})
        await db.chat_messages.delete_many({"sender_id": {"$in": [ids["vendor_id"], ids["buyer_id"]]}})

    _run(_cleanup())


# ====================================================================
# 1) GET /api/vendor/me/sales
# ====================================================================
class TestVendorSales:
    def test_returns_grouped_shape(self, seeded):
        r = requests.get(f"{BASE_URL}/api/vendor/me/sales",
                         headers=_auth(seeded["vendor_token"]), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "total" in body
        assert isinstance(body["items"], list)
        # There must be exactly 2 grouped orders (placed + shipped)
        assert body["total"] == 2, f"expected 2 grouped orders got {body['total']}: {body}"
        placed = next(o for o in body["items"] if o["order_id"] == seeded["order_placed_id"])
        # 3 line-items grouped into ONE order card
        assert len(placed["items"]) == 3, placed
        # Fields present
        for k in ("id", "order_id", "items", "total", "status",
                  "buyer_name", "buyer_email", "shipping_address",
                  "paid_via", "created_at"):
            assert k in placed, f"missing key {k}"
        # Total = 3 x 250
        assert abs(float(placed["total"]) - 750.0) < 0.01
        assert placed["status"] == "placed"
        assert placed["paid_via"] == "wallet"
        assert placed["shipping_address"]["city"] == "TestCity"

    @pytest.mark.parametrize("status,expected_ids_key", [
        ("placed", "order_placed_id"),
        ("shipped", "order_shipped_id"),
    ])
    def test_status_filter(self, seeded, status, expected_ids_key):
        r = requests.get(
            f"{BASE_URL}/api/vendor/me/sales",
            params={"status": status},
            headers=_auth(seeded["vendor_token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["order_id"] == seeded[expected_ids_key]
        assert body["items"][0]["status"] == status

    def test_status_all_returns_both(self, seeded):
        r = requests.get(f"{BASE_URL}/api/vendor/me/sales",
                         params={"status": "all"},
                         headers=_auth(seeded["vendor_token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_status_delivered_empty(self, seeded):
        r = requests.get(f"{BASE_URL}/api/vendor/me/sales",
                         params={"status": "delivered"},
                         headers=_auth(seeded["vendor_token"]), timeout=15)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_requires_vendor_auth(self, seeded):
        r = requests.get(f"{BASE_URL}/api/vendor/me/sales",
                         headers=_auth(seeded["buyer_token"]), timeout=15)
        assert r.status_code == 403


# ====================================================================
# 2) PATCH /api/vendor/orders/{id}/status
# ====================================================================
class TestVendorOrderStatus:
    def test_update_success(self, seeded, db):
        r = requests.patch(
            f"{BASE_URL}/api/vendor/orders/{seeded['order_placed_id']}/status",
            json={"status": "shipped"},
            headers=_auth(seeded["vendor_token"]),
            timeout=20,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        # Verify persisted
        async def _fetch():
            return await db.orders.find_one({"id": seeded["order_placed_id"]}, {"_id": 0, "status": 1})
        row = _run(_fetch())
        assert row["status"] == "shipped"

    def test_invalid_status_400(self, seeded):
        r = requests.patch(
            f"{BASE_URL}/api/vendor/orders/{seeded['order_placed_id']}/status",
            json={"status": "banana"},
            headers=_auth(seeded["vendor_token"]),
            timeout=15,
        )
        assert r.status_code == 400, r.text

    def test_not_your_order_403(self, seeded):
        # Buyer isn't a vendor at all → require_vendor rejects first (403)
        r = requests.patch(
            f"{BASE_URL}/api/vendor/orders/{seeded['order_placed_id']}/status",
            json={"status": "shipped"},
            headers=_auth(seeded["buyer_token"]),
            timeout=15,
        )
        assert r.status_code == 403

    def test_foreign_order_403(self, seeded, db):
        """Second vendor should not be able to update the first vendor's order."""
        # Create a second vendor user + login, then try
        email2 = f"{TAG.lower()}_vendor2@test.com"
        password = "Passw0rd!"
        rr = requests.post(f"{BASE_URL}/api/auth/register",
                           json={"email": email2, "password": password, "name": f"{TAG} V2"},
                           timeout=15)
        assert rr.status_code in (200, 201), rr.text

        async def _promote2():
            u = await db.users.find_one({"email": email2})
            await db.users.update_one({"id": u["id"]}, {"$set": {
                "role": "vendor", "is_vendor": True, "vendor_status": "approved",
                "approval_status": "approved", "registration_paid": True,
            }})
        _run(_promote2())
        tok = requests.post(f"{BASE_URL}/api/auth/login",
                            json={"email": email2, "password": password}, timeout=15).json()["token"]
        r = requests.patch(
            f"{BASE_URL}/api/vendor/orders/{seeded['order_shipped_id']}/status",
            json={"status": "delivered"},
            headers=_auth(tok),
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 for foreign order, got {r.status_code}: {r.text}"


# ====================================================================
# 3) POST /api/products/{pid}/questions — mirror to chat_thread
# ====================================================================
class TestProductQuestionsChatMirror:
    def test_first_question_creates_thread_and_message(self, seeded, db):
        r = requests.post(
            f"{BASE_URL}/api/products/{seeded['product_id']}/questions",
            json={"text": "Is this available in blue?"},
            headers=_auth(seeded["buyer_token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "thread_id" in body, f"missing thread_id in {body}"
        thread_id = body["thread_id"]

        async def _verify():
            th = await db.chat_threads.find_one({"id": thread_id})
            msgs = await db.chat_messages.find({"thread_id": thread_id}).to_list(50)
            return th, msgs
        th, msgs = _run(_verify())
        assert th is not None, "chat_thread not created"
        # participants = sorted [buyer_id, vendor_id]
        assert th["participants"] == sorted([seeded["buyer_id"], seeded["vendor_id"]])
        assert th.get("kind") == "product_qa"
        assert th.get("product_ref", {}).get("id") == seeded["product_id"]
        # A chat_message must exist with the product prefix
        assert len(msgs) >= 1
        first = msgs[0]
        assert first["text"].startswith(f"[About: {TAG} Widget]"), first["text"]
        assert first["sender_id"] == seeded["buyer_id"]

    def test_second_question_reuses_same_thread(self, seeded, db):
        r = requests.post(
            f"{BASE_URL}/api/products/{seeded['product_id']}/questions",
            json={"text": "What is the warranty period?"},
            headers=_auth(seeded["buyer_token"]),
            timeout=15,
        )
        assert r.status_code == 200, r.text
        thread_id = r.json()["thread_id"]

        async def _count():
            n = await db.chat_threads.count_documents({
                "participants": sorted([seeded["buyer_id"], seeded["vendor_id"]])
            })
            msgs = await db.chat_messages.find({"thread_id": thread_id}).to_list(50)
            return n, msgs
        n, msgs = _run(_count())
        assert n == 1, f"expected exactly 1 thread for the pair, got {n}"
        # 2 messages now (one from previous test + one new)
        assert len(msgs) >= 2

    def test_product_not_found_404(self, seeded):
        r = requests.post(
            f"{BASE_URL}/api/products/nonexistent-xyz/questions",
            json={"text": "hello?"},
            headers=_auth(seeded["buyer_token"]),
            timeout=15,
        )
        assert r.status_code == 404


# ====================================================================
# 4) GET /api/shop-categories (public)
# ====================================================================
class TestShopCategories:
    """Issue #10 — verify the admin-managed categories endpoint works.

    Note: this DB has previously had all shop_categories deleted by the
    admin, and the one-time seed marker prevents auto-recreation. We
    therefore create a category via /admin/shop-categories and verify
    the public /shop-categories endpoint surfaces it, then clean up.
    """

    def test_public_endpoint_returns_admin_categories(self):
        # Login admin (support@networkrupay.com)
        admin_email = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
        admin_pw = os.environ.get("ADMIN_PASSWORD", "Nlee@1115")
        rl = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": admin_email, "password": admin_pw}, timeout=15)
        assert rl.status_code == 200, f"admin login failed: {rl.status_code} {rl.text}"
        tok = rl.json()["token"]

        # Baseline empty allowed — but endpoint must still return 200 with list shape
        r0 = requests.get(f"{BASE_URL}/api/shop-categories", timeout=15)
        assert r0.status_code == 200, r0.text
        assert isinstance(r0.json().get("items"), list)

        # Create a temporary category as admin
        cname = f"{TAG}_Cat"
        rc = requests.post(
            f"{BASE_URL}/api/admin/shop-categories",
            json={"name": cname, "icon_pack": "feather", "icon_name": "shopping-bag",
                  "color": "#FCE7F3", "sort_order": 100, "active": True},
            headers=_auth(tok), timeout=15,
        )
        assert rc.status_code in (200, 201), rc.text
        cid = rc.json()["id"]

        try:
            r = requests.get(f"{BASE_URL}/api/shop-categories", timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "items" in body and isinstance(body["items"], list)
            names = [c["name"] for c in body["items"]]
            assert cname in names, f"created category not surfaced: {names}"
            our = next(c for c in body["items"] if c["name"] == cname)
            for k in ("id", "name", "slug", "icon_pack", "icon_name",
                      "color", "sort_order", "active"):
                assert k in our, f"missing key {k}"
            assert our["active"] is True
        finally:
            # Cleanup — delete the category
            requests.delete(f"{BASE_URL}/api/admin/shop-categories/{cid}",
                            headers=_auth(tok), timeout=15)
