"""E2E verification for the Oct-2026 chat/broadcast fixes.

1. An admin broadcast creates a DEDICATED read-only announcement thread.
2. The user's real DM thread with the admin is untouched, so contact-support
   (and any normal send) still works after a broadcast.
3. Sending into the announcement thread is still rejected for non-admins.
4. POST /chat/{id}/messages returns fast (push/notification moved off the
   request path).

Run:  python -m tests.verify_oct2026_chat_updates
"""
import asyncio
import os
import time

import httpx

BASE = os.environ.get("E2E_BASE", "http://localhost:8001/api")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
BUYER = ("testbuyer@test.com", "Test@1234")


async def login(c: httpx.AsyncClient, email: str, pw: str) -> str:
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    return r.json()["token"]


async def main() -> None:
    fails = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'} — {name}{f' :: {detail}' if detail else ''}")
        if not ok:
            fails.append(name)

    async with httpx.AsyncClient(timeout=60) as c:
        atok = await login(c, *ADMIN)
        btok = await login(c, *BUYER)
        ah = {"Authorization": f"Bearer {atok}"}
        bh = {"Authorization": f"Bearer {btok}"}

        # ── 1. Send a broadcast to every plain user ──────────────────────
        r = await c.post(
            f"{BASE}/admin/broadcasts", headers=ah,
            json={"title": "E2E check", "message": "Oct-2026 verification broadcast",
                  "audience": "all"},
        )
        check("broadcast created", r.status_code == 201, f"{r.status_code} {r.text[:160]}")

        # ── 2. Buyer's thread list: announcement channel is separate ─────
        r = await c.get(f"{BASE}/chat/threads", headers=bh)
        threads = r.json().get("threads", [])
        ann = [t for t in threads if t.get("is_announcement")]
        check("buyer sees an announcement channel", len(ann) >= 1, f"{len(ann)} found")

        # ── 3. Buyer cannot post into the announcement channel ───────────
        if ann:
            r = await c.post(
                f"{BASE}/chat/{ann[0]['id']}/messages", headers=bh,
                json={"text": "can I reply here?"},
            )
            check("announcement channel is read-only for buyer", r.status_code == 403,
                  f"{r.status_code} {r.text[:120]}")

        # ── 4. Buyer can still open a real DM with support ───────────────
        r = await c.post(f"{BASE}/chat/contact-support", headers=bh, json={"message": ""})
        check("contact-support returns a thread", r.status_code == 200 and r.json().get("count", 0) >= 1,
              f"{r.status_code} {r.text[:160]}")
        support_threads = r.json().get("threads", []) if r.status_code == 200 else []
        ann_ids = {t["id"] for t in ann}
        check("support thread is NOT the announcement channel",
              all(t["thread_id"] not in ann_ids for t in support_threads))

        # ── 5. Buyer can actually SEND to the admin after a broadcast ────
        if support_threads:
            tid = support_threads[0]["thread_id"]
            t0 = time.perf_counter()
            r = await c.post(
                f"{BASE}/chat/{tid}/messages", headers=bh,
                json={"text": "E2E: user → admin after broadcast"},
            )
            elapsed = time.perf_counter() - t0
            check("buyer can message the admin after a broadcast", r.status_code == 200,
                  f"{r.status_code} {r.text[:160]}")
            check("send latency under 1.5s", elapsed < 1.5, f"{elapsed*1000:.0f} ms")

        # ── 6. Branding exposes the admin-editable WhatsApp number ───────
        r = await c.get(f"{BASE}/branding")
        check("branding exposes support_whatsapp", bool(r.json().get("support_whatsapp")),
              str(r.json().get("support_whatsapp")))

    print("\n" + ("ALL PASSED" if not fails else f"FAILURES: {fails}"))


if __name__ == "__main__":
    asyncio.run(main())
