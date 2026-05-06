"""
Razorpay verify UTR-required behavior fix — backend test.

Scenarios:
  D — Code review (lines around _extract_utr and verify endpoint).
  B — LIVE mode, payment without real UTR → no auto-approve, no commission cascade.
  C — Manual admin approval still triggers commissions.
  A — Mock mode behavior preserved (informational/code-review only if LIVE keys configured).

BASE: https://network-pay-1.preview.emergentagent.com
"""
import hmac
import hashlib
import secrets
import sys
from typing import Dict, Any, List, Optional, Tuple

import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

ENV_KEY_ID = "rzp_test_SjgtHA4CxiFyTK"
ENV_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

session = requests.Session()


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _login(email: str, password: str) -> str:
    r = session.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return r.json()["token"]


def _get_admin() -> Tuple[str, Dict[str, Any]]:
    tok = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    r = session.get(f"{BASE}/auth/me", headers=_headers(tok), timeout=20)
    assert r.status_code == 200, r.text
    return tok, r.json()


def _admin_users(token: str) -> List[Dict[str, Any]]:
    r = session.get(f"{BASE}/admin/users", headers=_headers(token), timeout=30)
    assert r.status_code == 200, r.text
    items = r.json()
    return items if isinstance(items, list) else (items.get("items") or items.get("users") or [])


def _find_user_by_id(token: str, uid: str) -> Optional[Dict[str, Any]]:
    for u in _admin_users(token):
        if u.get("id") == uid:
            return u
    return None


def _delete_user(token: str, user_id: str) -> bool:
    r = session.delete(f"{BASE}/admin/users/{user_id}", headers=_headers(token), timeout=20)
    return r.status_code in (200, 204, 404)


def code_review_d() -> Tuple[bool, List[str]]:
    notes: List[str] = []
    src = open("/app/backend/server.py", "r").read()

    # 1) _extract_utr should NOT include payment_id fallback
    idx = src.find("def _extract_utr(")
    assert idx > 0, "_extract_utr not found"
    end = src.find("\n\n\n", idx)
    block = src[idx: end if end > 0 else idx + 1500]
    bad = ('rzp_payment.get("id")' in block) or ("rzp_payment.get('id')" in block)
    if bad:
        return False, notes + ["FAIL: _extract_utr still falls back to rzp_payment.id"]
    notes.append("OK: _extract_utr does NOT fall back to rzp_payment.id")

    if "has_real_utr = bool(utr)" not in src:
        return False, notes + ["FAIL: 'has_real_utr = bool(utr)' missing"]
    notes.append("OK: has_real_utr flag present")

    if 'creds["is_mock"] or has_real_utr' not in src and "creds['is_mock'] or has_real_utr" not in src:
        return False, notes + ["FAIL: auto_approve does not gate on (creds.is_mock or has_real_utr)"]
    notes.append("OK: auto_approve gates on (creds.is_mock or has_real_utr)")

    if "awaiting bank-side UTR confirmation" not in src:
        return False, notes + ["FAIL: pending notification missing 'awaiting bank-side UTR confirmation'"]
    notes.append("OK: pending notification mentions 'awaiting bank-side UTR confirmation'")

    return True, notes


def _gateway_source(admin_tok: str) -> Dict[str, Any]:
    r = session.get(f"{BASE}/admin/payment-gateway", headers=_headers(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _register_user(prefix: str = "utrtest") -> Tuple[str, Dict[str, Any]]:
    rand = secrets.token_hex(4)
    payload = {
        "name": f"UTR Bug Test {rand}",
        "email": f"{prefix}.{rand}@mailinator.com",
        "phone": f"9{secrets.randbelow(10**9):09d}",
        "password": "TestPass@123",
        "referral_code": "EARN",
        "pan": "ABCDE1234F",
    }
    r = session.post(f"{BASE}/auth/register", json=payload, timeout=20)
    assert r.status_code == 200, f"Register failed: {r.status_code} {r.text}"
    j = r.json()
    return j["token"], j["user"]


def _create_order(user_tok: str) -> Dict[str, Any]:
    r = session.post(f"{BASE}/payment/create-order", headers=_headers(user_tok), timeout=30)
    assert r.status_code == 200, f"create-order failed: {r.status_code} {r.text}"
    return r.json()


def _hmac_sig(order_id: str, payment_id: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def _user_transactions(admin_tok: str, user_id: str) -> List[Dict[str, Any]]:
    r = session.get(f"{BASE}/admin/transactions", headers=_headers(admin_tok),
                    params={"user_id": user_id, "limit": 200}, timeout=30)
    if r.status_code != 200:
        return []
    j = r.json()
    items = j if isinstance(j, list) else (j.get("items") or [])
    return [tx for tx in items if tx.get("user_id") == user_id]


def scenario_b(admin_tok: str, admin_user: Dict[str, Any], gw: Dict[str, Any]) -> Tuple[bool, List[str], Optional[str], Optional[Dict[str, Any]]]:
    notes: List[str] = []
    if gw.get("is_mock"):
        return False, ["SKIP: is_mock=True; cannot exercise LIVE branch"], None, None

    if gw.get("source") == "env":
        if gw.get("key_id") != ENV_KEY_ID:
            return False, [f"key_id mismatch with env: db_key_id={gw.get('key_id')}"], None, None
        secret = ENV_KEY_SECRET
        notes.append(f"Using ENV creds key_id={gw.get('key_id')}")
    elif gw.get("source") == "db":
        return False, [f"Cannot compute HMAC: source=db (secret hidden). key_id={gw.get('key_id')}"], None, None
    else:
        return False, [f"Unknown gateway source: {gw.get('source')}"], None, None

    admin_before = _find_user_by_id(admin_tok, admin_user["id"])
    assert admin_before
    admin_bal_before = float(admin_before.get("wallet_balance") or 0)
    admin_buckets_before = dict(admin_before.get("wallet_buckets") or {})
    notes.append(f"Admin BEFORE wallet_balance={admin_bal_before} buckets={admin_buckets_before}")

    u_tok, u = _register_user("utrbugb")
    notes.append(f"Registered user id={u['id']} email={u['email']} sponsor_id={u.get('sponsor_id')} referred_by={u.get('referred_by')}")

    order = _create_order(u_tok)
    notes.append(f"Order: order_id={order['order_id']} is_mock={order['is_mock']}")

    payment_id = "pay_TEST_NO_UTR"
    sig = _hmac_sig(order["order_id"], payment_id, secret)
    body = {
        "razorpay_order_id": order["order_id"],
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sig,
    }
    r = session.post(f"{BASE}/payment/verify", headers=_headers(u_tok), json=body, timeout=30)
    notes.append(f"Verify response: status={r.status_code} body={r.text[:600]}")
    if r.status_code != 200:
        return False, notes + [f"FAIL: verify returned {r.status_code}"], u["id"], None

    vresp = r.json()
    notes.append(f"Verify JSON: auto_approved={vresp.get('auto_approved')} approval_status={vresp.get('approval_status')} utr={vresp.get('utr')!r} rzp_status={vresp.get('rzp_status')} is_mock={vresp.get('is_mock')}")
    if vresp.get("auto_approved") is not False:
        return False, notes + [f"FAIL: auto_approved={vresp.get('auto_approved')} expected False"], u["id"], vresp
    if vresp.get("approval_status") != "pending":
        return False, notes + [f"FAIL: approval_status={vresp.get('approval_status')}"], u["id"], vresp
    if vresp.get("utr") not in ("", None):
        return False, notes + [f"FAIL: utr={vresp.get('utr')!r}"], u["id"], vresp
    notes.append("OK: verify response auto_approved=false, approval_status=pending, utr=''")

    fresh = _find_user_by_id(admin_tok, u["id"])
    assert fresh
    if float(fresh.get("wallet_balance") or 0) != 0:
        return False, notes + [f"FAIL: user wallet_balance={fresh.get('wallet_balance')}"], u["id"], vresp
    if not fresh.get("registration_paid"):
        return False, notes + ["FAIL: registration_paid != True"], u["id"], vresp
    if fresh.get("approval_status") != "pending":
        return False, notes + [f"FAIL: approval_status={fresh.get('approval_status')}"], u["id"], vresp
    notes.append("OK: user wallet_balance=0, registration_paid=True, approval_status=pending")

    admin_after = _find_user_by_id(admin_tok, admin_user["id"])
    admin_bal_after = float(admin_after.get("wallet_balance") or 0)
    admin_buckets_after = dict(admin_after.get("wallet_buckets") or {})
    notes.append(f"Admin AFTER wallet_balance={admin_bal_after} buckets={admin_buckets_after}")
    if admin_bal_after != admin_bal_before:
        return False, notes + [f"FAIL: admin wallet_balance changed by {admin_bal_after - admin_bal_before}"], u["id"], vresp
    if admin_buckets_after.get("referral_commission") != admin_buckets_before.get("referral_commission"):
        return False, notes + ["FAIL: admin referral_commission bucket changed"], u["id"], vresp
    notes.append("OK: admin wallet UNCHANGED — no upline cascade fired")

    txs = _user_transactions(admin_tok, u["id"])
    reg_txs = [t for t in txs if t.get("type") == "registration_fee" and t.get("status") == "paid"]
    notes.append(f"User registration_fee paid txs found: {len(reg_txs)}")
    if not reg_txs:
        return False, notes + [f"FAIL: no paid registration_fee tx. All types: {[t.get('type') + '/' + str(t.get('status')) for t in txs]}"], u["id"], vresp
    reg_tx = reg_txs[0]
    if reg_tx.get("reference_number") not in (None, ""):
        return False, notes + [f"FAIL: reg_tx.reference_number={reg_tx.get('reference_number')!r}"], u["id"], vresp
    notes.append(f"OK: registration_fee tx reference_number=''; description={reg_tx.get('description')!r}")

    nr = session.get(f"{BASE}/notifications/me", headers=_headers(u_tok), timeout=20)
    if nr.status_code == 200:
        notifs = nr.json()
        if isinstance(notifs, dict):
            notifs = notifs.get("items") or []
        any_match = [n for n in notifs if "awaiting bank-side UTR confirmation" in (n.get("body") or "")]
        notes.append(f"User notification titles: {[n.get('title') for n in notifs[:5]]}")
        if not any_match:
            return False, notes + ["FAIL: no notification body contains 'awaiting bank-side UTR confirmation'"], u["id"], vresp
        notes.append(f"OK: notification body matches (title='{any_match[0].get('title')}')")
    else:
        notes.append(f"WARN: /notifications/me returned {nr.status_code}")

    return True, notes, u["id"], vresp


def scenario_c(admin_tok: str, admin_user: Dict[str, Any], pending_user_id: str) -> Tuple[bool, List[str]]:
    notes: List[str] = []
    pending = _find_user_by_id(admin_tok, pending_user_id)
    sponsor_id = pending.get("sponsor_id")
    notes.append(f"Pending user sponsor_id={sponsor_id}")

    sponsor_before = _find_user_by_id(admin_tok, sponsor_id) if sponsor_id else None
    sponsor_directs_before = int((sponsor_before or {}).get("direct_referrals_count") or 0)
    sponsor_bal_before = float((sponsor_before or {}).get("wallet_balance") or 0)
    notes.append(f"Sponsor BEFORE direct_referrals_count={sponsor_directs_before} wallet_balance={sponsor_bal_before}")

    admin_before = _find_user_by_id(admin_tok, admin_user["id"])
    admin_buckets_before = dict(admin_before.get("wallet_buckets") or {})
    admin_directs_before = int(admin_before.get("direct_referrals_count") or 0)
    notes.append(f"Admin BEFORE direct_referrals_count={admin_directs_before} buckets={admin_buckets_before}")

    r = session.post(f"{BASE}/admin/approvals/{pending_user_id}/approve", headers=_headers(admin_tok), timeout=30)
    notes.append(f"approve resp: {r.status_code} {r.text[:300]}")
    if r.status_code != 200:
        return False, notes + [f"FAIL: approve returned {r.status_code}"]

    fresh = _find_user_by_id(admin_tok, pending_user_id)
    if fresh.get("approval_status") != "approved":
        return False, notes + [f"FAIL: user.approval_status={fresh.get('approval_status')}"]
    notes.append("OK: user approval_status=approved")

    sponsor_after = _find_user_by_id(admin_tok, sponsor_id) if sponsor_id else None
    sponsor_directs_after = int((sponsor_after or {}).get("direct_referrals_count") or 0)
    sponsor_bal_after = float((sponsor_after or {}).get("wallet_balance") or 0)
    notes.append(f"Sponsor AFTER direct_referrals_count={sponsor_directs_after} wallet_balance={sponsor_bal_after}")

    admin_after = _find_user_by_id(admin_tok, admin_user["id"])
    admin_buckets_after = dict(admin_after.get("wallet_buckets") or {})
    admin_directs_after = int(admin_after.get("direct_referrals_count") or 0)
    notes.append(f"Admin AFTER direct_referrals_count={admin_directs_after} buckets={admin_buckets_after}")

    # Validate that the cascade RAN: the immediate sponsor's direct_referrals_count must have incremented.
    if sponsor_before is None:
        return False, notes + ["FAIL: pending user has no sponsor; cannot validate cascade"]
    if sponsor_directs_after != sponsor_directs_before + 1:
        return False, notes + [f"FAIL: sponsor direct_referrals_count did not increment by 1 ({sponsor_directs_before} -> {sponsor_directs_after})"]
    notes.append("OK: sponsor.direct_referrals_count incremented by 1 — _trigger_referral_commissions ran")

    # Look for any new credit transaction created for any user since approval (referral_payout).
    rt = session.get(f"{BASE}/admin/transactions", headers=_headers(admin_tok),
                     params={"limit": 200}, timeout=30)
    new_payouts: List[Dict[str, Any]] = []
    if rt.status_code == 200:
        items = rt.json()
        if isinstance(items, dict):
            items = items.get("items") or []
        # Use source_user_name of just-approved user as a stable filter
        match_name = fresh.get("name") or ""
        new_payouts = [t for t in items if t.get("type") == "referral_payout" and (t.get("source_user_name") or "") == match_name]
    notes.append(f"referral_payout txs sourced by approved user '{fresh.get('name')}': {len(new_payouts)}")
    if new_payouts:
        for t in new_payouts[:5]:
            notes.append(f"  payout: level={t.get('level')} amount={t.get('amount')} user_id={t.get('user_id')} ts={t.get('created_at')}")
        notes.append(f"OK: cascade emitted {len(new_payouts)} referral_payout transaction(s) on manual approval")
    else:
        # If sponsor is admin itself and L1 didn't fire (count not Nth), and there's no L2 for root admin,
        # cascade can legitimately produce 0 *credit* transactions yet still 'run'. The direct_count
        # increment above already proves _trigger_referral_commissions executed.
        notes.append("INFO: no referral_payout txs created — cascade ran but no level threshold met (sponsor=admin at root, L1 only on Nth direct)")

    rar = session.get(f"{BASE}/admin/approved-registrations", headers=_headers(admin_tok),
                       params={"search": pending_user_id}, timeout=20)
    if rar.status_code == 200:
        items = rar.json()
        if isinstance(items, dict):
            items = items.get("items") or []
        matches = [it for it in items if it.get("original_user_id") == pending_user_id]
        if matches:
            notes.append(f"OK: approved_registrations entry id={matches[0].get('id')} approver_role={matches[0].get('approver_role')}")
        else:
            notes.append("WARN: no approved_registrations entry visible via search filter")
    return True, notes


def main() -> int:
    print(f"=== Razorpay verify UTR-required test ===")
    print(f"BASE = {BASE}")
    failures: List[str] = []
    summary: List[str] = []

    okD, notesD = code_review_d()
    summary.append(f"Scenario D (code review): {'PASS' if okD else 'FAIL'}")
    for n in notesD:
        print("  D:", n)
    if not okD:
        failures.append("D")

    admin_tok, admin_user = _get_admin()
    print(f"Admin id={admin_user['id']} role={admin_user.get('admin_role')}")

    gw = _gateway_source(admin_tok)
    print(f"Gateway: source={gw.get('source')} key_id={gw.get('key_id')} is_mock={gw.get('is_mock')} is_test_mode={gw.get('is_test_mode')}")
    summary.append(f"Gateway: source={gw.get('source')} is_mock={gw.get('is_mock')} key_id={gw.get('key_id')}")

    if gw.get("is_mock"):
        summary.append("Scenario A (MOCK): is_mock=True — auto_approve still fires, no commission gate (informational, by design).")
    else:
        summary.append("Scenario A (MOCK): is_mock=False; mock-mode logic verified via code review (creds.is_mock branch in `or` short-circuits).")

    okB, notesB, pending_uid, vresp = scenario_b(admin_tok, admin_user, gw)
    summary.append(f"Scenario B (LIVE no-UTR pending): {'PASS' if okB else 'FAIL'}")
    if vresp is not None:
        summary.append(f"  B response body: {vresp}")
    for n in notesB:
        print("  B:", n)
    if not okB:
        failures.append("B")

    if pending_uid and okB:
        okC, notesC = scenario_c(admin_tok, admin_user, pending_uid)
        summary.append(f"Scenario C (manual approve cascade): {'PASS' if okC else 'FAIL'}")
        for n in notesC:
            print("  C:", n)
        if not okC:
            failures.append("C")
    else:
        summary.append("Scenario C: SKIPPED (B did not produce pending user)")

    if pending_uid:
        ok = _delete_user(admin_tok, pending_uid)
        print(f"Cleanup: delete user {pending_uid} → {ok}")

    print("\n=== SUMMARY ===")
    for line in summary:
        print(line)
    print(f"Failures: {failures or 'none'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
