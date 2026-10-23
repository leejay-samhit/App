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
# Recharge kinds a rider can be scoped to (mirrors routes.recharge.KINDS).
KINDS_RECHARGE = ("mobile", "dth")
# Oct 2026 — when a rider is mapped to a shop, the SELLER's order management
# stops at accepting (or cancelling) the order. Everything after that is the
# rider's job, so the seller panel and API both refuse those transitions.
VENDOR_ALLOWED_WHEN_DP_MANAGED = ("confirmed", "cancelled")
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
    # Jun-2026 — per-seller recharge scope: {vendor_id: {"kinds": ["mobile"],
    # "networks": ["airtel", "jio"]}}. Empty / missing = that seller's whole
    # queue, which is how every normal shop is mapped.
    recharge_scopes: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)


async def _network_kinds() -> Dict[str, str]:
    """slug → recharge kind ("mobile" / "dth") for every configured operator."""
    out: Dict[str, str] = {}
    async for o in db.recharge_options.find(
        {"group": "network"}, {"_id": 0, "slug": 1, "kind": 1},
    ):
        if o.get("slug"):
            out[o["slug"]] = o.get("kind") or "mobile"
    return out


async def _recharge_catalogue_by_vendor() -> Dict[str, Dict[str, List[str]]]:
    """Which sellers sell recharges, and of what kind / operator.

    Reads the live catalogue (a seller "is a recharge seller" because he has
    recharge plans, not because of a flag someone forgot to tick). Vendor-
    added plans may carry only the mirrored sub-category name ("Airtel"), so
    the operator list is resolved through the option names too.
    """
    name_to_slug: Dict[str, str] = {}
    kind_of_slug: Dict[str, str] = {}
    async for o in db.recharge_options.find(
        {"group": "network"}, {"_id": 0, "name": 1, "slug": 1, "kind": 1},
    ):
        if o.get("name") and o.get("slug"):
            name_to_slug[str(o["name"]).strip().lower()] = o["slug"]
            kind_of_slug[o["slug"]] = o.get("kind") or "mobile"
    out: Dict[str, Dict[str, List[str]]] = {}
    async for p in db.products.find(
        {"$or": [
            {"recharge_kind": {"$in": list(KINDS_RECHARGE)}},
            {"category": {"$regex": "recharge", "$options": "i"}},
        ]},
        {"_id": 0, "vendor_id": 1, "recharge_kind": 1, "recharge_network": 1,
         "subcategory": 1, "sub_category": 1},
    ):
        vid = str(p.get("vendor_id") or "")
        if not vid:
            continue
        slug = p.get("recharge_network") or name_to_slug.get(
            str(p.get("subcategory") or p.get("sub_category") or "").strip().lower(), "",
        )
        kind = p.get("recharge_kind") or kind_of_slug.get(slug or "", "mobile")
        row = out.setdefault(vid, {"kinds": [], "networks": []})
        if kind and kind not in row["kinds"]:
            row["kinds"].append(kind)
        if slug and slug not in row["networks"]:
            row["networks"].append(slug)
    return out


@router.get("/admin/delivery-partners/{dp_id}/vendors")
async def admin_dp_vendors(dp_id: str, _admin: Dict[str, Any] = Depends(require_admin)):
    """Which sellers this rider delivers for, plus every seller to choose from.

    Oct 2026 — the projection used to mix inclusion with `"dp_pincodes": 0`,
    which MongoDB rejects, so this endpoint always 500'd and the admin saw
    "could not load shops". Every seller is now returned with the pincodes
    they serve so the admin can filter the list PIN-wise before selecting.
    """
    dp = await db.users.find_one(
        {"id": dp_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "dp_pincodes": 1},
    )
    if not dp:
        raise HTTPException(status_code=404, detail="Delivery partner not found")
    mapped = await db.dp_vendor_map.find(
        {"dp_id": dp_id, "active": True},
        {"_id": 0, "vendor_id": 1, "recharge_kinds": 1, "recharge_networks": 1},
    ).to_list(1000)
    mapped_ids = [m["vendor_id"] for m in mapped]
    scope_by_vendor = {
        m["vendor_id"]: {
            "kinds": m.get("recharge_kinds") or [],
            "networks": m.get("recharge_networks") or [],
        } for m in mapped
    }
    recharge_cat = await _recharge_catalogue_by_vendor()
    net_names: Dict[str, str] = {}
    net_kinds: Dict[str, str] = {}
    async for o in db.recharge_options.find(
        {"group": "network"}, {"_id": 0, "slug": 1, "name": 1, "kind": 1},
    ):
        net_names[o.get("slug") or ""] = o.get("name") or o.get("slug") or ""
        net_kinds[o.get("slug") or ""] = o.get("kind") or "mobile"
    vendors = await db.users.find(
        {"is_vendor": True, "is_vendor_approved": True},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1,
         "vendor_business_name": 1, "shop_name": 1, "pincode": 1,
         "store_pincode": 1, "delivery_pincodes": 1, "city": 1, "state": 1},
    ).to_list(2000)
    for v in vendors:
        v["shop"] = v.get("vendor_business_name") or v.get("shop_name") or v.get("name")
        v["mapped"] = v["id"] in mapped_ids
        pins = {str(p).strip() for p in (v.get("delivery_pincodes") or []) if str(p).strip()}
        for key in ("pincode", "store_pincode"):
            if str(v.get(key) or "").strip():
                pins.add(str(v[key]).strip())
        v["pincodes"] = sorted(pins)
        v["pincode"] = v.get("pincode") or v.get("store_pincode") or (v["pincodes"][0] if v["pincodes"] else "")
        # Jun-2026 — a recharge seller is mapped operator-wise, so the admin
        # screen needs to know which list he belongs in and what he sells.
        cat = recharge_cat.get(v["id"]) or {}
        v["is_recharge"] = bool(cat)
        v["recharge_kinds"] = cat.get("kinds") or []
        v["recharge_networks"] = [
            {"slug": s, "name": net_names.get(s) or s, "kind": net_kinds.get(s) or "mobile"}
            for s in (cat.get("networks") or [])
        ]
        sc = scope_by_vendor.get(v["id"]) or {}
        v["mapped_recharge_kinds"] = sc.get("kinds") or []
        v["mapped_recharge_networks"] = sc.get("networks") or []
    vendors.sort(key=lambda r: (not r["mapped"], str(r.get("shop") or "").lower()))
    # Every PIN any seller covers — powers the admin's pincode filter chips.
    all_pins = sorted({p for v in vendors for p in v["pincodes"]})
    return {
        "dp_id": dp_id,
        "dp_name": dp.get("name") or dp.get("email"),
        "dp_pincodes": [str(p).strip() for p in (dp.get("dp_pincodes") or []) if str(p).strip()],
        "mapped_vendor_ids": mapped_ids,
        "mapped_scopes": scope_by_vendor,
        "vendors": vendors,
        "all_pincodes": all_pins,
    }


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
        scope = (body.recharge_scopes or {}).get(vid) or {}
        kinds = [str(k) for k in (scope.get("kinds") or []) if str(k) in KINDS_RECHARGE]
        networks = [str(n) for n in (scope.get("networks") or []) if str(n).strip()]
        # A DTH-only rider cannot also be scoped to a mobile operator: drop any
        # operator that does not belong to a ticked kind (the UI does the same,
        # this is the server having the last word).
        if networks:
            kind_of = await _network_kinds()
            if not kinds:
                # Operators picked without a kind: the kinds are implied by the
                # operators themselves, so the saved scope is never ambiguous.
                kinds = sorted({(kind_of.get(n) or "mobile") for n in networks})
            networks = [n for n in networks if (kind_of.get(n) or "mobile") in kinds]
        await db.dp_vendor_map.update_one(
            {"dp_id": dp_id, "vendor_id": vid},
            {"$set": {
                "active": True,
                "shop_name": (v or {}).get("vendor_business_name") or (v or {}).get("shop_name")
                or (v or {}).get("name") or "Seller",
                "recharge_kinds": kinds,
                "recharge_networks": networks,
                "mapped_at": ts,
                "mapped_by": admin.get("email"),
            }, "$setOnInsert": {"id": str(uuid.uuid4())}},
            upsert=True,
        )
    await _audit_log(admin, "delivery_partner.map_vendors", "user", dp_id,
                     {"count": len(wanted)})
    return {"ok": True, "mapped": len(wanted)}


# ── Seller side: "is a rider handling my deliveries?" ──────────────────

async def _require_vendor(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Local approved-seller gate (server.require_vendor would be circular)."""
    if not (user.get("is_vendor") and user.get("is_vendor_approved")):
        raise HTTPException(status_code=403, detail="Vendor access required")
    return user


async def vendor_dp_partners(vendor_id: str) -> List[Dict[str, Any]]:
    """Active riders mapped to this seller. Empty list = seller self-delivers."""
    rows = await db.dp_vendor_map.find(
        {"vendor_id": vendor_id, "active": True}, {"_id": 0, "dp_id": 1},
    ).to_list(100)
    out: List[Dict[str, Any]] = []
    for r in rows:
        u = await db.users.find_one(
            {"id": r["dp_id"], "is_delivery_partner_approved": True},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "dp_phone": 1},
        )
        if u:
            out.append({
                "id": u["id"],
                "name": u.get("name") or "Delivery partner",
                "phone": u.get("dp_phone") or u.get("phone") or "",
            })
    return out


@router.get("/vendor/me/delivery-partners")
async def vendor_my_delivery_partners(vendor: Dict[str, Any] = Depends(_require_vendor)):
    """The seller's panel calls this to know whether order movement is his job.

    When a rider is mapped to the shop, the SELLER only accepts (confirms) or
    cancels an order — every delivery stage after that belongs to the rider.
    """
    partners = await vendor_dp_partners(vendor["id"])
    return {
        "managed": bool(partners),
        "partners": partners,
        "seller_statuses": list(VENDOR_ALLOWED_WHEN_DP_MANAGED) if partners else None,
    }


# ── Rider: mapped sellers + orders ─────────────────────────────────────

async def _mapped_vendor_ids(dp_id: str) -> List[str]:
    rows = await db.dp_vendor_map.find(
        {"dp_id": dp_id, "active": True}, {"_id": 0, "vendor_id": 1},
    ).to_list(1000)
    return [r["vendor_id"] for r in rows]


# ── Jun-2026 — RECHARGE riders are mapped category-wise ────────────────
#
# A recharge seller's queue is not "parcels from one shop": it is operator
# work. The owner's rule is that a rider can be put on, say, Airtel + Jio
# MOBILE recharges of that seller and must not see his DTH jobs at all. The
# scope lives on the mapping row (`recharge_kinds` / `recharge_networks`);
# an empty scope means "everything this seller sells", which is exactly how
# every pre-existing mapping behaves.
async def _dp_scopes(dp_id: str) -> Dict[str, Dict[str, Any]]:
    rows = await db.dp_vendor_map.find(
        {"dp_id": dp_id, "active": True},
        {"_id": 0, "vendor_id": 1, "recharge_kinds": 1, "recharge_networks": 1},
    ).to_list(1000)
    return {
        r["vendor_id"]: {
            "kinds": [str(k) for k in (r.get("recharge_kinds") or [])],
            "networks": [str(n) for n in (r.get("recharge_networks") or [])],
        }
        for r in rows
    }


def _order_in_scope(order: Dict[str, Any], scopes: Dict[str, Dict[str, Any]]) -> bool:
    if not order.get("is_recharge"):
        return True
    sc = scopes.get(str(order.get("vendor_id") or "")) or {}
    kinds, nets = sc.get("kinds") or [], sc.get("networks") or []
    if not kinds and not nets:
        return True
    if kinds and str(order.get("recharge_kind") or "mobile") not in kinds:
        return False
    if nets and str(order.get("recharge_network") or "") not in nets:
        return False
    return True


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
    scopes = await _dp_scopes(dp["id"])
    rows = [r for r in rows if _order_in_scope(r, scopes)]
    buyer_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    buyers: Dict[str, Any] = {}
    if buyer_ids:
        async for u in db.users.find(
            {"id": {"$in": buyer_ids}}, {"_id": 0, "id": 1, "name": 1, "phone": 1},
        ):
            buyers[u["id"]] = u
    # Shop names for the retailer-wise grouping the rider sees.
    shops: Dict[str, str] = {}
    async for v in db.users.find(
        {"id": {"$in": vids}},
        {"_id": 0, "id": 1, "name": 1, "vendor_business_name": 1, "shop_name": 1},
    ):
        shops[v["id"]] = (
            v.get("vendor_business_name") or v.get("shop_name") or v.get("name") or "Shop"
        )
    for r in rows:
        b = buyers.get(r.get("user_id") or "") or {}
        r["buyer_name"] = b.get("name") or "Customer"
        r["buyer_phone"] = b.get("phone")
        r["vendor_name"] = (
            shops.get(r.get("vendor_id") or "") or r.get("vendor_name") or "Shop"
        )
        r["cash_to_collect"] = _r(r.get("cod_due"))
        r["is_mine"] = r.get("dp_id") == dp["id"]
        r["status_label"] = STATUS_LABELS.get(r.get("status") or "", (r.get("status") or "").title())
    counts: Dict[str, int] = {}
    for r in await db.orders.find(
        filt, {"_id": 0, "status": 1, "vendor_id": 1, "is_recharge": 1,
               "recharge_kind": 1, "recharge_network": 1},
    ).to_list(2000):
        if not _order_in_scope(r, scopes):
            continue
        k = r.get("status") or "placed"
        counts[k] = counts.get(k, 0) + 1
    return {"items": rows, "total": len(rows), "counts": counts, "mapped_vendors": len(vids)}


class DPStatusUpdate(BaseModel):
    status: str
    delivery_person_name: Optional[str] = Field(default="", max_length=120)
    delivery_person_phone: Optional[str] = Field(default="", max_length=15)
    note: Optional[str] = Field(default="", max_length=300)


async def _dp_move_order(
    dp: Dict[str, Any],
    order: Dict[str, Any],
    status: str,
    person_name: str = "",
    person_phone: str = "",
) -> Dict[str, Any]:
    """Advance ONE order for this rider. Shared by the single-order endpoint
    and the customer-wise bulk endpoint, so the money moves through exactly
    one code path whichever button the rider taps."""
    order_id = order["id"]
    # Claim the order for this rider (first rider to move it owns it).
    await db.orders.update_one({"id": order_id}, {"$set": {
        "dp_id": dp["id"],
        "dp_name": dp.get("name") or dp.get("email"),
        "dp_phone": dp.get("dp_phone") or dp.get("phone"),
    }})
    if person_name or person_phone:
        await db.orders.update_one({"id": order_id}, {"$set": {
            "delivery_person_name": person_name or dp.get("name") or "",
            "delivery_person_phone": person_phone or dp.get("dp_phone") or "",
            "delivery_info_updated_at": now_utc().isoformat(),
        }})

    from server import admin_update_order_status, OrderStatusUpdate
    out = await admin_update_order_status(
        order_id=order_id,
        payload=OrderStatusUpdate(status=status),  # type: ignore
        admin=dp,   # user-shaped doc; downstream only reads id/email
    )

    # COD cash lands with the rider — a liability, never earnings.
    if status == "delivered":
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
    return out if isinstance(out, dict) else {}


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
    if not _order_in_scope(order, await _dp_scopes(dp["id"])):
        raise HTTPException(status_code=403, detail="This recharge type is not assigned to you")
    out = await _dp_move_order(
        dp, order, body.status, body.delivery_person_name or "", body.delivery_person_phone or "",
    )
    return {"ok": True, **out}


# ── Rider: CUSTOMER-WISE delivery (Jun-2026 owner request) ─────────────
#
# One customer who buys from three shops creates three orders. The rider's
# only view was shop-wise, so he had to hunt the same doorstep three times
# and update each shop separately. These two endpoints group the same orders
# by CUSTOMER and let him move all of them in one tap — the shop-wise list
# updates automatically because both views read the same orders.
OPEN_STATUSES = ["placed", "confirmed", "shipped", "out_for_delivery"]
# What "next step" means for the rider, in order.
NEXT_STATUS = {
    "placed": "confirmed",
    "confirmed": "shipped",
    "shipped": "out_for_delivery",
    "out_for_delivery": "delivered",
}


@router.get("/delivery-partner/me/customers")
async def dp_my_customers(
    status: str = "open",
    limit: int = 200,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    sort: str = "distance",
    dp: Dict[str, Any] = Depends(require_dp),
):
    """Open orders grouped by CUSTOMER, across every shop mapped to me.

    Jun-2026 — pass the rider's own `lat`/`lng` and every doorstep comes back
    with `distance_km`, nearest first, so he rides one loop instead of
    criss-crossing the town. Falls back to the pincode centroid when an
    address has no coordinates, and to the old most-orders-first order when
    the rider hasn't shared his location.
    """
    vids = await _mapped_vendor_ids(dp["id"])
    if not vids:
        return {"items": [], "total": 0, "mapped_vendors": 0}
    filt: Dict[str, Any] = {"vendor_id": {"$in": vids}}
    if status == "open":
        filt["status"] = {"$in": OPEN_STATUSES}
    elif status and status != "all":
        filt["status"] = status
    rows = await db.orders.find(filt, {"_id": 0}).sort("created_at", -1).limit(
        max(1, min(int(limit or 200), 500)),
    ).to_list(500)
    scopes = await _dp_scopes(dp["id"])
    rows = [r for r in rows if _order_in_scope(r, scopes)]
    buyer_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    buyers: Dict[str, Any] = {}
    if buyer_ids:
        async for u in db.users.find(
            {"id": {"$in": buyer_ids}},
            {"_id": 0, "id": 1, "name": 1, "phone": 1, "address": 1, "pincode": 1},
        ):
            buyers[u["id"]] = u
    shops: Dict[str, str] = {}
    async for v in db.users.find(
        {"id": {"$in": vids}},
        {"_id": 0, "id": 1, "name": 1, "vendor_business_name": 1, "shop_name": 1},
    ):
        shops[v["id"]] = (
            v.get("vendor_business_name") or v.get("shop_name") or v.get("name") or "Shop"
        )

    groups: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        uid = r.get("user_id") or "unknown"
        b = buyers.get(uid) or {}
        addr = r.get("shipping_address") or {}
        g = groups.setdefault(uid, {
            "user_id": uid,
            "name": addr.get("name") or b.get("name") or "Customer",
            "phone": addr.get("phone") or b.get("phone"),
            "address": ", ".join([x for x in [
                addr.get("line1"), addr.get("line2"), addr.get("city"),
            ] if x]) or b.get("address") or "",
            "pincode": addr.get("pincode") or b.get("pincode") or "",
            "lat": addr.get("latitude"),
            "lng": addr.get("longitude"),
            "orders": [],
            "shops": [],
            "order_count": 0,
            "item_count": 0,
            "order_value": 0.0,
            "cash_to_collect": 0.0,
        })
        # A later order may carry the coordinates an earlier one lacked.
        if g["lat"] is None and addr.get("latitude") is not None:
            g["lat"], g["lng"] = addr.get("latitude"), addr.get("longitude")
        if not g["pincode"] and addr.get("pincode"):
            g["pincode"] = addr["pincode"]
        shop_name = shops.get(r.get("vendor_id") or "") or r.get("vendor_name") or "Shop"
        g["orders"].append({
            "id": r.get("id"),
            "order_number": r.get("order_number"),
            "vendor_id": r.get("vendor_id"),
            "shop_name": shop_name,
            "status": r.get("status"),
            "status_label": STATUS_LABELS.get(r.get("status") or "", (r.get("status") or "").title()),
            "total": _r(r.get("total_amount") or r.get("total")),
            "cash_to_collect": _r(r.get("cod_due")),
            "payment_method": r.get("payment_method"),
            "items": [
                {"name": i.get("name") or i.get("product_name"), "qty": int(i.get("qty") or 1)}
                for i in (r.get("items") or [])
            ],
            "created_at": r.get("created_at"),
            "is_mine": r.get("dp_id") == dp["id"],
        })
        if shop_name not in g["shops"]:
            g["shops"].append(shop_name)
        g["order_count"] += 1
        g["item_count"] += sum(int(i.get("qty") or 1) for i in (r.get("items") or []))
        g["order_value"] = _r(g["order_value"] + _f(r.get("total_amount") or r.get("total")))
        g["cash_to_collect"] = _r(g["cash_to_collect"] + _f(r.get("cod_due")))

    # Distance from the rider to each doorstep.
    from core.delivery import haversine_km, pincode_centroid
    origin = (float(lat), float(lng)) if lat is not None and lng is not None else None
    if origin is None:
        me = await db.users.find_one(
            {"id": dp["id"]},
            {"_id": 0, "lat": 1, "lng": 1, "pincode": 1, "dp_pincodes": 1},
        ) or {}
        if me.get("lat") is not None and me.get("lng") is not None:
            origin = (float(me["lat"]), float(me["lng"]))
        else:
            base = me.get("pincode") or next(iter(me.get("dp_pincodes") or []), None)
            if base:
                origin = await pincode_centroid(str(base))
    pin_cache: Dict[str, Any] = {}
    for g in groups.values():
        point = None
        if g.get("lat") is not None and g.get("lng") is not None:
            point = (float(g["lat"]), float(g["lng"]))
        elif g.get("pincode"):
            pin = str(g["pincode"])
            if pin not in pin_cache:
                pin_cache[pin] = await pincode_centroid(pin)
            point = pin_cache[pin]
        g["distance_km"] = (
            round(haversine_km(origin[0], origin[1], point[0], point[1]), 1)
            if origin and point else None
        )

    out = []
    for g in groups.values():
        open_orders = [o for o in g["orders"] if o["status"] in OPEN_STATUSES]
        # The slowest order decides what the rider can do for this doorstep.
        stages = [o["status"] for o in open_orders]
        earliest = next((s for s in OPEN_STATUSES if s in stages), None)
        g["open_count"] = len(open_orders)
        g["next_status"] = NEXT_STATUS.get(earliest or "", "")
        g["next_label"] = STATUS_LABELS.get(g["next_status"], "")
        g["all_delivered"] = len(open_orders) == 0
        out.append(g)
    by_distance = sort != "orders" and any(g.get("distance_km") is not None for g in out)
    if by_distance:
        # Unknown distances go last — a rider can't plan around a blank.
        out.sort(key=lambda r: (
            r["distance_km"] if r.get("distance_km") is not None else 1e9,
            -r["open_count"],
        ))
    else:
        out.sort(key=lambda r: (-r["open_count"], -r["cash_to_collect"], r["name"]))
    return {
        "items": out, "total": len(out), "mapped_vendors": len(vids),
        "sorted_by": "distance" if by_distance else "orders",
        "has_origin": origin is not None,
    }


class DPBulkStatus(BaseModel):
    # Omit / leave blank to advance every order to ITS own next step.
    status: Optional[str] = None
    delivery_person_name: Optional[str] = Field(default="", max_length=120)
    delivery_person_phone: Optional[str] = Field(default="", max_length=15)


@router.post("/delivery-partner/customers/{user_id}/advance")
async def dp_advance_customer(
    user_id: str, body: DPBulkStatus, dp: Dict[str, Any] = Depends(require_dp),
):
    """Move EVERY open order of one customer (from my mapped shops).

    `status` empty  → each order steps to its own next stage.
    `status` given  → every order jumps straight to that stage
                      (the rider's "Mark all delivered").
    Orders already at or past the target are skipped, never re-posted, so
    the cash ledger can't double-count.
    """
    if body.status and body.status not in DP_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(STATUS_LABELS[s] for s in DP_STATUSES)}",
        )
    vids = await _mapped_vendor_ids(dp["id"])
    if not vids:
        raise HTTPException(status_code=403, detail="No shops are mapped to you yet")
    rows = await db.orders.find(
        {"user_id": user_id, "vendor_id": {"$in": vids}, "status": {"$in": OPEN_STATUSES}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    scopes = await _dp_scopes(dp["id"])
    rows = [r for r in rows if _order_in_scope(r, scopes)]
    if not rows:
        raise HTTPException(status_code=404, detail="This customer has no open orders for your shops")

    order_of = {s: i for i, s in enumerate(["placed", *DP_STATUSES])}
    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    cash_collected = 0.0
    for o in rows:
        target = body.status or NEXT_STATUS.get(o.get("status") or "", "")
        if not target:
            skipped.append({"order_number": o.get("order_number"), "reason": "nothing to do"})
            continue
        if order_of.get(target, 0) <= order_of.get(o.get("status") or "placed", 0):
            skipped.append({"order_number": o.get("order_number"),
                            "reason": f"already {STATUS_LABELS.get(o.get('status'), o.get('status'))}"})
            continue
        try:
            await _dp_move_order(
                dp, o, target,
                body.delivery_person_name or "", body.delivery_person_phone or "",
            )
            if target == "delivered":
                cash_collected = _r(cash_collected + _f(o.get("cod_due")))
            updated.append({"order_id": o["id"], "order_number": o.get("order_number"),
                            "shop_name": o.get("vendor_name"), "status": target})
        except HTTPException as err:
            failed.append({"order_number": o.get("order_number"), "reason": str(err.detail)[:160]})
        except Exception as err:  # keep going — one bad order can't block the doorstep
            logger.warning(f"dp bulk advance failed for {o.get('id')}: {err}")
            failed.append({"order_number": o.get("order_number"), "reason": str(err)[:160]})
    return {
        "ok": True,
        "updated": len(updated),
        "orders": updated,
        "skipped": skipped,
        "failed": failed,
        "cash_collected": cash_collected,
    }


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
    wallet = _r((u or {}).get("wallet_balance"))
    # Jun-2026 — the rider can clear what he owes out of his own wallet, so
    # the screen must show how much of the dues the wallet covers and what is
    # genuinely left to pay online.
    payable_from_wallet = _r(min(stored, wallet))
    return {
        "cash_collected": _r(collected),
        "cash_remitted": _r(remitted),
        "cash_in_hand": stored,
        "ledger_balance": ledger,
        "unledgered_difference": _r(stored - ledger),
        "in_sync": abs(stored - ledger) < 0.02,
        "personal_wallet": wallet,
        "payable_from_wallet": payable_from_wallet,
        "remaining_after_wallet": _r(max(0.0, stored - payable_from_wallet)),
        "wallet_covers_all": bool(stored > 0.009 and payable_from_wallet >= stored - 0.009),
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


@router.get("/delivery-partner/me/wallet-transactions")
async def dp_wallet_transactions(
    limit: int = 200, dp: Dict[str, Any] = Depends(require_dp),
):
    """Oct 2026 — the rider's EARNINGS ledger (personal wallet only).

    Delivery commissions in, withdrawals out. COD cash never appears here:
    that pot is Slangcart's money and lives in /me/cash-transactions.
    """
    rows = await db.transactions.find(
        {"user_id": dp["id"], "type": {"$in": [
            "dp_delivery_commission", "dp_delivery_commission_reversal",
            "withdrawal_hold", "withdrawal", "withdrawal_reversal",
            "dp_cash_paid_from_wallet",
            "admin_credit", "admin_debit",
        ]}},
        {"_id": 0},
    ).sort("created_at", -1).limit(max(1, min(int(limit or 200), 500))).to_list(500)
    earned = _r(sum(
        float(r.get("credit") or 0) for r in rows if r.get("type") == "dp_delivery_commission"
    ))
    withdrawn = _r(sum(
        float(r.get("debit") or 0) for r in rows
        if r.get("type") in ("withdrawal_hold", "withdrawal")
    ))
    return {
        "items": rows,
        "total": len(rows),
        "total_earned": earned,
        "total_withdrawn": withdrawn,
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
    res = await _settle_cod_orders(dp["id"], amount, remit["id"])
    settled, by_vendor_list, remaining = res["settled"], res["vendor_split"], res["unallocated"]
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
            "vendor_split": by_vendor_list, "unallocated": remaining, **view}


async def _settle_cod_orders(dp_id: str, amount: float, remit_id: str) -> Dict[str, Any]:
    """Release the oldest unremitted COD orders up to `amount` and record
    each seller's share. Shared by the Razorpay and wallet set-off paths."""
    remaining = _r(amount)
    settled: List[Dict[str, Any]] = []
    async for o in db.orders.find(
        {"dp_id": dp_id, "status": "delivered", "cod_due": {"$gt": 0},
         "dp_cash_remitted": {"$ne": True}},
        {"_id": 0, "id": 1, "cod_due": 1, "vendor_id": 1, "vendor_name": 1, "order_number": 1},
    ).sort("delivered_at", 1):
        due = _r(o.get("cod_due"))
        if due > remaining + 0.009:
            break
        await db.orders.update_one({"id": o["id"]}, {"$set": {
            "dp_cash_remitted": True,
            "dp_remit_id": remit_id,
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
    await db.dp_remittances.update_one({"id": remit_id}, {"$set": {
        "settled_orders": settled,
        "vendor_split": list(by_vendor.values()),
        "unallocated": remaining,
    }})
    return {"settled": settled, "vendor_split": list(by_vendor.values()), "unallocated": remaining}


class RemitFromWallet(BaseModel):
    amount: float = Field(..., gt=0)


@router.post("/delivery-partner/remit/wallet")
async def dp_remit_from_wallet(
    body: RemitFromWallet, dp: Dict[str, Any] = Depends(require_dp),
):
    """Jun-2026 owner request — settle Slangcart's cash from the rider's OWN
    wallet balance, so "Cash to pay" is always `cash in hand − what his
    wallet can cover`.

    This is a pure SET-OFF, not a payment: we owed the rider his wallet
    balance, he owed us the COD cash, so both sides shrink by the same
    rupee. Deliberately NO bank_ledger row — nothing arrives in the bank, and
    writing one would double-count the money in the Treasury. The admin's
    net worth is untouched: an asset (cash on hand) and a liability (rider
    wallet) both fall by `amount`.
    """
    view = await _dp_cash_view(dp["id"])
    amount = _r(body.amount)
    if dp.get("wallet_frozen"):
        raise HTTPException(status_code=400, detail="Your wallet is frozen — contact support.")
    if amount > view["cash_in_hand"] + 0.009:
        raise HTTPException(
            status_code=400,
            detail=f"You only owe Slangcart ₹{view['cash_in_hand']:,.2f}.",
        )
    if amount > view["personal_wallet"] + 0.009:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Your wallet has ₹{view['personal_wallet']:,.2f}. "
                f"Pay the rest online."
            ),
        )
    remit = {
        "id": str(uuid.uuid4()),
        "dp_id": dp["id"],
        "dp_name": dp.get("name") or dp.get("email"),
        "amount": amount,
        "status": "paid",
        "method": "wallet_setoff",
        "is_mock": False,
        "created_at": now_utc().isoformat(),
        "paid_at": now_utc().isoformat(),
    }
    await db.dp_remittances.insert_one(dict(remit))

    try:
        # 1. the rider's earnings wallet pays it (Group 2 liability falls)
        await shop_money.debit(
            dp["id"], "wallet_balance", amount,
            idempotency_key=f"DPWALLETREMIT:{remit['id']}",
            group="dp_cash",
            txn_type="dp_cash_paid_from_wallet",
            destination_wallet="system_treasury",
            settlement_status="remitted",
            description=f"₹{amount:.0f} of Slangcart cash settled from your wallet",
            extra={"remit_id": remit["id"], "dp_id": dp["id"], "method": "wallet_setoff"},
        )
        # 2. his cash-in-hand clears by the same rupee
        await shop_money.debit(
            dp["id"], CASH_FIELD, amount,
            idempotency_key=f"DPREMIT:{remit['id']}",
            group="dp_cash",
            txn_type="dp_cash_remitted",
            destination_wallet="system_treasury",
            payment_method="wallet",
            settlement_status="remitted",
            description=f"Cash settled from wallet · ₹{amount:.0f}",
            extra={"wallet_impact": "dp_cash_only", "remit_id": remit["id"],
                   "dp_id": dp["id"], "method": "wallet_setoff"},
        )
    except shop_money.InsufficientFunds as err:
        await db.dp_remittances.update_one(
            {"id": remit["id"]}, {"$set": {"status": "failed", "failed_reason": str(err)[:200]}},
        )
        raise HTTPException(status_code=409, detail=str(err))

    res = await _settle_cod_orders(dp["id"], amount, remit["id"])
    try:
        from core.notifications import create_notification
        await create_notification(
            dp["id"], "wallet", f"₹{amount:.0f} settled from your wallet",
            f"{len(res['settled'])} cash order(s) cleared. No online payment needed.",
            extra={"action_url": "/delivery/net-worth"},
        )
    except Exception:
        pass
    view = await _dp_cash_view(dp["id"])
    return {
        "ok": True, "method": "wallet_setoff", "amount": amount,
        "orders_cleared": len(res["settled"]),
        "vendor_split": res["vendor_split"], "unallocated": res["unallocated"],
        **view,
    }


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
