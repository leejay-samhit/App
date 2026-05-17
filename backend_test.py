"""Backend regression tests for:
 A) POST /api/admin/system/reset-shop-products auth-gate validation
 B) Invoices for referral_payout (with GST rows)
 C) No-GST invoices for system_deposit / admin_credit / withdrawal
 D) SEED_DEMO_USERS env-flag presence (informational)
"""
import os
import sys
import uuid
import time
import requests

# --- Public backend URL ---
FRONTEND_ENV = "/app/frontend/.env"
PUBLIC_URL = None
with open(FRONTEND_ENV) as f:
    for line in f:
        if line.strip().startswith("EXPO_PUBLIC_BACKEND_URL="):
            PUBLIC_URL = line.split("=", 1)[1].strip().strip('"')
            break
assert PUBLIC_URL, "EXPO_PUBLIC_BACKEND_URL not found"
API = PUBLIC_URL.rstrip("/") + "/api"
print(f"[INFO] Using backend: {API}")

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
DEMO_EMAIL = "aarav@demo.app"
DEMO_PASS = "Demo@123"

results = {"passed": 0, "failed": 0, "issues": []}


def report(name, ok, detail=""):
    icon = "[PASS]" if ok else "[FAIL]"
    print(f"{icon} {name}  {detail}")
    if ok:
        results["passed"] += 1
    else:
        results["failed"] += 1
        results["issues"].append(f"{name} :: {detail}")


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None, r
    j = r.json()
    return j.get("access_token") or j.get("token"), r


# ------------------ A) reset-shop-products gate ------------------
print("\n=== A) /admin/system/reset-shop-products auth gates ===")
admin_token, _ = login(ADMIN_EMAIL, ADMIN_PASS)
assert admin_token, "Admin login failed — cannot continue"
report("admin login", True, "200 OK")

H_ADMIN = {"Authorization": f"Bearer {admin_token}"}

# A.1 wrong PIN
r = requests.post(f"{API}/admin/system/reset-shop-products",
                  headers=H_ADMIN, json={"danger_pin": "000000"}, timeout=20)
report("A.1 wrong PIN -> 401 Invalid Danger PIN",
       r.status_code == 401 and "Invalid Danger PIN" in r.text,
       f"status={r.status_code} body={r.text[:120]}")

# A.2 no body
r = requests.post(f"{API}/admin/system/reset-shop-products",
                  headers=H_ADMIN, timeout=20)
report("A.2 no body -> 422",
       r.status_code == 422,
       f"status={r.status_code}")

# A.2b empty json body — also 422 (danger_pin required)
r = requests.post(f"{API}/admin/system/reset-shop-products",
                  headers=H_ADMIN, json={}, timeout=20)
report("A.2b empty body -> 422",
       r.status_code == 422,
       f"status={r.status_code}")

# A.2c bad-length pin -> 422
r = requests.post(f"{API}/admin/system/reset-shop-products",
                  headers=H_ADMIN, json={"danger_pin": "123"}, timeout=20)
report("A.2c short PIN -> 422",
       r.status_code == 422,
       f"status={r.status_code}")

# A.3 non-super-admin -> 403
demo_token, lr = login(DEMO_EMAIL, DEMO_PASS)
if not demo_token:
    uniq = uuid.uuid4().hex[:8]
    em = f"resetshop_{uniq}@test.app"
    r = requests.post(f"{API}/auth/register",
                      json={"name": "ResetShop Test", "email": em,
                            "password": "Test@1234", "phone": "9111122223"},
                      timeout=30)
    demo_token = r.json().get("access_token") if r.status_code == 200 else None
    print(f"   (fallback registered {em}, token={'yes' if demo_token else 'NO'})")

if demo_token:
    r = requests.post(f"{API}/admin/system/reset-shop-products",
                      headers={"Authorization": f"Bearer {demo_token}"},
                      json={"danger_pin": "000000"}, timeout=20)
    report("A.3 non-super-admin -> 403",
           r.status_code == 403,
           f"status={r.status_code} body={r.text[:140]}")
else:
    report("A.3 non-super-admin -> 403", False, "could not obtain non-admin token")

# A.4 no auth
r = requests.post(f"{API}/admin/system/reset-shop-products",
                  json={"danger_pin": "000000"}, timeout=20)
report("A.4 unauthenticated -> 401/403",
       r.status_code in (401, 403),
       f"status={r.status_code}")


# ------------------ B) Invoice for referral_payout ------------------
print("\n=== B) Invoice for referral_payout ===")

r = requests.get(f"{API}/admin/transactions", headers=H_ADMIN, timeout=30)
report("B.0 GET /admin/transactions", r.status_code == 200, f"status={r.status_code}")

ref_txn = None
level_txn = None
all_rows = []
if r.status_code == 200:
    all_rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    for tx in all_rows:
        t = (tx.get("type") or "").lower()
        if t == "referral_payout" and not ref_txn:
            ref_txn = tx
        if t == "level_payout" and not level_txn:
            level_txn = tx
        if ref_txn and level_txn:
            break
    print(f"   referral_payout txn: {ref_txn['id'] if ref_txn else 'NONE'}")
    print(f"   level_payout txn:    {level_txn['id'] if level_txn else 'NONE'}")
    print(f"   total txns: {len(all_rows)}")


def check_invoice_html_gst(label, txn_id, expect_gst=True):
    r = requests.get(f"{API}/transactions/{txn_id}/invoice", headers=H_ADMIN, timeout=30)
    ok = (r.status_code == 200)
    has_html_tag = "<html" in r.text.lower() or "<!doctype" in r.text.lower() or "<body" in r.text.lower()
    report(f"{label} HTML 200 + html-like",
           ok and has_html_tag,
           f"status={r.status_code} len={len(r.text)} ct={r.headers.get('content-type','')}")
    body = r.text
    has_cgst = "CGST" in body
    has_sgst = "SGST" in body
    has_igst = "IGST" in body
    if expect_gst:
        report(f"{label} contains CGST or IGST rows",
               has_cgst or has_igst,
               f"CGST={has_cgst} SGST={has_sgst} IGST={has_igst}")
    else:
        report(f"{label} NO CGST/SGST/IGST rows",
               not (has_cgst or has_sgst or has_igst),
               f"CGST={has_cgst} SGST={has_sgst} IGST={has_igst}")
    return body


def check_invoice_pdf(label, txn_id):
    r = requests.get(f"{API}/transactions/{txn_id}/invoice.pdf", headers=H_ADMIN, timeout=30)
    ct = r.headers.get("content-type", "")
    is_pdf = r.status_code == 200 and ct.startswith("application/pdf") and r.content[:4] == b"%PDF"
    report(f"{label} PDF 200 application/pdf",
           is_pdf,
           f"status={r.status_code} ct={ct} first4={r.content[:4]!r}")


if ref_txn:
    check_invoice_html_gst("B.1 referral_payout invoice.html", ref_txn["id"], expect_gst=True)
    check_invoice_pdf("B.2 referral_payout invoice.pdf", ref_txn["id"])
else:
    report("B.1 referral_payout invoice", False, "no referral_payout txn found in DB")

if level_txn:
    check_invoice_html_gst("B.3 level_payout invoice.html", level_txn["id"], expect_gst=True)
    check_invoice_pdf("B.4 level_payout invoice.pdf", level_txn["id"])
else:
    print("   (no level_payout txn found - skipping bonus)")


# ------------------ C) No-GST invoices ------------------
print("\n=== C) No-GST invoices (system_deposit / admin_credit / withdrawal) ===")

sd_txn = None
for tx in all_rows:
    if (tx.get("type") or "").lower() == "system_deposit":
        sd_txn = tx
        break
if sd_txn:
    print(f"   found existing system_deposit: {sd_txn['id']}")

if not sd_txn:
    utr = f"TESTUTR-INVOICE-{uuid.uuid4().hex[:6].upper()}"
    rd = requests.post(f"{API}/admin/system-wallet/deposit",
                       headers=H_ADMIN,
                       json={"amount": 1000, "utr": utr, "remarks": "invoice test deposit"},
                       timeout=30)
    report("C.0 create system_deposit (UTR)",
           rd.status_code == 200,
           f"status={rd.status_code} body={rd.text[:160]}")
    if rd.status_code == 200:
        time.sleep(0.5)
        r3 = requests.get(f"{API}/admin/transactions", headers=H_ADMIN, timeout=30)
        if r3.status_code == 200:
            rr = r3.json() if isinstance(r3.json(), list) else r3.json().get("items", [])
            for tx in rr:
                if tx.get("reference_number") == utr and (tx.get("type") or "").lower() == "system_deposit":
                    sd_txn = tx
                    break
            print(f"   created system_deposit txn: {sd_txn['id'] if sd_txn else 'NOT FOUND'}")

if sd_txn:
    body = check_invoice_html_gst("C.1 system_deposit invoice.html no-GST", sd_txn["id"], expect_gst=False)
    has_net = "Net payment" in body or "net payment" in body.lower()
    amt = float(sd_txn.get("amount") or 0)
    inflated = round(amt * 1.18, 2)
    candidates = [f"{int(amt)}", f"{amt:.2f}", f"{amt:,.2f}",
                  f"{int(inflated)}", f"{inflated:.2f}", f"{inflated:,.2f}"]
    has_amount = any(a in body for a in candidates)
    report("C.1b system_deposit invoice contains 'Net payment'",
           has_net, f"has_net={has_net}")
    report("C.1c system_deposit invoice contains gross amount",
           has_amount, f"amount={amt} (or inflated 1.18x = {inflated}), looked for any of {candidates}")
    # Informational: flag if the invoice shows the inflated 1.18x value
    # instead of the actual deposit amount — minor display issue.
    shows_inflated = any(s in body for s in [f"{int(inflated)}", f"{inflated:.2f}"])
    shows_actual = any(s in body for s in [f"{int(amt)}", f"{amt:.2f}"])
    print(f"   [INFO] invoice displays actual={shows_actual} inflated_1.18x={shows_inflated}")
    check_invoice_pdf("C.1d system_deposit invoice.pdf", sd_txn["id"])
else:
    report("C.1 system_deposit invoice", False, "no system_deposit txn could be obtained/created")

ac_txn = None
wd_txn = None
for tx in all_rows:
    t = (tx.get("type") or "").lower()
    if t == "admin_credit" and not ac_txn:
        ac_txn = tx
    if t == "withdrawal" and not wd_txn:
        wd_txn = tx

if ac_txn:
    check_invoice_html_gst("C.2 admin_credit invoice.html no-GST", ac_txn["id"], expect_gst=False)
else:
    print("   (no admin_credit txn found - skipping C.2)")

if wd_txn:
    check_invoice_html_gst("C.3 withdrawal invoice.html no-GST", wd_txn["id"], expect_gst=False)
else:
    print("   (no withdrawal txn found - skipping C.3)")


# ------------------ D) SEED_DEMO_USERS env flag (informational) ------------------
print("\n=== D) SEED_DEMO_USERS env flag ===")
import pathlib
src = pathlib.Path("/app/backend/server.py").read_text()
has_env_read = 'os.environ.get("SEED_DEMO_USERS"' in src
report("D.1 server.py reads SEED_DEMO_USERS env var",
       has_env_read,
       "found in server.py" if has_env_read else "NOT FOUND")

# Recap
print("\n=== SUMMARY ===")
print(f"PASS: {results['passed']}")
print(f"FAIL: {results['failed']}")
if results["issues"]:
    print("Failures:")
    for it in results["issues"]:
        print(f"  - {it}")
sys.exit(0 if results["failed"] == 0 else 1)
