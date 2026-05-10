"""Core shared utilities for the backend.
Provides: db handle, config constants, security/auth dependencies, and small helpers.

Migration plan:
  Phase 2A (current): Extract foundational utilities here. server.py imports from these.
  Phase 2B (future): Extract route groups (auth, distributor, services, shop, payments) into
                     /app/backend/routes/*.py files using FastAPI APIRouter.
"""
