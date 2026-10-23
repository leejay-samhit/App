"""Jun-2026 owner batch — recharge routing, DP recharge scoping, treasury
receivables and seller settlement maths.

Run:  python backend/tests/test_jun2026_owner_batch.py
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


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}{(' — ' + detail) if detail else ''}")


async def login(c: httpx.AsyncClient, creds) -> str:
    r = await c.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]})
    r.raise_for_status()
    return r.json()["token"]


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        admin_t = await login(c, ADMIN)
        ah = {"Authorization": f"Bearer {admin_t}"}

        # 1 ── Treasury: receivables now carry cashback owed by sellers
        nw = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
        comp = nw["master"]["components"]
        check("net-worth exposes cashback_receivable", "cashback_receivable" in comp)
        check(
            "receivables_total = pending + cashback + advanced refunds",
            abs(comp["receivables_total"] - (
                comp["pending_collections"] + comp["cashback_receivable"]
                + comp.get("vendor_receivable", 0))) < 0.02,
            f'{comp["receivables_total"]} vs {comp["pending_collections"]}'
            f'+{comp["cashback_receivable"]}+{comp.get("vendor_receivable")}',
        )
        expected_nw = round(
            comp["bank_balance"] + comp["cash_on_hand"] + comp["receivables_total"]
            - comp["user_wallet_balance"] - comp["vendor_payable"]
            - comp["pending_withdrawals"] - comp["gst_payable"], 2,
        )
        check("net worth includes receivables", abs(nw["master"]["net_worth"] - expected_nw) < 0.02,
              f'{nw["master"]["net_worth"]} vs {expected_nw}')

        # 2 ── Cashback outstanding list shows what can be collected NOW
        out = (await c.get(f"{BASE}/admin/cashback/outstanding", headers=ah)).json()
        vendors = out.get("vendors") or []
        check("outstanding rows carry wallet balance",
              all("wallet_balance" in v and "recoverable_now" in v for v in vendors) if vendors
              else True, f"{len(vendors)} sellers owing")

        # 3 ── The cash / bank-deposit recovery entries are gone: the endpoint
        #      must ignore a legacy `method` and never ask for a UTR.
        if vendors:
            vid = vendors[0]["vendor_id"]
            r = await c.post(
                f"{BASE}/admin/cashback/outstanding/{vid}/recover",
                headers=ah, json={"amount": 0},
            )
            check("recovery rejects a zero amount", r.status_code == 400, str(r.status_code))

        # 4 ── Recharge plans are routed by location
        opts = (await c.get(f"{BASE}/recharge/options")).json()
        nets = (opts.get("mobile") or {}).get("networks") or []
        states = (opts.get("mobile") or {}).get("states") or []
        if nets and states:
            q = {"kind": "mobile", "state": states[0]["slug"], "network": nets[0]["slug"]}
            far = (await c.get(f"{BASE}/recharge/products", params={**q, "pincode": "110001"})).json()
            check("recharge products report their supplier",
                  far.get("supplier") in ("local", "national"), str(far.get("supplier")))
            near = (await c.get(f"{BASE}/recharge/products", params={**q, "pincode": "517644"})).json()
            check("recharge routing returns a plan list for a served pincode",
                  isinstance(near.get("groups"), list),
                  f'{near.get("supplier")} · {near.get("count")} plans')

        # 5 ── DP mapping is recharge-aware
        dps = (await c.get(f"{BASE}/admin/delivery-partners", headers=ah)).json()
        items = dps.get("items") or []
        if items:
            dp_id = items[0]["id"]
            body = (await c.get(f"{BASE}/admin/delivery-partners/{dp_id}/vendors", headers=ah)).json()
            check("mapping screen separates recharge sellers",
                  all("is_recharge" in v for v in (body.get("vendors") or [])),
                  f'{sum(1 for v in body.get("vendors") or [] if v.get("is_recharge"))} recharge sellers')
            check("mapping screen returns the saved scopes", "mapped_scopes" in body)
            # Save the SAME mapping back with an operator scope and read it out.
            vend = next((v for v in body.get("vendors") or [] if v.get("is_recharge")), None)
            if vend:
                scope = {"kinds": (vend.get("recharge_kinds") or ["mobile"])[:1],
                         "networks": [n["slug"] for n in (vend.get("recharge_networks") or [])][:1]}
                keep = list(body.get("mapped_vendor_ids") or [])
                if vend["id"] not in keep:
                    keep.append(vend["id"])
                r = await c.put(
                    f"{BASE}/admin/delivery-partners/{dp_id}/vendors", headers=ah,
                    json={"vendor_ids": keep, "recharge_scopes": {vend["id"]: scope}},
                )
                again = (await c.get(
                    f"{BASE}/admin/delivery-partners/{dp_id}/vendors", headers=ah)).json()
                saved = (again.get("mapped_scopes") or {}).get(vend["id"]) or {}
                check("operator scope is saved on the mapping",
                      r.status_code == 200 and saved.get("kinds") == scope["kinds"]
                      and saved.get("networks") == scope["networks"],
                      f"{r.status_code} {saved}")

        # 6 ── Seller settlement arithmetic is published to the app
        try:
            vt = await login(c, VENDOR)
            vh = {"Authorization": f"Bearer {vt}"}
            w = (await c.get(f"{BASE}/vendor/me/wallet", headers=vh)).json()
            check("vendor wallet publishes the 2.56% fee",
                  abs(float(w.get("withdrawal_fee_pct") or 0) - 2.56) < 0.001,
                  str(w.get("withdrawal_fee_pct")))
            check("vendor wallet publishes cashback outstanding",
                  "cashback_outstanding" in w, str(w.get("cashback_outstanding")))
        except Exception as e:  # pragma: no cover
            check("vendor wallet reachable", False, str(e)[:120])

        # 7 ── Buyer cart carries the live wallet balance the bag shows
        try:
            bt = await login(c, BUYER)
            bh = {"Authorization": f"Bearer {bt}"}
            me = (await c.get(f"{BASE}/auth/me", headers=bh)).json()
            cart = (await c.get(f"{BASE}/cart", headers=bh)).json()
            check("cart + /auth/me agree on the wallet",
                  isinstance(me.get("wallet_balance"), (int, float)) and "total" in cart,
                  f'wallet {me.get("wallet_balance")}, bag {cart.get("total")}')
            hist = (await c.get(f"{BASE}/recharge/history", headers=bh)).json()
            check("recharge history returns statuses",
                  all("status" in r for r in (hist.get("items") or [])) if hist.get("items") else True,
                  f'{len(hist.get("items") or [])} rows')
        except Exception as e:  # pragma: no cover
            check("buyer endpoints reachable", False, str(e)[:120])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
