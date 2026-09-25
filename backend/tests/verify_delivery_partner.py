"""E2E test of the Delivery Partner role (Sep-2026).

Creates a throwaway rider, walks the full lifecycle and asserts the money
invariants, then cleans up completely.

  1. apply → pending → admin approves
  2. admin maps a seller; rider sees ONLY that seller's orders
  3. rider advances confirmed → shipped → on the way → delivered
  4. COD cash lands in his cash-in-hand (a liability, NOT earnings)
  5. Pay To Admin (Razorpay mock) → cash cleared, Group 7 bank CREDIT written,
     orders marked remitted, vendor-wise split recorded
  6. wallet + net worth always agree; min withdrawal is ₹1,000
  7. he can never see an unmapped seller's order
  8. Excel export downloads

Run: cd /app/backend && EXPO_BACKEND_URL=<preview> python3 tests/verify_delivery_partner.py
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
DP_EMAIL = f"rider-{uuid.uuid4().hex[:6]}@test.com"
DP_PW = "Rider@1234"

results = []


def check(name, ok, extra=""):
    results.append((name, bool(ok), extra))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {extra}")


def login(email, pw):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=30)
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def seed_rider():
    from core.db import db
    from core.security import hash_password
    uid = str(uuid.uuid4())
    await db.users.insert_one({
        "id": uid, "email": DP_EMAIL, "password_hash": hash_password(DP_PW),
        "name": "Test Rider", "role": "user", "phone": "9876543210",
        "referral_code": f"RDR{uuid.uuid4().hex[:8].upper()}",
        "registration_paid": True, "approval_status": "approved",
        "wallet_balance": 0.0, "is_active": True,
    })
    return uid


async def cleanup(uid, order_ids):
    from core.db import db, client
    await db.users.delete_one({"id": uid})
    await db.delivery_partner_applications.delete_many({"user_id": uid})
    await db.dp_vendor_map.delete_many({"dp_id": uid})
    await db.dp_remittances.delete_many({"dp_id": uid})
    await db.transactions.delete_many({"user_id": uid})
    await db.bank_ledger.delete_many({"user_id": uid})
    if order_ids:
        await db.orders.update_many({"id": {"$in": order_ids}},
                                    {"$unset": {"dp_id": "", "dp_cash_collected": ""}})
    client.close()


async def main():
    from core.db import db
    from core import bank

    uid = await seed_rider()
    order_ids = []
    try:
        dh, ah, vh, bh = login(DP_EMAIL, DP_PW), login(*ADMIN), login(*VENDOR), login(*BUYER)
        vendor_id = requests.get(f"{BASE}/auth/me", headers=vh, timeout=30).json()["id"]

        # 1 ── apply, then admin approves
        r = requests.post(f"{BASE}/delivery-partner/apply", headers=dh, timeout=30, json={
            "full_name": "Test Rider", "phone": "9876543210", "vehicle_type": "bike",
            "vehicle_number": "AP09XX1234", "delivery_radius_km": 8,
            "pincodes": ["517641", "517644"], "city": "X", "state": "AP",
        })
        check("rider can apply", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        app_id = r.json().get("id")
        me = requests.get(f"{BASE}/delivery-partner/me", headers=dh, timeout=30).json()
        check("application is pending", me.get("status") == "pending", str(me.get("status")))
        check("dashboard blocked before approval",
              requests.get(f"{BASE}/delivery-partner/me/orders", headers=dh, timeout=30).status_code == 403)
        r = requests.post(f"{BASE}/admin/delivery-partners/applications/{app_id}/approve",
                          headers=ah, json={"note": ""}, timeout=30)
        check("admin approves", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        dh = login(DP_EMAIL, DP_PW)

        # 2 ── no mapping yet ⇒ no orders at all
        o = requests.get(f"{BASE}/delivery-partner/me/orders", headers=dh, timeout=30).json()
        check("no shops mapped ⇒ zero orders visible", len(o.get("items") or []) == 0)

        r = requests.put(f"{BASE}/admin/delivery-partners/{uid}/vendors", headers=ah,
                         json={"vendor_ids": [vendor_id]}, timeout=30)
        check("admin maps a shop", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        v = requests.get(f"{BASE}/delivery-partner/me/vendors", headers=dh, timeout=30).json()
        check("rider sees his mapped shop", len(v.get("items") or []) == 1, str(len(v.get("items") or [])))

        # 3 ── a COD order for that seller
        prod = requests.post(f"{BASE}/vendor/me/products", headers=vh, timeout=30, json={
            "name": f"DP probe {uuid.uuid4().hex[:6]}", "price": 500, "purchase_price": 300,
            "purchase_gst_pct": 18, "selling_gst_pct": 18, "image_url": "https://e.com/x.jpg",
            "stock": 5, "category": "General", "is_published": True,
            "cashback_pct": 0, "free_delivery": True,
        }).json()
        requests.post(f"{BASE}/cart/clear", headers=bh, timeout=30)
        requests.post(f"{BASE}/cart/add", headers=bh, timeout=30,
                      json={"product_id": prod["id"], "qty": 1})
        co = requests.post(f"{BASE}/orders/checkout", headers=bh, timeout=60, json={
            "payment_method": "cod",
            "shipping_address": {"name": "T", "phone": "9999999999", "line1": "1",
                                 "city": "X", "state": "AP", "pincode": "517641"},
        })
        check("COD order placed", co.status_code == 200, f"{co.status_code} {co.text[:160]}")
        if co.status_code != 200:
            return
        order = co.json()["orders"][0]
        oid = order["id"]
        order_ids.append(oid)
        cod = float(order.get("cod_due") or 0)
        check("order has cash due", cod > 0, f"cod_due {cod}")

        o = requests.get(f"{BASE}/delivery-partner/me/orders", headers=dh, timeout=30).json()
        check("rider sees the new order", any(x["id"] == oid for x in o.get("items") or []))

        # 4 ── advance the order
        w0 = requests.get(f"{BASE}/delivery-partner/me/wallet", headers=dh, timeout=30).json()
        for st in ("confirmed", "shipped", "out_for_delivery", "delivered"):
            r = requests.patch(f"{BASE}/delivery-partner/orders/{oid}/status", headers=dh,
                               json={"status": st}, timeout=45)
            check(f"rider sets {st}", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

        # 5 ── COD cash became a liability, not earnings
        nw = requests.get(f"{BASE}/delivery-partner/me/net-worth", headers=dh, timeout=30).json()
        check("cash collected == COD amount", abs(float(nw["cash_collected"]) - cod) < 0.05,
              f"{nw['cash_collected']} vs {cod}")
        check("cash in hand == amount due to admin",
              abs(float(nw["cash_in_hand"]) - float(nw["amount_due_to_admin"])) < 0.01)
        check("rider books balanced", nw["in_sync"] is True, f"diff {nw['unledgered_difference']}")
        check("rider earned NOTHING in his own wallet",
              abs(float(nw["personal_wallet"]) - float(w0["personal_wallet"])) < 0.01,
              f"{w0['personal_wallet']} -> {nw['personal_wallet']}")
        check("per-shop split shows the seller",
              any(p["vendor_id"] == vendor_id for p in nw["per_vendor"]), str(nw["per_vendor"])[:120])

        w1 = requests.get(f"{BASE}/delivery-partner/me/wallet", headers=dh, timeout=30).json()
        check("wallet and net worth agree on cash",
              abs(float(w1["cash_in_hand"]) - float(nw["cash_in_hand"])) < 0.01)
        check("min withdrawal is ₹1000", float(w1["min_withdrawal"]) == 1000.0, str(w1["min_withdrawal"]))
        check("cannot withdraw on an empty wallet", w1["can_withdraw"] is False)

        cashtx = requests.get(f"{BASE}/delivery-partner/me/cash-transactions", headers=dh, timeout=30).json()
        check("cash ledger lists the collection", len(cashtx.get("items") or []) >= 1)

        # 6 ── Pay To Admin
        bank0 = await bank.totals()
        start = requests.post(f"{BASE}/delivery-partner/remit/start", headers=dh,
                              json={"amount": cod}, timeout=45)
        check("remit start ok", start.status_code == 200, f"{start.status_code} {start.text[:140]}")
        sj = start.json()
        check("over-paying is refused",
              requests.post(f"{BASE}/delivery-partner/remit/start", headers=dh,
                            json={"amount": cod + 5000}, timeout=30).status_code == 400)
        ver = requests.post(f"{BASE}/delivery-partner/remit/verify", headers=dh, timeout=45, json={
            "remit_id": sj["remit_id"], "razorpay_order_id": sj["razorpay_order_id"],
            "razorpay_payment_id": f"pay_MOCK_{uuid.uuid4().hex[:12]}",
            "razorpay_signature": "sig_MOCK",
        })
        check("remit verify ok", ver.status_code == 200, f"{ver.status_code} {ver.text[:160]}")
        vj = ver.json() if ver.status_code == 200 else {}
        check("cash in hand cleared", abs(float(vj.get("cash_in_hand", -1))) < 0.05,
              str(vj.get("cash_in_hand")))
        check("orders cleared by the payment", int(vj.get("orders_cleared") or 0) >= 1,
              str(vj.get("orders_cleared")))
        check("vendor-wise split recorded",
              any(x.get("vendor_id") == vendor_id for x in vj.get("vendor_split") or []),
              str(vj.get("vendor_split"))[:120])
        bank1 = await bank.totals()
        check("Group 7 bank CREDIT written for the cash",
              abs((bank1["credits"] - bank0["credits"]) - cod) < 0.05,
              f"{bank0['credits']} -> {bank1['credits']} (cod {cod})")
        row = await db.bank_ledger.find_one({"ref_key": f"DPREMIT:{sj['remit_id']}"}, {"_id": 0})
        check("bank row categorised as cod_remittance",
              (row or {}).get("category") == "cod_remittance", str((row or {}).get("category")))
        check("bank row flagged as a liability, not revenue",
              (row or {}).get("money_nature") == "liability", str((row or {}).get("money_nature")))
        ordoc = await db.orders.find_one({"id": oid}, {"_id": 0, "dp_cash_remitted": 1})
        check("order marked remitted", (ordoc or {}).get("dp_cash_remitted") is True)
        check("replaying verify is a no-op",
              requests.post(f"{BASE}/delivery-partner/remit/verify", headers=dh, timeout=30, json={
                  "remit_id": sj["remit_id"], "razorpay_order_id": sj["razorpay_order_id"],
                  "razorpay_payment_id": "pay_MOCK_replay", "razorpay_signature": "x",
              }).json().get("already_verified") is True)
        bank2 = await bank.totals()
        check("replay did NOT double the bank credit",
              abs(bank2["credits"] - bank1["credits"]) < 0.01)
        rem = requests.get(f"{BASE}/delivery-partner/me/remittances", headers=dh, timeout=30).json()
        check("payment receipt listed", len(rem.get("items") or []) >= 1)

        # 7 ── isolation: unmapping removes visibility
        requests.put(f"{BASE}/admin/delivery-partners/{uid}/vendors", headers=ah,
                     json={"vendor_ids": []}, timeout=30)
        o = requests.get(f"{BASE}/delivery-partner/me/orders", headers=dh, timeout=30).json()
        check("unmapped ⇒ rider loses visibility", len(o.get("items") or []) == 0)
        check("cannot touch an unmapped shop's order",
              requests.patch(f"{BASE}/delivery-partner/orders/{oid}/status", headers=dh,
                             json={"status": "delivered"}, timeout=30).status_code == 403)

        # 8 ── Excel + role isolation
        x = requests.get(f"{BASE}/delivery-partner/me/export.xlsx", headers=dh, timeout=60)
        check("excel export downloads", x.status_code == 200 and len(x.content) > 3000,
              f"{x.status_code} {len(x.content)} bytes")
        check("a buyer cannot use rider endpoints",
              requests.get(f"{BASE}/delivery-partner/me/net-worth", headers=bh, timeout=30).status_code == 403)
    finally:
        await cleanup(uid, order_ids)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    print("ALL PASS" if not failed else "FAILURES:\n  " + "\n  ".join(failed))
    sys.exit(1 if failed else 0)


asyncio.run(main())
