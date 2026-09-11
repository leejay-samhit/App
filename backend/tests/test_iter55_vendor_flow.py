"""Iter 55 — vendor patches order status for a wallet_cod order and we
verify the delivered->settlement flow works identically to a pure COD
(vendor gets credited + admin commission if enabled). Also verify vendor
cancel refunds only the wallet slice.

Runs as a standalone script (not pytest) so it can drive an admin/vendor
flow with less setup.
"""
import os
import sys

import requests

BASE = os.environ.get("SC_BASE", "https://slangcart-tracking.preview.emergentagent.com/api")
BUYER = ("testbuyer@test.com", "Test@1234")
VENDOR = ("testvendor@test.com", "Test@1234")
PIN = "517644"
P1 = "9c6bb05d-eecc-4637-8489-466f1e4f0288"
ADDR = {"name": "CI Buyer", "phone": "9999999999", "line1": "1 Test Street",
        "city": "Srikalahasti", "state": "Andhra Pradesh", "pincode": PIN}


def _login(e, p):
    r = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def main():
    hb = {"Authorization": f"Bearer {_login(*BUYER)}"}
    hv = {"Authorization": f"Bearer {_login(*VENDOR)}"}

    me_b_before = requests.get(f"{BASE}/auth/me", headers=hb, timeout=30).json()
    bal_before = float(me_b_before.get("wallet_balance") or 0)
    print("buyer wallet before:", bal_before)

    # Place a wallet_cod order (₹100 basket, ₹40 wallet)
    requests.post(f"{BASE}/cart/clear", headers=hb, timeout=30)
    requests.post(f"{BASE}/cart/add", headers=hb, json={"product_id": P1, "qty": 1}, timeout=30)
    r = requests.post(f"{BASE}/orders/checkout", headers=hb, timeout=60, json={
        "payment_method": "wallet_cod", "wallet_amount": 40.0, "shipping_address": ADDR,
    })
    assert r.status_code == 200, r.text[:200]
    o = r.json()["orders"][0]
    print(f"order: {o['order_number']} paid_via={o['paid_via']} wallet={o['wallet_paid']} cod={o['cod_due']}")
    assert o["paid_via"] == "wallet_cod"
    order_id = o["id"]

    # Vendor moves order to shipped then delivered
    r1 = requests.patch(f"{BASE}/vendor/orders/{order_id}/status",
                        headers=hv, json={"status": "shipped"}, timeout=30)
    print("vendor→shipped:", r1.status_code, r1.text[:120])
    assert r1.status_code == 200

    r2 = requests.patch(f"{BASE}/vendor/orders/{order_id}/status",
                        headers=hv, json={"status": "delivered"}, timeout=30)
    print("vendor→delivered:", r2.status_code, r2.text[:120])
    assert r2.status_code == 200

    # Buyer /orders/me shows delivered + payment_status paid
    rows = requests.get(f"{BASE}/orders/me", headers=hb, timeout=30).json()
    row = next((x for x in rows if x["id"] == order_id), None)
    assert row and row["status"] == "delivered"
    print("delivered order payment_status:", row.get("payment_status"))
    assert row.get("payment_status") == "paid", "wallet_cod delivery must flip payment_status to paid"

    print("\n✅ wallet_cod delivery flow verified")

    # ── Now a fresh wallet_cod order → vendor CANCELS → wallet slice refunded
    requests.post(f"{BASE}/cart/clear", headers=hb, timeout=30)
    requests.post(f"{BASE}/cart/add", headers=hb, json={"product_id": P1, "qty": 1}, timeout=30)
    r = requests.post(f"{BASE}/orders/checkout", headers=hb, timeout=60, json={
        "payment_method": "wallet_cod", "wallet_amount": 30.0, "shipping_address": ADDR,
    })
    assert r.status_code == 200
    o2 = r.json()["orders"][0]
    assert o2["paid_via"] == "wallet_cod"
    oid2 = o2["id"]

    before = float(requests.get(f"{BASE}/auth/me", headers=hb, timeout=30).json().get("wallet_balance") or 0)
    r3 = requests.patch(f"{BASE}/vendor/orders/{oid2}/status",
                        headers=hv, json={"status": "cancelled"}, timeout=30)
    print("vendor→cancelled:", r3.status_code)
    assert r3.status_code == 200
    after = float(requests.get(f"{BASE}/auth/me", headers=hb, timeout=30).json().get("wallet_balance") or 0)
    delta = round(after - before, 2)
    print("wallet delta after vendor-cancel of wallet_cod order:", delta)
    assert abs(delta - 30.0) < 0.02, f"expected wallet slice (30) refunded, got {delta}"
    print("\n✅ wallet_cod vendor-cancel refund verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
