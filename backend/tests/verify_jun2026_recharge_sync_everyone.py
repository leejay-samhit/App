"""Jun-2026 — Recharge operator ↔ shop sub-category sync + "Everyone" zone.

Covers the two owner reports:
  1. Admin → Recharge options → Networks/Operators must BE the Recharge
     sub-categories (grouped under Mobile / DTH), so a vendor product filed
     under "Airtel" actually shows on the Recharge screen; deleting an
     operator that still has products must be refused.
  2. Vendor delivery zone gains "Everyone" — ship anywhere in India once the
     admin approves, with COD refused for far-away orders.

Run: python backend/tests/verify_jun2026_recharge_sync_everyone.py
"""
import asyncio
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE = "http://localhost:8001/api"
ADMIN = {"email": "support@slangcart.com", "password": "3)Ywxtic"}

PASS = 0
FAIL = 0


def check(name: str, ok: bool, extra: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} {extra}")


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as hc:
        r = await hc.post("/auth/login", json=ADMIN)
        assert r.status_code == 200, r.text
        hdr = {"Authorization": f"Bearer {r.json()['token']}"}

        print("\n── 1. operator list mirrors into the Recharge tree ──")
        await hc.get("/recharge/options")
        root = await db.shop_categories.find_one({"parent_id": None, "recharge_root": True})
        check("root Recharge category exists", bool(root))
        groups = {}
        async for g in db.shop_categories.find({"parent_id": root["id"], "recharge_group": "kind"}):
            groups[g["recharge_kind"]] = g
        check("Mobile + DTH groups exist", set(groups) == {"mobile", "dth"}, str(list(groups)))
        kids = [c["name"] async for c in db.shop_categories.find(
            {"parent_id": groups["mobile"]["id"], "active": True})]
        check("mobile operators mirrored", {"Airtel", "Jio", "Vi", "BSNL"} <= set(kids), str(kids))
        dkids = [c["name"] async for c in db.shop_categories.find(
            {"parent_id": groups["dth"]["id"], "active": True})]
        check("dth operators mirrored", "Tata Play" in dkids, str(dkids))
        check("no duplicate Airtel under root",
              await db.shop_categories.count_documents(
                  {"name": "Airtel", "parent_id": root["id"]}) == 0)

        print("\n── 2. adding an operator creates its sub-category ──")
        nm = f"ZTest {uuid.uuid4().hex[:5]}"
        r = await hc.post("/admin/recharge/options",
                          json={"kind": "mobile", "group": "network", "name": nm}, headers=hdr)
        check("option created", r.status_code == 200, r.text[:160])
        opt_id = r.json().get("id")
        cat = await db.shop_categories.find_one({"recharge_option_id": opt_id})
        check("sub-category created under Mobile Recharge",
              bool(cat) and cat.get("parent_id") == groups["mobile"]["id"] and cat.get("active"))

        print("\n── 3. a vendor product filed under the operator shows up ──")
        vendor = await db.users.find_one({"email": "testvendor@test.com"})
        pid = str(uuid.uuid4())
        await db.products.insert_one({
            "id": pid, "name": "ZTest vendor plan", "price": 199.0, "stock": 99,
            "category": "Recharge", "subcategory": cat["name"],
            "vendor_id": vendor["id"], "is_published": False, "active": True,
        })
        try:
            r = await hc.get("/recharge/products", params={
                "kind": "mobile", "state": "andhra-pradesh-telangana-ap-tg",
                "network": cat["recharge_network"]})
            names = [p["name"] for g in r.json()["groups"] for p in g["products"]]
            check("unpublished plan hidden", "ZTest vendor plan" not in names, str(names))
            await db.products.update_one({"id": pid}, {"$set": {"is_published": True}})
            r = await hc.get("/recharge/products", params={
                "kind": "mobile", "state": "andhra-pradesh-telangana-ap-tg",
                "network": cat["recharge_network"]})
            names = [p["name"] for g in r.json()["groups"] for p in g["products"]]
            check("published plan listed for that operator", "ZTest vendor plan" in names, str(names))

            print("\n── 4. delete is refused while products exist ──")
            r = await hc.delete(f"/admin/recharge/options/{opt_id}", headers=hdr)
            check("delete blocked (409)", r.status_code == 409, f"{r.status_code} {r.text[:160]}")
            check("message names the count", "1 product" in r.text, r.text[:200])
        finally:
            await db.products.delete_one({"id": pid})

        r = await hc.delete(f"/admin/recharge/options/{opt_id}", headers=hdr)
        check("delete allowed once empty", r.status_code == 200, r.text[:160])
        cat = await db.shop_categories.find_one({"recharge_option_id": opt_id})
        check("sub-category hidden after delete", cat is not None and not cat.get("active"))
        await db.recharge_options.delete_one({"id": opt_id})
        await db.shop_categories.delete_one({"recharge_option_id": opt_id})

        print("\n── 5. seeded Airtel plans still list ──")
        r = await hc.get("/recharge/products", params={
            "kind": "mobile", "state": "andhra-pradesh-telangana-ap-tg", "network": "airtel"})
        check("airtel plans present", r.json()["count"] > 0, r.text[:120])

    print("\n── 6. 'Everyone' delivery zone ──")
    from core.delivery import vendor_covers, vendor_covers_locally, eligible_vendor_ids

    v = {"id": "zz", "delivery_radius_mode": "everywhere", "store_pincode": "517644",
         "delivery_radius_km": 5, "lat": 13.7484, "lng": 79.7027, "is_vendor_approved": True}
    res = await vendor_covers(v, pincode="110001")
    check("covers a far pincode", res["covered"] and res["reason"] == "everywhere", str(res))
    res = await vendor_covers(v, pincode=None, lat=28.6, lng=77.2)
    check("covers far coordinates", res["covered"], str(res))
    check("far order is NOT local", not await vendor_covers_locally(v, pincode="110001"))
    check("own pincode IS local", await vendor_covers_locally(v, pincode="517644"))
    off = await vendor_covers({**v, "delivery_available": False}, pincode="110001")
    check("delivery switched off still wins", not off["covered"], str(off))
    check("a normal vendor is always 'local'",
          await vendor_covers_locally({"delivery_radius_mode": "pincode", "store_pincode": "517644"},
                                      pincode="110001"))

    vid = str(uuid.uuid4())
    await db.users.insert_one({
        "id": vid, "email": f"zz-{vid[:6]}@t.com", "is_vendor_approved": True,
        "referral_code": f"ZZ{vid[:8].upper()}",
        "delivery_radius_mode": "everywhere", "store_pincode": "517644",
    })
    try:
        ids = await eligible_vendor_ids(pincode="110001")
        check("eligible-vendor filter includes the Everyone shop", vid in ids)
    finally:
        await db.users.delete_one({"id": vid})

    print(f"\n{PASS}/{PASS + FAIL} PASS")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
