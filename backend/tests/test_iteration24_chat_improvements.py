"""
Iteration 24 — Backend verification for the 6 chat-UX improvements.

Targets:
  • Biometric toggle persistence via POST /api/chat/lock/setup + /change
  • Per-user "scope=me"  clear via DELETE /api/chat/{thread_id}/messages?scope=me
  • Bilateral "scope=everyone" clear (+ WS thread.cleared broadcast)
  • GET /api/chat/{thread_id}/media still works
  • GET /api/chat/starred still works
"""
import os
import time
import json
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://vendor-network-app-1.preview.emergentagent.com").rstrip("/")

ALICE_EMAIL = "test_alice_73dc7f@test.com"
BOB_EMAIL   = "test_bob_d96d89@test.com"
PASSWORD    = "Passw0rd!"
THREAD_ID   = "4f3c5028-706f-43fa-a57b-494b13787718"
PIN         = "1234"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    assert token, f"no token in login response: {body}"
    return token


@pytest.fixture(scope="module")
def alice_token() -> str:
    return _login(ALICE_EMAIL, PASSWORD)


@pytest.fixture(scope="module")
def bob_token() -> str:
    return _login(BOB_EMAIL, PASSWORD)


def _h(t: str):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


# ─── 0. Reset Alice lock state (idempotent cleanup) ─────────────────────
@pytest.fixture(scope="module", autouse=True)
def _reset_alice_lock(alice_token):
    """Ensure Alice has a clean PIN setup of 1234 before tests run."""
    # Try disable (may 400 if already disabled — that's fine)
    requests.post(f"{BASE_URL}/api/chat/lock/disable",
                  headers=_h(alice_token), json={"pin": PIN}, timeout=15)
    # Setup PIN 1234 (may 400 if already set — disable first failed, try alt PIN drain)
    r = requests.post(f"{BASE_URL}/api/chat/lock/setup",
                      headers=_h(alice_token), json={"pin": PIN}, timeout=15)
    # Ignore 400 if already set up — assert via GET below
    s = requests.get(f"{BASE_URL}/api/chat/settings", headers=_h(alice_token), timeout=15)
    assert s.status_code == 200
    body = s.json()
    assert body.get("has_pin") is True, f"Alice PIN setup failed: {body}"


# ─── 1. Biometric toggle ────────────────────────────────────────────────
class TestBiometricToggle:
    """POST /api/chat/lock/change with use_biometric=true must flip + persist."""

    def test_change_pin_with_biometric_flag(self, alice_token):
        r = requests.post(
            f"{BASE_URL}/api/chat/lock/change",
            headers=_h(alice_token),
            json={"old_pin": PIN, "new_pin": PIN, "use_biometric": True},
            timeout=15,
        )
        assert r.status_code == 200, f"lock/change failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body.get("has_pin") is True
        assert body.get("use_biometric") is True

    def test_settings_reflects_biometric(self, alice_token):
        r = requests.get(f"{BASE_URL}/api/chat/settings", headers=_h(alice_token), timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("has_pin") is True
        assert body.get("use_biometric") is True


# ─── Helper: post a batch of messages ───────────────────────────────────
def _post_text(token: str, thread_id: str, text: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/chat/{thread_id}/messages",
        headers=_h(token),
        json={"text": text},
        timeout=15,
    )
    assert r.status_code == 200, f"post message failed: {r.status_code} {r.text[:200]}"
    return r.json()


def _post_image(token: str, thread_id: str) -> dict:
    # tiny 1x1 transparent PNG as data URL
    tiny_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    r = requests.post(
        f"{BASE_URL}/api/chat/{thread_id}/messages",
        headers=_h(token),
        json={"image_data_url": tiny_png, "text": ""},
        timeout=30,
    )
    assert r.status_code == 200, f"post image failed: {r.status_code} {r.text[:200]}"
    return r.json()


# ─── 2. DELETE thread messages scope=me ─────────────────────────────────
class TestClearForMe:
    """Alice clears for herself only — Bob still sees everything."""

    tag = uuid.uuid4().hex[:8]

    def test_seed_messages_and_clear_for_me(self, alice_token, bob_token):
        # 1) Seed messages from BOTH sides (Bob's so Alice can't 'delete' them
        #    on the wire — only HIDE for self)
        m1 = _post_text(bob_token, THREAD_ID, f"TEST_{self.tag} from-bob-1")
        m2 = _post_text(alice_token, THREAD_ID, f"TEST_{self.tag} from-alice-1")
        m3 = _post_text(bob_token, THREAD_ID, f"TEST_{self.tag} from-bob-2")
        # seed an image so media_count is non-zero
        img = _post_image(bob_token, THREAD_ID)
        # star the alice message from alice → starred_by contains alice
        sr = requests.post(
            f"{BASE_URL}/api/chat/messages/{m2['id']}/star",
            headers=_h(alice_token), timeout=15,
        )
        assert sr.status_code == 200

        # Confirm seed visible to alice
        a_list = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/messages",
                              headers=_h(alice_token), timeout=15).json()["messages"]
        seed_ids = {m1["id"], m2["id"], m3["id"], img["id"]}
        a_ids = {m["id"] for m in a_list}
        assert seed_ids.issubset(a_ids), f"seed not visible to Alice: missing {seed_ids - a_ids}"

        # 2) Pre-clear details
        det_pre_a = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/details",
                                 headers=_h(alice_token), timeout=15).json()
        det_pre_b = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/details",
                                 headers=_h(bob_token), timeout=15).json()
        assert det_pre_a["media_count"] >= 1
        assert det_pre_a["starred_count"] >= 1

        # 3) Alice clears for self
        r = requests.delete(
            f"{BASE_URL}/api/chat/{THREAD_ID}/messages?scope=me",
            headers=_h(alice_token), timeout=15,
        )
        assert r.status_code == 200, f"clear me failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True and body.get("scope") == "me"

        # 4) Alice list = empty, Bob list still has seed
        a2 = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/messages",
                          headers=_h(alice_token), timeout=15).json()["messages"]
        b2 = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/messages",
                          headers=_h(bob_token), timeout=15).json()["messages"]
        a2_ids = {m["id"] for m in a2}
        b2_ids = {m["id"] for m in b2}
        assert not (seed_ids & a2_ids), f"Alice still sees cleared msgs: {seed_ids & a2_ids}"
        assert seed_ids.issubset(b2_ids), f"Bob is missing msgs after Alice scope=me: {seed_ids - b2_ids}"

        # 5) Details: alice's counts drop, Bob's unchanged
        det_a = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/details",
                             headers=_h(alice_token), timeout=15).json()
        det_b = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/details",
                             headers=_h(bob_token), timeout=15).json()
        assert det_a["media_count"] == 0, f"alice media_count not 0: {det_a}"
        assert det_a["starred_count"] == 0, f"alice starred_count not 0: {det_a}"
        # Bob's media count must still be >= pre-clear (≥1)
        assert det_b["media_count"] >= det_pre_b["media_count"], \
            f"Bob media_count regressed: pre={det_pre_b['media_count']} post={det_b['media_count']}"


# ─── 3. DELETE thread messages scope=everyone + 4 + 5 ────────────────────
class TestClearForEveryoneAndMediaStarred:
    tag = uuid.uuid4().hex[:8]

    def test_seed_and_clear_everyone(self, alice_token, bob_token):
        # 1) Seed three messages (text + image) from both sides
        m1 = _post_text(alice_token, THREAD_ID, f"TEST_{self.tag} a1")
        m2 = _post_text(bob_token,   THREAD_ID, f"TEST_{self.tag} b1")
        img = _post_image(alice_token, THREAD_ID)
        # star one
        sr = requests.post(f"{BASE_URL}/api/chat/messages/{m1['id']}/star",
                           headers=_h(bob_token), timeout=15)
        assert sr.status_code == 200

        # — Test 4 PRE: media endpoint works and has rows for both
        a_med_pre = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/media",
                                 headers=_h(alice_token), timeout=15)
        assert a_med_pre.status_code == 200
        assert any(m["id"] == img["id"] for m in a_med_pre.json()["messages"]), \
            "freshly-posted image not in /media for Alice"

        # — Test 5 PRE: /chat/starred returns starred messages for Bob
        b_st_pre = requests.get(f"{BASE_URL}/api/chat/starred",
                                headers=_h(bob_token), timeout=15)
        assert b_st_pre.status_code == 200
        starred_pre_ids = {m["id"] for m in b_st_pre.json()["messages"]}
        assert m1["id"] in starred_pre_ids, "starred message not present for Bob pre-clear"

        # 2) Alice clears for everyone
        r = requests.delete(
            f"{BASE_URL}/api/chat/{THREAD_ID}/messages?scope=everyone",
            headers=_h(alice_token), timeout=15,
        )
        assert r.status_code == 200, f"clear everyone failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True and body.get("scope") == "everyone"

        # 3) BOTH sides: messages list either empty or every msg is deleted_for_everyone=True
        for name, tok in (("alice", alice_token), ("bob", bob_token)):
            lst = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/messages",
                               headers=_h(tok), timeout=15).json()["messages"]
            # The seed msgs MUST be present-but-tombstoned OR absent (alice has hidden_for_users from prior test)
            for sid in (m1["id"], m2["id"], img["id"]):
                row = next((m for m in lst if m["id"] == sid), None)
                if row is not None:  # if visible, must be deleted_for_everyone
                    assert row.get("deleted_for_everyone") is True, \
                        f"{name} sees {sid} but deleted_for_everyone is not True: {row}"

        # 4) /media returns empty for BOTH after everyone-clear
        for name, tok in (("alice", alice_token), ("bob", bob_token)):
            mr = requests.get(f"{BASE_URL}/api/chat/{THREAD_ID}/media",
                              headers=_h(tok), timeout=15)
            assert mr.status_code == 200
            assert mr.json()["messages"] == [], \
                f"{name} still sees media after scope=everyone: {mr.json()}"

        # 5) /chat/starred no longer returns the wiped message (for Bob)
        sr2 = requests.get(f"{BASE_URL}/api/chat/starred",
                           headers=_h(bob_token), timeout=15)
        assert sr2.status_code == 200
        post_ids = {m["id"] for m in sr2.json()["messages"]}
        assert m1["id"] not in post_ids, \
            f"starred message survived scope=everyone for Bob: {post_ids}"


# ─── 6. Sanity: scope param validation ─────────────────────────────────
class TestClearScopeValidation:
    def test_invalid_scope(self, alice_token):
        r = requests.delete(
            f"{BASE_URL}/api/chat/{THREAD_ID}/messages?scope=bogus",
            headers=_h(alice_token), timeout=15,
        )
        assert r.status_code == 400


# ─── 7. Final cleanup — restore biometric=false to keep state tidy ─────
class TestZZZCleanup:
    def test_restore_biometric_false(self, alice_token):
        r = requests.post(
            f"{BASE_URL}/api/chat/lock/change",
            headers=_h(alice_token),
            json={"old_pin": PIN, "new_pin": PIN, "use_biometric": False},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("use_biometric") is False
