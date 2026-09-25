"""Delivery Partner — apply, mapping, order management, money (Sep-2026).

A Delivery Partner (DP) is a rider account, NOT a seller:

  * He applies like a vendor (delivery radius, pincodes, documents) and admin
    approves him. He can never become a vendor or a service provider.
  * ADMIN maps sellers to him. He only ever sees orders belonging to the
    sellers he is mapped to — nothing else in the marketplace.
  * He advances orders: confirmed → shipped → on the way → delivered, and
    records the delivery information the customer sees.
  * **He earns nothing per delivery.** The only money he touches is the CASH
    he collects on COD orders, which lands in his wallet as a LIABILITY to
    Slangcart (he is holding our/the seller's money, not his own).
  * He remits that cash with **Pay To Admin** (Razorpay). On success the
    money is recorded as a Group 7 bank credit and released vendor-wise
    against Group 2 liability, so no rupee is ever double counted.

Money invariants
----------------
`users.dp_cash_in_hand`  = cash collected − cash remitted   (what he owes us)
`users.wallet_balance`   = his personal wallet (untouched by COD cash)
Every movement is a ledger row with an idempotency key, so a replayed webhook
or a double tap can only ever move money once.
"""
import io
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core import bank, shop_money
from core.db import db
from core.razorpay import create_order, get_creds, verify_signature
from core.security import get_current_user, require_admin, require_admin_role
from core.utils import audit_log as _audit_log, now_utc

logger = logging.getLogger(__name__)
router = APIRouter()

# The DP's cash pot. Deliberately NOT `wallet_balance` — it is money he holds
# on our behalf, so it must never mix with his personal wallet.
CASH_FIELD = "dp_cash_in_hand"
MIN_WITHDRAWAL = 1000.0            # owner's rule for delivery partners
DP_STATUSES = ("confirmed", "shipped", "out_for_delivery", "delivered")
STATUS_LABELS = {
    "confirmed": "Confirmed",
    "shipped": "Shipped",
    "out_for_delivery": "On the way",
    "delivered": "Delivered",
}


async def require_dp(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not (user.get("is_delivery_partner") and user.get("is_delivery_partner_approved")):
        raise HTTPException(status_code=403, detail="Delivery partner access required")
    return user


def _f(v: Any) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x != x else x


def _r(v: Any) -> float:
    return round(_f(v), 2)


# ── Apply / status ─────────────────────────────────────────────────────

class DPApply(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=120)
    phone: str = Field(..., min_length=10, max_length=15)
    vehicle_type: str = Field(default="bike", max_length=40)
    vehicle_number: str = Field(default="", max_length=30)
    delivery_radius_km: float = Field(default=5, ge=0, le=100)
    pincodes: List[str] = Field(default_factory=list)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    address: str = Field(default="", max_length=300)
    id_proof_url: str = Field(default="", max_length=600)
    licence_url: str = Field(default="", max_length=600)
    notes: str = Field(default="", max_length=500)


@router.post("/delivery-partner/apply")
async def dp_apply(payload: DPApply, user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("registration_paid"):
        raise HTTPException(status_code=403, detail="Complete registration before applying")
    if user.get("approval_status") != "approved":
        raise HTTPException(status_code=403, detail="Your account must be approved by admin first")
    if user.get("is_vendor") or user.get("is_service_provider"):
        raise HTTPException(
            status_code=400,
            detail="A seller or service provider account cannot also be a delivery partner.",
        )
    existing = await db.delivery_partner_applications.find_one(
        {"user_id": user["id"], "status": {"$in": ["pending", "approved"]}}, {"_id": 0},
    )
    if existing:
        raise HTTPException(status_code=400, detail="You already have an active application")

    pincodes = [p.strip() for p in (payload.pincodes or []) if p and p.strip()]
    app_id = str(uuid.uuid4())
    ts = now_utc().isoformat()
    doc = {
        "id": app_id,
        "user_id": user["id"],
        "email": user.get("email"),
        "status": "pending",
        "created_at": ts,
        **payload.dict(),
        "pincodes": pincodes,
    }
    await db.delivery_partner_applications.insert_one(dict(doc))
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "is_delivery_partner": True,
        "is_delivery_partner_approved": False,
        "dp_status": "pending",
        "dp_applied_at": ts,
        "dp_phone": payload.phone,
        "dp_vehicle_type": payload.vehicle_type,
        "dp_vehicle_number": payload.vehicle_number,
        "dp_radius_km": payload.delivery_radius_km,
        "dp_pincodes": pincodes,
        "dp_city": payload.city,
        "dp_state": payload.state,
    }})
    doc.pop("_id", None)
    return doc


@router.get("/delivery-partner/me")
async def dp_me(user: Dict[str, Any] = Depends(get_current_user)):
    """Application + approval state. Safe to call for ANY logged-in user, so
    the profile screen can decide what to show without guessing."""
    app = await db.delivery_partner_applications.find_one(
        {"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)],
    )
    approved = bool(user.get("is_delivery_partner_approved"))
    return {
        "is_delivery_partner": bool(user.get("is_delivery_partner")),
        "is_approved": approved,
        "status": user.get("dp_status") or (app or {}).get("status") or "none",
        "application": app,
        "can_apply": bool(
            user.get("approval_status") == "approved"
            and not user.get("is_vendor")
            and not user.get("is_service_provider")
            and not app
        ),
        "blocked_reason": (
            "Sellers and service providers cannot be delivery partners."
            if (user.get("is_vendor") or user.get("is_service_provider")) else ""
        ),
        "min_withdrawal": MIN_WITHDRAWAL,
    }


# ── Admin: applications, approval, vendor mapping ──────────────────────

@router.get("/admin/delivery-partners")
async def admin_list_dps(
    status: Optional[str] = None,
    _admin: Dict[str, Any] = Depends(require_admin),
):
    filt: Dict[str, Any] = {"is_delivery_partner": True}
    if status == "approved":
        filt["is_delivery_partner_approved"] = True
    elif status == "pending":
        filt["is_delivery_partner_approved"] = {"$ne": True}
    rows = await db.users.find(filt, {
        "_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "dp_status": 1,
        "dp_phone": 1, "dp_vehicle_type": 1, "dp_vehicle_number": 1,
        "dp_radius_km": 1, "dp_pincodes": 1, "dp_city": 1, "dp_state": 1,
        "is_delivery_partner_approved": 1, CASH_FIELD: 1, "dp_applied_at": 1,
    }).sort("dp_applied_at", -1).to_list(1000)
    for r in rows:
        r["cash_in_hand"] = _r(r.get(CASH_FIELD))
        r["mapped_vendor_count"] = await db.dp_vendor_map.count_documents(
            {"dp_id": r["id"], "active": True},
        )
    return {"items": rows, "total": len(rows)}


@router.get("/admin/delivery-partners/applications")
async def admin_dp_applications(
    status: str = Query("pending"),
    _admin: Dict[str, Any] = Depends(require_admin),
):
    filt: Dict[str, Any] = {} if status == "all" else {"status": status}
    rows = await db.delivery_partner_applications.find(filt, {"_id": 0}).sort(
        "created_at", -1,
    ).to_list(1000)
    return {"items": rows, "total": len(rows)}


class DPDecision(BaseModel):
    note: Optional[str] = Field(default="", max_length=500)


@router.post("/admin/delivery-partners/applications/{app_id}/approve")
async def admin_dp_approve(
    app_id: str, body: DPDecision,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support")),
):
    app = await db.delivery_partner_applications.find_one({"id": app_id}, {"_id": 0})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if app["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Application is already {app['status']}")
    ts = now_utc().isoformat()
    await db.delivery_partner_applications.update_one({"id": app_id}, {"$set": {
        "status": "approved", "reviewed_at": ts,
        "reviewed_by": admin.get("email"), "review_note": body.note or "",
    }})
    await db.users.update_one({"id": app["user_id"]}, {"$set": {
        "is_delivery_partner": True,
        "is_delivery_partner_approved": True,
        "dp_status": "approved",
        "dp_approved_at": ts,
    }})
    try:
        from core.notifications import create_notification
        await create_notification(
            app["user_id"], "account", "You're an approved delivery partner",
            "Your dashboard is ready. Admin will map the shops you deliver for.",
            extra={"action_url": "/delivery/dashboard"},
        )
    except Exception:
        pass
    await _audit_log(admin, "delivery_partner.approve", "user", app["user_id"], {"app_id": app_id})
    return {"ok": True}


@router.post("/admin/delivery-partners/applications/{app_id}/reject")
async def admin_dp_reject(
    app_id: str, body: DPDecision,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support")),
):
    app = await db.delivery_partner_applications.find_one({"id": app_id}, {"_id": 0})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    ts = now_utc().isoformat()
    await db.delivery_partner_applications.update_one({"id": app_id}, {"$set": {
        "status": "rejected", "reviewed_at": ts,
        "reviewed_by": admin.get("email"), "review_note": body.note or "",
    }})
    await db.users.update_one({"id": app["user_id"]}, {"$set": {
        "is_delivery_partner": False,
        "is_delivery_partner_approved": False,
        "dp_status": "rejected",
    }})
    await _audit_log(admin, "delivery_partner.reject", "user", app["user_id"], {"app_id": app_id})
    return {"ok": True}


class DPMapping(BaseModel):
    vendor_ids: List[str] = Field(default_factory=list)


@router.get("/admin/delivery-partners/{dp_id}/vendors")
async def admin_dp_vendors(dp_id: str, _admin: Dict[str, Any] = Depends(require_admin)):
    """Which sellers this rider delivers for, plus every seller to choose from."""
    mapped = await db.dp_vendor_map.find(
        {"dp_id": dp_id, "active": True}, {"_id": 0, "vendor_id": 1},
    ).to_list(1000)
    mapped_ids = [m["vendor_id"] for m in mapped]
    vendors = await db.users.find(
        {"is_vendor": True, "is_vendor_approved": True},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "vendor_business_name": 1,
         "shop_name": 1, "pincode": 1, "dp_pincodes": 0},
    ).sort("vendor_business_name", 1).to_list(2000)
    for v in vendors:
        v["shop"] = v.get("vendor_business_name") or v.get("shop_name") or v.get("name")
        v["mapped"] = v["id"] in mapped_ids
    return {"dp_id": dp_id, "mapped_vendor_ids": mapped_ids, "vendors": vendors}


@router.put("/admin/delivery-partners/{dp_id}/vendors")
async def admin_set_dp_vendors(
    dp_id: str, body: DPMapping,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support")),
):
    """Replace the rider's seller mapping. Rows are deactivated rather than
    deleted so historical orders keep their audit trail."""
    dp = await db.users.find_one({"id": dp_id, "is_delivery_partner": True}, {"_id": 0, "id": 1})
    if not dp:
        raise HTTPException(status_code=404, detail="Delivery partner not found")
    wanted = {v for v in (body.vendor_ids or []) if v}
    ts = now_utc().isoformat()
    await db.dp_vendor_map.update_many(
        {"dp_id": dp_id, "vendor_id": {"$nin": list(wanted)}},
        {"$set": {"active": False, "unmapped_at": ts}},
    )
    for vid in wanted:
        v = await db.users.find_one({"id": vid}, {"_id": 0, "vendor_business_name": 1,
                                                 "shop_name": 1, "name": 1})
        await db.dp_vendor_map.update_one(
            {"dp_id": dp_id, "vendor_id": vid},
            {"$set": {
                "active": True,
                "shop_name": (v or {}).get("vendor_business_name") or (v or {}).get("shop_name")
                or (v or {}).get("name") or "Seller",
                "mapped_at": ts,
                "mapped_by": admin.get("email"),
            }, "$setOnInsert": {"id": str(uuid.uuid4())}},
            upsert=True,
        )
    await _audit_log(admin, "delivery_partner.map_vendors", "user", dp_id,
                     {"count": len(wanted)})
    return {"ok": True, "mapped": len(wanted)}


# ── Rider: mapped sellers + orders ─────────────────────────────────────

async def _mapped_vendor_ids(dp_id: str) -> List[str]:
    rows = await db.dp_vendor_map.find(
        {"dp_id": dp_id, "active": True}, {"_id": 0, "vendor_id": 1},
    ).to_list(1000)
    return [r["vendor_id"] for r in rows]


@router.get("/delivery-partner/me/vendors")
async def dp_my_vendors(dp: Dict[str, Any] = Depends(require_dp)):
    """The shops this rider delivers for, with live order counts."""
    rows = await db.dp_vendor_map.find(
        {"dp_id": dp["id"], "active": True}, {"_id": 0},
    ).to_list(1000)
    out = []
    for m in rows:
        vid = m["vendor_id"]
        v = await db.users.find_one(
            {"id": vid},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "vendor_business_name": 1,
             "shop_name": 1, "pincode": 1, "address": 1},
        ) or {}
        open_count = await db.orders.count_documents(
            {"vendor_id": vid, "status": {"$in": ["placed", "confirmed", "shipped", "out_for_delivery"]}},
        )
        cod_rows = await db.orders.aggregate([
            {"$match": {"vendor_id": vid, "dp_id": dp["id"], "status": "delivered",
                        "cod_due": {"$gt": 0}, "dp_cash_remitted": {"$ne": True}}},
            {"$group": {"_id": None, "s": {"$sum": "$cod_due"}, "n": {"$sum": 1}}},
        ]).to_list(1)
        out.append({
            "vendor_id": vid,
            "shop_name": m.get("shop_name") or v.get("vendor_business_name")
            or v.get("shop_name") or v.get("name") or "Seller",
            "phone": v.get("phone"),
            "pincode": v.get("pincode"),
            "address": v.get("address"),
            "open_orders": open_count,
            "cash_to_remit": _r((cod_rows or [{}])[0].get("s")),
            "cash_orders": int((cod_rows or [{}])[0].get("n") or 0),
            "mapped_at": m.get("mapped_at"),
        })
    out.sort(key=lambda r: (-r["open_orders"], r["shop_name"]))
    return {"items": out, "total": len(out)}


@router.get("/delivery-partner/me/orders")
async def dp_my_orders(
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    limit: int = 300,
    dp: Dict[str, Any] = Depends(require_dp),
):
    """Orders from the rider's MAPPED sellers only. Nothing else is visible."""
    vids = await _mapped_vendor_ids(dp["id"])
    if not vids:
        return {"items": [], "total": 0, "counts": {}, "mapped_vendors": 0}
    filt: Dict[str, Any] = {"vendor_id": {"$in": vids}}
    if vendor_id:
        if vendor_id not in vids:
            raise HTTPException(status_code=403, detail="That shop is not mapped to you")
        filt["vendor_id"] = vendor_id
    if status and status != "all":
        filt["status"] = status
    rows = await db.orders.find(filt, {"_id": 0}).sort("created_at", -1).limit(
        max(1, min(int(limit or 300), 500)),
    ).to_list(500)
    buyer_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    buyers: Dict[str, Any] = {}
    if buyer_ids:
        async for u in db.users.find(
            {"id": {"$in": buyer_ids}}, {"_id": 0, "id": 1, "name": 1, "phone": 1},
        ):
            buyers[u["id"]] = u
    for r in rows:
        b = buyers.get(r.get("user_id") or "") or {}
        r["buyer_name"] = b.get("name") or "Customer"
        r["buyer_phone"] = b.get("phone")
        r["cash_to_collect"] = _r(r.get("cod_due"))
        r["is_mine"] = r.get("dp_id") == dp["id"]
        r["status_label"] = STATUS_LABELS.get(r.get("status") or "", (r.get("status") or "").title())
    counts: Dict[str, int] = {}
    for r in await db.orders.find(filt, {"_id": 0, "status": 1}).to_list(2000):
        k = r.get("status") or "placed"
        counts[k] = counts.get(k, 0) + 1
    return {"items": rows, "total": len(rows), "counts": counts, "mapped_vendors": len(vids)}


class DPStatusUpdate(BaseModel):
    status: str
    delivery_person_name: Optional[str] = Field(default="", max_length=120)
    delivery_person_phone: Optional[str] = Field(default="", max_length=15)
    note: Optional[str] = Field(default="", max_length=300)


@router.patch("/delivery-partner/orders/{order_id}/status")
async def dp_update_status(
    order_id: str, body: DPStatusUpdate, dp: Dict[str, Any] = Depends(require_dp),
):
    """Advance an order. Delegates to the SAME status engine the vendor and
    admin use, so delivery money (vendor credit, delivery fee, cashback)
    moves exactly once and exactly the same way whoever taps the button.

    On `delivered` with cash due, the COD cash is recorded into the rider's
    cash-in-hand as a liability to Slangcart — he has our money until he
    remits it. He is never credited a delivery fee: riders earn nothing here.
    """
    if body.status not in DP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(STATUS_LABELS[s] for s in DP_STATUSES)}",
        )
    vids = await _mapped_vendor_ids(dp["id"])
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("vendor_id") not in vids:
        raise HTTPException(status_code=403, detail="This order's shop is not mapped to you")

    # Claim the order for this rider (first rider to move it owns it).
    await db.orders.update_one({"id": order_id}, {"$set": {
        "dp_id": dp["id"],
        "dp_name": dp.get("name") or dp.get("email"),
        "dp_phone": dp.get("dp_phone") or dp.get("phone"),
    }})
    if body.delivery_person_name or body.delivery_person_phone:
        await db.orders.update_one({"id": order_id}, {"$set": {
            "delivery_person_name": body.delivery_person_name or dp.get("name") or "",
            "delivery_person_phone": body.delivery_person_phone or dp.get("dp_phone") or "",
            "delivery_info_updated_at": now_utc().isoformat(),
        }})

    from server import admin_update_order_status, OrderStatusUpdate
    out = await admin_update_order_status(
        order_id=order_id,
        payload=OrderStatusUpdate(status=body.status),  # type: ignore
        admin=dp,   # user-shaped doc; downstream only reads id/email
    )

    # COD cash lands with the rider — a liability, never earnings.
    if body.status == "delivered":
        cash = _r(order.get("cod_due"))
        if cash > 0.009:
            row = await shop_money.credit(
                dp["id"], CASH_FIELD, cash,
                idempotency_key=f"DPCASH:{order_id}",
                group="dp_cash",
                txn_type="dp_cash_collected",
                order_id=order_id,
                order_number=order.get("order_number"),
                vendor_id=order.get("vendor_id"),
                shop_name=order.get("vendor_name"),
                payment_method="cod",
                settlement_status="to_remit",
                description=(
                    f"Cash collected ₹{cash:.0f} for order {order.get('order_number')} "
                    f"— to be paid to Slangcart"
                ),
                extra={"wallet_impact": "dp_cash_only", "dp_id": dp["id"]},
            )
            if row:
                await db.orders.update_one(
                    {"id": order_id},
                    {"$set": {"dp_cash_collected": cash, "dp_cash_remitted": False}},
                )
    return {"ok": True, **(out if isinstance(out, dict) else {})}


# ── Rider: wallet + net worth ──────────────────────────────────────────

async def _dp_cash_view(dp_id: str) -> Dict[str, Any]:
    """Cash collected − remitted, straight off the ledger."""
    rows = await db.transactions.find(
        {"user_id": dp_id, "wallet_impact": "dp_cash_only"},
        {"_id": 0, "credit": 1, "debit": 1, "amount": 1, "type": 1},
    ).to_list(20000)
    collected = remitted = 0.0
    for r in rows:
        c, d = _f(r.get("credit")), _f(r.get("debit"))
        if c or d:
            collected += c
            remitted += d
        elif r.get("type") == "dp_cash_remitted":
            remitted += abs(_f(r.get("amount")))
        else:
            collected += abs(_f(r.get("amount")))
    u = await db.users.find_one({"id": dp_id}, {"_id": 0, CASH_FIELD: 1, "wallet_balance": 1})
    stored = _r((u or {}).get(CASH_FIELD))
    ledger = _r(collected - remitted)
    return {
        "cash_collected": _r(collected),
        "cash_remitted": _r(remitted),
        "cash_in_hand": stored,
        "ledger_balance": ledger,
        "unledgered_difference": _r(stored - ledger),
        "in_sync": abs(stored - ledger) < 0.02,
        "personal_wallet": _r((u or {}).get("wallet_balance")),
    }


@router.get("/delivery-partner/me/wallet")
async def dp_wallet(dp: Dict[str, Any] = Depends(require_dp)):
    """Wallet and net worth come from the SAME view, so they can never drift."""
    view = await _dp_cash_view(dp["id"])
    pending = await db.withdrawals.aggregate([
        {"$match": {"user_id": dp["id"], "status": {"$in": ["pending", "approved", "processing"]}}},
        {"$group": {"_id": None, "s": {"$sum": "$amount"}}},
    ]).to_list(1)
    available = view["personal_wallet"]
    return {
        **view,
        "available": available,
        "pending_withdrawals": _r((pending or [{}])[0].get("s")),
        "min_withdrawal": MIN_WITHDRAWAL,
        "can_withdraw": bool(available >= MIN_WITHDRAWAL and not dp.get("wallet_frozen")),
        "withdraw_blocked_reason": (
            "Wallet is frozen — contact support." if dp.get("wallet_frozen")
            else "" if available >= MIN_WITHDRAWAL
            else f"You need at least ₹{int(MIN_WITHDRAWAL):,} in your wallet to withdraw."
        ),
        "cash_note": (
            "Cash you collect on delivery belongs to Slangcart. Pay it in from "
            "Net Worth — it is never part of your withdrawable wallet."
        ),
    }


@router.get("/delivery-partner/me/net-worth")
async def dp_net_worth(dp: Dict[str, Any] = Depends(require_dp)):
    """Where the money came from, what is still owed, and per-shop split."""
    view = await _dp_cash_view(dp["id"])
    per_vendor = await db.orders.aggregate([
        {"$match": {"dp_id": dp["id"], "status": "delivered", "cod_due": {"$gt": 0},
                    "dp_cash_remitted": {"$ne": True}}},
        {"$group": {"_id": {"v": "$vendor_id", "n": "$vendor_name"},
                    "amount": {"$sum": "$cod_due"}, "orders": {"$sum": 1}}},
        {"$sort": {"amount": -1}},
    ]).to_list(500)
    delivered = await db.orders.count_documents({"dp_id": dp["id"], "status": "delivered"})
    live = await db.orders.count_documents(
        {"dp_id": dp["id"], "status": {"$in": ["confirmed", "shipped", "out_for_delivery"]}},
    )
    return {
        "dp_id": dp["id"],
        "name": dp.get("name") or dp.get("email"),
        **view,
        "amount_due_to_admin": view["cash_in_hand"],
        "deliveries_completed": delivered,
        "deliveries_in_progress": live,
        "per_vendor": [
            {"vendor_id": r["_id"].get("v"), "shop_name": r["_id"].get("n") or "Seller",
             "amount": _r(r["amount"]), "orders": int(r["orders"] or 0)}
            for r in per_vendor
        ],
        "earnings_note": "Delivery partners are not paid per delivery — you only hold and remit COD cash.",
    }


@router.get("/delivery-partner/me/cash-transactions")
async def dp_cash_transactions(limit: int = 300, dp: Dict[str, Any] = Depends(require_dp)):
    """Every cash-collected / cash-paid row, newest first."""
    rows = await db.transactions.find(
        {"user_id": dp["id"], "wallet_impact": "dp_cash_only"}, {"_id": 0},
    ).sort("created_at", -1).limit(max(1, min(int(limit or 300), 500))).to_list(500)
    for r in rows:
        r["direction"] = "in" if _f(r.get("credit")) > 0 else "out"
    return {"items": rows, "total": len(rows)}


# ── Rider: Pay To Admin (Razorpay) ─────────────────────────────────────

class RemitStart(BaseModel):
    amount: float = Field(..., gt=0)


class RemitVerify(BaseModel):
    remit_id: str
    razorpay_order_id: str = ""
    razorpay_payment_id: str
    razorpay_signature: str = ""


@router.post("/delivery-partner/remit/start")
async def dp_remit_start(body: RemitStart, dp: Dict[str, Any] = Depends(require_dp)):
    """Open a Razorpay checkout for the cash the rider is paying in."""
    view = await _dp_cash_view(dp["id"])
    amount = _r(body.amount)
    if amount > view["cash_in_hand"] + 0.009:
        raise HTTPException(
            status_code=400,
            detail=f"You are only holding ₹{view['cash_in_hand']:,.2f} of Slangcart cash.",
        )
    creds = await get_creds()
    try:
        rzp_order_id = await create_order(
            int(round(amount * 100)),
            f"dpremit_{dp['id'][:10]}_{uuid.uuid4().hex[:6]}",
            notes={"dp_id": dp["id"], "kind": "dp_cash_remittance"},
            creds=creds,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    # Snapshot the vendor-wise split NOW, so the money is released against the
    # right sellers even if more orders are delivered before he pays.
    nw = await dp_net_worth(dp)
    remit = {
        "id": str(uuid.uuid4()),
        "dp_id": dp["id"],
        "dp_name": dp.get("name") or dp.get("email"),
        "amount": amount,
        "razorpay_order_id": rzp_order_id,
        "status": "created",
        "is_mock": creds["is_mock"],
        "split_snapshot": nw["per_vendor"],
        "created_at": now_utc().isoformat(),
    }
    await db.dp_remittances.insert_one(dict(remit))
    return {
        "remit_id": remit["id"],
        "razorpay_order_id": rzp_order_id,
        "amount": amount,
        "amount_paise": int(round(amount * 100)),
        "currency": "INR",
        "key_id": creds["key_id"] or "rzp_test_MOCK",
        "is_mock": creds["is_mock"],
        "prefill": {"name": dp.get("name") or "", "email": dp.get("email") or "",
                    "contact": dp.get("dp_phone") or dp.get("phone") or ""},
        "description": f"Cash paid to Slangcart · ₹{amount:.0f}",
    }


@router.post("/delivery-partner/remit/verify")
async def dp_remit_verify(body: RemitVerify, dp: Dict[str, Any] = Depends(require_dp)):
    """Money received. ONE movement, three consistent records:

      1. the rider's cash-in-hand is debited (he no longer holds our money)
      2. a Group 7 BANK CREDIT is written, so bank ledger == bank statement
      3. the matching orders are marked remitted and the vendor-wise split is
         recorded, so Group 2 liability is released against the right sellers
    """
    remit = await db.dp_remittances.find_one(
        {"id": body.remit_id, "dp_id": dp["id"]}, {"_id": 0},
    )
    if not remit:
        raise HTTPException(status_code=404, detail="Payment attempt not found")
    if remit["status"] == "paid":
        return {"ok": True, "already_verified": True, "amount": remit["amount"]}
    creds = await get_creds()
    if not creds["is_mock"] and not verify_signature(
        remit["razorpay_order_id"], body.razorpay_payment_id,
        body.razorpay_signature, creds["key_secret"],
    ):
        await db.dp_remittances.update_one(
            {"id": remit["id"]}, {"$set": {"status": "failed", "failed_reason": "bad_signature"}},
        )
        raise HTTPException(status_code=401, detail="Invalid payment signature")

    claimed = await db.dp_remittances.update_one(
        {"id": remit["id"], "status": "created"},
        {"$set": {"status": "paid", "razorpay_payment_id": body.razorpay_payment_id,
                  "paid_at": now_utc().isoformat()}},
    )
    if claimed.modified_count != 1:
        return {"ok": True, "already_verified": True, "amount": remit["amount"]}

    amount = _r(remit["amount"])
    try:
        await shop_money.debit(
            dp["id"], CASH_FIELD, amount,
            idempotency_key=f"DPREMIT:{remit['id']}",
            group="dp_cash",
            txn_type="dp_cash_remitted",
            destination_wallet="system_treasury",
            payment_method="razorpay",
            payment_id=body.razorpay_payment_id,
            settlement_status="remitted",
            description=f"Cash paid to Slangcart · ₹{amount:.0f}",
            extra={"wallet_impact": "dp_cash_only", "remit_id": remit["id"],
                   "dp_id": dp["id"], "vendor_split": remit.get("split_snapshot") or []},
        )
    except shop_money.InsufficientFunds as err:
        await db.dp_remittances.update_one(
            {"id": remit["id"]}, {"$set": {"status": "created", "retry_reason": str(err)[:200]}},
        )
        raise HTTPException(status_code=409, detail=str(err))

    # Group 7 — the cash is now in the company bank account.
    await bank.post_bank(
        kind="credit",
        amount=amount,
        category="cod_remittance",
        description=f"COD cash paid in by {dp.get('name') or dp.get('email')}",
        ref_key=f"DPREMIT:{remit['id']}",
        utr=body.razorpay_payment_id,
        user_id=dp["id"],
        extra={"remit_id": remit["id"], "vendor_split": remit.get("split_snapshot") or []},
    )

    # Release the oldest unremitted COD orders up to the amount paid, and
    # record what each seller's share of this payment was.
    remaining = amount
    settled: List[Dict[str, Any]] = []
    async for o in db.orders.find(
        {"dp_id": dp["id"], "status": "delivered", "cod_due": {"$gt": 0},
         "dp_cash_remitted": {"$ne": True}},
        {"_id": 0, "id": 1, "cod_due": 1, "vendor_id": 1, "vendor_name": 1, "order_number": 1},
    ).sort("delivered_at", 1):
        due = _r(o.get("cod_due"))
        if due > remaining + 0.009:
            break
        await db.orders.update_one({"id": o["id"]}, {"$set": {
            "dp_cash_remitted": True,
            "dp_remit_id": remit["id"],
            "dp_remitted_at": now_utc().isoformat(),
        }})
        remaining = _r(remaining - due)
        settled.append({"order_id": o["id"], "order_number": o.get("order_number"),
                        "vendor_id": o.get("vendor_id"),
                        "shop_name": o.get("vendor_name"), "amount": due})
    by_vendor: Dict[str, Dict[str, Any]] = {}
    for s in settled:
        slot = by_vendor.setdefault(s["vendor_id"] or "unknown", {
            "vendor_id": s["vendor_id"], "shop_name": s["shop_name"],
            "amount": 0.0, "orders": 0,
        })
        slot["amount"] = _r(slot["amount"] + s["amount"])
        slot["orders"] += 1
    await db.dp_remittances.update_one({"id": remit["id"]}, {"$set": {
        "settled_orders": settled,
        "vendor_split": list(by_vendor.values()),
        "unallocated": remaining,
    }})
    try:
        from core.notifications import create_notification
        await create_notification(
            dp["id"], "wallet", f"₹{amount:.0f} paid to Slangcart",
            f"{len(settled)} cash order(s) cleared. Thank you!",
            extra={"action_url": "/delivery/net-worth"},
        )
    except Exception:
        pass
    view = await _dp_cash_view(dp["id"])
    return {"ok": True, "amount": amount, "orders_cleared": len(settled),
            "vendor_split": list(by_vendor.values()), "unallocated": remaining, **view}


@router.get("/delivery-partner/me/remittances")
async def dp_remittances(limit: int = 100, dp: Dict[str, Any] = Depends(require_dp)):
    rows = await db.dp_remittances.find(
        {"dp_id": dp["id"], "status": "paid"}, {"_id": 0},
    ).sort("paid_at", -1).limit(max(1, min(int(limit or 100), 300))).to_list(300)
    return {"items": rows, "total": len(rows)}


# ── Rider: Excel export ────────────────────────────────────────────────

@router.get("/delivery-partner/me/export.xlsx")
async def dp_export(dp: Dict[str, Any] = Depends(require_dp)):
    """Everything the rider has: summary, cash ledger, deliveries, payments."""
    from openpyxl import Workbook

    nw = await dp_net_worth(dp)
    wb = Workbook()

    ws = wb.active
    ws.title = "Summary"
    for row in [
        ["Delivery partner", nw["name"]],
        ["Cash collected (lifetime)", nw["cash_collected"]],
        ["Cash paid to Slangcart", nw["cash_remitted"]],
        ["Cash in hand (due to Slangcart)", nw["cash_in_hand"]],
        ["Ledger balance", nw["ledger_balance"]],
        ["Books balanced", "YES" if nw["in_sync"] else "NO"],
        ["Personal wallet", nw["personal_wallet"]],
        ["Deliveries completed", nw["deliveries_completed"]],
        ["Deliveries in progress", nw["deliveries_in_progress"]],
        ["Note", nw["earnings_note"]],
    ]:
        ws.append(row)

    ws2 = wb.create_sheet("Cash due by shop")
    ws2.append(["Shop", "Orders", "Amount due"])
    for r in nw["per_vendor"]:
        ws2.append([r["shop_name"], r["orders"], r["amount"]])

    ws3 = wb.create_sheet("Cash ledger")
    ws3.append(["Date", "Reference", "Type", "Shop", "Order", "In", "Out", "Description"])
    for t in (await dp_cash_transactions(500, dp))["items"]:
        ws3.append([
            t.get("created_at"), t.get("reference_number"), t.get("type"),
            t.get("shop_name"), t.get("order_number"),
            _f(t.get("credit")), _f(t.get("debit")), t.get("description"),
        ])

    ws4 = wb.create_sheet("Deliveries")
    ws4.append(["Date", "Order", "Shop", "Status", "Order total", "Cash collected", "Remitted"])
    async for o in db.orders.find(
        {"dp_id": dp["id"]},
        {"_id": 0, "order_number": 1, "vendor_name": 1, "status": 1, "total": 1,
         "cod_due": 1, "dp_cash_remitted": 1, "delivered_at": 1, "created_at": 1},
    ).sort("created_at", -1).limit(5000):
        ws4.append([
            o.get("delivered_at") or o.get("created_at"), o.get("order_number"),
            o.get("vendor_name"), STATUS_LABELS.get(o.get("status") or "", o.get("status")),
            _f(o.get("total")), _f(o.get("cod_due")),
            "YES" if o.get("dp_cash_remitted") else "NO",
        ])

    ws5 = wb.create_sheet("Payments to Slangcart")
    ws5.append(["Paid at", "Amount", "Razorpay payment id", "Orders cleared", "Shop split"])
    for r in (await dp_remittances(300, dp))["items"]:
        ws5.append([
            r.get("paid_at"), _f(r.get("amount")), r.get("razorpay_payment_id"),
            len(r.get("settled_orders") or []),
            "; ".join(f"{s.get('shop_name')}={s.get('amount')}" for s in (r.get("vendor_split") or [])),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    stamp = now_utc().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="slangcart-delivery-{stamp}.xlsx"'},
    )
