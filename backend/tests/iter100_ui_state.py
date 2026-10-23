"""Iter100 UI-state helper: park/restore testbuyer's reveal invoice for the one
provider, and flip registration_paid. Usage: python3 iter100_ui_state.py park|restore|member|free"""
import asyncio, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa
PROV = "22c44148-a5d3-417b-9c89-4d024c9b504a"
BK = "/tmp/iter100_invoice_backup.json"


async def main(cmd):
    u = await db.users.find_one({"email": "testbuyer@test.com"}, {"_id": 0, "id": 1})
    if cmd == "park":
        rows = await db.phone_reveal_invoices.find({"user_id": u["id"], "provider_id": PROV}, {"_id": 0}).to_list(10)
        if rows:
            json.dump(rows, open(BK, "w"), default=str)
            await db.phone_reveal_invoices.delete_many({"user_id": u["id"], "provider_id": PROV})
        print("parked", len(rows))
    elif cmd == "restore":
        await db.phone_reveal_invoices.delete_many({"user_id": u["id"], "provider_id": PROV})
        rows = json.load(open(BK)) if os.path.exists(BK) else []
        if rows:
            await db.phone_reveal_invoices.insert_many(rows)
        print("restored", len(rows))
    elif cmd in ("member", "free"):
        await db.users.update_one({"id": u["id"]}, {"$set": {"registration_paid": cmd == "member"}})
        print("registration_paid", cmd == "member")

asyncio.run(main(sys.argv[1]))
