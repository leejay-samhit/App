"""Delivery-charge engine — the ONE place delivery pricing is computed.

Rules (all admin-configurable in Admin → Settings, per-vendor overrides on
the vendor document, per-product override on the product):

* A charge is computed **per seller** from that seller's own item subtotal.
* A seller's items ship free once their subtotal reaches the free-delivery
  threshold.
* A multi-seller cart is NOT charged the full sum: the cart total is capped
  at `delivery_cart_max` so a customer never pays duplicate delivery.
* Any product marked `free_delivery` makes its seller's slice free.

The returned breakdown carries both the uncapped per-seller charge and the
final allocated amount, so the order document and the treasury both record
exactly what the customer paid.
"""
from typing import Any, Dict, List, Optional


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def vendor_delivery_rule(vendor: Optional[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, float]:
    """Effective rule for one seller: their own override, else the platform
    default."""
    vendor = vendor or {}
    flat = vendor.get("delivery_charge_flat")
    threshold = vendor.get("delivery_free_threshold")
    return {
        "flat": max(0.0, _num(flat if flat not in (None, "") else settings.get("delivery_charge_flat"), 0.0)),
        "free_above": max(0.0, _num(
            threshold if threshold not in (None, "") else settings.get("delivery_free_threshold"), 0.0,
        )),
    }


def compute_cart_delivery(
    vendor_slices: List[Dict[str, Any]],
    settings: Dict[str, Any],
    vendors_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Price delivery for a whole cart.

    `vendor_slices` — one entry per seller:
        {"vendor_key": str, "vendor_id": str | None, "subtotal": float,
         "free_delivery": bool}

    Returns::

        {
          "total": 30.0,              # what the customer pays for delivery
          "uncapped_total": 60.0,     # sum before the cart cap
          "cart_max": 40.0,
          "capped": True,
          "per_vendor": {vendor_key: {"charge": .., "raw_charge": ..,
                                      "free": bool, "reason": str}},
        }
    """
    enabled = bool(settings.get("delivery_charge_enabled", True))
    cart_max = max(0.0, _num(settings.get("delivery_cart_max"), 0.0))
    vendors_by_id = vendors_by_id or {}

    per_vendor: Dict[str, Dict[str, Any]] = {}
    raw_total = 0.0

    for slice_ in vendor_slices:
        key = slice_["vendor_key"]
        subtotal = round(_num(slice_.get("subtotal")), 2)
        if not enabled:
            per_vendor[key] = {"charge": 0.0, "raw_charge": 0.0, "free": True, "reason": "delivery_disabled"}
            continue
        if slice_.get("free_delivery"):
            per_vendor[key] = {"charge": 0.0, "raw_charge": 0.0, "free": True, "reason": "free_delivery_product"}
            continue
        rule = vendor_delivery_rule(vendors_by_id.get(slice_.get("vendor_id") or ""), settings)
        if rule["free_above"] > 0 and subtotal >= rule["free_above"] - 0.009:
            per_vendor[key] = {
                "charge": 0.0, "raw_charge": 0.0, "free": True,
                "reason": "above_free_threshold", "free_above": rule["free_above"],
            }
            continue
        charge = round(rule["flat"], 2)
        per_vendor[key] = {
            "charge": charge, "raw_charge": charge, "free": charge <= 0.009,
            "reason": "flat_charge", "free_above": rule["free_above"],
        }
        raw_total = round(raw_total + charge, 2)

    # ── Cart cap. Scale the per-seller charges down proportionally so the
    #    allocated amounts always sum EXACTLY to what the customer pays.
    total = raw_total
    capped = False
    if enabled and cart_max > 0 and raw_total > cart_max + 0.009:
        capped = True
        total = round(cart_max, 2)
        charged_keys = [k for k, v in per_vendor.items() if v["raw_charge"] > 0.009]
        allocated = 0.0
        for i, k in enumerate(charged_keys):
            if i == len(charged_keys) - 1:
                share = round(total - allocated, 2)
            else:
                share = round(total * (per_vendor[k]["raw_charge"] / raw_total), 2)
                allocated = round(allocated + share, 2)
            per_vendor[k]["charge"] = share
            per_vendor[k]["reason"] = "cart_cap_applied"

    return {
        "total": round(total, 2),
        "uncapped_total": round(raw_total, 2),
        "cart_max": cart_max,
        "capped": capped,
        "enabled": enabled,
        "per_vendor": per_vendor,
    }
