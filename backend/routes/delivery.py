"""Delivery zone endpoints (Phase 5A) — thin HTTP layer over core/delivery.py.

Both sides of the app now ask the SAME engine:
  • the vendor: "which addresses does my radius / pincode list actually
    cover?"  → GET /vendor/me/delivery-zone (+ /check?pincode=)
  • the customer: "does anybody deliver to the place I just picked?"
    → GET /delivery/check?pincode=&lat=&lng=
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.delivery import eligible_vendor_ids, pincode_centroid, vendor_covers, vendor_zone
from core.security import get_current_user

router = APIRouter(tags=["delivery"])


@router.get("/vendor/me/delivery-zone")
async def my_delivery_zone(user: Dict[str, Any] = Depends(get_current_user)):
    """The vendor's live zone, exactly as the customer filter reads it."""
    if not (user.get("is_vendor") and user.get("vendor_status") == "approved"):
        raise HTTPException(status_code=403, detail="Vendor access only")
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    zone = vendor_zone(fresh or {})
    return {
        **zone,
        "explains": {
            "everywhere": zone["mode"] == "everywhere",
            "pincode": zone["mode"] in ("pincode", "both") and bool(zone["store_pincode"]),
            "radius": zone["mode"] in ("radius", "both") and zone["radius_km"] > 0 and zone["lat"] is not None,
            "extra_pincodes": len(zone["pincodes"]),
        },
        "has_coordinates": zone["lat"] is not None and zone["lng"] is not None,
    }


@router.get("/vendor/me/delivery-zone/check")
async def my_delivery_zone_check(
    pincode: str = Query(..., min_length=5, max_length=6),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """"Do I deliver to 517641?" — same answer the customer's shop gets."""
    if not (user.get("is_vendor") and user.get("vendor_status") == "approved"):
        raise HTTPException(status_code=403, detail="Vendor access only")
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    res = await vendor_covers(fresh or {}, pincode=pincode)
    centre = await pincode_centroid(pincode)
    return {"pincode": pincode, **res, "pincode_centre": {"lat": centre[0], "lng": centre[1]} if centre else None}


@router.get("/delivery/check")
async def delivery_check(
    pincode: Optional[str] = Query(None),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    _: Dict[str, Any] = Depends(get_current_user),
):
    """How many shops can deliver to the place the customer just picked."""
    if not pincode and (lat is None or lng is None):
        raise HTTPException(status_code=400, detail="pincode or lat+lng is required")
    ids = await eligible_vendor_ids(pincode=pincode, lat=lat, lng=lng)
    return {"deliverable": len(ids) > 0, "vendor_count": len(ids), "pincode": pincode}
