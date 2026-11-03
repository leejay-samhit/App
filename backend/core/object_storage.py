"""Emergent Managed Object Storage helpers (Oct 2026).

Used for server-generated assets (festival artwork). The storage API has no
public URLs, so every read is proxied by our own backend.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

# `or`, not a default= argument: the platform sets this to "" when unset.
STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "slangcart"

_storage_key: str | None = None


def init_storage() -> str:
    """Call once; idempotent. Returns a reusable storage key."""
    global _storage_key
    if _storage_key:
        return _storage_key
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        raise RuntimeError("EMERGENT_LLM_KEY is not configured")
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": key}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def _reset_key() -> None:
    global _storage_key
    _storage_key = None


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload (silently overwrites an existing path)."""
    try:
        key = init_storage()
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data, timeout=120,
        )
        if resp.status_code == 503:
            # Stale storage key — re-init once, then give up.
            _reset_key()
            key = init_storage()
            resp = requests.put(
                f"{STORAGE_URL}/objects/{path}",
                headers={"X-Storage-Key": key, "Content-Type": content_type},
                data=data, timeout=120,
            )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status == 402:
            raise RuntimeError("Object storage is out of credits — top up to upload new artwork.") from e
        raise


def get_object(path: str) -> tuple[bytes, str]:
    """Download. A missing object comes back as 500, not 404."""
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 503:
        _reset_key()
        key = init_storage()
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")
