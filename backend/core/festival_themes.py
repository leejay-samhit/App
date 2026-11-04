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

All ten festivals are fully designed (Nov 2026): each has a real palette, a
dark festive hero gradient, a drawn decoration (`decor.pattern` →
`src/festival-icons.tsx`) and a banner prompt for the AI artwork generator.
Adding one now = adding a palette here and an icon in the registry — no screen
changes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _artwork_prompt(mood: str) -> str:
    return (
        f"A premium, modern {mood} festival banner for an Indian shopping app. "
        "Tasteful, uncluttered, lots of clean negative space in the upper middle for "
        "text. No text, no letters, no words, no logos, no people. Wide landscape "
        "composition, high quality, premium e-commerce look."
    )

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


def _theme(
    fid: str, name: str, subtitle: str, icon: str, swatches: List[str],
    colors: Dict[str, str], gradient: Dict[str, str], decor: Dict[str, Any],
    artwork_prompt: str,
) -> Dict[str, Any]:
    return {
        "id": fid,
        "name": name,
        "subtitle": subtitle,
        "icon": icon,
        "available": True,
        "swatches": swatches,
        "colors": colors,
        "gradient": gradient,
        "decor": decor,
        "artwork_prompt": artwork_prompt,
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
        "artwork_prompt": _artwork_prompt(
            "Deepavali festival of lights: an elegant dark indigo-to-deep-purple "
            "gradient with a warm golden glow, rows of lit clay diyas with soft amber "
            "flames along the lower edge, delicate golden rangoli line-art and subtle "
            "bokeh light particles"
        ),
    },
    # ── The remaining nine festivals (fully designed, Nov 2026) ───────────
    _theme(
        "ugadi", "Ugadi", "Telugu new year — fresh mango & neem greens",
        "sunrise", ["#15803D", "#65A30D", "#FACC15", "#FDE68A"],
        colors={
            "primary": "#166534",
            "primaryFg": "#FFFFFF",
            "accent": "#FACC15",
            "accentFg": "#3A2E00",
            "background": "#FBFDF4",
            "surface": "#FFFFFF",
            "surfaceMuted": "#EFF6DD",
            "textMain": "#1C2A10",
            "textMuted": "#5F7052",
            "border": "#DCE8C8",
            "success": "#2E7D52",
            "warning": "#B45309",
            "error": "#B3261E",
            "brand500": "#3F9142",
            "brand100": "#E2F0DA",
        },
        gradient={
            "start": "#0B2E17",
            "middle": "#166534",
            "end": "#A16207",
            "glow": "#FDE68A",
        },
        decor={
            "pattern": "leaf",
            "sparkles": True,
            "rangoli": True,
            "glow_color": "#FDE68A",
            "decor_tint": "#65A30D",
            "banner_title": "Happy Ugadi",
            "banner_subtitle": "New year, fresh picks & sweet deals",
        },
        artwork_prompt=_artwork_prompt(
            "Ugadi (Telugu new year): a deep fresh-green gradient with a golden glow, "
            "torans of mango and neem leaves strung along the top edge, a small brass "
            "kalasha pot with a coconut and mango leaves in a corner, soft bokeh"
        ),
    ),
    _theme(
        "independence_day", "Independence Day", "Tiranga saffron, white & green",
        "flag", ["#FF9933", "#FFFFFF", "#138808", "#0A3D91"],
        colors={
            "primary": "#1A3C8C",
            "primaryFg": "#FFFFFF",
            "accent": "#FF9933",
            "accentFg": "#3A1E00",
            "background": "#FDFCF9",
            "surface": "#FFFFFF",
            "surfaceMuted": "#F0F4FB",
            "textMain": "#16233E",
            "textMuted": "#5A6478",
            "border": "#DCE3EE",
            "success": "#138808",
            "warning": "#D97706",
            "error": "#B3261E",
            "brand500": "#2D56A8",
            "brand100": "#E0E9F7",
        },
        gradient={
            "start": "#0A1E4A",
            "middle": "#16307E",
            "end": "#0F6B2E",
            "glow": "#FFC069",
        },
        decor={
            "pattern": "tiranga",
            "sparkles": True,
            "rangoli": False,
            "glow_color": "#FFC069",
            "decor_tint": "#1A3C8C",
            "banner_title": "Happy Independence Day",
            "banner_subtitle": "Freedom offers across the store",
        },
        artwork_prompt=_artwork_prompt(
            "Indian Independence Day: an elegant deep navy gradient, a subtle waving "
            "Indian tricolour ribbon (saffron, white, green) sweeping across the lower "
            "third with a small Ashoka Chakra wheel, soft golden light and gentle bokeh"
        ),
    ),
    _theme(
        "ganesh_chaturthi", "Ganesh Chaturthi", "Modak gold & vermilion red",
        "star", ["#B91C1C", "#EA580C", "#F59E0B", "#FEF3C7"],
        colors={
            "primary": "#9A1C1C",
            "primaryFg": "#FFFFFF",
            "accent": "#F59E0B",
            "accentFg": "#3A1E00",
            "background": "#FFFAF2",
            "surface": "#FFFFFF",
            "surfaceMuted": "#FBEEDE",
            "textMain": "#2E1306",
            "textMuted": "#7A6154",
            "border": "#F0DCC4",
            "success": "#2E7D52",
            "warning": "#D97706",
            "error": "#B3261E",
            "brand500": "#C2410C",
            "brand100": "#FBE4CE",
        },
        gradient={
            "start": "#3D0707",
            "middle": "#9A1C1C",
            "end": "#C2410C",
            "glow": "#FCD34D",
        },
        decor={
            "pattern": "modak",
            "sparkles": True,
            "rangoli": True,
            "glow_color": "#FCD34D",
            "decor_tint": "#EA580C",
            "banner_title": "Ganpati Bappa Morya",
            "banner_subtitle": "Festive picks for the celebration",
        },
        artwork_prompt=_artwork_prompt(
            "Ganesh Chaturthi: a rich vermilion-to-deep-red gradient with a golden "
            "glow, a line of golden modak sweets and marigold garlands along the lower "
            "edge, delicate diya flames and soft bokeh"
        ),
    ),
    _theme(
        "dussehra", "Dussehra", "Victory reds with royal gold",
        "award", ["#991B1B", "#C2410C", "#D97706", "#FDE68A"],
        colors={
            "primary": "#7F1D1D",
            "primaryFg": "#FFFFFF",
            "accent": "#D97706",
            "accentFg": "#2A1500",
            "background": "#FFFAF5",
            "surface": "#FFFFFF",
            "surfaceMuted": "#FAECE3",
            "textMain": "#2B1208",
            "textMuted": "#74584C",
            "border": "#EDD9CB",
            "success": "#2E7D52",
            "warning": "#D97706",
            "error": "#B3261E",
            "brand500": "#B45309",
            "brand100": "#F8E3C8",
        },
        gradient={
            "start": "#2D0606",
            "middle": "#7F1D1D",
            "end": "#B45309",
            "glow": "#FDE68A",
        },
        decor={
            "pattern": "arrows",
            "sparkles": True,
            "rangoli": True,
            "glow_color": "#FDE68A",
            "decor_tint": "#C2410C",
            "banner_title": "Happy Dussehra",
            "banner_subtitle": "Victory offers on everything you love",
        },
        artwork_prompt=_artwork_prompt(
            "Dussehra: a dramatic deep crimson-to-ember gradient with a royal golden "
            "glow, a stylised golden bow and arrow motif with laurel, embers and light "
            "rays rising from the bottom, marigold accents"
        ),
    ),
    _theme(
        "maha_shivaratri", "Maha Shivaratri", "Moonlit blues & sacred ash",
        "moon", ["#1E3A8A", "#312E81", "#64748B", "#E2E8F0"],
        colors={
            "primary": "#1E3A8A",
            "primaryFg": "#FFFFFF",
            "accent": "#94A3B8",
            "accentFg": "#0F172A",
            "background": "#F6F8FC",
            "surface": "#FFFFFF",
            "surfaceMuted": "#E8EDF5",
            "textMain": "#141C33",
            "textMuted": "#5B6478",
            "border": "#D8E0EC",
            "success": "#2E7D52",
            "warning": "#B45309",
            "error": "#B3261E",
            "brand500": "#33459E",
            "brand100": "#DFE6F4",
        },
        gradient={
            "start": "#0A0F2E",
            "middle": "#1E3A8A",
            "end": "#312E81",
            "glow": "#C7D2FE",
        },
        decor={
            "pattern": "trishul",
            "sparkles": True,
            "rangoli": False,
            "glow_color": "#C7D2FE",
            "decor_tint": "#64748B",
            "banner_title": "Maha Shivaratri",
            "banner_subtitle": "A blessed night of calm & offers",
        },
        artwork_prompt=_artwork_prompt(
            "Maha Shivaratri: a moonlit deep-indigo gradient, a silver trishul with a "
            "small damaru drum silhouetted against a soft glowing full moon, gentle "
            "smoke swirls and stars, sacred ash tones"
        ),
    ),
    _theme(
        "ramzan", "Ramzan", "Crescent green, teal & lantern gold",
        "moon", ["#065F46", "#0F766E", "#CA8A04", "#FEF9C3"],
        colors={
            "primary": "#065F46",
            "primaryFg": "#FFFFFF",
            "accent": "#CA8A04",
            "accentFg": "#2A1E00",
            "background": "#F7FBF7",
            "surface": "#FFFFFF",
            "surfaceMuted": "#E9F3EC",
            "textMain": "#12261C",
            "textMuted": "#557061",
            "border": "#D3E4D9",
            "success": "#2E7D52",
            "warning": "#B45309",
            "error": "#B3261E",
            "brand500": "#0F766E",
            "brand100": "#DCF0E7",
        },
        gradient={
            "start": "#052E22",
            "middle": "#065F46",
            "end": "#0F766E",
            "glow": "#FDE68A",
        },
        decor={
            "pattern": "crescent",
            "sparkles": True,
            "rangoli": False,
            "glow_color": "#FDE68A",
            "decor_tint": "#CA8A04",
            "banner_title": "Ramzan Mubarak",
            "banner_subtitle": "Blessings and festive treats await",
        },
        artwork_prompt=_artwork_prompt(
            "Ramzan: a deep emerald-to-teal gradient night sky, a glowing golden "
            "crescent moon with a star, hanging ornate lanterns with warm light, "
            "delicate geometric arabesque borders, soft bokeh"
        ),
    ),
    _theme(
        "christmas", "Christmas", "Pine green, berry red & snow",
        "gift", ["#14532D", "#B91C1C", "#F8FAFC", "#D4AF37"],
        colors={
            "primary": "#14532D",
            "primaryFg": "#FFFFFF",
            "accent": "#B91C1C",
            "accentFg": "#FFFFFF",
            "background": "#FDFDFB",
            "surface": "#FFFFFF",
            "surfaceMuted": "#F0F5F0",
            "textMain": "#182615",
            "textMuted": "#5B6B5C",
            "border": "#DCE5DC",
            "success": "#2E7D52",
            "warning": "#B45309",
            "error": "#B3261E",
            "brand500": "#1E6B40",
            "brand100": "#DFEDE1",
        },
        gradient={
            "start": "#081F12",
            "middle": "#14532D",
            "end": "#7F1D1D",
            "glow": "#FDE68A",
        },
        decor={
            "pattern": "tree",
            "sparkles": True,
            "rangoli": False,
            "glow_color": "#FDE68A",
            "decor_tint": "#B91C1C",
            "banner_title": "Merry Christmas",
            "banner_subtitle": "Joyful gifts & festive offers",
        },
        artwork_prompt=_artwork_prompt(
            "Christmas: a deep pine-green gradient with warm golden glow, decorated "
            "Christmas tree silhouettes, hanging red-and-gold baubles, string lights "
            "and gentle falling snow, cosy premium feel"
        ),
    ),
    _theme(
        "new_year", "New Year", "Midnight blue & celebration gold",
        "zap", ["#0F172A", "#1D4ED8", "#F59E0B", "#FDE68A"],
        colors={
            "primary": "#0F172A",
            "primaryFg": "#FFFFFF",
            "accent": "#F59E0B",
            "accentFg": "#2A1A00",
            "background": "#F8FAFD",
            "surface": "#FFFFFF",
            "surfaceMuted": "#EEF2F8",
            "textMain": "#131C2E",
            "textMuted": "#5A6478",
            "border": "#DDE4EE",
            "success": "#2E7D52",
            "warning": "#D97706",
            "error": "#B3261E",
            "brand500": "#1D4ED8",
            "brand100": "#DFE8FA",
        },
        gradient={
            "start": "#070C1C",
            "middle": "#0F172A",
            "end": "#1D4ED8",
            "glow": "#FDE68A",
        },
        decor={
            "pattern": "fireworks",
            "sparkles": True,
            "rangoli": False,
            "glow_color": "#FDE68A",
            "decor_tint": "#F59E0B",
            "banner_title": "Happy New Year",
            "banner_subtitle": "New year, new deals to celebrate",
        },
        artwork_prompt=_artwork_prompt(
            "New Year celebration: a midnight-blue gradient sky, golden and silver "
            "fireworks bursting across the upper sky, confetti and sparkle particles, "
            "elegant and festive"
        ),
    ),
    _theme(
        "sankranti", "Sankranti", "Harvest yellows & kite-sky blue",
        "wind", ["#CA8A04", "#F59E0B", "#0EA5E9", "#FEF3C7"],
        colors={
            "primary": "#B45309",
            "primaryFg": "#FFFFFF",
            "accent": "#0EA5E9",
            "accentFg": "#062434",
            "background": "#FFFDF5",
            "surface": "#FFFFFF",
            "surfaceMuted": "#FCF3DC",
            "textMain": "#2A1E08",
            "textMuted": "#746548",
            "border": "#EFE3C8",
            "success": "#2E7D52",
            "warning": "#D97706",
            "error": "#B3261E",
            "brand500": "#D97706",
            "brand100": "#FAE8C8",
        },
        gradient={
            "start": "#3B2204",
            "middle": "#B45309",
            "end": "#0EA5E9",
            "glow": "#FDE68A",
        },
        decor={
            "pattern": "kite",
            "sparkles": True,
            "rangoli": True,
            "glow_color": "#FDE68A",
            "decor_tint": "#CA8A04",
            "banner_title": "Happy Sankranti",
            "banner_subtitle": "Harvest season, sky-high offers",
        },
        artwork_prompt=_artwork_prompt(
            "Makar Sankranti harvest festival: a warm golden-to-sky-blue gradient sky, "
            "colourful paper kites with flowing tails flying high, sugarcane stalks and "
            "harvest motifs along the bottom, sun flare and soft clouds"
        ),
    ),
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
