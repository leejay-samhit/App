"""Super-password and Danger-PIN helpers (admin destructive-action gate)."""
from typing import Optional
from fastapi import HTTPException

from .db import db
from .security import verify_password

# ---- Super Password ----
SUPER_PWD_SYMBOLS = "!@#$%^&*()_+-=[]{};:'\",.<>/?\\|"
SUPER_PWD_FORMAT_DESC = (
    "Must be exactly 10 characters: 1 digit, 3 uppercase letters, "
    "2 symbols (!@#$%^&*()_+-=[]{};:'\",.<>/?\\|), and 4 lowercase letters."
)


def validate_super_password_format(pwd: str) -> None:
    if not isinstance(pwd, str) or len(pwd) != 10:
        raise HTTPException(status_code=400, detail=f"Super password format invalid. {SUPER_PWD_FORMAT_DESC}")
    digits = sum(1 for c in pwd if c.isdigit())
    uppers = sum(1 for c in pwd if c.isupper())
    lowers = sum(1 for c in pwd if c.islower())
    syms = sum(1 for c in pwd if c in SUPER_PWD_SYMBOLS)
    other = len(pwd) - (digits + uppers + lowers + syms)
    if not (digits == 1 and uppers == 3 and lowers == 4 and syms == 2 and other == 0):
        raise HTTPException(status_code=400, detail=f"Super password format invalid. {SUPER_PWD_FORMAT_DESC}")


async def get_super_password_hash() -> Optional[str]:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "super_password_hash": 1})
    return (doc or {}).get("super_password_hash")


async def verify_super_password(provided: str) -> bool:
    if not provided:
        return False
    h = await get_super_password_hash()
    if not h:
        return False
    try:
        return verify_password(provided, h)
    except Exception:
        return False


# ---- Danger PIN ----
DANGER_PIN_FORMAT_DESC = "PIN must be exactly 6 digits (0–9)."


def validate_danger_pin_format(pin: str) -> None:
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isdigit():
        raise HTTPException(status_code=400, detail=f"Invalid PIN format. {DANGER_PIN_FORMAT_DESC}")


async def get_danger_pin_hash() -> Optional[str]:
    doc = await db.settings.find_one({"id": "global"}, {"_id": 0, "danger_pin_hash": 1})
    return (doc or {}).get("danger_pin_hash")


async def verify_danger_pin(provided: str) -> bool:
    if not provided:
        return False
    h = await get_danger_pin_hash()
    if not h:
        return False
    try:
        return verify_password(provided, h)
    except Exception:
        return False
