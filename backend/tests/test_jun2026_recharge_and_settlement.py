"""Jun-2026 — money paths that change state: a paid recharge becoming
"successful" when the work is done, and a seller settlement carrying the
2.56% transaction fee plus any cashback adjustment.

Run:  python backend/tests/test_jun2026_recharge_and_settlement.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import httpx

BASE = os.environ.get("BASE_URL", "https://slangcart-tracking.preview.emergentagent.com") + "/api"
ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}{(' — ' + detail) if detail else ''}")


async def login(c, creds):
    r = await c.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]})
    r.raise_for_status()
    return r.json()["token"]


async def main():
    async with httpx.AsyncClient(timeout=90) as c:
        ah = {"Authorization": f"Bearer {await login(c, ADMIN)}"}
        bh = {"Authorization": f"Bearer {await login(c, BUYER)}"}

        # ── A paid recharge: processing → successful on completion ────────
        opts = (await c.get(f"{BASE}/recharge/options")).json()
        nets = (opts.get("mobile") or {}).get("networks") or []
        states = (opts.get("mobile") or {}).get("states") or []
        plan = None
        if nets and states:
            prods = (await c.get(f"{BASE}/recharge/products", params={
                "kind": "mobile", "state": states[0]["slug"], "network": nets[0]["slug"],
                "pincode": "517644",
            })).json()
            for g in prods.get("groups") or []:
                for p in g.get("products") or []:
                    plan = plan or p
        if not plan:
            check("a recharge plan exists to test with", False)
            print("\nSKIPPED the recharge half — no plans in the catalogue")
        else:
            before = (await c.get(f"{BASE}/auth/me", headers=bh)).json().get("wallet_balance") or 0
            pay = await c.post(f"{BASE}/recharge/pay/wallet", headers=bh, json={
                "product_id": plan["id"], "kind": "mobile", "account": "9876501234",
                "state": states[0]["slug"], "network": nets[0]["slug"],
            })
            check("wallet recharge is accepted", pay.status_code == 200, pay.text[:160])
            if pay.status_code == 200:
                body = pay.json()
                rid, oid = body["recharge_id"], body.get("order_id")
                check("recharge starts as processing", body.get("status") == "processing",
                      str(body.get("status")))
                after = (await c.get(f"{BASE}/auth/me", headers=bh)).json().get("wallet_balance") or 0
                check("buyer wallet paid exactly the plan price",
                      abs((before - after) - float(plan["price"])) < 0.02,
                      f'{before} → {after} for ₹{plan["price"]}')
                check("a vendor-visible order was created", bool(oid), str(body.get("order_number")))

                # the seller (or rider) completes it
                r = await c.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah,
                                  json={"status": "delivered"})
                check("the recharge order can be completed", r.status_code == 200, r.text[:160])
                hist = (await c.get(f"{BASE}/recharge/history", headers=bh)).json()
                row = next((x for x in hist.get("items") or [] if x.get("id") == rid), None)
                check("history flips to successful once the work is done",
                      bool(row) and row.get("status") == "success",
                      str((row or {}).get("status")))
                check("the completion is stamped", bool((row or {}).get("completed_at")),
                      str((row or {}).get("completed_at")))
                # replay must not change it again
                await c.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah,
                              json={"status": "delivered"})
                hist2 = (await c.get(f"{BASE}/recharge/history", headers=bh)).json()
                row2 = next((x for x in hist2.get("items") or [] if x.get("id") == rid), None)
                check("replaying the completion is a no-op",
                      (row2 or {}).get("completed_at") == (row or {}).get("completed_at"))

        # ── Seller settlement: cashback adjustment + 2.56% fee ────────────
        vh = {"Authorization": f"Bearer {await login(c, VENDOR)}"}
        w = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
        avail = float(w.get("available") or 0)
        owed = float(w.get("cashback_outstanding") or 0)
        pending = float(w.get("pending_withdrawals") or 0)
        if avail < 5000 or pending > 0.009:
            print(f"\nSKIPPED the settlement half — available ₹{avail}, pending ₹{pending}")
        else:
            nw_before = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
            rev_before = nw_before["group_1_revenue"]["platform_fee"]
            r = await c.post(f"{BASE}/withdrawals", headers=vh, json={"amount": 5000})
            check("settlement is accepted", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                d = r.json()
                expected_fee = round(5000 * 0.0256, 2)
                expected_cb = round(min(owed, 5000), 2)
                check("the 2.56% fee is taken",
                      abs(float(d.get("transaction_fee") or 0) - expected_fee) < 0.02,
                      f'{d.get("transaction_fee")} vs {expected_fee}')
                check("cashback outstanding is adjusted first",
                      abs(float(d.get("cashback_adjusted") or 0) - expected_cb) < 0.02,
                      f'{d.get("cashback_adjusted")} vs {expected_cb}')
                check("only the remainder goes to the bank",
                      abs(float(d.get("amount") or 0) - round(5000 - expected_cb - expected_fee, 2)) < 0.02,
                      f'{d.get("amount")}')
                after = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
                check("the wallet dropped by exactly the full ₹5,000",
                      abs((avail - float(after.get("available") or 0)) - 5000) < 0.05,
                      f'{avail} → {after.get("available")}')
                nw_after = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
                check("the fee landed in the Revenue Ledger",
                      abs((nw_after["group_1_revenue"]["platform_fee"] - rev_before) - expected_fee) < 0.02,
                      f'{rev_before} → {nw_after["group_1_revenue"]["platform_fee"]}')
                check("no second settlement is possible while one is open",
                      (await c.post(f"{BASE}/withdrawals", headers=vh,
                                    json={"amount": 5000})).status_code == 400)
                # Leave the seller clean: an open settlement would block the
                # next run (and any real withdrawal the owner tries).
                rj = await c.post(
                    f"{BASE}/admin/withdrawals/{d['id']}/reject",
                    headers=ah, json={"reason": "automated test cleanup"},
                )
                check("the test settlement is rolled back", rj.status_code == 200,
                      rj.text[:200])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
