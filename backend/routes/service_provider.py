"""Service Provider — availability toggle + customer location capture + phone-reveal GETs.

Extracted from server.py (2026-05-28). All small, isolated read/write
endpoints that don't touch the commission engine.

Endpoints:
  PATCH /services/me/availability       — provider toggles online/busy/offline
  PATCH /service/me                     — provider edits their own service details
  POST  /users/me/location              — customer foreground GPS capture
  GET   /services/reveals/me            — list my phone-reveal invoices
  GET   /services/reveals/invoice/{id}  — single invoice
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
    if not (user.get("is_service_provider") or user.get("service_status") == "approved"):
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
# Edit own service details (June 2026)
# ============================================================
# Approved providers can update their listing without going through the
# admin approval flow again. Only descriptive fields are mutable here —
# pincode, sub-category, languages, description, visit charges, etc. The
# parent category can be changed too (categories are the public taxonomy and
# providers may legitimately pivot e.g. "Plumbing" → "Electrical"). KYC and
# approval status are NOT editable from this endpoint.
class ServiceEditRequest(BaseModel):
    service_name: Optional[str] = None
    category_id: Optional[str] = None
    service_category: Optional[str] = None  # display name; we trust the client for the label
    service_subcategory_id: Optional[str] = None
    service_subcategory_name: Optional[str] = None
    pincode: Optional[str] = Field(default=None, min_length=6, max_length=6)
    description: Optional[str] = None
    languages: Optional[List[str]] = None
    # Jun-2026 — the provider sets his own VISIT CHARGES (what a customer
    # pays him to come and look at the job). 0 = "on request".
    visit_charge: Optional[float] = Field(default=None, ge=0, le=1000000)


@router.patch("/service/me")
async def update_my_service(
    payload: ServiceEditRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Provider-only edit of their own listing.

    Returns the refreshed `users` doc (minus password_hash) so the client
    can hydrate the apply-screen form without an extra round-trip.
    """
    if not (user.get("is_service_provider") or user.get("service_status") == "approved"):
        raise HTTPException(status_code=403, detail="Only approved service providers can edit their listing")

    # Build $set incrementally so unsupplied fields stay untouched. None
    # means "don't change"; explicit empty string means "clear it".
    sets: Dict[str, Any] = {}
    if payload.service_name is not None:
        name = payload.service_name.strip()
        if len(name) < 2:
            raise HTTPException(status_code=400, detail="Service name must be at least 2 characters")
        sets["service_name"] = name
    if payload.service_category is not None:
        sets["service_category"] = payload.service_category.strip()
    if payload.category_id is not None:
        sets["category_id"] = payload.category_id
    if payload.service_subcategory_id is not None:
        # Allow clearing by sending empty string
        sets["service_subcategory_id"] = payload.service_subcategory_id or None
    if payload.service_subcategory_name is not None:
        sets["service_subcategory_name"] = payload.service_subcategory_name or None
    if payload.pincode is not None:
        pin = payload.pincode.strip()
        if not (pin.isdigit() and len(pin) == 6):
            raise HTTPException(status_code=400, detail="Pincode must be 6 digits")
        sets["service_pincode"] = pin
    if payload.description is not None:
        sets["service_description"] = payload.description.strip() or None
    if payload.languages is not None:
        sets["service_languages"] = [x for x in payload.languages if isinstance(x, str)]
    if payload.visit_charge is not None:
        sets["service_charge"] = round(float(payload.visit_charge), 2)

    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")

    sets["service_updated_at"] = now_utc().isoformat()
    await db.users.update_one({"id": user["id"]}, {"$set": sets})

    # Mirror to the corresponding service_application doc so admin search /
    # filters reflect the updated values. Best-effort — we don't fail the
    # primary update if the mirror write hits an issue.
    try:
        mirror: Dict[str, Any] = {}
        if "service_charge" in sets:          mirror["charge"] = sets["service_charge"]
        if "service_name" in sets:           mirror["service_name"] = sets["service_name"]
        if "service_category" in sets:        mirror["service_category"] = sets["service_category"]
        if "category_id" in sets:             mirror["category_id"] = sets["category_id"]
        if "service_subcategory_id" in sets:  mirror["service_subcategory_id"] = sets["service_subcategory_id"]
        if "service_subcategory_name" in sets:mirror["service_subcategory_name"] = sets["service_subcategory_name"]
        if "service_pincode" in sets:         mirror["pincode"] = sets["service_pincode"]
        if "service_description" in sets:     mirror["description"] = sets["service_description"]
        if "service_languages" in sets:       mirror["languages"] = sets["service_languages"]
        if mirror:
            mirror["updated_at"] = sets["service_updated_at"]
            await db.service_applications.update_many(
                {"user_id": user["id"], "status": "approved"},
                {"$set": mirror},
            )
    except Exception:
        pass

    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    return {"ok": True, "user": fresh}



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
