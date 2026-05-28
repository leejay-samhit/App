"""Application configuration: env-derived constants, payout defaults, branding defaults."""
from dotenv import load_dotenv
from pathlib import Path
import os
from typing import Dict, Any

_ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT_DIR / '.env')

# ---- Auth / JWT ----
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"

# ---- Default seed admin ----
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@app.com')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Admin@123')

# ---- MLM / payout config ----
REGISTRATION_FEE = float(os.environ.get('REGISTRATION_FEE', 118))
PAYOUT_PER_LEVEL = float(os.environ.get('PAYOUT_PER_LEVEL', 400))
LEVEL_2_PAYOUT = float(os.environ.get('LEVEL_2_PAYOUT', 100))
LEVEL_3_PAYOUT = float(os.environ.get('LEVEL_3_PAYOUT', 50))
DIRECTS_REQUIRED = 4

# Default payout amounts per level (10 levels). L1 is paid every Nth direct;
# L2..L10 are credited per qualifying down-line activation.
DEFAULT_LEVEL_PAYOUTS: Dict[str, float] = {
    "payout_l1": PAYOUT_PER_LEVEL,
    "payout_l2": LEVEL_2_PAYOUT,
    "payout_l3": LEVEL_3_PAYOUT,
    "payout_l4": 25.0,
    "payout_l5": 15.0,
    "payout_l6": 10.0,
    "payout_l7": 8.0,
    "payout_l8": 5.0,
    "payout_l9": 3.0,
    "payout_l10": 2.0,
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "registration_fee": REGISTRATION_FEE,
    **DEFAULT_LEVEL_PAYOUTS,
    "directs_required": DIRECTS_REQUIRED,
    "vendor_commission_pct": 70,
    "auto_approve_on_payment": True,
    # ── Service Provider — "Get phone number" reveal fee (June 2026 model) ──
    # Customer pays this small fee to reveal a service-provider's phone number
    # (replaces the old "book and charge full service rate" flow). GST is
    # collected separately and credited to `gst_collected` bucket of the
    # System Wallet. The base fee lands in `service_margin` bucket.
    "phone_reveal_fee": 1.0,            # ₹ per reveal — admin-configurable
    "phone_reveal_gst_pct": 18.0,       # GST percent on top of the base fee
    # ── Platform margin toggles (June 2026 — admin can disable) ──
    # When False, shop orders and service bookings will NOT route any
    # share to the platform System Wallet. Existing transactions are
    # untouched; this only affects future activity.
    "shop_margin_enabled": False,
    "service_booking_margin_enabled": False,
}

# ---- GST ----
REFERRAL_GST_PCT = 18.0  # GST-exclusive: gst = 18% OF gross → admin; net = gross - gst → user.

# ---- Achievement tiers ----
TIERS = [
    {"name": "Diamond", "min": 200, "color": "#E0F2FF", "icon": "award"},
    {"name": "Platinum", "min": 60, "color": "#E8E8E8", "icon": "star"},
    {"name": "Gold", "min": 16, "color": "#FFE9B3", "icon": "star"},
    {"name": "Silver", "min": 4, "color": "#E5E5E5", "icon": "shield"},
    {"name": "Bronze", "min": 0, "color": "#F4D9C0", "icon": "shield"},
]

def get_tier(team_size: int) -> Dict[str, Any]:
    for t in TIERS:
        if team_size >= t["min"]:
            return t
    return TIERS[-1]

# ---- Admin role buckets ----
ADMIN_ROLES_NON_FINANCE = ("super_admin", "manager", "support")

# ---- Branding ----
DEFAULT_BRANDING: Dict[str, Any] = {
    "app_name": "NetworkPay",
    "tagline": "Track your referrals, earnings and grow your team.",
    "login_subtitle": "Sign in to your network",
    "payment_hero": "Complete your registration",
    "pending_hero": "Awaiting finance approval",
    "colors": {
        "primary": "#143D2E",
        "primaryFg": "#FFFFFF",
        "accent": "#E57A44",
        "accentFg": "#FFFFFF",
        "background": "#FAF9F6",
        "surface": "#FFFFFF",
        "surfaceMuted": "#F3F1EC",
        "success": "#2E7D52",
        "warning": "#D9A05B",
        "textMain": "#1C2520",
        "textMuted": "#6B7280",
        "border": "#E5E4E0",
    },
    "font": "system",
    # Custom splash overlay shown for `splash_duration_ms` after the native
    # Expo splash dismisses. Admin can upload a base64 image + tweak duration.
    # Recommended resolution: 1080×1920 (9:16 portrait, ~500KB max).
    "splash_image":       None,        # base64 data URI or http URL (null = no overlay)
    "splash_duration_ms": 5000,        # default 5s — admin can set 1000-10000
    "splash_bg":          "#143D2E",   # solid background behind the image
    # ─── Payment methods config (Feb-2026) ───
    # Razorpay is HIDDEN by default (manual UPI flow is preferred for now).
    # Admin can flip `razorpay_enabled=true` to re-enable the Razorpay UI.
    # `payee_upi_id` + `payee_name` are used in the `upi://` deep link.
    "payment_methods": {
        "razorpay_enabled":   False,
        "upi_manual_enabled": True,
        "payee_upi_id":       "",      # e.g. "kiran@ibl"
        "payee_name":         "",      # display name on UPI app, default uses app_name
    },
    "tabs": [
        {"key": "dashboard", "label": "Dashboard", "icon": "home", "visible": True},
        {"key": "network", "label": "Network", "icon": "git-branch", "visible": True},
        {"key": "wallet", "label": "Wallet", "icon": "credit-card", "visible": True},
        {"key": "shop", "label": "Shop", "icon": "shopping-bag", "visible": True},
        {"key": "profile", "label": "Profile", "icon": "user", "visible": True},
    ],
}

ALLOWED_FONTS = {"system", "inter", "poppins", "jakarta", "manrope", "dmsans"}
ALLOWED_TAB_KEYS = {"dashboard", "network", "wallet", "shop", "profile"}
