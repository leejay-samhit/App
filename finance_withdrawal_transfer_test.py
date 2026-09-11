"""
NetworkPay backend test — Finance role + withdrawal processing flow + wallet transfer.

Covers scenarios A–AA from the review request, plus regression sanity checks.
"""
import os
import sys
import time
import uuid
import json
import requests

BASE = os.environ.get("BACKEND_URL") or "https://slangcart-tracking.preview.emergentagent.com"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"

PASSED = []
FAILED = []


def _log(name, ok, detail=""):
    if ok:
        PASSED.append(name)
        print(f"PASS  {name}")
    else:
        FAILED.append((name, detail))
        print(f"FAIL  {name}  -- {detail}")


def post(path, token=None, json_body=None, expect=None, name=None):
    url = API + path
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.post(url, headers=h, json=json_body or {}, timeout=30)
    if expect is not None and name:
        ok = r.status_code == expect
        _log(name, ok, f"got {r.status_code}: {r.text[:200]}")
    return r


def patch(path, token=None, json_body=None, expect=None, name=None):
    url = API + path
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.patch(url, headers=h, json=json_body or {}, timeout=30)
    if expect is not None and name:
        ok = r.status_code == expect
        _log(name, ok, f"got {r.status_code}: {r.text[:200]}")
    return r


def put(path, token=None, json_body=None, expect=None, name=None):
    url = API + path
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.put(url, headers=h, json=json_body or {}, timeout=30)
    if expect is not None and name:
        ok = r.status_code == expect
        _log(name, ok, f"got {r.status_code}: {r.text[:200]}")
    return r


def get(path, token=None, expect=None, name=None, params=None):
    url = API + path
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(url, headers=h, params=params, timeout=30)
    if expect is not None and name:
        ok = r.status_code == expect
        _log(name, ok, f"got {r.status_code}: {r.text[:200]}")
    return r


def delete(path, token=None, expect=None, name=None):
    url = API + path
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.delete(url, headers=h, timeout=30)
    if expect is not None and name:
        ok = r.status_code == expect
        _log(name, ok, f"got {r.status_code}: {r.text[:200]}")
    return r


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None, None
    j = r.json()
    return j["token"], j["user"]


def register(name, email, password, referral_code=None):
    body = {"name": name, "email": email, "password": password}
    if referral_code:
        body["referral_code"] = referral_code
    r = requests.post(f"{API}/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        return None, None
    j = r.json()
    return j["token"], j["user"]


def main():
    print(f"Testing against: {API}\n")
    rand = uuid.uuid4().hex[:8]

    # --- A. Login super admin ---
    t_super, u_super = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    _log("A. Super admin login", t_super is not None, "")

    if not t_super:
        print("Cannot proceed without super_admin token.")
        return summary()

    # --- B. Create finance admin ---
    fin_email = f"fin_{rand}@test.com"
    fin_password = "Fin@123456"
    r = post("/admin/admins", t_super,
             {"name": "Fin Test", "email": fin_email, "password": fin_password, "admin_role": "finance"})
    _log("B1. POST /admin/admins admin_role=finance -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    fin_user = r.json() if r.status_code == 200 else {}
    fin_id = fin_user.get("id")
    _log("B2. Created finance admin has admin_role=finance",
         fin_user.get("admin_role") == "finance", str(fin_user.get("admin_role")))

    t_fin, u_fin = login(fin_email, fin_password)
    _log("B3. Finance admin login", t_fin is not None)

    # --- C. Create regular U1, pay fee, super_admin approves ---
    u1_email = f"u1_{rand}@test.com"
    u1_password = "User@123"
    t_u1, u1 = register("Alice One", u1_email, u1_password)
    _log("C1. Register U1", t_u1 is not None)

    r = post("/payment/register-fee", t_u1)
    _log("C2. U1 pay registration fee", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    r = post(f"/admin/approvals/{u1['id']}/approve", t_super)
    _log("C3. Super approves U1", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Re-login U1 to get fresh data
    t_u1, u1 = login(u1_email, u1_password)
    _log("C4. U1 login after approval", t_u1 is not None)

    # --- D. T_fin: GET /admin/users -> 200 ---
    r = get("/admin/users", t_fin, expect=200, name="D. Finance GET /admin/users -> 200")

    # --- E. T_fin PATCH /admin/users/{U1.id} -> 403 ---
    r = patch(f"/admin/users/{u1['id']}", t_fin, {"name": "X-blocked"}, expect=403,
              name="E. Finance PATCH /admin/users/{id} -> 403")

    # --- F. T_fin POST block -> 403 ---
    r = post(f"/admin/users/{u1['id']}/block", t_fin, {"reason": "x"}, expect=403,
             name="F. Finance POST /admin/users/{id}/block -> 403")

    # --- G. T_fin PUT /admin/settings -> 403 ---
    r = put("/admin/settings", t_fin, {}, expect=403,
            name="G. Finance PUT /admin/settings -> 403")

    # --- H. T_fin POST /admin/admins -> 403 ---
    r = post("/admin/admins", t_fin,
             {"name": "X", "email": f"x_{rand}@x.com", "password": "Xxx@1234", "admin_role": "manager"},
             expect=403, name="H. Finance POST /admin/admins -> 403")

    # --- I. T_fin POST /admin/approvals/{id}/approve -> 403 ---
    r = post(f"/admin/approvals/{u1['id']}/approve", t_fin, expect=403,
             name="I. Finance POST /admin/approvals/{id}/approve -> 403")

    # --- J. Super PATCH U1 wallet_balance=1000 ---
    r = patch(f"/admin/users/{u1['id']}", t_super, {"wallet_balance": 1000})
    _log("J1. Super PATCH U1 wallet_balance=1000", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Add UPI for U1 so withdrawal works
    r = post("/users/me/bank", t_u1, {"upi_id": "alice@upi"})
    _log("J2. U1 add UPI", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Check balance
    r = get("/auth/me", t_u1)
    bal = r.json().get("wallet_balance") if r.status_code == 200 else None
    _log("J3. U1 wallet_balance == 1000", bal == 1000, f"got {bal}")

    # --- K. U1 POST /withdrawals {300} -> 200 status pending; balance -> 700 ---
    r = post("/withdrawals", t_u1, {"amount": 300})
    _log("K1. U1 withdrawal request -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    wid = None
    if r.status_code == 200:
        j = r.json()
        wid = j.get("id")
        _log("K2. Withdrawal status=pending", j.get("status") == "pending", str(j.get("status")))

    r = get("/auth/me", t_u1)
    bal = r.json().get("wallet_balance") if r.status_code == 200 else None
    _log("K3. U1 wallet_balance == 700 after withdraw", bal == 700, f"got {bal}")

    # --- L. T_fin GET /admin/withdrawals?status=pending ---
    r = get("/admin/withdrawals", t_fin, params={"status": "pending"})
    found = False
    if r.status_code == 200:
        for it in r.json():
            if it.get("id") == wid:
                found = True
                break
    _log("L. Finance GET /admin/withdrawals?status=pending includes our wid",
         r.status_code == 200 and found, f"{r.status_code}, found={found}")

    # --- M. T_fin POST /admin/withdrawals/{wid}/approve -> 200 status processing + ETA ---
    r = post(f"/admin/withdrawals/{wid}/approve", t_fin)
    _log("M1. Finance approve withdrawal -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    eta = None
    if r.status_code == 200:
        j = r.json()
        eta = j.get("estimated_completion_at")
        _log("M2. Approve returns estimated_completion_at", bool(eta), f"eta={eta}")

    # Verify withdrawal status is now processing
    r = get("/admin/withdrawals", t_fin, params={"status": "processing"})
    proc = None
    if r.status_code == 200:
        for it in r.json():
            if it.get("id") == wid:
                proc = it
                break
    _log("M3. Withdrawal.status == 'processing'",
         proc is not None and proc.get("status") == "processing",
         str(proc.get("status") if proc else None))
    _log("M4. Withdrawal has estimated_completion_at",
         proc is not None and proc.get("estimated_completion_at"),
         str(proc.get("estimated_completion_at") if proc else None))

    # --- N. U1 GET /transactions/me — withdrawal status=processing amount=-300 ETA in desc ---
    r = get("/transactions/me", t_u1)
    proc_txn = None
    if r.status_code == 200:
        for tx in r.json():
            if tx.get("type") == "withdrawal" and tx.get("status") == "processing" and tx.get("amount") == -300:
                proc_txn = tx
                break
    _log("N1. Transactions has processing withdrawal -300", proc_txn is not None)
    _log("N2. Description mentions ETA",
         proc_txn is not None and ("ETA" in (proc_txn.get("description") or "") or "process" in (proc_txn.get("description") or "").lower()),
         str(proc_txn.get("description") if proc_txn else None))

    # --- O. T_fin POST /admin/withdrawals/{wid}/complete -> 200 status success ---
    r = post(f"/admin/withdrawals/{wid}/complete", t_fin)
    _log("O. Finance complete withdrawal -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # --- P. U1 transactions row updated to success "Withdrawal paid" ---
    r = get("/transactions/me", t_u1)
    success_txn = None
    if r.status_code == 200:
        for tx in r.json():
            if tx.get("type") == "withdrawal" and tx.get("amount") == -300 and tx.get("status") == "success":
                success_txn = tx
                break
    _log("P1. Withdrawal txn status flipped to success", success_txn is not None)
    _log("P2. Description contains 'Withdrawal paid'",
         success_txn is not None and "Withdrawal paid" in (success_txn.get("description") or ""),
         str(success_txn.get("description") if success_txn else None))

    # --- Q. U1 GET /withdrawals/me status=success completed_at set ---
    r = get("/withdrawals/me", t_u1)
    wd = None
    if r.status_code == 200:
        for it in r.json():
            if it.get("id") == wid:
                wd = it
                break
    _log("Q1. /withdrawals/me has status=success",
         wd is not None and wd.get("status") == "success", str(wd.get("status") if wd else None))
    _log("Q2. completed_at set",
         wd is not None and wd.get("completed_at"), str(wd.get("completed_at") if wd else None))

    # --- R. WALLET TRANSFER: register U2, pay fee, super_admin approves ---
    u2_email = f"u2_{rand}@test.com"
    u2_password = "User@123"
    t_u2, u2 = register("Bob Two", u2_email, u2_password)
    _log("R1. Register U2", t_u2 is not None)
    r = post("/payment/register-fee", t_u2)
    _log("R2. U2 pay registration fee", r.status_code == 200)
    r = post(f"/admin/approvals/{u2['id']}/approve", t_super)
    _log("R3. Super approves U2", r.status_code == 200)

    # U1 currently has 700 (verify)
    r = get("/auth/me", t_u1)
    bal_u1 = r.json().get("wallet_balance") if r.status_code == 200 else None
    _log("R4. U1 balance is 700 (post-withdraw)", bal_u1 == 700, f"got {bal_u1}")

    # U1 transfer 200 to U2 by email
    r = post("/wallet/transfer", t_u1, {"recipient": u2_email, "amount": 200, "note": "test"})
    _log("R5. U1 transfer 200 to U2 -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    transfer_id = r.json().get("transfer_id") if r.status_code == 200 else None
    _log("R6. Transfer returns transfer_id", bool(transfer_id), str(transfer_id))

    # --- S. Verify balances U1=500, U2=200 ---
    r = get("/auth/me", t_u1)
    bal_u1 = r.json().get("wallet_balance")
    _log("S1. U1 wallet_balance == 500", bal_u1 == 500, f"got {bal_u1}")
    r = get("/auth/me", t_u2)
    bal_u2 = r.json().get("wallet_balance")
    _log("S2. U2 wallet_balance == 200", bal_u2 == 200, f"got {bal_u2}")

    # --- T. Transfer transactions on both sides ---
    r = get("/transactions/me", t_u1)
    out_txn = None
    if r.status_code == 200:
        for tx in r.json():
            if tx.get("type") == "transfer_out" and tx.get("amount") == -200:
                out_txn = tx
                break
    _log("T1. U1 has transfer_out -200", out_txn is not None)
    r = get("/transactions/me", t_u2)
    in_txn = None
    if r.status_code == 200:
        for tx in r.json():
            if tx.get("type") == "transfer_in" and tx.get("amount") == 200:
                in_txn = tx
                break
    _log("T2. U2 has transfer_in +200", in_txn is not None)

    # --- U. Transfer to self -> 400 "Cannot transfer to yourself" ---
    r = post("/wallet/transfer", t_u1, {"recipient": u1_email, "amount": 50})
    ok = r.status_code == 400 and "yourself" in r.text.lower()
    _log("U. Self-transfer -> 400 'Cannot transfer to yourself'", ok, f"{r.status_code} {r.text[:200]}")

    # --- V. Transfer to non-existent -> 404 "Recipient not found" ---
    r = post("/wallet/transfer", t_u1, {"recipient": "nobody@nowhere.xyz", "amount": 50})
    ok = r.status_code == 404 and "not found" in r.text.lower()
    _log("V. Transfer to non-existent -> 404 'Recipient not found'", ok, f"{r.status_code} {r.text[:200]}")

    # --- W. Negative amount -> 422 (validation) ---
    r = post("/wallet/transfer", t_u1, {"recipient": u2_email, "amount": -10})
    _log("W. Transfer negative amount -> 422", r.status_code == 422, f"{r.status_code} {r.text[:200]}")

    # --- X. Insufficient balance -> 400 "Insufficient balance" ---
    r = post("/wallet/transfer", t_u1, {"recipient": u2_email, "amount": 9999})
    ok = r.status_code == 400 and "insufficient" in r.text.lower()
    _log("X. Transfer insufficient balance -> 400 'Insufficient balance'", ok, f"{r.status_code} {r.text[:200]}")

    # --- Y. Recipient not approved -> register U3 (don't approve) ---
    u3_email = f"u3_{rand}@test.com"
    u3_password = "User@123"
    t_u3, u3 = register("Charlie Three", u3_email, u3_password)
    _log("Y1. Register U3 (pending)", t_u3 is not None)
    r = post("/wallet/transfer", t_u1, {"recipient": u3_email, "amount": 50})
    ok = r.status_code == 400 and "not approved" in r.text.lower()
    _log("Y2. Transfer to pending recipient -> 400 'Recipient is not approved yet'",
         ok, f"{r.status_code} {r.text[:200]}")

    # --- Z. Pending user (U3) tries to transfer -> 403 "awaiting admin approval" ---
    r = post("/wallet/transfer", t_u3, {"recipient": u2_email, "amount": 10})
    ok = r.status_code == 403 and ("awaiting" in r.text.lower() or "approval" in r.text.lower())
    _log("Z. Pending user transfer -> 403 'awaiting admin approval'",
         ok, f"{r.status_code} {r.text[:200]}")

    # --- REGRESSION sanity ---
    # finance can GET /admin/transactions
    r = get("/admin/transactions", t_fin, expect=200, name="REG1. Finance GET /admin/transactions -> 200")

    # finance can GET /admin/users
    r = get("/admin/users", t_fin, expect=200, name="REG2. Finance GET /admin/users -> 200")

    # Non-admin can't approve a withdrawal — use U2 token (regular user)
    # Need a fresh withdrawal id; use the existing wid (status=success now). Should still 403.
    r = post(f"/admin/withdrawals/{wid}/approve", t_u2)
    _log("REG3. Non-admin approve withdrawal -> 403",
         r.status_code == 403, f"{r.status_code} {r.text[:200]}")

    # Approve without auth -> 401/403
    r = requests.post(f"{API}/admin/withdrawals/{wid}/approve", timeout=30)
    _log("REG4. No-auth approve withdrawal -> 401/403",
         r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}")

    # POST /admin/users/{id}/promote with admin_role=finance accepts (we already created a finance via /admin/admins)
    # Promote U3 to finance, then demote back
    r = post(f"/admin/users/{u3['id']}/promote", t_super, {"admin_role": "finance"})
    _log("REG5. Super promote user to admin_role=finance -> 200",
         r.status_code == 200 and r.json().get("admin_role") == "finance",
         f"{r.status_code} {r.text[:200]}")

    # PATCH /admin/users/{id} with admin_role=finance for super_admin caller works
    r = patch(f"/admin/users/{u3['id']}", t_super, {"admin_role": "finance"})
    _log("REG6. Super PATCH admin_role=finance -> 200",
         r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Demote U3 back to user before cleanup
    r = post(f"/admin/users/{u3['id']}/demote", t_super)
    _log("REG7. Demote U3", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    # Withdrawal endpoints accept manager / support
    # Promote a fresh user to manager temporarily to verify? Use admin_role=manager via /admin/admins.
    mgr_email = f"mgr_{rand}@test.com"
    r = post("/admin/admins", t_super,
             {"name": "Mgr Test", "email": mgr_email, "password": "Mgr@12345", "admin_role": "manager"})
    if r.status_code == 200:
        mgr_id = r.json()["id"]
        t_mgr, _ = login(mgr_email, "Mgr@12345")
        # Make a new pending withdrawal by U2 to test manager approve path. U2 has 200 balance.
        r = post("/users/me/bank", t_u2, {"upi_id": "bob@upi"})
        r = post("/withdrawals", t_u2, {"amount": 50})
        if r.status_code == 200:
            wid2 = r.json()["id"]
            r = post(f"/admin/withdrawals/{wid2}/approve", t_mgr)
            _log("REG8. Manager approves withdrawal -> 200", r.status_code == 200,
                 f"{r.status_code} {r.text[:200]}")
            r = post(f"/admin/withdrawals/{wid2}/complete", t_mgr)
            _log("REG9. Manager completes withdrawal -> 200", r.status_code == 200,
                 f"{r.status_code} {r.text[:200]}")
        # cleanup mgr
        delete(f"/admin/users/{mgr_id}", t_super)

    # --- AA. Cleanup: delete U1, U2, U3, fin ---
    if u1 and u1.get("id"):
        r = delete(f"/admin/users/{u1['id']}", t_super, expect=200, name="AA1. Delete U1")
    if u2 and u2.get("id"):
        r = delete(f"/admin/users/{u2['id']}", t_super, expect=200, name="AA2. Delete U2")
    if u3 and u3.get("id"):
        r = delete(f"/admin/users/{u3['id']}", t_super, expect=200, name="AA3. Delete U3")
    if fin_id:
        r = delete(f"/admin/users/{fin_id}", t_super, expect=200, name="AA4. Delete finance admin")

    summary()


def summary():
    print("\n" + "=" * 70)
    print(f"PASSED: {len(PASSED)}")
    print(f"FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailed cases:")
        for n, d in FAILED:
            print(f"  - {n}: {d}")
    print("=" * 70)


if __name__ == "__main__":
    main()
