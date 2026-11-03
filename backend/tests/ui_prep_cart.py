# Helper for UI testing: python ui_prep_cart.py mixed|blocked|ok|reset
import sys
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
COD_OK = "401f3c2b-362a-4cfe-9d25-1e432f7ab97e"
COD_OFF = "9c6bb05d-eecc-4637-8489-466f1e4f0288"
tok = requests.post(f"{BASE}/auth/login", json={"email": "testbuyer@test.com", "password": "Test@1234"}).json()["token"]
h = {"Authorization": f"Bearer {tok}"}
mode = sys.argv[1]
requests.post(f"{BASE}/cart/clear", headers=h)
if mode == "reset":
    db.products.update_one({"id": COD_OFF}, {"$unset": {"cod_available": ""}})
else:
    db.products.update_one({"id": COD_OFF}, {"$set": {"cod_available": False}})
    if mode in ("mixed", "ok"):
        requests.post(f"{BASE}/cart/add", json={"product_id": COD_OK, "qty": 1}, headers=h)
    if mode in ("mixed", "blocked"):
        requests.post(f"{BASE}/cart/add", json={"product_id": COD_OFF, "qty": 2}, headers=h)
print(mode, requests.get(f"{BASE}/cart", params={"pincode": "517645"}, headers=h).json().get("cod"))
