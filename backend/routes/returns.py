"""Product Returns · Refunds — Phase 2 (Jun-2026).

Customer requests, seller reviews, money moves, stock comes back. All maths
lives in `core/returns.py`; these endpoints only authorise and call it, so
App, Customer Web, Vendor Web and Admin Web share one calculator.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core import returns as rt
from core.db import db
from core.security import get_current_user, require_admin
from core.utils import now_utc

router = APIRouter()


async def require_vendor(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not (user.get("is_vendor") and user.get("is_vendor_approved")):
        raise HTTPException(status_code=403, detail="Vendor access required")
    return user


async def _injected():
    """Late-bound server helpers (avoids a module-level import cycle)."""
    from server import credit_admin_bucket, _create_notification
    return credit_admin_bucket, _create_notification


class ReturnLine(BaseModel):
    product_id: str
    variant_id: Optional[str] = None
    qty: int = Field(..., ge=1, le=999)


class ReturnCreate(BaseModel):
    order_id: str
    items: List[ReturnLine]
    reason: str = Field(..., min_length=3, max_length=200)
    comments: Optional[str] = Field(default="", max_length=1000)


class DecisionBody(BaseModel):
    note: Optional[str] = Field(default="", max_length=500)


# ── Customer ───────────────────────────────────────────────────────────

@router.get("/orders/{order_id}/return-state")
async def order_return_state(order_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Is this order returnable, until when, and which units are left?"""
    order = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    state = await rt.order_return_state(order)
    state["returns"] = await db.returns.find(
        {"order_id": order_id}, {"_id": 0, "items": 0},
    ).sort("created_at", -1).to_list(50)
    return state


@router.post("/returns")
async def create_return(payload: ReturnCreate, user: Dict[str, Any] = Depends(get_current_user)):
    order = await db.orders.find_one({"id": payload.order_id, "user_id": user["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        doc = await rt.create_return(
            order, user, [i.dict() for i in payload.items], payload.reason, payload.comments or "",
        )
    except rt.ReturnError as err:
        raise HTTPException(status_code=400, detail=str(err))

    _, notify = await _injected()
    if order.get("vendor_id"):
        try:
            await notify(
                order["vendor_id"], "vendor", "Return requested",
                f"{doc['return_number']} · ₹{doc['refund_amount']:.0f} for order "
                f"{doc.get('order_number')}. Review it in Returns.",
                extra={"return_id": doc["id"], "action_url": "/vendor/returns"},
            )
        except Exception:
            pass
    return doc


@router.get("/returns/me")
async def my_returns(user: Dict[str, Any] = Depends(get_current_user), limit: int = 100):
    rows = await db.returns.find({"user_id": user["id"]}, {"_id": 0}).sort(
        "created_at", -1,
    ).limit(max(1, min(int(limit or 100), 300))).to_list(300)
    return {"items": rows, "total": len(rows)}


@router.get("/returns/{return_id}")
async def get_return(return_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    row = await db.returns.find_one({"id": return_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Return not found")
    allowed = (
        row.get("user_id") == user["id"]
        or row.get("vendor_id") == user["id"]
        or bool(user.get("is_admin") or user.get("admin_role"))
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Not your return")
    return row


# ── Vendor ─────────────────────────────────────────────────────────────

@router.get("/vendor/me/returns")
async def vendor_returns(
    status: Optional[str] = None,
    limit: int = 200,
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    filt: Dict[str, Any] = {"vendor_id": vendor["id"]}
    if status and status != "all":
        filt["status"] = status
    rows = await db.returns.find(filt, {"_id": 0}).sort("created_at", -1).limit(
        max(1, min(int(limit or 200), 500)),
    ).to_list(500)
    counts: Dict[str, int] = {}
    for r in await db.returns.find({"vendor_id": vendor["id"]}, {"_id": 0, "status": 1}).to_list(2000):
        k = r.get("status") or "requested"
        counts[k] = counts.get(k, 0) + 1
    return {"items": rows, "total": len(rows), "counts": counts}


async def _vendor_return(return_id: str, vendor_id: str) -> Dict[str, Any]:
    row = await db.returns.find_one({"id": return_id, "vendor_id": vendor_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Return not found")
    return row


@router.post("/vendor/me/returns/{return_id}/approve")
async def vendor_approve(return_id: str, body: DecisionBody, vendor: Dict[str, Any] = Depends(require_vendor)):
    row = await _vendor_return(return_id, vendor["id"])
    try:
        out = await rt.decide_return(row, True, vendor, body.note or "")
    except rt.ReturnError as err:
        raise HTTPException(status_code=400, detail=str(err))
    _, notify = await _injected()
    try:
        await notify(
            row["user_id"], "order", "Return approved",
            f"{row['return_number']} approved. Hand the item back to the seller to get "
            f"₹{row['refund_amount']:.0f} refunded.",
        )
    except Exception:
        pass
    return out


@router.post("/vendor/me/returns/{return_id}/reject")
async def vendor_reject(return_id: str, body: DecisionBody, vendor: Dict[str, Any] = Depends(require_vendor)):
    row = await _vendor_return(return_id, vendor["id"])
    try:
        out = await rt.decide_return(row, False, vendor, body.note or "")
    except rt.ReturnError as err:
        raise HTTPException(status_code=400, detail=str(err))
    _, notify = await _injected()
    try:
        await notify(
            row["user_id"], "order", "Return declined",
            f"{row['return_number']} was declined by the seller."
            + (f" Reason: {body.note}" if body.note else ""),
        )
    except Exception:
        pass
    return out


@router.post("/vendor/me/returns/{return_id}/received")
async def vendor_received(return_id: str, body: DecisionBody, vendor: Dict[str, Any] = Depends(require_vendor)):
    row = await _vendor_return(return_id, vendor["id"])
    try:
        return await rt.mark_product_returned(row, vendor, body.note or "")
    except rt.ReturnError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/vendor/me/returns/{return_id}/refund")
async def vendor_refund(return_id: str, vendor: Dict[str, Any] = Depends(require_vendor)):
    """Pay the refund: vendor wallet → customer wallet, stock restored."""
    row = await _vendor_return(return_id, vendor["id"])
    credit_admin_bucket, notify = await _injected()
    try:
        out = await rt.process_refund(
            row, credit_admin_bucket=credit_admin_bucket, notify=notify, actor=vendor,
        )
    except rt.ReturnError as err:
        raise HTTPException(status_code=400, detail=str(err))
    if not out.get("ok"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Refund could not be completed: your available balance is short by "
                f"₹{out.get('needed', 0):.2f}. Nothing has been deducted — add money and "
                f"retry, or admin can resolve it."
            ),
        )
    return {**out, "return": await db.returns.find_one({"id": return_id}, {"_id": 0})}


# ── Admin ──────────────────────────────────────────────────────────────

@router.get("/admin/returns")
async def admin_returns(
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    filt: Dict[str, Any] = {}
    if status and status != "all":
        filt["status"] = status
    if vendor_id:
        filt["vendor_id"] = vendor_id
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        filt["$or"] = [
            {"return_number": rx}, {"order_number": rx},
            {"customer_email": rx}, {"vendor_name": rx},
        ]
    rows = await db.returns.find(filt, {"_id": 0}).sort("created_at", -1).limit(
        max(1, min(int(limit or 200), 1000)),
    ).to_list(1000)
    pending = await db.returns.count_documents({"status": "refund_pending"})
    return {
        "items": rows,
        "total": len(rows),
        "refund_pending_count": pending,
        "refund_pending_amount": round(sum(
            float(r.get("refund_needed") or 0)
            for r in rows if r.get("status") == "refund_pending"
        ), 2),
    }


@router.post("/admin/returns/{return_id}/refund")
async def admin_refund(return_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    """Retry a parked refund once the seller has funded their wallet.

    NO money is invented here: the debit still comes out of the seller's
    balance. If it is still short the return stays parked.
    """
    row = await db.returns.find_one({"id": return_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Return not found")
    credit_admin_bucket, notify = await _injected()
    try:
        out = await rt.process_refund(
            row, credit_admin_bucket=credit_admin_bucket, notify=notify, actor=admin,
        )
    except rt.ReturnError as err:
        raise HTTPException(status_code=400, detail=str(err))
    if not out.get("ok"):
        raise HTTPException(
            status_code=409,
            detail=f"Seller balance still short by ₹{out.get('needed', 0):.2f}. Nothing deducted.",
        )
    return {**out, "return": await db.returns.find_one({"id": return_id}, {"_id": 0})}


@router.get("/admin/returns/{return_id}/audit")
async def admin_return_audit(return_id: str, _admin: Dict[str, Any] = Depends(require_admin)):
    try:
        return await rt.return_audit(return_id)
    except rt.ReturnError as err:
        raise HTTPException(status_code=404, detail=str(err))


# ── Financial error register (Phase 2 §21) ─────────────────────────────

@router.get("/admin/financial-errors")
async def list_financial_errors(
    status: str = Query("open"),
    limit: int = 200,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    filt: Dict[str, Any] = {} if status == "all" else {"status": status}
    rows = await db.financial_errors.find(filt, {"_id": 0}).sort("created_at", -1).limit(
        max(1, min(int(limit or 200), 1000)),
    ).to_list(1000)
    for r in rows:
        r.setdefault("error_type", r.get("kind"))
        r.setdefault("resolution_status", r.get("status"))
    return {
        "items": rows,
        "total": len(rows),
        "open_count": await db.financial_errors.count_documents({"status": "open"}),
    }


class ResolveBody(BaseModel):
    note: Optional[str] = Field(default="", max_length=500)


@router.post("/admin/financial-errors/{error_id}/resolve")
async def resolve_financial_error(
    error_id: str, body: ResolveBody, admin: Dict[str, Any] = Depends(require_admin),
):
    res = await db.financial_errors.update_one(
        {"id": error_id},
        {"$set": {
            "status": "resolved",
            "resolution_status": "resolved",
            "resolved_at": now_utc().isoformat(),
            "resolved_by": admin.get("email"),
            "resolution_note": body.note or "",
        }},
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Error record not found")
    return {"ok": True}
