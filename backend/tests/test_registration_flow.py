"""Registration + Truecaller + payment-choice flow (Oct 2026).

Covers the owner's ten scenarios as far as a server can:

  1-4. manual / Google signup → verification → Pay ₹118 or Continue Without Fee
  5.   Truecaller unavailable or cancelled
  6.   payment failure / cancellation
  7.   duplicate payment callback
  8.   existing account with an already verified number
  9.   linking a number that belongs to another account
  10.  logout then login again

The Truecaller consent sheet itself is an Android UI that cannot run here, so
the tests attack the thing that actually decides the outcome: the server-side
state + PKCE exchange. A client that merely claims success must fail.

Run:  python3 tests/test_registration_flow.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa: E402
from core.pkce import code_challenge_for  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}
PW = "Reg@Flow123"


async def login(c, creds):
    r = await c.post(f"{BASE}/auth/login", json=creds)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"], "X-Client-Platform": "android"}


async def make_user(c, tag, google=False):
    """Create a fresh account the same way the app does."""
    email = f"regflow.{tag}.{uuid.uuid4().hex[:6]}@example.com"
    r = await c.post(f"{BASE}/auth/register", json={
        "name": f"Reg Flow {tag}", "email": email, "password": PW, "role": "user",
    })
    r.raise_for_status()
    if google:
        # Mirror a Google sign-in: provider set, no password path used.
        await db.users.update_one({"email": email}, {"$set": {"auth_provider": "google"}})
    h = await login(c, {"email": email, "password": PW})
    me = (await c.get(f"{BASE}/auth/me", headers=h)).json()
    return h, me["id"], email


async def mint_state(uid, verifier="verifier-for-tests-0123456789"):
    """Insert a server state row the way /start would."""
    state = "st_" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    await db.truecaller_states.insert_one({
        "state": state, "user_id": uid, "code_verifier": verifier,
        "purpose": "registration", "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=300)).isoformat(), "used_at": None,
    })
    return state


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        ah = await login(c, ADMIN)

        # ── Scenario 1 + 3 setup: manual registration ────────────────────
        uh, uid, uemail = await make_user(c, "manual")
        st = (await c.get(f"{BASE}/auth/signup-gate/status", headers=uh)).json()
        check("new account starts pending_verification",
              st.get("registration_status") == "pending_verification", str(st.get("registration_status")))
        check("registration path undecided", st.get("registration_path") == "undecided")
        check("status reports whether Truecaller is configured", "truecaller_available" in st)

        # ── Scenario 5: cannot self-declare verification ────────────────
        r = await c.post(f"{BASE}/auth/truecaller/verify", json={
            "state": "totally-made-up", "authorization_code": "fake",
        }, headers=uh)
        check("forged state refused", r.status_code in (400, 503), f"HTTP {r.status_code}")

        state = await mint_state(uid)
        r = await c.post(f"{BASE}/auth/truecaller/verify", json={
            "state": state, "authorization_code": "fake-code",
        }, headers=uh)
        # 401 = Truecaller rejected the fake code; 503 = provider not configured.
        check("fake authorization code refused", r.status_code in (401, 503), f"HTTP {r.status_code}")
        after = (await c.get(f"{BASE}/auth/signup-gate/status", headers=uh)).json()
        check("still unverified after a failed attempt", after.get("phone_verified") is False)

        # A state is single use even when the exchange failed.
        row = await db.truecaller_states.find_one({"state": state}, {"_id": 0})
        if r.status_code == 401:
            check("state consumed after use", bool(row.get("used_at")))
            r2 = await c.post(f"{BASE}/auth/truecaller/verify", json={
                "state": state, "authorization_code": "fake-code",
            }, headers=uh)
            check("state cannot be replayed", r2.status_code == 400, f"HTTP {r2.status_code}")

        # Another account's state must never work.
        other_h, other_id, _ = await make_user(c, "other")
        foreign = await mint_state(other_id)
        r = await c.post(f"{BASE}/auth/truecaller/verify", json={
            "state": foreign, "authorization_code": "fake",
        }, headers=uh)
        check("another account's state refused", r.status_code in (400, 503), f"HTTP {r.status_code}")

        # Expired state.
        expired = await mint_state(uid)
        await db.truecaller_states.update_one(
            {"state": expired},
            {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()}},
        )
        r = await c.post(f"{BASE}/auth/truecaller/verify", json={
            "state": expired, "authorization_code": "fake",
        }, headers=uh)
        check("expired state refused", r.status_code in (400, 503), f"HTTP {r.status_code}")

        # PKCE derivation must match the S256 rule Truecaller enforces.
        check("pkce challenge is base64url without padding",
              "=" not in code_challenge_for("abc") and "+" not in code_challenge_for("abc"))

        # ── Alternative method still works (manual entry) ────────────────
        phone = ("9" + str(uuid.uuid4().int)[:9])[:10]
        r = await c.post(f"{BASE}/auth/signup-gate/confirm", json={"phone": phone}, headers=uh)
        check("manual number entry still accepted", r.status_code == 200, f"HTTP {r.status_code}")
        st = (await c.get(f"{BASE}/auth/signup-gate/status", headers=uh)).json()
        check("manual entry marks method self_declared",
              st.get("phone_verified_method") == "self_declared", str(st.get("phone_verified_method")))
        check("manual entry never claims third-party verification",
              st.get("phone_verified") is False)
        check("gate no longer required", st.get("required") is False)
        check("status is verified, payment still open", st.get("registration_status") == "verified")

        # ── Scenario 9: number belonging to another account ──────────────
        r = await c.post(f"{BASE}/auth/signup-gate/check", json={"phone": phone}, headers=other_h)
        body = r.json()
        check("duplicate number is refused", body.get("ok") is False, str(body)[:80])
        check("conflict names the owning account",
              (body.get("conflict") or {}).get("reason") == "phone_taken")
        r = await c.post(f"{BASE}/auth/signup-gate/confirm", json={"phone": phone}, headers=other_h)
        check("duplicate confirm blocked too", r.status_code == 409, f"HTTP {r.status_code}")
        # And through the Truecaller route: a verified-elsewhere number cannot
        # be claimed, which is the account-takeover shape.
        st2 = await mint_state(other_id)
        await db.users.update_one({"id": uid}, {"$set": {"phone_verified": True}})
        r = await c.post(f"{BASE}/auth/truecaller/verify", json={
            "state": st2, "authorization_code": "fake",
        }, headers=other_h)
        check("takeover attempt does not succeed", r.status_code != 200, f"HTTP {r.status_code}")
        await db.users.update_one({"id": uid}, {"$set": {"phone_verified": False}})

        # ── Scenario 3: Continue Without Fee (manual account) ────────────
        r = await c.post(f"{BASE}/payment/skip-subscription", headers=uh)
        check("Continue Without Fee accepted", r.status_code == 200, f"HTTP {r.status_code}")
        doc = await db.users.find_one({"id": uid}, {"_id": 0})
        check("free path recorded", bool(doc.get("subscription_skipped")))
        check("payment NOT marked successful", not doc.get("registration_paid"))
        check("no fake payment row created",
              await db.transactions.count_documents({"user_id": uid, "type": "registration_payment"}) == 0)
        st = (await c.get(f"{BASE}/auth/signup-gate/status", headers=uh)).json()
        check("status is free_registration", st.get("registration_status") == "free_registration", str(st))
        check("path is free", st.get("registration_path") == "free")
        # And the account genuinely works without paying.
        r = await c.get(f"{BASE}/products", headers=uh)
        check("free account can shop", r.status_code == 200, f"HTTP {r.status_code}")

        # ── Scenario 4: Google account → Continue Without Fee ────────────
        gh, gid, _ = await make_user(c, "google", google=True)
        gphone = ("8" + str(uuid.uuid4().int)[:9])[:10]
        await c.post(f"{BASE}/auth/signup-gate/confirm", json={"phone": gphone}, headers=gh)
        r = await c.post(f"{BASE}/payment/skip-subscription", headers=gh)
        check("Google account can continue free", r.status_code == 200, f"HTTP {r.status_code}")
        gst = (await c.get(f"{BASE}/auth/signup-gate/status", headers=gh)).json()
        check("Google auth provider preserved", gst.get("auth_provider") == "google", str(gst.get("auth_provider")))
        check("Google free path recorded", gst.get("registration_status") == "free_registration")

        # ── Scenario 2: Google account → Pay ₹118 ────────────────────────
        ph, pid, pemail = await make_user(c, "paid", google=True)
        pphone = ("7" + str(uuid.uuid4().int)[:9])[:10]
        await c.post(f"{BASE}/auth/signup-gate/confirm", json={"phone": pphone}, headers=ph)
        cfg = (await c.get(f"{BASE}/payment/config", headers=ph)).json()
        check("amount payable is ₹118", float(cfg.get("amount")) == 118.0, str(cfg.get("amount")))
        check("amount in paise matches", int(cfg.get("amount_paise")) == 11800, str(cfg.get("amount_paise")))

        order = await c.post(f"{BASE}/payment/create-order", headers=ph)
        check("order created", order.status_code == 200, f"HTTP {order.status_code}")
        od = order.json() if order.status_code == 200 else {}
        check("unique order reference stored", bool(od.get("order_id")), str(od)[:80])

        # Scenario 6: a callback with no real order behind it.
        r = await c.post(f"{BASE}/payment/verify", json={
            "razorpay_order_id": "order_does_not_exist_" + uuid.uuid4().hex[:8],
            "razorpay_payment_id": "pay_forged",
            "razorpay_signature": "forged-signature",
        }, headers=ph)
        check("callback for an unknown order refused", r.status_code >= 400, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/payment/verify", json={
            "razorpay_order_id": od.get("order_id", "x"),
            "razorpay_payment_id": "",
            "razorpay_signature": "",
        }, headers=ph)
        check("callback with no gateway fields refused", r.status_code >= 400, f"HTTP {r.status_code}")
        doc = await db.users.find_one({"id": pid}, {"_id": 0})
        check("account not marked paid by a bad callback", not doc.get("registration_paid"))
        # NOTE: signature HMAC is enforced only when real Razorpay keys are
        # configured; this preview runs in sandbox mode, where the gateway
        # itself is simulated. Live-mode signature checking is in
        # server.py /payment/verify and was not modified.

        # The real (mock-mode) path, then the duplicate callback.
        r = await c.post(f"{BASE}/payment/mock-success", json={"order_id": od.get("order_id")}, headers=ph)
        if r.status_code == 404:
            r = await c.post(f"{BASE}/payment/verify", json={
                "razorpay_order_id": od.get("order_id"),
                "razorpay_payment_id": "pay_mock_" + uuid.uuid4().hex[:10],
                "razorpay_signature": "mock",
            }, headers=ph)
        paid_ok = r.status_code == 200
        check("payment completes in sandbox mode", paid_ok, f"HTTP {r.status_code}")
        if paid_ok:
            doc = await db.users.find_one({"id": pid}, {"_id": 0})
            check("account marked paid only after verification", bool(doc.get("registration_paid")))
            pst = (await c.get(f"{BASE}/auth/signup-gate/status", headers=ph)).json()
            check("status is payment_success", pst.get("registration_status") == "payment_success", str(pst))
            check("path is paid", pst.get("registration_path") == "paid")
            before = await db.transactions.count_documents({"user_id": pid})
            # Scenario 7: repeat the same callback.
            again = await c.post(f"{BASE}/payment/verify", json={
                "razorpay_order_id": od.get("order_id"),
                "razorpay_payment_id": "pay_mock_repeat",
                "razorpay_signature": "mock",
            }, headers=ph)
            after_count = await db.transactions.count_documents({"user_id": pid})
            check("duplicate callback creates no extra money rows",
                  after_count == before, f"{before} → {after_count} (HTTP {again.status_code})")

        # ── Scenario 8: already verified account re-opens the screen ─────
        st = (await c.get(f"{BASE}/auth/signup-gate/status", headers=ph)).json()
        check("verified account is not asked again", st.get("required") is False)

        # ── Scenario 10: logout then login again ─────────────────────────
        r = await c.post(f"{BASE}/auth/logout", headers=ph)
        check("logout accepted", r.status_code in (200, 204), f"HTTP {r.status_code}")
        h2 = await login(c, {"email": pemail, "password": PW})
        st = (await c.get(f"{BASE}/auth/signup-gate/status", headers=h2)).json()
        check("state survives a re-login", st.get("registration_status") == "payment_success", str(st))
        check("phone still on the account after re-login", st.get("phone") == pphone)

        # ── Nothing unrelated broke ──────────────────────────────────────
        for path in ("/products", "/cart", "/orders/me", "/wallet/topup/config"):
            r = await c.get(f"{BASE}{path}", headers=h2)
            check(f"{path} still works", r.status_code == 200, f"HTTP {r.status_code}")
        r = await c.get(f"{BASE}/admin/sim-binding/overview", headers=ah)
        check("admin tools still work", r.status_code == 200, f"HTTP {r.status_code}")

        # Clean up the accounts this test created.
        for email in (uemail, pemail):
            await db.users.delete_many({"email": email})
        await db.users.delete_many({"email": {"$regex": "^regflow\\."}})
        await db.truecaller_states.delete_many({"user_id": {"$in": [uid, other_id, gid, pid]}})

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)


if __name__ == "__main__":
    asyncio.run(main())
