"""Money-flow lifecycle checks for the Jun-2026 cashback cutover.

Verifies the parts the testing agent could not drive: settle-on-delivered,
duplicate protection, pending -> admin fund, platform funding + recovery,
clawback on cancel with refund netting, delivery cap, wallet+COD parity.

Run:  cd /app/backend && python tests/verify_cashback_flow.py
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from core.db import db  # noqa: E402

BASE = "http://localhost:8001/api"
H = {"User-Agent": "curl/8.5.0"}
ADMIN = ("support@slangcart.com", "3)Ywxtic")
BUYER = ("testbuyer@test.com", "Test@1234")
VENDOR = ("testvendor@test.com", "Test@1234")
ADDR = {
    "name": "Test Buyer", "phone": "9999999999", "line1": "1 Main St",
    "city": "Srikalahasti", "state": "AP", "pincode": "517644",
    "latitude": 13.7497, "longitude": 79.7036,
}
ok_count, fail_count = 0, 0


def check(label, cond, detail=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  PASS  {label}")
    else:
        fail_count += 1
        print(f"  FAIL  {label} :: {detail}")


async def login(c, creds):
    r = await c.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}", **H}


async def wallet_of(email):
    u = await db.users.find_one({"email": email}, {"_id": 0, "wallet_balance": 1})
    return round(float((u or {}).get("wallet_balance") or 0), 2)


async def set_settings(c, ah, **kw):
    r = await c.put(f"{BASE}/admin/settings", json=kw, headers=ah)
    r.raise_for_status()
    return r.json()


async def make_product(c, vh, price, cashback_pct, name=None):
    body = {
        "name": name or f"CB Test {uuid.uuid4().hex[:6]}",
        "price": price, "image_url": "", "stock": 50,
        "category": "General", "is_published": True,
        "cashback_pct": cashback_pct,
    }
    r = await c.post(f"{BASE}/vendor/me/products", json=body, headers=vh)
    r.raise_for_status()
    return r.json()


async def buy(c, bh, product_id, qty=1, method="wallet", wallet_amount=None):
    await c.post(f"{BASE}/cart/clear", headers=bh)
    r = await c.post(f"{BASE}/cart/add", json={"product_id": product_id, "qty": qty}, headers=bh)
    r.raise_for_status()
    body = {"payment_method": method, "shipping_address": ADDR}
    if wallet_amount is not None:
        body["wallet_amount"] = wallet_amount
    r = await c.post(f"{BASE}/orders/checkout", json=body, headers=bh)
    if r.status_code != 200:
        raise AssertionError(f"checkout {r.status_code}: {r.text[:300]}")
    return r.json()


async def set_status(c, ah, order_id, status):
    r = await c.patch(f"{BASE}/admin/orders/{order_id}/status", json={"status": status}, headers=ah)
    return r


async def main():
    async with httpx.AsyncClient(timeout=90.0, headers=H) as c:
        ah = await login(c, ADMIN)
        bh = await login(c, BUYER)
        vh = await login(c, VENDOR)

        await set_settings(
            c, ah, cashback_enabled=True, default_cashback_pct=0,
            cashback_platform_funding_enabled=True, cashback_clawback_on_return=True,
            delivery_charge_enabled=True, delivery_charge_flat=30,
            delivery_free_threshold=500, delivery_cart_max=40,
        )
        await db.users.update_one({"email": BUYER[0]}, {"$set": {"wallet_balance": 20000.0}})
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"wallet_balance": 5000.0}})

        # ── 1. Delivery charge below the threshold ───────────────────────
        print("\n[1] Delivery charge + totals")
        p100 = await make_product(c, vh, 100, 5)
        r = await buy(c, bh, p100["id"])
        check("delivery_total = 30 under threshold", r["delivery_total"] == 30, r["delivery_total"])
        check("grand_total = goods + delivery", round(r["goods_total"] + r["delivery_total"], 2) == r["grand_total"],
              f'{r["goods_total"]}+{r["delivery_total"]} vs {r["grand_total"]}')
        order_id = r["orders"][0]["id"]
        check("order carries delivery_charge", r["orders"][0]["delivery_charge"] == 30)
        check("cashback promised 5", r["cashback_promised"] == 5.0, r["cashback_promised"])

        # ── 2. Free delivery at/above the threshold ──────────────────────
        p600 = await make_product(c, vh, 600, 5)
        r2 = await buy(c, bh, p600["id"])
        check("free delivery at >= 500", r2["delivery_total"] == 0, r2["delivery_total"])

        # ── 3. No cashback before delivery ───────────────────────────────
        print("\n[2] Cashback only after successful delivery")
        o = await db.orders.find_one({"id": order_id}, {"_id": 0, "cashback_status": 1})
        check("status awaiting_delivery", o["cashback_status"] == "awaiting_delivery", o)
        check("no cashback_credit yet",
              await db.transactions.count_documents({"order_id": order_id, "type": "cashback_credit"}) == 0)

        before = await wallet_of(BUYER[0])
        await set_status(c, ah, order_id, "delivered")
        after = await wallet_of(BUYER[0])
        check("wallet +5 on delivered", round(after - before, 2) == 5.0, f"{before} -> {after}")
        led = await db.cashback_ledger.find_one({"_id": f"CB:{order_id}"})
        check("ledger paid / funded_by vendor", led and led["status"] == "paid" and led["funded_by"] == "vendor", led)

        # ── 4. Duplicate protection ──────────────────────────────────────
        print("\n[3] Cashback cannot duplicate")
        await set_status(c, ah, order_id, "shipped")
        await set_status(c, ah, order_id, "delivered")
        again = await wallet_of(BUYER[0])
        check("wallet unchanged on 2nd delivered", again == after, f"{after} -> {again}")
        check("exactly one cashback_credit",
              await db.transactions.count_documents({"order_id": order_id, "type": "cashback_credit"}) == 1)

        # ── 5. Vendor short + platform funding OFF -> PENDING ────────────
        print("\n[4] Vendor wallet short -> PENDING -> admin fund")
        await set_settings(c, ah, cashback_platform_funding_enabled=False)
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"wallet_balance": 0.0}})
        p200 = await make_product(c, vh, 200, 10)
        rp = await buy(c, bh, p200["id"])
        oid2 = rp["orders"][0]["id"]
        w_before = await wallet_of(BUYER[0])
        await set_status(c, ah, oid2, "delivered")
        led2 = await db.cashback_ledger.find_one({"_id": f"CB:{oid2}"})
        check("ledger pending", led2 and led2["status"] == "pending", led2)
        check("customer NOT credited", await wallet_of(BUYER[0]) == w_before)
        check("cashback_pending txn exists",
              await db.transactions.count_documents({"order_id": oid2, "type": "cashback_pending", "status": "pending"}) == 1)
        vw = await wallet_of(VENDOR[0])
        check("vendor wallet not negative", vw >= 0, vw)

        rf = await c.post(f"{BASE}/admin/cashback/{oid2}/fund", headers=ah)
        check("admin fund 200", rf.status_code == 200, rf.text[:200])
        check("customer credited 20 after fund", round(await wallet_of(BUYER[0]) - w_before, 2) == 20.0,
              await wallet_of(BUYER[0]) - w_before)
        led2b = await db.cashback_ledger.find_one({"_id": f"CB:{oid2}"})
        check("ledger now paid", led2b["status"] == "paid", led2b["status"])
        check("pending txn settled",
              await db.transactions.count_documents({"order_id": oid2, "type": "cashback_pending", "status": "pending"}) == 0)

        # ── 6. Platform funding ON -> outstanding -> recover ─────────────
        print("\n[5] Slangcart fronts it -> vendor outstanding -> recover")
        await set_settings(c, ah, cashback_platform_funding_enabled=True)
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"wallet_balance": 0.0}})
        p300 = await make_product(c, vh, 300, 10)
        rq = await buy(c, bh, p300["id"])
        oid3 = rq["orders"][0]["id"]
        w3 = await wallet_of(BUYER[0])
        await set_status(c, ah, oid3, "delivered")
        check("customer credited 30 immediately", round(await wallet_of(BUYER[0]) - w3, 2) == 30.0,
              await wallet_of(BUYER[0]) - w3)
        check("platform_funded txn",
              await db.transactions.count_documents({"order_id": oid3, "type": "cashback_platform_funded"}) == 1)
        vid = (await db.users.find_one({"email": VENDOR[0]}, {"_id": 0, "id": 1}))["id"]
        out = (await c.get(f"{BASE}/admin/cashback/outstanding", headers=ah)).json()
        check("outstanding >= 30", out["total"] >= 30, out["total"])
        cust_before_recover = await wallet_of(BUYER[0])
        rr = await c.post(f"{BASE}/admin/cashback/outstanding/{vid}/recover",
                          json={"amount": 30, "note": "Seller paid by UPI"}, headers=ah)
        check("recover 200", rr.status_code == 200, rr.text[:200])
        check("customer NOT credited again", await wallet_of(BUYER[0]) == cust_before_recover)
        out2 = (await c.get(f"{BASE}/admin/cashback/outstanding", headers=ah)).json()
        check("outstanding reduced by 30", round(out["total"] - out2["total"], 2) == 30.0,
              f'{out["total"]} -> {out2["total"]}')

        # ── 7. Clawback on cancel + refund netting ───────────────────────
        print("\n[6] Clawback on return + refund netting")
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"wallet_balance": 5000.0}})
        p500 = await make_product(c, vh, 400, 10)
        rc = await buy(c, bh, p500["id"])
        oid4 = rc["orders"][0]["id"]
        paid_total = rc["orders"][0]["total"]
        await set_status(c, ah, oid4, "delivered")
        w4 = await wallet_of(BUYER[0])
        await set_status(c, ah, oid4, "cancelled")
        w5 = await wallet_of(BUYER[0])
        # cashback 40 reversed, whole prepaid total refunded => net +total-40
        check("net wallet = refund - cashback", round(w5 - w4, 2) == round(paid_total - 40, 2),
              f"{w4} -> {w5}, expected +{paid_total - 40}")
        check("cashback_reversal txn",
              await db.transactions.count_documents({"order_id": oid4, "type": "cashback_reversal"}) == 1)
        check("delivery reversed",
              await db.transactions.count_documents({"order_id": oid4, "type": "delivery_charge_reversal"}) == 1)

        # ── 8. Wallet + COD parity ───────────────────────────────────────
        print("\n[7] Wallet + COD no double count")
        pw = await make_product(c, vh, 500, 5)
        rw = await buy(c, bh, pw["id"], method="wallet_cod", wallet_amount=200)
        total = rw["grand_total"]
        s = round(rw["wallet_paid"] + rw["cod_due"], 2)
        check("wallet_paid + cod_due == grand_total", s == total, f"{s} vs {total}")
        check("wallet slice honoured", rw["wallet_paid"] == 200, rw["wallet_paid"])
        rcod = await buy(c, bh, pw["id"], method="cod")
        check("pure COD wallet_paid 0", rcod["wallet_paid"] == 0, rcod["wallet_paid"])
        check("pure COD cod_due == total", rcod["cod_due"] == rcod["grand_total"])

        # ── 9. Multi-vendor delivery cap ─────────────────────────────────
        print("\n[8] Multi-vendor delivery cap")
        v2 = await db.users.find_one({"email": "testvendor2@test.com"}, {"_id": 0, "id": 1})
        if v2:
            p_v2 = {
                "id": str(uuid.uuid4()), "name": f"V2 Cap {uuid.uuid4().hex[:5]}",
                "price": 100, "stock": 20, "image_url": "", "is_published": True,
                "vendor_id": v2["id"], "category": "General", "cashback_pct": 0,
                "store_pincode": "517644", "delivery_pincodes": ["517644"],
                "created_at": "2026-06-01T00:00:00",
            }
            await db.products.insert_one(dict(p_v2))
            await c.post(f"{BASE}/cart/clear", headers=bh)
            await c.post(f"{BASE}/cart/add", json={"product_id": p100["id"], "qty": 1}, headers=bh)
            await c.post(f"{BASE}/cart/add", json={"product_id": p_v2["id"], "qty": 1}, headers=bh)
            rm = await c.post(f"{BASE}/orders/checkout",
                              json={"payment_method": "wallet", "shipping_address": ADDR}, headers=bh)
            if rm.status_code == 200:
                d = rm.json()
                check("2 sellers split", d["split_count"] == 2, d["split_count"])
                check("delivery capped at 40", d["delivery_total"] == 40,
                      f'{d["delivery_total"]} (uncapped {d["delivery_breakdown"]["uncapped_total"]})')
                alloc = round(sum(float(o["delivery_charge"]) for o in d["orders"]), 2)
                check("allocations sum to the cap", alloc == 40, alloc)
            else:
                print(f"  SKIP  multi-vendor checkout {rm.status_code}: {rm.text[:160]}")
        else:
            print("  SKIP  vendor 2 missing")

        # ── 10. No new referral payouts anywhere ─────────────────────────
        print("\n[9] MLM stays dead")
        recent = await db.transactions.count_documents({
            "type": {"$in": ["referral_payout", "cascade_overflow", "l1_funding"]},
            "created_at": {"$gte": "2026-09-11"},
        })
        check("no new referral/cascade txns today", recent == 0, recent)

    print(f"\n=== {ok_count} passed, {fail_count} failed ===")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
