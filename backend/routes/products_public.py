"""Public product catalog routes.
Extracted from server.py during Phase 2B refactor.

Endpoint (mounted at /api by server.py):
  GET /products  — public, returns published products
"""
from __future__ import annotations

from fastapi import APIRouter

from core.db import db

router = APIRouter(tags=["products-public"])


@router.get("/products")
async def list_products():
    items = await db.products.find(
        {"$or": [{"is_published": True}, {"is_published": {"$exists": False}}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(1000)
    return items
