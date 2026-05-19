"""
Phase 2B refactor verification — Tickets + Pincodes extraction.

Sections:
  A — Tickets smoke (user + admin)
  B — Pincodes smoke
  C — Ledger integrity re-confirm
  D — Regression on pre-existing core flows

Run: python /app/backend_test.py
"""
import os
import sys
import json
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE = os.environ.get("BACKEND_URL", "").strip()
if not BASE:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                line = line.strip()
                if line.startswith("EXPO_PUBLIC_BACKEND_URL=") or line.startswith("REACT_APP_BACKEND_URL="):
                    BASE = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
if not BASE:
    BASE = "http://localhost:8001"
API = BASE.rstrip("/") + "/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
TESTUSER_EMAIL = "testuser@app.com"
TESTUSER_PASS = "Test@123"
TIMEOUT = 30

results: List[Tuple[str, bool, str]] = []


def log(msg: str):
    print(msg, flush=True)


def record(name: str, ok: bool, details: str = ""):
    status = "PASS" if ok else "FAIL"
    log(f"[{status}] {name}: {details}")
    results.append((name, ok, details))


def login(email: str, password: str) -> Optional[str]:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    if r.status_code != 200:
        log(f"  login {email} -> {r.status_code} {r.text[:200]}")
        return None
    body = r.json()
    return body.get("token") or body.get("access_token")


def H(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def G(path: str, tok: str, params=None):
    return requests.get(f"{API}{path}", headers=H(tok), params=params, timeout=TIMEOUT)


def P(path: str, tok: str, body=None):
    return requests.post(f"{API}{path}", headers=H(tok), json=body or {}, timeout=TIMEOUT)


def PATCH(path: str, tok: str, body=None):
    return requests.patch(f"{API}{path}", headers=H(tok), json=body or {}, timeout=TIMEOUT)


log(f"==> API base: {API}")

testuser_tok = login(TESTUSER_EMAIL, TESTUSER_PASS)
if not testuser_tok:
    log("FATAL: cannot log in testuser")
    sys.exit(1)
admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
if not admin_tok:
    log("FATAL: cannot log in admin")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════
# A — TICKETS SMOKE
# ════════════════════════════════════════════════════════════════════
log("\n========= A — Tickets smoke =========")
A_OK = True
ticket_id: Optional[str] = None

# A.1 user login already done
record("A.1 login as testuser", True, "token acquired (json 'token')")

# A.2 create ticket
r = P("/tickets", testuser_tok, {"subject": "refactor test", "message": "verifying", "category": "other"})
ok = r.status_code == 200 and r.json().get("ok") is True and r.json().get("ticket", {}).get("id")
if ok:
    ticket_id = r.json()["ticket"]["id"]
record("A.2 POST /tickets", ok, f"status={r.status_code} ticket_id={ticket_id}")
A_OK = A_OK and ok

# A.3 my tickets
r = G("/tickets/me", testuser_tok)
data = r.json() if r.status_code == 200 else {}
items = data.get("items", [])
ok = r.status_code == 200 and len(items) >= 1
record("A.3 GET /tickets/me", ok, f"status={r.status_code} items={len(items)}")
A_OK = A_OK and ok

# A.4 read ticket
if ticket_id:
    r = G(f"/tickets/{ticket_id}", testuser_tok)
    data = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and data.get("ticket") and isinstance(data.get("messages"), list)
    msg_count = len(data.get("messages", []))
    record("A.4 GET /tickets/{id}", ok, f"status={r.status_code} messages={msg_count}")
    A_OK = A_OK and ok

# A.5 user reply
if ticket_id:
    r = P(f"/tickets/{ticket_id}/reply", testuser_tok, {"message": "user follow-up"})
    data = r.json() if r.status_code == 200 else {}
    mc = (data.get("ticket") or {}).get("message_count")
    ok = r.status_code == 200 and mc == 2
    record("A.5 POST /tickets/{id}/reply (user)", ok, f"status={r.status_code} message_count={mc}")
    A_OK = A_OK and ok

# A.6 admin token already obtained
record("A.6 login as admin", True, "token acquired")

# A.7 admin list
r = G("/admin/tickets", admin_tok)
data = r.json() if r.status_code == 200 else {}
counts = data.get("counts")
ok = r.status_code == 200 and isinstance(data.get("items"), list) and isinstance(counts, dict)
record("A.7 GET /admin/tickets", ok, f"status={r.status_code} total={data.get('total')} counts={counts}")
A_OK = A_OK and ok

# A.8 admin stats
r = G("/admin/tickets/stats", admin_tok)
data = r.json() if r.status_code == 200 else {}
required = {"open", "in_progress", "resolved", "closed", "total", "unread_admin"}
ok = r.status_code == 200 and required.issubset(set(data.keys()))
record("A.8 GET /admin/tickets/stats", ok, f"status={r.status_code} keys={sorted(data.keys())}")
A_OK = A_OK and ok

# A.9 PATCH ticket priority
if ticket_id:
    r = PATCH(f"/admin/tickets/{ticket_id}", admin_tok, {"priority": "high"})
    data = r.json() if r.status_code == 200 else {}
    pr = (data.get("ticket") or {}).get("priority")
    ok = r.status_code == 200 and pr == "high"
    record("A.9 PATCH /admin/tickets/{id} {priority:high}", ok, f"status={r.status_code} priority={pr}")
    A_OK = A_OK and ok

# A.10 admin reply -> moves to in_progress
if ticket_id:
    r = P(f"/tickets/{ticket_id}/reply", admin_tok, {"message": "admin reply"})
    data = r.json() if r.status_code == 200 else {}
    st = (data.get("ticket") or {}).get("status")
    ok = r.status_code == 200 and st == "in_progress"
    record("A.10 admin reply moves status to in_progress", ok, f"status={r.status_code} ticket.status={st}")
    A_OK = A_OK and ok

# A.11 user closes
if ticket_id:
    r = P(f"/tickets/{ticket_id}/close", testuser_tok, {})
    ok = r.status_code == 200
    # verify
    r2 = G(f"/tickets/{ticket_id}", testuser_tok)
    st = (r2.json().get("ticket") or {}).get("status") if r2.status_code == 200 else None
    ok = ok and st == "closed"
    record("A.11 POST /tickets/{id}/close (user)", ok, f"status={r.status_code} ticket.status={st}")
    A_OK = A_OK and ok


# ════════════════════════════════════════════════════════════════════
# B — PINCODES SMOKE
# ════════════════════════════════════════════════════════════════════
log("\n========= B — Pincodes smoke =========")
B_OK = True

# B.2 search q=110 limit=3
r = G("/admin/pincodes/search", admin_tok, params={"q": "110", "limit": 3})
data = r.json() if r.status_code == 200 else {}
items = data.get("items", [])
ok = r.status_code == 200 and len(items) <= 3 and all(str(x.get("pincode", "")).startswith("110") for x in items)
record("B.2 GET /admin/pincodes/search?q=110&limit=3", ok,
       f"status={r.status_code} items={len(items)} sample={[x.get('pincode') for x in items[:3]]}")
B_OK = B_OK and ok

# B.3 in-region state=Delhi
r = G("/admin/pincodes/in-region", admin_tok, params={"state": "Delhi", "limit": 10})
data = r.json() if r.status_code == 200 else {}
items = data.get("items", [])
ok = r.status_code == 200 and len(items) >= 1 and all(str(x.get("state", "")).lower() == "delhi" for x in items)
record("B.3 GET /admin/pincodes/in-region?state=Delhi", ok,
       f"status={r.status_code} items={len(items)} states={set(x.get('state') for x in items)}")
B_OK = B_OK and ok

# B.4 single pincode lookup
r = G("/admin/pincodes/110001", admin_tok)
data = r.json() if r.status_code == 200 else {}
ok = r.status_code == 200 and data.get("pincode") == "110001" and "assigned_to" in data
record("B.4 GET /admin/pincodes/110001", ok,
       f"status={r.status_code} pincode={data.get('pincode')} assigned_to={data.get('assigned_to')}")
B_OK = B_OK and ok

# B.5 in-region with no params -> 400
r = G("/admin/pincodes/in-region", admin_tok)
ok = r.status_code == 400
detail = ""
try:
    detail = r.json().get("detail", "")
except Exception:
    pass
ok = ok and "state or district is required" in str(detail).lower()
record("B.5 GET /admin/pincodes/in-region (no params) -> 400", ok,
       f"status={r.status_code} detail={detail}")
B_OK = B_OK and ok


# ════════════════════════════════════════════════════════════════════
# C — LEDGER INTEGRITY RE-CONFIRM
# ════════════════════════════════════════════════════════════════════
log("\n========= C — Ledger integrity re-confirm =========")
C_OK = True

r = G("/admin/system-wallet/breakdown", admin_tok)
if r.status_code == 200:
    bd = r.json()
    infl = float(bd["inflow"]["total"])
    outfl = float(bd["outflow"]["total"])
    drift = abs(infl - outfl)
    ok = drift <= 2.0
    record("C.1 |inflow - outflow| <= ₹2", ok,
           f"inflow=₹{infl:.2f} outflow=₹{outfl:.2f} drift=₹{drift:.2f}")
    C_OK = C_OK and ok
else:
    record("C.1 breakdown 200", False, f"status={r.status_code}")
    C_OK = False

# C.2 ledger-alerts: items[] empty OR no drift > 100
r = G("/admin/ledger-alerts", admin_tok, params={"only_unresolved": True})
data = r.json() if r.status_code == 200 else {}
alerts = data.get("alerts", []) if isinstance(data, dict) else (data or [])
big = [a for a in alerts if abs(float(a.get("drift") or 0)) > 100.0 and not a.get("resolved")]
ok = r.status_code == 200 and len(big) == 0
record("C.2 no unresolved alert with |drift|>100", ok,
       f"status={r.status_code} alerts={len(alerts)} big={len(big)}")
C_OK = C_OK and ok


# ════════════════════════════════════════════════════════════════════
# D — Regression: pre-existing flows still work
# ════════════════════════════════════════════════════════════════════
log("\n========= D — Regression =========")
D_OK = True

r = G("/auth/me", testuser_tok)
ok = r.status_code == 200 and r.json().get("email") == TESTUSER_EMAIL
record("D.1 GET /auth/me (testuser)", ok, f"status={r.status_code} email={r.json().get('email') if r.status_code==200 else None}")
D_OK = D_OK and ok

r = G("/admin/users", admin_tok)
data = r.json() if r.status_code == 200 else None
# response may be a list or {items:[...]}
items = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
ok = r.status_code == 200 and items is not None and len(items) >= 1
record("D.2 GET /admin/users", ok, f"status={r.status_code} count={len(items) if items is not None else 'n/a'}")
D_OK = D_OK and ok

r = G("/admin/system-wallet", admin_tok)
data = r.json() if r.status_code == 200 else {}
ok = r.status_code == 200 and isinstance(data.get("buckets"), dict)
record("D.3 GET /admin/system-wallet has buckets", ok, f"status={r.status_code} buckets_keys={list((data.get('buckets') or {}).keys())[:6]}")
D_OK = D_OK and ok


# ════════════════════════════════════════════════════════════════════
# SUMMARY
# ════════════════════════════════════════════════════════════════════
log("\n========= SUMMARY =========")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
log(f"Passed: {passed}/{total}")
for n, ok, d in results:
    log(f"  [{'PASS' if ok else 'FAIL'}] {n}: {d}")

log("")
log(f"Section A (tickets smoke)         : {'PASS' if A_OK else 'FAIL'}")
log(f"Section B (pincodes smoke)        : {'PASS' if B_OK else 'FAIL'}")
log(f"Section C (ledger integrity)      : {'PASS' if C_OK else 'FAIL'}")
log(f"Section D (regression)            : {'PASS' if D_OK else 'FAIL'}")

green = A_OK and B_OK and C_OK and D_OK
log("")
log(f"Phase 2B refactor (tickets+pincodes) GREEN: {'YES' if green else 'NO'}")

sys.exit(0 if green else 1)
