"""
Iter83 · direct Mongo pipeline check — channel routing, legacy remap,
opted-out logging and new-device duplicate protection.
Run: cd /app/backend && python tests/iter83_direct_pipeline.py
"""
from __future__ import annotations
import asyncio
import sys
import time
import types
import uuid
from unittest.mock import MagicMock

sys.path.insert(0, "/app/backend")


class Req:
    """Minimal fake fastapi.Request replacement."""
    def __init__(self, headers=None, host="1.2.3.4"):
        self.headers = headers or {}
        self.client = types.SimpleNamespace(host=host)


async def main():
    from core.db import db
    from core.notifications import create_notification
    from core.login_history import record_login

    # pick a real user (buyer)
    user = await db.users.find_one({"email": "testbuyer@test.com"}, {"_id": 0})
    assert user, "buyer not found"
    uid = user["id"]
    fails = []

    # ── 1. Channel routing per kind ─────────────────────────────────────
    marker = f"iter83-{uuid.uuid4().hex[:8]}"
    kinds = [
        ("order", "orders_v2"),
        ("chat", "chat_v2"),
        ("announcement", "orders_v2"),
        ("security", "orders_v2"),
        ("vendor", "orders_v2"),
        ("cashback", "orders_v2"),
    ]
    # make sure prefs allow through
    await db.users.update_one({"id": uid}, {"$set": {"notification_prefs": {
        "orders": True, "chats": True, "offers": True,
        "login_alerts": True, "vendor_new_order": True,
    }}})
    for kind, expected_channel in kinds:
        title = f"{marker}-{kind}"
        await create_notification(uid, kind, title, "body-" + kind, push=True)
        # give it a beat
        await asyncio.sleep(0.05)
        log = await db.push_log.find_one({"title": title}, sort=[("created_at", -1)])
        if not log:
            fails.append(f"[routing] no push_log for kind={kind}"); continue
        if log.get("channel_id") != expected_channel:
            fails.append(f"[routing] kind={kind} channel={log.get('channel_id')} expected={expected_channel}")

    # ── 2. Legacy remap ('chat' -> chat_v2, 'default' -> orders_v2) ────
    from routes.push import send_push
    for legacy, expected in (("chat", "chat_v2"), ("default", "orders_v2")):
        title = f"{marker}-legacy-{legacy}"
        await send_push([uid], {"title": title, "message": "x", "channel_id": legacy})
        await asyncio.sleep(0.05)
        log = await db.push_log.find_one({"title": title}, sort=[("created_at", -1)])
        if not log or log.get("channel_id") != expected:
            fails.append(f"[legacy] {legacy} -> {log.get('channel_id') if log else 'none'} expected {expected}")

    # ── 3. opted_out logging ────────────────────────────────────────────
    await db.users.update_one({"id": uid}, {"$set": {"notification_prefs.orders": False}})
    title = f"{marker}-optout"
    from routes.push import send_push as sp2
    res = await sp2([uid], {"title": title, "message": "x"}, category="orders")
    log = await db.push_log.find_one({"title": title})
    if not log or log.get("stage") != "skipped" or log.get("result") != "opted_out":
        fails.append(f"[opt-out] stage={log.get('stage') if log else 'none'} "
                     f"result={log.get('result') if log else 'none'} rc={res}")
    # restore prefs
    await db.users.update_one({"id": uid}, {"$set": {"notification_prefs.orders": True}})

    # ── 4. New-device duplicate protection (record_login) ──────────────
    fp = f"android-iter83-{uuid.uuid4().hex[:8]}"
    # first ensure account already has some login history (else is_new_device=False)
    await db.login_history.insert_one({
        "id": str(uuid.uuid4()), "user_id": uid, "device_fp": "priming-" + uuid.uuid4().hex,
        "device_label": "primer", "session_id": "sid-old", "created_at": "2026-01-01T00:00:00+00:00",
    })
    req = Req(headers={
        "x-device-fp": fp, "x-device-name": "Iter83Phone",
        "user-agent": "Iter83Test/1.0 (Android 14)",
    })
    # count push_log rows for this user before
    ts_before = time.time()
    await record_login(user, req, sid="sid-iter83-" + uuid.uuid4().hex, method="password")
    await asyncio.sleep(0.15)
    # find new push_log rows targeting this uid inserted after ts_before with
    # a "New device signed in" title (both duplicates carried that title before fix)
    rows = await db.push_log.find(
        {"recipients": uid, "title": "New device signed in"},
        {"_id": 0}
    ).sort("created_at", -1).limit(5).to_list(5)
    # keep only ones from this run (created_at is ISO ts newer than ts_before iso)
    import datetime as _dt
    thr = _dt.datetime.utcfromtimestamp(ts_before - 2).isoformat()
    fresh = [r for r in rows if (r.get("created_at") or "") >= thr]
    if len(fresh) != 1:
        fails.append(f"[new-device] expected exactly ONE push_log, got {len(fresh)}: "
                     f"{[r.get('idempotency_key') for r in fresh]}")

    # ── 5. In-app notification row also created (untouched) ────────────
    n = await db.notifications.find_one({"user_id": uid, "kind": "security",
                                          "title": "New device signed in"},
                                         sort=[("created_at", -1)])
    if not n:
        fails.append("[in-app] no security notification row was written")

    # cleanup
    await db.push_log.delete_many({"title": {"$regex": f"^{marker}"}})
    await db.login_history.delete_many({"user_id": uid, "device_fp": {"$regex": "iter83|priming"}})
    await db.notifications.delete_many({"user_id": uid, "kind": "security",
                                         "title": "New device signed in",
                                         "created_at": {"$gte": thr}})

    if fails:
        print("FAILURES:")
        for f in fails: print(" ·", f)
        sys.exit(1)
    print("iter83 direct pipeline check: ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
