"""Service Provider — availability toggle + customer location capture + phone-reveal GETs.

Extracted from server.py (2026-05-28). All small, isolated read/write
endpoints that don't touch the commission engine.

Endpoints:
  PATCH /services/me/availability       — provider toggles online/busy/offline
  POST  /users/me/location              — customer foreground GPS capture
  GET   /services/reveals/me            — list my phone-reveal invoices
  GET   /services/reveals/invoice/{id}  — single invoice
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.security import get_current_user
from core.utils import now_utc
from models import ProviderAvailabilityRequest, UserLocationUpdate


router = APIRouter()


_AVAIL_STATUSES = {"available", "busy", "offline"}


# ============================================================
# Provider Availability (Available / Busy / Offline)
# ============================================================
@router.patch("/services/me/availability")
async def update_my_availability(
    payload: ProviderAvailabilityRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Provider toggles their own visibility status. Independent of location
    sharing — this is the green/yellow/gray dot users see next to them.
    """
    if not user.get("is_service_provider"):
        raise HTTPException(status_code=403, detail="Only service providers can set availability")
    status = (payload.status or "").lower().strip()
    if status not in _AVAIL_STATUSES:
        raise HTTPException(status_code=400, detail="status must be one of: available, busy, offline")
    ts = now_utc().isoformat()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"availability_status": status, "availability_updated_at": ts}},
    )
    return {"ok": True, "availability_status": status, "availability_updated_at": ts}


# ============================================================
# Customer Location Capture (foreground GPS — no background tracking)
# ============================================================
@router.post("/users/me/location")
async def save_user_location(
    payload: UserLocationUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Persist a single foreground GPS sample. Frontend should call this
    only when the user explicitly taps "Use my location" — never on app
    resume / background.
    """
    try:
        lat = float(payload.latitude)
        lng = float(payload.longitude)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid latitude / longitude")
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="Latitude or longitude out of range")
    ts = now_utc().isoformat()
    update: Dict[str, Any] = {
        "user_location": {"type": "Point", "coordinates": [lng, lat]},
        "user_location_lat": lat,
        "user_location_lng": lng,
        "user_location_updated_at": ts,
    }
    if payload.accuracy_m is not None:
        update["user_location_accuracy_m"] = float(payload.accuracy_m)
    if payload.address:  update["address"] = payload.address.strip()[:300]
    if payload.city:     update["city"]    = payload.city.strip()[:80]
    if payload.state:    update["state"]   = payload.state.strip()[:80]
    if payload.pincode:  update["pincode"] = payload.pincode.strip()[:10]
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    fresh = await db.users.find_one(
        {"id": user["id"]},
        {"_id": 0, "user_location_lat": 1, "user_location_lng": 1, "address": 1,
         "city": 1, "state": 1, "pincode": 1, "user_location_updated_at": 1},
    )
    return {"ok": True, "location": fresh}


# ============================================================
# Phone-reveal invoice history (read-only)
# The reveal-phone POST itself stays in server.py for now because it
# transitively touches the commission engine + wallet ledger.
# ============================================================
@router.get("/services/reveals/me")
async def my_phone_reveals(user: Dict[str, Any] = Depends(get_current_user)):
    """User's phone-reveal invoice history."""
    items = await db.phone_reveal_invoices.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return {"items": items, "total": len(items)}


@router.get("/services/reveals/invoice/{invoice_id}")
async def get_phone_reveal_invoice(
    invoice_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    inv = await db.phone_reveal_invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("user_id") != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not allowed")
    return inv
