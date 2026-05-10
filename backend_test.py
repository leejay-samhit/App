"""Phase A regression test: stock-aware checkout + interested tracker."""
import os
import sys
import time
import uuid
import json
from typing import Any, Dict, Optional

import requests
from pymongo import MongoClient

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "referral_ecom_db"

results = []

def log(name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}  {detail}")
    results.append({"name": name, "ok": ok, "detail": detail})


def req(method: str, path: str, token: Optional[str] = None, **kw):
    headers = kw.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, BASE + path, headers=headers, timeout=30, **kw)


def login(email: str, password: str) -> str:
    r = req("POST", "/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def main():
    # -------- D. SANITY --------
    print("\n========== D. SANITY ==========")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    log("D1 POST /auth/login admin", True, "got token")

    r = req("GET", "/branding")
    log("D2 GET /branding", r.status_code == 200, f"{r.status_code}")

    r = req("GET", "/admin/stats", token=admin_token)
    log("D3 GET /admin/stats", r.status_code == 200, f"{r.status_code}")

    r = req("GET", "/notifications/me", token=admin_token)
    log("D4 GET /notifications/me", r.status_code == 200, f"{r.status_code}")

    r = req("GET", "/admin/products", token=admin_token)
    log("D5 GET /admin/products", r.status_code == 200, f"{r.status_code}")
    admin_products = r.json() if r.status_code == 200 else []
    assert admin_products, "Need at least one product seeded for testing"

    # -------- A. PUBLIC PRODUCTS LIST --------
    print("\n========== A. PUBLIC PRODUCTS LIST ==========")
    r = req("GET", "/products")
    ok = r.status_code == 200 and isinstance(r.json(), list)
    log("A1 GET /products no auth -> 200 array", ok,
        f"status={r.status_code}, len={len(r.json()) if ok else 'NA'}")
    products = r.json() if ok else []
    assert products, "/products returned empty"
    p = products[0]
    required_keys = {"id", "name", "price", "stock", "is_in_stock", "interested_count"}
    missing = required_keys - set(p.keys())
    log("A2 each product has required keys (id,name,price,stock,is_in_stock,interested_count)",
        not missing, f"missing={missing} sample_keys={list(p.keys())[:15]}")
    leaks = [pp for pp in products if "interested_users" in pp]
    log("A3 raw 'interested_users' NOT in response (privacy)",
        not leaks, f"leaked in {len(leaks)} products" if leaks else "")

    # -------- B. STOCK-AWARE CHECKOUT --------
    print("\n========== B. STOCK-AWARE CHECKOUT ==========")
    suffix = uuid.uuid4().hex[:8]
    test_email = f"stocktest_{suffix}@example.com"
    reg_payload = {
        "name": f"Stock Tester {suffix}",
        "email": test_email,
        "password": "StockTest@123",
        "phone": f"9{int(time.time()) % 1000000000:09d}",
    }
    r = req("POST", "/auth/register", json=reg_payload)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    reg = r.json()
    user_token = reg["token"]
    user_id = reg["user"]["id"]
    log("B1 POST /auth/register fresh user", True, f"id={user_id[:8]}")

    # Approve user
    r = req("POST", f"/admin/approvals/{user_id}/approve", token=admin_token)
    log("B2 admin approve user", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Set wallet directly via Mongo
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    db.users.update_one({"id": user_id}, {"$set": {
        "wallet_balance": 50000.0,
        "subscription_active": True,
        "approval_status": "approved",
        "registration_paid": True,
    }})
    fresh = db.users.find_one({"id": user_id})
    log("B3 set wallet_balance=50000 via Mongo",
        float(fresh.get("wallet_balance", 0)) == 50000.0,
        f"wallet={fresh.get('wallet_balance')}")

    # Pick first product
    target_product = admin_products[0]
    pid = target_product["id"]
    pname = target_product["name"]
    original_stock = int(target_product.get("stock") or 0)

    # Set stock to 3
    r = req("PATCH", f"/admin/products/{pid}", token=admin_token, json={"stock": 3})
    log("B4 PATCH product stock=3", r.status_code == 200 and r.json().get("stock") == 3,
        f"{r.status_code}")

    # Clear cart & add qty=5
    req("POST", "/cart/clear", token=user_token)
    r = req("POST", "/cart/add", token=user_token, json={"product_id": pid, "qty": 5})
    log("B5 POST /cart/add qty=5", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Checkout - expect 400 with friendly message
    r = req("POST", "/orders/checkout", token=user_token)
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    msg_ok = (
        r.status_code == 400
        and "out of stock" in detail
        and "only 3 left" in detail
        and "you wanted 5" in detail
    )
    log("B6 checkout qty=5 vs stock=3 -> 400 friendly message",
        msg_ok, f"status={r.status_code} detail={detail!r}")

    # Confirm stock STILL 3 (rollback worked)
    r = req("GET", "/products")
    arr = r.json() if r.status_code == 200 else []
    found = next((x for x in arr if x["id"] == pid), None)
    log("B7 stock unchanged at 3 after failed checkout (rollback)",
        bool(found and found.get("stock") == 3),
        f"stock={found.get('stock') if found else 'N/A'}")

    # Reduce cart to qty=2
    r = req("POST", "/cart/remove", token=user_token, json={"product_id": pid})
    log("B8a /cart/remove", r.status_code == 200, f"{r.status_code}")
    r = req("POST", "/cart/add", token=user_token, json={"product_id": pid, "qty": 2})
    log("B8b /cart/add qty=2", r.status_code == 200, f"{r.status_code}")

    # Checkout - expect 200 with status="placed"
    r = req("POST", "/orders/checkout", token=user_token)
    body = {}
    try:
        body = r.json()
    except Exception:
        pass
    log("B9 checkout qty=2 -> 200 status=placed",
        r.status_code == 200 and body.get("status") == "placed",
        f"status={r.status_code} body_status={body.get('status')} body={str(body)[:300]}")

    # Confirm stock now 1
    r = req("GET", "/products")
    arr = r.json() if r.status_code == 200 else []
    found = next((x for x in arr if x["id"] == pid), None)
    log("B10 stock decremented to 1 (3-2)",
        bool(found and found.get("stock") == 1),
        f"stock={found.get('stock') if found else 'N/A'}")

    # Reset stock
    reset_to = original_stock if original_stock >= 50 else 50
    r = req("PATCH", f"/admin/products/{pid}", token=admin_token, json={"stock": reset_to})
    log("B11 reset stock", r.status_code == 200, f"reset to {reset_to}")

    # -------- C. INTERESTED ENDPOINT --------
    print("\n========== C. INTERESTED ENDPOINT ==========")
    suffix2 = uuid.uuid4().hex[:8]
    test_email2 = f"interest_{suffix2}@example.com"
    r = req("POST", "/auth/register", json={
        "name": f"Interest User {suffix2}",
        "email": test_email2,
        "password": "Interest@123",
        "phone": f"8{int(time.time()) % 1000000000:09d}",
    })
    assert r.status_code == 200, r.text
    interest_user = r.json()
    iu_token = interest_user["token"]
    iu_id = interest_user["user"]["id"]
    log("C0a register interest user", True, f"id={iu_id[:8]}")

    test_pid = pid

    # Get current count
    r = req("GET", "/products")
    arr = r.json()
    found = next((x for x in arr if x["id"] == test_pid), None)
    base_count = int(found.get("interested_count") or 0) if found else 0
    log("C0b baseline interested_count", True, f"count={base_count}")

    # First registration
    r = req("POST", f"/products/{test_pid}/interested", token=iu_token)
    body = r.json() if r.status_code == 200 else {}
    log("C1 first /interested -> already_registered=false, count=base+1",
        r.status_code == 200
        and body.get("ok") is True
        and body.get("already_registered") is False
        and body.get("interested_count") == base_count + 1,
        f"status={r.status_code} body={body}")
    new_count = body.get("interested_count")

    # Re-register same user
    r = req("POST", f"/products/{test_pid}/interested", token=iu_token)
    body2 = r.json() if r.status_code == 200 else {}
    log("C2 second /interested same user -> already_registered=true, same count",
        r.status_code == 200
        and body2.get("already_registered") is True
        and body2.get("interested_count") == new_count,
        f"status={r.status_code} body={body2}")

    # Admin GET /interested
    r = req("GET", f"/products/{test_pid}/interested", token=admin_token)
    body3 = r.json() if r.status_code == 200 else {}
    has_user = any(u.get("id") == iu_id for u in body3.get("users", []))
    log("C3 admin GET /interested -> 200 with users list including test user",
        r.status_code == 200 and "interested_count" in body3 and has_user,
        f"status={r.status_code} count={body3.get('interested_count')} users_len={len(body3.get('users', []))} has_test_user={has_user}")

    # Customer (test user) GET /interested -> 403
    r = req("GET", f"/products/{test_pid}/interested", token=iu_token)
    log("C4 customer GET /interested -> 403",
        r.status_code == 403, f"status={r.status_code} body={r.text[:200]}")

    # -------- CLEANUP --------
    print("\n========== CLEANUP ==========")
    db.products.update_one({"id": test_pid}, {"$pull": {"interested_users": iu_id}})

    r = req("DELETE", f"/admin/users/{user_id}", token=admin_token)
    log("CLN delete stocktest user", r.status_code == 200, f"{r.status_code}")
    r = req("DELETE", f"/admin/users/{iu_id}", token=admin_token)
    log("CLN delete interest user", r.status_code == 200, f"{r.status_code}")

    # -------- SUMMARY --------
    print("\n========== SUMMARY ==========")
    passed = sum(1 for r in results if r["ok"])
    failed = sum(1 for r in results if not r["ok"])
    print(f"PASSED: {passed} / {len(results)}")
    print(f"FAILED: {failed}")
    if failed:
        print("\nFailures:")
        for r in results:
            if not r["ok"]:
                print(f"  - {r['name']}: {r['detail']}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
