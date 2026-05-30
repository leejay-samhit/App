"""
Backend tests for the 2026-05-29 Commission Engine Change.

Validates:
 1. Sanity — GET /api/admin/system-wallet
 2. New endpoint shape — GET /api/admin/users/{user_id}/pending-levels
 3. Per-level counter increment (L2 pending_l2 += 1, no payout yet)
 4. Threshold-fire — pending_l2 reaches directs_required → L2 payout + l2_funding
 5. Idempotency — re-approve does NOT increment counters
 6. Ledger integrity — total == sum(buckets) (within tolerance)
 7. Regression — /services, /auth/login, /admin/service-categories
"""
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://vendor-network-app-1.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = "Nlee@1115"

EXPECTED_THRESHOLD = 4

def log(msg, *a):
    print(msg.format(*a) if a else msg, flush=True)

PASS_LIST: List[str] = []
FAIL_LIST: List[str] = []

def record_pass(name: str, note: str = ""):
    PASS_LIST.append(f"{name} :: {note}".rstrip(" :"))
    log("  PASS  {} {}", name, ("- " + note) if note else "")

def record_fail(name: str, note: str = ""):
    FAIL_LIST.append(f"{name} :: {note}".rstrip(" :"))
    log("  FAIL  {} {}", name, ("- " + note) if note else "")


class Client:
    def __init__(self, token: Optional[str] = None):
        self.s = requests.Session()
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"

    def _url(self, path: str) -> str:
        return f"{API}{path}" if path.startswith("/") else f"{API}/{path}"

    def post(self, path: str, payload: Optional[dict] = None, **kw):
        return self.s.post(self._url(path), json=(payload or {}), timeout=30, **kw)

    def get(self, path: str, **kw):
        return self.s.get(self._url(path), timeout=30, **kw)


def login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def admin_create_user(c: Client, name: str, email: str, password: str, referral_code: Optional[str] = None) -> Dict[str, Any]:
    payload = {
        "name": name,
        "email": email,
        "password": password,
        "phone": "9" + str(int(time.time() * 1000))[-9:],
        "mark_paid_offline": True,
        "registration_source": "offline_cash",
    }
    if referral_code:
        payload["referral_code"] = referral_code
    r = c.post("/admin/users/create", payload)
    if r.status_code != 200:
        raise RuntimeError(f"admin_create_user failed: {r.status_code} {r.text}")
    return r.json()["user"]


def admin_approve(c: Client, user_id: str) -> Dict[str, Any]:
    r = c.post(f"/admin/approvals/{user_id}/approve", {})
    if r.status_code != 200:
        raise RuntimeError(f"approve failed: {r.status_code} {r.text}")
    return r.json()


def get_pending_levels(c: Client, user_id: str) -> Dict[str, Any]:
    r = c.get(f"/admin/users/{user_id}/pending-levels")
    if r.status_code != 200:
        raise RuntimeError(f"pending-levels failed: {r.status_code} {r.text}")
    return r.json()


def get_system_wallet(c: Client) -> Dict[str, Any]:
    r = c.get("/admin/system-wallet")
    if r.status_code != 200:
        raise RuntimeError(f"system-wallet failed: {r.status_code} {r.text}")
    return r.json()


def list_user_txns(c: Client, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    for path in (
        f"/admin/users/{user_id}/transactions",
        f"/admin/users/{user_id}/ledger",
    ):
        r = c.get(path, params={"limit": limit})
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else (data.get("transactions") or data.get("items") or [])
    r = c.get("/admin/transactions", params={"user_id": user_id, "limit": limit})
    if r.status_code == 200:
        d = r.json()
        return d if isinstance(d, list) else (d.get("transactions") or d.get("items") or [])
    return []


def test_sanity_system_wallet(c: Client) -> Dict[str, Any]:
    log("\n[Test 1] Sanity GET /admin/system-wallet")
    sw = get_system_wallet(c)
    if not ({"buckets", "total", "deposits"} <= set(sw.keys())):
        record_fail("T1 system-wallet shape", f"keys={list(sw.keys())}")
        return sw
    log("    buckets keys: {}", sorted(sw["buckets"].keys()))
    log("    fee_residual={:.2f} referral_commission={:.2f} direct_signup={:.2f} direct_added={:.2f} total={:.2f}",
        sw["buckets"].get("fee_residual") or 0,
        sw["buckets"].get("referral_commission") or 0,
        sw["buckets"].get("direct_signup") or 0,
        sw["buckets"].get("direct_added") or 0,
        sw["total"])
    record_pass("T1 system-wallet sanity")
    return sw


def test_pending_levels_shape(c: Client) -> None:
    log("\n[Test 2] /admin/users/<id>/pending-levels shape")
    r = c.get("/admin/users", params={"limit": 20})
    if r.status_code != 200:
        record_fail("T2 list users", f"{r.status_code} {r.text[:200]}")
        return
    data = r.json()
    users = data if isinstance(data, list) else (data.get("users") or data.get("items") or [])
    if not users:
        record_fail("T2 list users", "empty")
        return
    target = next((u for u in users if u.get("role") == "user"), users[0])
    uid = target.get("id")
    res = get_pending_levels(c, uid)
    if "levels" not in res or len(res["levels"]) != 10:
        record_fail("T2 pending-levels shape", f"levels len={len(res.get('levels') or [])}")
        return
    required_keys = {"level", "pending", "threshold", "remaining", "payout_inr", "ready"}
    bad = [i for i, row in enumerate(res["levels"]) if not required_keys.issubset(row.keys())]
    if bad:
        record_fail("T2 row keys", f"bad rows at {bad}")
        return
    levels = [row["level"] for row in res["levels"]]
    if levels != list(range(1, 11)):
        record_fail("T2 row order", f"levels={levels}")
        return
    thr = res["levels"][1]["threshold"]
    record_pass("T2 pending-levels 10 rows", f"threshold={thr}")


def test_chain_counter_and_threshold(c: Client) -> None:
    log("\n[Test 3-6] Chain B->A->N* counter, threshold-fire, idempotency, ledger")
    stamp = int(time.time())
    pwd = "Test@1234"

    log("  > creating root B (no sponsor)")
    B = admin_create_user(c, "ChainRoot Bharat", f"chain_b_{stamp}@example.com", pwd)
    admin_approve(c, B["id"])

    log("  > creating A under B.referral_code={}", B["referral_code"])
    A = admin_create_user(c, "Mid Anil", f"chain_a_{stamp}@example.com", pwd, referral_code=B["referral_code"])
    admin_approve(c, A["id"])

    pl_B = get_pending_levels(c, B["id"])
    pending_l2_B = next(row["pending"] for row in pl_B["levels"] if row["level"] == 2)
    threshold = pl_B["threshold_per_level"]
    log("    after A approved: B.pending_l2={} (expect 0), threshold={}", pending_l2_B, threshold)
    if pending_l2_B == 0:
        record_pass("T3 pre-state B.pending_l2==0 after A approval")
    else:
        record_fail("T3 pre-state B.pending_l2 should be 0", f"got {pending_l2_B}")

    log("  > creating + approving N1 under A.referral_code={}", A["referral_code"])
    N1 = admin_create_user(c, "Down Naveen 1", f"chain_n1_{stamp}@example.com", pwd, referral_code=A["referral_code"])
    sw_before_n1 = get_system_wallet(c)
    admin_approve(c, N1["id"])

    pl_B = get_pending_levels(c, B["id"])
    pl_A = get_pending_levels(c, A["id"])
    pending_l2_B = next(row["pending"] for row in pl_B["levels"] if row["level"] == 2)
    pending_l1_A = next(row["pending"] for row in pl_A["levels"] if row["level"] == 1)
    sw_after_n1 = get_system_wallet(c)
    log("    after N1: B.pending_l2={} (expect 1), A.pending_l1={} (expect 1)", pending_l2_B, pending_l1_A)
    log("    Δref_commission=₹{:+.2f}  Δfee_residual=₹{:+.2f}  Δtotal=₹{:+.2f}",
        (sw_after_n1["buckets"].get("referral_commission") or 0) - (sw_before_n1["buckets"].get("referral_commission") or 0),
        (sw_after_n1["buckets"].get("fee_residual") or 0) - (sw_before_n1["buckets"].get("fee_residual") or 0),
        sw_after_n1["total"] - sw_before_n1["total"])

    if pending_l2_B == 1:
        record_pass("T3 L2 counter increments to 1")
    else:
        record_fail("T3 L2 counter should be 1", f"got {pending_l2_B}")

    if pending_l1_A == 1:
        record_pass("T3 L1 counter on A == 1")
    else:
        record_fail("T3 L1 counter on A should be 1", f"got {pending_l1_A}")

    txns_B = list_user_txns(c, B["id"], limit=50)
    payouts_B = [t for t in txns_B if t.get("type") == "referral_payout"]
    if not payouts_B:
        record_pass("T3 No referral_payout to B yet")
    else:
        record_fail("T3 unexpected referral_payout to B", f"count={len(payouts_B)}")

    log("  > re-approving N1 (idempotency)")
    re_resp = admin_approve(c, N1["id"])
    pl_B_after = get_pending_levels(c, B["id"])
    pl_A_after = get_pending_levels(c, A["id"])
    pending_l2_B_after = next(row["pending"] for row in pl_B_after["levels"] if row["level"] == 2)
    pending_l1_A_after = next(row["pending"] for row in pl_A_after["levels"] if row["level"] == 1)
    if re_resp.get("already_approved") and pending_l2_B_after == pending_l2_B and pending_l1_A_after == pending_l1_A:
        record_pass("T5 Idempotency - re-approve no-op")
    else:
        record_fail("T5 Idempotency",
                    f"resp={re_resp}, l2 {pending_l2_B}->{pending_l2_B_after}, l1 {pending_l1_A}->{pending_l1_A_after}")

    fire_target = threshold
    remaining_needed = fire_target - pending_l2_B_after
    log("  > firing L2: need {} more approvals (threshold={})", remaining_needed, fire_target)

    fired_signup_id = None
    for i in range(remaining_needed):
        idx = i + 2
        nu = admin_create_user(c, f"Down Naveen {idx}", f"chain_n{idx}_{stamp}@example.com", pwd,
                               referral_code=A["referral_code"])
        sw_before = get_system_wallet(c)
        admin_approve(c, nu["id"])
        sw_after = get_system_wallet(c)
        pl_B_now = get_pending_levels(c, B["id"])
        l2_now = next(row["pending"] for row in pl_B_now["levels"] if row["level"] == 2)
        log("    N{} approved: B.pending_l2={}  Δfee_residual=₹{:+.2f}  Δtotal=₹{:+.2f}",
            idx, l2_now,
            (sw_after["buckets"].get("fee_residual") or 0) - (sw_before["buckets"].get("fee_residual") or 0),
            sw_after["total"] - sw_before["total"])
        if i == remaining_needed - 1:
            fired_signup_id = nu["id"]

    pl_B_final = get_pending_levels(c, B["id"])
    l2_pending_final = next(row["pending"] for row in pl_B_final["levels"] if row["level"] == 2)
    if l2_pending_final == 0:
        record_pass("T4 B.pending_l2 reset to 0 after threshold fire")
    else:
        record_fail("T4 B.pending_l2 should reset to 0", f"got {l2_pending_final}")

    txns_B = list_user_txns(c, B["id"], limit=200)
    l2_payouts = [t for t in txns_B
                  if t.get("type") == "referral_payout"
                  and (t.get("level") == 2 or "L2" in (t.get("description") or "") or "level 2" in (t.get("description") or "").lower())]
    any_payouts = [t for t in txns_B if t.get("type") == "referral_payout"]
    if l2_payouts:
        amt = sum(float(t.get("amount") or t.get("net_amount") or 0) for t in l2_payouts)
        record_pass("T4 referral_payout L2 to B", f"count={len(l2_payouts)} amt≈₹{amt:.2f}")
    elif any_payouts:
        record_pass("T4 referral_payout to B (level marker missing in description)",
                    f"count={len(any_payouts)}")
    else:
        log("    DEBUG B txns count={}, sample={}", len(txns_B), txns_B[:3])
        record_fail("T4 referral_payout to B", "no payout txn found after threshold fire")

    # Admin l2_funding txn
    admin_uid = None
    r_me = c.get("/auth/me")
    if r_me.status_code == 200:
        admin_uid = r_me.json().get("id")
    l2_funding_found = False
    if admin_uid:
        admin_txns = list_user_txns(c, admin_uid, limit=500)
        l2_funding_txns = [t for t in admin_txns if t.get("type") == "l2_funding"]
        if l2_funding_txns:
            recent = l2_funding_txns[0]
            log("    l2_funding amount={} source_bucket={} related_signup={}",
                recent.get("amount"), recent.get("source_bucket"), recent.get("related_signup_id"))
            l2_funding_found = True
        else:
            log("    DEBUG admin txn types sample: {}",
                sorted({t.get("type") for t in admin_txns})[:20])
    if l2_funding_found:
        record_pass("T4 admin l2_funding txn written")
    else:
        record_fail("T4 admin l2_funding txn", "no l2_funding txn found in admin ledger")

    sw = get_system_wallet(c)
    s = sum(float(v or 0) for v in sw["buckets"].values())
    drift = abs(s - float(sw["total"]))
    log("    final Σ(buckets)=₹{:.2f}  total=₹{:.2f}  drift=₹{:.4f}", s, sw["total"], drift)
    if drift < 0.5:
        record_pass("T6 Ledger Σ(buckets) ≈ total", f"drift=₹{drift:.4f}")
    else:
        record_fail("T6 Ledger drift", f"Σ={s:.2f}, total={sw['total']:.2f}, drift=₹{drift:.2f}")


def test_regression(c: Client) -> None:
    log("\n[Test 7] Regression")
    r = c.get("/services")
    if r.status_code == 200:
        record_pass("T7 GET /services 200")
    else:
        record_fail("T7 GET /services", f"{r.status_code}")
    rl = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if rl.status_code == 200:
        record_pass("T7 POST /auth/login admin 200")
    else:
        record_fail("T7 POST /auth/login admin", f"{rl.status_code}")
    rc = c.get("/admin/service-categories")
    if rc.status_code == 200:
        record_pass("T7 GET /admin/service-categories 200")
    else:
        record_fail("T7 GET /admin/service-categories", f"{rc.status_code}")


def main():
    log("=" * 72)
    log("Commission engine 2026-05-29 — backend tests")
    log("API base: {}", API)
    log("=" * 72)

    token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    log("admin login OK ({}...)", token[:24])
    c = Client(token)

    test_sanity_system_wallet(c)
    test_pending_levels_shape(c)
    test_chain_counter_and_threshold(c)
    test_regression(c)

    log("\n" + "=" * 72)
    log("SUMMARY")
    log("=" * 72)
    log("PASS ({}):", len(PASS_LIST))
    for p in PASS_LIST:
        log("  PASS  {}", p)
    log("\nFAIL ({}):", len(FAIL_LIST))
    for f in FAIL_LIST:
        log("  FAIL  {}", f)
    log("=" * 72)
    sys.exit(0 if not FAIL_LIST else 1)


if __name__ == "__main__":
    main()
