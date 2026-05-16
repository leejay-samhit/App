#!/usr/bin/env python3
"""Backend regression tests for MLM payout & system-wallet redesign.

Coverage (per review brief):
  A) No-ref signup → admin direct_signup + GST + cascade overflow
  B) With-ref signup (cascade still works, no direct_signup_credit)
  C) Demo users seeded (5 users under admin)
  D) Admin tree visible-all-users (admin + orphans)
  E) New placement algorithm (4→3→2→1→admin) — sanity check
  F) Bucket endpoint validation
"""
import os
import re
import sys
import time
import uuid
import requests
from pathlib import Path


def _read_env(p):
    out = {}
    for ln in Path(p).read_text().splitlines():
        m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.+)\s*$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


FE_ENV = _read_env("/app/frontend/.env")
BASE = FE_ENV.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") + "/api"
print(f"BACKEND BASE: {BASE}")

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
DEMO_PASS = "Demo@123"

results = []


def rec(label, ok, details=""):
    status = "✅" if ok else "❌"
    print(f"{status} {label}")
    if details:
        print(f"   {details}")
    results.append((label, ok, details))


def H(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def login(email, pwd):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pwd}, timeout=30)
    if r.status_code != 200:
        print(f"login failed {email}: {r.status_code} {r.text[:200]}")
        return None
    return r.json().get("token")


def get_buckets(admin_tok):
    r = requests.get(f"{BASE}/admin/system-wallet", headers=H(admin_tok), timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("buckets") or {}


def get_admin_id(admin_tok):
    r = requests.get(f"{BASE}/auth/me", headers=H(admin_tok), timeout=30)
    return r.json().get("id") if r.status_code == 200 else None


def get_user_by_email(admin_tok, email):
    r = requests.get(f"{BASE}/admin/users", headers=H(admin_tok), timeout=30)
    if r.status_code != 200:
        return None
    users = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    for u in users:
        if (u.get("email") or "").lower() == email.lower():
            return u
    return None


# ========== C ==========
def test_demo_users(admin_tok):
    print("\n--- C) Demo users seeded ---")
    demo_emails = ["aarav@demo.app", "diya@demo.app", "vihaan@demo.app", "ananya@demo.app", "rohan@demo.app"]
    for em in demo_emails:
        tok = login(em, DEMO_PASS)
        rec(f"Demo login: {em}", bool(tok), "" if tok else "Login failed")
    r = requests.get(f"{BASE}/admin/users", headers=H(admin_tok), timeout=30)
    rec("GET /admin/users", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return
    users = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    admin_id = get_admin_id(admin_tok)
    by_email = {(u.get("email") or "").lower(): u for u in users}
    for em in demo_emails:
        u = by_email.get(em)
        ok = (u is not None
              and u.get("approval_status") == "approved"
              and u.get("registration_paid") is True
              and u.get("sponsor_id") == admin_id)
        det = ""
        if u is None:
            det = "missing"
        elif not ok:
            det = f"approval={u.get('approval_status')} paid={u.get('registration_paid')} sp_match={u.get('sponsor_id')==admin_id}"
        rec(f"Demo seeded correctly: {em}", ok, det)


# ========== D ==========
def test_admin_tree(admin_tok):
    print("\n--- D) Admin tree visible-all-users ---")
    r = requests.get(f"{BASE}/admin/users/tree?depth=10", headers=H(admin_tok), timeout=30)
    rec("GET /admin/users/tree?depth=10", r.status_code == 200, f"status={r.status_code}")
    if r.status_code != 200:
        return
    data = r.json()
    roots = data.get("roots") or []
    rec("Tree has at least 1 root", len(roots) >= 1, f"n_roots={len(roots)}")
    admin_root = next((rt for rt in roots if (rt.get("email") or "").lower() == ADMIN_EMAIL), None)
    rec("Admin is one of the roots", admin_root is not None)
    if admin_root:
        # children may be nested; flatten one level
        kids = admin_root.get("children") or []
        child_emails = {(c.get("email") or "").lower() for c in kids}
        demo_emails = {"aarav@demo.app", "diya@demo.app", "vihaan@demo.app", "ananya@demo.app", "rohan@demo.app"}
        rec("Admin's children include all 5 demo users",
            demo_emails.issubset(child_emails),
            f"missing={demo_emails - child_emails}")


# ========== A ==========
def test_no_ref_signup(admin_tok):
    print("\n--- A) No-ref signup → admin direct credit ---")
    pre = get_buckets(admin_tok)
    rec("Fetch admin wallet buckets (pre)", pre is not None, str(pre)[:200] if pre else "")
    if pre is None:
        return None

    uniq = uuid.uuid4().hex[:8]
    email = f"noref_{uniq}@test.app"
    name = f"NoRefTest {uniq}"
    reg = requests.post(f"{BASE}/auth/register", json={
        "name": name, "email": email, "password": "Pass@123",
        "phone": f"+919{int(time.time()*1000)%1000000000:09d}",
    }, timeout=30)
    rec("Register no-ref user", reg.status_code == 200, f"status={reg.status_code} body={reg.text[:200]}")
    if reg.status_code != 200:
        return None
    body = reg.json()
    new_token = body.get("token")
    new_user_id = (body.get("user") or {}).get("id") or body.get("id")

    pr = requests.post(f"{BASE}/payment/register-fee", headers=H(new_token), timeout=30)
    rec("Pay /payment/register-fee", pr.status_code == 200, f"status={pr.status_code} body={pr.text[:200]}")

    if not new_user_id:
        u = get_user_by_email(admin_tok, email)
        new_user_id = u.get("id") if u else None
    rec("Resolved new user id", bool(new_user_id), f"id={new_user_id}")
    if not new_user_id:
        return None

    ap = requests.post(f"{BASE}/admin/approvals/{new_user_id}/approve", headers=H(admin_tok), timeout=30)
    rec("POST /admin/approvals/{id}/approve", ap.status_code == 200, f"status={ap.status_code} body={ap.text[:200]}")

    post = get_buckets(admin_tok)
    rec("Fetch admin wallet buckets (post)", post is not None)
    if post is None:
        return None

    d_signup = round(post.get("direct_signup", 0) - pre.get("direct_signup", 0), 2)
    d_gst = round(post.get("gst_collected", 0) - pre.get("gst_collected", 0), 2)
    d_ref = round(post.get("referral_commission", 0) - pre.get("referral_commission", 0), 2)

    rec("direct_signup bucket increased by 100", abs(d_signup - 100.0) < 0.5, f"delta={d_signup}")
    rec("gst_collected bucket increased by 18.0", abs(d_gst - 18.0) < 0.5, f"delta={d_gst}")
    rec("referral_commission bucket increased by ~22.05 (cascade L2..L10)",
        abs(d_ref - 22.05) < 1.0, f"delta={d_ref}")

    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=direct_signup",
                     headers=H(admin_tok), timeout=30)
    rec("GET ?bucket=direct_signup", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        items = r.json().get("items") or []
        match = next((it for it in items if it.get("source_user_id") == new_user_id), None)
        rec("direct_signup_credit row for new user exists", match is not None)
        if match:
            rec("row.gross_amount==118", abs(float(match.get("gross_amount") or 0) - 118.0) < 0.01, f"got={match.get('gross_amount')}")
            rec("row.gst_amount==18", abs(float(match.get("gst_amount") or 0) - 18.0) < 0.01, f"got={match.get('gst_amount')}")
            rec("row.amount==100", abs(float(match.get("amount") or 0) - 100.0) < 0.01, f"got={match.get('amount')}")
            rec(f"row.source_user_name=={name}",
                (match.get("source_user_name") or "") == name, f"got={match.get('source_user_name')}")
            ps = (match.get("placement_sponsor_name") or "").lower()
            rec("row.placement_sponsor_name=='Admin' (case-insensitive)",
                ps in ("admin", "administrator"), f"got={match.get('placement_sponsor_name')}")
            desc = (match.get("description") or "").lower()
            rec("description mentions gross/gst/net",
                ("gross" in desc) and ("gst" in desc) and ("net" in desc),
                f"desc={match.get('description')[:150]}")

    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=referral_commission&limit=500",
                     headers=H(admin_tok), timeout=30)
    rec("GET ?bucket=referral_commission", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        items = r.json().get("items") or []
        cov = [it for it in items if it.get("type") == "cascade_overflow"
               and (it.get("source_user_name") or "") == name]
        levels = sorted({int(it.get("level")) for it in cov if it.get("level") is not None})
        rec("9 cascade_overflow rows (L2..L10) for new user",
            len(cov) == 9 and levels == list(range(2, 11)),
            f"n={len(cov)} levels={levels}")
        if cov:
            sample = cov[0]
            rec("cascade_overflow description includes 'cascade overflow'",
                "cascade overflow" in (sample.get("description") or "").lower(),
                f"desc={sample.get('description')[:120]}")

    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=gst_collected&limit=500",
                     headers=H(admin_tok), timeout=30)
    rec("GET ?bucket=gst_collected", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        items = r.json().get("items") or []
        target = next((it for it in items
                       if (it.get("source_user_id") == new_user_id or (it.get("source_user_name") or "") == name)
                       and "direct signup" in (it.get("description") or "").lower()),
                      None)
        rec("gst_collected row for direct signup of new user exists", target is not None,
            f"sample={items[0] if items else None}")
    return new_user_id


# ========== B ==========
def test_with_ref_signup(admin_tok):
    print("\n--- B) With-ref signup (AARAV01) ---")
    aarav = get_user_by_email(admin_tok, "aarav@demo.app")
    if not aarav:
        rec("Aarav demo user exists", False, "Skipping rest")
        return
    rec("Aarav demo user exists", True, f"directs_before={aarav.get('direct_referrals_count')}")
    aarav_directs_before = int(aarav.get("direct_referrals_count") or 0)
    pre = get_buckets(admin_tok)

    uniq = uuid.uuid4().hex[:8]
    email = f"refed_{uniq}@test.app"
    name = f"RefedUser {uniq}"
    reg = requests.post(f"{BASE}/auth/register", json={
        "name": name, "email": email, "password": "Pass@123",
        "phone": f"+918{int(time.time()*1000)%1000000000:09d}",
        "referral_code": "AARAV01",
    }, timeout=30)
    rec("Register user with referral_code=AARAV01",
        reg.status_code == 200, f"status={reg.status_code} body={reg.text[:200]}")
    if reg.status_code != 200:
        return
    body = reg.json()
    new_token = body.get("token")
    new_user_id = (body.get("user") or {}).get("id") or body.get("id")

    pr = requests.post(f"{BASE}/payment/register-fee", headers=H(new_token), timeout=30)
    rec("Pay /payment/register-fee", pr.status_code == 200, f"status={pr.status_code}")

    if not new_user_id:
        u = get_user_by_email(admin_tok, email)
        new_user_id = u.get("id") if u else None
    ap = requests.post(f"{BASE}/admin/approvals/{new_user_id}/approve", headers=H(admin_tok), timeout=30)
    rec("Approve refed user", ap.status_code == 200, f"status={ap.status_code}")

    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=direct_signup&limit=500",
                     headers=H(admin_tok), timeout=30)
    if r.status_code == 200:
        items = r.json().get("items") or []
        bad = [it for it in items if it.get("source_user_id") == new_user_id]
        rec("No direct_signup_credit row for refed user", len(bad) == 0,
            f"found {len(bad)} unwanted rows")

    aarav_after = get_user_by_email(admin_tok, "aarav@demo.app")
    after_count = int((aarav_after or {}).get("direct_referrals_count") or 0)
    rec("Aarav's direct_referrals_count incremented by 1",
        after_count == aarav_directs_before + 1,
        f"before={aarav_directs_before} after={after_count}")

    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=referral_commission&limit=500",
                     headers=H(admin_tok), timeout=30)
    if r.status_code == 200:
        items = r.json().get("items") or []
        cov = [it for it in items if it.get("type") == "cascade_overflow"
               and (it.get("source_user_name") or "") == name]
        cov_levels = sorted({int(it.get("level")) for it in cov if it.get("level") is not None})
        rec("cascade_overflow rows for refed user are L3..L10 (admin took L2)",
            len(cov) == 8 and cov_levels == list(range(3, 11)),
            f"n={len(cov)} levels={cov_levels}")
        l2 = [it for it in items if it.get("type") == "referral_payout"
              and (it.get("source_user_name") or "").startswith(name[:30])
              and int(it.get("level") or 0) == 2]
        rec("admin received L2 referral_payout for refed user", len(l2) >= 1, f"n_l2={len(l2)}")

    post = get_buckets(admin_tok)
    if pre and post:
        d_signup = round(post.get("direct_signup", 0) - pre.get("direct_signup", 0), 2)
        d_ref = round(post.get("referral_commission", 0) - pre.get("referral_commission", 0), 2)
        rec("direct_signup bucket unchanged for refed user", abs(d_signup) < 0.5, f"delta={d_signup}")
        rec("referral_commission bucket increased ~22.05 (L2 admin + L3..L10 cascade)",
            abs(d_ref - 22.05) < 1.0, f"delta={d_ref}")


# ========== E ==========
def test_placement_algo(admin_tok):
    print("\n--- E) Placement algorithm sanity ---")
    uniq = uuid.uuid4().hex[:6]
    email = f"placetest_{uniq}@test.app"
    reg = requests.post(f"{BASE}/auth/register", json={
        "name": f"PlaceTest {uniq}", "email": email, "password": "Pass@123",
        "phone": f"+917{int(time.time()*1000)%1000000000:09d}",
    }, timeout=30)
    rec("Register no-ref user (placement sanity)",
        reg.status_code == 200, f"status={reg.status_code}")
    if reg.status_code != 200:
        return
    u = get_user_by_email(admin_tok, email)
    admin_id = get_admin_id(admin_tok)
    sp = (u or {}).get("sponsor_id")
    # admin OR a qualifying downline (must be a real user id, non-empty)
    rec("Placement assigned (admin OR qualifying downline, no crash)",
        bool(sp), f"sponsor_id={sp} admin_id={admin_id}")


# ========== F ==========
def test_bucket_validation(admin_tok):
    print("\n--- F) Bucket endpoint validation ---")
    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=invalid_xx",
                     headers=H(admin_tok), timeout=30)
    rec("bucket=invalid_xx → 400 with 'Unknown bucket'",
        r.status_code == 400 and "unknown bucket" in r.text.lower(),
        f"status={r.status_code} body={r.text[:120]}")

    r = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=direct_signup&limit=5",
                     headers=H(admin_tok), timeout=30)
    rec("bucket=direct_signup&limit=5 → 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        items5 = r.json().get("items") or []
        r2 = requests.get(f"{BASE}/admin/system-wallet/transactions?bucket=direct_signup&limit=10",
                          headers=H(admin_tok), timeout=30)
        items10 = r2.json().get("items") or [] if r2.status_code == 200 else []
        # If DB has >=10 rows, limit=5 should still return 10 (clamped) - same as limit=10
        rec("limit=5 was clamped to >=10 (returns same rows as limit=10 when >=10 exist)",
            len(items5) >= min(10, len(items10)),
            f"limit=5 returned {len(items5)}; limit=10 returned {len(items10)}")


def main():
    admin_tok = login(ADMIN_EMAIL, ADMIN_PASS)
    if not admin_tok:
        print("FATAL: admin login failed")
        sys.exit(1)
    print(f"Admin login OK token len={len(admin_tok)}")

    test_demo_users(admin_tok)
    test_admin_tree(admin_tok)
    test_no_ref_signup(admin_tok)
    test_with_ref_signup(admin_tok)
    test_placement_algo(admin_tok)
    test_bucket_validation(admin_tok)

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"RESULT: {passed}/{total} passed")
    failed = [(label, det) for label, ok, det in results if not ok]
    if failed:
        print("\nFAILED:")
        for lbl, det in failed:
            print(f"  ❌ {lbl}  ({det})")


if __name__ == "__main__":
    main()
