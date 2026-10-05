"""Phase-1 money-flow verification (owner's TEST A … TEST H).

Run:  cd /app/backend && python tests/verify_phase1_money.py
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
ADDR = {"name": "T", "phone": "9999999999", "line1": "1 Main St", "city": "Srikalahasti",
        "state": "AP", "pincode": "517644", "latitude": 13.7497, "longitude": 79.7036}
ok, bad = 0, 0


def check(label, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        bad += 1
        print(f"  FAIL  {label} :: {detail}")


async def login(c, creds):
    r = await c.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}", **H}


async def vendor_wallet(email=VENDOR[0]):
    u = await db.users.find_one({"email": email}, {"_id": 0, "vendor_earnings": 1})
    return round(float((u or {}).get("vendor_earnings") or 0), 2)


async def cust_wallet(email=BUYER[0]):
    u = await db.users.find_one({"email": email}, {"_id": 0, "wallet_balance": 1})
    return round(float((u or {}).get("wallet_balance") or 0), 2)


async def treasury():
    u = await db.users.find_one({"email": ADMIN[0]}, {"_id": 0, "wallet_buckets": 1})
    return round(float((u or {}).get("wallet_buckets", {}).get("delivery_collected") or 0), 2)


async def make_product(c, vh, price, free_delivery=False):
    body = {"name": f"P1 {uuid.uuid4().hex[:6]}", "price": price, "image_url": "", "stock": 50,
            "category": "General", "is_published": True, "cashback_pct": 0,
            "free_delivery": free_delivery}
    r = await c.post(f"{BASE}/vendor/me/products", json=body, headers=vh)
    r.raise_for_status()
    return r.json()


async def buy(c, bh, pid, method, wallet_amount=None, payment_id=None):
    await c.post(f"{BASE}/cart/clear", headers=bh)
    await c.post(f"{BASE}/cart/add", json={"product_id": pid, "qty": 1}, headers=bh)
    body = {"payment_method": method, "shipping_address": ADDR}
    if wallet_amount is not None:
        body["wallet_amount"] = wallet_amount
    if payment_id:
        body["payment_id"] = payment_id
    r = await c.post(f"{BASE}/orders/checkout", json=body, headers=bh)
    if r.status_code != 200:
        raise AssertionError(f"checkout {r.status_code}: {r.text[:300]}")
    return r.json()


async def deliver(c, ah, oid):
    return await c.patch(f"{BASE}/admin/orders/{oid}/status", json={"status": "delivered"}, headers=ah)


async def main():
    async with httpx.AsyncClient(timeout=90.0, headers=H) as c:
        # A withdrawal left in flight by an earlier run blocks the settlement
        # tests ("settlement already in progress"), so clear the queue first
        # and make this script re-runnable back-to-back with Phase 2.
        await db.withdrawals.delete_many(
            {"status": {"$in": ["pending", "approved", "processing"]}},
        )
        ah, bh, vh = await login(c, ADMIN), await login(c, BUYER), await login(c, VENDOR)
        await c.put(f"{BASE}/admin/settings", json={
            "delivery_charge_enabled": True, "delivery_charge_flat": 30,
            "delivery_free_threshold": 100000, "delivery_cart_max": 60,
            "cashback_enabled": False, "default_cashback_pct": 0,
        }, headers=ah)
        await db.users.update_one({"email": BUYER[0]}, {"$set": {"wallet_balance": 50000.0}})
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"vendor_earnings": 10000.0}})

        p470 = await make_product(c, vh, 470)

        # ── TEST A — ONLINE ₹500 ────────────────────────────────────────
        print("\n[A] Online ₹470 + ₹30 delivery")
        r = await c.post(f"{BASE}/orders/payment/start", json={"wallet_amount": 0}, headers=bh)
        print("  (payment/start needs a cart) ->", r.status_code)
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p470["id"], "qty": 1}, headers=bh)
        st = (await c.post(f"{BASE}/orders/payment/start", json={"wallet_amount": 0}, headers=bh)).json()
        check("razorpay collects goods+delivery = 500", st["amount"] == 500.0,
              f'{st.get("amount")} goods={st.get("goods_total")} del={st.get("delivery_total")}')
        vr = await c.post(f"{BASE}/orders/payment/verify", json={
            "payment_id": st["payment_id"], "razorpay_order_id": st["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:10]}", "razorpay_signature": "sig",
        }, headers=bh)
        check("payment verify 200", vr.status_code == 200, vr.text[:150])
        v0, t0 = await vendor_wallet(), await treasury()
        oc = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "online", "shipping_address": ADDR, "payment_id": st["payment_id"],
        }, headers=bh)
        check("online checkout 200", oc.status_code == 200, oc.text[:200])
        d = oc.json()
        oid = d["orders"][0]["id"]
        check("order total = 500", d["grand_total"] == 500.0, d["grand_total"])
        v1 = await vendor_wallet()
        check("vendor credited full 500", round(v1 - v0, 2) == 500.0, f"{v0} -> {v1}")
        check("no shop commission txn",
              await db.transactions.count_documents({"order_id": oid, "type": "shop_commission"}) == 0)
        check("no delivery revenue before delivery", round(await treasury() - t0, 2) == 0.0)
        await deliver(c, ah, oid)
        v2, t2 = await vendor_wallet(), await treasury()
        # Oct-2026 OWNER RULE — no delivery partner is mapped to this seller,
        # so HE delivered and Slangcart collects ₹0: nothing leaves his wallet,
        # no delivery-revenue row. The rider-delivered case (where the charge
        # IS revenue) is covered by verify_oct2026_money_audit R5.
        check("self-delivery: vendor keeps the delivery charge",
              round(v1 - v2, 2) == 0.0, f"{v1} -> {v2}")
        check("self-delivery: treasury unchanged", round(t2 - t0, 2) == 0.0, f"{t0} -> {t2}")
        check("self-delivery: no delivery revenue row",
              await db.transactions.count_documents({"order_id": oid, "type": "delivery_charge_collected"}) == 0)
        # idempotent re-delivery
        await c.patch(f"{BASE}/admin/orders/{oid}/status", json={"status": "shipped"}, headers=ah)
        await deliver(c, ah, oid)
        check("delivery fee not taken twice", await vendor_wallet() == v2, await vendor_wallet())
        check("vendor credit exactly once",
              await db.transactions.count_documents({"order_id": oid, "type": "vendor_sale"}) == 1)

        # ── TEST B — WALLET ₹500 ────────────────────────────────────────
        print("\n[B] Wallet ₹500")
        c0, v0, t0 = await cust_wallet(), await vendor_wallet(), await treasury()
        d = await buy(c, bh, p470["id"], "wallet")
        oid = d["orders"][0]["id"]
        check("customer -500", round(c0 - await cust_wallet(), 2) == 500.0, await cust_wallet())
        check("vendor +500", round(await vendor_wallet() - v0, 2) == 500.0)
        v1 = await vendor_wallet()
        await deliver(c, ah, oid)
        check("self-delivery: vendor keeps delivery charge",
              round(v1 - await vendor_wallet(), 2) == 0.0)
        check("self-delivery: treasury unchanged", round(await treasury() - t0, 2) == 0.0)

        # ── TEST C — COD ₹500 ───────────────────────────────────────────
        print("\n[C] COD ₹500")
        c0, v0, t0 = await cust_wallet(), await vendor_wallet(), await treasury()
        d = await buy(c, bh, p470["id"], "cod")
        oid = d["orders"][0]["id"]
        check("customer wallet untouched", await cust_wallet() == c0)
        check("no vendor credit for cash order", await vendor_wallet() == v0, await vendor_wallet())
        await deliver(c, ah, oid)
        check("no fake customer credit after delivery", await cust_wallet() == c0, await cust_wallet())
        check("COD self-delivery: no wallet movement at all",
              round(v0 - await vendor_wallet(), 2) == 0.0)
        check("COD self-delivery: treasury unchanged", round(await treasury() - t0, 2) == 0.0)
        o = await db.orders.find_one({"id": oid}, {"_id": 0, "cod_due": 1, "paid_via": 1})
        check("order flagged cash on delivery", o["paid_via"] == "cod" and o["cod_due"] == 500.0, o)

        # ── TEST D — FREE DELIVERY ──────────────────────────────────────
        print("\n[D] Free delivery")
        pfree = await make_product(c, vh, 470, free_delivery=True)
        v0, t0 = await vendor_wallet(), await treasury()
        d = await buy(c, bh, pfree["id"], "wallet")
        oid = d["orders"][0]["id"]
        check("delivery = 0", d["delivery_total"] == 0.0, d["delivery_total"])
        check("vendor +470", round(await vendor_wallet() - v0, 2) == 470.0)
        v1 = await vendor_wallet()
        await deliver(c, ah, oid)
        check("no vendor delivery deduction", await vendor_wallet() == v1, await vendor_wallet())
        check("no treasury delivery revenue", await treasury() == t0)
        check("no delivery revenue row",
              await db.transactions.count_documents({"order_id": oid, "type": "delivery_charge_collected"}) == 0)

        # ── TEST E — WALLET + COD ───────────────────────────────────────
        print("\n[E] Wallet ₹200 + COD ₹300")
        c0, v0 = await cust_wallet(), await vendor_wallet()
        d = await buy(c, bh, p470["id"], "wallet_cod", wallet_amount=200)
        oid = d["orders"][0]["id"]
        check("wallet_paid 200 + cod_due 300 = 500",
              d["wallet_paid"] == 200.0 and d["cod_due"] == 300.0 and d["grand_total"] == 500.0,
              (d["wallet_paid"], d["cod_due"], d["grand_total"]))
        check("customer -200 only", round(c0 - await cust_wallet(), 2) == 200.0)
        check("vendor credited wallet slice only (200)",
              round(await vendor_wallet() - v0, 2) == 200.0, await vendor_wallet() - v0)
        v1 = await vendor_wallet()
        await deliver(c, ah, oid)
        check("no duplicate 300 vendor credit after delivery",
              round(await vendor_wallet() - v1, 2) == 0.0, await vendor_wallet() - v1)

        # ── TEST F — WALLET + ONLINE ────────────────────────────────────
        print("\n[F] Wallet ₹200 + online ₹300")
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p470["id"], "qty": 1}, headers=bh)
        st = (await c.post(f"{BASE}/orders/payment/start", json={"wallet_amount": 200}, headers=bh)).json()
        check("online slice = 300", st["amount"] == 300.0, st["amount"])
        await c.post(f"{BASE}/orders/payment/verify", json={
            "payment_id": st["payment_id"], "razorpay_order_id": st["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:10]}", "razorpay_signature": "sig",
        }, headers=bh)
        c0, v0 = await cust_wallet(), await vendor_wallet()
        oc = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "wallet_online", "wallet_amount": 200,
            "shipping_address": ADDR, "payment_id": st["payment_id"],
        }, headers=bh)
        check("combo checkout 200", oc.status_code == 200, oc.text[:200])
        d = oc.json()
        check("customer -200", round(c0 - await cust_wallet(), 2) == 200.0)
        check("vendor credited exactly 500 once", round(await vendor_wallet() - v0, 2) == 500.0,
              await vendor_wallet() - v0)
        check("one vendor_sale row", await db.transactions.count_documents(
            {"order_id": d["orders"][0]["id"], "type": "vendor_sale"}) == 1)

        # ── TEST G — payment success / order failure ────────────────────
        print("\n[G] Paid but order failed -> reconciliation")
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p470["id"], "qty": 1}, headers=bh)
        st = (await c.post(f"{BASE}/orders/payment/start", json={"wallet_amount": 0}, headers=bh)).json()
        await c.post(f"{BASE}/orders/payment/verify", json={
            "payment_id": st["payment_id"], "razorpay_order_id": st["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:10]}", "razorpay_signature": "sig",
        }, headers=bh)
        # never consumed — simulate the order never being created
        pend = (await c.get(f"{BASE}/orders/payment/pending", headers=bh)).json()
        check("customer can resume the paid attempt", (pend.get("pending") or {}).get("payment_id") == st["payment_id"], pend)
        recon = (await c.get(f"{BASE}/admin/finance/reconciliations", headers=ah)).json()
        ids = [r["payment_id"] for r in recon["reconciliations"]]
        check("reconciliation lists the orphan payment", st["payment_id"] in ids, ids[:3])
        c0 = await cust_wallet()
        rr = await c.post(f"{BASE}/admin/finance/reconciliations/{st['payment_id']}/resolve",
                          json={"action": "refund_to_wallet", "note": "order never created"}, headers=ah)
        check("resolve 200", rr.status_code == 200, rr.text[:200])
        check("refunded to wallet once", round(await cust_wallet() - c0, 2) == 500.0, await cust_wallet() - c0)
        rr2 = await c.post(f"{BASE}/admin/finance/reconciliations/{st['payment_id']}/resolve",
                           json={"action": "refund_to_wallet", "note": "double tap"}, headers=ah)
        check("second resolve pays nothing extra",
              rr2.status_code != 200 or rr2.json().get("refunded") == 0.0, rr2.text[:150])

        # ── TEST H — duplicate webhook ──────────────────────────────────
        print("\n[H] Duplicate webhook")
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p470["id"], "qty": 1}, headers=bh)
        st = (await c.post(f"{BASE}/orders/payment/start", json={"wallet_amount": 0}, headers=bh)).json()
        pay = f"pay_MOCK_{uuid.uuid4().hex[:10]}"
        hook = {"event": "payment.captured",
                "payload": {"payment": {"entity": {"id": pay, "order_id": st["razorpay_order_id"], "amount": 50000}}}}
        w1 = await c.post(f"{BASE}/payment/webhook", json=hook)
        w2 = await c.post(f"{BASE}/payment/webhook", json=hook)
        check("webhook accepted", w1.status_code == 200, w1.text[:150])
        check("replay is a no-op", w2.status_code == 200 and w2.json().get("duplicate") is True, w2.text[:150])
        att = await db.order_payments.find_one({"id": st["payment_id"]}, {"_id": 0, "status": 1})
        check("attempt marked paid by webhook", att["status"] == "paid", att)
        c0, v0 = await cust_wallet(), await vendor_wallet()
        oc = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "online", "shipping_address": ADDR, "payment_id": st["payment_id"],
        }, headers=bh)
        check("order created from webhook-paid attempt", oc.status_code == 200, oc.text[:200])
        check("exactly one vendor credit", round(await vendor_wallet() - v0, 2) == 500.0,
              await vendor_wallet() - v0)
        oc2 = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "online", "shipping_address": ADDR, "payment_id": st["payment_id"],
        }, headers=bh)
        check("same payment cannot buy twice", oc2.status_code != 200, oc2.status_code)

        # ── Vendor wallet + withdrawal rules ────────────────────────────
        print("\n[I] Vendor wallet + withdrawal")
        vw = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh))
        if vw.status_code == 200:
            data = vw.json()
            drift_before = data["unledgered_difference"]
            check("vendor wallet exposes ledger maths",
                  round(data["ledger_credits"] - data["ledger_debits"], 2) == data["ledger_balance"], data)
            d2 = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
            check("ledger explains every new movement (drift stable)",
                  d2["unledgered_difference"] == drift_before, (drift_before, d2["unledgered_difference"]))
        else:
            print(f"  SKIP  /vendor/me/wallet {vw.status_code}")
        low = await c.post(f"{BASE}/withdrawals", json={"amount": 1000}, headers=vh)
        check("below ₹5,000 rejected",
              low.status_code == 400 and ("5000" in low.text or "5,000" in low.text),
              low.text[:150])
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"vendor_earnings": 4000.0}})
        short = await c.post(f"{BASE}/withdrawals", json={"amount": 5000}, headers=vh)
        check("insufficient available balance refused",
              short.status_code == 400 and "insufficient" in short.text.lower(), short.text[:160])
        check("nothing deducted on refusal", await vendor_wallet() == 4000.0, await vendor_wallet())
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"vendor_earnings": 9000.0}})
        wok = await c.post(f"{BASE}/withdrawals", json={"amount": 5000}, headers=vh)
        check("valid settlement accepted", wok.status_code == 200, wok.text[:160])
        check("held out of vendor wallet", await vendor_wallet() == 4000.0, await vendor_wallet())
        dup = await c.post(f"{BASE}/withdrawals", json={"amount": 5000}, headers=vh)
        check("duplicate settlement blocked", dup.status_code == 400, dup.status_code)
        buyer_w = await c.post(f"{BASE}/withdrawals", json={"amount": 5000}, headers=bh)
        check("customer cannot withdraw", buyer_w.status_code == 403, buyer_w.status_code)

    print(f"\n=== {ok} passed, {bad} failed ===")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
