"""
Backend test for: Approved Registrations bucket + finance can approve users.

Scenarios A–M from /app/test_result.md.
"""
import sys
import time
import uuid
from typing import Optional, Dict, Any, List, Tuple

import requests

BASE = "https://network-pay-1.preview.emergentagent.com"
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
DANGER_PIN = "654321"

results: List[Tuple[str, bool, str]] = []
created_user_ids: List[str] = []
created_archive_ids: List[str] = []
promoted_admin_ids: List[Dict[str, Any]] = []  # entries {id, email, is_promoted_user}


def log(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def post(path: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.post(f"{API}{path}", headers=headers, timeout=60, **kwargs)


def get(path: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(f"{API}{path}", headers=headers, timeout=60, **kwargs)


def delete(path: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.delete(f"{API}{path}", headers=headers, timeout=60, **kwargs)


def patch(path: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.patch(f"{API}{path}", headers=headers, timeout=60, **kwargs)


def login(email: str, password: str) -> Optional[str]:
    r = post("/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json().get("token")
    return None


def register_user(name: str, email: str, password: str = "Test@123",
                  referral_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
    body = {"name": name, "email": email, "password": password,
            "phone": f"99{int(time.time()*1000) % 100000000:08d}"}
    if referral_code:
        body["referral_code"] = referral_code
    r = post("/auth/register", json=body)
    if r.status_code == 200:
        return r.json()
    print(f"   register failed: {r.status_code} {r.text[:120]}")
    return None


def main():
    rand = uuid.uuid4().hex[:8]

    # ADMIN LOGIN
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin_token:
        log("Admin login", False, "Could not login as admin@app.com")
        return False
    me = get("/auth/me", admin_token).json()
    super_admin_id = me["id"]
    log("Admin login (super_admin)", True, f"id={super_admin_id}")

    # A. super_admin approves U1
    u1_email = f"u1.appr.{rand}@netpay.example.com"
    u1_reg = register_user("Aarav Sharma", u1_email)
    if not u1_reg:
        log("A.1 Register U1", False)
        return False
    u1_id = u1_reg["user"]["id"]
    created_user_ids.append(u1_id)
    log("A.1 Register U1", True, f"id={u1_id}")

    r = post(f"/admin/approvals/{u1_id}/approve", admin_token)
    log("A.2 super_admin approve U1",
        r.status_code == 200 and r.json().get("ok"),
        f"{r.status_code} {r.text[:120]}")

    r = get("/admin/approved-registrations", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    u1_rec = next((it for it in items if it.get("original_user_id") == u1_id), None)
    cond = u1_rec is not None and u1_rec.get("approver_role") == "super_admin" and u1_rec.get("auto_approved") is False
    log("A.3 U1 in archive (approver_role=super_admin, auto_approved=false)",
        cond, f"rec_keys={list(u1_rec.keys()) if u1_rec else None}")
    if u1_rec:
        created_archive_ids.append(u1_rec["id"])

    # B. Promote a fresh user to finance, approve U2
    fin_email = f"finance.{rand}@netpay.example.com"
    fin_reg = register_user("Priya Iyer", fin_email)
    if not fin_reg:
        log("B.1 Register finance candidate", False)
        return False
    fin_id = fin_reg["user"]["id"]
    log("B.1 Register finance candidate", True, f"id={fin_id}")

    r = post(f"/admin/users/{fin_id}/promote", admin_token, json={"admin_role": "finance"})
    log("B.2 Promote candidate to finance",
        r.status_code == 200 and r.json().get("admin_role") == "finance",
        f"{r.status_code} {r.text[:120]}")
    promoted_admin_ids.append({"id": fin_id, "email": fin_email, "is_promoted_user": True})

    fin_token = login(fin_email, "Test@123")
    log("B.3 Finance login", fin_token is not None)

    u2_email = f"u2.appr.{rand}@netpay.example.com"
    u2_reg = register_user("Rohit Verma", u2_email)
    if not u2_reg:
        log("B.4 Register U2", False)
        return False
    u2_id = u2_reg["user"]["id"]
    created_user_ids.append(u2_id)
    log("B.4 Register U2", True, f"id={u2_id}")

    r = post(f"/admin/approvals/{u2_id}/approve", fin_token)
    log("B.5 Finance approve U2 (RBAC widened) → 200",
        r.status_code == 200 and r.json().get("ok"),
        f"{r.status_code} {r.text[:160]}")

    r = get("/admin/approved-registrations?role_filter=auto", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    u2_rec = next((it for it in items if it.get("original_user_id") == u2_id), None)
    cond = (
        u2_rec is not None
        and u2_rec.get("auto_approved") is True
        and u2_rec.get("approver_role") == "finance"
    )
    log("B.6 role_filter=auto returns U2 (auto_approved=true, approver_role=finance)",
        cond, f"rec_present={u2_rec is not None}")
    if u2_rec:
        created_archive_ids.append(u2_rec["id"])

    # C. role_filter=finance returns U2
    r = get("/admin/approved-registrations?role_filter=finance", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    cond = any(it.get("original_user_id") == u2_id for it in items)
    log("C. role_filter=finance contains U2", cond, f"items_count={len(items)}")

    # D. role_filter=super_admin returns U1 (and not U2)
    r = get("/admin/approved-registrations?role_filter=super_admin", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    has_u1 = any(it.get("original_user_id") == u1_id for it in items)
    has_u2 = any(it.get("original_user_id") == u2_id for it in items)
    log("D. role_filter=super_admin contains U1 and not U2",
        has_u1 and not has_u2, f"has_u1={has_u1} has_u2={has_u2}")

    # E. role_filter=manager → []; counts.manager == 0
    r = get("/admin/approved-registrations?role_filter=manager", admin_token)
    body = r.json() if r.status_code == 200 else {}
    items = body.get("items", [])
    counts = body.get("counts", {}) or {}
    cond_e = (len(items) == 0) and (counts.get("manager", 0) == 0)
    log("E. role_filter=manager returns [] and counts.manager==0",
        cond_e, f"items={len(items)} counts.manager={counts.get('manager', 0)}")

    # F. counts.all == sum(super_admin+finance+manager+support); counts.auto == counts.finance
    r = get("/admin/approved-registrations", admin_token)
    body = r.json() if r.status_code == 200 else {}
    counts = body.get("counts", {}) or {}
    sa = counts.get("super_admin", 0)
    fn = counts.get("finance", 0)
    mg = counts.get("manager", 0)
    sp = counts.get("support", 0)
    all_c = counts.get("all", 0)
    auto_c = counts.get("auto", 0)
    cond_f1 = all_c == sa + fn + mg + sp
    cond_f2 = auto_c == fn
    log("F.1 counts.all == sum of role counts", cond_f1,
        f"all={all_c} sum={sa+fn+mg+sp} ({sa},{fn},{mg},{sp})")
    log("F.2 counts.auto == counts.finance (in our test)", cond_f2,
        f"auto={auto_c} finance={fn}")

    # G. export as super_admin → 200 text/csv with header
    r = get("/admin/approved-registrations/export", admin_token)
    ct = r.headers.get("content-type", "")
    first_line = r.text.splitlines()[0] if r.text else ""
    cond_g = (r.status_code == 200 and ct.startswith("text/csv")
              and first_line.startswith("id,original_user_id"))
    log("G.1 export as super_admin → 200 text/csv with header",
        cond_g, f"{r.status_code} ct={ct} first_line={first_line[:80]}")

    r2 = get("/admin/approved-registrations/export?role_filter=auto", admin_token)
    log("G.2 export role_filter=auto super_admin → 200",
        r2.status_code == 200 and r2.headers.get("content-type", "").startswith("text/csv"),
        f"{r2.status_code}")

    # H. export as manager → 403
    mgr_email = f"manager.{rand}@netpay.example.com"
    r = post("/admin/admins", admin_token, json={
        "name": "Manager Mehta", "email": mgr_email,
        "password": "Test@123", "admin_role": "manager"
    })
    mgr_token = None
    if r.status_code != 200:
        log("Helper: create manager", False, f"{r.status_code} {r.text[:120]}")
    else:
        mgr_id = r.json()["id"]
        promoted_admin_ids.append({"id": mgr_id, "email": mgr_email, "is_promoted_user": False})
        log("Helper: create manager", True, f"id={mgr_id}")
        mgr_token = login(mgr_email, "Test@123")
        log("Helper: login manager", mgr_token is not None)
        r = get("/admin/approved-registrations/export", mgr_token)
        log("H. export as manager → 403", r.status_code == 403, f"{r.status_code}")
        r = get("/admin/approved-registrations", mgr_token)
        log("H.2 list as manager → 200", r.status_code == 200, f"{r.status_code}")

    # finance export → 200
    r = get("/admin/approved-registrations/export", fin_token)
    log("H.3 export as finance → 200 text/csv",
        r.status_code == 200 and r.headers.get("content-type", "").startswith("text/csv"),
        f"{r.status_code}")

    # support helper
    sup_email = f"support.{rand}@netpay.example.com"
    r = post("/admin/admins", admin_token, json={
        "name": "Support Singh", "email": sup_email,
        "password": "Test@123", "admin_role": "support"
    })
    sup_token = None
    if r.status_code == 200:
        sup_id = r.json()["id"]
        promoted_admin_ids.append({"id": sup_id, "email": sup_email, "is_promoted_user": False})
        sup_token = login(sup_email, "Test@123")
        r = get("/admin/approved-registrations", sup_token)
        log("H.4 list as support → 200", r.status_code == 200, f"{r.status_code}")
        r = get("/admin/approved-registrations/export", sup_token)
        log("H.5 export as support → 403", r.status_code == 403, f"{r.status_code}")
        if u2_rec:
            r = delete(f"/admin/approved-registrations/{u2_rec['id']}", sup_token)
            log("H.6 DELETE as support → 403", r.status_code == 403, f"{r.status_code}")
    else:
        log("Helper: create support", False, f"{r.status_code} {r.text[:120]}")

    # I. Approving same user twice does NOT duplicate archive
    # First approach: create U3, approve, flip to pending, approve again → expect 1 archive row
    u3_email = f"u3.dup.{rand}@netpay.example.com"
    u3_reg = register_user("Sneha Patel", u3_email)
    u3_archive_id = None
    if u3_reg:
        u3_id = u3_reg["user"]["id"]
        created_user_ids.append(u3_id)
        r = post(f"/admin/approvals/{u3_id}/approve", admin_token)
        log("I.0 Approve U3 first time", r.status_code == 200, f"{r.status_code}")
        # Flip back via PATCH /admin/users
        rp = patch(f"/admin/users/{u3_id}", admin_token, json={"approval_status": "pending"})
        if rp.status_code == 200:
            r = post(f"/admin/approvals/{u3_id}/approve", admin_token)
            log("I.1 Re-approve U3 after revert",
                r.status_code == 200 and r.json().get("ok") is True,
                f"{r.status_code} {r.text[:120]}")
            r = get("/admin/approved-registrations", admin_token)
            items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
            u3_rows = [it for it in items if it.get("original_user_id") == u3_id]
            log("I.2 Approving same user twice → only 1 archive entry (helper deletes prior rows)",
                len(u3_rows) == 1, f"rows={len(u3_rows)}")
            for it in u3_rows:
                if it.get("id") not in created_archive_ids:
                    created_archive_ids.append(it["id"])
                    u3_archive_id = it["id"]
        else:
            log("I.1 PATCH approval_status=pending (admin)",
                False, f"{rp.status_code} {rp.text[:140]}")

    # J. Re-approve attempt on already-approved user returns {already_approved:true}, no extra archive
    r = get("/admin/approved-registrations?role_filter=finance", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    u2_count_before = sum(1 for it in items if it.get("original_user_id") == u2_id)

    r = post(f"/admin/approvals/{u2_id}/approve", admin_token)
    body = r.json() if r.status_code == 200 else {}
    cond_j = r.status_code == 200 and body.get("already_approved") is True
    log("J.1 Re-approve already-approved user returns {already_approved:true}",
        cond_j, f"{r.status_code} {body}")

    r = get("/admin/approved-registrations?role_filter=finance", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    u2_count_after = sum(1 for it in items if it.get("original_user_id") == u2_id)
    log("J.2 No 2nd archive row added on already_approved",
        u2_count_after == u2_count_before,
        f"before={u2_count_before} after={u2_count_after}")

    # K. super_admin DELETE archive removes archive only; finance DELETE → 403
    if u2_rec:
        r = delete(f"/admin/approved-registrations/{u2_rec['id']}", fin_token)
        log("K.1 finance DELETE archive → 403",
            r.status_code == 403, f"{r.status_code} {r.text[:120]}")

    if u1_rec:
        u1_archive_id = u1_rec["id"]
        r = delete(f"/admin/approved-registrations/{u1_archive_id}", admin_token)
        log("K.2 super_admin DELETE archive → 200",
            r.status_code == 200 and r.json().get("ok"),
            f"{r.status_code} {r.text[:120]}")
        if u1_archive_id in created_archive_ids:
            created_archive_ids.remove(u1_archive_id)

        r = get("/admin/users", admin_token)
        users = r.json() if r.status_code == 200 else []
        still_present = any(u.get("id") == u1_id for u in users)
        log("K.3 Underlying U1 user still present after archive delete",
            still_present, f"present={still_present}")

        r = delete(f"/admin/approved-registrations/{u1_archive_id}", admin_token)
        log("K.4 Second DELETE same archive id → 404",
            r.status_code == 404, f"{r.status_code}")

    # L. Regression
    r = get("/admin/approvals/today", admin_token)
    log("L.1 GET /admin/approvals/today → 200", r.status_code == 200, f"{r.status_code}")

    r = get("/admin/approvals?status=pending", admin_token)
    log("L.2 GET /admin/approvals?status=pending → 200",
        r.status_code == 200, f"{r.status_code}")

    cart_email = f"cart.{rand}@netpay.example.com"
    cart_reg = register_user("Cart User", cart_email)
    cart_token = None
    if cart_reg:
        cart_token = cart_reg["token"]
        cart_id = cart_reg["user"]["id"]
        created_user_ids.append(cart_id)
        r = get("/cart", cart_token)
        body = r.json() or {}
        log("L.3 GET /cart → 200 with total/items/count",
            r.status_code == 200 and "total" in body and "items" in body and "count" in body,
            f"{r.status_code} keys={list(body.keys())}")

        r = get("/payment/config", cart_token)
        log("L.4 GET /payment/config → 200",
            r.status_code == 200 and "is_mock" in (r.json() or {}),
            f"{r.status_code}")

    # Non-admin user accessing approved-registrations endpoints → 401/403
    if cart_token:
        r = get("/admin/approved-registrations", cart_token)
        log("Auth: regular user GET list → 401/403",
            r.status_code in (401, 403), f"{r.status_code}")
        r = get("/admin/approved-registrations/export", cart_token)
        log("Auth: regular user GET export → 401/403",
            r.status_code in (401, 403), f"{r.status_code}")
        r = delete("/admin/approved-registrations/some-fake-id", cart_token)
        log("Auth: regular user DELETE → 401/403",
            r.status_code in (401, 403), f"{r.status_code}")
        r = post(f"/admin/approvals/{u1_id}/approve", cart_token)
        log("Auth: regular user POST approve → 401/403",
            r.status_code in (401, 403), f"{r.status_code}")

    # No-auth checks
    r = requests.get(f"{API}/admin/approved-registrations", timeout=30)
    log("Auth: no-auth GET list → 401/403", r.status_code in (401, 403), f"{r.status_code}")
    r = requests.get(f"{API}/admin/approved-registrations/export", timeout=30)
    log("Auth: no-auth GET export → 401/403", r.status_code in (401, 403), f"{r.status_code}")

    # M. Cleanup
    print("\n--- Cleanup phase ---")
    cleanup_errors = 0
    r = get("/admin/approved-registrations", admin_token)
    items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
    test_ids = {u1_id, u2_id} | set(created_user_ids)
    for it in items:
        if it.get("original_user_id") in test_ids:
            rr = delete(f"/admin/approved-registrations/{it['id']}", admin_token)
            print(f"   archive del {it['id']}: {rr.status_code}")
            if rr.status_code != 200:
                cleanup_errors += 1

    for adm in promoted_admin_ids:
        if adm.get("is_promoted_user"):
            rr = post(f"/admin/users/{adm['id']}/demote", admin_token)
            print(f"   demote {adm['email']}: {rr.status_code}")
        rr = delete(f"/admin/users/{adm['id']}", admin_token)
        print(f"   delete admin {adm['email']}: {rr.status_code}")
        if rr.status_code != 200:
            cleanup_errors += 1

    for uid in created_user_ids:
        rr = delete(f"/admin/users/{uid}", admin_token)
        if rr.status_code not in (200, 404):
            cleanup_errors += 1
            print(f"   delete user {uid}: {rr.status_code}")

    t = login(ADMIN_EMAIL, ADMIN_PASSWORD)
    log("M. admin@app.com still works after cleanup", t is not None,
        f"cleanup_errors={cleanup_errors}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Total: {len(results)}  Passed: {passed}  Failed: {failed}")
    if failed:
        print("\nFailed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
