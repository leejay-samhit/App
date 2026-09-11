#!/usr/bin/env python3
"""Seed 3 shop categories via admin API so /shop-categories/tree has
siblings for the swipe navigation test.  Records the created ids in
/tmp/iter56_seeded_cats.json so the cleanup step can delete them.

Also places a fresh 2-vendor split checkout (Vendor One Widget +
Vendor Two Gadget) so the group order header can be verified.
"""
import json
import os
import sys
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")

def login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]

def h(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}

def main():
    admin_t = login("support@slangcart.com", "3)Ywxtic")

    seeded = []
    # Ensure names are distinct + easy to spot
    for name in ("ITER56_Alpha", "ITER56_Beta", "ITER56_Gamma"):
        r = requests.post(f"{BASE}/api/admin/shop-categories",
                          json={"name": name, "active": True},
                          headers=h(admin_t), timeout=15)
        if r.status_code == 200:
            seeded.append(r.json())
            print(f"[+] {name} → {r.json().get('id')}")
        elif r.status_code == 409:
            # Already exists — fetch existing id
            all_r = requests.get(f"{BASE}/api/admin/shop-categories", headers=h(admin_t))
            for c in (all_r.json().get("items") or []):
                if c.get("name") == name:
                    seeded.append(c)
                    print(f"[=] {name} (existed) → {c.get('id')}")
        else:
            print(f"[!] {name} failed: {r.status_code} {r.text[:200]}")

    with open("/tmp/iter56_seeded_cats.json", "w") as f:
        json.dump(seeded, f)

    # Place a 2-vendor checkout
    buyer_t = login("testbuyer@test.com", "Test@1234")
    # Clear cart
    requests.post(f"{BASE}/api/cart/clear", headers=h(buyer_t))
    for pid in ("9c6bb05d-eecc-4637-8489-466f1e4f0288",
                "409e52af-3660-4bb3-92b4-e418a7f4a5aa"):
        r = requests.post(f"{BASE}/api/cart/add", json={"product_id": pid, "qty": 1}, headers=h(buyer_t))
        print(f"cart add {pid}: {r.status_code}")

    r = requests.post(f"{BASE}/api/orders/checkout", json={
        "shipping_address": {
            "name": "Test Buyer",
            "phone": "9999900000",
            "line1": "Test line",
            "city": "Srikalahasti",
            "state": "Andhra Pradesh",
            "pincode": "517644",
        },
        "payment_method": "wallet_cod",
        "wallet_amount": 0,
    }, headers=h(buyer_t), timeout=30)
    print("checkout:", r.status_code)
    if r.status_code == 200:
        body = r.json()
        print(f"  group_id={body.get('group_id')} split_count={body.get('split_count')} grand_total={body.get('grand_total')}")
        for o in body.get("orders", []):
            print(f"  → {o.get('order_number')} vendor={o.get('vendor_name')} total={o.get('total')} cod_due={o.get('cod_due')}")
    else:
        print(r.text[:400])

if __name__ == "__main__":
    main()
