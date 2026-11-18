"""Iteration 13 — Push Notifications + Super Admin Broadcast.

Covers:
  - POST /api/register-push       (auth + JWT/user mismatch guard + deferred status)
  - POST /api/push/test           (super_admin gating)
  - POST /api/admin/broadcasts    (super_admin gating + audience selectors)
  - GET  /api/admin/broadcasts    (sorted desc)
  - Announcement thread surfacing in /api/chat/threads
  - Announcement post guard (403 for non-super-admin)
  - GET  /api/chat/{tid}/details exposes is_announcement
  - Regression: normal chat flow still works while push relay fails silently
  - Regression: /api/branding, /api/users/me/privacy still 200
"""
from __future__ import annotations

import os
import time
import uuid
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
_fe = Path(__file__).resolve().parents[2] / "frontend" / ".env"
if _fe.exists():
    load_dotenv(_fe, override=False)

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "support@networkrupay.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", ""))


def _h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def admin_token(s):
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def two_users(s, admin_token):
    """Register + approve two non-admin users for chat regression + audience.

    Returns dict {alice:{id,token,refcode}, bob:{...}}.
    """
    out = {}
    for who in ("alice", "bob"):
        email = f"TEST_{who}_{uuid.uuid4().hex[:6]}@test.com"
        body = {
            "email": email,
            "password": "Passw0rd!",
            "name": who.title(),
            "phone": f"99999{uuid.uuid4().int % 100000:05d}",
            "referral_code": "EARN",  # super_admin's referral code
        }
        r = s.post(f"{BASE_URL}/api/auth/register", json=body)
        assert r.status_code in (200, 201), f"register {who}: {r.status_code} {r.text}"
        data = r.json()
        uid = data["user"]["id"]
        tok = data["token"]

        # Approve via super_admin so they qualify for audience selection in
        # case the broadcast filter ever consults approval_status. (Some
        # endpoints additionally require approval_status='approved' anyway.)
        ar = s.post(f"{BASE_URL}/api/admin/approvals/{uid}/approve",
                    headers=_h(admin_token))
        assert ar.status_code == 200, f"approve {who}: {ar.status_code} {ar.text}"

        # Re-fetch user via login to pick up fresh refcode/approval flags.
        lg = s.post(f"{BASE_URL}/api/auth/login",
                    json={"email": email, "password": "Passw0rd!"})
        assert lg.status_code == 200, lg.text
        d2 = lg.json()
        out[who] = {
            "id": uid,
            "email": email,
            "token": d2["token"],
            "refcode": d2["user"].get("referral_code"),
        }
    return out


# ────────────────────────────── /register-push ──────────────────────────────

class TestRegisterPush:
    def test_unauth_rejected(self, s):
        r = s.post(f"{BASE_URL}/api/register-push",
                   json={"user_id": "x", "platform": "android", "device_token": "t"})
        assert r.status_code in (401, 403), r.text

    def test_mismatch_user_id_forbidden(self, s, two_users):
        alice = two_users["alice"]
        r = s.post(f"{BASE_URL}/api/register-push",
                   headers=_h(alice["token"]),
                   json={"user_id": "someone-else", "platform": "android",
                         "device_token": "dev-abc"})
        assert r.status_code == 403, r.text
        assert "mismatch" in (r.json().get("detail") or "").lower()

    def test_valid_register_returns_deferred_or_registered(self, s, two_users):
        alice = two_users["alice"]
        r = s.post(f"{BASE_URL}/api/register-push",
                   headers=_h(alice["token"]),
                   json={"user_id": alice["id"], "platform": "android",
                         "device_token": f"tok-{uuid.uuid4().hex}"})
        # 201 on first create; either status acceptable per spec.
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("status") in ("registered", "deferred"), body


# ───────────────────────────────  /push/test  ────────────────────────────────

class TestPushTest:
    def test_unauth_rejected(self, s):
        r = s.post(f"{BASE_URL}/api/push/test", json={})
        assert r.status_code in (401, 403), r.text

    def test_non_admin_rejected(self, s, two_users):
        r = s.post(f"{BASE_URL}/api/push/test",
                   headers=_h(two_users["alice"]["token"]),
                   json={})
        assert r.status_code == 403, r.text

    def test_super_admin_ok(self, s, admin_token):
        r = s.post(f"{BASE_URL}/api/push/test",
                   headers=_h(admin_token),
                   json={"title": "Smoke", "message": "Hello"})
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True


# ──────────────────────────  /admin/broadcasts  ──────────────────────────────

class TestBroadcasts:
    def test_super_admin_required(self, s, two_users):
        r = s.post(f"{BASE_URL}/api/admin/broadcasts",
                   headers=_h(two_users["alice"]["token"]),
                   json={"title": "x", "message": "y", "audience": "all"})
        assert r.status_code == 403, r.text

    def test_list_super_admin_required(self, s, two_users):
        r = s.get(f"{BASE_URL}/api/admin/broadcasts",
                  headers=_h(two_users["alice"]["token"]))
        assert r.status_code == 403, r.text

    def test_create_all_audience_and_list_sorted(self, s, admin_token, two_users):
        title = f"TEST Broadcast {uuid.uuid4().hex[:6]}"
        msg = "This is an automated test announcement."
        r = s.post(f"{BASE_URL}/api/admin/broadcasts",
                   headers=_h(admin_token),
                   json={"title": title, "message": msg, "audience": "all"})
        # Spec: 201 with broadcast doc OR a documented 400 if there are no
        # users in the audience. Surface both for visibility but assert the
        # happy-path because we just approved two users above.
        if r.status_code == 400:
            pytest.fail(
                f"Broadcast audience='all' returned 400 even after approving "
                f"two non-admin users. Check whether the audience filter "
                f"uses 'status' or 'approval_status'. Response: {r.text}"
            )
        assert r.status_code == 201, r.text
        doc = r.json()
        assert doc.get("id") and doc.get("title") == title
        assert doc.get("recipient_count", 0) >= 2, doc
        bid = doc["id"]

        # List endpoint — newest first.
        lr = s.get(f"{BASE_URL}/api/admin/broadcasts", headers=_h(admin_token))
        assert lr.status_code == 200, lr.text
        rows = lr.json().get("broadcasts", [])
        assert rows, "list_broadcasts returned empty"
        assert rows[0]["id"] == bid, "newest broadcast not first"

        # Detail endpoint
        dr = s.get(f"{BASE_URL}/api/admin/broadcasts/{bid}", headers=_h(admin_token))
        assert dr.status_code == 200, dr.text
        det = dr.json()
        assert det["id"] == bid
        assert det.get("delivered_count", 0) >= 1

        # Stash for downstream tests
        pytest.broadcast_id = bid
        pytest.broadcast_title = title
        pytest.broadcast_msg = msg

    def test_segmented_audiences(self, s, admin_token):
        """providers/vendors/users may legitimately return 400 if no
        matching users exist — accept either 201 or 400 per spec."""
        for aud in ("providers", "vendors", "users"):
            r = s.post(f"{BASE_URL}/api/admin/broadcasts",
                       headers=_h(admin_token),
                       json={"title": f"seg-{aud}", "message": "test",
                             "audience": aud})
            assert r.status_code in (201, 400), \
                f"audience={aud} returned {r.status_code}: {r.text}"


# ─────────  Announcement thread visibility + post-guard + details  ──────────

class TestAnnouncementThread:
    def test_thread_appears_for_user_with_is_announcement_flag(self, s, two_users):
        # Wait briefly for any async fan-out to settle.
        time.sleep(1.5)
        alice = two_users["alice"]
        r = s.get(f"{BASE_URL}/api/chat/threads", headers=_h(alice["token"]))
        assert r.status_code == 200, r.text
        threads = r.json().get("threads", [])
        ann = [t for t in threads if t.get("is_announcement")]
        assert ann, f"No announcement thread for {alice['email']}: {threads}"
        tid = ann[0]["id"]
        # The original broadcast may not be the LAST message in the thread (the
        # later segmented audience='users' broadcast also lands here). Instead,
        # verify the original broadcast message exists in the message list.
        mr = s.get(f"{BASE_URL}/api/chat/{tid}/messages",
                   headers=_h(alice["token"]))
        assert mr.status_code == 200, mr.text
        msgs = mr.json().get("messages", [])
        texts = [m.get("text", "") for m in msgs]
        assert any(t.startswith("This is an automated test") for t in texts), \
            f"Original broadcast text not found in announcement thread: {texts}"
        pytest.alice_announcement_thread_id = tid

    def test_user_cannot_post_in_announcement_thread(self, s, two_users):
        tid = getattr(pytest, "alice_announcement_thread_id", None)
        assert tid, "No announcement thread captured."
        r = s.post(f"{BASE_URL}/api/chat/{tid}/messages",
                   headers=_h(two_users["alice"]["token"]),
                   json={"text": "reply attempt"})
        assert r.status_code == 403, r.text
        d = (r.json().get("detail") or "").lower()
        assert ("one-way" in d) or ("announcement" in d), d

    def test_thread_details_exposes_is_announcement(self, s, two_users):
        tid = getattr(pytest, "alice_announcement_thread_id", None)
        assert tid
        r = s.get(f"{BASE_URL}/api/chat/{tid}/details",
                  headers=_h(two_users["alice"]["token"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("is_announcement") is True, body


# ───────────────────────── Regression — normal chat flow ─────────────────────

class TestRegressionChat:
    def test_alice_to_bob_full_flow_with_push_failure_nonblocking(self, s, two_users):
        alice, bob = two_users["alice"], two_users["bob"]
        # 1. Send chat request
        rq = s.post(f"{BASE_URL}/api/chat/request",
                    headers=_h(alice["token"]),
                    json={"to_user_id": bob["id"], "message": "hi"})
        assert rq.status_code == 200, rq.text
        req = rq.json()
        # 2. Bob accepts
        ac = s.post(f"{BASE_URL}/api/chat/request/{req['id']}/accept",
                    headers=_h(bob["token"]))
        assert ac.status_code == 200, ac.text
        tid = ac.json()["thread_id"]
        # 3. Alice posts a message — placeholder push key MUST NOT block.
        mp = s.post(f"{BASE_URL}/api/chat/{tid}/messages",
                    headers=_h(alice["token"]),
                    json={"text": "hello bob"})
        assert mp.status_code == 200, mp.text
        m = mp.json()
        assert m.get("text") == "hello bob"
        # 4. Bob posts back
        mp2 = s.post(f"{BASE_URL}/api/chat/{tid}/messages",
                     headers=_h(bob["token"]),
                     json={"text": "hi alice"})
        assert mp2.status_code == 200, mp2.text


# ────────────────────────── Regression — unrelated endpoints ─────────────────

class TestUnrelatedRegression:
    def test_branding_ok(self, s):
        r = s.get(f"{BASE_URL}/api/branding")
        assert r.status_code == 200, r.text

    def test_privacy_ok(self, s, two_users):
        r = s.get(f"{BASE_URL}/api/users/me/privacy",
                  headers=_h(two_users["alice"]["token"]))
        assert r.status_code == 200, r.text
