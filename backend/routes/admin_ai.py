"""Admin AI routes — text + image generation via Emergent LLM Key.

Extracted from server.py (2026-05-28) as the first slice of the
server.py → routes/ refactor. No behaviour change; same handlers,
same prefixes, same auth.

Endpoints:
  POST /admin/ai/text   — kind / prompt / tone / max_words / existing
  POST /admin/ai/image  — prompt / style
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core.security import require_admin
from models import AITextRequest, AIImageRequest


router = APIRouter()


_AI_TEXT_SYSTEM_PROMPTS: Dict[str, str] = {
    "service_description": (
        "You write concise, persuasive descriptions for Indian local service "
        "providers (plumber, electrician, AC repair etc). Keep it under "
        "{max_words} words. Tone: {tone}. Avoid emojis."
    ),
    "category_description": (
        "You write short (under {max_words} words) descriptions of service "
        "categories on a marketplace app. Tone: {tone}. Be specific about "
        "what's covered."
    ),
    "marketing": (
        "Write punchy {tone} marketing copy under {max_words} words for an "
        "Indian fintech / services marketplace."
    ),
    "service_title": (
        "Suggest a short (3-6 word) service title. Tone: {tone}. Output ONLY "
        "the title, no quotes or punctuation."
    ),
    "improve": (
        "Improve the following text. Make it more {tone} and clearer. Keep "
        "under {max_words} words. Output ONLY the improved text."
    ),
}


@router.post("/admin/ai/text")
async def admin_ai_text(
    payload: AITextRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Generate or refine text via Emergent LLM Key (gpt-4o-mini)."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    except Exception:
        raise HTTPException(status_code=500, detail="AI library not available on server")
    api_key = os.getenv("EMERGENT_LLM_KEY") or ""
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY is not configured")
    kind = (payload.kind or "service_description").lower()
    tmpl = _AI_TEXT_SYSTEM_PROMPTS.get(kind, _AI_TEXT_SYSTEM_PROMPTS["service_description"])
    system = tmpl.format(
        max_words=max(20, min(payload.max_words or 80, 250)),
        tone=(payload.tone or "professional"),
    )
    user_text = payload.prompt.strip()
    if kind == "improve" and payload.existing:
        user_text = f"{payload.existing}\n\n[Refine this. Context: {payload.prompt}]"
    if not user_text:
        raise HTTPException(status_code=400, detail="Prompt is required")
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"ai-text-{admin['id']}-{uuid.uuid4().hex[:6]}",
            system_message=system,
        )
        chat.with_model("openai", "gpt-4o-mini")
        out = await chat.send_message(UserMessage(text=user_text))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider error: {str(e)[:120]}")
    return {"ok": True, "text": (out or "").strip()}


@router.post("/admin/ai/image")
async def admin_ai_image(
    payload: AIImageRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """Generate a category icon / service banner via Gemini Nano Banana.

    Returns base64 image (PNG or JPEG depending on provider) that the admin
    can attach to the category doc directly.
    """
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore
    except Exception:
        raise HTTPException(status_code=500, detail="AI library not available on server")
    api_key = os.getenv("EMERGENT_LLM_KEY") or ""
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY is not configured")
    style = (payload.style or "flat-icon").lower()
    style_hint = {
        "flat-icon":    "flat vector icon, single subject, no text, transparent-feeling background, vibrant color, centred, 1024x1024",
        "banner":       "horizontal banner, marketing photo, professional lighting, no text, clean composition",
        "illustration": "clean modern flat illustration, no text, vibrant colours",
        "hero":         "premium hero image, professional, no text, dramatic lighting",
    }.get(style, "")
    if not (payload.prompt or "").strip():
        raise HTTPException(status_code=400, detail="Prompt is required")
    final_prompt = f"{payload.prompt.strip()}. {style_hint}".strip()
    try:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"ai-img-{admin['id']}-{uuid.uuid4().hex[:6]}",
            system_message="You are an icon designer.",
        )
        chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(
            modalities=["image", "text"],
        )
        text, images = await chat.send_message_multimodal_response(UserMessage(text=final_prompt))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI provider error: {str(e)[:120]}")
    if not images:
        raise HTTPException(status_code=502, detail="AI returned no image")
    img0 = images[0]
    return {
        "ok": True,
        "text": (text or "").strip()[:200],
        "image_b64": img0.get("data"),
        "mime_type": img0.get("mime_type") or "image/png",
    }
