"""Iter100 — membership batch API e2e: checkout under a per-shop cashback
override, frozen rate, delivery settlement (no dup rows), product re-approval
hiding from the public shop, reveal-phone real POST, admin config guards,
member-only applications, and the net-worth / in_sync invariants.
Run: cd /app/backend && python3 tests/iter100_membership_e2e.py
"""
import asyncio, os, sys, time, uuid
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
    RES.append((n, ok)); print(("PASS" if ok else "FAIL"), "·", n, ("— " + str(extra)[:300]) if extra else "")


async def login(c, e, p):
    for _ in range(3):
        r = await c.post(f"{BASE}/auth/login", json={"email": e, "password": p})
        if r.status_code == 200:
            return {"Authorization": "Bearer " + r.json()["token"]}
        print("login", e, r.status_code, r.text[:100]); await asyncio.sleep(20)
    raise SystemExit("login failed")


async def main():
    s_doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "cashback_enabled": 1})
    orig_cb_enabled = s_doc.get("cashback_enabled", True)
    pid = None
    buyer = await db.users.find_one({"email": BUYER}, {"_id": 0, "id": 1, "wallet_balance": 1})
    async with httpx.AsyncClient(timeout=90) as c:
        ah = await login(c, "support@slangcart.com", "3)Ywxtic"); await asyncio.sleep(2)
        vh = await login(c, "testvendor@test.com", "Test@1234"); await asyncio.sleep(2)
        bh = await login(c, BUYER, "Test@1234")
        nw0 = (await c.get(f"{BASE}/vendor/me/net-worth", headers=vh)).json()
        print("vendor net-worth before:", {k: nw0.get(k) for k in ("in_sync", "unledgered_difference")})
        try:
            # ── seed a TEST_ product with NO cashback_pct ──
            pid = f"TEST_i100_{uuid.uuid4().hex[:8]}"
            base = await db.products.find_one({"id": "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"}, {"_id": 0})
            base.update({"id": pid, "name": "TEST_i100 Widget", "price": 100.0, "stock": 20,
                         "is_published": True, "review_status": "approved",
                         "created_at": datetime.now(timezone.utc).isoformat()})
            base.pop("cashback_pct", None)
            await db.products.insert_one(base)
            # cashback is globally OFF in this env → per-shop override silently gives 0
            if not orig_cb_enabled:
                print("NOTE: settings.cashback_enabled=False — enabling temporarily")
                await db.settings.update_one({"id": "global"}, {"$set": {"cashback_enabled": True}})
            r = await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}", headers=ah,
                            json={"cashback_pct": 7.5, "clear": []})
            check("PUT per-shop cashback 7.5", r.status_code == 200, r.text[:150])
            # ── checkout (COD) ──
            await c.post(f"{BASE}/cart/clear", headers=bh)
            r = await c.post(f"{BASE}/cart/add", headers=bh, json={"product_id": pid, "qty": 2})
            check("cart add", r.status_code == 200, r.text[:150])
            addr = {"name": "CI Buyer", "phone": "9999999999", "line1": "1 Test St",
                    "city": "Srikalahasti", "state": "Andhra Pradesh", "pincode": "517644"}
            r = await c.post(f"{BASE}/orders/checkout", headers=bh,
                             json={"payment_method": "cod", "shipping_address": addr})
            check("checkout COD", r.status_code == 200, r.text[:300])
            oid = r.json()["orders"][0]["id"] if r.status_code == 200 else None
            if oid:
                o = await db.orders.find_one({"id": oid}, {"_id": 0})
                line = o["items"][0]
                check("order line frozen cashback_pct == shop override 7.5",
                      abs(float(line.get("cashback_pct") or 0) - 7.5) < .01, line.get("cashback_pct"))
                # change the rate → frozen line must not move
                await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}", headers=ah,
                            json={"cashback_pct": 2.0, "clear": []})
                o2 = await db.orders.find_one({"id": oid}, {"_id": 0, "items": 1})
                check("frozen line unchanged after rate change",
                      abs(float(o2["items"][0].get("cashback_pct") or 0) - 7.5) < .01, o2["items"][0].get("cashback_pct"))
                # deliver
                for st in ("confirmed", "shipped", "out_for_delivery", "delivered"):
                    rr = await c.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah, json={"status": st})
                    if rr.status_code != 200:
                        print("status", st, rr.status_code, rr.text[:200])
                rr = await c.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah, json={"status": "delivered"})
                print("re-deliver:", rr.status_code)
                await asyncio.sleep(2)
                cb_rows = await db.transactions.find(
                    {"$or": [{"order_id": oid}, {"related_order_id": oid}],
                     "type": {"$regex": "cashback"}}, {"_id": 0, "type": 1, "amount": 1, "status": 1, "user_id": 1}).to_list(20)
                print("cashback rows:", cb_rows)
                od = await db.orders.find_one({"id": oid}, {"_id": 0, "status": 1, "cashback_amount": 1, "cashback_status": 1, "cashback_total": 1})
                print("order after delivery:", od)
                check("order delivered", od.get("status") == "delivered", od)
                types = [x["type"] for x in cb_rows]
                check("no duplicate cashback rows", len(types) == len(set((x["type"], x["user_id"]) for x in cb_rows)), types)
                credited = sum(float(x["amount"]) for x in cb_rows if x["user_id"] == buyer["id"] and float(x["amount"]) > 0)
                print("buyer cashback credited (free account):", credited, "expected 15.0 if free accounts earn cashback")
            # ── product re-approval ──
            r = await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh, json={"price": 120.0})
            p = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1, "review_status": 1, "review_fields": 1})
            check("price edit → unpublished + pending", r.status_code == 200 and not p.get("is_published")
                  and p.get("review_status") == "pending", p)
            pub = (await c.get(f"{BASE}/products", params={"search": "TEST_i100", "limit": 50})).json()
            items = pub if isinstance(pub, list) else (pub.get("items") or pub.get("products") or [])
            check("pending product hidden from public GET /products", all(x.get("id") != pid for x in items), len(items))
            rd = await c.get(f"{BASE}/products/{pid}")
            check("pending product detail not publicly visible", rd.status_code in (403, 404), rd.status_code)
            r = await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh, json={"is_published": True})
            p = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1})
            check("vendor cannot self-publish", not p.get("is_published"), (r.status_code, p))
            r = await c.patch(f"{BASE}/admin/products/{pid}", headers=ah, json={"is_published": True})
            p = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1, "review_status": 1})
            check("admin approve → published + approved", p.get("is_published") and p.get("review_status") == "approved", p)
            r = await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh, json={"stock": 15})
            p = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1})
            check("stock-only edit keeps live", p.get("is_published") is True, p)
            r = await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh, json={"description": "changed text"})
            p = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1, "review_status": 1})
            print("description-only edit →", p)
            # ── reveal-phone real POST ──
            svc = await db.users.find_one({"is_service_provider": True, "service_status": "approved"}, {"_id": 0, "id": 1})
            if not svc:
                svc = await db.services.find_one({}, {"_id": 0, "id": 1}) if hasattr(db, "services") else None
            print("service provider for reveal:", svc)
            if svc:
                await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": True}})
                w0 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
                rr = await c.post(f"{BASE}/services/{svc['id']}/reveal-phone", headers=bh)
                w1 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
                check("member reveal-phone: 200 & no wallet debit", rr.status_code == 200 and abs(w1 - w0) < .01,
                      (rr.status_code, rr.text[:200], w0, w1))
                # free_reveals=false → member pays
                g = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
                await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"free_reveals": False})
                rc = (await c.get(f"{BASE}/services/reveal-config", headers=bh)).json()
                check("free_reveals=false → member charged", float(rc.get("total") or 0) > 0, rc)
                await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"free_reveals": True})
                await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": False}})
                print("admin sub config keys:", list(g.keys())[:30])
            # ── admin config guard ──
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"invite_bonus": 80})
            check("invite bonus > platform share refused 400", r.status_code == 400, r.status_code)
            pc = (await c.get(f"{BASE}/subscription/config", headers=bh)).json()
            check("refused invite bonus NOT persisted", abs(float(pc.get("invite_bonus") or 0) - 25) < .01, pc.get("invite_bonus"))
            await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"invite_bonus": 25})
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"cashback_pct": 150})
            check("cashback pct 150 refused", r.status_code in (400, 422), (r.status_code, r.text[:120]))
            r = await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"price": -5})
            check("negative price refused", r.status_code in (400, 422), (r.status_code, r.text[:120]))
            # buyer (non-admin) cannot touch admin config
            r = await c.put(f"{BASE}/admin/subscription/config", headers=bh, json={"invite_bonus": 1})
            check("non-admin refused on admin config", r.status_code in (401, 403), r.status_code)
            # ── member-only applications ──
            for path in ("/vendor/apply", "/service/apply", "/delivery-partner/apply"):
                r = await c.post(f"{BASE}{path}", headers=bh, json={})
                check(f"free account refused at {path}", r.status_code in (402, 403), (r.status_code, r.text[:120]))
        finally:
            await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": False}})
            await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}", headers=ah, json={"clear": ["cashback_pct"]})
            await db.settings.update_one({"id": "global"}, {"$set": {"cashback_enabled": orig_cb_enabled}})
            await c.put(f"{BASE}/admin/subscription/config", headers=ah,
                        json={"free_reveals": True, "cashback_pct": 50,
                              "invite_bonus": 25})
            if pid:
                await db.products.delete_one({"id": pid})
            await c.post(f"{BASE}/cart/clear", headers=bh)
            nw1 = (await c.get(f"{BASE}/vendor/me/net-worth", headers=vh)).json()
            check("vendor shop wallet in_sync after tests",
                  nw1.get("in_sync") is True and abs(float(nw1.get("unledgered_difference") or 0)) < .01,
                  {k: nw1.get(k) for k in ("in_sync", "unledgered_difference")})
            fn = await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)
            fj = fn.json() if fn.status_code == 200 else {}
            print("admin net-worth:", fn.status_code, {k: fj.get(k) for k in list(fj.keys())[:12]})
            vo = await db.vendor_outstanding.aggregate([{"$match": {"status": {"$nin": ["settled", "closed", "paid"]}}},
                                                        {"$group": {"_id": None, "t": {"$sum": "$amount"}}}]).to_list(1)
            print("open vendor_outstanding sum:", vo)
            b2 = await db.users.find_one({"email": BUYER}, {"wallet_balance": 1})
            print("buyer wallet before/after:", buyer["wallet_balance"], b2["wallet_balance"])
    print(f"RESULT {sum(1 for _, o in RES if o)}/{len(RES)} pass")

asyncio.run(main())
