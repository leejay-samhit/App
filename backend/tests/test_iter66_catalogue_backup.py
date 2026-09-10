"""Phase 4A smoke test — vendor catalogue export → import (merge & replace)."""
import json
import os
import sys

import requests

BASE = os.environ.get("BASE", "http://localhost:8001") + "/api"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    d = r.json()
    tok = d.get("access_token") or d.get("token")
    assert tok, d
    return {"Authorization": f"Bearer {tok}"}


def export_all(h):
    out, offset, total = [], 0, None
    while True:
        r = requests.get(f"{BASE}/vendor/me/catalogue/export", params={"offset": offset, "limit": 10}, headers=h, timeout=120)
        r.raise_for_status()
        d = r.json()
        total = d["total"]
        out += d["products"]
        if not d["has_more"]:
            break
        offset += 10
    return out, total, d


def main():
    src = login("testvendor@test.com", "Test@1234")
    products, total, meta = export_all(src)
    print(f"exported {len(products)}/{total} products, format={meta['format']}")
    assert len(products) == total and total > 0
    assert all("vendor_id" not in p and "id" not in p for p in products), "ownership fields leaked"
    print("sample keys:", sorted(products[0].keys())[:14])

    dst = login("testvendor2@test.com", "Test@1234")
    before = requests.get(f"{BASE}/vendor/me/products", headers=dst, timeout=120).json()
    print("destination had", len(before), "products")

    # merge
    r = requests.post(f"{BASE}/vendor/me/catalogue/import", json={"products": products, "mode": "merge", "first_chunk": True}, headers=dst, timeout=180)
    r.raise_for_status()
    print("merge ->", r.json())
    after = requests.get(f"{BASE}/vendor/me/products", headers=dst, timeout=120).json()
    print("destination now", len(after))
    assert len(after) == len(before) + total

    restored = [p for p in after if p.get("restored_from_backup")]
    assert restored, "no restored flag"
    assert all(p.get("is_published") is False for p in restored), "restored products must be drafts"
    print("restored are drafts:", [p["name"] for p in restored][:5])

    # cleanup: delete the restored ones so re-runs stay clean
    for p in restored:
        requests.delete(f"{BASE}/vendor/me/products/{p['id']}", headers=dst, timeout=60)
    final = requests.get(f"{BASE}/vendor/me/products", headers=dst, timeout=120).json()
    print("cleaned up ->", len(final), "products (expected", len(before), ")")
    assert len(final) == len(before)
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
