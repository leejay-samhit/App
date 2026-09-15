"""THE centralized GST engine — Phase 2 (Jun-2026).

Every screen, invoice, report, export, return and refund calls in here.
No route, no component and no Excel sheet is allowed to do its own GST
arithmetic, which is the only way App, Web, Vendor and Admin can agree to
the paisa.

Tax basis
---------
The whole application works on a **GST-EXCLUSIVE base**: the `base` passed
in is the taxable value and GST is added on top. Where a price is stored
GST-inclusive (POS bills can be), call `split_inclusive()` to strip the tax
FIRST and then feed the resulting base back in — never mix the two.

India splits intra-state GST evenly:  CGST = SGST = GST ÷ 2.
"""
from typing import Any, Dict


def _f(value: Any) -> float:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v != v else v          # NaN guard


def clamp_gst_pct(value: Any) -> float:
    """Legal GST slabs run 0..28 in India; we allow 0..100 but never
    negative or NaN so a typo can't invert the books."""
    pct = _f(value)
    return round(min(max(pct, 0.0), 100.0), 2)


def split_gst(base: Any, pct: Any, *, qty: Any = 1) -> Dict[str, float]:
    """The ONE formula.

        taxable    = base × qty
        total_gst  = taxable × pct ÷ 100
        cgst = sgst = total_gst ÷ 2
        final      = taxable + total_gst
    """
    unit = round(_f(base), 2)
    q = _f(qty) or 1.0
    taxable = round(unit * q, 2)
    p = clamp_gst_pct(pct)
    total_gst = round(taxable * p / 100.0, 2)
    cgst = round(total_gst / 2.0, 2)
    sgst = round(total_gst - cgst, 2)    # keeps cgst+sgst == total_gst exactly
    return {
        "unit_base": unit,
        "qty": round(q, 2),
        "base_amount": taxable,
        "gst_pct": p,
        "cgst_pct": round(p / 2.0, 2),
        "sgst_pct": round(p / 2.0, 2),
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "total_gst": total_gst,
        "final_amount": round(taxable + total_gst, 2),
    }


def split_inclusive(gross: Any, pct: Any, *, qty: Any = 1) -> Dict[str, float]:
    """`gross` already CONTAINS the GST — strip it back to the base and
    return the same shape as `split_gst`."""
    g = round(_f(gross) * (_f(qty) or 1.0), 2)
    p = clamp_gst_pct(pct)
    base = round(g / (1 + p / 100.0), 2) if p > 0 else g
    out = split_gst(base, p, qty=1)
    out["qty"] = round(_f(qty) or 1.0, 2)
    out["final_amount"] = g
    return out


def pricing_block(product: Dict[str, Any]) -> Dict[str, Any]:
    """Full purchase / selling / profit block for one product.

    Purchase side is VENDOR-PRIVATE (see `public_pricing`).  Both sides use
    the same GST-exclusive basis, so profit is always base-to-base and can
    never be skewed by a tax-slab difference.
    """
    purchase_base = round(_f(product.get("purchase_price")), 2)
    purchase = split_gst(purchase_base, product.get("purchase_gst_pct"))
    selling_base = round(_f(product.get("price")), 2)
    selling = split_gst(selling_base, product.get("selling_gst_pct"))
    stock = int(_f(product.get("stock")))
    profit_per_unit = round(selling_base - purchase_base, 2)
    margin_pct = round(profit_per_unit / selling_base * 100.0, 2) if selling_base > 0 else 0.0
    return {
        "purchase": purchase,
        "selling": selling,
        "profit_per_unit": profit_per_unit,
        "margin_pct": margin_pct,
        "stock": stock,
        "potential_stock_profit": round(profit_per_unit * max(stock, 0), 2),
        "has_purchase_price": purchase_base > 0,
        "tax_basis": "gst_exclusive",
    }


PRIVATE_FIELDS = ("purchase_price", "purchase_gst_pct")


def public_pricing(product: Dict[str, Any]) -> Dict[str, Any]:
    """Customer-safe pricing: selling side ONLY.  Purchase price, purchase
    GST, vendor cost and margin are never exposed."""
    selling = split_gst(_f(product.get("price")), product.get("selling_gst_pct"))
    return {"selling": selling, "tax_basis": "gst_exclusive"}


def strip_private(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Remove vendor-private cost fields from a product dict in place-safe
    fashion (returns a copy)."""
    out = dict(doc or {})
    for key in PRIVATE_FIELDS:
        out.pop(key, None)
    out.pop("pricing", None)
    return out
