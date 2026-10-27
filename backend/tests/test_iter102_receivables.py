"""Iter102 — FIX 1/1b: cashback owed by sellers shows in Receivables + net worth,
and the Excel 'Receivables' sheet ties to the API exactly (no double count).

Run:  python3 tests/test_iter102_receivables.py
"""
import asyncio
import io
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx
from openpyxl import load_workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.db import db  # noqa: E402

PASS, FAIL = [], []
VID = "1115f762-0a4f-474e-bbdb-6227a06f08b1"


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} · {name}" + (f" — {extra}" if extra else ""))


def _env(path, key):
    for ln in open(path):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip().strip('"')


BASE = _env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL").rstrip("/") + "/api"


def sheet_figures(content):
    wb = load_workbook(io.BytesIO(content), data_only=True)
    out = {"sheets": wb.sheetnames}
    if "Receivables" not in wb.sheetnames:
        return out
    ws = wb["Receivables"]
    totals = []
    for row in ws.iter_rows(values_only=True):
        if row and row[0] == "TOTAL":
            totals.append(row)
        if row and isinstance(row[0], str) and row[0].startswith("RECEIVABLES TOTAL"):
            out["grand"] = float(row[1] or 0)
    out["cb_total"] = float(totals[0][1] or 0) if totals else None
    out["adv_total"] = float(totals[1][5] or 0) if len(totals) > 1 else None
    # how many OTHER sheets mention the seeded marker
    out["marker_hits"] = {}
    for name in wb.sheetnames:
        if name == "Receivables":
            continue
        hits = sum(1 for r in wb[name].iter_rows(values_only=True)
                   for c in r if isinstance(c, str) and "TEST_RCV" in c)
        if hits:
            out["marker_hits"][name] = hits
    return out


async def snapshot(c, ah):
    m = (await c.get(f"{BASE}/admin/finance/net-worth", headers=ah)).json()["master"]
    x = await c.get(f"{BASE}/admin/wallet/export/groupwise", headers=ah)
    return m, x.status_code, sheet_figures(x.content) if x.status_code == 200 else {}


async def main():
    ts = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=120) as c:
        ah = {"Authorization": "Bearer " + (await c.post(f"{BASE}/auth/login", json={
            "email": "support@slangcart.com", "password": "3)Ywxtic"})).json()["token"]}
        m0, sc0, x0 = await snapshot(c, ah)
        comps = m0.get("components") or {}
        print("baseline master keys:", {k: m0.get(k) for k in ("cashback_receivable", "vendor_receivable", "receivables_total", "pending_collections", "net_worth")})
        check("components carry cashback_receivable + vendor_receivable",
              "cashback_receivable" in comps and "vendor_receivable" in comps, str(list(comps)[:20]))
        rt = round(float(comps.get("pending_collections") or 0) + float(comps.get("cashback_receivable") or 0)
                   + float(comps.get("vendor_receivable") or 0), 2)
        check("receivables_total = pending + cashback + vendor", abs(rt - float(comps.get("receivables_total") or 0)) < 0.02,
              f"{rt} vs {comps.get('receivables_total')}")
        check("export 200 with Receivables sheet", sc0 == 200 and "Receivables" in x0.get("sheets", []), str(x0.get("sheets")))
        check("baseline: Excel cashback total == API", abs((x0.get("cb_total") or 0) - float(m0.get("cashback_receivable") or 0)) < 0.02,
              f"{x0.get('cb_total')} vs {m0.get('cashback_receivable')}")
        check("baseline: Excel advances total == API vendor_receivable", abs((x0.get("adv_total") or 0) - float(m0.get("vendor_receivable") or 0)) < 0.02,
              f"{x0.get('adv_total')} vs {m0.get('vendor_receivable')}")
        check("baseline: Excel RECEIVABLES TOTAL == API receivables_total", abs((x0.get("grand") or 0) - float(m0.get("receivables_total") or 0)) < 0.02,
              f"{x0.get('grand')} vs {m0.get('receivables_total')}")

        # seed ₹350 cashback outstanding
        prev = (await db.users.find_one({"id": VID}, {"_id": 0, "cashback_outstanding": 1})).get("cashback_outstanding") or 0
        rid = str(uuid.uuid4())
        await db.users.update_one({"id": VID}, {"$set": {"cashback_outstanding": round(float(prev) + 350.0, 2)}})
        await db.vendor_outstanding.insert_one({"id": rid, "vendor_id": VID, "vendor_name": "Test Shop", "kind": "cashback",
                                                "amount": 350.0, "recovered": 0.0, "status": "open",
                                                "order_number": "TEST_RCV", "description": "TEST_RCV seeded", "created_at": ts})
        try:
            m1, _, x1 = await snapshot(c, ah)
            d_cb = round(float(m1["cashback_receivable"]) - float(m0["cashback_receivable"]), 2)
            check("cashback_receivable rises by exactly 350 (no double count)", abs(d_cb - 350) < 0.02, str(d_cb))
            d_rt = round(float(m1["receivables_total"]) - float(m0["receivables_total"]), 2)
            check("receivables_total rises by exactly 350", abs(d_rt - 350) < 0.02, str(d_rt))
            nwk = "net_worth" if "net_worth" in m1 else None
            if nwk:
                d_nw = round(float(m1[nwk]) - float(m0[nwk]), 2)
                check("net worth rises by exactly 350", abs(d_nw - 350) < 0.02, str(d_nw))
            else:
                print("NOTE net_worth key not found in master:", list(m1)[:30])
            check("Excel cashback total == API after seed", abs((x1.get("cb_total") or 0) - float(m1["cashback_receivable"])) < 0.02,
                  f"{x1.get('cb_total')} vs {m1['cashback_receivable']}")
            check("Excel RECEIVABLES TOTAL == API after seed", abs((x1.get("grand") or 0) - float(m1["receivables_total"])) < 0.02,
                  f"{x1.get('grand')} vs {m1['receivables_total']}")
            check("no other sheet repeats the seeded outstanding", not x1.get("marker_hits"), str(x1.get("marker_hits")))
        finally:
            await db.vendor_outstanding.delete_one({"id": rid})
            await db.users.update_one({"id": VID}, {"$set": {"cashback_outstanding": float(prev)}})
        m2, _, _ = await snapshot(c, ah)
        check("after clearing, cashback_receivable back to baseline",
              abs(float(m2["cashback_receivable"]) - float(m0["cashback_receivable"])) < 0.02, str(m2["cashback_receivable"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
