"""Password recovery copy — Sep 2026 (owner-mandated exception).

Passwords stay bcrypt-hashed for LOGIN (that path is untouched). On top of
that, every password we set is also stored as a Fernet-encrypted copy so a
super-admin can read a customer's password back when they call support —
explicitly requested by the app owner.

Security rules that keep this as narrow as possible:
  • the key lives only in backend/.env (never in the Expo bundle),
  • the ciphertext is projected out of every list / detail response,
  • only `super_admin` can decrypt, and every read is written to audit_logs,
  • accounts that were created before this feature have no recoverable copy —
    the API answers 409 and the UI offers "Reset & reveal" instead.
"""
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

FIELD = "password_recovery_ciphertext"


def _fernet() -> Optional[Fernet]:
    key = os.environ.get("PASSWORD_RECOVERY_FERNET_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except Exception:
        logger.error("PASSWORD_RECOVERY_FERNET_KEY is invalid — password reveal disabled")
        return None


def encrypt_password(plain: str) -> Optional[str]:
    """Ciphertext for the recoverable copy, or None when unavailable.

    Never raises: a missing key must not stop a signup or a reset.
    """
    f = _fernet()
    if not f or not plain:
        return None
    try:
        return f.encrypt(plain.encode("utf-8")).decode("ascii")
    except Exception as e:
        logger.warning(f"password recovery encrypt failed: {e}")
        return None


def decrypt_password(token: str) -> str:
    f = _fernet()
    if not f:
        raise ValueError("recovery key not configured")
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError, TypeError) as e:
        raise ValueError("not recoverable") from e


def password_fields(plain: str) -> dict:
    """The $set payload for ANY password write — hash + recoverable copy."""
    from core.security import hash_password
    out = {"password_hash": hash_password(plain)}
    enc = encrypt_password(plain)
    if enc:
        out[FIELD] = enc
    return out


def generate_password(length: int = 12) -> str:
    """Human-shareable but strong temporary password."""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(length - 2))
    return f"{core}@{secrets.choice(string.digits)}"
