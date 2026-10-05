"""One-off helper: unset the danger_pin_hash so the testing agent can set a known one."""
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    r = await db.settings.update_one({"id":"global"},{"$unset":{"danger_pin_hash":"","danger_pin_set_at":""}})
    print("unset:", r.modified_count)
asyncio.run(main())
