# UI helper: python ui_prep_product.py setup|check|teardown
import json, sys, requests
from pymongo import MongoClient
B = [l.split("=",1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("EXPO_PUBLIC_BACKEND_URL=")][0] + "/api"
db = MongoClient("mongodb://localhost:27017")["referral_ecom_db"]
F = "/tmp/ui_prod_ids.json"
ah = {"Authorization": "Bearer " + requests.post(f"{B}/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"}).json()["token"]}
vh = {"Authorization": "Bearer " + requests.post(f"{B}/auth/login", json={"email": "testvendor@test.com", "password": "Test@1234"}).json()["token"]}
if sys.argv[1] == "setup":
    ids = {"cats": []}
    def cat(n, p=None):
        r = requests.post(f"{B}/admin/shop-categories", json={"name": n, "parent_id": p}, headers=ah).json()
        i = r.get("id") or r["item"]["id"]; ids["cats"].append(i); return i
    a = cat("TESTUICatA"); cat("TESTUIA1", a); cat("TESTUIA2", a)
    b = cat("TESTUICatB"); cat("TESTUIB1", b)
    p = requests.post(f"{B}/vendor/me/products", headers=vh, json={"name": "TESTUI Reclass Product", "price": 222, "stock": 9,
        "description": "ui reclass", "category": "TESTUICatA", "sub_category": "TESTUIA1", "image_url": "", "sku": "TESTUISKU", "selling_gst_pct": 5}).json()
    ids["pid"] = p["id"]
    json.dump(ids, open(F, "w")); print(ids)
elif sys.argv[1] == "check":
    ids = json.load(open(F))
    print(db.products.find_one({"id": ids["pid"]}, {"_id": 0, "name": 1, "price": 1, "stock": 1, "sku": 1, "description": 1, "selling_gst_pct": 1, "category": 1, "sub_category": 1, "subcategory": 1, "is_published": 1, "vendor_id": 1}))
else:
    ids = json.load(open(F))
    db.products.delete_one({"id": ids["pid"]}); db.shop_categories.delete_many({"id": {"$in": ids["cats"]}}); print("cleaned")
