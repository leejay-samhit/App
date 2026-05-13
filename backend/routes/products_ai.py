"""
Products AI — AI-powered image generation for product catalogs.

Endpoints:
  POST /api/products/ai-image   Generate 5 photorealistic model images
                                (Indian model, gender-matched) wearing the
                                uploaded clothes. Uses Gemini Nano Banana
                                via emergentintegrations + EMERGENT_LLM_KEY.

IMPORTANT (logging):
  NEVER print/log full base64 strings — they will instantly blow the context
  window. Use only short prefixes (first 20 chars) for debug.
"""
from __future__ import annotations
import asyncio
import base64
import os
import re
import uuid
import logging
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.security import get_current_user

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Request / response models ───

class AIImageRequest(BaseModel):
    image_data_url: str = Field(..., description="Source clothes image as a data URL or raw base64")
    gender: str = Field(..., description="One of: male | female | boys | girls")
    category: Optional[str] = Field("Clothes", description="Category (default Clothes)")
    size: Optional[str] = Field(None, description="Optional garment size hint (S/M/L/XL/XXL)")
    count: Optional[int] = Field(5, ge=1, le=5, description="Number of variations to produce (max 5)")


class AIImageResponse(BaseModel):
    images: List[str]  # array of data URLs (data:image/png;base64,...)
    count: int


# ─── Helpers ───

_DATA_URL_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,(.+)$")


def _strip_data_url(s: str) -> str:
    """Accept either a data URL or raw base64 and return raw base64."""
    if not s:
        raise ValueError("Empty image")
    m = _DATA_URL_RE.match(s.strip())
    return m.group(1) if m else s.strip()


def _short(s: str, n: int = 20) -> str:
    """Safe debug — only first n characters of a (possibly base64) string."""
    if not s:
        return ""
    return s[:n] + ("…" if len(s) > n else "")


def _prompt_for(gender: str, size: Optional[str], variation: int) -> str:
    """Build a tailored prompt for the requested model demographic."""
    gender = (gender or "").strip().lower()
    if gender in ("male", "men", "man"):
        subject = "an adult Indian male model (early-to-mid 20s, athletic build, warm Indian complexion, short well-groomed hair)"
    elif gender in ("female", "women", "woman"):
        subject = "an adult Indian female model (early-to-mid 20s, slender build, warm Indian complexion, long flowing dark hair)"
    elif gender in ("boy", "boys"):
        subject = "an Indian boy (around 8-10 years old, cheerful expression, short dark hair, warm Indian complexion)"
    elif gender in ("girl", "girls"):
        subject = "an Indian girl (around 8-10 years old, cheerful expression, neat long dark hair, warm Indian complexion)"
    else:
        subject = "an adult Indian model wearing the garment"

    # 5 distinct backdrops / poses so the 5 variations look different
    scenes = [
        "standing in a bright neutral studio with a soft seamless light-grey backdrop, front-facing pose, soft diffused softbox lighting, full-body shot",
        "outdoors in an urban Indian street setting with bokeh background, three-quarter pose, golden-hour natural light, full-body shot",
        "in a modern minimalist white room with daylight from a side window, candid pose looking slightly off-camera, full-body shot",
        "in a lifestyle setting near a contemporary cafe, walking pose, soft daylight, full-body shot",
        "in a clean fashion-catalog studio with a warm beige backdrop, hands-in-pockets confident pose, three-point studio lighting, full-body shot",
    ]
    scene = scenes[variation % len(scenes)]
    size_hint = f" The garment is in size {size}." if size else ""

    return (
        f"Create a photorealistic e-commerce catalog photograph of {subject} wearing the exact "
        f"clothing item from the reference image. Preserve the garment's design, color, pattern, "
        f"fabric texture and proportions accurately — only the model and scene change.{size_hint} "
        f"The model is {scene}. Sharp focus on the garment, realistic skin tones, photorealistic, "
        f"high resolution, professional fashion-catalog quality, no text or watermarks."
    )


async def _generate_one(api_key: str, model_id: str, image_b64: str, prompt: str, idx: int, per_call_timeout: float = 50.0) -> Optional[str]:
    """Generate one image variation; return data URL or None on failure.

    The per-call timeout protects against rare slow Gemini calls that would
    otherwise push the total wall-time past the 60-second Kubernetes ingress
    limit and cause the client to see a 502.
    """
    # Import lazily so the rest of the app boots even if lib has issues
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    async def _do() -> Optional[str]:
        chat = LlmChat(
            api_key=api_key,
            session_id=f"ai-image-{uuid.uuid4()}",
            system_message="You are a professional fashion photography AI. Generate accurate photorealistic catalog images.",
        )
        chat.with_model("gemini", model_id).with_params(modalities=["image", "text"])
        msg = UserMessage(text=prompt, file_contents=[ImageContent(image_b64)])
        text, images = await chat.send_message_multimodal_response(msg)
        # Only log SHORT prefixes — never the full base64.
        logger.info("ai-image variation #%s text=%r images=%s", idx, (text or "")[:80], len(images or []))
        if images:
            img = images[0]
            mime = img.get("mime_type") or "image/png"
            data = img.get("data") or ""
            if data:
                return f"data:{mime};base64,{data}"
        return None

    try:
        return await asyncio.wait_for(_do(), timeout=per_call_timeout)
    except asyncio.TimeoutError:
        logger.warning("ai-image variation #%s timed out after %ss", idx, per_call_timeout)
    except Exception as exc:
        logger.exception("ai-image variation #%s failed: %s", idx, exc)
    return None


# ─── Route ───

@router.post("/products/ai-image", response_model=AIImageResponse)
async def generate_ai_images(
    req: AIImageRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Generate 5 photorealistic catalog images of an Indian model wearing the
    clothes from the uploaded reference image.

    Auth: any authenticated admin or vendor.
    """
    role = (user.get("role") or "").lower()
    if role not in ("admin", "vendor"):
        raise HTTPException(status_code=403, detail="Only admins and vendors can use AI image generation.")

    try:
        b64 = _strip_data_url(req.image_data_url)
        # quick sanity check
        if len(b64) < 100:
            raise HTTPException(status_code=400, detail="Reference image is too small or invalid.")
        # validate it decodes
        try:
            base64.b64decode(b64[:200], validate=False)
        except Exception:
            raise HTTPException(status_code=400, detail="Reference image is not valid base64.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}")

    api_key = os.getenv("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY not configured on server.")

    model_id = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image-preview")
    count = max(1, min(5, int(req.count or 5)))

    logger.info(
        "AI image gen — user=%s role=%s gender=%s size=%s count=%s src=%s",
        user.get("id"), role, req.gender, req.size, count, _short(b64),
    )

    # Generate variations concurrently
    tasks = [
        _generate_one(api_key, model_id, b64, _prompt_for(req.gender, req.size, i), i)
        for i in range(count)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    images = [r for r in results if r]

    if not images:
        raise HTTPException(
            status_code=502,
            detail="AI did not return any images. Please try again with a clearer reference photo.",
        )

    logger.info("AI image gen — produced %s/%s images", len(images), count)
    return AIImageResponse(images=images, count=len(images))
