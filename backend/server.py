from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import json
import logging
import asyncio
import re
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import bcrypt
import httpx
import jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Query, Body
from fastapi.responses import Response, HTMLResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
from invoices import (
    invoice_html as _build_invoice_html,
    invoice_pdf as _build_invoice_pdf,
    invoice_number_for as _invoice_number_for,
    is_invoiceable as _is_invoiceable,
)
from pydantic import BaseModel, EmailStr, Field
from models import (
    RegisterRequest,
    LoginRequest,
    BankUpdate,
    WithdrawalRequest,
    ProductCreate,
    ProductUpdate,
    BrandingPayload,
    GoogleExchange,
    CreateOrderResponse,
    VerifyPaymentRequest,
    PaymentFailureRequest,
    WalletTransfer,
    WithdrawalCompleteRequest,
    WithdrawalRejectRequest,
    WithdrawalBatchRequest,
    AdminUserUpdate,
    AdminPasswordReset,
    AdminCreate,
    PromoteRequest,
    SuperPasswordSet,
    SuperPasswordVerify,
    DangerPinSet,
    WipeUsersRequest,
    WipeAllRequest,
    SettingsUpdate,
    CartItem,
    CartRemove,
    KYCSubmit,
    KYCReject,
    ApprovalReject,
    AdminCreateUserRequest,
    ExtraDocsSubmit,
    BlockRequest,
    WalletAdjust,
    SystemWalletDeposit,
    TxnStatusUpdate,
    OrderStatusUpdate,
    TakeBackupRequest,
    RestoreBackupRequest,
    PaymentGatewayPayload,
    VendorApplyRequest,
    VendorRejectRequest,
    ServiceApplyRequest,
    ServiceRejectRequest,
    ServiceBookRequest,
    ServiceCategoryCreate,
    ServiceCategoryUpdate,
    ProviderLocationUpdate,
    DistributorAreaAssign,
    DistributorPromote,
)


# ------------------ Core imports ------------------
# Phase 2A refactor: shared utilities live in /app/backend/core/.
# server.py keeps its existing variable names by re-binding the imports below
# so the route handlers further down DO NOT need to change.
from core.db import client, db, MONGO_URL, DB_NAME  # noqa: E402
from core.config import (  # noqa: E402
    JWT_SECRET,
    JWT_ALGORITHM,
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    REGISTRATION_FEE,
    PAYOUT_PER_LEVEL,
    LEVEL_2_PAYOUT,
    LEVEL_3_PAYOUT,
    DIRECTS_REQUIRED,
    DEFAULT_LEVEL_PAYOUTS,
    DEFAULT_SETTINGS,
    REFERRAL_GST_PCT,
    TIERS,
    get_tier,
    ADMIN_ROLES_NON_FINANCE,
    DEFAULT_BRANDING,
    ALLOWED_FONTS,
    ALLOWED_TAB_KEYS,
)
from core.security import (  # noqa: E402
    security,
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_admin,
    require_admin_role,
    require_admin_not_finance,
)
from core.utils import (  # noqa: E402
    now_utc,
    serialize_user,
    gen_referral_code,
    get_settings,
    audit_log as _audit_log,
    security_event as _security_event,
)
from core.danger import (  # noqa: E402
    SUPER_PWD_SYMBOLS,
    SUPER_PWD_FORMAT_DESC,
    validate_super_password_format,
    get_super_password_hash,
    verify_super_password,
    DANGER_PIN_FORMAT_DESC,
    validate_danger_pin_format,
    get_danger_pin_hash,
    verify_danger_pin,
)
# Phase 2B: shared notification + branding helpers + routers
from core.notifications import create_notification as _create_notification  # noqa: E402,F401
from core.branding import (  # noqa: E402
    get_branding_doc as _get_branding_doc,
    merge_branding as _merge_branding,
)
from routes import branding as branding_router  # noqa: E402
from routes import notifications as notifications_router  # noqa: E402
from routes import products_public as products_public_router  # noqa: E402
from routes import promo_banners as promo_banners_router  # noqa: E402
from routes import shop_layout as shop_layout_router  # noqa: E402
from routes import shop_layout_analytics as shop_layout_analytics_router  # noqa: E402
from routes import chat as chat_router  # noqa: E402
from routes import products_extended as products_extended_router  # noqa: E402
from routes import products_ai as products_ai_router  # noqa: E402
from routes import shop_categories as shop_categories_router  # noqa: E402
from routes import tickets as tickets_router  # noqa: E402
from routes import pincodes as pincodes_router  # noqa: E402
from routes import legal_pages as legal_pages_router  # noqa: E402
from routes import upi_manual as upi_manual_router  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ------------------ Models ------------------
# (DEFAULT_BRANDING / ALLOWED_FONTS / ALLOWED_TAB_KEYS are imported from core.config above.)


# ------------------ FastAPI App ------------------
app = FastAPI(title="Referral & E-commerce API")
api_router = APIRouter(prefix="/api")

# Performance / Security middleware ────────────────────────────────────────
# 1. GZip — compresses every response >1KB. Reduces network bytes by 60-80%
#    on JSON-heavy admin endpoints (users list, analytics, transactions).
# 2. Rate limiter — protects auth & payment endpoints from brute-force /
#    credential-stuffing / replay attacks. Friendly 429 instead of hard ban.
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from core.rate_limit import limiter as _rate_limiter, rate_limit_handler  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.state.limiter = _rate_limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


# Local alias so the @decorator syntax stays compact at the route definitions.
# (Importing as `_rate_limiter` keeps things explicit while preserving the
# already-exported `limiter` attribute on app.state above.)
_rl = _rate_limiter


# ------------------ Auth Endpoints ------------------
# Rate-limit register at 5/min per IP — generous for typos but tight enough
# to deter credential-stuffing scripts that try a list of emails fast.
@api_router.post("/auth/register")
@_rl.limit("5/minute")
async def register(request: Request, payload: RegisterRequest):
    email = payload.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    sponsor = None
    sponsor_code = (payload.referral_code or "").strip().upper() or None
    # `no_referral_signup` is True when the user did not provide a valid
    # sponsor referral code. Used by _trigger_referral_commissions to route
    # the registration fee (GST-inclusive) into admin's `direct_signup` bucket
    # and into the GST bucket — separate from the L1..L10 cascade payouts.
    no_referral_signup = False
    if sponsor_code:
        sponsor = await db.users.find_one({"referral_code": sponsor_code})
        if not sponsor:
            raise HTTPException(status_code=400, detail="Invalid referral code")
        # Capture the ORIGINAL inviter BEFORE any spillover so commission
        # ownership stays with them even when the placement moves deeper.
        referral_owner = sponsor

        if sponsor.get("email") == ADMIN_EMAIL.lower():
            # EARN code → admin-direct signup with placement spillover.
            no_referral_signup = True
            sponsor = await get_admin_sponsor() or sponsor
        else:
            # USER SPILLOVER — once the referrer has completed at least one
            # L1 cycle, NEW joiners they invite are SPILLED deeper into the
            # team using BFS + 4→3→2→1→0 preference. The original referrer
            # remains the commission owner (referral_owner_id) so they STILL
            # earn the L1 cycle credit from this new direct.
            if int(sponsor.get("payouts_received") or 0) >= 1:
                spill = await _find_spillover_under(sponsor)
                if spill:
                    sponsor = spill  # tree placement moves deeper
    else:
        # No referral code given → treat as direct admin signup. Money flows
        # to admin's `direct_signup` bucket on approval (see
        # _trigger_referral_commissions). User is still placed in the matrix
        # under the most-qualified downline so the cascade can fire.
        no_referral_signup = True
        sponsor = await get_admin_sponsor()
        referral_owner = sponsor  # for no-ref, owner == placement

    user_id = str(uuid.uuid4())
    # Ensure unique referral code
    while True:
        code = gen_referral_code()
        if not await db.users.find_one({"referral_code": code}):
            break

    user_doc = {
        "id": user_id,
        "name": payload.name.strip(),
        "email": email,
        "password_hash": hash_password(payload.password),
        "phone": payload.phone,
        "role": "user",
        "admin_role": None,
        "referral_code": code,
        "referred_by": sponsor["referral_code"] if sponsor else None,
        "sponsor_id": sponsor["id"] if sponsor else None,
        "wallet_balance": 0.0,
        "total_earned": 0.0,
        "registration_paid": False,
        "payment_attempts": 0,
        "last_payment_failure_at": None,
        "direct_referrals_count": 0,
        "payouts_received": 0,
        "upi_id": None,
        "bank_account": None,
        "ifsc": None,
        "account_holder": None,
        "is_blocked": False,
        "block_reason": None,
        "wallet_frozen": False,
        "kyc_status": "none",
        "kyc_full_name": None,
        "kyc_aadhaar": None,
        "kyc_pan": None,
        "kyc_submitted_at": None,
        "kyc_reviewed_at": None,
        "kyc_reject_reason": None,
        # Admin approval gate (gates payout entry + withdrawals)
        "approval_status": "pending",  # pending | approved | rejected
        "approval_reviewed_at": None,
        "approval_reviewed_by": None,
        "approval_reject_category": None,
        "approval_reject_reason": None,
        "commission_triggered": False,
        "no_referral_signup": no_referral_signup,
        # `sponsor_id` is the TREE-PLACEMENT parent (may be reassigned by
        # spillover BFS so the matrix stays balanced).
        # `referral_owner_id` is the ORIGINAL inviter who owns the L1
        # commission credit — never changes after signup. For no-ref/EARN
        # signups, owner == placement (admin or downline).
        "referral_owner_id": (referral_owner or sponsor or {}).get("id"),
        "referral_owner_code": (referral_owner or sponsor or {}).get("referral_code"),
        # ─── PLACEMENT AUDIT TRAIL (Feb-2026) ──────────────────────────
        # `original_sponsor_id` is the placement at signup time (AFTER BFS
        # spillover but BEFORE any admin-triggered manual realignment).
        # `original_referral_code` snapshot of what the user actually typed.
        # `placement_history` records every move (auto or manual) with who,
        # why, and when — no money is recalculated, just lineage tracking.
        "original_sponsor_id": sponsor["id"] if sponsor else None,
        "original_sponsor_code": sponsor["referral_code"] if sponsor else None,
        "original_referral_code": sponsor_code,  # raw input from signup form
        "placement_history": [],
        "placement_realigned_at": None,
        "placement_realigned_reason": None,
        "extra_docs": {
            "cibil_report": None,
            "bank_statement": None,
            "income_proof": None,
            "other": None,
            "submitted_at": None,
        },
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(user_doc)

    token = create_access_token(user_id, email, "user")
    return {"token": token, "user": serialize_user(user_doc)}


@api_router.post("/auth/login")
@_rl.limit("10/minute")
async def login(request: Request, payload: LoginRequest):
    email = payload.email.lower().strip()
    # Best-effort client IP (reads X-Forwarded-For when behind nginx/k8s ingress).
    client_ip = (request.headers.get("x-forwarded-for") or request.client.host if request.client else None or "").split(",")[0].strip() or None
    user = await db.users.find_one({"email": email})
    # IMPORTANT: use `user.get("password_hash") or ""` instead of indexing the
    # field directly.  Accounts created via Google OAuth (POST /auth/google/
    # exchange) have NO password_hash, so `user["password_hash"]` would raise
    # a KeyError → uncaught → 500 Internal Server Error.  By falling back to
    # an empty string, verify_password() returns False cleanly and the user
    # gets the proper 401 "Invalid credentials" message.  This was the exact
    # bug a deployed user hit when trying to log in.
    if not user or not verify_password(payload.password, user.get("password_hash") or ""):
        # Log every failed login for incident-response. Cheap insert into
        # security_events; never blocks the response.
        await _security_event(
            "auth.failed_login",
            user_id=user["id"] if user else None,
            email=email,
            ip=client_ip,
            details={"reason": "bad_credentials" if user else "unknown_email"},
            severity="warning",
        )
        # Before returning a generic 401, check if this email belongs to a rejected
        # registration archive record — give the user a category-specific message
        # so they know why they can't log in. Only do this on a plain not-found case
        # (we don't want to reveal password validity, so we still require the
        # password field to be present).
        if not user and payload.password:
            archived = await db.rejected_registrations.find_one(
                {"email": email}, {"_id": 0, "category": 1, "remarks": 1}, sort=[("rejected_at", -1)],
            )
            if archived:
                cat = archived.get("category") or "other"
                msg_map = {
                    "payment_unsuccessful": "Your registration payment was unsuccessful. Please contact support to re-register.",
                    "referral_code_mistake": "Your referral code was invalid. Please contact support to re-register.",
                    "other": archived.get("remarks") or "Your registration was rejected. Please contact support.",
                }
                raise HTTPException(status_code=403, detail=msg_map.get(cat, msg_map["other"]))
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("is_blocked"):
        reason = user.get("block_reason") or "Contact support."
        raise HTTPException(status_code=403, detail=f"Account blocked: {reason}")
    # Non-admin users whose registration was rejected (legacy in-place) cannot sign in.
    if user.get("role") == "user" and user.get("approval_status") == "rejected":
        cat = user.get("approval_reject_category") or "other"
        msg_map = {
            "payment_unsuccessful": "Your registration payment was unsuccessful. Please contact support.",
            "referral_code_mistake": "Your referral code was invalid. Please contact support to re-register.",
            "other": user.get("approval_reject_reason") or "Your registration was rejected. Please contact support.",
        }
        raise HTTPException(status_code=403, detail=msg_map.get(cat, msg_map["other"]))
    token = create_access_token(user["id"], email, user.get("role", "user"))
    # Multi-IP anomaly check: if the user has logged-in from a different IP
    # within the last 15 minutes, flag it (informational — does not block).
    try:
        recent_ip = user.get("last_login_ip")
        if client_ip and recent_ip and recent_ip != client_ip:
            await _security_event(
                "auth.multi_ip_login",
                user_id=user["id"],
                email=email,
                ip=client_ip,
                details={"previous_ip": recent_ip},
                severity="warning",
            )
        # Stamp the user with the current login IP/time so future logins can
        # diff against it (cheap upsert, no extra query).
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"last_login_ip": client_ip, "last_login_at": now_utc().isoformat()}},
        )
    except Exception:
        pass
    return {"token": token, "user": serialize_user(user)}


# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH


@api_router.post("/auth/google/exchange")
@_rl.limit("10/minute")
async def google_exchange(request: Request, payload: GoogleExchange):
    """Exchange an Emergent session_id for our JWT bearer token. Creates user on first sign-in."""
    # OAuth session-data URL is environment-configurable so the same code runs
    # in dev (Emergent demo) and prod (customer's own OAuth proxy if any).
    session_url = os.environ.get(
        "EMERGENT_OAUTH_SESSION_URL",
        "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            session_url,
            headers={"X-Session-ID": payload.session_id},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google session")
    data = r.json()
    email = (data.get("email") or "").lower().strip()
    name = data.get("name") or "Google user"
    picture = data.get("picture")
    google_id = data.get("id")
    if not email:
        raise HTTPException(status_code=400, detail="Google account did not return an email")

    user = await db.users.find_one({"email": email})
    is_new = False
    if not user:
        # Create new user
        sponsor = None
        sponsor_code = (payload.referral_code or "").strip().upper() or None
        if sponsor_code:
            sponsor = await db.users.find_one({"referral_code": sponsor_code})
        if not sponsor or sponsor.get("email") == ADMIN_EMAIL.lower():
            # No / invalid referral OR explicit EARN → spillover-aware admin sponsor
            sponsor = (await get_admin_sponsor()) or sponsor
        # Generate unique referral code
        while True:
            code = gen_referral_code()
            if not await db.users.find_one({"referral_code": code}):
                break
        user_id = str(uuid.uuid4())
        # Random password (Google users login via Google)
        random_password = secrets.token_hex(20)
        user = {
            "id": user_id,
            "name": name,
            "email": email,
            "password_hash": hash_password(random_password),
            "phone": None,
            "role": "user",
            "admin_role": None,
            "google_id": google_id,
            "picture": picture,
            "auth_provider": "google",
            "referral_code": code,
            "referred_by": sponsor["referral_code"] if sponsor else None,
            "sponsor_id": sponsor["id"] if sponsor else None,
            "wallet_balance": 0.0,
            "total_earned": 0.0,
            "registration_paid": False,
            "payment_attempts": 0,
            "last_payment_failure_at": None,
            "direct_referrals_count": 0,
            "payouts_received": 0,
            "upi_id": None,
            "bank_account": None,
            "ifsc": None,
            "account_holder": None,
            "is_blocked": False,
            "block_reason": None,
            "wallet_frozen": False,
            "kyc_status": "none",
            "kyc_full_name": None,
            "kyc_aadhaar": None,
            "kyc_pan": None,
            "kyc_submitted_at": None,
            "kyc_reviewed_at": None,
            "kyc_reject_reason": None,
            "approval_status": "pending",
            "approval_reviewed_at": None,
            "approval_reviewed_by": None,
            "approval_reject_category": None,
            "approval_reject_reason": None,
            "commission_triggered": False,
            "extra_docs": {
                "cibil_report": None,
                "bank_statement": None,
                "income_proof": None,
                "other": None,
                "submitted_at": None,
            },
            "created_at": now_utc().isoformat(),
        }
        await db.users.insert_one(user)
        is_new = True
        await _create_notification(user_id, "welcome", "Welcome to NetworkPay!", "Signed in with Google. Complete the ₹100 activation to start earning.")
    else:
        # Existing user: backfill google_id/picture if missing, refresh picture
        update = {}
        if not user.get("google_id"):
            update["google_id"] = google_id
        if picture and user.get("picture") != picture:
            update["picture"] = picture
        if update:
            await db.users.update_one({"id": user["id"]}, {"$set": update})

    if user.get("is_blocked"):
        reason = user.get("block_reason") or "Contact support."
        raise HTTPException(status_code=403, detail=f"Account blocked: {reason}")

    token = create_access_token(user["id"], email, user.get("role", "user"))
    return {"token": token, "user": serialize_user(user), "is_new": is_new}


@api_router.get("/auth/google/callback")
async def google_callback():
    """Trivial endpoint Emergent redirects to. Returns a tiny success page; the mobile WebBrowser
    captures this URL (with the #session_id fragment) and the app handles the exchange."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>Sign in</title></head>"
        "<body style='font-family:system-ui;text-align:center;padding:40px;background:#FAF9F6;color:#143D2E'>"
        "<h2>You are signed in</h2><p>You can close this window.</p>"
        "<script>setTimeout(()=>window.close(),200);</script></body></html>"
    )


@api_router.get("/auth/me")
async def me(user: Dict[str, Any] = Depends(get_current_user)):
    return serialize_user(user)


@api_router.post("/auth/logout")
async def logout(user: Dict[str, Any] = Depends(get_current_user)):
    return {"ok": True}


# ------------------ Payment (Mock) ------------------
async def _credit_no_ref_signup_to_admin(joiner: Dict[str, Any], placement_sponsor: Optional[Dict[str, Any]]) -> None:
    """Credit admin's `direct_signup` bucket for users who joined WITHOUT a
    referral code. GST-INCLUSIVE math: settings.registration_fee is the gross
    total paid by the user.

      gross = settings.registration_fee  (e.g. 118)
      gst   = gross × 18 / 118           (₹18 → routed to gst_collected)
      net   = gross − gst                (₹100 → routed to direct_signup)

    This is SEPARATE from the L1..L10 cascade. The cascade still fires up
    from the placement_sponsor afterward, so admin earns L2..L10 normally.
    """
    settings = await get_settings()
    gross = float(settings.get("registration_fee") or 0)
    if gross <= 0:
        return
    # GST-inclusive: GST is a portion of the gross
    gst = round(gross * (REFERRAL_GST_PCT / (100.0 + REFERRAL_GST_PCT)), 2)
    net = round(gross - gst, 2)

    ts = now_utc().isoformat()
    ref = f"DIRSU-{str(uuid.uuid4())[:8].upper()}"

    await credit_admin_bucket("direct_signup", net, also_total_earned=True)
    if gst > 0:
        await credit_admin_bucket("gst_collected", gst, also_total_earned=False)

    admin_user = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin_user:
        return

    placement_name = (placement_sponsor or {}).get("name") or "admin"
    placement_email = (placement_sponsor or {}).get("email") or ""

    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": admin_user["id"],
        "type": "direct_signup_credit",
        "amount": net,
        "gross_amount": gross,
        "gst_amount": gst,
        "gst_pct": REFERRAL_GST_PCT,
        "status": "success",
        "description": (
            f"Direct join (no referral) · {joiner.get('name','')} · "
            f"placed under {placement_name} · ₹{gross:g} gross − ₹{gst} GST = ₹{net} net"
        ),
        "source_user_id": joiner["id"],
        "source_user_name": joiner.get("name"),
        "source_user_email": joiner.get("email"),
        "placement_sponsor_id": (placement_sponsor or {}).get("id"),
        "placement_sponsor_name": placement_name,
        "placement_sponsor_email": placement_email,
        "reference_number": ref,
        "created_at": ts,
    })

    if gst > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_user["id"],
            "type": "gst_collected",
            "amount": gst,
            "status": "success",
            "description": (
                f"GST {int(REFERRAL_GST_PCT)}% on direct signup of {joiner.get('name','')} "
                f"(gross ₹{gross:g})"
            ),
            "source_user_id": joiner["id"],
            "source_user_name": joiner.get("name"),
            "linked_payout_to_user_id": joiner["id"],
            "reference_number": ref + "-GST",
            "created_at": ts,
        })


async def _credit_cascade_overflow_to_admin(joiner_name: str, missing_levels: List[int], level_payouts: List[float]) -> None:
    """When the upline chain runs out before all 10 levels are paid, the
    remaining (uncascaded) L_N..L10 amounts must not be lost — they're
    routed to admin's `referral_commission` bucket as overflow.
    """
    admin_user = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin_user or not missing_levels:
        return
    ts = now_utc().isoformat()
    for lv in missing_levels:
        amt = float(level_payouts[lv - 1] or 0)
        if amt <= 0:
            continue
        await credit_admin_bucket("referral_commission", amt, also_total_earned=True)
        ref = f"OVRFL-L{lv}-{str(uuid.uuid4())[:6].upper()}"
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_user["id"],
            "type": "cascade_overflow",
            "level": lv,
            "amount": amt,
            "status": "success",
            "description": (
                f"L{lv} cascade overflow · upline chain ended before L{lv} · "
                f"source {joiner_name}"
            ),
            "source_user_name": joiner_name,
            "reference_number": ref,
            "created_at": ts,
        })



async def _credit_payout(sponsor_user: Dict[str, Any], amount: float, level: int, source_user_name: str = "", signup_id: Optional[str] = None):
    """Credit a referral payout to a sponsor at a given level.

    Business rule (FinCom #3 — Option B / GST-exclusive):
    The configured payout is the GROSS commission. We deduct 18% GST from it
    and route that GST to the admin's `gst_collected` bucket.
        GST = gross × 18%       → admin
        NET = gross − GST       → user wallet

    Example: gross ₹400 → GST ₹72 → user receives ₹328.

    For admin recipients (Level-1 reaching the seed admin via cycle), no split
    happens — admin receives the full amount in `referral_commission`.

    Idempotency: when `signup_id` is provided, a unique key
    `PAYOUT:{signup_id}:{recipient_id}:{level}` prevents double-credit if the
    cascade re-fires (e.g. retry, race). First writer wins; later attempts
    silently no-op.
    """
    # Per-level idempotency guard — prevents the same (signup, recipient,
    # level) tuple from ever being credited twice.
    if signup_id:
        idem_key = f"PAYOUT:{signup_id}:{sponsor_user['id']}:L{level}"
        try:
            await db.payout_keys.insert_one({
                "_id": idem_key,
                "signup_id": signup_id,
                "recipient_id": sponsor_user["id"],
                "level": level,
                "amount": float(amount),
                "created_at": now_utc().isoformat(),
            })
        except Exception:
            # Already credited — silent no-op
            return

    gross = float(amount)
    is_admin_recipient = (sponsor_user.get("email") or "").lower() == ADMIN_EMAIL.lower()
    ts = now_utc().isoformat()
    src_short = (source_user_name or "")[:30]
    base_ref = f"REF-L{level}-{str(uuid.uuid4())[:6].upper()}"

    if is_admin_recipient:
        # Admin gets full amount in referral_commission bucket — no split needed
        await credit_admin_bucket("referral_commission", gross, also_total_earned=True)
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": sponsor_user["id"],
            "type": "referral_payout",
            "level": level,
            "amount": gross,
            "gross_amount": gross,
            "status": "success",
            "description": f"Level {level} payout from {src_short}" if src_short else f"Level {level} referral payout",
            "source_user_name": src_short or None,
            "reference_number": base_ref,
            "related_signup_id": signup_id,
            "related_payout_recipient": sponsor_user["id"],
            "created_at": ts,
        })
        await _create_notification(sponsor_user["id"], "payout", f"₹{int(gross)} credited!", f"Level {level} referral payout")
        return

    # Non-admin sponsor — apply GST-exclusive split: 18% OF gross → admin
    gst = round(gross * (REFERRAL_GST_PCT / 100.0), 2)
    net = round(gross - gst, 2)

    # 1. Credit user wallet with NET
    inc: Dict[str, Any] = {"wallet_balance": net, "total_earned": net}
    if level == 1:
        inc["payouts_received"] = 1
    await db.users.update_one({"id": sponsor_user["id"]}, {"$inc": inc})
    user_desc = (
        f"Level {level} payout from {src_short}" if src_short else f"Level {level} referral payout"
    ) + f" · ₹{int(gross)} − ₹{gst} GST"
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": sponsor_user["id"],
        "type": "referral_payout",
        "level": level,
        "amount": net,                 # only the net is credited to the user
        "gross_amount": gross,         # informational — original gross
        "gst_amount": gst,             # informational — GST that was withheld
        "gst_pct": REFERRAL_GST_PCT,
        "status": "success",
        "description": user_desc,
        "source_user_name": src_short or None,
        "reference_number": base_ref,
        "related_signup_id": signup_id,
        "related_payout_recipient": sponsor_user["id"],
        "created_at": ts,
    })
    await _create_notification(
        sponsor_user["id"],
        "payout",
        f"₹{int(net)} credited!",
        f"Level {level} referral payout received (₹{int(gross)} gross − ₹{gst} GST = ₹{net} net)",
    )

    # 2. Credit admin's gst_collected bucket with the GST share
    await credit_admin_bucket("gst_collected", gst, also_total_earned=False)
    admin_user = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if admin_user and gst > 0:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_user["id"],
            "type": "gst_collected",
            "level": level,
            "amount": gst,
            "status": "success",
            "description": (
                f"GST {int(REFERRAL_GST_PCT)}% on L{level} payout to {sponsor_user.get('name')} "
                f"(gross ₹{int(gross)}) · triggered by {src_short or 'a downline activation'}"
            ),
            "source_user_name": src_short or sponsor_user.get("name"),
            "sponsor_name": sponsor_user.get("name"),  # who received the payout
            "sponsor_email": sponsor_user.get("email"),
            "gross_amount": gross,
            "gst_pct": REFERRAL_GST_PCT,
            "reference_number": base_ref + "-GST",
            "linked_payout_to_user_id": sponsor_user["id"],
            "created_at": ts,
        })


async def _trigger_referral_commissions(user: Dict[str, Any]) -> None:
    """Pay multi-level referral commissions when a user becomes 'approved'.
    Walks up to 10 levels of upline. L1 is paid every Nth direct, L2..L10 are
    credited per qualifying activation. Idempotent via commission_triggered flag.

    L1 trigger model (FIX 2025-06):
      Uses a per-sponsor `pending_directs` counter (NOT a modulo on the global
      direct_referrals_count). When admin changes the payout structure
      mid-flight, past payouts and progress are preserved — only the *next*
      threshold uses the new rule. Counter resets on payout.
    """
    if user.get("commission_triggered"):
        return
    settings = await get_settings()
    directs_required = settings["directs_required"]
    level_payouts = [settings.get(f"payout_l{i}", 0) or 0 for i in range(1, 11)]  # 10 levels
    sponsor_id = user.get("sponsor_id")
    # Mark first to avoid race-condition double trigger
    await db.users.update_one({"id": user["id"]}, {"$set": {"commission_triggered": True}})

    # ─────────────────────────────────────────────────────────────────
    # NO-REFERRAL SIGNUP — clean accounting model
    # ─────────────────────────────────────────────────────────────────
    # The user paid the registration fee directly to admin. Admin pockets
    # the FULL fee, split GST-inclusive into direct_signup (net) and
    # gst_collected (18%).  We DO NOT trigger the L1..L10 cascade or
    # overflow for this signup — the user came directly to admin with
    # no upline to compensate, so the books exactly equal the fee paid:
    #
    #     ₹118 paid  →  ₹100 to direct_signup  +  ₹18 to GST  =  ₹118
    #
    # This eliminates the "double-entry" concern (same signup credited
    # to both direct_signup AND referral_commission overflow) and keeps
    # admin wallet exactly equal to the actual revenue inflow.
    if user.get("no_referral_signup"):
        placement_sponsor = await db.users.find_one({"id": sponsor_id}) if sponsor_id else None
        # Bump the placement sponsor's direct_referrals_count so the matrix
        # tree view reflects this new direct (without firing the cascade).
        # NOTE: pending_directs is intentionally NOT incremented here — the
        # L1 cycle counter belongs to USER-referral flow only. EARN / no-ref
        # signups feed admin's `direct_signup` bucket directly.
        if sponsor_id and placement_sponsor and placement_sponsor.get("email") != ADMIN_EMAIL.lower():
            await db.users.update_one(
                {"id": sponsor_id},
                {"$inc": {"direct_referrals_count": 1}},
            )
        await _credit_no_ref_signup_to_admin(user, placement_sponsor)
        return  # ← stop here. No cascade. No overflow.

    if not sponsor_id:
        return

    # ─── Idempotency guard ────────────────────────────────────────────
    # Each cascade run is uniquely keyed by the new joiner id. A separate
    # `payout_keys` collection acts as the system-wide mutex so concurrent
    # approval calls cannot double-credit. The first writer wins.
    payout_run_key = f"PAYOUT-RUN:{user['id']}"
    try:
        await db.payout_keys.insert_one({
            "_id": payout_run_key,
            "joiner_id": user["id"],
            "created_at": now_utc().isoformat(),
        })
    except Exception:
        # Key already exists → cascade already ran for this joiner. Bail
        # cleanly so we never double-pay.
        return

    # ─── L1 commission OWNERSHIP (PLACEMENT-BASED, Option B) ───────────
    # Business rule: L1 commission goes to the user under whose tree the
    # new joiner was PLACED (sponsor_id). When BFS spillover applies,
    # sponsor_id is the deeper downline who actually got the new direct
    # in their leg — they earn the L1 cycle credit.
    # `referral_owner_id` is preserved separately as an audit/genealogy
    # field ("who originally invited this user") but does NOT receive L1.
    # L2..L10 cascade walks the TREE from sponsor_id upward as usual.
    sponsor = await db.users.find_one({"id": sponsor_id})
    if not sponsor:
        return
    tree_parent_id = sponsor_id  # for L2..L10 cascade walk
    # Atomically bump both counters; pending_directs starts at 0 if missing.
    await db.users.update_one(
        {"id": sponsor_id},
        {"$inc": {"direct_referrals_count": 1, "pending_directs": 1}},
    )
    fresh_sponsor = await db.users.find_one({"id": sponsor_id})
    new_count = int(fresh_sponsor.get("direct_referrals_count", 0))
    pending = int(fresh_sponsor.get("pending_directs", 0))
    payout_l1 = level_payouts[0]
    remaining = max(0, directs_required - pending)
    await _create_notification(
        sponsor_id, "referral",
        f"New referral: {user['name']}",
        f"{user['name']} just joined your network. {remaining} more to next ₹{int(payout_l1)} payout.",
    )
    # Fire L1 payout when pending counter hits the configured threshold.
    # Use $inc -directs_required to handle the case where admin lowered the
    # threshold mid-flight (preserves overflow for next payout).
    if pending >= directs_required and payout_l1 > 0:
        await db.users.update_one(
            {"id": sponsor_id},
            {"$inc": {"pending_directs": -directs_required}},
        )
        fresh = await db.users.find_one({"id": sponsor_id})
        await _credit_payout(fresh, payout_l1, 1, user["name"], signup_id=user["id"])

        # ─── L1 FUNDING SOURCE (ledger integrity) ───────────────────────
        # L1 payout (e.g. ₹400) is much larger than the ₹118 fee, so the
        # money credited to the upline must come from somewhere accounted
        # for — otherwise it's "minted from thin air" and Held > Inflow.
        # We fund it from admin's `fee_residual` bucket which has been
        # accumulating the leftover from each of the `directs_required`
        # contributing signups (~₹95 each × 5 = ~₹475, enough to cover a
        # ₹400 L1). Falls back to `direct_signup` if fee_residual is
        # short; finally `referral_commission` as last resort.
        admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
        if admin_doc:
            remaining_to_fund = float(payout_l1)
            for source_bucket in ("fee_residual", "direct_signup", "referral_commission"):
                if remaining_to_fund <= 0.01:
                    break
                # Re-read admin doc each iteration since prior $inc may have changed it
                admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
                available = float((admin_doc.get("wallet_buckets") or {}).get(source_bucket) or 0)
                if available <= 0:
                    continue
                debit = round(min(available, remaining_to_fund), 2)
                await credit_admin_bucket(source_bucket, -debit, also_total_earned=False)
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_doc["id"],
                    "type": "l1_funding",
                    "amount": -debit,
                    "status": "success",
                    "description": (
                        f"L1 payout funded from {source_bucket} "
                        f"(₹{debit} for cycle of {directs_required} directs)"
                    ),
                    "source_bucket": source_bucket,
                    "related_signup_id": user["id"],
                    "related_payout_recipient": sponsor_id,
                    "created_at": now_utc().isoformat(),
                })
                remaining_to_fund -= debit
            # If fee_residual + direct_signup + referral_commission combined
            # are insufficient (only possible if admin debited them earlier),
            # log a residual shortfall — admin can top-up via UTR direct_added.
            if remaining_to_fund > 0.01:
                logger.warning(
                    f"L1 funding shortfall: ₹{remaining_to_fund} unfunded for "
                    f"cycle to {sponsor_id} — admin should top-up direct_added."
                )

    # Walk up levels 2..10 along the TREE (sponsor_id chain). The placement
    # parent (sponsor_id) already received the L1 cycle credit above, so we
    # start the cascade at the placement parent's sponsor (grandparent of
    # the new joiner) — preventing double payment to the placement parent.
    tree_parent = await db.users.find_one({"id": tree_parent_id})
    current_id = (tree_parent or {}).get("sponsor_id")
    paid_levels: List[int] = []
    for level in range(2, 11):
        if not current_id:
            break
        upline = await db.users.find_one({"id": current_id})
        if not upline:
            break
        # Skip blocked users in the cascade (but keep walking the chain)
        if upline.get("is_blocked"):
            current_id = upline.get("sponsor_id")
            continue
        amt = level_payouts[level - 1]
        if amt > 0:
            await _credit_payout(upline, amt, level, user["name"], signup_id=user["id"])
            paid_levels.append(level)
        current_id = upline.get("sponsor_id")

    # Cascade-overflow: any L2..L10 amounts that COULDN'T be paid because the
    # upline chain ended early are rerouted to admin's referral_commission
    # bucket so the configured payout pool isn't silently lost.
    missing_levels = [lv for lv in range(2, 11) if lv not in paid_levels and (level_payouts[lv - 1] or 0) > 0]
    if missing_levels:
        await _credit_cascade_overflow_to_admin(user["name"], missing_levels, level_payouts)

    # ── Fee-residual safety net ────────────────────────────────────────
    # When configured cascade payouts (incl. L2..L10 + their GST and
    # overflow) sum to LESS than the registration fee, the difference
    # would otherwise vanish from the books — the user paid ₹118 but
    # only e.g. ₹22 was credited internally, creating a permanent drift.
    # We route that residual to admin's `fee_residual` bucket so 100%
    # of every paid fee is always accounted for in some wallet.
    #
    # NOTE: L1 payouts are EXCLUDED from this sum — they're funded
    # SEPARATELY from the accumulated fee_residual pool via `l1_funding`
    # txns. If we included L1 here, the 6th signup (that triggers L1)
    # would see cascade > fee and skip the residual write, silently
    # losing its own ₹95.95 contribution to the pool.
    fee_paid = float(settings.get("registration_fee") or 0)
    total_credited_for_signup = 0.0
    # Sum every L2..L10 payout txn linked to this signup that we just wrote.
    async for txn in db.transactions.find({
        "$or": [
            {"related_signup_id": user["id"]},
            {"description": {"$regex": user["name"][:20]}, "type": {"$in": [
                "referral_payout", "gst_collected", "cascade_overflow",
            ]}, "status": "success", "created_at": {"$gte": user.get("created_at", "")}},
        ],
    }, {"_id": 0, "type": 1, "amount": 1, "gross_amount": 1, "level": 1}):
        # SKIP L1 — it's funded from the existing fee_residual pool, not
        # from THIS signup's fee. Including it would zero out the residual
        # for L1-cycle signups and silently lose ₹95.95 per cycle.
        if int(txn.get("level") or 0) == 1:
            continue
        if txn.get("type") == "referral_payout":
            # gross = net credited to user + GST routed to admin
            total_credited_for_signup += float(txn.get("gross_amount") or txn.get("amount") or 0)
        elif txn.get("type") in ("cascade_overflow",):
            total_credited_for_signup += float(txn.get("amount") or 0)
    residual = round(fee_paid - total_credited_for_signup, 2)
    if residual > 0.01:
        admin_user = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
        if admin_user:
            # Fee residual goes to its OWN dedicated bucket (`fee_residual`)
            # so it doesn't inflate the Direct Joins tile. Admin's overall
            # wallet_balance still receives this money — it's just labelled
            # separately for accounting clarity.
            await credit_admin_bucket("fee_residual", residual, also_total_earned=True)
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": admin_user["id"],
                "type": "fee_residual",
                "amount": residual,
                "status": "success",
                "description": (
                    f"Fee residual ₹{residual} from {user['name']}'s signup "
                    f"(₹{int(fee_paid)} fee − ₹{int(total_credited_for_signup)} cascade)"
                ),
                "related_signup_id": user["id"],
                "source_user_name": user["name"],
                "created_at": now_utc().isoformat(),
            })
    # Always mark the user as fee-residual-handled so the legacy cleanup
    # endpoint never double-credits them (regardless of whether a residual
    # was actually owed).
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"fee_residual_backfilled": True}},
    )


@api_router.post("/payment/register-fee")
async def pay_registration_fee(user: Dict[str, Any] = Depends(get_current_user)):
    """BACKWARD-COMPAT: Instant mock registration fee payment. Marks account paid.
    New flows should prefer /payment/create-order + /payment/verify (Razorpay-compatible).
    Note: referral commissions are NOT triggered here anymore — they trigger only after
    admin approves the user via /admin/approvals/{id}/approve."""
    if user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    settings = await get_settings()
    fee = settings["registration_fee"]

    txn_id = str(uuid.uuid4())
    await db.users.update_one({"id": user["id"]}, {"$set": {"registration_paid": True}})
    await db.transactions.insert_one({
        "id": txn_id,
        "user_id": user["id"],
        "type": "registration_fee",
        "amount": fee,
        "status": "paid",
        "description": "Registration fee (legacy mock)",
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(
        user["id"],
        "welcome",
        "Account activated — pending approval",
        "Thanks! Your registration is paid. An admin will review your profile shortly.",
    )
    return {"ok": True, "transaction_id": txn_id, "amount": fee, "approval_status": "pending"}


# ------------------ Razorpay-compatible payment flow (mock fallback) ------------------
# The backend ships with a "mock" mode when RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not
# configured. In mock mode, fake order IDs are generated and the /verify endpoint accepts
# any non-empty signature. When real keys are provided, we'll hit api.razorpay.com.
#
# Keys can be supplied via:
#   1) Admin Panel → Payment Gateway form (stored in settings.razorpay) [PREFERRED]
#   2) /app/backend/.env  (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET) — fallback
# DB override always wins over env so super_admin can rotate keys without redeploy.
RAZORPAY_ENV_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_ENV_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
MAX_PAYMENT_ATTEMPTS = 3


async def get_razorpay_creds() -> Dict[str, Any]:
    """Return active Razorpay credentials. Order of precedence: DB > env."""
    s = await get_settings()
    rzp = (s.get("razorpay") or {}) if isinstance(s.get("razorpay"), dict) else {}
    db_id = (rzp.get("key_id") or "").strip()
    db_secret = (rzp.get("key_secret") or "").strip()
    if db_id and db_secret:
        return {"key_id": db_id, "key_secret": db_secret, "source": "db", "is_mock": False}
    if RAZORPAY_ENV_KEY_ID and RAZORPAY_ENV_KEY_SECRET:
        return {"key_id": RAZORPAY_ENV_KEY_ID, "key_secret": RAZORPAY_ENV_KEY_SECRET, "source": "env", "is_mock": False}
    return {"key_id": "", "key_secret": "", "source": "none", "is_mock": True}


async def _fetch_razorpay_payment(payment_id: str, creds: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cross-check a Razorpay payment with their server. Returns None on mock/unreachable."""
    if creds.get("is_mock") or not creds.get("key_id") or not creds.get("key_secret") or not payment_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, auth=(creds["key_id"], creds["key_secret"])) as client:
            r = await client.get(f"https://api.razorpay.com/v1/payments/{payment_id}")
        if r.status_code == 200:
            return r.json()
        logger.warning(f"Razorpay payment fetch returned {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"Razorpay payment fetch failed: {e}")
    return None


def _extract_utr(rzp_payment: Optional[Dict[str, Any]]) -> str:
    """Pull the REAL UTR / acquirer reference number from Razorpay payment object.
    UPI: rrn or upi_transaction_id. Netbanking: bank_transaction_id. Card: auth_code.

    Returns empty string if no real settlement reference is present. We deliberately
    DO NOT fall back to the Razorpay payment id (`pay_xxx`) — that's a payment-gateway
    handle, not proof of bank settlement, so callers must treat the absence of a real
    UTR as "money has not yet been confirmed at the bank".
    """
    if not rzp_payment:
        return ""
    ad = rzp_payment.get("acquirer_data") or {}
    return (
        (ad.get("rrn") or "").strip()
        or (ad.get("upi_transaction_id") or "").strip()
        or (ad.get("bank_transaction_id") or "").strip()
        or (ad.get("auth_code") or "").strip()
    )


@api_router.get("/payment/config")
async def payment_config(user: Dict[str, Any] = Depends(get_current_user)):
    """Return public Razorpay config + user-specific payment state.
    Used by the frontend to render the checkout sheet."""
    settings = await get_settings()
    fee = settings["registration_fee"]
    attempts = int(user.get("payment_attempts") or 0)
    creds = await get_razorpay_creds()
    return {
        "key_id": creds["key_id"] or "rzp_test_MOCK",
        "is_mock": creds["is_mock"],
        "amount": fee,  # rupees
        "amount_paise": int(round(fee * 100)),
        "currency": "INR",
        "registration_paid": bool(user.get("registration_paid")),
        "approval_status": user.get("approval_status") or "pending",
        "attempts_used": attempts,
        "attempts_remaining": max(0, MAX_PAYMENT_ATTEMPTS - attempts),
        "max_attempts": MAX_PAYMENT_ATTEMPTS,
        "prefill": {
            "name": user.get("name"),
            "email": user.get("email"),
            "contact": user.get("phone") or "",
        },
        "description": "NetworkPay registration fee",
    }


@api_router.post("/payment/create-order")
async def payment_create_order(user: Dict[str, Any] = Depends(get_current_user)):
    """Create a Razorpay order (or mock order in dev). Returns order_id for checkout."""
    if user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    attempts = int(user.get("payment_attempts") or 0)
    if attempts >= MAX_PAYMENT_ATTEMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_PAYMENT_ATTEMPTS} payment attempts reached. Contact support.",
        )

    settings = await get_settings()
    amount_paise = int(round(settings["registration_fee"] * 100))
    creds = await get_razorpay_creds()

    if creds["is_mock"]:
        order_id = f"order_MOCK_{secrets.token_hex(8)}"
    else:
        async with httpx.AsyncClient(timeout=15.0, auth=(creds["key_id"], creds["key_secret"])) as client:
            r = await client.post(
                "https://api.razorpay.com/v1/orders",
                json={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": f"reg_{user['id'][:12]}",
                    "notes": {"user_id": user["id"], "email": user["email"]},
                },
            )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=502, detail=f"Razorpay order failed: {r.text}")
        order_id = r.json().get("id")

    # Record / refresh the pending transaction for traceability. We keep AT MOST
    # ONE `created` row per user — every "Pay" click replaces the previous pending
    # one rather than spawning a new row. This prevents the "5 phantom rows for
    # 1 payment" pollution that was inflating wallet history & total revenue.
    existing_pending = await db.transactions.find_one(
        {"user_id": user["id"], "type": "registration_fee", "status": "created"},
        {"_id": 0, "id": 1},
    )
    if existing_pending:
        await db.transactions.update_one(
            {"id": existing_pending["id"]},
            {"$set": {
                "razorpay_order_id": order_id,
                "amount": amount_paise / 100.0,
                "description": "Razorpay order created" + (" (mock)" if creds["is_mock"] else ""),
                "created_at": now_utc().isoformat(),
            }},
        )
    else:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "registration_fee",
            "amount": amount_paise / 100.0,
            "status": "created",
            "description": "Razorpay order created" + (" (mock)" if creds["is_mock"] else ""),
            "razorpay_order_id": order_id,
            "created_at": now_utc().isoformat(),
        })

    return CreateOrderResponse(
        order_id=order_id,
        amount_paise=amount_paise,
        currency="INR",
        key_id=creds["key_id"] or "rzp_test_MOCK",
        is_mock=creds["is_mock"],
    )


@api_router.post("/payment/verify")
async def payment_verify(payload: VerifyPaymentRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Verify Razorpay payment signature, cross-check with Razorpay server (UTR/amount/status),
    and auto-approve the user if `settings.auto_approve_on_payment` is True (default)."""
    if user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    if not payload.razorpay_signature or not payload.razorpay_payment_id or not payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Missing Razorpay fields")

    creds = await get_razorpay_creds()
    if not creds["is_mock"]:
        import hmac
        import hashlib
        expected = hmac.new(
            creds["key_secret"].encode(),
            f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, payload.razorpay_signature):
            raise HTTPException(status_code=401, detail="Invalid payment signature")

    settings = await get_settings()
    fee = settings["registration_fee"]
    expected_paise = int(round(fee * 100))

    # ---------------- Cross-check with Razorpay server (live mode only) ----------------
    rzp_payment = await _fetch_razorpay_payment(payload.razorpay_payment_id, creds)
    cross_check_ok = bool(creds["is_mock"])  # mock mode = trust HMAC
    rzp_status = "mock" if creds["is_mock"] else "unverified"

    if rzp_payment:
        rzp_status = (rzp_payment.get("status") or "").lower()
        rzp_order = rzp_payment.get("order_id")
        rzp_amount = int(rzp_payment.get("amount") or 0)
        if rzp_status not in ("captured", "authorized"):
            raise HTTPException(status_code=400, detail=f"Payment is not captured (Razorpay status: {rzp_status})")
        if rzp_order and rzp_order != payload.razorpay_order_id:
            raise HTTPException(status_code=400, detail="Payment order_id does not match the order on file")
        if rzp_amount and rzp_amount != expected_paise:
            raise HTTPException(status_code=400, detail=f"Payment amount mismatch: expected {expected_paise} paise, got {rzp_amount}")
        cross_check_ok = True
    elif not creds["is_mock"]:
        # Razorpay API unreachable — HMAC signature was valid, fall back to that.
        # Auto-approval still allowed per signature trust.
        cross_check_ok = True
        rzp_status = "signature_only"

    utr = _extract_utr(rzp_payment)
    has_real_utr = bool(utr)
    # In live mode, refuse to auto-approve (and skip the upline commission cascade)
    # if Razorpay hasn't yet returned a real bank-side UTR (rrn / upi_transaction_id /
    # bank_transaction_id / auth_code). The Razorpay payment_id (`pay_xxx`) by itself
    # is NOT proof that money settled at the bank — settling can take seconds–minutes.
    # In mock/test mode the gateway never returns a real UTR, so we treat any signature
    # as authoritative there to keep dev flow smooth.
    if not has_real_utr and not creds["is_mock"]:
        utr = ""  # explicit: no UTR on file yet
    auto_approve = bool(settings.get("auto_approve_on_payment", True)) and cross_check_ok and (creds["is_mock"] or has_real_utr)

    txn_id = str(uuid.uuid4())
    user_set: Dict[str, Any] = {
        "registration_paid": True,
        "payment_method": "razorpay" + ("_mock" if creds["is_mock"] else ""),
        "razorpay_payment_id": payload.razorpay_payment_id,
        "razorpay_order_id": payload.razorpay_order_id,
        "razorpay_utr": utr,
        "paid_at": now_utc().isoformat(),
    }
    if auto_approve:
        user_set.update({
            "approval_status": "approved",
            "approval_reviewed_at": now_utc().isoformat(),
            "approval_reviewed_by": "auto",
            "approval_reject_category": None,
            "approval_reject_reason": None,
        })

    # ATOMIC: only mark as paid if not already paid — prevents duplicates from concurrent calls.
    upd = await db.users.update_one(
        {"id": user["id"], "registration_paid": {"$ne": True}},
        {"$set": user_set},
    )
    if upd.modified_count == 0:
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    # Convert the pending "Razorpay order created" row into a single "paid" entry
    # instead of writing a second row — this fixes the duplicate-entry bug
    # ("order created" + "payment successful" both showing for one payment).
    pending_set = {
        "status": "paid",
        "description": (
            "Registration fee via Razorpay"
            + (f" · UTR {utr}" if utr else "")
            + (" (mock)" if creds["is_mock"] else "")
        ),
        "razorpay_payment_id": payload.razorpay_payment_id,
        "reference_number": utr,
        "paid_at": now_utc().isoformat(),
    }
    pending_res = await db.transactions.update_one(
        {
            "user_id": user["id"],
            "type": "registration_fee",
            "razorpay_order_id": payload.razorpay_order_id,
            "status": "created",
        },
        {"$set": pending_set},
    )
    if pending_res.modified_count > 0:
        # Reuse that row's id as the canonical txn_id so the response matches the DB.
        existing = await db.transactions.find_one(
            {"user_id": user["id"], "razorpay_order_id": payload.razorpay_order_id, "type": "registration_fee"},
            {"_id": 0, "id": 1},
        )
        if existing:
            txn_id = existing["id"]
    else:
        # No pre-existing pending row (e.g. direct verify without prior create-order, or it was already cleaned)
        try:
            await db.transactions.insert_one({
                "id": txn_id,
                "user_id": user["id"],
                "type": "registration_fee",
                "amount": fee,
                "status": "paid",
                "description": (
                    "Registration fee via Razorpay"
                    + (f" · UTR {utr}" if utr else "")
                    + (" (mock)" if creds["is_mock"] else "")
                ),
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "reference_number": utr,
                "created_at": now_utc().isoformat(),
            })
        except DuplicateKeyError:
            # Idempotent: a parallel call already wrote the txn. Treat as success.
            pass

    if auto_approve:
        # Trigger commission cascade + archive into approved_registrations
        fresh = await db.users.find_one({"id": user["id"]})
        if fresh:
            try:
                await _trigger_referral_commissions(fresh)
            except Exception as e:
                logger.warning(f"Auto-approval: commission trigger failed for {user['id']}: {e}")
            synthetic_admin = {"id": "system", "email": "system@auto-approval", "admin_role": "auto"}
            try:
                await _archive_approved_user(fresh, synthetic_admin)
            except Exception as e:
                logger.warning(f"Auto-approval: archive failed for {user['id']}: {e}")
            try:
                await _audit_log(
                    synthetic_admin, "user.auto_approve", "user", user["id"],
                    {"utr": utr, "rzp_status": rzp_status, "amount": fee},
                )
            except Exception:
                pass
        await _create_notification(
            user["id"], "approval", "Account approved automatically",
            (f"Welcome aboard! Your payment was verified" + (f" (UTR {utr})" if utr else "") +
             ". You're now approved and can start earning."),
        )
    else:
        pending_reason = (
            "We're awaiting bank-side UTR confirmation from Razorpay. The finance team will review and approve once the UTR is on file."
            if not has_real_utr and not creds["is_mock"]
            else "Your registration payment was successful. The finance team will review your profile shortly."
        )
        await _create_notification(
            user["id"], "welcome", "Payment received — awaiting approval",
            pending_reason,
        )

    return {
        "ok": True,
        "transaction_id": txn_id,
        "amount": fee,
        "approval_status": "approved" if auto_approve else "pending",
        "auto_approved": auto_approve,
        "utr": utr,
        "rzp_status": rzp_status,
        "is_mock": creds["is_mock"],
    }


@api_router.post("/payment/failure")
async def payment_failure(payload: PaymentFailureRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Record a failed payment attempt. After MAX_PAYMENT_ATTEMPTS, the user is
    auto-moved to `rejected_registrations` with category=payment_unsuccessful.
    Phase A note: archive to rejected_registrations happens in Phase B; for now
    we simply increment the counter and, on cap, mark approval_status='rejected'
    with category/reason so the UI can route to a polite rejection screen."""
    if user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    attempts = int(user.get("payment_attempts") or 0) + 1
    archived = False

    if attempts >= MAX_PAYMENT_ATTEMPTS:
        # Phase B: archive to rejected_registrations + delete user record.
        # Merge the increment into the doc so the snapshot reflects the final count.
        user["payment_attempts"] = attempts
        user["last_payment_failure_at"] = now_utc().isoformat()
        user["last_payment_failure_reason"] = (payload.reason or "Payment failed")[:500]
        reason_text = (
            f"Auto-rejected after {MAX_PAYMENT_ATTEMPTS} failed payment attempts. "
            f"Last reason: {payload.reason or 'unknown'}"
        )
        record = await _archive_and_delete_user(
            user, category="payment_unsuccessful", remarks=reason_text, rejected_by="system",
        )
        archived = True
        # Log a failed transaction for trail (amount=0 — must NOT count as revenue)
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "registration_fee",
            "amount": 0.0,
            "status": "failed",
            "description": f"Payment failed (attempt {attempts}/{MAX_PAYMENT_ATTEMPTS}) — archived",
            "razorpay_order_id": payload.razorpay_order_id,
            "created_at": now_utc().isoformat(),
        })
        return {
            "ok": True,
            "attempts_used": attempts,
            "attempts_remaining": 0,
            "archived": True,
            "category": "payment_unsuccessful",
            "archive_id": record["id"],
        }

    update_doc: Dict[str, Any] = {
        "payment_attempts": attempts,
        "last_payment_failure_at": now_utc().isoformat(),
        "last_payment_failure_reason": (payload.reason or "Payment failed")[:500],
    }
    await db.users.update_one({"id": user["id"]}, {"$set": update_doc})

    # Convert the existing pending `created` row for this order into a `failed`
    # row instead of inserting a new one. amount=0 so failed attempts never
    # pollute revenue/wallet aggregations. This eliminates the "5 phantom rows
    # for 1 payment" bug.
    failed_desc = f"Payment failed (attempt {attempts}/{MAX_PAYMENT_ATTEMPTS})" + (f" — {payload.reason}" if payload.reason else "")
    pending_q: Dict[str, Any] = {
        "user_id": user["id"], "type": "registration_fee", "status": "created",
    }
    if payload.razorpay_order_id:
        pending_q["razorpay_order_id"] = payload.razorpay_order_id
    upd_failed = await db.transactions.update_one(
        pending_q,
        {"$set": {
            "status": "failed",
            "amount": 0.0,  # zero — failed attempts must NOT count as revenue
            "description": failed_desc,
            "failed_at": now_utc().isoformat(),
        }},
    )
    if upd_failed.modified_count == 0:
        # No matching pending row — write a standalone zero-amount failure note.
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "registration_fee",
            "amount": 0.0,
            "status": "failed",
            "description": failed_desc,
            "razorpay_order_id": payload.razorpay_order_id,
            "created_at": now_utc().isoformat(),
        })

    return {
        "ok": True,
        "attempts_used": attempts,
        "attempts_remaining": max(0, MAX_PAYMENT_ATTEMPTS - attempts),
        "archived": archived,
        "category": None,
    }


# ------------------ User Endpoints ------------------
@api_router.get("/users/me/dashboard")
async def my_dashboard(user: Dict[str, Any] = Depends(get_current_user)):
    direct_count = user.get("direct_referrals_count", 0)
    # Compute team size (all descendants)
    team_size = await _count_team(user["id"])
    pending_withdrawals = await db.withdrawals.count_documents({"user_id": user["id"], "status": "pending"})
    unread_notifs = await db.notifications.count_documents({"user_id": user["id"], "read": False})
    settings = await get_settings()
    directs_required = settings["directs_required"]
    # Next payout progress
    needed = directs_required - (direct_count % directs_required)
    if direct_count > 0 and direct_count % directs_required == 0:
        needed = directs_required  # next cycle
    tier = get_tier(team_size)

    # Earnings per day (last 7 days) — for sparkline
    today = now_utc().date()
    earnings_per_day: List[float] = []
    day_labels: List[str] = []
    for i in range(6, -1, -1):
        d = (today - timedelta(days=i))
        d_iso = d.isoformat()
        agg = await db.transactions.aggregate([
            {"$match": {
                "user_id": user["id"],
                "type": {"$in": ["payout", "level_payout", "vendor_sale"]},
                "amount": {"$gt": 0},
                "created_at": {"$regex": f"^{d_iso}"},
            }},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        total = float(agg[0]["total"]) if agg else 0.0
        earnings_per_day.append(round(total, 2))
        day_labels.append(d.strftime("%a"))

    # Level breakdown (level 1..10) — sum of payouts for each level
    level_breakdown: Dict[str, float] = {}
    for lv in range(1, 11):
        agg = await db.transactions.aggregate([
            {"$match": {"user_id": user["id"], "type": "level_payout", "level": lv}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        level_breakdown[f"l{lv}"] = round(float(agg[0]["total"]), 2) if agg else 0.0

    return {
        "user": serialize_user(user),
        "wallet_balance": user.get("wallet_balance", 0),
        "total_earned": user.get("total_earned", 0),
        "direct_referrals": direct_count,
        "team_size": team_size,
        "payouts_received": user.get("payouts_received", 0),
        "next_payout_in": needed,
        "directs_required": directs_required,
        "registration_paid": user.get("registration_paid", False),
        "pending_withdrawals": pending_withdrawals,
        "referral_code": user.get("referral_code"),
        "unread_notifications": unread_notifs,
        "tier": tier,
        "level_payouts": {f"l{i}": settings.get(f"payout_l{i}", 0) or 0 for i in range(1, 11)},
        "earnings_per_day": earnings_per_day,
        "day_labels": day_labels,
        "level_breakdown": level_breakdown,
    }


async def _count_team(user_id: str) -> int:
    """Count all descendants recursively."""
    count = 0
    queue = [user_id]
    while queue:
        current = queue.pop(0)
        children = await db.users.find({"sponsor_id": current}, {"id": 1, "_id": 0}).to_list(1000)
        count += len(children)
        queue.extend([c["id"] for c in children])
    return count


@api_router.get("/users/me/network")
async def my_network(user: Dict[str, Any] = Depends(get_current_user), depth: int = 3):
    """Return nested referral tree up to `depth` levels."""
    async def build_tree(uid: str, level: int) -> List[Dict[str, Any]]:
        if level >= depth:
            return []
        children = await db.users.find({"sponsor_id": uid}, {"_id": 0, "password_hash": 0}).to_list(1000)
        result = []
        for c in children:
            result.append({
                "id": c["id"],
                "name": c["name"],
                "email": c["email"],
                "referral_code": c["referral_code"],
                "registration_paid": c.get("registration_paid", False),
                "direct_referrals_count": c.get("direct_referrals_count", 0),
                "created_at": c.get("created_at"),
                "children": await build_tree(c["id"], level + 1),
            })
        return result

    tree = await build_tree(user["id"], 0)
    return {"root": serialize_user(user), "children": tree}


@api_router.post("/users/me/bank")
async def update_bank(payload: BankUpdate, user: Dict[str, Any] = Depends(get_current_user)):
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return fresh


# ------------------ Withdrawals ------------------
# 5 withdrawal requests per hour per user — generous for legitimate users
# but tight enough to deter wallet-drain abuse scripts.
@api_router.post("/withdrawals")
@_rl.limit("5/hour")
async def request_withdrawal(request: Request, payload: WithdrawalRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Complete registration payment first")
    if user.get("approval_status", "approved") != "approved":
        raise HTTPException(status_code=403, detail="Account is awaiting admin approval. Withdrawals are disabled until approved.")
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=403, detail="Wallet is frozen. Contact support.")
    if user.get("wallet_balance", 0) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    if not (user.get("upi_id") or user.get("bank_account")):
        raise HTTPException(status_code=400, detail="Add UPI or bank details first")

    wid = str(uuid.uuid4())
    doc = {
        "id": wid,
        "user_id": user["id"],
        "user_name": user["name"],
        "user_email": user["email"],
        "amount": payload.amount,
        "status": "pending",
        "upi_id": user.get("upi_id"),
        "bank_account": user.get("bank_account"),
        "ifsc": user.get("ifsc"),
        "account_holder": user.get("account_holder"),
        "created_at": now_utc().isoformat(),
        "processed_at": None,
    }
    await db.withdrawals.insert_one(doc)
    # Lock the requested amount from wallet
    await db.users.update_one({"id": user["id"]}, {"$inc": {"wallet_balance": -payload.amount}})
    await _create_notification(user["id"], "withdrawal", "Withdrawal requested", f"₹{int(payload.amount)} withdrawal is pending admin approval.")
    doc.pop("_id", None)
    return doc


@api_router.get("/withdrawals/me")
async def my_withdrawals(user: Dict[str, Any] = Depends(get_current_user)):
    items = await db.withdrawals.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items


@api_router.get("/transactions/me")
async def my_transactions(
    user: Dict[str, Any] = Depends(get_current_user),
    include_pending: bool = False,
):
    """User wallet history. By default we hide pre-payment / failed registration
    rows (status in {created, failed}) so the wallet view shows only money that
    actually moved. Pass ?include_pending=true to see all rows for debugging."""
    q: Dict[str, Any] = {"user_id": user["id"]}
    if not include_pending:
        q["status"] = {"$nin": ["created", "failed"]}
    items = await db.transactions.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items


def _auto_remarks_for(tx: Dict[str, Any]) -> str:
    """Generate a human-readable summary line for any transaction. Used in
    the transaction-detail modal so users always see context even if the
    description is terse."""
    t = (tx.get("type") or "").lower()
    amt = tx.get("amount") or 0
    sign = "+" if (amt or 0) >= 0 else "-"
    abs_amt = abs(float(amt or 0))
    src = tx.get("source_user_name") or ""
    ref = tx.get("reference_number") or ""
    lvl = tx.get("level")
    pretty = {
        "registration_fee": f"Registration fee paid · ₹{int(abs_amt)}",
        "referral_payout": f"Level {lvl} referral payout from {src or 'a downline member'} · {sign}₹{int(abs_amt)}",
        "service_booking": f"Service booking · {sign}₹{int(abs_amt)}{(' · ref ' + ref) if ref else ''}",
        "service_earning": f"Service earning · {sign}₹{int(abs_amt)}",
        "service_commission": f"Service platform fee from {src or 'customer'} · {sign}₹{int(abs_amt)}",
        "shop_commission": f"Shop margin from order {tx.get('order_id', '')[:8]} · {sign}₹{int(abs_amt)}",
        "vendor_sale": f"Vendor share · {sign}₹{int(abs_amt)}",
        "order": f"Shop order placed · {sign}₹{int(abs_amt)}",
        "admin_credit": tx.get("remarks") or f"Credit ₹{int(abs_amt)} from admin",
        "admin_debit": tx.get("remarks") or f"Debit ₹{int(abs_amt)} by admin",
        "system_deposit": f"System wallet top-up · UTR {ref or 'n/a'} · {sign}₹{int(abs_amt)}",
        "withdrawal": f"Withdrawal · {sign}₹{int(abs_amt)}{(' · UTR ' + ref) if ref else ''}",
    }
    return pretty.get(t, tx.get("description") or f"{t.replace('_', ' ').title()} · {sign}₹{int(abs_amt)}")


@api_router.get("/transactions/{txn_id}")
async def transaction_detail(txn_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Return a single transaction with enriched counter-party info + auto-remarks.
    Visible to: the owning user, super_admin, and finance roles."""
    tx = await db.transactions.find_one({"id": txn_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    is_owner = tx.get("user_id") == user["id"]
    is_admin_view = user.get("role") == "admin" and user.get("admin_role") in ("super_admin", "finance", "manager", "support")
    if not is_owner and not is_admin_view:
        raise HTTPException(status_code=403, detail="Not allowed")

    # Owner basics
    owner = await db.users.find_one({"id": tx.get("user_id")}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})

    # Counter-party inference
    counter: Optional[Dict[str, Any]] = None
    counter_role = ""
    if tx.get("from_admin_id"):
        c = await db.users.find_one({"id": tx["from_admin_id"]}, {"_id": 0, "id": 1, "name": 1, "email": 1, "admin_role": 1})
        if c:
            counter = c
            counter_role = "admin"
    elif tx.get("booking_id"):
        booking = await db.service_bookings.find_one({"id": tx["booking_id"]}, {"_id": 0})
        if booking:
            other_id = booking["provider_id"] if tx.get("user_id") == booking.get("customer_id") else booking.get("customer_id")
            other_role = "provider" if tx.get("user_id") == booking.get("customer_id") else "customer"
            c = await db.users.find_one({"id": other_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
            if c:
                counter = c
                counter_role = other_role
    elif tx.get("order_id"):
        order = await db.orders.find_one({"id": tx["order_id"]}, {"_id": 0})
        if order and order.get("user_id") != tx.get("user_id"):
            c = await db.users.find_one({"id": order.get("user_id")}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
            if c:
                counter = c
                counter_role = "buyer"

    return {
        "transaction": tx,
        "owner": owner,
        "counter_party": counter,
        "counter_role": counter_role,
        "auto_remarks": _auto_remarks_for(tx),
        "utr": tx.get("reference_number"),
        "invoice_number": _invoice_number_for(tx),
        "invoiceable": _is_invoiceable(tx),
    }


# ------------------ GST Invoices ------------------
async def _resolve_invoice_data(txn_id: str, user: Dict[str, Any]):
    """Shared helper: fetch txn + permission check + resolve owner/counter/branding."""
    tx = await db.transactions.find_one({"id": txn_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    is_owner = tx.get("user_id") == user["id"]
    is_admin_view = user.get("role") == "admin" and user.get("admin_role") in ("super_admin", "finance")
    if not is_owner and not is_admin_view:
        raise HTTPException(status_code=403, detail="Not allowed")
    if not _is_invoiceable(tx):
        raise HTTPException(status_code=400, detail="No invoice available for this transaction type")
    owner = await db.users.find_one(
        {"id": tx.get("user_id")},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1},
    )
    # Counter-party (mirrors the logic in transaction_detail)
    counter: Optional[Dict[str, Any]] = None
    if tx.get("from_admin_id"):
        counter = await db.users.find_one({"id": tx["from_admin_id"]}, {"_id": 0, "id": 1, "name": 1, "email": 1})
    elif tx.get("booking_id"):
        booking = await db.service_bookings.find_one({"id": tx["booking_id"]}, {"_id": 0})
        if booking:
            other_id = booking["provider_id"] if tx.get("user_id") == booking.get("customer_id") else booking.get("customer_id")
            counter = await db.users.find_one({"id": other_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})
    elif tx.get("order_id"):
        order = await db.orders.find_one({"id": tx["order_id"]}, {"_id": 0})
        if order and order.get("user_id") != tx.get("user_id"):
            counter = await db.users.find_one({"id": order.get("user_id")}, {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1})

    # Branding
    branding_doc = await db.settings.find_one({"id": "branding"}, {"_id": 0}) or {}
    return tx, owner, counter, branding_doc


@api_router.get("/transactions/{txn_id}/invoice", response_class=HTMLResponse)
async def transaction_invoice_html(txn_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Render an HTML GST invoice for the given transaction. Visible to: owner,
    super_admin, finance roles. Auto-applies 18% GST per Indian GST law."""
    tx, owner, counter, branding = await _resolve_invoice_data(txn_id, user)
    html = _build_invoice_html(tx, owner, branding, counter)
    return HTMLResponse(content=html, status_code=200)


@api_router.get("/transactions/{txn_id}/invoice.pdf")
async def transaction_invoice_pdf(txn_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Render a PDF GST invoice for the given transaction. Same access as HTML version."""
    tx, owner, counter, branding = await _resolve_invoice_data(txn_id, user)
    pdf_bytes = _build_invoice_pdf(tx, owner, branding, counter)
    inv_no = _invoice_number_for(tx).replace("/", "-")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{inv_no}.pdf"',
            "Cache-Control": "no-store",
        },
    )


# ------------------ Wallet-to-wallet transfer ------------------


@api_router.post("/wallet/transfer")
async def wallet_transfer(payload: WalletTransfer, user: Dict[str, Any] = Depends(get_current_user)):
    """Transfer funds from this user's wallet to another user's wallet."""
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=403, detail="Your wallet is frozen. Contact support.")
    if user.get("approval_status", "approved") != "approved":
        raise HTTPException(status_code=403, detail="Account is awaiting admin approval.")
    if (user.get("wallet_balance") or 0) < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    rec_query = payload.recipient.strip()
    if "@" in rec_query:
        recipient = await db.users.find_one({"email": rec_query.lower()})
    else:
        recipient = await db.users.find_one({"referral_code": rec_query.upper()})
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    if recipient["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot transfer to yourself")
    if recipient.get("is_blocked"):
        raise HTTPException(status_code=400, detail="Recipient account is blocked")
    if recipient.get("approval_status", "approved") != "approved":
        raise HTTPException(status_code=400, detail="Recipient is not approved yet")

    # Atomic-ish transfer (Mongo without transactions on standalone — best effort).
    # Atomic balance check on debit; only proceed if the user has sufficient funds at this exact moment.
    debit_res = await db.users.update_one(
        {"id": user["id"], "wallet_balance": {"$gte": payload.amount}},
        {"$inc": {"wallet_balance": -payload.amount}},
    )
    if debit_res.modified_count == 0:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    await db.users.update_one({"id": recipient["id"]}, {"$inc": {"wallet_balance": payload.amount}})

    ts = now_utc().isoformat()
    transfer_id = str(uuid.uuid4())
    try:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "transfer_out",
            "amount": -payload.amount,
            "status": "success",
            "description": f"Transferred ₹{int(payload.amount)} to {recipient.get('name')} ({recipient.get('email')})" + (f" — {payload.note}" if payload.note else ""),
            "transfer_id": transfer_id,
            "counterparty_id": recipient["id"],
            "created_at": ts,
        })
    except DuplicateKeyError:
        pass
    try:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": recipient["id"],
            "type": "transfer_in",
            "amount": payload.amount,
            "status": "success",
            "description": f"Received ₹{int(payload.amount)} from {user.get('name')} ({user.get('email')})" + (f" — {payload.note}" if payload.note else ""),
            "transfer_id": transfer_id,
            "counterparty_id": user["id"],
            "created_at": ts,
        })
    except DuplicateKeyError:
        pass
    await _create_notification(
        recipient["id"], "transfer",
        f"₹{int(payload.amount)} received",
        f"{user.get('name')} sent you ₹{int(payload.amount)}" + (f" — {payload.note}" if payload.note else ""),
    )
    return {"ok": True, "transfer_id": transfer_id, "amount": payload.amount}


# ------------------ Products (E-commerce placeholder) ------------------
# Public list endpoint (GET /products) extracted to
# /app/backend/routes/products_public.py during Phase 2B refactor.


# ------------------ Branding (public read, super_admin write) ------------------
# Helpers (_get_branding_doc / _merge_branding) and the three routes
# (GET /branding, PUT/POST /admin/branding, /admin/branding/reset) have been
# extracted to /app/backend/core/branding.py and /app/backend/routes/branding.py
# during the Phase 2B refactor. server.py imports the helpers as aliases at the
# top of the file so the rest of this module's code keeps working unchanged.


# ------------------ Admin Endpoints ------------------
@api_router.get("/admin/users")
async def admin_list_users(_: Dict[str, Any] = Depends(require_admin)):
    items = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(5000)
    return items


# ------------------ Admin: referral tree views ------------------

def _slim_user_node(u: Dict[str, Any]) -> Dict[str, Any]:
    """Compact representation of a user for tree views."""
    return {
        "id": u.get("id"),
        "name": u.get("name") or "—",
        "email": u.get("email"),
        "phone": u.get("phone"),
        "role": u.get("role", "user"),
        "admin_role": u.get("admin_role"),
        "referral_code": u.get("referral_code"),
        "referred_by": u.get("referred_by"),
        "registration_paid": bool(u.get("registration_paid", False)),
        "approval_status": u.get("approval_status", "pending"),
        "is_blocked": bool(u.get("is_blocked", False)),
        "direct_referrals_count": int(u.get("direct_referrals_count", 0)),
        "wallet_balance": float(u.get("wallet_balance", 0) or 0),
        "total_earned": float(u.get("total_earned", 0) or 0),
        "created_at": u.get("created_at"),
    }


@api_router.get("/admin/users/tree")
async def admin_users_tree(
    _: Dict[str, Any] = Depends(require_admin),
    depth: int = 10,
    root_user_id: Optional[str] = None,
):
    """Return a nested referral tree.

    Parameters
    ----------
    depth : int (default 10) — max levels to descend (cap 10)
    root_user_id : str — start at this user (admin-scoped). If omitted, the
                   tree is rooted at the seed admin (the matrix root). If no
                   admin exists, returns all top-level users (no sponsor).
    """
    depth = max(1, min(int(depth or 10), 10))

    if root_user_id:
        root = await db.users.find_one({"id": root_user_id}, {"_id": 0, "password_hash": 0})
        if not root:
            raise HTTPException(status_code=404, detail="Root user not found")
        roots = [root]
    else:
        # Admin is the matrix root.
        admin = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "password_hash": 0})
        roots: List[Dict[str, Any]] = []
        if admin:
            roots.append(admin)
        # ALSO surface orphaned users — those with no sponsor OR a sponsor_id
        # that no longer points to a real user. Without this, any user not
        # linked to admin's subtree would be invisible (which is the bug
        # admin reported: "View Network Tree doesn't show all users").
        admin_id = admin["id"] if admin else None
        all_user_ids = {u["id"] async for u in db.users.find({}, {"id": 1, "_id": 0})}
        orphans_q = {
            "$or": [
                {"sponsor_id": None},
                {"sponsor_id": {"$exists": False}},
                {"sponsor_id": ""},
            ],
        }
        if admin_id:
            # exclude admin itself, already a root
            orphans_q = {"$and": [orphans_q, {"id": {"$ne": admin_id}}]}
        orphans_no_sp = await db.users.find(orphans_q, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(2000)
        # Users with stale sponsor_id (pointing to a deleted parent)
        stale_q: Dict[str, Any] = {"sponsor_id": {"$nin": list(all_user_ids) + [None, ""]}}
        if admin_id:
            stale_q = {"$and": [stale_q, {"id": {"$ne": admin_id}}]}
        orphans_stale = await db.users.find(stale_q, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(2000)
        # De-dupe across both queries
        seen_root_ids = {r["id"] for r in roots}
        for o in (orphans_no_sp + orphans_stale):
            if o["id"] not in seen_root_ids:
                seen_root_ids.add(o["id"])
                roots.append(o)

    # BFS with depth limit, batching DB calls per level for efficiency.
    async def build(uid: str, level: int) -> List[Dict[str, Any]]:
        if level >= depth:
            return []
        children = await db.users.find(
            {"sponsor_id": uid},
            {"_id": 0, "password_hash": 0},
        ).sort("created_at", 1).to_list(2000)
        out: List[Dict[str, Any]] = []
        for c in children:
            node = _slim_user_node(c)
            node["level"] = level + 1
            node["children"] = await build(c["id"], level + 1)
            out.append(node)
        return out

    result = []
    for r in roots:
        node = _slim_user_node(r)
        node["level"] = 0
        node["children"] = await build(r["id"], 0)
        result.append(node)
    return {"depth": depth, "roots": result}


@api_router.get("/admin/users/{user_id}/lineage")
async def admin_user_lineage(user_id: str, _: Dict[str, Any] = Depends(require_admin)):
    """Return the upline chain (sponsor → sponsor's sponsor → … → root) for a user,
    plus their direct downlines (1 level). Useful for a 'Who's above and below'
    quick view on any single user."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    # Walk upline by sponsor_id (more reliable than referral_code, also handles
    # spillover-aware admin sponsors).
    chain: List[Dict[str, Any]] = []
    cur = u
    seen = {u["id"]}
    while cur.get("sponsor_id"):
        parent = await db.users.find_one(
            {"id": cur["sponsor_id"]}, {"_id": 0, "password_hash": 0},
        )
        if not parent or parent["id"] in seen:
            break
        seen.add(parent["id"])
        chain.append(_slim_user_node(parent))
        cur = parent
    chain.reverse()  # root → … → immediate sponsor (top to bottom)

    # Direct downlines (1st level only)
    directs = await db.users.find(
        {"sponsor_id": user_id}, {"_id": 0, "password_hash": 0},
    ).sort("created_at", 1).to_list(2000)
    downline = [_slim_user_node(d) for d in directs]

    return {
        "user": _slim_user_node(u),
        "upline": chain,
        "downline": downline,
        "downline_count": len(downline),
    }


@api_router.get("/admin/withdrawals")
async def admin_list_withdrawals(_: Dict[str, Any] = Depends(require_admin), status: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    items = await db.withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return items


@api_router.post("/admin/withdrawals/{wid}/approve")
async def admin_approve_withdrawal(wid: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance"))):
    """Finance/admin approves a withdrawal. Moves status pending → processing with an ETA.
    The actual money-out is marked via /complete once paid."""
    w = await db.withdrawals.find_one({"id": wid})
    if not w:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    eta = (now_utc() + timedelta(hours=48)).isoformat()
    await db.withdrawals.update_one(
        {"id": wid},
        {"$set": {
            "status": "processing",
            "processed_at": now_utc().isoformat(),
            "approved_by": admin["id"],
            "approved_by_email": admin.get("email"),
            "estimated_completion_at": eta,
        }},
    )
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": w["user_id"],
        "type": "withdrawal",
        "amount": -w["amount"],
        "status": "processing",
        "description": f"Withdrawal in process (₹{int(w['amount'])}) — ETA 48h",
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(
        w["user_id"], "withdrawal", "Withdrawal in process",
        f"₹{int(w['amount'])} approved. Funds will reach your bank within 48 hours.",
    )
    await _audit_log(admin, "withdrawal.approve", "withdrawal", wid, {"amount": w["amount"]})
    return {"ok": True, "estimated_completion_at": eta}


@api_router.post("/admin/withdrawals/batch/complete")
async def admin_batch_complete_withdrawals(
    payload: WithdrawalBatchRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    """Batch settle many withdrawals at once.
    For each withdrawal:
      • If status==pending → flip directly to success (instant)
      • If status==processing → flip to success
      • Else → skip with reason
    Each gets a unique reference_number = `<prefix>-<id8>` (or just <id8> if no prefix).
    Returns a summary { settled, skipped, failures }.
    """
    ids = list({i for i in (payload.ids or []) if i})
    if not ids:
        raise HTTPException(status_code=400, detail="No withdrawal ids provided")
    prefix = (payload.reference_prefix or "").strip()
    settled: List[str] = []
    skipped: List[Dict[str, Any]] = []
    ts = now_utc().isoformat()

    for wid in ids:
        w = await db.withdrawals.find_one({"id": wid})
        if not w:
            skipped.append({"id": wid, "reason": "not_found"}); continue
        if w["status"] not in ("pending", "processing"):
            skipped.append({"id": wid, "reason": f"status_{w['status']}"}); continue

        ref = (f"{prefix}-{wid[:8]}" if prefix else wid[:8])
        was_pending = w["status"] == "pending"

        await db.withdrawals.update_one(
            {"id": wid},
            {"$set": {
                "status": "success",
                "processed_at": w.get("processed_at") or ts,
                "completed_at": ts,
                "completed_by": admin["id"],
                "completed_by_email": admin.get("email"),
                "approved_by": w.get("approved_by") or admin["id"],
                "approved_by_email": w.get("approved_by_email") or admin.get("email"),
                "reference_number": ref,
                "instant_settle": was_pending,
                "batch_settled": True,
            }},
        )

        desc = f"Withdrawal paid (₹{int(w['amount'])}) · ref {ref}"
        if was_pending:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": w["user_id"],
                "type": "withdrawal",
                "amount": -w["amount"],
                "status": "success",
                "description": desc,
                "reference_number": ref,
                "created_at": ts,
            })
        else:
            await db.transactions.update_many(
                {"user_id": w["user_id"], "type": "withdrawal", "status": "processing", "amount": -w["amount"]},
                {"$set": {"status": "success", "description": desc, "reference_number": ref}},
            )

        try:
            await _create_notification(
                w["user_id"], "withdrawal", "Withdrawal successful",
                f"₹{int(w['amount'])} paid · UTR {ref}",
            )
        except Exception:
            pass

        settled.append(wid)
        await _audit_log(admin, "withdrawal.batch_settle", "withdrawal", wid, {"amount": w["amount"], "reference": ref})

    return {"ok": True, "settled_count": len(settled), "skipped_count": len(skipped), "settled": settled, "skipped": skipped}


@api_router.post("/admin/withdrawals/{wid}/complete")
async def admin_complete_withdrawal(
    wid: str,
    payload: Optional[WithdrawalCompleteRequest] = None,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    """Mark a processing withdrawal as successfully paid out. Captures optional UTR / reference."""
    ref = (payload.reference_number if payload else "") or ""
    ref = ref.strip()
    w = await db.withdrawals.find_one({"id": wid})
    if not w:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if w["status"] != "processing":
        raise HTTPException(status_code=400, detail="Withdrawal is not in processing state")
    await db.withdrawals.update_one(
        {"id": wid},
        {"$set": {
            "status": "success",
            "completed_at": now_utc().isoformat(),
            "completed_by": admin["id"],
            "completed_by_email": admin.get("email"),
            "reference_number": ref,
        }},
    )
    desc = f"Withdrawal paid (₹{int(w['amount'])})" + (f" · ref {ref}" if ref else "")
    await db.transactions.update_many(
        {"user_id": w["user_id"], "type": "withdrawal", "status": "processing", "amount": -w["amount"]},
        {"$set": {"status": "success", "description": desc, "reference_number": ref}},
    )
    await _create_notification(
        w["user_id"], "withdrawal", "Withdrawal successful",
        f"₹{int(w['amount'])} has been paid" + (f" · UTR {ref}" if ref else "."),
    )
    await _audit_log(admin, "withdrawal.complete", "withdrawal", wid, {"amount": w["amount"], "reference": ref})
    return {"ok": True, "reference_number": ref}


@api_router.post("/admin/withdrawals/{wid}/approve-and-complete")
async def admin_approve_and_complete_withdrawal(
    wid: str,
    payload: Optional[WithdrawalCompleteRequest] = None,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    """One-step: pending → success directly. Useful for instant payouts (e.g., admin already paid via UPI)."""
    ref = (payload.reference_number if payload else "") or ""
    ref = ref.strip()
    w = await db.withdrawals.find_one({"id": wid})
    if not w:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    ts = now_utc().isoformat()
    await db.withdrawals.update_one(
        {"id": wid},
        {"$set": {
            "status": "success",
            "processed_at": ts,
            "approved_by": admin["id"],
            "approved_by_email": admin.get("email"),
            "completed_at": ts,
            "completed_by": admin["id"],
            "completed_by_email": admin.get("email"),
            "reference_number": ref,
            "instant_settle": True,
        }},
    )
    desc = f"Withdrawal paid (₹{int(w['amount'])})" + (f" · ref {ref}" if ref else "")
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": w["user_id"],
        "type": "withdrawal",
        "amount": -w["amount"],
        "status": "success",
        "description": desc,
        "reference_number": ref,
        "created_at": ts,
    })
    await _create_notification(
        w["user_id"], "withdrawal", "Withdrawal successful",
        f"₹{int(w['amount'])} has been paid" + (f" · UTR {ref}" if ref else "."),
    )
    await _audit_log(admin, "withdrawal.instant_settle", "withdrawal", wid, {"amount": w["amount"], "reference": ref})
    return {"ok": True, "reference_number": ref}


@api_router.post("/admin/withdrawals/{wid}/reject")
async def admin_reject_withdrawal(
    wid: str,
    payload: Optional[WithdrawalRejectRequest] = None,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    reason = (payload.reason if payload else "") or ""
    reason = reason.strip()
    w = await db.withdrawals.find_one({"id": wid})
    if not w:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    # Refund the locked amount
    await db.users.update_one({"id": w["user_id"]}, {"$inc": {"wallet_balance": w["amount"]}})
    await db.withdrawals.update_one(
        {"id": wid},
        {"$set": {
            "status": "rejected",
            "processed_at": now_utc().isoformat(),
            "rejected_by": admin["id"],
            "rejected_by_email": admin.get("email"),
            "rejection_reason": reason,
        }},
    )
    body = f"₹{int(w['amount'])} has been refunded to your wallet." + (f" Reason: {reason}" if reason else "")
    await _create_notification(w["user_id"], "withdrawal", "Withdrawal rejected", body)
    await _audit_log(admin, "withdrawal.reject", "withdrawal", wid, {"amount": w["amount"], "reason": reason})
    return {"ok": True, "rejection_reason": reason}


@api_router.get("/admin/withdrawals/digest")
async def admin_withdrawals_digest(_: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance"))):
    """Admin home banner — counts of pending / processing withdrawals + totals."""
    pending = await db.withdrawals.count_documents({"status": "pending"})
    processing = await db.withdrawals.count_documents({"status": "processing"})
    pending_total_agg = await db.withdrawals.aggregate([
        {"$match": {"status": "pending"}},
        {"$group": {"_id": None, "amt": {"$sum": "$amount"}}},
    ]).to_list(1)
    processing_total_agg = await db.withdrawals.aggregate([
        {"$match": {"status": "processing"}},
        {"$group": {"_id": None, "amt": {"$sum": "$amount"}}},
    ]).to_list(1)
    pending_amount = float(pending_total_agg[0]["amt"]) if pending_total_agg else 0.0
    processing_amount = float(processing_total_agg[0]["amt"]) if processing_total_agg else 0.0

    today = now_utc().date().isoformat()
    settled_today = await db.withdrawals.count_documents({
        "status": "success",
        "completed_at": {"$regex": f"^{today}"},
    })
    settled_today_amt_agg = await db.withdrawals.aggregate([
        {"$match": {"status": "success", "completed_at": {"$regex": f"^{today}"}}},
        {"$group": {"_id": None, "amt": {"$sum": "$amount"}}},
    ]).to_list(1)
    settled_today_amount = float(settled_today_amt_agg[0]["amt"]) if settled_today_amt_agg else 0.0

    # Oldest pending (alert flag if older than 24h)
    oldest = await db.withdrawals.find({"status": "pending"}, {"_id": 0, "created_at": 1}).sort("created_at", 1).limit(1).to_list(1)
    oldest_age_hours: Optional[float] = None
    if oldest:
        try:
            o = datetime.fromisoformat(oldest[0]["created_at"].replace("Z", "+00:00"))
            oldest_age_hours = round((now_utc() - o).total_seconds() / 3600, 1)
        except Exception:
            pass

    return {
        "pending": pending,
        "processing": processing,
        "pending_amount": round(pending_amount, 2),
        "processing_amount": round(processing_amount, 2),
        "settled_today": settled_today,
        "settled_today_amount": round(settled_today_amount, 2),
        "oldest_pending_age_hours": oldest_age_hours,
    }


@api_router.get("/admin/transactions")
async def admin_transactions(_: Dict[str, Any] = Depends(require_admin), include_pending: bool = False):
    """Admin transaction feed. By default hides pre-payment / failed registration
    rows so the wallet & revenue figures match. Pass ?include_pending=true to
    surface them for support / debugging.

    Each row is enriched with `user_name` (from users collection) and `reference_number`
    auto-derived if missing — UTR for bank transactions, TXN-{shortid} for in-app moves.
    """
    q: Dict[str, Any] = {}
    if not include_pending:
        q["status"] = {"$nin": ["created", "failed"]}
    items = await db.transactions.find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)

    # Build a one-shot user_id → name map to avoid N+1 lookups
    user_ids = {t.get("user_id") for t in items if t.get("user_id")}
    users_map: Dict[str, str] = {}
    if user_ids:
        async for u in db.users.find({"id": {"$in": list(user_ids)}}, {"_id": 0, "id": 1, "name": 1, "email": 1, "referral_code": 1}):
            users_map[u["id"]] = u

    enriched = []
    for t in items:
        u = users_map.get(t.get("user_id") or "", {})
        ref = (
            t.get("reference_number")
            or t.get("razorpay_payment_id")
            or (f"TXN-{t['id'][:8].upper()}" if t.get("id") else None)
        )
        enriched.append({
            **t,
            "user_name": u.get("name"),
            "user_email": u.get("email"),
            "user_referral_code": u.get("referral_code"),
            "reference_number": ref,
        })
    return enriched


@api_router.get("/admin/stats")
async def admin_stats(_: Dict[str, Any] = Depends(require_admin)):
    settings = await get_settings()
    total_users = await db.users.count_documents({"role": "user"})
    paid_users = await db.users.count_documents({"role": "user", "registration_paid": True})
    pending_payouts = await db.withdrawals.count_documents({"status": "pending"})
    # Revenue = sum of registration_fee transactions only.
    # Per user request: "Revenue → show only registration transactions, don't
    # include referral payouts, shop orders or service bookings".
    # NOTE: registration_fee txns use status="paid" (not "success") in the
    # legacy mock flow — we accept either marker since both mean "money
    # actually arrived".
    rev_agg = await db.transactions.aggregate([
        {"$match": {
            "type": "registration_fee",
            "status": {"$in": ["success", "paid"]},
        }},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_revenue = float(rev_agg[0]["total"] if rev_agg else 0)
    # Fallback for fresh installs / clean DB: assume legacy reg-fee × paid_users
    if total_revenue == 0:
        total_revenue = paid_users * settings["registration_fee"]

    payout_agg = await db.transactions.aggregate([
        {"$match": {"type": "referral_payout"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_paid_out = payout_agg[0]["total"] if payout_agg else 0

    # NEW: aggregate withdrawal totals by status — drives the "Withdrawal
    # pending" and "Settled" tiles on Admin → Users. Withdrawal status
    # vocabulary used elsewhere in this codebase: "pending" | "processing"
    # | "success" | "rejected". "Settled" maps to status="success".
    pending_wd_agg = await db.withdrawals.aggregate([
        {"$match": {"status": "pending"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    settled_wd_agg = await db.withdrawals.aggregate([
        {"$match": {"status": "success"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_pending_withdrawals_amount = float(pending_wd_agg[0]["total"] if pending_wd_agg else 0)
    total_completed_withdrawals_amount = float(settled_wd_agg[0]["total"] if settled_wd_agg else 0)

    return {
        "total_users": total_users,
        "paid_users": paid_users,
        "pending_payouts": pending_payouts,
        "total_revenue": total_revenue,
        "total_referral_payouts": total_paid_out,
        "total_pending_withdrawals_amount": total_pending_withdrawals_amount,
        "total_completed_withdrawals_amount": total_completed_withdrawals_amount,
    }


@api_router.post("/admin/products")
async def admin_create_product(p: ProductCreate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    doc = {"id": str(uuid.uuid4()), **p.dict(), "created_at": now_utc().isoformat()}
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    await _audit_log(admin, "product.create", "product", doc["id"], {"name": p.name, "price": p.price})
    return doc


@api_router.get("/admin/products")
async def admin_list_products(_: Dict[str, Any] = Depends(require_admin)):
    items = await db.products.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return items


@api_router.patch("/admin/products/{product_id}")
async def admin_update_product(product_id: str, payload: ProductUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.products.find_one({"id": product_id})
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.products.update_one({"id": product_id}, {"$set": update})
    await _audit_log(admin, "product.update", "product", product_id, {"fields": list(update.keys())})
    fresh = await db.products.find_one({"id": product_id}, {"_id": 0})
    return fresh


@api_router.delete("/admin/products/{product_id}")
async def admin_delete_product(product_id: str, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.products.find_one({"id": product_id})
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.products.delete_one({"id": product_id})
    # Also remove from any open carts
    await db.cart_items.delete_many({"product_id": product_id})
    await _audit_log(admin, "product.delete", "product", product_id, {"name": target.get("name")})
    return {"ok": True}


# ------------------ Admin: User Management ------------------


@api_router.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: str, payload: AdminUserUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    # Only super_admin can change role / admin_role (admin promotion/demotion)
    sensitive_fields = {"role", "admin_role"}
    if sensitive_fields & set(update.keys()):
        if (admin.get("admin_role") or "super_admin") != "super_admin":
            raise HTTPException(status_code=403, detail="Only super_admin can modify role / admin_role")
    if "email" in update:
        update["email"] = update["email"].lower().strip()
        # Check uniqueness
        clash = await db.users.find_one({"email": update["email"], "id": {"$ne": user_id}})
        if clash:
            raise HTTPException(status_code=400, detail="Email already taken")
    if "role" in update and update["role"] not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    if "admin_role" in update and update["admin_role"] not in ("super_admin", "manager", "support", "finance", None):
        raise HTTPException(status_code=400, detail="Invalid admin_role")
    # Prevent demoting/changing the last super_admin
    if target.get("admin_role") == "super_admin":
        downgrading = (
            ("role" in update and update["role"] != "admin")
            or ("admin_role" in update and update["admin_role"] != "super_admin")
        )
        if downgrading:
            super_count = await db.users.count_documents({"role": "admin", "admin_role": "super_admin"})
            if super_count <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last super_admin")
    # Prevent demoting the last admin
    if "role" in update and update["role"] == "user" and target.get("role") == "admin":
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last admin")
    await db.users.update_one({"id": user_id}, {"$set": update})
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    await _create_notification(user_id, "account", "Account updated", "Your account details were updated by admin.")
    if sensitive_fields & set(update.keys()):
        await _audit_log(admin, "admin.role_change", "user", user_id, {k: update[k] for k in sensitive_fields & set(update.keys())})
    return fresh


@api_router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, payload: AdminPasswordReset, _: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": user_id}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    await _create_notification(user_id, "account", "Password reset", "Your password was reset by admin. Please log in again.")
    return {"ok": True}


# ───────────────────────────── PLACEMENT REALIGNMENT ─────────────────────────────
# Admin can manually move a user under a different upline (sponsor_id).
# This is a PURE LINEAGE MOVE — no commissions are recalculated, no money
# is moved. Useful when a user was placed badly by BFS spillover or when
# someone needs to be re-parented for organizational reasons.
# Every change appends a row to placement_history with reason + admin id.
# referral_owner_id (commission ownership) is NOT changed by this endpoint.
class RealignPayload(BaseModel):
    new_sponsor_id: Optional[str] = None
    new_sponsor_code: Optional[str] = None
    reason: str = Field(..., min_length=3, max_length=500)


@api_router.post("/admin/users/{user_id}/realign")
async def admin_realign_user(
    user_id: str,
    payload: RealignPayload,
    admin: Dict[str, Any] = Depends(require_admin_not_finance),
):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Resolve new sponsor — accept either id or referral_code.
    new_sponsor = None
    if payload.new_sponsor_id:
        new_sponsor = await db.users.find_one({"id": payload.new_sponsor_id})
    elif payload.new_sponsor_code:
        new_sponsor = await db.users.find_one({"referral_code": payload.new_sponsor_code.strip().upper()})
    if not new_sponsor:
        raise HTTPException(status_code=400, detail="New sponsor not found (provide new_sponsor_id or new_sponsor_code)")
    if new_sponsor["id"] == user_id:
        raise HTTPException(status_code=400, detail="A user cannot be placed under themselves")

    # Guard against creating a cycle: new_sponsor must NOT be a descendant of `target`.
    cursor_id = new_sponsor.get("sponsor_id")
    hops = 0
    while cursor_id and hops < 50:
        if cursor_id == user_id:
            raise HTTPException(status_code=400, detail="Cannot move user under their own descendant (would create a cycle)")
        parent = await db.users.find_one({"id": cursor_id}, {"sponsor_id": 1})
        cursor_id = (parent or {}).get("sponsor_id")
        hops += 1

    old_sponsor_id = target.get("sponsor_id")
    old_sponsor = await db.users.find_one({"id": old_sponsor_id}) if old_sponsor_id else None
    if old_sponsor_id == new_sponsor["id"]:
        raise HTTPException(status_code=400, detail="User is already placed under this sponsor")

    history_entry = {
        "type": "manual_admin",
        "old_sponsor_id":    old_sponsor_id,
        "old_sponsor_code":  (old_sponsor or {}).get("referral_code"),
        "old_sponsor_email": (old_sponsor or {}).get("email"),
        "new_sponsor_id":    new_sponsor["id"],
        "new_sponsor_code":  new_sponsor.get("referral_code"),
        "new_sponsor_email": new_sponsor.get("email"),
        "reason":            payload.reason.strip(),
        "changed_by_admin_id":    admin["id"],
        "changed_by_admin_email": admin.get("email"),
        "changed_at":        now_utc().isoformat(),
    }

    await db.users.update_one(
        {"id": user_id},
        {
            "$set": {
                "sponsor_id": new_sponsor["id"],
                "referred_by": new_sponsor.get("referral_code"),
                "placement_realigned_at":     history_entry["changed_at"],
                "placement_realigned_reason": payload.reason.strip(),
            },
            "$push": {"placement_history": history_entry},
        },
    )

    # Notify both old and new sponsors + the user themselves.
    try:
        await _create_notification(
            user_id, "account", "Placement updated",
            f"Admin moved your placement to {new_sponsor.get('name')} ({new_sponsor.get('referral_code')}). Reason: {payload.reason.strip()}",
        )
        if old_sponsor and old_sponsor.get("role") == "user":
            await _create_notification(
                old_sponsor["id"], "downline", "Downline moved",
                f"{target.get('name')} was realigned by admin to {new_sponsor.get('name')}.",
            )
        if new_sponsor.get("role") == "user":
            await _create_notification(
                new_sponsor["id"], "downline", "Downline added",
                f"{target.get('name')} was placed under you by admin.",
            )
    except Exception:
        pass

    await _audit_log(admin, "admin.realign_user", "user", user_id, history_entry)
    return {"ok": True, "history_entry": history_entry}


@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if target.get("role") == "admin":
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    # ---------- AUTO BACKUP before destructive action ----------
    snap_info = await _take_snapshot(
        kind="auto-pre-delete",
        note=f"Auto-backup before deleting user {target.get('email')} ({target.get('name')})",
        created_by=admin["id"],
    )

    cascade: Dict[str, int] = {}

    # 1. Hard cascade — collections that should be wiped along with the user
    hard_cascade_specs = [
        ("cart_items",            {"user_id": user_id}),
        ("notifications",         {"user_id": user_id}),
        ("withdrawals",           {"user_id": user_id}),
        ("vendor_applications",   {"user_id": user_id}),
        ("service_applications",  {"user_id": user_id}),
        ("approved_registrations",{"user_id": user_id}),
        ("rejected_registrations",{"user_id": user_id}),
        # Service bookings as customer OR provider
        ("service_bookings",      {"$or": [{"customer_id": user_id}, {"provider_id": user_id}]}),
        # Tickets they raised + replies on those tickets are in ticket_messages keyed by ticket_id;
        # we'll delete tickets first then sweep ticket_messages for orphans below.
        ("tickets",               {"user_id": user_id}),
    ]
    for coll, query in hard_cascade_specs:
        res = await db[coll].delete_many(query)
        cascade[coll] = res.deleted_count

    # 2. Sweep ticket_messages whose tickets were just deleted (no longer have a parent)
    remaining_ticket_ids = {t["id"] async for t in db.tickets.find({}, {"_id": 0, "id": 1})}
    if remaining_ticket_ids:
        orphan_msgs = await db.ticket_messages.delete_many({"ticket_id": {"$nin": list(remaining_ticket_ids)}})
    else:
        orphan_msgs = await db.ticket_messages.delete_many({})
    cascade["ticket_messages_orphans"] = orphan_msgs.deleted_count

    # 3. Soft cleanup — preserve transactions/orders for audit, but unlink author refs
    # so the audit trail still resolves. We mark the original user_id as a sentinel.
    await db.transactions.update_many(
        {"counterparty_id": user_id}, {"$set": {"counterparty_id": None}},
    )

    # 4. Reassign downline: move direct referrals to the deleting admin (super_admin or
    # the seed admin). Without this, downline users have a dangling sponsor_id and the
    # tree query breaks. We reassign by clearing sponsor_id to None — it surfaces them
    # as "orphaned" in the network view, which super_admin can re-link manually.
    downline_unset = await db.users.update_many(
        {"sponsor_id": user_id},
        {"$set": {"sponsor_id": None, "sponsor_referral_code": None}},
    )
    cascade["downline_orphaned"] = downline_unset.modified_count

    # 5. If they were a vendor, mark their products as unavailable rather than delete
    products_unlinked = await db.products.update_many(
        {"vendor_id": user_id},
        {"$set": {"vendor_id": None, "stock": 0, "is_active": False}},
    )
    cascade["products_unlinked"] = products_unlinked.modified_count

    # 6. Vendor sales ledger — keep for audit, just null the vendor_id link
    vs_nulled = await db.vendor_sales.update_many(
        {"vendor_id": user_id}, {"$set": {"vendor_id": None}},
    )
    cascade["vendor_sales_unlinked"] = vs_nulled.modified_count

    # 7. Finally, the user itself
    await db.users.delete_one({"id": user_id})
    cascade["user"] = 1

    await _audit_log(
        admin, "user.delete", "user", user_id,
        {
            "email": target.get("email"),
            "name": target.get("name"),
            "role": target.get("role"),
            "wallet_balance_at_delete": target.get("wallet_balance"),
            "cascade": cascade,
            "snapshot_id": snap_info["id"],
        },
    )

    return {"ok": True, "cascade": cascade, "snapshot_id": snap_info["id"], "snapshot_created_at": snap_info["created_at"]}


# ------------------ Admin: Admins management (super_admin only) ------------------
@api_router.get("/admin/admins")
async def admin_list_admins(_: Dict[str, Any] = Depends(require_admin)):
    """List all admin accounts. Visible to any admin (so they know who else has access)."""
    items = await db.users.find(
        {"role": "admin"},
        {"_id": 0, "password_hash": 0, "kyc_aadhaar_front": 0, "kyc_aadhaar_back": 0, "kyc_pan_image": 0, "kyc_selfie": 0},
    ).sort("created_at", 1).to_list(2000)
    return items


@api_router.post("/admin/admins")
async def admin_create_admin(payload: AdminCreate, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Create a new admin account directly (no public registration)."""
    if payload.admin_role not in ("super_admin", "manager", "support", "finance"):
        raise HTTPException(status_code=400, detail="Invalid admin_role")
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already in use")
    while True:
        code = gen_referral_code()
        if not await db.users.find_one({"referral_code": code}):
            break
    user_id = str(uuid.uuid4())
    new_admin = {
        "id": user_id,
        "name": payload.name.strip(),
        "email": email,
        "password_hash": hash_password(payload.password),
        "phone": payload.phone,
        "role": "admin",
        "admin_role": payload.admin_role,
        "auth_provider": "password",
        "referral_code": code,
        "referred_by": None,
        "sponsor_id": None,
        "wallet_balance": 0.0,
        "total_earned": 0.0,
        "registration_paid": True,  # admins skip the ₹100 mock
        "direct_referrals_count": 0,
        "payouts_received": 0,
        "upi_id": None,
        "bank_account": None,
        "ifsc": None,
        "account_holder": None,
        "is_blocked": False,
        "block_reason": None,
        "wallet_frozen": False,
        "kyc_status": "approved",
        "kyc_full_name": payload.name.strip(),
        "kyc_aadhaar": None,
        "kyc_pan": None,
        "kyc_submitted_at": None,
        "kyc_reviewed_at": None,
        "kyc_reject_reason": None,
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(new_admin)
    await _audit_log(admin, "admin.create", "user", user_id, {"email": email, "admin_role": payload.admin_role})
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return fresh


@api_router.post("/admin/users/{user_id}/promote")
async def admin_promote_user(user_id: str, payload: PromoteRequest, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Promote an existing user to admin with a sub-role."""
    if payload.admin_role not in ("super_admin", "manager", "support", "finance"):
        raise HTTPException(status_code=400, detail="Invalid admin_role")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") == "admin":
        raise HTTPException(status_code=400, detail="User is already an admin")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"role": "admin", "admin_role": payload.admin_role, "registration_paid": True}},
    )
    await _audit_log(admin, "admin.promote", "user", user_id, {"admin_role": payload.admin_role})
    await _create_notification(user_id, "account", "Promoted to admin", f"You have been granted {payload.admin_role} access.")
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return fresh


@api_router.post("/admin/users/{user_id}/demote")
async def admin_demote_user(user_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Demote an admin back to a regular user."""
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") != "admin":
        raise HTTPException(status_code=400, detail="User is not an admin")
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    if target.get("admin_role") == "super_admin":
        super_count = await db.users.count_documents({"role": "admin", "admin_role": "super_admin"})
        if super_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last super_admin")
    admin_count = await db.users.count_documents({"role": "admin"})
    if admin_count <= 1:
        raise HTTPException(status_code=400, detail="Cannot demote the last admin")
    await db.users.update_one({"id": user_id}, {"$set": {"role": "user", "admin_role": None}})
    await _audit_log(admin, "admin.demote", "user", user_id)
    await _create_notification(user_id, "account", "Admin access revoked", "Your admin access has been removed.")
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return fresh


# ------------------ Admin: Super Password (Danger-zone gate) ------------------


@api_router.get("/admin/super-password")
async def admin_super_password_status(_: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    h = await get_super_password_hash()
    return {"is_set": bool(h), "format": SUPER_PWD_FORMAT_DESC}


@api_router.post("/admin/super-password")
async def admin_set_super_password(
    payload: SuperPasswordSet,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Set or rotate the danger-zone super password. super_admin only.
    If one is already set, current_password must be provided and match."""
    existing = await get_super_password_hash()
    if existing:
        if not payload.current_password or not verify_password(payload.current_password, existing):
            raise HTTPException(status_code=401, detail="Current super password is incorrect")
    validate_super_password_format(payload.new_password)
    new_hash = hash_password(payload.new_password)
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"super_password_hash": new_hash, "super_password_set_at": now_utc().isoformat()}},
        upsert=True,
    )
    await _audit_log(admin, "super_password.set", "system", "global")
    return {"ok": True}


@api_router.post("/admin/super-password/verify")
async def admin_verify_super_password(
    payload: SuperPasswordVerify,
    _: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    ok = await verify_super_password(payload.super_password)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid super password")
    return {"ok": True}


# ------------------ Danger PIN endpoints ------------------


@api_router.get("/admin/danger-pin")
async def admin_danger_pin_status(_: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    h = await get_danger_pin_hash()
    return {"is_set": bool(h), "format": DANGER_PIN_FORMAT_DESC}


@api_router.post("/admin/danger-pin")
async def admin_set_danger_pin(
    payload: DangerPinSet,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Set or rotate the Danger PIN. super_admin only.
    If one is already set, current_pin must be provided and match."""
    existing = await get_danger_pin_hash()
    if existing:
        if not payload.current_pin or not verify_password(payload.current_pin, existing):
            raise HTTPException(status_code=401, detail="Current Danger PIN is incorrect")
    validate_danger_pin_format(payload.new_pin)
    new_hash = hash_password(payload.new_pin)
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"danger_pin_hash": new_hash, "danger_pin_set_at": now_utc().isoformat()}},
        upsert=True,
    )
    await _audit_log(admin, "danger_pin.set", "system", "global")
    return {"ok": True}

class ResetShopRequest(BaseModel):
    danger_pin: str = Field(..., min_length=6, max_length=6)


@api_router.post("/admin/system/reset-shop-products")
async def admin_reset_shop_products(
    payload: ResetShopRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Scoped reset — wipes ONLY shop products and directly-related data:
      • products
      • product_reviews
      • cart_items
      • shop_layout_blocks  (the per-block layout config)
      • shop_categories      (dynamic category list)

    EVERYTHING else is preserved: users, transactions, withdrawals,
    orders (historical sales record), services, wallets, settings,
    branding, snapshots, tickets, audit log, system_wallet_deposits.

    Per user request — a less destructive alternative to the full
    "wipe-users" / "wipe-all" actions, so admin can rebuild the catalog
    without losing customer or financial data.

    Requires the 6-digit Danger PIN. super_admin only. Auto-snapshot
    taken just before deletion so a restore is always possible.
    """
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Please set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")

    snap_info = await _take_snapshot(
        kind="auto-pre-reset-shop",
        note="Auto-backup before Reset Shop Products",
        created_by=admin["id"],
    )

    products_deleted = await db.products.delete_many({})
    reviews_deleted = await db.product_reviews.delete_many({})
    cart_deleted = await db.cart_items.delete_many({})
    layout_deleted = await db.shop_layout_blocks.delete_many({})
    categories_deleted = await db.shop_categories.delete_many({})

    summary = {
        "products_deleted":          products_deleted.deleted_count,
        "product_reviews_deleted":   reviews_deleted.deleted_count,
        "cart_items_deleted":        cart_deleted.deleted_count,
        "shop_layout_blocks_deleted": layout_deleted.deleted_count,
        "shop_categories_deleted":   categories_deleted.deleted_count,
    }
    await _audit_log(admin, "system.reset_shop_products", "system", "shop", summary)
    return {
        "ok": True,
        "summary": summary,
        "snapshot_id": snap_info.get("id") if snap_info else None,
    }


@api_router.post("/admin/system/wipe-users")
async def admin_wipe_users(
    payload: WipeUsersRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """DESTRUCTIVE: Deletes all (non-admin) users + their related data.
    Caller must provide the 6-digit Danger PIN. super_admin only."""
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Please set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")

    # ---------- AUTO BACKUP before destructive action ----------
    snap_info = await _take_snapshot(
        kind="auto-pre-wipe-users",
        note="Auto-backup before Wipe-All-Users",
        created_by=admin["id"],
    )

    user_query: Dict[str, Any] = {"role": {"$ne": "admin"}} if payload.keep_admins else {"id": {"$ne": admin["id"]}}
    if not payload.keep_admins:
        # never wipe self
        user_query = {"id": {"$ne": admin["id"]}}

    # Snapshot ids before delete (so we can purge their dependent data)
    targets = await db.users.find(user_query, {"_id": 0, "id": 1, "email": 1, "role": 1}).to_list(100000)
    target_ids = [t["id"] for t in targets]

    users_deleted = await db.users.delete_many(user_query)

    # Wipe related collections fully — cleanest slate
    cart_deleted = await db.cart_items.delete_many({}) if target_ids else type("X", (), {"deleted_count": 0})()
    notif_deleted = await db.notifications.delete_many({}) if target_ids else type("X", (), {"deleted_count": 0})()
    tx_deleted = await db.transactions.delete_many({}) if target_ids else type("X", (), {"deleted_count": 0})()
    wd_deleted = await db.withdrawals.delete_many({}) if target_ids else type("X", (), {"deleted_count": 0})()
    orders_deleted = await db.orders.delete_many({}) if target_ids else type("X", (), {"deleted_count": 0})()

    # Reset wallet/referral counters on remaining (admin) users so the system starts clean
    await db.users.update_many(
        {},
        {"$set": {
            "wallet_balance": 0.0,
            "total_earned": 0.0,
            "direct_referrals_count": 0,
            "payouts_received": 0,
        }},
    )

    await _audit_log(
        admin,
        "system.wipe_users",
        "system",
        "all",
        {
            "users_deleted": users_deleted.deleted_count,
            "transactions_deleted": tx_deleted.deleted_count,
            "withdrawals_deleted": wd_deleted.deleted_count,
            "orders_deleted": orders_deleted.deleted_count,
            "cart_items_deleted": cart_deleted.deleted_count,
            "notifications_deleted": notif_deleted.deleted_count,
            "keep_admins": payload.keep_admins,
            "snapshot_id": snap_info["id"],
        },
    )

    return {
        "ok": True,
        "users_deleted": users_deleted.deleted_count,
        "transactions_deleted": tx_deleted.deleted_count,
        "withdrawals_deleted": wd_deleted.deleted_count,
        "orders_deleted": orders_deleted.deleted_count,
        "cart_items_deleted": cart_deleted.deleted_count,
        "notifications_deleted": notif_deleted.deleted_count,
        "snapshot_id": snap_info["id"],
        "snapshot_created_at": snap_info["created_at"],
    }


@api_router.post("/admin/system/wipe-all")
async def admin_wipe_all(
    payload: WipeAllRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """ULTRA DESTRUCTIVE: Full factory reset. Deletes every business record
    (users, txns, orders, products, vendors, services, tickets, audit log,
    backups, deposits) and resets the seeded super-admin's wallet to ₹0.
    Preserves: settings (branding + payouts) and the super-admin login itself.
    Caller must provide the 6-digit Danger PIN AND type the phrase 'RESET'."""
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Please set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")
    if (payload.confirm_phrase or "").strip().upper() != "RESET":
        raise HTTPException(status_code=400, detail='You must type "RESET" to confirm a full factory wipe')

    # ---------- AUTO BACKUP before destructive action ----------
    # Take the snapshot first; it lands in db_snapshots and we deliberately do NOT
    # include db_snapshots in the wipe list below, so the backup survives the reset
    # and can be restored from Admin → Data Backups.
    snap_info = await _take_snapshot(
        kind="auto-pre-wipe-all",
        note="Auto-backup before Reset App to Zero",
        created_by=admin["id"],
    )

    # Identify the seed super-admin so we can keep their account but reset stats.
    seed_admin_email = ADMIN_EMAIL.lower()
    seed = await db.users.find_one({"email": seed_admin_email})
    seed_id = seed["id"] if seed else None

    summary: Dict[str, int] = {}

    # --- Wipe data collections (db_snapshots is intentionally NOT in this list) ---
    wipe_collections = [
        "transactions", "withdrawals", "orders", "cart_items", "notifications",
        "products", "vendor_sales", "vendor_applications",
        "service_bookings", "service_applications",
        "tickets", "ticket_messages",
        "system_wallet_deposits",
        "approved_registrations", "rejected_registrations",
    ]
    for coll in wipe_collections:
        res = await db[coll].delete_many({})
        summary[f"{coll}_deleted"] = res.deleted_count

    # --- Delete users (preserve only the seed super-admin) ---
    user_q: Dict[str, Any] = {"id": {"$ne": seed_id}} if seed_id else {}
    users_res = await db.users.delete_many(user_q)
    summary["users_deleted"] = users_res.deleted_count

    # --- Reset the seed admin's wallet & counters to zero ---
    if seed_id:
        await db.users.update_one(
            {"id": seed_id},
            {"$set": {
                "wallet_balance": 0.0,
                "total_earned": 0.0,
                "direct_referrals_count": 0,
                "payouts_received": 0,
                "wallet_buckets": {b: 0.0 for b in SYSTEM_WALLET_BUCKETS},
                "wallet_frozen": False,
                "is_blocked": False,
                "block_reason": None,
            }},
        )

    # --- Audit log: wipe LAST so this entry survives ---
    await db.audit_logs.delete_many({})
    await _audit_log(
        admin, "system.wipe_all", "system", "all",
        {"summary": summary, "preserved": ["settings", "seed_admin", "db_snapshots"], "snapshot_id": snap_info["id"]},
    )
    summary["audit_logs_deleted"] = 0  # we just wiped them and re-wrote 1

    return {
        "ok": True,
        "summary": summary,
        "snapshot_id": snap_info["id"],
        "snapshot_created_at": snap_info["created_at"],
        "message": "App reset to zero. Settings, super-admin account, and pre-reset backup preserved.",
    }


# ------------------ Admin: Settings (Payout Structure) ------------------


@api_router.get("/admin/settings")
async def admin_get_settings(_: Dict[str, Any] = Depends(require_admin)):
    return await get_settings()


@api_router.put("/admin/settings")
async def admin_update_settings(payload: SettingsUpdate, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.settings.update_one(
        {"id": "global"},
        {"$set": update},
        upsert=True,
    )
    return await get_settings()


# ------------------ Health ------------------


# ------------------ Cart & Orders ------------------
@api_router.post("/cart/add")
async def cart_add(payload: CartItem, user: Dict[str, Any] = Depends(get_current_user)):
    product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    existing = await db.cart_items.find_one({"user_id": user["id"], "product_id": payload.product_id})
    if existing:
        await db.cart_items.update_one(
            {"user_id": user["id"], "product_id": payload.product_id},
            {"$inc": {"qty": payload.qty}}
        )
    else:
        await db.cart_items.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "product_id": payload.product_id,
            "qty": payload.qty,
            "created_at": now_utc().isoformat(),
        })
    return {"ok": True}


@api_router.get("/cart")
async def cart_get(user: Dict[str, Any] = Depends(get_current_user)):
    items = await db.cart_items.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    enriched = []
    total = 0.0
    for it in items:
        product = await db.products.find_one({"id": it["product_id"]}, {"_id": 0})
        if product:
            line_total = product["price"] * it["qty"]
            total += line_total
            enriched.append({**it, "product": product, "line_total": line_total})
    return {"items": enriched, "total": total, "count": sum(i["qty"] for i in items)}


@api_router.post("/cart/remove")
async def cart_remove(payload: CartRemove, user: Dict[str, Any] = Depends(get_current_user)):
    await db.cart_items.delete_one({"user_id": user["id"], "product_id": payload.product_id})
    return {"ok": True}


@api_router.post("/cart/clear")
async def cart_clear(user: Dict[str, Any] = Depends(get_current_user)):
    await db.cart_items.delete_many({"user_id": user["id"]})
    return {"ok": True}


@api_router.post("/orders/checkout")
async def checkout(payload: Dict[str, Any] = Body(default={}), user: Dict[str, Any] = Depends(get_current_user)):
    """Place an order. Body:
      {
        "payment_method": "wallet" | "cod",
        "shipping_address": {
            "name": "...",
            "phone": "...",
            "line1": "...",
            "line2": "...",
            "city": "...",
            "state": "...",
            "pincode": "..."
        }
      }
    Wallet flow debits the user's wallet immediately. COD skips wallet debit;
    the order is marked `paid_via: "cod"` and the platform/vendor commissions
    are credited only when the delivery is marked complete (out of scope here
    — captured on order status update). For COD we still atomically decrement
    stock so we don't oversell.
    """
    payment_method = str((payload or {}).get("payment_method") or "wallet").strip().lower()
    if payment_method not in ("wallet", "cod"):
        raise HTTPException(status_code=400, detail="Unsupported payment_method. Use 'wallet' or 'cod'.")
    raw_addr = (payload or {}).get("shipping_address") or {}
    # Defensive: some legacy clients may send shipping_address as a string
    # instead of an object. Treat anything non-dict as missing.
    if not isinstance(raw_addr, dict):
        raw_addr = {}
    shipping_address = {
        "name": str(raw_addr.get("name") or "").strip(),
        "phone": str(raw_addr.get("phone") or "").strip(),
        "line1": str(raw_addr.get("line1") or "").strip(),
        "line2": str(raw_addr.get("line2") or "").strip(),
        "city": str(raw_addr.get("city") or "").strip(),
        "state": str(raw_addr.get("state") or "").strip(),
        "pincode": str(raw_addr.get("pincode") or "").strip(),
    }
    # Validate required fields
    missing = [k for k in ("name", "phone", "line1", "city", "state", "pincode") if not shipping_address[k]]
    if missing:
        raise HTTPException(status_code=400, detail=f"Shipping address missing: {', '.join(missing)}")
    if len(shipping_address["pincode"]) < 5:
        raise HTTPException(status_code=400, detail="Pincode must be at least 5 digits.")

    if user.get("wallet_frozen") and payment_method == "wallet":
        raise HTTPException(status_code=403, detail="Wallet is frozen. Pick COD or contact support.")
    items = await db.cart_items.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    enriched = []
    total = 0.0
    settings = await get_settings()
    vendor_pct = float(settings.get("vendor_commission_pct") or 70)
    vendor_payouts: Dict[str, float] = {}  # vendor_id -> total credit

    # ---------------- ATOMIC STOCK DECREMENT (multi-product) ----------------
    # We decrement stock per line BEFORE wallet debit. If any line fails (out of
    # stock or insufficient stock), we roll back every successful decrement so
    # nobody is left holding the bag. This prevents overselling under concurrent
    # checkouts.
    decremented: List[Dict[str, Any]] = []  # [{product_id, qty}]
    try:
        for it in items:
            product = await db.products.find_one({"id": it["product_id"]}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=400, detail=f"Product no longer exists: {it['product_id']}")
            qty = int(it.get("qty") or 1)
            # Atomic conditional decrement — only succeeds when stock >= qty.
            res = await db.products.update_one(
                {"id": product["id"], "stock": {"$gte": qty}},
                {"$inc": {"stock": -qty}},
            )
            if res.modified_count == 0:
                # Refresh stock for a friendly error message
                fresh = await db.products.find_one({"id": product["id"]}, {"_id": 0, "stock": 1, "name": 1})
                avail = int((fresh or {}).get("stock") or 0)
                raise HTTPException(
                    status_code=400,
                    detail=f"'{product.get('name')}' is out of stock (only {avail} left, you wanted {qty})",
                )
            decremented.append({"product_id": product["id"], "qty": qty})

            line_total = product["price"] * qty
            total += line_total
            vendor_id = product.get("vendor_id")
            vendor_share = 0.0
            platform_share = line_total
            if vendor_id:
                vendor_share = round(line_total * (vendor_pct / 100.0), 2)
                platform_share = round(line_total - vendor_share, 2)
                vendor_payouts[vendor_id] = vendor_payouts.get(vendor_id, 0.0) + vendor_share
            enriched.append({
                "product_id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "image_url": product["image_url"],
                "qty": qty,
                "line_total": line_total,
                "vendor_id": vendor_id,
                "vendor_share": vendor_share,
                "platform_share": platform_share,
            })
        if total <= 0:
            raise HTTPException(status_code=400, detail="Cart total invalid")
    except HTTPException:
        # Roll back all successful stock decrements before re-raising
        for d in decremented:
            await db.products.update_one(
                {"id": d["product_id"]},
                {"$inc": {"stock": d["qty"]}},
            )
        raise

    # ATOMIC wallet debit — guards against rapid double-clicks creating duplicate orders.
    # Only succeeds if balance still >= total at the moment of update.
    # SKIPPED for cash-on-delivery — the cash is collected by the courier.
    if payment_method == "wallet":
        debit_res = await db.users.update_one(
            {"id": user["id"], "wallet_balance": {"$gte": total}},
            {"$inc": {"wallet_balance": -total}},
        )
        if debit_res.modified_count == 0:
            # Wallet debit failed AFTER stock was decremented — must restore stock.
            for d in decremented:
                await db.products.update_one(
                    {"id": d["product_id"]},
                    {"$inc": {"stock": d["qty"]}},
                )
            raise HTTPException(status_code=400, detail=f"Insufficient wallet balance. Need ₹{total:.0f}")

    order_id = str(uuid.uuid4())
    order = {
        "id": order_id,
        "user_id": user["id"],
        "items": enriched,
        "total": total,
        "status": "placed",
        "paid_via": payment_method,  # "wallet" or "cod"
        "payment_status": ("paid" if payment_method == "wallet" else "pending_cod"),
        "shipping_address": shipping_address,
        "created_at": now_utc().isoformat(),
    }
    await db.orders.insert_one(order)
    await db.cart_items.delete_many({"user_id": user["id"]})
    try:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "order",
            "amount": -total,
            "status": "success",
            "description": f"Order #{order_id[:8]} ({len(enriched)} items)",
            "order_id": order_id,
            "created_at": now_utc().isoformat(),
        })
    except DuplicateKeyError:
        pass  # idempotent — entry already exists for this order

    # Credit admin's shopping_margin bucket with the platform share total
    # COD orders defer this until delivery — credit only on wallet-paid orders
    # so admin's "earned" only reflects money actually collected. COD orders
    # will credit on status → "delivered" via _settle_order_commission.
    platform_total = round(sum(float(it.get("platform_share") or 0) for it in enriched), 2)
    if platform_total > 0 and payment_method == "wallet":
        admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
        if admin_doc:
            await credit_admin_bucket("shopping_margin", platform_total, also_total_earned=True)
            try:
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_doc["id"],
                    "type": "shop_commission",
                    "amount": platform_total,
                    "status": "success",
                    "description": f"Shop margin from order #{order_id[:8]}",
                    "order_id": order_id,
                    "source_user_name": user.get("name"),
                    "created_at": now_utc().isoformat(),
                })
            except DuplicateKeyError:
                pass

    # Credit vendor wallets and write vendor sales ledger entries
    for it in enriched:
        if not it.get("vendor_id"):
            continue
        await db.vendor_sales.insert_one({
            "id": str(uuid.uuid4()),
            "vendor_id": it["vendor_id"],
            "order_id": order_id,
            "buyer_id": user["id"],
            "buyer_email": user.get("email"),
            "product_id": it["product_id"],
            "product_name": it["name"],
            "qty": it["qty"],
            "line_total": it["line_total"],
            "vendor_share": it["vendor_share"],
            "platform_share": it["platform_share"],
            "commission_pct": vendor_pct,
            "created_at": now_utc().isoformat(),
        })
    for vid, amount in vendor_payouts.items():
        await db.users.update_one({"id": vid}, {"$inc": {"wallet_balance": amount}})
        try:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": vid,
                "type": "vendor_sale",
                "amount": amount,
                "status": "success",
                "description": f"Vendor share credited from order #{order_id[:8]}",
                "order_id": order_id,
                "created_at": now_utc().isoformat(),
            })
        except DuplicateKeyError:
            pass
        try:
            await _create_notification(vid, "vendor", "New sale!", f"₹{amount:.0f} credited from order #{order_id[:8]}.")
        except Exception:
            pass

    await _create_notification(user["id"], "order", "Order placed!", f"Your order of ₹{int(total)} has been placed.")
    order.pop("_id", None)
    return order


@api_router.get("/orders/me")
async def my_orders(user: Dict[str, Any] = Depends(get_current_user)):
    items = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


# ------------------ Notifications ------------------
# Routes (GET /notifications/me, POST /notifications/me/read-all) extracted to
# /app/backend/routes/notifications.py during Phase 2B refactor.


# ------------------ Phase 1: KYC ------------------


def _validate_b64_image(s: Optional[str], field: str, max_bytes: int = 1_600_000) -> Optional[str]:
    """Lightly validate a data URL base64 image. Returns the string or None."""
    if not s:
        return None
    if not s.startswith("data:image/"):
        raise HTTPException(status_code=400, detail=f"{field}: must be a data URL image")
    # Approx decoded size (base64 expands by ~4/3)
    if len(s) > int(max_bytes * 4 / 3) + 200:
        raise HTTPException(status_code=400, detail=f"{field}: image too large (max ~1.5MB)")
    return s


@api_router.post("/users/me/kyc")
async def submit_kyc(payload: KYCSubmit, user: Dict[str, Any] = Depends(get_current_user)):
    aadhaar = payload.aadhaar.strip().replace(" ", "")
    pan = payload.pan.strip().upper()
    if len(aadhaar) != 12 or not aadhaar.isdigit():
        raise HTTPException(status_code=400, detail="Aadhaar must be 12 digits")
    if len(pan) != 10:
        raise HTTPException(status_code=400, detail="PAN must be 10 characters")

    update: Dict[str, Any] = {
        "kyc_status": "pending",
        "kyc_full_name": payload.full_name.strip(),
        "kyc_aadhaar": aadhaar,
        "kyc_pan": pan,
        "kyc_submitted_at": now_utc().isoformat(),
        "kyc_reject_reason": None,
    }
    # Only overwrite image fields when caller actually sent something — lets users keep
    # previously uploaded images on resubmit.
    af = _validate_b64_image(payload.aadhaar_front, "aadhaar_front")
    ab = _validate_b64_image(payload.aadhaar_back, "aadhaar_back")
    pi = _validate_b64_image(payload.pan_image, "pan_image")
    sf = _validate_b64_image(payload.selfie, "selfie")
    if af is not None:
        update["kyc_aadhaar_front"] = af
    if ab is not None:
        update["kyc_aadhaar_back"] = ab
    if pi is not None:
        update["kyc_pan_image"] = pi
    if sf is not None:
        update["kyc_selfie"] = sf

    await db.users.update_one({"id": user["id"]}, {"$set": update})
    await _create_notification(user["id"], "kyc", "KYC submitted", "Your KYC details are under review.")
    return {"ok": True, "status": "pending"}


@api_router.get("/users/me/kyc")
async def my_kyc(user: Dict[str, Any] = Depends(get_current_user)):
    # Re-fetch to include image fields not in cached dependency
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0}) or user
    return {
        "status": u.get("kyc_status", "none"),
        "full_name": u.get("kyc_full_name"),
        "aadhaar": u.get("kyc_aadhaar"),
        "pan": u.get("kyc_pan"),
        "submitted_at": u.get("kyc_submitted_at"),
        "reviewed_at": u.get("kyc_reviewed_at"),
        "reject_reason": u.get("kyc_reject_reason"),
        "aadhaar_front": u.get("kyc_aadhaar_front"),
        "aadhaar_back": u.get("kyc_aadhaar_back"),
        "pan_image": u.get("kyc_pan_image"),
        "selfie": u.get("kyc_selfie"),
        "has_aadhaar_front": bool(u.get("kyc_aadhaar_front")),
        "has_aadhaar_back": bool(u.get("kyc_aadhaar_back")),
        "has_pan_image": bool(u.get("kyc_pan_image")),
        "has_selfie": bool(u.get("kyc_selfie")),
    }


@api_router.get("/admin/kyc")
async def admin_list_kyc(_: Dict[str, Any] = Depends(require_admin), status: Optional[str] = None):
    q: Dict[str, Any] = {"kyc_status": {"$ne": "none"}}
    if status:
        q["kyc_status"] = status
    # Exclude heavy base64 image fields from list — fetch via /admin/kyc/{id} for detail.
    projection = {
        "_id": 0,
        "password_hash": 0,
        "kyc_aadhaar_front": 0,
        "kyc_aadhaar_back": 0,
        "kyc_pan_image": 0,
        "kyc_selfie": 0,
    }
    items = await db.users.find(q, projection).sort("kyc_submitted_at", -1).to_list(2000)
    # Add lightweight has_* flags so admin UI can show "image attached" badges
    for it in items:
        it["has_aadhaar_front"] = False
        it["has_aadhaar_back"] = False
        it["has_pan_image"] = False
        it["has_selfie"] = False
    # Cheap second pass: fetch only the boolean presence of images
    presence = await db.users.find(
        q,
        {"_id": 0, "id": 1,
         "kyc_aadhaar_front": 1, "kyc_aadhaar_back": 1,
         "kyc_pan_image": 1, "kyc_selfie": 1},
    ).to_list(2000)
    pmap = {p["id"]: p for p in presence}
    for it in items:
        p = pmap.get(it.get("id"), {})
        it["has_aadhaar_front"] = bool(p.get("kyc_aadhaar_front"))
        it["has_aadhaar_back"] = bool(p.get("kyc_aadhaar_back"))
        it["has_pan_image"] = bool(p.get("kyc_pan_image"))
        it["has_selfie"] = bool(p.get("kyc_selfie"))
    return items


@api_router.get("/admin/kyc/{user_id}")
async def admin_get_kyc_detail(user_id: str, _: Dict[str, Any] = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": u.get("id"),
        "name": u.get("name"),
        "email": u.get("email"),
        "phone": u.get("phone"),
        "kyc_status": u.get("kyc_status"),
        "kyc_full_name": u.get("kyc_full_name"),
        "kyc_aadhaar": u.get("kyc_aadhaar"),
        "kyc_pan": u.get("kyc_pan"),
        "kyc_submitted_at": u.get("kyc_submitted_at"),
        "kyc_reviewed_at": u.get("kyc_reviewed_at"),
        "kyc_reject_reason": u.get("kyc_reject_reason"),
        "aadhaar_front": u.get("kyc_aadhaar_front"),
        "aadhaar_back": u.get("kyc_aadhaar_back"),
        "pan_image": u.get("kyc_pan_image"),
        "selfie": u.get("kyc_selfie"),
    }


@api_router.post("/admin/kyc/{user_id}/approve")
async def admin_approve_kyc(user_id: str, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"kyc_status": "approved", "kyc_reviewed_at": now_utc().isoformat(), "kyc_reject_reason": None}},
    )
    await _create_notification(user_id, "kyc", "KYC approved", "Your KYC has been verified.")
    await _audit_log(admin, "kyc.approve", "user", user_id)
    return {"ok": True}


@api_router.post("/admin/kyc/{user_id}/reject")
async def admin_reject_kyc(user_id: str, payload: KYCReject, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"kyc_status": "rejected", "kyc_reviewed_at": now_utc().isoformat(), "kyc_reject_reason": payload.reason}},
    )
    await _create_notification(user_id, "kyc", "KYC rejected", payload.reason)
    await _audit_log(admin, "kyc.reject", "user", user_id, {"reason": payload.reason})
    return {"ok": True}


# ------------------ Admin Approval Gate (registration → admin review → payout) ------------------
REJECT_CATEGORIES = {
    # New unified 3-category system (finance-approval flow)
    "payment_unsuccessful": "Payment unsuccessful",
    "referral_code_mistake": "Referral code was incorrect",
    "other": "Other",
    # Legacy categories (kept for backfill — UI no longer surfaces these for new rejections)
    "cibil_score": "CIBIL score insufficient — please upload your CIBIL report",
    "identity_mismatch": "Identity details don't match the documents",
    "suspicious_activity": "Suspicious activity detected on the account",
    "incomplete_documents": "Documents are incomplete or unclear",
    "custom": "Custom reason",
}

# Categories that archive + delete the user (new policy). Legacy ones stay in-place.
ARCHIVE_ON_REJECT_CATEGORIES = {"payment_unsuccessful", "referral_code_mistake", "other"}


async def _archive_and_delete_user(user_doc: Dict[str, Any], *, category: str, remarks: str, rejected_by: str) -> Dict[str, Any]:
    """Move a user into rejected_registrations + delete from the active users
    collection. Returns the created archive record."""
    record = {
        "id": str(uuid.uuid4()),
        "original_user_id": user_doc["id"],
        "email": user_doc.get("email"),
        "name": user_doc.get("name"),
        "phone": user_doc.get("phone"),
        "referral_code": user_doc.get("referral_code"),
        "referred_by": user_doc.get("referred_by"),
        "sponsor_id": user_doc.get("sponsor_id"),
        "category": category,
        "remarks": remarks,
        "rejected_at": now_utc().isoformat(),
        "rejected_by": rejected_by,
        "registration_paid": bool(user_doc.get("registration_paid")),
        "payment_method": user_doc.get("payment_method"),
        "payment_attempts": int(user_doc.get("payment_attempts") or 0),
        # Snapshot the full original doc (minus password hash & heavy image fields) for audit.
        "snapshot": {k: v for k, v in user_doc.items() if k not in {
            "_id", "password_hash",
            "kyc_aadhaar_front", "kyc_aadhaar_back", "kyc_pan_image", "kyc_selfie",
            "extra_docs",
        }},
        "created_at": now_utc().isoformat(),
    }
    await db.rejected_registrations.insert_one(record)
    # Purge the user + their dependent data (keep transactions for finance trail).
    await db.users.delete_one({"id": user_doc["id"]})
    await db.cart_items.delete_many({"user_id": user_doc["id"]})
    await db.notifications.delete_many({"user_id": user_doc["id"]})
    return record


@api_router.get("/admin/approvals")
async def admin_list_approvals(
    _: Dict[str, Any] = Depends(require_admin),
    status: Optional[str] = Query(default="pending"),
):
    """List users by approval_status. Defaults to pending."""
    if status not in ("pending", "approved", "rejected", "all"):
        raise HTTPException(status_code=400, detail="Invalid status")
    q: Dict[str, Any] = {"role": "user"}
    if status != "all":
        q["approval_status"] = status
    projection = {
        "_id": 0, "password_hash": 0,
        "kyc_aadhaar_front": 0, "kyc_aadhaar_back": 0, "kyc_pan_image": 0, "kyc_selfie": 0,
        "extra_docs": 0,
    }
    items = await db.users.find(q, projection).sort("created_at", -1).to_list(2000)
    # Add sponsor email for context
    sponsor_ids = list({i.get("sponsor_id") for i in items if i.get("sponsor_id")})
    sponsors = {s["id"]: s for s in await db.users.find(
        {"id": {"$in": sponsor_ids}},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "referral_code": 1},
    ).to_list(len(sponsor_ids) or 1)} if sponsor_ids else {}
    for it in items:
        sp = sponsors.get(it.get("sponsor_id"))
        it["sponsor_email"] = (sp or {}).get("email")
        it["sponsor_name"] = (sp or {}).get("name")
    return items


@api_router.get("/admin/approvals/today")
async def admin_list_approvals_today(_: Dict[str, Any] = Depends(require_admin)):
    """Users who registered today (server clock UTC)."""
    today = now_utc().date().isoformat()
    items = await db.users.find(
        {"role": "user", "created_at": {"$regex": f"^{today}"}},
        {"_id": 0, "password_hash": 0,
         "kyc_aadhaar_front": 0, "kyc_aadhaar_back": 0, "kyc_pan_image": 0, "kyc_selfie": 0,
         "extra_docs": 0},
    ).sort("created_at", -1).to_list(500)
    sponsor_ids = list({i.get("sponsor_id") for i in items if i.get("sponsor_id")})
    sponsors = {s["id"]: s for s in await db.users.find(
        {"id": {"$in": sponsor_ids}}, {"_id": 0, "id": 1, "email": 1, "name": 1},
    ).to_list(len(sponsor_ids) or 1)} if sponsor_ids else {}
    for it in items:
        sp = sponsors.get(it.get("sponsor_id"))
        it["sponsor_email"] = (sp or {}).get("email")
        it["sponsor_name"] = (sp or {}).get("name")
    return items


@api_router.get("/admin/approvals/{user_id}")
async def admin_get_approval_detail(user_id: str, _: Dict[str, Any] = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    sp = None
    if u.get("sponsor_id"):
        sp = await db.users.find_one({"id": u["sponsor_id"]}, {"_id": 0, "id": 1, "email": 1, "name": 1, "referral_code": 1})
    u["sponsor"] = sp
    return u


@api_router.post("/admin/approvals/{user_id}/approve")
async def admin_approve_user(
    user_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") != "user":
        raise HTTPException(status_code=400, detail="Only regular users need approval")
    if target.get("approval_status") == "approved":
        return {"ok": True, "already_approved": True}
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "approval_status": "approved",
            "approval_reviewed_at": now_utc().isoformat(),
            "approval_reviewed_by": admin["id"],
            "approval_reject_category": None,
            "approval_reject_reason": None,
        }},
    )
    fresh = await db.users.find_one({"id": user_id})
    # Trigger commissions only if registration is paid (paid users entering the tree).
    if fresh and fresh.get("registration_paid"):
        await _trigger_referral_commissions(fresh)
    # Archive into approved_registrations bucket (a separate "category" of data,
    # distinct from products and from rejected_registrations). Finance approvals
    # are tagged as auto_approved so they can be filtered in the admin UI.
    if fresh:
        await _archive_approved_user(fresh, admin)
    await _create_notification(
        user_id, "approval",
        "Account approved",
        "You have been approved by admin. Your sponsor's network has been credited and earnings are now active.",
    )
    await _audit_log(admin, "user.approve", "user", user_id, {"approver_role": admin.get("admin_role") or "super_admin"})
    return {"ok": True}


async def _archive_approved_user(user_doc: Dict[str, Any], admin: Dict[str, Any]) -> Dict[str, Any]:
    """Write/refresh a record in approved_registrations. The collection is a
    'separate data category' that holds an audit trail of every user who has
    been approved (by finance, super_admin, manager, or support). Finance-approved
    users are flagged auto_approved=True so they're easy to filter."""
    approver_role = admin.get("admin_role") or "super_admin"
    record = {
        "id": str(uuid.uuid4()),
        "original_user_id": user_doc["id"],
        "email": user_doc.get("email"),
        "name": user_doc.get("name"),
        "phone": user_doc.get("phone"),
        "referral_code": user_doc.get("referral_code"),
        "referred_by": user_doc.get("referred_by"),
        "sponsor_id": user_doc.get("sponsor_id"),
        "registration_paid": bool(user_doc.get("registration_paid")),
        "payment_method": user_doc.get("payment_method"),
        "wallet_balance_at_approval": float(user_doc.get("wallet_balance") or 0),
        "approver_role": approver_role,
        "approver_id": admin["id"],
        "approver_email": admin.get("email"),
        "auto_approved": approver_role in ("finance", "auto"),
        "source": "admin_created" if user_doc.get("created_by_admin") else (
            "google" if user_doc.get("auth_provider") == "google" else "self"
        ),
        "approved_at": now_utc().isoformat(),
        "snapshot": {k: v for k, v in user_doc.items() if k not in {
            "_id", "password_hash",
            "kyc_aadhaar_front", "kyc_aadhaar_back", "kyc_pan_image", "kyc_selfie",
            "extra_docs",
        }},
    }
    # Avoid duplicate archive entries if the same user is approved twice — replace existing.
    await db.approved_registrations.delete_many({"original_user_id": user_doc["id"]})
    await db.approved_registrations.insert_one(record)
    return record


# ------------------ Admin: Approved registrations bucket ------------------
@api_router.get("/admin/approved-registrations")
async def admin_list_approved_registrations(
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance", "manager", "support")),
    role_filter: Optional[str] = Query(default=None),  # all | finance | super_admin | manager | support | auto
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
):
    q: Dict[str, Any] = {}
    if role_filter and role_filter != "all":
        if role_filter == "auto":
            q["auto_approved"] = True
        elif role_filter in {"super_admin", "finance", "manager", "support"}:
            q["approver_role"] = role_filter
        else:
            raise HTTPException(status_code=400, detail="Invalid role filter")
    if search:
        s = search.strip()
        q["$or"] = [
            {"email": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}},
            {"phone": {"$regex": s, "$options": "i"}},
            {"referral_code": {"$regex": s, "$options": "i"}},
        ]
    items = await db.approved_registrations.find(q, {"_id": 0, "snapshot": 0}).sort("approved_at", -1).to_list(limit)
    pipeline = [{"$group": {"_id": "$approver_role", "n": {"$sum": 1}}}]
    agg = await db.approved_registrations.aggregate(pipeline).to_list(100)
    counts = {row["_id"]: row["n"] for row in agg if row["_id"]}
    counts["all"] = sum(counts.values())
    counts["auto"] = await db.approved_registrations.count_documents({"auto_approved": True})
    return {"items": items, "counts": counts}


@api_router.get("/admin/approved-registrations/export")
async def admin_export_approved(
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
    role_filter: Optional[str] = Query(default=None),
):
    q: Dict[str, Any] = {}
    if role_filter and role_filter != "all":
        if role_filter == "auto":
            q["auto_approved"] = True
        elif role_filter in {"super_admin", "finance", "manager", "support"}:
            q["approver_role"] = role_filter
        else:
            raise HTTPException(status_code=400, detail="Invalid role filter")
    items = await db.approved_registrations.find(q, {"_id": 0, "snapshot": 0}).sort("approved_at", -1).to_list(20000)
    def esc(v: Any) -> str:
        s = "" if v is None else str(v)
        if any(ch in s for ch in [",", "\"", "\n"]):
            s = '"' + s.replace('"', '""') + '"'
        return s
    fields = ["id", "original_user_id", "name", "email", "phone", "referral_code", "referred_by",
              "registration_paid", "payment_method", "wallet_balance_at_approval", "source",
              "approver_role", "approver_email", "auto_approved", "approved_at"]
    header = ",".join(fields)
    lines = [header]
    for it in items:
        lines.append(",".join(esc(it.get(f)) for f in fields))
    return Response(content="\n".join(lines), media_type="text/csv")


@api_router.delete("/admin/approved-registrations/{rec_id}")
async def admin_delete_approved(rec_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Removes the archive record only. Does NOT remove the underlying user."""
    r = await db.approved_registrations.delete_one({"id": rec_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")
    await _audit_log(admin, "approved.delete_record", "approved_registration", rec_id)
    return {"ok": True}


@api_router.post("/admin/approvals/{user_id}/reject")
async def admin_reject_user(user_id: str, payload: ApprovalReject, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") != "user":
        raise HTTPException(status_code=400, detail="Only regular users can be rejected")
    if payload.category not in REJECT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid rejection category")
    # "other" (new) requires free-text remarks; legacy "custom" also requires remarks.
    if payload.category in ("other", "custom") and not (payload.reason and payload.reason.strip()):
        raise HTTPException(status_code=400, detail="Remarks are required for this category")
    reason = (payload.reason or REJECT_CATEGORIES[payload.category]).strip()

    # NEW policy: the 3 finance-gate categories archive + delete the user record.
    if payload.category in ARCHIVE_ON_REJECT_CATEGORIES:
        record = await _archive_and_delete_user(
            target, category=payload.category, remarks=reason, rejected_by=admin["id"],
        )
        await _audit_log(
            admin, "user.reject", "user", user_id,
            {"category": payload.category, "reason": reason, "archived": True, "archive_id": record["id"]},
        )
        return {"ok": True, "archived": True, "archive_id": record["id"]}

    # Legacy categories — keep the user but flip approval_status (enables the extra-docs re-apply flow).
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "approval_status": "rejected",
            "approval_reviewed_at": now_utc().isoformat(),
            "approval_reviewed_by": admin["id"],
            "approval_reject_category": payload.category,
            "approval_reject_reason": reason,
        }},
    )
    msg = (
        f"Your account approval was rejected: {reason}. "
        f"Please upload additional documents (CIBIL report, bank statement, income proof) "
        f"under the 'Additional documents' section and we will re-review."
    )
    await _create_notification(user_id, "approval", "Account approval rejected", msg)
    await _audit_log(admin, "user.reject", "user", user_id, {"category": payload.category, "reason": reason, "archived": False})
    return {"ok": True, "archived": False}


# ------------------ Admin: Create user (offline-paid) ------------------


@api_router.post("/admin/users/create")
async def admin_create_user(
    payload: AdminCreateUserRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support")),
):
    """Create a user account from the admin panel (admin, support, super_admin).
    The account is marked paid-offline and routed to finance for approval."""
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    sponsor = None
    sponsor_code = (payload.referral_code or "").strip().upper() or None
    if sponsor_code:
        sponsor = await db.users.find_one({"referral_code": sponsor_code})
        if not sponsor:
            raise HTTPException(status_code=400, detail="Invalid referral code")

    user_id = str(uuid.uuid4())
    while True:
        code = gen_referral_code()
        if not await db.users.find_one({"referral_code": code}):
            break

    settings = await get_settings()
    now = now_utc().isoformat()

    user_doc = {
        "id": user_id,
        "name": payload.name.strip(),
        "email": email,
        "password_hash": hash_password(payload.password),
        "phone": payload.phone,
        "role": "user",
        "admin_role": None,
        "referral_code": code,
        "referred_by": sponsor["referral_code"] if sponsor else None,
        "sponsor_id": sponsor["id"] if sponsor else None,
        "wallet_balance": 0.0,
        "total_earned": 0.0,
        "registration_paid": bool(payload.mark_paid_offline),
        "payment_method": "admin_offline" if payload.mark_paid_offline else None,
        "paid_at": now if payload.mark_paid_offline else None,
        "payment_attempts": 0,
        "last_payment_failure_at": None,
        "direct_referrals_count": 0,
        "payouts_received": 0,
        "upi_id": None,
        "bank_account": None,
        "ifsc": None,
        "account_holder": None,
        "is_blocked": False,
        "block_reason": None,
        "wallet_frozen": False,
        "kyc_status": "none",
        "kyc_full_name": None,
        "kyc_aadhaar": None,
        "kyc_pan": None,
        "kyc_submitted_at": None,
        "kyc_reviewed_at": None,
        "kyc_reject_reason": None,
        "approval_status": "pending",
        "approval_reviewed_at": None,
        "approval_reviewed_by": None,
        "approval_reject_category": None,
        "approval_reject_reason": None,
        "commission_triggered": False,
        "created_by_admin": admin["id"],
        "extra_docs": {
            "cibil_report": None, "bank_statement": None, "income_proof": None, "other": None, "submitted_at": None,
        },
        "created_at": now,
    }
    await db.users.insert_one(user_doc)

    # Log an offline-paid transaction for bookkeeping
    if payload.mark_paid_offline:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "type": "registration_fee",
            "amount": settings["registration_fee"],
            "status": "paid",
            "description": f"Registration fee — offline (admin {admin.get('email')})",
            "created_at": now,
        })

    await _create_notification(
        user_id, "welcome",
        "Account created by admin",
        "Your account was created by our team. It is awaiting final finance approval before login access is enabled.",
    )
    await _audit_log(admin, "user.admin_create", "user", user_id, {"email": email, "mark_paid_offline": payload.mark_paid_offline})
    return {"ok": True, "user": serialize_user(user_doc)}


# ------------------ Admin: Rejected registrations archive ------------------
@api_router.get("/admin/rejected-registrations")
async def admin_list_rejected_registrations(
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance", "manager", "support")),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=500, le=2000),
):
    q: Dict[str, Any] = {}
    if category and category != "all":
        if category not in REJECT_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        q["category"] = category
    if search:
        s = search.strip()
        q["$or"] = [
            {"email": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}},
            {"phone": {"$regex": s, "$options": "i"}},
            {"referral_code": {"$regex": s, "$options": "i"}},
        ]
    items = await db.rejected_registrations.find(q, {"_id": 0, "snapshot": 0}).sort("rejected_at", -1).to_list(limit)

    # Counts per category for the UI tabs
    pipeline = [{"$group": {"_id": "$category", "n": {"$sum": 1}}}]
    agg = await db.rejected_registrations.aggregate(pipeline).to_list(100)
    counts = {row["_id"]: row["n"] for row in agg}
    counts["all"] = sum(counts.values())
    return {"items": items, "counts": counts}


@api_router.get("/admin/rejected-registrations/export")
async def admin_export_rejected(
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
    category: Optional[str] = Query(default=None),
):
    q: Dict[str, Any] = {}
    if category and category != "all":
        if category not in REJECT_CATEGORIES:
            raise HTTPException(status_code=400, detail="Invalid category")
        q["category"] = category
    items = await db.rejected_registrations.find(q, {"_id": 0, "snapshot": 0}).sort("rejected_at", -1).to_list(20000)
    # Manual CSV (to avoid pulling new deps)
    def esc(v: Any) -> str:
        s = "" if v is None else str(v)
        if any(ch in s for ch in [",", "\"", "\n"]):
            s = '"' + s.replace('"', '""') + '"'
        return s
    fields = ["id", "original_user_id", "name", "email", "phone", "referral_code", "referred_by",
              "category", "remarks", "registration_paid", "payment_method", "payment_attempts",
              "rejected_at", "rejected_by"]
    header = ",".join(fields)
    lines = [header]
    for it in items:
        lines.append(",".join(esc(it.get(f)) for f in fields))
    return Response(content="\n".join(lines), media_type="text/csv")


@api_router.delete("/admin/rejected-registrations/{rec_id}")
async def admin_delete_rejected(rec_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    r = await db.rejected_registrations.delete_one({"id": rec_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Record not found")
    await _audit_log(admin, "rejected.delete", "rejected_registration", rec_id)
    return {"ok": True}


# ------------------ User: Additional Documents (CIBIL etc.) ------------------


@api_router.post("/users/me/additional-docs")
async def submit_additional_docs(payload: ExtraDocsSubmit, user: Dict[str, Any] = Depends(get_current_user)):
    """Upload additional documents requested after a rejection."""
    update_extra: Dict[str, Any] = {}
    cb = _validate_b64_image(payload.cibil_report, "cibil_report") if payload.cibil_report else None
    bs = _validate_b64_image(payload.bank_statement, "bank_statement") if payload.bank_statement else None
    ip = _validate_b64_image(payload.income_proof, "income_proof") if payload.income_proof else None
    ot = _validate_b64_image(payload.other, "other") if payload.other else None
    if cb:
        update_extra["extra_docs.cibil_report"] = cb
    if bs:
        update_extra["extra_docs.bank_statement"] = bs
    if ip:
        update_extra["extra_docs.income_proof"] = ip
    if ot:
        update_extra["extra_docs.other"] = ot
    if not update_extra:
        raise HTTPException(status_code=400, detail="At least one document must be provided")
    update_extra["extra_docs.submitted_at"] = now_utc().isoformat()
    # Move user back to 'pending' so admin sees them in the queue again, only if currently rejected.
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "approval_status": 1})
    if fresh and fresh.get("approval_status") == "rejected":
        update_extra["approval_status"] = "pending"
    await db.users.update_one({"id": user["id"]}, {"$set": update_extra})
    await _create_notification(
        user["id"], "approval",
        "Additional documents submitted",
        "Thanks! Your additional documents have been re-submitted for admin review.",
    )
    return {"ok": True}


@api_router.get("/users/me/additional-docs")
async def my_additional_docs(user: Dict[str, Any] = Depends(get_current_user)):
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "extra_docs": 1, "approval_status": 1, "approval_reject_category": 1, "approval_reject_reason": 1})
    return {
        "approval_status": (u or {}).get("approval_status"),
        "reject_category": (u or {}).get("approval_reject_category"),
        "reject_reason": (u or {}).get("approval_reject_reason"),
        "extra_docs": (u or {}).get("extra_docs") or {},
    }


@api_router.get("/admin/approvals/{user_id}/additional-docs")
async def admin_get_user_extra_docs(user_id: str, _: Dict[str, Any] = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "extra_docs": 1, "name": 1, "email": 1, "approval_status": 1})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


# ------------------ Phase 1: User Block / Wallet Admin ------------------


@api_router.post("/admin/users/{user_id}/block")
async def admin_block_user(user_id: str, payload: BlockRequest, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    await db.users.update_one({"id": user_id}, {"$set": {"is_blocked": True, "block_reason": payload.reason}})
    await _audit_log(admin, "user.block", "user", user_id, {"reason": payload.reason})
    return {"ok": True}


@api_router.post("/admin/users/{user_id}/unblock")
async def admin_unblock_user(user_id: str, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    await db.users.update_one({"id": user_id}, {"$set": {"is_blocked": False, "block_reason": None}})
    await _audit_log(admin, "user.unblock", "user", user_id)
    return {"ok": True}


@api_router.get("/admin/system-wallet/breakdown")
async def get_system_wallet_breakdown(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    """Full money-flow breakdown — categorizes every successful transaction
    on the platform into INFLOW (money coming in) and OUTFLOW (money going
    out) so admin can reconcile WHY treasury balances differ from raw
    revenue. Answers: where did every rupee go?

    Inflow categories (cash entering the platform):
      • Registration fees — no-ref signups (admin pockets full ₹118)
      • Registration fees — with-ref signups (funds the L1..L10 cascade)
      • UTR direct-added deposits
      • Service margin (platform fees on bookings)
      • Shop margin (platform fees on orders)

    Outflow categories (cash leaving / being redistributed):
      • Referral commissions credited to user wallets (net of GST)
      • GST collected (regulatory hold)
      • User withdrawals (completed)
      • Cascade overflow rerouted to admin
    """
    settings = await get_settings()
    fee = float(settings.get("registration_fee") or 0)

    async def _sum(query: Dict[str, Any]) -> float:
        agg = await db.transactions.aggregate([
            {"$match": query},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        return float(agg[0]["total"] if agg else 0)

    async def _count(coll, query: Dict[str, Any]) -> int:
        return await coll.count_documents(query)

    # ─── INFLOW ───
    # Source of truth: actual `registration_fee` ledger transactions
    # (NOT user_count × fee — seed/demo users marked paid without a fee
    # txn would otherwise inflate the inflow total).
    reg_fee_txn_total = await _sum({
        "type": "registration_fee",
        "status": {"$in": ["paid", "success", "approved"]},
    })
    # Counts kept for UI breakdown but not used for inflow math
    no_ref_count = await _count(db.users, {"no_referral_signup": True, "registration_paid": True})
    with_ref_count = await _count(db.users, {
        "no_referral_signup": {"$ne": True},
        "registration_paid": True,
        "role": "user",
    })
    # Split actual fee inflow by no_ref vs with_ref based on the linked user
    no_ref_revenue_agg = await db.transactions.aggregate([
        {"$match": {"type": "registration_fee", "status": {"$in": ["paid", "success", "approved"]}}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "u"}},
        {"$match": {"u.no_referral_signup": True}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    no_ref_revenue = round(float(no_ref_revenue_agg[0]["total"] if no_ref_revenue_agg else 0), 2)
    with_ref_revenue = round(reg_fee_txn_total - no_ref_revenue, 2)
    total_revenue = round(reg_fee_txn_total, 2)
    utr_deposits = await _sum({"type": "system_deposit", "status": {"$in": ["success", "paid", "approved"]}})
    service_margin = await _sum({"type": {"$in": ["service_margin", "service_commission"]}, "status": "success"})
    shop_margin = await _sum({"type": {"$in": ["shopping_margin", "shop_commission"]}, "status": "success"})
    shop_margin -= abs(await _sum({"type": "shop_commission_reversal", "status": "success"}))
    service_margin -= abs(await _sum({"type": "service_commission_reversal", "status": "success"}))
    inflow_total = round(total_revenue + utr_deposits + service_margin + shop_margin, 2)

    # ─── OUTFLOW ───
    # Net amounts credited to user wallets via cascade payouts
    user_wallets_paid = await _sum({"type": "referral_payout", "status": "success"})
    gst_collected = await _sum({"type": "gst_collected", "status": "success"})
    cascade_overflow = await _sum({"type": "cascade_overflow", "status": "success"})
    # PURE direct-signup credits ONLY (no-ref + EARN flows: ₹100 each).
    # Fee-residuals from with-ref signups are tracked separately so the UI's
    # "Direct Joins" tab shows the right ledger value (matches no_ref_count
    # × ₹100) without inflating it with leftover commission pool slop.
    direct_signup_credit = await _sum({"type": "direct_signup_credit", "status": "success"})
    fee_residual = await _sum({"type": "fee_residual", "status": "success"})
    user_withdrawals_done = abs(await _sum({"type": "withdrawal", "status": "success"}))
    # L1 funding debits — these are NEGATIVE amounts subtracted from admin
    # buckets to pay L1 payouts (which exceed the per-signup fee). Adding
    # them keeps Inflow == Outflow because the L1 user-wallet credit was
    # already counted in `user_wallets_paid` and these debits zero out the
    # phantom-money inflation.
    l1_funding_debit = await _sum({"type": "l1_funding", "status": "success"})  # negative number
    # ─── Admin-held inflows mirrored as outflow lines ──────────────────
    # UTR deposits, shop_margin, service_margin all land in DEDICATED admin
    # wallet buckets (direct_added, shopping_margin, service_margin). They
    # are simultaneously an inflow (money into platform) AND held in admin
    # wallet — so to make the breakdown identity `inflow == outflow` hold,
    # we mirror them as offsetting outflow rows (admin-held buckets).
    admin_direct_added = round(utr_deposits, 2)
    admin_shop_margin_held = round(shop_margin, 2)
    admin_service_margin_held = round(service_margin, 2)
    # ─── CONSOLIDATED ADMIN-RETAINED LINE ──────────────────────────────
    # User-facing simplification (per Feb-2026 review):
    # Collapse direct_signup + fee_residual + cascade_overflow + GST into
    # ONE consolidated "Admin Wallet" figure that ALREADY nets the L1
    # funding debit. GST lives INSIDE this number (it's part of admin's
    # bank balance — the GST line on the UI is informational only and
    # NOT added to the tally a second time).
    #
    # This guarantees:    Inflow == Outflow == Visible 6-line Tally
    # Split user_wallets_paid into:
    #   - to NON-admin users (these are the funds that ACTUALLY land in
    #     user wallets and may eventually be withdrawn)
    #   - to admin (when admin is the L_N upline at a depth where cascade
    #     reaches root — these go straight to admin.referral_commission)
    admin_user = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"id": 1, "_id": 0})
    _aid = (admin_user or {}).get("id")
    to_users_referral_net = round(await _sum({
        "type": "referral_payout", "status": "success",
        **({"user_id": {"$ne": _aid}} if _aid else {}),
    }), 2)
    to_admin_via_cascade = round(await _sum({
        "type": "referral_payout", "status": "success",
        **({"user_id": _aid} if _aid else {}),
    }), 2)

    admin_retained = round(
        direct_signup_credit + fee_residual + cascade_overflow
        + gst_collected + l1_funding_debit + to_admin_via_cascade,
        2,
    )

    # ─── HONEST MONEY-FLOW IDENTITY ──────────────────────────────────
    # `to_user_wallets_referral_net` is the LIFETIME net credit to non-admin
    # users — it INCLUDES amounts subsequently withdrawn to bank (the credit
    # event already happened; withdrawal is a wallet→bank movement, not a
    # new redistribution event). Therefore `redistributed_total` mathematically
    # equals `inflow_total` (every rupee in has been allocated somewhere on
    # the ledger), and `outflow_total == redistributed_total == inflow_total`.
    #
    # Withdrawals are surfaced as a SEPARATE "left platform" line in the UI
    # (used to compute Bank Tally = inflow − withdrawn = currently held on
    # platform). They are NOT added a second time to `outflow.total`.
    redistributed_total = round(
        to_users_referral_net + admin_retained
        + admin_direct_added + admin_shop_margin_held + admin_service_margin_held,
        2,
    )
    # `outflow_total` == `inflow_total` (identity: every rupee in is allocated).
    outflow_total = redistributed_total

    # ─── BALANCE CHECK ───
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    admin_total = float((a or {}).get("wallet_balance") or 0)
    users_wallet_agg = await db.users.aggregate([
        {"$match": {"role": "user"}},
        {"$group": {"_id": None, "total": {"$sum": "$wallet_balance"}}},
    ]).to_list(1)
    users_wallet_total = float(users_wallet_agg[0]["total"] if users_wallet_agg else 0)

    return {
        "inflow": {
            "registration_fee_total": total_revenue,
            "no_ref_signup_revenue":  no_ref_revenue,
            "with_ref_signup_revenue": with_ref_revenue,
            "no_ref_count": no_ref_count,
            "with_ref_count": with_ref_count,
            "utr_deposits": round(utr_deposits, 2),
            "service_margin": round(service_margin, 2),
            "shop_margin": round(shop_margin, 2),
            "total": inflow_total,
        },
        "outflow": {
            # ─── INTERNAL REDISTRIBUTION (sums to inflow − withdrawals) ──
            "to_user_wallets_referral_net": to_users_referral_net,  # NEW: net to non-admin users only
            "to_admin_retained":         admin_retained,
            "to_admin_gst_collected":    round(gst_collected, 2),
            "to_admin_direct_added":     admin_direct_added,
            "to_admin_shop_margin":      admin_shop_margin_held,
            "to_admin_service_margin":   admin_service_margin_held,
            "to_admin_via_cascade":      to_admin_via_cascade,  # NEW: admin-recipient L_N (already in admin_retained)
            # ─── LEFT PLATFORM (cash withdrawn to bank) ──────────────────
            "user_withdrawals_settled":  round(user_withdrawals_done, 2),
            # ─── DEPRECATED: kept for backwards-compat — equals
            #     to_user_wallets_referral_net + to_admin_via_cascade.
            "to_user_wallets_referral":  round(user_wallets_paid, 2),
            # ─── Audit-level legacy sub-breakdown (still exposed so the
            #     drill-downs in /admin/system-wallet/transactions can map
            #     bucket keys correctly; UI no longer surfaces them as
            #     separate Treasury lines). ───────────────────────────────
            "_legacy_to_admin_direct_signup":    round(direct_signup_credit, 2),
            "_legacy_to_admin_fee_residual":     round(fee_residual, 2),
            "_legacy_to_admin_cascade_overflow": round(cascade_overflow, 2),
            "_legacy_l1_funding_debit":          round(l1_funding_debit, 2),
            # ─── TOTALS ──────────────────────────────────────────────────
            "redistributed_total":       redistributed_total,    # NEW: held internally
            "total":                     outflow_total,           # legacy: redistributed + withdrawn = inflow
        },
        "balance": {
            "in_admin_wallet": round(admin_total, 2),
            "in_user_wallets": round(users_wallet_total, 2),
            "held_total":      round(admin_total + users_wallet_total, 2),
        },
        "settings": {
            "registration_fee": fee,
            "directs_required": int(settings.get("directs_required") or 4),
            "level_payouts":    [float(settings.get(f"payout_l{i}", 0) or 0) for i in range(1, 11)],
        },
    }


@api_router.get("/admin/system-wallet")
async def get_system_wallet(admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance"))):
    """Return the admin's wallet broken down by bucket + recent deposits."""
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not a:
        raise HTTPException(status_code=404, detail="Admin not found")
    buckets = a.get("wallet_buckets") or {}
    out = {b: float(buckets.get(b) or 0) for b in SYSTEM_WALLET_BUCKETS}
    deposits = await db.system_wallet_deposits.find({}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return {
        "buckets": out,
        "total": float(a.get("wallet_balance") or 0),
        "deposits": deposits,
    }


@api_router.post("/admin/system-wallet/reconcile")
async def reconcile_system_wallet(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    """One-shot accounting reconciliation:
      • Recompute each bucket from the transactions ledger (source of truth).
      • Set admin.wallet_balance = sum(buckets) so the headline matches.

    Returns a before/after diff so admin can see what was corrected.
    """
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not a:
        raise HTTPException(status_code=404, detail="Admin not found")

    before = {b: float((a.get("wallet_buckets") or {}).get(b) or 0) for b in SYSTEM_WALLET_BUCKETS}
    before_total = float(a.get("wallet_balance") or 0)

    # Sum admin txns by (bucket → txn types) defined in _BUCKET_TXN_TYPES.
    # For buckets that don't have explicit types in that map yet (none
    # currently), recomputed value is left at 0 — admin can still see the
    # diff and decide whether to manually adjust.
    after: Dict[str, float] = {b: 0.0 for b in SYSTEM_WALLET_BUCKETS}
    for bucket, types in _BUCKET_TXN_TYPES.items():
        agg = await db.transactions.aggregate([
            {"$match": {
                "user_id": a["id"],
                "type": {"$in": types},
                "status": {"$in": ["success", "paid", "credited", "approved"]},
            }},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        after[bucket] = round(float(agg[0]["total"] if agg else 0), 2)

    after_total = round(sum(after.values()), 2)

    # Apply
    await db.users.update_one(
        {"id": a["id"]},
        {"$set": {
            "wallet_buckets": after,
            "wallet_balance": after_total,
        }},
    )
    await _audit_log(admin, "system_wallet.reconcile", "wallet", a["id"], {
        "before": {**before, "wallet_balance": before_total},
        "after": {**after, "wallet_balance": after_total},
    })

    # Build a per-bucket diff for the response (positive = bucket increased,
    # negative = decreased).
    diff = {b: round(after[b] - before[b], 2) for b in SYSTEM_WALLET_BUCKETS}
    diff["wallet_balance"] = round(after_total - before_total, 2)
    return {
        "ok": True,
        "before": {**before, "wallet_balance": before_total},
        "after":  {**after,  "wallet_balance": after_total},
        "diff":   diff,
    }


# Bucket → transaction type(s) mapping. Drives the per-bucket detail view in
# the frontend System Wallet UI AND the reconcile endpoint (which recomputes
# each bucket from its ledger types). Keep this in sync whenever new admin
# income types are added so the books always balance after a reconcile.
_BUCKET_TXN_TYPES: Dict[str, List[str]] = {
    # Each bucket's recompute = sum(amount) across these txn types. Include
    # debit-emitting types (e.g. `l1_funding`) INSIDE the bucket they debit
    # so reconcile produces the correct post-debit balance.
    #
    # `drift_correction` txns are intentionally EXCLUDED here — they are
    # pure audit entries that represent the auto-heal action itself, NOT
    # a separate debit. Including them would double-count after reconcile.
    "direct_signup":       ["direct_signup_credit"],
    "fee_residual":        ["fee_residual", "l1_funding"],
    "referral_commission": ["referral_payout", "cascade_overflow"],
    "gst_collected":       ["gst_collected"],
    # admin_credit/admin_debit are signed (positive=credit, negative=debit)
    # so summing them naturally captures both deposits and admin transfers
    # out — keeping the bucket reconciled with reality.
    "direct_added":        ["system_deposit", "admin_credit", "admin_debit"],
    "service_margin":      ["service_margin", "service_commission", "service_commission_reversal"],
    "shopping_margin":     ["shopping_margin", "shop_commission", "shop_commission_reversal"],
}


@api_router.get("/admin/system-wallet/transactions")
async def get_system_wallet_transactions(
    bucket: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
    limit: int = 200,
):
    """List admin transactions that contributed to a given system-wallet bucket.

    Powers the per-tab detail view (Direct Joins, Referral Commission, GST
    Collected, etc.) in /admin/system-wallet. Each row has the source user
    info plus the original gross / GST / net split where applicable.

    Special virtual bucket: `user_payouts` — combined view of every L1..L10
    referral payout credited to USER wallets PLUS every withdrawal settled
    (with UTR / payout ref). Used by the "Total Paid to Users" drilldown
    on the System Wallet treasury screen.
    """
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not a:
        raise HTTPException(status_code=404, detail="Admin not found")

    limit = max(10, min(int(limit or 200), 1000))

    # ─── Virtual: admin_wallet (NOT a real bucket; combines 4 sources) ─
    # The redesigned Treasury UI rolls direct_signup + fee_residual +
    # referral_commission + gst_collected into a single "Admin Wallet"
    # row. The drilldown surfaces ALL of those underlying txns together
    # so each one is auditable with its remarks / gross-GST-net split.
    if bucket == "admin_wallet":
        types = (
            _BUCKET_TXN_TYPES["direct_signup"]
            + _BUCKET_TXN_TYPES["fee_residual"]
            + _BUCKET_TXN_TYPES["referral_commission"]
            + _BUCKET_TXN_TYPES["gst_collected"]
            + ["l1_funding"]  # debits (negative amounts) that explain admin bucket drains
        )
        rows = await db.transactions.find(
            {"user_id": a["id"], "type": {"$in": list(set(types))}, "status": "success"},
            {"_id": 0, "password_hash": 0},
        ).sort("created_at", -1).limit(limit).to_list(limit)
        subtotal = round(sum(float(r.get("amount") or 0) for r in rows), 2)
        return {"bucket": bucket, "subtotal": subtotal, "count": len(rows), "items": rows}

    # ─── Virtual: user_payouts (NOT a per-admin bucket) ──────────────────
    if bucket == "user_payouts":
        # All referral payouts credited to NON-admin users + all settled
        # withdrawals, newest first. Joined with user email/name for display.
        cursor = db.transactions.find(
            {
                "$or": [
                    {"type": "referral_payout", "user_id": {"$ne": a["id"]}, "status": "success"},
                    {"type": "withdrawal", "status": "success"},
                ],
            },
            {"_id": 0, "password_hash": 0},
        ).sort("created_at", -1).limit(limit)
        rows: List[Dict[str, Any]] = await cursor.to_list(limit)
        # Enrich with user email/name (best-effort, batched)
        uids = list({r.get("user_id") for r in rows if r.get("user_id")})
        users_map: Dict[str, Dict[str, Any]] = {}
        if uids:
            async for u in db.users.find(
                {"id": {"$in": uids}}, {"_id": 0, "id": 1, "email": 1, "name": 1, "phone": 1},
            ):
                users_map[u["id"]] = u
        for r in rows:
            u = users_map.get(r.get("user_id") or "")
            if u:
                r["recipient_email"] = u.get("email")
                r["recipient_name"] = u.get("name")
                r["recipient_phone"] = u.get("phone")
        subtotal = round(sum(float(r.get("amount") or 0) for r in rows), 2)
        return {"bucket": bucket, "subtotal": subtotal, "count": len(rows), "items": rows}

    types = _BUCKET_TXN_TYPES.get(bucket)
    if not types:
        raise HTTPException(status_code=400, detail=f"Unknown bucket: {bucket}")
    rows = await db.transactions.find(
        {"user_id": a["id"], "type": {"$in": types}, "status": "success"},
        {"_id": 0, "password_hash": 0},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    # Subtotal of the visible rows (informational; differs from bucket total
    # if more rows exist beyond the limit).
    subtotal = round(sum(float(r.get("amount") or 0) for r in rows), 2)
    return {"bucket": bucket, "subtotal": subtotal, "count": len(rows), "items": rows}


@api_router.post("/admin/system-wallet/deposit")
async def system_wallet_deposit(payload: SystemWalletDeposit, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance"))):
    """Manual UTR deposit into the system wallet. Once recorded, the
    direct_added bucket grows and admin/finance can credit user wallets
    from this bucket only."""
    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not a:
        raise HTTPException(status_code=404, detail="Admin not found")
    # Idempotency: same UTR cannot be re-deposited.
    dup = await db.system_wallet_deposits.find_one({"utr": payload.utr})
    if dup:
        raise HTTPException(status_code=400, detail=f"UTR {payload.utr} already recorded")
    ts = now_utc().isoformat()
    dep_id = str(uuid.uuid4())
    await db.system_wallet_deposits.insert_one({
        "id": dep_id,
        "amount": float(payload.amount),
        "utr": payload.utr.strip(),
        "bank_ref": (payload.bank_ref or "").strip() or None,
        "remarks": (payload.remarks or "").strip() or None,
        "deposited_by": admin["id"],
        "deposited_by_email": admin.get("email"),
        "created_at": ts,
    })
    await credit_admin_bucket("direct_added", float(payload.amount), also_total_earned=False)
    try:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": a["id"],
            "type": "system_deposit",
            "amount": float(payload.amount),
            "status": "success",
            # Use the admin's typed remarks verbatim if present; otherwise a
            # short auto-generated label. Either way the UTR/amount remain on
            # separate fields so they're not swallowed by free-text remarks.
            "description": (payload.remarks.strip() if (payload.remarks and payload.remarks.strip()) else f"System wallet top-up · UTR {payload.utr}"),
            "remarks": (payload.remarks or "").strip() or None,
            "reference_number": payload.utr,
            "deposit_id": dep_id,
            "created_at": ts,
        })
    except DuplicateKeyError:
        pass
    await _audit_log(admin, "system_wallet.deposit", "deposit", dep_id, {"amount": payload.amount, "utr": payload.utr})
    return {"ok": True, "deposit_id": dep_id}


@api_router.post("/admin/users/{user_id}/wallet")
async def admin_wallet_adjust(user_id: str, payload: WalletAdjust, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance"))):
    if payload.type not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="type must be credit or debit")
    if not (payload.reason or "").strip():
        raise HTTPException(status_code=400, detail="Remarks are required for every wallet adjustment")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    delta = payload.amount if payload.type == "credit" else -payload.amount
    if delta < 0 and target.get("wallet_balance", 0) + delta < 0:
        raise HTTPException(status_code=400, detail="Cannot debit beyond available balance")

    # CREDIT path: must come from the system wallet's direct_added bucket.
    if payload.type == "credit":
        ok = await debit_admin_bucket("direct_added", payload.amount)
        if not ok:
            raise HTTPException(status_code=400, detail="Insufficient Direct-Added funds in system wallet. Please deposit first.")

    # DEBIT path: return funds to direct_added bucket so they're re-spendable.
    if payload.type == "debit":
        await credit_admin_bucket("direct_added", payload.amount, also_total_earned=False)

    inc = {"wallet_balance": delta}
    if payload.type == "credit":
        inc["total_earned"] = payload.amount
    await db.users.update_one({"id": user_id}, {"$inc": inc})
    txn_id = str(uuid.uuid4())
    await db.transactions.insert_one({
        "id": txn_id,
        "user_id": user_id,
        "type": "admin_credit" if payload.type == "credit" else "admin_debit",
        "amount": delta,
        "status": "success",
        # Use the admin's typed remarks verbatim — no auto-prefix. The type
        # itself is already conveyed by `type` and shown as a separate label.
        "description": payload.reason.strip(),
        "reference_number": txn_id[:8].upper(),
        "from_admin_id": admin["id"],
        "from_admin_email": admin.get("email"),
        "remarks": payload.reason.strip(),
        "created_at": now_utc().isoformat(),
    })
    # Mirror txn on ADMIN's record so the system-wallet reconcile (which
    # aggregates by admin.id) can see the direct_added bucket movement. The
    # buckets were already adjusted via debit/credit_admin_bucket above; this
    # mirror is purely for ledger-completeness so reconcile doesn't undo it.
    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if admin_doc:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": admin_doc["id"],
            # On user CREDIT (money out of admin's direct_added → into user wallet),
            # admin's bucket DECREASES, so we write a negative-amount admin_credit
            # entry. On user DEBIT (money back into admin), admin's bucket
            # INCREASES, so we write a positive-amount admin_debit. Sign matches
            # what reconcile expects when summing this bucket.
            "type": "admin_credit" if payload.type == "credit" else "admin_debit",
            "amount": -delta,  # opposite sign — money moved AWAY from admin on credit, BACK on debit
            "status": "success",
            "description": (
                f"Transfer {'to' if payload.type == 'credit' else 'from'} "
                f"{(target.get('name') or '')[:30]} · {payload.reason.strip()}"
            ),
            "linked_txn_id": txn_id,
            "linked_user_id": user_id,
            "linked_user_email": target.get("email"),
            "created_at": now_utc().isoformat(),
        })
    await _create_notification(user_id, "wallet", f"Wallet {payload.type}ed by ₹{int(payload.amount)}", payload.reason.strip())
    await _audit_log(admin, f"wallet.{payload.type}", "user", user_id, {"amount": payload.amount, "reason": payload.reason})
    return {"ok": True, "transaction_id": txn_id}


@api_router.post("/admin/users/{user_id}/wallet/freeze")
async def admin_wallet_freeze(user_id: str, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_state = not target.get("wallet_frozen", False)
    await db.users.update_one({"id": user_id}, {"$set": {"wallet_frozen": new_state}})
    await _audit_log(admin, "wallet.freeze" if new_state else "wallet.unfreeze", "user", user_id)
    await _create_notification(
        user_id, "wallet",
        "Wallet frozen" if new_state else "Wallet unfrozen",
        "Your wallet has been frozen by admin." if new_state else "Your wallet is active again.",
    )
    return {"ok": True, "frozen": new_state}


# ------------------ Phase 1: Transactions admin actions ------------------
@api_router.get("/admin/transactions/filter")
async def admin_filter_transactions(
    _: Dict[str, Any] = Depends(require_admin),
    type: Optional[str] = None,
    status: Optional[str] = None,
    user_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
):
    query: Dict[str, Any] = {}
    if type:
        query["type"] = type
    if status:
        query["status"] = status
    if user_id:
        query["user_id"] = user_id
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        query["created_at"] = rng
    if q:
        query["description"] = {"$regex": q, "$options": "i"}
    items = await db.transactions.find(query, {"_id": 0}).sort("created_at", -1).limit(2000).to_list(2000)
    return items


@api_router.patch("/admin/transactions/{txn_id}")
async def admin_update_txn_status(txn_id: str, payload: TxnStatusUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    txn = await db.transactions.find_one({"id": txn_id})
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await db.transactions.update_one({"id": txn_id}, {"$set": {"status": payload.status}})
    await _audit_log(admin, "txn.status", "transaction", txn_id, {"status": payload.status})
    return {"ok": True}


@api_router.post("/admin/transactions/{txn_id}/refund")
async def admin_refund_txn(txn_id: str, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    txn = await db.transactions.find_one({"id": txn_id})
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if txn.get("status") == "refunded":
        raise HTTPException(status_code=400, detail="Already refunded")
    refund_amount = abs(txn["amount"])
    await db.users.update_one({"id": txn["user_id"]}, {"$inc": {"wallet_balance": refund_amount}})
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": txn["user_id"],
        "type": "refund",
        "amount": refund_amount,
        "status": "credited",
        "description": f"Refund for txn #{txn_id[:8]}",
        "ref_txn_id": txn_id,
        "created_at": now_utc().isoformat(),
    })
    await db.transactions.update_one({"id": txn_id}, {"$set": {"status": "refunded"}})
    await _create_notification(txn["user_id"], "wallet", "Refund processed", f"₹{int(refund_amount)} has been refunded to your wallet.")
    await _audit_log(admin, "txn.refund", "transaction", txn_id, {"amount": refund_amount})
    return {"ok": True}


# ------------------ Phase 1: Orders Admin ------------------
@api_router.get("/admin/orders")
async def admin_list_orders(_: Dict[str, Any] = Depends(require_admin), status: Optional[str] = None):
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    items = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).limit(1000).to_list(1000)
    return items


@api_router.patch("/admin/orders/{order_id}/status")
async def admin_update_order_status(order_id: str, payload: OrderStatusUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    if payload.status not in ("placed", "shipped", "delivered", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    prev_status = order.get("status")
    await db.orders.update_one({"id": order_id}, {"$set": {"status": payload.status}})

    # ── COD delivery → settle commission + vendor wallets ────────────────
    # COD orders DEFER the admin commission credit and vendor wallet credit
    # until delivery is confirmed (cash actually collected). This keeps the
    # ledger honest: admin only counts money that was truly earned.
    paid_via = order.get("paid_via") or "wallet"
    items = order.get("items") or []
    if (payload.status == "delivered"
            and prev_status != "delivered"
            and paid_via == "cod"
            and not order.get("commission_settled")):
        # 1) Mark order paid + settled so we never double-credit
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"payment_status": "paid", "commission_settled": True}},
        )
        # 2) Admin platform commission
        platform_total = round(sum(float(it.get("platform_share") or 0) for it in items), 2)
        if platform_total > 0:
            admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
            if admin_doc:
                await credit_admin_bucket("shopping_margin", platform_total, also_total_earned=True)
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_doc["id"],
                    "type": "shop_commission",
                    "amount": platform_total,
                    "status": "success",
                    "description": f"Shop margin from COD order #{order_id[:8]} (settled on delivery)",
                    "order_id": order_id,
                    "created_at": now_utc().isoformat(),
                })
        # 3) Vendor share credits
        vendor_payouts: Dict[str, float] = {}
        for it in items:
            vid = it.get("vendor_id")
            vshare = float(it.get("vendor_share") or 0)
            if vid and vshare > 0:
                vendor_payouts[vid] = vendor_payouts.get(vid, 0) + vshare
        for vid, amt in vendor_payouts.items():
            amt = round(amt, 2)
            await db.users.update_one({"id": vid}, {"$inc": {"wallet_balance": amt}})
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": vid,
                "type": "vendor_sale",
                "amount": amt,
                "status": "success",
                "description": f"Vendor share — COD order #{order_id[:8]} delivered",
                "order_id": order_id,
                "created_at": now_utc().isoformat(),
            })

    if payload.status == "cancelled" and prev_status != "cancelled":
        order_total = float(order.get("total") or 0)

        # ── Refund the buyer ─────────────────────────────────────────────
        # Wallet-paid orders: credit the wallet back.
        # COD orders: no actual cash was held in wallet, so we DO NOT credit
        # the wallet — just mark the order cancelled.
        if paid_via == "wallet":
            await db.users.update_one({"id": order["user_id"]}, {"$inc": {"wallet_balance": order_total}})
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": order["user_id"],
                "type": "refund",
                "amount": order_total,
                "status": "credited",
                "description": f"Order #{order_id[:8]} cancelled — refund",
                "order_id": order_id,
                "created_at": now_utc().isoformat(),
            })

        # ── Reverse the LEDGER credits booked at order placement ─────────
        # For wallet-paid orders we DID credit shop_commission + vendor_share
        # at placement, so we must reverse both on cancellation. For COD
        # orders nothing was credited yet (deferred to delivery) so there is
        # nothing to reverse — unless the COD was already delivered and
        # later cancelled, in which case order.commission_settled is True
        # and we reverse the same way.
        should_reverse_commission = (
            paid_via == "wallet"
            or (paid_via == "cod" and order.get("commission_settled"))
        )
        if should_reverse_commission:
            platform_total = round(sum(float(it.get("platform_share") or 0) for it in items), 2)
            if platform_total > 0:
                admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
                if admin_doc:
                    await credit_admin_bucket("shopping_margin", -platform_total, also_total_earned=True)
                    await db.transactions.insert_one({
                        "id": str(uuid.uuid4()),
                        "user_id": admin_doc["id"],
                        "type": "shop_commission_reversal",
                        "amount": -platform_total,
                        "status": "success",
                        "description": f"Reversal — order #{order_id[:8]} cancelled",
                        "order_id": order_id,
                        "created_at": now_utc().isoformat(),
                    })
            # Reverse vendor credits
            vendor_payouts2: Dict[str, float] = {}
            for it in items:
                vid = it.get("vendor_id")
                vshare = float(it.get("vendor_share") or 0)
                if vid and vshare > 0:
                    vendor_payouts2[vid] = vendor_payouts2.get(vid, 0) + vshare
            for vid, amt in vendor_payouts2.items():
                amt = round(amt, 2)
                await db.users.update_one({"id": vid}, {"$inc": {"wallet_balance": -amt}})
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": vid,
                    "type": "vendor_sale_reversal",
                    "amount": -amt,
                    "status": "success",
                    "description": f"Vendor share reversed — order #{order_id[:8]} cancelled",
                    "order_id": order_id,
                    "created_at": now_utc().isoformat(),
                })

        await _create_notification(
            order["user_id"], "order", "Order cancelled",
            f"₹{int(order_total)} refunded to your wallet." if paid_via == "wallet" else "Your order was cancelled.",
        )
    elif payload.status != "cancelled":
        await _create_notification(order["user_id"], "order", f"Order {payload.status}", f"Your order is now {payload.status}.")
    await _audit_log(admin, "order.status", "order", order_id, {"status": payload.status, "prev": prev_status})
    return {"ok": True}


@api_router.post("/admin/system-wallet/cleanup-legacy-refunds")
async def admin_cleanup_legacy_refunds(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    """One-shot cleanup for the buggy cancel-refund flow that pre-dated the
    proper double-entry handling.

    Symptoms it fixes:
      • COD orders were credited admin's shop_commission AT PLACEMENT
        (before cash was collected). When cancelled, the bogus refund
        was deposited into the user's wallet too, doubling the drift.
      • Wallet orders never reversed admin's commission on cancel.

    Strategy (idempotent — flagged via order.legacy_drift_cleaned):
      1. For every cancelled order without a *_reversal txn:
           a) reverse the admin's `shop_commission` bucket
           b) reverse any vendor_sale credits
           c) for COD-paid orders: the user got a phantom refund (no real
              money flowed in or out) — debit the user's wallet back IF
              they still have at least that much balance. Otherwise log a
              `legacy_drift_residual` audit note (manual admin write-off).
    """
    settings = await get_settings()  # noqa: F841 (kept for parity)
    cancelled = await db.orders.find({"status": "cancelled"}).to_list(10000)
    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin_doc:
        raise HTTPException(status_code=500, detail="Admin user missing")
    report: List[Dict[str, Any]] = []

    for order in cancelled:
        if order.get("legacy_drift_cleaned"):
            continue
        items = order.get("items") or []
        order_id = order["id"]
        paid_via = order.get("paid_via") or "wallet"
        platform_total = round(sum(float(it.get("platform_share") or 0) for it in items), 2)

        # Already-reversed orders (new flow handled them) — just mark cleaned
        already_rev = await db.transactions.find_one({
            "type": "shop_commission_reversal",
            "order_id": order_id,
        })
        if already_rev:
            await db.orders.update_one({"id": order_id}, {"$set": {"legacy_drift_cleaned": True}})
            continue

        actions: List[str] = []

        # (a) reverse admin shop_commission for orders that actually got it
        # COD pre-fix DID credit at placement — same as wallet
        had_commission_credit = await db.transactions.find_one({
            "type": "shop_commission", "order_id": order_id,
        })
        if had_commission_credit and platform_total > 0:
            await credit_admin_bucket("shopping_margin", -platform_total, also_total_earned=True)
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": admin_doc["id"],
                "type": "shop_commission_reversal",
                "amount": -platform_total,
                "status": "success",
                "description": f"Legacy cleanup — reversal for cancelled order #{order_id[:8]}",
                "order_id": order_id,
                "created_at": now_utc().isoformat(),
            })
            actions.append(f"admin -{platform_total}")

        # (b) reverse vendor_sale credits
        vendor_payouts3: Dict[str, float] = {}
        for it in items:
            vid = it.get("vendor_id")
            vshare = float(it.get("vendor_share") or 0)
            if vid and vshare > 0:
                vendor_payouts3[vid] = vendor_payouts3.get(vid, 0) + vshare
        for vid, amt in vendor_payouts3.items():
            had_vendor_credit = await db.transactions.find_one({
                "user_id": vid, "type": "vendor_sale", "order_id": order_id,
            })
            if had_vendor_credit:
                amt = round(amt, 2)
                await db.users.update_one({"id": vid}, {"$inc": {"wallet_balance": -amt}})
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": vid,
                    "type": "vendor_sale_reversal",
                    "amount": -amt,
                    "status": "success",
                    "description": f"Legacy cleanup — reversal for cancelled order #{order_id[:8]}",
                    "order_id": order_id,
                    "created_at": now_utc().isoformat(),
                })
                actions.append(f"vendor {vid[:8]} -{amt}")

        # (c) for COD-paid orders: phantom refund — debit user back
        if paid_via == "cod":
            order_total = float(order.get("total") or 0)
            phantom_refund_txn = await db.transactions.find_one({
                "type": "refund", "order_id": order_id,
            }) or await db.transactions.find_one({
                "type": "refund", "user_id": order["user_id"],
                "description": {"$regex": order_id[:8]},
            })
            if phantom_refund_txn:
                u = await db.users.find_one({"id": order["user_id"]})
                bal = float((u or {}).get("wallet_balance") or 0)
                if bal >= order_total:
                    await db.users.update_one(
                        {"id": order["user_id"]},
                        {"$inc": {"wallet_balance": -order_total}},
                    )
                    await db.transactions.insert_one({
                        "id": str(uuid.uuid4()),
                        "user_id": order["user_id"],
                        "type": "refund_reversal",
                        "amount": -order_total,
                        "status": "success",
                        "description": f"Legacy cleanup — phantom COD refund reversed for order #{order_id[:8]}",
                        "order_id": order_id,
                        "created_at": now_utc().isoformat(),
                    })
                    actions.append(f"user {order['user_id'][:8]} -{order_total} (phantom refund)")
                else:
                    actions.append(
                        f"user {order['user_id'][:8]} residual ₹{order_total - bal:.2f} (balance too low)"
                    )

        await db.orders.update_one({"id": order_id}, {"$set": {"legacy_drift_cleaned": True}})
        report.append({"order_id": order_id, "paid_via": paid_via, "actions": actions})

    await _audit_log(admin, "system_wallet.cleanup_legacy_refunds", "wallet", admin_doc["id"], {
        "orders_processed": len(report),
    })

    # ── Phase 2: backfill fee-residuals for already-approved with-ref users ──
    # For every with-ref signup that was approved BEFORE the residual safety
    # net existed, compute (fee_paid − cascade_credited) and route any
    # positive residual to admin's direct_signup bucket. Idempotent via
    # users.fee_residual_backfilled flag.
    settings = await get_settings()
    fee = float(settings.get("registration_fee") or 0)
    residual_report: List[Dict[str, Any]] = []
    legacy_users = await db.users.find({
        "role": "user",
        "registration_paid": True,
        "no_referral_signup": {"$ne": True},
        "fee_residual_backfilled": {"$ne": True},
    }, {"_id": 0, "id": 1, "name": 1, "created_at": 1}).to_list(10000)

    for u in legacy_users:
        # Confirm the fee was actually paid (txn exists)
        fee_paid_txn = await db.transactions.find_one({
            "user_id": u["id"],
            "type": "registration_fee",
            "status": {"$in": ["paid", "success", "approved"]},
        })
        if not fee_paid_txn:
            # No fee txn → seed user without a real fee → skip
            await db.users.update_one({"id": u["id"]}, {"$set": {"fee_residual_backfilled": True}})
            continue

        # Sum the cascade credits (referral_payout gross + cascade_overflow)
        # that were triggered by this user's signup
        credited = 0.0
        async for tx in db.transactions.find({
            "$or": [
                {"related_signup_id": u["id"]},
                {
                    "source_user_name": u["name"],
                    "type": {"$in": ["referral_payout", "cascade_overflow", "gst_collected"]},
                    "status": "success",
                },
            ],
        }, {"_id": 0, "type": 1, "amount": 1, "gross_amount": 1}):
            if tx.get("type") == "referral_payout":
                credited += float(tx.get("gross_amount") or tx.get("amount") or 0)
            elif tx.get("type") == "cascade_overflow":
                credited += float(tx.get("amount") or 0)

        residual = round(fee - credited, 2)
        # Defensive: skip if a fee-residual credit ALREADY exists for this
        # signup (regardless of when written) — prevents double-credit if
        # this endpoint is called twice or if the new signup flow already
        # wrote the residual. Match both legacy (direct_signup_credit with
        # "Fee residual" desc) and new (`fee_residual`) txn types.
        existing_residual = await db.transactions.find_one({
            "$or": [
                {"type": "fee_residual", "related_signup_id": u["id"]},
                {
                    "type": "direct_signup_credit",
                    "related_signup_id": u["id"],
                    "description": {"$regex": "[Ff]ee residual"},
                },
            ],
        })
        if residual > 0.01 and not existing_residual:
            await credit_admin_bucket("fee_residual", residual, also_total_earned=True)
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": admin_doc["id"],
                "type": "fee_residual",
                "amount": residual,
                "status": "success",
                "description": (
                    f"Legacy fee residual ₹{residual} from {u['name']} "
                    f"(₹{int(fee)} fee − ₹{int(credited)} cascade)"
                ),
                "related_signup_id": u["id"],
                "source_user_name": u["name"],
                "created_at": now_utc().isoformat(),
            })
            residual_report.append({
                "user_id": u["id"], "name": u["name"], "residual": residual,
            })
        await db.users.update_one({"id": u["id"]}, {"$set": {"fee_residual_backfilled": True}})

    return {
        "ok": True,
        "orders_processed": len(report),
        "details": report,
        "fee_residuals_backfilled": len(residual_report),
        "residual_details": residual_report,
    }


# ------------------ Phase 1: Audit Log ------------------
@api_router.get("/admin/audit-logs")
async def admin_audit_logs(_: Dict[str, Any] = Depends(require_admin), limit: int = 200):
    items = await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return items


# ------------------ Security events (auth failures, IP anomalies) ------------------
@api_router.get("/admin/security-events")
async def admin_security_events(
    _: Dict[str, Any] = Depends(require_admin),
    limit: int = 200,
    action: Optional[str] = None,
    email: Optional[str] = None,
    severity: Optional[str] = None,
):
    """Returns the recent security event stream sorted newest-first.

    Optional filters:
      • action=auth.failed_login   → only failed login attempts.
      • action=auth.multi_ip_login → only multi-IP anomalies.
      • email=foo@bar              → events for one account.
      • severity=warning|info|critical
    """
    q: Dict[str, Any] = {}
    if action:
        q["action"] = action
    if email:
        q["email"] = email.lower().strip()
    if severity:
        q["severity"] = severity
    limit = max(1, min(limit, 1000))
    items = await db.security_events.find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items, "count": len(items)}


# ------------------ Phase 1: Analytics ------------------
@api_router.get("/admin/analytics")
async def admin_analytics(_: Dict[str, Any] = Depends(require_admin), days: int = 30):
    today = now_utc().date()

    today_iso = today.isoformat()
    month_start = today.replace(day=1).isoformat()
    new_users_today = await db.users.count_documents({"role": "user", "created_at": {"$gte": today_iso}})
    new_users_month = await db.users.count_documents({"role": "user", "created_at": {"$gte": month_start}})
    paid_users_today = await db.users.count_documents({"role": "user", "registration_paid": True, "created_at": {"$gte": today_iso}})

    success_txns = await db.transactions.count_documents({"status": {"$in": ["paid", "credited", "approved"]}})
    failed_txns = await db.transactions.count_documents({"status": "failed"})
    pending_txns = await db.transactions.count_documents({"status": "pending"})
    refunded_txns = await db.transactions.count_documents({"status": "refunded"})

    bal_agg = await db.users.aggregate([
        {"$match": {"role": "user"}},
        {"$group": {"_id": None, "total": {"$sum": "$wallet_balance"}}},
    ]).to_list(1)
    system_wallet = bal_agg[0]["total"] if bal_agg else 0

    rev_agg = await db.transactions.aggregate([
        {"$match": {"type": "registration_fee", "status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_revenue = rev_agg[0]["total"] if rev_agg else 0

    payout_agg = await db.transactions.aggregate([
        {"$match": {"type": "referral_payout"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_payouts = payout_agg[0]["total"] if payout_agg else 0

    orders_count = await db.orders.count_documents({})
    orders_revenue_agg = await db.orders.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$total"}}},
    ]).to_list(1)
    orders_revenue = orders_revenue_agg[0]["total"] if orders_revenue_agg else 0

    daily_users = []
    daily_revenue = []
    daily_txns = []
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i))
        d_start = d.isoformat()
        d_end = (d + timedelta(days=1)).isoformat()
        u = await db.users.count_documents({"role": "user", "created_at": {"$gte": d_start, "$lt": d_end}})
        r_agg = await db.transactions.aggregate([
            {"$match": {"type": "registration_fee", "created_at": {"$gte": d_start, "$lt": d_end}}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        r = r_agg[0]["total"] if r_agg else 0
        t = await db.transactions.count_documents({"created_at": {"$gte": d_start, "$lt": d_end}})
        daily_users.append({"date": d_start, "value": u})
        daily_revenue.append({"date": d_start, "value": r})
        daily_txns.append({"date": d_start, "value": t})

    return {
        "kpis": {
            "new_users_today": new_users_today,
            "new_users_month": new_users_month,
            "paid_users_today": paid_users_today,
            "total_revenue": total_revenue,
            "system_wallet": system_wallet,
            "total_payouts": total_payouts,
            "success_txns": success_txns,
            "failed_txns": failed_txns,
            "pending_txns": pending_txns,
            "refunded_txns": refunded_txns,
            "orders_count": orders_count,
            "orders_revenue": orders_revenue,
        },
        "daily_users": daily_users,
        "daily_revenue": daily_revenue,
        "daily_txns": daily_txns,
    }


# ------------------ Phase 1: CSV Export ------------------
def _to_csv(rows: List[Dict[str, Any]], fields: List[str]) -> str:
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for r in rows:
        writer.writerow([str(r.get(f, "")) for f in fields])
    return buf.getvalue()


@api_router.get("/admin/export/{kind}")
async def admin_export(kind: str, admin: Dict[str, Any] = Depends(require_admin)):
    if kind == "users":
        rows = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(10000)
        fields = ["id", "name", "email", "phone", "role", "referral_code", "referred_by", "wallet_balance", "total_earned", "registration_paid", "is_blocked", "kyc_status", "created_at"]
    elif kind == "transactions":
        rows = await db.transactions.find({}, {"_id": 0}).to_list(10000)
        fields = ["id", "user_id", "type", "amount", "status", "description", "created_at"]
    elif kind == "withdrawals":
        rows = await db.withdrawals.find({}, {"_id": 0}).to_list(10000)
        fields = ["id", "user_id", "user_email", "amount", "status", "upi_id", "bank_account", "ifsc", "created_at", "processed_at"]
    elif kind == "orders":
        rows = await db.orders.find({}, {"_id": 0}).to_list(10000)
        fields = ["id", "user_id", "total", "status", "paid_via", "created_at"]
    else:
        raise HTTPException(status_code=400, detail="Invalid export kind")
    csv_data = _to_csv(rows, fields)
    await _audit_log(admin, "export", kind, "", {"rows": len(rows)})
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={kind}.csv"},
    )


# ------------------ Health ------------------
@api_router.get("/")
async def root():
    return {"message": "Referral & E-commerce API", "ok": True}


# ------------------ Startup ------------------
async def seed_admin():
    existing = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not existing:
        # Try to claim "EARN" as the admin's referral code; fall back to
        # legacy "ADMIN001" then a random one if both are taken.
        admin_code = "EARN"
        for candidate in ("EARN", "ADMIN001"):
            clash = await db.users.find_one({"referral_code": candidate})
            if not clash:
                admin_code = candidate
                break
        else:
            while True:
                admin_code = gen_referral_code()
                if not await db.users.find_one({"referral_code": admin_code}):
                    break
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "name": "Admin",
            "email": ADMIN_EMAIL.lower(),
            "password_hash": hash_password(ADMIN_PASSWORD),
            "phone": None,
            "role": "admin",
            "admin_role": "super_admin",
            "referral_code": admin_code,
            "referred_by": None,
            "sponsor_id": None,
            "wallet_balance": 0.0,
            "total_earned": 0.0,
            "registration_paid": True,
            "direct_referrals_count": 0,
            "payouts_received": 0,
            "upi_id": None,
            "bank_account": None,
            "ifsc": None,
            "account_holder": None,
            "is_blocked": False,
            "block_reason": None,
            "wallet_frozen": False,
            "kyc_status": "approved",
            "kyc_full_name": "Admin",
            "kyc_aadhaar": None,
            "kyc_pan": None,
            "kyc_submitted_at": None,
            "kyc_reviewed_at": None,
            "kyc_reject_reason": None,
            "created_at": now_utc().isoformat(),
        })
        logger.info(f"Admin user seeded with referral_code={admin_code}")
    else:
        # Refresh password if env changed
        if not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
            await db.users.update_one(
                {"email": ADMIN_EMAIL.lower()},
                {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}},
            )
        # Backfill admin_role for legacy admin
        if not existing.get("admin_role"):
            await db.users.update_one(
                {"email": ADMIN_EMAIL.lower()},
                {"$set": {"admin_role": "super_admin"}},
            )
        # Migrate admin's referral_code to "EARN" if it isn't already, and "EARN" is free.
        if existing.get("referral_code") != "EARN":
            clash = await db.users.find_one({"referral_code": "EARN", "email": {"$ne": ADMIN_EMAIL.lower()}})
            if not clash:
                await db.users.update_one(
                    {"email": ADMIN_EMAIL.lower()},
                    {"$set": {"referral_code": "EARN"}},
                )
                # Cascade-update existing users who were referred via the old code
                old_code = existing.get("referral_code")
                if old_code:
                    await db.users.update_many(
                        {"referred_by": old_code},
                        {"$set": {"referred_by": "EARN"}},
                    )
                logger.info(f"Admin referral_code migrated from {old_code} → EARN")
        # Backfill system-wallet buckets on existing admin if missing
        if not isinstance(existing.get("wallet_buckets"), dict):
            current_balance = float(existing.get("wallet_balance") or 0)
            await db.users.update_one(
                {"email": ADMIN_EMAIL.lower()},
                {"$set": {"wallet_buckets": {
                    # Preserve existing balance under referral_commission since
                    # historically that's where most admin earnings came from.
                    "referral_commission": current_balance,
                    "direct_added": 0.0,
                    "service_margin": 0.0,
                    "shopping_margin": 0.0,
                }}},
            )


# ============================================================
# SYSTEM WALLET — admin's wallet broken down into 4 categorised buckets
# ============================================================
SYSTEM_WALLET_BUCKETS = ("referral_commission", "direct_signup", "fee_residual", "direct_added", "service_margin", "shopping_margin", "gst_collected")


async def credit_admin_bucket(bucket: str, amount: float, *, also_total_earned: bool = True):
    """Credit (or reverse) a specific bucket of the admin's system wallet AND
    the rolled-up wallet_balance. Use this everywhere admin earns money so
    the dashboard shows the right category breakdown.

    bucket ∈ SYSTEM_WALLET_BUCKETS

    Note: this function ALLOWS negative `amount` so reversal sites (cancelled
    orders, commission reversals, etc.) can debit the bucket atomically via
    the same `$inc` path. Only an exact-zero amount is a no-op.
    """
    if bucket not in SYSTEM_WALLET_BUCKETS:
        raise ValueError(f"Unknown bucket: {bucket}")
    if amount == 0:
        return
    admin = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin:
        return
    update: Dict[str, Any] = {f"wallet_buckets.{bucket}": amount, "wallet_balance": amount}
    if also_total_earned:
        update["total_earned"] = amount
    await db.users.update_one({"id": admin["id"]}, {"$inc": update})


async def debit_admin_bucket(bucket: str, amount: float) -> bool:
    """Debit a specific bucket and the rolled-up balance. Returns False (no-op) if
    insufficient balance in that bucket. Atomic via filter on bucket value.
    """
    if bucket not in SYSTEM_WALLET_BUCKETS:
        raise ValueError(f"Unknown bucket: {bucket}")
    admin = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin:
        return False
    res = await db.users.update_one(
        {"id": admin["id"], f"wallet_buckets.{bucket}": {"$gte": amount}},
        {"$inc": {f"wallet_buckets.{bucket}": -amount, "wallet_balance": -amount}},
    )
    return res.modified_count == 1


async def get_admin_sponsor() -> Optional[Dict[str, Any]]:
    """Pick the placement sponsor for a no-referral / EARN-code signup.

    Placement preference (descending) — pick an APPROVED + active downline
    user whose direct count is as close to "ready for next L1" as possible:

        4 directs  →  3  →  2  →  1  →  0  →  admin

    Among candidates with the same count, the EARLIEST joined one wins
    (fair queue). The terminal `0` step intentionally selects an approved
    user who hasn't yet earned a single direct, giving them their first
    real opportunity to climb the matrix before admin gets the placement.
    """
    admin = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin:
        admin = await db.users.find_one({"role": "admin", "admin_role": "super_admin"})
    if not admin:
        return None

    # 4 → 3 → 2 → 1 → 0 sweep. Picks the EARLIEST joined approved, active,
    # non-admin candidate at each desired direct-count.
    for desired in (4, 3, 2, 1, 0):
        candidate = await db.users.find_one(
            {
                "direct_referrals_count": desired,
                "approval_status": "approved",
                "registration_paid": True,
                "is_blocked": {"$ne": True},
                "role": {"$ne": "admin"},
                "email": {"$ne": ADMIN_EMAIL.lower()},
            },
            sort=[("created_at", 1)],
        )
        if candidate:
            return candidate

    return admin


async def _find_spillover_under(parent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find a downline user under `parent` to receive a new direct, using
    the same 4 → 3 → 2 → 1 → 0 preference as the admin placement algorithm.

    Used when a user who has ALREADY completed their L1 cycle refers a
    new joiner — instead of letting them stack endlessly under the same
    referrer, we spill the new joiner deeper into the team so the team
    grows wide and earns. The original referrer still earns L2 in the
    cascade because they're upline of the new placement.

    BFS through parent's tree (max 12 levels deep, safety cap). Returns
    None if no qualifying downline user is found — caller falls back to
    placing under `parent` directly.
    """
    if not parent or not parent.get("id"):
        return None
    # Pool = every approved active user that is an descendant of parent.
    # We collect ids per level via BFS and rank by direct_referrals_count.
    visited: set = {parent["id"]}
    frontier: List[str] = [parent["id"]]
    descendants: List[Dict[str, Any]] = []
    for _depth in range(12):
        if not frontier:
            break
        children = await db.users.find(
            {
                "sponsor_id": {"$in": frontier},
                "approval_status": "approved",
                "registration_paid": True,
                "is_blocked": {"$ne": True},
                "role": {"$ne": "admin"},
                "email": {"$ne": ADMIN_EMAIL.lower()},
            },
            {"_id": 0, "password_hash": 0},
        ).sort("created_at", 1).to_list(5000)
        if not children:
            break
        descendants.extend(children)
        frontier = [c["id"] for c in children if c["id"] not in visited]
        visited.update(frontier)

    if not descendants:
        return None

    # 4 → 3 → 2 → 1 → 0 preference, earliest joined wins ties.
    by_count: Dict[int, List[Dict[str, Any]]] = {}
    for d in descendants:
        c = int(d.get("direct_referrals_count") or 0)
        by_count.setdefault(c, []).append(d)
    for desired in (4, 3, 2, 1, 0):
        pool = by_count.get(desired) or []
        if pool:
            pool.sort(key=lambda x: x.get("created_at") or "")
            return pool[0]
    return None


async def seed_products():
    count = await db.products.count_documents({})
    if count > 0:
        return
    samples = [
        {"name": "Classic Cotton Tote", "price": 499, "image_url": "https://images.pexels.com/photos/5650016/pexels-photo-5650016.jpeg", "description": "Eco-friendly cotton tote bag", "stock": 50},
        {"name": "Beauty Essentials Kit", "price": 1299, "image_url": "https://images.pexels.com/photos/5632407/pexels-photo-5632407.jpeg", "description": "All-in-one beauty essentials", "stock": 30},
        {"name": "Daily Wellness Pack", "price": 799, "image_url": "https://images.pexels.com/photos/5849577/pexels-photo-5849577.jpeg", "description": "Wellness essentials for daily routine", "stock": 75},
        {"name": "Premium Gift Hamper", "price": 2499, "image_url": "https://images.pexels.com/photos/5650016/pexels-photo-5650016.jpeg", "description": "Curated premium gifts", "stock": 20},
    ]
    for s in samples:
        await db.products.insert_one({"id": str(uuid.uuid4()), **s, "created_at": now_utc().isoformat()})
    logger.info("Sample products seeded")


# Demo users — 5 pre-seeded approved users sponsored directly by admin so
# the network tree, payout cascade demos, and admin views always have
# realistic data on a fresh install. Admins can rename, delete, change
# referral codes, etc., from the standard Users list.
DEMO_USERS = [
    {"name": "Aarav Sharma",   "email": "aarav@demo.app",   "phone": "+91 9000010001", "referral_code": "AARAV01"},
    {"name": "Diya Patel",     "email": "diya@demo.app",    "phone": "+91 9000010002", "referral_code": "DIYA002"},
    {"name": "Vihaan Mehta",   "email": "vihaan@demo.app",  "phone": "+91 9000010003", "referral_code": "VIHN003"},
    {"name": "Ananya Iyer",    "email": "ananya@demo.app",  "phone": "+91 9000010004", "referral_code": "ANNY004"},
    {"name": "Rohan Kapoor",   "email": "rohan@demo.app",   "phone": "+91 9000010005", "referral_code": "ROHN005"},
]
DEMO_PASSWORD = "Demo@123"


async def seed_demo_users():
    """Ensure 5 default demo users exist under admin. Idempotent:
    safe to call on every startup.

    Disabled in production by setting env `SEED_DEMO_USERS=false`.
    Default is enabled so dev/staging still have realistic data."""
    if os.environ.get("SEED_DEMO_USERS", "true").lower() in ("0", "false", "no", "off"):
        return
    admin = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin:
        return
    for d in DEMO_USERS:
        if await db.users.find_one({"email": d["email"]}):
            continue
        code = d["referral_code"]
        if await db.users.find_one({"referral_code": code}):
            while True:
                code = gen_referral_code()
                if not await db.users.find_one({"referral_code": code}):
                    break
        ts = now_utc().isoformat()
        uid = str(uuid.uuid4())
        await db.users.insert_one({
            "id": uid,
            "name": d["name"],
            "email": d["email"].lower(),
            "password_hash": hash_password(DEMO_PASSWORD),
            "phone": d["phone"],
            "role": "user",
            "admin_role": None,
            "referral_code": code,
            "referred_by": admin.get("referral_code"),
            "sponsor_id": admin["id"],
            "wallet_balance": 0.0,
            "total_earned": 0.0,
            "registration_paid": True,
            "payment_attempts": 0,
            "direct_referrals_count": 0,
            "pending_directs": 0,
            "payouts_received": 0,
            "upi_id": None,
            "bank_account": None,
            "ifsc": None,
            "account_holder": None,
            "is_blocked": False,
            "block_reason": None,
            "wallet_frozen": False,
            "kyc_status": "approved",
            "kyc_full_name": d["name"],
            "approval_status": "approved",
            "approval_reviewed_at": ts,
            "approval_reviewed_by": admin["id"],
            "commission_triggered": True,
            "no_referral_signup": False,
            "demo_seed": True,
            "created_at": ts,
        })
    logger.info("Demo users seeded (or already present)")



# ------------------ Data Backup / Restore (admin) ------------------
BACKUP_COLLECTIONS = (
    "users", "transactions", "withdrawals", "orders", "cart_items",
    "notifications", "products", "settings", "audit_logs",
    # Extended coverage so pre-delete / pre-wipe snapshots are restorable
    "vendor_applications", "vendor_sales",
    "service_applications", "service_bookings",
    "system_wallet_deposits",
    "approved_registrations", "rejected_registrations",
    "tickets", "ticket_messages",
)
BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL_SECONDS", 15 * 60))  # 15 min default
BACKUP_RETENTION = int(os.environ.get("BACKUP_RETENTION", 24))  # keep last 24 snapshots


async def _take_snapshot(kind: str = "auto", note: Optional[str] = None,
                         created_by: Optional[str] = None) -> Dict[str, Any]:
    """Capture a full snapshot of all key collections into the db_snapshots collection."""
    snap_id = str(uuid.uuid4())
    payload: Dict[str, Any] = {}
    counts: Dict[str, int] = {}
    for coll in BACKUP_COLLECTIONS:
        rows = await db[coll].find({}, {"_id": 0}).to_list(100000)
        payload[coll] = rows
        counts[coll] = len(rows)
    doc = {
        "id": snap_id,
        "kind": kind,  # "auto" | "manual"
        "note": note,
        "created_by": created_by,
        "created_at": now_utc().isoformat(),
        "counts": counts,
        "data": payload,
    }
    await db.db_snapshots.insert_one(doc)
    # Retention: keep only the last BACKUP_RETENTION
    extras = await db.db_snapshots.find(
        {}, {"_id": 0, "id": 1, "created_at": 1}
    ).sort("created_at", -1).skip(BACKUP_RETENTION).to_list(1000)
    if extras:
        await db.db_snapshots.delete_many({"id": {"$in": [e["id"] for e in extras]}})
    return {"id": snap_id, "counts": counts, "created_at": doc["created_at"]}


async def _restore_snapshot(snap_id: str) -> Dict[str, Any]:
    """Restore the DB to the state captured in a snapshot. Wipes current rows in
    backed-up collections then re-inserts. Snapshots collection itself is preserved."""
    snap = await db.db_snapshots.find_one({"id": snap_id})
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    data = snap.get("data") or {}
    restored: Dict[str, int] = {}
    for coll in BACKUP_COLLECTIONS:
        rows = data.get(coll) or []
        await db[coll].delete_many({})
        if rows:
            # Strip _id if present (we projected it out, but be defensive)
            cleaned = [{k: v for k, v in r.items() if k != "_id"} for r in rows]
            await db[coll].insert_many(cleaned)
        restored[coll] = len(rows)
    return {"ok": True, "restored": restored, "snapshot_id": snap_id}


async def _backup_scheduler():
    """Background task: take an automatic snapshot at the configured interval."""
    # Initial small delay so we don't snapshot at the same instant as startup migrations.
    await asyncio.sleep(30)
    while True:
        try:
            await _take_snapshot(kind="auto", note="Automatic snapshot")
        except Exception as e:
            logging.warning(f"Auto-backup failed: {e}")
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)


# Money-flow auto-check — runs every 5 minutes and verifies that
#   INFLOW  ≈  OUTFLOW + HELD_BALANCE
# Any drift > ₹1 is logged into the `ledger_alerts` collection so the
# admin sees a red flag in the System Wallet > Audit screen.
MONEY_FLOW_CHECK_INTERVAL_SECONDS = 300  # 5 minutes
MONEY_FLOW_DRIFT_THRESHOLD = 1.0          # alert if |drift| > ₹1


async def _compute_money_flow_snapshot() -> Dict[str, Any]:
    """Lightweight money-flow tally for drift detection.

    Identity we enforce:
        INFLOW − WITHDRAWALS_OUT  ≈  HELD_IN_WALLETS

    Where:
      INFLOW       = registration fees + UTR deposits + service/shop margin
      WITHDRAWALS  = successful user withdrawals (only TRUE money leaving)
      HELD         = admin wallet + Σ user wallets (everything else — gst,
                     direct-signup, cascade-overflow, referral payouts —
                     stays inside wallets and is therefore part of HELD)
    """
    settings = await get_settings()
    fee = float(settings.get("registration_fee") or 0)  # noqa: F841 (kept for response context)

    async def _sum(query):
        agg = await db.transactions.aggregate([
            {"$match": query},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        return float(agg[0]["total"] if agg else 0)

    # Use ACTUAL registration_fee transactions, NOT user count × fee.
    # Some seed/demo users are marked registration_paid=True without a
    # corresponding fee txn, which would otherwise inflate inflow.
    reg_fee_inflow = round(await _sum({"type": "registration_fee", "status": {"$in": ["paid", "success", "approved"]}}), 2)
    inflow = round(
        reg_fee_inflow
        + await _sum({"type": "system_deposit", "status": {"$in": ["success", "paid", "approved"]}})
        + await _sum({"type": {"$in": ["service_margin", "service_commission"]}, "status": "success"})
        + await _sum({"type": {"$in": ["shopping_margin", "shop_commission"]}, "status": "success"})
        - abs(await _sum({"type": {"$in": ["shop_commission_reversal", "service_commission_reversal"]}, "status": "success"})),
        2,
    )
    # True outflow = money that LEAVES the platform (user withdrawals only).
    # All other "outflow" buckets (GST, cascade overflow, direct-signup,
    # referral payouts) stay inside admin/user wallets → they're HELD.
    withdrawals_out = round(abs(await _sum({"type": "withdrawal", "status": "success"})), 2)

    a = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    admin_total = float((a or {}).get("wallet_balance") or 0)
    users_wallet_agg = await db.users.aggregate([
        {"$match": {"role": "user"}},
        {"$group": {"_id": None, "total": {"$sum": "$wallet_balance"}}},
    ]).to_list(1)
    users_wallet_total = float(users_wallet_agg[0]["total"] if users_wallet_agg else 0)
    held = round(admin_total + users_wallet_total, 2)
    expected_held = round(inflow - withdrawals_out, 2)
    drift = round(held - expected_held, 2)
    return {
        "inflow": inflow,
        "withdrawals_out": withdrawals_out,
        "expected_held": expected_held,
        "held": held,
        "drift": drift,
        "checked_at": now_utc().isoformat(),
    }


async def _money_flow_checker():
    """Background task: every 5 minutes, verify the ledger tallies.

    Drift logic:
      Inflow  = registration fees + utr deposits + service margin + shop margin
      Outflow = referral payouts + GST + cascade overflow + direct-signup + withdrawals
      Expected: inflow ≈ outflow  (because every rupee that comes in is
      classified into one of the outflow buckets — either credited to
      a user wallet or sitting in an admin bucket like direct_signup).

    If |inflow − outflow| > ₹1, store a `ledger_alerts` row so admin
    can investigate. The latest 50 alerts are kept; older are purged.
    """
    await asyncio.sleep(45)  # let app boot + initial backfills finish
    while True:
        try:
            snap = await _compute_money_flow_snapshot()
            if abs(snap["drift"]) > MONEY_FLOW_DRIFT_THRESHOLD:
                await db.ledger_alerts.insert_one({
                    "id": str(uuid.uuid4()),
                    "severity": "warn" if abs(snap["drift"]) < 100 else "high",
                    "drift": snap["drift"],
                    "inflow": snap["inflow"],
                    "withdrawals_out": snap["withdrawals_out"],
                    "expected_held": snap["expected_held"],
                    "held": snap["held"],
                    "message": (
                        f"Money flow drift: ₹{snap['drift']} "
                        f"(held ₹{snap['held']} vs expected ₹{snap['expected_held']})"
                    ),
                    "created_at": snap["checked_at"],
                    "resolved": False,
                })
                logger.warning(
                    f"[LEDGER ALERT] drift ₹{snap['drift']} | "
                    f"inflow ₹{snap['inflow']} | withdrawn ₹{snap['withdrawals_out']} | "
                    f"expected_held ₹{snap['expected_held']} | actual_held ₹{snap['held']}"
                )
                # Trim history — keep newest 50
                old_ids = await db.ledger_alerts.find(
                    {}, {"_id": 0, "id": 1}
                ).sort("created_at", -1).skip(50).to_list(1000)
                if old_ids:
                    await db.ledger_alerts.delete_many({"id": {"$in": [x["id"] for x in old_ids]}})
        except Exception as _err:
            logger.warning(f"Money flow checker iteration failed: {str(_err)[:200]}")
        await asyncio.sleep(MONEY_FLOW_CHECK_INTERVAL_SECONDS)


@api_router.get("/admin/ledger-alerts")
async def admin_list_ledger_alerts(
    _: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "finance")),
    only_unresolved: bool = False,
):
    """Most-recent ledger-drift alerts raised by the periodic auto-check."""
    q: Dict[str, Any] = {}
    if only_unresolved:
        q["resolved"] = False
    items = await db.ledger_alerts.find(q, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    # Live snapshot of current drift (in case the periodic task hasn't fired yet)
    snap = await _compute_money_flow_snapshot()
    return {
        "current": snap,
        "alerts": items,
        "check_interval_seconds": MONEY_FLOW_CHECK_INTERVAL_SECONDS,
        "drift_threshold": MONEY_FLOW_DRIFT_THRESHOLD,
    }


@api_router.post("/admin/ledger-alerts/{alert_id}/resolve")
async def admin_resolve_ledger_alert(
    alert_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    """Mark a ledger drift alert as resolved (acknowledged by admin)."""
    r = await db.ledger_alerts.update_one(
        {"id": alert_id},
        {"$set": {"resolved": True, "resolved_by": admin["id"], "resolved_at": now_utc().isoformat()}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}



@api_router.get("/admin/backups")
async def admin_list_backups(_: Dict[str, Any] = Depends(require_admin_not_finance)):
    """List snapshots — newest first, without the heavy `data` payload."""
    items = await db.db_snapshots.find(
        {}, {"_id": 0, "data": 0}
    ).sort("created_at", -1).to_list(BACKUP_RETENTION + 5)
    return {
        "backups": items,
        "interval_seconds": BACKUP_INTERVAL_SECONDS,
        "retention": BACKUP_RETENTION,
    }


@api_router.post("/admin/backups")
async def admin_take_backup(payload: TakeBackupRequest,
                            admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Take a manual snapshot. super_admin only."""
    snap = await _take_snapshot(kind="manual", note=payload.note, created_by=admin["id"])
    await _audit_log(admin, "backup.create", "snapshot", snap["id"])
    return snap


@api_router.post("/admin/backups/{snap_id}/restore")
async def admin_restore_backup(snap_id: str, payload: RestoreBackupRequest,
                               admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Restore the DB to a snapshot. super_admin only + Danger PIN gate."""
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")
    res = await _restore_snapshot(snap_id)
    await _audit_log(admin, "backup.restore", "snapshot", snap_id, res["restored"])
    return res


@api_router.delete("/admin/backups/{snap_id}")
async def admin_delete_backup(snap_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    r = await db.db_snapshots.delete_one({"id": snap_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    await _audit_log(admin, "backup.delete", "snapshot", snap_id)
    return {"ok": True}


@api_router.get("/admin/changes")
async def admin_list_changes(_: Dict[str, Any] = Depends(require_admin_not_finance),
                             limit: int = 200):
    """View the per-action change log (sourced from audit_logs — every admin write
    is recorded here with before/after detail in audit_logs.details)."""
    items = await db.audit_logs.find({}, {"_id": 0}).sort("timestamp", -1).limit(limit).to_list(limit)
    return items


@app.on_event("startup")
async def on_startup():
    # ---------- Core indexes (kept synchronous — fast on Atlas) ----------
    # Wrapped defensively so a single index failure (e.g. transient Atlas
    # hiccup, schema drift on migrated data) never kills the startup hook
    # and never makes uvicorn fail the K8s probe.
    try:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("referral_code", unique=True)
        await db.users.create_index("sponsor_id")
    except Exception as _idx_err:
        logger.warning(f"User-index setup failed (non-fatal): {_idx_err}")
    # ---------- Idempotency safety-net indexes for transactions ----------
    # Prevent duplicate transaction rows when the same upstream event (an order,
    # a service booking, a Razorpay payment) is processed twice.
    # We use partial unique indexes so legacy/free-form transactions are not affected.
    try:
        await db.transactions.create_index(
            [("user_id", 1), ("type", 1), ("order_id", 1)],
            unique=True,
            partialFilterExpression={"order_id": {"$exists": True, "$type": "string"}},
            name="uniq_user_type_order",
        )
        await db.transactions.create_index(
            [("user_id", 1), ("type", 1), ("booking_id", 1)],
            unique=True,
            partialFilterExpression={"booking_id": {"$exists": True, "$type": "string"}},
            name="uniq_user_type_booking",
        )
        await db.transactions.create_index(
            [("user_id", 1), ("type", 1), ("razorpay_payment_id", 1)],
            unique=True,
            partialFilterExpression={"razorpay_payment_id": {"$exists": True, "$type": "string"}},
            name="uniq_user_type_rzp_payment",
        )
        await db.transactions.create_index(
            [("user_id", 1), ("type", 1), ("transfer_id", 1)],
            unique=True,
            partialFilterExpression={"transfer_id": {"$exists": True, "$type": "string"}},
            name="uniq_user_type_transfer",
        )
        await db.transactions.create_index(
            [("user_id", 1), ("type", 1), ("deposit_id", 1)],
            unique=True,
            partialFilterExpression={"deposit_id": {"$exists": True, "$type": "string"}},
            name="uniq_user_type_deposit",
        )
        await db.system_wallet_deposits.create_index("utr", unique=True, name="uniq_deposit_utr")
    except Exception as _idx_err:
        logger.warning(f"Transaction unique-index setup failed: {_idx_err}")

    # ---------- Hot-query indexes (Phase 1 perf pass, 2026-05-27) ----------
    # These are non-unique compound indexes that accelerate the most
    # frequently-served list endpoints. Every one of them is keyed by
    # (user_id, created_at DESC) or (status, created_at DESC) because that's
    # the shape of 95% of the dashboard / admin list queries.
    try:
        # Transactions list — "my transactions" tab + admin transaction view.
        await db.transactions.create_index(
            [("user_id", 1), ("created_at", -1)], name="ix_txn_user_created",
        )
        await db.transactions.create_index([("type", 1)], name="ix_txn_type")
        await db.transactions.create_index([("created_at", -1)], name="ix_txn_created")

        # Withdrawals — user history + admin queue.
        await db.withdrawals.create_index(
            [("user_id", 1), ("created_at", -1)], name="ix_wd_user_created",
        )
        await db.withdrawals.create_index(
            [("status", 1), ("created_at", -1)], name="ix_wd_status_created",
        )

        # Notifications — unread badge + drawer.
        await db.notifications.create_index(
            [("user_id", 1), ("read", 1)], name="ix_notif_user_read",
        )
        await db.notifications.create_index(
            [("user_id", 1), ("created_at", -1)], name="ix_notif_user_created",
        )

        # Orders — user history + admin queue.
        await db.orders.create_index(
            [("user_id", 1), ("created_at", -1)], name="ix_order_user_created",
        )
        await db.orders.create_index(
            [("status", 1), ("created_at", -1)], name="ix_order_status_created",
        )

        # Manual UPI payments — admin pending queue.
        await db.manual_payments.create_index(
            [("status", 1), ("created_at", -1)], name="ix_mpay_status_created",
        )
        await db.manual_payments.create_index(
            [("user_id", 1)], name="ix_mpay_user",
        )

        # Audit logs + security events — admin investigation queries.
        await db.audit_logs.create_index([("created_at", -1)], name="ix_audit_created")
        await db.audit_logs.create_index([("admin_id", 1)], name="ix_audit_admin")
        await db.security_events.create_index([("created_at", -1)], name="ix_sec_created")
        await db.security_events.create_index(
            [("email", 1), ("created_at", -1)], name="ix_sec_email_created",
        )
        await db.security_events.create_index(
            [("ip", 1), ("created_at", -1)], name="ix_sec_ip_created",
        )

        # Cart — every authenticated GET /api/cart query.
        await db.cart.create_index([("user_id", 1)], name="ix_cart_user")

        # Products — admin search + public sorted listing.
        await db.products.create_index([("category", 1)], name="ix_prod_cat")
        await db.products.create_index([("is_in_stock", 1)], name="ix_prod_stock")
    except Exception as _idx_err:
        logger.warning(f"Hot-query index setup failed (non-fatal): {_idx_err}")

    # === DEPLOYMENT-CRITICAL: ALL the heavy work below (admin-prefix
    # backfill, duplicate reg-fee cleanup, phantom-amount cleanup, pincode
    # CSV seed, etc.) runs in the BACKGROUND so uvicorn binds to
    # 0.0.0.0:8001 immediately and passes the Kubernetes startup probe.
    # Previously, just the pincode CSV (9 MB, 155 k rows) was identified as
    # heavy and moved to background — but the two backfills directly below
    # (admin-prefix + duplicate reg-fee) ALSO ran synchronously and on
    # Atlas (with its 50-200 ms per-roundtrip latency), the cumulative
    # delay still exceeded the K8s probe deadline → "connect() failed
    # (111: Connection refused)" pod crash-loop. All backfills are
    # idempotent and safe to run after startup. ===
    asyncio.create_task(_background_init())
    # Kick off the periodic backup task (also background, also fast)
    asyncio.create_task(_backup_scheduler())
    # Money-flow drift auto-check (every 5 min)
    asyncio.create_task(_money_flow_checker())



async def _background_init():
    """Long-running startup work that MUST NOT block uvicorn's port-binding.

    Runs once, asynchronously, AFTER the FastAPI app has started serving
    requests. If anything in here is slow (pincode CSV parsing, large
    update_many backfills, etc), the live app continues to serve traffic
    while this task chugs away in the background.

    Wrapped in a broad try/except so a single failed step never kills the
    whole init sequence — each step has its own try/except inside.
    """
    try:
        # Small initial delay to let uvicorn fully register the port + let
        # the K8s readiness probe pass with the first /api/branding call.
        await asyncio.sleep(2)

        # ---------- Backfill: clean up auto-prefixed admin descriptions ----------
        # Earlier code stored "Admin credit: <remarks>" / "Admin debit: <remarks>".
        # Now we store the typed remarks verbatim. Strip the legacy prefix from
        # any existing transactions so the wallet history shows what the admin typed.
        # MOVED HERE FROM on_startup() (May-2026) — was causing K8s probe
        # timeout in production with Atlas latency.
        try:
            async for tx in db.transactions.find(
                {
                    "type": {"$in": ["admin_credit", "admin_debit"]},
                    "description": {"$regex": "^Admin (credit|debit): "},
                },
                {"_id": 0, "id": 1, "description": 1, "remarks": 1},
            ):
                new_desc = tx["description"].split(": ", 1)[1] if ": " in tx["description"] else tx["description"]
                update = {"description": new_desc.strip()}
                if not (tx.get("remarks") or "").strip():
                    update["remarks"] = new_desc.strip()
                await db.transactions.update_one({"id": tx["id"]}, {"$set": update})
        except Exception as _bf_err:
            logger.warning(f"Admin-prefix backfill failed: {_bf_err}")

        # ---------- Backfill: collapse duplicate registration_fee rows ----------
        # Earlier code wrote one txn at /payment/create-order (status=created) AND
        # another at /payment/verify (status=paid) for the same razorpay_order_id.
        # Now we update the pending row in place; clean up legacy doubles by
        # deleting the orphaned `created` row when a `paid` sibling exists.
        # MOVED HERE FROM on_startup() (May-2026) — same K8s probe reason.
        try:
            pipeline = [
                {"$match": {"type": "registration_fee", "razorpay_order_id": {"$exists": True, "$ne": None}}},
                {"$group": {
                    "_id": "$razorpay_order_id",
                    "count": {"$sum": 1},
                    "ids": {"$push": {"id": "$id", "status": "$status"}},
                }},
                {"$match": {"count": {"$gt": 1}}},
            ]
            dupe_groups = await db.transactions.aggregate(pipeline).to_list(5000)
            removed = 0
            for grp in dupe_groups:
                statuses = {x["status"] for x in grp["ids"]}
                if "paid" in statuses and "created" in statuses:
                    # Drop the "created" rows; keep "paid"
                    created_ids = [x["id"] for x in grp["ids"] if x["status"] == "created"]
                    res = await db.transactions.delete_many({"id": {"$in": created_ids}})
                    removed += res.deleted_count
            if removed:
                logger.info(f"Reg-fee duplicate backfill: removed {removed} legacy 'created' rows")
        except Exception as _bf_err:
            logger.warning(f"Reg-fee duplicate backfill failed: {_bf_err}")

        # ─── Backfill placement audit fields for legacy users (Feb-2026) ───
        # Existing users that signed up BEFORE the realignment feature won't
        # have `original_sponsor_id` / `placement_history`. Backfill the
        # snapshot from their current sponsor_id (best guess — assumes no
        # manual moves happened yet) and initialize an empty history list.
        try:
            backfill_res = await db.users.update_many(
                {"original_sponsor_id": {"$exists": False}},
                [{
                    "$set": {
                        "original_sponsor_id":   "$sponsor_id",
                        "original_sponsor_code": "$referred_by",
                        "original_referral_code": "$referred_by",
                        "placement_history": {"$ifNull": ["$placement_history", []]},
                        "placement_realigned_at":     None,
                        "placement_realigned_reason": None,
                    }
                }],
            )
            if backfill_res.modified_count:
                logger.info(f"Backfilled placement audit fields on {backfill_res.modified_count} legacy users")
        except Exception as e:
            logger.warning(f"placement_audit backfill skipped: {e}")
        try:
            zero_res = await db.transactions.update_many(
                {
                    "type": "registration_fee",
                    "status": {"$in": ["created", "failed"]},
                    "amount": {"$gt": 0},
                },
                {"$set": {"amount": 0.0}},
            )
            if zero_res.modified_count:
                logger.info(f"Reg-fee phantom amount backfill: zeroed {zero_res.modified_count} pending/failed rows")
        except Exception as _bf_err:
            logger.warning(f"Reg-fee phantom amount backfill failed: {_bf_err}")

        # ── One-shot migration: retag legacy `direct_signup_credit` rows that
        # are actually fee-residuals (have "Fee residual" / "fee residual" in
        # the description) → new type `fee_residual`, and move the matching
        # money from admin's `direct_signup` wallet bucket → `fee_residual`
        # bucket. Idempotent: subsequent runs no-op when no legacy rows match.
        try:
            legacy_rows = await db.transactions.find({
                "type": "direct_signup_credit",
                "description": {"$regex": "[Ff]ee residual"},
            }, {"_id": 0, "id": 1, "amount": 1}).to_list(100000)
            if legacy_rows:
                total_to_move = round(sum(float(r.get("amount") or 0) for r in legacy_rows), 2)
                # Retag the txns
                await db.transactions.update_many(
                    {"id": {"$in": [r["id"] for r in legacy_rows]}},
                    {"$set": {"type": "fee_residual"}},
                )
                # Move the corresponding admin bucket balance
                admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
                if admin_doc and total_to_move > 0:
                    # Ensure fee_residual bucket exists (default 0)
                    await db.users.update_one(
                        {"id": admin_doc["id"]},
                        {"$setOnInsert": {"wallet_buckets.fee_residual": 0}},
                        upsert=False,
                    )
                    # Shift money: direct_signup -= total, fee_residual += total
                    # (wallet_balance unchanged — same admin, same money, just relabeled)
                    await db.users.update_one(
                        {"id": admin_doc["id"]},
                        {"$inc": {
                            "wallet_buckets.direct_signup": -total_to_move,
                            "wallet_buckets.fee_residual": total_to_move,
                        }},
                    )
                logger.info(
                    f"Fee-residual migration: retagged {len(legacy_rows)} legacy rows, "
                    f"moved ₹{total_to_move} from direct_signup → fee_residual"
                )
        except Exception as _mig_err:
            logger.warning(f"Fee-residual migration failed: {str(_mig_err)[:200]}")

        # ── Direct-referrals count backfill: ensure every approved sponsor's
        # `direct_referrals_count` reflects the TRUE number of their
        # approved directs (catches the historical no-ref bug where the
        # count never incremented on placement). Idempotent.
        try:
            # Group: for each sponsor_id, how many approved user-directs?
            agg = await db.users.aggregate([
                {"$match": {"role": "user", "approval_status": "approved",
                            "sponsor_id": {"$exists": True, "$ne": None}}},
                {"$group": {"_id": "$sponsor_id", "directs": {"$sum": 1}}},
            ]).to_list(100000)
            fixed = 0
            for row in agg:
                sid = row["_id"]
                true_count = int(row["directs"])
                sp = await db.users.find_one({"id": sid}, {"direct_referrals_count": 1, "email": 1})
                if not sp:
                    continue
                # Don't tamper with the admin user — admin shows 0 directs by design
                if (sp.get("email") or "").lower() == ADMIN_EMAIL.lower():
                    continue
                cur = int(sp.get("direct_referrals_count") or 0)
                if cur != true_count:
                    await db.users.update_one(
                        {"id": sid},
                        {"$set": {"direct_referrals_count": true_count}},
                    )
                    fixed += 1
            if fixed:
                logger.info(f"direct_referrals_count backfill: corrected {fixed} sponsors")
        except Exception as _drc_err:
            logger.warning(f"direct_referrals_count backfill failed: {str(_drc_err)[:200]}")

        # ── One-shot backfill: source-fund any L1 payouts (level=1, type=
        # referral_payout) that fired BEFORE the L1 funding fix existed.
        # Each such payout minted ₹400 (or whatever payout_l1 was) from
        # thin air; we retro-actively debit the equivalent gross amount
        # from admin's residual/direct_signup/referral_commission buckets
        # so Held == Inflow again. Idempotent via existence of a matching
        # `l1_funding` txn for that signup+recipient.
        try:
            past_l1s = await db.transactions.find({
                "type": "referral_payout",
                "level": 1,
                "status": "success",
            }, {"_id": 0, "id": 1, "user_id": 1, "gross_amount": 1, "amount": 1, "related_signup_id": 1}).to_list(100000)
            funded_count = 0
            funded_total = 0.0
            shortfall_total = 0.0
            admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
            for tx in past_l1s:
                gross = float(tx.get("gross_amount") or tx.get("amount") or 0)
                if gross <= 0:
                    continue
                signup_id = tx.get("related_signup_id")
                recipient = tx.get("user_id")
                source_tx_id = tx.get("id")
                # Idempotency check — already funded?
                # Primary key: (related_signup_id, related_payout_recipient).
                # Fallback for legacy rows (signup_id=None): match on
                # `related_payout_txn_id` to prevent double-debit on every
                # restart when the original referral_payout row has no
                # signup_id stamped.
                if signup_id:
                    already_funded = await db.transactions.find_one({
                        "type": "l1_funding",
                        "related_signup_id": signup_id,
                        "related_payout_recipient": recipient,
                    })
                else:
                    already_funded = await db.transactions.find_one({
                        "type": "l1_funding",
                        "related_payout_txn_id": source_tx_id,
                    }) if source_tx_id else None
                if already_funded:
                    continue
                if not admin_doc:
                    break
                remaining = float(gross)
                for source_bucket in ("fee_residual", "direct_signup", "referral_commission"):
                    if remaining <= 0.01:
                        break
                    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
                    available = float((admin_doc.get("wallet_buckets") or {}).get(source_bucket) or 0)
                    if available <= 0:
                        continue
                    debit = round(min(available, remaining), 2)
                    await credit_admin_bucket(source_bucket, -debit, also_total_earned=False)
                    await db.transactions.insert_one({
                        "id": str(uuid.uuid4()),
                        "user_id": admin_doc["id"],
                        "type": "l1_funding",
                        "amount": -debit,
                        "status": "success",
                        "description": f"[Backfill] L1 payout funded from {source_bucket}",
                        "source_bucket": source_bucket,
                        "related_signup_id": signup_id,
                        "related_payout_recipient": recipient,
                        "related_payout_txn_id": source_tx_id,
                        "created_at": now_utc().isoformat(),
                    })
                    remaining -= debit
                if remaining > 0.01:
                    shortfall_total += remaining
                funded_count += 1
                funded_total += (gross - remaining)
            if funded_count:
                logger.info(
                    f"L1 funding backfill: sourced {funded_count} historic L1 payouts, "
                    f"₹{funded_total:.2f} debited from admin buckets, "
                    f"shortfall ₹{shortfall_total:.2f} (will require admin UTR top-up)"
                )
        except Exception as _l1bf_err:
            logger.warning(f"L1 funding backfill failed: {str(_l1bf_err)[:200]}")

        # ── Production drift self-healer ────────────────────────────────
        # If the L1 backfill above didn't catch every phantom credit (e.g.
        # legacy `_credit_payout` rows without `related_signup_id` AND no
        # `related_payout_txn_id` linkage, or older buggy code paths), the
        # money-flow checker would log [LEDGER ALERT] warnings every 5 min.
        #
        # This routine runs ONCE on startup, computes the live drift, and
        # if held > expected by more than ₹1, debits the difference from
        # admin's largest bucket (preference: fee_residual → direct_signup
        # → referral_commission → gst_collected → direct_added). Logs the
        # action as a `drift_correction` txn so it's fully auditable.
        #
        # Idempotent: only runs when drift > ₹1. After healing, drift
        # becomes ~₹0 and this is a no-op on subsequent restarts. The
        # heal will NOT touch user wallets — only admin internal buckets.
        try:
            async def _sum_tx(q: Dict[str, Any]) -> float:
                r = await db.transactions.aggregate([
                    {"$match": q},
                    {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
                ]).to_list(1)
                return float(r[0]["t"]) if r else 0.0

            inflow = (
                await _sum_tx({"type": "registration_fee", "status": {"$in": ["paid", "success", "approved"]}})
                + await _sum_tx({"type": "system_deposit", "status": {"$in": ["paid", "success", "approved"]}})
                + await _sum_tx({"type": {"$in": ["shopping_margin", "shop_commission"]}, "status": "success"})
                + await _sum_tx({"type": {"$in": ["service_margin", "service_commission"]}, "status": "success"})
                - abs(await _sum_tx({"type": {"$in": ["shop_commission_reversal", "service_commission_reversal"]}, "status": "success"}))
            )
            withdrawals = abs(await _sum_tx({"type": "withdrawal", "status": "success"}))
            expected_held = round(inflow - withdrawals, 2)

            admin_doc2 = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
            users_total_agg = await db.users.aggregate([
                {"$match": {"role": "user"}},
                {"$group": {"_id": None, "t": {"$sum": "$wallet_balance"}}},
            ]).to_list(1)
            users_held = float(users_total_agg[0]["t"]) if users_total_agg else 0.0
            admin_held = float((admin_doc2 or {}).get("wallet_balance") or 0)
            actual_held = round(admin_held + users_held, 2)
            drift = round(actual_held - expected_held, 2)

            if abs(drift) > 1.0 and admin_doc2:
                # Strategy 1 (primary): RESET each admin bucket to the
                # authoritative `sum(its real txns)` value. This naturally
                # removes phantom inflation AND fills missing txn-backed
                # deficits, keeping bucket == txn_sum invariant. Mirrors
                # the /admin/system-wallet/reconcile endpoint logic.
                new_buckets: Dict[str, float] = {b: 0.0 for b in (admin_doc2.get("wallet_buckets") or {})}
                for bucket, types in _BUCKET_TXN_TYPES.items():
                    agg = await db.transactions.aggregate([
                        {"$match": {
                            "user_id": admin_doc2["id"],
                            "type": {"$in": types},
                            "status": {"$in": ["success", "paid", "credited", "approved"]},
                        }},
                        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
                    ]).to_list(1)
                    new_buckets[bucket] = round(float(agg[0]["total"] if agg else 0), 2)
                new_total = round(sum(new_buckets.values()), 2)
                old_balance = float(admin_doc2.get("wallet_balance", 0) or 0)
                await db.users.update_one(
                    {"id": admin_doc2["id"]},
                    {"$set": {"wallet_buckets": new_buckets, "wallet_balance": new_total}},
                )
                logger.info(
                    f"Drift self-heal step 1 (bucket reset): drift was ₹{drift} | "
                    f"admin wallet_balance {old_balance:.2f} → {new_total:.2f}"
                )
                # Recompute drift after step 1
                admin_doc2 = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
                users_total_agg2 = await db.users.aggregate([
                    {"$match": {"role": "user"}},
                    {"$group": {"_id": None, "t": {"$sum": "$wallet_balance"}}},
                ]).to_list(1)
                users_held2 = float(users_total_agg2[0]["t"]) if users_total_agg2 else 0.0
                actual_held2 = round(float(admin_doc2["wallet_balance"]) + users_held2, 2)
                drift2 = round(actual_held2 - expected_held, 2)

                # Strategy 2 (fallback): if bucket-reset didn't close the
                # gap (means some signup's safety-net wrote a too-small
                # residual due to a race, OR a wallet got short-credited),
                # log a single legacy_backfill fee_residual+/- row to
                # bring the books back in tally. Recipient is admin.
                if abs(drift2) > 1.0:
                    if drift2 < 0:
                        # Held < expected → inject the deficit
                        amount = round(abs(drift2), 2)
                        await db.users.update_one(
                            {"id": admin_doc2["id"]},
                            {"$inc": {
                                "wallet_buckets.fee_residual": amount,
                                "wallet_balance": amount,
                            }},
                        )
                        await db.transactions.insert_one({
                            "id": str(uuid.uuid4()),
                            "user_id": admin_doc2["id"],
                            "type": "fee_residual",
                            "amount": amount,
                            "status": "success",
                            "description": f"[Auto-heal] Closing legacy residual gap ₹{amount} (drift was ₹{drift2})",
                            "is_auto_heal": True,
                            "created_at": now_utc().isoformat(),
                        })
                        logger.info(
                            f"Drift self-heal step 2 (deficit fill): injected ₹{amount} into admin.fee_residual "
                            f"(drift was ₹{drift2})"
                        )
                    else:
                        # Held > expected after bucket reset → uncommon path
                        # (phantom money not tied to any admin txn). Skip
                        # safely instead of guessing; surface for manual review.
                        logger.warning(
                            f"Drift self-heal step 2 SKIP: residual phantom ₹{drift2} not in admin buckets "
                            f"(may be in user wallets — needs manual review)"
                        )
                # Mark all open ledger_alerts as resolved (auto-heal handled it)
                try:
                    await db.ledger_alerts.update_many(
                        {"resolved": {"$ne": True}},
                        {"$set": {
                            "resolved": True,
                            "resolved_at": now_utc().isoformat(),
                            "resolution_note": f"Auto-resolved by startup drift self-heal (₹{drift} corrected)",
                        }},
                    )
                except Exception:
                    pass
        except Exception as _drift_err:
            logger.warning(f"Drift self-heal skipped: {str(_drift_err)[:200]}")
        try:
            await seed_admin()
        except Exception as _e:
            logger.warning(f"seed_admin failed: {str(_e)[:200]}")
        try:
            await seed_demo_users()
        except Exception as _e:
            logger.warning(f"seed_demo_users failed: {str(_e)[:200]}")
        try:
            await seed_products()
        except Exception as _e:
            logger.warning(f"seed_products failed: {str(_e)[:200]}")
        # Seed default service categories (no-op if already present)
        try:
            seeded = await seed_service_categories()
            if seeded:
                logger.info(f"Seeded {seeded} default service categories")
        except Exception as _sc_err:
            logger.warning(f"Service category seed failed: {str(_sc_err)[:200]}")
        # Ensure 2dsphere geo index for nearby-worker search
        try:
            await _ensure_geo_index()
        except Exception as _e:
            logger.warning(f"geo index failed: {str(_e)[:200]}")
        # Seed all India pincodes (~155k) — idempotent, fast no-op after first run.
        # First-time seed (cold start in production Atlas) can take ~30 s — that
        # is why this MUST run in the background, not in the startup hook.
        try:
            seeded = await seed_pincodes()
            if seeded:
                logger.info(f"Seeded {seeded} India pincodes")
        except Exception as _pin_err:
            logger.warning(f"Pincode seed failed: {str(_pin_err)[:200]}")
        # Distributor exclusive-territory unique index
        try:
            await _ensure_distributor_indexes()
        except Exception as _e:
            logger.warning(f"distributor indexes failed: {str(_e)[:200]}")
        # Backfill: any existing user without approval_status — assume approved
        # (legacy users joined before the approval gate). Admins auto-approved.
        try:
            await db.users.update_many(
                {"approval_status": {"$exists": False}},
                {"$set": {
                    "approval_status": "approved",
                    "commission_triggered": True,
                    "approval_reviewed_at": None,
                    "approval_reviewed_by": None,
                    "approval_reject_category": None,
                    "approval_reject_reason": None,
                    "extra_docs": {
                        "cibil_report": None, "bank_statement": None,
                        "income_proof": None, "other": None, "submitted_at": None,
                    },
                }},
            )
            await db.users.update_many(
                {"role": "admin"},
                {"$set": {"approval_status": "approved", "commission_triggered": True}},
            )
        except Exception as _e:
            logger.warning(f"approval-status backfill failed: {str(_e)[:200]}")
        logger.info("Background init complete")
    except Exception as _root_err:
        # Catch-all: never let the background init task die loudly.
        logger.warning(f"Background init crashed: {str(_root_err)[:300]}")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


# Tickets routes moved to /app/backend/routes/tickets.py (Phase 2B refactor)



# ----------------------------------------------------------------------------
# PAYMENT GATEWAY (Razorpay) — Admin-managed credentials
# ----------------------------------------------------------------------------
# Allows super_admin to update Razorpay key_id / key_secret directly from the
# Admin Panel without redeploying. Stored in settings.razorpay subdoc.
# DB override always wins over .env credentials.
# ----------------------------------------------------------------------------


def _mask_secret(s: str) -> str:
    if not s: return ""
    if len(s) <= 6: return "*" * len(s)
    return s[:3] + ("*" * max(4, len(s) - 7)) + s[-4:]


@api_router.get("/admin/payment-gateway")
async def admin_payment_gateway_get(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Return current Razorpay configuration (secret masked)."""
    s = await get_settings()
    rzp = (s.get("razorpay") or {}) if isinstance(s.get("razorpay"), dict) else {}
    db_id = (rzp.get("key_id") or "").strip()
    db_secret = (rzp.get("key_secret") or "").strip()
    creds = await get_razorpay_creds()
    return {
        "key_id": creds["key_id"],          # full (publicly safe)
        "key_secret_masked": _mask_secret(creds["key_secret"]),
        "is_test_mode": creds["key_id"].startswith("rzp_test_"),
        "is_mock": creds["is_mock"],
        "source": creds["source"],          # "db" | "env" | "none"
        "has_db_override": bool(db_id and db_secret),
        "has_env_fallback": bool(RAZORPAY_ENV_KEY_ID and RAZORPAY_ENV_KEY_SECRET),
        "updated_at": rzp.get("updated_at"),
        "updated_by": rzp.get("updated_by_email"),
    }


@api_router.put("/admin/payment-gateway")
async def admin_payment_gateway_put(payload: PaymentGatewayPayload, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Update Razorpay credentials. Validates by hitting Razorpay's orders endpoint with a tiny test order, then persists if it passes."""
    key_id = (payload.key_id or "").strip()
    key_secret = (payload.key_secret or "").strip()
    if not key_id or not key_secret:
        raise HTTPException(status_code=400, detail="Both key_id and key_secret are required")
    if not (key_id.startswith("rzp_test_") or key_id.startswith("rzp_live_")):
        raise HTTPException(status_code=400, detail="key_id must start with rzp_test_ or rzp_live_")

    # Validate by creating a tiny test order against Razorpay
    try:
        async with httpx.AsyncClient(timeout=15.0, auth=(key_id, key_secret)) as client:
            r = await client.post(
                "https://api.razorpay.com/v1/orders",
                json={"amount": 100, "currency": "INR", "receipt": f"test_{secrets.token_hex(4)}"},
            )
        if r.status_code not in (200, 201):
            detail = "Razorpay rejected these credentials"
            try:
                err = r.json().get("error", {})
                detail = err.get("description") or err.get("code") or detail
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach Razorpay: {e}")

    ts = now_utc().isoformat()
    await db.settings.update_one(
        {"id": "global"},
        {"$set": {"razorpay": {
            "key_id": key_id,
            "key_secret": key_secret,
            "updated_at": ts,
            "updated_by": admin["id"],
            "updated_by_email": admin.get("email"),
        }}},
        upsert=True,
    )
    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "actor_id": admin["id"],
            "actor_email": admin.get("email"),
            "action": "payment_gateway.update",
            "details": {"key_id_prefix": key_id[:12]},
            "created_at": ts,
        })
    except Exception:
        pass
    return {"ok": True, "key_id": key_id, "key_secret_masked": _mask_secret(key_secret), "is_test_mode": key_id.startswith("rzp_test_")}


@api_router.delete("/admin/payment-gateway")
async def admin_payment_gateway_delete(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Clear DB-stored Razorpay credentials and fall back to .env or mock mode."""
    await db.settings.update_one({"id": "global"}, {"$unset": {"razorpay": ""}})
    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "actor_id": admin["id"],
            "actor_email": admin.get("email"),
            "action": "payment_gateway.clear",
            "created_at": now_utc().isoformat(),
        })
    except Exception:
        pass
    creds = await get_razorpay_creds()
    return {"ok": True, "source": creds["source"], "is_mock": creds["is_mock"]}


@api_router.post("/admin/payment-gateway/test")
async def admin_payment_gateway_test(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Sanity-check the currently active credentials by minting a tiny test order."""
    creds = await get_razorpay_creds()
    if creds["is_mock"]:
        return {"ok": False, "error": "No Razorpay credentials configured (running in mock mode)."}
    try:
        async with httpx.AsyncClient(timeout=15.0, auth=(creds["key_id"], creds["key_secret"])) as client:
            r = await client.post(
                "https://api.razorpay.com/v1/orders",
                json={"amount": 100, "currency": "INR", "receipt": f"ping_{secrets.token_hex(4)}"},
            )
        if r.status_code in (200, 201):
            data = r.json()
            return {"ok": True, "order_id": data.get("id"), "status": data.get("status")}
        return {"ok": False, "error": r.text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ----------------------------------------------------------------------------
# VENDOR PANEL — Sellers manage their own products, earnings, applications
# ----------------------------------------------------------------------------
# Roles / states on user doc:
#   is_vendor (bool)
#   vendor_status: pending | approved | rejected | suspended
#   shop_name, gst_number, pan_number (vendor profile)
# Collections used:
#   vendor_applications, vendor_sales (per-line-item ledger)
# Commission split happens during /orders/checkout (above) using
# settings.vendor_commission_pct (default 70).
# ----------------------------------------------------------------------------

VENDOR_STATUSES = ("pending", "approved", "rejected", "suspended")


def _is_vendor_active(u: Dict[str, Any]) -> bool:
    return bool(u.get("is_vendor")) and (u.get("vendor_status") == "approved")


async def require_vendor(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if not _is_vendor_active(user):
        raise HTTPException(status_code=403, detail="Vendor access only — your account is not an approved vendor")
    return user


# ---------------- USER endpoints ----------------

@api_router.post("/vendor/apply")
async def vendor_apply(payload: VendorApplyRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("registration_paid"):
        raise HTTPException(status_code=403, detail="Complete registration before applying as a vendor")
    if user.get("approval_status") != "approved":
        raise HTTPException(status_code=403, detail="Your account must be approved by admin first")
    shop = (payload.shop_name or "").strip()
    if len(shop) < 3:
        raise HTTPException(status_code=400, detail="Shop name is required (min 3 chars)")
    existing = await db.vendor_applications.find_one({"user_id": user["id"], "status": {"$in": ["pending", "approved"]}})
    if existing:
        raise HTTPException(status_code=400, detail="You already have an active application")
    app_id = str(uuid.uuid4())
    ts = now_utc().isoformat()
    doc = {
        "id": app_id,
        "user_id": user["id"],
        "user_email": user.get("email"),
        "user_name": user.get("name"),
        "shop_name": shop,
        "gst_number": (payload.gst_number or "").strip(),
        "pan_number": (payload.pan_number or "").strip(),
        "bank_name": (payload.bank_name or "").strip(),
        "bank_account": (payload.bank_account or "").strip(),
        "bank_ifsc": (payload.bank_ifsc or "").strip(),
        "description": (payload.description or "").strip(),
        "status": "pending",
        "created_at": ts,
        "updated_at": ts,
    }
    await db.vendor_applications.insert_one(doc)
    # Mark user with vendor_status pending
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "vendor_status": "pending",
        "shop_name": shop,
    }})
    # Notify admins
    async for a in db.users.find({"role": "admin", "admin_role": {"$in": ["super_admin", "support", "finance"]}}, {"id": 1, "_id": 0}):
        try:
            await _create_notification(a["id"], "vendor", "New vendor application", f"{user.get('name') or user.get('email')} applied with shop '{shop}'")
        except Exception:
            pass
    doc.pop("_id", None)
    return {"ok": True, "application": doc}


@api_router.get("/vendor/me/status")
async def vendor_my_status(user: Dict[str, Any] = Depends(get_current_user)):
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    app = await db.vendor_applications.find_one(
        {"user_id": user["id"]},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return {
        "is_vendor": bool(fresh.get("is_vendor")),
        "vendor_status": fresh.get("vendor_status") or "none",
        "shop_name": fresh.get("shop_name"),
        "application": app,
    }


@api_router.get("/vendor/me/stats")
async def vendor_my_stats(vendor: Dict[str, Any] = Depends(require_vendor)):
    today_iso = now_utc().date().isoformat()
    sales = await db.vendor_sales.find({"vendor_id": vendor["id"]}, {"_id": 0}).to_list(5000)
    total_sales = sum(s.get("line_total", 0) for s in sales)
    total_earnings = sum(s.get("vendor_share", 0) for s in sales)
    today_earnings = sum(s.get("vendor_share", 0) for s in sales if (s.get("created_at") or "").startswith(today_iso))
    today_orders = len({s.get("order_id") for s in sales if (s.get("created_at") or "").startswith(today_iso)})
    products_count = await db.products.count_documents({"vendor_id": vendor["id"]})
    published_count = await db.products.count_documents({"vendor_id": vendor["id"], "is_published": True})
    return {
        "total_sales": round(total_sales, 2),
        "total_earnings": round(total_earnings, 2),
        "today_earnings": round(today_earnings, 2),
        "today_orders": today_orders,
        "all_orders": len({s.get("order_id") for s in sales}),
        "products_count": products_count,
        "published_count": published_count,
        "wallet_balance": round(float(vendor.get("wallet_balance") or 0), 2),
    }


@api_router.get("/vendor/me/products")
async def vendor_my_products(vendor: Dict[str, Any] = Depends(require_vendor)):
    items = await db.products.find({"vendor_id": vendor["id"]}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items


@api_router.post("/vendor/me/products")
async def vendor_create_product(p: ProductCreate, vendor: Dict[str, Any] = Depends(require_vendor)):
    if (p.price or 0) <= 0:
        raise HTTPException(status_code=400, detail="Price must be > 0")
    if not (p.name or "").strip():
        raise HTTPException(status_code=400, detail="Name is required")
    doc = {
        "id": str(uuid.uuid4()),
        **{k: v for k, v in p.dict().items() if k != "vendor_id"},
        "vendor_id": vendor["id"],          # force-stamp
        "vendor_email": vendor.get("email"),
        "created_at": now_utc().isoformat(),
    }
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.patch("/vendor/me/products/{product_id}")
async def vendor_update_product(product_id: str, payload: ProductUpdate, vendor: Dict[str, Any] = Depends(require_vendor)):
    target = await db.products.find_one({"id": product_id})
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    if target.get("vendor_id") != vendor["id"]:
        raise HTTPException(status_code=403, detail="Not your product")
    update = {k: v for k, v in payload.dict().items() if v is not None and k != "vendor_id"}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.products.update_one({"id": product_id}, {"$set": update})
    fresh = await db.products.find_one({"id": product_id}, {"_id": 0})
    return fresh


@api_router.delete("/vendor/me/products/{product_id}")
async def vendor_delete_product(product_id: str, vendor: Dict[str, Any] = Depends(require_vendor)):
    target = await db.products.find_one({"id": product_id})
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    if target.get("vendor_id") != vendor["id"]:
        raise HTTPException(status_code=403, detail="Not your product")
    await db.products.delete_one({"id": product_id})
    await db.cart_items.delete_many({"product_id": product_id})
    return {"ok": True}


@api_router.get("/vendor/me/sales")
async def vendor_my_sales(vendor: Dict[str, Any] = Depends(require_vendor)):
    items = await db.vendor_sales.find({"vendor_id": vendor["id"]}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return {"items": items, "total": len(items)}


# ---------------- ADMIN endpoints ----------------

@api_router.get("/admin/vendor-applications")
async def admin_list_vendor_apps(
    status: Optional[str] = "pending",
    admin: Dict[str, Any] = Depends(require_admin),
):
    q: Dict[str, Any] = {}
    if status and status in VENDOR_STATUSES:
        q["status"] = status
    items = await db.vendor_applications.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    counts = {
        "pending": await db.vendor_applications.count_documents({"status": "pending"}),
        "approved": await db.vendor_applications.count_documents({"status": "approved"}),
        "rejected": await db.vendor_applications.count_documents({"status": "rejected"}),
        "suspended": await db.vendor_applications.count_documents({"status": "suspended"}),
    }
    return {"items": items, "total": len(items), "counts": counts}


@api_router.post("/admin/vendor-applications/{app_id}/approve")
async def admin_approve_vendor(app_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance"))):
    a = await db.vendor_applications.find_one({"id": app_id})
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")
    if a.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    ts = now_utc().isoformat()
    await db.vendor_applications.update_one({"id": app_id}, {"$set": {
        "status": "approved",
        "approved_at": ts,
        "approved_by": admin["id"],
        "approved_by_email": admin.get("email"),
        "updated_at": ts,
    }})
    await db.users.update_one({"id": a["user_id"]}, {"$set": {
        "is_vendor": True,
        "vendor_status": "approved",
        "shop_name": a.get("shop_name"),
        "vendor_approved_at": ts,
    }})
    try:
        await _create_notification(a["user_id"], "vendor", "Vendor account approved!", "You can now list and sell products.")
    except Exception:
        pass
    fresh = await db.vendor_applications.find_one({"id": app_id}, {"_id": 0})
    return {"ok": True, "application": fresh}


@api_router.post("/admin/vendor-applications/{app_id}/reject")
async def admin_reject_vendor(app_id: str, payload: VendorRejectRequest, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance"))):
    a = await db.vendor_applications.find_one({"id": app_id})
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")
    if a.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    ts = now_utc().isoformat()
    await db.vendor_applications.update_one({"id": app_id}, {"$set": {
        "status": "rejected",
        "rejection_reason": (payload.reason or "").strip(),
        "rejected_at": ts,
        "rejected_by": admin["id"],
        "rejected_by_email": admin.get("email"),
        "updated_at": ts,
    }})
    await db.users.update_one({"id": a["user_id"]}, {"$set": {"vendor_status": "rejected"}})
    try:
        await _create_notification(a["user_id"], "vendor", "Vendor application rejected", payload.reason or "Please contact support for details.")
    except Exception:
        pass
    fresh = await db.vendor_applications.find_one({"id": app_id}, {"_id": 0})
    return {"ok": True, "application": fresh}


@api_router.get("/admin/vendors")
async def admin_list_vendors(admin: Dict[str, Any] = Depends(require_admin)):
    vendors = await db.users.find({"is_vendor": True}, {"_id": 0, "hashed_password": 0}).sort("vendor_approved_at", -1).to_list(2000)
    out: List[Dict[str, Any]] = []
    for v in vendors:
        sales = await db.vendor_sales.find({"vendor_id": v["id"]}, {"_id": 0}).to_list(5000)
        out.append({
            **v,
            "total_sales": round(sum(s.get("line_total", 0) for s in sales), 2),
            "total_earnings": round(sum(s.get("vendor_share", 0) for s in sales), 2),
            "products_count": await db.products.count_documents({"vendor_id": v["id"]}),
        })
    return {"items": out, "total": len(out)}


@api_router.post("/admin/vendors/{user_id}/suspend")
async def admin_suspend_vendor(user_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance"))):
    u = await db.users.find_one({"id": user_id})
    if not u or not u.get("is_vendor"):
        raise HTTPException(status_code=404, detail="Vendor not found")
    await db.users.update_one({"id": user_id}, {"$set": {"vendor_status": "suspended"}})
    # Unpublish all of their products
    await db.products.update_many({"vendor_id": user_id}, {"$set": {"is_published": False}})
    try:
        await _create_notification(user_id, "vendor", "Vendor account suspended", "Contact support for clarification.")
    except Exception:
        pass
    return {"ok": True}


@api_router.post("/admin/vendors/{user_id}/reactivate")
async def admin_reactivate_vendor(user_id: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance"))):
    u = await db.users.find_one({"id": user_id})
    if not u or not u.get("is_vendor"):
        raise HTTPException(status_code=404, detail="Vendor not found")
    await db.users.update_one({"id": user_id}, {"$set": {"vendor_status": "approved"}})
    try:
        await _create_notification(user_id, "vendor", "Vendor account reactivated", "Welcome back! Your products can be published again.")
    except Exception:
        pass
    return {"ok": True}


# ============================================================
# SERVICES MARKETPLACE — admin-approved peer-to-peer service directory
# ============================================================
# Users apply to be listed as a service provider with their pincode + service
# + charge. Admin approves. Approved providers show up in /services for any
# logged-in user to browse. Other users can book a service which deducts the
# charge from the customer's wallet and credits the provider's wallet (minus
# the platform's `vendor_commission_pct` cut going to the admin).


@api_router.post("/service/apply")
async def service_apply(payload: ServiceApplyRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role") == "admin":
        raise HTTPException(status_code=400, detail="Admins cannot apply as service providers")
    if not user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Pay registration first")
    # Reject if there's already a pending or approved application
    existing = await db.service_applications.find_one(
        {"user_id": user["id"], "status": {"$in": ["pending", "approved"]}}
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"You already have a {existing['status']} service application")
    app_id = str(uuid.uuid4())
    ts = now_utc().isoformat()
    # Resolve category: if category_id provided, look up name from collection
    category_name = payload.service_category.strip()
    cat_doc = None
    if payload.category_id:
        cat_doc = await db.service_categories.find_one({"id": payload.category_id, "active": True})
        if cat_doc:
            category_name = cat_doc.get("name") or category_name
    # Validate languages (subset of allowed codes)
    allowed_langs = {"en", "te", "hi", "ta"}
    langs = [l for l in (payload.languages or []) if l in allowed_langs]
    doc = {
        "id": app_id,
        "user_id": user["id"],
        "name": user.get("name"),
        "email": user.get("email"),
        "phone": user.get("phone"),
        "referral_code": user.get("referral_code"),
        "service_name": payload.service_name.strip(),
        "service_category": category_name,
        "category_id": cat_doc["id"] if cat_doc else None,
        "languages": langs,
        "pincode": payload.pincode,
        "charge": float(payload.charge),
        "description": (payload.description or "").strip() or None,
        "status": "pending",
        "created_at": ts,
        "reviewed_at": None,
        "reviewed_by": None,
        "reject_reason": None,
    }
    await db.service_applications.insert_one(doc)
    # Mark user with pending state
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"service_status": "pending"}},
    )
    doc.pop("_id", None)
    return {"ok": True, "application": doc}


@api_router.get("/service/me")
async def service_me(user: Dict[str, Any] = Depends(get_current_user)):
    """Return the user's current service-provider state — any application + their listing if approved."""
    app = await db.service_applications.find_one(
        {"user_id": user["id"]},
        sort=[("created_at", -1)],
    )
    if app:
        app.pop("_id", None)
    fresh = await db.users.find_one({"id": user["id"]})
    return {
        "application": app,
        "is_service_provider": bool(fresh and fresh.get("is_service_provider")),
        "service_status": (fresh or {}).get("service_status"),
        "listing": (
            {
                "service_name": fresh.get("service_name"),
                "service_category": fresh.get("service_category"),
                "service_pincode": fresh.get("service_pincode"),
                "service_charge": fresh.get("service_charge"),
                "service_description": fresh.get("service_description"),
            }
            if fresh and fresh.get("is_service_provider")
            else None
        ),
    }


@api_router.get("/admin/service-applications")
async def admin_list_service_applications(
    status: Optional[str] = "pending",
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    q: Dict[str, Any] = {}
    if status and status != "all":
        q["status"] = status
    items = await db.service_applications.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    pending_n = await db.service_applications.count_documents({"status": "pending"})
    approved_n = await db.service_applications.count_documents({"status": "approved"})
    rejected_n = await db.service_applications.count_documents({"status": "rejected"})
    return {
        "items": items,
        "counts": {"pending": pending_n, "approved": approved_n, "rejected": rejected_n, "total": pending_n + approved_n + rejected_n},
    }


@api_router.post("/admin/service-applications/{aid}/approve")
async def admin_approve_service(aid: str, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager"))):
    app = await db.service_applications.find_one({"id": aid})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if app["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    ts = now_utc().isoformat()
    await db.service_applications.update_one(
        {"id": aid},
        {"$set": {"status": "approved", "reviewed_at": ts, "reviewed_by": admin["id"]}},
    )
    await db.users.update_one(
        {"id": app["user_id"]},
        {"$set": {
            "is_service_provider": True,
            "service_status": "approved",
            "service_name": app["service_name"],
            "service_category": app["service_category"],
            "category_id": app.get("category_id"),
            "service_languages": app.get("languages") or [],
            "service_pincode": app["pincode"],
            "service_charge": app["charge"],
            "service_description": app.get("description"),
            "service_approved_at": ts,
        }},
    )
    await _create_notification(
        app["user_id"], "service", "Service listing approved",
        f"You're now listed as a {app['service_category']} in pincode {app['pincode']}.",
    )
    await _audit_log(admin, "service.approve", "user", app["user_id"], {"service": app["service_name"]})
    return {"ok": True}


@api_router.post("/admin/service-applications/{aid}/reject")
async def admin_reject_service(aid: str, payload: ServiceRejectRequest, admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager"))):
    app = await db.service_applications.find_one({"id": aid})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    if app["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    ts = now_utc().isoformat()
    reason = (payload.reason or "").strip() or None
    await db.service_applications.update_one(
        {"id": aid},
        {"$set": {"status": "rejected", "reviewed_at": ts, "reviewed_by": admin["id"], "reject_reason": reason}},
    )
    await db.users.update_one(
        {"id": app["user_id"]},
        {"$set": {"service_status": "rejected"}},
    )
    await _create_notification(
        app["user_id"], "service", "Service listing rejected",
        reason or "Your service application was rejected.",
    )
    await _audit_log(admin, "service.reject", "user", app["user_id"], {"reason": reason})
    return {"ok": True}


@api_router.get("/services")
async def list_services(
    q: Optional[str] = None,
    pincode: Optional[str] = None,
    category: Optional[str] = None,
    category_id: Optional[str] = None,
    language: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_km: Optional[float] = None,
):
    """Public listing of approved service providers. Customer-facing — NO AUTH
    REQUIRED so anonymous browsers can discover services before they sign up.

    When `lat` and `lng` are supplied, results are sorted by distance using a
    Mongo `$geoNear` aggregation. Optional `radius_km` clamps to a max distance.
    Each row includes `distance_km` (or null) and `is_active` (true if the
    provider broadcast a heartbeat within the last ACTIVE_WINDOW_MIN minutes).
    """
    base_filt: Dict[str, Any] = {"is_service_provider": True}
    if pincode:
        base_filt["service_pincode"] = pincode
    if category_id:
        base_filt["category_id"] = category_id
    elif category and category != "all":
        base_filt["service_category"] = category
    if language:
        base_filt["service_languages"] = language
    if q:
        rgx = {"$regex": re.escape(q), "$options": "i"}
        base_filt["$or"] = [{"name": rgx}, {"service_name": rgx}, {"service_category": rgx}]

    project = {
        "_id": 0,
        "id": 1, "name": 1, "phone": 1, "email": 1, "referral_code": 1,
        "service_name": 1, "service_category": 1, "category_id": 1,
        "service_languages": 1,
        "service_pincode": 1, "service_charge": 1, "service_description": 1,
        "service_approved_at": 1,
        "service_location": 1, "location_sharing": 1, "location_updated_at": 1,
    }

    # ----- Geo path ----------------------------------------------------------
    if lat is not None and lng is not None:
        # `$geoNear` MUST be the first stage in an aggregation pipeline.
        # NEW (Feb-2026): no upper-bound on distance by default — caller can
        # still pass `radius_km` to clamp. Without a cap we surface EVERY
        # approved provider with a location, sorted by distance, so users in
        # remote areas can still discover services that are far away.
        geo_stage: Dict[str, Any] = {
            "near": {"type": "Point", "coordinates": [float(lng), float(lat)]},
            "distanceField": "distance_m",
            "spherical": True,
            "query": {**base_filt, "service_location": {"$type": "object"}},
        }
        if radius_km is not None:
            geo_stage["maxDistance"] = float(radius_km) * 1000.0
        pipeline: List[Dict[str, Any]] = [
            {"$geoNear": geo_stage},
            {"$project": {**project, "distance_m": 1}},
            {"$limit": 500},
        ]
        try:
            geo_rows = await db.users.aggregate(pipeline).to_list(300)
        except Exception as e:
            logger.warning(f"$geoNear failed (likely missing 2dsphere index): {e}")
            geo_rows = []
        # Also fetch providers without location, append at the end (no distance).
        no_loc_filt = {**base_filt, "$or": [
            {"service_location": None},
            {"service_location": {"$exists": False}},
        ]}
        no_loc_rows = await db.users.find(no_loc_filt, project).sort("service_approved_at", -1).to_list(300)

        def _enrich(r: Dict[str, Any]) -> Dict[str, Any]:
            d_m = r.get("distance_m")
            r["distance_km"] = round(d_m / 1000.0, 2) if d_m is not None else None
            r["is_active"] = _is_active(r.get("location_updated_at"))
            r.pop("distance_m", None)
            r.pop("service_location", None)  # don't leak raw GeoJSON
            return r
        items = [_enrich(r) for r in geo_rows] + [_enrich(r) for r in no_loc_rows]
        return {"items": items, "total": len(items), "geo": True}

    # ----- Non-geo path (default) -------------------------------------------
    rows = await db.users.find(base_filt, project).sort("service_approved_at", -1).to_list(300)
    for r in rows:
        r["distance_km"] = None
        r["is_active"] = _is_active(r.get("location_updated_at"))
        r.pop("service_location", None)
    return {"items": rows, "total": len(rows), "geo": False}


@api_router.get("/services/categories")
async def list_service_categories():
    """Public list of admin-curated service categories (active only) sorted by
    sort_order — NO AUTH REQUIRED so anonymous browsers see categories on
    the landing/discovery page."""
    cats = await db.service_categories.find(
        {"active": True}, {"_id": 0},
    ).sort([("sort_order", 1), ("name", 1)]).to_list(200)
    # Augment each with live provider count
    for c in cats:
        c["provider_count"] = await db.users.count_documents({
            "is_service_provider": True,
            "$or": [{"category_id": c["id"]}, {"service_category": c["name"]}],
        })
    return {"categories": cats}


# ----- Admin: Service Categories CRUD -----

DEFAULT_SERVICE_CATEGORIES = [
    {"name": "Construction Labour",   "slug": "construction-labour",   "icon": "tool",         "color": "#EA580C"},
    {"name": "Internet Installation", "slug": "internet-installation", "icon": "wifi",         "color": "#2563EB"},
    {"name": "Plumber",               "slug": "plumber",               "icon": "droplet",      "color": "#0891B2"},
    {"name": "Electrician",           "slug": "electrician",           "icon": "zap",          "color": "#CA8A04"},
    {"name": "Painter",               "slug": "painter",               "icon": "edit-3",       "color": "#9333EA"},
    {"name": "Carpenter",             "slug": "carpenter",             "icon": "settings",     "color": "#92400E"},
    {"name": "CCTV Technician",       "slug": "cctv-technician",       "icon": "camera",       "color": "#475569"},
    {"name": "AC Repair",             "slug": "ac-repair",             "icon": "wind",         "color": "#0EA5E9"},
    {"name": "Cleaning",              "slug": "cleaning",              "icon": "feather",      "color": "#10B981"},
    {"name": "Water Tank Cleaning",   "slug": "water-tank-cleaning",   "icon": "trash-2",      "color": "#06B6D4"},
    {"name": "Toilet Cleaner",        "slug": "toilet-cleaner",        "icon": "shield",       "color": "#65A30D"},
    {"name": "House Construction Labour", "slug": "house-construction-labour", "icon": "home", "color": "#DC2626"},
    {"name": "Mobile Repair",         "slug": "mobile-repair",         "icon": "smartphone",   "color": "#DB2777"},
]


async def seed_service_categories():
    """Idempotent seed: create the 13 default categories if collection is empty."""
    existing = await db.service_categories.count_documents({})
    if existing > 0:
        return 0
    ts = now_utc().isoformat()
    docs = []
    for i, c in enumerate(DEFAULT_SERVICE_CATEGORIES):
        docs.append({
            "id": str(uuid.uuid4()),
            "name": c["name"],
            "slug": c["slug"],
            "icon": c["icon"],
            "color": c["color"],
            "sort_order": (i + 1) * 10,
            "active": True,
            "created_at": ts,
        })
    if docs:
        await db.service_categories.insert_many(docs)
    return len(docs)


@api_router.get("/admin/service-categories")
async def admin_list_service_categories(_: Dict[str, Any] = Depends(require_admin)):
    cats = await db.service_categories.find({}, {"_id": 0}).sort([("sort_order", 1), ("name", 1)]).to_list(200)
    for c in cats:
        c["provider_count"] = await db.users.count_documents({
            "is_service_provider": True,
            "$or": [{"category_id": c["id"]}, {"service_category": c["name"]}],
        })
    return {"categories": cats}


@api_router.post("/admin/service-categories")
async def admin_create_service_category(
    payload: ServiceCategoryCreate,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    name = payload.name.strip()
    slug = (payload.slug or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"))[:40]
    # Reject duplicates by name or slug
    dup = await db.service_categories.find_one({"$or": [{"name": name}, {"slug": slug}]})
    if dup:
        raise HTTPException(status_code=400, detail=f"Category '{dup.get('name')}' already exists")
    cid = str(uuid.uuid4())
    doc = {
        "id": cid,
        "name": name,
        "slug": slug,
        "icon": payload.icon or "briefcase",
        "color": payload.color or "#2563EB",
        "sort_order": int(payload.sort_order or 0),
        "active": True if payload.active is None else bool(payload.active),
        "created_at": now_utc().isoformat(),
    }
    await db.service_categories.insert_one(doc)
    await _audit_log(admin, "service_category.create", "service_category", cid, {"name": name})
    doc.pop("_id", None)
    return {"ok": True, "category": doc}


@api_router.patch("/admin/service-categories/{cat_id}")
async def admin_update_service_category(
    cat_id: str,
    payload: ServiceCategoryUpdate,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    existing = await db.service_categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if "name" in update:
        update["name"] = update["name"].strip()
    if "slug" in update:
        update["slug"] = re.sub(r"[^a-z0-9]+", "-", update["slug"].lower()).strip("-")[:40]
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.service_categories.update_one({"id": cat_id}, {"$set": update})
    await _audit_log(admin, "service_category.update", "service_category", cat_id, update)
    fresh = await db.service_categories.find_one({"id": cat_id}, {"_id": 0})
    return {"ok": True, "category": fresh}


@api_router.delete("/admin/service-categories/{cat_id}")
async def admin_delete_service_category(
    cat_id: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    existing = await db.service_categories.find_one({"id": cat_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    # Check if any provider is currently linked
    in_use = await db.users.count_documents({"is_service_provider": True, "category_id": cat_id})
    if in_use > 0:
        # Soft-delete instead of hard-delete to avoid orphaning providers
        await db.service_categories.update_one({"id": cat_id}, {"$set": {"active": False}})
        await _audit_log(admin, "service_category.deactivate", "service_category", cat_id, {"in_use": in_use})
        return {"ok": True, "deactivated": True, "providers_using": in_use}
    await db.service_categories.delete_one({"id": cat_id})
    await _audit_log(admin, "service_category.delete", "service_category", cat_id, {"name": existing.get("name")})
    return {"ok": True, "deleted": True}


# ----- Provider live-location broadcast (Phase 2 — GPS) ------------------
ACTIVE_WINDOW_MIN = 30  # provider considered "active" if heartbeat ≤ 30 min ago


@api_router.post("/service/me/location")
async def provider_update_location(
    payload: ProviderLocationUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Broadcast current GPS coordinates.

    As of 2025-06 this is open to ANY authenticated user — both service
    providers (so they appear in nearby-worker search) and regular customers
    (so admins can see where users are coming from in the admin user list).
    Coordinates are stored as a GeoJSON Point so we can use Mongo's
    `$geoNear` to surface nearby workers to customers. When `sharing=false`
    the location is cleared.
    """
    ts = now_utc().isoformat()
    if payload.sharing is False:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "service_location": None,
                "location_sharing": False,
                "location_updated_at": ts,
            }},
        )
        return {"ok": True, "sharing": False}
    # Persist GeoJSON Point — coordinates order is [longitude, latitude] (Mongo convention)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "service_location": {
                "type": "Point",
                "coordinates": [float(payload.lng), float(payload.lat)],
                "accuracy_m": float(payload.accuracy_m) if payload.accuracy_m is not None else None,
            },
            "location_sharing": True,
            "location_updated_at": ts,
        }},
    )
    return {"ok": True, "sharing": True, "updated_at": ts}


def _is_active(updated_at: Optional[str]) -> bool:
    if not updated_at:
        return False
    try:
        from datetime import datetime, timezone, timedelta
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt) <= timedelta(minutes=ACTIVE_WINDOW_MIN)
    except Exception:
        return False


async def _ensure_geo_index():
    """Create 2dsphere index on service_location once."""
    try:
        await db.users.create_index([("service_location", "2dsphere")])
    except Exception as e:
        logger.warning(f"2dsphere index creation failed: {e}")


# ====================================================================
# Distributor Network — pincode area mapping (admin module)
# ====================================================================
PINCODES_CSV_PATH = "/app/backend/data/pincodes.csv"


async def seed_pincodes():
    """Idempotent: load all India pincodes from /app/backend/data/pincodes.csv
    into `pincodes` collection. Skips if collection already populated.

    Production-safe: aggressive early-exit checks PLUS a robust per-row upsert
    fallback so we NEVER spam 2 MB BulkWriteError dicts into the container
    logs on restart. The earlier version logged the full BulkWriteError on
    every Atlas reconnect / pod restart, producing ~2 MB warning lines that
    overwhelm CloudWatch / log aggregators in production.
    """
    try:
        # Phase 1 — early exit if ANY pincodes already exist. This is the
        # hot-path on every container restart in production. We deliberately
        # use a fast `estimated_document_count()` (constant-time metadata
        # query, no scan) instead of `count_documents({})` (full scan).
        try:
            existing = await db.pincodes.estimated_document_count()
        except Exception:
            existing = await db.pincodes.count_documents({}, limit=1)
        if existing >= 1000:  # any reasonable amount → already seeded
            return 0

        import csv
        from pathlib import Path
        if not Path(PINCODES_CSV_PATH).exists():
            logger.warning(f"Pincode CSV missing at {PINCODES_CSV_PATH}; skipping seed")
            return 0

        # Phase 2 — ensure the unique index EXISTS BEFORE we start inserting,
        # so even if multiple replicas race to seed, the loser's duplicates
        # are rejected cheaply at the row level (not as a 2 MB batch error).
        try:
            await db.pincodes.create_index("pincode", unique=True)
            await db.pincodes.create_index("state")
            await db.pincodes.create_index("district")
        except Exception as _idx_err:
            logger.info(f"Pincode index already present: {str(_idx_err)[:120]}")

        # Phase 3 — parse CSV (dedupe in memory so we never send a duplicate
        # row to MongoDB ourselves).
        seen: Dict[str, Dict[str, Any]] = {}
        with open(PINCODES_CSV_PATH, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pin = (row.get("Pincode") or "").strip()
                if not pin or len(pin) != 6 or not pin.isdigit():
                    continue
                office = (row.get("OfficeName") or "").upper()
                district = (row.get("District") or "").upper()
                state = (row.get("StateName") or "").upper()
                if pin == "999999" or "TEST" in office or "TEST" in district or "TEST" in state:
                    continue
                if pin in seen:
                    continue
                seen[pin] = {
                    "pincode": pin,
                    "district": (row.get("District") or "").strip().title(),
                    "state": (row.get("StateName") or "").strip().title(),
                    "region": (row.get("RegionName") or "").strip(),
                    "office": (row.get("OfficeName") or "").strip(),
                }
        if not seen:
            return 0

        # Phase 4 — bulk insert with ordered=False.  If a duplicate slips
        # through (race between replicas), we catch the BulkWriteError per
        # batch, count the successful inserts, and continue with the next
        # batch.  CRITICAL: we NEVER log the full BulkWriteError dict —
        # only the count — so production logs stay small.
        docs = list(seen.values())
        BATCH = 5000
        total = 0
        dup_total = 0
        for i in range(0, len(docs), BATCH):
            chunk = docs[i : i + BATCH]
            try:
                res = await db.pincodes.insert_many(chunk, ordered=False)
                total += len(res.inserted_ids)
            except Exception as _be:
                # pymongo BulkWriteError has a .details dict with nInserted.
                inserted = 0
                dups = 0
                details = getattr(_be, "details", None)
                if isinstance(details, dict):
                    inserted = int(details.get("nInserted") or 0)
                    dups = len(details.get("writeErrors") or [])
                total += inserted
                dup_total += dups
        if dup_total:
            # Single-line, fixed-size log — never 2 MB.
            logger.info(f"Pincode seed: {total} inserted, {dup_total} dups skipped")
        return total
    except Exception as e:
        # Last-resort guard: truncate at 200 chars (was 500). This branch
        # should ~never fire now that the per-batch handler above swallows
        # BulkWriteError.
        msg = str(e)
        if len(msg) > 200:
            msg = msg[:200] + f" ...[trunc {len(str(e))}]"
        logger.warning(f"Pincode seed skipped: {msg}")
        return 0


async def _ensure_distributor_indexes():
    """Unique index on distributor_assignments.pincode (exclusive territory)."""
    try:
        await db.distributor_assignments.create_index("pincode", unique=True)
        await db.distributor_assignments.create_index("distributor_id")
    except Exception as e:
        logger.warning(f"distributor index creation failed: {e}")


# Pincode routes moved to /app/backend/routes/pincodes.py (Phase 2B refactor)


@api_router.post("/admin/users/{user_id}/distributor")
async def admin_promote_distributor(
    user_id: str,
    payload: DistributorPromote,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    """Toggle a user's `is_distributor` flag."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.get("role") == "admin":
        raise HTTPException(status_code=400, detail="Admins cannot also be distributors")
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"is_distributor": bool(payload.is_distributor)}},
    )
    # If demoting, drop all their pincode mappings
    if not payload.is_distributor:
        await db.distributor_assignments.delete_many({"distributor_id": user_id})
    await _audit_log(admin, "distributor.toggle", "user", user_id,
                     {"is_distributor": payload.is_distributor})
    return {"ok": True, "is_distributor": payload.is_distributor}


@api_router.get("/admin/distributors")
async def admin_list_distributors(_: Dict[str, Any] = Depends(require_admin)):
    """List all users marked as distributors with their assigned pincode counts."""
    rows = await db.users.find(
        {"is_distributor": True},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "referral_code": 1},
    ).sort("name", 1).to_list(2000)
    # Attach pincode counts
    for r in rows:
        r["pincode_count"] = await db.distributor_assignments.count_documents(
            {"distributor_id": r["id"]}
        )
    return {"items": rows, "total": len(rows)}


@api_router.get("/admin/distributors/{user_id}/areas")
async def admin_list_distributor_areas(
    user_id: str, _: Dict[str, Any] = Depends(require_admin),
):
    """List the pincodes assigned to one distributor, joined with district/state."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "name": 1, "email": 1, "is_distributor": 1})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    rows = await db.distributor_assignments.find(
        {"distributor_id": user_id}, {"_id": 0},
    ).sort("pincode", 1).to_list(5000)
    # Enrich with pincode metadata (district/state)
    pins = [r["pincode"] for r in rows]
    if pins:
        meta = await db.pincodes.find({"pincode": {"$in": pins}}, {"_id": 0}).to_list(len(pins))
        mmap = {m["pincode"]: m for m in meta}
        for r in rows:
            md = mmap.get(r["pincode"]) or {}
            r["district"] = md.get("district")
            r["state"] = md.get("state")
            r["office"] = md.get("office")
    return {"distributor": u, "items": rows, "total": len(rows)}


@api_router.post("/admin/distributors/{user_id}/areas")
async def admin_assign_distributor_areas(
    user_id: str,
    payload: DistributorAreaAssign,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    """Assign one or more pincodes to a distributor (exclusive territory).
    Any pincode currently held by another distributor is reassigned to this one
    (the most recent assign wins). Pincodes that don't exist in our pincodes
    collection are rejected."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if not u.get("is_distributor"):
        raise HTTPException(status_code=400, detail="User is not marked as distributor. Promote them first.")

    # De-dupe + validate
    pins = sorted({p.strip() for p in payload.pincodes if p and len(p.strip()) == 6 and p.strip().isdigit()})
    if not pins:
        raise HTTPException(status_code=400, detail="No valid 6-digit pincodes provided")

    # Confirm pincodes exist in our master list
    valid_rows = await db.pincodes.find({"pincode": {"$in": pins}}, {"_id": 0, "pincode": 1}).to_list(len(pins))
    valid_set = {r["pincode"] for r in valid_rows}
    invalid = [p for p in pins if p not in valid_set]
    if invalid:
        raise HTTPException(status_code=400,
                            detail=f"{len(invalid)} pincode(s) not in master list: {', '.join(invalid[:5])}{'…' if len(invalid) > 5 else ''}")

    ts = now_utc().isoformat()
    reassigned: List[str] = []
    new_assigns: List[str] = []
    for pin in pins:
        existing = await db.distributor_assignments.find_one({"pincode": pin})
        if existing and existing.get("distributor_id") != user_id:
            reassigned.append(pin)
        elif not existing:
            new_assigns.append(pin)
        await db.distributor_assignments.update_one(
            {"pincode": pin},
            {"$set": {
                "pincode": pin,
                "distributor_id": user_id,
                "distributor_name": u.get("name"),
                "distributor_email": u.get("email"),
                "assigned_at": ts,
                "assigned_by": admin.get("id"),
            }},
            upsert=True,
        )
    await _audit_log(admin, "distributor.areas.assign", "user", user_id,
                     {"new": len(new_assigns), "reassigned": len(reassigned), "total": len(pins)})
    return {"ok": True, "new_assignments": len(new_assigns),
            "reassigned": len(reassigned), "total_now": len(pins)}


@api_router.delete("/admin/distributors/{user_id}/areas/{pincode}")
async def admin_unassign_distributor_area(
    user_id: str,
    pincode: str,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    res = await db.distributor_assignments.delete_one(
        {"distributor_id": user_id, "pincode": pincode},
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await _audit_log(admin, "distributor.areas.unassign", "user", user_id,
                     {"pincode": pincode})
    return {"ok": True}


@api_router.post("/admin/distributors/{user_id}/areas/bulk-unassign")
async def admin_bulk_unassign_distributor_areas(
    user_id: str,
    payload: DistributorAreaAssign,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager")),
):
    """Bulk-remove pincode mappings from a distributor in one request."""
    pins = sorted({p.strip() for p in payload.pincodes if p and p.strip()})
    if not pins:
        raise HTTPException(status_code=400, detail="No pincodes provided")
    res = await db.distributor_assignments.delete_many(
        {"distributor_id": user_id, "pincode": {"$in": pins}}
    )
    await _audit_log(admin, "distributor.areas.bulk_unassign", "user", user_id,
                     {"removed": res.deleted_count, "requested": len(pins)})
    return {"ok": True, "removed": res.deleted_count, "requested": len(pins)}


# (admin_pincodes_in_region moved above admin_pincode_get to fix route precedence)


# ───────────────────────────── SERVICE REVIEWS ──────────────────────────────
# Customers can leave a star-rating + comment on a provider AFTER booking them
# (i.e. they appear in `service_bookings` for that provider). Reviews are
# stored in a dedicated `service_reviews` collection. Average rating + count
# are returned by `/services/{provider_id}/profile` for ID-card display.
class ServiceReviewIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


@api_router.get("/services/{provider_id}/profile")
async def get_service_provider_profile(provider_id: str):
    """Public ID-card profile for a service provider — photo, charge, contact,
    aggregate rating + recent reviews. No auth required so anonymous browsers
    can preview before signing up.
    """
    p = await db.users.find_one(
        {"id": provider_id, "is_service_provider": True},
        {
            "_id": 0, "id": 1, "name": 1, "phone": 1, "email": 1, "referral_code": 1,
            "service_name": 1, "service_category": 1, "category_id": 1,
            "service_languages": 1, "service_pincode": 1, "service_charge": 1,
            "service_description": 1, "service_approved_at": 1,
            "location_updated_at": 1, "profile_image": 1, "kyc_status": 1,
        },
    )
    if not p:
        raise HTTPException(status_code=404, detail="Service provider not found")
    p["is_active"] = _is_active(p.get("location_updated_at"))
    # Reviews aggregate
    agg = await db.service_reviews.aggregate([
        {"$match": {"provider_id": provider_id}},
        {"$group": {"_id": None, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    p["rating_avg"] = round(float(agg[0]["avg"]), 2) if agg else 0.0
    p["rating_count"] = int(agg[0]["count"]) if agg else 0
    # Recent reviews (latest 20)
    reviews_raw = await db.service_reviews.find(
        {"provider_id": provider_id}, {"_id": 0},
    ).sort("created_at", -1).limit(20).to_list(20)
    # Enrich each review with reviewer's name (kept private — only first name).
    for r in reviews_raw:
        u = await db.users.find_one({"id": r.get("user_id")}, {"_id": 0, "name": 1})
        full = (u or {}).get("name", "Customer")
        r["reviewer_name"] = full.split(" ")[0] if full else "Customer"
        r.pop("user_id", None)
    p["reviews"] = reviews_raw
    # Bookings count (informational, drives "trusted by N customers" copy)
    p["bookings_count"] = await db.service_bookings.count_documents({"provider_id": provider_id})
    return p


@api_router.post("/services/{provider_id}/reviews")
async def post_service_review(
    provider_id: str,
    payload: ServiceReviewIn,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if provider_id == user["id"]:
        raise HTTPException(status_code=400, detail="You can't review yourself")
    provider = await db.users.find_one({"id": provider_id, "is_service_provider": True})
    if not provider:
        raise HTTPException(status_code=404, detail="Service provider not found")
    # Must have at least one booking for this provider (anti-spam).
    booked = await db.service_bookings.find_one({"provider_id": provider_id, "customer_id": user["id"]})
    if not booked:
        raise HTTPException(status_code=403, detail="You can only review providers you've booked")
    # Upsert latest review per user — replace if they review again.
    review_doc = {
        "id":           str(uuid.uuid4()),
        "provider_id":  provider_id,
        "user_id":      user["id"],
        "rating":       int(payload.rating),
        "comment":      (payload.comment or "").strip() or None,
        "created_at":   now_utc().isoformat(),
    }
    await db.service_reviews.update_one(
        {"provider_id": provider_id, "user_id": user["id"]},
        {"$set": review_doc},
        upsert=True,
    )
    try:
        await _create_notification(
            provider_id, "service",
            f"New {payload.rating}★ review",
            f"{user.get('name', 'A customer')} left you a review.",
        )
    except Exception:
        pass
    return {"ok": True, "review": review_doc}


@api_router.post("/services/{provider_id}/book")
async def book_service(provider_id: str, payload: ServiceBookRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if provider_id == user["id"]:
        raise HTTPException(status_code=400, detail="You can't book your own service")
    provider = await db.users.find_one({"id": provider_id, "is_service_provider": True})
    if not provider:
        raise HTTPException(status_code=404, detail="Service provider not found")
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=400, detail="Your wallet is frozen")
    charge = float(provider.get("service_charge") or 0)
    if charge <= 0:
        raise HTTPException(status_code=400, detail="Service has no fixed charge — contact provider directly")
    bal = float(user.get("wallet_balance") or 0)
    if bal < charge:
        raise HTTPException(status_code=400, detail=f"Insufficient wallet balance — need ₹{int(charge)}")
    settings = await get_settings()
    provider_pct = float(settings.get("vendor_commission_pct", 70)) / 100.0
    provider_share = round(charge * provider_pct, 2)
    admin_share = round(charge - provider_share, 2)
    book_id = str(uuid.uuid4())
    ts = now_utc().isoformat()
    # ATOMIC wallet debit — guards against rapid double-clicks.
    debit_res = await db.users.update_one(
        {"id": user["id"], "wallet_balance": {"$gte": charge}},
        {"$inc": {"wallet_balance": -charge}},
    )
    if debit_res.modified_count == 0:
        raise HTTPException(status_code=400, detail=f"Insufficient wallet balance — need ₹{int(charge)}")
    try:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "type": "service_booking",
            "amount": -charge,
            "status": "success",
            "description": f"Booked service: {provider.get('service_name')} from {provider.get('name')}",
            "booking_id": book_id,
            "created_at": ts,
        })
    except DuplicateKeyError:
        pass
    # Credit provider
    await db.users.update_one(
        {"id": provider_id},
        {"$inc": {"wallet_balance": provider_share, "total_earned": provider_share}},
    )
    try:
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": provider_id,
            "type": "service_earning",
            "amount": provider_share,
            "status": "success",
            "description": f"Service booking from {user.get('name')} (₹{int(charge)} - ₹{int(admin_share)} platform fee)",
            "booking_id": book_id,
            "created_at": ts,
        })
    except DuplicateKeyError:
        pass
    # Credit admin platform fee
    if admin_share > 0:
        admin = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
        if admin:
            await credit_admin_bucket("service_margin", admin_share, also_total_earned=True)
            try:
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin["id"],
                    "type": "service_commission",
                    "amount": admin_share,
                    "status": "success",
                    "description": f"Service platform fee from {provider.get('name')} (booking by {user.get('name')})",
                    "booking_id": book_id,
                    "source_user_name": user.get("name"),
                    "created_at": ts,
                })
            except DuplicateKeyError:
                pass
    booking = {
        "id": book_id,
        "customer_id": user["id"],
        "customer_name": user.get("name"),
        "customer_phone": user.get("phone"),
        "provider_id": provider_id,
        "provider_name": provider.get("name"),
        "provider_phone": provider.get("phone"),
        "service_name": provider.get("service_name"),
        "service_category": provider.get("service_category"),
        "charge": charge,
        "provider_share": provider_share,
        "admin_share": admin_share,
        "status": "confirmed",
        "scheduled_date": payload.scheduled_date,
        "notes": (payload.notes or "").strip() or None,
        "created_at": ts,
        "completed_at": None,
    }
    await db.service_bookings.insert_one(booking)
    booking.pop("_id", None)
    # Notifications
    await _create_notification(
        provider_id, "service", "New service booking",
        f"{user.get('name')} booked your {provider.get('service_name')} (+₹{int(provider_share)} credited)",
    )
    await _create_notification(
        user["id"], "service", "Service booking confirmed",
        f"You've booked {provider.get('service_name')} from {provider.get('name')} for ₹{int(charge)}.",
    )
    return {"ok": True, "booking": booking}


@api_router.get("/services/bookings/me")
async def my_service_bookings(role: Optional[str] = "all", user: Dict[str, Any] = Depends(get_current_user)):
    """Return both bookings I made (customer) and bookings on my services (provider)."""
    q: Dict[str, Any]
    if role == "customer":
        q = {"customer_id": user["id"]}
    elif role == "provider":
        q = {"provider_id": user["id"]}
    else:
        q = {"$or": [{"customer_id": user["id"]}, {"provider_id": user["id"]}]}
    rows = await db.service_bookings.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"items": rows, "total": len(rows)}


# Include router
app.include_router(api_router)

# Phase 2B refactor: extracted routers, mounted at /api so URLs are unchanged
# from the client's perspective.
app.include_router(branding_router.router, prefix="/api")
app.include_router(notifications_router.router, prefix="/api")
app.include_router(products_public_router.router, prefix="/api")
app.include_router(promo_banners_router.router, prefix="/api")
app.include_router(shop_layout_router.router, prefix="/api")
app.include_router(shop_layout_analytics_router.router, prefix="/api")
app.include_router(chat_router.router, prefix="/api")
app.include_router(products_extended_router.router, prefix="/api")
app.include_router(products_ai_router.router, prefix="/api")
app.include_router(shop_categories_router.router, prefix="/api")
app.include_router(tickets_router.router, prefix="/api")
app.include_router(pincodes_router.router, prefix="/api")
app.include_router(legal_pages_router.router, prefix="/api")
app.include_router(upi_manual_router.router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
