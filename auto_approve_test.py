"""End-to-end test for the /payment/verify auto-approval pipeline.

Covers scenarios A..I from the review request:
  A. Auto-approve happy path (valid HMAC)
  B. Commission cascade fired
  C. Second verify attempt -> 400
  D. Invalid signature -> 401
  E. Auto-approve toggle OFF
  F. Approved-registrations list (role_filter=auto)
  G. Edge: missing fields -> 400
  H. Regression: manual approve, withdrawals digest, branding, admin login
  I. Cleanup

Runs against the public REACT_APP_BACKEND_URL (from /app/frontend/.env).
"""
import hmac
import hashlib
import os
import random
import secrets
import string
import sys
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from dotenv import dotenv_values

# ---------- Config ----------
FRONT_ENV = dotenv_values("/app/frontend/.env")
BASE = (FRONT_ENV.get("EXPO_PUBLIC_BACKEND_URL") or FRONT_ENV.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE}/api"

BACK_ENV = dotenv_values("/app/backend/.env")
RZP_KEY_SECRET = (BACK_ENV.get("RAZORPAY_KEY_SECRET") or "").strip()
RZP_KEY_ID = (BACK_ENV.get("RAZORPAY_KEY_ID") or "").strip()

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

assert BASE, "Missing backend URL"
assert RZP_KEY_SECRET, "Missing RAZORPAY_KEY_SECRET"

print(f"API  : {API}")
print(f"RZP  : key_id={RZP_KEY_ID[:12]}… secret set={bool(RZP_KEY_SECRET)}")

# ---------- Results ----------
RESULTS: list = []
def check(label: str, ok: bool, detail: str = "") -> bool:
    tag = "PASS" if ok else "FAIL"
    RESULTS.append((ok, label, detail))
    print(f"[{tag}] {label}" + (f"  — {detail}" if detail else ""))
    return ok


# ---------- HTTP helpers ----------
client = httpx.Client(timeout=30.0, follow_redirects=False)


def hdr(token: Optional[str]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def rand_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def login(email: str, password: str) -> str:
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login {email} failed: {r.status_code} {r.text}"
    return r.json()["token"]


def register(name: str, email: str, password: str, referral_code: str) -> Tuple[str, str]:
    r = client.post(
        f"{API}/auth/register",
        json={
            "name": name,
            "email": email,
            "password": password,
            "phone": "9" + "".join(random.choices(string.digits, k=9)),
            "referral_code": referral_code,
        },
    )
    assert r.status_code == 200, f"Register {email} failed: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]["id"]


def me(token: str) -> Dict[str, Any]:
    r = client.get(f"{API}/auth/me", headers=hdr(token))
    assert r.status_code == 200, f"/auth/me failed: {r.status_code} {r.text}"
    return r.json()


def create_order(user_token: str) -> Dict[str, Any]:
    r = client.post(f"{API}/payment/create-order", headers=hdr(user_token))
    assert r.status_code == 200, f"create-order failed: {r.status_code} {r.text}"
    return r.json()


def hmac_sig(order_id: str, pay_id: str) -> str:
    return hmac.new(
        RZP_KEY_SECRET.encode(),
        f"{order_id}|{pay_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def verify(user_token: str, order_id: str, pay_id: str, sig: str) -> httpx.Response:
    return client.post(
        f"{API}/payment/verify",
        headers=hdr(user_token),
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
        },
    )


def admin_users(admin_token: str, **params) -> list:
    r = client.get(f"{API}/admin/users", headers=hdr(admin_token), params=params)
    assert r.status_code == 200, f"/admin/users failed: {r.text}"
    data = r.json()
    return data if isinstance(data, list) else data.get("users") or data.get("items") or []


# ---------- Scenario SETUP: admin login + admin referral code ----------
print("\n=== SETUP ===")
admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
check("admin login 200", True)

# Fetch admin's referral code via /admin/users
users_list = admin_users(admin_token)
admin_user = next((u for u in users_list if (u.get("email") or "").lower() == ADMIN_EMAIL), None)
assert admin_user, "admin user not found in /admin/users list"
ADMIN_REF = admin_user.get("referral_code") or "ADMIN001"
print(f"Admin referral_code = {ADMIN_REF}, admin.id = {admin_user.get('id')}")

# Snapshot sponsor (admin) direct_referrals_count BEFORE the test
pre_admin_direct = int(admin_user.get("direct_referrals_count") or 0)
print(f"Admin direct_referrals_count (pre) = {pre_admin_direct}")


# ---------- Helpers to notify cleanup ----------
cleanup_user_ids: list = []

def admin_delete_user(uid: str) -> None:
    try:
        r = client.delete(f"{API}/admin/users/{uid}", headers=hdr(admin_token))
        print(f"  cleanup: delete user {uid} -> {r.status_code}")
    except Exception as e:
        print(f"  cleanup: delete user {uid} failed {e}")


def admin_delete_approved_for_user(email: str) -> None:
    """Find approved_registrations records for this email and delete them."""
    try:
        r = client.get(
            f"{API}/admin/approved-registrations",
            headers=hdr(admin_token),
            params={"search": email, "limit": 50},
        )
        if r.status_code == 200:
            for rec in r.json().get("items", []):
                rid = rec.get("id")
                if rid:
                    dr = client.delete(f"{API}/admin/approved-registrations/{rid}", headers=hdr(admin_token))
                    print(f"  cleanup: delete approved_reg {rid} -> {dr.status_code}")
    except Exception as e:
        print(f"  cleanup approved_reg for {email} failed: {e}")


# =========================================================
# SCENARIO A: AUTO-APPROVE HAPPY PATH
# =========================================================
print("\n=== A. AUTO-APPROVE HAPPY PATH (valid HMAC) ===")
u1_email = f"u1.autoapprove.{rand_suffix()}@example.com"
u1_name = "Priya Auto"
u1_token, u1_id = register(u1_name, u1_email, "Passw0rd!", ADMIN_REF)
cleanup_user_ids.append(u1_id)
check("A.0 register U1", True, f"id={u1_id}")

order = create_order(u1_token)
u1_order_id = order["order_id"]
check(
    "A.1 create-order returns live order_id",
    isinstance(u1_order_id, str) and u1_order_id.startswith("order_") and not u1_order_id.startswith("order_MOCK_"),
    f"order_id={u1_order_id} is_mock={order.get('is_mock')}",
)

u1_pay_id = f"pay_test_{secrets.token_hex(6)}"
u1_sig = hmac_sig(u1_order_id, u1_pay_id)
resp = verify(u1_token, u1_order_id, u1_pay_id, u1_sig)
check("A.2 /payment/verify -> 200", resp.status_code == 200, f"status={resp.status_code} body={resp.text[:200]}")
body = resp.json() if resp.status_code == 200 else {}
check("A.3 approval_status == approved", body.get("approval_status") == "approved", str(body.get("approval_status")))
check("A.4 auto_approved == True", body.get("auto_approved") is True, str(body.get("auto_approved")))
check("A.5 utr matches pay_id (no Razorpay hit for pay_test_)", body.get("utr") == u1_pay_id, f"utr={body.get('utr')}")
check("A.6 rzp_status == signature_only", body.get("rzp_status") == "signature_only", str(body.get("rzp_status")))

u1_me = me(u1_token)
check("A.7 /auth/me registration_paid=True", u1_me.get("registration_paid") is True)
check("A.8 /auth/me approval_status=approved", u1_me.get("approval_status") == "approved", str(u1_me.get("approval_status")))
check("A.9 /auth/me razorpay_utr==pay_id", u1_me.get("razorpay_utr") == u1_pay_id, str(u1_me.get("razorpay_utr")))
check("A.10 /auth/me approval_reviewed_by=='auto'", u1_me.get("approval_reviewed_by") == "auto", str(u1_me.get("approval_reviewed_by")))

# Notification check
notifs = client.get(f"{API}/notifications/me", headers=hdr(u1_token)).json()
items = notifs if isinstance(notifs, list) else notifs.get("items") or []
auto_note = next((n for n in items if "approved automatically" in (n.get("title") or "").lower()), None)
check("A.11 notification 'Account approved automatically' delivered", bool(auto_note), str(auto_note)[:200] if auto_note else "missing")

# Approved_registrations archive
ar = client.get(f"{API}/admin/approved-registrations", headers=hdr(admin_token), params={"role_filter": "auto", "search": u1_email})
ar_data = ar.json() if ar.status_code == 200 else {}
ar_items = ar_data.get("items", []) if isinstance(ar_data, dict) else []
u1_arch = next((r for r in ar_items if r.get("original_user_id") == u1_id), None)
check("A.12 approved_registrations has U1", bool(u1_arch), f"found={bool(u1_arch)}")
if u1_arch:
    check("A.13 auto_approved=true on archive", u1_arch.get("auto_approved") is True, str(u1_arch.get("auto_approved")))
    check("A.14 approver_role=='auto'", u1_arch.get("approver_role") == "auto", str(u1_arch.get("approver_role")))
    check("A.15 approver_email=='system@auto-approval'", u1_arch.get("approver_email") == "system@auto-approval", str(u1_arch.get("approver_email")))

# Audit log
al = client.get(f"{API}/admin/audit-logs", headers=hdr(admin_token), params={"limit": 200})
if al.status_code == 200:
    al_items = al.json() if isinstance(al.json(), list) else al.json().get("items") or al.json().get("logs") or []
    auto_log = next((x for x in al_items if x.get("action") == "user.auto_approve" and x.get("target_id") == u1_id), None)
    check("A.16 audit-log user.auto_approve exists", bool(auto_log), str((auto_log or {}).get("details"))[:150])
    if auto_log:
        d = auto_log.get("details") or {}
        check("A.17 audit details include utr,rzp_status,amount",
              d.get("utr") == u1_pay_id and d.get("rzp_status") == "signature_only" and "amount" in d,
              str(d))
else:
    check("A.16 audit-log endpoint reachable", False, f"{al.status_code} {al.text[:120]}")


# =========================================================
# SCENARIO B: COMMISSION CASCADE
# =========================================================
print("\n=== B. COMMISSION CASCADE FIRED ===")
# Re-fetch admin doc
users_list2 = admin_users(admin_token)
admin_user2 = next((u for u in users_list2 if (u.get("email") or "").lower() == ADMIN_EMAIL), {})
post_admin_direct = int(admin_user2.get("direct_referrals_count") or 0)
check(
    "B.1 admin direct_referrals_count incremented by 1",
    post_admin_direct == pre_admin_direct + 1,
    f"pre={pre_admin_direct} post={post_admin_direct}",
)

# Admin notification
admin_notifs = client.get(f"{API}/notifications/me", headers=hdr(admin_token)).json()
admin_items = admin_notifs if isinstance(admin_notifs, list) else admin_notifs.get("items") or []
ref_note = next(
    (n for n in admin_items if "new referral" in (n.get("title") or "").lower() and u1_name in (n.get("title") or "")),
    None,
)
check("B.2 admin received 'New referral' notification", bool(ref_note), str((ref_note or {}).get("title")))

# L1 payout may fire if post_admin_direct % directs_required == 0. Check transactions for referral_payout
# We can't know directs_required from outside, but we can check settings via /admin/settings
settings_r = client.get(f"{API}/admin/settings", headers=hdr(admin_token))
settings = settings_r.json() if settings_r.status_code == 200 else {}
directs_required = int(settings.get("directs_required") or 0)
payout_l1 = float(settings.get("payout_l1") or 0)
print(f"  settings: directs_required={directs_required}, payout_l1={payout_l1}")
if directs_required and payout_l1 > 0 and post_admin_direct % directs_required == 0:
    # A referral_payout should have been credited to admin
    # Fetch admin transactions via /admin/transactions?user_id= maybe not. Try /transactions/me as admin
    tx_r = client.get(f"{API}/transactions/me", headers=hdr(admin_token))
    tx = tx_r.json() if tx_r.status_code == 200 else []
    tx_items = tx if isinstance(tx, list) else tx.get("items") or []
    pay_tx = [t for t in tx_items if t.get("type") == "referral_payout" and float(t.get("amount") or 0) > 0]
    check(
        "B.3 (L1 qualifier met) referral_payout transaction present for admin",
        len(pay_tx) >= 1,
        f"found={len(pay_tx)} post_direct={post_admin_direct} req={directs_required}",
    )
else:
    print(f"  B.3 L1 payout not due this cycle (post={post_admin_direct}, req={directs_required}, l1={payout_l1}) — skipped")


# =========================================================
# SCENARIO C: SECOND VERIFY ATTEMPT
# =========================================================
print("\n=== C. SECOND VERIFY ATTEMPT ===")
r2 = verify(u1_token, u1_order_id, u1_pay_id, u1_sig)
check("C.1 second /payment/verify -> 400", r2.status_code == 400, f"status={r2.status_code} body={r2.text[:200]}")
check("C.2 detail=='Registration fee already paid'", "already paid" in (r2.text or "").lower(), r2.text[:200])


# =========================================================
# SCENARIO D: INVALID SIGNATURE
# =========================================================
print("\n=== D. INVALID SIGNATURE ===")
u2_email = f"u2.badsig.{rand_suffix()}@example.com"
u2_token, u2_id = register("Rahul Badsig", u2_email, "Passw0rd!", ADMIN_REF)
cleanup_user_ids.append(u2_id)
order2 = create_order(u2_token)
u2_order_id = order2["order_id"]
u2_pay_id = f"pay_test_{secrets.token_hex(6)}"
r_bad = verify(u2_token, u2_order_id, u2_pay_id, "bad_sig")
check("D.1 invalid sig -> 401", r_bad.status_code == 401, f"status={r_bad.status_code} body={r_bad.text[:200]}")
check("D.2 detail=='Invalid payment signature'", "invalid payment signature" in (r_bad.text or "").lower(), r_bad.text[:200])
u2_me = me(u2_token)
check("D.3 U2 registration_paid still False", u2_me.get("registration_paid") is False, str(u2_me.get("registration_paid")))
check("D.4 U2 approval_status still pending", u2_me.get("approval_status") == "pending", str(u2_me.get("approval_status")))


# =========================================================
# SCENARIO E: AUTO-APPROVE TOGGLE OFF
# =========================================================
print("\n=== E. AUTO-APPROVE TOGGLE OFF ===")
set_off = client.put(
    f"{API}/admin/settings",
    headers=hdr(admin_token),
    json={"auto_approve_on_payment": False},
)
check("E.1 PUT /admin/settings auto_approve_on_payment=false -> 200",
      set_off.status_code == 200,
      f"status={set_off.status_code} body={set_off.text[:200]}")
settings_after = set_off.json() if set_off.status_code == 200 else {}
check("E.2 settings reflect auto_approve_on_payment=False",
      settings_after.get("auto_approve_on_payment") is False,
      f"value={settings_after.get('auto_approve_on_payment')}")

u3_email = f"u3.toggle.{rand_suffix()}@example.com"
u3_token, u3_id = register("Sneha Toggle", u3_email, "Passw0rd!", ADMIN_REF)
cleanup_user_ids.append(u3_id)
order3 = create_order(u3_token)
u3_order_id = order3["order_id"]
u3_pay_id = f"pay_test_{secrets.token_hex(6)}"
u3_sig = hmac_sig(u3_order_id, u3_pay_id)
r3 = verify(u3_token, u3_order_id, u3_pay_id, u3_sig)
check("E.3 U3 /payment/verify -> 200", r3.status_code == 200, f"status={r3.status_code} body={r3.text[:200]}")
b3 = r3.json() if r3.status_code == 200 else {}
check("E.4 approval_status=='pending' when toggle off", b3.get("approval_status") == "pending", str(b3.get("approval_status")))
check("E.5 auto_approved==False when toggle off", b3.get("auto_approved") is False, str(b3.get("auto_approved")))

u3_me = me(u3_token)
check("E.6 U3 /auth/me approval_status=='pending'", u3_me.get("approval_status") == "pending", str(u3_me.get("approval_status")))
check("E.7 U3 razorpay_utr still set", bool(u3_me.get("razorpay_utr")), str(u3_me.get("razorpay_utr")))
check("E.8 U3 registration_paid==True", u3_me.get("registration_paid") is True, str(u3_me.get("registration_paid")))

# Manual approve still works
r_man = client.post(f"{API}/admin/approvals/{u3_id}/approve", headers=hdr(admin_token))
check("E.9 manual POST /admin/approvals/{u3}/approve -> 200", r_man.status_code == 200, f"status={r_man.status_code} body={r_man.text[:200]}")
u3_me2 = me(u3_token)
check("E.10 U3 approval_status=='approved' after manual", u3_me2.get("approval_status") == "approved", str(u3_me2.get("approval_status")))

# Reset toggle back to True
set_on = client.put(
    f"{API}/admin/settings",
    headers=hdr(admin_token),
    json={"auto_approve_on_payment": True},
)
check("E.11 PUT /admin/settings auto_approve_on_payment=true -> 200",
      set_on.status_code == 200,
      f"status={set_on.status_code} body={set_on.text[:200]}")
settings_reset = set_on.json() if set_on.status_code == 200 else {}
check("E.12 settings reflect auto_approve_on_payment=True",
      settings_reset.get("auto_approve_on_payment") is True,
      f"value={settings_reset.get('auto_approve_on_payment')}")


# =========================================================
# SCENARIO F: APPROVED_REGISTRATIONS LIST
# =========================================================
print("\n=== F. APPROVED_REGISTRATIONS LIST ===")
f_auto = client.get(f"{API}/admin/approved-registrations", headers=hdr(admin_token), params={"role_filter": "auto"})
check("F.1 GET /admin/approved-registrations?role_filter=auto -> 200", f_auto.status_code == 200, f_auto.text[:120])
if f_auto.status_code == 200:
    data = f_auto.json()
    counts = data.get("counts") or {}
    items_f = data.get("items") or []
    check("F.2 counts.auto >= 1", int(counts.get("auto") or 0) >= 1, str(counts))
    has_u1 = any(r.get("original_user_id") == u1_id for r in items_f)
    check("F.3 items contain U1", has_u1, f"items={len(items_f)}")

# Check U3 archived under super_admin role
f_sa = client.get(f"{API}/admin/approved-registrations", headers=hdr(admin_token), params={"role_filter": "super_admin", "search": u3_email})
if f_sa.status_code == 200:
    items_sa = f_sa.json().get("items") or []
    has_u3 = any(r.get("original_user_id") == u3_id for r in items_sa)
    check("F.4 items under super_admin include U3", has_u3, f"items={len(items_sa)}")


# =========================================================
# SCENARIO G: EDGE CASES — missing fields
# =========================================================
print("\n=== G. EDGE CASES ===")
# Need an unpaid user for this test; create U4
u4_email = f"u4.edge.{rand_suffix()}@example.com"
u4_token, u4_id = register("Edge Case", u4_email, "Passw0rd!", ADMIN_REF)
cleanup_user_ids.append(u4_id)

r_miss = client.post(
    f"{API}/payment/verify",
    headers=hdr(u4_token),
    json={"razorpay_order_id": "", "razorpay_payment_id": "", "razorpay_signature": ""},
)
# FastAPI Pydantic may 422 if required fields missing; the handler uses empty-string checks -> 400 "Missing Razorpay fields".
check("G.1 missing fields -> 400 Missing Razorpay fields",
      r_miss.status_code == 400 and "missing razorpay fields" in (r_miss.text or "").lower(),
      f"status={r_miss.status_code} body={r_miss.text[:200]}")


# =========================================================
# SCENARIO H: REGRESSION
# =========================================================
print("\n=== H. REGRESSION ===")
# Manual approve path already covered E.9.
digest = client.get(f"{API}/admin/withdrawals/digest", headers=hdr(admin_token))
check("H.1 /admin/withdrawals/digest 200", digest.status_code == 200, f"status={digest.status_code} body={digest.text[:120]}")
brand = client.get(f"{API}/branding")
check("H.2 /branding 200", brand.status_code == 200, f"status={brand.status_code} body={brand.text[:120]}")
al2 = client.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
check("H.3 admin login still 200", al2.status_code == 200, f"status={al2.status_code}")


# =========================================================
# I. CLEANUP
# =========================================================
print("\n=== I. CLEANUP ===")
for uid in cleanup_user_ids:
    admin_delete_user(uid)
for em in [u1_email, u2_email, u3_email]:
    admin_delete_approved_for_user(em)

# Final toggle restore confirmation
final_settings = client.get(f"{API}/admin/settings", headers=hdr(admin_token)).json()
check("I.1 final auto_approve_on_payment is True", final_settings.get("auto_approve_on_payment") is True,
      f"value={final_settings.get('auto_approve_on_payment')}")


# ---------- Summary ----------
print("\n==================== SUMMARY ====================")
total = len(RESULTS)
passed = sum(1 for ok, *_ in RESULTS if ok)
failed = total - passed
print(f"PASSED: {passed}/{total}   FAILED: {failed}")
if failed:
    print("\nFailures:")
    for ok, label, detail in RESULTS:
        if not ok:
            print(f"  - {label}   {detail}")

sys.exit(0 if failed == 0 else 1)
