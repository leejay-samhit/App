"""Iter 98 — a refund the company funded for a short seller must be
recoverable, both by the admin button and automatically from his next sale.
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

        # A company-funded advance of ₹150 for this seller.
        rid = str(uuid.uuid4())
        await db.vendor_outstanding.insert_one({
            "id": str(uuid.uuid4()),
            "vendor_id": VID,
            "vendor_name": "Test Shop",
            "kind": "return_refund_company_funded",
            "amount": 150.0,
            "recovered": 0.0,
            "status": "open",
            "return_id": rid,
            "created_at": ts,
        })
        nw = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()["master"]
        check("the advance shows in Receivables",
              abs(float(nw["vendor_receivable"]) - 150.0) < 0.02,
              f'{nw["vendor_receivable"]}')

        lst = (await c.get(f"{BASE}/admin/cashback/outstanding", headers=ah)).json()
        row = next((v for v in lst["vendors"] if v["vendor_id"] == VID), None)
        check("the admin list shows it", row is not None and
              abs(float(row.get("advance_outstanding") or 0) - 150.0) < 0.02,
              str(row and row.get("advance_outstanding")))

        wallet_before = round(float((await db.users.find_one(
            {"id": VID}, {"_id": 0, "vendor_earnings": 1}))["vendor_earnings"]), 2)
        r = await c.post(f"{BASE}/admin/cashback/outstanding/{VID}/recover",
                         headers=ah, json={"amount": 150, "note": "iter98 advance recovery"})
        check("the admin can recover it", r.status_code == 200, r.text[:160])
        if r.status_code == 200:
            d = r.json()
            check("₹150 came out of the wallet",
                  abs(float(d.get("advance_applied") or 0) - 150.0) < 0.02, str(d))
            wallet_after = round(float((await db.users.find_one(
                {"id": VID}, {"_id": 0, "vendor_earnings": 1}))["vendor_earnings"]), 2)
            check("the wallet dropped by exactly ₹150",
                  abs((wallet_before - wallet_after) - 150.0) < 0.02,
                  f"{wallet_before} → {wallet_after}")
            left = await db.vendor_outstanding.find_one({"return_id": rid})
            check("the row is settled",
                  (left or {}).get("status") == "settled" and
                  abs(float((left or {}).get("recovered") or 0) - 150.0) < 0.02,
                  str((left or {}).get("status")))
            nw2 = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()["master"]
            check("Receivables came back down",
                  abs(float(nw2["vendor_receivable"]) - (float(nw["vendor_receivable"]) - 150.0)) < 0.02,
                  f'{nw["vendor_receivable"]} → {nw2["vendor_receivable"]}')
            # replay must not take it twice
            r2 = await c.post(f"{BASE}/admin/cashback/outstanding/{VID}/recover",
                              headers=ah, json={"amount": 150, "note": "iter98 replay"})
            wallet_r = round(float((await db.users.find_one(
                {"id": VID}, {"_id": 0, "vendor_earnings": 1}))["vendor_earnings"]), 2)
            check("a second recovery takes nothing",
                  abs(wallet_r - wallet_after) < 0.02, f"{wallet_after} → {wallet_r}")
            _ = r2

        # The ledger row must be visible and labelled.
        row = await db.transactions.find_one(
            {"user_id": VID, "type": "advance_recovery"}, sort=[("created_at", -1)])
        check("the recovery is a labelled debit row",
              row is not None and float(row.get("debit") or 0) > 0 and
              "advanced" in (row.get("description") or ""),
              str(row and row.get("description"))[:90])

        # Auto-recovery from the next sale.
        rid2 = str(uuid.uuid4())
        await db.vendor_outstanding.insert_one({
            "id": str(uuid.uuid4()), "vendor_id": VID, "vendor_name": "Test Shop",
            "kind": "return_refund_company_funded", "amount": 75.0, "recovered": 0.0,
            "status": "open", "return_id": rid2, "created_at": ts,
        })
        from core.cashback import auto_recover_from_vendor_credit

        async def _bucket(*_a, **_k):
            return None

        out = await auto_recover_from_vendor_credit(
            VID, {"id": f"ITER98-{uuid.uuid4().hex[:8]}", "order_number": "ITER98"},
            credit_admin_bucket=_bucket,
        )
        check("the next sale clears the advance",
              abs(float(out.get("advance_recovered") or 0) - 75.0) < 0.02, str(out))
        left2 = await db.vendor_outstanding.find_one({"return_id": rid2})
        check("that row is settled too", (left2 or {}).get("status") == "settled",
              str((left2 or {}).get("status")))

        # Clean up: drop the seeded rows AND put the money back, because the
        # company never actually funded these advances — the seller must not be
        # left short by a test run.
        await db.vendor_outstanding.delete_many({"return_id": {"$in": [rid, rid2]}})
        from core import shop_money
        taken = 0.0
        for key in ("advance_recovery",):
            rows = await db.transactions.find(
                {"user_id": VID, "type": key, "created_at": {"$gte": ts}},
                {"_id": 0, "debit": 1},
            ).to_list(50)
            taken = round(taken + sum(float(r.get("debit") or 0) for r in rows), 2)
        if taken > 0.009:
            await shop_money.credit(
                VID, shop_money.VENDOR_WALLET, taken,
                idempotency_key=f"ITER98-TESTREFUND:{rid}",
                group="vendor_payable",
                txn_type="vendor_adjustment_credit",
                vendor_id=VID,
                settlement_status="adjusted",
                description=f"Automated test cleanup — ₹{taken:g} returned to the shop wallet",
                extra={"wallet_impact": "vendor_earnings_only", "test_cleanup": True},
            )
            check("the test puts the seller's money back", True, f"₹{taken}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
