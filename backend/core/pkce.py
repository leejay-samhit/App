"""PKCE helper — S256 code challenge.

Kept separate so both the Truecaller flow and any future OAuth integration use
exactly the same derivation (Truecaller's token endpoint rejects a mismatch).
"""
import base64
import hashlib


def code_challenge_for(verifier: str) -> str:
    """Base64-url, no padding, SHA-256 of the verifier — the S256 method."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
