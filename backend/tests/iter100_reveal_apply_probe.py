"""Iter100 — member reveal-phone POST (no debit) + member-only application gates.
Run: cd /app/backend && python3 tests/iter100_reveal_apply_probe.py"""
import asyncio, os, sys
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa
BASE = [l.split("=", 1)[1].strip().strip('"') for l in open("/app/frontend/.env") if l.startswith("EXPO_PUBLIC_BACKEND_URL=")][0].rstrip("/") + "/api"
BUYER = "testbuyer@test.com"
RES = []


def check(n, ok, extra=""):
    RES.append(ok); print(("PASS" if ok else "FAIL"), "·", n, ("— " + str(extra)[:250]) if extra else "")


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        bh = {"Authorization": "Bearer " + (await c.post(f"{BASE}/auth/login", json={"email": BUYER, "password": "Test@1234"})).json()["token"]}
        u = await db.users.find_one({"email": BUYER}, {"_id": 0, "id": 1, "wallet_balance": 1})
        revealed = {d["provider_id"] async for d in db.phone_reveal_invoices.find({"user_id": u["id"]}, {"provider_id": 1})}
        prov = await db.users.find_one({"is_service_provider": True, "id": {"$nin": list(revealed) + [u["id"]]}}, {"_id": 0, "id": 1, "name": 1})
        backup = []
        if not prov:  # every provider already revealed → temporarily park one existing invoice
            prov = await db.users.find_one({"is_service_provider": True, "id": {"$ne": u["id"]}}, {"_id": 0, "id": 1, "name": 1})
            backup = await db.phone_reveal_invoices.find({"user_id": u["id"], "provider_id": prov["id"]}).to_list(10)
            await db.phone_reveal_invoices.delete_many({"user_id": u["id"], "provider_id": prov["id"]})
        print("provider:", prov, "parked invoices:", len(backup))
        await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": True}})
        try:
            if prov:
                w0 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
                r = await c.post(f"{BASE}/services/{prov['id']}/reveal-phone", headers=bh, json={"accept_terms": True})
                w1 = (await db.users.find_one({"email": BUYER}, {"wallet_balance": 1}))["wallet_balance"]
                inv = await db.phone_reveal_invoices.find_one({"user_id": u["id"], "provider_id": prov["id"]}, {"_id": 0})
                check("member reveal → 200, no debit", r.status_code == 200 and abs(w1 - w0) < .01, (r.status_code, r.text[:200], w0, w1))
                check("member reveal invoice total 0", inv is not None and float(inv.get("total") or inv.get("amount") or 0) == 0, inv)
                txn = await db.transactions.count_documents({"user_id": u["id"], "type": {"$regex": "reveal"}, "related_provider_id": prov["id"]})
                print("reveal txns for member:", txn)
                # cleanup the invoice so the next run starts free
                await db.phone_reveal_invoices.delete_many({"user_id": u["id"], "provider_id": prov["id"]})
        finally:
            await db.users.update_one({"email": BUYER}, {"$set": {"registration_paid": False}})
            if backup:
                await db.phone_reveal_invoices.insert_many(backup)
        # application gates on the (now free) account with VALID bodies
        r = await c.post(f"{BASE}/vendor/apply", headers=bh, json={"shop_name": "TEST_i100 shop"})
        check("free → /vendor/apply refused", r.status_code in (402, 403), (r.status_code, r.text[:150]))
        r = await c.post(f"{BASE}/service/apply", headers=bh, json={"service_name": "TEST_i100", "service_category": "Plumber", "pincode": "517644", "charge": 10})
        check("free → /service/apply refused", r.status_code in (402, 403), (r.status_code, r.text[:150]))
        r = await c.post(f"{BASE}/delivery-partner/apply", headers=bh, json={"full_name": "TEST i100", "phone": "9999999999"})
        check("free → /delivery-partner/apply refused", r.status_code in (402, 403), (r.status_code, r.text[:150]))
    print(f"RESULT {sum(RES)}/{len(RES)}")

asyncio.run(main())
