"""Recharge taxonomy — State and Network/Operator option lists.

Oct-2026 owner request. The Recharge category needs a different browsing
shape from the rest of the shop:

    Recharge
      ├─ Mobile Recharge   → pick State, then Network  → products
      └─ DTH TV Recharge   → pick State, then Network  → products

States and networks are DATA, not code: the owner adds and deletes them from
inside the app (different circles and operators come and go). Each option
carries a `kind` ("mobile" | "dth") and a `group` ("state" | "network") so one
collection serves all four lists.

Products are matched to an option by the slug stored on the product
(`recharge_state` / `recharge_network`), so an option can be renamed without
orphaning the catalogue.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import require_admin, require_admin_role
from core.utils import now_utc, audit_log as _audit_log

logger = logging.getLogger(__name__)
router = APIRouter()

KINDS = ("mobile", "dth")
GROUPS = ("state", "network")

# Seeded on first read so the screen is never empty. These are exactly the
# values the owner listed; everything else is added in-app.
DEFAULTS: List[Dict[str, Any]] = [
    {"kind": "mobile", "group": "state",   "name": "Andhra Pradesh, Telangana (AP&TG)", "sort_order": 0},
    {"kind": "mobile", "group": "network", "name": "Airtel", "sort_order": 0},
    {"kind": "mobile", "group": "network", "name": "Jio",    "sort_order": 1},
    {"kind": "mobile", "group": "network", "name": "Vi",     "sort_order": 2},
    {"kind": "mobile", "group": "network", "name": "BSNL",   "sort_order": 3},
    {"kind": "dth",    "group": "state",   "name": "Andhra Pradesh, Telangana (AP&TG)", "sort_order": 0},
    {"kind": "dth",    "group": "network", "name": "Tata Play",          "sort_order": 0},
    {"kind": "dth",    "group": "network", "name": "Airtel Digital TV",  "sort_order": 1},
    {"kind": "dth",    "group": "network", "name": "Dish TV",            "sort_order": 2},
    {"kind": "dth",    "group": "network", "name": "d2h",                "sort_order": 3},
    {"kind": "dth",    "group": "network", "name": "Sun Direct",         "sort_order": 4},
]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    return s.strip("-") or uuid.uuid4().hex[:8]


class OptionIn(BaseModel):
    kind: str
    group: str
    name: str
    sort_order: Optional[int] = None


async def seed_defaults() -> None:
    """Idempotent — only inserts what is missing."""
    if await db.recharge_options.count_documents({}) > 0:
        return
    ts = now_utc().isoformat()
    await db.recharge_options.insert_many([
        {**d, "id": str(uuid.uuid4()), "slug": slugify(d["name"]),
         "active": True, "created_at": ts, "updated_at": ts}
        for d in DEFAULTS
    ])
    logger.info("recharge options seeded")


# ─────────────────────────────────────────────────────────────────────
# Jun-2026 owner request — the operator list IS the Recharge
# sub-category tree.
#
# Before this, "Networks / Operators" (recharge_options) and
# Shop Categories → Recharge → <sub-category> were two unrelated lists.
# A vendor picking "Airtel" when adding a product therefore needed the
# admin to have hand-created that sub-category, and the plan never
# showed up on the Recharge screen because the product carried no
# `recharge_network` tag. Now ONE list drives both: adding an operator
# creates its sub-category, removing one hides it.
#
#   Recharge                      ← root shop category
#     ├─ Mobile Recharge          ← per-kind group
#     │    ├─ Airtel  Jio  Vi …   ← one per ACTIVE network option
#     └─ DTH TV Recharge
#          └─ Tata Play  Dish TV …
# ─────────────────────────────────────────────────────────────────────
RECHARGE_ROOT_NAME = "Recharge"
KIND_CATEGORY = {"mobile": "Mobile Recharge", "dth": "DTH TV Recharge"}
KIND_ICON = {"mobile": "cellphone", "dth": "television"}


def _name_rx(name: str) -> Dict[str, str]:
    return {"$regex": f"^{re.escape((name or '').strip())}$", "$options": "i"}


async def _upsert_category(
    name: str,
    parent_id: Optional[str],
    depth: int,
    extra: Dict[str, Any],
    match: Dict[str, Any],
) -> str:
    """Create or refresh ONE shop_categories row, returning its id.

    `match` finds an existing row (either a previously-synced one or a
    category the admin had already created by hand with the same name, so
    we adopt it instead of making a duplicate).
    """
    from routes.shop_categories import _slugify

    now = datetime.utcnow()
    row = await db.shop_categories.find_one(match, {"_id": 0})
    fields = {
        "name": name,
        "slug": _slugify(name),
        "parent_id": parent_id,
        "depth": depth,
        "active": True,
        "updated_at": now,
        **extra,
    }
    if row:
        changed = {k: v for k, v in fields.items() if row.get(k) != v}
        changed.pop("updated_at", None)
        if changed:
            await db.shop_categories.update_one(
                {"id": row["id"]}, {"$set": {**changed, "updated_at": now}},
            )
        return row["id"]
    doc = {
        "id": str(uuid.uuid4()),
        "icon_pack": "mci",
        "icon_name": "cellphone",
        "image_url": None,
        "color": "#E0E7FF",
        "sort_order": 0,
        "created_at": now,
        **fields,
    }
    await db.shop_categories.insert_one(dict(doc))
    return doc["id"]


async def sync_shop_categories() -> Dict[str, Any]:
    """Mirror the ACTIVE network options into the Recharge category tree.

    Idempotent and write-light: a row is only touched when a field
    actually differs, so this is safe to call on every options read.
    """
    root_id = await _upsert_category(
        RECHARGE_ROOT_NAME, None, 0,
        {"recharge_root": True, "icon_pack": "mci", "icon_name": "cellphone-wireless"},
        {"parent_id": None, "$or": [{"recharge_root": True}, {"name": _name_rx(RECHARGE_ROOT_NAME)}]},
    )

    synced: List[str] = []
    hidden: List[str] = []
    for kind, label in KIND_CATEGORY.items():
        group_id = await _upsert_category(
            label, root_id, 1,
            {"recharge_kind": kind, "recharge_group": "kind",
             "icon_pack": "mci", "icon_name": KIND_ICON[kind]},
            {"parent_id": root_id,
             "$or": [{"recharge_kind": kind, "recharge_group": "kind"}, {"name": _name_rx(label)}]},
        )
        options = await db.recharge_options.find(
            {"kind": kind, "group": "network"}, {"_id": 0},
        ).to_list(500)
        live_slugs = {o["slug"] for o in options if o.get("active")}
        for i, o in enumerate(options):
            if not o.get("active"):
                continue
            await _upsert_category(
                o["name"], group_id, 2,
                {"recharge_kind": kind, "recharge_network": o["slug"],
                 "recharge_option_id": o["id"], "recharge_synced": True,
                 "sort_order": int(o.get("sort_order") or i),
                 "icon_pack": "mci", "icon_name": KIND_ICON[kind]},
                # Adopt by option id first, then by name anywhere under the
                # Recharge tree (an operator the admin typed in by hand).
                {"$or": [
                    {"recharge_option_id": o["id"]},
                    {"parent_id": {"$in": [root_id, group_id]}, "name": _name_rx(o["name"])},
                ]},
            )
            synced.append(o["name"])
        async for c in db.shop_categories.find(
            {"parent_id": group_id, "recharge_synced": True, "active": True}, {"_id": 0},
        ):
            if c.get("recharge_network") not in live_slugs:
                await db.shop_categories.update_one(
                    {"id": c["id"]},
                    {"$set": {"active": False, "updated_at": datetime.utcnow()}},
                )
                hidden.append(c.get("name") or "")
    return {"root_id": root_id, "synced": synced, "hidden": hidden}


async def option_product_count(row: Dict[str, Any]) -> int:
    """How many products are listed under this option.

    Counts BOTH shapes: plans tagged with the option slug
    (`recharge_state` / `recharge_network`) and vendor products that
    simply picked the mirrored sub-category by name.
    """
    field = "recharge_state" if row.get("group") == "state" else "recharge_network"
    rx = _name_rx(row.get("name") or "")
    return await db.products.count_documents({"$or": [
        {field: row.get("slug")},
        {"subcategory": rx},
        {"sub_category": rx},
    ]})


@router.get("/recharge/options")
async def list_options(kind: Optional[str] = None) -> Dict[str, Any]:
    """Every option, grouped so the screen can render the two dropdowns
    without filtering client-side."""
    await seed_defaults()
    try:
        await sync_shop_categories()
    except Exception as e:  # never let the mirror break the screen
        logger.warning(f"recharge category sync failed: {e}")
    q: Dict[str, Any] = {"active": True}
    if kind in KINDS:
        q["kind"] = kind
    rows = await db.recharge_options.find(q, {"_id": 0}).to_list(2000)
    rows.sort(key=lambda r: (r.get("sort_order", 0), r.get("name", "")))

    def pick(k: str, g: str) -> List[Dict[str, Any]]:
        return [r for r in rows if r.get("kind") == k and r.get("group") == g]

    return {
        "mobile": {"states": pick("mobile", "state"), "networks": pick("mobile", "network")},
        "dth":    {"states": pick("dth", "state"),    "networks": pick("dth", "network")},
        "types": [
            {"key": "mobile", "label": "Mobile Recharge", "icon": "smartphone",
             "description": "Prepaid & postpaid top-ups for every network"},
            {"key": "dth", "label": "DTH TV Recharge", "icon": "tv",
             "description": "Recharge your set-top box in seconds"},
        ],
    }


@router.post("/admin/recharge/options")
async def create_option(
    payload: OptionIn,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "products_manager")),
) -> Dict[str, Any]:
    if payload.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {KINDS}")
    if payload.group not in GROUPS:
        raise HTTPException(status_code=400, detail=f"group must be one of {GROUPS}")
    name = (payload.name or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters")
    slug = slugify(name)
    existing = await db.recharge_options.find_one(
        {"kind": payload.kind, "group": payload.group, "slug": slug}, {"_id": 0},
    )
    if existing:
        if existing.get("active"):
            raise HTTPException(status_code=409, detail=f"“{name}” already exists in this list")
        # Re-activate rather than create a duplicate, so products that still
        # point at this slug come back to life with it.
        await db.recharge_options.update_one(
            {"id": existing["id"]},
            {"$set": {"active": True, "name": name, "updated_at": now_utc().isoformat()}},
        )
        await sync_shop_categories()
        return {**existing, "active": True, "name": name, "restored": True}

    if payload.sort_order is None:
        last = await db.recharge_options.find(
            {"kind": payload.kind, "group": payload.group},
        ).sort("sort_order", -1).limit(1).to_list(1)
        sort_order = int((last[0].get("sort_order") if last else -1) or -1) + 1
    else:
        sort_order = int(payload.sort_order)

    ts = now_utc().isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "kind": payload.kind,
        "group": payload.group,
        "name": name,
        "slug": slug,
        "sort_order": sort_order,
        "active": True,
        "created_at": ts,
        "updated_at": ts,
    }
    await db.recharge_options.insert_one(dict(doc))
    await sync_shop_categories()
    await _audit_log(admin, "recharge.option_add", "recharge_option", doc["id"],
                     {"kind": payload.kind, "group": payload.group, "name": name})
    return doc


@router.delete("/admin/recharge/options/{option_id}")
async def delete_option(
    option_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "products_manager")),
) -> Dict[str, Any]:
    """Remove an option. BLOCKED while products are still listed under it
    (owner's call — a silent hide would orphan a vendor's live plans)."""
    row = await db.recharge_options.find_one({"id": option_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="Option not found")
    in_use = await option_product_count(row)
    if in_use > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Can't remove “{row.get('name')}” — {in_use} product"
                f"{'s' if in_use != 1 else ''} are still listed under it. "
                f"Move or delete those products first."
            ),
        )
    await db.recharge_options.update_one(
        {"id": option_id},
        {"$set": {"active": False, "updated_at": now_utc().isoformat()}},
    )
    await sync_shop_categories()
    await _audit_log(admin, "recharge.option_delete", "recharge_option", option_id,
                     {"name": row.get("name"), "products_tagged": in_use})
    return {"ok": True, "removed": row.get("name"), "products_tagged": in_use}


@router.post("/admin/recharge/options/sync")
async def resync_categories(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "products_manager")),
) -> Dict[str, Any]:
    """Force-rebuild the Recharge sub-category tree from the option lists."""
    await seed_defaults()
    return await sync_shop_categories()


@router.get("/recharge/products")
async def recharge_products(
    kind: str,
    state: Optional[str] = None,
    network: Optional[str] = None,
) -> Dict[str, Any]:
    """Plans for one state + network, grouped by their own subcategory so the
    screen can show "Unlimited", "Data add-on" etc. under the dropdowns.

    Jun-2026 — this also has to list plans a VENDOR added from his own
    product form. Those carry no `recharge_*` tags; all they have is the
    mirrored sub-category name ("Airtel"), so we match on that too and
    treat a missing state tag as "available in every circle".
    """
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {KINDS}")
    ands: List[Dict[str, Any]] = [
        {"active": {"$ne": False}},
        # Vendor products only go live once an admin publishes them; the
        # seeded/admin plans carry no flag at all.
        {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}, {"is_published": None}]},
    ]
    net_name = ""
    if network:
        opt = await db.recharge_options.find_one(
            {"kind": kind, "group": "network", "slug": network}, {"_id": 0},
        )
        net_name = (opt or {}).get("name") or ""
        net_or: List[Dict[str, Any]] = [{"recharge_network": network}]
        if net_name:
            rx = _name_rx(net_name)
            net_or += [{"subcategory": rx}, {"sub_category": rx}]
        ands.append({"$or": net_or})
        ands.append({"$or": [
            {"recharge_kind": kind},
            {"recharge_kind": {"$exists": False}},
            {"recharge_kind": None},
        ]})
    else:
        ands.append({"recharge_kind": kind})
    if state:
        ands.append({"$or": [
            {"recharge_state": state},
            {"recharge_state": {"$exists": False}},
            {"recharge_state": None},
        ]})
    rows = await db.products.find(
        {"$and": ands}, {"_id": 0, "device_units": 0},
    ).limit(500).to_list(500)
    rows.sort(key=lambda r: float(r.get("price") or 0))
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for p in rows:
        label = (p.get("subcategory") or p.get("sub_category") or "Plans").strip()
        if net_name and label.lower() == net_name.lower():
            label = "Plans"
        groups.setdefault(label or "Plans", []).append(p)
    return {
        "count": len(rows),
        "groups": [{"name": k, "products": v} for k, v in groups.items()],
    }
