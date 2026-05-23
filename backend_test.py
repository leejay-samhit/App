"""
Test admin placement realignment endpoint:
POST /api/admin/users/{user_id}/realign
"""
import sys
import json
import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"


def pjson(label, resp):
    try:
        data = resp.json()
    except Exception:
        data = resp.text
    print(f"[{resp.status_code}] {label}: {json.dumps(data, indent=2, default=str)[:1200]}")
    return data


def main():
    results = []

    # 1. Login admin
    r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    data = pjson("login admin", r)
    assert r.status_code == 200, f"login failed: {r.status_code}"
    token = data.get("token") or data.get("access_token")
    assert token, "no token in login response"
    H = {"Authorization": f"Bearer {token}"}
    results.append(("1. Admin login", "PASS"))

    # 2. GET /api/admin/users
    r = requests.get(f"{BASE}/admin/users", headers=H, timeout=30)
    assert r.status_code == 200, f"admin/users failed: {r.status_code}"
    users = r.json()
    if isinstance(users, dict):
        users = users.get("items") or users.get("users") or []
    print(f"Total users: {len(users)}")
    assert len(users) >= 2, "need at least 2 users"
    results.append(("2. GET /admin/users", f"PASS ({len(users)} users)"))

    non_admins = [u for u in users if u.get("role") != "admin" and u.get("referral_code")]
    assert len(non_admins) >= 2, "need 2 non-admin users with referral_code"

    id_to_sponsor = {u["id"]: u.get("sponsor_id") for u in users}

    def is_descendant(maybe_desc_id, ancestor_id, max_hops=50):
        cur = id_to_sponsor.get(maybe_desc_id)
        hops = 0
        while cur and hops < max_hops:
            if cur == ancestor_id:
                return True
            cur = id_to_sponsor.get(cur)
            hops += 1
        return False

    user_a = None
    user_b = None
    for a in non_admins:
        for b in non_admins:
            if a["id"] == b["id"]:
                continue
            if a.get("sponsor_id") == b["id"]:
                continue
            if is_descendant(b["id"], a["id"]):
                continue
            user_a = a
            user_b = b
            break
        if user_a:
            break

    assert user_a and user_b, "couldn't find suitable user-A, user-B pair"
    print(f"user-A: {user_a['email']} id={user_a['id']} ref={user_a.get('referral_code')} sponsor_id={user_a.get('sponsor_id')}")
    print(f"user-B: {user_b['email']} id={user_b['id']} ref={user_b.get('referral_code')}")

    # 3. Backfill check
    required_fields = ["original_sponsor_id", "original_sponsor_code", "original_referral_code",
                       "placement_history", "placement_realigned_at", "placement_realigned_reason"]
    backfill_user = None
    for u in users:
        if all(f in u for f in required_fields):
            backfill_user = u
            break
    if backfill_user:
        print(f"Backfill user {backfill_user['email']}:")
        for f in required_fields:
            print(f"  {f} = {backfill_user.get(f)!r}")
        results.append(("3. Backfill fields present", "PASS"))
    else:
        sample = users[0]
        missing = [f for f in required_fields if f not in sample]
        print(f"Sample user keys: {list(sample.keys())}")
        print(f"Missing fields on user[0]: {missing}")
        results.append(("3. Backfill fields present", f"FAIL (missing: {missing})"))

    user_a_original_sponsor_code = user_a.get("original_sponsor_code") or user_a.get("referred_by")
    print(f"user-A original_sponsor_code = {user_a_original_sponsor_code}")

    # 4. Realign A under B
    body4 = {"new_sponsor_code": user_b["referral_code"], "reason": "Manual placement test"}
    r = requests.post(f"{BASE}/admin/users/{user_a['id']}/realign", json=body4, headers=H, timeout=30)
    data4 = pjson("realign A under B", r)
    if r.status_code == 200 and isinstance(data4, dict) and "history_entry" in data4:
        results.append(("4. Realign A under B", "PASS"))
    else:
        results.append(("4. Realign A under B", f"FAIL ({r.status_code})"))

    # 5. Verify
    r = requests.get(f"{BASE}/admin/users", headers=H, timeout=30)
    users2 = r.json()
    if isinstance(users2, dict):
        users2 = users2.get("items") or users2.get("users") or []
    user_a2 = next((u for u in users2 if u["id"] == user_a["id"]), None)
    assert user_a2, "user-A not found after realign"
    checks5 = []
    if user_a2.get("sponsor_id") == user_b["id"]:
        checks5.append("sponsor_id_OK")
    else:
        checks5.append(f"sponsor_id_BAD={user_a2.get('sponsor_id')}")
    if user_a2.get("referred_by") == user_b["referral_code"]:
        checks5.append("referred_by_OK")
    else:
        checks5.append(f"referred_by_BAD={user_a2.get('referred_by')}")
    if user_a2.get("placement_realigned_reason") == "Manual placement test":
        checks5.append("reason_OK")
    else:
        checks5.append(f"reason_BAD={user_a2.get('placement_realigned_reason')!r}")
    ph = user_a2.get("placement_history") or []
    if len(ph) == 1:
        checks5.append("history_len_OK")
        entry = ph[0]
        need = ["new_sponsor_id", "new_sponsor_code", "new_sponsor_email", "reason", "changed_by_admin_email"]
        miss = [k for k in need if k not in entry]
        if not miss:
            checks5.append("entry_keys_OK")
        else:
            checks5.append(f"entry_keys_BAD_missing={miss}")
    else:
        checks5.append(f"history_len_BAD={len(ph)}")
    print("Step 5 checks:", checks5)
    if all("_OK" in c for c in checks5):
        results.append(("5. Post-realign verification", "PASS"))
    else:
        results.append(("5. Post-realign verification", f"FAIL: {checks5}"))

    # 6. Self-placement → 400
    body6 = {"new_sponsor_code": user_a["referral_code"], "reason": "self-placement attempt"}
    r = requests.post(f"{BASE}/admin/users/{user_a['id']}/realign", json=body6, headers=H, timeout=30)
    data6 = pjson("self-placement", r)
    detail6 = data6.get("detail") if isinstance(data6, dict) else ""
    if r.status_code == 400 and "themselves" in str(detail6):
        results.append(("6. Self-placement blocked", "PASS"))
    else:
        results.append(("6. Self-placement blocked", f"FAIL ({r.status_code}, {detail6})"))

    # 7. Invalid sponsor
    body7 = {"new_sponsor_code": "NONEXISTENT99", "reason": "bad reason here"}
    r = requests.post(f"{BASE}/admin/users/{user_a['id']}/realign", json=body7, headers=H, timeout=30)
    data7 = pjson("invalid sponsor", r)
    detail7 = data7.get("detail") if isinstance(data7, dict) else ""
    if r.status_code == 400 and "not found" in str(detail7).lower():
        results.append(("7. Invalid sponsor 400", "PASS"))
    else:
        results.append(("7. Invalid sponsor 400", f"FAIL ({r.status_code}, {detail7})"))

    # 8. Short reason → 422
    body8 = {"new_sponsor_code": user_b["referral_code"], "reason": "x"}
    r = requests.post(f"{BASE}/admin/users/{user_a['id']}/realign", json=body8, headers=H, timeout=30)
    pjson("short reason", r)
    if r.status_code == 422:
        results.append(("8. Short reason 422", "PASS"))
    else:
        results.append(("8. Short reason 422", f"FAIL ({r.status_code})"))

    # 9. Unchanged placement
    body9 = {"new_sponsor_code": user_b["referral_code"], "reason": "again same sponsor"}
    r = requests.post(f"{BASE}/admin/users/{user_a['id']}/realign", json=body9, headers=H, timeout=30)
    data9 = pjson("same sponsor again", r)
    detail9 = data9.get("detail") if isinstance(data9, dict) else ""
    if r.status_code == 400 and "already placed" in str(detail9).lower():
        results.append(("9. Already placed 400", "PASS"))
    else:
        results.append(("9. Already placed 400", f"FAIL ({r.status_code}, {detail9})"))

    # 10. Restore original
    if not user_a_original_sponsor_code:
        results.append(("10. Restore", "SKIP - no original_sponsor_code on user-A"))
    else:
        body10 = {"new_sponsor_code": user_a_original_sponsor_code, "reason": "Restoring after test"}
        r = requests.post(f"{BASE}/admin/users/{user_a['id']}/realign", json=body10, headers=H, timeout=30)
        data10 = pjson("restore original", r)
        if r.status_code == 200:
            r2 = requests.get(f"{BASE}/admin/users", headers=H, timeout=30)
            users3 = r2.json()
            if isinstance(users3, dict):
                users3 = users3.get("items") or users3.get("users") or []
            user_a3 = next((u for u in users3 if u["id"] == user_a["id"]), None)
            ph3 = (user_a3 or {}).get("placement_history") or []
            if len(ph3) == 2:
                results.append(("10. Restore + history=2", "PASS"))
            else:
                results.append(("10. Restore + history=2", f"FAIL (history_len={len(ph3)})"))
        else:
            results.append(("10. Restore", f"FAIL ({r.status_code})"))

    print("\n" + "=" * 60)
    print("RESULTS:")
    for name, status in results:
        marker = "PASS" if status.startswith("PASS") else ("SKIP" if status.startswith("SKIP") else "FAIL")
        print(f"  [{marker}] {name}: {status}")
    failed = [n for n, s in results if not s.startswith("PASS") and not s.startswith("SKIP")]
    print(f"\nTotal: {len(results)} | Failed: {len(failed)}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
