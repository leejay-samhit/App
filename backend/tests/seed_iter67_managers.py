"""Seed one admin account per scoped manager role (preview DB only).

Run: cd /app/backend && python tests/seed_iter67_managers.py
Password for every account: Manager@123
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import db  # noqa: E402
from core.password_recovery import password_fields  # noqa: E402
from core.utils import now_utc  # noqa: E402

ROLES = ["products_manager", "layout_manager", "order_manager", "vendor_service_manager"]
PASSWORD = "Manager@123"


async def main():
    for role in ROLES:
        email = f"{role.replace('_', '')}@test.com"
        existing = await db.users.find_one({"email": email})
        fields = {
            **password_fields(PASSWORD),
            "role": "admin",
            "admin_role": role,
            "is_active": True,
            "is_blocked": False,
            "registration_paid": True,
            "approval_status": "approved",
        }
        if existing:
            await db.users.update_one({"id": existing["id"]}, {"$set": fields})
            print(f"updated {email} -> {role}")
            continue
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "name": role.replace("_", " ").title(),
            "email": email,
            "phone": "",
            "referral_code": uuid.uuid4().hex[:8].upper(),
            "wallet_balance": 0,
            "total_earned": 0,
            "created_at": now_utc().isoformat(),
            **fields,
        })
        print(f"created {email} -> {role}")


asyncio.run(main())
