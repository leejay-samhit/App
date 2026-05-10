"""FastAPI APIRouter modules.

Each submodule defines a `router` (an APIRouter) which is registered in
server.py via `app.include_router(router, prefix="/api")`.

Logical groups:
  - branding         : public branding + super-admin theme controls
  - notifications    : per-user notification list / mark-all-read
  - products_public  : public product catalog (read-only)

More groups (auth, payments, withdrawals, admin, services, vendor,
distributor, tickets, etc.) will be migrated incrementally.
"""
