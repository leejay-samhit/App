"""Phase 3 — GST Invoice endpoints test.

Tests:
  GET /api/transactions/{txn_id}/invoice (HTML)
  GET /api/transactions/{txn_id}/invoice.pdf (PDF)
  GET /api/transactions/{txn_id} new fields (invoice_number, invoiceable)
"""

from __future__ import annotations

import os
import re
import sys
import hmac
import hashlib
import secrets
import requests

BASE = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"

RZP_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"  # backend/.env RAZORPAY_KEY_SECRET

results = []


def rec(label: str, ok: bool, info: str = ""):
    results.append((label, ok, info))
    sym = "PASS" if ok else "FAIL"
    print(f"[{sym}] {label}{(' :: ' + info) if info else ''}")


def login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"login failed for {email}: {r.status_code} {r.text}")
    j = r.json()
    return j.get("token") or j.get("access_token")


def H(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def fresh_email(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}@invtest.com"


def register(name: str, email: str, password: str, referral=None) -> dict:
    body = {"name": name, "email": email, "password": password, "phone": "9000000000"}
    if referral:
        body["referral_code"] = referral
    r = requests.post(f"{API}/auth/register", json=body, timeout=20)
    r.raise_for_status()
    return r.json()


def auto_approve_pay(user_token: str) -> dict:
    h = H(user_token)
    co = requests.post(f"{API}/payment/create-order", headers=h, timeout=20)
    co.raise_for_status()
    order_id = co.json()["order_id"]
    pay_id = "pay_test_" + secrets.token_hex(8)
    sig = hmac.new(
        RZP_SECRET.encode("utf-8"),
        f"{order_id}|{pay_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    v = requests.post(
        f"{API}/payment/verify",
        headers=h,
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
        },
        timeout=20,
    )
    v.raise_for_status()
    return v.json()


def get_my_txs(token: str) -> list:
    r = requests.get(f"{API}/transactions/me", headers=H(token), timeout=20)
    r.raise_for_status()
    return r.json()


def main():
    cleanup_user_ids = []
    cleanup_product_ids = []

    print("\n=== STAGE 0: Logins ===")
    admin_token = login(ADMIN_EMAIL, ADMIN_PASS)
    rec("login admin", True)

    me = requests.get(f"{API}/auth/me", headers=H(admin_token), timeout=20).json()
    admin_id = me["id"]

    admin_txs = get_my_txs(admin_token)
    rec("admin /transactions/me", len(admin_txs) >= 1, f"count={len(admin_txs)}")

    by_type = {}
    for t in admin_txs:
        ty = (t.get("type") or "").lower()
        if ty not in by_type:
            by_type[ty] = t
    print(f"Admin txn types available: {list(by_type.keys())}")

    # === STAGE A ===
    print("\n=== STAGE A: Auth & Permissions ===")

    ua_email = fresh_email("ua")
    ua = register("Aarav Mehta", ua_email, "Aaaa1!aa")
    cleanup_user_ids.append(ua["user"]["id"])
    ua_token = login(ua_email, "Aaaa1!aa")
    auto_approve_pay(ua_token)
    ua_txs = get_my_txs(ua_token)
    ua_reg_tx = next((t for t in ua_txs if t.get("type") == "registration_fee"), None)
    if not ua_reg_tx:
        rec("user A has registration_fee txn", False, "no reg fee txn")
        return
    rec("user A has registration_fee txn", True, f"id={ua_reg_tx['id'][:8]}")

    ub_email = fresh_email("ub")
    ub = register("Bhavna Kapoor", ub_email, "Bbbb2!bb")
    cleanup_user_ids.append(ub["user"]["id"])
    ub_token = login(ub_email, "Bbbb2!bb")
    auto_approve_pay(ub_token)

    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice", timeout=20)
    rec("A.1 anonymous /invoice → 401/403", r.status_code in (401, 403), f"{r.status_code}")

    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice.pdf", timeout=20)
    rec("A.1b anonymous /invoice.pdf → 401/403", r.status_code in (401, 403), f"{r.status_code}")

    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice", headers=H(ub_token), timeout=20)
    rec("A.2 user B → user A invoice → 403", r.status_code == 403, f"{r.status_code}")

    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice", headers=H(admin_token), timeout=20)
    rec("A.3 super_admin → 200 on user A invoice", r.status_code == 200, f"{r.status_code}")

    def make_admin(role: str):
        em = fresh_email(role)
        u = register(f"{role.title()} Admin", em, "Pppp9!pp")
        cleanup_user_ids.append(u["user"]["id"])
        rr = requests.patch(
            f"{API}/admin/users/{u['user']['id']}",
            headers=H(admin_token),
            json={"role": "admin", "admin_role": role},
            timeout=20,
        )
        rr.raise_for_status()
        return em, login(em, "Pppp9!pp")

    mgr_email, mgr_token = make_admin("manager")
    sup_email, sup_token = make_admin("support")
    fin_email, fin_token = make_admin("finance")

    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice", headers=H(mgr_token), timeout=20)
    rec("A.4 manager → user A invoice → 403", r.status_code == 403, f"{r.status_code}")
    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice", headers=H(sup_token), timeout=20)
    rec("A.4b support → user A invoice → 403", r.status_code == 403, f"{r.status_code}")

    r = requests.get(f"{API}/transactions/{ua_reg_tx['id']}/invoice", headers=H(fin_token), timeout=20)
    rec("A.5 finance → user A invoice → 200", r.status_code == 200, f"{r.status_code}")

    r = requests.get(f"{API}/transactions/nonexistent_xxx_yyy/invoice", headers=H(admin_token), timeout=20)
    rec("A.6 invalid txn_id → 404", r.status_code == 404, f"{r.status_code}")

    # === STAGE B ===
    print("\n=== STAGE B: Happy path /invoice (HTML) ===")

    target_tx = admin_txs[0]
    target_id = target_tx["id"]
    r = requests.get(f"{API}/transactions/{target_id}/invoice", headers=H(admin_token), timeout=20)
    rec("B.1 admin /invoice → 200", r.status_code == 200, f"{r.status_code}")
    ct = r.headers.get("Content-Type", "")
    rec("B.2 Content-Type starts with text/html", ct.startswith("text/html"), ct)
    body = r.text
    branding = requests.get(f"{API}/branding", timeout=20).json()
    biz = branding.get("business_name") or branding.get("app_name") or ""
    rec("B.3 HTML contains company name", biz and biz in body, f"biz={biz!r}")
    m = re.search(r"(INV|STMT)/[A-Z]+/\d{6}/[A-F0-9]+", body)
    rec("B.4 HTML contains invoice number (INV/ or STMT/)", m is not None, f"inv={m.group(0) if m else None}")
    rec("B.5 HTML has CGST 9.0%", "CGST" in body and "9.0%" in body, "")
    rec("B.6 HTML has SGST 9.0%", "SGST" in body and "9.0%" in body, "")
    rec("B.7 HTML has 'Total payable' or 'Net payment'",
        ("Total payable" in body) or ("Net payment" in body), "")

    # Build order ₹1180
    sw = requests.get(f"{API}/admin/system-wallet", headers=H(admin_token), timeout=20).json()
    direct_added = sw["buckets"]["direct_added"]
    if direct_added < 1500:
        utr = "UTR-INVTEST-" + secrets.token_hex(4).upper()
        d = requests.post(
            f"{API}/admin/system-wallet/deposit",
            headers=H(admin_token),
            json={"amount": 2000, "utr": utr, "remarks": "invoice test top-up"},
            timeout=20,
        )
        d.raise_for_status()

    uo_email = fresh_email("uo")
    uo = register("Order User", uo_email, "Oooo3!oo")
    cleanup_user_ids.append(uo["user"]["id"])
    uo_token = login(uo_email, "Oooo3!oo")
    auto_approve_pay(uo_token)

    cred = requests.post(
        f"{API}/admin/users/{uo['user']['id']}/wallet",
        headers=H(admin_token),
        json={"amount": 1180, "type": "credit", "reason": "invoice test fund"},
        timeout=20,
    )
    cred.raise_for_status()

    prod = requests.post(
        f"{API}/admin/products",
        headers=H(admin_token),
        json={
            "name": "GST Test Product",
            "description": "For invoice math test",
            "price": 1180,
            "stock": 10,
            "image_url": "https://via.placeholder.com/150",
        },
        timeout=20,
    )
    if prod.status_code != 200:
        print("Product creation failed:", prod.status_code, prod.text[:300])
    else:
        pj = prod.json()
        pid = pj.get("id") or (pj.get("product") or {}).get("id") or pj.get("product_id")
        cleanup_product_ids.append(pid)

        requests.post(f"{API}/cart/add", headers=H(uo_token), json={"product_id": pid, "qty": 1}, timeout=20).raise_for_status()
        co = requests.post(f"{API}/orders/checkout", headers=H(uo_token), timeout=20)
        rec("B.8 checkout for ₹1180 → 200", co.status_code == 200, f"{co.status_code} {co.text[:200]}")

        uo_txs = get_my_txs(uo_token)
        order_tx = next((t for t in uo_txs if t.get("type") == "order"), None)
        rec("B.9 order tx exists", order_tx is not None, f"id={order_tx['id'][:8] if order_tx else 'none'}")

        if order_tx:
            r = requests.get(f"{API}/transactions/{order_tx['id']}/invoice", headers=H(uo_token), timeout=20)
            rec("B.10 owner /invoice on order → 200", r.status_code == 200, f"{r.status_code}")
            body = r.text
            rec("B.11 order invoice taxable=1000.00", "1000.00" in body, "")
            rec("B.12 order invoice CGST/SGST 90.00 (twice)", body.count("90.00") >= 2, f"count90={body.count('90.00')}")
            rec("B.13 order invoice gross=1180.00", "1180.00" in body, "")
            rec("B.14 order is TAX INVOICE heading", "TAX INVOICE" in body, "")
            rec("B.15 has INV/ prefix invoice no",
                re.search(r"INV/[A-Z]+/\d{6}/[A-F0-9]+", body) is not None, "")
            globals()["_order_tx_id"] = order_tx["id"]
            globals()["_order_tx"] = order_tx

    # Statement (commission) invoice
    stmt_tx = (by_type.get("referral_payout")
               or by_type.get("system_deposit")
               or by_type.get("admin_credit"))
    if stmt_tx:
        r = requests.get(f"{API}/transactions/{stmt_tx['id']}/invoice", headers=H(admin_token), timeout=20)
        rec("B.16 statement /invoice → 200", r.status_code == 200, f"{r.status_code}")
        sb = r.text
        rec("B.17 statement heading = PAYMENT STATEMENT (not TAX INVOICE)",
            ("PAYMENT STATEMENT" in sb) and ("TAX INVOICE" not in sb), "")
        rec("B.18 statement uses STMT/ prefix",
            re.search(r"STMT/[A-Z]+/\d{6}/[A-F0-9]+", sb) is not None, "")
        amt = abs(float(stmt_tx.get("amount") or 0))
        # exclusive: taxable=amt, gst added on top
        expected_gst = round(amt * 0.18, 2)
        expected_gross = round(amt + expected_gst, 2)
        gross_str = f"{expected_gross:.2f}"
        # The 'taxable' value should be amt itself
        taxable_str = f"{amt:.2f}"
        rec("B.19 statement exclusive: taxable equals amount",
            taxable_str in sb, f"expected taxable={taxable_str}")
        rec("B.20 statement exclusive: gross = amount + 18%",
            gross_str in sb, f"expected gross={gross_str}")
    else:
        rec("B.16 statement type tx available", False, "no admin stmt-type txn found")

    # === STAGE C: PDF ===
    print("\n=== STAGE C: Happy path /invoice.pdf ===")
    pdf_tx = globals().get("_order_tx") or target_tx
    pdf_token = uo_token if globals().get("_order_tx") else admin_token
    r = requests.get(f"{API}/transactions/{pdf_tx['id']}/invoice.pdf", headers=H(pdf_token), timeout=30)
    rec("C.1 /invoice.pdf → 200", r.status_code == 200, f"{r.status_code}")
    ct = r.headers.get("Content-Type", "")
    rec("C.2 Content-Type application/pdf", ct.startswith("application/pdf"), ct)
    pdf_bytes = r.content
    rec("C.3 PDF body length > 1500", len(pdf_bytes) > 1500, f"len={len(pdf_bytes)}")
    rec("C.4 PDF magic %PDF-", pdf_bytes[:5] == b"%PDF-", f"first8={pdf_bytes[:8]!r}")
    cd = r.headers.get("Content-Disposition", "")
    rec("C.5 Content-Disposition has filename", "filename=" in cd, f"cd={cd}")
    has_dashed_invno = bool(re.search(r"filename=\"(INV|STMT)-[A-Z]+-\d{6}-[A-F0-9]+\.pdf\"", cd))
    rec("C.6 filename contains invoice no with dashes", has_dashed_invno, f"cd={cd}")
    print(f"\n[PDF info] size={len(pdf_bytes)} bytes  first8={pdf_bytes[:8]!r}")

    # === STAGE D: Detail enhancements ===
    print("\n=== STAGE D: Detail endpoint /transactions/{id} new fields ===")

    invoiceable_types = {
        "order", "service_booking", "registration_fee",
        "referral_payout", "level_payout", "vendor_sale", "service_earning",
        "shop_commission", "service_commission", "admin_credit", "transfer_in",
        "transfer_out", "withdrawal", "admin_debit", "system_deposit",
    }
    sampled = 0
    for ty in invoiceable_types:
        sample = by_type.get(ty)
        if not sample:
            continue
        sampled += 1
        r = requests.get(f"{API}/transactions/{sample['id']}", headers=H(admin_token), timeout=20)
        if r.status_code != 200:
            rec(f"D.{ty} detail GET 200", False, f"{r.status_code}")
            continue
        j = r.json()
        ok_inv_no = isinstance(j.get("invoice_number"), str) and len(j.get("invoice_number")) > 0
        ok_inv_able = j.get("invoiceable") is True
        rec(f"D.{ty} returns invoice_number string", ok_inv_no, f"{j.get('invoice_number')}")
        rec(f"D.{ty} returns invoiceable=true", ok_inv_able, f"{j.get('invoiceable')}")
    rec("D.sampled_at_least_3", sampled >= 3, f"sampled={sampled}")

    # === STAGE E: Regression smoke ===
    print("\n=== STAGE E: Regression smoke ===")
    ut1_email = fresh_email("ut1")
    ut1 = register("Transfer Sender", ut1_email, "Tttt4!tt")
    cleanup_user_ids.append(ut1["user"]["id"])
    ut1_token = login(ut1_email, "Tttt4!tt")
    auto_approve_pay(ut1_token)
    ut2_email = fresh_email("ut2")
    ut2 = register("Transfer Recv", ut2_email, "Tttt5!tt")
    cleanup_user_ids.append(ut2["user"]["id"])
    ut2_token = login(ut2_email, "Tttt5!tt")
    auto_approve_pay(ut2_token)
    requests.post(
        f"{API}/admin/users/{ut1['user']['id']}/wallet",
        headers=H(admin_token),
        json={"amount": 100, "type": "credit", "reason": "smoke transfer"},
        timeout=20,
    ).raise_for_status()
    tr = requests.post(
        f"{API}/wallet/transfer",
        headers=H(ut1_token),
        json={"recipient": ut2_email, "amount": 50, "note": "smoke"},
        timeout=20,
    )
    rec("E.1 wallet/transfer 50 → 200", tr.status_code == 200, f"{tr.status_code} {tr.text[:120]}")

    # === STAGE F: GST math ===
    print("\n=== STAGE F: GST math unit-style verification ===")
    order_tx = globals().get("_order_tx")
    if order_tx:
        amt = abs(float(order_tx["amount"]))
        taxable = round(amt / 1.18, 2)
        gst_total = round(amt - taxable, 2)
        cgst = round(gst_total / 2, 2)
        sgst = round(gst_total - cgst, 2)
        sumcheck = round(taxable + cgst + sgst, 2)
        rec("F.1 inclusive split sum-check",
            abs(sumcheck - amt) < 0.01,
            f"taxable={taxable} cgst={cgst} sgst={sgst} sum={sumcheck} amt={amt}")
        rec("F.2 cgst==sgst for intra-state",
            abs(cgst - sgst) < 0.01, f"cgst={cgst} sgst={sgst}")
    amt2 = abs(float(ua_reg_tx["amount"]))
    taxable2 = round(amt2 / 1.18, 2)
    gst2 = round(amt2 - taxable2, 2)
    rec(f"F.3 reg_fee {amt2} inclusive: taxable~{round(amt2/1.18,2)} GST~{round(amt2-(amt2/1.18),2)}",
        abs(taxable2 + gst2 - amt2) < 0.01,
        f"taxable={taxable2} gst={gst2}")

    # CLEANUP
    print("\n=== CLEANUP ===")
    for uid in cleanup_user_ids:
        try:
            requests.delete(f"{API}/admin/users/{uid}", headers=H(admin_token), timeout=20)
        except Exception:
            pass
    for pid in cleanup_product_ids:
        if pid:
            try:
                requests.delete(f"{API}/admin/products/{pid}", headers=H(admin_token), timeout=20)
            except Exception:
                pass

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed}/{total} passed")
    print("=" * 60)
    fails = [(l, i) for l, ok, i in results if not ok]
    if fails:
        print("FAILURES:")
        for l, i in fails:
            print(f"  - {l} :: {i}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
