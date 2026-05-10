"""Branding routes — public theme + super-admin theme management.
Extracted from server.py during Phase 2B refactor.

Endpoints (mounted at /api by server.py):
  GET  /branding                 — public, returns merged branding doc
  PUT  /admin/branding           — super_admin, partial update
  POST /admin/branding/reset     — super_admin, reset to defaults
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from core.branding import get_branding_doc, merge_branding
from core.config import ALLOWED_FONTS, ALLOWED_TAB_KEYS, DEFAULT_BRANDING
from core.db import db
from core.security import require_admin_role
from core.utils import audit_log
from models import BrandingPayload

router = APIRouter(tags=["branding"])


@router.get("/branding")
async def get_branding():
    """PUBLIC endpoint — returns current branding so the app can theme itself
    before the user is authenticated."""
    stored = await get_branding_doc()
    return merge_branding(stored)


@router.put("/admin/branding")
async def admin_update_branding(
    payload: BrandingPayload,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    update: Dict[str, Any] = {}
    if payload.app_name is not None:
        update["app_name"] = payload.app_name.strip()[:60] or DEFAULT_BRANDING["app_name"]
    if payload.tagline is not None:
        update["tagline"] = payload.tagline.strip()[:200]
    if payload.login_subtitle is not None:
        update["login_subtitle"] = payload.login_subtitle.strip()[:120]
    if payload.payment_hero is not None:
        update["payment_hero"] = payload.payment_hero.strip()[:120]
    if payload.pending_hero is not None:
        update["pending_hero"] = payload.pending_hero.strip()[:120]
    if payload.colors is not None:
        clean: Dict[str, str] = {}
        for k, v in payload.colors.items():
            if k in DEFAULT_BRANDING["colors"] and isinstance(v, str):
                v = v.strip()
                if re.match(r"^#[0-9A-Fa-f]{3,8}$", v):
                    clean[k] = v
        if clean:
            existing = (await get_branding_doc()).get("colors") or {}
            existing.update(clean)
            update["colors"] = existing
    if payload.font is not None:
        if payload.font not in ALLOWED_FONTS:
            raise HTTPException(status_code=400, detail=f"Font must be one of: {sorted(ALLOWED_FONTS)}")
        update["font"] = payload.font
    if payload.tabs is not None:
        cleaned: List[Dict[str, Any]] = []
        seen: set = set()
        for t in payload.tabs:
            key = t.get("key")
            if key in ALLOWED_TAB_KEYS and key not in seen:
                default_t = next((d for d in DEFAULT_BRANDING["tabs"] if d["key"] == key), {})
                cleaned.append({
                    "key": key,
                    "label": (t.get("label") or default_t.get("label", key.title())).strip()[:24],
                    "icon": t.get("icon") or default_t.get("icon", "circle"),
                    "visible": bool(t.get("visible", True)),
                })
                seen.add(key)
        for d in DEFAULT_BRANDING["tabs"]:
            if d["key"] not in seen:
                cleaned.append(dict(d))
        if not any(t["visible"] for t in cleaned):
            raise HTTPException(status_code=400, detail="At least one tab must be visible")
        update["tabs"] = cleaned

    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")

    await db.settings.update_one({"id": "branding"}, {"$set": update}, upsert=True)
    await audit_log(admin, "branding.update", "branding", "global", {"fields": list(update.keys())})
    stored = await get_branding_doc()
    return merge_branding(stored)


@router.post("/admin/branding/reset")
async def admin_reset_branding(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    await db.settings.update_one({"id": "branding"}, {"$set": dict(DEFAULT_BRANDING)}, upsert=True)
    await audit_log(admin, "branding.reset", "branding", "global")
    stored = await get_branding_doc()
    return merge_branding(stored)
