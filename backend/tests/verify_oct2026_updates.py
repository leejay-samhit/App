"""Oct-2026 update pack verification.

1. POS search by serial / IMEI  — product carries device_units and the API
   round-trips them (search itself is client-side over this payload).
2. Per-unit device identity      — 10 qty ⇒ 10 device_units saved and read back.
3. DP vendor mapping            — GET /admin/delivery-partners/{id}/vendors is
   200 (was a 500 from a mixed Mongo projection) and returns pincodes.
4. Seller order management      — a shop mapped to a rider can only confirm or
   cancel; shipped/out_for_delivery/delivered are 403 for the seller.

Run: cd /app/backend && python tests/verify_oct2026_updates.py
"""
import asyncio
import os
import sys
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa: E402

BASE = "http://localhost:8001/api"
ADMIN = ("support@slangcart.com", "3)Ywxtic")
VENDOR = ("testvendor@test.com", "Test@1234")
BUYER = ("testbuyer@test.com", "Test@1234")

PASS = FAIL = 0


def check(label: str, ok: bool, extra: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {extra}")


async def login(c: httpx.AsyncClient, email: str, pw: str) -> dict:
    r = await c.post(f"{BASE}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def main() -> None:
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": "curl/8.5.0"}) as c:
        ah = await login(c, *ADMIN)
        vh = await login(c, *VENDOR)
        bh = await login(c, *BUYER)
        vendor = (await c.get(f"{BASE}/auth/me", headers=vh)).json()
        vendor_id = vendor["id"]

        # ── 1 + 2. Per-unit device identity round-trip ──────────────────
        print("\n[1] Per-unit serial / IMEI on a product")
        units = [
            {"serial_number": f"SN-{i:04d}-{uuid.uuid4().hex[:4].upper()}",
             "imei_1": "", "imei_2": ""}
            for i in range(10)
        ]
        units[0]["serial_number"] = "12340987"          # the owner's example
        r = await c.post(f"{BASE}/vendor/me/products", json={
            "name": f"Oct26 Device {uuid.uuid4().hex[:6]}",
            "price": 9999, "image_url": "", "stock": 10,
            "serial_number": "12340987",
            "device_units": units,
        }, headers=vh)
        check("product with 10 device_units created", r.status_code in (200, 201), r.text[:200])
        pid = r.json().get("id") if r.status_code in (200, 201) else None

        if pid:
            doc = (await c.get(f"{BASE}/vendor/me/products/{pid}", headers=vh)).json()
            saved = doc.get("device_units") or []
            check("10 units persisted", len(saved) == 10, str(len(saved)))
            check("unit #1 serial is the searched code",
                  (saved[0] or {}).get("serial_number") == "12340987",
                  str(saved[:1]))
            check("top-level serial mirrors unit #1", doc.get("serial_number") == "12340987",
                  str(doc.get("serial_number")))

            # The POS screen filters this exact payload client-side.
            lst = (await c.get(f"{BASE}/vendor/me/products", headers=vh)).json()
            row = next((p for p in lst if p.get("id") == pid), None)
            check("slim POS list exposes device_units", bool(row and row.get("device_units")),
                  "missing" if not row else str(list(row.keys()))[:120])
            codes = []
            for u in (row or {}).get("device_units") or []:
                codes += [u.get("serial_number"), u.get("imei_1"), u.get("imei_2")]
            check("searched serial 12340987 is findable in the POS payload",
                  "12340987" in [str(x) for x in codes], str(codes[:4]))

            # Turning tracking off clears the rows.
            await c.patch(f"{BASE}/vendor/me/products/{pid}", json={"device_units": []}, headers=vh)
            doc2 = (await c.get(f"{BASE}/vendor/me/products/{pid}", headers=vh)).json()
            check("tracking off clears device_units", not (doc2.get("device_units") or []),
                  str(doc2.get("device_units"))[:80])
            await c.delete(f"{BASE}/vendor/me/products/{pid}", headers=vh)

        # ── 3. Admin → DP vendor mapping no longer 500s ─────────────────
        print("\n[2] Admin maps shops to a rider")
        email = f"dp_oct26_{uuid.uuid4().hex[:6]}@test.com"
        r = await c.post(f"{BASE}/auth/register", json={
            "name": "Oct26 Rider", "email": email, "password": "Test@1234",
            "phone": "9" + uuid.uuid4().int.__str__()[:9],
        })
        check("rider account created", r.status_code in (200, 201), r.text[:160])
        dh = await login(c, email, "Test@1234")
        me = (await c.get(f"{BASE}/auth/me", headers=dh)).json()
        await db.users.update_one({"id": me["id"]}, {"$set": {
            "registration_paid": True, "approval_status": "approved",
        }})
        r = await c.post(f"{BASE}/delivery-partner/apply", json={
            "full_name": "Oct26 Rider", "phone": "9876500011",
            "vehicle_type": "bike", "vehicle_number": "AP01AB1234",
            "delivery_radius_km": 10, "pincodes": ["517644"],
            "city": "Srikalahasti", "state": "AP",
        }, headers=dh)
        check("rider application accepted", r.status_code in (200, 201), r.text[:200])
        apps = (await c.get(f"{BASE}/admin/delivery-partners/applications?status=pending",
                            headers=ah)).json()
        app = next((a for a in apps.get("items", []) if a.get("user_id") == me["id"]), None)
        check("application visible to admin", app is not None)
        if app:
            r = await c.post(
                f"{BASE}/admin/delivery-partners/applications/{app['id']}/approve",
                json={"note": ""}, headers=ah)
            check("admin approved the rider", r.status_code == 200, r.text[:160])

        r = await c.get(f"{BASE}/admin/delivery-partners/{me['id']}/vendors", headers=ah)
        check("map-shops loads (was 500)", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            d = r.json()
            check("every approved seller is listed", len(d.get("vendors") or []) > 0,
                  str(len(d.get("vendors") or [])))
            check("sellers carry their pincodes for the filter",
                  all("pincodes" in v for v in d["vendors"]))
            check("pincode filter options returned", isinstance(d.get("all_pincodes"), list))
            check("rider's own pincodes returned", d.get("dp_pincodes") == ["517644"],
                  str(d.get("dp_pincodes")))

        r = await c.put(f"{BASE}/admin/delivery-partners/{me['id']}/vendors",
                        json={"vendor_ids": [vendor_id]}, headers=ah)
        check("mapping saved", r.status_code == 200 and r.json().get("mapped") == 1, r.text[:160])

        # ── 4. Seller order management is handed to the rider ───────────
        print("\n[3] Seller can only accept / cancel once a rider is mapped")
        r = await c.get(f"{BASE}/vendor/me/delivery-partners", headers=vh)
        check("seller sees he is rider-managed",
              r.status_code == 200 and r.json().get("managed") is True, r.text[:160])

        p = (await c.post(f"{BASE}/vendor/me/products", json={
            "name": f"Oct26 DPGate {uuid.uuid4().hex[:6]}", "price": 200,
            "image_url": "", "stock": 5, "is_published": True,
        }, headers=vh)).json()
        await db.products.update_one({"id": p["id"]}, {"$set": {
            "delivery_pincodes": ["517644"], "store_pincode": "517644",
        }})
        await db.users.update_one({"email": BUYER[0]}, {"$set": {"wallet_balance": 5000.0}})
        await c.post(f"{BASE}/cart/clear", headers=bh)
        await c.post(f"{BASE}/cart/add", json={"product_id": p["id"], "qty": 1}, headers=bh)
        co = await c.post(f"{BASE}/orders/checkout", json={
            "payment_method": "wallet",
            "shipping_address": {"name": "Test Buyer", "phone": "9876500022",
                                 "line1": "1 Test St", "city": "Srikalahasti",
                                 "state": "AP", "pincode": "517644"},
        }, headers=bh)
        oid = None
        if co.status_code in (200, 201):
            body = co.json()
            oid = (body.get("orders") or [{}])[0].get("id") or body.get("order_id")
        check("order placed for the mapped shop", bool(oid), co.text[:200])

        if oid:
            r = await c.patch(f"{BASE}/vendor/orders/{oid}/status",
                              json={"status": "confirmed"}, headers=vh)
            check("seller CAN accept the order", r.status_code == 200, r.text[:200])
            for bad in ("shipped", "out_for_delivery", "delivered"):
                r = await c.patch(f"{BASE}/vendor/orders/{oid}/status",
                                  json={"status": bad}, headers=vh)
                check(f"seller blocked from '{bad}'", r.status_code == 403, r.text[:140])
            # The rider owns those stages.
            for good in ("shipped", "out_for_delivery", "delivered"):
                r = await c.patch(f"{BASE}/delivery-partner/orders/{oid}/status",
                                  json={"status": good}, headers=dh)
                check(f"rider CAN set '{good}'", r.status_code == 200, r.text[:160])
            orders = (await c.get(f"{BASE}/delivery-partner/me/orders", headers=dh)).json()
            row = next((o for o in orders.get("items", []) if o["id"] == oid), None)
            check("rider's list carries the shop name for grouping",
                  bool(row and row.get("vendor_name")), str(row and row.get("vendor_name")))

        # cleanup
        await db.products.delete_one({"id": p["id"]})
        await db.dp_vendor_map.delete_many({"dp_id": me["id"]})
        await db.delivery_partner_applications.delete_many({"user_id": me["id"]})
        await db.users.delete_one({"id": me["id"]})

    print("\n" + "=" * 64)
    print(f"  PASS {PASS}   FAIL {FAIL}")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
