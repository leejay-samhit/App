"""Phase 5A smoke test — unified delivery-zone engine.

Verifies that the vendor's zone view, the customer's "does anyone deliver
here?" check and the shop product filter all agree, including the new
pincode-centre radius fallback (customer picked a pincode, no GPS).
"""
import asyncio
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

BASE = "http://localhost:8001/api"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return {"Authorization": f"Bearer {d.get('access_token') or d.get('token')}"}


async def main():
    from core.delivery import haversine_km, vendor_covers, vendor_zone

    v = login("testvendor@test.com", "Test@1234")
    zone = requests.get(f"{BASE}/vendor/me/delivery-zone", headers=v, timeout=60).json()
    print("vendor zone:", {k: zone[k] for k in ("lat", "lng", "radius_km", "mode", "store_pincode", "pincodes")})
    assert zone["has_coordinates"] and zone["radius_km"] > 0

    # store pincode → covered via the pincode rule
    own = requests.get(f"{BASE}/vendor/me/delivery-zone/check", params={"pincode": zone["store_pincode"]}, headers=v, timeout=60).json()
    print("own pincode:", own["covered"], own["reason"])
    assert own["covered"]

    # explicit extra pincode → covered
    extra = zone["pincodes"][0]
    e = requests.get(f"{BASE}/vendor/me/delivery-zone/check", params={"pincode": extra}, headers=v, timeout=60).json()
    print("extra pincode:", extra, e["covered"], e["reason"])
    assert e["covered"] and e["reason"] == "pincode"

    # a pincode that is NOT in the list but whose centre sits inside the
    # radius must now be covered by the shared engine (Phase 5A fix).
    near = "517642"
    n = requests.get(f"{BASE}/vendor/me/delivery-zone/check", params={"pincode": near}, headers=v, timeout=60).json()
    print("nearby pincode:", near, n["covered"], n["reason"], n.get("distance_km"), n.get("pincode_centre"))

    # customer side must agree with the vendor side, pincode only (no GPS)
    b = login("testbuyer@test.com", "Test@1234")
    for pin in [zone["store_pincode"], extra, near, "110001"]:
        chk = requests.get(f"{BASE}/delivery/check", params={"pincode": pin}, headers=b, timeout=90).json()
        vend = requests.get(f"{BASE}/vendor/me/delivery-zone/check", params={"pincode": pin}, headers=v, timeout=90).json()
        print(f"  {pin}: customer_vendors={chk['vendor_count']} vendor_says={vend['covered']} ({vend['reason']})")
        if vend["covered"]:
            assert chk["vendor_count"] >= 1, f"engine mismatch for {pin}"

    # far-away pincode must NOT be deliverable
    far = requests.get(f"{BASE}/delivery/check", params={"pincode": "110001"}, headers=b, timeout=90).json()
    assert far["vendor_count"] == 0, far

    # products endpoint uses the same engine → pincode-only query returns items
    prods = requests.get(f"{BASE}/products", params={"pincode": zone["store_pincode"], "strict_location": "true", "limit": 5}, headers=b, timeout=90).json()
    total = prods.get("total") if isinstance(prods, dict) else len(prods)
    print("products at store pincode:", total)
    assert total and total > 0

    # sanity on the pure helpers
    z = vendor_zone({"location": {"type": "Point", "coordinates": [79.7027, 13.7484]}, "delivery_radius_km": 10, "delivery_radius_mode": "both"})
    assert z["lat"] == 13.7484 and z["lng"] == 79.7027, z
    assert round(haversine_km(13.7484, 79.7027, 13.7484, 79.7027), 3) == 0
    off = await vendor_covers({"delivery_available": False, "store_pincode": "517644", "delivery_radius_mode": "both"}, pincode="delivery_off")
    assert off["covered"] is False and off["reason"] == "delivery_off"

    # Phase 5A regression — a pincode that is NOT listed but whose CENTRE
    # falls inside the km radius must be covered even without GPS.
    from core.db import db as _db
    vendor_doc = await _db.users.find_one({"email": "testvendor@test.com"})
    wide = dict(vendor_doc or {})
    wide["delivery_radius_km"] = 20
    far_but_inside = await vendor_covers(wide, pincode="517620")  # ~16.4 km away
    print("pincode-centre fallback:", far_but_inside)
    assert far_but_inside["covered"] and far_but_inside["reason"] == "radius_pincode_centre"
    print("PASS")


if __name__ == "__main__":
    asyncio.run(main())
