"""
Services Marketplace end-to-end test suite.

Scenarios A-H as per review request. Uses live backend URL. Registers
fresh users, funds via HMAC-valid /payment/verify (auto-approve), then
exercises the full apply→approve→list→book→split→bookings-me→reject
cycle plus RBAC/edge cases. Cleans up all throwaway users at the end.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests


BASE_URL = "https://network-pay-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASSWORD = "Admin@123"
RAZORPAY_KEY_SECRET = "QrEEeWzxU5xJdRh1HrXeDUIy"

S = requests.Session()
S.headers.update({"Content-Type": "application/json"})

PASS = 0
FAIL = 0
FAILURES: List[str] = []
CREATED_USER_IDS: List[str] = []


def rec(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        msg = f"❌ {name} :: {detail}"
        FAILURES.append(msg)
        print(f"  {msg}")


def api(method: str, path: str, token: Optional[str] = None, json_body: Any = None,
        params: Dict[str, Any] | None = None, expect: int | None = None) -> Tuple[int, Any]:
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = S.request(method, url, headers=headers, data=json.dumps(json_body) if json_body is not None else None,
                      params=params, timeout=30)
    except Exception as e:
        return 0, {"error": str(e)}
    try:
        body = r.json()
    except Exception:
        body = {"_text": r.text[:500]}
    return r.status_code, body


def login_admin() -> str:
    sc, body = api("POST", "/auth/login", json_body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert sc == 200, f"admin login failed {sc} {body}"
    return body["token"]


def register_and_approve(name_prefix: str, pay: bool = True) -> Dict[str, Any]:
    """Register a fresh user + auto-approve via valid HMAC /payment/verify."""
    suffix = secrets.token_hex(4)
    email = f"{name_prefix}.{suffix}@svctest.example.com"
    password = "Passw0rd!" + suffix
    body = {"name": f"{name_prefix.capitalize()} {suffix}", "email": email, "password": password,
            "phone": f"99{secrets.randbelow(10**8):08d}"}
    sc, resp = api("POST", "/auth/register", json_body=body)
    assert sc == 200, f"register {name_prefix} failed: {sc} {resp}"
    token = resp["token"]
    uid = resp["user"]["id"]
    CREATED_USER_IDS.append(uid)
    if not pay:
        return {"id": uid, "email": email, "password": password, "token": token, "referral_code": resp["user"]["referral_code"]}
    # create order
    sc, resp = api("POST", "/payment/create-order", token=token)
    assert sc == 200, f"create-order for {email} failed: {sc} {resp}"
    order_id = resp["order_id"]
    pay_id = f"pay_test_{secrets.token_hex(8)}"
    sig = hmac.new(RAZORPAY_KEY_SECRET.encode(),
                   f"{order_id}|{pay_id}".encode(),
                   hashlib.sha256).hexdigest()
    sc, resp = api("POST", "/payment/verify", token=token, json_body={
        "razorpay_order_id": order_id, "razorpay_payment_id": pay_id, "razorpay_signature": sig,
    })
    assert sc == 200, f"verify for {email} failed: {sc} {resp}"
    assert resp.get("approval_status") == "approved", f"not auto-approved for {email}: {resp}"
    return {"id": uid, "email": email, "password": password, "token": token,
            "referral_code": None}  # referral_code not needed later


def get_user_doc(admin_token: str, uid: str) -> Optional[Dict[str, Any]]:
    sc, body = api("GET", "/admin/users", token=admin_token)
    if sc != 200:
        return None
    for u in body:
        if u["id"] == uid:
            return u
    return None


def admin_credit(admin_token: str, uid: str, amount: float) -> Tuple[int, Any]:
    return api("POST", f"/admin/users/{uid}/wallet", token=admin_token, json_body={
        "amount": amount, "type": "credit", "reason": "Services marketplace test seed",
    })


def delete_user(admin_token: str, uid: str) -> None:
    api("DELETE", f"/admin/users/{uid}", token=admin_token)


# ============================================================================
# Scenario runner
# ============================================================================
def run():
    print("=" * 72)
    print("SERVICES MARKETPLACE — end-to-end test")
    print("=" * 72)

    # --- SETUP ---
    print("\n[SETUP] admin login + register 3 throwaway users")
    admin_token = login_admin()
    rec("admin login", True)

    # Grab admin doc for later wallet delta
    admin_doc_before = None
    sc, users = api("GET", "/admin/users", token=admin_token)
    for u in users:
        if u["email"] == ADMIN_EMAIL:
            admin_doc_before = u
            break
    rec("admin user doc resolved", admin_doc_before is not None,
        detail="no admin row")

    U_p = register_and_approve("provider")
    U_c = register_and_approve("customer")
    U_q = register_and_approve("rejecting")  # for reject-flow in scenario E
    U_p2 = register_and_approve("provider2")  # second provider for insufficient-balance test

    print(f"  U_p  id={U_p['id'][:8]}  U_c id={U_c['id'][:8]}")
    print(f"  U_q  id={U_q['id'][:8]}  U_p2 id={U_p2['id'][:8]}")

    # Seed customer wallet with 1000
    sc, resp = admin_credit(admin_token, U_c["id"], 1000.0)
    rec("admin credit U_c wallet ₹1000 (200)", sc == 200, detail=f"{sc} {resp}")

    # ------------------------------------------------------------------
    # Scenario A — APPLY + ADMIN APPROVE
    # ------------------------------------------------------------------
    print("\n[A] Apply + admin approve")
    apply_body = {
        "service_name": "AC Repair",
        "service_category": "Electrician",
        "pincode": "560001",
        "charge": 500,
        "description": "Same-day service",
    }
    sc, resp = api("POST", "/service/apply", token=U_p["token"], json_body=apply_body)
    rec("A.1 POST /service/apply by U_p → 200", sc == 200, detail=f"{sc} {resp}")
    app_id = (resp.get("application") or {}).get("id") if isinstance(resp, dict) else None
    rec("A.1b application.id returned", bool(app_id), detail=str(resp))

    sc, resp = api("GET", "/service/me", token=U_p["token"])
    rec("A.2 GET /service/me → 200", sc == 200, detail=f"{sc} {resp}")
    rec("A.2b service_status == 'pending'", resp.get("service_status") == "pending",
        detail=str(resp))
    rec("A.2c is_service_provider false before approval",
        resp.get("is_service_provider") is False, detail=str(resp))

    sc, resp = api("GET", "/admin/service-applications", token=admin_token,
                   params={"status": "pending"})
    rec("A.3 admin list pending → 200", sc == 200, detail=f"{sc} {resp}")
    items = resp.get("items", []) if isinstance(resp, dict) else []
    counts = resp.get("counts", {}) if isinstance(resp, dict) else {}
    rec("A.3b counts.pending >= 1", counts.get("pending", 0) >= 1, detail=str(counts))
    ids_in_list = {i.get("id") for i in items}
    rec("A.3c U_p's application in list", app_id in ids_in_list, detail=str(ids_in_list))

    sc, resp = api("POST", f"/admin/service-applications/{app_id}/approve", token=admin_token)
    rec("A.4 admin approve → 200", sc == 200, detail=f"{sc} {resp}")

    # Verify U_p state
    up_doc = get_user_doc(admin_token, U_p["id"])
    rec("A.5 U_p.is_service_provider=True", bool(up_doc and up_doc.get("is_service_provider")),
        detail=str(up_doc))
    rec("A.5b U_p.service_status='approved'", (up_doc or {}).get("service_status") == "approved",
        detail=str(up_doc))
    rec("A.5c U_p.service_charge == 500",
        float((up_doc or {}).get("service_charge") or 0) == 500.0, detail=str(up_doc))
    rec("A.5d U_p.service_category == 'Electrician'",
        (up_doc or {}).get("service_category") == "Electrician", detail=str(up_doc))
    rec("A.5e U_p.service_pincode == '560001'",
        (up_doc or {}).get("service_pincode") == "560001", detail=str(up_doc))

    # approve U_p2 (for later insufficient-balance test @600)
    sc, resp = api("POST", "/service/apply", token=U_p2["token"], json_body={
        "service_name": "Plumbing Emergency", "service_category": "Plumber",
        "pincode": "560002", "charge": 600, "description": "24x7 plumber",
    })
    rec("A.6 U_p2 apply → 200", sc == 200, detail=f"{sc} {resp}")
    app2_id = (resp.get("application") or {}).get("id")
    sc, resp = api("POST", f"/admin/service-applications/{app2_id}/approve", token=admin_token)
    rec("A.7 U_p2 approved → 200", sc == 200, detail=f"{sc} {resp}")

    # notification check
    sc, resp = api("GET", "/notifications/me", token=U_p["token"])
    if sc == 200 and isinstance(resp, list):
        has_approved_notif = any("Service listing approved" == (n.get("title") or "") for n in resp)
        rec("A.8 U_p notification 'Service listing approved'", has_approved_notif,
            detail=str([n.get('title') for n in resp][:5]))
    else:
        rec("A.8 U_p notifications GET 200", False, detail=f"{sc} {resp}")

    # ------------------------------------------------------------------
    # Scenario B — PUBLIC LISTING + FILTERS
    # ------------------------------------------------------------------
    print("\n[B] Public listing + filters")

    sc, resp = api("GET", "/services", token=U_c["token"])
    rec("B.1 GET /services (U_c) → 200", sc == 200, detail=f"{sc} {resp}")
    items = resp.get("items", []) if isinstance(resp, dict) else []
    ids_in_list = {i.get("id") for i in items}
    rec("B.1b U_p present in items", U_p["id"] in ids_in_list,
        detail=f"saw {len(items)} items, ids={list(ids_in_list)[:5]}")

    sc, resp = api("GET", "/services", token=U_c["token"], params={"pincode": "560001"})
    rec("B.2 /services?pincode=560001 → 200", sc == 200)
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("B.2b U_p in 560001 filter",
        U_p["id"] in {i.get("id") for i in items}, detail=str(items))

    sc, resp = api("GET", "/services", token=U_c["token"], params={"pincode": "999999"})
    rec("B.3 /services?pincode=999999 → 200", sc == 200)
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("B.3b no-results for pincode=999999", len(items) == 0, detail=str(items))

    sc, resp = api("GET", "/services", token=U_c["token"], params={"category": "Electrician"})
    rec("B.4 /services?category=Electrician → 200", sc == 200)
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("B.4b U_p in category=Electrician",
        U_p["id"] in {i.get("id") for i in items}, detail=str(items))

    sc, resp = api("GET", "/services", token=U_c["token"], params={"q": "AC"})
    rec("B.5 /services?q=AC → 200", sc == 200)
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("B.5b U_p in q=AC",
        U_p["id"] in {i.get("id") for i in items}, detail=str(items))

    sc, resp = api("GET", "/services/categories", token=U_c["token"])
    rec("B.6 /services/categories → 200", sc == 200, detail=f"{sc} {resp}")
    cats = resp.get("categories", []) if isinstance(resp, dict) else []
    rec("B.6b categories contains 'Electrician'", "Electrician" in cats,
        detail=str(cats))

    # ------------------------------------------------------------------
    # Scenario C — BOOK + WALLET FLOW
    # ------------------------------------------------------------------
    print("\n[C] Book + wallet split")

    # Snapshot balances
    uc_before = get_user_doc(admin_token, U_c["id"])
    up_before = get_user_doc(admin_token, U_p["id"])
    admin_before = get_user_doc(admin_token, admin_doc_before["id"])
    uc_bal_before = float((uc_before or {}).get("wallet_balance") or 0)
    up_bal_before = float((up_before or {}).get("wallet_balance") or 0)
    admin_bal_before = float((admin_before or {}).get("wallet_balance") or 0)

    sc, resp = api("POST", f"/services/{U_p['id']}/book", token=U_c["token"], json_body={
        "notes": "Come between 10-12 AM",
        "scheduled_date": "2026-06-15",
    })
    rec("C.1 U_c books U_p service → 200", sc == 200, detail=f"{sc} {resp}")
    booking = resp.get("booking", {}) if isinstance(resp, dict) else {}
    booking_id = booking.get("id")
    rec("C.1b booking.id returned", bool(booking_id), detail=str(booking))
    rec("C.1c booking.charge == 500", float(booking.get("charge") or 0) == 500.0, detail=str(booking))
    rec("C.1d booking.provider_share == 350", float(booking.get("provider_share") or 0) == 350.0, detail=str(booking))
    rec("C.1e booking.admin_share == 150", float(booking.get("admin_share") or 0) == 150.0, detail=str(booking))
    rec("C.1f booking.status == 'confirmed'", booking.get("status") == "confirmed", detail=str(booking))

    # Wallet deltas
    uc_after = get_user_doc(admin_token, U_c["id"])
    up_after = get_user_doc(admin_token, U_p["id"])
    admin_after = get_user_doc(admin_token, admin_doc_before["id"])
    uc_delta = float(uc_after["wallet_balance"]) - uc_bal_before
    up_delta = float(up_after["wallet_balance"]) - up_bal_before
    admin_delta = float(admin_after["wallet_balance"]) - admin_bal_before
    rec("C.2 U_c wallet delta == -500",
        round(uc_delta, 2) == -500.0, detail=f"delta={uc_delta}")
    rec("C.3 U_p wallet delta == +350 (70%)",
        round(up_delta, 2) == 350.0, detail=f"delta={up_delta}")
    rec("C.4 admin wallet delta == +150 (30% platform fee)",
        round(admin_delta, 2) == 150.0, detail=f"delta={admin_delta}")

    # 3 transactions inserted
    sc, uc_txs = api("GET", "/transactions/me", token=U_c["token"])
    sc2, up_txs = api("GET", "/transactions/me", token=U_p["token"])
    uc_book_txs = [t for t in (uc_txs or []) if t.get("booking_id") == booking_id and t.get("type") == "service_booking"]
    up_earn_txs = [t for t in (up_txs or []) if t.get("booking_id") == booking_id and t.get("type") == "service_earning"]
    rec("C.5 customer tx type=service_booking, -500 inserted",
        len(uc_book_txs) == 1 and float(uc_book_txs[0].get("amount") or 0) == -500.0,
        detail=str(uc_book_txs))
    rec("C.6 provider tx type=service_earning, +350 inserted",
        len(up_earn_txs) == 1 and float(up_earn_txs[0].get("amount") or 0) == 350.0,
        detail=str(up_earn_txs))

    # admin commission tx
    sc, admin_txs_resp = api("GET", "/admin/transactions", token=admin_token, params={"user_id": admin_doc_before["id"]})
    # admin/transactions maybe different path — fall back to /transactions/me with admin token
    if sc != 200 or not isinstance(admin_txs_resp, list):
        sc, admin_txs_resp = api("GET", "/transactions/me", token=admin_token)
    admin_comm_txs = [t for t in (admin_txs_resp or []) if isinstance(t, dict)
                      and t.get("booking_id") == booking_id
                      and t.get("type") == "service_commission"]
    rec("C.7 admin tx type=service_commission, +150 inserted",
        len(admin_comm_txs) == 1 and float(admin_comm_txs[0].get("amount") or 0) == 150.0,
        detail=str(admin_comm_txs))

    # Provider notification "New service booking"
    sc, up_notifs = api("GET", "/notifications/me", token=U_p["token"])
    rec("C.8 provider notif 'New service booking'",
        any(n.get("title") == "New service booking" for n in (up_notifs or [])),
        detail=str([n.get("title") for n in (up_notifs or [])][:5]))
    sc, uc_notifs = api("GET", "/notifications/me", token=U_c["token"])
    rec("C.9 customer notif 'Service booking confirmed'",
        any(n.get("title") == "Service booking confirmed" for n in (uc_notifs or [])),
        detail=str([n.get("title") for n in (uc_notifs or [])][:5]))

    # ------------------------------------------------------------------
    # Scenario D — EDGE CASES
    # ------------------------------------------------------------------
    print("\n[D] Edge cases")

    sc, resp = api("POST", f"/services/{U_p['id']}/book", token=U_p["token"], json_body={})
    rec("D.1 self-book → 400", sc == 400, detail=f"{sc} {resp}")

    # U_c now has 500 balance; booking U_p2 @600 must 400
    sc, resp = api("POST", f"/services/{U_p2['id']}/book", token=U_c["token"], json_body={})
    rec("D.2 insufficient balance U_p2(600) → 400", sc == 400, detail=f"{sc} {resp}")

    # admin tries to apply → 400
    sc, resp = api("POST", "/service/apply", token=admin_token, json_body={
        "service_name": "Consulting", "service_category": "Consultant",
        "pincode": "110001", "charge": 100,
    })
    rec("D.3 admin apply → 400", sc == 400, detail=f"{sc} {resp}")

    # double-apply: U_p2 already has an approved application → 400
    sc, resp = api("POST", "/service/apply", token=U_p2["token"], json_body={
        "service_name": "Another", "service_category": "Plumber",
        "pincode": "560002", "charge": 150,
    })
    rec("D.4 double-apply (approved already) → 400", sc == 400, detail=f"{sc} {resp}")

    # invalid pincode (5 digit) → 422
    sc, resp = api("POST", "/service/apply", token=U_q["token"], json_body={
        "service_name": "Tutor", "service_category": "Tutor",
        "pincode": "12345", "charge": 250,
    })
    rec("D.5 pincode=5 digits → 422", sc == 422, detail=f"{sc} {resp}")

    # ------------------------------------------------------------------
    # Scenario E — REJECT FLOW
    # ------------------------------------------------------------------
    print("\n[E] Reject flow")

    sc, resp = api("POST", "/service/apply", token=U_q["token"], json_body={
        "service_name": "Math Tutor", "service_category": "Tutor",
        "pincode": "560003", "charge": 300, "description": "Grade 9-12",
    })
    rec("E.1 U_q apply → 200", sc == 200, detail=f"{sc} {resp}")
    uq_app_id = (resp.get("application") or {}).get("id")

    sc, resp = api("POST", f"/admin/service-applications/{uq_app_id}/reject",
                   token=admin_token, json_body={"reason": "Outside city"})
    rec("E.2 admin reject with reason → 200", sc == 200, detail=f"{sc} {resp}")

    uq_doc = get_user_doc(admin_token, U_q["id"])
    rec("E.3 U_q.service_status=='rejected'",
        (uq_doc or {}).get("service_status") == "rejected", detail=str(uq_doc))

    # notification body matches reason
    sc, uq_notifs = api("GET", "/notifications/me", token=U_q["token"])
    rej_notif = next((n for n in (uq_notifs or []) if n.get("title") == "Service listing rejected"), None)
    rec("E.4 U_q notification has 'Outside city' in body",
        bool(rej_notif) and "Outside city" in (rej_notif.get("body") or ""),
        detail=str(rej_notif))

    # U_q can re-apply after rejection
    sc, resp = api("POST", "/service/apply", token=U_q["token"], json_body={
        "service_name": "Math Tutor v2", "service_category": "Tutor",
        "pincode": "110011", "charge": 350,
    })
    rec("E.5 U_q re-apply after reject → 200", sc == 200, detail=f"{sc} {resp}")
    uq_app2_id = (resp.get("application") or {}).get("id")
    rec("E.5b new application id is new",
        bool(uq_app2_id) and uq_app2_id != uq_app_id, detail=f"old={uq_app_id} new={uq_app2_id}")

    # ------------------------------------------------------------------
    # Scenario F — BOOKINGS-ME
    # ------------------------------------------------------------------
    print("\n[F] /services/bookings/me")

    sc, resp = api("GET", "/services/bookings/me", token=U_p["token"], params={"role": "provider"})
    rec("F.1 U_p role=provider → 200", sc == 200, detail=f"{sc} {resp}")
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("F.1b U_p sees booking as provider",
        any(b.get("id") == booking_id for b in items), detail=f"items={items}")

    sc, resp = api("GET", "/services/bookings/me", token=U_c["token"], params={"role": "customer"})
    rec("F.2 U_c role=customer → 200", sc == 200, detail=f"{sc} {resp}")
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("F.2b U_c sees booking as customer",
        any(b.get("id") == booking_id for b in items), detail=f"items={items}")

    # all role
    sc, resp = api("GET", "/services/bookings/me", token=U_p["token"], params={"role": "all"})
    items = resp.get("items", []) if isinstance(resp, dict) else []
    rec("F.3 role=all returns booking for U_p",
        sc == 200 and any(b.get("id") == booking_id for b in items), detail=str(resp))

    # ------------------------------------------------------------------
    # Scenario G — RBAC
    # ------------------------------------------------------------------
    print("\n[G] RBAC")

    sc, resp = api("GET", "/admin/service-applications", token=U_c["token"])
    rec("G.1 non-admin GET /admin/service-applications → 403", sc == 403, detail=f"{sc} {resp}")

    sc, resp = api("GET", "/services", token=U_c["token"])
    rec("G.2 non-admin logged-in GET /services → 200", sc == 200, detail=f"{sc} {resp}")

    sc, resp = api("GET", "/services")
    rec("G.3 unauthenticated GET /services → 401/403",
        sc in (401, 403), detail=f"{sc} {resp}")

    # ------------------------------------------------------------------
    # Scenario H — CLEANUP
    # ------------------------------------------------------------------
    print("\n[H] Cleanup")
    deleted = 0
    for uid in CREATED_USER_IDS:
        sc, _ = api("DELETE", f"/admin/users/{uid}", token=admin_token)
        if sc == 200:
            deleted += 1
    rec(f"H.1 deleted {deleted}/{len(CREATED_USER_IDS)} throwaway users",
        deleted == len(CREATED_USER_IDS), detail=f"deleted={deleted}")

    # Summary
    print("\n" + "=" * 72)
    print(f"RESULTS: {PASS} passed / {FAIL} failed")
    print("=" * 72)
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  {f}")
    return FAIL == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
