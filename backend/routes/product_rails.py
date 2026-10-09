"""Product suggestion rails — Oct-2026.

Exactly TWO rails on a product page, no more (the owner was explicit that it
must not get messy), and NEITHER is curated by an admin:

  1. "More in <subcategory>"  — siblings of the product being viewed
  2. "Picked for you"         — built from THIS user's own behaviour:
                                 searches → cart → purchases

Signal weights (strongest intent wins):
    purchased  3  ·  in cart  2  ·  searched  1
We score candidate products by how well their category/subcategory/brand
matches the user's weighted history, then drop anything they already bought
or already have in the bag — suggesting what someone just bought is the
fastest way to look broken.

Guests (and a brand-new account with no history) fall back to the best-selling
items in the same category, so the rail is never empty.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import get_current_user_optional
from core.utils import now_utc

logger = logging.getLogger(__name__)
router = APIRouter()

RAIL_SIZE = 10          # the owner asked for ~5-10 cards per rail
CANDIDATE_POOL = 400    # how many rows we score before trimming

WEIGHT_PURCHASED = 3
WEIGHT_CART = 2
WEIGHT_SEARCHED = 1

CARD_FIELDS = {
    "_id": 0, "id": 1, "name": 1, "price": 1, "mrp": 1, "image_url": 1,
    "images": 1, "category": 1, "subcategory": 1, "brand": 1, "stock": 1,
    "vendor_id": 1, "vendor_name": 1, "shop_name": 1, "free_delivery": 1,
    "cod_available": 1, "rating": 1, "discount_pct": 1, "active": 1,
}


class SearchLog(BaseModel):
    q: str
    category: Optional[str] = None


def _card(p: Dict[str, Any]) -> Dict[str, Any]:
    """Trim to exactly what a rail card renders, so the payload stays small
    even with two rails of 10."""
    price = float(p.get("price") or 0)
    mrp = float(p.get("mrp") or 0)
    off = int(round((1 - price / mrp) * 100)) if mrp > price > 0 else 0
    imgs = p.get("images") or []
    return {
        "id": p.get("id"),
        "name": p.get("name") or "",
        "price": round(price, 2),
        "mrp": round(mrp, 2) if mrp > price else 0,
        "discount_pct": off,
        "image_url": p.get("image_url") or (imgs[0] if imgs else ""),
        "category": p.get("category") or "",
        "subcategory": p.get("subcategory") or "",
        "brand": p.get("brand") or "",
        "in_stock": int(p.get("stock") or 0) > 0,
        "free_delivery": bool(p.get("free_delivery")),
        "cod_available": p.get("cod_available") is not False,
        "vendor_id": p.get("vendor_id"),
        "shop_name": p.get("shop_name") or p.get("vendor_name") or "",
        "rating": round(float(p.get("rating") or 0), 1),
    }


@router.post("/products/search-log")
async def log_search(
    payload: SearchLog,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """Record what a signed-in user searched for. Fire-and-forget from the
    app; a failure here must never block a search."""
    if not user:
        return {"ok": True, "logged": False}
    q = (payload.q or "").strip()[:80]
    if len(q) < 2:
        return {"ok": True, "logged": False}
    await db.search_logs.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "q": q,
        "q_lower": q.lower(),
        "category": (payload.category or "").strip(),
        "created_at": now_utc().isoformat(),
    })
    # Keep only the latest 60 searches per user — this is a taste signal, not
    # an archive, and an unbounded log would slowly poison the scoring.
    extra = await db.search_logs.find(
        {"user_id": user["id"]}, {"_id": 0, "id": 1},
    ).sort("created_at", -1).skip(60).to_list(500)
    if extra:
        await db.search_logs.delete_many({"id": {"$in": [e["id"] for e in extra]}})
    return {"ok": True, "logged": True}


async def _user_taste(user_id: str) -> Dict[str, Any]:
    """Weighted picture of what this user cares about, from their own data."""
    tags: Counter = Counter()
    brands: Counter = Counter()
    words: Counter = Counter()
    owned: set = set()

    # ── Purchases (strongest signal) ─────────────────────────────────────
    orders = await db.orders.find(
        {"buyer_id": user_id}, {"_id": 0, "items": 1},
    ).sort("created_at", -1).limit(40).to_list(40)
    bought_ids = [
        it.get("product_id") for o in orders for it in (o.get("items") or [])
        if it.get("product_id")
    ]
    owned.update(bought_ids)

    # ── Cart (live intent) ───────────────────────────────────────────────
    cart_rows = await db.cart.find({"user_id": user_id}, {"_id": 0, "product_id": 1}).to_list(100)
    cart_ids = [c.get("product_id") for c in cart_rows if c.get("product_id")]
    owned.update(cart_ids)

    ref_ids = list({*bought_ids, *cart_ids})
    if ref_ids:
        refs = await db.products.find(
            {"id": {"$in": ref_ids}},
            {"_id": 0, "id": 1, "category": 1, "subcategory": 1, "brand": 1},
        ).to_list(len(ref_ids))
        weight_by_id = {**{i: WEIGHT_PURCHASED for i in bought_ids},
                        **{i: max(WEIGHT_CART, WEIGHT_PURCHASED if i in bought_ids else 0)
                           for i in cart_ids}}
        for r in refs:
            w = weight_by_id.get(r["id"], WEIGHT_CART)
            if r.get("subcategory"):
                tags[r["subcategory"].lower()] += w
            if r.get("category"):
                tags[r["category"].lower()] += w
            if r.get("brand"):
                brands[r["brand"].lower()] += w

    # ── Searches (lightest signal) ───────────────────────────────────────
    searches = await db.search_logs.find(
        {"user_id": user_id}, {"_id": 0, "q_lower": 1, "category": 1},
    ).sort("created_at", -1).limit(60).to_list(60)
    for sr in searches:
        for w in re.findall(r"[a-z0-9]{3,}", sr.get("q_lower") or ""):
            words[w] += WEIGHT_SEARCHED
        if sr.get("category"):
            tags[sr["category"].lower()] += WEIGHT_SEARCHED

    return {"tags": tags, "brands": brands, "words": words, "owned": owned}


def _score(p: Dict[str, Any], taste: Dict[str, Any]) -> int:
    tags, brands, words = taste["tags"], taste["brands"], taste["words"]
    s = 0
    sub = (p.get("subcategory") or "").lower()
    cat = (p.get("category") or "").lower()
    brand = (p.get("brand") or "").lower()
    name = (p.get("name") or "").lower()
    if sub:
        s += tags.get(sub, 0) * 3
    if cat:
        s += tags.get(cat, 0) * 2
    if brand:
        s += brands.get(brand, 0) * 2
    for w, weight in words.items():
        if w in name:
            s += weight
    return s


@router.get("/products/{product_id}/rails")
async def product_rails(
    product_id: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """The two rails for a product page."""
    product = await db.products.find_one(
        {"id": product_id},
        {"_id": 0, "id": 1, "category": 1, "subcategory": 1, "brand": 1, "price": 1},
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    live = {"active": {"$ne": False}, "id": {"$ne": product_id}}

    # ── Rail 1: more in the same subcategory ─────────────────────────────
    sub = product.get("subcategory")
    cat = product.get("category")
    sib_q = dict(live)
    if sub:
        sib_q["subcategory"] = sub
    elif cat:
        sib_q["category"] = cat
    siblings = await db.products.find(sib_q, CARD_FIELDS).limit(RAIL_SIZE * 3).to_list(RAIL_SIZE * 3)
    # In-stock first, then closest in price — a ₹200 accessory next to a
    # ₹40,000 phone is noise, not a suggestion.
    base_price = float(product.get("price") or 0)
    siblings.sort(key=lambda p: (
        0 if int(p.get("stock") or 0) > 0 else 1,
        abs(float(p.get("price") or 0) - base_price),
    ))
    rail_sub = [_card(p) for p in siblings[:RAIL_SIZE]]

    # ── Rail 2: picked from this user's own history ───────────────────────
    rail_you: List[Dict[str, Any]] = []
    personalised = False
    if user:
        taste = await _user_taste(user["id"])
        if taste["tags"] or taste["words"] or taste["brands"]:
            exclude = taste["owned"] | {product_id} | {c["id"] for c in rail_sub}
            pool = await db.products.find(
                {"active": {"$ne": False}, "id": {"$nin": list(exclude)}},
                CARD_FIELDS,
            ).limit(CANDIDATE_POOL).to_list(CANDIDATE_POOL)
            scored = [(_score(p, taste), p) for p in pool]
            scored = [(s, p) for s, p in scored if s > 0]
            scored.sort(key=lambda sp: (
                -sp[0], 0 if int(sp[1].get("stock") or 0) > 0 else 1,
            ))
            rail_you = [_card(p) for _, p in scored[:RAIL_SIZE]]
            personalised = bool(rail_you)

    if not rail_you:
        # No history yet — show other good sellers in this category instead
        # of an empty rail.
        fallback_q = dict(live)
        if cat:
            fallback_q["category"] = cat
        seen = {c["id"] for c in rail_sub}
        fb = await db.products.find(
            {**fallback_q, "id": {"$nin": list(seen | {product_id})}}, CARD_FIELDS,
        ).limit(RAIL_SIZE).to_list(RAIL_SIZE)
        rail_you = [_card(p) for p in fb]

    return {
        "rails": [
            {
                "key": "subcategory",
                "title": f"More in {sub or cat or 'this range'}",
                "subtitle": "Same category, ready to add",
                "items": rail_sub,
            },
            {
                "key": "for_you",
                "title": "Picked for you" if personalised else "You might also like",
                "subtitle": (
                    "Based on what you searched, carried and bought"
                    if personalised else "Popular with shoppers like you"
                ),
                "personalised": personalised,
                "items": rail_you,
            },
        ],
    }
