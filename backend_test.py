"""End-to-end test for the manual UPI payment flow (Feb-2026)."""
import json
import time
import requests
import random
import string

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"

results = []

def log(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}: {detail}")
    results.append((name, ok, detail))

def post(path, token=None, **kwargs):
    h = kwargs.pop("headers", {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.post(BASE + path, headers=h, timeout=30, **kwargs)

def put(path, token=None, **kwargs):
    h = kwargs.pop("headers", {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.put(BASE + path, headers=h, timeout=30, **kwargs)

def get(path, token=None, **kwargs):
    h = kwargs.pop("headers", {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.get(BASE + path, headers=h, timeout=30, **kwargs)


def reg_user(email_prefix):
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = f"{email_prefix}_{int(time.time())}_{rand}@example.com"
    r = post("/auth/register", json={
        "name": email_prefix.title() + " Test",
        "email": email,
        "password": "Pass@123",
        "phone": "9" + "".join(random.choices(string.digits, k=9)),
    })
    if r.status_code not in (200, 201):
        return None, None, r
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        r2 = post("/auth/login", json={"email": email, "password": "Pass@123"})
        if r2.status_code == 200:
            token = r2.json().get("token") or r2.json().get("access_token")
    return email, token, r


def main():
    # A1. Admin login
    r = post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    ok = r.status_code == 200
    admin_token = (r.json().get("token") or r.json().get("access_token")) if ok else None
    log("A1 admin login", ok and bool(admin_token), f"status={r.status_code}")
    if not admin_token:
        return

    # A2.
    body2 = {"payment_methods": {
        "razorpay_enabled": False,
        "upi_manual_enabled": True,
        "payee_upi_id": "kiran@ibl",
        "payee_name": "NetworkRupay",
    }}
    r = put("/admin/branding", token=admin_token, json=body2)
    log("A2 PUT branding (enable UPI)", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    # A3.
    r = get("/branding")
    ok = False; detail = ""
    if r.status_code == 200:
        pm = r.json().get("payment_methods") or {}
        ok = (pm.get("razorpay_enabled") is False
              and pm.get("upi_manual_enabled") is True
              and pm.get("payee_upi_id") == "kiran@ibl"
              and pm.get("payee_name") == "NetworkRupay")
        detail = f"pm={pm}"
    log("A3 GET /branding reflects payment_methods", ok, detail)

    # A4.
    r = put("/admin/branding", token=admin_token, json={"payment_methods": {"payee_upi_id": "bad upi id no at"}})
    log("A4 PUT bad payee_upi_id → 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")

    # B5.
    email1, token1, r = reg_user("upitest")
    log("B5 register fresh unpaid user", token1 is not None, f"email={email1} status={r.status_code if hasattr(r,'status_code') else 'n/a'}")
    if not token1:
        return

    # B6.
    r = get("/payment/upi-config", token=token1)
    cfg = r.json() if r.status_code == 200 else {}
    me = cfg.get("methods_enabled") or {}
    ok = (r.status_code == 200
          and me.get("razorpay") is False
          and me.get("upi_manual") is True
          and float(cfg.get("amount") or 0) == 118.0
          and (cfg.get("deeplink_prefix") or "").startswith("upi://pay?pa=kiran@ibl&pn=NetworkRupay&am=")
          and cfg.get("registration_paid") is False
          and cfg.get("pending_payment") is None)
    log("B6 GET /payment/upi-config", ok,
        f"status={r.status_code} amount={cfg.get('amount')} deeplink={cfg.get('deeplink_prefix')} pending={cfg.get('pending_payment')} reg_paid={cfg.get('registration_paid')} methods={me}")

    # B7.
    r = post("/payment/upi-manual", token=token1, json={"utr": "short", "app_used": "gpay"})
    log("B7 POST upi-manual short UTR → 422", r.status_code == 422, f"status={r.status_code} body={r.text[:200]}")

    # B8.
    r = post("/payment/upi-manual", token=token1, json={"utr": "TEST12345678", "app_used": "gpay", "note": "E2E test"})
    ok = r.status_code == 200 and r.json().get("status") == "PENDING"
    log("B8 POST upi-manual valid UTR → 200 PENDING", ok, f"status={r.status_code} body={r.text[:300]}")

    # B9.
    r = get("/payment/upi-manual/status", token=token1)
    p = (r.json().get("payment") or {}) if r.status_code == 200 else {}
    ok = r.status_code == 200 and p.get("status") == "PENDING" and p.get("utr") == "TEST12345678"
    log("B9 GET upi-manual/status PENDING+UTR", ok, f"status={r.status_code} payment.status={p.get('status')} payment.utr={p.get('utr')}")

    # B10.
    r = post("/payment/upi-manual", token=token1, json={"utr": "DIFFERENT123", "app_used": "phonepe"})
    log("B10 POST upi-manual update UTR → 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    # B11.
    r = get("/payment/upi-manual/status", token=token1)
    p = (r.json().get("payment") or {}) if r.status_code == 200 else {}
    ok = r.status_code == 200 and p.get("utr") == "DIFFERENT123" and p.get("app_used") == "phonepe"
    log("B11 GET upi-manual/status updated", ok, f"status={r.status_code} payment.utr={p.get('utr')} payment.app_used={p.get('app_used')}")

    # C12.
    r = get("/admin/payments/pending?status=PENDING", token=admin_token)
    items = (r.json().get("items") or []) if r.status_code == 200 else []
    pending_id = None
    for it in items:
        if it.get("utr") == "DIFFERENT123":
            pending_id = it.get("id"); break
    log("C12 GET /admin/payments/pending contains row", pending_id is not None,
        f"status={r.status_code} found_id={pending_id} count={len(items)}")

    if pending_id:
        # C13.
        r = post(f"/admin/payments/{pending_id}/approve", token=admin_token, json={"note": "verified"})
        ok = r.status_code == 200 and r.json().get("status") == "APPROVED"
        log("C13 POST approve → 200 APPROVED", ok, f"status={r.status_code} body={r.text[:300]}")

        # C14.
        r = get("/payment/upi-manual/status", token=token1)
        body = r.json() if r.status_code == 200 else {}
        ok = r.status_code == 200 and body.get("registration_paid") is True
        log("C14 status registration_paid=true", ok, f"status={r.status_code} reg_paid={body.get('registration_paid')}")

        # C15. /users/me or /auth/me
        c15_done = False
        for me_path in ["/users/me", "/auth/me"]:
            r2 = get(me_path, token=token1)
            if r2.status_code == 200:
                body = r2.json()
                u = body.get("user") if isinstance(body, dict) and "user" in body else body
                ok = bool(u.get("registration_paid"))
                log(f"C15 GET {me_path} registration_paid=true", ok, f"reg_paid={u.get('registration_paid')}")
                c15_done = True
                break
        if not c15_done:
            log("C15 GET users/me", False, "no /users/me or /auth/me responded 200")

    # D16.
    email2, token2, _ = reg_user("upireject")
    if token2:
        r = post("/payment/upi-manual", token=token2, json={"utr": "REJECT1234567", "app_used": "gpay"})
        log("D16 second user submit → 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

        r = get("/admin/payments/pending?status=PENDING", token=admin_token)
        items = (r.json().get("items") or []) if r.status_code == 200 else []
        rej_id = None
        for it in items:
            if it.get("utr") == "REJECT1234567":
                rej_id = it.get("id"); break

        if rej_id:
            r = post(f"/admin/payments/{rej_id}/reject", token=admin_token, json={"reason": "UTR not found in bank statement"})
            log("D17 POST reject → 200", r.status_code == 200, f"status={r.status_code} body={r.text[:300]}")

            r = get("/payment/upi-manual/status", token=token2)
            p = (r.json().get("payment") or {}) if r.status_code == 200 else {}
            ok = r.status_code == 200 and p.get("status") == "REJECTED" and (p.get("rejection_reason") or "").strip() != ""
            log("D18 status REJECTED with rejection_reason", ok, f"status={r.status_code} payment.status={p.get('status')} reason={p.get('rejection_reason')}")

            r = post(f"/admin/payments/{rej_id}/approve", token=admin_token, json={"note": "try approve rejected"})
            log("D19 approve rejected → 400", r.status_code == 400, f"status={r.status_code} body={r.text[:200]}")
        else:
            log("D17-19 find rejected payment id", False, "could not find row")
    else:
        log("D16 register second user", False, "couldn't register")

    # E20.
    email3, token3, _ = reg_user("upidupe")
    if token3:
        r = post("/payment/upi-manual", token=token3, json={"utr": "TEST12345678", "app_used": "gpay"})
        log("E20 duplicate UTR → 409", r.status_code == 409, f"status={r.status_code} body={r.text[:300]}")
    else:
        log("E20 register third user", False, "couldn't register")

    # F21.
    r = put("/admin/branding", token=admin_token, json={"payment_methods": {"razorpay_enabled": True, "upi_manual_enabled": True}})
    log("F21 re-enable Razorpay", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")

    print("\n========== SUMMARY ==========")
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"{passed}/{len(results)} passed")
    for name, ok, _ in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


if __name__ == "__main__":
    main()
