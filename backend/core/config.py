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
# Dec 2026 — MUST come from environment.  If unset, we DO NOT provide a
# fallback so a production deploy never boots with a predictable
# admin@app.com / Admin@123 credential pair.  Deployments should set
# ADMIN_EMAIL and ADMIN_PASSWORD in the pipeline env.
ADMIN_EMAIL = os.environ['ADMIN_EMAIL']
ADMIN_PASSWORD = os.environ['ADMIN_PASSWORD']

# ---- Subscription fee ----
REGISTRATION_FEE = float(os.environ.get('REGISTRATION_FEE', 118))

# ---- Purchase cashback (MLM cutover, Jun-2026) ----
# HARD platform ceiling. No vendor, admin, product or campaign value may
# ever exceed this. Enforced server-side in core/cashback.py.
MAX_CASHBACK_PCT = 10.0

DEFAULT_SETTINGS: Dict[str, Any] = {
    "registration_fee": REGISTRATION_FEE,
    "vendor_commission_pct": 70,
    # ── Purchase cashback ────────────────────────────────────────────────
    # Credited to the customer wallet ONLY after a successful delivery.
    # `default_cashback_pct` applies to products that don't set their own.
    "max_cashback_pct": MAX_CASHBACK_PCT,
    "default_cashback_pct": 0.0,
    "cashback_enabled": True,
    # Platform may front the cashback when a vendor wallet is short; the
    # amount becomes a vendor outstanding recoverable by Slangcart.
    "cashback_platform_funding_enabled": True,
    # ── Delivery charges ────────────────────────────────────────────────
    "delivery_charge_enabled": True,
    "delivery_charge_flat": 30.0,          # charged per vendor below the threshold
    "delivery_free_threshold": 500.0,      # per-vendor subtotal for free delivery
    "delivery_cart_max": 40.0,             # cap on the WHOLE cart's delivery
    # ── Returns ─────────────────────────────────────────────────────────
    # Cashback already credited is always clawed back on a return; if the
    # wallet is short the shortfall is netted off the refund payout.
    "cashback_clawback_on_return": True,
    # Phase 2 — product returns after successful delivery.
    "return_window_minutes": 10,
    "return_vendor_window_hours": 24,
    # Delivery charge is NOT refunded by default (owner's policy). When
    # switched on it is refunded as its own ledger component, never mixed
    # into the item refund.
    "return_delivery_refundable": False,
    "return_refund_method": "customer_wallet",
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

# ---- Admin role buckets ----
ADMIN_ROLES_NON_FINANCE = ("super_admin", "manager", "support")

# ---- Branding ----
DEFAULT_BRANDING: Dict[str, Any] = {
    "app_name": "Slangcart",
    "tagline": "Shop local vendors. Get cashback on every delivered order.",
    "login_subtitle": "Sign in to your Slangcart account",
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
    # ─── Premium theme controls (June 2026) ───
    # Lets admin set a hero gradient, button shape and home-screen banner
    # so the app's onboarding/payment screens can be themed without code.
    "gradient": {
        "start":  "#0A0E27",   # Deep blue
        "middle": "#1E2A78",   # Mid royal
        "end":    "#5B21B6",   # Purple
        "glow":   "#06B6D4",   # Cyan glow blob
    },
    "button_style": "rounded",   # "rounded" | "pill" | "square"
    "home_banner_b64": None,     # base64 image overlay on home screen
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
        {"key": "wallet", "label": "Wallet", "icon": "credit-card", "visible": True},
        {"key": "shop", "label": "Shop", "icon": "shopping-bag", "visible": True},
        {"key": "profile", "label": "Profile", "icon": "user", "visible": True},
    ],
}

ALLOWED_FONTS = {"system", "inter", "poppins", "jakarta", "manrope", "dmsans"}
ALLOWED_TAB_KEYS = {"dashboard", "wallet", "shop", "profile"}
