"""
Ledger Drift Self-Heal Upgrade — End-to-End Test (v2, dynamic-seed)
====================================================================
Verifies the new behaviour added in /app/backend/server.py at the
startup `_background_init` self-healer (lines 6579-6744):

  1) `_compute_money_flow_snapshot` adds `legacy_reconcile_inflow`
     to its inflow sum (server.py:6015).
  2) Startup self-heal inflow tally also adds `legacy_reconcile_inflow`
     for idempotency on restart (server.py:6609).
  3) Step 2 positive-drift branch now INSERTS one
     `legacy_reconcile_inflow` txn instead of SKIPping with a warning
     (server.py:6692-6730).

Because the test env may already carry pre-existing drift that
step-1 won't move, we compute the seed dynamically so step-2 always
fires with a predictable amount.
"""
import asyncio
import time
import subprocess
import requests
from motor.motor_asyncio import AsyncIOMotorClient

# ─── Config ─────────────────────────────────────────────────────
BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "referral_ecom_db"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASS = "Test@123"

# Target Step-2 audit-txn amount (must equal post-step-1 drift)
TARGET_AUDIT = 50.0
BACKEND_OUT_LOG = "/var/log/supervisor/backend.out.log"
BACKEND_ERR_LOG = "/var/log/supervisor/backend.err.log"

PASS = 0
FAIL = 0
FAILS = []


def _p(tag, ok, msg=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {tag}  {msg}")
    else:
        FAIL += 1
        FAILS.append(f"{tag} — {msg}")
        print(f"  ❌ {tag}  {msg}")


def post(path, body=None, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.post(BASE + path, json=body, headers=h, timeout=30)


def get(path, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.get(BASE + path, headers=h, timeout=30)


def login(email, pw):
    r = post("/auth/login", {"email": email, "password": pw})
    if r.status_code != 200:
        print(f"LOGIN FAILED {email}: {r.status_code} {r.text[:200]}")
        return None
    j = r.json()
    return j.get("token") or j.get("access_token")


# ── mongo helpers ───────────────────────────────────────────────
async def _state():
    c = AsyncIOMotorClient(MONGO_URL)
    db = c[DB_NAME]
    admin = await db.users.find_one({"email": ADMIN_EMAIL})
    user = await db.users.find_one({"email": USER_EMAIL})
    cnt = await db.transactions.count_documents({"type": "legacy_reconcile_inflow"})
    rows = await db.transactions.find(
        {"type": "legacy_reconcile_inflow"}, {"_id": 0}
    ).to_list(50)
    c.close()
    return {
        "admin_id": admin["id"],
        "admin_balance": float(admin.get("wallet_balance") or 0),
        "admin_buckets": admin.get("wallet_buckets") or {},
        "user_id": user["id"],
        "user_balance": float(user.get("wallet_balance") or 0),
        "user_role": user.get("role"),
        "lri_count": cnt,
        "lri_rows": rows,
    }


def mongo_state():
    return asyncio.run(_state())


async def _seed(amount):
    c = AsyncIOMotorClient(MONGO_URL)
    db = c[DB_NAME]
    await db.users.update_one({"email": USER_EMAIL}, {"$inc": {"wallet_balance": amount}})
    c.close()


async def _cleanup(seed_amt, restore_admin_to):
    """Restore env: debit seed from user, delete LRI rows, set admin balance back."""
    c = AsyncIOMotorClient(MONGO_URL)
    db = c[DB_NAME]
    await db.users.update_one({"email": USER_EMAIL}, {"$inc": {"wallet_balance": -seed_amt}})
    await db.transactions.delete_many({"type": "legacy_reconcile_inflow"})
    if restore_admin_to is not None:
        await db.users.update_one(
            {"email": ADMIN_EMAIL}, {"$set": {"wallet_balance": float(restore_admin_to)}}
        )
    c.close()


async def _find_user(email):
    c = AsyncIOMotorClient(MONGO_URL)
    db = c[DB_NAME]
    u = await db.users.find_one({"email": email})
    c.close()
    return u


def restart_backend(wait=40):
    print(f"\n  ⟳ supervisorctl restart backend (wait up to {wait}s)…")
    subprocess.run(
        ["sudo", "supervisorctl", "restart", "backend"],
        capture_output=True, text=True, timeout=60,
    )
    time.sleep(wait)
    for _ in range(20):
        try:
            if requests.get(BASE + "/branding", timeout=5).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(2)
    # extra grace for _background_init to complete self-heal
    time.sleep(12)


def tail_logs():
    out = ""
    for f in (BACKEND_OUT_LOG, BACKEND_ERR_LOG):
        try:
            res = subprocess.run(["tail", "-n", "800", f], capture_output=True, text=True, timeout=10)
            out += res.stdout + "\n"
        except Exception:
            pass
    return out


def section(name):
    print(f"\n══════════ {name} ══════════")


def main():
    section("Phase 0 — Pre-state snapshot (and baseline drift)")
    pre = mongo_state()
    print(f"  admin_balance pre   = ₹{pre['admin_balance']}")
    print(f"  user_balance  pre   = ₹{pre['user_balance']}")
    print(f"  user_role           = {pre['user_role']}")
    print(f"  lri_count     pre   = {pre['lri_count']}")
    _p("P0.1 user is role=user", pre["user_role"] == "user", f"role={pre['user_role']}")

    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    user_tok = login(USER_EMAIL, USER_PASS)
    _p("P0.2 admin login 200", admin_tok is not None)
    _p("P0.3 user  login 200", user_tok is not None)

    r = get("/admin/ledger-alerts", admin_tok)
    _p("P0.4 GET /admin/ledger-alerts 200", r.status_code == 200, f"status={r.status_code}")
    snap = r.json().get("current", {}) if r.status_code == 200 else {}
    baseline_drift = float(snap.get("drift") or 0)
    baseline_inflow = float(snap.get("inflow") or 0)
    print(f"  baseline_drift      = ₹{baseline_drift}")
    print(f"  baseline_inflow     = ₹{baseline_inflow}")

    # Choose seed so post-restart drift2 == TARGET_AUDIT (₹50)
    # drift_after_seed = baseline_drift + seed. We want it = TARGET_AUDIT.
    seed_amount = round(TARGET_AUDIT - baseline_drift, 2)
    if seed_amount <= 0:
        seed_amount = TARGET_AUDIT  # safety
    print(f"  seed_amount         = ₹{seed_amount}  (expected step-2 audit ₹{TARGET_AUDIT})")

    # Pre-clean: ensure no leftover LRI rows from any prior attempt
    asyncio.run(_cleanup(0, None))

    # ── Phase A+B ───────────────────────────────────────────
    section("Phase A+B — Seed phantom into user wallet (bypass txn)")
    asyncio.run(_seed(seed_amount))
    after_seed = mongo_state()
    print(f"  user_balance after seed = ₹{after_seed['user_balance']}")
    _p("A.1 user wallet incremented by seed",
       round(after_seed["user_balance"] - pre["user_balance"], 2) == seed_amount,
       f"delta=₹{after_seed['user_balance'] - pre['user_balance']}")
    _p("A.2 admin wallet_balance unchanged after seed",
       round(after_seed["admin_balance"], 2) == round(pre["admin_balance"], 2))

    pre_restart_admin_balance = after_seed["admin_balance"]
    pre_restart_user_balance = after_seed["user_balance"]

    # ── Phase C: Restart #1 ─────────────────────────────────
    section("Phase C — Restart backend #1 (trigger startup self-heal)")
    restart_backend(wait=42)

    rh = get("/branding")
    _p("C.0 backend healthy after restart#1", rh.status_code == 200, f"status={rh.status_code}")

    after_r1 = mongo_state()
    print(f"  admin_balance after R1 = ₹{after_r1['admin_balance']}")
    print(f"  user_balance  after R1 = ₹{after_r1['user_balance']}")
    print(f"  lri_count     after R1 = {after_r1['lri_count']}")
    for row in after_r1["lri_rows"]:
        print(
            f"    row → amount=₹{row.get('amount')} status={row.get('status')} "
            f"type={row.get('type')} is_auto_heal={row.get('is_auto_heal')} "
            f"legacy_reconcile={row.get('legacy_reconcile')} "
            f"user_id={row.get('user_id')}"
        )

    _p("C.1 exactly ONE legacy_reconcile_inflow txn",
       after_r1["lri_count"] == 1, f"count={after_r1['lri_count']}")

    if after_r1["lri_rows"]:
        row = after_r1["lri_rows"][0]
        _p(f"C.2 amount ≈ ₹{TARGET_AUDIT} (matches drift2)",
           abs(round(float(row.get("amount") or 0), 2) - TARGET_AUDIT) <= 1.0,
           f"amount={row.get('amount')}")
        _p("C.3 status = success", row.get("status") == "success",
           f"status={row.get('status')}")
        _p("C.4 is_auto_heal = True", row.get("is_auto_heal") is True,
           f"={row.get('is_auto_heal')}")
        _p("C.5 legacy_reconcile = True", row.get("legacy_reconcile") is True,
           f"={row.get('legacy_reconcile')}")
        _p("C.6 user_id = admin.id", row.get("user_id") == pre["admin_id"],
           f"got={row.get('user_id')} expected={pre['admin_id']}")
        _p("C.7 type = legacy_reconcile_inflow",
           row.get("type") == "legacy_reconcile_inflow", f"type={row.get('type')}")
    else:
        for tag in ("C.2", "C.3", "C.4", "C.5", "C.6", "C.7"):
            _p(tag, False, "no legacy_reconcile_inflow row to inspect")

    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    r = get("/admin/ledger-alerts", admin_tok)
    if r.status_code == 200:
        cur_drift = float(r.json().get("current", {}).get("drift") or 0)
        print(f"  drift after R1 = ₹{cur_drift}")
        _p("C.8 live drift ≤ ₹1", abs(cur_drift) <= 1.0, f"drift={cur_drift}")
    else:
        _p("C.8 /admin/ledger-alerts 200 post-R1", False,
           f"status={r.status_code} body={r.text[:200]}")

    # Admin balance unchanged across restart (bucket reset shouldn't shift
    # admin if buckets were already matching sum(txns), AND audit txn must
    # NOT credit admin)
    _p("C.9 admin wallet_balance UNCHANGED across restart "
       "(audit txn did NOT inflate admin)",
       round(after_r1["admin_balance"], 2) == round(pre_restart_admin_balance, 2),
       f"pre=₹{pre_restart_admin_balance} post=₹{after_r1['admin_balance']}")

    _p("C.10 user wallet_balance UNCHANGED (no debit applied)",
       round(after_r1["user_balance"], 2) == round(pre_restart_user_balance, 2),
       f"pre=₹{pre_restart_user_balance} post=₹{after_r1['user_balance']}")

    logs = tail_logs()
    has_recognition = "Drift self-heal step 2 (phantom inflow recognition)" in logs
    has_skip = "Drift self-heal step 2 SKIP" in logs
    _p("C.11 log line 'Drift self-heal step 2 (phantom inflow recognition)' present",
       has_recognition)
    _p("C.12 log line 'Drift self-heal step 2 SKIP' NOT present", not has_skip)

    # Print the relevant heal lines for evidence
    print("\n  ── Heal-related log lines ──")
    for line in logs.splitlines():
        if "Drift self-heal" in line or "[LEDGER ALERT]" in line:
            print(f"    {line[:240]}")

    # ── Phase D: Idempotency ────────────────────────────────
    section("Phase D — Restart backend #2 (idempotency)")
    snapshot_admin_before_r2 = after_r1["admin_balance"]
    restart_backend(wait=42)
    rh = get("/branding")
    _p("D.0 backend healthy after restart#2", rh.status_code == 200, f"status={rh.status_code}")

    after_r2 = mongo_state()
    print(f"  lri_count     after R2 = {after_r2['lri_count']}")
    print(f"  admin_balance after R2 = ₹{after_r2['admin_balance']}")
    _p("D.1 still exactly ONE legacy_reconcile_inflow txn after R2",
       after_r2["lri_count"] == 1, f"count={after_r2['lri_count']}")
    _p("D.2 admin wallet_balance still unchanged after R2",
       round(after_r2["admin_balance"], 2) == round(snapshot_admin_before_r2, 2),
       f"R1=₹{snapshot_admin_before_r2} R2=₹{after_r2['admin_balance']}")

    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    r = get("/admin/ledger-alerts", admin_tok)
    if r.status_code == 200:
        d2 = float(r.json().get("current", {}).get("drift") or 0)
        print(f"  drift after R2 = ₹{d2}")
        _p("D.3 live drift still ≤ ₹1 after R2", abs(d2) <= 1.0, f"drift={d2}")

    # ── Phase E: Regression ─────────────────────────────────
    section("Phase E — Regression sweep")
    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    user_tok = login(USER_EMAIL, USER_PASS)
    _p("E.1 POST /auth/login admin 200", admin_tok is not None)
    _p("E.2 POST /auth/login user  200", user_tok is not None)

    r = get("/admin/system-wallet", admin_tok)
    _p("E.3 GET /admin/system-wallet 200", r.status_code == 200, f"status={r.status_code}")

    r = get("/admin/ledger-alerts", admin_tok)
    _p("E.4 GET /admin/ledger-alerts 200", r.status_code == 200, f"status={r.status_code}")

    r = get("/admin/users?limit=5", admin_tok)
    _p("E.5 GET /admin/users 200", r.status_code == 200, f"status={r.status_code}")

    # MLM network endpoint (correct path)
    r = get("/users/me/network", user_tok)
    _p("E.6 GET /users/me/network 200", r.status_code == 200, f"status={r.status_code}")

    r = get("/products")
    _p("E.7 GET /products (public) 200", r.status_code == 200, f"status={r.status_code}")

    r = get("/services")
    _p("E.8 GET /services 200/404 (env-dependent)",
       r.status_code in (200, 404), f"status={r.status_code}")

    r = get("/admin/distributors", admin_tok)
    _p("E.8b GET /admin/distributors 200", r.status_code == 200, f"status={r.status_code}")

    # Offline-create regression — use admin's real referral code 'EARN'
    import random
    sfx = random.randint(100000, 999999)
    test_email = f"ledger_drift_qa_{sfx}@app.com"
    body = {
        "name": "Ledger Drift QA",
        "email": test_email,
        "password": "Test@1234",
        "phone": f"9{sfx}",
        "referral_code": "EARN",
        "mark_paid_offline": True,
        "registration_source": "offline_cash",
    }
    r = post("/admin/users/create", body, admin_tok)
    print(f"  /admin/users/create → {r.status_code} {r.text[:200]}")
    if r.status_code == 200:
        _p("E.9 POST /admin/users/create (offline) 200", True)
        u_doc = asyncio.run(_find_user(test_email))
        marker = (u_doc or {}).get("offline_pre_credit_amount")
        _p("E.10 offline_pre_credit_amount stamped on new user",
           marker is not None and float(marker) > 0,
           f"offline_pre_credit_amount={marker}")
        # Cleanup created user
        if u_doc:
            d = requests.delete(
                BASE + f"/admin/users/{u_doc['id']}",
                headers={"Authorization": f"Bearer {admin_tok}"},
                timeout=30,
            )
            print(f"  cleanup user delete → {d.status_code}")
            # If delete endpoint missing, drop directly from Mongo to avoid lingering test users
            if d.status_code not in (200, 204):
                async def _drop():
                    c = AsyncIOMotorClient(MONGO_URL); db = c[DB_NAME]
                    await db.users.delete_one({"email": test_email})
                    await db.transactions.delete_many({"user_id": u_doc["id"]})
                    await db.system_wallet_deposits.delete_many({"linked_user_id": u_doc["id"]})
                    c.close()
                asyncio.run(_drop())
                print(f"  fallback Mongo cleanup performed")
    else:
        _p("E.9 POST /admin/users/create (offline) 200",
           False, f"status={r.status_code} body={r.text[:200]}")
        _p("E.10 offline_pre_credit_amount stamped on new user", False, "skipped — create failed")

    # ── Phase F: Cleanup ────────────────────────────────────
    section("Phase F — Cleanup (restore env to pre-test state)")
    asyncio.run(_cleanup(seed_amount, pre["admin_balance"]))
    final = mongo_state()
    print(f"  user_balance final  = ₹{final['user_balance']}")
    print(f"  admin_balance final = ₹{final['admin_balance']}")
    print(f"  lri_count    final  = {final['lri_count']}")

    section("RESULTS")
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    if FAILS:
        print("\nFAILURES:")
        for f in FAILS:
            print(f"  • {f}")
    return FAIL == 0


if __name__ == "__main__":
    ok = main()
    raise SystemExit(0 if ok else 1)
