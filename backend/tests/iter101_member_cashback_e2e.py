"""Iter101 — free-account vs member shopping cashback (real COD orders), admin
subscription-config guard (no persist on 400), service/apply 403, ledger ties.
Restores settings, per-shop override and the testbuyer flag.
Run: cd /app/backend && python3 tests/iter101_member_cashback_e2e.py
"""
import asyncio, os, sys, uuid
from datetime import datetime, timezone
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa


def _env(p, k):
    for ln in open(p):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
BUYER = "testbuyer@test.com"
RES = []


def check(n, ok, extra=""):
    RES.append((n, ok)); print(("PASS" if ok else "FAIL"), "·", n, ("— " + str(extra)[:300]) if extra != "" else "")


async def login(c, e, p):
    for _ in range(3):
        r = await c.post(f"{BASE}/auth/login", json={"email": e, "password": p})
        if r.status_code == 200:
            return {"Authorization": "Bearer " + r.json()["token"]}
        print("login", e, r.status_code, r.text[:100]); await asyncio.sleep(25)
    raise SystemExit("login failed")


async def cb_rows(oid):
    return await db.transactions.find({"$or": [{"order_id": oid}, {"related_order_id": oid}],
                                       "type": {"$regex": "cashback"}},
                                      {"_id": 0, "type": 1, "amount": 1, "user_id": 1, "idempotency_key": 1}).to_list(50)


async def order_and_deliver(c, bh, ah, pid, qty=2):
    await c.post(f"{BASE}/cart/clear", headers=bh)
    r = await c.post(f"{BASE}/cart/add", headers=bh, json={"product_id": pid, "qty": qty})
    assert r.status_code == 200, r.text
    addr = {"name": "CI Buyer", "phone": "9999999999", "line1": "1 Test St",
            "city": "Srikalahasti", "state": "Andhra Pradesh", "pincode": "517644"}
    r = await c.post(f"{BASE}/orders/checkout", headers=bh, json={"payment_method": "cod", "shipping_address": addr})
    check("checkout COD 200", r.status_code == 200, r.text[:200])
    oid = r.json()["orders"][0]["id"]
    for st in ("confirmed", "shipped", "out_for_delivery", "delivered", "delivered"):
        await c.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah, json={"status": st})
    await asyncio.sleep(2)
    return oid


async def main():
    s_doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    orig_cb_enabled = s_doc.get("cashback_enabled", True)
    buyer = await db.users.find_one({"email": BUYER}, {"_id": 0, "id": 1, "wallet_balance": 1, "registration_paid": 1})
    orig_paid = buyer.get("registration_paid")
    pid = None
    async with httpx.AsyncClient(timeout=90) as c:
        ah = await login(c, "support@slangcart.com", "3)Ywxtic"); await asyncio.sleep(3)
        vh = await login(c, "testvendor@test.com", "Test@1234"); await asyncio.sleep(3)
        bh = await login(c, BUYER, "Test@1234")
        cfg0 = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
        print("admin sub config:", {k: v for k, v in cfg0.items() if k != "benefits"})
        try:
            # ── FIX 8 — applications refused 403 for a free account ──
            for path in ("/service/apply", "/vendor/apply", "/delivery-partner/apply"):
                r = await c.post(f"{BASE}{path}", headers=bh, json={})
                check(f"FIX8 free account {path} empty body → 422/403 (body validated first; valid-body 403 is in iter101_apply_receivables.py)", r.status_code in (403, 422), (r.status_code, r.text[:120]))
            r = await c.post(f"{BASE}/service/apply", headers=bh,
                             json={"service_type": "Plumber", "name": "x", "phone": "9999999999", "city": "x"})
            check("FIX8 free account /service/apply partial body → 422/403", r.status_code in (403, 422), (r.status_code, r.text[:120]))

            # ── FIX 5 — config guard ──
            ib0 = float(cfg0.get("invite_bonus") or 0)
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"invite_bonus": 80})
            check("FIX5 oversized invite_bonus 80 → 400", r.status_code == 400, (r.status_code, r.text[:160]))
            g = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
            check("FIX5 refused bonus NOT persisted (admin GET)", abs(float(g.get("invite_bonus") or 0) - ib0) < .01, g.get("invite_bonus"))
            pc = (await c.get(f"{BASE}/subscription/config", headers=bh)).json()
            check("FIX5 refused bonus NOT persisted (public GET)", abs(float(pc.get("invite_bonus") or 0) - ib0) < .01, pc.get("invite_bonus"))
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"invite_bonus": 55})
            check("FIX5 bonus 55 refused at cashback 50%", r.status_code == 400, r.status_code)
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"cashback_pct": 40, "invite_bonus": 55})
            g = r.json() if r.status_code == 200 else {}
            check("FIX5 lowering cashback_pct to 40 allows bonus 55", r.status_code == 200 and float(g.get("invite_bonus") or 0) == 55
                  and float(g.get("cashback_pct") or 0) == 40, (r.status_code, r.text[:160]))
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"cashback_pct": 60})
            check("FIX5 raising cashback to 60 with bonus 55 → 400", r.status_code == 400, r.status_code)
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah,
                            json={"price": 119, "free_reveals": False, "zero_ads": False, "priority_support": False,
                                  "support_whatsapp": "+91 90000 11111", "cashback_pct": 50, "invite_bonus": 25})
            g = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
            check("FIX5 price/switches/WhatsApp persisted",
                  r.status_code == 200 and float(g.get("price") or 0) == 119 and g.get("free_reveals") is False
                  and g.get("zero_ads") is False and g.get("priority_support") is False and g.get("support_whatsapp") == "919000011111",
                  {k: g.get(k) for k in ("price", "free_reveals", "zero_ads", "priority_support", "support_whatsapp")})
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah,
                            json={"price": float(cfg0.get("price") or 118), "free_reveals": cfg0.get("free_reveals", True),
                                  "zero_ads": cfg0.get("zero_ads", True), "priority_support": cfg0.get("priority_support", True),
                                  "support_whatsapp": cfg0.get("support_whatsapp") or "",
                                  "cashback_pct": float(cfg0.get("cashback_pct") or 50), "invite_bonus": ib0})
            check("FIX5 config restored", r.status_code == 200, r.status_code)

            # ── FIX 7 — shopping cashback member-only ──
            pid = f"TEST_i101_{uuid.uuid4().hex[:8]}"
            base = await db.products.find_one({"id": "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"}, {"_id": 0})
            base.update({"id": pid, "name": "TEST_i101 Widget", "price": 100.0, "stock": 20, "is_published": True,
                         "review_status": "approved", "created_at": datetime.now(timezone.utc).isoformat()})
            base.pop("cashback_pct", None)
            await db.products.insert_one(base)
            if not orig_cb_enabled:
                await db.settings.update_one({"id": "global"}, {"$set": {"cashback_enabled": True}})
            r = await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}", headers=ah, json={"cashback_pct": 5, "clear": []})
            check("per-shop override 5%", r.status_code == 200, r.text[:120])
            await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": False}})
            w0 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
            oid1 = await order_and_deliver(c, bh, ah, pid)
            o1 = await db.orders.find_one({"id": oid1}, {"_id": 0})
            check("FIX7 free account: every line cashback_pct 0", all(float(i.get("cashback_pct") or 0) == 0 for i in o1["items"]),
                  [i.get("cashback_pct") for i in o1["items"]])
            check("FIX7 free account: order delivered", o1.get("status") == "delivered", o1.get("status"))
            rows1 = await cb_rows(oid1)
            w1 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
            check("FIX7 free account: NO cashback rows & wallet unchanged", not rows1 and abs(w1 - w0) < .01, (rows1, w0, w1))

            await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": True}})
            oid2 = await order_and_deliver(c, bh, ah, pid)
            o2 = await db.orders.find_one({"id": oid2}, {"_id": 0})
            check("FIX7 member: line frozen 5%", all(abs(float(i.get("cashback_pct") or 0) - 5) < .01 for i in o2["items"]),
                  [i.get("cashback_pct") for i in o2["items"]])
            # extra delivery replays
            for _ in range(2):
                await c.patch(f"{BASE}/admin/orders/{oid2}/status", headers=ah, json={"status": "delivered"})
            await asyncio.sleep(2)
            rows2 = await cb_rows(oid2)
            w2 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
            buyer_cb = [x for x in rows2 if x["user_id"] == buyer["id"] and float(x["amount"]) > 0]
            print("member cashback rows:", rows2)
            check("FIX7 member: exactly one buyer credit of ₹10 (5% of 200)",
                  len(buyer_cb) == 1 and abs(float(buyer_cb[0]["amount"]) - 10) < .01, buyer_cb)
            check("FIX7 member: wallet +10 exactly", abs(w2 - w1 - 10) < .01, (w1, w2))
            check("FIX7 member: no duplicate (type,user) cashback rows",
                  len(rows2) == len({(x["type"], x["user_id"]) for x in rows2}), [x["type"] for x in rows2])
        finally:
            await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": orig_paid}})
            await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}", headers=ah, json={"clear": ["cashback_pct"]})
            await db.settings.update_one({"id": "global"}, {"$set": {"cashback_enabled": orig_cb_enabled}})
            if pid:
                await db.products.delete_one({"id": pid})
            await c.post(f"{BASE}/cart/clear", headers=bh)
            cfg1 = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
            check("subscription config identical to start",
                  all(cfg0.get(k) == cfg1.get(k) for k in ("price", "cashback_pct", "invite_bonus", "free_reveals",
                                                           "zero_ads", "priority_support", "support_whatsapp")),
                  {k: (cfg0.get(k), cfg1.get(k)) for k in ("price", "cashback_pct", "invite_bonus", "support_whatsapp")})
            # ── Regression ledger ties ──
            nw = (await c.get(f"{BASE}/vendor/me/net-worth", headers=vh)).json()
            check("vendor in_sync & unledgered 0", nw.get("in_sync") is True and abs(float(nw.get("unledgered_difference") or 0)) < .01,
                  {k: nw.get(k) for k in ("in_sync", "unledgered_difference")})
            fn = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
            vo = await db.vendor_outstanding.aggregate([{"$match": {"status": {"$nin": ["settled", "closed", "paid", "cleared"]}}},
                                                        {"$group": {"_id": None, "t": {"$sum": "$amount"}}}]).to_list(1)
            rec = fn.get("receivables")
            rec_v = rec.get("total") if isinstance(rec, dict) else rec
            print("admin receivables:", rec, "open vendor_outstanding:", vo)
            check("admin receivables == open vendor_outstanding",
                  abs(float(rec_v or 0) - float((vo[0]["t"] if vo else 0))) < .01, (rec_v, vo))
            dup_idem = await db.transactions.aggregate([{"$match": {"idempotency_key": {"$type": "string"}}},
                                                        {"$group": {"_id": "$idempotency_key", "n": {"$sum": 1}}},
                                                        {"$match": {"n": {"$gt": 1}}}]).to_list(5)
            check("no duplicate idempotency_key rows", not dup_idem, dup_idem)
            dup_ref = await db.transactions.aggregate([{"$match": {"reference_number": {"$type": "string", "$ne": ""}}},
                                                       {"$group": {"_id": {"t": "$type", "u": "$user_id", "r": "$reference_number"}, "n": {"$sum": 1}}},
                                                       {"$match": {"n": {"$gt": 1}}}]).to_list(10)
            check("no duplicate (type,user,reference_number) rows", not dup_ref, dup_ref)
            b2 = await db.users.find_one({"email": BUYER}, {"wallet_balance": 1, "registration_paid": 1})
            print("buyer wallet before/after:", buyer["wallet_balance"], b2["wallet_balance"], "paid flag:", b2.get("registration_paid"))
    print(f"RESULT {sum(1 for _, o in RES if o)}/{len(RES)} pass")

asyncio.run(main())
