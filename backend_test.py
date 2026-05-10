"""Backend test for 2 NEW Distributor Area-Mapping admin endpoints.

Endpoints:
  POST /api/admin/distributors/{user_id}/areas/bulk-unassign
  GET  /api/admin/pincodes/in-region?state=&district=&limit=
"""
import os
import sys
import json
import uuid
import requests

ENV_PATH = "/app/frontend/.env"
BASE = None
with open(ENV_PATH) as f:
    for ln in f:
        if ln.startswith("EXPO_PUBLIC_BACKEND_URL="):
            BASE = ln.strip().split("=", 1)[1].strip().strip('"')
            break
assert BASE, "EXPO_PUBLIC_BACKEND_URL missing"
API = BASE.rstrip("/") + "/api"
print(f"API base: {API}")

results = []
def rec(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name} :: {detail}")
    results.append((name, ok, detail))

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
FIN_EMAIL = "finance@app.com"
FIN_PASS = "Finance@123"


def login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        return None, r
    return r.json().get("token"), r


def H(token):
    return {"Authorization": f"Bearer {token}"}


# 1. Login admin
tokenA, r = login(ADMIN_EMAIL, ADMIN_PASS)
if not tokenA:
    rec("admin login", False, f"{r.status_code} {r.text[:200]}")
    sys.exit(1)
rec("admin login", True, "tokenA acquired")

# 2. Login finance else create
tokenF, r = login(FIN_EMAIL, FIN_PASS)
if not tokenF:
    print(f"finance login failed ({r.status_code}); creating finance admin")
    cr = requests.post(
        f"{API}/admin/admins",
        headers=H(tokenA),
        json={"email": FIN_EMAIL, "password": FIN_PASS, "name": "Finance Admin", "admin_role": "finance"},
        timeout=30,
    )
    if cr.status_code not in (200, 201):
        rec("create finance admin", False, f"{cr.status_code} {cr.text[:200]}")
    else:
        rec("create finance admin", True, "")
    tokenF, r = login(FIN_EMAIL, FIN_PASS)
if not tokenF:
    rec("finance login", False, f"{r.status_code} {r.text[:200]}")
    sys.exit(1)
rec("finance login", True, "tokenF acquired")

# 3. Register fresh user
suffix = uuid.uuid4().hex[:8]
test_email = f"distrib_{suffix}@example.com"
reg_payload = {
    "name": f"Distrib Test {suffix}",
    "email": test_email,
    "password": "Test@1234",
    "phone": "9000000000",
}
r = requests.post(f"{API}/auth/register", json=reg_payload, timeout=30)
if r.status_code != 200:
    rec("register fresh user", False, f"{r.status_code} {r.text[:300]}")
    sys.exit(1)
rj = r.json()
user_token = rj.get("token") or rj.get("access_token")
user_id = (rj.get("user") or {}).get("id") or rj.get("id")
if not user_id and user_token:
    me = requests.get(f"{API}/auth/me", headers=H(user_token), timeout=30).json()
    user_id = me.get("id")
rec("register fresh user", bool(user_id), f"user_id={user_id} email={test_email}")

# 4. Make distributor
r = requests.post(
    f"{API}/admin/users/{user_id}/distributor",
    headers=H(tokenA),
    json={"is_distributor": True},
    timeout=30,
)
rec("mark user as distributor", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

# 5. Assign 3 pincodes
r = requests.post(
    f"{API}/admin/distributors/{user_id}/areas",
    headers=H(tokenA),
    json={"pincodes": ["500001", "500003", "500004"]},
    timeout=30,
)
rec("assign 3 pincodes", r.status_code == 200, f"{r.status_code} {r.text[:300]}")

# 6. Bulk-unassign 2
r = requests.post(
    f"{API}/admin/distributors/{user_id}/areas/bulk-unassign",
    headers=H(tokenA),
    json={"pincodes": ["500001", "500003"]},
    timeout=30,
)
ok = False
detail = f"{r.status_code} {r.text[:300]}"
if r.status_code == 200:
    body = r.json()
    if body.get("ok") and body.get("removed") == 2 and body.get("requested") == 2:
        ok = True
        detail = json.dumps(body)
rec("bulk-unassign 2 pincodes (super_admin)", ok, detail)

# 7. GET areas — only 500004 should remain
r = requests.get(f"{API}/admin/distributors/{user_id}/areas", headers=H(tokenA), timeout=30)
ok = False
detail = f"{r.status_code} {r.text[:300]}"
remaining_pins = []
if r.status_code == 200:
    body = r.json()
    if isinstance(body, dict):
        items = body.get("items") or body.get("areas") or []
    else:
        items = body or []
    remaining_pins = sorted([(it.get("pincode") if isinstance(it, dict) else it) for it in items])
    ok = remaining_pins == ["500004"]
    detail = f"remaining={remaining_pins}"
rec("GET areas after bulk-unassign -> only 500004", ok, detail)

# 8. Empty array -> 400
r = requests.post(
    f"{API}/admin/distributors/{user_id}/areas/bulk-unassign",
    headers=H(tokenA),
    json={"pincodes": []},
    timeout=30,
)
rec("bulk-unassign empty -> 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")

# 9. Finance token -> 403
r = requests.post(
    f"{API}/admin/distributors/{user_id}/areas/bulk-unassign",
    headers=H(tokenF),
    json={"pincodes": ["500004"]},
    timeout=30,
)
rec("bulk-unassign as finance -> 403", r.status_code == 403, f"{r.status_code} {r.text[:200]}")

# 10. GET in-region state+district
r = requests.get(
    f"{API}/admin/pincodes/in-region",
    headers=H(tokenA),
    params={"state": "Telangana", "district": "Hyderabad"},
    timeout=60,
)
ok = False
detail = f"{r.status_code} {r.text[:200]}"
if r.status_code == 200:
    body = r.json()
    items = body.get("items") or []
    total = body.get("total")
    row_500004 = next((it for it in items if it.get("pincode") == "500004"), None)
    others_assigned = [it for it in items if it.get("pincode") != "500004" and it.get("assigned_to") is not None]
    has_fields = (
        row_500004 is not None
        and "state" in row_500004
        and "district" in row_500004
    )
    if (
        len(items) >= 1
        and total == len(items)
        and row_500004
        and isinstance(row_500004.get("assigned_to"), dict)
        and row_500004["assigned_to"].get("distributor_id") == user_id
        and row_500004["assigned_to"].get("distributor_email") == test_email
        and has_fields
    ):
        ok = True
        detail = (
            f"total={total} 500004.assigned_to={row_500004.get('assigned_to')} "
            f"other_assigned_count={len(others_assigned)} sample_keys={list(items[0].keys())}"
        )
    else:
        detail = (
            f"total={total} items_len={len(items)} 500004={row_500004} "
            f"first={items[0] if items else None}"
        )
rec("GET in-region(state=Telangana,district=Hyderabad) -> 500004 has assigned_to", ok, detail)

# 11. No params -> 400
r = requests.get(f"{API}/admin/pincodes/in-region", headers=H(tokenA), timeout=30)
rec("GET in-region no params -> 400", r.status_code == 400, f"{r.status_code} {r.text[:200]}")

# 12. district=NonExistentXyz -> 200 items=[]
r = requests.get(
    f"{API}/admin/pincodes/in-region",
    headers=H(tokenA),
    params={"district": "NonExistentXyz"},
    timeout=30,
)
ok = False
detail = f"{r.status_code} {r.text[:200]}"
if r.status_code == 200:
    body = r.json()
    if body.get("items") == [] and body.get("total") == 0:
        ok = True
        detail = "empty"
    else:
        detail = json.dumps(body)[:300]
rec("GET in-region district=NonExistentXyz -> items=[]", ok, detail)

# 13. Anon -> 401/403
r = requests.get(
    f"{API}/admin/pincodes/in-region",
    params={"state": "Telangana"},
    timeout=30,
)
rec("GET in-region anonymous -> 401/403", r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}")

# CLEANUP
print("\n--- cleanup ---")
r = requests.post(
    f"{API}/admin/distributors/{user_id}/areas/bulk-unassign",
    headers=H(tokenA),
    json={"pincodes": ["500004"]},
    timeout=30,
)
print("cleanup bulk-unassign:", r.status_code, r.text[:200])

r = requests.post(
    f"{API}/admin/users/{user_id}/distributor",
    headers=H(tokenA),
    json={"is_distributor": False},
    timeout=30,
)
print("cleanup unmark distributor:", r.status_code, r.text[:200])

r = requests.delete(f"{API}/admin/users/{user_id}", headers=H(tokenA), timeout=30)
print("cleanup delete user:", r.status_code, r.text[:200])

# Summary
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n==== {passed}/{total} passed ====")
for n, ok, d in results:
    print(("PASS" if ok else "FAIL"), "-", n, "::", d)

sys.exit(0 if passed == total else 1)
