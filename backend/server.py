from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import logging
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import bcrypt
import jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field


# ------------------ Config ------------------
MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
JWT_SECRET = os.environ['JWT_SECRET']
JWT_ALGORITHM = "HS256"
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@app.com')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Admin@123')
REGISTRATION_FEE = float(os.environ.get('REGISTRATION_FEE', 100))
PAYOUT_PER_LEVEL = float(os.environ.get('PAYOUT_PER_LEVEL', 400))
LEVEL_2_PAYOUT = float(os.environ.get('LEVEL_2_PAYOUT', 100))
LEVEL_3_PAYOUT = float(os.environ.get('LEVEL_3_PAYOUT', 50))
DIRECTS_REQUIRED = 4

DEFAULT_SETTINGS = {
    "registration_fee": REGISTRATION_FEE,
    "payout_l1": PAYOUT_PER_LEVEL,
    "payout_l2": LEVEL_2_PAYOUT,
    "payout_l3": LEVEL_3_PAYOUT,
    "directs_required": DIRECTS_REQUIRED,
}


async def get_settings() -> Dict[str, Any]:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0})
    if not doc:
        return {**DEFAULT_SETTINGS, "id": "global"}
    return doc

# Achievement tiers based on team size
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

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ------------------ Helpers ------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def gen_referral_code(prefix: str = "") -> str:
    alphabet = string.ascii_uppercase + string.digits
    return prefix + ''.join(secrets.choice(alphabet) for _ in range(6))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def serialize_user(u: Dict[str, Any]) -> Dict[str, Any]:
    if not u:
        return u
    u = dict(u)
    u.pop("_id", None)
    u.pop("password_hash", None)
    return u


# ------------------ Auth Dependency ------------------
security = HTTPBearer(auto_error=False)


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = creds.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_admin_role(*allowed: str):
    """Restrict an endpoint to specific admin sub-roles (super_admin, manager, support)."""
    async def checker(admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
        sub = admin.get("admin_role") or "super_admin"  # legacy admins default super
        if sub not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires admin role: {' or '.join(allowed)}")
        return admin
    return checker


async def _audit_log(admin: Dict[str, Any], action: str, target_type: str = "", target_id: str = "", details: Optional[Dict[str, Any]] = None):
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "admin_id": admin["id"],
        "admin_email": admin.get("email"),
        "admin_role": admin.get("admin_role") or "super_admin",
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details": details or {},
        "created_at": now_utc().isoformat(),
    })


# ------------------ Models ------------------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)
    phone: Optional[str] = None
    referral_code: Optional[str] = None  # sponsor code


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class BankUpdate(BaseModel):
    upi_id: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    account_holder: Optional[str] = None


class WithdrawalRequest(BaseModel):
    amount: float = Field(gt=0)


class ProductCreate(BaseModel):
    name: str
    price: float
    image_url: str
    description: Optional[str] = ""
    stock: int = 100


# ------------------ FastAPI App ------------------
app = FastAPI(title="Referral & E-commerce API")
api_router = APIRouter(prefix="/api")


# ------------------ Auth Endpoints ------------------
@api_router.post("/auth/register")
async def register(payload: RegisterRequest):
    email = payload.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    sponsor = None
    sponsor_code = (payload.referral_code or "").strip().upper() or None
    if sponsor_code:
        sponsor = await db.users.find_one({"referral_code": sponsor_code})
        if not sponsor:
            raise HTTPException(status_code=400, detail="Invalid referral code")

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
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(user_doc)

    token = create_access_token(user_id, email, "user")
    return {"token": token, "user": serialize_user(user_doc)}


@api_router.post("/auth/login")
async def login(payload: LoginRequest):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("is_blocked"):
        reason = user.get("block_reason") or "Contact support."
        raise HTTPException(status_code=403, detail=f"Account blocked: {reason}")
    token = create_access_token(user["id"], email, user.get("role", "user"))
    return {"token": token, "user": serialize_user(user)}


@api_router.get("/auth/me")
async def me(user: Dict[str, Any] = Depends(get_current_user)):
    return serialize_user(user)


@api_router.post("/auth/logout")
async def logout(user: Dict[str, Any] = Depends(get_current_user)):
    return {"ok": True}


# ------------------ Payment (Mock) ------------------
async def _credit_payout(sponsor_user: Dict[str, Any], amount: float, level: int, source_user_name: str = ""):
    """Credit payout to sponsor at a given level, log transaction & notification."""
    inc = {"wallet_balance": amount, "total_earned": amount}
    if level == 1:
        inc["payouts_received"] = 1
    await db.users.update_one({"id": sponsor_user["id"]}, {"$inc": inc})
    desc = (
        f"Level {level} payout from {source_user_name}" if source_user_name
        else f"Level {level} referral payout"
    )
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": sponsor_user["id"],
        "type": "referral_payout",
        "level": level,
        "amount": amount,
        "status": "credited",
        "description": desc,
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(
        sponsor_user["id"],
        "payout",
        f"₹{int(amount)} credited!",
        desc,
    )


async def _create_notification(user_id: str, kind: str, title: str, body: str):
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": kind,
        "title": title,
        "body": body,
        "read": False,
        "created_at": now_utc().isoformat(),
    })


@api_router.post("/payment/register-fee")
async def pay_registration_fee(user: Dict[str, Any] = Depends(get_current_user)):
    """Mock registration fee payment. Activates account & triggers multi-level referral payouts."""
    if user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Registration fee already paid")

    settings = await get_settings()
    fee = settings["registration_fee"]
    payout_l1 = settings["payout_l1"]
    payout_l2 = settings["payout_l2"]
    payout_l3 = settings["payout_l3"]
    directs_required = settings["directs_required"]

    txn_id = str(uuid.uuid4())
    await db.users.update_one({"id": user["id"]}, {"$set": {"registration_paid": True}})
    await db.transactions.insert_one({
        "id": txn_id,
        "user_id": user["id"],
        "type": "registration_fee",
        "amount": fee,
        "status": "paid",
        "description": "Registration fee (mocked)",
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(user["id"], "welcome", "Welcome to NetworkPay!", f"Your account is now active. Start referring to earn ₹{int(payout_l1)} per {directs_required} directs.")

    # Walk up the upline 3 levels
    sponsor_id = user.get("sponsor_id")
    if sponsor_id:
        # Level 1: direct sponsor — increment direct count, payout on every Nth
        sponsor = await db.users.find_one({"id": sponsor_id})
        if sponsor:
            await db.users.update_one({"id": sponsor_id}, {"$inc": {"direct_referrals_count": 1}})
            new_count = sponsor.get("direct_referrals_count", 0) + 1
            await _create_notification(
                sponsor_id, "referral",
                f"New referral: {user['name']}",
                f"{user['name']} just joined your network. {directs_required - (new_count % directs_required or directs_required)} more to next ₹{int(payout_l1)} payout.",
            )
            if new_count % directs_required == 0:
                fresh = await db.users.find_one({"id": sponsor_id})
                await _credit_payout(fresh, payout_l1, 1, user["name"])

            # Level 2
            l2_id = sponsor.get("sponsor_id")
            if l2_id:
                l2 = await db.users.find_one({"id": l2_id})
                if l2:
                    await _credit_payout(l2, payout_l2, 2, user["name"])
                    # Level 3
                    l3_id = l2.get("sponsor_id")
                    if l3_id:
                        l3 = await db.users.find_one({"id": l3_id})
                        if l3:
                            await _credit_payout(l3, payout_l3, 3, user["name"])

    return {"ok": True, "transaction_id": txn_id, "amount": fee}


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
        "level_payouts": {"l1": settings["payout_l1"], "l2": settings["payout_l2"], "l3": settings["payout_l3"]},
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
@api_router.post("/withdrawals")
async def request_withdrawal(payload: WithdrawalRequest, user: Dict[str, Any] = Depends(get_current_user)):
    if not user.get("registration_paid"):
        raise HTTPException(status_code=400, detail="Complete registration payment first")
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
async def my_transactions(user: Dict[str, Any] = Depends(get_current_user)):
    items = await db.transactions.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return items


# ------------------ Products (E-commerce placeholder) ------------------
@api_router.get("/products")
async def list_products():
    items = await db.products.find({}, {"_id": 0}).to_list(1000)
    return items


# ------------------ Admin Endpoints ------------------
@api_router.get("/admin/users")
async def admin_list_users(_: Dict[str, Any] = Depends(require_admin)):
    items = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(5000)
    return items


@api_router.get("/admin/withdrawals")
async def admin_list_withdrawals(_: Dict[str, Any] = Depends(require_admin), status: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    items = await db.withdrawals.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return items


@api_router.post("/admin/withdrawals/{wid}/approve")
async def admin_approve_withdrawal(wid: str, _: Dict[str, Any] = Depends(require_admin)):
    w = await db.withdrawals.find_one({"id": wid})
    if not w:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    await db.withdrawals.update_one(
        {"id": wid},
        {"$set": {"status": "approved", "processed_at": now_utc().isoformat()}},
    )
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": w["user_id"],
        "type": "withdrawal",
        "amount": -w["amount"],
        "status": "approved",
        "description": f"Withdrawal approved (₹{w['amount']})",
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(w["user_id"], "withdrawal", "Withdrawal approved", f"₹{int(w['amount'])} has been sent to your account.")
    return {"ok": True}


@api_router.post("/admin/withdrawals/{wid}/reject")
async def admin_reject_withdrawal(wid: str, _: Dict[str, Any] = Depends(require_admin)):
    w = await db.withdrawals.find_one({"id": wid})
    if not w:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    if w["status"] != "pending":
        raise HTTPException(status_code=400, detail="Already processed")
    # Refund the locked amount
    await db.users.update_one({"id": w["user_id"]}, {"$inc": {"wallet_balance": w["amount"]}})
    await db.withdrawals.update_one(
        {"id": wid},
        {"$set": {"status": "rejected", "processed_at": now_utc().isoformat()}},
    )
    await _create_notification(w["user_id"], "withdrawal", "Withdrawal rejected", f"₹{int(w['amount'])} has been refunded to your wallet.")
    return {"ok": True}


@api_router.get("/admin/transactions")
async def admin_transactions(_: Dict[str, Any] = Depends(require_admin)):
    items = await db.transactions.find({}, {"_id": 0}).sort("created_at", -1).to_list(5000)
    return items


@api_router.get("/admin/stats")
async def admin_stats(_: Dict[str, Any] = Depends(require_admin)):
    settings = await get_settings()
    total_users = await db.users.count_documents({"role": "user"})
    paid_users = await db.users.count_documents({"role": "user", "registration_paid": True})
    pending_payouts = await db.withdrawals.count_documents({"status": "pending"})
    total_revenue = paid_users * settings["registration_fee"]
    payout_agg = await db.transactions.aggregate([
        {"$match": {"type": "referral_payout"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_paid_out = payout_agg[0]["total"] if payout_agg else 0
    return {
        "total_users": total_users,
        "paid_users": paid_users,
        "pending_payouts": pending_payouts,
        "total_revenue": total_revenue,
        "total_referral_payouts": total_paid_out,
    }


@api_router.post("/admin/products")
async def admin_create_product(p: ProductCreate, _: Dict[str, Any] = Depends(require_admin)):
    doc = {"id": str(uuid.uuid4()), **p.dict(), "created_at": now_utc().isoformat()}
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    return doc


# ------------------ Admin: User Management ------------------
class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None  # "user" or "admin"
    wallet_balance: Optional[float] = None
    total_earned: Optional[float] = None
    registration_paid: Optional[bool] = None
    upi_id: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    account_holder: Optional[str] = None


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=6)


@api_router.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: str, payload: AdminUserUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    update = {k: v for k, v in payload.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields provided")
    if "email" in update:
        update["email"] = update["email"].lower().strip()
        # Check uniqueness
        clash = await db.users.find_one({"email": update["email"], "id": {"$ne": user_id}})
        if clash:
            raise HTTPException(status_code=400, detail="Email already taken")
    if "role" in update and update["role"] not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    # Prevent demoting the last admin
    if "role" in update and update["role"] == "user" and target.get("role") == "admin":
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last admin")
    await db.users.update_one({"id": user_id}, {"$set": update})
    fresh = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    await _create_notification(user_id, "account", "Account updated", "Your account details were updated by admin.")
    return fresh


@api_router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, payload: AdminPasswordReset, _: Dict[str, Any] = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"id": user_id}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    await _create_notification(user_id, "account", "Password reset", "Your password was reset by admin. Please log in again.")
    return {"ok": True}


@api_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    if target.get("role") == "admin":
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")
    await db.users.delete_one({"id": user_id})
    # Cascade clean: remove their cart items, notifications (keep transactions/orders for audit)
    await db.cart_items.delete_many({"user_id": user_id})
    await db.notifications.delete_many({"user_id": user_id})
    return {"ok": True}


# ------------------ Admin: Settings (Payout Structure) ------------------
class SettingsUpdate(BaseModel):
    registration_fee: Optional[float] = Field(default=None, ge=0)
    payout_l1: Optional[float] = Field(default=None, ge=0)
    payout_l2: Optional[float] = Field(default=None, ge=0)
    payout_l3: Optional[float] = Field(default=None, ge=0)
    directs_required: Optional[int] = Field(default=None, ge=1, le=20)


@api_router.get("/admin/settings")
async def admin_get_settings(_: Dict[str, Any] = Depends(require_admin)):
    return await get_settings()


@api_router.put("/admin/settings")
async def admin_update_settings(payload: SettingsUpdate, _: Dict[str, Any] = Depends(require_admin)):
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


class CartItem(BaseModel):
    product_id: str
    qty: int = Field(gt=0)


class CartRemove(BaseModel):
    product_id: str


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
async def checkout(user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("wallet_frozen"):
        raise HTTPException(status_code=403, detail="Wallet is frozen. Contact support.")
    items = await db.cart_items.find({"user_id": user["id"]}, {"_id": 0}).to_list(1000)
    if not items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    enriched = []
    total = 0.0
    for it in items:
        product = await db.products.find_one({"id": it["product_id"]}, {"_id": 0})
        if not product:
            continue
        line_total = product["price"] * it["qty"]
        total += line_total
        enriched.append({
            "product_id": product["id"],
            "name": product["name"],
            "price": product["price"],
            "image_url": product["image_url"],
            "qty": it["qty"],
            "line_total": line_total,
        })
    if total <= 0:
        raise HTTPException(status_code=400, detail="Cart total invalid")
    fresh = await db.users.find_one({"id": user["id"]})
    if fresh.get("wallet_balance", 0) < total:
        raise HTTPException(status_code=400, detail=f"Insufficient wallet balance. Need ₹{total:.0f}")

    order_id = str(uuid.uuid4())
    order = {
        "id": order_id,
        "user_id": user["id"],
        "items": enriched,
        "total": total,
        "status": "placed",
        "paid_via": "wallet",
        "created_at": now_utc().isoformat(),
    }
    await db.orders.insert_one(order)
    await db.users.update_one({"id": user["id"]}, {"$inc": {"wallet_balance": -total}})
    await db.cart_items.delete_many({"user_id": user["id"]})
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "type": "order",
        "amount": -total,
        "status": "paid",
        "description": f"Order #{order_id[:8]} ({len(enriched)} items)",
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(user["id"], "order", "Order placed!", f"Your order of ₹{int(total)} has been placed.")
    order.pop("_id", None)
    return order


@api_router.get("/orders/me")
async def my_orders(user: Dict[str, Any] = Depends(get_current_user)):
    items = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return items


# ------------------ Notifications ------------------
@api_router.get("/notifications/me")
async def my_notifications(user: Dict[str, Any] = Depends(get_current_user), unread_only: bool = False):
    q = {"user_id": user["id"]}
    if unread_only:
        q["read"] = False
    items = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    return items


@api_router.post("/notifications/me/read-all")
async def read_all_notifications(user: Dict[str, Any] = Depends(get_current_user)):
    await db.notifications.update_many({"user_id": user["id"], "read": False}, {"$set": {"read": True}})
    return {"ok": True}


# ------------------ Phase 1: KYC ------------------
class KYCSubmit(BaseModel):
    full_name: str
    aadhaar: str
    pan: str


@api_router.post("/users/me/kyc")
async def submit_kyc(payload: KYCSubmit, user: Dict[str, Any] = Depends(get_current_user)):
    aadhaar = payload.aadhaar.strip().replace(" ", "")
    pan = payload.pan.strip().upper()
    if len(aadhaar) != 12 or not aadhaar.isdigit():
        raise HTTPException(status_code=400, detail="Aadhaar must be 12 digits")
    if len(pan) != 10:
        raise HTTPException(status_code=400, detail="PAN must be 10 characters")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "kyc_status": "pending",
            "kyc_full_name": payload.full_name.strip(),
            "kyc_aadhaar": aadhaar,
            "kyc_pan": pan,
            "kyc_submitted_at": now_utc().isoformat(),
            "kyc_reject_reason": None,
        }},
    )
    await _create_notification(user["id"], "kyc", "KYC submitted", "Your KYC details are under review.")
    return {"ok": True, "status": "pending"}


@api_router.get("/users/me/kyc")
async def my_kyc(user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "status": user.get("kyc_status", "none"),
        "full_name": user.get("kyc_full_name"),
        "aadhaar": user.get("kyc_aadhaar"),
        "pan": user.get("kyc_pan"),
        "submitted_at": user.get("kyc_submitted_at"),
        "reviewed_at": user.get("kyc_reviewed_at"),
        "reject_reason": user.get("kyc_reject_reason"),
    }


@api_router.get("/admin/kyc")
async def admin_list_kyc(_: Dict[str, Any] = Depends(require_admin), status: Optional[str] = None):
    q: Dict[str, Any] = {"kyc_status": {"$ne": "none"}}
    if status:
        q["kyc_status"] = status
    items = await db.users.find(q, {"_id": 0, "password_hash": 0}).sort("kyc_submitted_at", -1).to_list(2000)
    return items


@api_router.post("/admin/kyc/{user_id}/approve")
async def admin_approve_kyc(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
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


class KYCReject(BaseModel):
    reason: str


@api_router.post("/admin/kyc/{user_id}/reject")
async def admin_reject_kyc(user_id: str, payload: KYCReject, admin: Dict[str, Any] = Depends(require_admin)):
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


# ------------------ Phase 1: User Block / Wallet Admin ------------------
class BlockRequest(BaseModel):
    reason: str


@api_router.post("/admin/users/{user_id}/block")
async def admin_block_user(user_id: str, payload: BlockRequest, admin: Dict[str, Any] = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    await db.users.update_one({"id": user_id}, {"$set": {"is_blocked": True, "block_reason": payload.reason}})
    await _audit_log(admin, "user.block", "user", user_id, {"reason": payload.reason})
    return {"ok": True}


@api_router.post("/admin/users/{user_id}/unblock")
async def admin_unblock_user(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    await db.users.update_one({"id": user_id}, {"$set": {"is_blocked": False, "block_reason": None}})
    await _audit_log(admin, "user.unblock", "user", user_id)
    return {"ok": True}


class WalletAdjust(BaseModel):
    amount: float = Field(gt=0)
    type: str
    reason: str


@api_router.post("/admin/users/{user_id}/wallet")
async def admin_wallet_adjust(user_id: str, payload: WalletAdjust, admin: Dict[str, Any] = Depends(require_admin)):
    if payload.type not in ("credit", "debit"):
        raise HTTPException(status_code=400, detail="type must be credit or debit")
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    delta = payload.amount if payload.type == "credit" else -payload.amount
    if delta < 0 and target.get("wallet_balance", 0) + delta < 0:
        raise HTTPException(status_code=400, detail="Cannot debit beyond available balance")
    inc = {"wallet_balance": delta}
    if payload.type == "credit":
        inc["total_earned"] = payload.amount
    await db.users.update_one({"id": user_id}, {"$inc": inc})
    await db.transactions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "type": "admin_adjust",
        "amount": delta,
        "status": "credited" if delta > 0 else "debited",
        "description": f"Admin {payload.type}: {payload.reason}",
        "created_at": now_utc().isoformat(),
    })
    await _create_notification(user_id, "wallet", f"Wallet {payload.type}ed by ₹{int(payload.amount)}", payload.reason)
    await _audit_log(admin, f"wallet.{payload.type}", "user", user_id, {"amount": payload.amount, "reason": payload.reason})
    return {"ok": True}


@api_router.post("/admin/users/{user_id}/wallet/freeze")
async def admin_wallet_freeze(user_id: str, admin: Dict[str, Any] = Depends(require_admin)):
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


class TxnStatusUpdate(BaseModel):
    status: str


@api_router.patch("/admin/transactions/{txn_id}")
async def admin_update_txn_status(txn_id: str, payload: TxnStatusUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    txn = await db.transactions.find_one({"id": txn_id})
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await db.transactions.update_one({"id": txn_id}, {"$set": {"status": payload.status}})
    await _audit_log(admin, "txn.status", "transaction", txn_id, {"status": payload.status})
    return {"ok": True}


@api_router.post("/admin/transactions/{txn_id}/refund")
async def admin_refund_txn(txn_id: str, admin: Dict[str, Any] = Depends(require_admin)):
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


class OrderStatusUpdate(BaseModel):
    status: str


@api_router.patch("/admin/orders/{order_id}/status")
async def admin_update_order_status(order_id: str, payload: OrderStatusUpdate, admin: Dict[str, Any] = Depends(require_admin)):
    if payload.status not in ("placed", "shipped", "delivered", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    prev_status = order.get("status")
    await db.orders.update_one({"id": order_id}, {"$set": {"status": payload.status}})
    if payload.status == "cancelled" and prev_status != "cancelled":
        await db.users.update_one({"id": order["user_id"]}, {"$inc": {"wallet_balance": order["total"]}})
        await db.transactions.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": order["user_id"],
            "type": "refund",
            "amount": order["total"],
            "status": "credited",
            "description": f"Order #{order_id[:8]} cancelled - refund",
            "created_at": now_utc().isoformat(),
        })
        await _create_notification(order["user_id"], "order", "Order cancelled", f"₹{int(order['total'])} refunded to your wallet.")
    else:
        await _create_notification(order["user_id"], "order", f"Order {payload.status}", f"Your order is now {payload.status}.")
    await _audit_log(admin, "order.status", "order", order_id, {"status": payload.status, "prev": prev_status})
    return {"ok": True}


# ------------------ Phase 1: Audit Log ------------------
@api_router.get("/admin/audit-logs")
async def admin_audit_logs(_: Dict[str, Any] = Depends(require_admin), limit: int = 200):
    items = await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return items


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
        {"$match": {"type": "registration_fee"}},
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
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "name": "Admin",
            "email": ADMIN_EMAIL.lower(),
            "password_hash": hash_password(ADMIN_PASSWORD),
            "phone": None,
            "role": "admin",
            "admin_role": "super_admin",
            "referral_code": "ADMIN001",
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
        logger.info("Admin user seeded")
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


@app.on_event("startup")
async def on_startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("referral_code", unique=True)
    await db.users.create_index("sponsor_id")
    await seed_admin()
    await seed_products()


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


# Include router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
