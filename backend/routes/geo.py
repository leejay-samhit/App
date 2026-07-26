"""Geo — Nov 2026.

Public endpoints for location resolution used by the customer Shop tab.
Uses OpenStreetMap Nominatim as the free reverse/forward-geocode source.

Endpoints (mounted at /api by server.py):
  GET  /api/geo/search?q=<place-name>   — forward geocode
  GET  /api/geo/reverse?lat=&lng=       — reverse geocode
  GET  /api/geo/pincode/{pincode}       — quick lookup from local pincodes CSV

Nominatim usage policy — max 1 rps, mandatory User-Agent.  We enforce
both here so we don't get banned.
"""
from __future__ import annotations
import time
import logging
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException, Query

from core.db import db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["geo"])

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "Slangcart/1.0 (contact: support@slangcart.com)"
# Simple 1 rps throttle — Nominatim's usage policy.
_last_call_ts: float = 0.0
_MIN_INTERVAL = 1.05


async def _throttle() -> None:
    global _last_call_ts
    now = time.time()
    delta = now - _last_call_ts
    if delta < _MIN_INTERVAL:
        # httpx is async — a plain sleep is fine here (short).
        import asyncio
        await asyncio.sleep(_MIN_INTERVAL - delta)
    _last_call_ts = time.time()


def _shape_nominatim(r: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Nominatim response into a compact place object."""
    addr = r.get("address") or {}
    return {
        "display_name": r.get("display_name") or "",
        "lat": float(r.get("lat") or 0),
        "lng": float(r.get("lon") or 0),
        "pincode": addr.get("postcode") or "",
        "area": addr.get("suburb") or addr.get("village") or addr.get("town") or addr.get("city_district") or addr.get("neighbourhood") or "",
        "city": addr.get("city") or addr.get("town") or addr.get("village") or "",
        "district": addr.get("state_district") or addr.get("county") or "",
        "state": addr.get("state") or "",
        "country": addr.get("country") or "",
        "type": r.get("type") or r.get("class") or "",
    }


@router.get("/geo/search")
async def geo_search(
    q: str = Query(..., min_length=2, description="Place name to search"),
    limit: int = Query(5, ge=1, le=10),
):
    """Forward geocode via Nominatim.  Falls back to the local pincode
    catalogue for pure-digit queries so 6-digit pincode look-ups work
    even when Nominatim is unreachable."""
    q = q.strip()
    # Pincode shortcut — hit the local catalogue first (fast, offline-safe)
    if q.isdigit() and 5 <= len(q) <= 6:
        row = await db.pincodes.find_one({"pincode": q}, {"_id": 0})
        if row:
            return {"items": [{
                "display_name": f"{row.get('office_name') or q}, {row.get('district','')}, {row.get('state','')}",
                "lat": float(row.get("lat") or 0),
                "lng": float(row.get("lng") or 0),
                "pincode": q,
                "area": row.get("office_name") or "",
                "city": row.get("district") or "",
                "district": row.get("district") or "",
                "state": row.get("state") or "",
                "country": "India",
                "type": "pincode",
            }]}
    # ── Remote Nominatim call ──
    await _throttle()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{NOMINATIM_BASE}/search",
                params={
                    "q": q,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "countrycodes": "in",  # bias to India
                    "limit": limit,
                },
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"geo/search failed: {e}")
        raise HTTPException(status_code=502, detail="Location search is temporarily unavailable. Please try again in a moment.")
    return {"items": [_shape_nominatim(x) for x in data]}


@router.get("/geo/reverse")
async def geo_reverse(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    await _throttle()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                f"{NOMINATIM_BASE}/reverse",
                params={
                    "lat": lat, "lon": lng,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "zoom": 14,  # neighbourhood / suburb precision
                },
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"geo/reverse failed: {e}")
        raise HTTPException(status_code=502, detail="Location lookup unavailable")
    return _shape_nominatim(data)


@router.get("/geo/pincode/{pincode}")
async def geo_pincode(pincode: str):
    if not (pincode.isdigit() and 5 <= len(pincode) <= 6):
        raise HTTPException(status_code=400, detail="Invalid pincode")
    row = await db.pincodes.find_one({"pincode": pincode}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Pincode not found")
    return {
        "pincode": pincode,
        "area": row.get("office_name") or "",
        "district": row.get("district") or "",
        "state": row.get("state") or "",
        "lat": float(row.get("lat") or 0) or None,
        "lng": float(row.get("lng") or 0) or None,
    }
