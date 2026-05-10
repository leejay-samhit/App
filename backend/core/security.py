"""Auth helpers: password hashing, JWT, FastAPI dependencies."""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import JWT_SECRET, JWT_ALGORITHM
from .db import db

security = HTTPBearer(auto_error=False)


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
    """Restrict an endpoint to specific admin sub-roles (super_admin, manager, support, finance)."""
    async def checker(admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
        sub = admin.get("admin_role") or "super_admin"  # legacy admins default super
        if sub not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires admin role: {' or '.join(allowed)}")
        return admin
    return checker


async def require_admin_not_finance(admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """Block finance role from non-financial admin write actions."""
    sub = admin.get("admin_role") or "super_admin"
    if sub == "finance":
        raise HTTPException(status_code=403, detail="Finance role cannot perform this action — only withdrawals.")
    return admin
