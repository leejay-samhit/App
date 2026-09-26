"""COD delivered by a delivery partner — every rupee tracked (Oct 2026).

Chain under test:
  buyer places a COD order
    → seller confirms
    → rider ships / delivers
        · seller wallet CREDITED the full cash collected
        · delivery charge taken back as revenue (GST-exclusive) + GST ledger
        · rider earns dp_commission_pct % of the delivery revenue
        · cash sits with the rider as a liability
    → rider remits via Razorpay
        · Group 7 bank CREDIT appears
        · rider's cash-in-hand returns to 0
  and the whole thing is replay-safe (no double entry, no duplicates).

Run: cd /app/backend && python tests/verify_oct2026_cod_money.py
"""
import asyncio
import os
import sys
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa: E402
from core import gst as gst_engine  # noqa: E402

BASE = "http://localhost:8001/api"
ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")
RIDER = ("rider_test@test.com", "Test@1234")
DP_PCT = 20.0

PASS = FAIL = 0


def check(label, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {extra}")


async def login(c, email, pw):
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def vendor_wallet(vid):
    u = await db.users.find_one({"id": vid}, {"_id": 0, "vendor_earnings": 1})
    return round(float((u or {}).get("vendor_earnings") or 0), 2)


async def user_wallet(uid):
    u = await db.users.find_one({"id": uid}, {"_id": 0, "wallet_balance": 1})
    return round(float((u or {}).get("wallet_balance") or 0), 2)


async def main():
    async with httpx.AsyncClient(timeout=90, headers={"User-Agent": "curl/8.5.0"}) as c:
        ah = await login(c, *ADMIN)
        vh = await login(c, *VENDOR)
        bh = await login(c, *BUYER)
        dh = await login(c, *RIDER)
        vendor = (await c.get(f"{BASE}/auth/me", headers=vh)).json()
        rider = (await c.get(f"{BASE}/auth/me", headers=dh)).json()
        vid, did = vendor["id"], rider["id"]

        print("\n[0] Setup — rider commission % and vendor mapping")
        r = await c.put(f"{BASE}/admin/settings", json={"dp_commission_pct": DP_PCT,
                                                        "delivery_charge_enabled": True}, headers=ah)
        check("admin can set the rider's commission %",
              r.status_code == 200 and float(r.json().get("dp_commission_pct")) == DP_PCT, r.text[:160])
        r = await c.put(f"{BASE}/admin/delivery-partners/{did}/vendors",
                        json={"vendor_ids": [vid]}, headers=ah)
        check("shop mapped to the rider", r.status_code == 200, r.text[:160])

        print("\n[1] Buyer places a COD order")
        p = (await c.post(f"{BASE}/vendor/me/products", json={
            "name": f"COD Money {uuid.uuid4().hex[:6]}", "price": 300,
            "image_url": "", "stock": 5, "is_published": True,
        }, headers=vh)).json()
        await db.products.update_one({"id": p["id"]}, {"$set": {
            "delivery_pincodes": ["517644"], "store_pincode": "517644",
        }})
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p["id"], "qty": 1}, headers=bh)
        co = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "cod",
            "shipping_address": {"name": "Test Buyer", "phone": "9876500022",
                                 "line1": "1 Test St", "city": "Srikalahasti",
                                 "state": "AP", "pincode": "517644"},
        }, headers=bh)
        check("COD order placed", co.status_code in (200, 201), co.text[:200])
        body = co.json()
        oid = (body.get("orders") or [{}])[0].get("id") or body.get("order_id")
        order = await db.orders.find_one({"id": oid}, {"_id": 0})
        cash = round(float(order.get("cod_due") or 0), 2)
        fee = round(float(order.get("delivery_charge") or 0), 2)
        items_value = round(cash - fee, 2)
        check("cash to collect = items + delivery", cash > 0 and fee > 0,
              f"cash={cash} fee={fee}")
        check("nothing credited before delivery",
              not await db.transactions.find_one({"idempotency_key": f"VENDORCOD:{oid}"}))

        v0 = await vendor_wallet(vid)
        d0 = await user_wallet(did)
        bank0 = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
        bank_before = round(float(bank0["group_7_bank"]["balance"]), 2)

        print("\n[2] Rider delivers — money lands exactly once")
        for st in ("confirmed", "shipped", "out_for_delivery", "delivered"):
            r = await c.patch(f"{BASE}/delivery-partner/orders/{oid}/status",
                              json={"status": st}, headers=dh)
            check(f"rider set '{st}'", r.status_code == 200, r.text[:140])

        v1 = await vendor_wallet(vid)
        check("seller keeps EXACTLY the item value",
              round(v1 - v0, 2) == items_value, f"{v0} → {v1}, expected +{items_value}")
        split = gst_engine.split_inclusive(fee, 18.0)
        rev_base = round(float(split["base_amount"]), 2)
        rev_gst = round(float(split["total_gst"]), 2)
        check("delivery revenue + GST add back to the fee",
              round(rev_base + rev_gst, 2) == fee, f"{rev_base}+{rev_gst} vs {fee}")
        rev = await db.transactions.find_one({"idempotency_key": f"DELREV:{oid}"}, {"_id": 0})
        check("revenue ledger row written net of GST",
              rev is not None and round(float(rev["amount"]), 2) == rev_base,
              str(rev and rev.get("amount")))
        g = await db.transactions.find_one({"idempotency_key": f"DELGST:{oid}"}, {"_id": 0})
        check("GST ledger row written", g is not None and round(float(g["amount"]), 2) == rev_gst,
              str(g and g.get("amount")))

        expected_comm = round(rev_base * DP_PCT / 100.0, 2)
        d1 = await user_wallet(did)
        check(f"rider earned {DP_PCT:g}% of the delivery revenue",
              round(d1 - d0, 2) == expected_comm, f"{d0} → {d1}, expected +{expected_comm}")

        dpw = (await c.get(f"{BASE}/delivery-partner/me/wallet", headers=dh)).json()
        check("rider's cash-in-hand holds the collected cash",
              round(float(dpw["cash_in_hand"]), 2) >= cash, str(dpw.get("cash_in_hand")))
        check("rider's earnings are separate from the cash he owes",
              round(float(dpw["available"]), 2) == d1, f'{dpw.get("available")} vs {d1}')
        wtx = (await c.get(f"{BASE}/delivery-partner/me/wallet-transactions", headers=dh)).json()
        check("earning appears in the rider's wallet ledger",
              any(t["type"] == "dp_delivery_commission" and t.get("order_id") == oid
                  for t in wtx.get("items", [])))

        print("\n[3] Replay safety — no double entry")
        await c.patch(f"{BASE}/delivery-partner/orders/{oid}/status",
                      json={"status": "delivered"}, headers=dh)
        check("seller wallet unchanged on replay", await vendor_wallet(vid) == v1)
        check("rider wallet unchanged on replay", await user_wallet(did) == d1)
        for key in (f"VENDORCOD:{oid}", f"DELREV:{oid}", f"DELGST:{oid}", f"DPCOMM:{oid}"):
            n = await db.transactions.count_documents({"idempotency_key": key})
            check(f"exactly one ledger row for {key.split(':')[0]}", n == 1, str(n))

        print("\n[4] Seller can withdraw the money he earned")
        nw = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
        check("vendor wallet endpoint agrees with the DB",
              round(float(nw.get("available") or nw.get("balance") or 0), 2) == v1,
              f'{nw.get("available")} vs {v1}')

        print("\n[5] Rider remits the cash — bank tally moves")
        start = (await c.post(f"{BASE}/delivery-partner/remit/start",
                              json={"amount": cash}, headers=dh)).json()
        done = await c.post(f"{BASE}/delivery-partner/remit/verify", json={
            "remit_id": start["remit_id"],
            "razorpay_order_id": start.get("razorpay_order_id") or f"order_{uuid.uuid4().hex[:10]}",
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": f"sig_MOCK_{uuid.uuid4().hex[:16]}",
        }, headers=dh)
        check("remittance accepted", done.status_code == 200, done.text[:200])
        after = (await c.get(f"{BASE}/delivery-partner/me/wallet", headers=dh)).json()
        check("rider no longer holds that cash",
              round(float(after["cash_in_hand"]), 2) == round(float(dpw["cash_in_hand"]) - cash, 2),
              f'{dpw["cash_in_hand"]} → {after["cash_in_hand"]}')
        check("rider's EARNINGS survived the remittance",
              round(float(after["available"]), 2) == d1, f'{after.get("available")} vs {d1}')
        bank1 = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
        bank_after = round(float(bank1["group_7_bank"]["balance"]), 2)
        check("company bank balance rose by exactly the cash remitted",
              round(bank_after - bank_before, 2) == cash,
              f"{bank_before} → {bank_after}, expected +{cash}")
        rows = await db.bank_ledger.count_documents({"order_id": oid, "category": "cod_remittance"})
        check("one bank row per remitted order", rows <= 1, str(rows))

        print("\n[6] Nothing changes for a seller who collects his own cash")
        await c.put(f"{BASE}/admin/delivery-partners/{did}/vendors",
                    json={"vendor_ids": []}, headers=ah)
        p2 = (await c.post(f"{BASE}/vendor/me/products", json={
            "name": f"Self COD {uuid.uuid4().hex[:6]}", "price": 300,
            "image_url": "", "stock": 5, "is_published": True,
        }, headers=vh)).json()
        await db.products.update_one({"id": p2["id"]}, {"$set": {
            "delivery_pincodes": ["517644"], "store_pincode": "517644",
        }})
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p2["id"], "qty": 1}, headers=bh)
        co2 = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "cod",
            "shipping_address": {"name": "Test Buyer", "phone": "9876500022",
                                 "line1": "1 Test St", "city": "Srikalahasti",
                                 "state": "AP", "pincode": "517644"},
        }, headers=bh)
        b2 = co2.json()
        oid2 = (b2.get("orders") or [{}])[0].get("id") or b2.get("order_id")
        v2 = await vendor_wallet(vid)
        for st in ("confirmed", "shipped", "out_for_delivery", "delivered"):
            await c.patch(f"{BASE}/vendor/orders/{oid2}/status", json={"status": st}, headers=vh)
        o2 = await db.orders.find_one({"id": oid2}, {"_id": 0})
        fee2 = round(float(o2.get("delivery_charge") or 0), 2)
        v3 = await vendor_wallet(vid)
        check("self-delivery seller is NOT credited the cash he already holds",
              not await db.transactions.find_one({"idempotency_key": f"VENDORCOD:{oid2}"}))
        check("self-delivery seller still pays the delivery charge",
              round(v2 - v3, 2) == fee2, f"{v2} → {v3}, expected −{fee2}")
        check("no rider earning on a self-delivered order",
              not await db.transactions.find_one({"idempotency_key": f"DPCOMM:{oid2}"}))

        # cleanup
        await db.products.delete_many({"id": {"$in": [p["id"], p2["id"]]}})

    print("\n" + "=" * 64)
    print(f"  PASS {PASS}   FAIL {FAIL}")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
