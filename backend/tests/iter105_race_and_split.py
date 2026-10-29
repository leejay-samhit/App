# Iteration 105 — ad-hoc: (1) cross-account phone-link race over many rounds, (2) paid-registration money split dump.
import sys, os, uuid, threading
sys.path.insert(0, os.path.dirname(__file__))
import requests
from test_iter105_registration_probe import make_user, gate, BASE, MDB, CREATED, rand_phone

users = [make_user(f"race{i}") for i in range(6)]
dups = 0
for rnd in range(10):
    p = rand_phone()
    barrier = threading.Barrier(len(users))
    codes = []

    def go(u):
        barrier.wait()
        codes.append(gate(u[0], p).status_code)
    ts = [threading.Thread(target=go, args=(u,)) for u in users]
    [t.start() for t in ts]; [t.join() for t in ts]
    n = MDB.users.count_documents({"phone": p})
    if n > 1:
        dups += 1
    print(f"round {rnd}: owners={n} codes={sorted(codes)}")
print("RACE DUPLICATE ROUNDS:", dups, "/ 10")

# paid split
h, uid, _ = users[0]
oid = requests.post(f"{BASE}/payment/create-order", headers=h, timeout=30).json()["order_id"]
r = requests.post(f"{BASE}/payment/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": "pay_split",
                                                  "razorpay_signature": "s"}, headers=h, timeout=60)
print("verify", r.status_code)
for t in MDB.transactions.find({"$or": [{"user_id": uid}, {"source_user_id": uid}, {"from_user_id": uid}]},
                               {"_id": 0, "type": 1, "amount": 1, "status": 1, "user_id": 1}):
    print("TXN", t)
for coll in ("bank_ledger", "gst_ledger", "platform_revenue", "company_ledger", "ledger_entries"):
    if coll in MDB.list_collection_names():
        for t in MDB[coll].find({"$or": [{"user_id": uid}, {"ref_key": {"$regex": oid}}]}, {"_id": 0}).limit(5):
            print(coll.upper(), {k: t.get(k) for k in ("kind", "amount", "category", "type", "description")})
u = MDB.users.find_one({"id": uid}, {"_id": 0, "wallet_balance": 1, "registration_paid": 1})
print("USER", u)

ids = [x["id"] for x in MDB.users.find({"email": {"$in": CREATED}}, {"id": 1})]
MDB.transactions.delete_many({"user_id": {"$in": ids}})
MDB.users.delete_many({"email": {"$in": CREATED}})
print("cleaned", len(ids))
