"""Membership batch (Jun-2026) — the ₹118 split, member benefits, per-shop
payout structure and the product re-approval rule.

Run:  python3 tests/test_membership_batch.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import db  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"


async def main() -> None:
    ts = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=90) as c:
        ah = {"Authorization": "Bearer " + (await c.post(
            f"{BASE}/auth/login",
            json={"email": "support@slangcart.com", "password": "3)Ywxtic"},
        )).json()["token"]}
        vh = {"Authorization": "Bearer " + (await c.post(
            f"{BASE}/auth/login",
            json={"email": "testvendor@test.com", "password": "Test@1234"},
        )).json()["token"]}
        bh = {"Authorization": "Bearer " + (await c.post(
            f"{BASE}/auth/login",
            json={"email": "testbuyer@test.com", "password": "Test@1234"},
        )).json()["token"]}

        # ── 1. the split the app is told about ───────────────────────────
        cfg = (await c.get(f"{BASE}/subscription/config", headers=bh)).json()
        check("₹118 splits into 18 GST + 50 member + 50 platform",
              abs(cfg["price"] - 118) < 0.01 and abs(cfg["gst"] - 18) < 0.01
              and abs(cfg["member_cashback"] - 50) < 0.01
              and abs(cfg["platform_revenue"] - 50) < 0.01,
              f'{cfg["gst"]}/{cfg["member_cashback"]}/{cfg["platform_revenue"]}')
        check("the invite bonus comes out of the platform's share",
              abs(cfg["invite_bonus"] - 25) < 0.01
              and abs(cfg["platform_revenue_with_invite"] - 25) < 0.01,
              f'{cfg["invite_bonus"]} / {cfg["platform_revenue_with_invite"]}')
        keys = [b["key"] for b in cfg["benefits"]]
        check("the removed benefits are gone",
              not ({"shopping", "priority_customer", "higher_cashback", "delivery_perks",
                    "lifetime"} & set(keys)), str(keys))
        check("the asked-for benefits are there",
              {"cashback", "support", "ads", "numbers", "apply", "referral"} <= set(keys),
              str(keys))

        # ── 2. a real ₹118 booking ───────────────────────────────────────
        joiner_id = f"TEST_sub_{uuid.uuid4().hex[:6]}"
        sponsor_id = f"TEST_spon_{uuid.uuid4().hex[:6]}"
        code = f"TST{uuid.uuid4().hex[:5].upper()}"
        await db.users.insert_one({
            "id": sponsor_id, "name": "Test Sponsor", "email": f"{sponsor_id}@test.com",
            "role": "user", "registration_paid": True, "referral_code": code,
            "wallet_balance": 0.0, "created_at": ts,
        })
        await db.users.insert_one({
            "id": joiner_id, "name": "Test Joiner", "email": f"{joiner_id}@test.com",
            "role": "user", "registration_paid": True, "sponsor_id": sponsor_id,
            "referred_by": code, "wallet_balance": 0.0, "created_at": ts,
            "referral_code": f"J{uuid.uuid4().hex[:6].upper()}",
        })
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": joiner_id, "type": "registration_fee",
            "amount": 118.0, "status": "success", "created_at": ts,
            "description": "test subscription payment",
        })
        from server import _trigger_referral_commissions

        fresh = await db.users.find_one({"id": joiner_id})
        await _trigger_referral_commissions(fresh)
        j = await db.users.find_one({"id": joiner_id}, {"_id": 0, "wallet_balance": 1})
        sp = await db.users.find_one({"id": sponsor_id}, {"_id": 0, "wallet_balance": 1})
        check("the member got ₹50 instantly",
              abs(float(j["wallet_balance"]) - 50.0) < 0.01, str(j))
        check("the inviter got ₹25", abs(float(sp["wallet_balance"]) - 25.0) < 0.01, str(sp))
        rows = await db.transactions.find(
            {"user_id": {"$in": [joiner_id, sponsor_id]},
             "type": {"$in": ["subscription_cashback", "referral_payout"]}},
        ).to_list(20)
        check("one cashback row and one bonus row, both described",
              len(rows) == 2 and all(r.get("description") for r in rows),
              str([(r["type"], r.get("amount")) for r in rows]))

        # replay must change nothing
        await _trigger_referral_commissions(await db.users.find_one({"id": joiner_id}))
        j2 = await db.users.find_one({"id": joiner_id}, {"_id": 0, "wallet_balance": 1})
        check("replaying the subscription pays nothing twice",
              abs(float(j2["wallet_balance"]) - 50.0) < 0.01, str(j2))

        # an UNPAID account books nothing
        ghost_id = f"TEST_ghost_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": ghost_id, "name": "Ghost", "email": f"{ghost_id}@test.com",
            "role": "user", "registration_paid": False, "wallet_balance": 0.0,
            "created_at": ts, "referral_code": f"G{uuid.uuid4().hex[:6].upper()}",
        })
        await _trigger_referral_commissions(await db.users.find_one({"id": ghost_id}))
        g = await db.users.find_one({"id": ghost_id}, {"_id": 0, "wallet_balance": 1})
        check("an unpaid account is never credited",
              abs(float(g["wallet_balance"])) < 0.01, str(g))

        # a PAID flag with no payment row books nothing either
        liar_id = f"TEST_liar_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": liar_id, "name": "Liar", "email": f"{liar_id}@test.com",
            "role": "user", "registration_paid": True, "wallet_balance": 0.0,
            "created_at": ts, "referral_code": f"L{uuid.uuid4().hex[:6].upper()}",
        })
        await _trigger_referral_commissions(await db.users.find_one({"id": liar_id}))
        li = await db.users.find_one({"id": liar_id}, {"_id": 0, "wallet_balance": 1})
        check("paid flag without a payment row is refused",
              abs(float(li["wallet_balance"])) < 0.01, str(li))

        # ── 2b. the UPI / offline path must still pay ₹50, not ₹59 ───────
        upi_id = f"TEST_upi_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": upi_id, "name": "Test UPI Joiner", "email": f"{upi_id}@test.com",
            "role": "user", "registration_paid": True, "wallet_balance": 0.0,
            "registration_gst_collected_at_create": True, "created_at": ts,
            "referral_code": f"U{uuid.uuid4().hex[:6].upper()}",
        })
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": upi_id, "type": "registration_fee",
            "amount": 118.0, "status": "success", "created_at": ts,
            "description": "test UPI subscription payment",
        })
        await _trigger_referral_commissions(await db.users.find_one({"id": upi_id}))
        u = await db.users.find_one({"id": upi_id}, {"_id": 0, "wallet_balance": 1})
        check("the UPI / offline path also pays exactly ₹50",
              abs(float(u["wallet_balance"]) - 50.0) < 0.01, str(u))

        # ── 2c. two triggers at once book the revenue ONCE ────────────────
        race_id = f"TEST_race_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": race_id, "name": "Test Race", "email": f"{race_id}@test.com",
            "role": "user", "registration_paid": True, "wallet_balance": 0.0,
            "created_at": ts, "referral_code": f"R{uuid.uuid4().hex[:6].upper()}",
        })
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": race_id, "type": "registration_fee",
            "amount": 118.0, "status": "success", "created_at": ts,
        })
        admin_before = await db.users.find_one({"email": "support@slangcart.com"},
                                               {"_id": 0, "wallet_buckets": 1})
        rb = round(float((admin_before.get("wallet_buckets") or {}).get("direct_signup") or 0), 2)
        gb = round(float((admin_before.get("wallet_buckets") or {}).get("gst_collected") or 0), 2)
        doc = await db.users.find_one({"id": race_id})
        await asyncio.gather(*[_trigger_referral_commissions(dict(doc)) for _ in range(4)],
                             return_exceptions=True)
        admin_after = await db.users.find_one({"email": "support@slangcart.com"},
                                              {"_id": 0, "wallet_buckets": 1})
        ra = round(float((admin_after.get("wallet_buckets") or {}).get("direct_signup") or 0), 2)
        ga = round(float((admin_after.get("wallet_buckets") or {}).get("gst_collected") or 0), 2)
        check("4 triggers at once book ₹50 revenue once", abs((ra - rb) - 50.0) < 0.02,
              f"{rb} → {ra}")
        check("4 triggers at once book ₹18 GST once", abs((ga - gb) - 18.0) < 0.02,
              f"{gb} → {ga}")
        rows_race = await db.transactions.count_documents(
            {"source_user_id": race_id, "type": "direct_signup_credit"})
        check("exactly one revenue row", rows_race == 1, str(rows_race))
        r_wallet = await db.users.find_one({"id": race_id}, {"_id": 0, "wallet_balance": 1})
        check("the member is still paid exactly ₹50 under a race",
              abs(float(r_wallet["wallet_balance"]) - 50.0) < 0.01, str(r_wallet))

        # ── 2d. an early trigger must not burn the payout ─────────────────
        early_id = f"TEST_early_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": early_id, "name": "Test Early", "email": f"{early_id}@test.com",
            "role": "user", "registration_paid": True, "wallet_balance": 0.0,
            "created_at": ts, "referral_code": f"E{uuid.uuid4().hex[:6].upper()}",
        })
        await _trigger_referral_commissions(await db.users.find_one({"id": early_id}))
        burnt = await db.users.find_one({"id": early_id}, {"_id": 0, "commission_triggered": 1})
        check("a skipped split releases the claim", not burnt.get("commission_triggered"),
              str(burnt))
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": early_id, "type": "registration_fee",
            "amount": 118.0, "status": "success", "created_at": ts,
        })
        await _trigger_referral_commissions(await db.users.find_one({"id": early_id}))
        e = await db.users.find_one({"id": early_id}, {"_id": 0, "wallet_balance": 1})
        check("…and pays ₹50 once the payment lands",
              abs(float(e["wallet_balance"]) - 50.0) < 0.01, str(e))

        # ── 2e. a small top-up is not a subscription payment ──────────────
        topup_id = f"TEST_topup_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": topup_id, "name": "Test Topup", "email": f"{topup_id}@test.com",
            "role": "user", "registration_paid": True, "wallet_balance": 0.0,
            "created_at": ts, "referral_code": f"T{uuid.uuid4().hex[:6].upper()}",
        })
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()), "user_id": topup_id, "type": "wallet_topup",
            "amount": 10.0, "status": "success", "created_at": ts,
        })
        await _trigger_referral_commissions(await db.users.find_one({"id": topup_id}))
        tu = await db.users.find_one({"id": topup_id}, {"_id": 0, "wallet_balance": 1})
        check("a ₹10 top-up does not unlock the split",
              abs(float(tu["wallet_balance"])) < 0.01, str(tu))

        # ── 3. service numbers ───────────────────────────────────────────
        rc_free = (await c.get(f"{BASE}/services/reveal-config", headers=bh)).json()
        check("a free account is charged for a provider's number",
              rc_free.get("is_subscriber") is False and float(rc_free.get("total") or 0) > 0,
              str({k: rc_free.get(k) for k in ("is_subscriber", "total")}))
        # Same account, now a member — same endpoint, no charge.
        await db.users.update_one({"email": "testbuyer@test.com"},
                                  {"$set": {"registration_paid": True}})
        rc_mem = (await c.get(f"{BASE}/services/reveal-config", headers=bh)).json()
        await db.users.update_one({"email": "testbuyer@test.com"},
                                  {"$set": {"registration_paid": False}})
        check("a member pays nothing for a provider's number",
              rc_mem.get("is_subscriber") is True and float(rc_mem.get("total") or 0) == 0.0,
              str({k: rc_mem.get(k) for k in ("is_subscriber", "total", "non_member_total")}))
        check("the non-member price is still quoted to the member",
              float(rc_mem.get("non_member_total") or 0) > 0, str(rc_mem.get("non_member_total")))

        # ── 4. per-shop payout structure ─────────────────────────────────
        ps = (await c.get(f"{BASE}/admin/payout-structure/vendors", headers=ah)).json()
        check("every shop is listed with its effective rates",
              ps["total"] > 0 and all("effective_cashback_pct" in r for r in ps["vendors"]),
              f'{ps["total"]} shops')
        r = await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}",
                        headers=ah, json={"cashback_pct": 4.5, "clear": []})
        check("a shop can be given its own cashback %", r.status_code == 200, r.text[:140])
        ps2 = (await c.get(f"{BASE}/admin/payout-structure/vendors", headers=ah)).json()
        row = next(x for x in ps2["vendors"] if x["vendor_id"] == VID)
        check("the override shows on the shop", abs(row["effective_cashback_pct"] - 4.5) < 0.01
              and row["has_override"] is True, str(row["effective_cashback_pct"]))
        from core.cashback import product_cashback_pct

        settings = await db.settings.find_one({"id": "global"}, {"_id": 0}) or {}
        vdoc = await db.users.find_one({"id": VID}, {"_id": 0, "default_cashback_pct": 1})
        check("the engine reads the shop's rate for a product with none",
              abs(product_cashback_pct({}, {**settings, "cashback_enabled": True}, vdoc) - 4.5) < 0.01)
        check("a product's own rate still wins",
              abs(product_cashback_pct({"cashback_pct": 2}, {**settings, "cashback_enabled": True}, vdoc) - 2) < 0.01)
        r = await c.put(f"{BASE}/admin/payout-structure/vendors/{VID}",
                        headers=ah, json={"clear": ["cashback_pct"]})
        ps3 = (await c.get(f"{BASE}/admin/payout-structure/vendors", headers=ah)).json()
        row3 = next(x for x in ps3["vendors"] if x["vendor_id"] == VID)
        check("clearing it puts the shop back on the default",
              row3["cashback_pct"] is None
              and abs(row3["effective_cashback_pct"] - ps3["defaults"]["cashback_pct"]) < 0.01,
              str(row3["effective_cashback_pct"]))

        # ── 5. a seller's edit needs approval again ──────────────────────
        pid = f"TEST_prod_{uuid.uuid4().hex[:6]}"
        await db.products.insert_one({
            "id": pid, "name": "Membership test product", "price": 100.0, "stock": 5,
            "vendor_id": VID, "vendor_email": "testvendor@test.com",
            "is_published": True, "created_at": ts,
        })
        r = await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh,
                          json={"stock": 9})
        after_stock = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1, "review_status": 1})
        check("a stock-only change keeps the product live",
              r.status_code == 200 and after_stock.get("is_published") is True,
              str(after_stock))
        r = await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh,
                          json={"price": 150})
        after_price = await db.products.find_one(
            {"id": pid}, {"_id": 0, "is_published": 1, "review_status": 1, "review_fields": 1})
        check("a price change pulls it out of the shop for approval",
              r.status_code == 200 and after_price.get("is_published") is False
              and after_price.get("review_status") == "pending",
              str(after_price))
        check("the admin can see WHAT changed",
              "price" in (after_price.get("review_fields") or []),
              str(after_price.get("review_fields")))
        pub = await c.patch(f"{BASE}/admin/products/{pid}", headers=ah,
                            json={"is_published": True})
        after_pub = await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1, "review_status": 1})
        check("admin approval puts it back and clears the flag",
              pub.status_code == 200 and after_pub.get("is_published") is True
              and after_pub.get("review_status") == "approved", str(after_pub))
        check("a vendor cannot publish it himself",
              (await c.patch(f"{BASE}/vendor/me/products/{pid}", headers=vh,
                             json={"is_published": True, "name": "sneaky"})).status_code == 200
              and (await db.products.find_one({"id": pid}, {"_id": 0, "is_published": 1}))
              .get("is_published") is False)

        # ── 6. admin screen data ─────────────────────────────────────────
        ac = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
        check("the admin screen shows the split and the member counts",
              "subscribers" in ac and "non_subscribers" in ac and len(ac["benefits"]) >= 6,
              f'{ac.get("subscribers")} members / {ac.get("non_subscribers")} free')
        r = await c.put(f"{BASE}/admin/subscription/config", headers=ah,
                        json={"invite_bonus": 500})
        check("a bonus bigger than the platform's share is refused",
              r.status_code == 400, f"{r.status_code} {r.text[:90]}")
        kept = (await c.get(f"{BASE}/admin/subscription/config", headers=ah)).json()
        check("the refused bonus was never saved",
              abs(float(kept["invite_bonus"]) - 25.0) < 0.01, str(kept["invite_bonus"]))
        await c.put(f"{BASE}/admin/subscription/config", headers=ah, json={"invite_bonus": 25})

        # cleanup
        await db.products.delete_one({"id": pid})
        seeded = [joiner_id, sponsor_id, ghost_id, liar_id, upi_id, race_id, early_id, topup_id]
        await db.users.delete_many({"id": {"$in": seeded}})
        await db.transactions.delete_many({"user_id": {"$in": seeded}})
        await db.transactions.delete_many({"related_signup_id": {"$in": seeded}})
        await db.transactions.delete_many({"source_user_id": {"$in": seeded}})

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
