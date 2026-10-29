# Iteration 105 — ad-hoc: can a FREE (Continue Without Fee) account reach paid status + ₹50 cashback with no payment
# via the legacy /payment/register-fee endpoint (+ admin approval)?
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import requests
from test_iter105_registration_probe import make_user, gate, BASE, MDB, CREATED, rand_phone

h, uid, email = make_user("legacyfree")
gate(h, rand_phone())
print("skip", requests.post(f"{BASE}/payment/skip-subscription", headers=h, timeout=30).status_code)
r = requests.post(f"{BASE}/payment/register-fee", headers=h, timeout=30)
print("register-fee", r.status_code, r.text[:160])
u = MDB.users.find_one({"id": uid}, {"_id": 0, "registration_paid": 1, "wallet_balance": 1, "approval_status": 1})
print("after register-fee", u, [(t["type"], t["amount"], t.get("status")) for t in MDB.transactions.find({"user_id": uid})])
print("bank rows", MDB.bank_ledger.count_documents({"user_id": uid}) if "bank_ledger" in MDB.list_collection_names() else "n/a")
ah = {"Authorization": "Bearer " + requests.post(f"{BASE}/auth/login", json={"email": "support@slangcart.com", "password": "3)Ywxtic"}, timeout=30).json()["token"]}
r = requests.post(f"{BASE}/admin/approvals/{uid}/approve", json={}, headers=ah, timeout=60)
print("admin approve", r.status_code, r.text[:160])
u = MDB.users.find_one({"id": uid}, {"_id": 0, "registration_paid": 1, "wallet_balance": 1, "approval_status": 1})
print("after approve", u, [(t["type"], t["amount"], t.get("status")) for t in MDB.transactions.find({"user_id": uid})])
st = requests.get(f"{BASE}/auth/signup-gate/status", headers=h, timeout=30).json()
print("status", st["registration_status"], st["registration_path"])
# cleanup (also sponsor-side rows sourced from this user)
MDB.transactions.delete_many({"$or": [{"user_id": uid}, {"source_user_id": uid}, {"from_user_id": uid}]})
MDB.users.delete_many({"email": {"$in": CREATED}})
print("cleaned")
