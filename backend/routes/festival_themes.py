"""Festival theme routes (Oct 2026).

A festival theme writes a named palette into the existing branding document,
so every screen that already themes itself from branding picks it up without
per-screen work. The previous palette is stashed first, so "restore default"
puts the admin's own Slangcart colours back — not the factory ones.

Endpoints (mounted at /api by server.py):
  GET  /festival-themes                      — public: cards for the admin screen
  GET  /festival-theme/active                — public: tiny poll payload
  POST /admin/festival-theme/apply           — super_admin
  POST /admin/festival-theme/clear           — super_admin
  POST /admin/festival-theme/artwork         — super_admin: AI-generate artwork
  GET  /festival-artwork/{fid}/{slot}        — public image proxy
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.branding import get_branding_doc, merge_branding
from core.db import db
from core.festival_themes import (
    ARTWORK_SLOTS, DEFAULT_GRADIENT, DEFAULT_PALETTE, get_festival, list_festivals,
)
from core.object_storage import get_object, put_object
from core.security import require_admin_role
from core.utils import audit_log

log = logging.getLogger(__name__)
router = APIRouter(tags=["festival-themes"])

ARTWORK_MODEL = "gemini-3.1-flash-image-preview"


class ApplyPayload(BaseModel):
    festival_id: str


class ArtworkPayload(BaseModel):
    festival_id: str
    slot: str = "banner"


class BannerTextPayload(BaseModel):
    """Editable banner copy + layout for ONE festival (Nov-2026, req 17).

    Every field is optional — anything left out falls back to the festival's
    own wording, so a half-filled form never blanks the banner.
    """
    festival_id: str
    title: Optional[str] = Field(None, max_length=60)
    subtitle: Optional[str] = Field(None, max_length=120)
    align: Optional[str] = None            # left | center | right
    title_size: Optional[int] = Field(None, ge=12, le=34)
    subtitle_size: Optional[int] = Field(None, ge=10, le=24)
    title_color: Optional[str] = Field(None, max_length=9)
    subtitle_color: Optional[str] = Field(None, max_length=9)
    height: Optional[int] = Field(None, ge=84, le=200)


def _short(e: Exception, limit: int = 300) -> str:
    """Upstream failures can carry an entire HTML page — keep it readable."""
    msg = " ".join(str(e).split())
    if "<" in msg and ">" in msg:
        msg = "the image service returned an unexpected response"
    return msg[:limit]


def _version() -> int:
    """Monotonic theme version — open apps poll this and re-theme when it moves."""
    return int(time.time())


@router.get("/festival-themes")
async def get_festival_themes():
    """PUBLIC — the admin screen needs this before any theme is applied."""
    stored = await get_branding_doc()
    fest = stored.get("festival") or {}
    return {
        "items": list_festivals(),
        "active_id": fest.get("id"),
        "theme_version": stored.get("theme_version") or 0,
    }


@router.get("/festival-theme/active")
async def get_active_festival_theme():
    """PUBLIC, deliberately tiny — polled by open apps to spot a theme change."""
    stored = await get_branding_doc()
    fest = stored.get("festival") or {}
    return {
        "id": fest.get("id"),
        "name": fest.get("name"),
        "theme_version": stored.get("theme_version") or 0,
    }


@router.post("/admin/festival-theme/apply")
async def apply_festival_theme(
    payload: ApplyPayload,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    fest = get_festival(payload.festival_id)
    if not fest:
        raise HTTPException(status_code=404, detail="Unknown festival")
    if not fest.get("available"):
        raise HTTPException(
            status_code=400,
            detail=f"The {fest['name']} theme isn't ready yet.",
        )

    stored = await get_branding_doc()
    already_festive = bool((stored.get("festival") or {}).get("id"))

    # Stash the admin's own palette ONCE, so switching between festivals never
    # loses the real Slangcart colours.
    base_colors = dict(stored.get("pre_festival_colors") or {})
    base_gradient = dict(stored.get("pre_festival_gradient") or {})
    if not already_festive or not base_colors:
        base_colors = dict(stored.get("colors") or DEFAULT_PALETTE)
        base_gradient = dict(stored.get("gradient") or DEFAULT_GRADIENT)

    new_colors = {**DEFAULT_PALETTE, **base_colors, **fest["colors"]}
    new_gradient = {**DEFAULT_GRADIENT, **base_gradient, **fest["gradient"]}

    artwork = ((stored.get("festival") or {}).get("artwork")
               if (stored.get("festival") or {}).get("id") == fest["id"] else {}) or {}
    stored_art = (stored.get("festival_artwork") or {}).get(fest["id"]) or {}
    if stored_art:
        artwork = {**artwork, **stored_art}

    update = {
        "colors": new_colors,
        "gradient": new_gradient,
        "pre_festival_colors": base_colors,
        "pre_festival_gradient": base_gradient,
        "festival": {
            "banner_text": (stored.get("festival_banner_text") or {}).get(fest["id"]) or {},
            "id": fest["id"],
            "name": fest["name"],
            "subtitle": fest["subtitle"],
            "icon": fest["icon"],
            "decor": fest["decor"],
            "artwork": artwork,
        },
        "theme_version": _version(),
    }
    await db.settings.update_one({"id": "branding"}, {"$set": update}, upsert=True)
    await audit_log(admin, "festival_theme.apply", "branding", fest["id"], {"name": fest["name"]})
    return merge_branding(await get_branding_doc())


@router.post("/admin/festival-theme/clear")
async def clear_festival_theme(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Restore the palette that was in place before any festival was applied."""
    stored = await get_branding_doc()
    base_colors = dict(stored.get("pre_festival_colors") or {}) or dict(DEFAULT_PALETTE)
    base_gradient = dict(stored.get("pre_festival_gradient") or {}) or dict(DEFAULT_GRADIENT)

    await db.settings.update_one(
        {"id": "branding"},
        {
            "$set": {
                "colors": {**DEFAULT_PALETTE, **base_colors},
                "gradient": {**DEFAULT_GRADIENT, **base_gradient},
                "festival": None,
                "theme_version": _version(),
            },
            "$unset": {"pre_festival_colors": "", "pre_festival_gradient": ""},
        },
        upsert=True,
    )
    await audit_log(admin, "festival_theme.clear", "branding", "global")
    return merge_branding(await get_branding_doc())


@router.put("/admin/festival-theme/banner-text")
async def set_festival_banner_text(
    payload: BannerTextPayload,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Save the editable heading / subtitle / layout for a festival banner."""
    fest = get_festival(payload.festival_id)
    if not fest:
        raise HTTPException(status_code=404, detail="Unknown festival")
    if payload.align and payload.align not in ("left", "center", "right"):
        raise HTTPException(status_code=400, detail="align must be left, center or right")
    for field in ("title_color", "subtitle_color"):
        val = getattr(payload, field)
        if val and not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", val):
            raise HTTPException(status_code=400, detail=f"{field} must be a hex colour like #FFD700")

    overrides = {
        k: v for k, v in payload.model_dump(exclude={"festival_id"}).items() if v not in (None, "")
    }
    await db.settings.update_one(
        {"id": "branding"},
        {"$set": {f"festival_banner_text.{fest['id']}": overrides}},
        upsert=True,
    )
    # Republish instantly when this festival is the live one.
    stored = await get_branding_doc()
    if (stored.get("festival") or {}).get("id") == fest["id"]:
        await db.settings.update_one(
            {"id": "branding"},
            {"$set": {"festival.banner_text": overrides, "theme_version": _version()}},
        )
    await audit_log(admin, "festival_theme.banner_text", "branding", fest["id"], overrides)
    return {"ok": True, "festival_id": fest["id"], "banner_text": overrides}


@router.get("/admin/festival-theme/banner-text")
async def list_festival_banner_text(
    _admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    stored = await get_branding_doc()
    return {"items": stored.get("festival_banner_text") or {}}


def _storage_path(fid: str, slot: str) -> str:
    return f"slangcart/festival-themes/{fid}/{slot}.png"


@router.post("/admin/festival-theme/artwork")
async def generate_festival_artwork(
    payload: ArtworkPayload,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Generate the festival banner with Gemini and park it in object storage.

    Generated once by an admin and then served to every user from our own
    image proxy — the app never talks to storage or to the model.
    """
    fest = get_festival(payload.festival_id)
    if not fest:
        raise HTTPException(status_code=404, detail="Unknown festival")
    slot = (payload.slot or "banner").strip().lower()
    if slot not in ARTWORK_SLOTS:
        raise HTTPException(status_code=400, detail=f"slot must be one of: {', '.join(ARTWORK_SLOTS)}")
    prompt = fest.get("artwork_prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail=f"No artwork prompt defined for {fest['name']} yet.")
    if not os.environ.get("EMERGENT_LLM_KEY"):
        raise HTTPException(status_code=503, detail="Image generation is not configured (EMERGENT_LLM_KEY missing).")

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        chat = LlmChat(
            api_key=os.environ.get("EMERGENT_LLM_KEY"),
            session_id=f"festival-art-{fest['id']}-{slot}-{int(time.time())}",
            system_message="You generate premium festival artwork for a mobile shopping app.",
        )
        chat.with_model("gemini", ARTWORK_MODEL).with_params(modalities=["image", "text"])
        _text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    except Exception as e:  # noqa: BLE001 — surface a readable reason to the admin
        log.exception("festival artwork generation failed")
        msg = str(e)
        # Nov 2026 — the raw litellm chain ("litellm.AuthenticationError:
        # OpenAIException - API key is inactive") meant nothing to the admin.
        # Translate the known failure modes into plain instructions.
        if "api key is inactive" in msg.lower() or "authenticationerror" in msg.lower():
            detail = (
                "The AI artwork service needs balance: open Profile → Manage plan → "
                "Universal Key → Add balance (or enable auto top-up), then try again."
            )
        elif "quota" in msg.lower() or "rate" in msg.lower():
            detail = "The AI service is rate-limited right now. Wait a minute and try again."
        else:
            detail = f"Artwork generation failed: {_short(e)}"
        # 424, not 502: the ingress replaces 5xx bodies with a generic HTML
        # error page, so a 5xx would hide this message from the admin screen.
        raise HTTPException(status_code=424, detail=detail) from e

    if not images:
        raise HTTPException(status_code=424, detail="The model returned no image. Please try again.")

    img = images[0]
    try:
        img_bytes = base64.b64decode(img["data"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=424, detail="The generated image could not be decoded.") from e

    path = _storage_path(fest["id"], slot)
    try:
        await run_in_threadpool(put_object, path, img_bytes, img.get("mime_type") or "image/png")
    except RuntimeError as e:
        raise HTTPException(status_code=402, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.exception("festival artwork upload failed")
        raise HTTPException(status_code=424, detail=f"Could not save the artwork: {_short(e)}") from e

    url = f"/api/festival-artwork/{fest['id']}/{slot}?v={int(time.time())}"
    await db.settings.update_one(
        {"id": "branding"},
        {"$set": {
            f"festival_artwork.{fest['id']}.{slot}": url,
            f"festival_artwork.{fest['id']}.storage_path_{slot}": path,
        }},
        upsert=True,
    )
    # If this festival is the live one, publish the artwork immediately.
    stored = await get_branding_doc()
    if (stored.get("festival") or {}).get("id") == fest["id"]:
        await db.settings.update_one(
            {"id": "branding"},
            {"$set": {f"festival.artwork.{slot}": url, "theme_version": _version()}},
        )
    await audit_log(admin, "festival_theme.artwork", "branding", fest["id"], {"slot": slot})
    return {"ok": True, "festival_id": fest["id"], "slot": slot, "url": url, "bytes": len(img_bytes)}


@router.get("/festival-artwork/{fid}/{slot}")
async def serve_festival_artwork(fid: str, slot: str):
    """PUBLIC image proxy — festival artwork is branding, shown before login."""
    fest = get_festival(fid)
    if not fest or slot not in ARTWORK_SLOTS:
        raise HTTPException(status_code=404, detail="Not found")
    stored = await get_branding_doc()
    art = (stored.get("festival_artwork") or {}).get(fest["id"]) or {}
    if not art.get(slot) and not art.get(f"storage_path_{slot}"):
        raise HTTPException(status_code=404, detail="No artwork generated for this festival yet")
    path = art.get(f"storage_path_{slot}") or _storage_path(fest["id"], slot)
    try:
        content, ctype = await run_in_threadpool(get_object, path)
    except Exception as e:  # noqa: BLE001 — storage 500s on a missing object
        log.warning("festival artwork fetch failed for %s: %s", path, e)
        raise HTTPException(status_code=404, detail="Artwork is unavailable") from e
    return Response(
        content=content,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=86400"},
    )
