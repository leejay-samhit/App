"""Delivery zoning — ONE engine for "can this vendor deliver here?" (Phase 5A).

Before this module the same question was answered in three different places
with three slightly different rules:

  • the vendor's own Delivery Radius screen (km circle + entire-pincode +
    extra pincodes),
  • the customer "Deliver to" product filter in routes/products_public.py,
  • the checkout / cart guards.

The visible symptom the owner reported: a pincode that the vendor's radius map
clearly captures showed NO products for a customer who picked that pincode,
because the customer-side filter could only do the km-radius test when it had
raw GPS coordinates. Pick a delivery pincode by hand (no GPS fix at that
address) and the radius rule was silently skipped.

The engine below is now the only implementation. It answers the question from
whatever signal is available:

  1. `pincode` == vendor.store_pincode  and the vendor's mode allows pincode
     delivery (`pincode` / `both`, or legacy docs with no mode set)
  2. `pincode` ∈ vendor.delivery_pincodes  (explicit allow-list, any mode)
  3. the customer's coordinates are inside vendor.delivery_radius_km
  4. NEW — no coordinates? we resolve the PINCODE's centroid (geocoded once
     and cached on the pincodes row) and run the very same radius test, so the
     customer side and the vendor's map agree.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional, Set, Tuple

import httpx

from core.db import db

logger = logging.getLogger(__name__)

EARTH_RADIUS_KM = 6371.0088

# Jun-2026 owner request — a vendor can ask the admin for "Everyone", i.e.
# ship anywhere in India. Approved vendors in this mode clear the zone test
# for every customer, regardless of pincode or distance. Cash on Delivery is
# refused for those far-away orders (checkout pays online / by wallet) because
# nobody is physically near enough to collect cash.
EVERYWHERE = "everywhere"
LOCAL_MODES = ("pincode", "radius", "both")

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "Slangcart/1.0 (contact: support@slangcart.com)"
_last_geocode_ts: float = 0.0
_GEOCODE_MIN_INTERVAL = 1.05  # Nominatim policy: 1 request / second


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2) - math.radians(lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def vendor_zone(v: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a vendor USER document into a delivery zone.

    Coordinates may live either as flat `lat`/`lng` or inside the GeoJSON
    `location` field (older / edit-request writes) — read both so a vendor who
    moved their shop is never treated as location-less.
    """
    lat = v.get("lat")
    lng = v.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        coords = ((v.get("location") or {}).get("coordinates") or [None, None])
        if isinstance(coords, list) and len(coords) == 2:
            lng, lat = coords[0], coords[1]
    try:
        radius = float(v.get("delivery_radius_km") or 0)
    except (TypeError, ValueError):
        radius = 0.0
    pins = v.get("delivery_pincodes") or []
    return {
        "lat": float(lat) if isinstance(lat, (int, float)) else None,
        "lng": float(lng) if isinstance(lng, (int, float)) else None,
        "radius_km": radius,
        # An unset mode is legacy = "my own pincode only".
        "mode": (v.get("delivery_radius_mode") or "pincode"),
        "store_pincode": str(v.get("store_pincode") or v.get("pincode") or "") or None,
        "pincodes": [str(p).strip() for p in pins if str(p).strip()],
        "delivery_available": v.get("delivery_available", True),
    }


async def _throttle_geocode() -> None:
    global _last_geocode_ts
    import asyncio
    delta = time.time() - _last_geocode_ts
    if delta < _GEOCODE_MIN_INTERVAL:
        await asyncio.sleep(_GEOCODE_MIN_INTERVAL - delta)
    _last_geocode_ts = time.time()


async def pincode_centroid(pincode: str) -> Optional[Tuple[float, float]]:
    """(lat, lng) for the centre of an Indian pincode.

    Read from the local `pincodes` catalogue when it already carries
    coordinates; otherwise geocoded ONCE via Nominatim and written back onto
    the row, so the radius test costs nothing from then on.
    """
    pin = str(pincode or "").strip()
    if not (pin.isdigit() and 5 <= len(pin) <= 6):
        return None
    row = await db.pincodes.find_one({"pincode": pin}, {"_id": 0, "lat": 1, "lng": 1, "geo_failed_at": 1})
    if row:
        lat, lng = row.get("lat"), row.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and (lat or lng):
            return float(lat), float(lng)
        # Don't hammer Nominatim for a pincode it couldn't resolve — retry daily.
        failed_at = row.get("geo_failed_at")
        if isinstance(failed_at, (int, float)) and (time.time() - failed_at) < 86400:
            return None
    try:
        await _throttle_geocode()
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{NOMINATIM_BASE}/search",
                params={"postalcode": pin, "country": "India", "format": "jsonv2", "limit": 1},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            )
            r.raise_for_status()
            data = r.json() or []
    except Exception as e:  # network / rate limit — never break the request
        logger.warning(f"pincode_centroid({pin}) geocode failed: {e}")
        data = []
    if not data:
        await db.pincodes.update_one({"pincode": pin}, {"$set": {"geo_failed_at": time.time()}}, upsert=True)
        return None
    lat = float(data[0].get("lat") or 0)
    lng = float(data[0].get("lon") or 0)
    if not lat and not lng:
        return None
    await db.pincodes.update_one(
        {"pincode": pin},
        {"$set": {"lat": lat, "lng": lng, "geo_source": "nominatim"}, "$unset": {"geo_failed_at": ""}},
        upsert=True,
    )
    return lat, lng


def zone_covers_pincode(zone: Dict[str, Any], pincode: Optional[str]) -> bool:
    """Rules 1 + 2 — the pure, coordinate-free part of the test."""
    if zone["mode"] == EVERYWHERE:
        return True
    if not pincode:
        return False
    pin = str(pincode).strip()
    if pin in zone["pincodes"]:
        return True
    if zone["store_pincode"] and pin == zone["store_pincode"] and zone["mode"] in ("pincode", "both"):
        return True
    return False


def zone_covers_point(zone: Dict[str, Any], lat: Optional[float], lng: Optional[float]) -> bool:
    """Rule 3 — km radius around the shop."""
    if lat is None or lng is None:
        return False
    if zone["lat"] is None or zone["lng"] is None or zone["radius_km"] <= 0:
        return False
    if zone["mode"] not in ("radius", "both"):
        return False
    return haversine_km(lat, lng, zone["lat"], zone["lng"]) <= zone["radius_km"]


async def vendor_covers(
    vendor: Dict[str, Any],
    pincode: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> Dict[str, Any]:
    """Full check for ONE vendor. Returns {covered, reason, distance_km}."""
    zone = vendor_zone(vendor)
    if zone["delivery_available"] is False:
        return {"covered": False, "reason": "delivery_off", "distance_km": None}
    if zone["mode"] == EVERYWHERE:
        return {"covered": True, "reason": EVERYWHERE, "distance_km": None}
    if zone_covers_pincode(zone, pincode):
        return {"covered": True, "reason": "pincode", "distance_km": None}
    if zone_covers_point(zone, lat, lng):
        d = haversine_km(lat, lng, zone["lat"], zone["lng"])  # type: ignore[arg-type]
        return {"covered": True, "reason": "radius", "distance_km": round(d, 2)}
    # Rule 4 — no usable coordinates, but the radius may still reach this
    # pincode's centre. This is the fix for "the vendor's map shows this
    # pincode but the customer sees nothing".
    if (lat is None or lng is None) and pincode and zone["radius_km"] > 0 and zone["mode"] in ("radius", "both"):
        centre = await pincode_centroid(pincode)
        if centre and zone_covers_point(zone, centre[0], centre[1]):
            d = haversine_km(centre[0], centre[1], zone["lat"], zone["lng"])  # type: ignore[arg-type]
            return {"covered": True, "reason": "radius_pincode_centre", "distance_km": round(d, 2)}
    return {"covered": False, "reason": "out_of_zone", "distance_km": None}


async def vendor_covers_locally(
    vendor: Dict[str, Any],
    pincode: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> bool:
    """Would this vendor reach the customer WITHOUT the "Everyone" flag?

    Checkout uses this to tell a nearby order from a ship-anywhere one:
    an "Everyone" vendor still does normal Cash on Delivery inside his own
    pincode / km radius, and online-only beyond it.
    """
    zone = vendor_zone(vendor)
    if zone["mode"] != EVERYWHERE:
        return True
    local = dict(vendor)
    local["delivery_radius_mode"] = "both"
    res = await vendor_covers(local, pincode=pincode, lat=lat, lng=lng)
    return bool(res.get("covered"))


async def eligible_vendor_ids(
    pincode: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> Set[str]:
    """Every approved vendor that can deliver to this customer.

    One Mongo pass over approved vendors, then the shared rules above — so
    the customer filter, the vendor's own zone preview and checkout can never
    disagree again.
    """
    ids: Set[str] = set()
    if not pincode and (lat is None or lng is None):
        return ids

    centre: Optional[Tuple[float, float]] = None
    if (lat is None or lng is None) and pincode:
        centre = await pincode_centroid(pincode)

    projection = {
        "_id": 0, "id": 1, "lat": 1, "lng": 1, "location": 1,
        "delivery_radius_km": 1, "delivery_radius_mode": 1,
        "delivery_pincodes": 1, "store_pincode": 1, "pincode": 1,
        "delivery_available": 1,
    }
    async for v in db.users.find({"is_vendor_approved": True}, projection):
        zone = vendor_zone(v)
        if zone["delivery_available"] is False:
            continue
        if zone_covers_pincode(zone, pincode):
            ids.add(v["id"])
            continue
        if zone_covers_point(zone, lat, lng):
            ids.add(v["id"])
            continue
        if centre and zone_covers_point(zone, centre[0], centre[1]):
            ids.add(v["id"])
    return ids
