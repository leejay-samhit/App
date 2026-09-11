#!/usr/bin/env python3
"""
Vendor Panel — backend tests.
Tests against https://slangcart-tracking.preview.emergentagent.com/api
"""
import os, sys, json, time, uuid, random, string
import requests

BASE = "https://slangcart-tracking.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"

RUN = "vnd" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

PASSED = 0
FAILED = 0
FAILURES = []


def log(msg):
    print(msg, flush=True)


def check(cond, desc):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        log(f"  PASS: {desc}")
    else:
        FAILED += 1
        FAILURES.append(desc)
        log(f"  FAIL: {desc}")


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"login {email} failed {r.status_code}: {r.text}")
    return r.json()["token"], r.json()["user"]


def register(name, email, password, referral_code=None):
    body = {"name": name, "email": email, "password": password}
    if referral_code:
        body["referral_code"] = referral_code
    r = requests.post(f"{BASE}/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"register {email} failed {r.status_code}: {r.text}")
    return r.json()["token"], r.json()["user"]


def me(tok):
    r = requests.get(f"{BASE}/auth/me", headers=hdr(tok), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"me failed {r.status_code}: {r.text}")
    return r.json()


def admin_approve_user(admin_tok, uid):
    r = requests.post(f"{BASE}/admin/approvals/{uid}/approve", headers=hdr(admin_tok), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"admin approve user {uid} failed {r.status_code}: {r.text}")
    return r.json()


def admin_credit_wallet(admin_tok, uid, amount, reason="topup"):
    r = requests.post(
        f"{BASE}/admin/users/{uid}/wallet",
        headers=hdr(admin_tok),
        json={"amount": amount, "type": "credit", "reason": reason},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"wallet credit {uid} failed {r.status_code}: {r.text}")
    return r.json()


def main():
    global PASSED, FAILED
    cleanup_user_ids = []
    cleanup_product_ids = []  # not strictly needed (cascade on user delete? products won't cascade). We'll delete via admin endpoints.

    log(f"=== VENDOR PANEL TEST RUN {RUN} ===")
    log(f"BASE={BASE}")

    # === SETUP: admin login ===
    admin_tok, admin_u = login(ADMIN_EMAIL, ADMIN_PASS)
    check(bool(admin_tok), "Admin login admin@app.com / Admin@123 -> 200")

    # === 1. APPLY GUARDS ===
    log("\n=== 1. APPLY GUARDS ===")
    u1_email = f"u1.{RUN}@example.com"
    u1_tok, u1 = register("Aarav Vendor One", u1_email, "Test@123")
    cleanup_user_ids.append(u1["id"])
    check(bool(u1_tok), "Register U1")

    # 1a. Not paid -> 403 "Complete registration"
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u1_tok), json={"shop_name": "Tester Store"}, timeout=30)
    check(r.status_code == 403 and "Complete registration" in (r.json().get("detail") or ""),
          f"vendor/apply (unpaid) -> 403 'Complete registration' (got {r.status_code} {r.text[:120]})")

    # 1b. Pay registration -> still pending approval -> 403 "must be approved"
    r = requests.post(f"{BASE}/payment/register-fee", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"U1 /payment/register-fee -> 200 (got {r.status_code} {r.text[:120]})")
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u1_tok), json={"shop_name": "Tester Store"}, timeout=30)
    check(r.status_code == 403 and "must be approved" in (r.json().get("detail") or "").lower(),
          f"vendor/apply (paid, not approved) -> 403 'must be approved' (got {r.status_code} {r.text[:120]})")

    # 1c. Admin approves U1
    admin_approve_user(admin_tok, u1["id"])
    check(True, f"Admin approves U1")

    # 1d. valid apply -> 200
    apply_payload = {
        "shop_name": "Tester Store",
        "gst_number": "GST123456789012",
        "pan_number": "ABCDE1234F",
        "bank_name": "Test Bank",
        "bank_account": "1234567890",
        "bank_ifsc": "TEST0001234",
        "description": "Test vendor shop",
    }
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u1_tok), json=apply_payload, timeout=30)
    check(r.status_code == 200 and r.json().get("ok") and r.json().get("application", {}).get("status") == "pending",
          f"U1 vendor/apply -> 200 application created pending (got {r.status_code} {r.text[:200]})")
    if r.status_code == 200:
        u1_app_id = r.json()["application"]["id"]
    else:
        u1_app_id = None

    # Verify user.vendor_status=pending
    u1_me = me(u1_tok)
    check(u1_me.get("vendor_status") == "pending",
          f"U1 user.vendor_status == 'pending' after apply (got {u1_me.get('vendor_status')})")

    # 1e. Re-apply -> 400 already active
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u1_tok), json=apply_payload, timeout=30)
    check(r.status_code == 400 and "already" in (r.json().get("detail") or "").lower(),
          f"U1 re-apply while pending -> 400 'already have an active application' (got {r.status_code} {r.text[:120]})")

    # 1f. Need a fresh user to test shop_name length validator (else we'd hit "already active")
    # But spec says shop_name='Hi' on U1 should return 400. The code checks length BEFORE existing-app check, so this works on U1 too.
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u1_tok), json={"shop_name": "Hi"}, timeout=30)
    check(r.status_code == 400 and "min" in (r.json().get("detail") or "").lower(),
          f"U1 shop_name='Hi' -> 400 (min 3 chars) (got {r.status_code} {r.text[:120]})")

    # === 2. ADMIN APPROVE ===
    log("\n=== 2. ADMIN APPROVE ===")
    r = requests.get(f"{BASE}/admin/vendor-applications?status=pending", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"admin GET /admin/vendor-applications?status=pending -> 200")
    if r.status_code == 200:
        body = r.json()
        items = body.get("items") or []
        ids = [a.get("id") for a in items]
        check(u1_app_id in ids, f"U1 app present in pending list (counts={body.get('counts')})")
        check((body.get("counts") or {}).get("pending", 0) >= 1, "counts.pending >= 1")

    # Approve the application
    r = requests.post(f"{BASE}/admin/vendor-applications/{u1_app_id}/approve", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200 and r.json().get("ok") and r.json()["application"]["status"] == "approved",
          f"admin approve vendor application -> 200 status='approved' (got {r.status_code} {r.text[:200]})")

    u1_me = me(u1_tok)
    check(u1_me.get("is_vendor") is True and u1_me.get("vendor_status") == "approved",
          f"U1 is_vendor=true, vendor_status='approved' (got is_vendor={u1_me.get('is_vendor')}, vs={u1_me.get('vendor_status')})")

    # Notification
    r = requests.get(f"{BASE}/notifications/me", headers=hdr(u1_tok), timeout=30)
    notes = r.json() if r.status_code == 200 else []
    has_approve_note = any(n.get("kind") == "vendor" and "approved" in (n.get("title") or "").lower() for n in notes)
    check(has_approve_note, f"U1 received vendor approval notification (titles={[n.get('title') for n in notes][:5]})")

    # /vendor/me/status
    r = requests.get(f"{BASE}/vendor/me/status", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200 and r.json().get("is_vendor") is True and r.json().get("vendor_status") == "approved",
          f"GET /vendor/me/status -> is_vendor:true, vendor_status:approved (got {r.status_code} {r.text[:200]})")

    # === 3. VENDOR PRODUCTS CRUD ===
    log("\n=== 3. VENDOR PRODUCTS CRUD ===")
    r = requests.get(f"{BASE}/vendor/me/products", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200 and isinstance(r.json(), list) and len(r.json()) == 0,
          f"GET /vendor/me/products as U1 (fresh) -> [] (got {r.status_code} {r.text[:120]})")

    prod_payload = {
        "name": "Test Lamp",
        "price": 500,
        "stock": 10,
        "image_url": "https://placehold.it/300",
        "description": "test",
        "is_published": True,
        "vendor_id": "FAKE_VENDOR_ID",  # must be ignored / overwritten
    }
    r = requests.post(f"{BASE}/vendor/me/products", headers=hdr(u1_tok), json=prod_payload, timeout=30)
    check(r.status_code == 200, f"POST /vendor/me/products -> 200 (got {r.status_code} {r.text[:200]})")
    p1_id = None
    if r.status_code == 200:
        body = r.json()
        p1_id = body.get("id")
        cleanup_product_ids.append(p1_id)
        check(body.get("vendor_id") == u1["id"],
              f"product.vendor_id force-stamped to U1.id (got {body.get('vendor_id')} vs U1.id={u1['id']})")
        check(body.get("vendor_email") == u1["email"],
              f"product.vendor_email == U1.email (got {body.get('vendor_email')})")

    # PATCH price
    r = requests.patch(f"{BASE}/vendor/me/products/{p1_id}", headers=hdr(u1_tok), json={"price": 600}, timeout=30)
    check(r.status_code == 200 and r.json().get("price") == 600,
          f"PATCH product price -> 200 price=600 (got {r.status_code} {r.text[:200]})")

    # Register U2 as another vendor; verify cannot PATCH/DELETE U1's product
    u2_email = f"u2.{RUN}@example.com"
    u2_tok, u2 = register("Bharath Vendor Two", u2_email, "Test@123")
    cleanup_user_ids.append(u2["id"])
    requests.post(f"{BASE}/payment/register-fee", headers=hdr(u2_tok), timeout=30)
    admin_approve_user(admin_tok, u2["id"])

    # apply + admin approve U2 as vendor
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u2_tok),
                      json={"shop_name": "U2 Store", "gst_number": "G2", "pan_number": "P2"}, timeout=30)
    check(r.status_code == 200, f"U2 vendor/apply -> 200 (got {r.status_code} {r.text[:200]})")
    u2_app_id = r.json()["application"]["id"] if r.status_code == 200 else None
    if u2_app_id:
        r = requests.post(f"{BASE}/admin/vendor-applications/{u2_app_id}/approve", headers=hdr(admin_tok), timeout=30)
        check(r.status_code == 200, f"admin approve U2 vendor app -> 200")

    # U2 attempts to PATCH U1's product
    r = requests.patch(f"{BASE}/vendor/me/products/{p1_id}", headers=hdr(u2_tok), json={"price": 999}, timeout=30)
    check(r.status_code == 403 and "Not your product" in (r.json().get("detail") or ""),
          f"U2 PATCH U1's product -> 403 'Not your product' (got {r.status_code} {r.text[:200]})")
    r = requests.delete(f"{BASE}/vendor/me/products/{p1_id}", headers=hdr(u2_tok), timeout=30)
    check(r.status_code == 403 and "Not your product" in (r.json().get("detail") or ""),
          f"U2 DELETE U1's product -> 403 'Not your product' (got {r.status_code} {r.text[:200]})")

    # U1 deletes own product
    r = requests.delete(f"{BASE}/vendor/me/products/{p1_id}", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200 and r.json().get("ok"),
          f"U1 DELETE own product -> 200 (got {r.status_code} {r.text[:120]})")
    if p1_id in cleanup_product_ids:
        cleanup_product_ids.remove(p1_id)

    # === 4. CHECKOUT COMMISSION SPLIT ===
    log("\n=== 4. CHECKOUT COMMISSION SPLIT ===")
    # U1 creates fresh product priced 500 published
    prod2_payload = {
        "name": "Vendor Checkout Lamp",
        "price": 500,
        "stock": 50,
        "image_url": "https://placehold.it/300",
        "description": "for checkout test",
        "is_published": True,
    }
    r = requests.post(f"{BASE}/vendor/me/products", headers=hdr(u1_tok), json=prod2_payload, timeout=30)
    check(r.status_code == 200, f"U1 creates fresh product priced 500 -> 200")
    p2_id = r.json().get("id") if r.status_code == 200 else None
    if p2_id:
        cleanup_product_ids.append(p2_id)

    # Register U3 buyer
    u3_email = f"u3.{RUN}@example.com"
    u3_tok, u3 = register("Chandni Buyer Three", u3_email, "Test@123")
    cleanup_user_ids.append(u3["id"])
    requests.post(f"{BASE}/payment/register-fee", headers=hdr(u3_tok), timeout=30)
    admin_approve_user(admin_tok, u3["id"])
    admin_credit_wallet(admin_tok, u3["id"], 1000, reason="checkout test topup")
    u3_me = me(u3_tok)
    check(u3_me.get("wallet_balance", 0) >= 1000, f"U3 wallet_balance >= 1000 (got {u3_me.get('wallet_balance')})")

    # Snapshot U1 wallet pre-checkout
    u1_pre = me(u1_tok)
    u1_balance_pre = u1_pre.get("wallet_balance") or 0

    # U3 cart.add then checkout
    r = requests.post(f"{BASE}/cart/add", headers=hdr(u3_tok), json={"product_id": p2_id, "qty": 1}, timeout=30)
    check(r.status_code == 200, f"U3 cart/add -> 200")

    r = requests.post(f"{BASE}/orders/checkout", headers=hdr(u3_tok), timeout=30)
    check(r.status_code == 200, f"U3 /orders/checkout -> 200 (got {r.status_code} {r.text[:300]})")
    order = r.json() if r.status_code == 200 else {}
    order_id = order.get("id")
    log(f"   order_id={order_id}")

    # Order document items[0].vendor_id == U1.id, vendor_share == 350
    items = order.get("items") or []
    if items:
        check(items[0].get("vendor_id") == u1["id"],
              f"Order.items[0].vendor_id == U1.id (got {items[0].get('vendor_id')})")
        check(items[0].get("vendor_share") == 350,
              f"Order.items[0].vendor_share == 350 (got {items[0].get('vendor_share')})")
    else:
        check(False, "Order has items")

    # U3 wallet decreased by 500
    u3_post = me(u3_tok)
    u3_post_bal = u3_post.get("wallet_balance") or 0
    check(round(u3_me.get("wallet_balance") - u3_post_bal, 2) == 500.0,
          f"U3 wallet_balance reduced by 500 (pre={u3_me.get('wallet_balance')}, post={u3_post_bal})")

    # U1 wallet increased by 350
    u1_post = me(u1_tok)
    u1_balance_post = u1_post.get("wallet_balance") or 0
    delta = round(u1_balance_post - u1_balance_pre, 2)
    check(delta == 350.0,
          f"U1 wallet_balance increased by 350 (pre={u1_balance_pre}, post={u1_balance_post}, delta={delta})")

    # vendor_sales row check via /vendor/me/sales
    r = requests.get(f"{BASE}/vendor/me/sales", headers=hdr(u1_tok), timeout=30)
    sales_items = (r.json().get("items") if r.status_code == 200 else []) or []
    matching = [s for s in sales_items if s.get("order_id") == order_id]
    check(len(matching) == 1, f"vendor_sales has 1 row for order_id={order_id} (found {len(matching)})")
    if matching:
        s = matching[0]
        check(s.get("vendor_id") == u1["id"], f"sale.vendor_id == U1.id (got {s.get('vendor_id')})")
        check(s.get("line_total") == 500, f"sale.line_total == 500 (got {s.get('line_total')})")
        check(s.get("vendor_share") == 350, f"sale.vendor_share == 350 (got {s.get('vendor_share')})")
        check(s.get("platform_share") == 150, f"sale.platform_share == 150 (got {s.get('platform_share')})")
        check(int(s.get("commission_pct") or 0) == 70, f"sale.commission_pct == 70 (got {s.get('commission_pct')})")

    # U1 has a transaction type=vendor_sale amount=350
    r = requests.get(f"{BASE}/transactions/me", headers=hdr(u1_tok), timeout=30)
    txs = r.json() if r.status_code == 200 else []
    if isinstance(txs, dict):
        txs = txs.get("items") or []
    vendor_tx = [t for t in txs if t.get("type") == "vendor_sale" and t.get("amount") == 350]
    check(len(vendor_tx) >= 1, f"U1 has vendor_sale transaction +350 (count={len(vendor_tx)})")

    # U1 has notification kind=vendor
    r = requests.get(f"{BASE}/notifications/me", headers=hdr(u1_tok), timeout=30)
    notes = r.json() if r.status_code == 200 else []
    new_sale_notes = [n for n in notes if n.get("kind") == "vendor" and "sale" in (n.get("title") or "").lower()]
    check(len(new_sale_notes) >= 1, f"U1 has vendor notification 'New sale!' (titles={[n.get('title') for n in notes][:5]})")

    # === 5. STATS ===
    log("\n=== 5. STATS ===")
    r = requests.get(f"{BASE}/vendor/me/stats", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"GET /vendor/me/stats -> 200 (got {r.status_code} {r.text[:200]})")
    if r.status_code == 200:
        s = r.json()
        check(s.get("total_earnings", 0) >= 350, f"stats.total_earnings >= 350 (got {s.get('total_earnings')})")
        check(s.get("total_sales", 0) >= 500, f"stats.total_sales >= 500 (got {s.get('total_sales')})")
        check(s.get("today_orders", 0) >= 1, f"stats.today_orders >= 1 (got {s.get('today_orders')})")
        check(s.get("products_count", 0) >= 1, f"stats.products_count >= 1 (got {s.get('products_count')})")

    # === 6. ADMIN VENDORS LIST + SUSPEND/REACTIVATE ===
    log("\n=== 6. ADMIN VENDORS LIST + SUSPEND/REACTIVATE ===")
    r = requests.get(f"{BASE}/admin/vendors", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"GET /admin/vendors -> 200")
    if r.status_code == 200:
        items = r.json().get("items") or []
        u1_row = next((v for v in items if v.get("id") == u1["id"]), None)
        check(u1_row is not None, f"U1 in /admin/vendors list (count={len(items)})")
        if u1_row:
            check(u1_row.get("total_earnings", 0) >= 350,
                  f"U1 total_earnings >= 350 (got {u1_row.get('total_earnings')})")

    # Suspend U1
    r = requests.post(f"{BASE}/admin/vendors/{u1['id']}/suspend", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"POST /admin/vendors/U1/suspend -> 200 (got {r.status_code} {r.text[:200]})")
    u1_me = me(u1_tok)
    check(u1_me.get("vendor_status") == "suspended",
          f"U1 vendor_status='suspended' after suspend (got {u1_me.get('vendor_status')})")

    # U1's products is_published=false (check via /vendor/me/products is gated 403; use admin GET /admin/products)
    r = requests.get(f"{BASE}/admin/products", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        prods = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        u1_prods = [p for p in prods if p.get("vendor_id") == u1["id"]]
        all_unpub = all(p.get("is_published") is False for p in u1_prods) if u1_prods else False
        check(all_unpub, f"All U1 products is_published=False after suspend (count={len(u1_prods)})")

    # /vendor/me/stats now 403
    r = requests.get(f"{BASE}/vendor/me/stats", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 403, f"GET /vendor/me/stats while suspended -> 403 (got {r.status_code})")

    # Reactivate
    r = requests.post(f"{BASE}/admin/vendors/{u1['id']}/reactivate", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"POST /admin/vendors/U1/reactivate -> 200")
    u1_me = me(u1_tok)
    check(u1_me.get("vendor_status") == "approved",
          f"U1 vendor_status='approved' after reactivate (got {u1_me.get('vendor_status')})")
    r = requests.get(f"{BASE}/vendor/me/stats", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"GET /vendor/me/stats after reactivate -> 200 (got {r.status_code})")

    # === 7. REJECTION FLOW ===
    log("\n=== 7. REJECTION FLOW ===")
    u4_email = f"u4.{RUN}@example.com"
    u4_tok, u4 = register("Divya Vendor Four", u4_email, "Test@123")
    cleanup_user_ids.append(u4["id"])
    requests.post(f"{BASE}/payment/register-fee", headers=hdr(u4_tok), timeout=30)
    admin_approve_user(admin_tok, u4["id"])
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u4_tok),
                      json={"shop_name": "U4 Store", "gst_number": "G4", "pan_number": "P4"}, timeout=30)
    check(r.status_code == 200, f"U4 vendor/apply -> 200")
    u4_app_id = r.json()["application"]["id"] if r.status_code == 200 else None

    r = requests.post(f"{BASE}/admin/vendor-applications/{u4_app_id}/reject",
                      headers=hdr(admin_tok), json={"reason": "Insufficient docs"}, timeout=30)
    check(r.status_code == 200 and r.json().get("ok") and r.json()["application"].get("status") == "rejected",
          f"admin reject U4 vendor app -> 200 (got {r.status_code} {r.text[:200]})")
    if r.status_code == 200:
        check(r.json()["application"].get("rejection_reason") == "Insufficient docs",
              f"application.rejection_reason saved")
    u4_me = me(u4_tok)
    check(u4_me.get("vendor_status") == "rejected",
          f"U4 vendor_status='rejected' (got {u4_me.get('vendor_status')})")

    # Notification check
    r = requests.get(f"{BASE}/notifications/me", headers=hdr(u4_tok), timeout=30)
    notes = r.json() if r.status_code == 200 else []
    rejected_notes = [n for n in notes if n.get("kind") == "vendor" and "reject" in (n.get("title") or "").lower()]
    check(len(rejected_notes) >= 1, f"U4 received rejection notification (titles={[n.get('title') for n in notes][:5]})")

    # U4 re-apply -> 200 allowed
    r = requests.post(f"{BASE}/vendor/apply", headers=hdr(u4_tok),
                      json={"shop_name": "U4 Re-applied Store", "gst_number": "G4r", "pan_number": "P4r"}, timeout=30)
    check(r.status_code == 200, f"U4 re-apply after rejection -> 200 (got {r.status_code} {r.text[:200]})")

    # === 8. REGRESSION ===
    log("\n=== 8. REGRESSION ===")
    r = requests.get(f"{BASE}/products", timeout=30)
    check(r.status_code == 200 and isinstance(r.json(), list),
          f"GET /api/products (public) -> 200 list (got {r.status_code})")

    r = requests.get(f"{BASE}/admin/approvals?status=pending", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"GET /admin/approvals?status=pending -> 200 (got {r.status_code})")

    r = requests.get(f"{BASE}/branding", timeout=30)
    check(r.status_code == 200, f"GET /branding -> 200 (got {r.status_code})")

    # Platform-owned product checkout — no vendor_sales row written
    log("\n--- Platform-owned product checkout regression ---")
    plat_prod = {
        "name": f"Platform Test {RUN}",
        "price": 200,
        "stock": 5,
        "image_url": "https://placehold.it/200",
        "description": "platform-owned",
        "is_published": True,
    }
    r = requests.post(f"{BASE}/admin/products", headers=hdr(admin_tok), json=plat_prod, timeout=30)
    check(r.status_code == 200, f"admin POST /admin/products platform-owned -> 200")
    plat_pid = r.json().get("id") if r.status_code == 200 else None
    if plat_pid:
        cleanup_product_ids.append(plat_pid)

    # Topup U3 again
    admin_credit_wallet(admin_tok, u3["id"], 500, reason="platform test topup")
    requests.post(f"{BASE}/cart/clear", headers=hdr(u3_tok), timeout=30)
    requests.post(f"{BASE}/cart/add", headers=hdr(u3_tok), json={"product_id": plat_pid, "qty": 1}, timeout=30)
    pre_sales = requests.get(f"{BASE}/vendor/me/sales", headers=hdr(u1_tok), timeout=30).json()
    pre_count = len(pre_sales.get("items") or [])
    r = requests.post(f"{BASE}/orders/checkout", headers=hdr(u3_tok), timeout=30)
    check(r.status_code == 200, f"U3 checkout platform-owned product -> 200 (got {r.status_code} {r.text[:200]})")
    if r.status_code == 200:
        plat_order = r.json()
        items = plat_order.get("items") or []
        if items:
            check(not items[0].get("vendor_id"),
                  f"Platform-owned order item.vendor_id is empty (got {items[0].get('vendor_id')})")
    post_sales = requests.get(f"{BASE}/vendor/me/sales", headers=hdr(u1_tok), timeout=30).json()
    post_count = len(post_sales.get("items") or [])
    check(post_count == pre_count,
          f"vendor_sales count unchanged after platform-owned checkout (pre={pre_count}, post={post_count})")

    # === CLEANUP ===
    log("\n=== CLEANUP ===")
    cleanup_errors = 0
    # Delete platform-owned product via /admin/products
    if plat_pid:
        r = requests.delete(f"{BASE}/admin/products/{plat_pid}", headers=hdr(admin_tok), timeout=30)
        if r.status_code != 200:
            cleanup_errors += 1
            log(f"   cleanup: failed to delete platform product {plat_pid}: {r.status_code}")
    # Delete vendor products via /admin/products
    for pid in cleanup_product_ids:
        if pid == plat_pid:
            continue
        r = requests.delete(f"{BASE}/admin/products/{pid}", headers=hdr(admin_tok), timeout=30)
        if r.status_code not in (200, 404):
            cleanup_errors += 1
            log(f"   cleanup: failed to delete product {pid}: {r.status_code}")

    # Delete users
    for uid in cleanup_user_ids:
        r = requests.delete(f"{BASE}/admin/users/{uid}", headers=hdr(admin_tok), timeout=30)
        if r.status_code not in (200, 404):
            cleanup_errors += 1
            log(f"   cleanup: failed to delete user {uid}: {r.status_code}")

    # Verify admin login still works
    try:
        login(ADMIN_EMAIL, ADMIN_PASS)
        check(True, "admin@app.com login still works after cleanup")
    except Exception as e:
        check(False, f"admin login broken: {e}")

    log(f"\ncleanup_errors={cleanup_errors}")

    # === SUMMARY ===
    log(f"\n=== SUMMARY: {PASSED} passed, {FAILED} failed ===")
    if FAILURES:
        log("FAILURES:")
        for f in FAILURES:
            log(f"  - {f}")
    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    main()
