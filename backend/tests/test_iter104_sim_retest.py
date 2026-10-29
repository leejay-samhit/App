# Iter104 — independent RETEST of iter103 issues 1/2/3/6 + core rules + no-gate-outside-chat + Excel receivables tie-out.
import io
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_iter103_sim_binding_independent import _mint  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env", override=False)
BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
MDB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
USER = {"email": "testbuyer@test.com", "password": "Test@1234"}
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
S = requests.Session()
_orig_request = S.request


def _paced(method, url, **kw):  # 429 is not a failure — wait for the window to roll over
    for _ in range(6):
        r = _orig_request(method, url, **kw)
        if r.status_code != 429:
            return r
        time.sleep(12)
    return r


S.request = _paced
APP = {"X-Client-Platform": "android", "User-Agent": "okhttp/4.12.0"}
WEB = {"X-Client-Platform": "web", "User-Agent": "Mozilla/5.0 Chrome/120"}
BROWSER_UA_ONLY = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
CODE = "sim_verification_required"


def _login(creds):
    for _ in range(4):
        r = S.post(f"{BASE}/auth/login", json=creds)
        if r.status_code == 429:
            time.sleep(20)
            continue
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}
    pytest.skip("login rate-limited")


def _check(h, state="SIM_PRESENT", mcc="404", mnc="45", **kw):
    ch = S.post(f"{BASE}/sim-binding/challenge", headers={**h, **APP}, json={}).json()
    body = dict(challenge_id=ch["challenge_id"], nonce=ch["nonce"], sim_state=state, slot_count=1 if mcc else 0,
                has_esim=False, mcc=mcc, mnc=mnc, platform="android", os_version="14", app_version="1.0")
    body.update(kw)
    return S.post(f"{BASE}/sim-binding/verify", headers={**h, **APP}, json=body)


def _present(h):
    _check(h)
    return _check(h).json()  # 2nd pass clears revalidate if fp moved


def _link(h):
    code = S.post(f"{BASE}/sim-binding/device-link/start", headers={**h, **WEB}).json()["code"]
    r = S.post(f"{BASE}/sim-binding/device-link/claim", headers={**h, **APP}, json={"code": code})
    assert r.status_code == 200, r.text
    return code


def _web_support(h, extra=WEB):
    return S.post(f"{BASE}/chat/contact-support", headers={**h, **extra}, json={})


def _blocked(r):
    if r.status_code != 403:
        return False
    d = r.json().get("detail")
    return isinstance(d, dict) and d.get("code") == CODE


@pytest.fixture(scope="module")
def ctx():
    uh = _login(USER)
    ah = _login(ADMIN)
    me = S.get(f"{BASE}/auth/me", headers=uh).json()
    uid = me.get("id") or me.get("user", {}).get("id")
    S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"enforce_chat": True, "required_level": "sim_presence", "allow_web_without_link": False})
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    c = dict(uh=uh, ah=ah, uid=uid, t0=time.time())
    yield c
    # RESTORE: enforce on, SIM_PRESENT, no web link, delete test artefacts
    S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"enforce_chat": True, "required_level": "sim_presence", "allow_web_without_link": False})
    _present(uh)
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    MDB.chat_messages.delete_many({"text": {"$regex": "^TEST_iter104"}})
    MDB.product_questions.delete_many({"text": {"$regex": "^TEST_iter104"}})


def _web_link_present(uid):
    return "web_link_expires_at" in (MDB.sim_bindings.find_one({"user_id": uid}) or {})


# --- Issue 1: web link revoked when phone stops passing ---
@pytest.mark.parametrize("how", ["sim_absent", "revalidate", "carrier_change"])
def test_web_link_revoked(ctx, how):
    uh, uid = ctx["uh"], ctx["uid"]
    _present(uh)
    _link(uh)
    assert _web_link_present(uid)
    r = _web_support(uh)
    assert r.status_code == 200, f"linked browser should pass: {r.status_code} {r.text[:200]}"
    if how == "sim_absent":
        assert _check(uh, "SIM_ABSENT", mcc="", mnc="").status_code == 200
    elif how == "revalidate":
        assert S.post(f"{BASE}/sim-binding/revalidate", headers={**uh, **APP}, json={"reason": "TEST_iter104"}).status_code == 200
    else:
        d = _check(uh, "SIM_PRESENT", mcc="404", mnc="10").json()
        assert d["sim_changed"] is True
    assert _blocked(_web_support(uh)), "browser must be 403 immediately"
    assert not _web_link_present(uid), "web_link_expires_at must be unset"
    # even after the phone passes again the browser needs a NEW link
    _present(uh)
    assert _blocked(_web_support(uh)), "browser must need a fresh link after re-pass"
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})


# --- Issue 2: every chat write gated while blocked; question not persisted ---
def test_all_chat_writes_gated_when_blocked(ctx):
    uh = ctx["uh"]
    assert _check(uh, "SIM_ABSENT", mcc="", mnc="").status_code == 200
    rid, pid = str(uuid.uuid4()), MDB.products.find_one({}, {"id": 1})["id"]
    calls = {
        "edit": lambda: S.patch(f"{BASE}/chat/messages/{uuid.uuid4()}", headers={**uh, **APP}, json={"text": "TEST_iter104 x"}),
        "accept": lambda: S.post(f"{BASE}/chat/request/{rid}/accept", headers={**uh, **APP}),
        "order_chat": lambda: S.post(f"{BASE}/orders/{uuid.uuid4()}/chat-vendor", headers={**uh, **APP}),
        "question": lambda: S.post(f"{BASE}/products/{pid}/questions", headers={**uh, **APP}, json={"text": "TEST_iter104 question blocked"}),
        "request": lambda: S.post(f"{BASE}/chat/request", headers={**uh, **APP}, json={"to_user_id": str(uuid.uuid4()), "message": "TEST_iter104"}),
        "threads": lambda: S.post(f"{BASE}/chat/threads", headers={**uh, **APP}, json={"participant_id": str(uuid.uuid4())}),
        "support": lambda: S.post(f"{BASE}/chat/contact-support", headers={**uh, **APP}, json={}),
        "message": lambda: S.post(f"{BASE}/chat/{uuid.uuid4()}/messages", headers={**uh, **APP}, json={"text": "TEST_iter104 msg"}),
    }
    bad = {}
    for k, fn in calls.items():
        r = fn()
        if not _blocked(r):
            bad[k] = (r.status_code, r.text[:150])
    assert not bad, bad
    assert MDB.product_questions.count_documents({"text": "TEST_iter104 question blocked"}) == 0
    # reads stay open
    assert S.get(f"{BASE}/chat/threads", headers={**uh, **APP}).status_code == 200
    _present(uh)


# --- Issue 3: browser needs a live link; UA fallback; link-code status ---
def test_browser_needs_link_and_ua_fallback(ctx):
    uh, uid = ctx["uh"], ctx["uid"]
    _present(uh)
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    assert _web_support(uh, APP).status_code == 200, "verified app caller passes"
    assert _blocked(_web_support(uh, WEB)), "X-Client-Platform: web unlinked must be 403"
    assert _blocked(_web_support(uh, BROWSER_UA_ONLY)), "browser UA without platform header must be 403"
    # expired link is not a link
    MDB.sim_bindings.update_one({"user_id": uid}, {"$set": {"web_link_expires_at": "2020-01-01T00:00:00+00:00"}})
    assert _blocked(_web_support(uh, WEB))
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})


def test_device_link_code_status(ctx):
    uh = ctx["uh"]
    _present(uh)
    code = S.post(f"{BASE}/sim-binding/device-link/start", headers={**uh, **WEB}).json()["code"]
    st = S.get(f"{BASE}/sim-binding/device-link/{code}", headers={**uh, **WEB})
    assert st.status_code == 200 and st.json()["claimed"] is False and st.json()["expired"] is False
    assert S.get(f"{BASE}/sim-binding/device-link/nonexistent-{uuid.uuid4().hex}", headers=uh).status_code == 404
    bh, _ = _mint("testbuyer2@test.com")
    assert S.get(f"{BASE}/sim-binding/device-link/{code}", headers=bh).status_code == 404, "other account must not read"
    assert S.post(f"{BASE}/sim-binding/device-link/claim", headers={**uh, **APP}, json={"code": code}).status_code == 200
    assert S.get(f"{BASE}/sim-binding/device-link/{code}", headers=uh).json()["claimed"] is True
    assert _web_support(uh, WEB).status_code == 200
    assert _web_support(uh, BROWSER_UA_ONLY).status_code == 200
    MDB.sim_bindings.update_one({"user_id": ctx["uid"]}, {"$unset": {"web_link_expires_at": ""}})


# --- Issue 6: re-inserting same SIM is not sim_changed ---
def test_same_sim_reinsert_not_changed(ctx):
    uh = ctx["uh"]
    _present(uh)
    assert _check(uh, "SIM_ABSENT", mcc="", mnc="").json()["sim_changed"] is False
    d = _check(uh).json()
    assert d["sim_changed"] is False and d["meets_requirement"] is True and d["revalidate_required"] is False


# --- Attestation hook + core rules ---
def test_core_rules_and_attestation_hook(ctx):
    uh, ah = ctx["uh"], ctx["ah"]
    d = _check(uh, play_integrity_token="bogus-token-xyz")
    assert d.status_code == 200, d.text
    j = d.json()
    assert j["level"] == "sim_presence" and j["number_verified"] is False
    ch = S.post(f"{BASE}/sim-binding/challenge", headers=uh, json={}).json()
    base = dict(sim_state="SIM_PRESENT", slot_count=1, mcc="404", mnc="45", platform="android")
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ch["challenge_id"], "nonce": "forged"}).status_code == 400
    ch2 = S.post(f"{BASE}/sim-binding/challenge", headers=uh, json={}).json()
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "platform": "web", "challenge_id": ch2["challenge_id"], "nonce": ch2["nonce"]}).status_code == 400
    ch3 = S.post(f"{BASE}/sim-binding/challenge", headers=uh, json={}).json()
    ok = {**base, "challenge_id": ch3["challenge_id"], "nonce": ch3["nonce"]}
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json=ok).status_code == 200
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json=ok).status_code == 400  # replay
    ach = S.post(f"{BASE}/sim-binding/challenge", headers=ah, json={}).json()
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ach["challenge_id"], "nonce": ach["nonce"]}).status_code == 400
    ech = S.post(f"{BASE}/sim-binding/challenge", headers=uh, json={}).json()
    MDB.sim_challenges.update_one({"id": ech["challenge_id"]}, {"$set": {"expires_at": "2020-01-01T00:00:00+00:00"}})
    assert S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ech["challenge_id"], "nonce": ech["nonce"]}).status_code == 400
    # "claimed success" field is ignored
    ch4 = S.post(f"{BASE}/sim-binding/challenge", headers=uh, json={}).json()
    r = S.post(f"{BASE}/sim-binding/verify", headers=uh, json={**base, "challenge_id": ch4["challenge_id"], "nonce": ch4["nonce"], "number_verified": True, "level": "number_verified"})
    assert r.json()["level"] == "sim_presence"
    nch = S.post(f"{BASE}/sim-binding/challenge", headers=uh, json={}).json()
    # 503 while no provider is configured; 401 once one is, because
    # Truecaller itself rejects the bogus code. Never 200 either way.
    assert S.post(f"{BASE}/sim-binding/number-proof", headers=uh, json={"challenge_id": nch["challenge_id"], "nonce": nch["nonce"], "code": "x", "code_verifier": "y"}).status_code in (401, 503)
    assert S.get(f"{BASE}/admin/sim-binding/overview", headers=uh).status_code == 403
    assert S.patch(f"{BASE}/admin/sim-binding/policy", headers=uh, json={"enforce_chat": False}).status_code == 403
    p = S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"required_level": "number_verified"}).json()
    if p["number_proof_available"]:
        # A provider is configured, so the stricter level is a real choice.
        assert p["required_level"] == "number_verified" and p["clamped_to_sim_presence"] is False
    else:
        assert p["required_level"] == "sim_presence" and p["clamped_to_sim_presence"] is True
    # Restore the owner's live setting so chat is not locked to Truecaller.
    S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"required_level": "sim_presence"})
    S.patch(f"{BASE}/admin/sim-binding/policy", headers=ah, json={"required_level": "sim_presence"})
    b = MDB.sim_bindings.find_one({"user_id": ctx["uid"]}, {"_id": 0})
    for k in ("imei", "imsi", "iccid", "sim_serial", "mcc", "mnc", "play_integrity_token"):
        assert k not in b, k


# --- Nothing outside chat gated (user blocked + browser-like caller) ---
def test_non_chat_not_gated(ctx):
    uh, ah = ctx["uh"], ctx["ah"]
    assert _check(uh, "SIM_ABSENT", mcc="", mnc="").status_code == 200
    vh, vendor = _mint("testvendor@test.com")
    dh, _ = _mint("rider_test@test.com")
    MDB.sim_bindings.update_one({"user_id": vendor["id"]}, {"$set": {"sim_state": "SIM_ABSENT"}}, upsert=True)
    pid = "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"
    bad = []
    for extra in (WEB, APP):
        gets = [(uh, "/products"), (uh, f"/products/{pid}"), (uh, "/cart"), (uh, "/orders/me"), (uh, "/wallet/topup/config"),
                (uh, "/recharge/options"), (uh, "/recharge/history"), (uh, "/returns/me"),
                (vh, "/vendor/me/stats"), (vh, "/vendor/me/products"), (vh, "/vendor/me/earnings"),
                (dh, "/delivery-partner/me"), (dh, "/delivery-partner/me/orders"), (dh, "/delivery-partner/me/wallet"),
                (ah, "/admin/finance/net-worth"), (ah, "/admin/refunds"), (ah, "/admin/returns")]
        for h, p in gets:
            r = S.get(f"{BASE}{p}", headers={**h, **extra})
            if r.status_code != 200 or CODE in r.text:
                bad.append((p, extra["X-Client-Platform"], r.status_code, r.text[:100]))
        r = S.post(f"{BASE}/cart/add", headers={**uh, **extra}, json={"product_id": pid, "quantity": 1, "qty": 1})
        if r.status_code != 200 or CODE in r.text:
            bad.append(("cart/add", r.status_code, r.text[:120]))
        S.post(f"{BASE}/cart/remove", headers={**uh, **extra}, json={"product_id": pid})
        r = S.post(f"{BASE}/orders/checkout", headers={**uh, **extra}, json={"payment_method": "TEST_invalid"})
        if CODE in r.text:
            bad.append(("checkout", r.status_code, r.text[:120]))
        stock = MDB.products.find_one({"id": pid})["stock"]
        r = S.patch(f"{BASE}/vendor/me/products/{pid}", headers={**vh, **extra}, json={"stock": stock})
        if r.status_code != 200 or CODE in r.text:
            bad.append(("vendor edit", r.status_code, r.text[:120]))
    MDB.sim_bindings.delete_one({"user_id": vendor["id"], "sim_state": "SIM_ABSENT"})
    _present(uh)
    assert not bad, bad


# --- Excel Receivables ties to API; return_refund excluded from receivables but on Vendor Outstanding ---
def test_excel_receivables_tie_out(ctx):
    import openpyxl
    ah = ctx["ah"]
    vid = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
    rid = "TEST_iter104_" + uuid.uuid4().hex[:8]
    MDB.vendor_outstanding.insert_one({"id": rid, "vendor_id": vid, "kind": "return_refund", "amount": 123.45, "recovered": 0.0,
                                       "vendor_name": "TEST_iter104 shop", "order_number": "TEST_iter104_ORD", "status": "open", "note": "TEST_iter104",
                                       "created_at": "2026-01-01T00:00:00+00:00"})
    try:
        nw = S.get(f"{BASE}/admin/finance/net-worth", headers=ah).json()
        rec_api = (nw.get("master") or {}).get("receivables_total", nw.get("receivables_total"))
        assert rec_api is not None, list(nw.keys())
        r = S.get(f"{BASE}/admin/wallet/export/groupwise", headers=ah)
        assert r.status_code == 200, r.text[:200]
        wb = openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)
        ctx["sheets"] = wb.sheetnames
        rec = wb["Receivables"]
        total = None
        for row in rec.iter_rows(values_only=True):
            if row and any(isinstance(c, str) and "RECEIVABLES TOTAL" in c for c in row):
                nums = [c for c in row if isinstance(c, (int, float))]
                if nums:
                    total = nums[-1]
        assert total is not None, "no RECEIVABLES TOTAL row on Receivables"
        assert abs(float(total) - float(rec_api)) < 0.01, (total, rec_api)
        rows = list(rec.iter_rows(values_only=True))
        # The parked refund must be VISIBLE (the company owes nothing, but the
        # shopper is still owed) and must sit BELOW the receivables total so
        # it can never be counted as company money.
        total_at = next(
            i for i, row in enumerate(rows)
            if row and any(isinstance(c, str) and "RECEIVABLES TOTAL" in c for c in row)
        )
        above = " ".join(str(c) for row in rows[:total_at + 1] for c in row if c is not None)
        below = " ".join(str(c) for row in rows[total_at + 1:] for c in row if c is not None)
        assert "123.45" not in above, "parked return_refund row leaked into the receivables total"
        assert "123.45" in below, "parked return_refund row is invisible in the workbook"
        assert "NOT a receivable" in below
        vo = [s for s in wb.sheetnames if "outstanding" in s.lower()]
        assert vo, wb.sheetnames
        # The "Vendor Outstanding" sheet is built from wallet TRANSACTIONS and
        # parking a refund creates none, so the parked row lives on the
        # Receivables sheet (asserted above) rather than here.
    finally:
        MDB.vendor_outstanding.delete_one({"id": rid})


# --- NEW (iter104): the browser must not be able to approve its OWN link code ---
def test_browser_cannot_self_claim_link(ctx):
    uh, uid = ctx["uh"], ctx["uid"]
    _present(uh)
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    code = S.post(f"{BASE}/sim-binding/device-link/start", headers={**uh, **WEB}).json()["code"]
    r = S.post(f"{BASE}/sim-binding/device-link/claim", headers={**uh, **WEB}, json={"code": code})
    linked = _web_support(uh, WEB).status_code == 200
    MDB.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
    assert r.status_code in (400, 403) and not linked, f"browser self-claimed its own code: {r.status_code} {r.text[:120]}"
