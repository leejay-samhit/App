# Iter98 — admin group-wise + vendor Excel export audit: Recharge sheet present,
# every debit in Debit column with remark, no transaction twice across group sheets.
import io
import os
import sys
from collections import Counter, defaultdict

import requests
from openpyxl import load_workbook


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = (os.environ.get("EXPO_BACKEND_URL") or _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL")).rstrip("/") + "/api"
DEBIT_TYPES = {"delivery_charge_paid", "cashback_recovery", "cashback_vendor_recovery", "withdrawal_hold",
               "withdrawal_transaction_fee", "return_refund_debit", "reversal", "refund_company_funded"}


def tok(e, p):
    d = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=60).json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


def audit(wb, label, wallet_sheets_skip=True):
    print(f"\n===== {label}: sheets = {wb.sheetnames}")
    seen = defaultdict(list)
    problems = []
    type_seen = Counter()
    for ws in wb.worksheets:
        hdr_row, hdr = None, None
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=40, values_only=True), start=1):
            vals = [str(c).strip().lower() if c is not None else "" for c in row]
            if any(v in ("debit", "debit (₹)", "debit (rs)") or v.startswith("debit") for v in vals) and any("type" in v for v in vals):
                hdr_row, hdr = i, vals
                break
        if not hdr:
            print(f"  [{ws.title}] no txn header (rows={ws.max_row})")
            continue
        col = {h: j for j, h in enumerate(hdr)}
        def find(*names):
            for n in names:
                for h, j in col.items():
                    if h.startswith(n):
                        return j
        ci_id, ci_type = find("transaction id"), find("transaction type")
        ci_deb, ci_cred = find("debit"), find("credit")
        ci_rem = find("remark", "description", "narration", "note")
        if ws.title in ("All Transactions", "Net Worth Ledger"):
            print("  FULL HEADER", ws.title, hdr)
        n = 0
        for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
            if not row or all(c is None for c in row):
                continue
            t = str(row[ci_type] or "").strip() if ci_type is not None else ""
            if not t or t.lower() in ("group summary", "opening", "closing", "total"):
                continue
            n += 1
            tid = row[ci_id] if ci_id is not None else None
            if tid:
                seen[str(tid)].append(ws.title)
            type_seen[t] += 1
            deb = row[ci_deb] if ci_deb is not None else None
            cred = row[ci_cred] if ci_cred is not None else None
            rem = row[ci_rem] if ci_rem is not None else None
            if t in DEBIT_TYPES:
                try:
                    dv = float(deb or 0)
                except Exception:
                    dv = 0
                if abs(dv) < 0.009:
                    problems.append(f"{ws.title}: {t} {tid} not in Debit col (debit={deb} credit={cred})")
                if not (rem and str(rem).strip()):
                    problems.append(f"{ws.title}: {t} {tid} has no remark")
        print(f"  [{ws.title}] header@{hdr_row} rows={n} cols={hdr[:14]}")
    return seen, problems, type_seen


def main():
    A = tok("support@slangcart.com", "3)Ywxtic")
    r = requests.get(f"{BASE}/admin/wallet/export/groupwise", headers=A, timeout=180)
    print("admin export", r.status_code, r.headers.get("content-type"), len(r.content))
    wb = load_workbook(io.BytesIO(r.content), read_only=True)
    assert any("recharge" in s.lower() for s in wb.sheetnames), "Recharge sheet missing"
    seen, probs, types = audit(wb, "ADMIN")
    group_sheets = {s for s in wb.sheetnames}
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    # allow a txn to appear once in a group sheet + once in a wallet sheet only
    print("\nids appearing more than once:", len(dups))
    multi_group = {k: v for k, v in dups.items() if len([s for s in v if "wallet" not in s.lower() and "all" not in s.lower()]) > 1}
    print("ids in >1 GROUP sheet:", len(multi_group), list(multi_group.items())[:5])
    same_sheet = {k: v for k, v in dups.items() if len(v) != len(set(v))}
    print("ids twice in SAME sheet:", len(same_sheet), list(same_sheet.items())[:5])
    print("debit problems:", len(probs))
    for p in probs[:15]:
        print("   ", p)
    print("types:", {t: c for t, c in types.items() if t in DEBIT_TYPES})

    V = tok("testvendor@test.com", "Test@1234")
    r = requests.get(f"{BASE}/vendor/me/net-worth/export", headers=V, timeout=180)
    print("\nvendor export", r.status_code, r.headers.get("content-type"), len(r.content))
    if r.status_code == 200:
        wb = load_workbook(io.BytesIO(r.content), read_only=True)
        seen, probs, types = audit(wb, "VENDOR")
        same_sheet = {k: v for k, v in seen.items() if len(v) != len(set(v))}
        print("vendor ids twice in SAME sheet:", len(same_sheet), list(same_sheet.items())[:5])
        print("vendor debit problems:", len(probs))
        for p in probs[:15]:
            print("   ", p)
        print("vendor types:", dict(types))


main()
