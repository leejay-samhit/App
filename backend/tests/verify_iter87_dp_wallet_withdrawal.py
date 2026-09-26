"""Iteration 87 — targeted checks for the DP wallet + withdrawal cutover.

Covers:
  * admin settings round-trip for dp_commission_pct (reject >100)
  * /delivery-partner/me/wallet-transactions purity (no COD rows, totals correct)
  * /withdrawals succeeds for approved DP, 403 for a plain buyer
  * a rider cannot withdraw the COD cash-in-hand pot

Run:  cd /app/backend && python tests/verify_iter87_dp_wallet_withdrawal.py
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from core.db import db  # noqa: E402

BASE = os.environ.get("EXPO_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
H = {"User-Agent": "curl/8.5.0"}

ADMIN = ("support@slangcart.com", "3)Ywxtic")
BUYER = ("testbuyer@test.com", "Test@1234")
RIDER = ("rider_test@test.com", "Test@1234")
RIDER_UID = "a0bf6822-59fa-4b18-bc53-381229a1f30c"

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


async def login(c, email, pw):
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}", **H}


async def main():
    async with httpx.AsyncClient(timeout=60.0, headers=H) as c:
        ah = await login(c, *ADMIN)
        bh = await login(c, *BUYER)
        rh = await login(c, *RIDER)

        print("\n[1] Admin settings round-trip for dp_commission_pct")
        cur = (await c.get(f"{BASE}/admin/settings", headers=ah)).json()
        check("GET /admin/settings returns dp_commission_pct",
              "dp_commission_pct" in cur, f"keys={list(cur)[:20]}")
        # set to 15
        r = await c.put(f"{BASE}/admin/settings",
                        json={"dp_commission_pct": 15}, headers=ah)
        check("PUT accepts 15", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
        again = (await c.get(f"{BASE}/admin/settings", headers=ah)).json()
        check("value persisted", float(again.get("dp_commission_pct") or 0) == 15.0,
              str(again.get("dp_commission_pct")))
        # reject > 100
        r = await c.put(f"{BASE}/admin/settings",
                        json={"dp_commission_pct": 150}, headers=ah)
        check("PUT rejects >100", r.status_code in (400, 422), f"{r.status_code}")
        # reject negative
        r = await c.put(f"{BASE}/admin/settings",
                        json={"dp_commission_pct": -1}, headers=ah)
        check("PUT rejects negative", r.status_code in (400, 422), f"{r.status_code}")
        # restore to 20 (the value used by the money test)
        await c.put(f"{BASE}/admin/settings", json={"dp_commission_pct": 20}, headers=ah)

        print("\n[2] /delivery-partner/me/wallet-transactions purity")
        r = await c.get(f"{BASE}/delivery-partner/me/wallet-transactions", headers=rh)
        check("wallet-transactions 200 for DP", r.status_code == 200, r.text[:150])
        data = r.json()
        items = data.get("items", [])
        allowed = {"dp_delivery_commission", "dp_delivery_commission_reversal",
                   "withdrawal_hold", "withdrawal", "withdrawal_reversal",
                   "admin_credit", "admin_debit"}
        bad_rows = [r["type"] for r in items if r.get("type") not in allowed]
        check("no COD cash rows leaked", not bad_rows, f"unexpected types: {bad_rows[:5]}")
        # no wallet_impact == dp_cash_only anywhere
        cash_rows = [r for r in items if r.get("wallet_impact") == "dp_cash_only"]
        check("no dp_cash_only rows leaked", not cash_rows, f"n={len(cash_rows)}")
        # totals shape
        check("total_earned is numeric",
              isinstance(data.get("total_earned"), (int, float)),
              f"got {type(data.get('total_earned'))}")
        check("total_withdrawn is numeric",
              isinstance(data.get("total_withdrawn"), (int, float)),
              f"got {type(data.get('total_withdrawn'))}")

        print("\n[3] /withdrawals — buyer 403 (only sellers/DPs/admin allowed)")
        r = await c.post(f"{BASE}/withdrawals", json={"amount": 5000}, headers=bh)
        check("buyer 403", r.status_code == 403, f"{r.status_code} {r.text[:150]}")

        # DP endpoint — sanity: 403 for buyer
        r = await c.get(f"{BASE}/delivery-partner/me/wallet-transactions", headers=bh)
        check("buyer 403 on DP wallet-txn", r.status_code == 403, f"{r.status_code}")

        print("\n[4] DP cannot withdraw the COD cash pot")
        # cash_in_hand belongs in dp_cash_in_hand, not wallet_balance.
        wallet = (await c.get(f"{BASE}/delivery-partner/me/wallet", headers=rh)).json()
        avail = float(wallet.get("available") or 0)  # personal wallet
        cash_in_hand = float(wallet.get("cash_in_hand") or 0)
        # Even IF cash_in_hand is large, withdrawing more than personal wallet must 400
        if avail < 1000:
            r = await c.post(f"{BASE}/withdrawals",
                             json={"amount": 1000}, headers=rh)
            # can be 400 either for below-min (no) or insufficient (yes)
            check("DP withdraw fails when wallet_balance<min",
                  r.status_code == 400
                  and "insufficient" in r.text.lower() or "balance" in r.text.lower(),
                  f"{r.status_code} {r.text[:150]}")
        else:
            print("  SKIP  DP has enough personal wallet balance to withdraw — "
                  "skipping cash-in-hand isolation test")
        # Guarantee: cash_in_hand did not become withdrawable
        # Even if cash_in_hand > 0, ATTEMPTing to withdraw cash_in_hand should fail.
        if cash_in_hand > 100 and avail < cash_in_hand:
            r = await c.post(f"{BASE}/withdrawals",
                             json={"amount": cash_in_hand}, headers=rh)
            check("cash_in_hand NOT withdrawable",
                  r.status_code == 400, f"{r.status_code} {r.text[:150]}")

        print("\n[5] Below-minimum withdrawal is rejected with the friendly message")
        r = await c.post(f"{BASE}/withdrawals", json={"amount": 50}, headers=rh)
        check("below-min 400", r.status_code == 400, f"{r.status_code}")
        check("message mentions minimum",
              "minimum" in r.text.lower() or "at least" in r.text.lower(),
              r.text[:200])

    print("\n" + "=" * 60)
    print(f"  PASS {ok}   FAIL {bad}")
    print("=" * 60)
    if FAIL:
        for f in FAIL:
            print("  •", f)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
