"""
Live Razorpay payment flow test suite (test keys).
Targets: https://network-pay-1.preview.emergentagent.com
"""
import sys
import hmac
import hashlib
import secrets
import requests
from typing import Any, Dict, Optional, Tuple, List

BASE = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE}/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
RAZORPAY_KEY_ID = "rzp_test_SjgtHA4CxiFyTK"
RAZORPAY_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

results: List[Tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    flag = "PASS" if passed else "FAIL"
    print(f"  [{flag}] {name}{(' — ' + detail) if detail else ''}")


def hdr(t: Optional[str]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {t}"} if t else {}


def jpost(path: str, body: Dict[str, Any], token: Optional[str] = None):
    return requests.post(f"{API}{path}", json=body, headers=hdr(token), timeout=30)


def jget(path: str, token: Optional[str] = None, params: Optional[Dict[str, Any]] = None):
    return requests.get(f"{API}{path}", headers=hdr(token), params=params, timeout=30)


def jdel(path: str, token: Optional[str] = None):
    return requests.delete(f"{API}{path}", headers=hdr(token), timeout=30)


def register_user(name: str, email: str, password: str = "Pass@123") -> Tuple[Optional[str], Optional[Dict]]:
    r = jpost("/auth/register", {"name": name, "email": email, "password": password})
    if r.status_code != 200:
        print(f"  Register failed: {r.status_code} {r.text[:200]}")
        return None, None
    j = r.json()
    return j.get("token"), j.get("user")


def login(email: str, password: str) -> Optional[str]:
    r = jpost("/auth/login", {"email": email, "password": password})
    if r.status_code != 200:
        return None
    return r.json().get("token")


def main():
    print("\n=== Live Razorpay Test Suite ===\n")
    rand = secrets.token_hex(4)

    admin_t = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    record("Admin login admin@app.com", admin_t is not None)
    if not admin_t:
        return finalize()

    # Setup: register fresh U1
    u1_email = f"testpay1.{rand}@example.com"
    u1_token, u1 = register_user("Test Pay One", u1_email)
    record("Register U1", u1_token is not None and u1 is not None, f"email={u1_email}")
    if not u1_token:
        return finalize()
    u1_id = u1["id"]
    u1_token = login(u1_email, "Pass@123") or u1_token
    record("Login U1", u1_token is not None)

    # ---------- Scenario A ----------
    print("\n--- Scenario A: /payment/config (live mode) ---")
    rcfg = jget("/payment/config", u1_token)
    record("A. GET /payment/config → 200", rcfg.status_code == 200, f"status={rcfg.status_code}")
    cfg = rcfg.json() if rcfg.status_code == 200 else {}
    record("A. is_mock == false", cfg.get("is_mock") is False, f"is_mock={cfg.get('is_mock')}")
    record("A. key_id starts with 'rzp_test_'",
           isinstance(cfg.get("key_id"), str) and cfg["key_id"].startswith("rzp_test_"),
           f"key_id={cfg.get('key_id')}")
    amt = cfg.get("amount")
    amt_paise = cfg.get("amount_paise")
    record("A. amount_paise == amount * 100",
           isinstance(amt, (int, float)) and isinstance(amt_paise, int) and amt_paise == int(round(amt * 100)),
           f"amount={amt}, amount_paise={amt_paise}")
    record("A. registration_paid == false", cfg.get("registration_paid") is False)
    record("A. attempts_remaining == 3", cfg.get("attempts_remaining") == 3)

    # ---------- Scenario B ----------
    print("\n--- Scenario B: /payment/create-order (real Razorpay API) ---")
    rco = jpost("/payment/create-order", {}, u1_token)
    co_ok = rco.status_code == 200
    record("B. POST /payment/create-order → 200", co_ok,
           f"status={rco.status_code} body={rco.text[:300]}")
    if not co_ok:
        return finalize()
    co = rco.json()
    order_id = co.get("order_id")
    record("B. order_id starts with 'order_'",
           isinstance(order_id, str) and order_id.startswith("order_"), f"order_id={order_id}")
    record("B. order_id NOT mock prefix",
           isinstance(order_id, str) and not order_id.startswith("order_MOCK_"), f"order_id={order_id}")
    record("B. is_mock == false", co.get("is_mock") is False)
    record("B. key_id starts with 'rzp_test_'",
           isinstance(co.get("key_id"), str) and co["key_id"].startswith("rzp_test_"))
    record("B. amount_paise matches config", co.get("amount_paise") == amt_paise)
    record("B. currency == INR", co.get("currency") == "INR")

    # ---------- Scenario C ----------
    print("\n--- Scenario C: /payment/verify rejects invalid signature ---")
    rv_bad = jpost("/payment/verify", {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": "pay_MOCK_xxx",
        "razorpay_signature": "sig_MOCK_xxx",
    }, u1_token)
    record("C. Bad signature → 401", rv_bad.status_code == 401,
           f"status={rv_bad.status_code} body={rv_bad.text[:200]}")
    detail = ""
    try:
        detail = (rv_bad.json() or {}).get("detail", "")
    except Exception:
        detail = rv_bad.text
    record("C. detail mentions 'Invalid payment signature'",
           "Invalid payment signature" in str(detail), f"detail={detail}")

    me_after_c = jget("/auth/me", u1_token)
    record("C. registration_paid still false",
           me_after_c.status_code == 200 and me_after_c.json().get("registration_paid") is False)

    # ---------- Scenario D ----------
    print("\n--- Scenario D: /payment/verify with VALID HMAC signature ---")
    fake_payment_id = f"pay_test_{secrets.token_hex(8)}"
    valid_sig = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        f"{order_id}|{fake_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    rv_good = jpost("/payment/verify", {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": fake_payment_id,
        "razorpay_signature": valid_sig,
    }, u1_token)
    record("D. Valid signature → 200", rv_good.status_code == 200,
           f"status={rv_good.status_code} body={rv_good.text[:200]}")
    if rv_good.status_code == 200:
        rj = rv_good.json()
        record("D. response ok=true", rj.get("ok") is True)
        record("D. response is_mock=false", rj.get("is_mock") is False)
        record("D. response approval_status='pending'", rj.get("approval_status") == "pending")

    me2 = jget("/auth/me", u1_token)
    me2j = me2.json() if me2.status_code == 200 else {}
    record("D. /auth/me registration_paid=true",
           me2j.get("registration_paid") is True,
           f"registration_paid={me2j.get('registration_paid')}")
    record("D. /auth/me razorpay_order_id matches",
           me2j.get("razorpay_order_id") == order_id)
    record("D. /auth/me razorpay_payment_id matches",
           me2j.get("razorpay_payment_id") == fake_payment_id)
    record("D. /auth/me payment_method == 'razorpay'",
           me2j.get("payment_method") == "razorpay",
           f"payment_method={me2j.get('payment_method')}")

    txn = jget("/transactions/me", u1_token)
    txns = txn.json() if txn.status_code == 200 else []
    paid_txn = [t for t in txns if t.get("type") == "registration_fee"
                and t.get("status") == "paid"
                and t.get("razorpay_order_id") == order_id
                and t.get("razorpay_payment_id") == fake_payment_id]
    record("D. registration_fee 'paid' transaction inserted with razorpay ids",
           len(paid_txn) >= 1, f"matching_txns={len(paid_txn)}, total_txns={len(txns)}")

    re_co = jpost("/payment/create-order", {}, u1_token)
    record("D. Re-POST /payment/create-order → 400 'already paid'",
           re_co.status_code == 400 and "already paid" in re_co.text.lower(),
           f"status={re_co.status_code} body={re_co.text[:200]}")

    # ---------- Scenario E ----------
    print("\n--- Scenario E: 3-attempt failure cap ---")
    u2_email = f"testpay2.{rand}@example.com"
    u2_token, u2 = register_user("Test Pay Two", u2_email)
    record("E. Register U2", u2_token is not None and u2 is not None, f"email={u2_email}")
    archive_id = None
    if u2_token:
        f1 = jpost("/payment/failure", {"reason": "card_declined"}, u2_token)
        f1j = f1.json() if f1.status_code == 200 else {}
        record("E. 1st failure → 200, archived=false",
               f1.status_code == 200 and f1j.get("archived") is False,
               f"status={f1.status_code} archived={f1j.get('archived')} attempts={f1j.get('attempts_used')}")

        f2 = jpost("/payment/failure", {"reason": "card_declined"}, u2_token)
        f2j = f2.json() if f2.status_code == 200 else {}
        record("E. 2nd failure → 200, archived=false",
               f2.status_code == 200 and f2j.get("archived") is False,
               f"status={f2.status_code} archived={f2j.get('archived')} attempts={f2j.get('attempts_used')}")

        f3 = jpost("/payment/failure", {"reason": "card_declined"}, u2_token)
        f3j = f3.json() if f3.status_code == 200 else {}
        record("E. 3rd failure → 200, archived=true",
               f3.status_code == 200 and f3j.get("archived") is True,
               f"status={f3.status_code} archived={f3j.get('archived')} category={f3j.get('category')}")
        record("E. 3rd failure category='payment_unsuccessful'",
               f3j.get("category") == "payment_unsuccessful")
        archive_id = f3j.get("archive_id")

        rej = jget("/admin/rejected-registrations", admin_t,
                   params={"category": "payment_unsuccessful"})
        rej_items = (rej.json() or {}).get("items", []) if rej.status_code == 200 else []
        u2_in_rej = any(i.get("email") == u2_email for i in rej_items)
        record("E. U2 found in rejected_registrations", u2_in_rej,
               f"items_count={len(rej_items)}")

        users_list = jget("/admin/users", admin_t)
        u2_still_active = False
        if users_list.status_code == 200:
            u2_still_active = any(u.get("email") == u2_email for u in users_list.json())
        record("E. U2 removed from active users", not u2_still_active)

    # ---------- Scenario F ----------
    print("\n--- Scenario F: Regression ---")
    rapp_pending = jget("/admin/approvals", admin_t, params={"status": "pending"})
    record("F. /admin/approvals?status=pending → 200", rapp_pending.status_code == 200,
           f"status={rapp_pending.status_code}")

    rapp_today = jget("/admin/approvals/today", admin_t)
    record("F. /admin/approvals/today → 200", rapp_today.status_code == 200)

    rcart = jget("/cart", u1_token)
    record("F. /cart → 200 for paid user U1", rcart.status_code == 200,
           f"status={rcart.status_code}")
    if rcart.status_code == 200:
        cj = rcart.json()
        record("F. /cart shape ok", isinstance(cj, dict) and {"items", "total", "count"}.issubset(cj.keys()),
               f"keys={list(cj.keys())}")

    rbrand = requests.get(f"{API}/branding", timeout=15)
    record("F. /branding (public, no auth) → 200", rbrand.status_code == 200)

    radmin_me = jget("/auth/me", admin_t)
    record("F. admin /auth/me → 200", radmin_me.status_code == 200)

    # ---------- Cleanup ----------
    print("\n--- Cleanup ---")
    if u1_id:
        d1 = jdel(f"/admin/users/{u1_id}", admin_t)
        if d1.status_code != 200:
            print(f"  WARN: failed to delete U1: {d1.status_code} {d1.text[:120]}")
    if archive_id:
        da = jdel(f"/admin/rejected-registrations/{archive_id}", admin_t)
        if da.status_code != 200:
            print(f"  WARN: failed to delete U2 archive: {da.status_code} {da.text[:120]}")

    ulist = jget("/admin/users", admin_t)
    if ulist.status_code == 200:
        for u in ulist.json():
            if rand in (u.get("email") or ""):
                jdel(f"/admin/users/{u['id']}", admin_t)
    rlist = jget("/admin/rejected-registrations", admin_t)
    if rlist.status_code == 200:
        for r in (rlist.json() or {}).get("items", []):
            if rand in (r.get("email") or ""):
                jdel(f"/admin/rejected-registrations/{r['id']}", admin_t)

    finalize()


def finalize():
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print("\n========================================")
    print(f"Total: {len(results)}  PASS: {passed}  FAIL: {failed}")
    print("========================================\n")
    if failed:
        print("FAILED items:")
        for n, ok, d in results:
            if not ok:
                print(f"  [FAIL] {n} — {d}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
