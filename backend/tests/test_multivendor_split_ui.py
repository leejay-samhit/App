"""Multi-vendor split + wallet/COD combo — API-level verification.

Adds one product from each of two vendors to the buyer's cart, checks that
GET /cart now ships `vendor_name` per line (needed for the new seller
grouping in cart.tsx / checkout.tsx), then checks out with a wallet+COD
combo and asserts two sibling orders were created with the money split
across them.
"""
import os
import requests

BASE = os.environ.get("TEST_BASE", "http://localhost:8001/api")
BUYER = ("testbuyer@test.com", "Test@1234")
PIN = "517644"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def main():
    tok = login(*BUYER)
    h = {"Authorization": f"Bearer {tok}"}

    requests.post(f"{BASE}/cart/clear", headers=h, timeout=30)

    prods = requests.get(f"{BASE}/products", params={"pincode": PIN}, headers=h, timeout=60).json()
    rows = prods.get("items") if isinstance(prods, dict) else prods
    by_vendor = {}
    for p in rows:
        vid = p.get("vendor_id")
        if vid and vid not in by_vendor and float(p.get("price") or 0) > 0 and not p.get("variants"):
            by_vendor[vid] = p
    assert len(by_vendor) >= 2, f"need products from 2 vendors at {PIN}, got {len(by_vendor)}"
    picked = list(by_vendor.values())[:2]
    for p in picked:
        r = requests.post(f"{BASE}/cart/add", headers=h, json={"product_id": p["id"], "qty": 1}, timeout=30)
        assert r.status_code == 200, r.text

    cart = requests.get(f"{BASE}/cart", headers=h, timeout=30).json()
    names = {i["product"].get("vendor_name") for i in cart["items"]}
    assert all(names), f"cart lines missing vendor_name: {names}"
    assert len(names) == 2, f"expected 2 distinct sellers, got {names}"
    total = float(cart["total"])
    print(f"cart OK — total ₹{total}, sellers {names}")

    me = requests.get(f"{BASE}/auth/me", headers=h, timeout=30).json()
    bal = float(me.get("wallet_balance") or 0)
    wallet_amount = round(min(bal, total) / 2, 2)
    assert wallet_amount > 0, "buyer wallet is empty — top up before running"

    r = requests.post(
        f"{BASE}/orders/checkout",
        headers=h,
        json={
            "payment_method": "wallet_cod",
            "wallet_amount": wallet_amount,
            "shipping_address": {
                "name": "Test Buyer", "phone": "9876543210",
                "line1": "1 Test Street", "line2": "",
                "city": "Srikalahasti", "state": "Andhra Pradesh",
                "pincode": PIN, "latitude": 13.7497, "longitude": 79.7036,
            },
        },
        timeout=60,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert int(res.get("split_count") or 1) == 2, res
    assert abs(float(res.get("wallet_paid") or 0) - wallet_amount) < 0.05, res
    assert abs(float(res.get("cod_due") or 0) - (total - wallet_amount)) < 0.05, res
    print("checkout OK —", res.get("split_count"), "orders,",
          "wallet", res.get("wallet_paid"), "cod", res.get("cod_due"))

    orders = requests.get(f"{BASE}/orders/me", headers=h, timeout=30).json()
    rows = orders.get("items") if isinstance(orders, dict) else orders
    gid = None
    for o in rows:
        if int(o.get("split_count") or 1) > 1:
            gid = o.get("group_id")
            break
    assert gid, "no split order group found in /orders/my"
    sibs = [o for o in rows if o.get("group_id") == gid]
    assert len(sibs) == 2, f"expected 2 sibling orders, got {len(sibs)}"
    for o in sibs:
        assert o.get("vendor_name"), f"sibling missing vendor_name: {o.get('order_number')}"
        print(" ", o["order_number"], o["vendor_name"], "total", o["total"],
              "wallet", o.get("wallet_paid"), "cod", o.get("cod_due"), o.get("payment_status"))
    money = sum(float(o.get("wallet_paid") or 0) for o in sibs)
    assert abs(money - wallet_amount) < 0.05, f"wallet allocation mismatch {money} vs {wallet_amount}"
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
