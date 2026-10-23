# Iter97 — FIX 4 recharge notification wording + FIX 7 catalogue fallback.
import os
import time
import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]


def tok(e, p):
    d = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=60).json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


A = tok("support@slangcart.com", "3)Ywxtic")
B = tok("testbuyer@test.com", "Test@1234")


def test_recharge_notifications():
    opts = requests.get(f"{BASE}/recharge/options", timeout=60).json()["mobile"]
    st, net = opts["states"][0]["slug"], opts["networks"][0]["slug"]
    prods = requests.get(f"{BASE}/recharge/products", params={"kind": "mobile", "state": st, "network": net,
                                                              "pincode": "517644"}, timeout=60).json()
    print("supplier", {k: prods.get(k) for k in prods if k != "groups"})
    plan = next(p for g in prods["groups"] for p in g["products"])
    pay = requests.post(f"{BASE}/recharge/pay/wallet", headers=B, json={
        "product_id": plan["id"], "kind": "mobile", "account": "9876501111", "state": st, "network": net},
        timeout=60)
    assert pay.status_code == 200, pay.text
    rid, oid = pay.json()["recharge_id"], pay.json()["order_id"]
    order = db.orders.find_one({"id": oid})
    buyer, vendor = order["user_id"], order.get("vendor_id")
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 2))
    try:
        for s in ["confirmed", "delivered", "delivered", "delivered"]:
            r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=A, json={"status": s}, timeout=60)
            print(s, r.status_code, r.text[:120])
        time.sleep(2)
        bn = list(db.notifications.find({"user_id": buyer, "created_at": {"$gte": t0}}, {"_id": 0, "title": 1, "message": 1, "body": 1}))
        vn = list(db.notifications.find({"user_id": vendor, "created_at": {"$gte": t0}}, {"_id": 0, "title": 1, "message": 1}))
        pl = list(db.push_log.find({"created_at": {"$gte": t0}}, {"_id": 0}).limit(20))
        print("BUYER", bn)
        print("VENDOR", vn)
        print("PUSH", [(p.get("title") or (p.get("data") or {}).get("title"), p.get("idempotency_key")) for p in pl])
        titles = [n["title"] for n in bn]
        assert not any("parcel" in (str(n.get("message")) + str(n.get("body"))).lower() for n in bn), "parcel copy on recharge"
        assert titles.count("Recharge successful") == 1, titles
        assert "Recharge update" in titles and "Order delivered" not in titles
        # One notice per REAL event: the new request, the confirm and the
        # completion. Replays must not add a fourth.
        vt = [n["title"] for n in vn]
        assert len(vt) == len(set(vt)), f"vendor notified twice for the same event: {vt}"
        assert len(vn) <= 3, f"vendor notified {len(vn)} times: {vt}"
    finally:
        db.recharges.update_one({"id": rid}, {"$set": {"account": "TEST_iter97"}})
