"""E2E verification of the Sep-2026 money/GST rework.

Covers, in one real order:
  1. Inclusive GST break-up appears on /cart (server-computed)
  2. Order line + sub-order carry a frozen GST snapshot
  3. Vendor SHOP wallet (vendor_earnings) is credited, and /vendor/me/wallet
     reports the same number the ledger does
  4. Delivery charge on delivery → revenue NET of 18% GST + a GST ledger row
  5. Bank ledger records the online receipt (bank statement == bank ledger)
  6. Group 2 liability drilldown actually lists rows
  7. Return window is 10 minutes for the customer, 24 h for the vendor
  8. Every transaction type has an invoice

Run: cd /app/backend && EXPO_BACKEND_URL=<preview> python3 tests/verify_sep2026_money.py
"""
import asyncio
import os
import sys
import uuid

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ["EXPO_BACKEND_URL"].rstrip("/") + "/api"
BUYER = ("testbuyer@test.com", "Test@1234")
VENDOR = ("testvendor@test.com", "Test@1234")
ADMIN = ("support@slangcart.com", "3)Ywxtic")

results = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {extra}")


def login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def main():
    from core.db import db, client
    from core import bank, shop_money

    bh, vh, ah = login(*BUYER), login(*VENDOR), login(*ADMIN)

    vme = requests.get(f"{BASE}/auth/me", headers=vh, timeout=30).json()
    vendor_id = vme["id"]

    # ── Product with a real GST rate, paid delivery ────────────────────
    prod = requests.post(f"{BASE}/vendor/me/products", headers=vh, timeout=30, json={
        "name": f"GST probe {uuid.uuid4().hex[:6]}",
        "price": 1180, "purchase_price": 800,
        "purchase_gst_pct": 18, "selling_gst_pct": 18,
        "image_url": "https://example.com/x.jpg",
        "stock": 20, "category": "General", "is_published": True,
        "cashback_pct": 0, "free_delivery": False,
    }).json()
    check("product created", bool(prod.get("id")), str(prod)[:120])
    pid = prod["id"]

    requests.post(f"{BASE}/cart/clear", headers=bh, timeout=30)
    requests.post(f"{BASE}/cart/add", headers=bh, timeout=30, json={"product_id": pid, "qty": 1})

    # 1 ── cart GST break-up
    cart = requests.get(f"{BASE}/cart", headers=bh, timeout=30).json()
    g = cart.get("gst_summary") or {}
    check("cart exposes gst_summary", bool(g), str(g)[:160])
    check("cart taxable value = 1000 (1180 incl 18%)", abs(float(g.get("taxable_value", 0)) - 1000) < 0.05,
          f"got {g.get('taxable_value')}")
    check("cart CGST = 90", abs(float(g.get("cgst_amount", 0)) - 90) < 0.05, f"got {g.get('cgst_amount')}")
    check("cart SGST = 90", abs(float(g.get("sgst_amount", 0)) - 90) < 0.05, f"got {g.get('sgst_amount')}")
    check("cart by_rate populated", len(g.get("by_rate") or []) >= 1)

    # ── balances before
    vw0 = requests.get(f"{BASE}/vendor/me/wallet", headers=vh, timeout=30).json()
    bank0 = await bank.totals()

    # 2 ── place a WALLET order (deterministic, no gateway needed)
    co = requests.post(f"{BASE}/orders/checkout", headers=bh, timeout=60, json={
        "payment_method": "wallet",
        "shipping_address": {"name": "T", "phone": "9999999999", "line1": "1",
                             "city": "X", "state": "AP", "pincode": "517641"},
    })
    check("checkout ok", co.status_code == 200, f"{co.status_code} {co.text[:180]}")
    if co.status_code != 200:
        client.close(); return
    order = co.json()["orders"][0]
    oid = order["id"]
    delivery_charge = float(order.get("delivery_charge") or 0)

    # 3 ── frozen GST snapshot on the order
    osnap = order.get("gst_summary") or {}
    check("order has gst_summary", bool(osnap), str(osnap)[:160])
    check("order CGST = 90", abs(float(osnap.get("cgst_amount", 0)) - 90) < 0.05, f"got {osnap.get('cgst_amount')}")
    line = (order.get("items") or [{}])[0]
    check("order line has gst_pct 18", abs(float(line.get("gst_pct", 0)) - 18) < 0.01, f"got {line.get('gst_pct')}")
    check("order line taxable = 1000", abs(float(line.get("taxable_value", 0)) - 1000) < 0.05,
          f"got {line.get('taxable_value')}")

    # 4 ── vendor shop wallet credited, and the endpoint agrees with the ledger
    vw1 = requests.get(f"{BASE}/vendor/me/wallet", headers=vh, timeout=30).json()
    gained = round(float(vw1["available_balance"]) - float(vw0["available_balance"]), 2)
    check("vendor shop wallet credited with prepaid total",
          abs(gained - float(order["total"])) < 0.05, f"gained {gained} vs order {order['total']}")
    check("vendor wallet endpoint exposes `available` for the app",
          "available" in vw1 and abs(float(vw1["available"]) - float(vw1["available_balance"])) < 0.01)
    check("vendor wallet is ledger-synced", vw1.get("in_sync") is True,
          f"diff {vw1.get('unledgered_difference')}")
    ustored = await db.users.find_one({"id": vendor_id}, {"_id": 0, "vendor_earnings": 1})
    check("DB vendor_earnings == reported available",
          abs(float(ustored["vendor_earnings"]) - float(vw1["available_balance"])) < 0.01)

    # vendor DASHBOARD must report the same pot (this was the visual bug)
    st = requests.get(f"{BASE}/vendor/me/stats", headers=vh, timeout=30).json()
    check("dashboard WALLET tile == shop wallet",
          abs(float(st["wallet_balance"]) - float(vw1["available_balance"])) < 0.01,
          f"tile {st['wallet_balance']} vs wallet {vw1['available_balance']}")
    check("dashboard also reports personal wallet separately",
          "personal_wallet_balance" in st)

    # 5 ── deliver it → delivery charge split into revenue + GST
    for status in ("confirmed", "shipped", "delivered"):
        r = requests.patch(f"{BASE}/vendor/orders/{oid}/status", headers=vh,
                           json={"status": status}, timeout=45)
        if r.status_code != 200:
            r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah,
                               json={"status": status}, timeout=45)
        check(f"status → {status}", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

    if delivery_charge > 0.009:
        rev = await db.transactions.find_one({"idempotency_key": f"DELREV:{oid}"}, {"_id": 0})
        gstrow = await db.transactions.find_one({"idempotency_key": f"DELGST:{oid}"}, {"_id": 0})
        check("delivery revenue row written", bool(rev))
        check("delivery GST row written", bool(gstrow))
        if rev and gstrow:
            base, tax = float(rev["amount"]), float(gstrow["amount"])
            check("revenue is NET of GST", abs(base - delivery_charge * 100 / 118) < 0.05,
                  f"base {base} of fee {delivery_charge}")
            check("GST is 18/118 of the fee", abs(tax - delivery_charge * 18 / 118) < 0.05,
                  f"gst {tax}")
            check("revenue + GST == cash collected", abs((base + tax) - delivery_charge) < 0.05,
                  f"{base}+{tax} vs {delivery_charge}")
            check("GST row tagged as delivery", gstrow.get("gst_kind") == "delivery_charge",
                  str(gstrow.get("gst_kind")))
    else:
        check("free delivery → no revenue row",
              not await db.transactions.find_one({"idempotency_key": f"DELREV:{oid}"}))

    # 6 ── return windows: 10 min customer / 24 h vendor
    rs = requests.get(f"{BASE}/orders/{oid}/return-state", headers=bh, timeout=30).json()
    check("customer return window is 10 minutes", int(rs.get("return_window_minutes") or 0) == 10,
          str(rs.get("return_window_minutes")))
    check("vendor window is 24 hours", int(rs.get("vendor_window_hours") or 0) == 24,
          str(rs.get("vendor_window_hours")))
    check("return eligible right after delivery", rs.get("return_eligible") is True)
    check("seconds_left counts down under 10 min",
          0 < int(rs.get("seconds_left") or 0) <= 600, str(rs.get("seconds_left")))
    check("vendor can act now", rs.get("vendor_can_act") is True)

    # 7 ── bank ledger + Group 2 drilldown (admin views)
    bank1 = await bank.totals()
    check("bank ledger unchanged by a WALLET order (no cash arrived)",
          abs(bank1["credits"] - bank0["credits"]) < 0.01,
          f"{bank0['credits']} -> {bank1['credits']}")
    nw = requests.get(f"{BASE}/admin/finance/net-worth", headers=ah, timeout=45).json()
    check("bank tally net == bank ledger balance",
          abs(float(nw["bank_tally"]["net"]) - bank1["balance"]) < 0.01,
          f"{nw['bank_tally']['net']} vs {bank1['balance']}")
    check("group 7 balance == bank ledger balance",
          abs(float(nw["group_7_bank"]["balance"]) - bank1["balance"]) < 0.01)
    check("vendor payable shown as a liability",
          float(nw["group_2_liability"]["vendor_payable"]) > 0,
          str(nw["group_2_liability"]["vendor_payable"]))
    check("delivery revenue surfaced in group 1", "delivery" in nw["group_1_revenue"])
    check("cash on hand reported separately", "cash_on_hand" in nw)
    g2 = requests.get(f"{BASE}/admin/finance/groups/group_2_liability/transactions",
                      headers=ah, timeout=45).json()
    check("group 2 drilldown LISTS rows (was empty)", len(g2.get("items") or []) > 0,
          f"{len(g2.get('items') or [])} rows")
    check("group 2 rows tagged customer/vendor wallet",
          any(i.get("wallet") == "vendor" for i in (g2.get("items") or [])))

    # 8 ── every transaction type has a document
    rows = requests.get(f"{BASE}/transactions/me", headers=bh, timeout=45).json()
    seen, bad = {}, []
    for r in rows:
        seen.setdefault(r["type"], r["id"])
    for t, i in seen.items():
        code = requests.get(f"{BASE}/transactions/{i}/invoice", headers=bh, timeout=30).status_code
        if code != 200:
            bad.append(f"{t}={code}")
    check("every transaction type has an invoice", not bad, ", ".join(bad) or f"{len(seen)} types OK")

    # 9 ── vendor order card gets a product image + tappable product_id
    sales = requests.get(f"{BASE}/vendor/me/sales", headers=vh, timeout=45).json()
    srows = sales if isinstance(sales, list) else sales.get("items") or []
    mine = [s for s in srows if s.get("order_id") == oid]
    it = (mine[0].get("items") or [{}])[0] if mine else {}
    check("vendor order item has an image", bool(it.get("image_url")), str(it.get("image_url"))[:60])
    check("vendor order item is tappable (product_id)", bool(it.get("product_id")))

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    print("ALL PASS" if not failed else "FAILURES:\n  " + "\n  ".join(failed))
    client.close()
    sys.exit(1 if failed else 0)


asyncio.run(main())
