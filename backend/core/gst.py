"""THE centralized GST engine — Phase 2 (Jun-2026).

Every screen, invoice, report, export, return and refund calls in here.
No route, no component and no Excel sheet is allowed to do its own GST
arithmetic, which is the only way App, Web, Vendor and Admin can agree to
the paisa.

Tax basis
---------
The whole application is **GST-INCLUSIVE** (owner's rule, Sep 2026): the
price a vendor types is the final price, and the CGST/SGST shown is the tax
already contained inside it. GST is NEVER added on top, so the "selling
total" can never differ from the price that was entered, and the customer
always pays exactly the price on the card. `split_gst()` (add-on-top) is kept
for the rare exclusive quote; everything product-facing uses
`split_inclusive()` via `pricing_block()` / `public_pricing()`.

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
    """`gross` already CONTAINS the GST — pull the tax back out of it.

    The returned `final_amount` is ALWAYS exactly the amount passed in (that
    is the whole point: the price the vendor typed is the price the customer
    pays), and `base_amount + total_gst == final_amount` to the paisa.
    """
    q = _f(qty) or 1.0
    unit = round(_f(gross), 2)
    total = round(unit * q, 2)
    p = clamp_gst_pct(pct)
    base = round(total / (1 + p / 100.0), 2) if p > 0 else total
    total_gst = round(total - base, 2)
    cgst = round(total_gst / 2.0, 2)
    sgst = round(total_gst - cgst, 2)
    return {
        "unit_base": round(base / q, 2) if q else base,
        "unit_price": unit,
        "qty": round(q, 2),
        "base_amount": base,
        "gst_pct": p,
        "cgst_pct": round(p / 2.0, 2),
        "sgst_pct": round(p / 2.0, 2),
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "total_gst": total_gst,
        "final_amount": total,
        "inclusive": True,
    }


def pricing_block(product: Dict[str, Any]) -> Dict[str, Any]:
    """Full purchase / selling / cashback / profit block for one product.

    **GST-INCLUSIVE (owner's rule, Sep 2026).** Whatever the vendor types IS
    the final price — GST is never added on top:

        purchase price ₹1,000 @ 18%  →  total stays ₹1,000
                                        base ₹847.46 · CGST ₹76.27 · SGST ₹76.27
        selling  price ₹1,180 @ 18%  →  customer pays ₹1,180 (exactly what
                                        they see on the product page)

    Adding the tax on top is what made the "selling total" differ from the
    price the vendor entered, which is the confusion the owner reported.

    Cashback is EITHER a percentage OR a flat amount — never both. Profit is
    then the plain, real-money margin the vendor keeps:

        profit = selling price − purchase price − cashback
    """
    purchase_gross = round(_f(product.get("purchase_price")), 2)
    purchase = split_inclusive(purchase_gross, product.get("purchase_gst_pct"))
    selling_gross = round(_f(product.get("price")), 2)
    selling = split_inclusive(selling_gross, product.get("selling_gst_pct"))

    cash = cashback_block(product, selling_gross)
    stock = int(_f(product.get("stock")))
    gross_profit = round(selling_gross - purchase_gross, 2)
    profit_per_unit = round(gross_profit - cash["amount"], 2)
    margin_pct = round(profit_per_unit / selling_gross * 100.0, 2) if selling_gross > 0 else 0.0
    return {
        "purchase": purchase,
        "selling": selling,
        "cashback": cash,
        "purchase_total": purchase_gross,
        "selling_total": selling_gross,
        "gross_profit_per_unit": gross_profit,
        "profit_per_unit": profit_per_unit,
        "margin_pct": margin_pct,
        "stock": stock,
        "potential_stock_profit": round(profit_per_unit * max(stock, 0), 2),
        "has_purchase_price": purchase_gross > 0,
        "tax_basis": "gst_inclusive",
    }


def cashback_block(product: Dict[str, Any], selling_gross: Any = None) -> Dict[str, Any]:
    """Cashback the customer earns on one unit.

    EITHER a percentage of the selling price OR a flat rupee amount — never
    both (owner's rule §19: 5% of ₹500 = ₹25, or a flat ₹25, never ₹50). A
    percentage wins when both are somehow set, and the flat amount can never
    exceed the price.
    """
    price = round(_f(selling_gross if selling_gross is not None else product.get("price")), 2)
    pct = round(max(0.0, _f(product.get("cashback_pct"))), 2)
    flat = round(max(0.0, _f(product.get("cashback_flat"))), 2)
    if pct > 0:
        return {
            "mode": "percent",
            "pct": pct,
            "amount": round(price * pct / 100.0, 2),
            "on_price": price,
        }
    if flat > 0:
        amount = round(min(flat, price) if price > 0 else flat, 2)
        return {"mode": "flat", "pct": 0.0, "amount": amount, "on_price": price}
    return {"mode": "none", "pct": 0.0, "amount": 0.0, "on_price": price}


PRIVATE_FIELDS = ("purchase_price", "purchase_gst_pct")


def public_pricing(product: Dict[str, Any]) -> Dict[str, Any]:
    """Customer-safe pricing: selling side ONLY, GST-INCLUSIVE.

    `final_amount` always equals the price on the product card, and the
    CGST/SGST shown is the tax already contained in it. Purchase price,
    purchase GST, vendor cost and margin are never exposed.
    """
    selling = split_inclusive(_f(product.get("price")), product.get("selling_gst_pct"))
    return {
        "selling": selling,
        "cashback": cashback_block(product),
        "tax_basis": "gst_inclusive",
    }


def strip_private(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Remove vendor-private cost fields from a product dict in place-safe
    fashion (returns a copy)."""
    out = dict(doc or {})
    for key in PRIVATE_FIELDS:
        out.pop(key, None)
    out.pop("pricing", None)
    return out
