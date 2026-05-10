"""Branding helpers.
Extracted from server.py during Phase 2B refactor.

Provides:
  - get_branding_doc(): fetch (or seed) the canonical branding document.
  - merge_branding(stored): merge a stored partial doc over DEFAULT_BRANDING
    so the API always returns a fully-shaped object.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .config import ALLOWED_TAB_KEYS, DEFAULT_BRANDING
from .db import db


async def get_branding_doc() -> Dict[str, Any]:
    doc = await db.settings.find_one({"id": "branding"}, {"_id": 0})
    if not doc:
        doc = {"id": "branding", **DEFAULT_BRANDING}
        await db.settings.insert_one(doc)
    return doc


def merge_branding(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Merge stored branding over defaults so partial docs always serve a complete object."""
    out: Dict[str, Any] = json.loads(json.dumps(DEFAULT_BRANDING))
    for k, v in stored.items():
        if k == "_id" or k == "id":
            continue
        if k == "colors" and isinstance(v, dict):
            out["colors"].update(v)
        elif k == "tabs" and isinstance(v, list) and v:
            seen = set()
            merged: List[Dict[str, Any]] = []
            for t in v:
                if not isinstance(t, dict):
                    continue
                key = t.get("key")
                if key in ALLOWED_TAB_KEYS and key not in seen:
                    default_t = next((d for d in DEFAULT_BRANDING["tabs"] if d["key"] == key), {})
                    merged.append({
                        "key": key,
                        "label": t.get("label") or default_t.get("label", key.title()),
                        "icon": t.get("icon") or default_t.get("icon", "circle"),
                        "visible": bool(t.get("visible", True)),
                    })
                    seen.add(key)
            for d in DEFAULT_BRANDING["tabs"]:
                if d["key"] not in seen:
                    merged.append(dict(d))
            out["tabs"] = merged
        else:
            out[k] = v
    return out
