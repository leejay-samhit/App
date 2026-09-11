"""
Seed helper for iter 58 frontend testing.
Adds 3 root shop categories so /shop-category/<name> has siblings for
the swipe-past-end behaviour to be observable.  Also has a --cleanup
mode that removes only categories we created (identified by ITER58_* prefix).
"""
import os
import sys
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://slangcart-tracking.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "support@slangcart.com"
ADMIN_PW = "3)Ywxtic"

CATS = ["ITER58_Electronics", "ITER58_Fashion", "ITER58_Home"]


def admin_token():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=15)
    r.raise_for_status()
    return r.json().get("token") or r.json().get("access_token")


def seed():
    tok = admin_token()
    h = {"Authorization": f"Bearer {tok}"}
    created = []
    for c in CATS:
        r = requests.post(f"{BASE}/api/admin/shop-categories", json={"name": c}, headers=h, timeout=15)
        if r.status_code in (200, 201):
            created.append(r.json())
            print(f"seeded {c}")
        else:
            print(f"seed {c} → {r.status_code} {r.text[:200]}")
    return created


def cleanup():
    tok = admin_token()
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{BASE}/api/shop-categories", timeout=15)
    for item in (r.json().get("items") or []):
        if item.get("name", "").startswith("ITER58_"):
            d = requests.delete(f"{BASE}/api/admin/shop-categories/{item['id']}", headers=h, timeout=15)
            print(f"deleted {item['name']} → {d.status_code}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        cleanup()
    else:
        seed()
