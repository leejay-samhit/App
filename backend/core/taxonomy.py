"""Product taxonomy normaliser — Jun-2026.

Two field shapes for the same idea had drifted apart:

* the product editor and `ProductCreate` speak `sub_category`
* every customer-facing query (rails, cascade browse, recharge plans)
  reads `subcategory`

so a vendor could file an item under "Essentials → Rice" and the product
page's "More in …" rail would still fall back to the WHOLE category, which
is exactly what the owner reported. We mirror the two keys on every write.

The same hook stamps the Recharge tags. The operator list IS the Recharge
sub-category tree (see routes/recharge.py), so a plan filed under "Airtel"
can have its `recharge_kind` / `recharge_network` derived instead of asking
the vendor to retype what he already picked. Only the circle (`recharge_state`)
is a genuine extra choice, and the editor asks for it.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from core.db import db


def _clean(v: Any) -> str:
    return str(v or "").strip()


async def normalize_product_taxonomy(
    fields: Dict[str, Any],
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return `fields` with the taxonomy keys squared up.

    Safe to call on a create payload (pass `existing=None`) or on a partial
    update (pass the stored product so a category-only edit still resolves).
    """
    base = existing or {}
    sent_sub = "subcategory" in fields or "sub_category" in fields
    sub = (
        _clean(fields.get("subcategory"))
        or _clean(fields.get("sub_category"))
        or (_clean(base.get("subcategory")) or _clean(base.get("sub_category"))
            if not sent_sub else "")
    )
    if sub:
        fields["subcategory"] = sub
        fields["sub_category"] = sub
    elif sent_sub:
        # Nov-2026 BUGFIX — an EXPLICIT clear must wipe BOTH spellings.
        # The product carries `subcategory` and `sub_category`; clearing only
        # the one the client happened to send left the other in place, so the
        # product stayed listed under its old sub-category.
        fields["subcategory"] = ""
        fields["sub_category"] = ""

    category = _clean(fields.get("category")) or _clean(base.get("category"))

    # Nov-2026 — the sub-category must belong to the selected main category.
    # When the admin tree knows children for this category, a sub-category
    # from somewhere else (typically left over from a previous category) is
    # dropped instead of being saved. Categories without a managed child list
    # keep accepting free-form sub-categories.
    if sub and category:
        parent = await db.shop_categories.find_one(
            {"name": {"$regex": f"^{re.escape(category)}$", "$options": "i"}},
            {"_id": 0, "id": 1},
        )
        if parent:
            kids = await db.shop_categories.find(
                {"parent_id": parent["id"]}, {"_id": 0, "name": 1},
            ).to_list(500)
            names = {(k.get("name") or "").strip().lower() for k in kids}
            if names and sub.strip().lower() not in names:
                sub = ""
                fields["subcategory"] = ""
                fields["sub_category"] = ""

    if not category or category.lower() != "recharge":
        return fields

    # A Recharge plan: resolve the operator the vendor picked.
    if sub:
        opt = await db.recharge_options.find_one(
            {"group": "network", "name": {"$regex": f"^{re.escape(sub)}$", "$options": "i"}},
            {"_id": 0, "kind": 1, "slug": 1},
        )
        if opt:
            fields["recharge_kind"] = opt["kind"]
            fields["recharge_network"] = opt["slug"]
        else:
            # Could be the group row itself ("Mobile Recharge" / "DTH TV …").
            grp = await db.shop_categories.find_one(
                {"recharge_group": "kind", "name": {"$regex": f"^{re.escape(sub)}$", "$options": "i"}},
                {"_id": 0, "recharge_kind": 1},
            )
            if grp:
                fields["recharge_kind"] = grp.get("recharge_kind")
    if not fields.get("recharge_kind") and not base.get("recharge_kind"):
        fields.setdefault("recharge_kind", "mobile")
    # "" means "every circle" — store None so the plan query's
    # missing-state branch picks it up.
    if "recharge_state" in fields and not _clean(fields.get("recharge_state")):
        fields["recharge_state"] = None
    return fields
