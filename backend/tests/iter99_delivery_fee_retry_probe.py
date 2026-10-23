# Iter99 probe — can an unfunded delivery fee be both paid on a later re-delivery AND
# recovered again as an open `delivery_fee` advance (double recovery / duplicate rows)?
import uuid
import requests
from pymongo import MongoClient


def _env(p, k):
    for ln in open(p):
        if ln.startswith(k + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
A = {"Authorization": "Bearer " + requests.post(f"{BASE}/auth/login", json={
    "email": "support@slangcart.com", "password": "3)Ywxtic"}, timeout=60).json()["token"]}
tag = uuid.uuid4().hex[:6]
vid, cid, dpid, oid = f"TEST_vdf_{tag}", f"TEST_cdf_{tag}", f"TEST_dpdf_{tag}", f"TEST_odf_{tag}"
db.users.insert_many([
    {"id": vid, "email": f"{vid}@x.com", "name": "TEST vdf", "is_vendor": True, "is_vendor_approved": True,
     "vendor_earnings": 0.0, "wallet_balance": 0.0, "referral_code": f"TVDF{tag}"},
    {"id": cid, "email": f"{cid}@x.com", "name": "TEST cdf", "wallet_balance": 0.0, "referral_code": f"TCDF{tag}"},
    {"id": dpid, "email": f"{dpid}@x.com", "name": "TEST dpdf", "is_delivery_partner": True,
     "wallet_balance": 0.0, "referral_code": f"TDDF{tag}"},
])
db.orders.insert_one({"id": oid, "order_number": f"TEST-DF-{tag}", "user_id": cid, "vendor_id": vid,
                      "vendor_name": "TEST vdf", "dp_id": dpid, "status": "shipped", "total": 10.0,
                      "delivery_charge": 20.0, "paid_via": "wallet", "items": [], "status_history": [],
                      "created_at": "2026-01-01T00:00:00+00:00"})
try:
    def mv(st):
        r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=A, json={"status": st}, timeout=60)
        print(" ->", st, r.status_code, r.text[:120])

    def state(lbl):
        rows = list(db.vendor_outstanding.find({"order_id": oid}, {"_id": 0, "kind": 1, "status": 1, "amount": 1}))
        paid = db.transactions.count_documents({"order_id": oid, "type": "delivery_charge_paid"})
        w = db.users.find_one({"id": vid}, {"_id": 0, "vendor_earnings": 1})["vendor_earnings"]
        print(f"[{lbl}] outstanding={rows} delivery_charge_paid={paid} wallet={w}")

    mv("delivered"); state("short seller delivered")
    mv("shipped"); mv("delivered"); state("re-delivered while still short")
    db.users.update_one({"id": vid}, {"$set": {"vendor_earnings": 100.0}})
    mv("shipped"); mv("delivered"); state("re-delivered with money")
finally:
    db.users.delete_many({"id": {"$in": [vid, cid, dpid]}})
    db.orders.delete_one({"id": oid})
    db.vendor_outstanding.delete_many({"order_id": oid})
    db.transactions.delete_many({"$or": [{"order_id": oid}, {"user_id": {"$in": [vid, cid, dpid]}}]})
    db.notifications.delete_many({"user_id": {"$in": [vid, cid, dpid]}})
    if "financial_errors" in db.list_collection_names():
        db.financial_errors.delete_many({"order_id": oid})
