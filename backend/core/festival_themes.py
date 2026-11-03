"""Festival theme registry (Oct 2026).

A festival theme is NOT a new styling system — it is a named palette that is
written into the existing branding document, so every screen that already
reads `colors` / `gradient` from branding picks it up with no per-screen work.

Each entry carries:
  • id / name / subtitle / icon         — admin card identity
  • available                            — False = placeholder card (no Apply)
  • swatches                             — 4 colours for the preview strip
  • colors                               — full branding palette override
  • gradient                             — hero gradient (login/register/pay)
  • decor                                — drawn-in-app decoration settings
  • artwork_prompt                       — used by the AI artwork generator

Deepavali is the fully-designed theme for this round; the other nine are
placeholders with their real palettes already chosen so a later round only has
to flip `available` to True.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# The default Slangcart palette, kept here so "restore default" never has to
# guess. Mirrors frontend/src/theme.ts.
DEFAULT_PALETTE: Dict[str, str] = {
    "background": "#FAF9F6",
    "surface": "#FFFFFF",
    "surfaceMuted": "#F3F1EC",
    "primary": "#143D2E",
    "primaryFg": "#FFFFFF",
    "accent": "#E57A44",
    "accentFg": "#FFFFFF",
    "success": "#2E7D52",
    "warning": "#D9A05B",
    "error": "#B3261E",
    "textMain": "#1C2520",
    "textMuted": "#6B7280",
    "border": "#E5E4E0",
    "brand500": "#2C6B50",
    "brand100": "#DDE8E2",
}

DEFAULT_GRADIENT: Dict[str, str] = {
    "start": "#0A0E27",
    "middle": "#1E2A78",
    "end": "#5B21B6",
    "glow": "#06B6D4",
}


def _placeholder(
    fid: str, name: str, subtitle: str, icon: str, swatches: List[str],
) -> Dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "subtitle": subtitle,
        "icon": icon,
        "available": False,
        "swatches": swatches,
        "colors": {},
        "gradient": {},
        "decor": {},
        "artwork_prompt": "",
    }


FESTIVALS: List[Dict[str, Any]] = [
    # ── The fully-designed theme ─────────────────────────────────────────
    {
        "id": "deepavali",
        "name": "Deepavali",
        "subtitle": "Diyas, rangoli & gold — the festival of lights",
        "icon": "sun",
        "available": True,
        "swatches": ["#4C1D95", "#1E3A8A", "#F59E0B", "#FB923C"],
        "colors": {
            # Deep purple leads, royal blue supports, gold accents.
            "primary": "#4C1D95",
            "primaryFg": "#FFFFFF",
            "accent": "#F59E0B",
            "accentFg": "#2A1500",
            # Warm ivory surfaces keep product photos and prices readable;
            # the dark festive gradients live in the heroes and banners.
            "background": "#FFF8EE",
            "surface": "#FFFFFF",
            "surfaceMuted": "#FDF0DC",
            "textMain": "#241038",
            "textMuted": "#6D5A82",
            "border": "#EBDAC2",
            "success": "#2E7D52",
            "warning": "#D97706",
            "error": "#B3261E",
            "brand500": "#6D28D9",
            "brand100": "#EDE4FB",
        },
        "gradient": {
            "start": "#190A33",
            "middle": "#3B1178",
            "end": "#7C2D12",
            "glow": "#FBBF24",
        },
        "decor": {
            # Read by the in-app decoration layer (react-native-svg).
            "pattern": "diya",
            "sparkles": True,
            "rangoli": True,
            "glow_color": "#FBBF24",
            "decor_tint": "#F59E0B",
            "banner_title": "Happy Deepavali",
            "banner_subtitle": "Festive picks, lit-up prices",
        },
        "artwork_prompt": (
            "A premium, modern Deepavali festival banner for an Indian shopping app. "
            "Elegant dark indigo-to-deep-purple gradient background with a warm golden "
            "glow. Rows of lit clay diyas (oil lamps) with soft amber flames along the "
            "lower edge, delicate golden rangoli line-art and subtle bokeh light "
            "particles. Tasteful, uncluttered, lots of clean negative space in the "
            "upper middle for text. No text, no letters, no words, no logos, no people. "
            "Wide landscape composition, high quality, premium e-commerce look."
        ),
    },
    # ── Placeholders: palettes chosen, artwork/decor to follow ────────────
    _placeholder("ugadi", "Ugadi", "Telugu new year — fresh mango & neem greens",
                 "sunrise", ["#15803D", "#65A30D", "#FACC15", "#FDE68A"]),
    _placeholder("independence_day", "Independence Day", "Tiranga saffron, white & green",
                 "flag", ["#FF9933", "#FFFFFF", "#138808", "#0A3D91"]),
    _placeholder("ganesh_chaturthi", "Ganesh Chaturthi", "Modak gold & vermilion red",
                 "star", ["#B91C1C", "#EA580C", "#F59E0B", "#FEF3C7"]),
    _placeholder("dussehra", "Dussehra", "Victory reds with royal gold",
                 "award", ["#991B1B", "#C2410C", "#D97706", "#FDE68A"]),
    _placeholder("maha_shivaratri", "Maha Shivaratri", "Moonlit blues & sacred ash",
                 "moon", ["#1E3A8A", "#312E81", "#64748B", "#E2E8F0"]),
    _placeholder("ramzan", "Ramzan", "Crescent green, teal & lantern gold",
                 "moon", ["#065F46", "#0F766E", "#CA8A04", "#FEF9C3"]),
    _placeholder("christmas", "Christmas", "Pine green, berry red & snow",
                 "gift", ["#14532D", "#B91C1C", "#F8FAFC", "#D4AF37"]),
    _placeholder("new_year", "New Year", "Midnight blue & celebration gold",
                 "zap", ["#0F172A", "#1D4ED8", "#F59E0B", "#FDE68A"]),
    _placeholder("sankranti", "Sankranti", "Harvest yellows & kite-sky blue",
                 "wind", ["#CA8A04", "#F59E0B", "#0EA5E9", "#FEF3C7"]),
]

FESTIVAL_BY_ID: Dict[str, Dict[str, Any]] = {f["id"]: f for f in FESTIVALS}
ARTWORK_SLOTS = ("banner",)


def list_festivals() -> List[Dict[str, Any]]:
    """Card data for the admin screen (no heavy fields)."""
    return [
        {
            "id": f["id"],
            "name": f["name"],
            "subtitle": f["subtitle"],
            "icon": f["icon"],
            "available": f["available"],
            "swatches": f["swatches"],
            "colors": f["colors"],
            "gradient": f["gradient"],
            "decor": f["decor"],
        }
        for f in FESTIVALS
    ]


def get_festival(fid: str) -> Optional[Dict[str, Any]]:
    return FESTIVAL_BY_ID.get((fid or "").strip().lower())
