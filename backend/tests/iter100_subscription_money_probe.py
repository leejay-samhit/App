"""Iter100 — membership ₹118 split: treasury arithmetic, non-member inviter,
admin EARN code, direct replay of _credit_no_ref_signup_to_admin, UPI-manual
(GST-at-create) path, guard ordering, concurrency. Cleans up after itself.
Run: cd /app/backend && python3 tests/iter100_subscription_money_probe.py
"""
import asyncio, os, sys, uuid
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa
import server  # noqa
from server import _trigger_referral_commissions, _credit_no_ref_signup_to_admin, credit_admin_bucket, ADMIN_EMAIL

RES = []
SEEDED = []
DELTA = {"direct_signup": 0.0, "gst_collected": 0.0}


def check(n, ok, extra=""):
    RES.append((n, ok)); print(("PASS" if ok else "FAIL"), "·", n, ("— " + str(extra)) if extra else "")


async def buckets():
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "wallet_buckets": 1})
    b = a.get("wallet_buckets") or {}
    return float(b.get("direct_signup") or 0), float(b.get("gst_collected") or 0)


async def mk_user(paid=True, sponsor=None, code=None, payrow=True, extra=None):
    uid = f"TEST_i100_{uuid.uuid4().hex[:8]}"
    ts = datetime.now(timezone.utc).isoformat()
    doc = {"id": uid, "name": "TEST i100", "email": f"{uid}@test.com", "role": "user",
           "registration_paid": paid, "wallet_balance": 0.0, "created_at": ts,
           "referral_code": code or f"T{uuid.uuid4().hex[:7].upper()}"}
    if sponsor:
        doc["sponsor_id"] = sponsor
    doc.update(extra or {})
    await db.users.insert_one(doc); SEEDED.append(uid)
    if payrow:
        await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "type": "registration_fee",
                                          "amount": 118.0, "status": "success", "created_at": ts})
    return uid


async def wb(uid):
    return float((await db.users.find_one({"id": uid}, {"wallet_balance": 1}) or {}).get("wallet_balance") or 0)


async def run_case(name, joiner_kwargs, inviter_kwargs=None, exp_member=50, exp_inviter=25, exp_ds=25, exp_gst=18):
    inv = await mk_user(**inviter_kwargs) if inviter_kwargs is not None else None
    j = await mk_user(sponsor=inv, **joiner_kwargs)
    d0, g0 = await buckets()
    await _trigger_referral_commissions(await db.users.find_one({"id": j}))
    d1, g1 = await buckets()
    DELTA["direct_signup"] += d1 - d0; DELTA["gst_collected"] += g1 - g0
    check(f"{name}: member wallet = {exp_member}", abs(await wb(j) - exp_member) < .01, await wb(j))
    if inv:
        check(f"{name}: inviter wallet = {exp_inviter}", abs(await wb(inv) - exp_inviter) < .01, await wb(inv))
    check(f"{name}: direct_signup Δ = {exp_ds}", abs((d1 - d0) - exp_ds) < .01, round(d1 - d0, 2))
    check(f"{name}: gst_collected Δ = {exp_gst}", abs((g1 - g0) - exp_gst) < .01, round(g1 - g0, 2))
    return j, inv


async def main():
    adm0 = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "total_earned": 1, "wallet_balance": 1})
    try:
        # A. member inviter → admin keeps 25
        j, inv = await run_case("A member-inviter", {}, {"paid": True})
        # A2. DIRECT replay of the split function (not shielded by commission_triggered)
        d0, g0 = await buckets()
        await _credit_no_ref_signup_to_admin(await db.users.find_one({"id": j}), await db.users.find_one({"id": inv}))
        d1, g1 = await buckets()
        DELTA["direct_signup"] += d1 - d0; DELTA["gst_collected"] += g1 - g0
        check("A2 direct replay: member wallet unchanged", abs(await wb(j) - 50) < .01, await wb(j))
        check("A2 direct replay: inviter unchanged", abs(await wb(inv) - 25) < .01, await wb(inv))
        check("A2 direct replay: admin direct_signup unchanged", abs(d1 - d0) < .01, round(d1 - d0, 2))
        check("A2 direct replay: admin gst unchanged", abs(g1 - g0) < .01, round(g1 - g0, 2))
        n_rows = await db.transactions.count_documents({"source_user_id": j, "type": "direct_signup_credit"})
        check("A2 direct replay: one direct_signup_credit row", n_rows == 1, n_rows)
        # B. non-member inviter → nothing to inviter, admin keeps 50
        await run_case("B non-member-inviter", {}, {"paid": False, "payrow": False}, exp_inviter=0, exp_ds=50)
        # C. no inviter
        await run_case("C no-inviter", {}, None, exp_ds=50)
        # D. sponsor = admin's own EARN code
        adm = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"id": 1, "wallet_balance": 1})
        aw0 = float(adm.get("wallet_balance") or 0)
        j_d = await mk_user(sponsor=adm["id"])
        d0, g0 = await buckets()
        await _trigger_referral_commissions(await db.users.find_one({"id": j_d}))
        d1, g1 = await buckets()
        DELTA["direct_signup"] += d1 - d0; DELTA["gst_collected"] += g1 - g0
        check("D admin-code: member 50", abs(await wb(j_d) - 50) < .01, await wb(j_d))
        check("D admin-code: direct_signup Δ 50", abs(d1 - d0 - 50) < .01, round(d1 - d0, 2))
        # E. UPI-manual / offline path: GST already booked at create
        await run_case("E gst-at-create (UPI manual)", {"extra": {"registration_gst_collected_at_create": True}},
                       None, exp_member=50, exp_ds=50, exp_gst=0)
        # F. guard ordering: paid flag, payment row arrives LATER
        f = await mk_user(payrow=False)
        await _trigger_referral_commissions(await db.users.find_one({"id": f}))
        await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": f, "type": "registration_fee",
                                          "amount": 118.0, "status": "success",
                                          "created_at": datetime.now(timezone.utc).isoformat()})
        d0, g0 = await buckets()
        await _trigger_referral_commissions(await db.users.find_one({"id": f}))
        d1, g1 = await buckets()
        DELTA["direct_signup"] += d1 - d0; DELTA["gst_collected"] += g1 - g0
        check("F skipped-then-paid: member eventually gets 50 (commission_triggered not burnt by a skip)",
              abs(await wb(f) - 50) < .01, await wb(f))
        # G. concurrency: two triggers at once
        g = await mk_user()
        doc = await db.users.find_one({"id": g})
        d0, g0 = await buckets()
        await asyncio.gather(_trigger_referral_commissions(dict(doc)), _trigger_referral_commissions(dict(doc)))
        d1, g1 = await buckets()
        DELTA["direct_signup"] += d1 - d0; DELTA["gst_collected"] += g1 - g0
        check("G concurrent x2: member 50", abs(await wb(g) - 50) < .01, await wb(g))
        check("G concurrent x2: direct_signup Δ 50", abs(d1 - d0 - 50) < .01, round(d1 - d0, 2))
        check("G concurrent x2: gst Δ 18", abs(g1 - g0 - 18) < .01, round(g1 - g0, 2))
        # H. weak 'check twice': a mere wallet_topup row satisfies the payment check
        h = await mk_user(payrow=False)
        await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": h, "type": "wallet_topup",
                                          "amount": 10.0, "status": "success",
                                          "created_at": datetime.now(timezone.utc).isoformat()})
        d0, g0 = await buckets()
        await _trigger_referral_commissions(await db.users.find_one({"id": h}))
        d1, g1 = await buckets()
        DELTA["direct_signup"] += d1 - d0; DELTA["gst_collected"] += g1 - g0
        check("H ₹10 wallet_topup (no ₹118 payment) must NOT unlock the split", abs(await wb(h)) < .01, await wb(h))
    finally:
        # cleanup: reverse bucket deltas, delete seeded rows
        for b, v in DELTA.items():
            if abs(v) > 0.009:
                await credit_admin_bucket(b, -round(v, 2), also_total_earned=False)
        adm1 = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1, "total_earned": 1, "wallet_balance": 1})
        te = round(float(adm1.get("total_earned") or 0) - float(adm0.get("total_earned") or 0), 2)
        print("admin total_earned drift during test (direct_signup credited 50 even when admin keeps 25):", te)
        if abs(te) > 0.009:
            await db.users.update_one({"id": adm1["id"]}, {"$inc": {"total_earned": -te}})
        print("admin wallet_balance drift after reversal:", round(float(adm1.get("wallet_balance") or 0) - float(adm0.get("wallet_balance") or 0), 2))
        r1 = await db.transactions.delete_many({"$or": [{"user_id": {"$in": SEEDED}}, {"source_user_id": {"$in": SEEDED}},
                                                         {"related_signup_id": {"$in": SEEDED}}]})
        await db.notifications.delete_many({"user_id": {"$in": SEEDED}})
        r2 = await db.users.delete_many({"id": {"$in": SEEDED}})
        print("cleanup: bucket reversal", DELTA, "txns", r1.deleted_count, "users", r2.deleted_count)
        print(f"RESULT {sum(1 for _, o in RES if o)}/{len(RES)} pass")

asyncio.run(main())
