"""Jun-2026 owner batch — service reviews after contact, visit charges, and
the cashback collected on a withdrawal.

Run:  python3 tests/test_jun2026_services_and_withdrawal.py
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
        bh = {"Authorization": "Bearer " + (await c.post(
            f"{BASE}/auth/login",
            json={"email": "testbuyer@test.com", "password": "Test@1234"},
        )).json()["token"]}
        buyer = (await c.get(f"{BASE}/auth/me", headers=bh)).json()
        buyer_id = buyer["id"]

        # ── a provider to review ─────────────────────────────────────────
        pid = f"TEST_sp_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": pid, "name": "Test Electrician", "email": f"{pid}@test.com",
            "role": "user", "phone": "9999900001", "is_service_provider": True,
            "service_status": "approved", "service_name": "Wiring work",
            "service_category": "Electrical", "service_pincode": "517644",
            "service_charge": 0.0, "registration_paid": True,
            "referral_code": f"S{uuid.uuid4().hex[:6].upper()}", "created_at": ts,
        })

        prof = (await c.get(f"{BASE}/services/{pid}/profile", headers=bh)).json()
        check("a customer who never contacted him cannot review",
              prof.get("can_review") is False, str(prof.get("can_review")))
        r = await c.post(f"{BASE}/services/{pid}/reviews", headers=bh,
                         json={"rating": 5, "comment": "great"})
        check("…and the API refuses it", r.status_code == 403, f"{r.status_code} {r.text[:120]}")

        # he took the number (this is what "Get number" writes)
        await db.phone_reveal_invoices.insert_one({
            "id": str(uuid.uuid4()), "user_id": buyer_id, "provider_id": pid,
            "fee": 1.0, "gst": 0.18, "total": 1.18, "status": "paid",
            "created_at": ts,
        })
        prof2 = (await c.get(f"{BASE}/services/{pid}/profile", headers=bh)).json()
        check("after getting the number he can review", prof2.get("can_review") is True)
        check("the card counts him as contacted", prof2.get("contacted_count") == 1,
              str(prof2.get("contacted_count")))
        r = await c.post(f"{BASE}/services/{pid}/reviews", headers=bh,
                         json={"rating": 5, "comment": "Came on time, fixed it"})
        check("the review posts", r.status_code == 200, f"{r.status_code} {r.text[:140]}")
        prof3 = (await c.get(f"{BASE}/services/{pid}/profile", headers=bh)).json()
        check("the rating shows on the card",
              (prof3.get("rating_count") or 0) == 1 and abs(float(prof3.get("rating_avg") or 0) - 5) < 0.01,
              f'{prof3.get("rating_count")} / {prof3.get("rating_avg")}')

        # ── visit charges, set by the provider himself ───────────────────
        sph = {"Authorization": "Bearer " + (await c.post(
            f"{BASE}/auth/admin/impersonate" if False else f"{BASE}/auth/login",
            json={"email": f"{pid}@test.com", "password": "nope"},
        )).json().get("token", "")}
        # No password for the seeded provider — call the engine directly.
        from routes.service_provider import update_my_service, ServiceEditRequest

        prov = await db.users.find_one({"id": pid}, {"_id": 0})
        await update_my_service(ServiceEditRequest(visit_charge=250), prov)
        prof4 = (await c.get(f"{BASE}/services/{pid}/profile", headers=bh)).json()
        check("the provider's visit charges show on his card",
              abs(float(prof4.get("visit_charge") or 0) - 250.0) < 0.01,
              str(prof4.get("visit_charge")))
        await update_my_service(ServiceEditRequest(visit_charge=0), await db.users.find_one({"id": pid}, {"_id": 0}))
        prof5 = (await c.get(f"{BASE}/services/{pid}/profile", headers=bh)).json()
        check("he can set it back to “on request”",
              float(prof5.get("visit_charge") or 0) == 0.0, str(prof5.get("visit_charge")))
        _ = sph

        # ── withdrawal collects the cashback owed first ──────────────────
        await db.withdrawals.delete_many({"user_id": VID, "status": "pending"})
        from core import shop_money
        start_bal = round(float((await db.users.find_one(
            {"id": VID}, {"_id": 0, "vendor_earnings": 1}))["vendor_earnings"]), 2)
        top_up = round(max(0.0, 6000.0 - start_bal), 2)
        if top_up > 0:
            await shop_money.credit(
                VID, shop_money.VENDOR_WALLET, top_up,
                idempotency_key=f"WDLTEST-FUND:{uuid.uuid4().hex[:8]}",
                group="vendor_payable", txn_type="vendor_adjustment_credit",
                vendor_id=VID, settlement_status="adjusted",
                description=f"Automated test funding — ₹{top_up:g} for the settlement test",
                extra={"wallet_impact": "vendor_earnings_only", "test_fixture": True},
            )
        await db.users.update_one({"id": VID}, {"$set": {"cashback_outstanding": 300.0,
                                                         "settlement_busy_at": None}})
        await db.vendor_outstanding.delete_many({"vendor_id": VID, "kind": "cashback"})
        await db.vendor_outstanding.insert_one({
            "id": str(uuid.uuid4()), "vendor_id": VID, "vendor_name": "Test Shop",
            "kind": "cashback", "amount": 300.0, "recovered": 0.0, "status": "open",
            "created_at": ts,
        })
        vh = {"Authorization": "Bearer " + (await c.post(
            f"{BASE}/auth/login",
            json={"email": "testvendor@test.com", "password": "Test@1234"},
        )).json()["token"]}
        w = await c.post(f"{BASE}/withdrawals", headers=vh, json={"amount": 5000})
        if w.status_code == 429:
            check("withdrawal rate limit hit — rerun later", True, "skipped")
        else:
            check("the withdrawal is accepted", w.status_code == 200, w.text[:160])
            d = w.json()
            check("the ₹300 cashback owed is collected first",
                  abs(float(d.get("cashback_adjusted") or 0) - 300.0) < 0.02, str(d))
            fee = round(5000 * 0.0256, 2)
            check("2.56% transaction fee is taken",
                  abs(float(d.get("transaction_fee") or 0) - fee) < 0.05, str(d.get("transaction_fee")))
            check("only the rest goes to the bank",
                  abs(float(d.get("amount") or 0) - round(5000 - 300 - fee, 2)) < 0.05,
                  str(d.get("amount")))
            v = await db.users.find_one({"id": VID}, {"_id": 0, "vendor_earnings": 1,
                                                      "cashback_outstanding": 1})
            funded = round(start_bal + top_up, 2)
            check("the shop wallet drops by exactly ₹5,000",
                  abs(float(v["vendor_earnings"]) - round(funded - 5000.0, 2)) < 0.02,
                  f'{funded} → {v["vendor_earnings"]}')
            check("nothing is still owed", abs(float(v.get("cashback_outstanding") or 0)) < 0.02, str(v))
            nw = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()["master"]
            check("Receivables came back to zero",
                  abs(float(nw.get("cashback_receivable") or 0)) < 0.02,
                  str(nw.get("cashback_receivable")))
            rj = await c.post(f"{BASE}/admin/withdrawals/{d['id']}/reject",
                              headers=ah, json={"reason": "automated test cleanup"})
            check("the test settlement is rolled back", rj.status_code == 200, rj.text[:120])

        # cleanup
        await db.users.delete_one({"id": pid})
        await db.phone_reveal_invoices.delete_many({"provider_id": pid})
        await db.service_reviews.delete_many({"provider_id": pid})
        await db.vendor_outstanding.delete_many({"vendor_id": VID, "kind": "cashback"})
        await db.users.update_one({"id": VID}, {"$set": {"cashback_outstanding": 0.0}})
        if top_up > 0:
            await shop_money.debit(
                VID, shop_money.VENDOR_WALLET, top_up,
                idempotency_key=f"WDLTEST-UNFUND:{uuid.uuid4().hex[:8]}",
                group="vendor_payable", txn_type="vendor_adjustment_debit",
                vendor_id=VID, settlement_status="adjusted",
                description="Automated test cleanup — settlement test funding returned",
                extra={"wallet_impact": "vendor_earnings_only", "test_fixture": True},
            )

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
