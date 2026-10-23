"""Iter101 — FIX8 applications 403 with VALID bodies + admin receivables tie.
Run: cd /app/backend && python3 tests/iter101_apply_receivables.py
"""
import asyncio, os, sys
import httpx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa


def _env(p, k):
    for ln in open(p):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
RES = []


def check(n, ok, extra=""):
    RES.append((n, ok)); print(("PASS" if ok else "FAIL"), "·", n, "—", str(extra)[:250])


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{BASE}/auth/login", json={"email": "testbuyer@test.com", "password": "Test@1234"})
        bh = {"Authorization": "Bearer " + r.json()["token"]}
        await asyncio.sleep(3)
        r = await c.post(f"{BASE}/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"})
        ah = {"Authorization": "Bearer " + r.json()["token"]}
        bodies = {
            "/service/apply": {"service_name": "TEST Plumbing", "service_category": "Plumber", "pincode": "517644", "charge": 100},
            "/vendor/apply": {"shop_name": "TEST shop"},
            "/delivery-partner/apply": {"full_name": "TEST Rider", "phone": "9999999999", "vehicle_type": "bike",
                                        "vehicle_number": "AP01AA0001", "pincode": "517644", "city": "Srikalahasti",
                                        "aadhaar_number": "123412341234", "license_number": "DL123"},
        }
        for path, body in bodies.items():
            r = await c.post(f"{BASE}{path}", headers=bh, json=body)
            check(f"FIX8 free testbuyer {path} (valid body) → 403", r.status_code == 403, (r.status_code, r.text[:160]))
        n = await db.service_applications.count_documents({"user_id": (await db.users.find_one({"email": "testbuyer@test.com"}))["id"], "status": "pending"})
        check("no pending service application created for free buyer", n == 0, n)
        fn = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()
        m = fn.get("master") or {}
        vo = await db.vendor_outstanding.aggregate([
            {"$match": {"status": "open", "kind": {"$in": ["return_refund_company_funded", "delivery_fee_company_funded", "delivery_fee"]}}},
            {"$group": {"_id": None, "t": {"$sum": {"$subtract": ["$amount", {"$ifNull": ["$recovered", 0]}]}}}}]).to_list(1)
        all_open = await db.vendor_outstanding.count_documents({"status": "open"})
        cbo = await db.users.aggregate([{"$match": {"cashback_outstanding": {"$gt": 0}}},
                                        {"$group": {"_id": None, "t": {"$sum": "$cashback_outstanding"}}}]).to_list(1)
        print("master:", {k: m.get(k) for k in ("pending_collections", "cashback_receivable", "vendor_receivable", "receivables_total")},
              "open vo rows:", all_open, "vo sum:", vo, "cashback_outstanding:", cbo)
        check("vendor_receivable == open vendor_outstanding (funded kinds)",
              abs(float(m.get("vendor_receivable") or 0) - float(vo[0]["t"] if vo else 0)) < .01, (m.get("vendor_receivable"), vo))
        check("cashback_receivable == sum users.cashback_outstanding",
              abs(float(m.get("cashback_receivable") or 0) - float(cbo[0]["t"] if cbo else 0)) < .01, (m.get("cashback_receivable"), cbo))
    print(f"RESULT {sum(1 for _, o in RES if o)}/{len(RES)} pass")

asyncio.run(main())
