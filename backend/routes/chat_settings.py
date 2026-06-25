"""
Chat personalization — per-user settings for wallpaper + chat lock.

Single MongoDB document per user under `chat_settings` collection:
  {
    user_id: str,
    default_wallpaper:   { kind: 'preset'|'color'|'image', value: str } | None,
    thread_wallpapers:   { [thread_id]: same shape | None },
    # Chat Lock
    pin_hash:            bcrypt-hashed PIN (str) or None,
    use_biometric:       bool,
    lock_chat_tab:       bool,        # gate the whole Chat tab
    locked_thread_ids:   [str],       # per-thread lock list
  }

We expose two surfaces:
  - GET    /api/chat/settings                    → full doc (PIN hash redacted)
  - PATCH  /api/chat/settings/wallpaper          → mutate wallpapers
  - POST   /api/chat/lock/setup                  → set PIN
  - POST   /api/chat/lock/change                 → change PIN (requires old)
  - POST   /api/chat/lock/disable                → require PIN, wipe lock state
  - POST   /api/chat/lock/verify                 → check PIN (returns ok)
  - PATCH  /api/chat/lock/threads                → set locked_thread_ids list
  - PATCH  /api/chat/lock/tab                    → toggle lock_chat_tab

PIN format: 4-6 digits, hashed with bcrypt — never returned in plaintext.
Biometric handling lives client-side via `expo-local-authentication`; the
server just records whether the user opted in (`use_biometric`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Wallpaper presets the client can render natively ──────────────────────
# Each preset is a gradient or solid the React Native side renders without
# any image asset. Storing a stable string key keeps the DB small and lets
# us swap the visual later without a migration.
WALLPAPER_PRESETS = {
    "default":      "#F2F1EC",
    "green-soft":   "#E8F1EA",
    "sky":          "#E3F2FD",
    "sand":         "#FFF4DC",
    "rose":         "#FCE4EC",
    "slate":        "#1F2A24",   # dark
    "midnight":     "#0B1411",   # dark
    "doodle":       "#F7F2E8",
}

_PIN_RE = re.compile(r"^\d{4,6}$")


# ============== Models ==============

class Wallpaper(BaseModel):
    kind: str = Field(..., pattern=r"^(preset|color|image)$")
    value: str = Field(..., min_length=1, max_length=4_000_000)


class WallpaperPatch(BaseModel):
    """Either set `default` (applies to every thread without an override)
    or set `thread_wallpapers` (per-thread overrides). Passing `null` for a
    key removes that override / default."""
    default: Optional[Wallpaper] = None
    clear_default: bool = False
    thread_wallpapers: Optional[Dict[str, Optional[Wallpaper]]] = None


class PinBody(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6)


class ChangePinBody(BaseModel):
    old_pin: str = Field(..., min_length=4, max_length=6)
    new_pin: str = Field(..., min_length=4, max_length=6)
    use_biometric: Optional[bool] = None


class LockedThreadsPatch(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6)
    locked_thread_ids: List[str] = Field(default_factory=list)


class LockTabPatch(BaseModel):
    pin: str = Field(..., min_length=4, max_length=6)
    lock_chat_tab: bool
    use_biometric: Optional[bool] = None


# ============== Helpers ==============

async def _get_settings(user_id: str) -> Dict[str, Any]:
    doc = await db.chat_settings.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        doc = {
            "user_id": user_id,
            "default_wallpaper": None,
            "thread_wallpapers": {},
            "pin_hash": None,
            "use_biometric": False,
            "lock_chat_tab": False,
            "locked_thread_ids": [],
        }
    return doc


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the bcrypt hash before returning to the client."""
    pin_hash = doc.get("pin_hash")
    return {
        "default_wallpaper":  doc.get("default_wallpaper"),
        "thread_wallpapers":  doc.get("thread_wallpapers") or {},
        "has_pin":            bool(pin_hash),
        "use_biometric":      bool(doc.get("use_biometric")),
        "lock_chat_tab":      bool(doc.get("lock_chat_tab")),
        "locked_thread_ids":  list(doc.get("locked_thread_ids") or []),
        "presets":            WALLPAPER_PRESETS,
    }


def _verify_pin(pin: str, pin_hash: Optional[str]) -> bool:
    if not pin_hash or not _PIN_RE.match(pin or ""):
        return False
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except Exception:
        return False


def _hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


async def _save_settings(user_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    await db.chat_settings.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, **patch}},
        upsert=True,
    )
    return await _get_settings(user_id)


# ============== Settings (read) ==============

@router.get("/chat/settings")
async def get_chat_settings(user: Dict[str, Any] = Depends(get_current_user)):
    doc = await _get_settings(user["id"])
    return _public(doc)


# ============== Wallpaper ==============

@router.patch("/chat/settings/wallpaper")
async def patch_wallpaper(
    body: WallpaperPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    current = await _get_settings(user["id"])
    patch: Dict[str, Any] = {}

    # Default wallpaper handling.
    if body.clear_default:
        patch["default_wallpaper"] = None
    elif body.default is not None:
        if body.default.kind == "preset" and body.default.value not in WALLPAPER_PRESETS:
            raise HTTPException(status_code=400, detail="Unknown preset key.")
        patch["default_wallpaper"] = body.default.model_dump()

    # Per-thread overrides.
    if body.thread_wallpapers is not None:
        merged: Dict[str, Any] = dict(current.get("thread_wallpapers") or {})
        for tid, wp in body.thread_wallpapers.items():
            if wp is None:
                merged.pop(tid, None)
            else:
                if wp.kind == "preset" and wp.value not in WALLPAPER_PRESETS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unknown preset key for thread {tid}.",
                    )
                merged[tid] = wp.model_dump()
        patch["thread_wallpapers"] = merged

    if not patch:
        # No-op patch — return the current doc so clients still get a 200.
        return _public(current)

    doc = await _save_settings(user["id"], patch)
    return _public(doc)


# ============== Chat Lock ==============

@router.post("/chat/lock/setup")
async def lock_setup(body: PinBody, user: Dict[str, Any] = Depends(get_current_user)):
    if not _PIN_RE.match(body.pin):
        raise HTTPException(status_code=400, detail="PIN must be 4-6 digits.")
    current = await _get_settings(user["id"])
    if current.get("pin_hash"):
        raise HTTPException(
            status_code=400,
            detail="Chat lock is already set up. Use 'change' to update.",
        )
    doc = await _save_settings(user["id"], {"pin_hash": _hash_pin(body.pin)})
    return _public(doc)


@router.post("/chat/lock/change")
async def lock_change(
    body: ChangePinBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if not _PIN_RE.match(body.new_pin):
        raise HTTPException(status_code=400, detail="New PIN must be 4-6 digits.")
    current = await _get_settings(user["id"])
    if not _verify_pin(body.old_pin, current.get("pin_hash")):
        raise HTTPException(status_code=403, detail="Old PIN is incorrect.")
    patch: Dict[str, Any] = {"pin_hash": _hash_pin(body.new_pin)}
    if body.use_biometric is not None:
        patch["use_biometric"] = bool(body.use_biometric)
    doc = await _save_settings(user["id"], patch)
    return _public(doc)


@router.post("/chat/lock/verify")
async def lock_verify(body: PinBody, user: Dict[str, Any] = Depends(get_current_user)):
    current = await _get_settings(user["id"])
    if not current.get("pin_hash"):
        raise HTTPException(status_code=400, detail="No chat PIN configured.")
    if not _verify_pin(body.pin, current.get("pin_hash")):
        raise HTTPException(status_code=403, detail="Wrong PIN.")
    return {"ok": True}


@router.post("/chat/lock/disable")
async def lock_disable(body: PinBody, user: Dict[str, Any] = Depends(get_current_user)):
    current = await _get_settings(user["id"])
    if not current.get("pin_hash"):
        raise HTTPException(status_code=400, detail="Chat lock not configured.")
    if not _verify_pin(body.pin, current.get("pin_hash")):
        raise HTTPException(status_code=403, detail="Wrong PIN.")
    doc = await _save_settings(user["id"], {
        "pin_hash":          None,
        "use_biometric":     False,
        "lock_chat_tab":     False,
        "locked_thread_ids": [],
    })
    return _public(doc)


@router.patch("/chat/lock/threads")
async def lock_threads(
    body: LockedThreadsPatch,
    user: Dict[str, Any] = Depends(get_current_user),
):
    current = await _get_settings(user["id"])
    if not current.get("pin_hash"):
        raise HTTPException(status_code=400, detail="Set up chat lock first.")
    if not _verify_pin(body.pin, current.get("pin_hash")):
        raise HTTPException(status_code=403, detail="Wrong PIN.")
    # De-dupe + cap at 200 thread IDs to keep the doc compact.
    cleaned = list(dict.fromkeys([t for t in body.locked_thread_ids if t]))[:200]
    doc = await _save_settings(user["id"], {"locked_thread_ids": cleaned})
    return _public(doc)


@router.patch("/chat/lock/tab")
async def lock_tab(body: LockTabPatch, user: Dict[str, Any] = Depends(get_current_user)):
    current = await _get_settings(user["id"])
    if not current.get("pin_hash"):
        raise HTTPException(status_code=400, detail="Set up chat lock first.")
    if not _verify_pin(body.pin, current.get("pin_hash")):
        raise HTTPException(status_code=403, detail="Wrong PIN.")
    patch: Dict[str, Any] = {"lock_chat_tab": bool(body.lock_chat_tab)}
    if body.use_biometric is not None:
        patch["use_biometric"] = bool(body.use_biometric)
    doc = await _save_settings(user["id"], patch)
    return _public(doc)
