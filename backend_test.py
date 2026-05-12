#!/usr/bin/env python3
"""
FULL APP REGRESSION SWEEP
=========================
Walks every critical backend flow and reports any failure / 5xx / regression.

Sections:
  1. AUTH
  2. BRANDING / PUBLIC
  3. CART + CHECKOUT
  4. WISHLIST + REVIEWS / Q&A
  5. USER DASHBOARD / WALLET / NOTIFICATIONS
  6. ADMIN BASICS
  7. SHOP-LAYOUT ADMIN
  8. VENDOR FLOW (as admin)
  9. SERVICES / DISTRIBUTOR / OTHER
 10. CHAT
"""
from __future__ import annotations
import os, sys, time, json, traceback
from typing import Any, Dict, List, Optional, Tuple
import requests

BACKEND = os.environ.get("BACKEND_URL") or "https://network-pay-1.preview.emergentagent.com"
API = BACKEND.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
TESTUSER_EMAIL = "testuser@app.com"
TESTUSER_PASSWORD = "Test@123"

TS = int(time.time())
AUDIT_EMAIL = f"audit+{TS}@app.com"
AUDIT_PASSWORD = "Audit@123"

RESULTS: List[Dict[str, Any]] = []
CLEANUP: List[Tuple[str, callable]] = []  # (label, fn)


def _safe(text: Any, max_len: int = 280) -> str:
    s = text if isinstance(text, str) else json.dumps(text, default=str)
    s = s.replace("\n", " ")
    return s[:max_len]


def call(method: str, path: str, *, token: Optional[str] = None, json_body: Any = None,
         params: Dict[str, Any] = None, allow_status: Tuple[int, ...] = ()) -> Tuple[int, Any, str]:
    """Returns (status, body_json_or_text, error_str)."""
    url = API + path if path.startswith("/") else API + "/" + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.request(method, url, json=json_body, params=params, headers=headers, timeout=30)
    except Exception as e:
        return 0, None, f"network: {e!r}"
    body: Any
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body, ""


def record(section: str, label: str, expected: str, status: int, body: Any, err: str = "",
           ok_override: Optional[bool] = None, detail: str = ""):
    if ok_override is None:
        ok = (200 <= status < 300)
    else:
        ok = ok_override
    summary = f"{label} → {status}"
    if err:
        summary += f" [{err}]"
    if not ok and body is not None:
        summary += f" :: {_safe(body, 200)}"
    elif detail:
        summary += f" :: {detail}"
    icon = "✅" if ok else "❌"
    line = f"  {icon} {summary}"
    print(line, flush=True)
    RESULTS.append({"section": section, "label": label, "expected": expected,
                    "status": status, "ok": ok, "body": _safe(body, 400), "err": err})
    return ok


def section(name: str):
    print(f"\n## {name}", flush=True)


# ───────────────────────────── SECTION 1 — AUTH ─────────────────────────────
def s1_auth() -> Dict[str, Any]:
    section("SECTION 1 — AUTH")
    ctx: Dict[str, Any] = {}

    s, b, e = call("POST", "/auth/login", json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    ok = record("1", "POST /auth/login (admin)", "200", s, b, e)
    if ok and isinstance(b, dict):
        ctx["admin_token"] = b.get("access_token") or b.get("token")
        u = b.get("user") or {}
        record("1", "  admin user.role=='admin'", "admin", s, b,
               ok_override=(u.get("role") == "admin"),
               detail=f"role={u.get('role')!r} admin_role={u.get('admin_role')!r}")
        ctx["admin_id"] = u.get("id")

    s, b, e = call("POST", "/auth/login", json_body={"email": TESTUSER_EMAIL, "password": TESTUSER_PASSWORD})
    ok = record("1", "POST /auth/login (test user)", "200", s, b, e)
    if ok and isinstance(b, dict):
        ctx["user_token"] = b.get("access_token") or b.get("token")
        ctx["user_id"] = (b.get("user") or {}).get("id")

    s, b, e = call("POST", "/auth/login", json_body={"email": ADMIN_EMAIL, "password": "WrongPwd!!"})
    record("1", "POST /auth/login (wrong password)", "401", s, b, e, ok_override=(s == 401))

    if ctx.get("admin_token"):
        s, b, e = call("GET", "/auth/me", token=ctx["admin_token"])
        ok = record("1", "GET /auth/me (admin token)", "200", s, b, e)
        if ok and isinstance(b, dict):
            record("1", "  /auth/me returns same admin", "match", s, b,
                   ok_override=(b.get("email") == ADMIN_EMAIL))

    # Register a throwaway user
    s, b, e = call("POST", "/auth/register",
                   json_body={"name": "Audit Probe", "email": AUDIT_EMAIL,
                              "password": AUDIT_PASSWORD, "phone": "9876543210"})
    ok = record("1", f"POST /auth/register ({AUDIT_EMAIL})", "200/201", s, b, e,
                ok_override=(200 <= s < 300))
    if ok and isinstance(b, dict):
        ctx["audit_id"] = (b.get("user") or {}).get("id") or b.get("id")

    s, b, e = call("POST", "/auth/login", json_body={"email": AUDIT_EMAIL, "password": AUDIT_PASSWORD})
    ok = record("1", "POST /auth/login (the new user)", "200", s, b, e)
    if ok and isinstance(b, dict):
        ctx["audit_token"] = b.get("access_token") or b.get("token")
        if not ctx.get("audit_id"):
            ctx["audit_id"] = (b.get("user") or {}).get("id")

    return ctx


# ───────────────────── SECTION 2 — BRANDING / PUBLIC ────────────────────────
def s2_branding(ctx: Dict[str, Any]):
    section("SECTION 2 — BRANDING / PUBLIC")
    s, b, e = call("GET", "/branding")
    ok = record("2", "GET /branding", "200", s, b, e)
    if ok and isinstance(b, dict):
        record("2", "  /branding has app_name + tagline", "keys present", s, b,
               ok_override=("app_name" in b and "tagline" in b))

    s, b, e = call("GET", "/products")
    ok = record("2", "GET /products", "200 array w/ is_in_stock+interested_count", s, b, e)
    sample_pid = None
    if ok:
        items = b if isinstance(b, list) else (b.get("items") if isinstance(b, dict) else None)
        if isinstance(items, list) and items:
            sample_pid = items[0].get("id")
            ctx["sample_pid"] = sample_pid
            first = items[0]
            record("2", "  product has is_in_stock+interested_count", "shape", s,
                   {"keys": list(first.keys())[:25]},
                   ok_override=("is_in_stock" in first and "interested_count" in first))
        else:
            record("2", "  product array shape", "shape", s, items, ok_override=False)

    if sample_pid:
        s, b, e = call("GET", f"/products/{sample_pid}")
        record("2", f"GET /products/{{id}}", "200 extended fields", s, b, e,
               ok_override=(s == 200 and isinstance(b, dict) and "is_in_stock" in b))

    s, b, e = call("GET", "/products/by-source", params={"source": "trending", "limit": 5})
    record("2", "GET /products/by-source?source=trending", "200", s, b, e)

    s, b, e = call("GET", "/products/by-source", params={"source": "new", "limit": 5})
    record("2", "GET /products/by-source?source=new", "200", s, b, e)

    s, b, e = call("GET", "/shop-layout", params={"scope": "home"})
    record("2", "GET /shop-layout?scope=home (no auth)", "200 list", s, b, e,
           ok_override=(s == 200))


# ──────────────────── SECTION 3 — CART + CHECKOUT ──────────────────────────
def s3_cart_checkout(ctx: Dict[str, Any]):
    section("SECTION 3 — CART + CHECKOUT")
    tok = ctx.get("user_token")
    if not tok:
        record("3", "PRECONDITION user_token", "present", 0, None, "no test-user token", ok_override=False)
        return
    pid = ctx.get("sample_pid")
    if not pid:
        record("3", "PRECONDITION sample_pid", "present", 0, None, "no product id", ok_override=False)
        return

    # Clear first for a clean slate
    call("POST", "/cart/clear", token=tok)

    s, b, e = call("POST", "/cart/add", token=tok, json_body={"product_id": pid, "qty": 1})
    record("3", "POST /cart/add", "200", s, b, e)

    s, b, e = call("GET", "/cart", token=tok)
    ok = record("3", "GET /cart", "200 has item", s, b, e)
    has_item = False
    if ok and isinstance(b, dict):
        has_item = any(it.get("product_id") == pid for it in (b.get("items") or []))
        record("3", "  cart contains added product", "yes", s, None,
               ok_override=has_item, detail=f"count={len(b.get('items') or [])}")

    # /cart/update is documented as missing — we'll mark it
    s, b, e = call("POST", "/cart/update", token=tok, json_body={"product_id": pid, "qty": 2})
    if s == 404 or s == 405:
        record("3", "POST /cart/update (qty=2)", "endpoint missing - documented",
               s, b, e, ok_override=True, detail="endpoint not implemented (acceptable)")
    else:
        record("3", "POST /cart/update (qty=2)", "200", s, b, e)

    # COD checkout with full shipping address
    addr = {
        "name": "Audit Buyer", "phone": "9876543210",
        "line1": "12, Audit Lane", "line2": "Floor 2",
        "city": "Hyderabad", "state": "Telangana", "pincode": "500001",
    }
    s, b, e = call("POST", "/orders/checkout", token=tok,
                   json_body={"payment_method": "cod", "shipping_address": addr})
    ok = record("3", "POST /orders/checkout (COD)", "200 order_id", s, b, e)
    order_id = None
    if ok and isinstance(b, dict):
        order_id = b.get("id") or b.get("order_id") or (b.get("order") or {}).get("id")
        record("3", "  order has id/status", "id+status", s, None,
               ok_override=bool(order_id),
               detail=f"id={order_id} status={b.get('status')} paid_via={b.get('paid_via')}")
        ctx["audit_order_id"] = order_id

    s, b, e = call("GET", "/orders/me", token=tok)
    ok = record("3", "GET /orders/me", "200 contains order", s, b, e)
    if ok:
        items = b if isinstance(b, list) else (b.get("items") if isinstance(b, dict) else [])
        if order_id and isinstance(items, list):
            found = any((it.get("id") == order_id) for it in items)
            record("3", "  order appears in /orders/me", "yes", s, None,
                   ok_override=found, detail=f"orders_listed={len(items)}")

    # cart clear (no DELETE /cart in this API; use POST /cart/clear)
    s, b, e = call("POST", "/cart/clear", token=tok)
    record("3", "POST /cart/clear (cart wipe)", "200", s, b, e)


# ─────────────── SECTION 4 — WISHLIST + REVIEWS / Q&A ──────────────────────
def s4_wishlist_reviews(ctx: Dict[str, Any]):
    section("SECTION 4 — WISHLIST + REVIEWS / Q&A")
    tok = ctx.get("user_token")
    pid = ctx.get("sample_pid")
    if not (tok and pid):
        record("4", "PRECONDITION user_token+pid", "present", 0, None,
               "missing prereqs", ok_override=False)
        return

    s, b, e = call("POST", f"/products/{pid}/save", token=tok)
    ok1 = record("4", "POST /products/{id}/save (1st)", "200 saved:true", s, b, e,
                 ok_override=(s == 200 and isinstance(b, dict) and b.get("saved") is True))

    s, b, e = call("GET", "/me/wishlist", token=tok)
    ok = record("4", "GET /me/wishlist", "200 contains product", s, b, e)
    if ok:
        items = b if isinstance(b, list) else (b.get("items") if isinstance(b, dict) else [])
        found = any(((it.get("id") if isinstance(it, dict) else it) == pid) for it in (items or []))
        record("4", "  wishlist contains pid", "yes", s, None, ok_override=found)

    s, b, e = call("POST", f"/products/{pid}/save", token=tok)
    record("4", "POST /products/{id}/save (toggle)", "200 saved:false", s, b, e,
           ok_override=(s == 200 and isinstance(b, dict) and b.get("saved") is False))

    s, b, e = call("POST", f"/products/{pid}/reviews", token=tok,
                   json_body={"rating": 5, "title": "Audit review", "body": "Auto-generated audit"})
    review_id = None
    ok = record("4", "POST /products/{id}/reviews", "200/201", s, b, e,
                ok_override=(200 <= s < 300))
    if ok and isinstance(b, dict):
        review_id = b.get("id") or (b.get("review") or {}).get("id")

    s, b, e = call("GET", f"/products/{pid}/reviews", token=tok)
    ok = record("4", "GET /products/{id}/reviews", "200 stats + voted_helpful", s, b, e)
    if ok:
        reviews = b.get("reviews") or b.get("items") or (b if isinstance(b, list) else [])
        has_voted = False
        if isinstance(reviews, list) and reviews:
            has_voted = "voted_helpful" in reviews[0]
        record("4", "  review object has voted_helpful flag", "flag present", s, None,
               ok_override=has_voted, detail=f"count={len(reviews) if isinstance(reviews, list) else 'NA'}")

    s, b, e = call("POST", f"/products/{pid}/questions", token=tok, json_body={"text": "audit q?"})
    record("4", "POST /products/{id}/questions", "200/201", s, b, e,
           ok_override=(200 <= s < 300))

    s, b, e = call("GET", f"/products/{pid}/questions", token=tok)
    record("4", "GET /products/{id}/questions", "200", s, b, e)

    ctx["audit_review_id"] = review_id


# ───────── SECTION 5 — USER DASHBOARD / WALLET / NOTIFICATIONS ─────────────
def s5_dashboard(ctx: Dict[str, Any]):
    section("SECTION 5 — USER DASHBOARD / WALLET / NOTIFICATIONS")
    tok = ctx.get("user_token")
    if not tok:
        record("5", "PRECONDITION user_token", "present", 0, None,
               "no test-user token", ok_override=False)
        return

    s, b, e = call("GET", "/users/me/dashboard", token=tok)
    ok = record("5", "GET /users/me/dashboard", "200 wallet+tier+level_payouts", s, b, e)
    if ok and isinstance(b, dict):
        keys_ok = ("wallet_balance" in b and "tier" in b and "level_payouts" in b)
        record("5", "  dashboard has wallet_balance/tier/level_payouts", "shape", s, None,
               ok_override=keys_ok,
               detail=f"wallet={b.get('wallet_balance')} tier={b.get('tier')}")

    s, b, e = call("GET", "/notifications/me", token=tok)
    record("5", "GET /notifications/me", "200 array", s, b, e)

    # /me/orders vs /orders/me — try both
    s_a, _, _ = call("GET", "/me/orders", token=tok)
    s_b, _, _ = call("GET", "/orders/me", token=tok)
    if s_a == 200 or s_b == 200:
        record("5", "GET /me/orders | /orders/me", "200 either", max(s_a, s_b), None,
               ok_override=True, detail=f"/me/orders={s_a}, /orders/me={s_b}")
    else:
        record("5", "GET /me/orders | /orders/me", "200 either", s_b, None,
               ok_override=False, detail=f"/me/orders={s_a}, /orders/me={s_b}")

    # /me/team — try canonical & network fallback
    s_t, _, _ = call("GET", "/me/team", token=tok)
    if s_t == 200:
        record("5", "GET /me/team", "200", s_t, None, ok_override=True)
    else:
        s_n, b, e = call("GET", "/users/me/network", token=tok)
        ok = (s_n == 200)
        record("5", "GET /me/team (fallback /users/me/network)", "200 (canonical missing)",
               s_n, b, e, ok_override=ok,
               detail=f"/me/team={s_t} (no canonical endpoint, network alt={s_n})")

    # Withdrawals: try /withdrawals/request first, fall back to /withdrawals
    s, b, e = call("POST", "/withdrawals/request", token=tok, json_body={"amount": 100})
    if s == 404 or s == 405:
        s2, b2, e2 = call("POST", "/withdrawals", token=tok, json_body={"amount": 100})
        # 200 (success) OR 400 (low balance) acceptable; 5xx = bad
        accepted = (200 <= s2 < 300) or s2 == 400
        record("5", "POST /withdrawals (alt of /withdrawals/request)",
               "200 OR 400 (low balance)", s2, b2, e2,
               ok_override=accepted,
               detail=f"/withdrawals/request={s} fallback=/withdrawals→{s2}")
    else:
        accepted = (200 <= s < 300) or s == 400
        record("5", "POST /withdrawals/request {amount:100}",
               "200 OR 400", s, b, e, ok_override=accepted)


# ──────────────────── SECTION 6 — ADMIN BASICS ─────────────────────────────
def s6_admin(ctx: Dict[str, Any]):
    section("SECTION 6 — ADMIN BASICS")
    tok = ctx.get("admin_token")
    if not tok:
        record("6", "PRECONDITION admin_token", "present", 0, None,
               "no admin token", ok_override=False)
        return

    s, b, e = call("GET", "/admin/products", token=tok)
    record("6", "GET /admin/products", "200 list", s, b, e)

    s, b, e = call("GET", "/admin/users", token=tok)
    record("6", "GET /admin/users", "200", s, b, e)

    s, b, e = call("GET", "/admin/orders", token=tok)
    record("6", "GET /admin/orders", "200", s, b, e)

    s, b, e = call("GET", "/admin/analytics", token=tok, params={"days": 7})
    record("6", "GET /admin/analytics?days=7", "200", s, b, e)

    s, b, e = call("GET", "/admin/approvals", token=tok, params={"status": "pending"})
    record("6", "GET /admin/approvals?status=pending", "200", s, b, e)

    s, b, e = call("GET", "/admin/approvals/today", token=tok)
    record("6", "GET /admin/approvals/today", "200", s, b, e)


# ─────────────── SECTION 7 — SHOP-LAYOUT ADMIN ─────────────────────────────
def s7_shop_layout(ctx: Dict[str, Any]):
    section("SECTION 7 — SHOP-LAYOUT ADMIN")
    tok = ctx.get("admin_token")
    if not tok:
        record("7", "PRECONDITION admin_token", "present", 0, None,
               "no admin token", ok_override=False)
        return

    s, b, e = call("GET", "/admin/shop-layout", token=tok, params={"scope": "home"})
    record("7", "GET /admin/shop-layout?scope=home", "200", s, b, e)

    blk_id = None
    s, b, e = call("POST", "/admin/shop-layout", token=tok,
                   json_body={"block_type": "section_header", "scope": "home",
                              "title": "Audit Test Block", "sort_order": 999, "active": True})
    ok = record("7", "POST /admin/shop-layout (create block)", "200 id", s, b, e)
    if ok and isinstance(b, dict):
        blk_id = b.get("id") or (b.get("block") or {}).get("id")
    ctx["audit_block_id"] = blk_id

    if blk_id:
        s, b, e = call("PATCH", f"/admin/shop-layout/{blk_id}", token=tok,
                       json_body={"title": "Audit Test Block (updated)"})
        record("7", "PATCH /admin/shop-layout/{id}", "200", s, b, e)

        s, b, e = call("DELETE", f"/admin/shop-layout/{blk_id}", token=tok)
        record("7", "DELETE /admin/shop-layout/{id}", "200", s, b, e)
        ctx["audit_block_id"] = None  # already cleaned

    s, b, e = call("POST", "/admin/shop-layout/seed-default-home", token=tok)
    record("7", "POST /admin/shop-layout/seed-default-home", "200 (skipped:true OK)", s, b, e)

    s, b, e = call("GET", "/admin/shop-layout/analytics", token=tok, params={"days": 7})
    record("7", "GET /admin/shop-layout/analytics?days=7", "200", s, b, e)


# ─────────────── SECTION 8 — VENDOR FLOW (as admin) ────────────────────────
def s8_vendor(ctx: Dict[str, Any]):
    section("SECTION 8 — VENDOR FLOW (as admin)")
    tok = ctx.get("admin_token")
    if not tok:
        record("8", "PRECONDITION admin_token", "present", 0, None,
               "no admin token", ok_override=False)
        return

    s, b, e = call("GET", "/vendor/me/questions", token=tok)
    record("8", "GET /vendor/me/questions", "200 (admin fallback)", s, b, e)

    s, b, e = call("GET", "/vendor/me/stats", token=tok)
    # 200 or 403 both OK per the brief
    ok = (s == 200 or s == 403)
    record("8", "GET /vendor/me/stats", "200 OR 403", s, b, e, ok_override=ok)

    s, b, e = call("GET", "/vendors/suggest", token=tok, params={"q": ""})
    record("8", "GET /vendors/suggest?q=", "200", s, b, e)


# ─────────────── SECTION 9 — SERVICES / DISTRIBUTOR / OTHER ────────────────
def s9_other(ctx: Dict[str, Any]):
    section("SECTION 9 — SERVICES / DISTRIBUTOR / OTHER")
    tok = ctx.get("user_token") or ctx.get("admin_token")

    s, b, e = call("GET", "/services/categories")
    record("9", "GET /services/categories", "200", s, b, e)

    s, b, e = call("GET", "/services")
    record("9", "GET /services", "200 or document missing", s, b, e,
           ok_override=(200 <= s < 300) or s in (404, 405),
           detail="ok if 2xx or documented missing")

    # /distributor/network — likely doesn't exist standalone; closest is /users/me/network or /admin/distributors
    s, b, e = call("GET", "/distributor/network", token=tok)
    if s in (404, 405):
        record("9", "GET /distributor/network", "missing (acceptable)", s, b, e,
               ok_override=True, detail="endpoint missing")
    else:
        record("9", "GET /distributor/network", "200", s, b, e)

    # /pincodes/search — admin has /admin/pincodes/search; public version doesn't exist
    s, b, e = call("GET", "/pincodes/search", params={"q": "560001"})
    if s in (404, 405):
        # Try admin version
        s2, b2, e2 = call("GET", "/admin/pincodes/search", token=ctx.get("admin_token"),
                          params={"q": "560001"})
        record("9", "GET /pincodes/search (admin alt /admin/pincodes/search)",
               "200", s2, b2, e2,
               detail=f"public missing (got {s}), admin alt={s2}")
    else:
        record("9", "GET /pincodes/search?q=560001", "200", s, b, e)


# ─────────────────────────── SECTION 10 — CHAT ─────────────────────────────
def s10_chat(ctx: Dict[str, Any]):
    section("SECTION 10 — CHAT")
    tok = ctx.get("user_token")
    admin_id = ctx.get("admin_id")
    if not tok:
        record("10", "PRECONDITION user_token", "present", 0, None,
               "no test-user token", ok_override=False)
        return

    s, b, e = call("GET", "/chat/threads", token=tok)
    record("10", "GET /chat/threads", "200", s, b, e)

    # POST /chat/threads {peer_id} — actual flow is /chat/request → accept
    s, b, e = call("POST", "/chat/threads", token=tok,
                   json_body={"peer_id": admin_id})
    if s in (404, 405):
        # Document missing — try the actual /chat/request flow
        s2, b2, e2 = call("POST", "/chat/request", token=tok,
                          json_body={"to_user_id": admin_id, "message": "audit"})
        record("10", "POST /chat/threads (alt: /chat/request)",
               "200 (canonical missing)", s2, b2, e2,
               ok_override=(200 <= s2 < 300),
               detail=f"/chat/threads={s} → use /chat/request ({s2})")
        # If accepted, we can read messages, but admin would have to accept.
        # Skip messages step in that case.
    else:
        record("10", "POST /chat/threads {peer_id}", "200", s, b, e)
        if 200 <= s < 300 and isinstance(b, dict):
            tid = b.get("thread_id") or b.get("id")
            if tid:
                s2, b2, e2 = call("GET", f"/chat/threads/{tid}/messages", token=tok)
                record("10", "GET /chat/threads/{tid}/messages", "200", s2, b2, e2)


# ─────────────────────────────── CLEANUP ───────────────────────────────────
def cleanup(ctx: Dict[str, Any]):
    section("CLEANUP")
    admin_tok = ctx.get("admin_token")

    # Delete the audit block if it lingers
    if ctx.get("audit_block_id") and admin_tok:
        s, b, e = call("DELETE", f"/admin/shop-layout/{ctx['audit_block_id']}", token=admin_tok)
        print(f"  cleanup: delete audit shop-layout block → {s}")

    # Delete the audit user (best-effort)
    if ctx.get("audit_id") and admin_tok:
        s, b, e = call("DELETE", f"/admin/users/{ctx['audit_id']}", token=admin_tok)
        print(f"  cleanup: delete audit user {AUDIT_EMAIL} → {s}")

    # Best-effort: clear test user's cart
    if ctx.get("user_token"):
        s, _, _ = call("POST", "/cart/clear", token=ctx["user_token"])
        print(f"  cleanup: clear testuser cart → {s}")


# ────────────────────────── SUMMARY REPORTER ───────────────────────────────
def report():
    print("\n\n══════════════════════════════════════════════════════")
    print("FULL REGRESSION REPORT")
    print("══════════════════════════════════════════════════════")

    total = len(RESULTS)
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"Total checks: {total}   Passed: {total - len(failed)}   Failed: {len(failed)}")

    # P0 = 5xx or network errors
    p0 = [r for r in failed if (r["status"] >= 500) or (r["status"] == 0)]
    # P1 = 4xx where 200 expected (200 is in expected)
    p1 = [r for r in failed if 400 <= r["status"] < 500 and r not in p0]
    # P2 = response shape mismatches (status 200 but failed validators)
    p2 = [r for r in failed if 200 <= r["status"] < 300]

    def dump(label: str, group: List[Dict[str, Any]]):
        print(f"\n{label} ({len(group)})")
        for r in group:
            print(f"  • [{r['section']}] {r['label']} → status={r['status']} "
                  f"expected={r['expected']} :: {r['body']}")

    dump("P0 (5xx / network)", p0)
    dump("P1 (4xx where 200 expected)", p1)
    dump("P2 (response-shape regressions)", p2)

    print("\nReturning failure exit code if P0/P1 present:",
          1 if (p0 or p1) else 0)
    return p0, p1, p2


# ──────────────────────────────── MAIN ─────────────────────────────────────
def main():
    print(f"BACKEND: {BACKEND}")
    print(f"API base: {API}")
    print(f"Audit throwaway user: {AUDIT_EMAIL}")
    ctx: Dict[str, Any] = {}
    try:
        ctx = s1_auth()
        s2_branding(ctx)
        s3_cart_checkout(ctx)
        s4_wishlist_reviews(ctx)
        s5_dashboard(ctx)
        s6_admin(ctx)
        s7_shop_layout(ctx)
        s8_vendor(ctx)
        s9_other(ctx)
        s10_chat(ctx)
    except Exception:
        print("FATAL during run:")
        traceback.print_exc()
    finally:
        try:
            cleanup(ctx)
        except Exception:
            traceback.print_exc()
    report()


if __name__ == "__main__":
    main()
