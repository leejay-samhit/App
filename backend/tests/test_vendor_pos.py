"""
Backend tests for Slangcart Vendor Cloud-POS endpoints (SALES_BACKEND_SPEC.md).

Scope: validates all 22 vendor_pos.py endpoints
- Settings GET/PUT, invoice counter peek/consume, sales create/cancel/refund/list/get/invoice.html
- Bulk-import dedupe, dashboard / cash-summary / statement / analytics, customers CRUD
- Admin RO fan-out + global summary
- CRITICAL: tenant isolation, wallet untouched, atomic concurrent inventory, atomic rollback
"""
import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env", override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ALICE = {"email": "test_alice_73dc7f@test.com", "password": "Passw0rd!"}
BOB = {"email": "test_bob_d96d89@test.com", "password": "Passw0rd!"}
ADMIN = {"email": "support@networkrupay.com", "password": os.environ.get("ADMIN_PASSWORD", "")}


# ──────────────────── Fixtures ────────────────────

def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    j = r.json()
    return j["token"], j["user"]["id"]


@pytest.fixture(scope="module")
def alice():
    tok, uid = _login(ALICE)
    return {"token": tok, "id": uid, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def bob():
    tok, uid = _login(BOB)
    return {"token": tok, "id": uid, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def admin():
    tok, uid = _login(ADMIN)
    return {"token": tok, "id": uid, "h": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    return client[DB_NAME]


def _make_product(mongo, vendor_id, name, stock=10, price=100.0, cost=50.0):
    pid = f"TEST_pos_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": pid,
        "vendor_id": vendor_id,
        "name": name,
        "price": price,
        "cost_price": cost,
        "stock": stock,
        "created_at": "2026-06-30T00:00:00",
    }
    mongo.products.insert_one(doc)
    return pid


@pytest.fixture(scope="module")
def alice_product(mongo, alice):
    pid = _make_product(mongo, alice["id"], "TEST_Widget", stock=10)
    yield pid
    mongo.products.delete_one({"id": pid})


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after(mongo, alice, bob):
    yield
    # cleanup test-created sales/customers/products/settings/counters for both vendors
    for vid in (alice["id"], bob["id"]):
        mongo.offline_sales.delete_many({"vendor_id": vid})
        mongo.vendor_customers.delete_many({"vendor_id": vid})
        mongo.products.delete_many({"vendor_id": vid, "id": {"$regex": "^TEST_pos_"}})
        mongo.vendor_pos_settings.delete_many({"vendor_id": vid})
        mongo.vendor_invoice_counters.delete_many({"vendor_id": vid})


# ──────────────────── Auth required ────────────────────

class TestAuth:
    def test_settings_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/settings", timeout=20)
        assert r.status_code in (401, 403), r.text

    def test_create_sale_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", json={"items": []}, timeout=20)
        assert r.status_code in (401, 403)

    def test_admin_endpoint_requires_admin(self, alice):
        r = requests.get(f"{BASE_URL}/api/admin/pos/global-summary", headers=alice["h"], timeout=20)
        assert r.status_code == 403, r.text

    def test_admin_endpoint_no_token(self):
        r = requests.get(f"{BASE_URL}/api/admin/pos/global-summary", timeout=20)
        assert r.status_code in (401, 403)


# ──────────────────── Settings ────────────────────

class TestSettings:
    def test_settings_get_defaults(self, alice, mongo):
        # ensure clean state
        mongo.vendor_pos_settings.delete_one({"vendor_id": alice["id"]})
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/settings", headers=alice["h"], timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["invoice_prefix"] == "INV"
        assert d["invoice_pad"] == 4
        assert d["vendor_id"] == alice["id"]

    def test_settings_put_partial_preserves_others(self, alice):
        # First set business_name
        r = requests.put(f"{BASE_URL}/api/vendor/me/pos/settings", headers=alice["h"], json={"business_name": "Alice Mart"}, timeout=20)
        assert r.status_code == 200
        # Now change invoice_prefix only
        r = requests.put(f"{BASE_URL}/api/vendor/me/pos/settings", headers=alice["h"], json={"invoice_prefix": "SLG"}, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["invoice_prefix"] == "SLG"
        assert d["invoice_pad"] == 4
        assert d["business_name"] == "Alice Mart"

    def test_counter_prefix_mirror(self, alice, mongo):
        # After setting prefix to SLG, the counter doc should now have prefix=SLG
        counter = mongo.vendor_invoice_counters.find_one({"vendor_id": alice["id"]})
        assert counter is not None
        assert counter.get("prefix") == "SLG"

    def test_tenant_isolation_settings(self, alice, bob):
        # Bob's settings must NOT have Alice's business_name
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/settings", headers=bob["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["vendor_id"] == bob["id"]
        assert d.get("business_name", "") != "Alice Mart"
        assert d.get("invoice_prefix", "INV") in ("INV", "")  # bob defaults


# ──────────────────── Invoice counter ────────────────────

class TestInvoiceCounter:
    def test_peek_does_not_bump(self, alice, mongo):
        # Reset counter for deterministic numbering, keep prefix SLG from prior test
        mongo.vendor_invoice_counters.update_one(
                {"vendor_id": alice["id"]}, {"$set": {"last_number": 0}}, upsert=True
            )
        r1 = requests.post(f"{BASE_URL}/api/vendor/me/pos/invoice/peek", headers=alice["h"], timeout=20)
        r2 = requests.post(f"{BASE_URL}/api/vendor/me/pos/invoice/peek", headers=alice["h"], timeout=20)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["invoice_no"] == r2.json()["invoice_no"]

    def test_consume_bumps(self, alice, mongo):
        mongo.vendor_invoice_counters.update_one(
                {"vendor_id": alice["id"]}, {"$set": {"last_number": 0}}, upsert=True
            )
        a = requests.post(f"{BASE_URL}/api/vendor/me/pos/invoice/consume", headers=alice["h"], timeout=20).json()["invoice_no"]
        b = requests.post(f"{BASE_URL}/api/vendor/me/pos/invoice/consume", headers=alice["h"], timeout=20).json()["invoice_no"]
        # extract numeric suffix
        n_a = int(a.rsplit("-", 1)[-1])
        n_b = int(b.rsplit("-", 1)[-1])
        assert n_b == n_a + 1


# ──────────────────── Sales — happy path + wallet snapshot ────────────────────

class TestSales:
    def test_create_sale_happy(self, alice, mongo, alice_product):
        # snapshot wallet
        u_before = mongo.users.find_one({"id": alice["id"]}, {"_id": 0, "wallet_balance": 1})
        wallet_before = (u_before or {}).get("wallet_balance", 0)
        tx_before = mongo.transactions.count_documents({"user_id": alice["id"]})

        payload = {
            "items": [{"product_id": alice_product, "name": "TEST_Widget", "qty": 3, "price": 100.0, "gst_pct": 18.0}],
            "payments": [{"mode": "cash", "amount": 354.0}],
            "customer": {"kind": "named", "name": "Cust A", "phone": "9000000001"},
            "gst_inclusive": False,
            "round_off": True,
        }
        r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], json=payload, timeout=30)
        assert r.status_code == 200, r.text
        sale = r.json()
        assert sale["status"] == "completed"
        assert sale["invoice_no"].startswith("SLG-") or sale["invoice_no"].startswith("INV-")
        assert sale["totals"]["subtotal"] == 300.0
        assert sale["totals"]["gst_total"] == 54.0
        assert sale["totals"]["grand_total"] in (354.0, 354)
        # stock now 7
        prod = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})
        assert prod["stock"] == 7
        # wallet untouched
        u_after = mongo.users.find_one({"id": alice["id"]}, {"_id": 0, "wallet_balance": 1})
        wallet_after = (u_after or {}).get("wallet_balance", 0)
        assert wallet_after == wallet_before, f"wallet changed {wallet_before} -> {wallet_after}"
        tx_after = mongo.transactions.count_documents({"user_id": alice["id"]})
        assert tx_after == tx_before, "transactions row added by POS"
        # stash for later tests
        TestSales.sale_id = sale["id"]
        TestSales.invoice_no = sale["invoice_no"]

    def test_oversell_returns_409_no_stock_change(self, alice, mongo, alice_product):
        # current stock=7; ask for 99
        stock_before = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]
        payload = {
            "items": [{"product_id": alice_product, "name": "TEST_Widget", "qty": 99, "price": 100.0}],
            "payments": [],
            "customer": {"kind": "walkin", "name": "WI"},
        }
        r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], json=payload, timeout=30)
        assert r.status_code == 409, r.text
        d = r.json()["detail"]
        assert d["error"] == "stock_insufficient"
        assert isinstance(d["items"], list) and len(d["items"]) >= 1
        stock_after = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]
        assert stock_after == stock_before, f"stock changed despite 409: {stock_before} -> {stock_after}"

    def test_multi_line_one_overshoot_rolls_back(self, alice, mongo, alice_product):
        # Create a second product, then send [ok_qty, overshoot] — expect rollback of the OK one.
        p2 = _make_product(mongo, alice["id"], "TEST_W2", stock=10)
        try:
            p2_before = 10
            p1_before = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]
            payload = {
                "items": [
                    {"product_id": p2, "name": "TEST_W2", "qty": 2, "price": 50.0},
                    {"product_id": alice_product, "name": "TEST_Widget", "qty": 9999, "price": 100.0},
                ],
                "payments": [],
                "customer": {"kind": "walkin", "name": "WI"},
            }
            r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], json=payload, timeout=30)
            assert r.status_code == 409, r.text
            p2_after = mongo.products.find_one({"id": p2}, {"_id": 0, "stock": 1})["stock"]
            p1_after = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]
            assert p2_after == p2_before, f"good item not rolled back: {p2_before} -> {p2_after}"
            assert p1_after == p1_before
        finally:
            mongo.products.delete_one({"id": p2})

    def test_concurrent_oversell_prevented(self, alice, mongo):
        # Make a fresh product with stock=5
        pid = _make_product(mongo, alice["id"], "TEST_Race", stock=5)
        try:
            payload = {
                "items": [{"product_id": pid, "name": "TEST_Race", "qty": 4, "price": 10.0}],
                "payments": [],
                "customer": {"kind": "walkin", "name": "WI"},
            }
            from concurrent.futures import ThreadPoolExecutor
            def _hit():
                return requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], json=payload, timeout=30)
            with ThreadPoolExecutor(max_workers=2) as ex:
                fa = ex.submit(_hit)
                fb = ex.submit(_hit)
                ra, rb = fa.result(), fb.result()
            codes = sorted([ra.status_code, rb.status_code])
            assert codes == [200, 409], f"expected one 200 one 409, got {codes} | {ra.text[:200]} | {rb.text[:200]}"
            stock_final = mongo.products.find_one({"id": pid}, {"_id": 0, "stock": 1})["stock"]
            assert stock_final == 1, f"oversell or undersell — stock={stock_final}"
        finally:
            mongo.products.delete_one({"id": pid})
            mongo.offline_sales.delete_many({"vendor_id": alice["id"], "items.product_id": pid})

    def test_list_sales(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        assert any(s["id"] == TestSales.sale_id for s in d["items"])

    def test_list_filter_status(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales?status=completed", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        for s in r.json()["items"]:
            assert s["status"] == "completed"

    def test_list_filter_q(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales?q=Cust+A", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        assert any(s["customer"]["name"] == "Cust A" for s in r.json()["items"])

    def test_list_filter_payment_mode(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales?payment_mode=cash", headers=alice["h"], timeout=20)
        assert r.status_code == 200

    def test_get_sale_by_id(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales/{TestSales.sale_id}", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        assert r.json()["id"] == TestSales.sale_id

    def test_get_sale_tenant_isolation(self, bob):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales/{TestSales.sale_id}", headers=bob["h"], timeout=20)
        assert r.status_code == 404

    def test_invoice_html(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/sales/{TestSales.sale_id}/invoice.pdf", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        assert "Invoice" in r.text
        assert TestSales.invoice_no in r.text
        assert "Cust A" in r.text


# ──────────────────── Cancel / Refund ────────────────────

class TestCancelRefund:
    def test_cancel_restocks(self, alice, mongo, alice_product):
        # Create a fresh sale
        payload = {
            "items": [{"product_id": alice_product, "name": "TEST_Widget", "qty": 2, "price": 100.0}],
            "payments": [{"mode": "cash", "amount": 200.0}],
            "customer": {"kind": "walkin", "name": "WI"},
        }
        r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], json=payload, timeout=30)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        stock_after_sale = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]

        # wallet snapshot
        u_before = mongo.users.find_one({"id": alice["id"]}, {"_id": 0, "wallet_balance": 1}) or {}
        wb = u_before.get("wallet_balance", 0)

        r2 = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales/{sid}/cancel", headers=alice["h"], timeout=20)
        assert r2.status_code == 200
        assert r2.json()["status"] == "cancelled"
        stock_after_cancel = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]
        assert stock_after_cancel == stock_after_sale + 2

        # cancel again -> 409
        r3 = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales/{sid}/cancel", headers=alice["h"], timeout=20)
        assert r3.status_code == 409

        # wallet untouched
        u_after = mongo.users.find_one({"id": alice["id"]}, {"_id": 0, "wallet_balance": 1}) or {}
        assert u_after.get("wallet_balance", 0) == wb

    def test_refund_restocks(self, alice, mongo, alice_product):
        payload = {
            "items": [{"product_id": alice_product, "name": "TEST_Widget", "qty": 1, "price": 100.0}],
            "payments": [{"mode": "cash", "amount": 100.0}],
            "customer": {"kind": "walkin", "name": "WI"},
        }
        r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales", headers=alice["h"], json=payload, timeout=30)
        assert r.status_code == 200
        sid = r.json()["id"]
        stock_after_sale = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]

        u_before = mongo.users.find_one({"id": alice["id"]}, {"_id": 0, "wallet_balance": 1}) or {}
        wb = u_before.get("wallet_balance", 0)
        tx_before = mongo.transactions.count_documents({"user_id": alice["id"]})

        r2 = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales/{sid}/refund", headers=alice["h"], json={"reason": "damaged"}, timeout=20)
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "refunded"
        assert r2.json()["refund_reason"] == "damaged"
        stock_after_refund = mongo.products.find_one({"id": alice_product}, {"_id": 0, "stock": 1})["stock"]
        assert stock_after_refund == stock_after_sale + 1

        # refund again -> 409
        r3 = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales/{sid}/refund", headers=alice["h"], json={}, timeout=20)
        assert r3.status_code == 409

        # wallet untouched
        u_after = mongo.users.find_one({"id": alice["id"]}, {"_id": 0, "wallet_balance": 1}) or {}
        assert u_after.get("wallet_balance", 0) == wb
        tx_after = mongo.transactions.count_documents({"user_id": alice["id"]})
        assert tx_after == tx_before


# ──────────────────── Bulk import ────────────────────

class TestBulkImport:
    def test_bulk_import_then_dedupe(self, alice, mongo):
        pid = _make_product(mongo, alice["id"], "TEST_Bulk", stock=100)
        try:
            sales = [
                {
                    "id": f"local-{i}-{uuid.uuid4().hex[:6]}",
                    "items": [{"product_id": pid, "name": "TEST_Bulk", "qty": 1, "price": 50.0}],
                    "payments": [{"mode": "cash", "amount": 50.0}],
                    "customer": {"kind": "walkin", "name": f"WI{i}"},
                }
                for i in range(3)
            ]
            r = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales/bulk-import", headers=alice["h"], json={"sales": sales}, timeout=30)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["imported"] == 3, d
            assert len(d["id_map"]) == 3

            # Re-import same client_ids — should dedupe.
            r2 = requests.post(f"{BASE_URL}/api/vendor/me/pos/sales/bulk-import", headers=alice["h"], json={"sales": sales}, timeout=30)
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["imported"] == 0
            assert len(d2["skipped"]) == 3
            assert len(d2["id_map"]) == 3
        finally:
            mongo.products.delete_one({"id": pid})


# ──────────────────── Dashboard / KPIs ────────────────────

class TestDashboard:
    def test_dashboard(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/dashboard", headers=alice["h"], timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(d.keys()) >= {"today", "month"}
        for k in ("bills", "turnover", "gst", "profit", "items"):
            assert k in d["today"]
            assert k in d["month"]
        assert d["today"]["bills"] >= 1

    def test_cash_summary(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/cash-summary", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "by_mode" in d
        assert "opening_balance" in d
        assert "expected_close" in d

    def test_statement(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/statement", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        # running balance is monotonic non-decreasing
        prev = -1
        for it in d["items"]:
            assert it["running"] >= prev
            prev = it["running"]

    def test_analytics(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/analytics?days=7", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("days", "daily", "top_sold", "top_revenue", "top_gst", "least_sold"):
            assert k in d
        assert d["days"] == 7


# ──────────────────── Customers ────────────────────

class TestCustomers:
    def test_upsert_then_dedup(self, alice):
        phone = f"9{int(time.time()) % 1000000000:09d}"
        body = {"name": "TEST_CustU", "phone": phone}
        r = requests.post(f"{BASE_URL}/api/vendor/me/pos/customers", headers=alice["h"], json=body, timeout=20)
        assert r.status_code == 200, r.text
        c1 = r.json()
        cid = c1["id"]
        # Second upsert same phone
        r2 = requests.post(f"{BASE_URL}/api/vendor/me/pos/customers", headers=alice["h"], json={"name": "TEST_Updated", "phone": phone}, timeout=20)
        assert r2.status_code == 200
        c2 = r2.json()
        assert c2["id"] == cid  # same row
        assert c2["name"] == "TEST_Updated"
        TestCustomers.cid = cid
        TestCustomers.phone = phone

    def test_list_customers(self, alice):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/customers", headers=alice["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert any(c["id"] == TestCustomers.cid for c in d["items"])

    def test_get_customer_tenant_isolation(self, bob):
        r = requests.get(f"{BASE_URL}/api/vendor/me/pos/customers/{TestCustomers.cid}", headers=bob["h"], timeout=20)
        assert r.status_code == 404

    def test_patch_customer_partial(self, alice):
        r = requests.patch(f"{BASE_URL}/api/vendor/me/pos/customers/{TestCustomers.cid}", headers=alice["h"], json={"address": "TEST Addr"}, timeout=20)
        assert r.status_code == 200
        assert r.json()["address"] == "TEST Addr"
        assert r.json()["name"] == "TEST_Updated"


# ──────────────────── Admin RO ────────────────────

class TestAdminReadOnly:
    def test_admin_can_read_vendor_sales(self, admin, alice):
        r = requests.get(f"{BASE_URL}/api/admin/vendors/{alice['id']}/pos/sales", headers=admin["h"], timeout=20)
        assert r.status_code == 200, r.text
        assert "items" in r.json()

    def test_non_admin_blocked(self, alice, bob):
        r = requests.get(f"{BASE_URL}/api/admin/vendors/{alice['id']}/pos/sales", headers=bob["h"], timeout=20)
        assert r.status_code == 403

    def test_admin_dashboard(self, admin, alice):
        r = requests.get(f"{BASE_URL}/api/admin/vendors/{alice['id']}/pos/dashboard", headers=admin["h"], timeout=20)
        assert r.status_code == 200
        assert "today" in r.json() and "month" in r.json()

    def test_global_summary(self, admin):
        r = requests.get(f"{BASE_URL}/api/admin/pos/global-summary", headers=admin["h"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "today" in d and "month" in d and "top_vendors_this_month" in d
