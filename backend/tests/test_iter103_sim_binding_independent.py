# Iter103 — independent SIM-binding + chat-gate probe (API + DB). Restores policy/binding at end.
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env", override=False)
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
MDB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
USER = {"email": "testbuyer@test.com", "password": "Test@1234"}
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
S = requests.Session()


def _login(creds):
    for _ in range(3):
        r = S.post(f"{BASE}/auth/login", json=creds)
        if r.status_code == 429:
            time.sleep(15)
            continue
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}
    pytest.skip("login rate-limited")


def _mint(email):
    """Mint a token for a seeded account whose password is unknown (vendor / 2nd buyer)."""
    from core.config import JWT_SECRET  # noqa
    u = MDB.users.find_one({"email": email})
    if not u:
        pytest.skip(f"{email} missing")
    sids = u.get("active_session_ids") or []
    sid = sids[-1] if sids else u.get("active_session_id")
    if not sid:
        sid = "iter103-" + uuid.uuid4().hex[:8]
        MDB.users.update_one({"id": u["id"]}, {"$push": {"active_session_ids": sid}})
    now = datetime.now(timezone.utc)
    tok = jwt.encode({"sub": u["id"], "email": email, "role": u.get("role", "user"), "iat": now,
                      "exp": now + timedelta(minutes=15), "type": "access", "sid": sid}, JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}, u


@pytest.fixture(scope="module")
def ctx():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    uh = _login(USER)
    ah = _login(ADMIN)
    vh, vendor = _mint("testvendor@test.com")
    bh, buyer2 = _mint("testbuyer2@test.com")
    me = S.get(f"{BASE}/auth/me", headers=uh).json()
    uid = me.get("id") or me.get("user", {}).get("id")
    # a lingering web link (left by earlier suites) silently bypasses the whole gate — start clean
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    c = dict(uh=uh, ah=ah, vh=vh, bh=bh, uid=uid, vendor=vendor, buyer2=buyer2, nonces=[], codes=[])
    yield c
    # restore: enforce on, user SIM_PRESENT via proper path
    S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"enforce_chat": True, "required_level": "sim_presence"})
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    _check(uh, "SIM_PRESENT", mcc="404", mnc="45")
    _check(uh, "SIM_PRESENT", mcc="404", mnc="45")  # second pass clears revalidate if fp changed
    for who in (vendor["id"], buyer2["id"]):
        MDB.sim_bindings.delete_one({"user_id": who})


def _ch(h, c=None):
    r = S.post(f"{BASE}/sim-binding/challenge", headers=h, json={})
    assert r.status_code == 200, r.text
    d = r.json()
    if c is not None:
        c["nonces"].append(d["nonce"])
    return d


def _check(h, state="SIM_PRESENT", platform="android", mcc="404", mnc="45", c=None, **kw):
    ch = _ch(h, c)
    body = dict(challenge_id=ch["challenge_id"], nonce=ch["nonce"], sim_state=state, slot_count=1,
                has_esim=False, mcc=mcc, mnc=mnc, platform=platform, os_version="14", app_version="1.0")
    body.update(kw)
    return S.post(f"{BASE}/sim-binding/verify", headers=h, json=body)


# --- challenge / verify hardening ---
def test_challenge_requires_auth_and_ttl(ctx):
    assert S.post(f"{BASE}/sim-binding/challenge", json={}).status_code in (401, 403)
    d = _ch(ctx["uh"], ctx)
    assert d["ttl_seconds"] == 120 and len(d["nonce"]) >= 32
    exp = datetime.fromisoformat(d["expires_at"])
    assert 100 < (exp - datetime.now(timezone.utc)).total_seconds() <= 121


def test_verify_rejects_forged_replayed_expired_cross_web(ctx):
    uh, ah = ctx["uh"], ctx["ah"]
    base = dict(sim_state="SIM_PRESENT", slot_count=1, mcc="404", mnc="45", platform="android")
    # forged nonce
    ch = _ch(uh, ctx)
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ch["challenge_id"], "nonce": "forged"}).status_code == 400
    # unknown challenge id
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": str(uuid.uuid4()), "nonce": "x"}).status_code == 400
    # cross-account: admin's challenge used by user
    ach = _ch(ah, ctx)
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ach["challenge_id"], "nonce": ach["nonce"]}).status_code == 400
    # expired
    ech = _ch(uh, ctx)
    MDB.sim_challenges.update_one({"id": ech["challenge_id"]}, {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}})
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ech["challenge_id"], "nonce": ech["nonce"]}).status_code == 400
    # web platform
    assert _check(uh, platform="web", c=ctx).status_code == 400
    assert _check(uh, platform="WEB", c=ctx).status_code == 400
    # unknown state
    assert _check(uh, state="VERIFIED", c=ctx).status_code == 400
    # replay
    rch = _ch(uh, ctx)
    body = {**base, "challenge_id": rch["challenge_id"], "nonce": rch["nonce"]}
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json=body).status_code == 200
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json=body).status_code == 400


def test_sim_present_never_sets_number_verified(ctx):
    r = _check(ctx["uh"], c=ctx, number_verified=True, level="number_verified", phone="9999999999")
    assert r.status_code == 200
    d = r.json()
    assert d["level"] == "sim_presence" and d["number_verified"] is False and d["meets_requirement"] is True
    assert "not proof" in d["disclaimer"]
    doc = MDB.sim_bindings.find_one({"user_id": ctx["uid"]})
    assert not doc.get("number_verified")


def test_number_proof_never_self_asserts(ctx):
    ch = _ch(ctx["uh"], ctx)
    r = S.post(f"{BASE}/sim-binding/number-proof", headers=ctx["uh"], json={
        "challenge_id": ch["challenge_id"], "nonce": ch["nonce"], "provider": "truecaller",
        "code": "FAKE-CODE-123", "code_verifier": "v" * 50})
    # 503 before a provider is configured, 401 after (Truecaller rejects the
    # fake code). Never 200.
    assert r.status_code in (401, 503)
    st = S.get(f"{BASE}/sim-binding/status", headers=ctx["uh"]).json()
    # The number must stay unverified whatever happens; whether a provider is
    # configured depends on the deployment (Truecaller Client ID present).
    assert st["number_verified"] is False


def test_revalidate_blocks_chat_then_recheck_unblocks(ctx):
    uh = ctx["uh"]
    d = S.post(f"{BASE}/sim-binding/revalidate", headers=uh, json={"reason": "iter103"}).json()
    assert d["revalidate_required"] is True and d["level"] == "none"
    r = S.post(f"{BASE}/chat/contact-support", headers=uh, json={})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "sim_verification_required"
    assert _check(uh, c=ctx).json()["level"] == "sim_presence"


def test_sim_change_wipes_number_verified(ctx):
    uh, uid = ctx["uh"], ctx["uid"]
    MDB.sim_bindings.update_one({"user_id": uid}, {"$set": {"number_verified": True, "phone_last4": "1234", "number_proof_method": "truecaller"}})
    d = _check(uh, mcc="404", mnc="10", c=ctx).json()
    assert d["sim_changed"] is True and d["number_verified"] is False and d["revalidate_required"] is True
    assert d["level"] == "none"
    doc = MDB.sim_bindings.find_one({"user_id": uid})
    assert doc.get("phone_last4") is None
    assert _check(uh, mcc="404", mnc="10", c=ctx).json()["level"] == "sim_presence"


# --- chat gate: writes blocked, reads open ---
def test_chat_writes_blocked_reads_open(ctx):
    uh = ctx["uh"]
    # while allowed, open a support thread so we have a real thread id
    r = S.post(f"{BASE}/chat/contact-support", headers=uh, json={})
    assert r.status_code == 200, r.text
    threads = S.get(f"{BASE}/chat/threads", headers=uh).json()
    tl = threads if isinstance(threads, list) else threads.get("threads", threads.get("items", []))
    assert tl, "no threads"
    tid = tl[0]["id"]
    ok = S.post(f"{BASE}/chat/{tid}/messages", headers=uh, json={"text": "TEST_iter103 allowed"})
    assert ok.status_code == 200, ok.text
    ctx["msg_id"] = ok.json().get("id") or ok.json().get("message", {}).get("id")
    ctx["tid"] = tid
    # block
    assert _check(uh, state="SIM_ABSENT", mcc="", mnc="", c=ctx).json()["meets_requirement"] is False
    calls = [
        ("post", "/chat/contact-support", {}),
        ("post", "/chat/request", {"to_user_id": ctx["vendor"]["id"], "message": "TEST hi"}),
        ("post", "/chat/threads", {"provider_id": ctx["vendor"]["id"], "to_user_id": ctx["vendor"]["id"]}),
        ("post", f"/chat/{tid}/messages", {"text": "TEST_iter103 blocked"}),
    ]
    for m, p, b in calls:
        r = getattr(S, m)(f"{BASE}{p}", headers=uh, json=b)
        assert r.status_code == 403, f"{p} -> {r.status_code} {r.text[:200]}"
        det = r.json()["detail"]
        assert det["code"] == "sim_verification_required" and "No SIM" in det["message"], det
    for p in ("/chat/threads", f"/chat/{tid}/messages", "/chat/starred"):
        r = S.get(f"{BASE}{p}", headers=uh)
        assert r.status_code == 200, f"{p} {r.status_code}"
    msgs = S.get(f"{BASE}/chat/{tid}/messages", headers=uh).json()
    assert "TEST_iter103 allowed" in str(msgs)


def test_ungated_chat_write_paths_under_block(ctx):
    """Probe chat-ish writes NOT wrapped by the gate. Records results; asserts gate expectation."""
    uh = ctx["uh"]
    out = {}
    if ctx.get("msg_id"):
        out["edit"] = S.patch(f"{BASE}/chat/messages/{ctx['msg_id']}", headers=uh, json={"text": "TEST_iter103 edited while blocked"}).status_code
    prod = MDB.products.find_one({"vendor_id": {"$ne": None}, "status": {"$in": ["approved", "active", None]}}, {"id": 1})
    if prod:
        r = S.post(f"{BASE}/products/{prod['id']}/questions", headers=uh, json={"text": "TEST_iter103 question while SIM absent"})
        out["product_question"] = r.status_code
        if r.status_code == 200:
            qid = r.json().get("id")
            MDB.product_questions.delete_many({"text": {"$regex": "^TEST_iter103"}})
            MDB.chat_messages.delete_many({"text": {"$regex": "^TEST_iter103 question"}})
            out["qid"] = qid
    print("UNGATED_PROBE", out)
    assert out.get("edit") == 403 and out.get("product_question") == 403, f"chat writes bypass the SIM gate: {out}"


def test_non_chat_endpoints_unaffected_while_blocked(ctx):
    uh, ah, vh = ctx["uh"], ctx["ah"], ctx["vh"]
    MDB.sim_bindings.update_one({"user_id": ctx["vendor"]["id"]}, {"$set": {"sim_state": "SIM_ABSENT", "user_id": ctx["vendor"]["id"]}}, upsert=True)
    # vendor is blocked in chat
    assert S.post(f"{BASE}/chat/contact-support", headers=vh, json={}).status_code == 403
    checks = [
        (uh, "/products"), (uh, "/cart"), (uh, "/orders/me"), (uh, "/wallet/topup/config"), (uh, "/returns/me"),
        (vh, "/vendor/me/stats"), (vh, "/vendor/me/products"), (vh, "/vendor/me/earnings"), (vh, "/vendor/me/net-worth"), (vh, "/vendor/me/returns"),
        (ah, "/admin/finance/net-worth"), (ah, "/admin/refunds"), (ah, "/admin/returns"), (ah, "/admin/sim-binding/overview"),
    ]
    bad = []
    for h, p in checks:
        r = S.get(f"{BASE}{p}", headers=h)
        if r.status_code != 200:
            bad.append((p, r.status_code, r.text[:120]))
    assert not bad, bad


# --- device linking ---
def test_device_link_lifecycle(ctx):
    uh, bh = ctx["uh"], ctx["bh"]
    # user currently SIM_ABSENT -> cannot claim
    code = S.post(f"{BASE}/sim-binding/device-link/start", headers=uh).json()
    ctx["codes"].append(code["code"])
    assert code["ttl_seconds"] == 180
    assert S.post(f"{BASE}/sim-binding/device-link/claim", headers=uh, json={"code": code["code"]}).status_code == 403
    _check(uh, c=ctx); _check(uh, c=ctx)
    # cross-account: buyer2 verified phone claims user's code
    _check(bh); _check(bh)
    assert S.post(f"{BASE}/sim-binding/device-link/claim", headers=bh, json={"code": code["code"]}).status_code == 403
    # owner claims -> ok, replay -> 400
    r = S.post(f"{BASE}/sim-binding/device-link/claim", headers=uh, json={"code": code["code"]})
    assert r.status_code == 200 and r.json()["linked"] is True
    assert S.post(f"{BASE}/sim-binding/device-link/claim", headers=uh, json={"code": code["code"]}).status_code == 400
    # expired
    c2 = S.post(f"{BASE}/sim-binding/device-link/start", headers=uh).json()
    ctx["codes"].append(c2["code"])
    MDB.device_links.update_one({"code": c2["code"]}, {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}})
    assert S.post(f"{BASE}/sim-binding/device-link/claim", headers=uh, json={"code": c2["code"]}).status_code == 400
    assert S.post(f"{BASE}/sim-binding/device-link/claim", headers=uh, json={"code": "nope"}).status_code == 400


def test_web_link_does_not_override_sim_absent(ctx):
    """After linking, the phone reports SIM_ABSENT. block_on_sim_absent should still block chat."""
    uh = ctx["uh"]
    _check(uh, state="SIM_ABSENT", mcc="", mnc="", c=ctx)
    r = S.post(f"{BASE}/chat/contact-support", headers=uh, json={})
    print("contact-support after link + SIM_ABSENT:", r.status_code)
    assert r.status_code == 403, "web_link_expires_at keeps chat open for 24h after SIM removed"


# --- admin ---
def test_admin_only_and_clamp(ctx):
    uh, ah = ctx["uh"], ctx["ah"]
    assert S.get(f"{BASE}/admin/sim-binding/overview", headers=uh).status_code == 403
    assert S.patch(f"{BASE}/admin/sim-binding/policy", headers=uh, json={"enforce_chat": False}).status_code == 403
    p = S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"required_level": "number_verified"}).json()
    if p["number_proof_available"]:
        assert p["required_level"] == "number_verified" and p["clamped_to_sim_presence"] is False
    else:
        assert p["required_level"] == "sim_presence" and p["clamped_to_sim_presence"] is True
    S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"required_level": "sim_presence"})
    assert S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"required_level": "god"}).status_code == 400
    p = S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"enforce_chat": False, "required_level": "sim_presence"}).json()
    assert p["enforce_chat"] is False
    assert S.post(f"{BASE}/chat/contact-support", headers=uh, json={}).status_code == 200
    p = S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"enforce_chat": True}).json()
    assert p["enforce_chat"] is True
    ov = S.get(f"{BASE}/admin/sim-binding/overview", headers=ah).json()
    assert ov["policy"]["enforce_chat"] is True and "totals" in ov and isinstance(ov["recent_events"], list)


# --- privacy ---
def test_privacy_no_identifiers_no_secrets_in_audit(ctx):
    banned = ("imei", "imsi", "iccid", "sim_serial", "subscription_id", "msisdn", "phone_number", "nonce", "code")
    for doc in MDB.sim_bindings.find({}):
        keys = {k.lower() for k in doc.keys()}
        assert not (keys & set(banned)), keys
    secrets_ = ctx["nonces"] + ctx["codes"]
    for row in MDB.sim_audit.find({}, {"_id": 0}).sort("created_at", -1).limit(500):
        blob = str(row)
        assert not any(s in blob for s in secrets_), row
        assert "nonce" not in row and "code" not in row
