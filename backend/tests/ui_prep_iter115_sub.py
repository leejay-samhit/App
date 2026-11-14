# Iter115 UI prep: temp TEST_ sub-categories under Men (75 + 40 perftest products). Usage: setup | teardown
import os, sys, json, asyncio, requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
STATE = "/tmp/iter115_sub_state.json"
SUBS = [("TEST_115_A", 75), ("TEST_115_B", 40)]


def db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def hdr():
    t = requests.post(f"{BASE}/api/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def setup():
    h = hdr()
    async def pick():
        d = db()
        men = await d.shop_categories.find_one({"name": "Men"}, {"_id": 0, "id": 1})
        rows = await d.products.find({"category": "Men", "perftest": True},
                                     {"_id": 0, "id": 1, "category": 1, "sub_category": 1, "subcategory": 1}).sort("id", -1).to_list(115)
        return men["id"], rows
    men_id, rows = asyncio.run(pick())
    state = {"originals": rows, "cats": []}
    i = 0
    for name, n in SUBS:
        c = requests.post(f"{BASE}/api/admin/shop-categories", headers=h, json={"name": name, "parent_id": men_id}).json()
        state["cats"].append(c.get("id") or (c.get("item") or {}).get("id"))
        ids = [r["id"] for r in rows[i:i + n]]; i += n
        r = requests.post(f"{BASE}/api/admin/products/bulk-category", headers=h, json={"product_ids": ids, "category": "Men", "subcategory": name})
        print(name, r.status_code, r.json().get("updated"))
    json.dump(state, open(STATE, "w"))


def teardown():
    h = hdr()
    st = json.load(open(STATE))
    async def restore():
        d = db()
        for o in st["originals"]:
            upd = {"$set": {k: o[k] for k in ("category", "sub_category", "subcategory") if k in o}}
            uns = {k: "" for k in ("sub_category", "subcategory") if k not in o}
            if uns:
                upd["$unset"] = uns
            await d.products.update_one({"id": o["id"]}, upd)
    asyncio.run(restore())
    for cid in st["cats"]:
        print("delete cat", requests.delete(f"{BASE}/api/admin/shop-categories/{cid}", headers=h).status_code)


if __name__ == "__main__":
    setup() if sys.argv[1] == "setup" else teardown()
