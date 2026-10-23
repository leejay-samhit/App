"""Subscription + per-shop payout structure — Jun 2026.

Two owner-facing knobs live here:

* **Subscription** (`/api/admin/subscription/config`) — the ₹118 price and how
  it is split: GST, the member's instant cashback, the inviter's bonus and
  what the platform keeps. The same numbers are served to the app
  (`/api/subscription/config`) so the paywall never shows a figure the
  backend would not actually book.

* **Per-shop payout structure** (`/api/admin/payout-structure/vendors`) — the
  cashback % and delivery charge used to be ONE value for every shop. Each
  shop can now carry its own; a shop with no override falls back to the
  platform default, so nothing changes for sellers the owner never touches.

Nothing in here moves money — it only decides the rates the money engines
(`core/cashback.py`, `core/delivery_charges.py`, the subscription split in
`server._credit_no_ref_signup_to_admin`) read when they do.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.config import MAX_CASHBACK_PCT, REFERRAL_GST_PCT
from core.db import db
from core.security import get_current_user, require_admin
from core.utils import get_settings, now_utc

router = APIRouter(tags=["subscription"])


def _split(settings: Dict[str, Any]) -> Dict[str, Any]:
    """The ₹118 broken down exactly the way the ledger books it."""
    gross = round(float(settings.get("registration_fee") or 0), 2)
    gst = round(gross * (REFERRAL_GST_PCT / (100.0 + REFERRAL_GST_PCT)), 2)
    net = round(gross - gst, 2)
    pct = max(0.0, min(100.0, float(settings.get("subscription_cashback_pct") or 0)))
    member_cashback = round(net * pct / 100.0, 2)
    invite_bonus = round(float(settings.get("subscription_invite_bonus") or 0), 2)
    revenue = round(net - member_cashback, 2)
    return {
        "price": gross,
        "gst_pct": REFERRAL_GST_PCT,
        "gst": gst,
        "net": net,
        "cashback_pct": pct,
        "member_cashback": member_cashback,
        "invite_bonus": min(invite_bonus, revenue),
        "platform_revenue": revenue,
        "platform_revenue_with_invite": round(revenue - min(invite_bonus, revenue), 2),
    }


async def _benefits(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The SEVEN things a member gets — the only list the app renders."""
    sp = _split(settings)
    reveal_fee = settings.get("phone_reveal_fee")
    reveal_fee = float(reveal_fee) if reveal_fee is not None else 1.0
    reveal_gst = float(
        settings.get("phone_reveal_gst_pct")
        if settings.get("phone_reveal_gst_pct") is not None else 18.0
    )
    reveal_total = round(reveal_fee + reveal_fee * reveal_gst / 100.0, 2)
    branding = await db.branding.find_one({"id": "global"}, {"_id": 0, "support_whatsapp": 1}) or {}
    return [
        {
            "key": "cashback",
            "icon": "gift",
            "title": f"Instant {int(sp['cashback_pct'])}% cashback",
            "sub": f"₹{sp['member_cashback']:g} lands in your wallet the moment you pay",
            "free_text": "Not available",
            "enabled": True,
        },
        {
            "key": "support",
            "icon": "headphones",
            "title": "Real-time priority support",
            "sub": "Instant answers on WhatsApp and live order updates",
            "free_text": "Standard queue only",
            "enabled": bool(settings.get("subscription_priority_support", True)),
            "whatsapp": branding.get("support_whatsapp") or "",
        },
        {
            "key": "ads",
            "icon": "slash",
            "title": "Zero ads",
            "sub": "No banners, no interruptions — anywhere in the app",
            "free_text": "Ads shown",
            "enabled": bool(settings.get("subscription_zero_ads", True)),
        },
        {
            "key": "numbers",
            "icon": "phone-call",
            "title": "Unlimited service provider numbers",
            "sub": "Get any provider's number free, as many as you like",
            "free_text": f"₹{reveal_total:g} per number",
            "enabled": bool(settings.get("subscription_free_reveals", True)),
        },
        {
            "key": "apply",
            "icon": "briefcase",
            "title": "Apply as seller, service provider or rider",
            "sub": "Only members can run a shop, list a service or deliver",
            "free_text": "Locked",
            "enabled": True,
        },
        {
            "key": "referral",
            "icon": "users",
            "title": "Earn referral bonus",
            "sub": f"₹{sp['invite_bonus']:g} in your wallet for every friend who subscribes",
            "free_text": "Cannot earn",
            "enabled": sp["invite_bonus"] > 0,
        },
        {
            "key": "wallet",
            "icon": "credit-card",
            "title": "Shopping cashback + bank withdrawals",
            "sub": "Earn cashback on every delivered order and withdraw to your bank",
            "free_text": "Locked",
            "enabled": bool(settings.get("cashback_enabled", True)),
        },
    ]


@router.get("/subscription/config")
async def subscription_config(user: Dict[str, Any] = Depends(get_current_user)):
    """What the paywall, the upsell banner and every locked card read."""
    settings = await get_settings()
    branding = await db.branding.find_one(
        {"id": "global"}, {"_id": 0, "support_whatsapp": 1, "app_name": 1},
    ) or {}
    return {
        **_split(settings),
        "benefits": [b for b in await _benefits(settings) if b["enabled"]],
        "support_whatsapp": branding.get("support_whatsapp") or "",
        "app_name": branding.get("app_name") or "Slangcart",
        "is_subscriber": bool(user.get("registration_paid")),
        "subscription_skipped": bool(user.get("subscription_skipped")),
        "subscribed_at": user.get("registration_paid_at") or user.get("payment_verified_at"),
    }


class SubscriptionConfigPatch(BaseModel):
    price: Optional[float] = Field(default=None, ge=0, le=100000)
    cashback_pct: Optional[float] = Field(default=None, ge=0, le=100)
    invite_bonus: Optional[float] = Field(default=None, ge=0, le=100000)
    free_reveals: Optional[bool] = None
    zero_ads: Optional[bool] = None
    priority_support: Optional[bool] = None
    support_whatsapp: Optional[str] = None


@router.get("/admin/subscription/config")
async def admin_subscription_config(_: Dict[str, Any] = Depends(require_admin)):
    settings = await get_settings()
    branding = await db.branding.find_one({"id": "global"}, {"_id": 0, "support_whatsapp": 1}) or {}
    subs = await db.users.count_documents({"registration_paid": True, "role": {"$ne": "admin"}})
    free = await db.users.count_documents({
        "registration_paid": {"$ne": True}, "role": {"$ne": "admin"},
    })
    return {
        **_split(settings),
        "benefits": await _benefits(settings),
        "free_reveals": bool(settings.get("subscription_free_reveals", True)),
        "zero_ads": bool(settings.get("subscription_zero_ads", True)),
        "priority_support": bool(settings.get("subscription_priority_support", True)),
        "support_whatsapp": branding.get("support_whatsapp") or "",
        "subscribers": subs,
        "non_subscribers": free,
    }


@router.put("/admin/subscription/config")
async def admin_update_subscription_config(
    payload: SubscriptionConfigPatch,
    admin: Dict[str, Any] = Depends(require_admin),
):
    update: Dict[str, Any] = {}
    if payload.price is not None:
        update["registration_fee"] = round(float(payload.price), 2)
    if payload.cashback_pct is not None:
        update["subscription_cashback_pct"] = round(float(payload.cashback_pct), 2)
    if payload.invite_bonus is not None:
        update["subscription_invite_bonus"] = round(float(payload.invite_bonus), 2)
    for key, field in (
        ("subscription_free_reveals", payload.free_reveals),
        ("subscription_zero_ads", payload.zero_ads),
        ("subscription_priority_support", payload.priority_support),
    ):
        if field is not None:
            update[key] = bool(field)
    # Validate BEFORE writing — a bonus larger than the platform's share used
    # to be saved and only then rejected.
    probe = {**(await get_settings()), **update}
    probe_split = _split(probe)
    probe_bonus = round(float(probe.get("subscription_invite_bonus") or 0), 2)
    if probe_bonus > probe_split["platform_revenue"] + 0.009:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The invite bonus (₹{probe_bonus:g}) cannot be more than what the platform "
                f"keeps (₹{probe_split['platform_revenue']:g}) — lower the bonus or the cashback %."
            ),
        )
    if update:
        await db.settings.update_one({"id": "global"}, {"$set": update}, upsert=True)
    if payload.support_whatsapp is not None:
        digits = "".join(ch for ch in payload.support_whatsapp if ch.isdigit())
        await db.branding.update_one(
            {"id": "global"}, {"$set": {"support_whatsapp": digits}}, upsert=True,
        )
    await db.audit_logs.insert_one({
        "actor_id": admin.get("id"),
        "actor_email": admin.get("email"),
        "action": "subscription.config_updated",
        "payload": update,
        "created_at": now_utc().isoformat(),
    })
    return await admin_subscription_config(admin)


# ─────────────────────────── per-shop payout structure ───────────────────

@router.get("/admin/payout-structure/vendors")
async def payout_structure_vendors(
    q: Optional[str] = Query(default=None),
    _: Dict[str, Any] = Depends(require_admin),
):
    """Every shop with its effective cashback % and delivery charge."""
    settings = await get_settings()
    default_pct = round(float(settings.get("default_cashback_pct") or 0), 2)
    default_flat = round(float(settings.get("delivery_charge_flat") or 0), 2)
    default_free = round(float(settings.get("delivery_free_threshold") or 0), 2)

    query: Dict[str, Any] = {"$or": [{"is_vendor": True}, {"is_vendor_approved": True}]}
    if q and q.strip():
        rx = {"$regex": q.strip(), "$options": "i"}
        query = {"$and": [query, {"$or": [
            {"name": rx}, {"vendor_business_name": rx}, {"email": rx}, {"store_pincode": rx},
        ]}]}

    rows: List[Dict[str, Any]] = []
    for v in await db.users.find(query, {
        "_id": 0, "id": 1, "name": 1, "email": 1, "vendor_business_name": 1,
        "store_pincode": 1, "default_cashback_pct": 1, "delivery_charge_flat": 1,
        "delivery_free_threshold": 1, "dp_commission_pct": 1, "is_vendor_approved": 1,
    }).sort("vendor_business_name", 1).to_list(1000):
        cb = v.get("default_cashback_pct")
        flat = v.get("delivery_charge_flat")
        free = v.get("delivery_free_threshold")
        rows.append({
            "vendor_id": v["id"],
            "shop_name": v.get("vendor_business_name") or v.get("name") or "Shop",
            "email": v.get("email"),
            "pincode": v.get("store_pincode"),
            "approved": bool(v.get("is_vendor_approved")),
            "cashback_pct": None if cb in (None, "") else round(float(cb), 2),
            "delivery_charge_flat": None if flat in (None, "") else round(float(flat), 2),
            "delivery_free_threshold": None if free in (None, "") else round(float(free), 2),
            "effective_cashback_pct": default_pct if cb in (None, "") else round(float(cb), 2),
            "effective_delivery_flat": default_flat if flat in (None, "") else round(float(flat), 2),
            "effective_free_threshold": default_free if free in (None, "") else round(float(free), 2),
            "has_override": any(x not in (None, "") for x in (cb, flat, free)),
        })
    return {
        "defaults": {
            "cashback_pct": default_pct,
            "delivery_charge_flat": default_flat,
            "delivery_free_threshold": default_free,
            "max_cashback_pct": MAX_CASHBACK_PCT,
            "delivery_cart_max": round(float(settings.get("delivery_cart_max") or 0), 2),
            "cashback_enabled": bool(settings.get("cashback_enabled", True)),
        },
        "vendors": rows,
        "total": len(rows),
        "overrides": sum(1 for r in rows if r["has_override"]),
    }


class VendorPayoutPatch(BaseModel):
    # null clears the override and puts the shop back on the platform default.
    cashback_pct: Optional[float] = Field(default=None, ge=0, le=MAX_CASHBACK_PCT)
    delivery_charge_flat: Optional[float] = Field(default=None, ge=0, le=100000)
    delivery_free_threshold: Optional[float] = Field(default=None, ge=0, le=10000000)
    clear: List[str] = Field(default_factory=list)


@router.put("/admin/payout-structure/vendors/{vendor_id}")
async def update_vendor_payout(
    vendor_id: str,
    payload: VendorPayoutPatch,
    admin: Dict[str, Any] = Depends(require_admin),
):
    vendor = await db.users.find_one(
        {"id": vendor_id}, {"_id": 0, "id": 1, "vendor_business_name": 1, "name": 1},
    )
    if not vendor:
        raise HTTPException(status_code=404, detail="Shop not found")

    sets: Dict[str, Any] = {}
    if payload.cashback_pct is not None:
        sets["default_cashback_pct"] = round(float(payload.cashback_pct), 2)
    if payload.delivery_charge_flat is not None:
        sets["delivery_charge_flat"] = round(float(payload.delivery_charge_flat), 2)
    if payload.delivery_free_threshold is not None:
        sets["delivery_free_threshold"] = round(float(payload.delivery_free_threshold), 2)

    allowed_clear = {"cashback_pct": "default_cashback_pct",
                     "delivery_charge_flat": "delivery_charge_flat",
                     "delivery_free_threshold": "delivery_free_threshold"}
    unsets = {allowed_clear[k]: "" for k in payload.clear if k in allowed_clear}
    if not sets and not unsets:
        raise HTTPException(status_code=400, detail="Nothing to change")

    ops: Dict[str, Any] = {}
    if sets:
        ops["$set"] = sets
    if unsets:
        ops["$unset"] = unsets
    await db.users.update_one({"id": vendor_id}, ops)
    await db.audit_logs.insert_one({
        "actor_id": admin.get("id"),
        "actor_email": admin.get("email"),
        "action": "payout_structure.vendor_updated",
        "target_id": vendor_id,
        "payload": {"set": sets, "cleared": list(unsets.keys())},
        "created_at": now_utc().isoformat(),
    })
    # New rates apply to FUTURE orders only — every existing order froze its
    # own cashback % and delivery charge at checkout, so no past money moves.
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
    fresh = await db.users.find_one({"id": vendor_id}, {
        "_id": 0, "default_cashback_pct": 1, "delivery_charge_flat": 1,
        "delivery_free_threshold": 1,
    }) or {}
    return {
        "ok": True,
        "vendor_id": vendor_id,
        "shop_name": vendor.get("vendor_business_name") or vendor.get("name"),
        "applies_to": "future orders only — existing orders keep what they were promised",
        **fresh,
    }
