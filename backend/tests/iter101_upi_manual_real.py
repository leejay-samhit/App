"""Iter101 — REAL UPI-manual approval path through the public API (FIX1/FIX2):
seed a TEST_ joiner + PENDING manual payment, fire 4 concurrent admin approvals,
then 2 sequential ones. Expect member ₹50, revenue ₹50, ONE GST row, direct_added
net 0, exactly one deposit row. Fully reversed afterwards.
Run: cd /app/backend && python3 tests/iter101_upi_manual_real.py
"""
import asyncio, os, sys, uuid, logging
from datetime import datetime, timezone
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.disable(logging.WARNING)
from core.db import db  # noqa
from server import credit_admin_bucket, ADMIN_EMAIL  # noqa


def _env(p, k):
    for ln in open(p):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
RES = []


def check(n, ok, extra=""):
    RES.append((n, ok)); print(("PASS" if ok else "FAIL"), "·", n, "—", str(extra)[:250])


async def adm():
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "wallet_buckets": 1, "total_earned": 1})
    b = a.get("wallet_buckets") or {}
    return {"ds": float(b.get("direct_signup") or 0), "gst": float(b.get("gst_collected") or 0),
            "da": float(b.get("direct_added") or 0), "te": float(a.get("total_earned") or 0)}


async def main():
    uid = f"TEST_i101upi_{uuid.uuid4().hex[:8]}"; pay_id = str(uuid.uuid4()); utr = "TEST" + uuid.uuid4().hex[:8].upper()
    ts = datetime.now(timezone.utc).isoformat()
    await db.users.insert_one({"id": uid, "name": "TEST i101 UPI", "email": f"{uid}@test.com", "role": "user",
                               "registration_paid": False, "wallet_balance": 0.0, "created_at": ts,
                               "referral_code": "T" + uuid.uuid4().hex[:7].upper()})
    await db.manual_payments.insert_one({"id": pay_id, "user_id": uid, "user_email": f"{uid}@test.com", "user_name": "TEST i101 UPI",
                                         "amount": 118.0, "currency": "INR", "utr": utr, "app_used": "gpay",
                                         "payment_method": "upi_manual", "status": "PENDING", "created_at": ts})
    await db.transactions.insert_one({"id": str(uuid.uuid4()), "user_id": uid, "type": "registration_fee", "amount": 118.0,
                                      "status": "pending", "reference_number": utr, "payment_method": "upi_manual",
                                      "manual_payment_id": pay_id, "created_at": ts})
    s0 = await adm()
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{BASE}/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"})
            ah = {"Authorization": "Bearer " + r.json()["token"]}
            rs = await asyncio.gather(*[c.post(f"{BASE}/admin/payments/{pay_id}/approve", headers=ah, json={}) for _ in range(4)])
            print("concurrent approve codes:", [x.status_code for x in rs])
            for _ in range(2):
                r = await c.post(f"{BASE}/admin/payments/{pay_id}/approve", headers=ah, json={})
            print("sequential approve:", r.status_code, r.text[:120])
        await asyncio.sleep(2)
        s1 = await adm(); d = {k: round(s1[k] - s0[k], 2) for k in s0}
        u = await db.users.find_one({"id": uid}, {"_id": 0})
        print("admin deltas:", d)
        check("UPI real: member wallet exactly 50", round(float(u.get("wallet_balance") or 0), 2) == 50, u.get("wallet_balance"))
        check("UPI real: direct_signup +50 once, total_earned +50", d["ds"] == 50 and d["te"] == 50, d)
        check("UPI real: direct_added net 0 (pre-credit reversed exactly once)", d["da"] == 0, d)
        n = {}
        for t in ("direct_signup_credit", "gst_collected", "subscription_cashback", "admin_debit", "registration_fee", "subscription_revenue_claim"):
            n[t] = await db.transactions.count_documents({"$or": [{"user_id": uid}, {"source_user_id": uid}, {"related_signup_id": uid}], "type": t})
        print("row counts:", n)
        check("UPI real: one ds row, one GST row, one cashback, one reversal, one fee row",
              n["direct_signup_credit"] == 1 and n["gst_collected"] == 1 and n["subscription_cashback"] == 1
              and n["admin_debit"] == 1 and n["registration_fee"] == 1, n)
        gst_rows = await db.transactions.find({"related_signup_id": uid, "type": "gst_collected"}, {"_id": 0, "amount": 1}).to_list(5)
        check("UPI real: GST row = ₹18", [x["amount"] for x in gst_rows] == [18.0], gst_rows)
        dep = await db.system_wallet_deposits.count_documents({"linked_user_id": uid})
        check("UPI real: exactly one system_wallet_deposit", dep == 1, dep)
        print("gst_collected bucket delta (UPI path):", d["gst"])
    finally:
        s2 = await adm(); d = {k: round(s2[k] - s0[k], 2) for k in s0}
        for b, k in (("direct_signup", "ds"), ("gst_collected", "gst"), ("direct_added", "da")):
            if abs(d[k]) > 0.009:
                await credit_admin_bucket(b, -d[k], also_total_earned=False)
        te = round((await adm())["te"] - s0["te"], 2)
        if abs(te) > 0.009:
            await db.users.update_one({"email": ADMIN_EMAIL.lower()}, {"$inc": {"total_earned": -te}})
        await db.transactions.delete_many({"$or": [{"user_id": uid}, {"source_user_id": uid}, {"related_signup_id": uid}, {"manual_payment_id": pay_id}]})
        await db.system_wallet_deposits.delete_many({"linked_user_id": uid})
        await db.manual_payments.delete_many({"id": pay_id})
        await db.notifications.delete_many({"user_id": uid})
        for coll in ("approved_users", "archived_users", "user_archive"):
            await db[coll].delete_many({"$or": [{"id": uid}, {"user_id": uid}]})
        await db.users.delete_many({"id": uid})
        print("final drift:", {k: round((await adm())[k] - s0[k], 2) for k in s0})
    print(f"RESULT {sum(1 for _, o in RES if o)}/{len(RES)} pass")

asyncio.run(main())
