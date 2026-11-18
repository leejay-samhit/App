"""Admin-editable legal pages: Contact Us, Refund/Cancellation, Privacy
Policy, Terms & Conditions.

Stored in MongoDB collection `legal_pages` with shape:
    { kind, content_text, updated_at, updated_by }
where `kind` ∈ {"privacy", "terms", "refund", "contact_us"}.

The frontend renders the text as plain paragraphs split on blank lines.
Lines starting with `## ` are rendered as headings — keeps editing simple
without requiring a rich-text editor.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import db
from core.security import require_admin  # noqa: F401
from core.utils import now_utc


router = APIRouter()

VALID_KINDS = {"privacy", "terms", "refund", "contact_us", "about"}

# Sensible defaults used when the admin hasn't customized a page yet.
DEFAULTS: Dict[str, str] = {
    "privacy": (
        "## Privacy Policy\n\n"
        "We respect your privacy. This page describes what data we collect, "
        "how we use it, and your choices.\n\n"
        "## 1. Information we collect\n\n"
        "Account details (name, email, mobile), KYC documents for withdrawals, "
        "transaction history, and device information.\n\n"
        "## 2. How we use your data\n\n"
        "To verify your identity, process payments, prevent fraud, and send "
        "transactional notifications.\n\n"
        "## 3. Your rights\n\n"
        "You can request a copy of your data, correct inaccuracies, or delete "
        "your account by contacting support."
    ),
    "terms": (
        "## Terms & Conditions\n\n"
        "By using this platform you agree to the terms below.\n\n"
        "## 1. Eligibility\n\n"
        "You must be 18+ to register. One account per individual.\n\n"
        "## 2. Referral programme\n\n"
        "Rewards are earned only after a referral completes the registration "
        "and pays the joining fee. We reserve the right to clawback rewards "
        "earned through fraudulent referrals.\n\n"
        "## 3. Withdrawals\n\n"
        "Approved KYC and minimum balance are required. Settlement is via "
        "UPI/IMPS to the bank account on file."
    ),
    "refund": (
        "## Refund & Cancellation Policy\n\n"
        "## 1. Registration fee\n\n"
        "The joining fee is non-refundable once the account is activated. If "
        "payment was deducted but activation failed, please contact support "
        "within 7 days for a full refund.\n\n"
        "## 2. Service bookings\n\n"
        "Refunds for service bookings are at the provider's discretion. The "
        "platform fee is non-refundable unless the booking is cancelled "
        "before the provider accepts.\n\n"
        "## 3. Shop orders\n\n"
        "Defective items can be returned within 7 days of delivery for a "
        "full refund, less shipping."
    ),
    "contact_us": (
        "## Contact Us\n\n"
        "We're here to help.\n\n"
        "## Support\n\n"
        "Email: support@example.com\n"
        "Phone: +91 90000 00000\n"
        "Hours: Mon–Sat, 10am to 7pm IST\n\n"
        "## Grievance officer\n\n"
        "For grievances under the IT Act, please email the support address "
        "above and include the word \"Grievance\" in the subject. We respond "
        "within 30 days."
    ),
    "about": (
        "## Who we are\n\n"
        "Slangcart is a neighbourhood commerce platform. Customers shop from "
        "verified local vendors, book trusted service professionals nearby, "
        "and grow a referral network that earns rewards in the in-app "
        "wallet.\n\n"
        "## What we offer\n\n"
        "A location-aware shop that only shows vendors who actually deliver "
        "to your pincode.\n"
        "A services marketplace of verified local professionals with clear "
        "pricing and coverage areas.\n"
        "A reward wallet with transparent earnings history and "
        "admin-reviewed withdrawals to UPI or bank.\n\n"
        "## Our principles\n\n"
        "Every vendor, service provider and member is admin-reviewed before "
        "going live.\n"
        "No guaranteed income — every reward tier is disclosed inside the "
        "app.\n"
        "Full KYC before any withdrawal is released.\n"
        "No forced purchases and no mandatory recruitment.\n\n"
        "## Reach us\n\n"
        "Use Contact us inside the app to raise a support ticket — we reply "
        "within 48 hours."
    ),
}


class LegalUpdate(BaseModel):
    content_text: str = Field(..., min_length=10, max_length=50000)


async def ensure_indexes() -> None:
    """One row per kind, forever.

    Older builds allowed two simultaneous upserts to create duplicate rows
    for the same kind; the readers use find_one() and could then keep
    showing the older copy after a save. Keep the newest copy of each kind
    and make repeats impossible.
    """
    keep: Dict[str, Any] = {}
    dup_ids = []
    async for d in db.legal_pages.find(
        {"superseded": {"$ne": True}}, {"kind": 1, "updated_at": 1},
    ):
        k = d.get("kind")
        prev = keep.get(k)
        if prev is None or (d.get("updated_at") or "") > (prev.get("updated_at") or ""):
            if prev is not None:
                dup_ids.append(prev["_id"])
            keep[k] = d
        else:
            dup_ids.append(d["_id"])
    if dup_ids:
        # Nov-2026 — a boot must never hard-delete admin-authored content. The
        # stale copies are retired instead: `kind` is renamed out of the way so
        # the unique index can still build, and the readers skip them. The
        # explicit admin reset endpoint is the only thing that deletes.
        await db.legal_pages.update_many(
            {"_id": {"$in": dup_ids}},
            {"$set": {"superseded": True}, "$rename": {"kind": "superseded_kind"}},
        )
    try:
        await db.legal_pages.create_index(
            "kind", unique=True,
            partialFilterExpression={"kind": {"$exists": True, "$type": "string"}},
        )
    except Exception:
        pass


@router.get("/legal/{kind}")
async def get_legal_page(kind: str):
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=404, detail="Unknown legal page")
    doc = await db.legal_pages.find_one({"kind": kind, "superseded": {"$ne": True}}, {"_id": 0})
    if not doc:
        return {
            "kind":         kind,
            "content_text": DEFAULTS[kind],
            "is_default":   True,
            "updated_at":   None,
        }
    doc["is_default"] = False
    return doc


@router.get("/admin/legal")
async def list_legal_pages(_: Dict[str, Any] = Depends(require_admin)):
    out = []
    for kind in sorted(VALID_KINDS):
        doc = await db.legal_pages.find_one({"kind": kind, "superseded": {"$ne": True}}, {"_id": 0})
        if doc:
            doc["is_default"] = False
            out.append(doc)
        else:
            out.append({
                "kind":         kind,
                "content_text": DEFAULTS[kind],
                "is_default":   True,
                "updated_at":   None,
            })
    return {"items": out}


@router.put("/admin/legal/{kind}")
async def upsert_legal_page(
    kind: str,
    payload: LegalUpdate,
    admin: Dict[str, Any] = Depends(require_admin),
):
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=404, detail="Unknown legal page")
    now_iso = now_utc().isoformat()
    update_doc = {
        "kind":         kind,
        "content_text": payload.content_text.strip(),
        "updated_at":   now_iso,
        "updated_by":   admin.get("email") or admin.get("id"),
    }
    await db.legal_pages.update_one(
        {"kind": kind, "superseded": {"$ne": True}}, {"$set": update_doc}, upsert=True
    )
    return {"ok": True, "kind": kind, "updated_at": now_iso}


@router.delete("/admin/legal/{kind}")
async def reset_legal_page(
    kind: str,
    _: Dict[str, Any] = Depends(require_admin),
):
    """Delete the custom copy so the page falls back to the system default
    (and the editor's 'using system default' banner comes back)."""
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=404, detail="Unknown legal page")
    await db.legal_pages.delete_one({"kind": kind})
    return {"ok": True, "kind": kind, "is_default": True}
