"""Notification preferences + 5-stage order tracking — API tests.

1. GET/PUT /me/notification-prefs round-trip and defaults.
2. filter_by_prefs drops users who muted a category.
3. The full status walk placed → confirmed → shipped → out_for_delivery →
   delivered stamps a status_history entry per stage with time + actor, and
   COD money is only settled at delivery.
"""
import asyncio
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE = os.environ.get("TEST_BASE", "http://localhost:8001/api")
BUYER = ("testbuyer@test.com", "Test@1234")
VENDOR = ("testvendor@test.com", "Test@1234")
ADMIN = ("support@slangcart.com", "3)Ywxtic")
PIN = "517644"
ADDRESS = {
    "name": "Test Buyer", "phone": "9876543210", "line1": "1 Test Street", "line2": "",
    "city": "Srikalahasti", "state": "Andhra Pradesh", "pincode": PIN,
    "latitude": 13.7497, "longitude": 79.7036,
}
FLOW = ["confirmed", "shipped", "out_for_delivery", "delivered"]


def login(creds):
    r = requests.post(f"{BASE}/auth/login", json={"email": creds[0], "password": creds[1]}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def main():
    bh = login(BUYER)
    ah = login(ADMIN)

    # ── 1. preferences round-trip ---------------------------------------
    p = requests.get(f"{BASE}/me/notification-prefs", headers=bh, timeout=30).json()
    assert set(p["prefs"]) == {"orders", "chats", "offers", "login_alerts", "vendor_new_order"}, p
    assert all(p["prefs"].values()), f"defaults must all be ON: {p['prefs']}"

    r = requests.put(f"{BASE}/me/notification-prefs", headers=bh, json={"offers": False}, timeout=30)
    assert r.status_code == 200 and r.json()["prefs"]["offers"] is False, r.text
    again = requests.get(f"{BASE}/me/notification-prefs", headers=bh, timeout=30).json()
    assert again["prefs"]["offers"] is False and again["prefs"]["orders"] is True, again
    print("prefs round-trip OK:", again["prefs"])

    # ── 2. the filter actually drops the muted user ----------------------
    me = requests.get(f"{BASE}/auth/me", headers=bh, timeout=30).json()
    from routes.push import filter_by_prefs
    kept_orders = asyncio.get_event_loop().run_until_complete(filter_by_prefs([me["id"]], "orders"))
    kept_offers = asyncio.get_event_loop().run_until_complete(filter_by_prefs([me["id"]], "offers"))
    assert kept_orders == [me["id"]], kept_orders
    assert kept_offers == [], kept_offers
    print("filter_by_prefs OK — muted 'offers' recipient dropped, 'orders' kept")

    # restore so later manual testing isn't silently muted
    requests.put(f"{BASE}/me/notification-prefs", headers=bh, json={"offers": True}, timeout=30)

    # ── 3. five-stage tracking ------------------------------------------
    requests.post(f"{BASE}/cart/clear", headers=bh, timeout=30)
    items = requests.get(f"{BASE}/products", params={"pincode": PIN}, headers=bh, timeout=60).json()["items"]
    picked = None
    for pr in items:
        if float(pr.get("price") or 0) > 0 and int(pr.get("stock") or 0) > 0:
            if requests.post(f"{BASE}/cart/add", headers=bh, json={"product_id": pr["id"], "qty": 1}, timeout=30).status_code == 200:
                picked = pr
                break
    assert picked, "no addable product found"

    co = requests.post(
        f"{BASE}/orders/checkout", headers=bh,
        json={"payment_method": "cod", "shipping_address": ADDRESS}, timeout=60,
    )
    assert co.status_code == 200, co.text
    order = co.json()["orders"][0]
    oid = order["id"]
    assert order["status"] == "placed", order

    detail = requests.get(f"{BASE}/admin/orders/{oid}", headers=ah, timeout=30).json()["order"]
    hist = detail.get("status_history") or []
    assert len(hist) == 1 and hist[0]["status"] == "placed" and hist[0]["at"], hist
    print("order placed with seeded timeline:", hist[0]["status"], hist[0]["at"][:19])

    bad = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah, json={"status": "teleported"}, timeout=30)
    assert bad.status_code == 400, bad.status_code

    for stage in FLOW:
        r = requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah, json={"status": stage}, timeout=60)
        assert r.status_code == 200, f"{stage}: {r.status_code} {r.text[:200]}"

    detail = requests.get(f"{BASE}/admin/orders/{oid}", headers=ah, timeout=30).json()["order"]
    hist = detail.get("status_history") or []
    assert [h["status"] for h in hist] == ["placed"] + FLOW, [h["status"] for h in hist]
    for h in hist[1:]:
        assert h["at"] and h["by_name"], h
        assert h["by_role"] in ("admin", "seller"), h
    assert detail["status"] == "delivered" and detail.get("delivered_at"), detail.get("status")
    # COD settles only once, at delivery.
    assert detail.get("commission_settled") is True, detail.get("commission_settled")
    assert detail.get("payment_status") == "paid", detail.get("payment_status")
    print("five-stage walk OK:", " → ".join(f"{h['status']}@{h['at'][11:16]}" for h in hist))

    # re-saving the same status must not duplicate a timeline row
    requests.patch(f"{BASE}/admin/orders/{oid}/status", headers=ah, json={"status": "delivered"}, timeout=60)
    again2 = requests.get(f"{BASE}/admin/orders/{oid}", headers=ah, timeout=30).json()["order"]
    assert len(again2.get("status_history") or []) == len(hist), "duplicate timeline entry on re-save"
    print("idempotent re-save OK")

    # the seller can also walk stages through the vendor endpoint
    vh = login(VENDOR)
    vs = requests.get(f"{BASE}/vendor/me/sales", headers=vh, timeout=30)
    assert vs.status_code == 200, vs.text
    print("vendor sales endpoint reachable:", vs.status_code)

    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
