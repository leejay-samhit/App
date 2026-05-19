"""Pincode lookup — Admin endpoints for India pincode + distributor area mapping.
Extracted from server.py during Phase 2B refactor.

Endpoints (mounted at /api):
  GET  /admin/pincodes/search       — autocomplete by pin / district / state
  GET  /admin/pincodes/in-region    — bulk fetch by state and/or district
  GET  /admin/pincodes/{pin}        — single pincode with current assignment

Note: route order matters — `/in-region` MUST precede `/{pin}` so FastAPI
doesn't capture it as a path param.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from core.db import db
from core.security import require_admin


router = APIRouter(tags=["pincodes"])


async def _attach_assignments(rows: list[Dict[str, Any]]) -> None:
    """Mutates rows in-place, adding `assigned_to` dict (or None)."""
    pins = [r["pincode"] for r in rows]
    if not pins:
        return
    assignments = await db.distributor_assignments.find(
        {"pincode": {"$in": pins}}, {"_id": 0},
    ).to_list(len(pins))
    amap = {a["pincode"]: a for a in assignments}
    for r in rows:
        a = amap.get(r["pincode"])
        r["assigned_to"] = (
            {
                "distributor_id": a["distributor_id"],
                "distributor_name": a.get("distributor_name"),
                "distributor_email": a.get("distributor_email"),
            }
            if a
            else None
        )


@router.get("/admin/pincodes/search")
async def admin_pincode_search(
    q: str = "",
    state: Optional[str] = None,
    limit: int = 50,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Lookup pincodes for autocomplete in the admin Area-Mapping screen.
    Matches pincode prefix, district name, or state name (case-insensitive).
    Returns up to `limit` results (capped at 200)."""
    limit = max(1, min(int(limit or 50), 200))
    q = (q or "").strip()
    filt: Dict[str, Any] = {}
    if state:
        filt["state"] = {"$regex": f"^{re.escape(state)}$", "$options": "i"}
    if q:
        if q.isdigit():
            filt["pincode"] = {"$regex": f"^{q}", "$options": "i"}
        else:
            rgx = {"$regex": re.escape(q), "$options": "i"}
            filt["$or"] = [
                {"district": rgx},
                {"state": rgx},
                {"region": rgx},
                {"office": rgx},
            ]
    rows = await db.pincodes.find(filt, {"_id": 0}).sort("pincode", 1).to_list(limit)
    await _attach_assignments(rows)
    return {"items": rows, "total": len(rows)}


@router.get("/admin/pincodes/in-region")
async def admin_pincodes_in_region(
    state: Optional[str] = None,
    district: Optional[str] = None,
    limit: int = 5000,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Return all pincodes belonging to a state and/or district. Used by the
    admin Area-Mapping screen for one-click 'assign whole state/district'.
    NOTE: This MUST be declared BEFORE /admin/pincodes/{pin}."""
    if not state and not district:
        raise HTTPException(status_code=400, detail="state or district is required")
    limit = max(1, min(int(limit or 5000), 10000))
    filt: Dict[str, Any] = {}
    if state:
        filt["state"] = {"$regex": f"^{re.escape(state)}$", "$options": "i"}
    if district:
        filt["district"] = {"$regex": f"^{re.escape(district)}$", "$options": "i"}
    rows = await db.pincodes.find(filt, {"_id": 0}).sort("pincode", 1).to_list(limit)
    await _attach_assignments(rows)
    return {"items": rows, "total": len(rows)}


@router.get("/admin/pincodes/{pin}")
async def admin_pincode_get(
    pin: str,
    _: Dict[str, Any] = Depends(require_admin),
):
    p = await db.pincodes.find_one({"pincode": pin}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Pincode not found")
    a = await db.distributor_assignments.find_one({"pincode": pin}, {"_id": 0})
    p["assigned_to"] = a if a else None
    return p
