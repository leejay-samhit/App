"""Backend test runner — 2026-05-30 finance & accounting endpoints.

Tests endpoints exposed by /app/backend/routes/finance.py and the wallet
regression after the `platform_fee_collected` bucket addition.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, Optional

import requests

BASE = "https://vendor-network-app-1.preview.emergentagent.com/api"
ADMIN_EMAIL = "support@networkrupay.com"
ADMIN_PASSWORD = "Nlee@1115"

results: list[tuple[str, bool, str]] = []
admin_token: Optional[str] = None
admin_user_id: Optional[str] = None


def _h(token: Optional[str] = None) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def record(name: str, ok: bool, detail: str = "") -> bool:
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}  -- {detail}")
    results.append((name, ok, detail))
    return ok


TXN_RE = re.compile(r"^TXN-\d{6}$")


def test_01_unauth_net_worth():
    r = requests.get(f"{BASE}/admin/finance/net-worth")
    record("01 net-worth no-auth → 401/403", r.status_code in (401, 403),
           f"status={r.status_code}")


def test_login() -> Optional[str]:
    global admin_token, admin_user_id
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        record("00 admin login", False, f"status={r.status_code} body={r.text[:200]}")
        return None
    j = r.json()
    admin_token = j.get("access_token") or j.get("token")
    user = j.get("user") or {}
    admin_user_id = user.get("id")
    record("00 admin login", bool(admin_token and admin_user_id),
           f"user_id={admin_user_id}")
    return admin_token


def test_02_net_worth_groups():
    r = requests.get(f"{BASE}/admin/finance/net-worth", headers=_h(admin_token))
    if r.status_code != 200:
        record("02 net-worth admin → 200", False,
               f"status={r.status_code} body={r.text[:300]}")
        return None
    j = r.json()
    needed_groups = {
        "group_1_revenue": ["registration", "service", "platform_fee", "shop", "gross"],
        "group_2_liability": ["total_reward_credits", "total_withdrawals_settled", "available_user_balance"],
        "group_3_gst": ["collected", "paid", "payable"],
        "group_4_platform_fee": ["collected"],
        "group_5_expenses": ["total"],
        "group_6_pending_withdrawals": ["pending_amount"],
        "group_7_bank": ["credits", "debits", "balance"],
        "master": ["pending_collections", "net_worth", "formula"],
    }
    missing = []
    for g, keys in needed_groups.items():
        if g not in j:
            missing.append(g)
            continue
        for k in keys:
            if k not in j[g]:
                missing.append(f"{g}.{k}")
    ok = not missing
    record("02 net-worth admin (groups+master)", ok,
           f"status={r.status_code} missing={missing}")
    return j


def test_03_list_expenses():
    r = requests.get(f"{BASE}/admin/expenses", headers=_h(admin_token))
    ok = r.status_code == 200 and "items" in r.json()
    record("03 list expenses", ok, f"status={r.status_code} count={(r.json() or {}).get('total')}")


def test_04_create_expense() -> Optional[str]:
    payload = {
        "category": "server_hosting",
        "amount": 1500,
        "description": "AWS bill May 2026",
        "vendor": "AWS",
    }
    r = requests.post(f"{BASE}/admin/expenses", headers=_h(admin_token), json=payload)
    if r.status_code != 200:
        record("04 create expense", False, f"status={r.status_code} body={r.text[:300]}")
        return None
    j = r.json()
    exp = j.get("expense") or {}
    eid = exp.get("id")
    disp = exp.get("display_id") or ""
    ok = bool(eid) and TXN_RE.match(disp) is not None
    record("04 create expense (id+display_id TXN-NNNNNN)", ok,
           f"id={eid} display_id={disp}")
    return eid


def test_05_list_expenses_after_create():
    r = requests.get(f"{BASE}/admin/expenses", headers=_h(admin_token))
    ok = r.status_code == 200 and r.json().get("total", 0) >= 1
    record("05 list expenses after create (>=1)", ok,
           f"status={r.status_code} total={r.json().get('total')}")


def test_06_delete_expense(eid: str):
    if not eid:
        record("06 delete expense", False, "no expense id")
        return
    r = requests.delete(f"{BASE}/admin/expenses/{eid}", headers=_h(admin_token))
    if r.status_code != 200:
        record("06 delete expense", False, f"status={r.status_code} body={r.text[:200]}")
        return
    # Verify status="void"
    r2 = requests.get(f"{BASE}/admin/expenses", headers=_h(admin_token))
    rows = (r2.json() or {}).get("items") or []
    target = next((x for x in rows if x.get("id") == eid), None)
    ok = target is not None and target.get("status") == "void"
    record("06 delete expense → void", ok,
           f"target_status={(target or {}).get('status')}")


def test_07_bank_ledger_list():
    r = requests.get(f"{BASE}/admin/bank-ledger", headers=_h(admin_token))
    j = r.json() if r.status_code == 200 else {}
    ok = (r.status_code == 200
          and "items" in j and "credits" in j and "debits" in j and "balance" in j)
    record("07 bank-ledger list (items+credits+debits+balance)", ok,
           f"status={r.status_code} credits={j.get('credits')} balance={j.get('balance')}")
    return j


def test_08_bank_ledger_credit() -> Optional[Dict[str, Any]]:
    payload = {
        "kind": "credit", "amount": 50000, "bank": "HDFC", "utr": "TESTUTR123",
        "description": "Razorpay settlement May",
    }
    r = requests.post(f"{BASE}/admin/bank-ledger", headers=_h(admin_token), json=payload)
    if r.status_code != 200:
        record("08 bank credit ₹50000", False, f"status={r.status_code} body={r.text[:200]}")
        return None
    j = r.json()
    entry = j.get("entry") or {}
    disp = entry.get("display_id") or ""
    ok = TXN_RE.match(disp) is not None
    record("08 bank credit ₹50000 (display_id)", ok, f"display_id={disp}")
    return entry


def test_09_bank_ledger_after_credit(initial: Dict[str, Any]):
    r = requests.get(f"{BASE}/admin/bank-ledger", headers=_h(admin_token))
    j = r.json() if r.status_code == 200 else {}
    delta_c = j.get("credits", 0) - (initial.get("credits") or 0)
    delta_b = j.get("balance", 0) - (initial.get("balance") or 0)
    ok = abs(delta_c - 50000) < 0.5 and abs(delta_b - 50000) < 0.5
    record("09 bank-ledger after credit (delta=50000)", ok,
           f"delta_credits={delta_c} delta_balance={delta_b}")


def test_10_bank_ledger_debit() -> Optional[Dict[str, Any]]:
    payload = {"kind": "debit", "amount": 2000, "description": "Office rent"}
    r = requests.post(f"{BASE}/admin/bank-ledger", headers=_h(admin_token), json=payload)
    if r.status_code != 200:
        record("10 bank debit ₹2000", False, f"status={r.status_code} body={r.text[:200]}")
        return None
    j = r.json()
    entry = j.get("entry") or {}
    ok = TXN_RE.match(entry.get("display_id") or "") is not None
    record("10 bank debit ₹2000 (display_id)", ok, f"display_id={entry.get('display_id')}")
    return entry


def test_11_bank_ledger_after_debit(initial_balance: float):
    r = requests.get(f"{BASE}/admin/bank-ledger", headers=_h(admin_token))
    j = r.json()
    expected = initial_balance + 50000 - 2000  # initial balance before credit/debit
    ok = abs(j.get("balance", 0) - expected) < 0.5
    record("11 bank-ledger balance after credit+debit", ok,
           f"balance={j.get('balance')} expected={expected}")


def test_12_adjust_transaction():
    if not admin_user_id:
        record("12 adjust txn", False, "no admin id")
        return
    payload = {"user_id": admin_user_id, "amount": 100,
               "description": "Test correction", "category": "correction"}
    r = requests.post(f"{BASE}/admin/transactions/adjust",
                      headers=_h(admin_token), json=payload)
    if r.status_code != 200:
        record("12 adjust txn", False, f"status={r.status_code} body={r.text[:200]}")
        return
    j = r.json()
    adj = j.get("adjustment") or {}
    disp = adj.get("display_id") or ""
    ok = TXN_RE.match(disp) is not None
    record("12 adjust txn (display_id TXN-NNNNNN)", ok, f"display_id={disp}")


def test_13_reverse_transaction() -> Optional[str]:
    # Find a successful txn (any other type than reversal/adjustment is fine)
    r = requests.get(f"{BASE}/admin/transactions?limit=50", headers=_h(admin_token))
    if r.status_code != 200:
        record("13 reverse: list txns", False, f"status={r.status_code}")
        return None
    body = r.json()
    txns = body if isinstance(body, list) else (body.get("items") or [])
    cand = None
    for t in txns:
        if (t.get("status") == "success"
                and not t.get("reversed_by")
                and not t.get("reverses")
                and t.get("type") not in ("reversal",)):
            cand = t
            break
    if not cand:
        record("13 reverse: pick candidate", False, "no eligible txn")
        return None
    txn_id = cand.get("id")
    r2 = requests.post(f"{BASE}/admin/transactions/{txn_id}/reverse",
                       headers=_h(admin_token), json={"reason": "test reversal"})
    if r2.status_code != 200:
        record("13 reverse txn", False, f"status={r2.status_code} body={r2.text[:200]}")
        return None
    j = r2.json()
    rev = j.get("reversal") or {}
    rev_id = rev.get("id")
    # Verify forward+back links
    r3 = requests.get(f"{BASE}/admin/transactions?limit=200", headers=_h(admin_token))
    rows = r3.json() if isinstance(r3.json(), list) else (r3.json().get("items") or [])
    original = next((x for x in rows if x.get("id") == txn_id), None)
    reversal = next((x for x in rows if x.get("id") == rev_id), None)
    ok = (original is not None and original.get("reversed_by") == rev_id
          and reversal is not None and reversal.get("reverses") == txn_id)
    record("13 reverse txn → both linked", ok,
           f"orig.reversed_by={original.get('reversed_by') if original else None} "
           f"rev.reverses={reversal.get('reverses') if reversal else None}")
    return txn_id


def test_14_double_reverse(txn_id: str):
    if not txn_id:
        record("14 double-reverse", False, "no txn_id")
        return
    r = requests.post(f"{BASE}/admin/transactions/{txn_id}/reverse",
                      headers=_h(admin_token), json={"reason": "another test"})
    ok = r.status_code == 400 and "already reversed" in (r.text or "").lower()
    record("14 double-reverse → 400 'already reversed'", ok,
           f"status={r.status_code} body={r.text[:200]}")


def test_15_export_transactions():
    r = requests.get(f"{BASE}/admin/finance/export/transactions",
                     headers=_h(admin_token))
    ct = r.headers.get("content-type", "")
    first_line = (r.text or "").split("\n", 1)[0]
    ok = r.status_code == 200 and "text/csv" in ct and "display_id" in first_line
    record("15 export transactions CSV", ok,
           f"status={r.status_code} content-type={ct} header_has_display_id={'display_id' in first_line}")


def test_16_export_expenses():
    r = requests.get(f"{BASE}/admin/finance/export/expenses", headers=_h(admin_token))
    ct = r.headers.get("content-type", "")
    ok = r.status_code == 200 and "text/csv" in ct
    record("16 export expenses CSV", ok, f"status={r.status_code} content-type={ct}")


def test_17_export_bank():
    r = requests.get(f"{BASE}/admin/finance/export/bank", headers=_h(admin_token))
    ct = r.headers.get("content-type", "")
    ok = r.status_code == 200 and "text/csv" in ct
    record("17 export bank CSV", ok, f"status={r.status_code} content-type={ct}")


def test_18_net_worth_after_ops(initial: Dict[str, Any]):
    r = requests.get(f"{BASE}/admin/finance/net-worth", headers=_h(admin_token))
    j = r.json()
    bank_balance = (j.get("group_7_bank") or {}).get("balance")
    # After: voided expense (not counted), bank credit 50000 - debit 2000 = +48000
    initial_bank = (initial.get("group_7_bank") or {}).get("balance") or 0
    expected_bank = initial_bank + 48000
    ok_bank = abs((bank_balance or 0) - expected_bank) < 0.5
    record("18 net-worth bank balance after ops (+48000)", ok_bank,
           f"bank={bank_balance} expected≈{expected_bank}")
    # group_5 expenses total — void should not be counted
    record("18b net-worth group_5_expenses present",
           "total" in (j.get("group_5_expenses") or {}),
           f"expenses_total={(j.get('group_5_expenses') or {}).get('total')}")


def test_19_regression_admin_login():
    """Login again. May revoke the active session token (single-session policy),
    so we update the global admin_token afterwards."""
    global admin_token
    r = requests.post(f"{BASE}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    ok = r.status_code == 200
    record("19a admin login regression", ok, f"status={r.status_code}")
    if ok:
        j = r.json()
        new_tok = j.get("access_token") or j.get("token")
        if new_tok:
            admin_token = new_tok


def test_19_system_wallet():
    r = requests.get(f"{BASE}/admin/system-wallet", headers=_h(admin_token))
    if r.status_code != 200:
        record("19b system-wallet (old)", False, f"status={r.status_code} body={r.text[:200]}")
        return
    j = r.json()
    buckets = j.get("buckets") or {}
    has_pf = "platform_fee_collected" in buckets
    bucket_count = len(buckets)
    record("19b system-wallet has 8 buckets incl platform_fee_collected",
           has_pf and bucket_count == 8,
           f"buckets={list(buckets.keys())} count={bucket_count}")


def test_19_service_categories():
    r = requests.get(f"{BASE}/admin/service-categories", headers=_h(admin_token))
    record("19c admin/service-categories", r.status_code == 200,
           f"status={r.status_code} body={r.text[:200]}")


def main():
    print(f"Base URL: {BASE}")
    if not test_login():
        sys.exit(1)
    # Capture initial state for net-worth+bank
    initial_nw = test_02_net_worth_groups()
    initial_bank = test_07_bank_ledger_list() or {}
    initial_balance = initial_bank.get("balance") or 0

    test_01_unauth_net_worth()
    test_03_list_expenses()
    eid = test_04_create_expense()
    test_05_list_expenses_after_create()
    if eid:
        test_06_delete_expense(eid)

    test_08_bank_ledger_credit()
    test_09_bank_ledger_after_credit(initial_bank)
    test_10_bank_ledger_debit()
    test_11_bank_ledger_after_debit(initial_balance)

    test_12_adjust_transaction()
    txn_id = test_13_reverse_transaction()
    if txn_id:
        test_14_double_reverse(txn_id)

    test_15_export_transactions()
    test_16_export_expenses()
    test_17_export_bank()

    test_18_net_worth_after_ops(initial_nw or {})

    test_19_regression_admin_login()
    test_19_system_wallet()
    test_19_service_categories()

    # Summary
    n_pass = sum(1 for _, ok, _ in results if ok)
    n_fail = sum(1 for _, ok, _ in results if not ok)
    print("\n" + "=" * 70)
    print(f"PASS={n_pass}  FAIL={n_fail}  TOTAL={len(results)}")
    if n_fail:
        print("\nFAILURES:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
