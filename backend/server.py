from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import logging
import asyncio
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

import httpx
import jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Query, Body
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field
from models import (
    RegisterRequest,
    LoginRequest,
    BankUpdate,
    ProductCreate,
    ProductUpdate,
    GoogleExchange,
    CreateOrderResponse,
    VerifyPaymentRequest,
    PaymentFailureRequest,
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
    ProviderLocationUpdate,
    DistributorAreaAssign,
    DistributorPromote,
    AdminTallyWithdrawRequest,
    RevealPhoneRequest,
    AddressUpdateRequest,
)


# ------------------ Core imports ------------------
# Phase 2A refactor: shared utilities live in /app/backend/core/.
# server.py keeps its existing variable names by re-binding the imports below
# so the route handlers further down DO NOT need to change.
from core.db import client, db  # noqa: E402
from core.config import (  # noqa: E402
    JWT_SECRET,
    JWT_ALGORITHM,
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    REFERRAL_GST_PCT,
)
from core.password_recovery import password_fields  # noqa: E402
from core import shop_money  # noqa: E402
from core import bank  # noqa: E402
from core import gst as _gst_engine  # noqa: E402

# Assignable admin sub-roles. The four scoped ones are what the promote screen
# offers now; manager/support/finance stay valid for admins promoted earlier.
ADMIN_SUB_ROLES = (
    "super_admin",
    "products_manager", "layout_manager", "order_manager", "vendor_service_manager",
    "manager", "support", "finance",
)
from core.security import (  # noqa: E402
    security,
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    new_session_id,
    register_session,
    revoke_session,
    rotate_session,
    rotation_target,
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
    SUPER_PWD_FORMAT_DESC,
    validate_super_password_format,
    get_super_password_hash,
    verify_super_password,
    DANGER_PIN_FORMAT_DESC,
    validate_danger_pin_format,
    get_danger_pin_hash,
    verify_danger_pin,
)
# Phase 2B: shared notification helper (also re-exported for legacy
# `from server import _create_notification` call-sites in routes/*.py).
from core.notifications import create_notification as _create_notification  # noqa: E402,F401
from routes import branding as branding_router  # noqa: E402
from routes import notifications as notifications_router  # noqa: E402
from routes import products_public as products_public_router  # noqa: E402
from routes import products_master as products_master_router  # noqa: E402
from routes import products_master_specs as products_master_specs_router  # noqa: E402
from routes import products_master_images as products_master_images_router  # noqa: E402
from routes import promo_banners as promo_banners_router  # noqa: E402
from routes import shop_layout as shop_layout_router  # noqa: E402
from routes import shop_layout_analytics as shop_layout_analytics_router  # noqa: E402
from routes import chat as chat_router  # noqa: E402
from routes import chat_audit as chat_audit_router  # noqa: E402
from routes import products_extended as products_extended_router  # noqa: E402
from routes import products_ai as products_ai_router  # noqa: E402
from routes import shop_categories as shop_categories_router  # noqa: E402
from routes import tickets as tickets_router  # noqa: E402
from routes import pincodes as pincodes_router  # noqa: E402
from routes import legal_pages as legal_pages_router  # noqa: E402
from routes import upi_manual as upi_manual_router  # noqa: E402
from routes import wallet as wallet_router  # noqa: E402
from routes import wallet_topup as wallet_topup_router  # noqa: E402
from routes import payment_recon as payment_recon_router  # noqa: E402
from routes import withdrawals as withdrawals_router  # noqa: E402
from routes import cart as cart_router  # noqa: E402
from routes import admin_ai as admin_ai_router  # noqa: E402
from routes import service_subcategories as service_subcategories_router  # noqa: E402
from routes import service_admin as service_admin_router  # noqa: E402
from routes import service_provider as service_provider_router  # noqa: E402
from routes import finance as finance_router  # noqa: E402
from routes import refunds as refunds_router  # noqa: E402
from routes import returns as returns_router  # noqa: E402
from routes import vendor_networth as vendor_networth_router  # noqa: E402
from routes import reconciliation as reconciliation_router  # noqa: E402
from routes import privacy as privacy_router  # noqa: E402
from routes import push as push_router  # noqa: E402
from routes import vendor_pos as vendor_pos_router  # noqa: E402
from routes import broadcast as broadcast_router  # noqa: E402
from routes import maintenance as maintenance_router  # noqa: E402
from routes import chat_settings as chat_settings_router  # noqa: E402
from routes import backup as backup_router  # noqa: E402
from routes import delivery as delivery_router  # noqa: E402
from routes import admin_passwords as admin_passwords_router  # noqa: E402
from routes import login_history as login_history_router  # noqa: E402
from routes import order_payments as order_payments_router  # noqa: E402
from core.login_history import record_login  # noqa: E402

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
# Dec 2026 — Idempotency guard for retried writes.  When the frontend
# auto-retries a POST/PUT/PATCH/DELETE because its previous attempt
# timed out mid-response, this middleware detects the same
# `Idempotency-Key` header and REPLAYS the original success response
# instead of executing the handler twice.  Prevents duplicate orders,
# duplicate wallet debits, etc. at any scale.
from core.idempotency import IdempotencyMiddleware  # noqa: E402
app.add_middleware(IdempotencyMiddleware)
app.state.limiter = _rate_limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


# Jun 2026 (Phase 5B) — OVERSIZED RESPONSE WATCHDOG.
# The "Cloudflare could not parse the response" reports were always the same
# root cause: an endpoint answering with megabytes of inline base64 artwork.
# Slim payloads fixed the known offenders (vendor products, shop layout), and
# this logs any future one by name instead of leaving us guessing.
_RESPONSE_SIZE_WARN_BYTES = 2 * 1024 * 1024


@app.middleware("http")
async def _warn_on_huge_response(request, call_next):
    response = await call_next(request)
    try:
        size = int(response.headers.get("content-length") or 0)
        if size > _RESPONSE_SIZE_WARN_BYTES:
            logging.warning(
                f"[HUGE RESPONSE] {size / (1024 * 1024):.1f} MB from "
                f"{request.method} {request.url.path} — inline base64? "
                f"Serve images by URL instead (edge proxies truncate large bodies)."
            )
    except Exception:
        pass
    return response


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

    # ─── INVITE CODE (MLM cutover, Jun-2026) ──────────────────────────
    # The code is now nothing more than an attribution tag. There is no
    # matrix, no spillover BFS placement, no L1..L10 cascade and no payout
    # of any kind — the inviter simply shows up as the referrer on the
    # roster. An unknown code is rejected so typos are caught at signup.
    sponsor = None
    sponsor_code = (payload.referral_code or "").strip().upper() or None
    if sponsor_code:
        sponsor = await db.users.find_one({"referral_code": sponsor_code})
        if not sponsor:
            raise HTTPException(status_code=400, detail="Invalid invite code")
        if (sponsor.get("email") or "").lower() == ADMIN_EMAIL.lower():
            sponsor = None  # the seed admin is never anybody's referrer
    referral_owner = sponsor
    # Kept for backwards compatibility with historical reports: True means
    # "nobody referred this user", it no longer routes money anywhere
    # special (100% of every fee is platform revenue now).
    no_referral_signup = sponsor is None

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
        # Sep 2026 — hash for login + Fernet copy so a super-admin can read
        # the password back on a support call (see core/password_recovery).
        **password_fields(payload.password),
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

    # Mint a fresh session — registration immediately logs the user in.
    sid = new_session_id()
    await register_session(user_id, sid)
    token = create_access_token(user_id, email, "user", sid=sid)
    refresh = create_refresh_token(user_id, sid)
    return {"token": token, "refresh_token": refresh, "user": serialize_user(user_doc)}


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
    # Multi-session login: mint a fresh session id and ADD it to the
    # user's active_session_ids set (capped at MAX_SESSIONS_PER_USER).
    # Concurrent logins from other devices (e.g. APK + web slangcart.com)
    # keep their own sids and stay authenticated.
    sid = new_session_id()
    await register_session(user["id"], sid)
    token = create_access_token(user["id"], email, user.get("role", "user"), sid=sid)
    refresh = create_refresh_token(user["id"], sid)
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
        # Stamp the user with the current login IP/time (the sid was
        # already pushed to active_session_ids by register_session above).
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "last_login_ip": client_ip,
                "last_login_at": now_utc().isoformat(),
            }},
        )
    except Exception:
        pass
    # Device login history + new-device alert (never blocks sign-in).
    await record_login(user, request, sid, method="password")
    return {"token": token, "refresh_token": refresh, "user": serialize_user(user)}


# REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH


@api_router.post("/auth/google/exchange")
@_rl.limit("10/minute")
async def google_exchange(request: Request, payload: GoogleExchange):
    """Exchange an Emergent session_id for our JWT bearer token. Creates user on first sign-in."""
    # OAuth session-data URL is REQUIRED to come from the environment so
    # production deployments can't accidentally hit a demo endpoint.
    session_url = os.environ.get("EMERGENT_OAUTH_SESSION_URL")
    if not session_url:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured on this server (EMERGENT_OAUTH_SESSION_URL missing).",
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
        # Invite code = attribution only (MLM cutover, Jun-2026).
        sponsor = None
        sponsor_code = (payload.referral_code or "").strip().upper() or None
        if sponsor_code:
            sponsor = await db.users.find_one({"referral_code": sponsor_code})
        if sponsor and (sponsor.get("email") or "").lower() == ADMIN_EMAIL.lower():
            sponsor = None
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
        await _create_notification(user_id, "welcome", "Welcome to Slangcart!", "Signed in with Google. Complete the ₹100 activation to start earning.")
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

    sid = new_session_id()
    await register_session(user["id"], sid)
    token = create_access_token(user["id"], email, user.get("role", "user"), sid=sid)
    refresh = create_refresh_token(user["id"], sid)
    await record_login(user, request, sid, method="google")
    return {"token": token, "refresh_token": refresh, "user": serialize_user(user), "is_new": is_new}


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
async def logout(
    user: Dict[str, Any] = Depends(get_current_user),
    creds: HTTPAuthorizationCredentials = Depends(security),
):
    # Revoke ONLY the current device's sid — other concurrent sessions
    # (e.g. APK if user logged out from web, or vice versa) stay alive.
    try:
        token = creds.credentials if creds else None
        sid: Optional[str] = None
        if token:
            try:
                payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                sid = payload.get("sid")
            except Exception:
                sid = None
        if sid:
            await revoke_session(user["id"], sid)
        else:
            # Legacy token (no sid) — nuke all sessions as the safe default.
            await db.users.update_one(
                {"id": user["id"]},
                {"$unset": {"active_session_id": "", "active_session_ids": ""}},
            )
    except Exception:
        pass
    return {"ok": True}


# ─────────────── Token refresh (Phase 1 Session B, 2026-05-27) ───────────────
class _RefreshPayload(BaseModel):
    refresh_token: str


@api_router.post("/auth/refresh")
@_rl.limit("30/minute")
async def refresh_token(request: Request, payload: _RefreshPayload):
    """Exchange a valid refresh token for a fresh access token (and a rotated
    refresh token). The submitted refresh token's `sid` MUST match the user's
    `active_session_id` — otherwise the session has been revoked (because the
    user logged in from another device or explicitly logged out) and we
    respond 401 detail=session_revoked so the FE can clean its local state.

    Refresh-token rotation: every successful call mints a brand-new refresh
    token AND assigns the user a brand-new `active_session_id`. This means an
    attacker who steals a refresh token can only use it once — on next legit
    use, the real user's session will already have been rotated and the
    attacker's call returns session_revoked.
    """
    data = decode_refresh_token(payload.refresh_token)
    user_id = data.get("sub")
    sid = data.get("sid")
    if not user_id or not sid:
        raise HTTPException(status_code=401, detail="refresh_invalid")
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="refresh_invalid")
    if user.get("is_blocked"):
        raise HTTPException(status_code=403, detail="Account blocked")
    # The refresh token's sid must still be in the user's active set —
    # otherwise this device was logged out (or its session evicted from
    # the 10-slot pool).
    active_sids = user.get("active_session_ids") or []
    legacy_sid = user.get("active_session_id")
    sid_known = (sid in active_sids) or (not active_sids and legacy_sid == sid)
    if not sid_known:
        # Grace path: this device's token was rotated moments ago but it never
        # received the new one (app killed mid-refresh, weak signal, or two
        # refreshes raced). Hand it the CURRENT session instead of signing the
        # user out — the owner's rule is "only a manual logout signs me out".
        target = rotation_target(user, sid)
        if target:
            return {
                "token": create_access_token(user_id, user.get("email", ""), user.get("role", "user"), sid=target),
                "refresh_token": create_refresh_token(user_id, target),
            }
        raise HTTPException(status_code=401, detail="session_revoked")
    # Rotate within this device's slot — new sid replaces old, other
    # devices' sids remain untouched.
    new_sid = new_session_id()
    await rotate_session(user_id, sid, new_sid)
    email = user.get("email", "")
    role = user.get("role", "user")
    new_access = create_access_token(user_id, email, role, sid=new_sid)
    new_refresh = create_refresh_token(user_id, new_sid)
    return {"token": new_access, "refresh_token": new_refresh}


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
    # Bug-fix · 2026-05-31: If admin already collected GST at the moment of
    # offline-creation, skip the entry-level GST here (would double-count).
    # Net still goes into direct_signup. Payout-level GST on L2-L10 platform
    # fees is untouched.
    if joiner.get("registration_gst_collected_at_create"):
        gst = 0.0
        net = round(gross, 2)

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
            # ── GST classification (June-2026) ───────────────────────────
            # `registration_entry` = the ₹18-of-₹118 GST embedded in a
            # joining fee. Group 3 (GST Ledger) DERIVES this figure from
            # Razorpay-sourced registrations only, so these rows are tagged
            # and EXCLUDED from the ledger sum to avoid double-counting.
            "gst_kind": "registration_entry",
            "related_signup_id": joiner["id"],
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



async def _trigger_referral_commissions(user: Dict[str, Any]) -> None:
    """Book a paid subscription fee as plain marketplace revenue.

    MLM CUTOVER (Jun-2026) — the Level 1..10 referral cascade, spillover
    placement, cascade overflow, L1 cycle counters and the fee-residual
    pool are REMOVED.  No upline is ever paid for a signup again.

    The full gross fee is recognised as platform revenue: net into admin's
    `direct_signup` bucket, the 18% entry GST into `gst_collected`.  An
    invite code still bumps the inviter's roster counter, but it moves no
    money.

    The function name is kept so the existing call sites (admin approval,
    UPI-manual confirm, Razorpay success) keep working unchanged.
    Idempotent via the `commission_triggered` flag.
    """
    if user.get("commission_triggered"):
        return
    sponsor_id = user.get("sponsor_id")
    # Mark first so two concurrent approvals can never book the fee twice.
    await db.users.update_one({"id": user["id"]}, {"$set": {"commission_triggered": True}})

    # ─── Offline pre-credit REVERSAL (ledger integrity) ───────────────
    # Admin offline-create pre-credits the fee into `direct_added` so the
    # books balance between create and approval.  We are about to book the
    # same fee as `direct_signup` revenue, so the pre-credit MUST be
    # reversed first or the money is counted twice in HELD.
    pre_credit = float(user.get("offline_pre_credit_amount") or 0)
    if pre_credit > 0.01:
        admin_doc_pre = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
        if admin_doc_pre:
            avail_da = float((admin_doc_pre.get("wallet_buckets") or {}).get("direct_added") or 0)
            debit_amt = round(min(avail_da, pre_credit), 2)
            if debit_amt > 0:
                await credit_admin_bucket("direct_added", -debit_amt, also_total_earned=False)
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_doc_pre["id"],
                    "type": "admin_debit",
                    "amount": -debit_amt,
                    "status": "success",
                    "description": (
                        f"Offline pre-credit reversal — ₹{debit_amt:g} for {user.get('name')} "
                        f"(fee re-booked as subscription revenue)"
                    ),
                    "source_user_id": user["id"],
                    "source_user_name": user.get("name"),
                    "related_signup_id": user["id"],
                    "is_offline_reversal": True,
                    "created_at": now_utc().isoformat(),
                })
        await db.users.update_one(
            {"id": user["id"]},
            {"$unset": {"offline_pre_credit_amount": ""}},
        )

    # ─── Invite-code roster counter (tracking only, pays nothing) ──────
    placement_sponsor = await db.users.find_one({"id": sponsor_id}) if sponsor_id else None
    if (
        sponsor_id
        and placement_sponsor
        and (placement_sponsor.get("email") or "").lower() != ADMIN_EMAIL.lower()
    ):
        await db.users.update_one(
            {"id": sponsor_id},
            {"$inc": {"direct_referrals_count": 1}},
        )

    # ─── Revenue recognition — 100% of the fee to the platform ─────────
    await _credit_no_ref_signup_to_admin(user, placement_sponsor)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"fee_residual_backfilled": True}},
    )



@api_router.post("/payment/skip-subscription")
async def skip_subscription(user: Dict[str, Any] = Depends(get_current_user)):
    """Free entry — "Continue without subscription" (Aug-2026).

    The ₹118 joining fee is a SUBSCRIPTION, not a hard gate. A user may
    enter the app without paying: they can browse and shop, but wallet /
    cashback / referral earnings / withdrawals stay locked until they
    subscribe. This endpoint only records the choice — no money moves and
    no referral commission is ever triggered for a free account.
    """
    if user.get("registration_paid"):
        return {"ok": True, "already_paid": True, "subscription_skipped": False}
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "subscription_skipped": True,
            "subscription_skipped_at": now_utc().isoformat(),
        }},
    )
    return {"ok": True, "subscription_skipped": True}


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
    """Return active Razorpay credentials. Order of precedence: DB > env.

    Thin wrapper — the real logic lives in core/razorpay.py so the order
    checkout flow (routes/order_payments.py) reads the exact same keys.
    """
    from core.razorpay import get_creds as _core_get_creds
    return await _core_get_creds()


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
        "description": "Slangcart registration fee",
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
        # Canonical source tag (mock variant still attributes to razorpay
        # for breakdown purposes — they're real Razorpay-shaped orders).
        "registration_source": "razorpay",
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
        # Canonical source tag for the registration_fee row.
        "source": "razorpay",
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
                "source": "razorpay",
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

    # Sep-2026 — the cash is in the COMPANY BANK ACCOUNT. One bank row per
    # Razorpay receipt so Bank Ledger == Bank Statement (Group 7).
    await bank.post_bank(
        kind="credit",
        amount=fee,
        category="registration_fee",
        description=f"Registration fee · {user.get('name') or user.get('email')}",
        ref_key=f"REGFEE:{payload.razorpay_order_id}",
        utr=utr or payload.razorpay_payment_id,
        user_id=user["id"],
        extra={"razorpay_payment_id": payload.razorpay_payment_id,
               "razorpay_order_id": payload.razorpay_order_id},
    )

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
            ("Welcome aboard! Your payment was verified" + (f" (UTR {utr})" if utr else "") +
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
    """Buyer dashboard — purchase + cashback centric (MLM cutover Jun-2026).

    The old payload (team size, tier, L1..L10 breakdown, next-payout
    countdown) is gone. What a Slangcart customer cares about now is: what
    is in my wallet, how much cashback have I earned from my orders and
    how much is still on its way.
    """
    uid = user["id"]
    unread_notifs = await db.notifications.count_documents({"user_id": uid, "read": False})
    orders_count = await db.orders.count_documents({"user_id": uid})
    delivered_count = await db.orders.count_documents({"user_id": uid, "status": "delivered"})
    pending_withdrawals = await db.withdrawals.count_documents({"user_id": uid, "status": "pending"})

    async def _sum(match: Dict[str, Any]) -> float:
        agg = await db.transactions.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        return round(float(agg[0]["total"]), 2) if agg else 0.0

    cashback_earned = await _sum({
        "user_id": uid, "type": "cashback_credit", "status": "success",
    })
    cashback_reversed = abs(await _sum({
        "user_id": uid, "type": "cashback_reversal", "status": "success",
    }))
    pending_cashback = await _sum({
        "user_id": uid, "type": "cashback_pending", "status": "pending",
    })
    total_spent = abs(await _sum({
        "user_id": uid, "type": {"$in": ["purchase", "order_payment"]}, "status": "success",
    }))

    # Last 7 days of cashback — powers the dashboard sparkline.
    today = now_utc().date()
    cashback_per_day: List[float] = []
    day_labels: List[str] = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        cashback_per_day.append(await _sum({
            "user_id": uid, "type": "cashback_credit", "status": "success",
            "created_at": {"$regex": f"^{d.isoformat()}"},
        }))
        day_labels.append(d.strftime("%a"))

    return {
        "user": serialize_user(user),
        "wallet_balance": round(float(user.get("wallet_balance") or 0), 2),
        "cashback_earned": round(cashback_earned - cashback_reversed, 2),
        "pending_cashback": pending_cashback,
        "total_spent": total_spent,
        "orders_count": orders_count,
        "delivered_count": delivered_count,
        "pending_withdrawals": pending_withdrawals,
        "invite_code": user.get("referral_code"),
        "unread_notifications": unread_notifs,
        "cashback_per_day": cashback_per_day,
        "day_labels": day_labels,
    }


@api_router.post("/users/me/bank")
async def update_bank(payload: BankUpdate, user: Dict[str, Any] = Depends(get_current_user)):
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    return fresh


# ── Profile picture upload (2026-06-12) ────────────────────────────────────
# Uploads via base64 data-URI so we don't need multipart/form-data, S3, or
# any blob storage — the image is stored inline on the user doc. Capped at
# ~1.5 MB base64 (≈ 1 MB binary) to keep the user document under Mongo's
# 16 MB hard limit even when other fields grow.
class ProfileImageUpload(BaseModel):
    image_data_url: str  # full data URI like "data:image/jpeg;base64,..."


@api_router.post("/users/me/profile-image")
async def update_profile_image(payload: ProfileImageUpload, user: Dict[str, Any] = Depends(get_current_user)):
    img = (payload.image_data_url or "").strip()
    if not img or not img.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Invalid image format. Use a base64 data URI.")
    # Soft cap at 1.5 MB base64 — ~1.1 MB binary. Higher quality should be
    # client-down-scaled before upload.
    MAX_LEN = 1_500_000
    if len(img) > MAX_LEN:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large. Please use a photo under ~1 MB (got {len(img)//1024} KB).",
        )
    ts = datetime.utcnow().isoformat()
    # June 2026 — also stamp a default `profile_visibility` on first-ever
    # upload so the field always exists when other endpoints check it.
    # SP/Vendor accounts are HARD-LOCKED to "everyone" (enforced again
    # by routes/privacy.update_my_privacy) so even a tampered client can
    # never hide a public account.
    from routes.privacy import is_public_account, DEFAULT_VISIBILITY  # local import to avoid cycles
    desired_vis = "everyone" if is_public_account(user) else (
        user.get("profile_visibility") or DEFAULT_VISIBILITY
    )
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "profile_image": img,
            "profile_image_updated_at": ts,
            "profile_visibility": desired_vis,
        }},
    )
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    return fresh


@api_router.delete("/users/me/profile-image")
async def remove_profile_image(user: Dict[str, Any] = Depends(get_current_user)):
    await db.users.update_one(
        {"id": user["id"]},
        {"$unset": {"profile_image": "", "profile_image_updated_at": ""}},
    )
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    return fresh


# ------------------ Withdrawals ------------------
# POST /withdrawals — moved to routes/withdrawals.py (2026-06-04, commission
# engine extraction wave). GET /withdrawals/me was already in the router file.


# /transactions/me — moved to routes/wallet.py (Phase 2B Iter 4)
# /transactions/{txn_id} — moved to routes/wallet.py
# /transactions/{txn_id}/invoice — moved to routes/wallet.py
# /transactions/{txn_id}/invoice.pdf — moved to routes/wallet.py
# Helpers _auto_remarks_for() and _resolve_invoice_data() also live in
# routes/wallet.py now — they were only used by the four endpoints above.


# ------------------ Wallet-to-wallet transfer ------------------
# POST /wallet/transfer — moved to routes/wallet.py (2026-06-04, commission
# engine extraction wave). The endpoint never touched _trigger_referral_commissions
# so the migration was zero-risk.


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
async def admin_list_users(
    _: Dict[str, Any] = Depends(require_admin),
    limit: int = 0,
    offset: int = 0,
    q: Optional[str] = None,
    source: Optional[str] = None,
):
    """Admin user roster.

    • limit/offset (opt-in): pass limit=20 for infinite-scroll pagination.
      When limit is 0 or omitted we return the legacy unbounded list
      (capped at 5000) so existing admin tooling keeps working.
    • q (opt-in): server-side substring filter on name/email/phone/referral_code
      — case-insensitive. Lets the FE search the whole roster (not just the
      currently-loaded page) which becomes critical once we paginate.
    • source (opt-in): razorpay | upi_manual | offline_cash | unpaid — how the
      user joined (June-2026 categorisation request).
    """
    mongo_q: Dict[str, Any] = _users_source_query(source)
    if q and q.strip():
        # Anchored regex on indexed fields — Mongo uses ix_users_* when available
        # and falls back to a collscan otherwise (still fast for <100k users).
        import re as _re
        safe = _re.escape(q.strip())
        mongo_q["$or"] = [
            {"name": {"$regex": safe, "$options": "i"}},
            {"email": {"$regex": safe, "$options": "i"}},
            {"phone": {"$regex": safe, "$options": "i"}},
            {"referral_code": {"$regex": safe, "$options": "i"}},
        ]
    cursor = db.users.find(mongo_q, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0}).sort("created_at", -1)
    if limit and limit > 0:
        cursor = cursor.skip(max(0, offset)).limit(min(limit, 200))
        return await cursor.to_list(min(limit, 200))
    return await cursor.to_list(5000)


def _users_source_query(source: Optional[str]) -> Dict[str, Any]:
    """Mongo filter for the join-source category tabs on Admin → Users.

    `unpaid`  → not yet marked paid/approved by anyone
    `razorpay` / `upi_manual` / `offline_cash` → paid via that channel
    """
    if not source or source == "all":
        return {}
    if source in ("unpaid", "non_subscriber"):
        return {"registration_paid": {"$ne": True}}
    if source == "subscriber":
        # Aug-2026: a Subscriber is a member whose Razorpay payment succeeded.
        return {"registration_paid": True, "registration_source": "razorpay"}
    if source == "legacy":
        # Historical UPI-manual / offline-cash joinings (kept for the books).
        return {"role": "user", "registration_paid": True,
                "registration_source": {"$in": ["upi_manual", "offline_cash"]}}
    if source == "unknown":
        return {
            "registration_paid": True,
            "registration_source": {"$nin": ["razorpay", "upi_manual", "offline_cash"]},
        }
    return {"registration_paid": True, "registration_source": source}


@api_router.get("/admin/users/source-counts")
async def admin_users_source_counts(_: Dict[str, Any] = Depends(require_admin)):
    """Counts for the Admin → Users category tabs (all / razorpay / upi_manual
    / offline_cash / unknown / unpaid)."""
    out: Dict[str, int] = {"all": await db.users.count_documents({})}
    for key in ("razorpay", "upi_manual", "offline_cash", "unknown", "unpaid",
                "subscriber", "non_subscriber", "legacy"):
        out[key] = await db.users.count_documents(_users_source_query(key))
    return out


@api_router.get("/admin/withdrawals")
async def admin_list_withdrawals(
    _: Dict[str, Any] = Depends(require_admin),
    status: Optional[str] = None,
    limit: int = 0,
    offset: int = 0,
):
    """Admin withdrawal queue. Pagination opt-in via limit (1..200) + offset."""
    q = {}
    if status:
        q["status"] = status
    cursor = db.withdrawals.find(q, {"_id": 0}).sort("created_at", -1)
    if limit and limit > 0:
        cursor = cursor.skip(max(0, offset)).limit(min(limit, 200))
        return await cursor.to_list(min(limit, 200))
    return await cursor.to_list(2000)


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
    # Money physically left the company bank account → Group 7 debit.
    await bank.post_bank(
        kind="debit",
        amount=float(w["amount"]),
        category="withdrawal_payout",
        description=f"Payout to {w.get('user_name') or w.get('user_email')}" + (f" · UTR {ref}" if ref else ""),
        ref_key=f"WDLPAY:{wid}",
        utr=ref or None,
        user_id=w["user_id"],
        payment_method="bank_transfer",
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
    await bank.post_bank(
        kind="debit",
        amount=float(w["amount"]),
        category="withdrawal_payout",
        description=f"Instant payout to {w.get('user_name') or w.get('user_email')}" + (f" · UTR {ref}" if ref else ""),
        ref_key=f"WDLPAY:{wid}",
        utr=ref or None,
        user_id=w["user_id"],
        payment_method="bank_transfer",
    )
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
    # Refund the locked amount back to the SAME wallet it was held from
    # (a seller's settlement comes out of the shop wallet, not the
    # customer/referral wallet) — ledgered and replay-safe.
    _wf = w.get("wallet_field") or "wallet_balance"
    await shop_money.credit(
        w["user_id"], _wf, float(w["amount"]),
        idempotency_key=f"WDL_REJECT:{wid}",
        group="withdrawal",
        txn_type="withdrawal_refund",
        source_wallet="pending_withdrawal",
        settlement_status="rejected",
        description=f"Settlement rejected — ₹{float(w['amount']):,.0f} returned" + (f" ({reason})" if reason else ""),
        extra={"withdrawal_id": wid,
               **({"wallet_impact": "vendor_earnings_only"} if _wf == shop_money.VENDOR_WALLET else {})},
    )
    # Jun-2026 — a settlement that never happened must not cost the seller the
    # 2.56% transaction fee: give it back and take the revenue off the books.
    _fee = round(float(w.get("transaction_fee") or 0), 2)
    if _fee > 0.009:
        await shop_money.credit(
            w["user_id"], _wf, _fee,
            idempotency_key=f"WDL_FEEBACK:{wid}",
            group="revenue_ledger",
            txn_type="withdrawal_transaction_fee_refund",
            vendor_id=w["user_id"],
            source_wallet="system_treasury",
            settlement_status="rejected",
            description=(
                f"Transaction fee ₹{_fee:,.2f} returned — settlement rejected"
                + (f" ({reason})" if reason else "")
            ),
            extra={"withdrawal_id": wid, "reverses_fee": True,
                   **({"wallet_impact": "vendor_earnings_only"} if _wf == shop_money.VENDOR_WALLET else {})},
        )
        # The reversal runs on EVERY reject, not only when the credit above was
        # fresh: `shop_money.post` is keyed, so a replay is a no-op, while a
        # reject whose fee credit landed in an earlier call still gets its
        # revenue taken off the books.
        _rev = await shop_money.post(
                group="revenue_ledger",
                txn_type="reversal",
                amount=_fee,
                debit=_fee,
                idempotency_key=f"WDLFEEREV_REJECT:{wid}",
                user_id=admin["id"],
                vendor_id=w["user_id"],
                source_wallet="system_treasury",
                settlement_status="reversed",
                description=f"Withdrawal transaction fee reversed — settlement {wid[:8]} rejected",
                extra={"withdrawal_id": wid, "original_type": "platform_fee_collected"},
            )
        if _rev is not None:
            await credit_admin_bucket("platform_fee_collected", -_fee, also_total_earned=False)
    # The cashback that was adjusted on the request is NOT returned: it was a
    # genuine debt the seller owed and it is now settled.
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


# ── Short, human-trackable transaction references (June-2026) ─────────
# Admin asked for reference numbers that are SHORT and tell you WHAT the
# row is at a glance. Format: <KIND>-<6 chars>, e.g. REG-4F9K2P (joining
# fee), GST-91B3C7, PAY-77AA10 (referral payout), WDL-… (withdrawal).
_TXN_REF_PREFIX: Dict[str, str] = {
    "registration_fee":       "REG",
    "gst_collected":          "GST",
    "platform_fee_collected": "PLF",
    "referral_payout":        "PAY",
    "direct_signup_credit":   "DSC",
    "cascade_overflow":       "OVF",
    "fee_residual":           "RES",
    "l1_funding":             "L1F",
    "withdrawal":             "WDL",
    "system_deposit":         "DEP",
    "order_payment":          "ORD",
    "order_payment_upi":      "UPI",
    "service_booking":        "SRV",
    "service_margin":         "SRM",
    "shopping_margin":        "SHM",
    "refund":                 "RFD",
    "reversal":               "REV",
    "adjustment":             "ADJ",
    "manual_adjustment":      "ADJ",
    "wallet_transfer":        "TRF",
    "transfer_in":            "TIN",
    "transfer_out":           "TOU",
}


def _short_txn_ref(t: Dict[str, Any]) -> str:
    """`REG-4F9K2P` style short reference — stable per transaction."""
    prefix = _TXN_REF_PREFIX.get(t.get("type") or "", "TXN")
    seed = str(t.get("display_id") or t.get("id") or "").replace("-", "").upper()
    return f"{prefix}-{seed[-6:]}" if seed else prefix


# Canonical registration sources surfaced in the admin UI.
REGISTRATION_SOURCES = ("razorpay", "upi_manual", "offline_cash", "unknown")


@api_router.get("/admin/transactions")
async def admin_transactions(
    _: Dict[str, Any] = Depends(require_admin),
    include_pending: bool = False,
    limit: int = 0,
    offset: int = 0,
    type: Optional[str] = None,
    source: Optional[str] = None,
    q: Optional[str] = None,
):
    """Admin transaction feed. By default hides pre-payment / failed registration
    rows so the wallet & revenue figures match. Pass ?include_pending=true to
    surface them for support / debugging.

    Server-side filters (June-2026 fix): `type` (e.g. registration_fee),
    `source` (razorpay | upi_manual | offline_cash | unknown — resolved from
    the linked user's `registration_source`) and `q` (name / email / member id
    / reference substring). Previously the type filter ran CLIENT-side on a
    20-row page, which made the "Registration fee revenue" screen show only
    the handful of matching rows that happened to be in the latest page.

    Pagination opt-in via limit (1..200) + offset.
    Each row is enriched with `user_name`, `registration_source`, and a SHORT
    trackable `short_ref` (REG-XXXXXX / GST-XXXXXX / …).
    """
    match: Dict[str, Any] = {}
    if not include_pending:
        match["status"] = {"$nin": ["created", "failed"]}
    if type:
        match["type"] = type

    pipeline: List[Dict[str, Any]] = [
        {"$match": match},
        {"$sort": {"created_at": -1}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "_u"}},
        {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {
            "_src": {"$ifNull": ["$_u.registration_source", {"$ifNull": ["$source", "unknown"]}]},
        }},
    ]
    if source:
        if source == "unknown":
            pipeline.append({"$match": {"_src": {"$nin": ["razorpay", "upi_manual", "offline_cash"]}}})
        else:
            pipeline.append({"$match": {"_src": source}})
    if q and q.strip():
        import re as _re
        safe = _re.escape(q.strip())
        rx = {"$regex": safe, "$options": "i"}
        pipeline.append({"$match": {"$or": [
            {"_u.name": rx}, {"_u.email": rx}, {"_u.phone": rx}, {"_u.referral_code": rx},
            {"reference_number": rx}, {"razorpay_payment_id": rx}, {"description": rx},
        ]}})

    page = min(limit, 200) if limit and limit > 0 else 5000
    if limit and limit > 0 and offset:
        pipeline.append({"$skip": max(0, offset)})
    pipeline.append({"$limit": page})

    rows = await db.transactions.aggregate(pipeline, allowDiskUse=True).to_list(page)

    enriched = []
    for t in rows:
        t.pop("_id", None)
        u = t.pop("_u", None) or {}
        src = t.pop("_src", None) or "unknown"
        if src not in REGISTRATION_SOURCES:
            src = "unknown"
        ref = (
            t.get("reference_number")
            or t.get("razorpay_payment_id")
            or (f"TXN-{t['id'][:8].upper()}" if t.get("id") else None)
        )
        # Invoice-like detail description (2026-06-01): if the txn doesn't
        # have a rich description, synthesize one so the admin list shows
        # WHO + WHAT + WHY + AMOUNT + REFERENCE on every single row.
        TYPE_HUMAN = {
            "registration_fee":      "Registration fee (Joining ₹118 = ₹100 + 18% GST)",
            "referral_payout":       "Referral commission payout",
            "withdrawal":            "User withdrawal to bank/UPI",
            "gst_collected":         "GST 18% collected on registration",
            "platform_fee_collected":"Platform fee collected on commission",
            "direct_signup_credit":  "Direct signup credit to sponsor (Level 1)",
            "order_payment":         "Shop order payment",
            "order_payment_upi":     "Shop order paid by UPI / card",
            "service_booking":       "Service booking payment",
            "system_deposit":        "Admin direct UTR deposit to system wallet",
            "wallet_transfer":       "Peer-to-peer wallet transfer",
            "transfer_in":           "Wallet credit received (transfer in)",
            "transfer_out":          "Wallet debit sent (transfer out)",
            "service_commission":    "Service commission credit",
            "shopping_margin":       "Shopping margin earned",
            "reversal":              "Transaction reversal (admin adjustment)",
            "adjustment":            "Manual adjustment (admin)",
            "manual_adjustment":     "Manual adjustment (admin)",
        }
        existing_desc = (t.get("description") or "").strip()
        # Compose a self-describing line — invoice copy style
        actor = u.get("name") or u.get("email") or t.get("user_id", "unknown user")
        type_human = TYPE_HUMAN.get(t.get("type") or "", (t.get("type") or "").replace("_", " ").title())
        level_str = ""
        if t.get("level") is not None:
            try:
                level_str = f" · Level {int(t['level'])}"
            except Exception:
                pass
        short_ref = _short_txn_ref(t)
        ref_str = f" · Ref {short_ref}"
        # Status label
        status_lbl = (t.get("status") or "").upper()
        rich = f"{type_human}{level_str} · ₹{abs(float(t.get('amount') or 0)):.2f} · {actor}{ref_str} · {status_lbl}"
        enriched.append({
            **t,
            "user_name": u.get("name"),
            "user_email": u.get("email"),
            "user_phone": u.get("phone"),
            "user_referral_code": u.get("referral_code"),
            "registration_source": src,
            "reference_number": ref,
            "short_ref": short_ref,
            "description": existing_desc or rich,
            "invoice_line": rich,  # Always populated, even when description exists
        })
    return enriched


@api_router.get("/admin/transactions/summary")
async def admin_transactions_summary(
    _: Dict[str, Any] = Depends(require_admin),
    type: Optional[str] = None,
    include_pending: bool = False,
    q: Optional[str] = None,
):
    """Totals + per-source split for the whole filtered result set (NOT just
    the loaded page). Powers the category tabs on the Registration-fee
    revenue screen so the counts/amounts are always the true DB figures.
    """
    match: Dict[str, Any] = {}
    if not include_pending:
        match["status"] = {"$nin": ["created", "failed"]}
    if type:
        match["type"] = type
    pipeline: List[Dict[str, Any]] = [
        {"$match": match},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "_u"}},
        {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {
            "_src": {"$ifNull": ["$_u.registration_source", {"$ifNull": ["$source", "unknown"]}]},
        }},
    ]
    if q and q.strip():
        import re as _re
        safe = _re.escape(q.strip())
        rx = {"$regex": safe, "$options": "i"}
        pipeline.append({"$match": {"$or": [
            {"_u.name": rx}, {"_u.email": rx}, {"_u.phone": rx}, {"_u.referral_code": rx},
            {"reference_number": rx}, {"razorpay_payment_id": rx}, {"description": rx},
        ]}})
    pipeline.append({"$group": {"_id": "$_src", "count": {"$sum": 1}, "amount": {"$sum": "$amount"}}})
    rows = await db.transactions.aggregate(pipeline, allowDiskUse=True).to_list(50)

    by_source: Dict[str, Dict[str, Any]] = {s: {"count": 0, "amount": 0.0} for s in REGISTRATION_SOURCES}
    total_count, total_amount = 0, 0.0
    for r in rows:
        key = r["_id"] if r["_id"] in REGISTRATION_SOURCES else "unknown"
        by_source[key]["count"] += int(r.get("count") or 0)
        by_source[key]["amount"] = round(by_source[key]["amount"] + float(r.get("amount") or 0), 2)
        total_count += int(r.get("count") or 0)
        total_amount += float(r.get("amount") or 0)
    return {
        "type": type,
        "total": {"count": total_count, "amount": round(total_amount, 2)},
        "by_source": by_source,
    }


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
    from core.image_compress import compress_product_payload
    from core.variants import apply_variants_to_payload
    payload = compress_product_payload(p.dict())
    payload = apply_variants_to_payload(payload, float(payload.get("price") or 0))
    from core.taxonomy import normalize_product_taxonomy
    payload = await normalize_product_taxonomy(payload)
    doc = {"id": str(uuid.uuid4()), **payload, "created_at": now_utc().isoformat()}
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    await _audit_log(admin, "product.create", "product", doc["id"], {"name": p.name, "price": p.price})
    return doc


@api_router.get("/admin/products")
async def admin_list_products(
    vendor_id: Optional[str] = None,
    vendor_q: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Admin product list with vendor name enrichment + filters.

    Jun 2026 (scalability fix):
      • PAGINATED (default 60/page, up to 300).  Old endpoint tried to
        return up to 2000 products with FULL docs (base64 images
        included) → 500 error at ~150 products.  Now uses the same
        slim projection as the public list endpoint and pages results.
      • Base64 image URLs are rewritten to lazy-loaded thumbnails so
        the grid can render instantly regardless of catalog size.

    Vendor enrichment stays as a single batched lookup.  Full text
    search via `?q=` uses the same regex across name/brand/category.
    """
    limit = max(1, min(300, int(limit)))
    offset = max(0, int(offset))

    prod_query: Dict[str, Any] = {}
    if vendor_id:
        prod_query["vendor_id"] = vendor_id
    elif vendor_q:
        rx = {"$regex": vendor_q.strip(), "$options": "i"}
        vend_ids = [
            v["id"] async for v in db.users.find(
                {"$or": [{"name": rx}, {"vendor_business_name": rx}, {"email": rx}]},
                {"id": 1},
            )
        ]
        if not vend_ids:
            return {"items": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}
        prod_query["vendor_id"] = {"$in": vend_ids}

    if q and q.strip():
        import re as _re
        needle = _re.escape(q.strip())
        text_or = {"$or": [
            {"name": {"$regex": needle, "$options": "i"}},
            {"brand": {"$regex": needle, "$options": "i"}},
            {"category": {"$regex": needle, "$options": "i"}},
            {"sub_category": {"$regex": needle, "$options": "i"}},
            {"tags": {"$regex": needle, "$options": "i"}},
        ]}
        prod_query = {"$and": [prod_query, text_or]} if prod_query else text_or

    # Same slim projection used by the public list — drops base64 images
    # + reviews/questions/interested_users so the wire payload stays
    # small even for 10k+ products.
    LIST_PROJ = {
        "_id": 0,
        "images": 0,
        "description": 0,
        "specifications": 0,
        "interested_users": 0,
        "reviews": 0,
        "questions": 0,
    }

    total = await db.products.count_documents(prod_query)
    # Jun 2026 fix — `_gallery_n` lets us know whether a product has gallery
    # images WITHOUT shipping the (base64, multi-MB) `images` array.  Vendor
    # products that only carry gallery photos previously rendered as an empty
    # placeholder in the admin grid.
    items = await db.products.aggregate([
        {"$match": prod_query},
        {"$sort": {"created_at": -1}},
        {"$skip": offset},
        {"$limit": limit},
        {"$addFields": {"_gallery_n": {"$size": {"$ifNull": ["$images", []]}}}},
        {"$project": LIST_PROJ},
    ]).to_list(limit)

    # Rewrite base64 image_url to lazy thumbnail endpoint so the wire
    # payload doesn't balloon on data:image URIs.
    for p in items:
        img = p.get("image_url") or ""
        gallery_n = int(p.pop("_gallery_n", 0) or 0)
        inline = isinstance(img, str) and img.startswith("data:")
        if inline or (not img and gallery_n > 0):
            p["image_url"] = f"/api/products/{p.get('id')}/image?w=360&q=72"
            p["has_inline_image"] = True

    # Enrich with vendor name / email in a single batched lookup.
    vend_ids_present = [p.get("vendor_id") for p in items if p.get("vendor_id")]
    vend_map: Dict[str, Dict[str, Any]] = {}
    if vend_ids_present:
        async for v in db.users.find(
            {"id": {"$in": list(set(vend_ids_present))}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "vendor_business_name": 1},
        ):
            vend_map[v["id"]] = v
    for p in items:
        vid = p.get("vendor_id")
        if vid and vid in vend_map:
            vv = vend_map[vid]
            p["vendor_name"] = vv.get("vendor_business_name") or vv.get("name") or "—"
            p["vendor_email"] = vv.get("email")
        elif not p.get("vendor_name"):
            p["vendor_name"] = "Admin catalog"

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
    }


@api_router.get("/admin/vendors")
async def admin_list_vendors(q: Optional[str] = None, _: Dict[str, Any] = Depends(require_admin)):
    """Lightweight vendor picker for the admin Products page filter.

    Dec 2026 — Returns ALL vendors (approved + pending) so the admin can
    filter products by ANY vendor, not just approved ones.  Search also
    now covers store_pincode so admins can find a vendor by their PIN
    (useful when a customer complains about a specific area).

    Kept fast and paginated-off for the ≤ few-hundred vendors we have
    today.  Sorted approved-first, then by display name.
    """
    query: Dict[str, Any] = {
        "$or": [
            {"is_vendor": True},
            {"is_vendor_approved": True},
            {"vendor_status": {"$exists": True}},
        ],
    }
    if q:
        rx = {"$regex": q.strip(), "$options": "i"}
        query = {
            "$and": [
                query,
                {"$or": [
                    {"name": rx},
                    {"vendor_business_name": rx},
                    {"email": rx},
                    {"store_pincode": rx},
                    {"phone": rx},
                ]},
            ],
        }
    items = []
    async for v in db.users.find(
        query,
        {"_id": 0, "id": 1, "name": 1, "email": 1, "vendor_business_name": 1,
         "store_pincode": 1, "is_vendor_approved": 1, "vendor_status": 1},
    ).sort([("is_vendor_approved", -1), ("vendor_business_name", 1)]).limit(1000):
        items.append({
            "id": v["id"],
            "name": v.get("vendor_business_name") or v.get("name") or v.get("email"),
            "email": v.get("email"),
            "store_pincode": v.get("store_pincode") or "",
            "is_approved": bool(v.get("is_vendor_approved")),
            "status": v.get("vendor_status") or ("approved" if v.get("is_vendor_approved") else "pending"),
        })
    return {"items": items, "total": len(items)}


@api_router.post("/admin/products/publish-all")
async def admin_publish_all_products(
    payload: Dict[str, Any] = Body(default={}),
    admin: Dict[str, Any] = Depends(require_admin_not_finance),
):
    """Jun 2026 — Bulk publish/unpublish.

    Vendors upload in batches of 50-200 SKUs; flipping each one by hand in
    the Admin Products grid was the single biggest operational time-sink.
    Body:
      • `vendor_id` (optional) — restrict to one vendor's catalogue.
      • `publish`   (default true) — set False to bulk-UNPUBLISH.
    Returns how many documents actually changed.
    """
    vendor_id = (payload or {}).get("vendor_id") or None
    publish = bool((payload or {}).get("publish", True))

    query: Dict[str, Any] = {}
    if vendor_id:
        query["vendor_id"] = vendor_id
    if publish:
        query["$or"] = [{"is_published": {"$ne": True}}, {"is_published": {"$exists": False}}]
    else:
        query["is_published"] = True

    res = await db.products.update_many(query, {"$set": {"is_published": publish}})
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
    await _audit_log(
        admin, "product.publish_all", "product", vendor_id or "all",
        {"publish": publish, "matched": res.matched_count, "modified": res.modified_count},
    )
    return {"ok": True, "publish": publish, "matched": res.matched_count, "updated": res.modified_count}


@api_router.get("/admin/products/{product_id}")
async def admin_product_detail(product_id: str, _: Dict[str, Any] = Depends(require_admin)):
    """FULL product document for the admin editor (cover + gallery base64).

    The list endpoint ships slim rows whose `image_url` is a lazy-load URL,
    so the editor must hydrate from here — otherwise the admin sees no photo
    before publishing and a save would blank it.
    """
    doc = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc


@api_router.patch("/admin/products/{product_id}")
async def admin_update_product(product_id: str, payload: ProductUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.products.find_one({"id": product_id})
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    from core.image_compress import compress_product_payload, strip_managed_image_urls
    from core.variants import apply_variants_to_payload
    update = compress_product_payload(strip_managed_image_urls(update, target))
    # Base price for "extra" mode = the price in THIS update if the vendor
    # changed it, otherwise the stored base/current price.
    _base = float(
        update.get("price")
        if update.get("price") is not None
        else (target.get("base_price") or target.get("price") or 0)
    )
    update = apply_variants_to_payload(update, _base)
    from core.taxonomy import normalize_product_taxonomy
    update = await normalize_product_taxonomy(update, target)
    await db.products.update_one({"id": product_id}, {"$set": update})
    # Dec 2026 — Bust shop caches so customers see the publish/edit
    # change on their very next /products call (was up to 60s delay).
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
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
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
    await _audit_log(admin, "product.delete", "product", product_id, {"name": target.get("name")})
    return {"ok": True}


# ------------------ Admin: User Management ------------------


@api_router.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: str, payload: AdminUserUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    # ── Paid status is IMMUTABLE (Aug-2026) ───────────────────────────
    # Once a Razorpay payment succeeded the member is a Subscriber for
    # life — no admin action may show them as unpaid again. Referral
    # payouts are controlled separately by
    # POST /admin/users/{id}/referral-approval.
    update.pop("registration_paid", None)
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
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    await _create_notification(user_id, "account", "Account updated", "Your account details were updated by admin.")
    if sensitive_fields & set(update.keys()):
        await _audit_log(admin, "admin.role_change", "user", user_id, {k: update[k] for k in sensitive_fields & set(update.keys())})
    return fresh


@api_router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, payload: AdminPasswordReset, _: Dict[str, Any] = Depends(require_admin_not_finance)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": user_id}, {"$set": password_fields(payload.new_password)})
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
        {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0, "kyc_aadhaar_front": 0, "kyc_aadhaar_back": 0, "kyc_pan_image": 0, "kyc_selfie": 0},
    ).sort("created_at", 1).to_list(2000)
    return items


@api_router.post("/admin/admins")
async def admin_create_admin(payload: AdminCreate, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Create a new admin account directly (no public registration)."""
    # Sep 2026 — scoped manager roles replace the old generic manager/support
    # ones for NEW promotions; existing manager/support/finance admins keep
    # working, so both sets are accepted here.
    if payload.admin_role not in ADMIN_SUB_ROLES:
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
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    return fresh


@api_router.post("/admin/users/{user_id}/promote")
async def admin_promote_user(user_id: str, payload: PromoteRequest, admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """Promote an existing user to admin with a sub-role."""
    # Sep 2026 — scoped manager roles replace the old generic manager/support
    # ones for NEW promotions; existing manager/support/finance admins keep
    # working, so both sets are accepted here.
    if payload.admin_role not in ADMIN_SUB_ROLES:
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
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
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
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
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
    # Sep 2026 — scoped reset: WHICH vendor's shop are we clearing?
    vendor_id: str
    backup_downloaded: bool = False


class AccountResetRequest(BaseModel):
    danger_pin: str = Field(..., min_length=6, max_length=6)
    user_id: str
    mode: str = "clear"          # "clear" (keep the login) | "delete"
    backup_downloaded: bool = False


# Sep 2026 — Danger-zone policy change (owner's decision):
# these resets NO LONGER write a snapshot inside the app. The admin must
# download the .json backup first (the UI enforces it and sets
# `backup_downloaded`), and restores happen by uploading that file in
# Admin → Data backups → File backup. One source of truth, no silent
# half-backups.
_BACKUP_REQUIRED_MSG = (
    "Download the backup file first — restores are only possible from that file."
)


@api_router.post("/admin/system/reset-shop-products")
async def admin_reset_shop_products(
    payload: ResetShopRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Clear ONE vendor's shop (owner's choice: products + layout + POS).

    Deletes, for the selected vendor only:
      • their products (and every review / cart row pointing at them)
      • their POS + online sales records and invoices
      • their product ids inside admin layout blocks (blocks left empty are
        removed, so the home page never shows a dead slot)

    Everything belonging to OTHER vendors, plus users, wallets, orders of
    other shops and global settings, is untouched. Requires the Danger PIN
    and a downloaded backup.
    """
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Please set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")
    if not payload.backup_downloaded:
        raise HTTPException(status_code=400, detail=_BACKUP_REQUIRED_MSG)

    vendor = await db.users.find_one({"id": payload.vendor_id}, {"_id": 0})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    mine = await db.products.find({"vendor_id": vendor["id"]}, {"_id": 0, "id": 1}).to_list(10000)
    product_ids = [m["id"] for m in mine if m.get("id")]

    summary: Dict[str, int] = {}
    summary["products_deleted"] = (await db.products.delete_many({"vendor_id": vendor["id"]})).deleted_count
    if product_ids:
        summary["product_reviews_deleted"] = (await db.product_reviews.delete_many({"product_id": {"$in": product_ids}})).deleted_count
        summary["cart_items_deleted"] = (await db.cart_items.delete_many({"product_id": {"$in": product_ids}})).deleted_count
        summary["product_questions_deleted"] = (await db.product_questions.delete_many({"product_id": {"$in": product_ids}})).deleted_count
    for coll in ("vendor_sales", "offline_sales", "vendor_invoices", "pos_invoices"):
        try:
            summary[f"{coll}_deleted"] = (await db[coll].delete_many({"vendor_id": vendor["id"]})).deleted_count
        except Exception:
            summary[f"{coll}_deleted"] = 0

    # Scrub this vendor's products out of hand-curated layout blocks.
    blocks_cleaned = 0
    blocks_removed = 0
    if product_ids:
        async for b in db.shop_layout_blocks.find({"product_ids": {"$in": product_ids}}, {"_id": 0, "id": 1, "product_ids": 1}):
            keep = [pid for pid in (b.get("product_ids") or []) if pid not in product_ids]
            if keep:
                await db.shop_layout_blocks.update_one({"id": b["id"]}, {"$set": {"product_ids": keep}})
                blocks_cleaned += 1
            else:
                await db.shop_layout_blocks.delete_one({"id": b["id"]})
                blocks_removed += 1
    summary["layout_blocks_cleaned"] = blocks_cleaned
    summary["layout_blocks_removed"] = blocks_removed

    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass

    await _audit_log(admin, "system.reset_shop_products", "vendor", vendor["id"], {**summary, "vendor_email": vendor.get("email")})
    return {
        "ok": True,
        "vendor": {"id": vendor["id"], "email": vendor.get("email"), "shop_name": vendor.get("shop_name") or vendor.get("name")},
        "summary": summary,
    }


@api_router.post("/admin/system/account-reset")
async def admin_account_reset(
    payload: AccountResetRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """Reset ONE account — replaces the old blanket "wipe all users".

    `mode="clear"` keeps the login and wipes everything the account owns
    (orders, transactions, withdrawals, cart, chat, notifications, tickets,
    products if they're a vendor, referral counters, wallet → ₹0), so the
    customer stays in the admin's list as a fresh account.
    `mode="delete"` does the same and then removes the account itself.

    Uses the SAME link-up rules as the per-account backup file, so what was
    downloaded is exactly what gets cleared.
    """
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Please set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")
    if not payload.backup_downloaded:
        raise HTTPException(status_code=400, detail=_BACKUP_REQUIRED_MSG)
    mode = (payload.mode or "clear").lower()
    if mode not in ("clear", "delete"):
        raise HTTPException(status_code=400, detail="mode must be 'clear' or 'delete'")
    if payload.user_id == admin["id"] and mode == "delete":
        raise HTTPException(status_code=400, detail="You can't delete your own admin account — use Clear data instead.")

    target = await db.users.find_one({"id": payload.user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if (target.get("role") == "admin") and mode == "delete":
        raise HTTPException(status_code=400, detail="Admin accounts can't be deleted here — use Admin access.")

    from routes.backup import scope_query
    email = (target.get("email") or "").lower() or None

    # Vendor products need their dependants cleaned too.
    mine = await db.products.find({"vendor_id": target["id"]}, {"_id": 0, "id": 1}).to_list(10000)
    product_ids = [m["id"] for m in mine if m.get("id")]
    if product_ids:
        await db.product_reviews.delete_many({"product_id": {"$in": product_ids}})
        await db.cart_items.delete_many({"product_id": {"$in": product_ids}})

    summary: Dict[str, int] = {}
    from routes.backup import NEVER_EXPORT, REFERENCE_COLLECTIONS
    protected = set(NEVER_EXPORT) | set(REFERENCE_COLLECTIONS) | {
        "settings", "branding", "audit_logs", "db_snapshots", "db_snapshot_chunks",
        "shop_categories", "shop_layout_blocks", "service_categories",
    }
    for coll in await db.list_collection_names():
        if coll in protected:
            continue
        q = scope_query(target["id"], email, coll)
        if coll == "users":
            # handled below so "clear" can keep the login
            continue
        try:
            res = await db[coll].delete_many(q)
            if res.deleted_count:
                summary[f"{coll}_deleted"] = res.deleted_count
        except Exception as e:
            logging.warning(f"account-reset: {coll} skipped: {e}")

    if mode == "delete":
        await db.users.delete_one({"id": target["id"]})
        summary["account_deleted"] = 1
    else:
        # Oct-2026 FIX — this only zeroed `wallet_balance`, so a vendor's
        # `vendor_earnings` (and a rider's COD cash-in-hand) survived a
        # "Clear data". That leftover vendor payable is subtracted from
        # company net worth, which is exactly why a freshly reset app still
        # showed a small negative figure. Every money pot and every role
        # flag is now zeroed — if a new wallet field is ever added it MUST
        # be added here too.
        await db.users.update_one({"id": target["id"]}, {"$set": {
            "wallet_balance": 0.0,
            "wallet_buckets": {b: 0.0 for b in SYSTEM_WALLET_BUCKETS},
            "total_earned": 0.0,
            "direct_referrals_count": 0,
            "payouts_received": 0,
            "wallet_frozen": False,
            # Shop / rider / legacy money pots
            "vendor_earnings": 0.0,
            "dp_cash_in_hand": 0.0,
            "pending_balance": 0.0,
            "refund_debt": 0.0,
            "total_spent": 0.0,
            "cashback_earned": 0.0,
            "pending_cashback": 0.0,
        }})
        summary["account_cleared"] = 1

    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass

    await _audit_log(admin, f"system.account_{mode}", "user", target["id"], {
        **summary, "email": target.get("email"), "name": target.get("name"),
    })
    return {
        "ok": True,
        "mode": mode,
        "account": {"id": target["id"], "email": target.get("email"), "name": target.get("name")},
        "summary": summary,
    }


@api_router.post("/admin/system/wipe-all")
async def admin_wipe_all(
    payload: WipeAllRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin")),
):
    """RESET APP TO ZERO — a true full-scan wipe.

    Sep 2026 rewrite. The old version deleted a hand-maintained list of ~22
    collections, so every feature added since (chat, POS invoices, wallet
    ledgers, shop layout, services, wishlists, device logins…) survived a
    "reset to zero" and the app was never actually zero. It now walks EVERY
    collection in the database (the same list the backup covers) and clears
    it, keeping only:
      • `settings` + `branding` (payout structure, business identity)
      • the seed super-admin login (wallet and counters zeroed)

    Requires the Danger PIN, the typed phrase "RESET", and a downloaded
    backup file — restores are done by uploading that file.
    """
    if not await get_danger_pin_hash():
        raise HTTPException(status_code=400, detail="Danger PIN not set. Please set it in Admin → Admin access.")
    if not await verify_danger_pin(payload.danger_pin):
        raise HTTPException(status_code=401, detail="Invalid Danger PIN")
    if (payload.confirm_phrase or "").strip().upper() != "RESET":
        raise HTTPException(status_code=400, detail='You must type "RESET" to confirm a full factory wipe')
    if not payload.backup_downloaded:
        raise HTTPException(status_code=400, detail=_BACKUP_REQUIRED_MSG)

    seed_admin_email = ADMIN_EMAIL.lower()
    seed = await db.users.find_one({"email": seed_admin_email})
    seed_id = seed["id"] if seed else admin["id"]

    from routes.backup import REFERENCE_COLLECTIONS
    keep_collections = {
        "settings", "branding",
        "db_snapshots", "db_snapshot_chunks",   # historical backups must survive a wipe
        *REFERENCE_COLLECTIONS,                 # pincode catalogue is reference data
    }

    summary: Dict[str, int] = {}
    for coll in await db.list_collection_names():
        if coll in keep_collections or coll == "users":
            continue
        try:
            res = await db[coll].delete_many({})
            if res.deleted_count:
                summary[f"{coll}_deleted"] = res.deleted_count
        except Exception as e:
            logging.warning(f"wipe-all: {coll} skipped: {e}")

    users_res = await db.users.delete_many({"id": {"$ne": seed_id}})
    summary["users_deleted"] = users_res.deleted_count

    await db.users.update_one({"id": seed_id}, {"$set": {
        "wallet_balance": 0.0,
        "total_earned": 0.0,
        "direct_referrals_count": 0,
        "payouts_received": 0,
        "wallet_buckets": {b: 0.0 for b in SYSTEM_WALLET_BUCKETS},
        "wallet_frozen": False,
        "is_blocked": False,
        "block_reason": None,
        # Oct 2026 — zero EVERY money pot and role the admin account may have
        # picked up while testing, so "reset to zero" really is zero. Any
        # future wallet field should be added here too.
        "vendor_earnings": 0.0,
        "dp_cash_in_hand": 0.0,
        "pending_balance": 0.0,
        "is_vendor": False,
        "is_vendor_approved": False,
        "vendor_status": None,
        "is_service_provider": False,
        "is_delivery_partner": False,
        "is_delivery_partner_approved": False,
        "dp_status": None,
        "dp_pincodes": [],
    }})

    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass

    # Audit last so this entry survives the wipe.
    await _audit_log(
        admin, "system.wipe_all", "system", "all",
        {"collections_cleared": len(summary), "summary": summary,
         "preserved": ["settings", "branding", "seed_admin", "db_snapshots", "pincodes"]},
    )
    return {
        "ok": True,
        "summary": summary,
        "collections_cleared": len(summary),
        "message": "App reset to zero. Only settings, branding and the super-admin login remain.",
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
# /cart/add, /cart, /cart/remove, /cart/clear, /orders/me — moved to
# routes/cart.py (Phase 2B Iter 4). POST /orders/checkout stays here for
# now because it depends on _trigger_referral_commissions (commission engine
# extraction is planned for the next refactor pass).


@api_router.post("/orders/checkout")
async def checkout(payload: Dict[str, Any] = Body(default={}), user: Dict[str, Any] = Depends(get_current_user)):
    """Place an order. Body:
      {
        "payment_method": "wallet" | "cod" | "wallet_cod" | "online" | "wallet_online",
        "wallet_amount": 250.0,        # only for "wallet_cod" / "wallet_online"
        "payment_id": "...",           # required for "online" / "wallet_online"
                                       # (a VERIFIED /orders/payment/verify attempt)
        "shipping_address": { ... }
      }
    Wallet flow debits the user's wallet immediately. COD skips wallet debit;
    the order is marked `paid_via: "cod"` and the platform/vendor commissions
    are credited only when the delivery is marked complete (out of scope here
    — captured on order status update). For COD we still atomically decrement
    stock so we don't oversell.  Online (Razorpay) money is captured BEFORE
    this call, so those orders are fully prepaid like wallet orders.
    """
    payment_method = str((payload or {}).get("payment_method") or "wallet").strip().lower()
    # Oct 2026 — delivery partners are riders, never customers.
    from routes.cart import _block_dp_shopping
    _block_dp_shopping(user)
    if payment_method not in ("wallet", "cod", "wallet_cod", "online", "wallet_online"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported payment_method. Use 'wallet', 'cod', 'wallet_cod', 'online' or 'wallet_online'.",
        )
    online_payment_id = str((payload or {}).get("payment_id") or "").strip()
    if payment_method in ("online", "wallet_online") and not online_payment_id:
        raise HTTPException(status_code=400, detail="Missing payment_id for the online payment.")
    raw_addr = (payload or {}).get("shipping_address") or {}
    # Defensive: some legacy clients may send shipping_address as a string
    # instead of an object. Treat anything non-dict as missing.
    if not isinstance(raw_addr, dict):
        raw_addr = {}
    # Preserve optional geospatial fields (latitude/longitude/district) —
    # required so the radius-mode delivery-zone check below can compute
    # haversine distance against the vendor's own lat/lng.
    def _num_or_none(v: Any) -> Optional[float]:
        try:
            if v is None or v == "": return None
            f = float(v)
            if f != f: return None  # NaN
            return f
        except Exception:
            return None
    shipping_address = {
        "name": str(raw_addr.get("name") or "").strip(),
        "phone": str(raw_addr.get("phone") or "").strip(),
        "line1": str(raw_addr.get("line1") or "").strip(),
        "line2": str(raw_addr.get("line2") or "").strip(),
        "city": str(raw_addr.get("city") or "").strip(),
        "state": str(raw_addr.get("state") or "").strip(),
        "pincode": str(raw_addr.get("pincode") or "").strip(),
        "latitude": _num_or_none(raw_addr.get("latitude") or raw_addr.get("lat")),
        "longitude": _num_or_none(raw_addr.get("longitude") or raw_addr.get("lng")),
        "district": str(raw_addr.get("district") or "").strip() or None,
    }
    # Validate required fields
    missing = [k for k in ("name", "phone", "line1", "city", "state", "pincode") if not shipping_address[k]]
    if missing:
        raise HTTPException(status_code=400, detail=f"Shipping address missing: {', '.join(missing)}")
    if len(shipping_address["pincode"]) < 5:
        raise HTTPException(status_code=400, detail="Pincode must be at least 5 digits.")

    if user.get("wallet_frozen") and payment_method in ("wallet", "wallet_cod", "wallet_online"):
        raise HTTPException(status_code=403, detail="Wallet is frozen. Pick COD or contact support.")
    items = await db.cart_items.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # ── Dec 2026 rewrite — Delivery-zone guard now MIRRORS the /products
    # eligibility rules used by the customer-facing shop.  This fixes the
    # bug where a vendor updated their pincode / radius / delivery mode
    # (admin-approved), the products listed correctly, but checkout still
    # rejected because the guard only inspected stale `store_pincode` /
    # `delivery_pincodes` fields denormalised onto the product document.
    #
    # The vendor's LIVE delivery config lives on the users doc.  We fetch
    # it once per unique vendor and apply the mode-aware check:
    #
    #   • mode "pincode" (or unset): customer pincode must equal
    #     `pincode`/`store_pincode`, OR appear in `delivery_pincodes`.
    #   • mode "radius": customer lat/lng must be within
    #     `delivery_radius_km` of vendor lat/lng (haversine).  If the
    #     customer didn't supply lat/lng, we fall back to Nominatim
    #     reverse-geocode via /geo/pincode (best-effort, non-fatal).
    #   • mode "both": either check passes.
    #
    # This is what customers now see in the Shop, so an add-to-cart that
    # succeeds MUST also allow checkout — no more silent mismatches.
    # ── Dec 2026 v2 — SINGLE SOURCE OF TRUTH.
    # The checkout guard now delegates to the EXACT same
    # `_eligible_vendor_ids` helper used by /products (the customer-facing
    # shop).  If a product is visible in the shop for the customer's
    # current pincode / lat-lng, it MUST be checkout-eligible.  Any drift
    # between the two checks was the root cause of "shows in shop but
    # can't be delivered at checkout".
    #
    # Customer lat/lng resolution order:
    #   1. shipping_address.latitude/longitude (if the app sent them).
    #   2. /geo/pincode → local db.pincodes catalogue.
    #   3. Nominatim forward geocode of the shipping pincode.
    # If none of these resolve, we still allow the pincode-only match to
    # succeed — same behaviour as the shop's /products endpoint.
    from routes.products_public import _eligible_vendor_ids as _shop_eligible_vendor_ids

    async def _pincode_latlng(pin: str) -> Optional[Tuple[float, float]]:
        """Best-effort lat/lng for a pincode (local DB → Nominatim)."""
        if not pin or not pin.isdigit():
            return None
        try:
            row = await db.pincodes.find_one({"pincode": pin}, {"_id": 0, "lat": 1, "lng": 1})
            if row and row.get("lat") and row.get("lng"):
                return (float(row["lat"]), float(row["lng"]))
        except Exception:
            pass
        try:
            import httpx
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": pin, "format": "jsonv2", "countrycodes": "in", "limit": 1},
                    headers={"User-Agent": "Slangcart/1.0 (contact: support@slangcart.com)", "Accept-Language": "en"},
                )
                if r.status_code == 200:
                    arr = r.json() or []
                    if arr:
                        return (float(arr[0].get("lat") or 0), float(arr[0].get("lon") or 0))
        except Exception:
            pass
        return None

    customer_pin = str(shipping_address.get("pincode") or "").strip()
    cust_lat = shipping_address.get("latitude")
    cust_lng = shipping_address.get("longitude")
    # Auto-resolve pincode → lat/lng when the client didn't send GPS,
    # so the radius-mode check still has coordinates to work with.
    if not (isinstance(cust_lat, (int, float)) and isinstance(cust_lng, (int, float))):
        pin_ll = await _pincode_latlng(customer_pin)
        if pin_ll:
            cust_lat, cust_lng = pin_ll
            shipping_address["latitude"] = cust_lat
            shipping_address["longitude"] = cust_lng

    # ── Compute the SAME "vendors who can deliver here" set that the
    #    shop uses.  Any product whose vendor is in this set is
    #    guaranteed deliverable.
    eligible_vids = await _shop_eligible_vendor_ids(
        pincode=customer_pin or None,
        lat=float(cust_lat) if isinstance(cust_lat, (int, float)) else None,
        lng=float(cust_lng) if isinstance(cust_lng, (int, float)) else None,
    )

    zone_conflicts: List[str] = []
    cod_blocked: List[str] = []
    _vendor_name_cache: Dict[str, str] = {}
    # Jun-2026 — "Everyone" vendors (admin-approved ship-anywhere sellers)
    # keep normal COD inside their own pincode / km radius, but a far-away
    # order has to be paid online or from the wallet: there is nobody near
    # the buyer to collect cash. Resolved once per vendor, lazily.
    _far_away_cache: Dict[str, bool] = {}

    async def _is_far_away(vid: str) -> bool:
        if vid in _far_away_cache:
            return _far_away_cache[vid]
        from core.delivery import vendor_covers_locally
        v = await db.users.find_one({"id": vid}, {"_id": 0})
        far = not await vendor_covers_locally(
            v or {},
            pincode=customer_pin or None,
            lat=float(cust_lat) if isinstance(cust_lat, (int, float)) else None,
            lng=float(cust_lng) if isinstance(cust_lng, (int, float)) else None,
        )
        _far_away_cache[vid] = far
        return far

    async def _vendor_name(vid: str) -> str:
        if vid in _vendor_name_cache:
            return _vendor_name_cache[vid]
        v = await db.users.find_one({"id": vid}, {"_id": 0, "vendor_business_name": 1, "shop_name": 1, "name": 1, "pincode": 1, "store_pincode": 1, "delivery_radius_km": 1})
        # Keep this priority identical to routes/cart.py so the seller name
        # the buyer saw in the bag matches the name on the placed order.
        nm = (v or {}).get("vendor_business_name") or (v or {}).get("shop_name") or (v or {}).get("name") or "Vendor"
        _vendor_name_cache[vid] = nm
        return nm

    for it in items:
        prod = await db.products.find_one(
            {"id": it["product_id"]},
            {"_id": 0, "name": 1, "vendor_id": 1, "delivery_available": 1, "cod_available": 1},
        )
        if not prod:
            continue
        if prod.get("delivery_available") is False:
            zone_conflicts.append(f"{prod.get('name', 'A product')} is not available for delivery.")
            continue
        # Oct-2026 — per-product Cash-on-Delivery switch. The seller decides
        # which of his items he is willing to hand over against cash; if even
        # one item in the bag is prepaid-only the whole COD checkout is
        # refused with the item names, so the app can show exactly what to
        # remove (or tell the buyer to pay online).
        if payment_method in ("cod", "wallet_cod") and prod.get("cod_available") is False:
            cod_blocked.append(prod.get("name") or "A product")
        vid = prod.get("vendor_id")
        if not vid:
            # Legacy product with no vendor — allow through (matches
            # /products behaviour where legacy items surface too).
            continue
        if (
            payment_method in ("cod", "wallet_cod")
            and prod.get("cod_available") is not False
            and await _is_far_away(vid)
        ):
            cod_blocked.append(prod.get("name") or "A product")
        if vid in eligible_vids:
            continue  # ✅ Shop said "yes", checkout says "yes".
        vn = await _vendor_name(vid)
        zone_conflicts.append(
            f"{prod.get('name', 'A product')} — {vn} does not deliver to pincode {customer_pin or '(none)'}. "
            f"Try changing your shipping address or removing this item.",
        )

    if zone_conflicts:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "out_of_delivery_zone",
                "message": "Some cart items are outside the delivery zone for your shipping pincode.",
                "conflicts": zone_conflicts,
            },
        )
    if cod_blocked:
        names = ", ".join(cod_blocked[:4]) + ("…" if len(cod_blocked) > 4 else "")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "cod_not_available",
                "message": (
                    f"This item can't be delivered as Cash on Delivery. "
                    f"Please make the payment for the item and delivery to continue."
                ),
                "items": cod_blocked,
                "names": names,
            },
        )
    enriched = []
    total = 0.0
    settings = await get_settings()
    vendor_pct = float(settings.get("vendor_commission_pct") or 70)
    vendor_payouts: Dict[str, float] = {}  # vendor_id -> total credit (legacy, unused post-split)

    # Cashback helpers bound to THIS checkout's settings snapshot.
    from core.cashback import (
        product_cashback_pct as _cb_pct,
        cashback_amount as _cb_amount,
    )

    def _cb_line_pct(prod: Dict[str, Any]) -> float:
        return _cb_pct(prod, settings)

    # ---------------- ATOMIC STOCK DECREMENT (multi-product) ----------------
    # We decrement stock per line BEFORE wallet debit. If any line fails (out of
    # stock or insufficient stock), we roll back every successful decrement so
    # nobody is left holding the bag. This prevents overselling under concurrent
    # checkouts.
    decremented: List[Dict[str, Any]] = []  # [{product_id, qty, variant_id}]
    from core.variants import effective_line_price as _variant_price, find_variant as _find_variant
    try:
        for it in items:
            product = await db.products.find_one({"id": it["product_id"]}, {"_id": 0})
            if not product:
                raise HTTPException(status_code=400, detail=f"Product no longer exists: {it['product_id']}")
            qty = int(it.get("qty") or 1)
            # ── Jun 2026 — variant-aware stock ──────────────────────────
            # For products with sizes / RAM-ROM options the authoritative
            # stock sits on the VARIANT. We decrement the matching array
            # element AND the product total in one conditional update, so
            # two shoppers can't buy the last size-L at the same time.
            variant = _find_variant(product, it.get("variant_id"))
            active_variants = [v for v in (product.get("variants") or []) if v.get("active", True)]
            if active_variants and not variant:
                raise HTTPException(
                    status_code=400,
                    detail=f"'{product.get('name')}' needs a size / option — please re-pick it in your cart.",
                )
            if variant:
                res = await db.products.update_one(
                    {
                        "id": product["id"],
                        "variants": {"$elemMatch": {"id": variant.get("id"), "stock": {"$gte": qty}}},
                    },
                    {"$inc": {"variants.$.stock": -qty, "stock": -qty}},
                )
                if res.modified_count == 0:
                    fresh = await db.products.find_one({"id": product["id"]}, {"_id": 0, "variants": 1, "name": 1})
                    fv = _find_variant(fresh or {}, variant.get("id")) or {}
                    avail = int(fv.get("stock") or 0)
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"'{product.get('name')}' — {variant.get('label')} is out of stock "
                            f"(only {avail} left, you wanted {qty})"
                        ),
                    )
            else:
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
            decremented.append({
                "product_id": product["id"],
                "qty": qty,
                "variant_id": (variant or {}).get("id"),
            })

            unit_price = _variant_price(product, variant)
            line_total = round(unit_price * qty, 2)
            total += line_total
            vendor_id = product.get("vendor_id")
            # Phase 1 (Jun-2026) — NO SHOP COMMISSION on the shop delivery
            # flow. The vendor is entitled to 100 % of the goods value; the
            # only money Slangcart takes is the delivery charge, and that is
            # settled from the vendor wallet AFTER successful delivery.
            vendor_share = line_total if vendor_id else 0.0
            platform_share = 0.0 if vendor_id else line_total
            if vendor_id:
                vendor_payouts[vendor_id] = vendor_payouts.get(vendor_id, 0.0) + vendor_share
            enriched.append({
                "product_id": product["id"],
                "name": product["name"],
                "price": unit_price,
                # Jun 2026 — remember which size / option was bought so the
                # invoice, vendor packing slip and returns all agree.
                "variant_id": (variant or {}).get("id") or None,
                "variant_label": (variant or {}).get("label") or "",                # Dec 2026 — image_url is optional on modern products
                # (multi-image `images[]` array is the new source of truth).
                # Fall back to the first images[] entry or an empty string
                # so checkout never crashes on legacy / minimal seeds.
                "image_url": (
                    product.get("image_url")
                    or (product.get("images") or [None])[0]
                    or ""
                ),
                "qty": qty,
                "line_total": line_total,
                "vendor_id": vendor_id,
                "vendor_share": vendor_share,
                "platform_share": platform_share,
                # ── Purchase cashback (Jun-2026) ───────────────────────
                # The percentage is FROZEN onto the order line here, so a
                # later vendor edit can never change what this customer
                # was promised. Calculated server-side only — the client
                # never gets to say what the cashback is.
                "cashback_pct": _cb_line_pct(product),
                "cashback_amount": _cb_amount(line_total, _cb_line_pct(product)),
                "free_delivery": bool(product.get("free_delivery")),
                # ── GST snapshot (Sep-2026) ────────────────────────────
                # Prices are GST-INCLUSIVE, so the tax is pulled OUT of
                # `line_total` and frozen onto the order line. Checkout, the
                # order screen and the web invoice all read these same
                # numbers, so the customer's CGST/SGST can never differ
                # between screens or change if the vendor edits the product.
                **(lambda sp: {
                    "gst_pct": sp["gst_pct"],
                    "taxable_value": sp["base_amount"],
                    "cgst_pct": sp["cgst_pct"],
                    "sgst_pct": sp["sgst_pct"],
                    "cgst_amount": sp["cgst_amount"],
                    "sgst_amount": sp["sgst_amount"],
                    "gst_amount": sp["total_gst"],
                })(_gst_engine.split_inclusive(
                    line_total, _gst_engine.clamp_gst_pct(product.get("selling_gst_pct")),
                )),
            })
        if total <= 0:
            raise HTTPException(status_code=400, detail="Cart total invalid")
    except HTTPException:
        # Roll back all successful stock decrements before re-raising
        # (variant rows put the stock back on BOTH the option and the total).
        for d in decremented:
            if d.get("variant_id"):
                await db.products.update_one(
                    {"id": d["product_id"], "variants.id": d["variant_id"]},
                    {"$inc": {"variants.$.stock": d["qty"], "stock": d["qty"]}},
                )
            else:
                await db.products.update_one(
                    {"id": d["product_id"]},
                    {"$inc": {"stock": d["qty"]}},
                )
        raise

    # ── Jun 2026 — MULTI-VENDOR SPLIT + WALLET/COD COMBO ─────────────
    # Every checkout is now split into ONE order document per vendor so
    # each seller owns an independent status thread, order number,
    # delivery ETA and cancellation window.  A shared `group_id` ties
    # the sibling orders back to the single customer checkout.
    #
    # Payment is resolved once for the whole basket and then allocated
    # across the sub-orders in cart order:
    #   • "wallet"     → wallet_paid = line total, cod_due = 0
    #   • "cod"        → wallet_paid = 0,          cod_due = line total
    #   • "wallet_cod" → wallet covers `wallet_amount`, cash covers rest
    LEGACY_VENDOR_KEY = "__no_vendor__"
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for it in enriched:
        groups.setdefault(it.get("vendor_id") or LEGACY_VENDOR_KEY, []).append(it)

    # ── Jun-2026 — DELIVERY CHARGES ──────────────────────────────────────
    # Priced per seller from that seller's own subtotal, then capped for the
    # whole cart so a multi-seller basket never pays duplicate delivery.
    # Computed entirely server-side; the client cannot influence it.
    from core.delivery_charges import compute_cart_delivery

    _vendor_docs: Dict[str, Dict[str, Any]] = {}
    for _vk in groups:
        if _vk != LEGACY_VENDOR_KEY:
            _vd = await db.users.find_one(
                {"id": _vk},
                {"_id": 0, "id": 1, "delivery_charge_flat": 1, "delivery_free_threshold": 1},
            )
            if _vd:
                _vendor_docs[_vk] = _vd

    delivery_quote = compute_cart_delivery(
        [
            {
                "vendor_key": vk,
                "vendor_id": None if vk == LEGACY_VENDOR_KEY else vk,
                "subtotal": round(sum(float(i["line_total"]) for i in vitems), 2),
                "free_delivery": all(bool(i.get("free_delivery")) for i in vitems),
            }
            for vk, vitems in groups.items()
        ],
        settings,
        _vendor_docs,
    )
    delivery_total = float(delivery_quote["total"])
    # Everything the customer owes — goods + delivery. All payment splits
    # below are resolved against this figure.
    payable_total = round(total + delivery_total, 2)

    # Resolve how much of the basket the wallet should cover.
    online_target = 0.0
    if payment_method == "wallet":
        wallet_target = payable_total
    elif payment_method == "cod":
        wallet_target = 0.0
    elif payment_method == "online":
        # Razorpay already collected the whole bill.
        wallet_target = 0.0
        online_target = payable_total
    elif payment_method == "wallet_online":
        try:
            wallet_target = float((payload or {}).get("wallet_amount") or 0)
        except Exception:
            wallet_target = 0.0
        wallet_target = max(0.0, min(round(wallet_target, 2), payable_total))
        online_target = round(payable_total - wallet_target, 2)
        if online_target <= 0.009:
            payment_method, online_target, wallet_target = "wallet", 0.0, payable_total
    else:  # wallet_cod
        try:
            wallet_target = float((payload or {}).get("wallet_amount") or 0)
        except Exception:
            wallet_target = 0.0
        wallet_target = max(0.0, min(round(wallet_target, 2), payable_total))
        if wallet_target <= 0:
            payment_method = "cod"
        elif wallet_target >= payable_total - 0.009:
            payment_method = "wallet"
            wallet_target = payable_total

    # ── Online (Razorpay) money was captured BEFORE this call.  Claim the
    #    verified attempt now — single-use, and it must match the amounts we
    #    just priced from the cart.  Any mismatch aborts before stock/wallet
    #    are touched (the stock rollback below runs on the raised error).
    online_attempt = None
    if online_target > 0:
        from routes.order_payments import consume_paid_attempt
        try:
            online_attempt = await consume_paid_attempt(
                user["id"], online_payment_id, online_target, wallet_target,
            )
        except HTTPException:
            for d in decremented:
                if d.get("variant_id"):
                    await db.products.update_one(
                        {"id": d["product_id"], "variants.id": d["variant_id"]},
                        {"$inc": {"variants.$.stock": d["qty"], "stock": d["qty"]}},
                    )
                else:
                    await db.products.update_one({"id": d["product_id"]}, {"$inc": {"stock": d["qty"]}})
            raise
        # Phase 1 — payment reconciliation. The money is captured; from here
        # on, if ANYTHING stops the order from being created, this row is the
        # trace: it stays `awaiting_order` and shows up in
        # GET /api/admin/finance/reconciliations (and the customer can resume
        # via GET /orders/payment/pending — never paying twice).
        try:
            await db.payment_reconciliations.update_one(
                {"_id": f"PAY:{online_attempt['id']}"},
                {"$setOnInsert": {
                    "payment_id": online_attempt["id"],
                    "razorpay_order_id": online_attempt.get("razorpay_order_id"),
                    "razorpay_payment_id": online_attempt.get("razorpay_payment_id"),
                    "user_id": user["id"],
                    "user_email": user.get("email"),
                    "amount": round(float(online_attempt.get("online_amount") or 0), 2),
                    "wallet_amount": round(float(online_attempt.get("wallet_amount") or 0), 2),
                    "intended_total": round(float(online_attempt.get("cart_total") or 0), 2),
                    "status": "awaiting_order",
                    "error": None,
                    "created_at": now_utc().isoformat(),
                }},
                upsert=True,
            )
        except Exception as _rc_err:
            logger.warning(f"reconciliation row failed: {str(_rc_err)[:160]}")
    if wallet_target > 0:
        # ATOMIC debit — guards against rapid double-clicks creating
        # duplicate orders. Only succeeds if the balance still covers it.
        debit_res = await db.users.update_one(
            {"id": user["id"], "wallet_balance": {"$gte": wallet_target}},
            {"$inc": {"wallet_balance": -wallet_target}},
        )
        if debit_res.modified_count == 0:
            for d in decremented:
                if d.get("variant_id"):
                    await db.products.update_one(
                        {"id": d["product_id"], "variants.id": d["variant_id"]},
                        {"$inc": {"variants.$.stock": d["qty"], "stock": d["qty"]}},
                    )
                else:
                    await db.products.update_one({"id": d["product_id"]}, {"$inc": {"stock": d["qty"]}})
            raise HTTPException(status_code=400, detail=f"Insufficient wallet balance. Need ₹{wallet_target:.0f}")

    group_id = str(uuid.uuid4())
    group_ref = group_id[:6].upper()
    split_count = len(groups)
    ts_now = now_utc().isoformat()

    # Warm the vendor-name cache (one lookup per vendor).
    for vkey in list(groups.keys()):
        if vkey != LEGACY_VENDOR_KEY:
            await _vendor_name(vkey)

    settings_now = await get_settings()
    shop_margin_on = bool(settings_now.get("shop_margin_enabled", False))
    # Needed for the delivery-charge ledger rows too, so fetch it always.
    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1})

    created_orders: List[Dict[str, Any]] = []
    wallet_left = round(wallet_target, 2)
    online_left = round(online_target, 2)
    for idx, (vkey, vitems) in enumerate(groups.items(), start=1):
        goods_total = round(sum(float(i["line_total"]) for i in vitems), 2)
        delivery_charge = round(float((delivery_quote["per_vendor"].get(vkey) or {}).get("charge") or 0), 2)
        sub_total = round(goods_total + delivery_charge, 2)
        wallet_paid = round(min(wallet_left, sub_total), 2)
        online_paid = round(min(online_left, sub_total - wallet_paid), 2)
        cod_due = round(sub_total - wallet_paid - online_paid, 2)
        wallet_left = round(wallet_left - wallet_paid, 2)
        online_left = round(online_left - online_paid, 2)

        if cod_due <= 0.009:
            cod_due = 0.0
            if online_paid > 0.009 and wallet_paid > 0.009:
                sub_paid_via, sub_pay_status = "wallet_online", "paid"
            elif online_paid > 0.009:
                sub_paid_via, sub_pay_status = "online", "paid"
            else:
                sub_paid_via, sub_pay_status = "wallet", "paid"
        elif wallet_paid <= 0.009:
            wallet_paid = 0.0
            sub_paid_via, sub_pay_status = "cod", "pending_cod"
        else:
            sub_paid_via, sub_pay_status = "wallet_cod", "partial_cod"

        order_id = str(uuid.uuid4())
        order_number = f"SC-{group_ref}" + (f"-{idx}" if split_count > 1 else "")
        vendor_id = None if vkey == LEGACY_VENDOR_KEY else vkey
        order = {
            "id": order_id,
            "order_number": order_number,
            "group_id": group_id,
            "split_index": idx,
            "split_count": split_count,
            "user_id": user["id"],
            "vendor_id": vendor_id,
            "vendor_name": _vendor_name_cache.get(vkey) if vendor_id else None,
            "items": vitems,
            "total": sub_total,
            # Jun-2026 — goods vs delivery kept separate so the treasury
            # never mixes delivery money with product revenue or cashback.
            "goods_total": goods_total,
            "delivery_charge": delivery_charge,
            # GST snapshot for this seller's sub-order (prices are inclusive).
            "gst_summary": {
                "inclusive": True,
                "taxable_value": round(sum(float(i.get("taxable_value") or 0) for i in vitems), 2),
                "cgst_amount": round(sum(float(i.get("cgst_amount") or 0) for i in vitems), 2),
                "sgst_amount": round(sum(float(i.get("sgst_amount") or 0) for i in vitems), 2),
                "total_gst": round(sum(float(i.get("gst_amount") or 0) for i in vitems), 2),
                "delivery_gst": round(
                    float(_gst_engine.split_inclusive(delivery_charge, 18.0)["total_gst"]), 2,
                ) if delivery_charge > 0 else 0.0,
                "delivery_taxable": round(
                    float(_gst_engine.split_inclusive(delivery_charge, 18.0)["base_amount"]), 2,
                ) if delivery_charge > 0 else 0.0,
            },
            "delivery_free": bool((delivery_quote["per_vendor"].get(vkey) or {}).get("free")),
            "delivery_reason": (delivery_quote["per_vendor"].get(vkey) or {}).get("reason"),
            # Cashback promised on this sub-order, credited only on delivery.
            "cashback_amount": round(sum(float(i.get("cashback_amount") or 0) for i in vitems), 2),
            "cashback_status": "awaiting_delivery",
            "wallet_paid": wallet_paid,
            "online_paid": online_paid,
            "cod_due": cod_due,
            "status": "placed",
            # Jun 2026 — tracking timeline starts the moment the order lands.
            "status_history": [{
                "status": "placed",
                "at": ts_now,
                "by_name": user.get("name") or "Customer",
                "by_role": "customer",
            }],
            "paid_via": sub_paid_via,
            "payment_status": sub_pay_status,
            "razorpay_payment_id": (online_attempt or {}).get("razorpay_payment_id") if online_paid > 0 else None,
            "shipping_address": shipping_address,
            "created_at": ts_now,
        }
        await db.orders.insert_one(dict(order))
        created_orders.append(order)

        # ── Buyer ledger entries ────────────────────────────────────────
        # Oct-2026 FIX — only the wallet slice was ever written, so a
        # "wallet + UPI" order showed ONE row for part of the money and the
        # UPI amount appeared nowhere in the customer's transaction list.
        # Both legs are now recorded: the wallet leg really moves a balance,
        # and the UPI leg is marked `informational` so it is visible without
        # being counted twice in any balance reconciliation.
        if wallet_paid > 0:
            try:
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": user["id"],
                    "type": "order",
                    "amount": -wallet_paid,
                    "status": "success",
                    "description": (
                        f"Order {order_number} ({len(vitems)} items) — "
                        f"₹{wallet_paid:,.2f} paid from Slangcart wallet"
                        + (f" of ₹{round(wallet_paid + online_paid, 2):,.2f}" if online_paid > 0.009 else "")
                    ),
                    "payment_leg": "wallet",
                    "order_id": order_id,
                    "created_at": ts_now,
                })
            except DuplicateKeyError:
                pass
        if online_paid > 0.009:
            try:
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": user["id"],
                    "type": "order_payment_upi",
                    "amount": -online_paid,
                    "status": "success",
                    "description": (
                        f"Order {order_number} ({len(vitems)} items) — "
                        f"₹{online_paid:,.2f} paid by UPI / card"
                        + (f", ₹{wallet_paid:,.2f} from wallet" if wallet_paid > 0.009 else "")
                    ),
                    "payment_leg": "online",
                    "payment_method": "razorpay",
                    "razorpay_payment_id": (online_attempt or {}).get("razorpay_payment_id"),
                    "order_id": order_id,
                    # Never touched the wallet balance — money went straight
                    # from the buyer's bank to ours.
                    "wallet_impact": "informational",
                    "created_at": ts_now,
                })
            except DuplicateKeyError:
                pass

        # Vendor sales ledger rows (one per line item, scoped to sub-order).
        for it in vitems:
            if not it.get("vendor_id"):
                continue
            await db.vendor_sales.insert_one({
                "id": str(uuid.uuid4()),
                "vendor_id": it["vendor_id"],
                "order_id": order_id,
                "order_number": order_number,
                "group_id": group_id,
                "buyer_id": user["id"],
                "buyer_email": user.get("email"),
                "product_id": it["product_id"],
                "product_name": it["name"],
                # Sep-2026 — store the image so the vendor's order card can
                # render a thumbnail without re-joining the catalogue.
                "product_image_url": it.get("image_url") or "",
                "qty": it["qty"],
                "line_total": it["line_total"],
                "vendor_share": it["vendor_share"],
                "platform_share": it["platform_share"],
                "commission_pct": vendor_pct,
                "created_at": ts_now,
            })

        # ── Sep 2026 — ORDER NOTIFICATIONS (bell + phone push) ──────────
        # The buyer and vendor already get bell rows further down; what was
        # missing was (a) any notification for ADMINS and (b) a phone push
        # for anyone, which is why "order notifications not coming" was
        # reported across the board.
        try:
            push_targets = [user["id"]]
            if admin_doc:
                await _create_notification(
                    admin_doc["id"], "order", "New order",
                    f"{order_number} · ₹{sub_total:.0f} from {user.get('name') or user.get('email')}",
                    extra={"order_id": order_id, "action_url": "/admin/orders"},
                    push=False,  # covered by the batched send_push below
                )
                push_targets.append(admin_doc["id"])
            from routes.push import send_push
            await send_push(
                recipients=push_targets,
                data={
                    "title": f"🛒 Order {order_number}",
                    "message": f"₹{sub_total:.0f} · {len(vitems)} item(s)",
                    "action_url": f"/orders/{order_id}",
                },
                idempotency_key=f"order-new-{order_id}",
                category="orders",
            )
            # The seller's "New order received" alert is its own preference —
            # a shop owner may want order pings while muting everything else.
            if vendor_id:
                await send_push(
                    recipients=[vendor_id],
                    data={
                        "title": f"🛒 New order {order_number}",
                        "message": f"₹{sub_total:.0f} · {len(vitems)} item(s) — tap to pack it.",
                        "action_url": "/vendor/orders",
                    },
                    idempotency_key=f"order-new-vendor-{order_id}",
                    category="vendor_new_order",
                )
        except Exception as e:
            logging.warning(f"order notification failed (non-blocking): {e}")

        # ── Phase 1 money movement ─────────────────────────────────────
        # The vendor is credited the PREPAID money for this sub-order
        # (wallet slice + Razorpay slice, delivery included) — exactly once,
        # through the single shop-money engine. Cash-on-delivery money is
        # collected physically by the seller, so it is never credited into a
        # wallet and never faked into the customer's wallet.
        #
        # The delivery charge is NOT recognised here any more: it is settled
        # vendor wallet → system treasury when the order is DELIVERED
        # (PATCH …/orders/{id}/status), which is the only point the service
        # has actually been performed. No shop commission is taken at all.
        fresh_sub = await db.orders.find_one({"id": order_id}, {"_id": 0})
        if cod_due > 0.009:
            # Cash-on-delivery leg: no money moves, but the customer must SEE
            # the order in their history and on the invoice as a cash order.
            await shop_money.post(
                group="customer_liability",
                txn_type="cod_order",
                amount=0.0,
                idempotency_key=f"COD:{order_id}",
                user_id=user["id"],
                order_id=order_id,
                order_number=order_number,
                vendor_id=vendor_id,
                shop_name=(fresh_sub or {}).get("vendor_name"),
                payment_method=(fresh_sub or {}).get("paid_via") or "cod",
                delivery_charge=delivery_charge,
                settlement_status="pay_on_delivery",
                description=(
                    f"Cash on Delivery order {order_number} — ₹{cod_due:.0f} to be paid "
                    f"to the delivery agent"
                ),
                extra={"order_amount": round(float(sub_total), 2),
                       "cod_amount": cod_due,
                       "wallet_paid": round(float(sub_total) - cod_due, 2),
                       "wallet_impact": "none"},
            )
        try:
            _sub_for_credit = fresh_sub or {"id": order_id, "vendor_id": vendor_id,
                                            "order_number": order_number,
                                            "total": sub_total, "cod_due": cod_due}
            _credited = await shop_money.credit_vendor_for_order(_sub_for_credit)
            # Oct-2026 OWNER RULE — before this money becomes withdrawable,
            # claw back any cashback Slangcart fronted to buyers on this
            # seller's behalf. Only the remainder stays in his wallet, and
            # both the gross sale and the recovery stay visible as separate
            # ledger rows.
            if vendor_id and _credited > 0.009:
                from core.cashback import auto_recover_from_vendor_credit
                _rec = await auto_recover_from_vendor_credit(
                    vendor_id, _sub_for_credit, credit_admin_bucket=credit_admin_bucket,
                )
                if _rec.get("recovered", 0) > 0.009:
                    logger.info(
                        f"cashback auto-recovered ₹{_rec['recovered']} from vendor "
                        f"{vendor_id} on order {order_number}"
                    )
        except Exception as _vc_err:
            logger.warning(f"vendor credit failed for {order_id}: {str(_vc_err)[:200]}")
            await shop_money.record_financial_error(
                "vendor_credit_failed", str(_vc_err), order_id=order_id, vendor_id=vendor_id,
            )
        if vendor_id and shop_money.prepaid_amount(fresh_sub or {"total": sub_total, "cod_due": cod_due}) > 0.009:
            try:
                await _create_notification(
                    vendor_id, "vendor", "New sale!",
                    f"₹{shop_money.prepaid_amount(fresh_sub or {'total': sub_total, 'cod_due': cod_due}):.0f} "
                    f"credited from order {order_number}.",
                )
            except Exception:
                pass

    # Vendors with a cash balance still need a heads-up about the order.
    for o in created_orders:
        if o.get("vendor_id") and float(o.get("cod_due") or 0) > 0.009:
            try:
                await _create_notification(
                    o["vendor_id"], "vendor", "New order received",
                    f"Order {o['order_number']} · ₹{o['total']:.0f} ({o['paid_via'].upper().replace('_', '+')}).",
                )
            except Exception:
                pass

    await db.cart_items.delete_many({"user_id": user["id"]})

    # Bind the Razorpay payment to this order group so it can never be
    # reused for a second checkout.
    if online_attempt:
        from routes.order_payments import mark_attempt_consumed
        await mark_attempt_consumed(online_attempt["id"], group_id)
        # Sep-2026 — the customer's online money physically landed in OUR
        # bank account, so it must appear in the Bank Ledger (Group 7).
        # It is NOT our revenue: the goods belong to the vendor, so the
        # matching vendor payable sits in Group 2 (user/vendor liability).
        await bank.post_bank(
            kind="credit",
            amount=float(online_attempt.get("online_amount") or 0),
            category="shop_order_online",
            description=(
                f"Shop order paid online · {user.get('name') or user.get('email')} "
                f"· group {group_id[:8]}"
            ),
            ref_key=f"ORDERPAY:{online_attempt['id']}",
            utr=online_attempt.get("razorpay_payment_id"),
            user_id=user["id"],
            extra={
                "order_group_id": group_id,
                "razorpay_payment_id": online_attempt.get("razorpay_payment_id"),
                "razorpay_order_id": online_attempt.get("razorpay_order_id"),
                "vendor_ids": [o.get("vendor_id") for o in created_orders if o.get("vendor_id")],
            },
        )
        await db.payment_reconciliations.update_one(
            {"_id": f"PAY:{online_attempt['id']}"},
            {"$set": {
                "status": "completed",
                "order_group_id": group_id,
                "completed_at": now_utc().isoformat(),
            }},
        )

    wallet_total_used = round(sum(float(o["wallet_paid"]) for o in created_orders), 2)
    online_total_used = round(sum(float(o.get("online_paid") or 0) for o in created_orders), 2)
    cod_total_due = round(sum(float(o["cod_due"]) for o in created_orders), 2)
    await _create_notification(
        user["id"], "order",
        "Order placed!" if split_count == 1 else f"{split_count} orders placed!",
        f"Your order of ₹{int(payable_total)} has been placed."
        + (f" ₹{int(cod_total_due)} due on delivery." if cod_total_due > 0 else ""),
    )

    cashback_promised = round(sum(float(o.get("cashback_amount") or 0) for o in created_orders), 2)
    first = created_orders[0]
    return {
        # Multi-vendor payload — one entry per seller.
        "orders": created_orders,
        "group_id": group_id,
        "split_count": split_count,
        "grand_total": payable_total,
        "goods_total": total,
        "delivery_total": delivery_total,
        "delivery_breakdown": delivery_quote,
        "cashback_promised": cashback_promised,
        "wallet_paid": wallet_total_used,
        "online_paid": online_total_used,
        "cod_due": cod_total_due,
        # Legacy top-level fields (older clients read these directly).
        "id": first["id"],
        "order_number": first["order_number"],
        "total": payable_total,
        "status": "placed",
        "paid_via": payment_method,
        "items": enriched,
        "shipping_address": shipping_address,
        "created_at": ts_now,
    }


# GET /orders/me extracted to /app/backend/routes/cart.py during Phase 2B refactor.


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
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0}) or user
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
        "password_hash": 0, "password_recovery_ciphertext": 0,
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
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
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
        "_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0,
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
        {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0,
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
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
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
    # Approving a member also switches referral payouts ON (the switch the
    # admin sees as "Admin Approved" on the user edit sheet).
    await db.users.update_one(
        {"id": user_id},
        {"$set": {
            "referral_enabled": True,
            "referral_switch_note": "Enabled on account approval",
            "referral_switch_at": now_utc().isoformat(),
            "referral_switch_by": admin.get("email") or admin.get("id"),
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
        # Sep 2026 — hash for login + Fernet copy so a super-admin can read
        # the password back on a support call (see core/password_recovery).
        **password_fields(payload.password),
        "phone": payload.phone,
        "role": "user",
        "admin_role": None,
        "referral_code": code,
        "referred_by": sponsor["referral_code"] if sponsor else None,
        "sponsor_id": sponsor["id"] if sponsor else None,
        "wallet_balance": 0.0,
        "total_earned": 0.0,
        # ── Aug-2026: only TWO account types exist ────────────────────
        #   Subscriber      → Razorpay payment successful (in-app)
        #   Non-subscriber  → no subscription yet
        # Admin-created accounts always start as NON-SUBSCRIBERS. The member
        # activates the ₹118 subscription themselves from Shop / Dashboard /
        # Profile, which keeps the treasury + GST maths exact (every rupee
        # comes from a real Razorpay collection).
        "registration_paid": False,
        "registration_source": None,
        "payment_method": None,
        "paid_at": None,
        # Never wall an admin-created account behind the payment screen.
        "subscription_skipped": True,
        "subscription_skipped_at": now,
        # Referral payouts stay OFF until the admin flips "Admin Approved".
        "referral_enabled": False,
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

    await _create_notification(
        user_id, "welcome",
        "Account created by admin",
        "Your account was created by our team. You can sign in and start shopping right away — "
        "activate the ₹118 subscription any time from Shop, Dashboard or Profile to unlock cashback.",
    )
    await _audit_log(admin, "user.admin_create", "user", user_id, {"email": email, "type": "non_subscriber"})
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
    # Nov 2026 — Expose the GST sub-ledger (POS invoice GST collected
    # by vendors, tracked here for platform-side reporting).  Not part
    # of `wallet_balance` — this is a *ledger* count, not held cash.
    gst_agg = await db.system_wallet_deposits.aggregate([
        {"$match": {"bucket": "gst"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    gst_total = float(gst_agg[0]["total"]) if gst_agg else 0.0
    gst_count = int(gst_agg[0]["count"]) if gst_agg else 0
    deposits = await db.system_wallet_deposits.find({}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return {
        "buckets": out,
        "gst_bucket": {"total": round(gst_total, 2), "invoice_count": gst_count},
        "total": float(a.get("wallet_balance") or 0),
        "deposits": deposits,
    }


@api_router.get("/admin/system-wallet/source-breakdown")
async def system_wallet_source_breakdown(
    _admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "manager", "support", "finance")),
):
    """Group registration revenue by the canonical source the user registered through.

    Joins transactions(type=registration_fee, status=paid) → users.registration_source
    via $lookup so we don't have to denormalize the source onto every payout txn —
    the user doc is the single source of truth.

    Response shape:
      { "rows": [{source, count, amount}, ...],
        "totals": {count, amount},
        "fan_out": {source: {payouts_count, payouts_amount}, ...},
        "generated_at": iso8601 }

    `fan_out` is the downstream view: for each registration_source, how much
    money was paid out to the upline (referral_payout / direct_signup_credit /
    cascade_overflow). Lets admin see "Razorpay users generated ₹X in payouts,
    Offline users generated ₹Y" — the full accountability matrix.
    """
    # 1) Inflow side — registration fees grouped by user.registration_source
    inflow_pipeline = [
        {"$match": {"type": "registration_fee", "status": "paid"}},
        {"$lookup": {
            "from": "users",
            "localField": "user_id",
            "foreignField": "id",
            "as": "_u",
        }},
        {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": {"$ifNull": ["$_u.registration_source", "unknown"]},
            "count": {"$sum": 1},
            "amount": {"$sum": "$amount"},
        }},
        {"$project": {"_id": 0, "source": "$_id", "count": 1, "amount": 1}},
        {"$sort": {"amount": -1}},
    ]
    rows = await db.transactions.aggregate(inflow_pipeline).to_list(50)

    # 2) Fan-out side — payout txns whose `related_signup_id` ties back to a user.
    # These are the L1..L10 payouts + direct_signup_credit + cascade_overflow.
    fan_out_pipeline = [
        {"$match": {
            "type": {"$in": [
                "referral_payout", "direct_signup_credit", "cascade_overflow",
                "l1_funding", "gst_collected",
            ]},
            "status": {"$in": ["success", "paid"]},
            # Only payouts that were triggered by a SIGNUP (not by a shop order/withdrawal).
            "related_signup_id": {"$exists": True, "$ne": None},
        }},
        {"$lookup": {
            "from": "users",
            "localField": "related_signup_id",
            "foreignField": "id",
            "as": "_u",
        }},
        {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": {"$ifNull": ["$_u.registration_source", "unknown"]},
            "payouts_count": {"$sum": 1},
            "payouts_amount": {"$sum": {"$abs": "$amount"}},
        }},
        {"$project": {"_id": 0, "source": "$_id", "payouts_count": 1, "payouts_amount": 1}},
    ]
    fan_out_rows = await db.transactions.aggregate(fan_out_pipeline).to_list(50)
    fan_out = {r["source"]: {
        "payouts_count": int(r.get("payouts_count") or 0),
        "payouts_amount": float(r.get("payouts_amount") or 0),
    } for r in fan_out_rows}

    totals = {
        "count": sum(int(r.get("count") or 0) for r in rows),
        "amount": round(sum(float(r.get("amount") or 0) for r in rows), 2),
    }
    return {
        "rows": rows,
        "totals": totals,
        "fan_out": fan_out,
        "generated_at": now_utc().isoformat(),
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
    # Jun-2026 marketplace buckets. Signed types, so summing captures the
    # collection AND any settlement/reversal that flowed back out.
    "delivery_collected":  ["delivery_charge_collected", "delivery_charge_reversal"],
    "cashback_funded":     ["cashback_platform_funded", "cashback_vendor_recovery"],
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
            {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0},
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
            {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0},
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
        {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0},
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

    # ── Oct-2026 — pick the right pot ───────────────────────────────────
    # This endpoint only ever looked at `wallet_balance`, so debiting a
    # seller (money in `vendor_earnings`) or a rider (money in
    # `dp_cash_in_hand`) always failed with "Cannot debit beyond available
    # balance" even though they were in credit — and the admin screen never
    # showed those pots, so there was no way to tell why.
    POT_LABELS = {
        "wallet_balance":  "customer wallet",
        "vendor_earnings": "shop earnings",
        "dp_cash_in_hand": "rider cash in hand",
    }
    pot = (payload.wallet or "wallet_balance").strip()
    if pot not in POT_LABELS:
        raise HTTPException(
            status_code=400,
            detail="wallet must be wallet_balance, vendor_earnings or dp_cash_in_hand",
        )
    available = round(float(target.get(pot) or 0), 2)
    delta = payload.amount if payload.type == "credit" else -payload.amount
    if delta < 0 and round(available + delta, 2) < -0.009:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot debit ₹{payload.amount:,.2f} — {target.get('name') or 'this member'} "
                f"has ₹{available:,.2f} in their {POT_LABELS[pot]}."
            ),
        )

    # ── FUNDING SOURCE: COMPANY NET WORTH (Jun-2026) ─────────────────────
    # It used to require a balance in the system wallet's `direct_added`
    # bucket, which could only be filled by the "Add Direct-Added Money
    # (UTR)" button — and that button was REMOVED, so every admin credit
    # failed with "Insufficient Direct-Added funds". Admin credits now come
    # straight out of COMPANY NET WORTH, which is honest accounting:
    # crediting a customer raises the user-wallet liability, and net worth
    # already subtracts that liability, so the money is accounted for with
    # no extra ledger row. No hard block here — the company's own owner
    # decides what to hand out; the current net worth is surfaced in the UI
    # and returned below so the decision is always informed.
    if payload.type == "credit":
        await credit_admin_bucket("direct_added", -payload.amount, also_total_earned=False)

    # DEBIT path: money comes back out of the user's wallet into the company.
    if payload.type == "debit":
        await credit_admin_bucket("direct_added", payload.amount, also_total_earned=False)

    inc = {pot: delta}
    if payload.type == "credit" and pot == "wallet_balance":
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
        "wallet_target": pot,
        # Keep seller/rider pot movements out of the CUSTOMER wallet
        # reconciliation — they belong to a different balance.
        **({"wallet_impact": "vendor_earnings_only"} if pot == "vendor_earnings"
           else {"wallet_impact": "informational"} if pot == "dp_cash_in_hand" else {}),
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
    await _audit_log(admin, f"wallet.{payload.type}", "user", user_id, {"amount": payload.amount, "reason": payload.reason, "funded_from": "company_net_worth"})
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "wallet_balance": 1})
    return {
        "ok": True,
        "transaction_id": txn_id,
        "funded_from": "company_net_worth",
        "user_balance": round(float((fresh or {}).get("wallet_balance") or 0), 2),
    }


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
    return await _attach_order_parties(items)


async def _attach_order_parties(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add buyer + seller identity to order rows (Sep 2026, owner request).

    The admin order screen showed only an id and the products, so nobody knew
    WHO bought it or WHICH shop has to ship it. Names/phones are read in one
    batched query so the list stays fast.
    """
    if not orders:
        return orders
    ids = {o.get("user_id") for o in orders if o.get("user_id")}
    ids |= {o.get("vendor_id") for o in orders if o.get("vendor_id")}
    people: Dict[str, Dict[str, Any]] = {}
    if ids:
        rows = await db.users.find(
            {"id": {"$in": [i for i in ids if i]}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "store_name": 1, "shop_name": 1},
        ).to_list(2000)
        people = {r["id"]: r for r in rows}
    for o in orders:
        buyer = people.get(o.get("user_id") or "") or {}
        addr = o.get("shipping_address") or {}
        o["buyer_name"] = buyer.get("name") or addr.get("name") or "Customer"
        o["buyer_email"] = buyer.get("email") or ""
        o["buyer_phone"] = buyer.get("phone") or addr.get("phone") or ""
        seller = people.get(o.get("vendor_id") or "") or {}
        o["vendor_name"] = o.get("vendor_name") or seller.get("store_name") or seller.get("shop_name") or seller.get("name") or ""
        o["vendor_email"] = seller.get("email") or ""
        o["vendor_phone"] = seller.get("phone") or ""
    return orders


@api_router.get("/admin/orders/{order_id}")
async def admin_order_detail(order_id: str, _: Dict[str, Any] = Depends(require_admin)):
    """Everything about one order — used by the admin order-details sheet."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    (order,) = await _attach_order_parties([order])
    # Sibling sub-orders from the same checkout (multi-vendor split).
    siblings: List[Dict[str, Any]] = []
    if order.get("group_id"):
        rows = await db.orders.find(
            {"group_id": order["group_id"], "id": {"$ne": order_id}},
            {"_id": 0, "id": 1, "order_number": 1, "vendor_name": 1, "total": 1, "status": 1},
        ).to_list(20)
        siblings = rows
    return {"order": order, "siblings": siblings}


# Jun 2026 — Order tracking now has FIVE forward steps so the buyer can
# follow the parcel instead of guessing between "placed" and "delivered".
# `cancelled` is terminal and lives outside the flow.
ORDER_STATUS_FLOW = ("placed", "confirmed", "shipped", "out_for_delivery", "delivered")
ORDER_STATUSES = ORDER_STATUS_FLOW + ("cancelled",)
# Anything before delivery still owes cash on a COD order.
COD_PENDING_STATUSES = ("placed", "confirmed", "shipped", "out_for_delivery")

ORDER_STATUS_COPY = {
    "placed": ("Order placed", "We've got your order and the seller is reviewing it."),
    "confirmed": ("Order confirmed", "The seller confirmed your order and is packing it."),
    "shipped": ("Order shipped", "Your parcel has left the shop."),
    "out_for_delivery": ("Out for delivery", "Your parcel is on the way to you today."),
    "delivered": ("Order delivered", "Your parcel has been delivered. Enjoy!"),
}


@api_router.patch("/admin/orders/{order_id}/status")
async def admin_update_order_status(order_id: str, payload: OrderStatusUpdate, admin: Dict[str, Any] = Depends(require_admin_not_finance)):
    if payload.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Use one of: {', '.join(ORDER_STATUSES)}")
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    prev_status = order.get("status")
    ts_change = now_utc().isoformat()
    # Who moved it? The vendor endpoint delegates here with its own user doc.
    actor_role = "admin" if (admin.get("admin_role") or admin.get("is_admin")) else "seller"
    actor_name = (
        admin.get("vendor_business_name") or admin.get("shop_name")
        or admin.get("name") or admin.get("email") or "Slangcart"
    )
    await db.orders.update_one({"id": order_id}, {"$set": {"status": payload.status}})
    # Jun 2026 — append to the tracking timeline the buyer sees. Only real
    # transitions are recorded, so re-saving the same status is a no-op.
    if payload.status != prev_status:
        await db.orders.update_one(
            {"id": order_id},
            {"$push": {"status_history": {
                "status": payload.status,
                "at": ts_change,
                "by_name": actor_name,
                "by_role": actor_role,
            }}},
        )
    # Jun 2026 — Stamp the delivery moment so the vendor's "cash collected
    # today" figure keys off when the cash actually changed hands, not when
    # the order was placed.
    if payload.status == "delivered" and prev_status != "delivered":
        await db.orders.update_one({"id": order_id}, {"$set": {"delivered_at": now_utc().isoformat()}})
        # ── PURCHASE CASHBACK (Jun-2026) ──────────────────────────────────
        # This is the ONLY place cashback is credited: a real purchase that
        # actually reached the customer. `settle_order_cashback` claims the
        # order in `cashback_ledger` first, so duplicate delivery updates,
        # webhook retries and concurrent taps can never pay twice.
        try:
            from core.cashback import settle_order_cashback
            fresh_order = await db.orders.find_one({"id": order_id}, {"_id": 0})
            await settle_order_cashback(
                fresh_order or order,
                credit_admin_bucket=credit_admin_bucket,
                notify=_create_notification,
            )
        except Exception as _cb_err:
            logger.warning(f"cashback settlement failed for {order_id}: {str(_cb_err)[:300]}")

        # ── RECHARGE DONE (Jun-2026 owner report) ─────────────────────────
        # A recharge order has nothing to ship: "delivered" means the seller
        # (or the rider working that operator) actually performed the top-up.
        # That is the moment the buyer's Recharge history must stop saying
        # "Processing" and read "Successful".
        if order.get("is_recharge") and order.get("recharge_id"):
            done_at = now_utc().isoformat()
            res_rc = await db.recharges.update_one(
                {"id": order["recharge_id"], "status": {"$ne": "success"}},
                {"$set": {"status": "success", "completed_at": done_at,
                          "completed_by": actor_name, "completed_by_role": actor_role}},
            )
            if res_rc.modified_count:
                try:
                    await _create_notification(
                        order["user_id"], "order", "Recharge successful",
                        f"{order.get('recharge_account') or ''} · ₹{float(order.get('total') or 0):.0f} "
                        f"— your recharge is done.",
                        extra={"order_id": order_id, "action_url": "/recharge-history"},
                    )
                except Exception:
                    pass

    # ── DELIVERED → settle the delivery charge, once, for EVERY order ────
    # Phase 1: the ONLY money Slangcart takes on a shop order is the
    # delivery charge, and it is recognised the moment delivery succeeds:
    # vendor wallet → system treasury + Revenue Ledger. Free delivery moves
    # nothing. There is NO shop commission anywhere in this flow.
    paid_via = order.get("paid_via") or "wallet"
    items = order.get("items") or []
    if payload.status == "delivered" and prev_status != "delivered":
        fresh_for_fee = await db.orders.find_one({"id": order_id}, {"_id": 0}) or order
        admin_for_del = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1})
        # Oct 2026 — COD collected by a DELIVERY PARTNER is the company's
        # cash, not the seller's, so the seller is credited the full cash
        # here and `settle_delivery_fee` (next) takes the delivery charge
        # back as revenue + GST. Net: seller keeps exactly the item value
        # and can withdraw it. Sellers who collect their own cash (no rider
        # mapped) are untouched — nothing enters a wallet for them.
        if paid_via in ("cod", "wallet_cod") and fresh_for_fee.get("dp_id"):
            try:
                await shop_money.credit_vendor_cod_on_delivery(fresh_for_fee)
            except Exception as _cod_err:
                logger.warning(f"COD vendor credit failed for {order_id}: {str(_cod_err)[:200]}")
                await shop_money.record_financial_error(
                    "cod_vendor_credit_failed", str(_cod_err),
                    order_id=order_id, vendor_id=order.get("vendor_id"),
                )
        elif paid_via in ("cod", "wallet_cod"):
            # Oct-2026 — the SELLER delivered and took the cash himself. No
            # money moves (it is already in his pocket); we only write the
            # informational row so the ₹ is traceable in his Net Worth.
            try:
                await shop_money.record_vendor_cod_self_collected(fresh_for_fee)
            except Exception as _self_err:
                logger.warning(f"COD self-collect record failed for {order_id}: {str(_self_err)[:200]}")
        try:
            await shop_money.settle_delivery_fee(
                fresh_for_fee,
                credit_admin_bucket=credit_admin_bucket,
                admin_id=(admin_for_del or {}).get("id"),
            )
        except Exception as _df_err:
            logger.warning(f"delivery fee settlement failed for {order_id}: {str(_df_err)[:200]}")
            await shop_money.record_financial_error(
                "delivery_fee_settlement_failed", str(_df_err),
                order_id=order_id, vendor_id=order.get("vendor_id"),
            )
        # ── Rider's pay: % of the delivery charge, admin-configurable ────
        # Credited to his PERSONAL wallet (a liability), never to the COD
        # cash pot, so it is withdrawable and can never blur with our cash.
        if fresh_for_fee.get("dp_id"):
            try:
                _st = await get_settings()
                await shop_money.settle_dp_commission(
                    fresh_for_fee, float(_st.get("dp_commission_pct") or 0),
                )
            except Exception as _dpc_err:
                logger.warning(f"DP commission failed for {order_id}: {str(_dpc_err)[:200]}")
                await shop_money.record_financial_error(
                    "dp_commission_failed", str(_dpc_err), order_id=order_id,
                )
        # COD money never enters a wallet — the seller collected the cash in
        # person. We only stamp the order as paid/settled.
        if paid_via in ("cod", "wallet_cod") and not order.get("commission_settled"):
            await db.orders.update_one(
                {"id": order_id},
                {"$set": {"payment_status": "paid", "commission_settled": True,
                          "cod_collected": True, "cod_collected_at": now_utc().isoformat()}},
            )

    if payload.status == "cancelled" and prev_status != "cancelled":
        order_total = float(order.get("total") or 0)

        # ── Cashback claw-back (Jun-2026) ────────────────────────────────
        # Owner rule: cashback already credited is ALWAYS recovered. Runs
        # BEFORE the refund so whatever the wallet could not cover is
        # deducted from the money we hand back (UPI / cash entry), leaving
        # the ledger exact either way.
        cashback_netted_off_refund = 0.0
        try:
            from core.cashback import reverse_order_cashback
            _cb_rev = await reverse_order_cashback(
                order, f"Order {payload.status}",
                credit_admin_bucket=credit_admin_bucket,
                notify=_create_notification,
            )
            cashback_netted_off_refund = round(float(_cb_rev.get("netted_off_refund") or 0), 2)
        except Exception as _cb_err:
            logger.warning(f"cashback reversal failed for {order_id}: {str(_cb_err)[:300]}")

        # ── Refund the buyer ─────────────────────────────────────────────
        # Wallet-paid orders: credit the wallet back.
        # COD orders: no actual cash was held in wallet, so we DO NOT credit
        # the wallet — just mark the order cancelled.
        if paid_via == "wallet":
            refund_amt = round(max(0.0, order_total - cashback_netted_off_refund), 2)
            if refund_amt > 0:
                await db.users.update_one({"id": order["user_id"]}, {"$inc": {"wallet_balance": refund_amt}})
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": order["user_id"],
                "type": "refund",
                "amount": refund_amt,
                "status": "credited",
                "description": (
                    f"Order #{order_id[:8]} cancelled — refund"
                    + (f" (₹{cashback_netted_off_refund:g} cashback recovered)"
                       if cashback_netted_off_refund > 0.009 else "")
                ),
                "order_id": order_id,
                "gross_refund": order_total,
                "cashback_recovered": cashback_netted_off_refund,
                "created_at": now_utc().isoformat(),
            })
        elif paid_via in ("wallet_cod", "online", "wallet_online"):
            # Jun 2026 — refund exactly what was actually collected up-front:
            # the wallet slice plus any Razorpay-captured amount.  Online money
            # is returned as wallet credit (instant, no gateway round-trip).
            # The cash portion was never taken, so nothing to give back.
            gross_refund = round(
                float(order.get("wallet_paid") or 0) + float(order.get("online_paid") or 0), 2,
            )
            refund_amt = round(max(0.0, gross_refund - cashback_netted_off_refund), 2)
            if gross_refund > 0:
                if refund_amt > 0:
                    await db.users.update_one({"id": order["user_id"]}, {"$inc": {"wallet_balance": refund_amt}})
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": order["user_id"],
                    "type": "refund",
                    "amount": refund_amt,
                    "status": "credited",
                    "description": (
                        f"Order {order.get('order_number') or ('#' + order_id[:8])} cancelled — prepaid amount refunded to wallet"
                        + (f" (₹{cashback_netted_off_refund:g} cashback recovered)"
                           if cashback_netted_off_refund > 0.009 else "")
                    ),
                    "order_id": order_id,
                    "gross_refund": gross_refund,
                    "cashback_recovered": cashback_netted_off_refund,
                    "created_at": now_utc().isoformat(),
                })

        # ── Reverse exactly what was posted (Phase 1 engine) ─────────────
        # One call undoes the recorded vendor credit and, if it had already
        # been settled, the delivery fee (vendor refunded, treasury debited).
        # Amounts come from the LEDGER, so a reversal can never differ from
        # the original movement, and it is idempotent. There is no shop
        # commission in this flow, so there is none to reverse.
        try:
            fresh_cancel = await db.orders.find_one({"id": order_id}, {"_id": 0}) or order
            _adm_c = await db.users.find_one({"email": ADMIN_EMAIL.lower()}, {"_id": 0, "id": 1})
            await shop_money.reverse_order_money(
                fresh_cancel, f"order {payload.status}",
                credit_admin_bucket=credit_admin_bucket,
                admin_id=(_adm_c or {}).get("id"),
            )
        except Exception as _rev_err:
            logger.warning(f"order money reversal failed for {order_id}: {str(_rev_err)[:200]}")
            await shop_money.record_financial_error(
                "order_reversal_failed", str(_rev_err),
                order_id=order_id, vendor_id=order.get("vendor_id"),
            )

        await _create_notification(
            order["user_id"], "order", "Order cancelled",
            f"₹{int(order_total)} refunded to your wallet." if paid_via == "wallet" else "Your order was cancelled.",
        )
    elif payload.status != "cancelled" and payload.status != prev_status:
        # Only a REAL transition talks: re-saving the same status (a double tap
        # on the vendor's button, a rider retry) must not notify again.
        title, body = ORDER_STATUS_COPY.get(
            payload.status, (f"Order {payload.status}", f"Your order is now {payload.status}."),
        )
        # Jun-2026 — a recharge has no parcel: "Your parcel has been
        # delivered" was plainly wrong, and its own "Recharge successful"
        # notification (written in the delivered branch above) already tells
        # the buyer what happened. Only re-word the earlier stages.
        if order.get("is_recharge"):
            if payload.status == "delivered":
                title = body = ""
            else:
                title = "Recharge update"
                body = (
                    f"{order.get('recharge_account') or 'Your recharge'} — the seller is "
                    f"working on it."
                )
        if title:
            await _create_notification(order["user_id"], "order", title, body, push=False)
        # Sep 2026 — also push it to the phone, and tell the vendor.
        try:
            from routes.push import send_push
            targets = [order["user_id"]]
            if order.get("vendor_id"):
                await _create_notification(
                    order["vendor_id"], "vendor", title or "Recharge done",
                    (
                        f"{order.get('order_number') or order['id'][:8]} — recharge of "
                        f"{order.get('recharge_account') or 'the number'} is "
                        f"{'done' if payload.status == 'delivered' else 'in progress'}."
                    ) if order.get("is_recharge") else
                    f"{order.get('order_number') or order['id'][:8]} is now {payload.status.replace('_', ' ')}.",
                    extra={"order_id": order["id"], "action_url": "/vendor/orders"},
                    push=False,  # covered by the batched send_push below
                )
                targets.append(order["vendor_id"])
            if title:
                await send_push(
                    recipients=targets,
                    data={
                        "title": f"{'⚡' if order.get('is_recharge') else '📦'} {title}",
                        "message": f"{order.get('order_number') or ''} · {body}".strip(" ·"),
                        "action_url": f"/orders/{order['id']}",
                    },
                    idempotency_key=f"order-status-{order['id']}-{payload.status}",
                    category="orders",
                )
        except Exception as e:
            logging.warning(f"order status push failed (non-blocking): {e}")
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
                # Sept 2026 — mirror the credit sites: debit vendor_earnings,
                # not wallet_balance.
                await db.users.update_one({"id": vid}, {"$inc": {"vendor_earnings": -amt}})
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": vid,
                    "type": "vendor_sale_reversal",
                    "amount": -amt,
                    "status": "success",
                    "description": f"Legacy cleanup — reversal for cancelled order #{order_id[:8]}",
                    "order_id": order_id,
                    "created_at": now_utc().isoformat(),
                    "wallet_impact": "vendor_earnings_only",
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


# ============================================================
# Phase 3 — Anti-tampering / Integrity reporting
# ============================================================
# The frontend runs a battery of client-side integrity checks (root /
# jailbreak, emulator, dev-mode, SSL pin, Play Integrity attestation) and
# POSTs the verdict here on app boot + at key checkpoints. We:
#   1. Stamp the verdict onto users.integrity_status so financial guards
#      (withdrawals, payments) can read it.
#   2. Log the event to security_events for the admin investigation UI.
#   3. Return the BLOCK LEVEL — the FE uses this to decide whether to
#      render TamperBlockedScreen / disable financial buttons / show a
#      soft warning.
#
# Severity policy (Session A defaults — confirmed by user):
#   • root / jailbreak             → read_only      (block payouts/payments)
#   • Play Integrity FAIL_VERDICT  → hard_block     (Google's strongest signal)
#   • emulator                     → warn           (don't block our own QA)
#   • developer-mode               → warn
#   • SSL pin mismatch             → hard_block     (MITM defence — non-negotiable)
#
# Backwards compatibility: Expo Go cannot run native checks. Each check the
# FE sends carries `available: bool`. If `available=false` (unsupported build
# type), we record `unknown` and apply the SOFTEST policy (warn) for that
# check — never hard-block users on missing data.

class _IntegrityCheck(BaseModel):
    name: str
    passed: bool
    available: bool = True
    detail: Optional[str] = None


class _IntegrityReport(BaseModel):
    checks: List[_IntegrityCheck]
    play_integrity_token: Optional[str] = None
    build_type: Optional[str] = None  # "expo-go" | "dev-client" | "production"
    app_version: Optional[str] = None
    os: Optional[str] = None


# Per-check severity ladder. Higher = more severe.
_SEVERITY = {"warn": 1, "read_only": 2, "hard_block": 3}
_INV_SEVERITY = {v: k for k, v in _SEVERITY.items()}
_CHECK_POLICY = {
    "root_jailbreak":          "read_only",
    "play_integrity":          "hard_block",
    "emulator":                "warn",
    "developer_mode":          "warn",
    "ssl_pin":                 "hard_block",
    "apk_signature":           "hard_block",
}


def _evaluate_integrity(checks: List[_IntegrityCheck]) -> Dict[str, Any]:
    """Convert a list of FE checks into the strongest applicable block level
    + a human-readable reason list. `available=false` checks never escalate."""
    block_severity = 0  # severity 0 = "none"
    reasons: List[str] = []
    for c in checks:
        if not c.available:
            continue
        if c.passed:
            continue
        # Failed + available — apply the policy for this check name.
        policy = _CHECK_POLICY.get(c.name, "warn")
        sev = _SEVERITY.get(policy, 1)
        reasons.append(f"{c.name}:{policy}")
        if sev > block_severity:
            block_severity = sev
    block_level = _INV_SEVERITY.get(block_severity, "none") if block_severity > 0 else "none"
    return {"block_level": block_level, "reasons": reasons}


@api_router.post("/security/integrity-report")
@_rl.limit("30/minute")
async def integrity_report(
    request: Request,
    payload: _IntegrityReport,
    user: Dict[str, Any] = Depends(get_current_user),
):
    verdict = _evaluate_integrity(payload.checks)
    # Server-side Play Integrity verification. Enabled when:
    #   1. PLAY_INTEGRITY_ENABLED=1 in backend/.env
    #   2. google-auth + httpx are installed
    #   3. GOOGLE_APPLICATION_CREDENTIALS points to a valid service-account JSON
    # See backend/core/play_integrity.py for activation steps. Until enabled
    # this is a no-op — we still accept the FE's verdict (jail-monkey already
    # catches most tampering).
    if payload.play_integrity_token:
        try:
            from core.play_integrity import is_enabled as _pi_enabled, verify_integrity_token, evaluate_verdicts
            if _pi_enabled():
                decoded = await verify_integrity_token(payload.play_integrity_token)
                if decoded is not None:
                    pi_result = evaluate_verdicts(decoded)
                    if not pi_result["passed"]:
                        # Server overrides client claim — Play Integrity is the
                        # strongest signal we have. Promote to hard_block.
                        if "play_integrity:hard_block" not in verdict["reasons"]:
                            verdict["reasons"].append("play_integrity:hard_block")
                        verdict["reasons"].extend([f"play_integrity:{r}" for r in pi_result["reasons"]])
                        verdict["block_level"] = "hard_block"
        except Exception as _pi_err:
            logger.warning(f"play integrity verification failed: {_pi_err}")

    now_iso = now_utc().isoformat()
    # Stamp the user doc — financial endpoints will read this.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "integrity_status": {
                "block_level": verdict["block_level"],
                "reasons": verdict["reasons"],
                "last_check_at": now_iso,
                "build_type": payload.build_type,
                "app_version": payload.app_version,
                "os": payload.os,
            },
        }},
    )
    # Log to security_events for admin visibility — only when the verdict
    # is NOT "none". A clean device shouldn't spam the event stream.
    if verdict["block_level"] != "none":
        ip = (request.client.host if request.client else None)
        await _security_event(
            f"integrity.{verdict['block_level']}",
            user_id=user["id"],
            email=user.get("email"),
            ip=ip,
            details={
                "reasons": verdict["reasons"],
                "build_type": payload.build_type,
                "app_version": payload.app_version,
                "os": payload.os,
                "checks": [c.dict() for c in payload.checks],
            },
            severity="critical" if verdict["block_level"] == "hard_block" else "warning",
        )
    return {
        "ok": True,
        "block_level": verdict["block_level"],
        "reasons": verdict["reasons"],
    }


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
        writer.writerow(["" if r.get(f) is None else str(r.get(f)) for f in fields])
    return buf.getvalue()


@api_router.get("/admin/export/{kind}")
async def admin_export(
    kind: str,
    admin: Dict[str, Any] = Depends(require_admin),
    source: Optional[str] = None,
):
    if kind == "users":
        rows = await db.users.find(
            _users_source_query(source), {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0},
        ).sort("created_at", -1).to_list(20000)
        # Human-readable join source + approval columns (June-2026 request).
        SRC_LABEL = {
            "razorpay": "Razorpay gateway",
            "upi_manual": "UPI manual transfer",
            "offline_cash": "Offline / cash",
        }
        for r in rows:
            paid = bool(r.get("registration_paid"))
            src = r.get("registration_source")
            r["join_source"] = SRC_LABEL.get(src or "", "Unknown source") if paid else "No subscription"
            r["account_type"] = "Subscriber" if paid else "Non-subscriber"
            r["paid_status"] = "₹118 PAID" if paid else "Not paid"
            r["admin_approved"] = "ON" if r.get("referral_enabled") else "OFF"
            r["admin_approved_note"] = r.get("referral_switch_note") or ""
            r["admin_approved_on"] = r.get("referral_switch_at") or ""
            r["admin_approved_by"] = r.get("referral_switch_by") or ""
        fields = [
            "id", "name", "email", "phone", "role", "referral_code", "referred_by",
            "account_type", "paid_status", "join_source",
            "admin_approved", "admin_approved_note", "admin_approved_on", "admin_approved_by",
            "approval_status", "paid_at",
            "direct_referrals_count", "wallet_balance", "total_earned",
            "upi_id", "bank_account", "ifsc", "account_holder",
            "is_blocked", "kyc_status", "created_at",
        ]
    elif kind in ("registration-fees", "registration_fees"):
        # Full Registration-fee revenue list (all sources or one category).
        match: Dict[str, Any] = {
            "type": "registration_fee",
            "status": {"$nin": ["created", "failed"]},
        }
        pipeline: List[Dict[str, Any]] = [
            {"$match": match},
            {"$sort": {"created_at": -1}},
            {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "id", "as": "_u"}},
            {"$unwind": {"path": "$_u", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"_src": {"$ifNull": ["$_u.registration_source", {"$ifNull": ["$source", "unknown"]}]}}},
        ]
        if source and source not in ("all",):
            if source == "unknown":
                pipeline.append({"$match": {"_src": {"$nin": ["razorpay", "upi_manual", "offline_cash"]}}})
            else:
                pipeline.append({"$match": {"_src": source}})
        pipeline.append({"$limit": 20000})
        raw = await db.transactions.aggregate(pipeline, allowDiskUse=True).to_list(20000)
        SRC_LABEL = {
            "razorpay": "Razorpay gateway",
            "upi_manual": "UPI manual transfer",
            "offline_cash": "Offline / cash",
        }
        rows = []
        for t in raw:
            u = t.get("_u") or {}
            gross = float(t.get("amount") or 0)
            gst = round(gross * (REFERRAL_GST_PCT / (100.0 + REFERRAL_GST_PCT)), 2)
            rows.append({
                "reference": _short_txn_ref(t),
                "paid_on": t.get("paid_at") or t.get("created_at"),
                "name": u.get("name"),
                "member_id": u.get("referral_code"),
                "email": u.get("email"),
                "phone": u.get("phone"),
                "join_source": SRC_LABEL.get(t.get("_src") or "", "Unknown source"),
                "amount": f"{gross:.2f}",
                "gst_18_inclusive": f"{gst:.2f}",
                "net_excl_gst": f"{round(gross - gst, 2):.2f}",
                "status": t.get("status"),
                "razorpay_payment_id": t.get("razorpay_payment_id") or "",
                "razorpay_order_id": t.get("razorpay_order_id") or "",
                "utr_bank_ref": t.get("reference_number") or u.get("razorpay_utr") or "",
                "sponsor_code": u.get("referred_by") or "",
                "description": t.get("description") or "",
            })
        fields = [
            "reference", "paid_on", "name", "member_id", "email", "phone", "join_source",
            "amount", "gst_18_inclusive", "net_excl_gst", "status",
            "razorpay_payment_id", "razorpay_order_id", "utr_bank_ref", "sponsor_code", "description",
        ]
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
                {"$set": password_fields(ADMIN_PASSWORD)},
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
SYSTEM_WALLET_BUCKETS = (
    "referral_commission", "direct_signup", "fee_residual", "direct_added",
    "service_margin", "shopping_margin", "gst_collected", "platform_fee_collected",
    # ── Jun-2026 marketplace buckets ─────────────────────────────────────
    # `delivery_collected` — delivery charges the platform has collected.
    #   Its own accounting category so delivery money is never mixed with
    #   cashback, GST, vendor sales or subscription revenue.
    # `cashback_funded`    — cashback Slangcart fronted for a seller whose
    #   wallet was short. Runs NEGATIVE while the money is out and returns
    #   to zero as the seller settles their outstanding.
    "delivery_collected", "cashback_funded",
)


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
    # Sept 2026 (Slangcart · Bank tally = referral money only) — Owner
    # requested that shop/service cashflows STOP contributing to the
    # system-wallet Treasury.  Silently no-op every credit into these
    # buckets; the money is instead accounted for in the per-vendor
    # Sales dashboard (independent of the referral treasury).
    if bucket in ("shopping_margin", "service_margin"):
        logger.info("credit_admin_bucket: skipping %s +%s (owner-locked)", bucket, amount)
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

    SAFE-BY-DEFAULT (June 2026 update): demo seeding is now OFF by default.
    Production deployments must NOT carry seeded test users. Set the env
    var `SEED_DEMO_USERS=true` (in backend/.env) ONLY for dev/staging."""
    if os.environ.get("SEED_DEMO_USERS", "false").lower() not in ("1", "true", "yes", "on"):
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


@api_router.post("/admin/purge-demo-users")
async def admin_purge_demo_users(admin: Dict[str, Any] = Depends(require_admin_role("super_admin"))):
    """One-shot cleanup endpoint — deletes every user that was created by
    the seed_demo_users() helper (flagged via `demo_seed: True` in the
    user doc). Use this to scrub demo accounts out of the LIVE deployment
    that were created back when SEED_DEMO_USERS defaulted to True.

    Safe even if there are no demo users: returns count=0.
    """
    demo_users = await db.users.find({"demo_seed": True}, {"_id": 0, "id": 1, "email": 1}).to_list(100)
    if not demo_users:
        return {"ok": True, "removed": 0, "message": "No demo users found."}
    demo_ids = [u["id"] for u in demo_users]
    demo_emails = [u.get("email") for u in demo_users]
    # Cascade-delete user-owned rows so wallet/ledger stays clean
    await db.users.delete_many({"id": {"$in": demo_ids}})
    await db.wallet_transactions.delete_many({"user_id": {"$in": demo_ids}})
    await db.ledger_entries.delete_many({"user_id": {"$in": demo_ids}})
    await db.notifications.delete_many({"user_id": {"$in": demo_ids}})
    await _audit_log(admin, "demo_users.purge", "users", "bulk", {
        "count": len(demo_ids), "emails": demo_emails,
    })
    logger.info(f"Purged {len(demo_ids)} demo users: {demo_emails}")
    return {"ok": True, "removed": len(demo_ids), "emails": demo_emails}



# ------------------ Data Backup / Restore (admin) ------------------
BACKUP_INTERVAL_SECONDS = int(os.environ.get("BACKUP_INTERVAL_SECONDS", 15 * 60))  # 15 min default
BACKUP_RETENTION = int(os.environ.get("BACKUP_RETENTION", 24))  # keep last 24 snapshots
# Auto snapshots are full-database copies now — keep fewer of them.
BACKUP_AUTO_RETENTION = int(os.environ.get("BACKUP_AUTO_RETENTION", 6))


async def _snapshot_collections() -> List[str]:
    """Every collection worth snapshotting.

    Jun 2026 — this used to be a hardcoded list of 19 collections, so a
    snapshot silently missed chat, POS invoices, wallet ledgers, shop layout,
    services and more: restoring one looked like it worked but left half the
    app behind. It now mirrors the FILE backup (routes/backup.py) exactly, so
    both paths cover the same A-to-Z data.
    """
    from routes.backup import NEVER_EXPORT, REFERENCE_COLLECTIONS
    names = await db.list_collection_names()
    skip = set(NEVER_EXPORT) | set(REFERENCE_COLLECTIONS) | {"db_snapshots", "db_snapshot_chunks"}
    return sorted(n for n in names if n not in skip)


# One chunk document per slice of a collection. Mongo caps a document at
# 16 MB, and the old code stuffed the ENTIRE database into ONE document —
# which is why snapshots on a real catalogue (base64 product photos) failed
# and then silently degraded to "metadata-only", i.e. a useless backup.
_SNAPSHOT_CHUNK_ROWS = 200
_SNAPSHOT_CHUNK_BYTES = 6 * 1024 * 1024


async def _take_snapshot(kind: str = "auto", note: Optional[str] = None,
                         created_by: Optional[str] = None) -> Dict[str, Any]:
    """Capture every collection into `db_snapshot_chunks`, then index it with
    one small parent doc in `db_snapshots`.

    Chunking means a snapshot can never hit the 16 MB document limit again,
    no matter how many base64 images the catalogue carries.
    """
    snap_id = str(uuid.uuid4())
    counts: Dict[str, int] = {}
    skipped: List[str] = []
    chunk_total = 0

    for coll in await _snapshot_collections():
        try:
            rows: List[Dict[str, Any]] = []
            approx = 0
            n = 0
            seq = 0

            async def _flush(batch: List[Dict[str, Any]], seq_no: int) -> None:
                if not batch:
                    return
                await db.db_snapshot_chunks.insert_one({
                    "id": str(uuid.uuid4()),
                    "snapshot_id": snap_id,
                    "collection": coll,
                    "seq": seq_no,
                    "rows": batch,
                })

            async for doc in db[coll].find({}, {"_id": 0}):
                rows.append(doc)
                n += 1
                approx += len(str(doc))
                if len(rows) >= _SNAPSHOT_CHUNK_ROWS or approx >= _SNAPSHOT_CHUNK_BYTES:
                    await _flush(rows, seq)
                    chunk_total += 1
                    seq += 1
                    rows = []
                    approx = 0
            await _flush(rows, seq)
            if rows:
                chunk_total += 1
            counts[coll] = n
        except Exception as e:
            logging.warning(f"snapshot: skipping collection {coll}: {e}")
            skipped.append(coll)
            counts[coll] = 0

    doc = {
        "id": snap_id,
        "kind": kind,
        "note": note,
        "created_by": created_by,
        "created_at": now_utc().isoformat(),
        "counts": counts,
        "chunks": chunk_total,
        "storage": "chunked",
    }
    await db.db_snapshots.insert_one(doc.copy())

    # Retention (Jun 2026) — snapshots now cover the WHOLE database including
    # base64 product photos, so keeping 24 full copies could balloon storage.
    # Auto snapshots are pruned harder than the ones an admin (or a Danger
    # Zone action) deliberately took.
    for kinds, keep in (
        (["auto"], BACKUP_AUTO_RETENTION),
        (None, BACKUP_RETENTION),
    ):
        q = {"kind": {"$in": kinds}} if kinds else {}
        extras = await db.db_snapshots.find(
            q, {"_id": 0, "id": 1, "created_at": 1}
        ).sort("created_at", -1).skip(keep).to_list(1000)
        if extras:
            stale = [e["id"] for e in extras]
            await db.db_snapshots.delete_many({"id": {"$in": stale}})
            await db.db_snapshot_chunks.delete_many({"snapshot_id": {"$in": stale}})
    doc.pop("_id", None)
    return {"id": snap_id, "counts": counts, "created_at": doc["created_at"], "skipped": skipped}


async def _restore_snapshot(snap_id: str) -> Dict[str, Any]:
    """Put the database back exactly as the snapshot captured it.

    Reads the chunked format written above, and still understands the legacy
    single-document `data` field so older snapshots stay restorable.
    """
    snap = await db.db_snapshots.find_one({"id": snap_id})
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    legacy_data = snap.get("data") or {}
    restored: Dict[str, int] = {}
    collections = [c for c, n in (snap.get("counts") or {}).items()] or list(legacy_data.keys())

    for coll in collections:
        if coll in ("db_snapshots", "db_snapshot_chunks"):
            continue
        rows: List[Dict[str, Any]] = list(legacy_data.get(coll) or [])
        if not rows:
            async for ch in db.db_snapshot_chunks.find(
                {"snapshot_id": snap_id, "collection": coll}, {"_id": 0, "rows": 1, "seq": 1},
            ).sort("seq", 1):
                rows.extend(ch.get("rows") or [])
        # A collection captured as EMPTY must end up empty — that's what the
        # snapshot recorded.
        await db[coll].delete_many({})
        if rows:
            cleaned = [{k: v for k, v in r.items() if k != "_id"} for r in rows]
            for i in range(0, len(cleaned), 500):
                await db[coll].insert_many(cleaned[i:i + 500])
        restored[coll] = len(rows)

    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
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
    _ = settings  # get_settings() is called for its DB-init side effect; the
    #             registration_fee value is derived downstream from actual
    #             transaction rows (not user count × fee) — see _sum() below.

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
        # `legacy_reconcile_inflow` — audit-only txns inserted by the
        # startup drift self-healer when it detects phantom money already
        # sitting in user wallets (legacy data). They balance the books
        # without crediting any wallet. NOT included in _BUCKET_TXN_TYPES,
        # so admin bucket reconciliation ignores them.
        + await _sum({"type": "legacy_reconcile_inflow", "status": "success"})
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
        "auto_retention": BACKUP_AUTO_RETENTION,
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
    # Chunked snapshots keep their payload in a side collection.
    await db.db_snapshot_chunks.delete_many({"snapshot_id": snap_id})
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
    # ---------- Critical unique-constraint indexes only (fast — kept sync) ----------
    # Only the indexes that PREVENT corrupt writes (unique constraints) run
    # synchronously. Everything else — perf indexes, partial unique indexes,
    # backfills — runs in the background so uvicorn binds to 0.0.0.0:8001
    # within < 1 second and the Kubernetes startup probe passes immediately.
    try:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("referral_code", unique=True)
        # Phase 1 — idempotency for every money movement is enforced by the
        # DATABASE, so a replayed webhook / double tap cannot move money twice.
        await shop_money.ensure_indexes()
        await bank.ensure_indexes()
        # Phase 2 — returns / inventory-restoration lookups + guards.
        from core import returns as _returns_core
        await _returns_core.ensure_indexes()
        # Push diagnostics (Sep 2026): the send log is evidence, not data —
        # keep 30 days of it and index the lookups the admin screen uses.
        try:
            await db.push_log.create_index("created_at")
            await db.push_log.create_index("recipients")
            await db.push_log.create_index("stage")
            await db.push_devices.create_index([("user_id", 1), ("token_fingerprint", 1)])
            await db.push_devices.create_index("last_seen_at")
        except Exception as _pl_err:
            logger.warning(f"push diagnostics index setup: {str(_pl_err)[:160]}")
    except Exception as _idx_err:
        logger.warning(f"User-unique-index setup failed (non-fatal): {_idx_err}")

    # === DEPLOYMENT-CRITICAL: ALL the heavier work below (the rest of the
    # indexes, admin-prefix backfill, duplicate reg-fee cleanup, phantom-amount
    # cleanup, pincode CSV seed, hot-query indexes, etc.) runs in the
    # BACKGROUND so uvicorn binds to 0.0.0.0:8001 immediately and passes the
    # Kubernetes startup probe. All operations below are idempotent. ===
    asyncio.create_task(_background_init())
    # Kick off the periodic backup task (also background, also fast)
    asyncio.create_task(_backup_scheduler())
    # Money-flow drift auto-check (every 5 min)
    asyncio.create_task(_money_flow_checker())


async def _background_init():
    """Long-running startup work that MUST NOT block uvicorn's port-binding.

    Runs once, asynchronously, AFTER the FastAPI app has started serving
    requests. If anything in here is slow (pincode CSV parsing, large
    update_many backfills, idx builds on Atlas, etc), the live app continues
    to serve traffic while this task chugs away in the background.

    Wrapped in a broad try/except so a single failed step never kills the
    whole init sequence — each step has its own try/except inside.
    """
    try:
        # ---- Non-critical user index (sponsor lookups) ----
        try:
            await db.users.create_index("sponsor_id")
        except Exception as _idx_err:
            logger.warning(f"sponsor_id index setup failed: {_idx_err}")
        # ---- Idempotency safety-net partial-unique indexes ----
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
            await db.system_wallet_deposits.create_index(
                "utr", unique=True, name="uniq_deposit_utr",
            )
        except Exception as _idx_err:
            logger.warning(f"Transaction unique-index setup failed: {_idx_err}")
        # ---- Hot-query (perf-only) indexes ----
        try:
            await db.transactions.create_index(
                [("user_id", 1), ("created_at", -1)], name="ix_txn_user_created",
            )
            await db.transactions.create_index([("type", 1)], name="ix_txn_type")
            await db.transactions.create_index([("created_at", -1)], name="ix_txn_created")
            await db.withdrawals.create_index(
                [("user_id", 1), ("created_at", -1)], name="ix_wd_user_created",
            )
            await db.withdrawals.create_index(
                [("status", 1), ("created_at", -1)], name="ix_wd_status_created",
            )
            await db.notifications.create_index(
                [("user_id", 1), ("read", 1)], name="ix_notif_user_read",
            )
            await db.notifications.create_index(
                [("user_id", 1), ("created_at", -1)], name="ix_notif_user_created",
            )
            await db.orders.create_index(
                [("user_id", 1), ("created_at", -1)], name="ix_order_user_created",
            )
            await db.orders.create_index(
                [("status", 1), ("created_at", -1)], name="ix_order_status_created",
            )
            await db.manual_payments.create_index(
                [("status", 1), ("created_at", -1)], name="ix_mpay_status_created",
            )
            await db.manual_payments.create_index([("user_id", 1)], name="ix_mpay_user")
            await db.audit_logs.create_index([("created_at", -1)], name="ix_audit_created")
            await db.audit_logs.create_index([("admin_id", 1)], name="ix_audit_admin")
            await db.security_events.create_index([("created_at", -1)], name="ix_sec_created")
            await db.login_history.create_index(
                [("user_id", 1), ("created_at", -1)], name="ix_loginhist_user_created",
            )
            await db.security_events.create_index(
                [("email", 1), ("created_at", -1)], name="ix_sec_email_created",
            )
            await db.security_events.create_index(
                [("ip", 1), ("created_at", -1)], name="ix_sec_ip_created",
            )
            await db.cart.create_index([("user_id", 1)], name="ix_cart_user")
            await db.products.create_index([("category", 1)], name="ix_prod_cat")
            # Nov 2026 — Hot-path indexes for the strict pincode filter
            # and delivery-zone check.  Avoids collection scans on
            # /products?pincode= for stores with lots of vendors.
            await db.products.create_index([("store_pincode", 1)], name="ix_prod_store_pin")
            await db.products.create_index([("delivery_pincodes", 1)], name="ix_prod_del_pins")
            await db.products.create_index([("vendor_id", 1)], name="ix_prod_vendor")
            await db.vendor_edit_requests.create_index([("user_id", 1), ("status", 1)], name="ix_ver_user_status")
            await db.vendor_edit_requests.create_index([("status", 1), ("created_at", -1)], name="ix_ver_status_created")
            await db.shop_layout_blocks.create_index([("scope", 1), ("active", 1)], name="ix_sl_scope_active")
            await db.shop_layout_blocks.create_index([("scope_pincode", 1)], name="ix_sl_scope_pin")
            await db.system_wallet_deposits.create_index([("bucket", 1)], name="ix_swd_bucket")
            await db.products.create_index([("is_in_stock", 1)], name="ix_prod_stock")
        except Exception as _idx_err:
            logger.warning(f"Hot-query index setup failed (non-fatal): {_idx_err}")

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
                # Idempotency: include prior legacy_reconcile_inflow audit
                # txns so subsequent restarts see drift=0 and skip step 2.
                + await _sum_tx({"type": "legacy_reconcile_inflow", "status": "success"})
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
                        # Held > expected after bucket reset → phantom money
                        # is sitting in USER wallets (legacy data from older
                        # buggy code paths that credited users without an
                        # admin-side inflow txn). We can't safely debit user
                        # wallets retroactively, so instead we RECOGNIZE the
                        # historical inflow on paper: insert an audit-only
                        # `legacy_reconcile_inflow` txn for the admin.
                        #
                        # This txn:
                        #   • is summed into the inflow tally (above and in
                        #     _compute_money_flow_snapshot), so inflow
                        #     increases by ₹amount → expected_held catches
                        #     up to actual_held → drift falls to ₹0.
                        #   • is NOT mapped to any bucket in _BUCKET_TXN_TYPES,
                        #     so the per-restart bucket reset does NOT credit
                        #     admin's wallet_balance — keeping books honest.
                        #   • is_auto_heal=True + legacy_reconcile=True so
                        #     finance can audit/trace these adjustments.
                        amount = round(drift2, 2)
                        await db.transactions.insert_one({
                            "id": str(uuid.uuid4()),
                            "user_id": admin_doc2["id"],
                            "type": "legacy_reconcile_inflow",
                            "amount": amount,
                            "status": "success",
                            "description": (
                                f"[Auto-heal] Legacy phantom user-wallet inflow recognised ₹{amount} "
                                f"(drift was ₹{drift2}). Audit-only — no wallet credited. "
                                f"Books re-balanced to clear recurring [LEDGER ALERT]."
                            ),
                            "is_auto_heal": True,
                            "legacy_reconcile": True,
                            "created_at": now_utc().isoformat(),
                        })
                        logger.info(
                            f"Drift self-heal step 2 (phantom inflow recognition): recorded ₹{amount} "
                            f"legacy_reconcile_inflow audit txn (drift was ₹{drift2}) — user wallets untouched."
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
        # ── Aug-2026 · Two-account-type migration (one-time) ─────────────
        # Business rule change: only a successful RAZORPAY payment makes a
        # member a Subscriber. Legacy UPI-manual / offline-cash joinings are
        # converted to Non-subscribers (their historical revenue rows are
        # KEPT so the books and GST reports stay truthful). Also seeds the
        # new `referral_enabled` switch from the existing approval state so
        # nothing changes for members who are already earning.
        try:
            _mig_key = "two_account_types_migration_2026_08"
            _mig = await db.app_state.find_one({"_id": _mig_key})
            if not _mig:
                _ts = now_utc().isoformat()
                legacy = await db.users.update_many(
                    {
                        "role": "user",
                        "registration_paid": True,
                        "registration_source": {"$in": ["upi_manual", "offline_cash"]},
                    },
                    {"$set": {
                        "registration_paid": False,
                        "subscription_skipped": True,
                        "legacy_non_subscriber": True,
                        "converted_to_non_subscriber_at": _ts,
                    }},
                )
                on_res = await db.users.update_many(
                    {"role": "user", "referral_enabled": {"$exists": False},
                     "approval_status": "approved", "registration_source": "razorpay"},
                    {"$set": {"referral_enabled": True,
                              "referral_switch_note": "Seeded ON from existing approval",
                              "referral_switch_at": _ts}},
                )
                off_res = await db.users.update_many(
                    {"role": "user", "referral_enabled": {"$exists": False}},
                    {"$set": {"referral_enabled": False}},
                )
                await db.app_state.insert_one({
                    "_id": _mig_key, "at": _ts,
                    "legacy_converted": legacy.modified_count,
                    "referral_on": on_res.modified_count,
                    "referral_off": off_res.modified_count,
                })
                logger.info(
                    f"two-account-type migration: {legacy.modified_count} legacy → non-subscriber, "
                    f"referral switch seeded ON={on_res.modified_count} OFF={off_res.modified_count}"
                )
        except Exception as _mig_err:
            logger.warning(f"two-account-type migration skipped: {str(_mig_err)[:200]}")
        # ── Jun-2026 · MLM cutover (one-time) ────────────────────────────
        # Stops referral income for good and reclaims the referral money
        # still sitting in member wallets, with a balancing platform entry.
        try:
            from core.mlm_cutover import run_mlm_cutover
            await run_mlm_cutover(ADMIN_EMAIL, credit_admin_bucket)
        except Exception as _cut_err:
            logger.warning(f"MLM cutover skipped: {str(_cut_err)[:300]}")
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

        # ── Backfill registration_source on legacy users + transactions ──
        # Phase: User-source unification (2026-05-27). Existing users were
        # created before this field existed — infer their source from the
        # already-stored payment_method so the breakdown card is accurate
        # from day one. Idempotent: only touches docs where
        # registration_source is missing/null.
        try:
            now_iso = now_utc().isoformat()
            for pm_pattern, src in [
                ("razorpay", "razorpay"),
                ("upi_manual", "upi_manual"),
                ("admin_offline", "offline_cash"),
            ]:
                # users
                u_res = await db.users.update_many(
                    {
                        "registration_paid": True,
                        "payment_method": {"$regex": f"^{pm_pattern}"},
                        "$or": [
                            {"registration_source": {"$exists": False}},
                            {"registration_source": None},
                        ],
                    },
                    {"$set": {"registration_source": src, "_source_backfilled_at": now_iso}},
                )
                if u_res.modified_count:
                    logger.info(f"backfill registration_source={src}: stamped {u_res.modified_count} users")
            # Any remaining paid user without a payment_method (e.g. seeded
            # demo accounts) gets tagged "offline_cash" so the breakdown
            # totals don't show "unknown".
            unk_res = await db.users.update_many(
                {
                    "registration_paid": True,
                    "$or": [
                        {"registration_source": {"$exists": False}},
                        {"registration_source": None},
                    ],
                },
                {"$set": {"registration_source": "offline_cash", "_source_backfilled_at": now_iso}},
            )
            if unk_res.modified_count:
                logger.info(f"backfill registration_source=offline_cash (fallback): stamped {unk_res.modified_count} users")
        except Exception as _e:
            logger.warning(f"registration_source backfill failed: {str(_e)[:200]}")

        # ─── Backfill availability_status for legacy service providers (June-2026) ───
        # Approved providers from before the availability feature was added won't
        # have `availability_status` set, so the Service Analytics dashboard
        # shows them as "unset". Default them to "available" so the live
        # buckets (Available/Busy/Offline) tally correctly and providers
        # show up in customer searches. Idempotent: only touches docs missing
        # the field.
        try:
            now_iso2 = now_utc().isoformat()
            avail_bf = await db.users.update_many(
                {
                    "is_service_provider": True,
                    "$or": [
                        {"availability_status": {"$exists": False}},
                        {"availability_status": None},
                        {"availability_status": ""},
                    ],
                },
                {"$set": {
                    "availability_status": "available",
                    "availability_updated_at": now_iso2,
                }},
            )
            if avail_bf.modified_count:
                logger.info(f"backfill availability_status=available: stamped {avail_bf.modified_count} providers")
        except Exception as _e:
            logger.warning(f"availability_status backfill failed: {str(_e)[:200]}")

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
    # Dec 2026 — Extract lat/lng scalars from the GeoJSON `location` payload
    # so the products_public / eligibility checks can read them directly.
    # Without this, radius-mode delivery never matched (the filter reads
    # top-level lat/lng, not location.coordinates).
    loc_lat: Optional[float] = None
    loc_lng: Optional[float] = None
    if isinstance(payload.location, dict):
        coords = payload.location.get("coordinates") or []
        if isinstance(coords, list) and len(coords) >= 2:
            try:
                loc_lng = float(coords[0]); loc_lat = float(coords[1])
            except Exception:
                loc_lat = loc_lng = None
    # Normalize delivery_pincodes into stripped strings.
    pins_in = payload.delivery_pincodes or []
    if not isinstance(pins_in, list):
        pins_in = []
    delivery_pincodes_clean = [str(p).strip() for p in pins_in if str(p).strip()]

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
        # Nov 2026 — persist location / delivery details on the application row
        # so the admin can see what was submitted for approval.
        "location": payload.location,
        "lat": loc_lat,
        "lng": loc_lng,
        "pincode": (payload.pincode or "").strip() or None,
        "state": (payload.state or "").strip() or None,
        "district": (payload.district or "").strip() or None,
        "city": (payload.city or "").strip() or None,
        "store_address": (payload.store_address or "").strip() or None,
        "delivery_radius_km": payload.delivery_radius_km,
        "delivery_radius_mode": payload.delivery_radius_mode,
        "delivery_pincodes": delivery_pincodes_clean,
        "delivery_available": payload.delivery_available if payload.delivery_available is not None else True,
        # Sept 2026 — Persist the consent audit block for legal review.
        "accepted_terms": (payload.accepted_terms.model_dump() if payload.accepted_terms else None),
        "status": "pending",
        "created_at": ts,
        "updated_at": ts,
    }
    await db.vendor_applications.insert_one(doc)
    # Mark user with vendor_status pending + snapshot the shop location so we
    # can fall back on it before admin approval too.
    user_update: Dict[str, Any] = {
        "vendor_status": "pending",
        "shop_name": shop,
    }
    if payload.pincode:
        user_update["pincode"] = payload.pincode
        # Denormalise as store_pincode so the eligibility check (which reads
        # pincode OR store_pincode) sees it consistently.
        user_update["store_pincode"] = payload.pincode
    if payload.state: user_update["state"] = payload.state
    if payload.district: user_update["district"] = payload.district
    if payload.city: user_update["city"] = payload.city
    if payload.store_address: user_update["store_address"] = payload.store_address
    if payload.location: user_update["location"] = payload.location
    if loc_lat is not None: user_update["lat"] = loc_lat
    if loc_lng is not None: user_update["lng"] = loc_lng
    if payload.delivery_radius_km is not None: user_update["delivery_radius_km"] = payload.delivery_radius_km
    if payload.delivery_radius_mode: user_update["delivery_radius_mode"] = payload.delivery_radius_mode
    if delivery_pincodes_clean: user_update["delivery_pincodes"] = delivery_pincodes_clean
    if payload.delivery_available is not None: user_update["delivery_available"] = payload.delivery_available
    await db.users.update_one({"id": user["id"]}, {"$set": user_update})
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
    """Jul 2026 rewrite — Vendor Dashboard KPI numbers now report the
    GROSS customer-paid amount for BOTH channels (online + POS), no
    margin or commission deduction.  Also returns per-channel breakdowns
    so the dashboard drill-down can filter cleanly.
    """
    today_iso = now_utc().date().isoformat()

    # ── Online sales (vendor_sales collection — one row per line item) ─
    online_rows = await db.vendor_sales.find({"vendor_id": vendor["id"]}, {"_id": 0}).to_list(20000)

    # Jun 2026 — EXCLUDE cancelled / refunded orders from the sales math.
    # `vendor_sales` rows are kept for audit even after a cancellation, so
    # counting them made Today/Lifetime earnings overstate reality.
    order_ids = list({s.get("order_id") for s in online_rows if s.get("order_id")})
    dead_order_ids: set = set()
    if order_ids:
        dead_rows = await db.orders.find(
            {"id": {"$in": order_ids}, "status": {"$in": ["cancelled", "refunded", "returned"]}},
            {"_id": 0, "id": 1},
        ).to_list(len(order_ids))
        dead_order_ids = {r["id"] for r in dead_rows}
    online_rows = [s for s in online_rows if s.get("order_id") not in dead_order_ids]

    online_total = sum(float(s.get("line_total") or 0) for s in online_rows)
    online_today = sum(
        float(s.get("line_total") or 0)
        for s in online_rows if (s.get("created_at") or "").startswith(today_iso)
    )
    online_orders_all = len({s.get("order_id") for s in online_rows if s.get("order_id")})
    online_orders_today = len({
        s.get("order_id") for s in online_rows
        if s.get("order_id") and (s.get("created_at") or "").startswith(today_iso)
    })

    # ── Store Sale / Cloud POS (db.offline_sales — one row per invoice) ─
    # Jun 2026 BUGFIX: this used to read `db.vendor_pos_sales`, a
    # collection the POS module never writes to, so "NEW SALES · POS"
    # always rendered ₹0 / 0 invoices. The POS writes completed invoices
    # to `offline_sales` with the money under `totals.grand_total`.
    pos_rows = await db.offline_sales.find(
        {"vendor_id": vendor["id"], "status": "completed"},
        {"_id": 0, "created_at": 1, "totals": 1},
    ).to_list(20000)

    def _pos_amount(s: Dict[str, Any]) -> float:
        return float((s.get("totals") or {}).get("grand_total") or 0)

    pos_total = sum(_pos_amount(s) for s in pos_rows)
    pos_today = sum(
        _pos_amount(s)
        for s in pos_rows if (s.get("created_at") or "").startswith(today_iso)
    )
    pos_orders_all = len(pos_rows)
    pos_orders_today = len([s for s in pos_rows if (s.get("created_at") or "").startswith(today_iso)])

    # ── Cash-to-collect summary (Jun 2026) ────────────────────────────
    # Wallet+COD and pure-COD orders carry a `cod_due` balance the rider
    # must collect. Vendors asked for a daily figure so the shop's cash
    # drawer can be reconciled at closing time.
    cod_rows = await db.orders.find(
        {"vendor_id": vendor["id"], "cod_due": {"$gt": 0}},
        {"_id": 0, "cod_due": 1, "status": 1, "created_at": 1, "delivered_at": 1},
    ).to_list(20000)
    cod_pending_total = sum(
        float(o.get("cod_due") or 0) for o in cod_rows
        if (o.get("status") or "") in COD_PENDING_STATUSES
    )
    cod_pending_count = len([o for o in cod_rows if (o.get("status") or "") in COD_PENDING_STATUSES])
    cod_collected_today = sum(
        float(o.get("cod_due") or 0) for o in cod_rows
        if (o.get("status") or "") == "delivered"
        and str(o.get("delivered_at") or o.get("created_at") or "").startswith(today_iso)
    )
    cod_collected_today_count = len([
        o for o in cod_rows
        if (o.get("status") or "") == "delivered"
        and str(o.get("delivered_at") or o.get("created_at") or "").startswith(today_iso)
    ])

    products_count = await db.products.count_documents({"vendor_id": vendor["id"]})
    published_count = await db.products.count_documents({"vendor_id": vendor["id"], "is_published": True})

    return {
        # Gross customer-paid amounts (no margin / commission deduction).
        "total_sales": round(online_total + pos_total, 2),
        "total_earnings": round(online_total + pos_total, 2),  # alias for legacy FE
        "today_earnings": round(online_today + pos_today, 2),
        "today_orders": online_orders_today + pos_orders_today,
        "all_orders": online_orders_all + pos_orders_all,
        # Per-channel breakdown for the dashboard drill-down.
        "online_total": round(online_total, 2),
        "online_today": round(online_today, 2),
        "online_orders_all": online_orders_all,
        "online_orders_today": online_orders_today,
        "pos_total": round(pos_total, 2),
        "pos_today": round(pos_today, 2),
        "pos_orders_all": pos_orders_all,
        "pos_orders_today": pos_orders_today,
        "products_count": products_count,
        "published_count": published_count,
        # Sep-2026 — "WALLET" on the vendor dashboard means the SHOP wallet
        # (`vendor_earnings`), which is what sales credit and what a
        # settlement withdraws. It used to report the personal/referral
        # wallet, so sales money looked like it had vanished.
        "wallet_balance": round(float(vendor.get(shop_money.VENDOR_WALLET) or 0), 2),
        "shop_wallet_balance": round(float(vendor.get(shop_money.VENDOR_WALLET) or 0), 2),
        "personal_wallet_balance": round(float(vendor.get("wallet_balance") or 0), 2),
        # Jun 2026 — Cash-to-collect summary so vendors can tally their
        # drawer at closing time. `cod_pending_*` is money still out with
        # riders (placed/shipped), `cod_collected_today` is cash actually
        # taken in today (orders delivered today with a cash balance).
        "cod_pending_total": round(cod_pending_total, 2),
        "cod_pending_count": cod_pending_count,
        "cod_collected_today": round(cod_collected_today, 2),
        "cod_collected_today_count": cod_collected_today_count,
    }


@api_router.get("/vendor/me/earnings")
async def vendor_my_earnings(
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    to_date: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    month: Optional[str] = Query(None, description="YYYY-MM shortcut for from/to a whole month"),
    channel: Optional[str] = Query(None, description="'online' | 'pos' | None=both"),
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    """Jul 2026 — Earnings drill-down endpoint used by the Vendor
    Dashboard's tap-to-open detail sheet.  Returns raw sale rows
    (both online and POS unless `channel` is set) with per-row totals
    and product summaries, filtered by date/month.
    """
    # Normalise date range
    if month:
        try:
            y, m = month.split("-")
            y_i, m_i = int(y), int(m)
        except Exception:
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        from_date = f"{y_i:04d}-{m_i:02d}-01"
        # naive next-month calc
        if m_i == 12:
            to_date = f"{y_i + 1:04d}-01-01"
        else:
            to_date = f"{y_i:04d}-{m_i + 1:02d}-01"

    def _in_range(s: str) -> bool:
        if not s:
            return False
        if from_date and s < from_date:
            return False
        if to_date and s >= to_date:
            return False
        return True

    online_out: List[Dict[str, Any]] = []
    pos_out: List[Dict[str, Any]] = []

    if channel in (None, "", "online", "both"):
        rows = await db.vendor_sales.find({"vendor_id": vendor["id"]}, {"_id": 0}).sort("created_at", -1).to_list(20000)
        # Jun 2026 — drop rows belonging to cancelled / refunded orders.
        oids = list({s.get("order_id") for s in rows if s.get("order_id")})
        dead: set = set()
        if oids:
            dead_rows = await db.orders.find(
                {"id": {"$in": oids}, "status": {"$in": ["cancelled", "refunded", "returned"]}},
                {"_id": 0, "id": 1},
            ).to_list(len(oids))
            dead = {r["id"] for r in dead_rows}
        for s in rows:
            if s.get("order_id") in dead:
                continue
            if from_date or to_date:
                if not _in_range((s.get("created_at") or "")[:10]):
                    continue
            online_out.append({
                "channel": "online",
                "id": s.get("id"),
                "order_id": s.get("order_id"),
                "order_number": s.get("order_number"),
                "created_at": s.get("created_at"),
                "product_name": s.get("product_name") or "Product",
                "qty": int(s.get("qty") or 1) or 1,
                "line_total": round(float(s.get("line_total") or 0), 2),
                "buyer_email": s.get("buyer_email"),
            })

    if channel in (None, "", "pos", "both"):
        # Jun 2026 BUGFIX — Store Sale rows live in `offline_sales`.
        rows = await db.offline_sales.find(
            {"vendor_id": vendor["id"], "status": "completed"},
            {"_id": 0},
        ).sort("created_at", -1).to_list(20000)
        for s in rows:
            if from_date or to_date:
                if not _in_range((s.get("created_at") or "")[:10]):
                    continue
            items = s.get("items") or []
            summary = ", ".join(
                f"{(it.get('name') or 'Item')} × {int(it.get('qty') or 1)}"
                for it in items[:3]
            ) or "Store Sale"
            if len(items) > 3:
                summary += f" +{len(items) - 3} more"
            pos_out.append({
                "channel": "pos",
                "id": s.get("id"),
                "invoice_no": s.get("invoice_no") or s.get("invoice_number"),
                "created_at": s.get("created_at"),
                "product_name": summary,
                "qty": sum(int(it.get("qty") or 1) for it in items),
                "line_total": round(float((s.get("totals") or {}).get("grand_total") or 0), 2),
                "customer_name": (s.get("customer") or {}).get("name") or "Walk-in",
            })

    merged = sorted(online_out + pos_out, key=lambda x: x.get("created_at") or "", reverse=True)
    return {
        "items": merged,
        "total": len(merged),
        "sum_amount": round(sum(r["line_total"] for r in merged), 2),
        "online_count": len(online_out),
        "pos_count": len(pos_out),
        "online_sum": round(sum(r["line_total"] for r in online_out), 2),
        "pos_sum": round(sum(r["line_total"] for r in pos_out), 2),
    }


@api_router.get("/vendor/me/products")
async def vendor_my_products(vendor: Dict[str, Any] = Depends(require_vendor)):
    """Jun 2026 — SLIM list.

    This used to return every product document in full, including the
    base64 `image_url` AND the whole `images[]` gallery. A vendor with 150
    SKUs was therefore downloading 20-40 MB on every dashboard open, which
    is exactly the "vendor panel loading very slow / Cloudflare could not
    parse the response" report: the edge times out or truncates the body.

    We now drop `images` entirely and swap inline base64 covers for the
    on-demand thumbnail endpoint. The editor pulls the full document from
    GET /vendor/me/products/{id} when it opens a product.
    """
    items = await db.products.aggregate([
        {"$match": {"vendor_id": vendor["id"]}},
        {"$sort": {"created_at": -1}},
        {"$limit": 1000},
        {"$addFields": {"_gallery_n": {"$size": {"$ifNull": ["$images", []]}}}},
        {"$project": {"_id": 0, "images": 0, "image_data_url": 0}},
    ]).to_list(1000)
    for p in items:
        img = p.get("image_url") or ""
        gallery_n = int(p.pop("_gallery_n", 0) or 0)
        p["gallery_count"] = gallery_n
        if (isinstance(img, str) and img.startswith("data:")) or (not img and gallery_n > 0):
            p["image_url"] = f"/api/products/{p.get('id')}/image?w=240&q=70"
            p["has_inline_image"] = True
    return items


@api_router.get("/vendor/me/products/{product_id}")
async def vendor_my_product_detail(product_id: str, vendor: Dict[str, Any] = Depends(require_vendor)):
    """Full document for ONE of the vendor's own products (cover + gallery).

    Companion to the slim list above — the product editor calls this so it
    still has the real base64 images to show and re-save.
    """
    doc = await db.products.find_one({"id": product_id, "vendor_id": vendor["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc


@api_router.post("/vendor/me/products")
async def vendor_create_product(p: ProductCreate, vendor: Dict[str, Any] = Depends(require_vendor)):
    if (p.price or 0) <= 0:
        raise HTTPException(status_code=400, detail="Price must be > 0")
    if not (p.name or "").strip():
        raise HTTPException(status_code=400, detail="Name is required")
    from core.image_compress import compress_product_payload
    from core.variants import apply_variants_to_payload
    payload = compress_product_payload(p.dict())
    # Jun 2026 — variants own the stock/price. `apply_variants_to_payload`
    # rewrites `stock` (sum of options) and `price` (cheapest buyable
    # option) so every existing badge / filter / POS screen keeps working.
    payload = apply_variants_to_payload(payload, float(payload.get("price") or 0))
    from core.taxonomy import normalize_product_taxonomy
    payload = await normalize_product_taxonomy(payload)
    doc = {
        "id": str(uuid.uuid4()),
        **{k: v for k, v in payload.items() if k != "vendor_id"},
        "vendor_id": vendor["id"],          # force-stamp
        "vendor_email": vendor.get("email"),
        # ── Nov 2026 — Denormalise shop location onto the product so
        # the customer-facing pincode / delivery-zone filter can query
        # `products` directly (avoids a per-product join to `users`). ──
        "store_pincode": vendor.get("pincode") or None,
        "store_location": vendor.get("location") or None,
        "store_city": vendor.get("city") or None,
        "store_state": vendor.get("state") or None,
        "store_district": vendor.get("district") or None,
        "delivery_radius_km": vendor.get("delivery_radius_km"),
        "delivery_radius_mode": vendor.get("delivery_radius_mode") or "pincode",
        "delivery_available": vendor.get("delivery_available", True),
        "delivery_pincodes": vendor.get("delivery_pincodes") or [],
        "created_at": now_utc().isoformat(),
        # UPDATE 1 (June 2026) — Publish is admin-only. Vendors create their
        # products in a HIDDEN state; only an admin can flip is_published=True
        # via /api/admin/products/{id}. This prevents self-listing abuse and
        # keeps the public shop moderated.
        "is_published": False,
    }
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    # Dec 2026 — Bust caches so admin listing (auto-poll every 15s) sees
    # the new product on its next tick.
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
    return doc


@api_router.patch("/vendor/me/products/{product_id}")
async def vendor_update_product(product_id: str, payload: ProductUpdate, vendor: Dict[str, Any] = Depends(require_vendor)):
    target = await db.products.find_one({"id": product_id})
    if not target:
        raise HTTPException(status_code=404, detail="Product not found")
    if target.get("vendor_id") != vendor["id"]:
        raise HTTPException(status_code=403, detail="Not your product")
    # UPDATE 1 — Strip `is_published` from vendor updates: only admins can
    # publish/unpublish. If a vendor sends the field (older client), we drop it
    # silently so the current admin decision is respected.
    update = {
        k: v for k, v in payload.dict().items()
        if v is not None and k not in ("vendor_id", "is_published")
    }
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    # Dec 2026 — Compress any image fields present in the update
    # (Pillow, ≤1280 px, JPEG q=82).  Safe no-op for non-image updates.
    from core.image_compress import compress_product_payload, strip_managed_image_urls
    from core.variants import apply_variants_to_payload
    update = compress_product_payload(strip_managed_image_urls(update, target))
    _base = float(
        update.get("price")
        if update.get("price") is not None
        else (target.get("base_price") or target.get("price") or 0)
    )
    update = apply_variants_to_payload(update, _base)
    from core.taxonomy import normalize_product_taxonomy
    update = await normalize_product_taxonomy(update, target)
    await db.products.update_one({"id": product_id}, {"$set": update})
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
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
async def vendor_my_sales(
    status: Optional[str] = None,
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    """Return vendor sales enriched with the parent order's status and buyer
    info, so the mobile Vendor Orders screen can filter by
    placed/shipped/delivered/cancelled and display buyer + line-item totals.

    Also aggregates sales by order_id so each order shows once with all its
    items (not once per line).  This matches the web dashboard.
    """
    q: Dict[str, Any] = {"vendor_id": vendor["id"]}
    sales = await db.vendor_sales.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)

    # Bulk fetch parent orders in one shot
    order_ids = list({s.get("order_id") for s in sales if s.get("order_id")})
    orders_by_id: Dict[str, Any] = {}
    if order_ids:
        async for o in db.orders.find({"id": {"$in": order_ids}}, {"_id": 0}):
            orders_by_id[o["id"]] = o

    # Bulk fetch buyer users
    buyer_ids = list({s.get("buyer_id") for s in sales if s.get("buyer_id")})
    buyers_by_id: Dict[str, Any] = {}
    if buyer_ids:
        async for u in db.users.find(
            {"id": {"$in": buyer_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1},
        ):
            buyers_by_id[u["id"]] = u

    # Group by order_id so the vendor sees one card per order
    # Sep-2026 — `vendor_sales` rows never stored a product image, so the
    # vendor's order cards rendered blank thumbnails. Fall back to the
    # parent order's line item (same product_id) and finally to the product
    # catalogue, so the seller sees exactly what the customer saw.
    order_item_images: Dict[str, Dict[str, str]] = {}
    for oid, o in orders_by_id.items():
        for it in o.get("items") or []:
            if it.get("product_id") and it.get("image_url"):
                order_item_images.setdefault(oid, {})[it["product_id"]] = it["image_url"]
    missing_pids = list({
        s.get("product_id") for s in sales
        if s.get("product_id")
        and not s.get("product_image_url")
        and not (order_item_images.get(s.get("order_id") or "", {}).get(s.get("product_id")))
    })
    product_images: Dict[str, str] = {}
    if missing_pids:
        async for p in db.products.find(
            {"id": {"$in": missing_pids}}, {"_id": 0, "id": 1, "image_url": 1, "images": 1},
        ):
            imgs = p.get("images") or []
            product_images[p["id"]] = p.get("image_url") or (imgs[0] if imgs else "")

    grouped: Dict[str, Dict[str, Any]] = {}
    for s in sales:
        oid = s.get("order_id") or s.get("id")
        line_total = float(s.get("line_total") or 0)
        qty = int(s.get("qty") or 1) or 1
        unit_price = round(line_total / qty, 2) if qty else line_total
        pid = s.get("product_id") or ""
        item = {
            "product_id": pid,
            "name": s.get("product_name") or "Product",
            "price": unit_price,
            "qty": qty,
            "image_url": (
                s.get("product_image_url")
                or order_item_images.get(oid, {}).get(pid)
                or product_images.get(pid)
                or ""
            ),
            "line_total": line_total,
        }
        if oid not in grouped:
            parent = orders_by_id.get(oid) or {}
            buyer = buyers_by_id.get(s.get("buyer_id") or "") or {}
            # Pull address details if present on the parent order
            addr = parent.get("shipping_address") or {}
            grouped[oid] = {
                "id": s.get("id"),
                "order_id": oid,
                "order_number": parent.get("order_number") or s.get("order_number") or f"SC-{str(oid)[:6].upper()}",
                "user_id": s.get("buyer_id"),
                "created_at": s.get("created_at") or parent.get("created_at"),
                "status": parent.get("status") or "placed",
                "items": [],
                "total": 0.0,
                "cod_due": round(float(parent.get("cod_due") or 0), 2),
                "wallet_paid": round(float(parent.get("wallet_paid") or 0), 2),
                "buyer_name": buyer.get("name") or s.get("buyer_email") or "Customer",
                "buyer_email": buyer.get("email") or s.get("buyer_email"),
                "buyer_phone": buyer.get("phone"),
                "shipping_address": addr,
                "paid_via": parent.get("paid_via") or "wallet",
                "payment_status": parent.get("payment_status"),
                # Jul 2026 — Delivery info (set via PATCH /vendor/orders/{id}/delivery-info)
                "estimated_delivery_at": parent.get("estimated_delivery_at") or s.get("estimated_delivery_at"),
                "delivery_person_name": parent.get("delivery_person_name") or s.get("delivery_person_name"),
                "delivery_person_phone": parent.get("delivery_person_phone") or s.get("delivery_person_phone"),
                # Jun-2026 — a RECHARGE order has nothing to pack: the seller
                # needs the number to recharge, front and centre.
                "order_kind": parent.get("order_kind"),
                "is_recharge": bool(parent.get("is_recharge")),
                "recharge_kind": parent.get("recharge_kind"),
                "recharge_account": parent.get("recharge_account"),
                "recharge_network": parent.get("recharge_network"),
            }
        grouped[oid]["items"].append(item)
        grouped[oid]["total"] = round(float(grouped[oid]["total"]) + line_total, 2)

    out = list(grouped.values())

    # Jul 2026 — Also include POS sales so the Sales screen shows every
    # channel in one list (per user directive: "showing value Zero and
    # not showing Product details — should display both online and new
    # sales").  POS rows are already order-shaped (one row per invoice).
    pos_rows = await db.offline_sales.find(
        {"vendor_id": vendor["id"]},
        {"_id": 0},
    ).to_list(20000)
    for s in pos_rows:
        items = s.get("items") or []
        shaped_items = [{
            "name": it.get("name") or "Item",
            "price": float(it.get("price") or it.get("unit_price") or 0),
            "qty": int(it.get("qty") or 1) or 1,
            "image_url": it.get("image_url") or "",
            "line_total": float(it.get("line_total") or (float(it.get("price") or 0) * int(it.get("qty") or 1))),
        } for it in items]
        cust = s.get("customer") or {}
        out.append({
            "id": s.get("id"),
            "order_id": s.get("id"),
            "user_id": None,
            "created_at": s.get("created_at"),
            "status": "delivered" if s.get("status") == "completed" else "cancelled",
            "items": shaped_items,
            "total": round(float((s.get("totals") or {}).get("grand_total") or 0), 2),
            "buyer_name": cust.get("name") or "Walk-in customer",
            "buyer_email": cust.get("email"),
            "buyer_phone": cust.get("phone"),
            "paid_via": ((s.get("payments") or [{}])[0].get("mode") or "cash").lower(),
            "payment_status": "paid",
            "channel": "pos",
            "invoice_no": s.get("invoice_no") or s.get("invoice_number"),
        })

    # Filter by status if requested
    if status and status != "all":
        out = [o for o in out if o.get("status") == status]
    # Sort newest first
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"items": out, "total": len(out)}


# ---- Vendor-scoped order status update (mirrors admin endpoint) ----
class VendorOrderStatusUpdate(BaseModel):
    status: str


class VendorOrderDeliveryInfo(BaseModel):
    """Jul 2026 — Vendor sets/updates ETA + delivery-person contact.

    Both fields are optional; the vendor can update one at a time. The
    ETA is stored as an ISO-8601 string so the user-facing timeline can
    format it in the customer's locale. Delivery person is a
    lightweight name + phone — no separate user record needed.
    """
    estimated_delivery_at: Optional[str] = None
    delivery_person_name: Optional[str] = None
    delivery_person_phone: Optional[str] = None


@api_router.patch("/vendor/orders/{order_id}/delivery-info")
async def vendor_update_delivery_info(
    order_id: str,
    payload: VendorOrderDeliveryInfo,
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    """Vendor sets estimated delivery time + delivery person contact.
    Also mirrors the values onto the vendor_sales rows so the /vendor/me/sales
    listing can render the same info without a per-order lookup.
    """
    owns = await db.vendor_sales.find_one({"order_id": order_id, "vendor_id": vendor["id"]})
    if not owns:
        raise HTTPException(status_code=403, detail="Not your order")

    update: Dict[str, Any] = {"delivery_info_updated_at": now_utc().isoformat()}
    if payload.estimated_delivery_at is not None:
        update["estimated_delivery_at"] = (payload.estimated_delivery_at or "").strip() or None
    if payload.delivery_person_name is not None:
        update["delivery_person_name"] = (payload.delivery_person_name or "").strip() or None
    if payload.delivery_person_phone is not None:
        update["delivery_person_phone"] = (payload.delivery_person_phone or "").strip() or None

    await db.orders.update_one({"id": order_id}, {"$set": update})
    # Denormalise onto vendor_sales rows so /vendor/me/sales sees updates instantly.
    await db.vendor_sales.update_many({"order_id": order_id, "vendor_id": vendor["id"]}, {"$set": update})

    # Notify the customer if we have a buyer_id on the order.
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "user_id": 1, "id": 1})
    if o and o.get("user_id"):
        try:
            bits: List[str] = []
            if payload.estimated_delivery_at:
                bits.append(f"ETA: {payload.estimated_delivery_at}")
            if payload.delivery_person_name or payload.delivery_person_phone:
                dn = payload.delivery_person_name or "Rider"
                dp = payload.delivery_person_phone or ""
                bits.append(f"{dn}{(' · ' + dp) if dp else ''}")
            await _create_notification(
                o["user_id"], "order",
                f"Delivery info updated for #{order_id[:8].upper()}",
                " · ".join(bits) if bits else "Your vendor updated delivery info.",
            )
        except Exception:
            pass

    fresh = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return {"ok": True, "order": fresh}


@api_router.patch("/vendor/orders/{order_id}/status")
async def vendor_update_order_status(
    order_id: str,
    payload: VendorOrderStatusUpdate,
    vendor: Dict[str, Any] = Depends(require_vendor),
):
    if payload.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Use one of: {', '.join(ORDER_STATUSES)}")
    # Ensure the order has at least one line for this vendor.
    owns = await db.vendor_sales.find_one({"order_id": order_id, "vendor_id": vendor["id"]})
    if not owns:
        raise HTTPException(status_code=403, detail="Not your order")
    # Oct 2026 — if admin mapped a delivery partner to this shop, the seller
    # only accepts or cancels. Every delivery stage belongs to the rider so
    # the two panels can never fight over the same order.
    from routes.delivery_partner import (
        VENDOR_ALLOWED_WHEN_DP_MANAGED, vendor_dp_partners,
    )
    if payload.status not in VENDOR_ALLOWED_WHEN_DP_MANAGED:
        partners = await vendor_dp_partners(vendor["id"])
        if partners:
            names = ", ".join(p["name"] for p in partners)
            raise HTTPException(
                status_code=403,
                detail=f"Your deliveries are handled by {names}. You can accept or "
                       f"cancel an order — the delivery partner marks it shipped and delivered.",
            )
    # Delegate to the admin handler so the commission-settle side-effects
    # (COD delivery credit, refunds on cancel) fire identically.
    return await admin_update_order_status(
        order_id=order_id,
        payload=OrderStatusUpdate(status=payload.status),  # type: ignore
        admin=vendor,  # vendor doc is user-shaped, downstream only reads id/email
    )


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
    # Dec 2026 — CRITICAL: Set is_vendor_approved AND denormalise every
    # delivery-config field from the application onto the user doc.  The
    # customer-facing shop's `_eligible_vendor_ids` filter reads these
    # scalar fields (lat, lng, store_pincode, delivery_pincodes,
    # delivery_radius_km, delivery_radius_mode) — so without this copy,
    # newly-approved vendors' products never appear in the Shop for
    # customers even though the vendor CAN log in and add products.
    user_set: Dict[str, Any] = {
        "is_vendor": True,
        "is_vendor_approved": True,
        "vendor_status": "approved",
        "shop_name": a.get("shop_name"),
        "vendor_approved_at": ts,
    }
    # Denormalise delivery / location config
    if a.get("pincode"):
        user_set["pincode"] = a["pincode"]
        user_set["store_pincode"] = a["pincode"]
    if a.get("state"): user_set["state"] = a["state"]
    if a.get("district"): user_set["district"] = a["district"]
    if a.get("city"): user_set["city"] = a["city"]
    if a.get("store_address"): user_set["store_address"] = a["store_address"]
    if a.get("location"): user_set["location"] = a["location"]
    if isinstance(a.get("lat"), (int, float)): user_set["lat"] = float(a["lat"])
    if isinstance(a.get("lng"), (int, float)): user_set["lng"] = float(a["lng"])
    if a.get("delivery_radius_km") is not None:
        user_set["delivery_radius_km"] = a["delivery_radius_km"]
    if a.get("delivery_radius_mode"):
        user_set["delivery_radius_mode"] = a["delivery_radius_mode"]
    if a.get("delivery_pincodes"):
        user_set["delivery_pincodes"] = a["delivery_pincodes"]
    if a.get("delivery_available") is not None:
        user_set["delivery_available"] = a["delivery_available"]
    await db.users.update_one({"id": a["user_id"]}, {"$set": user_set})
    # Bust the products_public cascade + eligibility caches so the newly
    # approved vendor's zone takes effect immediately across /products.
    try:
        from routes.products_public import bust_products_public_caches
        bust_products_public_caches()
    except Exception:
        pass
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


# Jul 2026 — Renamed from GET /admin/vendors to /admin/vendors/detailed
# because the new lightweight vendor picker at /admin/vendors (line 2707)
# takes precedence for the Products page filter.  This detailed endpoint
# still powers the Admin → Vendors dashboard with per-vendor sales rollups.
@api_router.get("/admin/vendors/detailed")
async def admin_list_vendors_detailed(admin: Dict[str, Any] = Depends(require_admin)):
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
    # Resolve sub-category (June 2026): must belong to the picked parent
    sub_doc = None
    if payload.service_subcategory_id:
        sub_doc = await db.service_subcategories.find_one({
            "id": payload.service_subcategory_id, "active": True,
        })
        if sub_doc and cat_doc and sub_doc.get("parent_id") != cat_doc.get("id"):
            # Subcategory mismatch with selected category — reject silently
            sub_doc = None
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
        # June 2026 — sub-category support
        "service_subcategory_id": sub_doc["id"] if sub_doc else None,
        "service_subcategory_name": sub_doc.get("name") if sub_doc else None,
        "languages": langs,
        "pincode": payload.pincode,
        "charge": float(payload.charge),
        "description": (payload.description or "").strip() or None,
        # Sept 2026 — Persist the consent audit block for legal review.
        "accepted_terms": (payload.accepted_terms.model_dump() if payload.accepted_terms else None),
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
                "category_id": fresh.get("category_id"),
                "service_subcategory_id": fresh.get("service_subcategory_id"),
                "service_subcategory_name": fresh.get("service_subcategory_name"),
                "service_pincode": fresh.get("service_pincode"),
                "service_charge": fresh.get("service_charge"),
                "service_description": fresh.get("service_description"),
                "service_languages": fresh.get("service_languages") or [],
                "service_updated_at": fresh.get("service_updated_at"),
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
            # June 2026 — sub-category support
            "service_subcategory_id": app.get("service_subcategory_id"),
            "service_subcategory_name": app.get("service_subcategory_name"),
            "service_languages": app.get("languages") or [],
            "service_pincode": app["pincode"],
            "service_charge": app["charge"],
            "service_description": app.get("description"),
            "service_approved_at": ts,
            # June 2026 — default availability so the provider shows up
            # immediately in customer searches and admin analytics buckets.
            # They can toggle Available/Busy/Offline themselves later.
            "availability_status": "available",
            "availability_updated_at": ts,
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
    subcategory_id: Optional[str] = None,
    availability: Optional[str] = None,  # filter to "available" | "busy" | "offline"
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
    if subcategory_id:
        base_filt["service_subcategory_id"] = subcategory_id
    if availability and availability in {"available", "busy", "offline"}:
        # Explicit filter — respect exactly what the caller asked for.
        base_filt["availability_status"] = availability
    else:
        # Default behaviour (June 2026): hide providers who explicitly marked
        # themselves "offline" so customers don't see / try to book them.
        # `available`, `busy`, missing, and any other legacy values stay visible.
        base_filt["availability_status"] = {"$ne": "offline"}
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
        # Provider availability (June 2026) — independent of live location.
        # Drives the green/yellow/gray dot shown next to a provider in the
        # services listing & detail screen.
        "availability_status": 1,
        "availability_updated_at": 1,
        # Profile picture (June 2026) — uploaded by the provider from their
        # Profile screen. Always projected so the listing card + detail
        # hero avatar can render the real photo. Base64 data URI inline.
        "profile_image": 1,
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
    # ── June 2026 expansion (modern service icons) ──
    {"name": "Appliance Repair",      "slug": "appliance-repair",      "icon": "refresh-ccw",  "color": "#7C3AED"},
    {"name": "Delivery",              "slug": "delivery",              "icon": "package",      "color": "#F97316"},
    {"name": "Vehicle Repair",        "slug": "vehicle-repair",        "icon": "truck",        "color": "#1F2937"},
    {"name": "Home Maintenance",      "slug": "home-maintenance",      "icon": "clipboard",    "color": "#0F766E"},
    {"name": "Labour",                "slug": "labour",                "icon": "users",        "color": "#B45309"},
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


# Service Category CRUD + Service Analytics moved to routes/service_admin.py
# (2026-05-28 refactor — extracted from server.py)


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
            "availability_status": 1, "availability_updated_at": 1,
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
    # Oct 2026 — delivery partners are riders, never customers.
    from routes.cart import _block_dp_shopping
    _block_dp_shopping(user)
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
    # Credit admin platform fee (skipped when service_booking_margin_enabled=False)
    settings_now3 = await get_settings()
    svc_margin_on = bool(settings_now3.get("service_booking_margin_enabled", False))
    if svc_margin_on and admin_share > 0:
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


# ============================================================
# Phone-number Reveal Fee (June 2026)
# Replaces the old "Book full service" flow. Customer pays a small fee
# (default ₹1 + 18% GST) from their wallet; base fee credits the System
# Wallet `service_margin` bucket, GST goes into `gst_collected`. The
# transaction generates an invoice surfaced under "My Service Bills"
# (collection: phone_reveal_invoices).
# ============================================================
@api_router.get("/services/reveal-config")
async def get_phone_reveal_config(user: Dict[str, Any] = Depends(get_current_user)):
    """Return fee + GST + user balance + already-revealed providers."""
    settings = await get_settings()
    # Sep 2026 — `or 1.0` swallowed a deliberate ₹0 fee, so admins could not
    # make unlock/chat free. Read the value as configured (None = default ₹1).
    _fee_cfg = settings.get("phone_reveal_fee")
    fee = float(_fee_cfg) if _fee_cfg is not None else 1.0
    gst_pct = float(settings.get("phone_reveal_gst_pct") if settings.get("phone_reveal_gst_pct") is not None else 18.0)
    gst_amt = round(fee * gst_pct / 100.0, 2)
    total = round(fee + gst_amt, 2)
    # Providers already revealed by this user (so we can show without re-charging)
    revealed_rows = await db.phone_reveal_invoices.find(
        {"user_id": user["id"]}, {"_id": 0, "provider_id": 1}
    ).to_list(500)
    return {
        "fee": fee,
        "gst_pct": gst_pct,
        "gst_amount": gst_amt,
        "total": total,
        "wallet_balance": float(user.get("wallet_balance") or 0),
        "revealed_provider_ids": list({r.get("provider_id") for r in revealed_rows if r.get("provider_id")}),
    }


@api_router.post("/services/{provider_id}/reveal-phone")
async def reveal_phone_number(provider_id: str, payload: RevealPhoneRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Charge wallet, credit System Wallet (service_margin + gst_collected),
    write a phone_reveal_invoices doc and return the provider's phone number.

    Idempotent per (user_id, provider_id): if the user has already paid for
    this provider's phone we just return the existing invoice — no double
    charge. T&C must be explicitly accepted via `accept_terms=true`.
    """
    if not payload.accept_terms:
        raise HTTPException(status_code=400, detail="You must accept the terms & conditions.")
    if provider_id == user["id"]:
        raise HTTPException(status_code=400, detail="You can't reveal your own number")
    provider = await db.users.find_one({"id": provider_id, "is_service_provider": True})
    if not provider:
        raise HTTPException(status_code=404, detail="Service provider not found")
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=400, detail="Your wallet is frozen")

    # Idempotency — already revealed once
    existing = await db.phone_reveal_invoices.find_one(
        {"user_id": user["id"], "provider_id": provider_id}, {"_id": 0}
    )
    if existing:
        return {
            "ok": True,
            "already_revealed": True,
            "invoice": existing,
            "provider_phone": provider.get("phone"),
            "provider_name": provider.get("name"),
        }

    settings = await get_settings()
    # Sep 2026 — `or 1.0` swallowed a deliberate ₹0 fee, so admins could not
    # make unlock/chat free. Read the value as configured (None = default ₹1).
    _fee_cfg = settings.get("phone_reveal_fee")
    fee = float(_fee_cfg) if _fee_cfg is not None else 1.0
    gst_pct = float(settings.get("phone_reveal_gst_pct") if settings.get("phone_reveal_gst_pct") is not None else 18.0)
    gst_amt = round(fee * gst_pct / 100.0, 2)
    total = round(fee + gst_amt, 2)
    bal = float(user.get("wallet_balance") or 0)
    if bal < total:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient wallet balance — need ₹{total:.2f} (₹{fee:.2f} + ₹{gst_amt:.2f} GST). Please top up.",
        )

    # Atomic wallet debit guarded by balance condition.
    # A ₹0 configured fee means unlocking is free — skip the debit entirely
    # (an $inc of 0 would still fail the $gte guard on an empty wallet).
    if total > 0:
        debit_res = await db.users.update_one(
            {"id": user["id"], "wallet_balance": {"$gte": total}},
            {"$inc": {"wallet_balance": -total}},
        )
        if debit_res.modified_count == 0:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance — please top up.")

    inv_id = str(uuid.uuid4())
    ts = now_utc().isoformat()
    invoice_no = f"PR-{ts[:10].replace('-', '')}-{inv_id[:6].upper()}"

    # Credit admin buckets: fee → service_margin, gst → gst_collected
    if fee > 0:
        await credit_admin_bucket("service_margin", fee, also_total_earned=True)
    if gst_amt > 0:
        await credit_admin_bucket("gst_collected", gst_amt, also_total_earned=False)

    # Customer-side debit transaction (nothing to record when unlocking is free)
    try:
        if total > 0:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "type": "phone_reveal_fee",
                "amount": -total,
                "status": "success",
                "description": f"Phone reveal fee for {provider.get('name')} (₹{fee:.2f} + ₹{gst_amt:.2f} GST)",
                "provider_id": provider_id,
                "invoice_id": inv_id,
                "invoice_no": invoice_no,
                "created_at": ts,
            })
    except DuplicateKeyError:
        pass
    # Admin-side credit transaction (records the income side for ledger sums)
    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()}) if fee > 0 else None
    if admin_doc:
        try:
            await db.transactions.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": admin_doc["id"],
                "type": "service_margin",
                "amount": fee,
                "status": "success",
                "description": f"Phone reveal fee from {user.get('name')} for {provider.get('name')}",
                "provider_id": provider_id,
                "invoice_id": inv_id,
                "invoice_no": invoice_no,
                "source_user_name": user.get("name"),
                "created_at": ts,
            })
            if gst_amt > 0:
                await db.transactions.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": admin_doc["id"],
                    "type": "gst_collected",
                    "amount": gst_amt,
                    "status": "success",
                    "description": f"GST on phone reveal fee from {user.get('name')}",
                    "provider_id": provider_id,
                    "invoice_id": inv_id,
                    "invoice_no": invoice_no,
                    "source_user_name": user.get("name"),
                    "created_at": ts,
                })
        except DuplicateKeyError:
            pass

    branding = await db.branding.find_one({"id": "global"}, {"_id": 0}) or {}
    invoice = {
        "id":              inv_id,
        "invoice_no":      invoice_no,
        "user_id":         user["id"],
        "user_name":       user.get("name"),
        "user_email":      user.get("email"),
        "provider_id":     provider_id,
        "provider_name":   provider.get("name"),
        "provider_phone":  provider.get("phone"),
        "service_name":    provider.get("service_name"),
        "service_category": provider.get("service_category"),
        "fee":             fee,
        "gst_pct":         gst_pct,
        "gst_amount":      gst_amt,
        "total":           total,
        "currency":        "INR",
        "biller_name":     branding.get("business_name") or branding.get("app_name") or "Slangcart",
        "biller_gst":      branding.get("business_gst"),
        "biller_address":  branding.get("business_address"),
        "biller_city":     branding.get("business_city"),
        "biller_state":    branding.get("business_state"),
        "biller_pincode":  branding.get("business_pincode"),
        "created_at":      ts,
    }
    await db.phone_reveal_invoices.insert_one(invoice)
    invoice.pop("_id", None)

    # Notify provider that someone unlocked their number (no PII exchange)
    try:
        await _create_notification(
            provider_id, "service", "Someone got your number",
            f"{user.get('name')} unlocked your phone via the platform.",
        )
    except Exception:
        pass
    return {
        "ok": True,
        "already_revealed": False,
        "invoice": invoice,
        "provider_phone": provider.get("phone"),
        "provider_name":  provider.get("name"),
    }


# my_phone_reveals + get_phone_reveal_invoice moved to routes/service_provider.py
# (2026-05-28 refactor)


# ============================================================
# Admin: Withdraw funds from System Wallet for Account Tally
# Lets the admin record an off-platform usage of System Wallet funds
# (e.g. owner withdrew money for personal/business use). Properly
# audit-logged and reflected in a new collection so the ledger stays
# transparent.
# ============================================================
SYSTEM_WALLET_TALLY_DEFAULT_BUCKET = "direct_added"


@api_router.post("/admin/system-wallet/tally-withdraw")
async def admin_tally_withdraw(
    payload: AdminTallyWithdrawRequest,
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance")),
):
    amount = round(float(payload.amount or 0), 2)
    note = (payload.note or "").strip()
    bucket = (payload.bucket or SYSTEM_WALLET_TALLY_DEFAULT_BUCKET).strip()
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="Please add a note explaining this withdrawal")
    if bucket not in SYSTEM_WALLET_BUCKETS:
        raise HTTPException(status_code=400, detail=f"Invalid bucket. Allowed: {', '.join(SYSTEM_WALLET_BUCKETS)}")
    admin_doc = await db.users.find_one({"email": ADMIN_EMAIL.lower()})
    if not admin_doc:
        raise HTTPException(status_code=500, detail="Admin user not found")
    bucket_balance = float((admin_doc.get("wallet_buckets") or {}).get(bucket) or 0)
    if bucket_balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance in bucket '{bucket}' (₹{bucket_balance:.2f} available)",
        )
    ok = await debit_admin_bucket(bucket, amount)
    if not ok:
        raise HTTPException(status_code=400, detail="Race condition — try again")
    wid = str(uuid.uuid4())
    ts = now_utc().isoformat()
    record = {
        "id":            wid,
        "amount":        amount,
        "bucket":        bucket,
        "note":          note[:500],
        "admin_id":      admin["id"],
        "admin_email":   admin.get("email"),
        "created_at":    ts,
    }
    await db.system_wallet_tally_withdrawals.insert_one(record)
    # Mirror as a transaction so reports stay coherent.
    try:
        await db.transactions.insert_one({
            "id":          str(uuid.uuid4()),
            "user_id":     admin_doc["id"],
            "type":        "system_wallet_tally_withdraw",
            "amount":      -amount,
            "status":      "success",
            "description": f"Account tally: {note[:120]}",
            "tally_id":    wid,
            "bucket":      bucket,
            "created_at":  ts,
        })
    except DuplicateKeyError:
        pass
    await _audit_log(
        admin, "system_wallet.tally_withdraw", "wallet", admin_doc["id"],
        {"amount": amount, "bucket": bucket, "note": note[:120]},
    )
    record.pop("_id", None)
    return {"ok": True, "withdrawal": record}


@api_router.get("/admin/system-wallet/tally-withdrawals")
async def admin_list_tally_withdrawals(
    admin: Dict[str, Any] = Depends(require_admin_role("super_admin", "finance", "manager", "support")),
):
    rows = await db.system_wallet_tally_withdrawals.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    total = round(sum(float(r.get("amount") or 0) for r in rows), 2)
    return {"items": rows, "total_count": len(rows), "total_amount": total}


# ============================================================
# Address Edit (authenticated user)
# Lets a regular user update their delivery / contact address from
# the Profile screen. KYC-related identity fields are NOT touched.
# ============================================================
@api_router.patch("/users/me/address")
async def update_my_address(payload: AddressUpdateRequest, user: Dict[str, Any] = Depends(get_current_user)):
    update: Dict[str, Any] = {}
    if payload.address is not None:
        update["address"] = (payload.address or "").strip()[:300]
    if payload.city is not None:
        update["city"] = (payload.city or "").strip()[:80]
    if payload.state is not None:
        update["state"] = (payload.state or "").strip()[:80]
    if payload.pincode is not None:
        pc = (payload.pincode or "").strip()
        if pc and not pc.isdigit():
            raise HTTPException(status_code=400, detail="Pincode must be numeric")
        if pc and (len(pc) < 4 or len(pc) > 10):
            raise HTTPException(status_code=400, detail="Pincode looks invalid")
        update["pincode"] = pc
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["address_updated_at"] = now_utc().isoformat()
    await db.users.update_one({"id": user["id"]}, {"$set": update})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0, "password_recovery_ciphertext": 0})
    return {"ok": True, "user": fresh}


# ============================================================
# ============================================================
# Provider Availability + Customer Location moved to routes/service_provider.py
# (2026-05-28 refactor — extracted from server.py)
# ============================================================
_AVAIL_STATUSES = {"available", "busy", "offline"}  # kept for any in-file refs


# ============================================================
# Service Subcategories routes extracted to routes/service_subcategories.py
# (2026-05-28 refactor)
# ============================================================


# ============================================================
# AI Generation routes extracted to routes/admin_ai.py (2026-05-28 refactor)
# ============================================================


# Service Analytics endpoint moved to routes/service_admin.py
# (2026-05-28 refactor — extracted from server.py)


# Include router
app.include_router(api_router)


# Phase 2B refactor: extracted routers, mounted at /api so URLs are unchanged
# from the client's perspective.
app.include_router(branding_router.router, prefix="/api")
app.include_router(notifications_router.router, prefix="/api")
app.include_router(products_public_router.router, prefix="/api")
app.include_router(products_master_router.router, prefix="/api")
app.include_router(products_master_specs_router.router, prefix="/api")
app.include_router(products_master_images_router.router, prefix="/api")
app.include_router(promo_banners_router.router, prefix="/api")
app.include_router(shop_layout_router.router, prefix="/api")
app.include_router(shop_layout_analytics_router.router, prefix="/api")
app.include_router(chat_router.router, prefix="/api")
app.include_router(chat_audit_router.router, prefix="/api")
app.include_router(products_extended_router.router, prefix="/api")
app.include_router(products_ai_router.router, prefix="/api")
app.include_router(shop_categories_router.router, prefix="/api")
# Nov 2026 — vendor edit-request approval flow + OSM geo endpoints
from routes import vendor_edit_requests as vendor_edit_requests_router  # noqa: E402
from routes import geo as geo_router  # noqa: E402
app.include_router(vendor_edit_requests_router.router, prefix="/api")
app.include_router(geo_router.router, prefix="/api")
app.include_router(tickets_router.router, prefix="/api")
app.include_router(pincodes_router.router, prefix="/api")
app.include_router(legal_pages_router.router, prefix="/api")
app.include_router(upi_manual_router.router, prefix="/api")
# Phase 2B Iter 4 (2026-05-27) — wallet / withdrawals / cart routers
app.include_router(wallet_router.router, prefix="/api")
app.include_router(wallet_topup_router.router, prefix="/api")
app.include_router(payment_recon_router.router, prefix="/api")
app.include_router(withdrawals_router.router, prefix="/api")
from routes import cashback as cashback_router  # noqa: E402
app.include_router(cashback_router.router, prefix="/api")
from routes import signup_gate as signup_gate_router  # noqa: E402
app.include_router(signup_gate_router.router, prefix="/api")
from routes import recharge as recharge_router  # noqa: E402
app.include_router(recharge_router.router, prefix="/api")
from routes import product_rails as product_rails_router  # noqa: E402
app.include_router(product_rails_router.router, prefix="/api")
from routes import wallet_export as wallet_export_router  # noqa: E402
app.include_router(wallet_export_router.router, prefix="/api")
app.include_router(cart_router.router, prefix="/api")
app.include_router(admin_ai_router.router, prefix="/api")
app.include_router(service_subcategories_router.router, prefix="/api")
app.include_router(service_admin_router.router, prefix="/api")
app.include_router(service_provider_router.router, prefix="/api")
app.include_router(finance_router.router, prefix="/api")
app.include_router(refunds_router.router, prefix="/api")
app.include_router(returns_router.router, prefix="/api")
app.include_router(vendor_networth_router.router, prefix="/api")
app.include_router(reconciliation_router.router, prefix="/api")
# Vendor Cloud-POS (SALES_BACKEND_SPEC, 29-Jun-2026). Strictly vendor
# business-records + inventory sync — does NOT touch wallets/ledgers.
app.include_router(vendor_pos_router.router, prefix="/api")
app.include_router(privacy_router.router, prefix="/api")
app.include_router(push_router.router, prefix="/api")
app.include_router(broadcast_router.router, prefix="/api")
app.include_router(maintenance_router.router, prefix="/api")
app.include_router(chat_settings_router.router, prefix="/api")
app.include_router(backup_router.router, prefix="/api")
app.include_router(delivery_router.router, prefix="/api")
app.include_router(admin_passwords_router.router, prefix="/api")
app.include_router(login_history_router.router, prefix="/api")
app.include_router(order_payments_router.router, prefix="/api")
from routes import delivery_partner as delivery_partner_router  # noqa: E402
app.include_router(delivery_partner_router.router, prefix="/api")

# ============================================================
# CORS — explicit allowlist for production (June 2026 hardening)
# Was wildcard "*"; tightened after networkrupay.com was linked
# as the public domain. Driver: better browser-credentials handling
# (wildcard + allow_credentials=True is rejected by some browsers)
# and reduced attack surface vs. open CORS.
# Env-var override: set ALLOWED_ORIGINS="https://a.com,https://b.com"
# in backend/.env to extend without code changes.
# ============================================================
_DEFAULT_ALLOWED_ORIGINS = [
    # Production custom domain — Slangcart
    "https://www.slangcart.com",
    "https://slangcart.com",
    # Legacy custom domain — kept for backward compatibility
    "https://www.networkrupay.com",
    "https://networkrupay.com",
    # Emergent deployment URL
    "https://network-pay-1.emergent.host",
    # Emergent preview (dev) URL
    "https://slangcart-tracking.preview.emergentagent.com",
    # Local dev / Expo Go
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:8081",
    "http://localhost:19006",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8081",
]
_env_origins = (os.getenv("ALLOWED_ORIGINS") or "").strip()
_extra_origins = [o.strip() for o in _env_origins.split(",") if o.strip()] if _env_origins else []
ALLOWED_ORIGINS = list({*_DEFAULT_ALLOWED_ORIGINS, *_extra_origins})

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=ALLOWED_ORIGINS,
    # Hot-fix (2026-05-29 evening): the previous regex only allowed ONE
    # optional subdomain level which broke Emergent preview URLs like
    # `<slug>.preview.emergentagent.com` (three parts). The new pattern
    # accepts any number of subdomain levels for the trusted root hosts,
    # so future Emergent rotations / new preview shapes don't break login.
    allow_origin_regex=(
        r"https?://"
        r"(?:[a-z0-9-]+\.)*"
        r"(?:emergent\.host|emergentagent\.com|slangcart\.com|networkrupay\.com|"
        r"emergent\.sh|pages\.dev|vercel\.app|netlify\.app)"
        r"(?::\d+)?$"
    ),
    allow_methods=["*"],
    allow_headers=["*"],
)
