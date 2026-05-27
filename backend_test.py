"""
Backend test harness for THREE features (see /app/test_result.md request):

  F1 — Public (guest) Support Ticket endpoint POST /api/tickets/public
  F2 — Splash image remove fix (PUT /api/admin/branding with splash_image="")
  F3 — Authenticated ticket regression

Credentials read from /app/memory/test_credentials.md:
  admin@app.com / Admin@123
  testuser@app.com / Test@123
"""
from __future__ import annotations

import sys
import uuid
import asyncio
from typing import Any, Dict, List, Optional

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@app.com"
ADMIN_PASS = "Admin@123"
USER_EMAIL = "testuser@app.com"
USER_PASS = "Test@123"

MONGO_URL: Optional[str] = None
DB_NAME: Optional[str] = None
try:
    with open("/app/backend/.env", "r") as f:
        for ln in f:
            ln = ln.strip()
            if ln.startswith("MONGO_URL="):
                MONGO_URL = ln.split("=", 1)[1].strip().strip('"').strip("'")
            elif ln.startswith("DB_NAME="):
                DB_NAME = ln.split("=", 1)[1].strip().strip('"').strip("'")
except Exception:
    pass

if not MONGO_URL:
    MONGO_URL = "mongodb://localhost:27017"
if not DB_NAME:
    DB_NAME = "test_database"

PASSED: List[str] = []
FAILED: List[str] = []


def ok(label: str) -> None:
    PASSED.append(label)
    print(f"  ✅ {label}")


def fail(label: str, detail: str = "") -> None:
    FAILED.append(f"{label} — {detail}" if detail else label)
    print(f"  ❌ {label} — {detail}")


def assert_eq(label: str, got: Any, want: Any) -> None:
    if got == want:
        ok(f"{label} (={got!r})")
    else:
        fail(label, f"expected={want!r} got={got!r}")


def section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


async def login(client: httpx.AsyncClient, email: str, password: str) -> Optional[str]:
    r = await client.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        print(f"  ! login {email} → {r.status_code} {r.text[:200]}")
        return None
    return r.json().get("token")


async def db_get(coll: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cli = AsyncIOMotorClient(MONGO_URL)
    try:
        return await cli[DB_NAME][coll].find_one(query)
    finally:
        cli.close()


# ──────────────────────────────────────────────────────────────────────
# FEATURE 1 — PUBLIC GUEST TICKET
# ──────────────────────────────────────────────────────────────────────
async def feature1_guest_tickets(client: httpx.AsyncClient) -> List[str]:
    created_guest_ids: List[str] = []
    section("FEATURE 1 — POST /api/tickets/public (guest)")

    # ── A: HAPPY PATH (category=other + custom_category)
    print("\n[A] Happy path — category='other' with custom_category")
    test_uuid = uuid.uuid4().hex[:8]
    a_email = f"guest-a-{test_uuid}@example.com"
    a_name = "Asha Patel"
    a_subject = "App keeps crashing"
    a_custom_cat = "Splash crash"
    a_message = "App crashes immediately after splash on Android 13 device."  # ≥10 chars
    payload_a = {
        "email": a_email,
        "name": a_name,
        "subject": a_subject,
        "category": "other",
        "custom_category": a_custom_cat,
        "message": a_message,
    }
    r = await client.post(f"{BASE}/tickets/public", json=payload_a)
    if r.status_code == 200:
        body = r.json()
        if body.get("ok") is True and body.get("ticket_id"):
            tid_a = body["ticket_id"]
            ok(f"A1 POST /tickets/public 200 ticket_id={tid_a[:8]}…")
            created_guest_ids.append(tid_a)
            try:
                uuid.UUID(tid_a)
                ok("A2 ticket_id is a uuid")
            except ValueError:
                fail("A2 ticket_id is a uuid", f"got={tid_a!r}")

            await asyncio.sleep(0.3)
            t = await db_get("tickets", {"id": tid_a})
            if not t:
                fail("A3 tickets row exists")
            else:
                ok("A3 tickets row exists")
                assert_eq("A4 is_guest", t.get("is_guest"), True)
                assert_eq("A5 guest_email", t.get("guest_email"), a_email)
                assert_eq("A6 guest_name", t.get("guest_name"), a_name)
                assert_eq("A7 guest_custom_category", t.get("guest_custom_category"), a_custom_cat)
                if isinstance(t.get("user_id"), str) and t["user_id"].startswith("guest:"):
                    ok(f"A8 user_id starts with 'guest:' ({t['user_id']})")
                else:
                    fail("A8 user_id starts with 'guest:'", f"got={t.get('user_id')!r}")
                assert_eq("A9 category", t.get("category"), "other")
                assert_eq("A10 subject", t.get("subject"), a_subject)
                assert_eq("A11 status", t.get("status"), "open")
                assert_eq("A12 priority", t.get("priority"), "normal")

            tm = await db_get("ticket_messages", {"ticket_id": tid_a})
            if not tm:
                fail("A13 ticket_messages row exists")
            else:
                ok("A13 ticket_messages row exists")
                assert_eq("A14 message.is_guest", tm.get("is_guest"), True)
                assert_eq("A15 message.sender_type", tm.get("sender_type"), "user")
                assert_eq("A16 message.message", tm.get("message"), a_message)
        else:
            fail("A1 happy path body", f"body={body!r}")
    else:
        fail("A1 POST /tickets/public 200", f"status={r.status_code} body={r.text[:200]}")

    # ── B: STANDARD CATEGORY (withdrawal)
    print("\n[B] Standard category — withdrawal, no custom_category")
    b_email = f"guest-b-{uuid.uuid4().hex[:8]}@example.com"
    payload_b = {
        "email": b_email,
        "category": "withdrawal",
        "message": "I cannot withdraw my payout amount — UPI failed yesterday.",
    }
    r = await client.post(f"{BASE}/tickets/public", json=payload_b)
    if r.status_code == 200 and r.json().get("ticket_id"):
        tid_b = r.json()["ticket_id"]
        ok(f"B1 POST 200 ticket_id={tid_b[:8]}…")
        created_guest_ids.append(tid_b)
        await asyncio.sleep(0.3)
        t = await db_get("tickets", {"id": tid_b})
        if not t:
            fail("B2 tickets row exists")
        else:
            ok("B2 tickets row exists")
            assert_eq("B3 category", t.get("category"), "withdrawal")
            gcc = t.get("guest_custom_category")
            if gcc is None or gcc == "":
                ok(f"B4 guest_custom_category None/missing (got={gcc!r})")
            else:
                fail("B4 guest_custom_category None/missing", f"got={gcc!r}")
    else:
        fail("B1 POST standard category 200", f"status={r.status_code} body={r.text[:200]}")

    # ── C: VALIDATION — each must 400
    print("\n[C] Validation — each must 400")
    val_cases = [
        ("C1 invalid email", {"email": "not-an-email", "category": "other", "message": "This is a valid msg >=10 chars"}),
        ("C2 missing email", {"category": "other", "message": "This is a valid msg >=10 chars"}),
        ("C3 empty email", {"email": "", "category": "other", "message": "This is a valid msg >=10 chars"}),
        ("C4 short message", {"email": "x@x.com", "category": "other", "message": "too short"}),
        ("C5 5001-char message", {"email": "x@x.com", "category": "other", "message": "a" * 5001}),
    ]
    for label, body in val_cases:
        r = await client.post(f"{BASE}/tickets/public", json=body)
        if r.status_code == 400:
            ok(f"{label} → 400")
        else:
            fail(label, f"expected 400, got {r.status_code} body={r.text[:160]}")

    # ── D: RATE LIMIT
    print("\n[D] Rate limit — 5 OK, 6th = 429")
    rl_email = f"rate-{uuid.uuid4().hex[:8]}@example.com"
    rl_payload = {
        "email": rl_email,
        "category": "other",
        "custom_category": "rate test",
        "message": "Rate-limit test message — exceeds ten chars easily.",
    }
    statuses: List[int] = []
    for i in range(6):
        r = await client.post(f"{BASE}/tickets/public", json=rl_payload)
        statuses.append(r.status_code)
        if i < 5 and r.status_code == 200:
            tid = r.json().get("ticket_id")
            if tid:
                created_guest_ids.append(tid)
    print(f"  statuses[0..5] = {statuses}")
    if statuses[:5] == [200, 200, 200, 200, 200]:
        ok("D1 first 5 POSTs all 200")
    else:
        fail("D1 first 5 POSTs all 200", f"got={statuses[:5]}")
    if statuses[5] == 429:
        ok("D2 6th POST → 429")
    else:
        fail("D2 6th POST → 429", f"got={statuses[5]}")

    return created_guest_ids


async def feature1_admin_visibility(
    client: httpx.AsyncClient, admin_tok: str, guest_ids: List[str]
) -> None:
    section("FEATURE 1 — E: Admin visibility of guest tickets")
    headers = {"Authorization": f"Bearer {admin_tok}"}

    r = await client.get(f"{BASE}/admin/tickets", headers=headers)
    if r.status_code != 200:
        fail("E1 GET /admin/tickets 200", f"status={r.status_code} body={r.text[:200]}")
        return
    items = r.json().get("items", []) or []
    ok(f"E1 GET /admin/tickets 200 items={len(items)}")

    items_by_id = {t.get("id"): t for t in items}
    sample = [gid for gid in guest_ids if gid in items_by_id][:2]
    if len(sample) >= 1:
        ok(f"E2 Guest tickets surfaced in admin list ({len(sample)} found of {len(guest_ids)})")
        for s in sample:
            t = items_by_id[s]
            if t.get("is_guest") is True and t.get("guest_email"):
                ok(f"E3 ticket {s[:8]}… is_guest=True, guest_email={t['guest_email']}")
            else:
                fail(
                    f"E3 ticket {s[:8]}… is_guest+guest_email",
                    f"is_guest={t.get('is_guest')} guest_email={t.get('guest_email')!r}",
                )
    else:
        fail(
            "E2 Guest tickets surfaced in admin list",
            f"none of {len(guest_ids)} guest ids appeared in items[]",
        )
        return

    pick = sample[0]
    r = await client.get(f"{BASE}/tickets/{pick}", headers=headers)
    if r.status_code == 200:
        body = r.json()
        if body.get("ticket") and body.get("messages") is not None:
            ok(f"E4 Admin GET /tickets/{pick[:8]}… 200")
        else:
            fail("E4 Admin GET ticket body", f"body keys={list(body.keys())}")
    else:
        fail(f"E4 Admin GET /tickets/{pick[:8]}…", f"status={r.status_code} body={r.text[:200]}")

    r = await client.post(
        f"{BASE}/tickets/{pick}/reply",
        headers=headers,
        json={"message": "Hi — we have received your issue and are looking into it."},
    )
    if r.status_code == 200 and r.json().get("ok") is True:
        ok(f"E5 Admin POST /tickets/{pick[:8]}…/reply 200")
    else:
        fail("E5 Admin POST reply", f"status={r.status_code} body={r.text[:200]}")


# ──────────────────────────────────────────────────────────────────────
# FEATURE 2
# ──────────────────────────────────────────────────────────────────────
PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


async def feature2_splash_image(client: httpx.AsyncClient, admin_tok: str) -> None:
    section("FEATURE 2 — Splash image remove via empty string")
    headers = {"Authorization": f"Bearer {admin_tok}"}

    print("\n[F] SET splash_image first")
    r = await client.put(
        f"{BASE}/admin/branding", headers=headers, json={"splash_image": PNG_DATA_URI}
    )
    if r.status_code != 200:
        fail("F1 PUT /admin/branding {splash_image:<png>}", f"status={r.status_code} body={r.text[:200]}")
        return
    ok("F1 PUT /admin/branding {splash_image:<png>} 200")
    r2 = await client.get(f"{BASE}/branding")
    if r2.status_code == 200 and r2.json().get("splash_image"):
        ok(f"F2 GET /branding has splash_image set (len={len(r2.json()['splash_image'])})")
    else:
        fail("F2 GET /branding has splash_image set", f"status={r2.status_code} body={r2.text[:200]}")
        return

    print("\n[G] CLEAR via empty string")
    r = await client.put(
        f"{BASE}/admin/branding", headers=headers, json={"splash_image": ""}
    )
    if r.status_code == 200:
        ok("G1 PUT /admin/branding {splash_image:''} 200")
    else:
        fail("G1 PUT /admin/branding {splash_image:''} 200", f"status={r.status_code} body={r.text[:200]}")
        return
    r2 = await client.get(f"{BASE}/branding")
    if r2.status_code == 200:
        si = r2.json().get("splash_image", None)
        if si is None or si == "":
            ok(f"G2 GET /branding splash_image cleared (got={si!r})")
        else:
            fail("G2 GET /branding splash_image cleared", f"got={si!r}")
    else:
        fail("G2 GET /branding 200", f"status={r2.status_code}")

    print("\n[H] Backward compat — PUT without splash_image key keeps existing")
    r = await client.put(
        f"{BASE}/admin/branding", headers=headers, json={"splash_image": PNG_DATA_URI}
    )
    if r.status_code != 200:
        fail("H0 setup re-set splash_image", f"status={r.status_code} body={r.text[:200]}")
        return
    r = await client.put(
        f"{BASE}/admin/branding",
        headers=headers,
        json={"tagline": "Track your referrals, earnings and grow your team."},
    )
    if r.status_code != 200:
        fail("H1 PUT {tagline:…} (no splash_image key)", f"status={r.status_code} body={r.text[:200]}")
        return
    ok("H1 PUT {tagline:…} (no splash_image key) 200")
    r2 = await client.get(f"{BASE}/branding")
    if r2.status_code == 200 and r2.json().get("splash_image"):
        ok("H2 GET /branding splash_image preserved")
    else:
        fail(
            "H2 GET /branding splash_image preserved",
            f"si={r2.json().get('splash_image')!r}",
        )

    # cleanup — leave splash cleared
    await client.put(
        f"{BASE}/admin/branding", headers=headers, json={"splash_image": ""}
    )


# ──────────────────────────────────────────────────────────────────────
# FEATURE 3
# ──────────────────────────────────────────────────────────────────────
async def feature3_auth_tickets(client: httpx.AsyncClient, user_tok: str) -> None:
    section("FEATURE 3 — Authenticated ticket regression")
    headers = {"Authorization": f"Bearer {user_tok}"}

    subject = f"Regression check {uuid.uuid4().hex[:6]}"
    body_msg = "Following up on a withdrawal that hasn't landed in my bank yet."
    r = await client.post(
        f"{BASE}/tickets",
        headers=headers,
        json={"subject": subject, "category": "withdrawal", "message": body_msg},
    )
    if r.status_code != 200:
        fail("I1 POST /tickets (auth)", f"status={r.status_code} body={r.text[:200]}")
        return
    body = r.json()
    tid = (body.get("ticket") or {}).get("id")
    if body.get("ok") is True and tid:
        ok(f"I1 POST /tickets (auth) 200 ticket.id={tid[:8]}…")
        assert_eq("I2 ticket.subject", body["ticket"].get("subject"), subject)
    else:
        fail("I1 body shape", f"body={body!r}")
        return

    r = await client.get(f"{BASE}/tickets/me", headers=headers)
    if r.status_code != 200:
        fail("J1 GET /tickets/me", f"status={r.status_code} body={r.text[:200]}")
        return
    items = r.json().get("items", []) or []
    if any(t.get("id") == tid for t in items):
        ok(f"J1 GET /tickets/me 200 — new ticket appears (items={len(items)})")
    else:
        fail("J1 new ticket appears in /tickets/me", f"items={len(items)}")


# ──────────────────────────────────────────────────────────────────────
async def main() -> int:
    print(f"BASE = {BASE}")
    print(f"MONGO = {MONGO_URL}  DB = {DB_NAME}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        admin_tok = await login(client, ADMIN_EMAIL, ADMIN_PASS)
        if not admin_tok:
            print("FATAL: admin login failed — aborting")
            return 2
        print(f"✓ admin logged in (token len={len(admin_tok)})")

        user_tok = await login(client, USER_EMAIL, USER_PASS)
        if not user_tok:
            print(f"!! {USER_EMAIL} login failed — falling back to demo user aarav@demo.app/Demo@123")
            user_tok = await login(client, "aarav@demo.app", "Demo@123")
        if not user_tok:
            print("FATAL: no working test-user credentials — aborting")
            return 2
        print(f"✓ test user logged in (token len={len(user_tok)})")

        guest_ids = await feature1_guest_tickets(client)
        await feature1_admin_visibility(client, admin_tok, guest_ids)
        await feature2_splash_image(client, admin_tok)
        await feature3_auth_tickets(client, user_tok)

    print()
    print("=" * 70)
    print(f"PASS: {len(PASSED)}    FAIL: {len(FAILED)}")
    print("=" * 70)
    if FAILED:
        print("FAILURES:")
        for f in FAILED:
            print(f"  ❌ {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
