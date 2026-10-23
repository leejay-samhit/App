# Iter99 — final money sweep: duplicates across ALL ledger types (incl. advance_recovery,
# LEDGERFIX), advance_recovery ↔ vendor_outstanding trace, Receivables tie, fee revenue tie.
import os
from collections import Counter, defaultdict

import requests
from pymongo import MongoClient


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"
db = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
TV = "1115f762-0a4f-474e-bbdb-6227a06f08b1"
REF_KEYS = ("order_id", "withdrawal_id", "return_id", "payment_id", "recovery_ref")

print("== duplicates per (type, user, ref) across ALL types ==")
dups = defaultdict(list)
types = Counter()
for t in db.transactions.find({}, {"_id": 0, "type": 1, "user_id": 1, "idempotency_key": 1, "debit": 1,
                                   "credit": 1, "amount": 1, **{k: 1 for k in REF_KEYS}}):
    types[t.get("type")] += 1
    ref = next((t.get(k) for k in REF_KEYS if t.get(k)), None)
    if not ref:
        continue
    dups[(t.get("type"), t.get("user_id"), ref)].append(t.get("idempotency_key"))
bad = {k: v for k, v in dups.items() if len(v) > 1}
by_type = Counter(k[0] for k in bad)
print("types:", dict(types))
print("dup groups by type:", dict(by_type))
for k, v in list(bad.items())[:12]:
    print("  ", k[0], str(k[1])[:10], str(k[2])[:14], v)

print("\n== idempotency key duplicates ==")
agg = list(db.transactions.aggregate([{"$match": {"idempotency_key": {"$ne": None}}},
                                      {"$group": {"_id": "$idempotency_key", "n": {"$sum": 1}}},
                                      {"$match": {"n": {"$gt": 1}}}]))
print("  ", agg[:5])

print("\n== wallet debits without remark/description, or debit stored in credit ==")
nodesc = db.transactions.count_documents({"debit": {"$gt": 0}, "$and": [
    {"$or": [{"description": {"$in": [None, ""]}}, {"description": {"$exists": False}}]},
    {"$or": [{"remarks": {"$in": [None, ""]}}, {"remarks": {"$exists": False}}]}]})
both = db.transactions.count_documents({"debit": {"$gt": 0}, "credit": {"$gt": 0}})
print("  debit rows w/o remark:", nodesc, "| rows with BOTH debit and credit:", both)
ar = list(db.transactions.find({"type": "advance_recovery"}, {"_id": 0}))
print("  advance_recovery rows:", len(ar), "credit>0:", sum(1 for r in ar if (r.get("credit") or 0) > 0),
      "no desc:", sum(1 for r in ar if not r.get("description")))

print("\n== advance_recovery ↔ vendor_outstanding trace ==")
adv_debit = defaultdict(float)
for r in ar:
    adv_debit[r.get("user_id")] += float(r.get("debit") or 0)
rec = defaultdict(float)
for r in db.vendor_outstanding.find({"kind": {"$in": ["return_refund_company_funded", "delivery_fee",
                                                     "delivery_fee_company_funded"]}}, {"_id": 0}):
    rec[r["vendor_id"]] += float(r.get("recovered") or 0)
for v in set(adv_debit) | set(rec):
    if abs(adv_debit[v] - rec[v]) > 0.009:
        print(f"  UNTRACED vendor {v[:12]}: advance_recovery debits {adv_debit[v]:.2f} vs rows recovered {rec[v]:.2f}")
funded = list(db.transactions.find({"type": "refund_company_funded"}, {"_id": 0, "amount": 1, "vendor_id": 1}))
print("  refund_company_funded txns:", len(funded), "sum", round(sum(float(f.get('amount') or 0) for f in funded), 2))

print("\n== LEDGERFIX ==")
lf = list(db.transactions.find({"idempotency_key": {"$regex": "^LEDGERFIX"}}, {"_id": 0, "user_id": 1, "type": 1,
                                                                              "debit": 1, "credit": 1}))
print("  ", lf)

print("\n== Receivables tie ==")
A = {"Authorization": "Bearer " + requests.post(f"{BASE}/auth/login", json={
    "email": "support@slangcart.com", "password": "3)Ywxtic"}, timeout=60).json()["token"]}
nw = requests.get(f"{BASE}/admin/finance/net-worth", headers=A, timeout=60).json()
m = nw["master"]
open_adv = sum(float(r["amount"]) - float(r.get("recovered") or 0) for r in db.vendor_outstanding.find(
    {"status": "open", "kind": {"$in": ["return_refund_company_funded", "delivery_fee", "delivery_fee_company_funded"]}}))
cb_users = sum(float(u.get("cashback_outstanding") or 0) for u in db.users.find(
    {"cashback_outstanding": {"$gt": 0}}, {"_id": 0, "cashback_outstanding": 1}))
cb_rows = sum(float(r["amount"]) - float(r.get("recovered") or 0) for r in db.vendor_outstanding.find(
    {"status": "open", "kind": "cashback"}))
print("  vendor_receivable", m.get("vendor_receivable"), "open advance rows", round(open_adv, 2))
print("  cashback_receivable", m.get("cashback_receivable"), "users.cashback_outstanding", round(cb_users, 2),
      "open cashback rows", round(cb_rows, 2))
print("  receivables_total", m.get("receivables_total"), "pending_collections", m.get("pending_collections"))
open_kinds = Counter(r["kind"] for r in db.vendor_outstanding.find({"status": "open"}, {"kind": 1}))
print("  open rows by kind:", dict(open_kinds))
g1 = nw.get("group_1_revenue") or {}
fee_rows = sum(float(r.get("amount") or 0) for r in db.transactions.find({"type": "platform_fee_collected"}))
fee_rev = sum(abs(float(r.get("amount") or 0)) for r in db.transactions.find(
    {"type": "reversal", "original_type": "platform_fee_collected"}))
print("  group_1 platform_fee", g1.get("platform_fee"), "rows-reversals", round(fee_rows - fee_rev, 2))
