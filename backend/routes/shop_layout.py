"""
Shop Layout — admin-managed content blocks rendered on the customer Shop tab
and on category pages. JSON-driven; mobile app does NOT hardcode home layout.

BLOCK TYPES (12):
  Hero / Banners:  banner_slider, background (single banner), announcement_strip
  Navigation:      category_circles, brand_slider
  Products:        product_grid, horizontal_slider, content_box, flash_sale
  Promo:           offer_cards
  Typography:      section_header, text

SCOPE:
  scope="home"      → rendered on /(tabs)/shop
  scope="category"  → rendered on /shop-category/{scope_category}

ENDPOINTS:
  GET    /api/shop-layout                       (public; ?scope=&category=)
  GET    /api/admin/shop-layout                 (admin; ?scope=&category=)
  POST   /api/admin/shop-layout                 (admin; extended payload)
  PATCH  /api/admin/shop-layout/{id}            (admin; partial update)
  DELETE /api/admin/shop-layout/{id}            (admin)
  POST   /api/admin/shop-layout/reorder         (admin; bulk reorder)
  POST   /api/admin/shop-layout/migrate-banners (admin; one-time migration)
"""
from __future__ import annotations
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.db import db
from core.image_compress import compress_data_url
from core.security import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_TYPES = {
    # legacy / existing
    "background", "section_header", "text", "content_box",
    # new
    "banner_slider", "product_grid", "horizontal_slider",
    "category_circles", "flash_sale", "offer_cards",
    "brand_slider", "announcement_strip",
    # Jun 2026 — "Spotlight": a full-width immersive showcase card sized to
    # ~1/3 of a 6-inch phone screen. Swipeable when the admin adds several
    # slides; each slide can deep-link to a product, a category, or the
    # block's own product list via "View more".
    "spotlight",
}
ALLOWED_SCOPES = {"home", "category"}
ALLOWED_DATA_SOURCES = {"manual", "trending", "new", "best", "category"}
ALLOWED_LAYOUT_STYLES = {"grid", "list", "horizontal"}
ALLOWED_ALIGN = {"left", "center", "right"}


# ---------- Models ----------

class LayoutItem(BaseModel):
    """Generic item used for category_circles, brand_slider, offer_cards,
    banner_slider slides etc."""
    label: Optional[str] = ""
    subtitle: Optional[str] = ""
    image_data_url: Optional[str] = Field(default="", max_length=4_000_000)
    link_type: Optional[str] = None  # "product" | "category" | None
    link_value: Optional[str] = ""
    color: Optional[str] = ""
    # August 2026 — how the renderer should fit the image inside the block:
    #   "cover"   (default) — image fills the frame, may crop edges
    #   "contain" — full image visible, letterboxed with `color` / bg_color
    image_fit: Optional[str] = "cover"


class ShopLayoutBlockIn(BaseModel):
    block_type: str = Field(..., min_length=1, max_length=32)
    # scope routing
    scope: Optional[str] = "home"
    scope_category: Optional[str] = ""
    # Nov 2026 — Pincode-scoped layouts.  When set, this block ONLY
    # renders for customers whose delivery pincode matches.  Allows
    # per-area campaigns (e.g. Tirupati-only banner).  Empty = no
    # pincode restriction (block renders for all customers on the
    # given scope).
    scope_pincode: Optional[str] = ""
    # Jun 2026 — MULTI-pincode targeting.  Supersedes the single
    # `scope_pincode` above (which is kept for backward compatibility with
    # every block created before this change).  A block renders when the
    # customer's pincode appears in this list.  Empty list + empty
    # `scope_pincode` = global block (renders everywhere).
    scope_pincodes: Optional[List[str]] = None
    # core
    title: Optional[str] = ""
    subtitle: Optional[str] = ""
    body: Optional[str] = ""
    cta_label: Optional[str] = ""
    sort_order: int = 0
    active: bool = True
    size: Optional[str] = "medium"
    image_data_url: Optional[str] = Field(default="", max_length=4_000_000)
    # August 2026 — see LayoutItem.image_fit docstring above.
    image_fit: Optional[str] = "cover"
    product_id: Optional[str] = None
    # styling overrides
    text_color: Optional[str] = ""
    bg_color: Optional[str] = ""
    font_size: Optional[int] = None
    text_align: Optional[str] = ""
    button_color: Optional[str] = ""
    button_text_color: Optional[str] = ""
    height: Optional[int] = None
    # data binding
    product_ids: Optional[List[str]] = None
    data_source: Optional[str] = "manual"
    product_count: Optional[int] = 10
    layout_style: Optional[str] = "grid"
    category_filter: Optional[str] = ""
    items: Optional[List[LayoutItem]] = None
    flash_sale_ends_at: Optional[str] = ""
    # Grid layout extras
    products_per_row: Optional[int] = 2          # 1..4 (product_grid only)
    show_view_all: Optional[bool] = False        # show top-right "View More" link
    view_all_link: Optional[str] = ""            # category name or "" for /shop
    # Sept 2026 — For `category_circles` blocks only.  Explicit list of
    # `shop_categories.id` values to show in this block.  Empty list means
    # "auto-show every category not already used in ANOTHER category_circles
    # block on this scope" (see renderer for the auto-dedupe logic).
    category_ids: Optional[List[str]] = None


class ShopLayoutBlockPatch(BaseModel):
    block_type: Optional[str] = None
    scope: Optional[str] = None
    scope_category: Optional[str] = None
    scope_pincode: Optional[str] = None
    scope_pincodes: Optional[List[str]] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    body: Optional[str] = None
    cta_label: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None
    size: Optional[str] = None
    image_data_url: Optional[str] = None
    image_fit: Optional[str] = None
    product_id: Optional[str] = None
    text_color: Optional[str] = None
    bg_color: Optional[str] = None
    font_size: Optional[int] = None
    text_align: Optional[str] = None
    button_color: Optional[str] = None
    button_text_color: Optional[str] = None
    height: Optional[int] = None
    product_ids: Optional[List[str]] = None
    data_source: Optional[str] = None
    product_count: Optional[int] = None
    layout_style: Optional[str] = None
    category_filter: Optional[str] = None
    items: Optional[List[LayoutItem]] = None
    flash_sale_ends_at: Optional[str] = None
    products_per_row: Optional[int] = None
    show_view_all: Optional[bool] = None
    view_all_link: Optional[str] = None
    category_ids: Optional[List[str]] = None


class ReorderItem(BaseModel):
    id: str
    sort_order: int


class ReorderRequest(BaseModel):
    items: List[ReorderItem]


# ---------- Helpers ----------

def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return {}
    doc.pop("_id", None)
    # Backfill new fields on legacy docs so the client sees a consistent shape.
    doc.setdefault("scope", "home")
    doc.setdefault("scope_category", "")
    doc.setdefault("scope_pincode", "")
    doc.setdefault("text_color", "")
    doc.setdefault("bg_color", "")
    doc.setdefault("font_size", None)
    doc.setdefault("text_align", "")
    doc.setdefault("button_color", "")
    doc.setdefault("button_text_color", "")
    doc.setdefault("height", None)
    doc.setdefault("product_ids", [])
    doc.setdefault("data_source", "manual")
    doc.setdefault("product_count", 10)
    doc.setdefault("layout_style", "grid")
    doc.setdefault("category_filter", "")
    doc.setdefault("items", [])
    doc.setdefault("flash_sale_ends_at", "")
    doc.setdefault("products_per_row", 2)
    doc.setdefault("show_view_all", False)
    doc.setdefault("view_all_link", "")
    doc.setdefault("category_ids", [])
    # Jun 2026 — Multi-pincode backfill: legacy blocks only carry the single
    # `scope_pincode`, so surface it as a one-item list for the admin UI.
    if not doc.get("scope_pincodes"):
        legacy_pin = str(doc.get("scope_pincode") or "").strip()
        doc["scope_pincodes"] = [legacy_pin] if legacy_pin else []
    # Aug 2026 — image_fit + per-slide image_fit backfill for legacy docs.
    doc.setdefault("image_fit", "cover")
    for it in doc.get("items") or []:
        if isinstance(it, dict):
            it.setdefault("image_fit", "cover")
    return doc


# ── Jun 2026 (Phase 5B) — never ship base64 artwork inside a LIST ────────
#
# Banner / offer / category artwork is stored as a base64 data URL (up to
# 4 MB each, 30 slides per block, 200 blocks per response). A home screen
# with a few real banners therefore answered `GET /shop-layout` with tens of
# megabytes of JSON — which is exactly what makes the edge proxy give up with
# "could not parse the response". Lists now hand back a tiny IMAGE URL and
# the bytes are streamed on demand (and cached) from the endpoints below.
IMAGE_URL_PREFIX = "/api/shop-layout"


def _is_managed_image_url(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(f"{IMAGE_URL_PREFIX}/") and v.endswith("/image")


def _slim_images(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Swap inline base64 for the on-demand image endpoint (list responses)."""
    if not doc:
        return doc
    bid = doc.get("id")
    if isinstance(doc.get("image_data_url"), str) and doc["image_data_url"].startswith("data:"):
        doc["image_data_url"] = f"{IMAGE_URL_PREFIX}/{bid}/image"
    items = doc.get("items") or []
    for idx, it in enumerate(items):
        if isinstance(it, dict) and isinstance(it.get("image_data_url"), str) and it["image_data_url"].startswith("data:"):
            it["image_data_url"] = f"{IMAGE_URL_PREFIX}/{bid}/items/{idx}/image"
    return doc


def _serialize_slim(doc: Dict[str, Any]) -> Dict[str, Any]:
    return _slim_images(_serialize(doc))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_type(t: Optional[str]) -> str:
    if not t:
        raise HTTPException(status_code=400, detail="block_type is required")
    if t not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"block_type must be one of {sorted(ALLOWED_TYPES)}")
    return t


def _scope_filter(scope: Optional[str], category: Optional[str], pincode: Optional[str] = None, admin_view: bool = False) -> Dict[str, Any]:
    """Build the Mongo query used by both the public and admin
    shop-layout endpoints.

    admin_view=True skips the strict "hide-targeted-when-no-pincode"
    guard so that the Admin UI can still see every block regardless of
    scope_pincode (they can then filter by pincode explicitly).
    """
    q: Dict[str, Any] = {}
    if scope:
        if scope not in ALLOWED_SCOPES:
            raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(ALLOWED_SCOPES)}")
        # treat missing scope as "home" for backward compat
        if scope == "home":
            q["$or"] = [{"scope": "home"}, {"scope": {"$exists": False}}, {"scope": None}, {"scope": ""}]
        else:
            q["scope"] = "category"
            if category:
                q["scope_category"] = category
    # Jun 2026 → MULTI-pincode targeting.  A block can now carry a LIST of
    # pincodes in `scope_pincodes`; the legacy single `scope_pincode` field
    # is still honoured so pre-existing blocks keep working untouched.
    #
    # Semantics for the PUBLIC /shop-layout endpoint:
    #   • When the customer's pincode IS known, we return blocks that list
    #     that pincode (in either field) PLUS global blocks (both fields
    #     empty).
    #   • When the customer's pincode is UNKNOWN (missing or empty), we
    #     ONLY return the global blocks — pincode-targeted campaigns
    #     must never leak to customers whose location we can't verify.
    #     (Bug fix Jul 2026: previously we returned every block in this
    #     branch, so a "Srikalahasti Sale" block was visible to
    #     Cuddapah users.)
    #
    # Admin view bypasses this and can see everything (with the option
    # to explicitly filter by pincode).
    global_only = {
        "$and": [
            {"$or": [
                {"scope_pincode": {"$in": ["", None]}},
                {"scope_pincode": {"$exists": False}},
            ]},
            {"$or": [
                {"scope_pincodes": {"$in": [[], None]}},
                {"scope_pincodes": {"$exists": False}},
            ]},
        ],
    }
    pin_filter: Dict[str, Any] = {}
    if pincode:
        pin_filter = {
            "$or": [
                {"scope_pincode": pincode},
                # Mongo matches a scalar against every element of an array.
                {"scope_pincodes": pincode},
                global_only,
            ],
        }
    elif not admin_view:
        pin_filter = global_only
    if pin_filter:
        if q:
            q = {"$and": [q, pin_filter]}
        else:
            q = pin_filter
    return q


def _norm_pincodes(values: Optional[List[str]], legacy: Optional[str] = None) -> List[str]:
    """Normalise a multi-pincode target list.

    Jun 2026 — Keeps only 6-digit numeric pincodes, de-dupes while
    preserving admin ordering, caps at 50. The legacy single
    `scope_pincode` is folded in so old blocks upgrade transparently.
    """
    out: List[str] = []
    for raw in list(values or []) + ([legacy] if legacy else []):
        p = "".join(ch for ch in str(raw or "") if ch.isdigit())
        if len(p) == 6 and p not in out:
            out.append(p)
    return out[:50]


def _build_doc_from_in(body: ShopLayoutBlockIn) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "block_type": body.block_type,
        "scope": (body.scope if body.scope in ALLOWED_SCOPES else "home"),
        "scope_category": (body.scope_category or "").strip(),
        "scope_pincode": (body.scope_pincode or "").strip(),
        "scope_pincodes": _norm_pincodes(body.scope_pincodes, body.scope_pincode),
        "title": (body.title or "").strip(),
        "subtitle": (body.subtitle or "").strip(),
        "body": (body.body or "").strip(),
        "cta_label": (body.cta_label or "").strip(),
        "sort_order": int(body.sort_order or 0),
        "active": bool(body.active),
        "size": (body.size if body.size in ("small", "medium", "large") else "medium"),
        "image_data_url": body.image_data_url or "",
        # Aug 2026 — persist the fit mode so the renderer knows whether to
        # crop (`cover`) or letterbox (`contain`).
        "image_fit": (body.image_fit if body.image_fit in ("cover", "contain") else "cover"),
        "product_id": (body.product_id or "").strip() or None,
        "text_color": (body.text_color or "").strip(),
        "bg_color": (body.bg_color or "").strip(),
        "font_size": body.font_size if isinstance(body.font_size, int) else None,
        "text_align": (body.text_align if body.text_align in ALLOWED_ALIGN else ""),
        "button_color": (body.button_color or "").strip(),
        "button_text_color": (body.button_text_color or "").strip(),
        "height": body.height if isinstance(body.height, int) else None,
        "product_ids": [str(p) for p in (body.product_ids or [])][:500],
        "data_source": (body.data_source if body.data_source in ALLOWED_DATA_SOURCES else "manual"),
        "product_count": max(1, min(500, int(body.product_count or 10))),
        "layout_style": (body.layout_style if body.layout_style in ALLOWED_LAYOUT_STYLES else "grid"),
        "category_filter": (body.category_filter or "").strip(),
        "items": [i.dict() for i in (body.items or [])][:30],
        "flash_sale_ends_at": (body.flash_sale_ends_at or "").strip(),
        "products_per_row": max(1, min(4, int(body.products_per_row or 2))),
        "show_view_all": bool(body.show_view_all),
        "view_all_link": (body.view_all_link or "").strip(),
        "category_ids": [str(cid) for cid in (body.category_ids or [])][:50],
        "created_at": _now(),
        "updated_at": _now(),
    }


def _build_updates(payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Phase 5B — the client now receives an image URL instead of the base64
    # blob, so a plain "save" round-trips that URL back to us. Treat it as
    # "image unchanged" and keep the stored artwork instead of destroying it.
    existing = existing or {}
    existing_items = existing.get("items") or []
    if _is_managed_image_url(payload.get("image_data_url")):
        payload = {k: v for k, v in payload.items() if k != "image_data_url"}
    elif str(payload.get("image_data_url") or "").startswith("data:"):
        payload = {**payload, "image_data_url": compress_data_url(payload["image_data_url"]) or payload["image_data_url"]}
    if isinstance(payload.get("items"), list):
        merged_items = []
        for it in payload["items"]:
            src = dict(it) if isinstance(it, dict) else it
            if isinstance(src, dict) and _is_managed_image_url(src.get("image_data_url")):
                m = re.search(r"/items/(\d+)/image$", str(src["image_data_url"]))
                old_idx = int(m.group(1)) if m else -1
                old = existing_items[old_idx] if 0 <= old_idx < len(existing_items) else {}
                src["image_data_url"] = (old or {}).get("image_data_url") or ""
            if isinstance(src, dict) and str(src.get("image_data_url") or "").startswith("data:"):
                # Sep 2026 — compress on the way in. A raw camera-roll photo
                # can exceed the 4 MB field cap and the save came back as a
                # bare validation error ("save failed") with no clue why.
                src["image_data_url"] = compress_data_url(src["image_data_url"]) or src["image_data_url"]
            merged_items.append(src)
        payload = {**payload, "items": merged_items}
    updates: Dict[str, Any] = {}
    if "block_type" in payload and payload["block_type"] is not None:
        updates["block_type"] = _validate_type(payload["block_type"])
    if "scope" in payload and payload["scope"] is not None:
        s = str(payload["scope"]).strip().lower()
        if s and s not in ALLOWED_SCOPES:
            raise HTTPException(status_code=400, detail=f"scope must be one of {sorted(ALLOWED_SCOPES)}")
        updates["scope"] = s or "home"
    for f in ("scope_category", "scope_pincode", "title", "subtitle", "body", "cta_label",
              "text_color", "bg_color", "button_color", "button_text_color",
              "category_filter", "flash_sale_ends_at"):
        if f in payload and payload[f] is not None:
            updates[f] = str(payload[f]).strip()
    if "image_data_url" in payload and payload["image_data_url"] is not None:
        updates["image_data_url"] = payload["image_data_url"]
    # Aug 2026 — Persist the block-level image_fit toggle on PATCH.
    if "image_fit" in payload and payload["image_fit"] is not None:
        v = str(payload["image_fit"]).strip().lower()
        if v in ("cover", "contain"):
            updates["image_fit"] = v
    if "product_id" in payload:
        v = payload["product_id"]
        updates["product_id"] = (str(v).strip() if v else None) or None
    # Jun 2026 — Multi-pincode targeting. When the client sends the list we
    # rewrite BOTH fields so the legacy single-pincode readers stay correct.
    if "scope_pincodes" in payload and payload["scope_pincodes"] is not None:
        pins = _norm_pincodes(payload["scope_pincodes"])
        updates["scope_pincodes"] = pins
        updates["scope_pincode"] = pins[0] if len(pins) == 1 else ""
    elif "scope_pincode" in payload and payload["scope_pincode"] is not None:
        pins = _norm_pincodes(None, payload["scope_pincode"])
        updates["scope_pincodes"] = pins
    if "sort_order" in payload and payload["sort_order"] is not None:
        updates["sort_order"] = int(payload["sort_order"])
    if "active" in payload and payload["active"] is not None:
        updates["active"] = bool(payload["active"])
    if "size" in payload and payload["size"] is not None:
        s = str(payload["size"]).lower()
        if s in ("small", "medium", "large"):
            updates["size"] = s
    if "font_size" in payload and payload["font_size"] is not None:
        try:
            updates["font_size"] = int(payload["font_size"])
        except (TypeError, ValueError):
            pass
    if "text_align" in payload and payload["text_align"] is not None:
        a = str(payload["text_align"]).lower()
        if a in ALLOWED_ALIGN or a == "":
            updates["text_align"] = a
    if "height" in payload and payload["height"] is not None:
        try:
            updates["height"] = int(payload["height"])
        except (TypeError, ValueError):
            pass
    if "product_ids" in payload and payload["product_ids"] is not None:
        updates["product_ids"] = [str(p) for p in payload["product_ids"]][:500]
    if "data_source" in payload and payload["data_source"] is not None:
        ds = str(payload["data_source"]).strip().lower()
        if ds in ALLOWED_DATA_SOURCES:
            updates["data_source"] = ds
    if "product_count" in payload and payload["product_count"] is not None:
        try:
            updates["product_count"] = max(1, min(500, int(payload["product_count"])))
        except (TypeError, ValueError):
            pass
    if "layout_style" in payload and payload["layout_style"] is not None:
        ls = str(payload["layout_style"]).strip().lower()
        if ls in ALLOWED_LAYOUT_STYLES:
            updates["layout_style"] = ls
    if "items" in payload and payload["items"] is not None:
        cleaned: List[Dict[str, Any]] = []
        for it in payload["items"][:30]:
            if isinstance(it, dict):
                cleaned.append({
                    "label": str(it.get("label") or "").strip(),
                    "subtitle": str(it.get("subtitle") or "").strip(),
                    "image_data_url": it.get("image_data_url") or "",
                    "link_type": (str(it.get("link_type") or "").strip() or None),
                    "link_value": str(it.get("link_value") or "").strip(),
                    "color": str(it.get("color") or "").strip(),
                    # Aug 2026 — preserve per-slide image_fit through PATCH.
                    "image_fit": (
                        it.get("image_fit")
                        if it.get("image_fit") in ("cover", "contain")
                        else "cover"
                    ),
                })
        updates["items"] = cleaned
    if "products_per_row" in payload and payload["products_per_row"] is not None:
        try:
            updates["products_per_row"] = max(1, min(4, int(payload["products_per_row"])))
        except (TypeError, ValueError):
            pass
    if "show_view_all" in payload and payload["show_view_all"] is not None:
        updates["show_view_all"] = bool(payload["show_view_all"])
    if "view_all_link" in payload and payload["view_all_link"] is not None:
        updates["view_all_link"] = str(payload["view_all_link"]).strip()
    if "category_ids" in payload and payload["category_ids"] is not None:
        updates["category_ids"] = [str(c) for c in payload["category_ids"]][:50]
    return updates


# ---------- Public ----------

@router.get("/shop-layout")
async def list_active_shop_layout(
    scope: Optional[str] = Query("home"),
    category: Optional[str] = Query(None),
    pincode: Optional[str] = Query(None, description="Nov 2026 — customer delivery pincode; matches pincode-scoped blocks"),
):
    """Public read for the mobile app — NO AUTH REQUIRED so unauthenticated
    customers (e.g. on a marketing landing or pre-login browse) can still see
    the merchandised home. Returns active blocks for the requested scope
    (default 'home'). For scope='category', filter by `scope_category`.
    When `pincode` is provided, pincode-scoped blocks matching AND global
    (empty scope_pincode) blocks are returned; other pincode blocks are excluded."""
    q = _scope_filter(scope, category, pincode)
    q["active"] = True
    cursor = db.shop_layout_blocks.find(q).sort([("sort_order", 1), ("created_at", 1)])
    items = [_serialize_slim(d) for d in await cursor.to_list(200)]
    return {"items": items, "scope": scope or "home", "category": category or "", "pincode": pincode or ""}


@router.get("/shop-layout/curated-product-ids")
async def curated_product_ids(
    pincode: Optional[str] = Query(None, description="Customer delivery pincode"),
):
    """Nov 2026 — every product id an admin pinned into ANY active block.

    The shop hides these from the plain browse grids, so a curated product
    appears inside its block only instead of being listed twice. Both the shop
    home and the category screens need the FULL set (a product pinned into a
    home block must also vanish from the category screen), which is why this
    is scope-less. Pincode-targeted blocks only count for that pincode.
    """
    q: Dict[str, Any] = {"active": True}
    # Mirror the public visibility rules for pincode-targeted blocks: a block
    # the shopper can't see must not hide its products either (without a
    # pincode only GLOBAL blocks render, so only those count here).
    global_only = [
        {"$or": [{"scope_pincodes": {"$in": [None, []]}}, {"scope_pincodes": {"$exists": False}}]},
        {"$or": [{"scope_pincode": {"$in": [None, ""]}}, {"scope_pincode": {"$exists": False}}]},
    ]
    if pincode:
        q["$or"] = [
            {"scope_pincodes": pincode},
            {"scope_pincode": pincode},
            {"$and": global_only},
        ]
    else:
        q["$and"] = global_only
    cursor = db.shop_layout_blocks.find(q, {"_id": 0, "product_ids": 1, "product_id": 1})
    ids: List[str] = []
    for d in await cursor.to_list(500):
        for pid in (d.get("product_ids") or []):
            if pid:
                ids.append(str(pid))
        if d.get("product_id"):
            ids.append(str(d["product_id"]))
    unique = sorted(set(ids))
    return {"items": unique, "count": len(unique)}


# ── Image endpoints (Phase 5B) ───────────────────────────────────────────

def _decode_data_url(data_url: str):
    """('image/png', b'...') from a base64 data URL, or (None, None)."""
    import base64
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None, None
    try:
        head, b64 = data_url.split(",", 1)
        mime = head[5:].split(";")[0] or "image/jpeg"
        return mime, base64.b64decode(b64)
    except Exception:
        return None, None


@router.get("/shop-layout/{block_id}/image")
async def shop_layout_block_image(block_id: str):
    doc = await db.shop_layout_blocks.find_one({"id": block_id}, {"_id": 0, "image_data_url": 1})
    mime, raw = _decode_data_url((doc or {}).get("image_data_url") or "")
    if not raw:
        raise HTTPException(status_code=404, detail="No image on this block")
    return Response(content=raw, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/shop-layout/{block_id}/items/{index}/image")
async def shop_layout_item_image(block_id: str, index: int):
    doc = await db.shop_layout_blocks.find_one({"id": block_id}, {"_id": 0, "items": 1})
    items = (doc or {}).get("items") or []
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail="No such slide")
    mime, raw = _decode_data_url((items[index] or {}).get("image_data_url") or "")
    if not raw:
        raise HTTPException(status_code=404, detail="No image on this slide")
    return Response(content=raw, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})


# ---------- Admin ----------

@router.get("/admin/shop-layout")
async def list_all_shop_layout(
    scope: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    pincode: Optional[str] = Query(None),
    _: Dict[str, Any] = Depends(require_admin),
):
    q = _scope_filter(scope, category, pincode, admin_view=True) if (scope or pincode) else {}
    cursor = db.shop_layout_blocks.find(q).sort([("sort_order", 1), ("created_at", 1)])
    items = [_serialize_slim(d) for d in await cursor.to_list(1000)]
    return {"items": items}


@router.post("/admin/shop-layout")
async def create_shop_layout_block(body: ShopLayoutBlockIn, _: Dict[str, Any] = Depends(require_admin)):
    _validate_type(body.block_type)
    doc = _build_doc_from_in(body)
    await db.shop_layout_blocks.insert_one(doc.copy())
    return _serialize_slim(doc)


@router.patch("/admin/shop-layout/{block_id}")
async def update_shop_layout_block(block_id: str, body: ShopLayoutBlockPatch, _: Dict[str, Any] = Depends(require_admin)):
    existing = await db.shop_layout_blocks.find_one({"id": block_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Block not found")
    payload = body.dict(exclude_unset=True)
    updates = _build_updates(payload, existing)
    if updates:
        updates["updated_at"] = _now()
        await db.shop_layout_blocks.update_one({"id": block_id}, {"$set": updates})
    refreshed = await db.shop_layout_blocks.find_one({"id": block_id})
    return _serialize_slim(refreshed)


@router.delete("/admin/shop-layout/{block_id}")
async def delete_shop_layout_block(block_id: str, _: Dict[str, Any] = Depends(require_admin)):
    res = await db.shop_layout_blocks.delete_one({"id": block_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"ok": True}


@router.post("/admin/shop-layout/reorder")
async def reorder_shop_layout_blocks(body: ReorderRequest, _: Dict[str, Any] = Depends(require_admin)):
    """Bulk reorder. Pass [{id, sort_order}, ...]. Used by drag-to-reorder UI."""
    n = 0
    for it in body.items:
        res = await db.shop_layout_blocks.update_one(
            {"id": it.id},
            {"$set": {"sort_order": int(it.sort_order), "updated_at": _now()}},
        )
        if res.matched_count:
            n += 1
    return {"ok": True, "updated": n}


@router.post("/admin/shop-layout/migrate-banners")
async def migrate_promo_banners(_: Dict[str, Any] = Depends(require_admin)):
    """One-time migration: collapse all `promo_banners` into a single
    `banner_slider` block on the home scope. Each banner becomes a slide
    item. Safe to run multiple times — only creates the block once."""
    existing = await db.shop_layout_blocks.find_one({"block_type": "banner_slider", "scope": "home"})
    cursor = db.promo_banners.find({}).sort([("sort_order", 1), ("created_at", 1)])
    promos = await cursor.to_list(50)
    if not promos:
        return {"ok": True, "migrated": 0, "message": "no promo banners to migrate"}
    items = [
        {
            "label": (p.get("title") or "").strip(),
            "subtitle": (p.get("subtitle") or "").strip(),
            "image_data_url": p.get("image_data_url") or "",
            "link_type": "product" if p.get("product_id") else None,
            "link_value": p.get("product_id") or "",
            "color": "",
        }
        for p in promos
    ]
    if existing:
        await db.shop_layout_blocks.update_one(
            {"id": existing["id"]},
            {"$set": {"items": items, "updated_at": _now()}},
        )
        return {"ok": True, "migrated": len(items), "block_id": existing["id"], "updated": True}
    doc = {
        "id": str(uuid.uuid4()),
        "block_type": "banner_slider",
        "scope": "home",
        "scope_category": "",
        "title": "Featured",
        "subtitle": "",
        "body": "",
        "cta_label": "Shop now",
        "sort_order": -100,  # put it at the very top
        "active": True,
        "size": "medium",
        "image_data_url": "",
        "product_id": None,
        "text_color": "",
        "bg_color": "",
        "font_size": None,
        "text_align": "",
        "button_color": "",
        "button_text_color": "",
        "height": 180,
        "product_ids": [],
        "data_source": "manual",
        "product_count": 10,
        "layout_style": "horizontal",
        "category_filter": "",
        "items": items,
        "flash_sale_ends_at": "",
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.shop_layout_blocks.insert_one(doc.copy())
    return {"ok": True, "migrated": len(items), "block_id": doc["id"], "updated": False}


# ────────────────────────────────────────────────────────────
# Quick-start: seed a sensible default Home layout
# ────────────────────────────────────────────────────────────

DEFAULT_HOME_PALETTE = {
    "primary": "#0F766E",         # emerald-700 (matches app theme)
    "primary_dark": "#064E3B",
    "accent": "#FDE68A",
    "white": "#FFFFFF",
    "ink": "#0F172A",
    "muted": "#6B7280",
    "red": "#DC2626",
    "amber": "#F59E0B",
}


def _seed_doc(
    *,
    block_type: str,
    sort_order: int,
    title: str = "",
    subtitle: str = "",
    body: str = "",
    cta_label: str = "",
    size: str = "medium",
    bg_color: str = "",
    text_color: str = "",
    button_color: str = "",
    button_text_color: str = "",
    height: Optional[int] = None,
    data_source: str = "manual",
    product_count: int = 8,
    layout_style: str = "grid",
    category_filter: str = "",
    items: Optional[List[Dict[str, Any]]] = None,
    flash_sale_ends_at: str = "",
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "block_type": block_type,
        "scope": "home",
        "scope_category": "",
        "title": title,
        "subtitle": subtitle,
        "body": body,
        "cta_label": cta_label,
        "sort_order": sort_order,
        "active": True,
        "size": size,
        "image_data_url": "",
        "product_id": None,
        "text_color": text_color,
        "bg_color": bg_color,
        "font_size": None,
        "text_align": "",
        "button_color": button_color,
        "button_text_color": button_text_color,
        "height": height,
        "product_ids": [],
        "data_source": data_source,
        "product_count": product_count,
        "layout_style": layout_style,
        "category_filter": category_filter,
        "items": items or [],
        "flash_sale_ends_at": flash_sale_ends_at,
        "created_at": _now(),
        "updated_at": _now(),
    }


@router.post("/admin/shop-layout/seed-default-home")
async def seed_default_home(_: Dict[str, Any] = Depends(require_admin)):
    """One-tap default Home layout for fresh installs / demos.

    Idempotent-ish: skips if any block already exists in scope=home so we
    don't double-seed. Caller must pass ?force=1 to overwrite, OR the admin
    can delete the existing blocks first. Inserts a curated set of 7 blocks:
      1. announcement_strip — welcome banner
      2. banner_slider      — promo banners (2 slides)
      3. category_circles   — dynamic from real categories
      4. flash_sale         — auto from newest products (24h timer)
      5. section_header     — "Trending now"
      6. product_grid       — top published products (auto, 8 items)
      7. offer_cards        — 3 lifestyle promo tiles
    """
    P = DEFAULT_HOME_PALETTE
    existing = await db.shop_layout_blocks.count_documents({"scope": "home"})
    if existing > 0:
        return {
            "ok": False,
            "skipped": True,
            "existing": existing,
            "message": (
                f"You already have {existing} block(s) in Home scope. "
                "Delete them first if you want a fresh seed."
            ),
        }

    # 24h flash sale end timestamp
    flash_end = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    docs: List[Dict[str, Any]] = []

    # 1. Announcement strip
    docs.append(_seed_doc(
        block_type="announcement_strip",
        sort_order=0,
        title="Free delivery on orders above ₹499 · COD available",
        bg_color=P["primary"],
        text_color=P["white"],
    ))

    # 2. Banner slider (2 slides)
    docs.append(_seed_doc(
        block_type="banner_slider",
        sort_order=1,
        size="medium",
        items=[
            {
                "label": "Big Days are here",
                "subtitle": "Up to 60% off across all categories",
                "image_data_url": "",
                "link_type": "category",
                "link_value": "",
                "color": P["primary"],
            },
            {
                "label": "New Arrivals",
                "subtitle": "Fresh styles every week",
                "image_data_url": "",
                "link_type": "category",
                "link_value": "",
                "color": P["primary_dark"],
            },
        ],
    ))

    # 3. Category circles (auto, from real categories)
    docs.append(_seed_doc(
        block_type="category_circles",
        sort_order=2,
        title="Shop by category",
        data_source="auto_categories",
        product_count=12,
        layout_style="circle",
    ))

    # 4. Flash sale strip (auto from newest products, 24h)
    docs.append(_seed_doc(
        block_type="flash_sale",
        sort_order=3,
        title="Flash Sale",
        subtitle="Hurry — deals end soon",
        data_source="auto_newest",
        product_count=10,
        layout_style="horizontal",
        flash_sale_ends_at=flash_end,
        bg_color="#FEF2F2",
    ))

    # 5. Section header
    docs.append(_seed_doc(
        block_type="section_header",
        sort_order=4,
        title="Trending now",
        subtitle="Most-loved by our customers",
        text_color=P["ink"],
    ))

    # 6. Product grid (auto, 8 items)
    docs.append(_seed_doc(
        block_type="product_grid",
        sort_order=5,
        data_source="auto_top_selling",
        product_count=8,
        layout_style="grid",
    ))

    # 7. Offer cards (3 lifestyle tiles)
    docs.append(_seed_doc(
        block_type="offer_cards",
        sort_order=6,
        title="Don't miss out",
        items=[
            {
                "label": "Cash on Delivery",
                "subtitle": "Pay when you receive",
                "color": P["primary"],
                "link_type": None,
            },
            {
                "label": "Easy 7-day returns",
                "subtitle": "Quick refund, no questions",
                "color": P["amber"],
                "link_type": None,
            },
            {
                "label": "Refer & Earn ₹400",
                "subtitle": "Invite friends, build your team",
                "color": P["primary_dark"],
                "link_type": None,
            },
        ],
    ))

    await db.shop_layout_blocks.insert_many([d.copy() for d in docs])
    return {
        "ok": True,
        "inserted": len(docs),
        "block_ids": [d["id"] for d in docs],
    }
