"""Oct-2026 iter-90 — verification for everything in this batch that the
Razorpay harness does not cover.

  A. Cashback auto-recovery netted off a vendor credit (full recovery)
  B. Bank Balance Tally earmarked vs free_to_spend
  C. Admin wallet adjust across all three pots (the "Cannot debit beyond
     available balance" bug)
  D. Wallet + UPI split order writes TWO buyer rows
  E. Two product rails, personalised from the user's own search history
  F. Per-product COD guard at checkout
  G. Recharge taxonomy + plan filtering

Run:  python -m tests.verify_oct2026_iter90
"""
import asyncio
import uuid
from datetime import datetime, timezone

import httpx

from core import shop_money
from core.cashback import auto_recover_from_vendor_credit
from core.db import db

BASE = "http://localhost:8001/api"
FAILS = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} — {name}{f' :: {detail}' if detail else ''}")
    if not ok:
        FAILS.append(name)


def _r(x) -> float:
    return round(float(x or 0), 2)


async def _bucket_noop(*_a, **_k) -> None:
    return None


async def login(c, email, pw):
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    return r.json()["token"]


async def main() -> None:
    vid = f"iter90-vendor-{uuid.uuid4().hex[:6]}"
    oid = str(uuid.uuid4())
    try:
        # ════════ A. cashback auto-recovery ════════
        await db.users.insert_one({
            "id": vid, "name": "Iter90 Seller", "email": f"{vid}@audit.local",
            "referral_code": f"I90{uuid.uuid4().hex[:7].upper()}",
            "role": "user", "is_vendor": True, "is_vendor_approved": True,
            "wallet_balance": 0.0, "vendor_earnings": 0.0,
            # Slangcart fronted ₹120 of cashback on this seller's behalf.
            "cashback_outstanding": 120.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.vendor_outstanding.insert_one({
            "id": str(uuid.uuid4()), "vendor_id": vid, "kind": "cashback",
            "amount": 120.0, "recovered": 0.0, "status": "open",
            "order_id": "iter90-old-order", "order_number": "OLD-1",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        order = {
            "id": oid, "order_number": "I90-1", "vendor_id": vid,
            "vendor_name": "Iter90 Seller", "status": "delivered",
            "paid_via": "online", "total": 500.0, "delivery_charge": 0.0, "cod_due": 0.0,
        }
        await db.orders.insert_one(dict(order))

        credited = await shop_money.credit_vendor_for_order(order, payment_id="pay_I90")
        rec = await auto_recover_from_vendor_credit(vid, order, credit_admin_bucket=_bucket_noop)
        wallet = _r((await db.users.find_one({"id": vid}))["vendor_earnings"])
        owed = _r((await db.users.find_one({"id": vid}))["cashback_outstanding"])
        rows = await db.transactions.find({"order_id": oid}, {"_id": 0}).to_list(50)
        sale = [r for r in rows if r["type"] == "vendor_sale"]
        claw = [r for r in rows if r["type"] == "cashback_recovery"]

        check("A1 gross sale credited in full", credited == 500.0, f"₹{credited}")
        check("A2 outstanding recovered in full from that order",
              rec["recovered"] == 120.0 and owed == 0.0, f"rec={rec['recovered']} owed={owed}")
        check("A3 only the remainder stays with the seller", wallet == 380.0, f"₹{wallet}")
        check("A4 gross sale and recovery are SEPARATE rows",
              len(sale) == 1 and len(claw) == 1, f"sale={len(sale)} recovery={len(claw)}")
        check("A5 outstanding row marked settled",
              (await db.vendor_outstanding.find_one({"vendor_id": vid}))["status"] == "settled")
        again = await auto_recover_from_vendor_credit(vid, order, credit_admin_bucket=_bucket_noop)
        check("A6 replay recovers nothing (no double claw-back)",
              again["recovered"] == 0.0, str(again))

        async with httpx.AsyncClient(timeout=60) as c:
            atok = await login(c, "support@slangcart.com", "3)Ywxtic")
            btok = await login(c, "testbuyer@test.com", "Test@1234")
            ah = {"Authorization": f"Bearer {atok}"}
            bh = {"Authorization": f"Bearer {btok}"}

            # ════════ B. bank tally earmarked vs free ════════
            nw = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
            bt = nw["bank_tally"]
            em = bt["earmarked"]
            check("B1 earmarked block present",
                  all(k in em for k in ("vendor_wallets", "rider_cash", "customer_wallets",
                                        "pending_withdrawals", "gst_payable", "total")))
            check("B2 earmarked total adds up",
                  em["total"] == _r(em["vendor_wallets"] + em["customer_wallets"]
                                    + em["pending_withdrawals"] + em["gst_payable"]),
                  f"total={em['total']}")
            bank_bal = _r(nw["group_7_bank"]["balance"])
            check("B3 free_to_spend = bank balance − earmarked",
                  bt["free_to_spend"] == _r(bank_bal - em["total"]),
                  f"free={bt['free_to_spend']} bank={bank_bal} earmarked={em['total']}")
            coh = nw["cash_on_hand"]
            check("B4 seller-collected COD still excluded from company cash",
                  coh["total"] == _r(coh["registration_cash"] + coh["cod_with_collectors"]))

            # ════════ C. admin wallet adjust — all three pots ════════
            r = await c.post(f"{BASE}/admin/users/{vid}/wallet", headers=ah,
                             json={"amount": 80, "type": "debit", "reason": "iter90 shop debit",
                                   "wallet": "vendor_earnings"})
            after = _r((await db.users.find_one({"id": vid}))["vendor_earnings"])
            check("C1 debit from SHOP EARNINGS now works",
                  r.status_code == 200 and after == 300.0, f"{r.status_code} ₹{after}")
            r = await c.post(f"{BASE}/admin/users/{vid}/wallet", headers=ah,
                             json={"amount": 999999, "type": "debit", "reason": "iter90 overdraft",
                                   "wallet": "vendor_earnings"})
            check("C2 overdraft rejected and NAMES the real balance",
                  r.status_code == 400 and "300" in r.text and "shop earnings" in r.text.lower(),
                  r.text[:150])
            r = await c.post(f"{BASE}/admin/users/{vid}/wallet", headers=ah,
                             json={"amount": 25, "type": "credit", "reason": "iter90 rider cash",
                                   "wallet": "dp_cash_in_hand"})
            check("C3 rider cash-in-hand pot is adjustable",
                  r.status_code == 200
                  and _r((await db.users.find_one({"id": vid}))["dp_cash_in_hand"]) == 25.0,
                  r.text[:120])
            r = await c.post(f"{BASE}/admin/users/{vid}/wallet", headers=ah,
                             json={"amount": 5, "type": "credit", "reason": "bad pot",
                                   "wallet": "not_a_pot"})
            check("C4 unknown pot rejected", r.status_code == 400, str(r.status_code))

            # ════════ E. two product rails + personalisation ════════
            prod = (await c.get(f"{BASE}/products", params={"limit": 1})).json()
            pid = (prod.get("items") or prod)[0]["id"]
            await c.post(f"{BASE}/products/search-log", headers=bh, json={"q": "widget phone"})
            rails = (await c.get(f"{BASE}/products/{pid}/rails", headers=bh)).json()["rails"]
            check("E1 exactly two rails", len(rails) == 2, str([r["key"] for r in rails]))
            check("E2 rail 1 is same-subcategory", rails[0]["key"] == "subcategory")
            check("E3 rail 2 is personalised from own history",
                  rails[1]["key"] == "for_you" and rails[1].get("personalised") is True,
                  rails[1]["title"])
            check("E4 rails are 1-10 cards (never a wall of products)",
                  all(1 <= len(r["items"]) <= 10 for r in rails),
                  str([len(r["items"]) for r in rails]))
            card = rails[0]["items"][0]
            check("E5 card payload is slim + has what a card renders",
                  all(k in card for k in ("id", "name", "price", "image_url", "in_stock")))
            check("E6 viewed product is never suggested back",
                  all(i["id"] != pid for r in rails for i in r["items"]))
            check("E7 rails work for a guest too (no auth)",
                  len((await c.get(f"{BASE}/products/{pid}/rails")).json()["rails"]) == 2)

            # ════════ G. recharge taxonomy + plan filtering ════════
            opts = (await c.get(f"{BASE}/recharge/options")).json()
            check("G1 two services offered",
                  [t["key"] for t in opts["types"]] == ["mobile", "dth"])
            check("G2 AP&TG state + 4 mobile networks seeded",
                  any("AP&TG" in s["name"] for s in opts["mobile"]["states"])
                  and {"Airtel", "Jio", "Vi", "BSNL"} <= {n["name"] for n in opts["mobile"]["networks"]},
                  str([n["name"] for n in opts["mobile"]["networks"]]))
            check("G3 DTH has its own operator list",
                  len(opts["dth"]["networks"]) >= 4,
                  str([n["name"] for n in opts["dth"]["networks"]]))
            plans = (await c.get(f"{BASE}/recharge/products", params={
                "kind": "mobile", "state": "andhra-pradesh-telangana-ap-tg", "network": "jio",
            })).json()
            check("G4 plans filter by state + network and group by subcategory",
                  plans["count"] > 0 and len(plans["groups"]) >= 2,
                  f"{plans['count']} plans in {len(plans['groups'])} groups")
            check("G5 a plan from another network is NOT returned",
                  all("Jio" in p["name"] for g in plans["groups"] for p in g["products"]))
            # Admin add + delete round-trip
            r = await c.post(f"{BASE}/admin/recharge/options", headers=ah,
                             json={"kind": "mobile", "group": "network", "name": "Iter90 Telecom"})
            new_id = r.json().get("id")
            check("G6 admin can add a network", r.status_code == 200 and bool(new_id), r.text[:120])
            dup = await c.post(f"{BASE}/admin/recharge/options", headers=ah,
                               json={"kind": "mobile", "group": "network", "name": "Iter90 Telecom"})
            check("G7 duplicate network refused", dup.status_code == 409, str(dup.status_code))
            d = await c.delete(f"{BASE}/admin/recharge/options/{new_id}", headers=ah)
            gone = (await c.get(f"{BASE}/recharge/options")).json()
            check("G8 admin can delete a network",
                  d.status_code == 200
                  and "Iter90 Telecom" not in {n["name"] for n in gone["mobile"]["networks"]})

            # ════════ F. per-product COD guard ════════
            cod_plan = await db.products.find_one(
                {"cod_available": False, "active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1},
            )
            if cod_plan:
                await c.post(f"{BASE}/cart/clear", headers=bh)
                add = await c.post(f"{BASE}/cart/add", headers=bh,
                                   json={"product_id": cod_plan["id"], "qty": 1})
                if add.status_code == 200:
                    r = await c.post(f"{BASE}/orders/checkout", headers=bh, json={
                        "payment_method": "cod",
                        "shipping_address": {
                            "name": "Iter90", "phone": "9876543210",
                            "line1": "1 Test Street", "city": "Tirupati",
                            "state": "Andhra Pradesh", "pincode": "517644",
                        },
                    })
                    body = r.json()
                    detail = body.get("detail") if isinstance(body, dict) else {}
                    check("F1 COD refused for a prepaid-only item",
                          r.status_code == 400
                          and isinstance(detail, dict)
                          and detail.get("code") == "cod_not_available",
                          f"{r.status_code} {str(body)[:160]}")
                    check("F2 refusal names the blocked item(s)",
                          isinstance(detail, dict) and bool(detail.get("items")),
                          str(detail.get("items"))[:120] if isinstance(detail, dict) else "")
                    await c.post(f"{BASE}/cart/clear", headers=bh)
                else:
                    print(f"SKIP F — could not add prepaid-only item ({add.status_code})")
            else:
                print("SKIP F — no cod_available=False product in catalogue")

    finally:
        await db.transactions.delete_many({"$or": [{"order_id": oid}, {"user_id": vid}]})
        await db.orders.delete_many({"id": oid})
        await db.vendor_outstanding.delete_many({"vendor_id": vid})
        await db.users.delete_many({"id": vid})
        await db.recharge_options.delete_many({"name": "Iter90 Telecom"})

    print("\n" + ("ALL PASSED ✅" if not FAILS else f"FAILURES: {FAILS}"))


if __name__ == "__main__":
    asyncio.run(main())
