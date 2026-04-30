#!/usr/bin/env python3
"""
Support / Ticket System — backend tests.
Tests against https://network-pay-1.preview.emergentagent.com/api
"""
import os, sys, json, time, uuid, random, string, re
import requests

BASE = "https://network-pay-1.preview.emergentagent.com/api"

ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"

RUN = "tkt" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

PASSED = 0
FAILED = 0
FAILURES = []


def log(msg):
    print(msg, flush=True)


def check(cond, desc):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        log(f"  ✅ {desc}")
    else:
        FAILED += 1
        FAILURES.append(desc)
        log(f"  ❌ {desc}")


def hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"login {email} failed {r.status_code}: {r.text}")
    return r.json()["token"], r.json()["user"]


def register(name, email, password, referral_code=None):
    body = {"name": name, "email": email, "password": password}
    if referral_code:
        body["referral_code"] = referral_code
    r = requests.post(f"{BASE}/auth/register", json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"register {email} failed {r.status_code}: {r.text}")
    return r.json()["token"], r.json()["user"]


def main():
    cleanup_ids = {
        "users": [],
        "tickets": [],  # just for manual DB sanity; we drop these via admin if endpoint exists
    }

    # ------------------------------------------------------------------
    # SETUP: admin, plus helper admins (support + finance)
    # ------------------------------------------------------------------
    log("\n=== SETUP ===")
    admin_tok, admin_user = login(ADMIN_EMAIL, ADMIN_PASS)
    check(admin_user.get("admin_role") == "super_admin", "admin login → super_admin")

    # Create a helper support-role admin directly
    support_email = f"support.{RUN}@example.com"
    support_pass = "SuppPass@123"
    r = requests.post(
        f"{BASE}/admin/admins",
        headers=hdr(admin_tok),
        json={"name": "Support Helper", "email": support_email, "password": support_pass, "admin_role": "support"},
        timeout=30,
    )
    check(r.status_code == 200, f"POST /admin/admins support → 200 (got {r.status_code})")
    support_admin = r.json()
    support_id = support_admin.get("id")
    cleanup_ids["users"].append(support_id)
    support_tok, _ = login(support_email, support_pass)

    # Promote a throwaway user to finance
    fin_email = f"fin.{RUN}@example.com"
    fin_pass = "FinPass@123"
    _, fin_user_pre = register("Finance Helper", fin_email, fin_pass)
    fin_id = fin_user_pre["id"]
    cleanup_ids["users"].append(fin_id)
    r = requests.post(f"{BASE}/admin/users/{fin_id}/promote", headers=hdr(admin_tok), json={"admin_role": "finance"}, timeout=30)
    check(r.status_code == 200 and r.json().get("admin_role") == "finance", f"promote {fin_email} to finance")
    fin_tok, _ = login(fin_email, fin_pass)

    # Create a helper manager-role admin (for RBAC negative test)
    mgr_email = f"mgr.{RUN}@example.com"
    mgr_pass = "MgrPass@123"
    r = requests.post(
        f"{BASE}/admin/admins",
        headers=hdr(admin_tok),
        json={"name": "Manager Helper", "email": mgr_email, "password": mgr_pass, "admin_role": "manager"},
        timeout=30,
    )
    check(r.status_code == 200, f"POST /admin/admins manager → 200 (got {r.status_code})")
    mgr_id = r.json().get("id")
    cleanup_ids["users"].append(mgr_id)
    mgr_tok, _ = login(mgr_email, mgr_pass)

    # Register fresh users U1, U2
    u1_email = f"u1.{RUN}@example.com"
    u1_pass = "User1Pass@123"
    _, u1 = register("Aarav Sharma", u1_email, u1_pass)
    u1_id = u1["id"]
    cleanup_ids["users"].append(u1_id)
    u1_tok, _ = login(u1_email, u1_pass)

    u2_email = f"u2.{RUN}@example.com"
    u2_pass = "User2Pass@123"
    _, u2 = register("Priya Verma", u2_email, u2_pass)
    u2_id = u2["id"]
    cleanup_ids["users"].append(u2_id)
    u2_tok, _ = login(u2_email, u2_pass)

    # ------------------------------------------------------------------
    # 1. CREATE ticket
    # ------------------------------------------------------------------
    log("\n=== 1. CREATE TICKET ===")
    # Snapshot admin notif counts for later verification
    def count_ticket_notifs(tok):
        r = requests.get(f"{BASE}/notifications/me", headers=hdr(tok), timeout=30)
        if r.status_code != 200:
            return 0
        return sum(1 for n in r.json() if n.get("kind") == "ticket")

    pre_admin = count_ticket_notifs(admin_tok)
    pre_support = count_ticket_notifs(support_tok)
    pre_fin = count_ticket_notifs(fin_tok)
    pre_mgr = count_ticket_notifs(mgr_tok)

    payload = {
        "subject": "Can't withdraw",
        "category": "withdrawal",
        "message": "I tried to withdraw 500 and it failed",
    }
    r = requests.post(f"{BASE}/tickets", headers=hdr(u1_tok), json=payload, timeout=30)
    check(r.status_code == 200, f"POST /tickets → 200 (got {r.status_code}: {r.text[:200]})")
    if r.status_code == 200:
        body = r.json()
        t = body.get("ticket", {})
        ticket_id = t.get("id")
        cleanup_ids["tickets"].append(ticket_id)
        check(t.get("status") == "open", f"status == open (got {t.get('status')})")
        check(t.get("priority") == "normal", f"priority == normal (got {t.get('priority')})")
        check(t.get("message_count") == 1, f"message_count == 1 (got {t.get('message_count')})")
        check(t.get("has_unread_admin") is True, f"has_unread_admin == True (got {t.get('has_unread_admin')})")
        check(t.get("category") == "withdrawal", f"category == withdrawal (got {t.get('category')})")
    else:
        ticket_id = None

    # Notifications should be delivered to super_admin, support, finance (NOT manager)
    time.sleep(0.5)
    check(count_ticket_notifs(admin_tok) >= pre_admin + 1, "super_admin got a ticket notification")
    check(count_ticket_notifs(support_tok) >= pre_support + 1, "support admin got a ticket notification")
    check(count_ticket_notifs(fin_tok) >= pre_fin + 1, "finance admin got a ticket notification")
    check(count_ticket_notifs(mgr_tok) == pre_mgr, "manager admin did NOT get ticket notification (not in TICKET_ADMIN_ROLES)")

    # 2. Invalid category normalized to "other"
    r = requests.post(
        f"{BASE}/tickets", headers=hdr(u1_tok),
        json={"subject": "bogus cat test", "category": "not-a-real-category", "message": "something here"},
        timeout=30,
    )
    check(r.status_code == 200 and r.json()["ticket"]["category"] == "other", "invalid category → 'other'")
    if r.status_code == 200:
        cleanup_ids["tickets"].append(r.json()["ticket"]["id"])

    # 3. Short subject → 400
    r = requests.post(f"{BASE}/tickets", headers=hdr(u1_tok), json={"subject": "hi", "category": "other", "message": "proper message"}, timeout=30)
    check(r.status_code == 400, f"short subject → 400 (got {r.status_code})")
    r = requests.post(f"{BASE}/tickets", headers=hdr(u1_tok), json={"subject": "valid subject", "category": "other", "message": "a"}, timeout=30)
    check(r.status_code == 400, f"short message → 400 (got {r.status_code})")

    # ------------------------------------------------------------------
    # 4. GET /tickets/me
    # ------------------------------------------------------------------
    log("\n=== 4. GET /tickets/me ===")
    r = requests.get(f"{BASE}/tickets/me", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"GET /tickets/me → 200 (got {r.status_code})")
    if r.status_code == 200:
        ids = [t["id"] for t in r.json().get("items", [])]
        check(ticket_id in ids, "new ticket appears in /tickets/me")

    # ------------------------------------------------------------------
    # 5. GET /tickets/{id} as U1
    # ------------------------------------------------------------------
    log("\n=== 5. GET /tickets/{id} as owner ===")
    r = requests.get(f"{BASE}/tickets/{ticket_id}", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"GET /tickets/{{id}} → 200 (got {r.status_code})")
    if r.status_code == 200:
        body = r.json()
        check("messages" in body and len(body["messages"]) >= 1, f"messages[] present (len={len(body.get('messages', []))})")
        check(body["ticket"].get("has_unread_user") is False, "has_unread_user cleared")

    # ------------------------------------------------------------------
    # 6. GET /tickets/{id} as U2 → 403
    # ------------------------------------------------------------------
    log("\n=== 6. GET /tickets/{id} as another user ===")
    r = requests.get(f"{BASE}/tickets/{ticket_id}", headers=hdr(u2_tok), timeout=30)
    check(r.status_code == 403, f"U2 fetching U1's ticket → 403 (got {r.status_code})")

    # ------------------------------------------------------------------
    # 7. U1 replies
    # ------------------------------------------------------------------
    log("\n=== 7. U1 replies ===")
    r = requests.post(f"{BASE}/tickets/{ticket_id}/reply", headers=hdr(u1_tok), json={"message": "update on my withdrawal issue"}, timeout=30)
    check(r.status_code == 200, f"U1 reply → 200 (got {r.status_code}: {r.text[:200]})")
    if r.status_code == 200:
        t = r.json()["ticket"]
        check(t["message_count"] == 2, f"message_count == 2 (got {t['message_count']})")
        check(t["has_unread_admin"] is True, "has_unread_admin == True after user reply")
        check(t["last_message_by"] == "user", f"last_message_by == user (got {t.get('last_message_by')})")

    # ------------------------------------------------------------------
    # 8. ADMIN REPLY (super_admin)
    # ------------------------------------------------------------------
    log("\n=== 8. admin replies ===")
    pre_u1_notifs = count_ticket_notifs(u1_tok)
    r = requests.post(f"{BASE}/tickets/{ticket_id}/reply", headers=hdr(admin_tok), json={"message": "we'll check this out"}, timeout=30)
    check(r.status_code == 200, f"admin reply → 200 (got {r.status_code}: {r.text[:200]})")
    if r.status_code == 200:
        t = r.json()["ticket"]
        check(t["status"] == "in_progress", f"status flipped to in_progress (got {t['status']})")
        check(t["has_unread_user"] is True, "has_unread_user == True after admin reply")
        check(t["last_message_by"] == "admin", f"last_message_by == admin (got {t['last_message_by']})")
    # Verify messages include admin sender_type
    r = requests.get(f"{BASE}/tickets/{ticket_id}", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        types = [m["sender_type"] for m in r.json().get("messages", [])]
        check("admin" in types, f"admin message has sender_type='admin' (types={types})")
    # Verify U1 got notified
    time.sleep(0.3)
    check(count_ticket_notifs(u1_tok) >= pre_u1_notifs + 1, "U1 received notification for admin reply")

    # ------------------------------------------------------------------
    # 9. ADMIN LIST + filters
    # ------------------------------------------------------------------
    log("\n=== 9. ADMIN LIST + FILTERS ===")
    r = requests.get(f"{BASE}/admin/tickets", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"GET /admin/tickets → 200 (got {r.status_code})")
    if r.status_code == 200:
        body = r.json()
        check("items" in body and "counts" in body, "list returns items + counts")
        counts = body.get("counts", {})
        check(all(k in counts for k in ("open", "in_progress", "unread_admin")), f"counts has open/in_progress/unread_admin (got {list(counts.keys())})")

    # status=in_progress
    r = requests.get(f"{BASE}/admin/tickets?status=in_progress", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        items = r.json().get("items", [])
        check(all(i["status"] == "in_progress" for i in items), "status=in_progress filter only returns in_progress")
        check(any(i["id"] == ticket_id for i in items), "U1's in_progress ticket appears")

    # category=withdrawal
    r = requests.get(f"{BASE}/admin/tickets?category=withdrawal", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        ids = [i["id"] for i in r.json().get("items", [])]
        check(ticket_id in ids, "category=withdrawal contains U1's ticket")

    # q=withdraw (case-insensitive)
    r = requests.get(f"{BASE}/admin/tickets?q=WiTHdraw", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        ids = [i["id"] for i in r.json().get("items", [])]
        check(ticket_id in ids, "q='WiTHdraw' case-insensitive matches U1's ticket")

    # assigned_to=me (before assignment) → empty / not contain our ticket
    r = requests.get(f"{BASE}/admin/tickets?assigned_to=me", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        ids = [i["id"] for i in r.json().get("items", [])]
        check(ticket_id not in ids, "assigned_to=me before assignment does NOT include our ticket")

    # assigned_to=unassigned → includes ticket
    r = requests.get(f"{BASE}/admin/tickets?assigned_to=unassigned", headers=hdr(admin_tok), timeout=30)
    if r.status_code == 200:
        ids = [i["id"] for i in r.json().get("items", [])]
        check(ticket_id in ids, "assigned_to=unassigned includes our unassigned ticket")

    # Manager → 403
    r = requests.get(f"{BASE}/admin/tickets", headers=hdr(mgr_tok), timeout=30)
    check(r.status_code == 403, f"manager admin → 403 (got {r.status_code})")

    # support → 200
    r = requests.get(f"{BASE}/admin/tickets", headers=hdr(support_tok), timeout=30)
    check(r.status_code == 200, f"support admin → 200 (got {r.status_code})")

    # finance → 200
    r = requests.get(f"{BASE}/admin/tickets", headers=hdr(fin_tok), timeout=30)
    check(r.status_code == 200, f"finance admin → 200 (got {r.status_code})")

    # No auth → 401 or 403
    r = requests.get(f"{BASE}/admin/tickets", timeout=30)
    check(r.status_code in (401, 403), f"no-auth → 401/403 (got {r.status_code})")

    # ------------------------------------------------------------------
    # 10. ADMIN PATCH
    # ------------------------------------------------------------------
    log("\n=== 10. ADMIN PATCH ===")
    pre_u1_notifs = count_ticket_notifs(u1_tok)

    # status=resolved
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"status": "resolved"}, timeout=30)
    check(r.status_code == 200, f"PATCH status=resolved → 200 (got {r.status_code})")
    if r.status_code == 200:
        t = r.json()["ticket"]
        check(t["status"] == "resolved", "status == resolved")
        check(t.get("resolved_at") is not None, "resolved_at stamped")

    # priority=high
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"priority": "high"}, timeout=30)
    check(r.status_code == 200 and r.json()["ticket"]["priority"] == "high", "PATCH priority=high")

    # assigned_to=support_id
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"assigned_to": support_id}, timeout=30)
    check(r.status_code == 200, f"PATCH assigned_to=support_id → 200 (got {r.status_code}: {r.text[:200]})")
    if r.status_code == 200:
        t = r.json()["ticket"]
        check(t["assigned_to"] == support_id, f"assigned_to stored (got {t['assigned_to']})")
        check(t["assigned_to_email"] == support_email, f"assigned_to_email stored (got {t['assigned_to_email']})")

    # after PATCH, assigned_to=me from support_tok perspective returns it
    r = requests.get(f"{BASE}/admin/tickets?assigned_to=me", headers=hdr(support_tok), timeout=30)
    if r.status_code == 200:
        ids = [i["id"] for i in r.json().get("items", [])]
        check(ticket_id in ids, "assigned_to=me from support returns the assigned ticket")

    # Invalid assignee
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"assigned_to": "not-a-real-id-" + RUN}, timeout=30)
    check(r.status_code == 400, f"invalid assignee → 400 (got {r.status_code})")

    # Unassign
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"assigned_to": ""}, timeout=30)
    check(r.status_code == 200 and r.json()["ticket"]["assigned_to"] is None, "PATCH assigned_to='' → unassigned (null)")

    # Invalid status
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"status": "bogus"}, timeout=30)
    check(r.status_code == 400, f"invalid status → 400 (got {r.status_code})")

    # Invalid priority
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"priority": "bogus"}, timeout=30)
    check(r.status_code == 400, f"invalid priority → 400 (got {r.status_code})")

    # Check U1 received at least one notification across these changes
    time.sleep(0.3)
    check(count_ticket_notifs(u1_tok) > pre_u1_notifs, f"U1 got notification(s) from PATCH changes (before={pre_u1_notifs}, after={count_ticket_notifs(u1_tok)})")

    # ------------------------------------------------------------------
    # 11. USER CLOSE by owner while resolved
    # ------------------------------------------------------------------
    log("\n=== 11. USER CLOSE ===")
    # Bring ticket back to resolved
    r = requests.patch(f"{BASE}/admin/tickets/{ticket_id}", headers=hdr(admin_tok), json={"status": "resolved"}, timeout=30)
    check(r.status_code == 200, "bring ticket back to resolved for close test")
    r = requests.post(f"{BASE}/tickets/{ticket_id}/close", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"U1 close resolved ticket → 200 (got {r.status_code})")
    # Second close → 400
    r = requests.post(f"{BASE}/tickets/{ticket_id}/close", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 400, f"U1 close already-closed ticket → 400 (got {r.status_code})")

    # ------------------------------------------------------------------
    # 12. Reply to closed ticket → 400
    # ------------------------------------------------------------------
    log("\n=== 12. REPLY TO CLOSED ===")
    r = requests.post(f"{BASE}/tickets/{ticket_id}/reply", headers=hdr(u1_tok), json={"message": "another attempt"}, timeout=30)
    check(r.status_code == 400, f"reply to closed → 400 (got {r.status_code})")

    # ------------------------------------------------------------------
    # 13. ADMIN STATS
    # ------------------------------------------------------------------
    log("\n=== 13. ADMIN STATS ===")
    r = requests.get(f"{BASE}/admin/tickets/stats", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"GET /admin/tickets/stats → 200 (got {r.status_code})")
    if r.status_code == 200:
        s = r.json()
        needed = ("total", "open", "in_progress", "resolved", "closed", "unread_admin")
        check(all(k in s for k in needed), f"stats has all keys (got {list(s.keys())})")
        check(all(isinstance(s[k], int) and s[k] >= 0 for k in needed), "all stats are non-negative integers")

    # ------------------------------------------------------------------
    # 14. ADMIN EXPORT
    # ------------------------------------------------------------------
    log("\n=== 14. ADMIN EXPORT CSV ===")
    r = requests.get(f"{BASE}/admin/tickets/export", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"GET /admin/tickets/export → 200 (got {r.status_code})")
    if r.status_code == 200:
        ctype = r.headers.get("content-type", "")
        check("text/csv" in ctype, f"content-type text/csv (got {ctype})")
        check("attachment" in r.headers.get("content-disposition", "").lower(), f"Content-Disposition attachment (got {r.headers.get('content-disposition')})")
        header_line = r.text.split("\n", 1)[0]
        needed_cols = ["id", "subject", "category", "priority", "status", "user_email", "user_name",
                       "assigned_to_email", "message_count", "created_at", "updated_at",
                       "last_message_at", "last_message_by"]
        missing = [c for c in needed_cols if c not in header_line]
        check(not missing, f"CSV header has all 13 cols (missing={missing})")

    # ------------------------------------------------------------------
    # 15. REGRESSION
    # ------------------------------------------------------------------
    log("\n=== 15. REGRESSION ===")
    r = requests.get(f"{BASE}/admin/approvals?status=pending", headers=hdr(admin_tok), timeout=30)
    check(r.status_code == 200, f"/admin/approvals?status=pending → 200 (got {r.status_code})")
    r = requests.get(f"{BASE}/cart", headers=hdr(u1_tok), timeout=30)
    check(r.status_code == 200, f"/cart → 200 (got {r.status_code})")
    r = requests.get(f"{BASE}/branding", timeout=30)
    check(r.status_code == 200, f"/branding → 200 (got {r.status_code})")

    # ------------------------------------------------------------------
    # CLEANUP
    # ------------------------------------------------------------------
    log("\n=== CLEANUP ===")
    # Delete each user via admin DELETE; we have to demote admin helpers first only if necessary
    # DELETE /admin/users/{id} should work for any user (admin or not)
    # Delete tickets/messages via direct mongo — but we don't have direct mongo tool here.
    # Tickets will still exist in DB. We'll just delete users.
    for uid in cleanup_ids["users"]:
        if not uid:
            continue
        r = requests.delete(f"{BASE}/admin/users/{uid}", headers=hdr(admin_tok), timeout=30)
        log(f"  delete user {uid}: {r.status_code}")

    # Try to clean up tickets too — no dedicated endpoint exists, attempt via db is not exposed. Skip.
    # Verify admin still works
    r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    check(r.status_code == 200, "admin@app.com still works after cleanup")

    # ------------------------------------------------------------------
    log(f"\n==== RESULT: {PASSED} PASSED, {FAILED} FAILED ====")
    if FAILURES:
        log("FAILURES:")
        for f in FAILURES:
            log(f"  - {f}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
