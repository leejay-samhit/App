"""
Sprint 1 — WhatsApp-style chat upgrade backend tests.

Covers extended POST /chat/{thread_id}/messages (offensive filter, reply, dedupe,
rate-limit, block), reactions, star, pin, delivered, typing, presence, block
lifecycle, report, search, delete-for-everyone, and the Service-Provider
Start-Chat shortcut.

Test users are created via /api/auth/register and then flipped to
registration_paid=true + approval_status=approved directly in Mongo so the
ordinary chat endpoints don't gate them out.
"""
from __future__ import annotations

import os
import time
import uuid
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Reuse env loading from sibling conftest.py.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe_env = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe_env.exists():
    load_dotenv(_fe_env, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

RUN_TAG = f"sprint1-{int(time.time())}-{uuid.uuid4().hex[:6]}"


# ---------- Mongo helpers (sync inside async wrappers via asyncio.run) ----------

def _mongo():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


async def _approve_user_async(email: str):
    db = _mongo()
    await db.users.update_one(
        {"email": email.lower()},
        {"$set": {
            "registration_paid": True,
            "approval_status": "approved",
            "status": "approved",
        }},
    )


async def _seed_reveal_invoice_async(customer_id: str, provider_id: str):
    db = _mongo()
    await db.phone_reveal_invoices.insert_one({
        "id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "provider_id": provider_id,
        "status": "paid",
        "created_at": datetime.now(timezone.utc),
        "TEST_TAG": RUN_TAG,
    })


async def _set_user_service_provider_async(user_id: str):
    db = _mongo()
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"is_service_provider": True, "service_status": "approved"}},
    )


async def _backdate_message_async(msg_id: str, hours: int):
    db = _mongo()
    new_dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    await db.chat_messages.update_one({"id": msg_id}, {"$set": {"created_at": new_dt}})


async def _cleanup_async(emails):
    db = _mongo()
    users = await db.users.find({"email": {"$in": [e.lower() for e in emails]}}).to_list(50)
    uids = [u["id"] for u in users]
    if uids:
        threads = await db.chat_threads.find({"participants": {"$in": uids}}).to_list(200)
        tids = [t["id"] for t in threads]
        if tids:
            await db.chat_messages.delete_many({"thread_id": {"$in": tids}})
            await db.chat_threads.delete_many({"id": {"$in": tids}})
        await db.chat_blocks.delete_many({"$or": [
            {"blocker_id": {"$in": uids}}, {"blocked_id": {"$in": uids}},
        ]})
        await db.chat_reports.delete_many({"$or": [
            {"reporter_id": {"$in": uids}}, {"target_user_id": {"$in": uids}},
        ]})
        await db.phone_reveal_invoices.delete_many({"TEST_TAG": RUN_TAG})
        await db.chat_requests.delete_many({"$or": [
            {"from_user_id": {"$in": uids}}, {"to_user_id": {"$in": uids}},
        ]})
        await db.users.delete_many({"id": {"$in": uids}})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------- Auth helpers ----------

def _register(email: str, name: str, password: str = "Password@123"):
    r = requests.post(f"{BASE_URL}/api/auth/register", json={
        "email": email, "name": name, "password": password, "phone": "9999999999",
    })
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- Session fixture: two participants + a thread ----------

@pytest.fixture(scope="module")
def participants():
    """Create userA + userB, approve them, seed a thread, return their ctx."""
    emails = [
        f"TEST_chatA_{RUN_TAG}@example.com",
        f"TEST_chatB_{RUN_TAG}@example.com",
        f"TEST_chatC_{RUN_TAG}@example.com",  # non-participant
    ]
    tokA, userA = _register(emails[0], "TEST ChatA")
    tokB, userB = _register(emails[1], "TEST ChatB")
    tokC, userC = _register(emails[2], "TEST ChatC")

    # Flip registration_paid + approved on all three
    for e in emails:
        _run(_approve_user_async(e))

    # Create a thread between A and B by seeding directly.
    parts = sorted([userA["id"], userB["id"]])
    thread_id = str(uuid.uuid4())

    async def _seed_thread():
        db = _mongo()
        await db.chat_threads.insert_one({
            "id": thread_id,
            "participants": parts,
            "created_at": datetime.now(timezone.utc),
            "last_message_at": datetime.now(timezone.utc),
        })
    _run(_seed_thread())

    # Re-login so tokens reflect latest session (registration tokens are
    # still valid since we only set active_session_id during register).
    yield {
        "A": {"tok": tokA, "user": userA},
        "B": {"tok": tokB, "user": userB},
        "C": {"tok": tokC, "user": userC},
        "thread_id": thread_id,
        "emails": emails,
    }
    # Cleanup
    _run(_cleanup_async(emails))


# ============================================================================
# 1. POST /api/chat/{thread_id}/messages — extended body
# ============================================================================

class TestPostMessage:
    def test_offensive_word_blocked(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "this is shit"},
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code} {r.text}"
        assert "not allowed" in r.text.lower() or "language" in r.text.lower()

    def test_reply_quote(self, participants):
        p = participants
        # First send a base message
        r1 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "Hello, this is the original message that will be quoted"},
        )
        assert r1.status_code == 200, r1.text
        orig = r1.json()
        # Now reply to it
        r2 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["B"]["tok"]),
            json={"text": "Replying!", "reply_to_id": orig["id"]},
        )
        assert r2.status_code == 200, r2.text
        m2 = r2.json()
        assert m2.get("reply_to") is not None, f"reply_to missing: {m2}"
        rq = m2["reply_to"]
        assert rq["id"] == orig["id"]
        assert rq["sender_id"] == p["A"]["user"]["id"]
        assert rq["text"].startswith("Hello, this is the original")
        assert len(rq["text"]) <= 160
        assert rq["has_image"] is False
        # stash reply target for later
        participants["_reply_orig_id"] = orig["id"]
        participants["_msg_from_A"] = orig["id"]

    def test_dedupe_returns_same_doc(self, participants):
        p = participants
        key = f"dedupe-{uuid.uuid4().hex}"
        r1 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "dedupe test 1", "client_dedupe_key": key},
        )
        assert r1.status_code == 200, r1.text
        m1 = r1.json()
        # Same key again within 30s -> same doc
        r2 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "dedupe test 1 (should NOT insert)", "client_dedupe_key": key},
        )
        assert r2.status_code == 200, r2.text
        m2 = r2.json()
        assert m1["id"] == m2["id"], f"dedupe failed: {m1['id']} vs {m2['id']}"
        # Different key -> new doc
        r3 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "dedupe test 2", "client_dedupe_key": f"other-{uuid.uuid4().hex}"},
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["id"] != m1["id"]

    def test_rate_limit_31st_message(self, participants):
        p = participants
        # We've already posted some messages above. To avoid coupling, create
        # an isolated thread for this test (admin-seeded between B and C).
        thread_id = str(uuid.uuid4())

        async def _seed():
            db = _mongo()
            await db.chat_threads.insert_one({
                "id": thread_id,
                "participants": sorted([p["B"]["user"]["id"], p["C"]["user"]["id"]]),
                "created_at": datetime.now(timezone.utc),
                "last_message_at": datetime.now(timezone.utc),
            })
        _run(_seed())

        status_codes = []
        for i in range(31):
            r = requests.post(
                f"{BASE_URL}/api/chat/{thread_id}/messages",
                headers=_hdr(p["B"]["tok"]),
                json={"text": f"rl-{i}"},
            )
            status_codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in status_codes, f"expected 429 within 31 sends, got {status_codes}"
        # And it should be on the 31st (index 30)
        idx = status_codes.index(429)
        assert idx == 30, f"expected 429 at attempt 31, got it at {idx + 1}"

    def test_block_prevents_both_sides(self, participants):
        p = participants
        # A blocks B
        rb = requests.post(
            f"{BASE_URL}/api/chat/block/{p['B']['user']['id']}",
            headers=_hdr(p["A"]["tok"]),
        )
        assert rb.status_code == 200, rb.text
        # A → cannot send
        r1 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "blocked from A?"},
        )
        assert r1.status_code == 403, f"A→B should be 403, got {r1.status_code} {r1.text}"
        # B → cannot send either (symmetric)
        r2 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["B"]["tok"]),
            json={"text": "blocked from B?"},
        )
        assert r2.status_code == 403, f"B→A should be 403, got {r2.status_code} {r2.text}"
        # Cleanup: unblock so later tests can post
        ru = requests.delete(
            f"{BASE_URL}/api/chat/block/{p['B']['user']['id']}",
            headers=_hdr(p["A"]["tok"]),
        )
        assert ru.status_code == 200, ru.text


# ============================================================================
# 2. POST /api/chat/messages/{msg_id}/react
# ============================================================================

class TestReactions:
    def _send_msg(self, p, sender="A", text="react target"):
        r = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p[sender]["tok"]),
            json={"text": text},
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_react_add_toggle_replace(self, participants):
        p = participants
        m = self._send_msg(p, sender="A", text="react me")
        # A reacts with thumbs up
        r1 = requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/react",
            headers=_hdr(p["A"]["tok"]),
            json={"emoji": "👍"},
        )
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["reactions"].get("👍") == [p["A"]["user"]["id"]], d1
        # Same emoji again from same user -> removed
        r2 = requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/react",
            headers=_hdr(p["A"]["tok"]),
            json={"emoji": "👍"},
        )
        assert r2.status_code == 200, r2.text
        assert "👍" not in r2.json()["reactions"], r2.json()
        # Add 👍 again
        requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/react",
            headers=_hdr(p["A"]["tok"]),
            json={"emoji": "👍"},
        )
        # Now react with different emoji from same user -> replaces
        r3 = requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/react",
            headers=_hdr(p["A"]["tok"]),
            json={"emoji": "❤️"},
        )
        assert r3.status_code == 200, r3.text
        reacts = r3.json()["reactions"]
        assert "👍" not in reacts, f"old emoji should be replaced: {reacts}"
        assert reacts.get("❤️") == [p["A"]["user"]["id"]], reacts

    def test_non_participant_cannot_react(self, participants):
        p = participants
        m = self._send_msg(p, sender="A", text="non-part react")
        r = requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/react",
            headers=_hdr(p["C"]["tok"]),
            json={"emoji": "👍"},
        )
        assert r.status_code in (403, 404), f"non-participant should be denied, got {r.status_code} {r.text}"


# ============================================================================
# 3. POST /api/chat/messages/{msg_id}/star + GET /api/chat/starred
# ============================================================================

class TestStar:
    def test_star_toggle_and_list(self, participants):
        p = participants
        # Send a message
        r0 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "star me please"},
        )
        assert r0.status_code == 200, r0.text
        m = r0.json()
        # Star
        r1 = requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/star",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["starred"] is True
        # GET starred returns it
        r2 = requests.get(f"{BASE_URL}/api/chat/starred", headers=_hdr(p["A"]["tok"]))
        assert r2.status_code == 200, r2.text
        ids = [x["id"] for x in r2.json()["messages"]]
        assert m["id"] in ids
        # Toggle off
        r3 = requests.post(
            f"{BASE_URL}/api/chat/messages/{m['id']}/star",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r3.json()["starred"] is False


# ============================================================================
# 4. POST /api/chat/threads/{thread_id}/pin
# ============================================================================

class TestPin:
    def test_pin_toggle(self, participants):
        p = participants
        r1 = requests.post(
            f"{BASE_URL}/api/chat/threads/{p['thread_id']}/pin",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["pinned"] is True
        r2 = requests.post(
            f"{BASE_URL}/api/chat/threads/{p['thread_id']}/pin",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r2.json()["pinned"] is False

    def test_non_participant_pin_denied(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/threads/{p['thread_id']}/pin",
            headers=_hdr(p["C"]["tok"]),
        )
        # _assert_thread_member raises 404 (not 403). Either is acceptable
        # as a "denied" result.
        assert r.status_code in (403, 404), f"expected denied, got {r.status_code}"


# ============================================================================
# 5. POST /api/chat/{thread_id}/delivered
# ============================================================================

class TestDelivered:
    def test_mark_delivered_increments(self, participants):
        p = participants
        # Use a fresh thread to keep counts deterministic
        thread_id = str(uuid.uuid4())

        async def _seed():
            db = _mongo()
            await db.chat_threads.insert_one({
                "id": thread_id,
                "participants": sorted([p["A"]["user"]["id"], p["B"]["user"]["id"]]),
                "created_at": datetime.now(timezone.utc),
                "last_message_at": datetime.now(timezone.utc),
            })
        _run(_seed())

        # A sends 3 messages
        for i in range(3):
            r = requests.post(
                f"{BASE_URL}/api/chat/{thread_id}/messages",
                headers=_hdr(p["A"]["tok"]),
                json={"text": f"delivered-test-{i}"},
            )
            assert r.status_code == 200, r.text
        # B marks delivered
        r = requests.post(
            f"{BASE_URL}/api/chat/{thread_id}/delivered",
            headers=_hdr(p["B"]["tok"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["count"] == 3, f"expected 3, got {body}"


# ============================================================================
# 6. POST /api/chat/{thread_id}/typing
# ============================================================================

class TestTyping:
    def test_typing_ok(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/typing",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True


# ============================================================================
# 7. GET /api/chat/{thread_id}/presence
# ============================================================================

class TestPresence:
    def test_presence_offline(self, participants):
        p = participants
        r = requests.get(
            f"{BASE_URL}/api/chat/{p['thread_id']}/presence",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["online"] is False
        # last_seen can be None or an ISO string
        ls = body["last_seen"]
        assert ls is None or isinstance(ls, str)


# ============================================================================
# 8. POST /DELETE /GET /api/chat/block/...
# ============================================================================

class TestBlockLifecycle:
    def test_self_block_400(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/block/{p['A']['user']['id']}",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r.status_code == 400, r.text

    def test_block_list_unblock(self, participants):
        p = participants
        # Block C from A
        r1 = requests.post(
            f"{BASE_URL}/api/chat/block/{p['C']['user']['id']}",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r1.status_code == 200
        # GET blocks
        r2 = requests.get(f"{BASE_URL}/api/chat/blocks", headers=_hdr(p["A"]["tok"]))
        assert r2.status_code == 200
        ids = [b["blocked_id"] for b in r2.json()["blocks"]]
        assert p["C"]["user"]["id"] in ids
        # Unblock
        r3 = requests.delete(
            f"{BASE_URL}/api/chat/block/{p['C']['user']['id']}",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r3.status_code == 200
        r4 = requests.get(f"{BASE_URL}/api/chat/blocks", headers=_hdr(p["A"]["tok"]))
        ids2 = [b["blocked_id"] for b in r4.json()["blocks"]]
        assert p["C"]["user"]["id"] not in ids2


# ============================================================================
# 9. POST /api/chat/report
# ============================================================================

class TestReport:
    def test_self_report_400(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/report",
            headers=_hdr(p["A"]["tok"]),
            json={"target_user_id": p["A"]["user"]["id"], "reason": "x"},
        )
        assert r.status_code == 400, r.text

    def test_report_creates_open_row(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/report",
            headers=_hdr(p["A"]["tok"]),
            json={"target_user_id": p["B"]["user"]["id"], "reason": "spam"},
        )
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["status"] == "open"
        assert doc["target_user_id"] == p["B"]["user"]["id"]
        assert doc["reporter_id"] == p["A"]["user"]["id"]


# ============================================================================
# 10. GET /api/chat/search/messages
# ============================================================================

class TestSearch:
    def test_search_thread_scoped(self, participants):
        p = participants
        # Send a unique-keyword message
        keyword = f"PIZZADELIGHT{uuid.uuid4().hex[:6]}"
        r0 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": f"I love {keyword} so much"},
        )
        assert r0.status_code == 200, r0.text
        # Search within thread
        r1 = requests.get(
            f"{BASE_URL}/api/chat/search/messages",
            params={"q": keyword, "thread_id": p["thread_id"]},
            headers=_hdr(p["A"]["tok"]),
        )
        assert r1.status_code == 200, r1.text
        msgs = r1.json()["messages"]
        assert len(msgs) >= 1
        assert any(keyword.lower() in (m.get("text") or "").lower() for m in msgs)
        # Global search across my threads
        r2 = requests.get(
            f"{BASE_URL}/api/chat/search/messages",
            params={"q": keyword},
            headers=_hdr(p["A"]["tok"]),
        )
        assert r2.status_code == 200
        assert len(r2.json()["messages"]) >= 1

    def test_search_excludes_deleted_for_everyone(self, participants):
        p = participants
        keyword = f"SECRETMSG{uuid.uuid4().hex[:6]}"
        r0 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": f"hide me {keyword}"},
        )
        assert r0.status_code == 200, r0.text
        msg = r0.json()
        # Delete for everyone
        rd = requests.delete(
            f"{BASE_URL}/api/chat/messages/{msg['id']}/for-everyone",
            headers=_hdr(p["A"]["tok"]),
        )
        assert rd.status_code == 200, rd.text
        rs = requests.get(
            f"{BASE_URL}/api/chat/search/messages",
            params={"q": keyword},
            headers=_hdr(p["A"]["tok"]),
        )
        assert rs.status_code == 200
        assert len(rs.json()["messages"]) == 0


# ============================================================================
# 11. DELETE /api/chat/messages/{msg_id}/for-everyone
# ============================================================================

class TestDeleteForEveryone:
    def test_non_sender_403(self, participants):
        p = participants
        r0 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "I sent this"},
        )
        assert r0.status_code == 200
        mid = r0.json()["id"]
        r = requests.delete(
            f"{BASE_URL}/api/chat/messages/{mid}/for-everyone",
            headers=_hdr(p["B"]["tok"]),
        )
        assert r.status_code == 403, r.text

    def test_sender_within_window_clears_text(self, participants):
        p = participants
        r0 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "deleteable", "image_data_url": ""},
        )
        assert r0.status_code == 200
        mid = r0.json()["id"]
        rd = requests.delete(
            f"{BASE_URL}/api/chat/messages/{mid}/for-everyone",
            headers=_hdr(p["A"]["tok"]),
        )
        assert rd.status_code == 200
        # Verify text cleared in Mongo
        async def _check():
            db = _mongo()
            m = await db.chat_messages.find_one({"id": mid})
            return m
        m = _run(_check())
        assert m["deleted_for_everyone"] is True
        assert m["text"] == ""
        assert m["image_data_url"] == ""

    def test_after_1hr_400(self, participants):
        p = participants
        r0 = requests.post(
            f"{BASE_URL}/api/chat/{p['thread_id']}/messages",
            headers=_hdr(p["A"]["tok"]),
            json={"text": "old message"},
        )
        assert r0.status_code == 200
        mid = r0.json()["id"]
        # backdate 2 hours
        _run(_backdate_message_async(mid, hours=2))
        r = requests.delete(
            f"{BASE_URL}/api/chat/messages/{mid}/for-everyone",
            headers=_hdr(p["A"]["tok"]),
        )
        assert r.status_code == 400, r.text


# ============================================================================
# 12. POST /api/chat/threads — Service-Provider Start-Chat shortcut
# ============================================================================

class TestStartThreadShortcut:
    def test_self_start_400(self, participants):
        p = participants
        r = requests.post(
            f"{BASE_URL}/api/chat/threads",
            headers=_hdr(p["A"]["tok"]),
            json={"other_user_id": p["A"]["user"]["id"]},
        )
        assert r.status_code == 400, r.text

    def test_non_provider_no_thread_403(self, participants):
        p = participants
        # Register a fresh 4th user D so no thread exists between A↔D.
        email_d = f"TEST_chatD_{RUN_TAG}-{uuid.uuid4().hex[:6]}@example.com"
        tokD, userD = _register(email_d, "TEST ChatD")
        _run(_approve_user_async(email_d))
        participants["emails"].append(email_d)  # ensure cleanup
        # A → D: D is NOT a provider, no thread, no request — must 403
        r = requests.post(
            f"{BASE_URL}/api/chat/threads",
            headers=_hdr(p["A"]["tok"]),
            json={"other_user_id": userD["id"]},
        )
        assert r.status_code == 403, r.text
        assert "chat request" in r.text.lower()

    def test_provider_without_reveal_403(self, participants):
        p = participants
        # Flip C to be a service provider
        _run(_set_user_service_provider_async(p["C"]["user"]["id"]))
        # A has no reveal invoice for C → 403
        r = requests.post(
            f"{BASE_URL}/api/chat/threads",
            headers=_hdr(p["A"]["tok"]),
            json={"other_user_id": p["C"]["user"]["id"]},
        )
        assert r.status_code == 403, r.text
        assert "reveal" in r.text.lower()

    def test_provider_with_reveal_creates_thread(self, participants):
        p = participants
        # Ensure C is provider
        _run(_set_user_service_provider_async(p["C"]["user"]["id"]))
        # Seed invoice A->C
        _run(_seed_reveal_invoice_async(p["A"]["user"]["id"], p["C"]["user"]["id"]))
        r = requests.post(
            f"{BASE_URL}/api/chat/threads",
            headers=_hdr(p["A"]["tok"]),
            json={"other_user_id": p["C"]["user"]["id"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "id" in body
        assert sorted([p["A"]["user"]["id"], p["C"]["user"]["id"]]) == body["participants"]
