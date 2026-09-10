"""Vendor Edit Requests — Nov 2026.

Vendors can no longer directly edit their profile (shop details, location,
delivery radius, banking).  Every change must land as a `vendor_edit_requests`
document that an admin approves or rejects.

Endpoints (mounted at /api by server.py):
  POST   /api/vendor/edit-requests             — vendor submits an edit
  GET    /api/vendor/edit-requests/mine        — vendor's own history
  GET    /api/admin/vendor-edit-requests       — admin list (all statuses)
  POST   /api/admin/vendor-edit-requests/{id}/approve
  POST   /api/admin/vendor-edit-requests/{id}/reject
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from core.security import require_admin, get_current_user
from core.utils import audit_log
from models import VendorEditRequestPayload

router = APIRouter(tags=["vendor-edit-requests"])


# Fields we allow the vendor to REQUEST changes to. Anything outside this
# whitelist is silently dropped.  This defends against a malicious client
# trying to promote themselves via a rogue payload.
ALLOWED_FIELDS = {
    "shop_name", "gst_number", "pan_number",
    "bank_name", "bank_account", "bank_ifsc",
    "description", "phone",
    "location", "pincode", "state", "district", "city",
    "store_address", "delivery_radius_km", "delivery_radius_mode",
    "delivery_available",
    # Nov 2026 — extra explicit-delivery pincode list.
    "delivery_pincodes",
}


class RejectBody(BaseModel):
    reason: Optional[str] = ""


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in doc.items() if k != "_id"}
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


async def _require_vendor(user: Dict[str, Any]) -> None:
    if not user.get("is_vendor") or user.get("vendor_status") != "approved":
        raise HTTPException(status_code=403, detail="Only approved vendors can request edits")


@router.post("/vendor/edit-requests")
async def vendor_submit_edit_request(
    payload: VendorEditRequestPayload,
    user: Dict[str, Any] = Depends(get_current_user),
):
    await _require_vendor(user)
    # Reject if the vendor already has a pending request — one at a time.
    existing = await db.vendor_edit_requests.find_one({
        "user_id": user["id"], "status": "pending",
    })
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending edit request.  Please wait for the admin to review it before submitting another.")

    # Jun 2026 (Phase 5A) — `exclude_none` used to drop explicit nulls, so a
    # vendor could never TURN OFF their km-radius or clear their extra
    # pincode list: the field was silently removed from the request and the
    # old value stayed live. `exclude_unset` keeps what the client actually
    # sent (including nulls) and still ignores fields it left out.
    body = payload.model_dump(exclude_unset=True)
    note = str(body.pop("note", "") or "")
    changes: Dict[str, Any] = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
    if not changes:
        raise HTTPException(status_code=400, detail="No changes submitted.")

    # Snapshot the CURRENT values so admin can see the diff at review time.
    fresh_user = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    current: Dict[str, Any] = {k: fresh_user.get(k) for k in changes.keys()}

    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_name": user.get("name"),
        "shop_name": fresh_user.get("shop_name"),
        "changes": changes,
        "current": current,
        "note": note,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await db.vendor_edit_requests.insert_one(doc.copy())
    # Notify admins (best-effort)
    try:
        async for a in db.users.find({"role": "admin"}, {"id": 1, "_id": 0}):
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": a["id"],
                "kind": "vendor_edit_request",
                "title": "Vendor edit request",
                "body": f"{user.get('name') or user.get('email')} requested {len(changes)} change(s).",
                "extra": {"request_id": doc["id"]},
                "read": False,
                "created_at": datetime.utcnow(),
            })
    except Exception:
        pass
    return _serialize(doc)


@router.get("/vendor/edit-requests/mine")
async def vendor_my_edit_requests(user: Dict[str, Any] = Depends(get_current_user)):
    await _require_vendor(user)
    docs = await db.vendor_edit_requests.find(
        {"user_id": user["id"]}, {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    return {"items": [_serialize(d) for d in docs]}


@router.get("/admin/vendor-edit-requests")
async def admin_list_edit_requests(
    status: Optional[str] = Query("pending", description="pending | approved | rejected | all"),
    _: Dict[str, Any] = Depends(require_admin),
):
    q: Dict[str, Any] = {}
    if status and status != "all":
        q["status"] = status
    docs = await db.vendor_edit_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"items": [_serialize(d) for d in docs], "total": len(docs)}


@router.post("/admin/vendor-edit-requests/{req_id}/approve")
async def admin_approve_edit_request(req_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    doc = await db.vendor_edit_requests.find_one({"id": req_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {doc.get('status')}")

    changes = doc.get("changes") or {}
    # Apply approved changes to the vendor's user document.
    if changes:
        user_set: Dict[str, Any] = dict(changes)
        # Jun 2026 (Phase 5A) — keep the fields the DELIVERY ENGINE reads in
        # sync. The engine matches on `store_pincode` and on flat `lat`/`lng`;
        # an approved edit used to write only `pincode` and the GeoJSON
        # `location`, so a vendor who moved their shop kept serving their OLD
        # area and the new one showed nothing.
        if changes.get("pincode"):
            user_set["store_pincode"] = changes["pincode"]
        loc = changes.get("location") or {}
        coords = (loc.get("coordinates") if isinstance(loc, dict) else None) or []
        if isinstance(coords, list) and len(coords) == 2:
            try:
                user_set["lng"] = float(coords[0])
                user_set["lat"] = float(coords[1])
            except (TypeError, ValueError):
                pass
        await db.users.update_one({"id": doc["user_id"]}, {"$set": user_set})
        # Denormalise pincode/location onto any of the vendor's products so
        # the customer-facing filter works instantly.
        if any(k in changes for k in ("pincode", "location", "delivery_radius_km", "delivery_radius_mode", "delivery_pincodes")):
            prod_updates: Dict[str, Any] = {}
            if "pincode" in changes: prod_updates["store_pincode"] = changes["pincode"]
            if "location" in changes: prod_updates["store_location"] = changes["location"]
            if "delivery_radius_km" in changes: prod_updates["delivery_radius_km"] = changes["delivery_radius_km"]
            if "delivery_radius_mode" in changes: prod_updates["delivery_radius_mode"] = changes["delivery_radius_mode"]
            if "delivery_pincodes" in changes: prod_updates["delivery_pincodes"] = changes["delivery_pincodes"]
            if prod_updates:
                await db.products.update_many({"vendor_id": doc["user_id"]}, {"$set": prod_updates})
            # Dec 2026 — Bust the products_public cascade + eligibility
            # caches so the vendor's new pincode / radius / mode takes
            # effect immediately across /products, /products/by-source,
            # and category screens.
            try:
                from routes.products_public import bust_products_public_caches
                bust_products_public_caches()
            except Exception:
                pass

    await db.vendor_edit_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "approved",
            "approved_by": admin["id"],
            "approved_by_email": admin.get("email"),
            "approved_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }},
    )
    await audit_log(admin, "vendor_edit_request.approve", {"id": req_id, "user_id": doc["user_id"], "fields": list(changes.keys())})
    # Notify the vendor
    try:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": doc["user_id"],
            "kind": "vendor_edit_approved",
            "title": "Edit request approved",
            "body": f"Your edit request ({len(changes)} change(s)) was approved.",
            "read": False,
            "created_at": datetime.utcnow(),
        })
    except Exception:
        pass
    fresh = await db.vendor_edit_requests.find_one({"id": req_id}, {"_id": 0})
    return _serialize(fresh) if fresh else {"ok": True}


@router.post("/admin/vendor-edit-requests/{req_id}/reject")
async def admin_reject_edit_request(
    req_id: str,
    body: RejectBody,
    admin: Dict[str, Any] = Depends(require_admin),
):
    doc = await db.vendor_edit_requests.find_one({"id": req_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {doc.get('status')}")
    reason = (body.reason or "").strip() or "No reason given"
    await db.vendor_edit_requests.update_one(
        {"id": req_id},
        {"$set": {
            "status": "rejected",
            "rejected_by": admin["id"],
            "rejected_by_email": admin.get("email"),
            "rejected_at": datetime.utcnow(),
            "reject_reason": reason,
            "updated_at": datetime.utcnow(),
        }},
    )
    await audit_log(admin, "vendor_edit_request.reject", {"id": req_id, "user_id": doc["user_id"], "reason": reason})
    try:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": doc["user_id"],
            "kind": "vendor_edit_rejected",
            "title": "Edit request rejected",
            "body": f"Your edit request was rejected. Reason: {reason}",
            "read": False,
            "created_at": datetime.utcnow(),
        })
    except Exception:
        pass
    fresh = await db.vendor_edit_requests.find_one({"id": req_id}, {"_id": 0})
    return _serialize(fresh) if fresh else {"ok": True}
