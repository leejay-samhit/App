# UI helper: python ui_prep_layout.py setup|teardown  (ids saved in /tmp/ui_layout_ids.json)
import json
import sys
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
h = {"Authorization": "Bearer " + requests.post(f"{BASE}/auth/login", json={
    "email": "support@slangcart.com", "password": "3)Ywxtic"}).json()["token"]}
F = "/tmp/ui_layout_ids.json"

if sys.argv[1] == "setup":
    ids = {"cats": [], "blocks": []}

    def cat(name, parent=None):
        r = requests.post(f"{BASE}/admin/shop-categories", json={"name": name, "parent_id": parent}, headers=h)
        cid = r.json().get("id") or r.json().get("item", {}).get("id")
        ids["cats"].append(cid)
        return cid

    def blk(c, title):
        r = requests.post(f"{BASE}/admin/shop-layout", headers=h, json={
            "block_type": "section_header", "title": title, "scope": "category",
            "scope_category": c, "active": True})
        ids["blocks"].append(r.json().get("id") or r.json().get("item", {}).get("id"))

    p = cat("TESTUIParent")
    cat("TESTUISubOne", p)
    cat("TESTUISubTwo", p)
    blk("TESTUIParent", "TESTUI PARENT BLOCK")
    blk("TESTUISubOne", "TESTUI SUBONE BLOCK")
    json.dump(ids, open(F, "w"))
    for c in ("TESTUIParent", "TESTUISubOne", "TESTUISubTwo"):
        print(c, [b["title"] for b in requests.get(f"{BASE}/shop-layout", params={"scope": "category", "category": c}).json()["items"]])
else:
    ids = json.load(open(F))
    for b in ids["blocks"]:
        print("del block", requests.delete(f"{BASE}/admin/shop-layout/{b}", headers=h).status_code)
    for c in reversed(ids["cats"]):
        print("del cat", requests.delete(f"{BASE}/admin/shop-categories/{c}", headers=h).status_code)
    db.shop_layout_blocks.delete_many({"id": {"$in": ids["blocks"]}})
    db.shop_categories.delete_many({"id": {"$in": ids["cats"]}})
