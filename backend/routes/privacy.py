"""Profile picture privacy controls (June 2026).

Lets normal users restrict who can see their profile picture across the
entire app — Chat, Shop, Services, Marketplace, Search, Referral Network.

Account-type rules:
  • Service Provider (`is_service_provider:true` or `service_status:"approved"`)
  • Vendor          (`is_vendor:true`   and `vendor_status:"approved"`)
  → MUST always be visible to everyone so customers can identify/contact them.
    The backend ALWAYS coerces their `profile_visibility` to "everyone" on
    every write, regardless of what the client sent.

Visibility levels (string enum on user.profile_visibility):
  • "everyone"           — default. Public.
  • "downline"           — only the viewer is descended from this user.
  • "accepted_requests"  — only users with an accepted `chat_threads` row.

Future-ready: add new levels (e.g. "nobody", "favorites") by adding to
`VISIBILITY_LEVELS` and a branch in `can_view_profile_image`.

Public helpers exported for use across server.py / routes/*:
  • is_public_account(user)              — SP or Vendor → True
  • can_view_profile_image(viewer_id, target) — gate
  • mask_profile_image(viewer_id, target_dict) — mutate in place, drop pic
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import get_current_user
from core.utils import now_utc

router = APIRouter()

VISIBILITY_LEVELS = {"everyone", "downline", "accepted_requests"}
DEFAULT_VISIBILITY = "everyone"


def is_public_account(user: Dict[str, Any]) -> bool:
    """Service Providers and Vendors are always publicly visible."""
    if not user:
        return False
    if user.get("is_service_provider") or user.get("service_status") == "approved":
        return True
    if user.get("is_vendor") and user.get("vendor_status") == "approved":
        return True
    return False


async def _downline_ids(root_id: str) -> Set[str]:
    """Return the set of user_ids in `root_id`'s downline (any depth).

    Uses a BFS over `sponsor_id`. Depth-capped at 12 levels (matches the
    1+10 matrix + buffer). Cached per-process would be nice but we keep
    it simple — listing endpoints are rare enough to absorb the cost.
    """
    seen: Set[str] = set()
    frontier: Set[str] = {root_id}
    for _ in range(12):
        if not frontier:
            break
        rows = await db.users.find(
            {"sponsor_id": {"$in": list(frontier)}},
            {"_id": 0, "id": 1},
        ).to_list(20000)
        ids = {r["id"] for r in rows if r.get("id")}
        new = ids - seen
        seen |= new
        frontier = new
    return seen


async def _has_accepted_thread(a_id: str, b_id: str) -> bool:
    """Truthy if the two users have at least one mutual `chat_threads`
    row (which only exists after a request is accepted or via the
    Service-Provider shortcut)."""
    parts = sorted([a_id, b_id])
    doc = await db.chat_threads.find_one({"participants": parts})
    return bool(doc)


async def can_view_profile_image(viewer_id: Optional[str], target: Dict[str, Any]) -> bool:
    """Single-pair permission check.

    Returns True when the viewer is allowed to see `target.profile_image`,
    False otherwise. Always True for:
      • viewer == target (own profile)
      • target is a Service Provider / Vendor (always-public)
      • visibility level is "everyone" (default)
    """
    if not target:
        return False
    tid = target.get("id")
    if viewer_id and tid and viewer_id == tid:
        return True
    if is_public_account(target):
        return True
    level = (target.get("profile_visibility") or DEFAULT_VISIBILITY).strip()
    if level not in VISIBILITY_LEVELS:
        level = DEFAULT_VISIBILITY
    if level == "everyone":
        return True
    if not viewer_id:
        return False
    if level == "downline":
        # Viewer must be IN the target's downline (descendant of target).
        descendants = await _downline_ids(tid)
        return viewer_id in descendants
    if level == "accepted_requests":
        return await _has_accepted_thread(viewer_id, tid)
    return False


async def mask_profile_image(viewer_id: Optional[str], target: Dict[str, Any]) -> Dict[str, Any]:
    """In-place strip of `profile_image` (+ derived URLs) when the viewer
    isn't allowed. Returns the same dict for chaining convenience.

    The client then falls back to its default-avatar component. We DO NOT
    blank the user's `name` / `initial` — those are non-sensitive and the
    default avatar needs them.
    """
    if not target:
        return target
    if await can_view_profile_image(viewer_id, target):
        return target
    target.pop("profile_image", None)
    target.pop("profile_image_url", None)
    target.pop("profile_image_thumb", None)
    target["profile_image_hidden"] = True
    return target


# ────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────
class PrivacyUpdate(BaseModel):
    profile_visibility: str = Field(..., min_length=4, max_length=32)


@router.get("/users/me/privacy")
async def get_my_privacy(user: Dict[str, Any] = Depends(get_current_user)):
    """Return the caller's current visibility setting + whether it's
    server-locked (SP/Vendor accounts can't change it)."""
    locked = is_public_account(user)
    level = (user.get("profile_visibility") or DEFAULT_VISIBILITY)
    if locked:
        level = "everyone"
    return {
        "profile_visibility": level,
        "locked": locked,
        "locked_reason": (
            "Your profile picture must always be visible to everyone so "
            "customers can identify and contact you."
        ) if locked else None,
        "options": [
            {"value": "everyone",          "label": "Everyone",                  "icon": "globe"},
            {"value": "downline",          "label": "Downline Only",             "icon": "users"},
            {"value": "accepted_requests", "label": "Accepted Message Requests", "icon": "message-square"},
        ],
    }


@router.patch("/users/me/privacy")
async def update_my_privacy(
    payload: PrivacyUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Update the caller's `profile_visibility`. Service Providers and
    Vendors are LOCKED to "everyone" — the backend overrides any other
    value silently so a tampered client can never hide a public account.
    """
    level = (payload.profile_visibility or "").strip().lower()
    if level not in VISIBILITY_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid visibility. Allowed: {sorted(VISIBILITY_LEVELS)}",
        )
    if is_public_account(user):
        # Hard override — never persist a non-public value for SP/Vendor.
        level = "everyone"
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "profile_visibility": level,
            "profile_visibility_updated_at": now_utc().isoformat(),
        }},
    )
    return {
        "ok": True,
        "profile_visibility": level,
        "locked": is_public_account(user),
    }
