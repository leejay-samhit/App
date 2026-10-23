"""Iter101 — RETEST of iter100 money fixes: GST-at-create + inviter, 8x concurrent
triggers, mixed concurrent/sequential + direct split replays, released claim,
strict payment-row check, total_earned net of invite bonus, roster counter on
release/retrigger. Cleans up after itself (bucket + total_earned reversal).
Run: cd /app/backend && python3 tests/iter101_subscription_race_probe.py
"""
import asyncio, os, sys, uuid, logging
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)
from core.db import db  # noqa
import server  # noqa
from server import _trigger_referral_commissions, _credit_no_ref_signup_to_admin, credit_admin_bucket, ADMIN_EMAIL

RES, SEEDED = [], []


def check(n, ok, extra=""):
    RES.append((n, ok)); print(("PASS" if ok else "FAIL"), "·", n, ("— " + str(extra)) if extra != "" else "")


async def adm():
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "wallet_buckets": 1, "total_earned": 1, "wallet_balance": 1})
    b = a.get("wallet_buckets") or {}
    return {"ds": float(b.get("direct_signup") or 0), "gst": float(b.get("gst_collected") or 0),
            "da": float(b.get("direct_added") or 0), "te": float(a.get("total_earned") or 0)}


def diff(a, b):
    return {k: round(b[k] - a[k], 2) for k in a}


async def mk_user(paid=True, sponsor=None, payrow=None, extra=None):
    uid = f"TEST_i101_{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc).isoformat()
    doc = {"id": uid, "name": "TEST i101", "email": f"{uid}@test.com", "role": "user",
           "registration_paid": paid, "wallet_balance": 0.0, "created_at": ts,
           "referral_code": f"T{uuid.uuid4().hex[:7].upper()}", "direct_referrals_count": 0}
    if sponsor:
        doc["sponsor_id"] = sponsor
    doc.update(extra or {})
    await db.users.insert_one(doc); SEEDED.append(uid)
    rows = [{"type": "registration_fee", "amount": 118.0, "status": "success"}] if payrow is None else payrow
    for r in rows:
        await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "created_at": ts, **r})
    return uid


async def u(uid):
    return await db.users.find_one({"id": uid}, {"_id": 0})


async def wb(uid):
    return round(float((await u(uid)).get("wallet_balance") or 0), 2)


async def rows(j):
    ds = await db.transactions.count_documents({"source_user_id": j, "type": "direct_signup_credit"})
    gst = await db.transactions.count_documents({"source_user_id": j, "type": "gst_collected"})
    cb = await db.transactions.count_documents({"user_id": j, "type": "subscription_cashback"})
    inv = await db.transactions.count_documents({"source_user_id": j, "type": "referral_payout"})
    return ds, gst, cb, inv


async def main():
    s0 = await adm()
    try:
        idx = await db.transactions.index_information()
        uniq = [v for v in idx.values() if v.get("key") and v["key"][0][0] == "idempotency_key" and v.get("unique")]
        check("unique index on transactions.idempotency_key exists", bool(uniq), uniq)

        # 1. FIX1 — GST-at-create WITH a member inviter
        inv = await mk_user()
        await _trigger_referral_commissions(await u(inv))
        j = await mk_user(sponsor=inv, payrow=[], extra={"registration_gst_collected_at_create": True})
        a0 = await adm(); w_inv0 = await wb(inv)
        await _trigger_referral_commissions(await u(j))
        d = diff(a0, await adm())
        check("F1 gst-at-create+inviter: member 50", await wb(j) == 50, await wb(j))
        check("F1 inviter +25", round(await wb(inv) - w_inv0, 2) == 25, await wb(inv) - w_inv0)
        check("F1 direct_signup +25 & gst +0", d["ds"] == 25 and d["gst"] == 0, d)
        check("F1 total_earned +25", d["te"] == 25, d)
        r = await rows(j)
        check("F1 rows: 1 ds row, 0 gst row, 1 cashback, 1 invite", r == (1, 0, 1, 1), r)
        row = await db.transactions.find_one({"source_user_id": j, "type": "direct_signup_credit"})
        check("F1 ds row amount 25, gst_amount 18, member_cashback 50",
              row and row["amount"] == 25 and row["gst_amount"] == 18 and row["member_cashback"] == 50,
              row and (row["amount"], row["gst_amount"], row["member_cashback"]))

        # 2. FIX2 — 8 concurrent triggers with inviter
        inv2 = await mk_user(); await _trigger_referral_commissions(await u(inv2))
        j2 = await mk_user(sponsor=inv2)
        doc = await u(j2)
        a0 = await adm(); w0 = await wb(inv2)
        await asyncio.gather(*[_trigger_referral_commissions(dict(doc)) for _ in range(8)])
        d = diff(a0, await adm())
        check("F2 8x concurrent: member 50", await wb(j2) == 50, await wb(j2))
        check("F2 8x concurrent: inviter +25", round(await wb(inv2) - w0, 2) == 25, await wb(inv2) - w0)
        check("F2 8x concurrent: ds +25, gst +18, te +25", d["ds"] == 25 and d["gst"] == 18 and d["te"] == 25, d)
        check("F2 8x concurrent rows (1,1,1,1)", await rows(j2) == (1, 1, 1, 1), await rows(j2))
        check("F2 inviter roster counter +1", (await u(inv2)).get("direct_referrals_count") == 1,
              (await u(inv2)).get("direct_referrals_count"))

        # 3. FIX2 — mix: clear commission_triggered and hammer the split DIRECTLY
        #    (8 concurrent split calls) + 3 sequential triggers + 4 concurrent triggers
        j3 = await mk_user(sponsor=inv2)
        a0 = await adm(); w0 = await wb(inv2)
        d3, s3 = await u(j3), await u(inv2)
        await asyncio.gather(*[_credit_no_ref_signup_to_admin(dict(d3), dict(s3)) for _ in range(8)],
                             *[_trigger_referral_commissions(dict(d3)) for _ in range(4)])
        for _ in range(3):
            await db.users.update_one({"id": j3}, {"$unset": {"commission_triggered": ""}})
            await _trigger_referral_commissions(await u(j3))
        await asyncio.gather(*[_credit_no_ref_signup_to_admin(await u(j3), s3) for _ in range(4)])
        d = diff(a0, await adm())
        check("F2 mixed direct+concurrent+sequential: member 50", await wb(j3) == 50, await wb(j3))
        check("F2 mixed: inviter +25 once", round(await wb(inv2) - w0, 2) == 25, await wb(inv2) - w0)
        check("F2 mixed: ds +25, gst +18, te +25", d["ds"] == 25 and d["gst"] == 18 and d["te"] == 25, d)
        check("F2 mixed rows (1,1,1,1)", await rows(j3) == (1, 1, 1, 1), await rows(j3))
        check("F2 mixed: inviter roster counter == 2 (j2 + j3) — not bumped per replay",
              (await u(inv2)).get("direct_referrals_count") == 2, (await u(inv2)).get("direct_referrals_count"))

        # 4. FIX3 — released claim; also roster counter on release+retrigger
        inv4 = await mk_user(); await _trigger_referral_commissions(await u(inv4))
        f = await mk_user(sponsor=inv4, payrow=[])
        a0 = await adm(); w_inv4 = await wb(inv4)
        await _trigger_referral_commissions(await u(f))
        check("F3 no payment row: commission_triggered released", not (await u(f)).get("commission_triggered"),
              (await u(f)).get("commission_triggered"))
        check("F3 no payment row: nothing booked", diff(a0, await adm())["ds"] == 0 and await wb(f) == 0)
        await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": f, "type": "registration_fee",
                                          "amount": 118.0, "status": "success",
                                          "created_at": datetime.now(timezone.utc).isoformat()})
        await _trigger_referral_commissions(await u(f))
        d = diff(a0, await adm())
        check("F3 after row lands: member 50, inviter +25, ds +25", await wb(f) == 50 and round(await wb(inv4) - w_inv4, 2) == 25 and d["ds"] == 25,
              (await wb(f), await wb(inv4) - w_inv4, d))
        check("F3 commission_triggered now set", (await u(f)).get("commission_triggered") is True)
        rc = (await u(inv4)).get("direct_referrals_count")
        check("F3 inviter roster counter == 1 after skip+retrigger (not double-counted)", rc == 1, rc)
        # unpaid flag also releases
        f2 = await mk_user(paid=False)
        await _trigger_referral_commissions(await u(f2))
        check("F3 registration_paid=False: released + nothing paid",
              not (await u(f2)).get("commission_triggered") and await wb(f2) == 0)

        # 5. FIX4 — strict payment-row check
        for name, prow in [("₹10 wallet_topup", {"type": "wallet_topup", "amount": 10.0, "status": "success"}),
                           ("₹10 registration_fee", {"type": "registration_fee", "amount": 10.0, "status": "success"}),
                           ("pending ₹118", {"type": "registration_fee", "amount": 118.0, "status": "pending"}),
                           ("₹118 no status", {"type": "registration_fee", "amount": 118.0}),
                           ("₹118 wallet_topup", {"type": "wallet_topup", "amount": 118.0, "status": "success"})]:
            x = await mk_user(payrow=[prow])
            a0 = await adm()
            await _trigger_referral_commissions(await u(x))
            dd = diff(a0, await adm())
            check(f"F4 {name}: books NOTHING & claim released",
                  await wb(x) == 0 and dd["ds"] == 0 and dd["gst"] == 0 and not (await u(x)).get("commission_triggered"), dd)
        for name, prow in [("₹118 registration_fee success", {"type": "registration_fee", "amount": 118.0, "status": "success"}),
                           ("₹118 registration_fee_upi paid", {"type": "registration_fee_upi", "amount": 118.0, "status": "paid"}),
                           ("₹117 registration_fee completed (>= price-1)", {"type": "registration_fee", "amount": 117.0, "status": "completed"})]:
            x = await mk_user(payrow=[prow])
            a0 = await adm()
            await _trigger_referral_commissions(await u(x))
            dd = diff(a0, await adm())
            check(f"F4 {name}: books 50/50/18", await wb(x) == 50 and dd["ds"] == 50 and dd["gst"] == 18, dd)

        # 6. Offline pre-credit + no flag + no row: does the reversal still fire when the split refuses?
        o = await mk_user(payrow=[], extra={"offline_pre_credit_amount": 118.0})
        await credit_admin_bucket("direct_added", 118.0, also_total_earned=False)
        a0 = await adm()
        await _trigger_referral_commissions(await u(o))
        dd = diff(a0, await adm())
        check("F6 offline pre-credit (no flag/row): either books 50/50 or leaves direct_added intact",
              (await wb(o) == 50 and dd["ds"] == 50) or dd["da"] == 0, {"member": await wb(o), **dd,
               "pre_credit_left": (await u(o)).get("offline_pre_credit_amount")})
    finally:
        s1 = await adm()
        dd = diff(s0, s1)
        for b, k in (("direct_signup", "ds"), ("gst_collected", "gst"), ("direct_added", "da")):
            if abs(dd[k]) > 0.009:
                await credit_admin_bucket(b, -dd[k], also_total_earned=False)
        s2 = await adm()
        te = round(s2["te"] - s0["te"], 2)
        if abs(te) > 0.009:
            await db.users.update_one({"email": ADMIN_EMAIL.lower()}, {"$inc": {"total_earned": -te}})
        r1 = await db.transactions.delete_many({"$or": [{"user_id": {"$in": SEEDED}}, {"source_user_id": {"$in": SEEDED}},
                                                         {"related_signup_id": {"$in": SEEDED}}]})
        await db.notifications.delete_many({"user_id": {"$in": SEEDED}})
        r2 = await db.users.delete_many({"id": {"$in": SEEDED}})
        print("cleanup: reversed", dd, "txns", r1.deleted_count, "users", r2.deleted_count, "final drift", diff(s0, await adm()))
        print(f"RESULT {sum(1 for _, o in RES if o)}/{len(RES)} pass")

asyncio.run(main())
