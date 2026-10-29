"""SIM-binding module — security and policy tests (Oct 2026).

Covers the things that actually matter:
  • a client cannot self-declare verification (no/forged/replayed/expired nonce)
  • a browser cannot claim a SIM reading
  • local SIM presence never sets `number_verified`
  • a SIM change wipes any number proof and demands a re-check
  • the chat gate blocks chat WRITES and nothing else
  • reading chat history keeps working while blocked
  • shopping / wallet / orders are untouched while blocked
  • device-link codes are single-use, expiring and same-account only
  • policy cannot demand a level the platform can't deliver
  • audit rows never contain a nonce

Run:  python3 tests/test_sim_binding.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa: E402
from core import sim_binding as sb  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
USER = {"email": "testbuyer@test.com", "password": "Test@1234"}
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}


async def login(c, creds):
    r = await c.post(f"{BASE}/auth/login", json=creds)
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


async def device_payload(c, h, state="SIM_PRESENT", platform="android", **kw):
    ch = (await c.post(f"{BASE}/sim-binding/challenge", json={"purpose": "sim_check"}, headers=h)).json()
    body = {
        "challenge_id": ch["challenge_id"],
        "nonce": ch["nonce"],
        "sim_state": state,
        "slot_count": 1,
        "has_esim": False,
        "mcc": "404",
        "mnc": "45",
        "platform": platform,
        "os_version": "14",
        "app_version": "1.0.0",
        "is_device": True,
    }
    body.update(kw)
    return body


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        uh = await login(c, USER)
        ah = await login(c, ADMIN)
        me = (await c.get(f"{BASE}/auth/me", headers=uh)).json()
        uid = me["id"]

        # Clean slate for this user.
        await db.sim_bindings.delete_many({"user_id": uid})
        await db.sim_challenges.delete_many({"user_id": uid})
        await db.app_settings.delete_one({"_id": sb.POLICY_DOC_ID})

        # ── 1. Client cannot self-declare ────────────────────────────────
        r = await c.post(
            f"{BASE}/sim-binding/verify",
            json={
                "challenge_id": "made-up", "nonce": "made-up", "sim_state": "SIM_PRESENT",
                "slot_count": 1, "platform": "android",
            },
            headers=uh,
        )
        check("forged challenge rejected", r.status_code == 400, f"HTTP {r.status_code}")

        body = await device_payload(c, uh)
        bad = dict(body, nonce="wrong-nonce")
        r = await c.post(f"{BASE}/sim-binding/verify", json=bad, headers=uh)
        check("wrong nonce rejected", r.status_code == 400, f"HTTP {r.status_code}")

        # The original nonce is still unused, so the honest attempt works.
        r = await c.post(f"{BASE}/sim-binding/verify", json=body, headers=uh)
        check("valid device check accepted", r.status_code == 200, f"HTTP {r.status_code}")
        status = r.json() if r.status_code == 200 else {}
        check("level is sim_presence only", status.get("level") == "sim_presence", str(status.get("level")))
        check("number NOT marked verified", status.get("number_verified") is False)
        check(
            "disclaimer present",
            "not proof" in (status.get("disclaimer") or ""),
        )

        # ── 2. Replay ────────────────────────────────────────────────────
        r = await c.post(f"{BASE}/sim-binding/verify", json=body, headers=uh)
        check("replayed nonce rejected", r.status_code == 400, f"HTTP {r.status_code}")

        # ── 3. Expiry ────────────────────────────────────────────────────
        body2 = await device_payload(c, uh)
        await db.sim_challenges.update_one(
            {"id": body2["challenge_id"]},
            {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()}},
        )
        r = await c.post(f"{BASE}/sim-binding/verify", json=body2, headers=uh)
        check("expired challenge rejected", r.status_code == 400, f"HTTP {r.status_code}")

        # ── 4. Another user's challenge ──────────────────────────────────
        body3 = await device_payload(c, ah)  # minted for the admin
        r = await c.post(f"{BASE}/sim-binding/verify", json=body3, headers=uh)
        check("other account's challenge rejected", r.status_code == 400, f"HTTP {r.status_code}")

        # ── 5. A browser cannot claim a SIM ──────────────────────────────
        webbody = await device_payload(c, uh, platform="web")
        r = await c.post(f"{BASE}/sim-binding/verify", json=webbody, headers=uh)
        check("web platform rejected", r.status_code == 400, f"HTTP {r.status_code}")

        # ── 6. Number proof needs a real provider ────────────────────────
        npbody = await device_payload(c, uh)
        r = await c.post(
            f"{BASE}/sim-binding/number-proof",
            json={
                "challenge_id": npbody["challenge_id"], "nonce": npbody["nonce"],
                "provider": "truecaller", "code": "fake", "code_verifier": "fake",
            },
            headers=uh,
        )
        check(
            "number proof refuses without provider",
            r.status_code in (503, 401),
            f"HTTP {r.status_code}",
        )
        st = (await c.get(f"{BASE}/sim-binding/status", headers=uh)).json()
        check("still not number_verified", st.get("number_verified") is False)

        # ── 7. Chat gate — blocked when no SIM ───────────────────────────
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh, state="SIM_ABSENT"), headers=uh)
        st = (await c.get(f"{BASE}/sim-binding/status", headers=uh)).json()
        check("SIM_ABSENT ⇒ level none", st.get("level") == "none", str(st.get("level")))

        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=uh)
        gated = r.status_code == 403 and (r.json().get("detail") or {}).get("code") == "sim_verification_required"
        check("chat write blocked without SIM", gated, f"HTTP {r.status_code}")
        if gated:
            check(
                "block message is plain language",
                "SIM" in (r.json()["detail"]["message"] or ""),
                r.json()["detail"]["message"][:60],
            )

        # Reading must keep working — no conversation is ever lost.
        r = await c.get(f"{BASE}/chat/threads", headers=uh)
        check("chat history still readable while blocked", r.status_code == 200, f"HTTP {r.status_code}")

        # Everything outside chat must be untouched.
        for path in ("/products", "/wallet/topup/config", "/orders/me", "/cart"):
            r = await c.get(f"{BASE}{path}", headers=uh)
            check(f"{path} unaffected by gate", r.status_code == 200, f"HTTP {r.status_code}")

        # ── 8. Verified again ⇒ chat opens ───────────────────────────────
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=uh)
        check("chat write allowed once verified", r.status_code == 200, f"HTTP {r.status_code}")

        # ── 9. SIM change wipes proof and demands re-check ───────────────
        await sb.record_number_proof(uid, method="test", phone_last4="1234")
        st = (await c.get(f"{BASE}/sim-binding/status", headers=uh)).json()
        check("number proof recorded (fixture)", st.get("number_verified") is True)
        changed = await device_payload(c, uh, mcc="405", mnc="840")  # different carrier
        r = await c.post(f"{BASE}/sim-binding/verify", json=changed, headers=uh)
        after = r.json()
        check("SIM change detected", after.get("sim_changed") is True, str(after.get("sim_changed")))
        check("number proof dropped on SIM change", after.get("number_verified") is False)
        check("re-check demanded", after.get("revalidate_required") is True)

        # Back to a good state for the remaining tests.
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh, mcc="405", mnc="840"), headers=uh)

        # ── 10. No sensitive identifiers stored ──────────────────────────
        doc = await db.sim_bindings.find_one({"user_id": uid}, {"_id": 0})
        banned = {"imei", "imsi", "iccid", "sim_serial", "subscription_id", "msisdn"}
        check("no SIM identifiers stored", not (banned & set(doc.keys())), str(sorted(doc.keys()))[:120])
        check("carrier stored only as a fingerprint", len(doc.get("carrier_fp", "")) == 32)

        # ── 11. Audit never leaks a nonce ────────────────────────────────
        rows = await db.sim_audit.find({"user_id": uid}, {"_id": 0}).to_list(100)
        leaked = [r_ for r_ in rows if any(
            isinstance(v, str) and len(v) > 30 and ("nonce" in str(k) or "token" in str(k))
            for k, v in r_.items()
        )]
        check("audit rows carry no nonce/token", not leaked, str(len(leaked)))
        check("audit recorded rejections", any(r_["result"] == "rejected" for r_ in rows))

        # ── 12. Device linking ───────────────────────────────────────────
        link = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=uh)
        check("link code minted", link.status_code == 200, f"HTTP {link.status_code}")
        code = link.json().get("code") if link.status_code == 200 else ""
        r = await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": code}, headers=uh)
        check("verified phone can approve", r.status_code == 200, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": code}, headers=uh)
        check("link code single-use", r.status_code == 400, f"HTTP {r.status_code}")

        link2 = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=uh)
        code2 = link2.json()["code"]
        r = await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": code2}, headers=ah)
        check("cross-account claim refused", r.status_code in (403, 400), f"HTTP {r.status_code}")

        link3 = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=uh)
        await db.device_links.update_one(
            {"code": link3.json()["code"]},
            {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()}},
        )
        r = await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": link3.json()["code"]}, headers=uh)
        check("expired link code refused", r.status_code == 400, f"HTTP {r.status_code}")

        # ── 13. Policy clamp + admin view ────────────────────────────────
        r = await c.patch(
            f"{BASE}/admin/sim-binding/policy", json={"required_level": "number_verified"}, headers=ah
        )
        clamped = r.json() if r.status_code == 200 else {}
        if clamped.get("number_proof_available"):
            # A provider IS configured, so demanding confirmed numbers is a
            # real option and must be accepted as asked.
            check(
                "number_verified accepted when a provider is configured",
                clamped.get("required_level") == "number_verified"
                and clamped.get("clamped_to_sim_presence") is False,
                str(clamped.get("required_level")),
            )
        else:
            check(
                "policy clamped when no number provider",
                clamped.get("required_level") == "sim_presence"
                and clamped.get("clamped_to_sim_presence") is True,
                str(clamped.get("required_level")),
            )
        # Put the live policy back to the owner's setting before the chat
        # tests below — leaving "number_verified" behind would lock every real
        # user out of chat until they ran Truecaller.
        await c.patch(
            f"{BASE}/admin/sim-binding/policy", json={"required_level": "sim_presence"}, headers=ah
        )
        r = await c.patch(f"{BASE}/admin/sim-binding/policy", json={"required_level": "nonsense"}, headers=ah)
        check("unknown level refused", r.status_code == 400, f"HTTP {r.status_code}")

        r = await c.get(f"{BASE}/admin/sim-binding/overview", headers=ah)
        ov = r.json() if r.status_code == 200 else {}
        check("admin overview loads", r.status_code == 200, f"HTTP {r.status_code}")
        check("overview counts rejections", (ov.get("totals") or {}).get("rejected_attempts", 0) > 0)

        # A non-admin must never reach the admin view.
        r = await c.get(f"{BASE}/admin/sim-binding/overview", headers=uh)
        check("admin view refused for user", r.status_code in (401, 403), f"HTTP {r.status_code}")

        # ── 14. Enforcement off ⇒ chat open again ────────────────────────
        await c.patch(f"{BASE}/admin/sim-binding/policy", json={"enforce_chat": False}, headers=ah)
        await db.sim_bindings.update_one({"user_id": uid}, {"$set": {"sim_state": "SIM_ABSENT"}})
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=uh)
        check("gate off ⇒ chat open", r.status_code == 200, f"HTTP {r.status_code}")

        # ── 15. Admins are never locked out of support ───────────────────
        await c.patch(f"{BASE}/admin/sim-binding/policy", json={"enforce_chat": True}, headers=ah)
        r = await c.get(f"{BASE}/chat/threads", headers=ah)
        check("admin chat reachable", r.status_code == 200, f"HTTP {r.status_code}")

        # ── 16. Iter103 bypass #1 — a web link must not outlive the phone ─
        await db.sim_bindings.update_one({"user_id": uid}, {"$set": {"sim_state": "SIM_PRESENT"}})
        # Twice: the first run may land on a different carrier than the last
        # test left behind, which is correctly treated as a swap. The second
        # run is a steady state.
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        link = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=uh)
        await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": link.json()["code"]}, headers=uh)
        web = dict(uh, **{"X-Client-Platform": "web"})
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=web)
        check("linked browser can chat", r.status_code == 200, f"HTTP {r.status_code}")
        # Phone now reports no SIM — the browser must lose access at once.
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh, state="SIM_ABSENT"), headers=uh)
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=web)
        check("web link dies with the phone's SIM", r.status_code == 403, f"HTTP {r.status_code}")
        doc = await db.sim_bindings.find_one({"user_id": uid}, {"_id": 0})
        check("web link cleared on SIM loss", "web_link_expires_at" not in doc)

        # Revalidation must do the same.
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        link = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=uh)
        await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": link.json()["code"]}, headers=uh)
        await c.post(f"{BASE}/sim-binding/revalidate", json={"reason": "test"}, headers=uh)
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=web)
        check("web link dies on revalidation", r.status_code == 403, f"HTTP {r.status_code}")

        # ── 17. Iter103 bypass #3 — a browser needs its OWN link ─────────
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=uh)
        check("verified phone can chat", r.status_code == 200, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=web)
        check("unlinked browser blocked even when phone passes", r.status_code == 403, f"HTTP {r.status_code}")
        if r.status_code == 403:
            check(
                "browser gets the linking instruction",
                "link" in (r.json()["detail"]["message"] or "").lower(),
                r.json()["detail"]["message"][:60],
            )
        # A browser UA with no platform header must be treated as a browser.
        ua_web = dict(uh, **{"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/131 Safari/537.36"})
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=ua_web)
        check("browser detected by user-agent", r.status_code == 403, f"HTTP {r.status_code}")

        # Per-code polling: the browser's own code reports its real state.
        link = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=web)
        code = link.json()["code"]
        st = (await c.get(f"{BASE}/sim-binding/device-link/{code}", headers=web)).json()
        check("fresh code is not claimed", st.get("claimed") is False, str(st))
        await c.post(f"{BASE}/sim-binding/device-link/claim", json={"code": code}, headers=uh)
        st = (await c.get(f"{BASE}/sim-binding/device-link/{code}", headers=web)).json()
        check("code reports claimed after the phone approves", st.get("claimed") is True, str(st))
        r = await c.get(f"{BASE}/sim-binding/device-link/not-a-code", headers=web)
        check("unknown code 404s", r.status_code == 404, f"HTTP {r.status_code}")

        # ── 18. Iter103 bypass #2 — every chat write is gated ────────────
        thread_id = ""
        threads = (await c.get(f"{BASE}/chat/threads", headers=uh)).json()
        rows = threads if isinstance(threads, list) else threads.get("threads") or []
        if rows:
            thread_id = rows[0].get("id") or ""
        msg_id = ""
        if thread_id:
            m = await c.post(f"{BASE}/chat/{thread_id}/messages", json={"text": "gate probe"}, headers=uh)
            msg_id = (m.json() or {}).get("id", "") if m.status_code == 200 else ""

        await db.sim_bindings.update_one({"user_id": uid}, {"$set": {"sim_state": "SIM_ABSENT"}})
        if msg_id:
            r = await c.patch(f"{BASE}/chat/messages/{msg_id}", json={"text": "edited while blocked"}, headers=uh)
            check("message EDIT is gated", r.status_code == 403, f"HTTP {r.status_code}")
        prod = (await c.get(f"{BASE}/products", headers=uh)).json()
        plist = prod if isinstance(prod, list) else prod.get("products") or []
        if plist:
            pid = plist[0]["id"]
            r = await c.post(f"{BASE}/products/{pid}/questions", json={"text": "gate probe?"}, headers=uh)
            check("product question is gated", r.status_code == 403, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/chat/request", json={"to_user_id": "someone", "message": "hi"}, headers=uh)
        check("chat request is gated", r.status_code == 403, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/chat/request/does-not-exist/accept", headers=uh)
        check("request ACCEPT is gated", r.status_code == 403, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/orders/no-such-order/chat-vendor", headers=uh)
        check("order chat-vendor is gated", r.status_code == 403, f"HTTP {r.status_code}")

        # ── 19. Re-inserting the SAME SIM is not a "change" ───────────────
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        await c.post(
            f"{BASE}/sim-binding/verify",
            json=await device_payload(c, uh, state="SIM_ABSENT", mcc="", mnc="", slot_count=0),
            headers=uh,
        )
        again = await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        check(
            "same SIM removed and re-inserted is not a swap",
            again.json().get("sim_changed") is False,
            str(again.json().get("sim_changed")),
        )
        check("and it passes again straight away", again.json().get("meets_requirement") is True)

        # ── 20. Iter104 — a browser must not approve its OWN code ────────
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        await c.post(f"{BASE}/sim-binding/verify", json=await device_payload(c, uh), headers=uh)
        await db.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})
        mine = await c.post(f"{BASE}/sim-binding/device-link/start", json={}, headers=web)
        r = await c.post(
            f"{BASE}/sim-binding/device-link/claim", json={"code": mine.json()["code"]}, headers=web
        )
        check("browser cannot approve its own link code", r.status_code == 403, f"HTTP {r.status_code}")
        ua_claim = dict(uh, **{"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36"})
        r = await c.post(
            f"{BASE}/sim-binding/device-link/claim", json={"code": mine.json()["code"]}, headers=ua_claim
        )
        check("browser user-agent cannot approve either", r.status_code == 403, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=web)
        check("self-claim attempt did not open browser chat", r.status_code == 403, f"HTTP {r.status_code}")
        # The real flow still works: the APP approves it.
        r = await c.post(
            f"{BASE}/sim-binding/device-link/claim", json={"code": mine.json()["code"]}, headers=uh
        )
        check("the app can still approve the browser's code", r.status_code == 200, f"HTTP {r.status_code}")
        r = await c.post(f"{BASE}/chat/contact-support", json={"message": "hi"}, headers=web)
        check("browser chats after the phone approves", r.status_code == 200, f"HTTP {r.status_code}")

        # Leave the policy enforcing (owner's choice) and the user verified.
        await db.sim_bindings.update_one({"user_id": uid}, {"$set": {"sim_state": "SIM_PRESENT"}})
        await db.sim_bindings.update_one({"user_id": uid}, {"$unset": {"web_link_expires_at": ""}})

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)


if __name__ == "__main__":
    asyncio.run(main())
