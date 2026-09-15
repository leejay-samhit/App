"""Wallet top-up — the "Razorpay succeeded but my wallet wasn't credited" bug.

Run:  cd /app/backend && python tests/verify_wallet_topup.py
"""
import asyncio
import os
import uuid
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from core.db import db  # noqa: E402

BASE = "http://localhost:8001/api"
H = {"User-Agent": "curl/8.5.0"}
BUYER = ("testbuyer@test.com", "Test@1234")
ok, bad, FAIL = 0, 0, []


def check(label, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        bad += 1
        FAIL.append(f"{label} :: {detail}")
        print(f"  FAIL  {label} :: {detail}")


async def bal():
    u = await db.users.find_one({"email": BUYER[0]}, {"_id": 0, "wallet_balance": 1})
    return round(float((u or {}).get("wallet_balance") or 0), 2)


async def main():
    async with httpx.AsyncClient(timeout=60.0, headers=H) as c:
        r = await c.post(f"{BASE}/auth/login", json={"email": BUYER[0], "password": BUYER[1]})
        bh = {"Authorization": f"Bearer {r.json()['token']}", **H}

        print("\n[1] Straight top-up credits exactly once")
        b0 = await bal()
        s = (await c.post(f"{BASE}/wallet/topup/start", json={"amount": 100}, headers=bh)).json()
        v = await c.post(f"{BASE}/wallet/topup/verify", json={
            "payment_id": s["payment_id"], "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": f"pay_T_{uuid.uuid4().hex[:10]}", "razorpay_signature": "sig",
        }, headers=bh)
        check("verify returns ok", v.status_code == 200, v.text[:200])
        check("wallet credited ₹100", await bal() == round(b0 + 100, 2), f"{b0} -> {await bal()}")
        again = await c.post(f"{BASE}/wallet/topup/verify", json={
            "payment_id": s["payment_id"], "razorpay_order_id": s["razorpay_order_id"],
            "razorpay_payment_id": f"pay_T_{uuid.uuid4().hex[:10]}", "razorpay_signature": "sig",
        }, headers=bh)
        check("re-verify does NOT credit twice", await bal() == round(b0 + 100, 2),
              f"{again.status_code} {await bal()}")
        row = await db.transactions.find_one(
            {"topup_id": s["payment_id"]}, {"_id": 0, "credit": 1, "debit": 1, "new_balance": 1,
                                            "idempotency_key": 1, "type": 1},
        )
        check("ledgered with credit + running balance", bool(row) and row.get("credit") == 100.0
              and row.get("new_balance") is not None, str(row))
        check("idempotency key present", (row or {}).get("idempotency_key") == f"TOPUP:{s['payment_id']}",
              str((row or {}).get("idempotency_key")))
        bank = await db.bank_ledger.count_documents({"topup_id": s["payment_id"]})
        check("exactly one bank-ledger (asset) row", bank == 1, str(bank))

        print("\n[2] THE BUG: a second 'Add money' tap must not orphan the first payment")
        b0 = await bal()
        first = (await c.post(f"{BASE}/wallet/topup/start", json={"amount": 150}, headers=bh)).json()
        second = (await c.post(f"{BASE}/wallet/topup/start", json={"amount": 200}, headers=bh)).json()
        check("the first attempt still exists (not deleted)",
              await db.wallet_topups.count_documents({"id": first["payment_id"]}) == 1)
        stale = await db.wallet_topups.find_one({"id": first["payment_id"]}, {"_id": 0, "status": 1})
        check("first attempt parked as abandoned", stale.get("status") == "abandoned", str(stale))
        v = await c.post(f"{BASE}/wallet/topup/verify", json={
            "payment_id": first["payment_id"], "razorpay_order_id": first["razorpay_order_id"],
            "razorpay_payment_id": f"pay_S_{uuid.uuid4().hex[:10]}", "razorpay_signature": "sig",
        }, headers=bh)
        check("the paid-but-stale attempt STILL verifies (was 404 before)",
              v.status_code == 200, v.text[:200])
        check("wallet credited ₹150", await bal() == round(b0 + 150, 2), f"{b0} -> {await bal()}")

        print("\n[3] Recovery when the checkout callback lied about failing")
        b0 = await bal()
        pend = (await c.get(f"{BASE}/wallet/topup/pending", headers=bh)).json()
        check("the unfinished ₹200 attempt is offered for recovery",
              any(i["id"] == second["payment_id"] for i in pend["items"]), str(pend["total"]))
        rec = await c.post(f"{BASE}/wallet/topup/recover", json={
            "payment_id": second["payment_id"],
        }, headers=bh)
        check("recover credits the money", rec.status_code == 200, rec.text[:200])
        check("wallet credited ₹200", await bal() == round(b0 + 200, 2), f"{b0} -> {await bal()}")
        rec2 = await c.post(f"{BASE}/wallet/topup/recover", json={
            "payment_id": second["payment_id"],
        }, headers=bh)
        check("recover twice does NOT double credit", await bal() == round(b0 + 200, 2),
              f"{rec2.status_code} {await bal()}")

        print("\n[4] Recovery by Razorpay order id (client lost our attempt id)")
        b0 = await bal()
        third = (await c.post(f"{BASE}/wallet/topup/start", json={"amount": 300}, headers=bh)).json()
        rec = await c.post(f"{BASE}/wallet/topup/recover", json={
            "razorpay_order_id": third["razorpay_order_id"],
        }, headers=bh)
        check("recovered by order id", rec.status_code == 200, rec.text[:200])
        check("wallet credited ₹300", await bal() == round(b0 + 300, 2), f"{b0} -> {await bal()}")

        print("\n[5] Nothing is invented: unknown attempt cannot mint money")
        b0 = await bal()
        bogus = await c.post(f"{BASE}/wallet/topup/recover", json={
            "payment_id": "does-not-exist",
        }, headers=bh)
        check("unknown attempt is refused", bogus.status_code == 404, str(bogus.status_code))
        check("balance unchanged", await bal() == b0)
        other = await c.post(f"{BASE}/wallet/topup/verify", json={
            "payment_id": "does-not-exist", "razorpay_payment_id": "pay_X",
        }, headers=bh)
        check("verify of an unknown attempt is refused", other.status_code == 404,
              str(other.status_code))

        print("\n[6] Limits still enforced by the SERVER")
        lo = await c.post(f"{BASE}/wallet/topup/start", json={"amount": 5}, headers=bh)
        hi = await c.post(f"{BASE}/wallet/topup/start", json={"amount": 999999}, headers=bh)
        check("below minimum refused", lo.status_code == 400, lo.text[:120])
        check("above maximum refused", hi.status_code == 400, hi.text[:120])

        print("\n[7] Admin books: liability and asset both moved")
        liab = await db.users.aggregate([
            {"$group": {"_id": None, "s": {"$sum": "$wallet_balance"}}},
        ]).to_list(1)
        check("user-liability total is a real number", bool(liab), str(liab))
        creds = await db.bank_ledger.count_documents({"category": "wallet_topup"})
        check("top-ups appear as bank credits (asset side)", creds >= 4, str(creds))

        print(f"\n{'='*60}\n  PASS {ok}   FAIL {bad}\n{'='*60}")
        for f in FAIL:
            print("  ✗", f)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
