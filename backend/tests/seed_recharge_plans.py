"""Seed demo Recharge plans — Oct-2026.

The Recharge screen has nothing to show until a vendor (or the owner) lists
plans. This seeds a realistic AP&TG set for every mobile network plus a few
DTH packs, tagged with `recharge_kind` / `recharge_state` / `recharge_network`
so `/api/recharge/products` can filter them.

Idempotent — keyed on a stable `id`, so re-running updates instead of
duplicating. Safe to run on a live DB.

Run:  python -m tests.seed_recharge_plans
"""
import asyncio
from datetime import datetime, timezone

from core.db import db
from routes.recharge import seed_defaults, slugify

# (label, price, subcategory, blurb)
MOBILE_PLANS = [
    ("Unlimited 28 days · 2GB/day",  349, "Unlimited",  "Truly unlimited calls, 2GB/day, 100 SMS/day"),
    ("Unlimited 56 days · 1.5GB/day", 579, "Unlimited",  "Truly unlimited calls, 1.5GB/day, 100 SMS/day"),
    ("Unlimited 84 days · 2GB/day",  859, "Unlimited",  "Truly unlimited calls, 2GB/day, 100 SMS/day"),
    ("Annual · 2.5GB/day",         3359, "Unlimited",  "365 days validity, 2.5GB/day, unlimited calls"),
    ("Data add-on · 1GB",            19, "Data add-on", "1GB extra data, valid for existing pack"),
    ("Data add-on · 6GB",            125, "Data add-on", "6GB extra data, no validity change"),
    ("Talktime ₹100",                100, "Talktime",   "Full talktime top-up"),
]

DTH_PLANS = [
    ("Value Pack · 1 month",   299, "Monthly packs", "180+ channels incl. regional"),
    ("Family Pack · 1 month",  449, "Monthly packs", "250+ channels incl. HD"),
    ("Family Pack · 3 months", 1299, "Long term",    "250+ channels, 3-month validity"),
    ("Sports Add-on",           150, "Add-ons",      "All sports channels for 1 month"),
]


async def main() -> None:
    await seed_defaults()
    opts = await db.recharge_options.find({"active": True}, {"_id": 0}).to_list(500)
    ts = datetime.now(timezone.utc).isoformat()

    vendor = await db.users.find_one(
        {"is_vendor": True, "is_vendor_approved": True}, {"_id": 0, "id": 1, "shop_name": 1, "name": 1},
    )
    if not vendor:
        print("No approved vendor found — recharge plans need an owner. Aborting.")
        return

    written = 0
    for kind, plans in (("mobile", MOBILE_PLANS), ("dth", DTH_PLANS)):
        states = [o for o in opts if o["kind"] == kind and o["group"] == "state"]
        networks = [o for o in opts if o["kind"] == kind and o["group"] == "network"]
        for st in states:
            for nw in networks:
                for label, price, subcat, blurb in plans:
                    pid = f"rchg-{kind}-{st['slug']}-{nw['slug']}-{slugify(label)}"
                    doc = {
                        "id": pid,
                        "name": f"{nw['name']} {label}",
                        "description": blurb,
                        "price": float(price),
                        "mrp": float(price),
                        "stock": 99999,
                        "category": "Recharge",
                        "subcategory": subcat,
                        "brand": nw["name"],
                        "recharge_kind": kind,
                        "recharge_state": st["slug"],
                        "recharge_network": nw["slug"],
                        "vendor_id": vendor["id"],
                        "vendor_name": vendor.get("name") or "",
                        "shop_name": vendor.get("shop_name") or "",
                        "active": True,
                        # A recharge is delivered instantly and digitally —
                        # never COD, never a delivery charge.
                        "cod_available": False,
                        "free_delivery": True,
                        "is_digital": True,
                        "updated_at": ts,
                    }
                    await db.products.update_one(
                        {"id": pid},
                        {"$set": doc, "$setOnInsert": {"created_at": ts}},
                        upsert=True,
                    )
                    written += 1

    # Make sure a Recharge category exists so the shop strip can route to it.
    existing_cat = await db.shop_categories.find_one({"slug": "recharge"}, {"_id": 0})
    if not existing_cat:
        import uuid
        await db.shop_categories.insert_one({
            "id": str(uuid.uuid4()),
            "name": "Recharge",
            "slug": "recharge",
            "parent_id": None,
            "depth": 0,
            "active": True,
            "created_at": datetime.now(timezone.utc),
        })
        print("created Recharge category")

    total = await db.products.count_documents({"category": "Recharge"})
    print(f"seeded/updated {written} plans · {total} recharge products in catalogue")


if __name__ == "__main__":
    asyncio.run(main())
