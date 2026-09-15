"""Phase-2 verification — Returns · Refunds · Inventory · GST · Net Worth.

Run:  cd /app/backend && python tests/verify_phase2_returns.py

Covers the owner's §25 double-QA list:
  full return · partial return · wallet return · COD return · online return
  · refund failure (vendor short) · admin resolve · inventory restoration
  · cashback reversal · 7-day expiry · duplicate return · duplicate refund
  · GST · profit · Excel totals · net-worth reconciliation
"""
import asyncio
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

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
FAILURES = []


def check(label, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        bad += 1
        FAILURES.append(f"{label} :: {detail}")
        print(f"  FAIL  {label} :: {detail}")


async def login(c, creds):
    r = await c.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}", **H}


async def vw(email=VENDOR[0]):
    u = await db.users.find_one({"email": email}, {"_id": 0, "vendor_earnings": 1})
    return round(float((u or {}).get("vendor_earnings") or 0), 2)


async def cw(email=BUYER[0]):
    u = await db.users.find_one({"email": email}, {"_id": 0, "wallet_balance": 1})
    return round(float((u or {}).get("wallet_balance") or 0), 2)


async def stock(pid):
    p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
    return int(float((p or {}).get("stock") or 0))


async def make_product(c, vh, price, *, cashback=0, purchase=None, pgst=None, sgst=None, qty=50):
    body = {"name": f"P2 {uuid.uuid4().hex[:6]}", "price": price, "image_url": "", "stock": qty,
            "category": "General", "is_published": True, "cashback_pct": cashback,
            "free_delivery": False}
    if purchase is not None:
        body["purchase_price"] = purchase
        body["purchase_gst_pct"] = pgst
        body["selling_gst_pct"] = sgst
    r = await c.post(f"{BASE}/vendor/me/products", json=body, headers=vh)
    r.raise_for_status()
    doc = r.json()
    await db.products.update_one({"id": doc["id"]}, {"$set": {"is_published": True}})
    return doc


async def buy(c, bh, items, method, wallet_amount=None, payment_id=None):
    await c.post(f"{BASE}/cart/clear", headers=bh)
    for pid, q in items:
        await c.post(f"{BASE}/cart/add", json={"product_id": pid, "qty": q}, headers=bh)
    body = {"payment_method": method, "shipping_address": ADDR}
    if wallet_amount is not None:
        body["wallet_amount"] = wallet_amount
    if payment_id:
        body["payment_id"] = payment_id
    r = await c.post(f"{BASE}/orders/checkout", json=body, headers=bh)
    if r.status_code != 200:
        raise AssertionError(f"checkout {r.status_code}: {r.text[:400]}")
    return r.json()


async def pay_online(c, bh, items, wallet_amount=0):
    await c.post(f"{BASE}/cart/clear", headers=bh)
    for pid, q in items:
        await c.post(f"{BASE}/cart/add", json={"product_id": pid, "qty": q}, headers=bh)
    st = (await c.post(f"{BASE}/orders/payment/start",
                       json={"wallet_amount": wallet_amount}, headers=bh)).json()
    await c.post(f"{BASE}/orders/payment/verify", json={
        "payment_id": st["payment_id"],
        "razorpay_order_id": st.get("razorpay_order_id") or st.get("order_id"),
        "razorpay_payment_id": f"pay_{uuid.uuid4().hex[:12]}",
        "razorpay_signature": "mock",
    }, headers=bh)
    return st["payment_id"]


async def deliver(c, ah, oid):
    return await c.patch(f"{BASE}/admin/orders/{oid}/status",
                         json={"status": "delivered"}, headers=ah)


async def full_return_cycle(c, bh, vh, oid, lines, *, approve=True, refund=True):
    r = await c.post(f"{BASE}/returns", json={
        "order_id": oid, "items": lines, "reason": "Damaged on arrival",
        "comments": "auto test",
    }, headers=bh)
    if r.status_code != 200:
        return {"error": r.status_code, "detail": r.text[:300]}
    ret = r.json()
    if not approve:
        return ret
    await c.post(f"{BASE}/vendor/me/returns/{ret['id']}/approve", json={"note": "ok"}, headers=vh)
    await c.post(f"{BASE}/vendor/me/returns/{ret['id']}/received", json={"note": "got it"}, headers=vh)
    if refund:
        rf = await c.post(f"{BASE}/vendor/me/returns/{ret['id']}/refund", headers=vh)
        ret["_refund_status"] = rf.status_code
        ret["_refund_body"] = rf.json() if rf.headers.get("content-type", "").startswith("application/json") else {}
    return ret


async def main():
    async with httpx.AsyncClient(timeout=120.0, headers=H) as c:
        ah, bh, vh = await login(c, ADMIN), await login(c, BUYER), await login(c, VENDOR)
        await c.put(f"{BASE}/admin/settings", json={
            "delivery_charge_enabled": True, "delivery_charge_flat": 30,
            "delivery_free_threshold": 1_000_000, "delivery_cart_max": 60,
            "cashback_enabled": False, "default_cashback_pct": 0,
            "return_window_days": 7, "return_delivery_refundable": False,
        }, headers=ah)
        await db.users.update_one({"email": BUYER[0]}, {"$set": {"wallet_balance": 50000.0}})
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"vendor_earnings": 20000.0}})

        # ── 1. WALLET · FULL RETURN ─────────────────────────────────────
        print("\n[1] Wallet order · full return")
        p200 = await make_product(c, vh, 200)
        o = await buy(c, bh, [(p200["id"], 1)], "wallet")
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        await deliver(c, ah, oid)
        v0, c0, s0 = await vw(), await cw(), await stock(p200["id"])
        ret = await full_return_cycle(c, bh, vh, oid, [{"product_id": p200["id"], "qty": 1}])
        check("return created + refunded", ret.get("_refund_status") == 200, str(ret)[:200])
        check("customer refunded exactly the item amount (₹200)", await cw() == round(c0 + 200, 2),
              f"{c0} -> {await cw()}")
        check("vendor debited exactly ₹200", await vw() == round(v0 - 200, 2), f"{v0} -> {await vw()}")
        check("stock restored by 1", await stock(p200["id"]) == s0 + 1)
        fresh = await db.orders.find_one({"id": oid}, {"_id": 0, "status": 1, "return_status": 1})
        check("order marked returned", fresh.get("status") == "returned", str(fresh))
        rdoc = await db.returns.find_one({"id": ret["id"]}, {"_id": 0})
        check("return reached completed", rdoc.get("status") == "completed", rdoc.get("status"))
        check("delivery charge NOT refunded", round(float(rdoc.get("delivery_refund") or 0), 2) == 0.0)

        # duplicate refund must not move money twice
        again = await c.post(f"{BASE}/vendor/me/returns/{ret['id']}/refund", headers=vh)
        check("duplicate refund is a no-op", await cw() == round(c0 + 200, 2),
              f"status={again.status_code} wallet={await cw()}")
        # duplicate return request on the same unit must be refused
        dup = await c.post(f"{BASE}/returns", json={
            "order_id": oid, "items": [{"product_id": p200["id"], "qty": 1}], "reason": "again",
        }, headers=bh)
        check("duplicate return request refused", dup.status_code == 400, dup.text[:160])

        # ── 2. PARTIAL RETURN (A 200 · B 300 · C 500 → return B) ────────
        print("\n[2] Partial return — only B refunded")
        pa = await make_product(c, vh, 200)
        pb = await make_product(c, vh, 300)
        pc = await make_product(c, vh, 500)
        o = await buy(c, bh, [(pa["id"], 1), (pb["id"], 1), (pc["id"], 1)], "wallet")
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        await deliver(c, ah, oid)
        v0, c0 = await vw(), await cw()
        sa, sb, sc = await stock(pa["id"]), await stock(pb["id"]), await stock(pc["id"])
        ret = await full_return_cycle(c, bh, vh, oid, [{"product_id": pb["id"], "qty": 1}])
        check("partial refund = ₹300 exactly (not ₹1000)", await cw() == round(c0 + 300, 2),
              f"{c0} -> {await cw()}")
        check("vendor debited ₹300 only", await vw() == round(v0 - 300, 2), f"{v0} -> {await vw()}")
        check("only B restocked", (await stock(pa["id"]), await stock(pb["id"]), await stock(pc["id"]))
              == (sa, sb + 1, sc + 1 - 1))
        parent = await db.orders.find_one({"id": oid}, {"_id": 0, "status": 1, "return_status": 1})
        check("partial return keeps order delivered", parent.get("status") == "delivered", str(parent))
        # A and C still returnable
        st = (await c.get(f"{BASE}/orders/{oid}/return-state", headers=bh)).json()
        left = {i["product_id"]: i["returnable_qty"] for i in st["items"]}
        check("B has no returnable units left", left.get(pb["id"]) == 0, str(left))
        check("A and C still returnable", left.get(pa["id"]) == 1 and left.get(pc["id"]) == 1, str(left))

        # ── 3. COD RETURN ───────────────────────────────────────────────
        print("\n[3] COD return — vendor wallet → customer wallet")
        pcod = await make_product(c, vh, 200)
        o = await buy(c, bh, [(pcod["id"], 1)], "cod")
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        await deliver(c, ah, oid)
        v0, c0 = await vw(), await cw()
        ret = await full_return_cycle(c, bh, vh, oid, [{"product_id": pcod["id"], "qty": 1}])
        check("COD: customer credited ₹200", await cw() == round(c0 + 200, 2), f"{c0} -> {await cw()}")
        check("COD: vendor debited ₹200", await vw() == round(v0 - 200, 2), f"{v0} -> {await vw()}")
        rdoc = await db.returns.find_one({"id": ret["id"]}, {"_id": 0})
        check("COD: refund method is customer wallet", rdoc.get("refund_method") == "customer_wallet")

        # ── 4. ONLINE RETURN ────────────────────────────────────────────
        print("\n[4] Online (Razorpay) return")
        pon = await make_product(c, vh, 400)
        pid_pay = await pay_online(c, bh, [(pon["id"], 1)])
        o = await buy(c, bh, [(pon["id"], 1)], "online", payment_id=pid_pay)
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        await deliver(c, ah, oid)
        v0, c0 = await vw(), await cw()
        ret = await full_return_cycle(c, bh, vh, oid, [{"product_id": pon["id"], "qty": 1}])
        check("Online: customer credited ₹400", await cw() == round(c0 + 400, 2), f"{c0} -> {await cw()}")
        check("Online: vendor debited ₹400", await vw() == round(v0 - 400, 2), f"{v0} -> {await vw()}")
        rdoc = await db.returns.find_one({"id": ret["id"]}, {"_id": 0})
        check("Online: original payment id captured", bool(rdoc.get("original_payment_id")),
              str(rdoc.get("original_payment_id")))
        audit = (await c.get(f"{BASE}/admin/returns/{ret['id']}/audit", headers=ah)).json()
        check("Online: vendor debit == customer credit == refund", audit.get("balanced"), str(audit)[:200])

        # ── 5. VENDOR SHORT → refund_pending, nothing deducted ─────────
        print("\n[5] Vendor balance short — refund parks, no phantom money")
        pshort = await make_product(c, vh, 600)
        o = await buy(c, bh, [(pshort["id"], 1)], "wallet")
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        await deliver(c, ah, oid)
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"vendor_earnings": 10.0}})
        v0, c0 = await vw(), await cw()
        ret = await full_return_cycle(c, bh, vh, oid, [{"product_id": pshort["id"], "qty": 1}])
        check("refund refused with 409", ret.get("_refund_status") == 409, str(ret.get("_refund_status")))
        check("nothing deducted from vendor", await vw() == v0, f"{v0} -> {await vw()}")
        check("nothing credited to customer", await cw() == c0, f"{c0} -> {await cw()}")
        rdoc = await db.returns.find_one({"id": ret["id"]}, {"_id": 0})
        check("return parked as refund_pending", rdoc.get("status") == "refund_pending", rdoc.get("status"))
        check("stock NOT restored before refund", not rdoc.get("inventory_restored"))
        errs = (await c.get(f"{BASE}/admin/financial-errors?status=open", headers=ah)).json()
        check("financial error logged", any(
            e.get("return_id") == ret["id"] for e in errs.get("items", [])
        ), f"{errs.get('total')} open errors")
        # fund the vendor and let admin resolve
        await db.users.update_one({"email": VENDOR[0]}, {"$inc": {"vendor_earnings": 5000.0}})
        v1, c1 = await vw(), await cw()
        res = await c.post(f"{BASE}/admin/returns/{ret['id']}/refund", headers=ah)
        check("admin resolve succeeds after funding", res.status_code == 200, res.text[:200])
        check("resolved: customer credited ₹600", await cw() == round(c1 + 600, 2), f"{c1} -> {await cw()}")
        check("resolved: vendor debited ₹600", await vw() == round(v1 - 600, 2), f"{v1} -> {await vw()}")
        rdoc = await db.returns.find_one({"id": ret["id"]}, {"_id": 0})
        check("resolved: inventory restored", bool(rdoc.get("inventory_restored")))

        # ── 6. 7-DAY WINDOW EXPIRY ──────────────────────────────────────
        print("\n[6] Return window expiry")
        pexp = await make_product(c, vh, 150)
        o = await buy(c, bh, [(pexp["id"], 1)], "wallet")
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        await deliver(c, ah, oid)
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        await db.orders.update_one({"id": oid}, {"$set": {"delivered_at": old}})
        st = (await c.get(f"{BASE}/orders/{oid}/return-state", headers=bh)).json()
        check("expired order is not return-eligible", st.get("return_eligible") is False, str(st)[:160])
        check("expired order displays as completed", st.get("display_status") == "completed",
              st.get("display_status"))
        r = await c.post(f"{BASE}/returns", json={
            "order_id": oid, "items": [{"product_id": pexp["id"], "qty": 1}], "reason": "too late",
        }, headers=bh)
        check("return refused after the window", r.status_code == 400, r.text[:160])
        # inside the window it IS eligible and Cancel is not offered
        await db.orders.update_one({"id": oid}, {"$set": {
            "delivered_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}})
        st = (await c.get(f"{BASE}/orders/{oid}/return-state", headers=bh)).json()
        check("inside window: eligible with days_left", st.get("return_eligible") and st.get("days_left") >= 4,
              str(st.get("days_left")))
        check("delivered order cannot be cancelled", st.get("can_cancel") is False)

        # ── 7. CASHBACK REVERSAL ────────────────────────────────────────
        print("\n[7] Cashback reversal on return (pro-rata)")
        await c.put(f"{BASE}/admin/settings", json={
            "cashback_enabled": True, "default_cashback_pct": 0,
            "cashback_clawback_on_return": True,
        }, headers=ah)
        await db.users.update_one({"email": VENDOR[0]}, {"$set": {"vendor_earnings": 20000.0,
                                                                 "wallet_balance": 20000.0}})
        pcb1 = await make_product(c, vh, 500, cashback=5)     # ₹25 cashback
        pcb2 = await make_product(c, vh, 500, cashback=5)     # ₹25 cashback
        o = await buy(c, bh, [(pcb1["id"], 1), (pcb2["id"], 1)], "wallet")
        oid = o["orders"][0]["id"] if o.get("orders") else o["order_id"]
        c_before_deliver = await cw()
        await deliver(c, ah, oid)
        c_after = await cw()
        check("cashback ₹50 credited on delivery", c_after == round(c_before_deliver + 50, 2),
              f"{c_before_deliver} -> {c_after}")
        c0 = await cw()
        ret = await full_return_cycle(c, bh, vh, oid, [{"product_id": pcb1["id"], "qty": 1}])
        # refund 500 in, cashback 25 clawed back out
        check("net wallet change = +500 − 25 cashback", await cw() == round(c0 + 475, 2),
              f"{c0} -> {await cw()}")
        rdoc = await db.returns.find_one({"id": ret["id"]}, {"_id": 0})
        check("only the returned item's cashback reversed (₹25)",
              round(float(rdoc.get("cashback_reversed") or 0), 2) == 25.0,
              str(rdoc.get("cashback_reversed")))
        cbl = await db.cashback_ledger.find_one({"_id": f"CB:{oid}"})
        check("cashback ledger marked partially reversed", cbl.get("status") == "partially_reversed",
              cbl.get("status"))
        check("no over-recovery (reversed_total ≤ paid)",
              round(float(cbl.get("reversed_total") or 0), 2) <= round(float(cbl.get("amount") or 0), 2))
        await c.put(f"{BASE}/admin/settings", json={"cashback_enabled": False}, headers=ah)

        # ── 8. GST + PROFIT ENGINE ──────────────────────────────────────
        print("\n[8] GST engine + profit")
        pg = await make_product(c, vh, 1000, purchase=800, pgst=18, sgst=18)
        pr = (await c.get(f"{BASE}/vendor/me/products/{pg['id']}/pricing", headers=vh)).json()
        check("purchase CGST 9% = ₹72", pr["purchase"]["cgst_amount"] == 72.0, str(pr["purchase"]))
        check("purchase SGST 9% = ₹72", pr["purchase"]["sgst_amount"] == 72.0)
        check("purchase total = ₹944", pr["purchase"]["final_amount"] == 944.0)
        check("selling CGST 9% = ₹90", pr["selling"]["cgst_amount"] == 90.0, str(pr["selling"]))
        check("selling total = ₹1180", pr["selling"]["final_amount"] == 1180.0)
        check("profit per unit = ₹200", pr["profit_per_unit"] == 200.0)
        check("potential stock profit = ₹200 × stock",
              pr["potential_stock_profit"] == round(200.0 * pr["stock"], 2), str(pr["stock"]))
        check("CGST + SGST == total GST",
              pr["selling"]["cgst_amount"] + pr["selling"]["sgst_amount"] == pr["selling"]["total_gst"])
        pub = (await c.get(f"{BASE}/products/{pg['id']}")).json()
        check("purchase price hidden from customers", "purchase_price" not in pub, str(list(pub)[:40]))
        check("purchase GST hidden from customers", "purchase_gst_pct" not in pub)
        check("customer sees selling GST breakdown",
              (pub.get("gst_breakdown") or {}).get("total_gst") == 180.0, str(pub.get("gst_breakdown")))
        rep = (await c.get(f"{BASE}/vendor/me/profit-report", headers=vh)).json()
        check("profit report lists the product", any(
            i["product_id"] == pg["id"] and i["profit_per_unit"] == 200.0 for i in rep["items"]
        ), f"{rep['total']} items")

        # ── 9. NET WORTH + LEDGERS ──────────────────────────────────────
        print("\n[9] Vendor net worth + sales ledgers")
        # Balances were seeded straight into the DB by this harness (and by
        # older fixtures), which is exactly the legacy case the opening-balance
        # journal entry exists for. Post it, then prove the formula.
        ob = await c.post(f"{BASE}/admin/reconciliation/opening-balance?scope=all", headers=ah)
        check("opening-balance journal entry posted", ob.status_code == 200, ob.text[:200])
        nw = (await c.get(f"{BASE}/vendor/me/net-worth", headers=vh)).json()
        check("net worth reconciles to the ledger", nw["reconciliation"]["balanced"],
              str(nw["reconciliation"]))
        check("net worth exposes sales / delivery / refunds / withdrawals",
              all(k in nw["breakdown"] for k in
                  ("sales", "delivery_charges", "refunds", "withdrawals")))
        check("refunds bucket is non-zero after the returns above",
              nw["breakdown"]["refunds"] > 0, str(nw["breakdown"]))
        led = (await c.get(f"{BASE}/vendor/me/sales-ledger", headers=vh)).json()
        for sec in ("cod", "wallet", "online", "returns"):
            check(f"sales ledger has the {sec} section", sec in led, str(list(led)))
        check("COD rows carry cash-to-collect", led["cod"]["cash_to_collect"] >= 0)
        check("return rows carry vendor debit + customer credit", all(
            r["vendor_debit"] == r["customer_credit"] for r in led["returns"]["rows"]
        ), str(led["returns"]["rows"][:2]))
        off = (await c.get(f"{BASE}/vendor/me/offline-ledger", headers=vh)).json()
        check("offline ledger splits cash/upi/card",
              all(k in off for k in ("cash", "upi", "card")), str(list(off)))

        # ── 10. EXCEL ───────────────────────────────────────────────────
        print("\n[10] Net-worth Excel export")
        xl = await c.get(f"{BASE}/vendor/me/net-worth/export", headers=vh)
        check("xlsx downloads", xl.status_code == 200 and len(xl.content) > 5000,
              f"{xl.status_code} {len(xl.content)}b")
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(xl.content))
            names = wb.sheetnames
            check("workbook has the ledger sheet", "Net Worth Ledger" in names, str(names))
            check("workbook has Return Items", "Return Items" in names, str(names))
            check("workbook has Reconciliation", "Reconciliation" in names, str(names))
            ws = wb["Net Worth Ledger"]
            headers = [c.value for c in ws[1]]
            for col in ("Transaction ID", "Debit", "Credit", "Previous Balance",
                        "New Balance", "Settlement Status", "GST"):
                check(f"column present: {col}", col in headers, str(headers))
            rec = {r[0].value: r[1].value for r in wb["Reconciliation"].iter_rows(min_row=2)}
            check("Excel reconciliation says balanced", rec.get("Balanced") == "YES", str(rec))
        except ImportError:
            print("  (openpyxl not available — skipped sheet inspection)")

        # ── 11. GLOBAL RECONCILIATION ───────────────────────────────────
        print("\n[11] Final reconciliation")
        rc = (await c.get(f"{BASE}/admin/reconciliation?log_errors=false", headers=ah)).json()
        by = {ch["name"]: ch for ch in rc["checks"]}
        check("vendor wallets in sync", by["vendor_wallets"]["balanced"],
              str(by["vendor_wallets"])[:200])
        check("inventory restorations exact (none missing, none doubled)",
              by["inventory"]["balanced"], str(by["inventory"])[:300])
        check("return money balanced", by["returns"]["balanced"], str(by["returns"])[:300])
        check("GST recomputation balanced", by["gst"]["balanced"], str(by["gst"])[:200])

        print(f"\n{'='*64}\n  PASS {ok}   FAIL {bad}\n{'='*64}")
        for f in FAILURES:
            print("  ✗", f)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
