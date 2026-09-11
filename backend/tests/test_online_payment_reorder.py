"""Online (Razorpay) order payment + reorder + cart qty stepper — API tests.

Runs against the live backend in mock Razorpay mode (no keys configured):
  1. cart qty stepper  (/cart/adjust up & down, stock cap)
  2. wallet + online combo (start → verify → checkout) across TWO vendors,
     asserting the split orders carry wallet_paid / online_paid and are
     fully prepaid (cod_due 0)
  3. single-use guard — the same payment id can't place a second order
  4. reorder of one sub-order re-adds its lines to the cart
"""
import os
import requests

BASE = os.environ.get("TEST_BASE", "http://localhost:8001/api")
BUYER = ("testbuyer@test.com", "Test@1234")
PIN = "517644"
ADDRESS = {
    "name": "Test Buyer", "phone": "9876543210",
    "line1": "1 Test Street", "line2": "",
    "city": "Srikalahasti", "state": "Andhra Pradesh",
    "pincode": PIN, "latitude": 13.7497, "longitude": 79.7036,
}


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def main():
    h = {"Authorization": f"Bearer {login(*BUYER)}"}
    requests.post(f"{BASE}/cart/clear", headers=h, timeout=30)

    items = requests.get(f"{BASE}/products", params={"pincode": PIN}, headers=h, timeout=60).json()["items"]
    by_vendor = {}
    for p in items:
        vid = p.get("vendor_id")
        if not vid or vid in by_vendor or float(p.get("price") or 0) <= 0 or int(p.get("stock") or 0) < 2:
            continue
        # The list projection omits `variants`, so probe with a real add and
        # skip anything that demands a size / option.
        r = requests.post(f"{BASE}/cart/add", headers=h, json={"product_id": p["id"], "qty": 1}, timeout=30)
        if r.status_code == 200:
            by_vendor[vid] = p
    assert len(by_vendor) >= 2, f"need 2 vendors at {PIN}, got {len(by_vendor)}"
    a, b = list(by_vendor.values())[:2]
    # Drop any extra sellers so the cart is exactly the two we asserted on.
    for extra in list(by_vendor.values())[2:]:
        requests.post(f"{BASE}/cart/remove", headers=h, json={"product_id": extra["id"]}, timeout=30)

    # ---- 1. qty stepper -------------------------------------------------
    r = requests.post(f"{BASE}/cart/adjust", headers=h, json={"product_id": a["id"], "delta": 1}, timeout=30)
    assert r.status_code == 200 and r.json()["qty"] == 2, r.text
    r = requests.post(f"{BASE}/cart/adjust", headers=h, json={"product_id": a["id"], "delta": -1}, timeout=30)
    assert r.status_code == 200 and r.json()["qty"] == 1, r.text
    over = requests.post(
        f"{BASE}/cart/adjust", headers=h,
        json={"product_id": a["id"], "delta": int(a.get("stock") or 1) + 5}, timeout=30,
    )
    assert over.status_code == 400, f"stock cap not enforced: {over.status_code} {over.text}"
    print("qty stepper OK (up, down, stock cap)")

    cart = requests.get(f"{BASE}/cart", headers=h, timeout=30).json()
    total = float(cart["total"])

    # ---- 2. wallet + online combo --------------------------------------
    me = requests.get(f"{BASE}/auth/me", headers=h, timeout=30).json()
    wallet_amount = round(min(float(me.get("wallet_balance") or 0), total) / 2, 2)
    assert wallet_amount > 0, "buyer wallet empty"

    start = requests.post(
        f"{BASE}/orders/payment/start", headers=h, json={"wallet_amount": wallet_amount}, timeout=30,
    )
    assert start.status_code == 200, start.text
    s = start.json()
    assert s["is_mock"] is True, "expected mock mode (no Razorpay keys configured)"
    assert abs(s["amount"] - (total - wallet_amount)) < 0.05, s
    print(f"payment start OK — online ₹{s['amount']} + wallet ₹{wallet_amount} (order {s['razorpay_order_id']})")

    # An unverified attempt must NOT be usable.
    bad = requests.post(
        f"{BASE}/orders/checkout", headers=h,
        json={"payment_method": "wallet_online", "wallet_amount": wallet_amount,
              "payment_id": s["payment_id"], "shipping_address": ADDRESS}, timeout=60,
    )
    assert bad.status_code == 400, f"unverified payment was accepted! {bad.status_code} {bad.text}"
    print("unverified payment correctly rejected")

    v = requests.post(
        f"{BASE}/orders/payment/verify", headers=h,
        json={"payment_id": s["payment_id"], "razorpay_order_id": s["razorpay_order_id"],
              "razorpay_payment_id": "pay_MOCK_test123", "razorpay_signature": "sig_MOCK_test"}, timeout=30,
    )
    assert v.status_code == 200, v.text

    pend = requests.get(f"{BASE}/orders/payment/pending", headers=h, timeout=30).json()
    assert pend["pending"] and pend["pending"]["payment_id"] == s["payment_id"], pend
    print("verify OK, pending-resume endpoint sees the paid attempt")

    r = requests.post(
        f"{BASE}/orders/checkout", headers=h,
        json={"payment_method": "wallet_online", "wallet_amount": wallet_amount,
              "payment_id": s["payment_id"], "shipping_address": ADDRESS}, timeout=60,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert int(res["split_count"]) == 2, res
    assert abs(float(res["wallet_paid"]) - wallet_amount) < 0.05, res
    assert abs(float(res["online_paid"]) - (total - wallet_amount)) < 0.05, res
    assert float(res["cod_due"]) == 0, res
    for o in res["orders"]:
        assert float(o["cod_due"]) == 0, o
        assert o["payment_status"] == "paid", o
        assert o["paid_via"] in ("wallet", "online", "wallet_online"), o
        print("  ", o["order_number"], o["vendor_name"], "total", o["total"],
              "wallet", o["wallet_paid"], "online", o["online_paid"], o["paid_via"])
    print("wallet+online checkout OK")

    # ---- 3. single-use guard -------------------------------------------
    requests.post(f"{BASE}/cart/add", headers=h, json={"product_id": a["id"], "qty": 1}, timeout=30)
    reuse = requests.post(
        f"{BASE}/orders/checkout", headers=h,
        json={"payment_method": "online", "payment_id": s["payment_id"], "shipping_address": ADDRESS},
        timeout=60,
    )
    assert reuse.status_code == 400, f"payment reuse allowed! {reuse.status_code} {reuse.text}"
    print("payment reuse correctly blocked:", reuse.json()["detail"][:70])
    assert requests.get(f"{BASE}/orders/payment/pending", headers=h, timeout=30).json()["pending"] is None
    requests.post(f"{BASE}/cart/clear", headers=h, timeout=30)

    # ---- 4. reorder ----------------------------------------------------
    orders = requests.get(f"{BASE}/orders/me", headers=h, timeout=30).json()
    target = orders[0]
    ro = requests.post(f"{BASE}/orders/{target['id']}/reorder", headers=h, timeout=60)
    assert ro.status_code == 200, ro.text
    data = ro.json()
    assert data["added"], data
    cart2 = requests.get(f"{BASE}/cart", headers=h, timeout=30).json()
    assert cart2["count"] >= 1, cart2
    print(f"reorder OK — added {len(data['added'])}, skipped {len(data['skipped'])}, cart count {cart2['count']}")

    requests.post(f"{BASE}/cart/clear", headers=h, timeout=30)
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
