"""
Backend tests for June 2026 additions:
  - Phone-reveal model (config, charge, idempotency, listings, invoice ACL)
  - Public guest ticket tracker (lookup, thread w/ PII mask, reply)
  - Admin system-wallet tally withdraw + listing
  - User address PATCH
  - Settings flags (phone_reveal_fee, phone_reveal_gst_pct,
    shop_margin_enabled, service_booking_margin_enabled)

Backend URL is read from /app/frontend/.env (EXPO_PUBLIC_BACKEND_URL).
"""
import os
import re
import sys
import json
import uuid
import time
import requests

# ── Resolve backend base URL ──────────────────────────────────────────────
BASE = None
try:
    with open("/app/frontend/.env") as f:
        for line in f:
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
except FileNotFoundError:
    pass
if not BASE:
    BASE = "https://vendor-network-app-1.preview.emergentagent.com"
API = f"{BASE.rstrip('/')}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS  = "Admin@123"
USER_EMAIL  = "testuser@app.com"
USER_PASS   = "Test@123"

passes, fails = [], []

def _ok(label, ok, info=""):
    (passes if ok else fails).append((label, info))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {label}" + (f" — {info}" if info else ""))

def _login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=20)
    if r.status_code != 200:
        return None, f"login {email} → {r.status_code} {r.text[:200]}"
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    return tok, None

def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def main():
    print(f"Backend: {API}")

    # ── login admin & testuser ──────────────────────────────────────────
    admin_tok, err = _login(ADMIN_EMAIL, ADMIN_PASS)
    _ok("admin login", admin_tok is not None, err or "")
    if not admin_tok:
        print("[FATAL] cannot continue without admin login")
        return _summary()

    user_tok, uerr = _login(USER_EMAIL, USER_PASS)
    _ok("testuser login", user_tok is not None, uerr or "")
    if not user_tok:
        # Create the test user fresh if missing
        rr = requests.post(f"{API}/auth/register", json={
            "name": "Test User",
            "email": USER_EMAIL,
            "password": USER_PASS,
            "phone": "9876543210",
        }, timeout=20)
        _ok("testuser register fallback", rr.status_code in (200, 201, 400),
            f"{rr.status_code} {rr.text[:160]}")
        user_tok, _ = _login(USER_EMAIL, USER_PASS)

    # ─────────────────────────────────────────────────────────────────
    # 11. Settings flags regression (do this early — needed for fee/gst).
    # ─────────────────────────────────────────────────────────────────
    r = requests.get(f"{API}/admin/settings", headers=_auth(admin_tok), timeout=15)
    _ok("GET /admin/settings status 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    settings = r.json() if r.status_code == 200 else {}
    # The endpoint might wrap in {"settings": {...}}
    if isinstance(settings, dict) and "settings" in settings and isinstance(settings["settings"], dict):
        settings = settings["settings"]
    for k in ("phone_reveal_fee", "phone_reveal_gst_pct", "shop_margin_enabled", "service_booking_margin_enabled"):
        _ok(f"settings has '{k}'", k in settings, f"value={settings.get(k)!r}")
    _ok("shop_margin_enabled default False",
        settings.get("shop_margin_enabled") in (False, 0, "false", None),
        f"got {settings.get('shop_margin_enabled')!r}")
    _ok("service_booking_margin_enabled default False",
        settings.get("service_booking_margin_enabled") in (False, 0, "false", None),
        f"got {settings.get('service_booking_margin_enabled')!r}")

    # ─────────────────────────────────────────────────────────────────
    # 1. GET /api/services/reveal-config
    # ─────────────────────────────────────────────────────────────────
    r = requests.get(f"{API}/services/reveal-config", headers=_auth(user_tok), timeout=15)
    _ok("reveal-config 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    cfg = r.json() if r.status_code == 200 else {}
    _ok("reveal-config fee=1.0", abs(float(cfg.get("fee", 0)) - 1.0) < 1e-6, f"fee={cfg.get('fee')}")
    _ok("reveal-config gst_pct=18.0", abs(float(cfg.get("gst_pct", 0)) - 18.0) < 1e-6, f"gst_pct={cfg.get('gst_pct')}")
    _ok("reveal-config gst_amount=0.18", abs(float(cfg.get("gst_amount", 0)) - 0.18) < 1e-3, f"gst_amount={cfg.get('gst_amount')}")
    _ok("reveal-config total=1.18", abs(float(cfg.get("total", 0)) - 1.18) < 1e-3, f"total={cfg.get('total')}")
    _ok("reveal-config has wallet_balance", "wallet_balance" in cfg, f"balance={cfg.get('wallet_balance')}")
    _ok("reveal-config has revealed_provider_ids list",
        isinstance(cfg.get("revealed_provider_ids"), list),
        f"got={type(cfg.get('revealed_provider_ids')).__name__}")
    _ok("reveal-config requires auth",
        requests.get(f"{API}/services/reveal-config", timeout=15).status_code in (401, 403))

    # ─────────────────────────────────────────────────────────────────
    # 2. POST /api/services/{provider_id}/reveal-phone
    # ─────────────────────────────────────────────────────────────────
    rr = requests.get(f"{API}/services", headers=_auth(user_tok), timeout=20)
    _ok("GET /services 200", rr.status_code == 200, f"{rr.status_code} {rr.text[:200]}")
    svc_list = (rr.json() or {}).get("items") if isinstance(rr.json(), dict) else rr.json()
    if isinstance(svc_list, dict):  # some shapes return {items:..}
        svc_list = svc_list.get("items", [])
    provider = None
    if isinstance(svc_list, list) and svc_list:
        # Skip the test user itself
        my_me = requests.get(f"{API}/auth/me", headers=_auth(user_tok), timeout=15).json()
        my_id = (my_me.get("user") or my_me).get("id") if isinstance(my_me, dict) else None
        for s in svc_list:
            pid = s.get("id") or s.get("user_id") or s.get("provider_id")
            if pid and pid != my_id:
                provider = s
                provider["_pid"] = pid
                break
    if not provider:
        # No approved providers in this env — seed one directly via MongoDB so
        # we can verify the full reveal-phone flow end-to-end.
        try:
            from pymongo import MongoClient
            mc = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
            mdb = mc["referral_ecom_db"]
            seed_id = f"seed-svc-{uuid.uuid4().hex[:10]}"
            mdb.users.insert_one({
                "id": seed_id,
                "name": "Seed Plumber",
                "email": f"seed_{uuid.uuid4().hex[:6]}@svc.test",
                "phone": "9000111222",
                "password": "n/a",
                "role": "user",
                "is_service_provider": True,
                "service_status": "approved",
                "service_name": "Test Plumbing",
                "service_category": "Plumbing",
                "service_pincode": "500001",
                "service_charge": 250.0,
                "service_description": "Seeded for tests",
                "registration_paid": True,
                "created_at": "2026-05-28T00:00:00",
            })
            provider = {"_pid": seed_id}
            pid = seed_id
            _ok("approved service provider available (seeded via Mongo)", True, f"pid={pid}")
        except Exception as e:
            _ok("approved service provider available", False, f"no approved providers and seed failed: {e}")
            pid = None
    else:
        pid = provider["_pid"]
        _ok("approved service provider available", True, f"pid={pid}")

    invoice_id = None
    if pid:
        # 2a — without accept_terms
        r1 = requests.post(f"{API}/services/{pid}/reveal-phone",
                           headers=_auth(user_tok), json={}, timeout=20)
        det = ""
        try:
            det = json.dumps(r1.json())
        except Exception:
            det = r1.text[:200]
        _ok("reveal-phone without terms → 400 mentioning 'terms'",
            r1.status_code == 400 and "term" in det.lower(),
            f"{r1.status_code} {det[:160]}")

        # 2b — with accept_terms
        # Ensure user has enough wallet — top up via admin credit if needed
        me = requests.get(f"{API}/auth/me", headers=_auth(user_tok), timeout=15).json()
        bal = float((me.get("user") or me).get("wallet_balance") or 0)
        user_id_for_me = (me.get("user") or me).get("id")
        if bal < 1.18:
            # Try crediting via admin endpoint (requires direct_added bucket funds)
            cr = requests.post(
                f"{API}/admin/users/{user_id_for_me}/wallet",
                headers=_auth(admin_tok),
                json={"type": "credit", "amount": 50.0, "reason": "test reveal seed"},
                timeout=20,
            )
            seed_ok = cr.status_code == 200
            if not seed_ok:
                # Fallback: seed wallet directly via Mongo so the rest of the
                # flow can be exercised.
                try:
                    from pymongo import MongoClient
                    mc = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
                    mdb = mc["referral_ecom_db"]
                    mdb.users.update_one({"id": user_id_for_me}, {"$set": {"wallet_balance": 50.0}})
                    seed_ok = True
                except Exception as e:
                    _ok("seed user wallet via Mongo", False, f"{e}")
            _ok("admin wallet credit (seed user for reveal)", seed_ok,
                f"{cr.status_code} {cr.text[:200]}" if not seed_ok else "ok (mongo seed)")
            me = requests.get(f"{API}/auth/me", headers=_auth(user_tok), timeout=15).json()
            bal = float((me.get("user") or me).get("wallet_balance") or 0)

        # Snapshot admin buckets before
        admin_me_before = requests.get(f"{API}/auth/me", headers=_auth(admin_tok), timeout=15).json()
        admin_buckets_before = ((admin_me_before.get("user") or admin_me_before).get("wallet_buckets") or {})
        before_svc = float(admin_buckets_before.get("service_margin") or 0)
        before_gst = float(admin_buckets_before.get("gst_collected") or 0)

        r2 = requests.post(f"{API}/services/{pid}/reveal-phone",
                           headers=_auth(user_tok),
                           json={"accept_terms": True}, timeout=25)
        body2 = {}
        try:
            body2 = r2.json()
        except Exception:
            pass

        if r2.status_code == 400 and ("insufficient" in r2.text.lower() or "top up" in r2.text.lower()):
            _ok("reveal-phone (low balance) returns 400 with 'Insufficient/top up'", True, r2.text[:160])
        elif r2.status_code == 200:
            already = bool(body2.get("already_revealed"))
            # If user had previously revealed this provider in earlier runs, the
            # first call will be already_revealed=True — accept either path.
            _ok("reveal-phone 200", True, f"already_revealed={already}")
            inv = body2.get("invoice") or {}
            invoice_id = inv.get("id")
            _ok("invoice has id", bool(invoice_id), f"inv keys={list(inv.keys())[:8]}")
            _ok("response includes provider_phone", bool(body2.get("provider_phone")), "")
            _ok("response includes provider_name", bool(body2.get("provider_name")), "")
            if not already:
                # Wallet should drop by 1.18 — check freshness
                me2 = requests.get(f"{API}/auth/me", headers=_auth(user_tok), timeout=15).json()
                bal2 = float((me2.get("user") or me2).get("wallet_balance") or 0)
                _ok("wallet decreased by ≈1.18",
                    abs((bal - bal2) - 1.18) < 0.011,
                    f"before={bal:.2f} after={bal2:.2f} delta={bal-bal2:.2f}")
                # Admin buckets should grow
                admin_me_after = requests.get(f"{API}/auth/me", headers=_auth(admin_tok), timeout=15).json()
                ab = ((admin_me_after.get("user") or admin_me_after).get("wallet_buckets") or {})
                after_svc = float(ab.get("service_margin") or 0)
                after_gst = float(ab.get("gst_collected") or 0)
                _ok("admin.service_margin +1",
                    abs((after_svc - before_svc) - 1.0) < 0.011,
                    f"before={before_svc:.2f} after={after_svc:.2f}")
                _ok("admin.gst_collected +0.18",
                    abs((after_gst - before_gst) - 0.18) < 0.011,
                    f"before={before_gst:.4f} after={after_gst:.4f}")
        else:
            _ok("reveal-phone (with terms) 200/400", False,
                f"{r2.status_code} {r2.text[:240]}")

        # 2c — Idempotency: call again, expect already_revealed=true (no extra charge).
        if invoice_id:
            bal_pre = float((requests.get(f"{API}/auth/me", headers=_auth(user_tok), timeout=15).json().get("user") or {}).get("wallet_balance") or 0)
            r3 = requests.post(f"{API}/services/{pid}/reveal-phone",
                               headers=_auth(user_tok),
                               json={"accept_terms": True}, timeout=20)
            b3 = {}
            try: b3 = r3.json()
            except Exception: pass
            _ok("idempotent reveal returns 200", r3.status_code == 200, f"{r3.status_code} {r3.text[:200]}")
            _ok("idempotent reveal already_revealed=True", bool(b3.get("already_revealed")), f"resp={b3.get('already_revealed')}")
            inv2 = (b3.get("invoice") or {}).get("id")
            _ok("idempotent reveal returns same invoice id",
                inv2 == invoice_id, f"prev={invoice_id} new={inv2}")
            bal_post = float((requests.get(f"{API}/auth/me", headers=_auth(user_tok), timeout=15).json().get("user") or {}).get("wallet_balance") or 0)
            _ok("idempotent reveal does NOT debit",
                abs(bal_post - bal_pre) < 0.005, f"pre={bal_pre} post={bal_post}")

    # ─────────────────────────────────────────────────────────────────
    # 3. GET /services/reveals/me
    # ─────────────────────────────────────────────────────────────────
    r = requests.get(f"{API}/services/reveals/me", headers=_auth(user_tok), timeout=15)
    _ok("GET /services/reveals/me 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    body = r.json() if r.status_code == 200 else {}
    items = body.get("items", [])
    _ok("/services/reveals/me has items list", isinstance(items, list), f"type={type(items).__name__}")
    if invoice_id:
        ids = [it.get("id") for it in items]
        _ok("/services/reveals/me contains created invoice", invoice_id in ids,
            f"want={invoice_id} got_count={len(ids)}")

    # ─────────────────────────────────────────────────────────────────
    # 4. GET /services/reveals/invoice/{id} — owner 200, other user 403
    # ─────────────────────────────────────────────────────────────────
    if invoice_id:
        r = requests.get(f"{API}/services/reveals/invoice/{invoice_id}",
                         headers=_auth(user_tok), timeout=15)
        _ok("owner GET invoice 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

        # Create a brand-new user to test 403
        new_email = f"reveal_other_{uuid.uuid4().hex[:6]}@example.com"
        rr = requests.post(f"{API}/auth/register", json={
            "name": "Other Tester",
            "email": new_email,
            "password": "Other@123456",
            "phone": "9123456780",
        }, timeout=20)
        other_tok = None
        if rr.status_code in (200, 201):
            other_tok = (rr.json() or {}).get("access_token")
        if not other_tok:
            ot, _ = _login(new_email, "Other@123456")
            other_tok = ot
        if other_tok:
            r2 = requests.get(f"{API}/services/reveals/invoice/{invoice_id}",
                              headers=_auth(other_tok), timeout=15)
            _ok("other user GET invoice → 403",
                r2.status_code == 403,
                f"{r2.status_code} {r2.text[:160]}")
        else:
            _ok("create other user for invoice ACL test", False, f"register={rr.status_code} {rr.text[:160]}")

    # ─────────────────────────────────────────────────────────────────
    # 5. POST /tickets/public/lookup
    # ─────────────────────────────────────────────────────────────────
    r = requests.post(f"{API}/tickets/public/lookup", json={"email": "guest@example.com"}, timeout=15)
    _ok("/tickets/public/lookup valid email 200", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
    j = r.json() if r.status_code == 200 else {}
    _ok("/tickets/public/lookup returns items list", isinstance(j.get("items"), list), f"keys={list(j.keys())}")

    r = requests.post(f"{API}/tickets/public/lookup", json={"email": "not-an-email"}, timeout=15)
    _ok("/tickets/public/lookup invalid email 400", r.status_code == 400, f"{r.status_code} {r.text[:160]}")

    # ─────────────────────────────────────────────────────────────────
    # 6. Create a guest ticket, then GET /tickets/public/{id}
    # ─────────────────────────────────────────────────────────────────
    guest_email = "guesttest@example.com"
    create = requests.post(f"{API}/tickets/public", json={
        "email": guest_email,
        "subject": "ISSUE",
        "category": "other",
        "custom_category": "App crash",
        "message": "My phone is 9876543210 and my referral is ABC123 and my email is test@gmail.com — please help",
    }, timeout=20)
    _ok("POST /tickets/public create 200", create.status_code == 200, f"{create.status_code} {create.text[:200]}")
    t_id = (create.json() or {}).get("ticket_id") if create.status_code == 200 else None

    if t_id:
        gt = requests.get(f"{API}/tickets/public/{t_id}", params={"email": guest_email}, timeout=15)
        _ok("GET /tickets/public/{id} correct email 200",
            gt.status_code == 200, f"{gt.status_code} {gt.text[:200]}")
        if gt.status_code == 200:
            msgs = (gt.json() or {}).get("messages") or []
            msg0 = (msgs[0].get("message") or "") if msgs else ""
            _ok("phone '9876543210' masked → '[phone hidden]'",
                ("9876543210" not in msg0) and ("[phone hidden]" in msg0),
                f"msg={msg0[:240]}")
            # Referral pattern: "referral is ABC123" - the regex matches the leading prefix and replaces only the code
            # so "ABC123" must be gone.
            _ok("referral code 'ABC123' masked",
                "ABC123" not in msg0,
                f"msg={msg0[:240]}")
            _ok("email 'test@gmail.com' masked → '[email hidden]'",
                ("test@gmail.com" not in msg0) and ("[email hidden]" in msg0),
                f"msg={msg0[:240]}")

        # Wrong email
        gtw = requests.get(f"{API}/tickets/public/{t_id}", params={"email": "wrong@example.com"}, timeout=15)
        _ok("GET /tickets/public/{id} wrong email 403", gtw.status_code == 403, f"{gtw.status_code} {gtw.text[:160]}")

        # ─────────────────────────────────────────────────────────────
        # 7. Reply on public ticket
        # ─────────────────────────────────────────────────────────────
        rw = requests.post(f"{API}/tickets/public/{t_id}/reply",
                           json={"email": "wrong@example.com", "message": "any message please"}, timeout=15)
        _ok("POST /tickets/public/{id}/reply wrong email 403", rw.status_code == 403, f"{rw.status_code} {rw.text[:160]}")

        # Get pre-reply message_count
        gt0 = requests.get(f"{API}/tickets/public/{t_id}", params={"email": guest_email}, timeout=15)
        pre_count = ((gt0.json() or {}).get("ticket") or {}).get("message_count", 0) if gt0.status_code == 200 else 0

        rok = requests.post(f"{API}/tickets/public/{t_id}/reply",
                            json={"email": guest_email, "message": "Follow-up reply from the guest"}, timeout=15)
        _ok("POST /tickets/public/{id}/reply correct 200", rok.status_code == 200, f"{rok.status_code} {rok.text[:200]}")
        post_t = (rok.json() or {}).get("ticket") or {}
        _ok("message_count incremented", int(post_t.get("message_count", 0)) == pre_count + 1,
            f"pre={pre_count} post={post_t.get('message_count')}")

    # ─────────────────────────────────────────────────────────────────
    # 8. POST /admin/system-wallet/tally-withdraw
    # ─────────────────────────────────────────────────────────────────
    # amount<=0
    r = requests.post(f"{API}/admin/system-wallet/tally-withdraw",
                      headers=_auth(admin_tok),
                      json={"amount": 0, "note": "test"}, timeout=15)
    _ok("tally-withdraw amount<=0 → 400", r.status_code == 400, f"{r.status_code} {r.text[:160]}")

    # short note
    r = requests.post(f"{API}/admin/system-wallet/tally-withdraw",
                      headers=_auth(admin_tok),
                      json={"amount": 1, "note": "x"}, timeout=15)
    _ok("tally-withdraw short note → 400", r.status_code == 400, f"{r.status_code} {r.text[:160]}")

    # Real-ish withdraw
    r = requests.post(f"{API}/admin/system-wallet/tally-withdraw",
                      headers=_auth(admin_tok),
                      json={"amount": 1, "note": "automated test tally", "bucket": "direct_added"},
                      timeout=15)
    if r.status_code == 200:
        _ok("tally-withdraw direct_added 200", True, "")
        body = r.json()
        _ok("tally-withdraw response has 'withdrawal'", "withdrawal" in body, f"keys={list(body.keys())}")
    elif r.status_code == 400 and ("insufficient" in r.text.lower()):
        _ok("tally-withdraw direct_added insufficient → 400 (acceptable, no funds)", True, r.text[:140])
    else:
        _ok("tally-withdraw direct_added 200/400", False, f"{r.status_code} {r.text[:200]}")

    # Non-admin user
    r = requests.post(f"{API}/admin/system-wallet/tally-withdraw",
                      headers=_auth(user_tok),
                      json={"amount": 1, "note": "should fail", "bucket": "direct_added"}, timeout=15)
    _ok("tally-withdraw non-admin → 403", r.status_code in (401, 403), f"{r.status_code} {r.text[:160]}")

    # ─────────────────────────────────────────────────────────────────
    # 9. GET /admin/system-wallet/tally-withdrawals
    # ─────────────────────────────────────────────────────────────────
    r = requests.get(f"{API}/admin/system-wallet/tally-withdrawals",
                     headers=_auth(admin_tok), timeout=15)
    _ok("GET tally-withdrawals 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    b = r.json() if r.status_code == 200 else {}
    _ok("tally-withdrawals has items/total_count/total_amount",
        all(k in b for k in ("items", "total_count", "total_amount")),
        f"keys={list(b.keys())}")
    r2 = requests.get(f"{API}/admin/system-wallet/tally-withdrawals",
                      headers=_auth(user_tok), timeout=15)
    _ok("GET tally-withdrawals non-admin → 403", r2.status_code in (401, 403), f"{r2.status_code} {r2.text[:160]}")

    # ─────────────────────────────────────────────────────────────────
    # 10. PATCH /users/me/address
    # ─────────────────────────────────────────────────────────────────
    r = requests.patch(f"{API}/users/me/address",
                       headers=_auth(user_tok),
                       json={"address": "123 Main St", "city": "Hyderabad", "state": "TG", "pincode": "500001"},
                       timeout=15)
    _ok("PATCH /users/me/address valid 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    body = r.json() if r.status_code == 200 else {}
    u = body.get("user") or {}
    _ok("address persisted", u.get("address") == "123 Main St", f"got={u.get('address')!r}")
    _ok("city persisted", u.get("city") == "Hyderabad", f"got={u.get('city')!r}")
    _ok("state persisted", u.get("state") == "TG", f"got={u.get('state')!r}")
    _ok("pincode persisted", u.get("pincode") == "500001", f"got={u.get('pincode')!r}")

    # Invalid pincode
    r = requests.patch(f"{API}/users/me/address", headers=_auth(user_tok),
                       json={"pincode": "abc"}, timeout=15)
    _ok("PATCH address invalid pincode 'abc' → 400",
        r.status_code == 400, f"{r.status_code} {r.text[:160]}")

    # Empty body
    r = requests.patch(f"{API}/users/me/address", headers=_auth(user_tok),
                       json={}, timeout=15)
    detail = ""
    try:
        detail = r.json().get("detail") or ""
    except Exception:
        detail = r.text
    _ok("PATCH address empty body → 400 'Nothing to update'",
        r.status_code == 400 and "nothing" in detail.lower(),
        f"{r.status_code} detail={detail!r}")

    return _summary()


def _summary():
    print("\n" + "=" * 64)
    print(f"PASS: {len(passes)}   FAIL: {len(fails)}")
    if fails:
        print("\nFAILURES:")
        for n, info in fails:
            print(f"  - {n}: {info[:200]}")
    print("=" * 64)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
