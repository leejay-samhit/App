"""Iteration 96 fixes — races and reversals that must hold under double taps.

Run:  python backend/tests/test_iter96_fixes.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db          # noqa: E402
from core.utils import now_utc  # noqa: E402

BASE = os.environ.get("BASE_URL", "https://slangcart-tracking.preview.emergentagent.com") + "/api"
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}{(' — ' + detail) if detail else ''}")


async def seed_outstanding(amount: float) -> str:
    oid = str(uuid.uuid4())
    await db.vendor_outstanding.insert_one({
        "id": oid, "vendor_id": VID, "vendor_name": "Test Vendor", "kind": "cashback",
        "amount": amount, "recovered": 0.0, "status": "open",
        "order_id": f"ITER96-{oid[:6]}", "order_number": "ITER96",
        "created_at": now_utc().isoformat(),
    })
    await db.users.update_one({"id": VID}, {"$inc": {"cashback_outstanding": amount}})
    return oid


async def clear_pending(c, ah):
    for w in (await c.get(f"{BASE}/admin/withdrawals?status=pending", headers=ah)).json():
        if w["user_id"] == VID:
            await c.post(f"{BASE}/admin/withdrawals/{w['id']}/reject",
                         headers=ah, json={"reason": "iter96 cleanup"})


async def main():
    async with httpx.AsyncClient(timeout=90) as c:
        ah = {"Authorization": f"Bearer {(await c.post(f'{BASE}/auth/login', json={'email': 'support@slangcart.com', 'password': '3)Ywxtic'})).json()['token']}"}
        vh = {"Authorization": f"Bearer {(await c.post(f'{BASE}/auth/login', json={'email': 'testvendor@test.com', 'password': 'Test@1234'})).json()['token']}"}
        await clear_pending(c, ah)

        # ── 1. Parallel cashback recovery can only collect the debt ONCE ──
        await db.users.update_one({"id": VID}, {"$set": {"cashback_outstanding": 0.0}})
        await seed_outstanding(60.0)
        before = (await db.users.find_one({"id": VID}, {"_id": 0, "vendor_earnings": 1}))["vendor_earnings"]
        res = await asyncio.gather(*[
            c.post(f"{BASE}/admin/cashback/outstanding/{VID}/recover", headers=ah, json={"amount": 60})
            for _ in range(4)
        ], return_exceptions=True)
        applied = sum(
            float(r.json().get("applied") or 0)
            for r in res if not isinstance(r, Exception) and r.status_code == 200
        )
        u = await db.users.find_one({"id": VID}, {"_id": 0, "vendor_earnings": 1, "cashback_outstanding": 1})
        check("4 parallel recoveries collect ₹60 once", abs(applied - 60) < 0.02, f"applied {applied}")
        check("outstanding never goes negative", u["cashback_outstanding"] >= -0.009,
              str(u["cashback_outstanding"]))
        check("the wallet is debited exactly ₹60",
              abs((before - u["vendor_earnings"]) - 60) < 0.02,
              f'{before} → {u["vendor_earnings"]}')

        # ── 2. Parallel settlements: only ONE may be raised ───────────────
        await clear_pending(c, ah)
        w0 = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
        avail = float(w0.get("available") or 0)
        if avail < 5000:
            print(f"SKIPPED the settlement race — wallet only ₹{avail}")
        else:
            res = await asyncio.gather(*[
                c.post(f"{BASE}/withdrawals", headers=vh, json={"amount": 5000})
                for _ in range(4)
            ], return_exceptions=True)
            oks = [r for r in res if not isinstance(r, Exception) and r.status_code == 200]
            check("only one of 4 parallel settlements is accepted", len(oks) == 1,
                  f"{[getattr(r, 'status_code', 'err') for r in res]}")
            pend = await db.withdrawals.count_documents(
                {"user_id": VID, "status": {"$in": ["pending", "approved", "processing"]}})
            check("exactly one open settlement row exists", pend == 1, str(pend))
            after = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
            check("the wallet dropped by exactly ₹5,000, not ₹15,000",
                  abs((avail - float(after.get("available") or 0)) - 5000) < 0.05,
                  f'{avail} → {after.get("available")}')
            fees = await db.transactions.count_documents(
                {"user_id": VID, "type": "withdrawal_transaction_fee",
                 "withdrawal_id": oks[0].json()["id"]}) if oks else 0
            check("the fee is charged once", fees == 1, str(fees))

            # ── 3. Rejecting a settlement returns the fee ─────────────────
            wid = oks[0].json()["id"] if oks else None
            if wid:
                nw_before = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
                rev_before = nw_before["group_1_revenue"]["platform_fee"]
                bal_before = float((await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()["available"])
                r = await c.post(f"{BASE}/admin/withdrawals/{wid}/reject", headers=ah,
                                 json={"reason": "iter96 fee reversal"})
                check("the settlement can be rejected", r.status_code == 200, r.text[:120])
                bal_after = float((await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()["available"])
                check("the seller gets the payout AND the fee back",
                      abs((bal_after - bal_before) - (4872.0 + 128.0)) < 0.05,
                      f"{bal_before} → {bal_after}")
                nw_after = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
                check("the fee revenue is reversed",
                      abs((rev_before - nw_after["group_1_revenue"]["platform_fee"]) - 128.0) < 0.05,
                      f'{rev_before} → {nw_after["group_1_revenue"]["platform_fee"]}')
                # replay must not refund twice
                await c.post(f"{BASE}/admin/withdrawals/{wid}/reject", headers=ah, json={"reason": "replay"})
                bal_replay = float((await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()["available"])
                check("rejecting twice changes nothing", abs(bal_replay - bal_after) < 0.02)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
