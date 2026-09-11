"""Iter 55 — multi-vendor order split + wallet/COD combo smoke test.

Runs against the live preview API. Puts two different vendors' products in
the CI buyer's cart, checks out with `wallet_cod`, then asserts:
  • one order per vendor (unique order_number, shared group_id)
  • wallet_paid + cod_due ties back to the basket total
  • /orders/me returns each sub-order with vendor identity
  • POST /orders/{id}/chat-vendor opens a thread
Run `python tests/seed_iter55.py` first.
"""
import os

import requests

BASE = os.environ.get("SC_BASE", "https://slangcart-tracking.preview.emergentagent.com/api")
BUYER = ("testbuyer@test.com", "Test@1234")
PIN = "517644"
P1 = "9c6bb05d-eecc-4637-8489-466f1e4f0288"  # Vendor One Widget  ₹100
P2 = "409e52af-3660-4bb3-92b4-e418a7f4a5aa"  # Vendor Two Gadget  ₹250


def main():
    r = requests.post(f"{BASE}/auth/login", json={"email": BUYER[0], "password": BUYER[1]}, timeout=30)
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['token']}"}

    requests.post(f"{BASE}/cart/clear", headers=h, timeout=30)
    for pid, qty in ((P1, 2), (P2, 1)):
        rr = requests.post(f"{BASE}/cart/add", headers=h, json={"product_id": pid, "qty": qty}, timeout=30)
        print("cart/add", pid[:8], rr.status_code)

    cart = requests.get(f"{BASE}/cart", headers=h, timeout=30).json()
    basket = sum(float(i.get("line_total") or 0) for i in cart.get("items", []))
    print("basket total:", basket)

    addr = {
        "name": "CI Buyer", "phone": "9999999999", "line1": "1 Test Street",
        "city": "Srikalahasti", "state": "Andhra Pradesh", "pincode": PIN,
    }
    wallet_amount = 150.0
    res = requests.post(
        f"{BASE}/orders/checkout", headers=h, timeout=60,
        json={"payment_method": "wallet_cod", "wallet_amount": wallet_amount, "shipping_address": addr},
    )
    print("checkout:", res.status_code)
    if res.status_code != 200:
        print(res.text[:800]); return 1
    d = res.json()
    print("split_count:", d["split_count"], "group:", d["group_id"][:8])
    print("wallet_paid:", d["wallet_paid"], "cod_due:", d["cod_due"], "grand:", d["grand_total"])
    for o in d["orders"]:
        print(f"  {o['order_number']}  vendor={o['vendor_name']}  total={o['total']}  "
              f"wallet={o['wallet_paid']}  cod={o['cod_due']}  paid_via={o['paid_via']}")

    assert d["split_count"] == 2, "expected one order per vendor"
    assert abs(d["wallet_paid"] + d["cod_due"] - d["grand_total"]) < 0.02, "payment split must tie out"
    assert abs(d["wallet_paid"] - wallet_amount) < 0.02, "wallet slice mismatch"
    assert len({o["order_number"] for o in d["orders"]}) == 2, "order numbers must be unique"

    mine = requests.get(f"{BASE}/orders/me", headers=h, timeout=30).json()
    fresh = [o for o in mine if o.get("group_id") == d["group_id"]]
    print("orders/me rows for group:", len(fresh))
    assert len(fresh) == 2
    for o in fresh:
        assert o.get("vendor_name"), "vendor_name must be present"

    ch = requests.post(f"{BASE}/orders/{fresh[0]['id']}/chat-vendor", headers=h, timeout=30)
    print("chat-vendor:", ch.status_code, str(ch.json())[:160])
    assert ch.status_code == 200 and ch.json().get("thread_id")

    print("\n✅ ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
