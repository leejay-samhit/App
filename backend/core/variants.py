"""Product variants — size / storage options with their own stock & price.

Jun 2026, owner spec:
  • Fashion needs a size selector with **stock per size** and a price that
    can differ per size, using the RIGHT chart for the product type
    (apparel = S-XXL, footwear = UK/EU numbers, trousers = waist inches,
    kids = age, mobiles = RAM/ROM).
  • Customers must not be able to buy a size the vendor doesn't stock, and
    they must see real measurements so they don't order the wrong fit.

Design decisions (confirmed with the owner):
  1. Stock lives on the VARIANT. The product-level `stock` field is kept in
     sync as the sum of active variants, so every existing stock badge,
     low-stock warning, POS screen and "out of stock" filter keeps working
     with zero changes.
  2. Price mode is per product:
       • "extra"    → base price + a per-variant delta (XL = +₹50)
       • "absolute" → the vendor types the full price for each variant
     The product-level `price` becomes the CHEAPEST buyable variant so the
     shop can show "from ₹499" and sorting/filtering stays correct.
  3. Charts are defined HERE (server-side) and exposed over
     GET /api/product-variant-charts, so the vendor app, the admin panel and
     the web build can never drift out of sync.
"""
from typing import Any, Dict, List, Optional, Tuple


def _sizes(*labels: str) -> List[Dict[str, str]]:
    return [{"label": str(x)} for x in labels]


# ── Chart catalogue ──────────────────────────────────────────────────────
# `guide` rows are the measurement table shown in the customer's "Size guide"
# sheet. `columns` names them. Empty guide = no measurement table (e.g. RAM).
CHARTS: Dict[str, Dict[str, Any]] = {
    "apparel": {
        "label": "Apparel (S · M · L · XL)",
        "hint": "T-shirts, shirts, kurtas, dresses, jackets",
        "unit": "in",
        "columns": ["Size", "Chest (in)", "Length (in)", "Shoulder (in)"],
        "options": _sizes("XS", "S", "M", "L", "XL", "XXL", "3XL"),
        "guide": [
            ["XS", "34", "26", "15.5"],
            ["S", "36", "27", "16.5"],
            ["M", "38", "28", "17.5"],
            ["L", "40", "29", "18.5"],
            ["XL", "42", "30", "19.5"],
            ["XXL", "44", "31", "20.5"],
            ["3XL", "46", "32", "21.5"],
        ],
    },
    "footwear_uk": {
        "label": "Footwear — India / UK sizes",
        "hint": "Shoes, sandals, slippers (adult)",
        "unit": "cm",
        "columns": ["UK / IND", "EU", "Foot length (cm)"],
        "options": _sizes("5", "6", "7", "8", "9", "10", "11", "12"),
        "guide": [
            ["5", "38", "24.1"],
            ["6", "39", "24.8"],
            ["7", "41", "25.7"],
            ["8", "42", "26.7"],
            ["9", "43", "27.3"],
            ["10", "44", "28.0"],
            ["11", "45", "28.8"],
            ["12", "46", "29.6"],
        ],
    },
    "footwear_eu": {
        "label": "Footwear — EU sizes",
        "hint": "Imported / branded footwear",
        "unit": "cm",
        "columns": ["EU", "UK / IND", "Foot length (cm)"],
        "options": _sizes("38", "39", "40", "41", "42", "43", "44", "45", "46"),
        "guide": [
            ["38", "5", "24.1"],
            ["39", "6", "24.8"],
            ["40", "6.5", "25.2"],
            ["41", "7", "25.7"],
            ["42", "8", "26.7"],
            ["43", "9", "27.3"],
            ["44", "10", "28.0"],
            ["45", "11", "28.8"],
            ["46", "12", "29.6"],
        ],
    },
    "footwear_kids": {
        "label": "Footwear — Kids",
        "hint": "Kids shoes & sandals",
        "unit": "cm",
        "columns": ["Kids UK", "EU", "Foot length (cm)"],
        "options": _sizes("K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12", "K13"),
        "guide": [
            ["K4", "20", "12.7"], ["K5", "21", "13.4"], ["K6", "23", "14.3"],
            ["K7", "24", "15.1"], ["K8", "25", "15.9"], ["K9", "26", "16.7"],
            ["K10", "27", "17.5"], ["K11", "28", "18.3"], ["K12", "30", "19.1"],
            ["K13", "31", "19.9"],
        ],
    },
    "waist_in": {
        "label": "Waist (inches)",
        "hint": "Jeans, trousers, chinos",
        "unit": "in",
        "columns": ["Waist (in)", "Hip (in)", "Inseam (in)"],
        "options": _sizes("28", "30", "32", "34", "36", "38", "40", "42"),
        "guide": [
            ["28", "36", "30"], ["30", "38", "30"], ["32", "40", "31"],
            ["34", "42", "31"], ["36", "44", "32"], ["38", "46", "32"],
            ["40", "48", "32"], ["42", "50", "32"],
        ],
    },
    "kids_age": {
        "label": "Kids — by age",
        "hint": "Kidswear",
        "unit": "in",
        "columns": ["Age", "Height (in)", "Chest (in)"],
        "options": _sizes("0-1y", "1-2y", "2-3y", "3-4y", "4-5y", "6-7y", "8-9y", "10-11y", "12-13y"),
        "guide": [
            ["0-1y", "20-28", "18"], ["1-2y", "28-34", "20"], ["2-3y", "34-38", "21"],
            ["3-4y", "38-41", "22"], ["4-5y", "41-44", "23"], ["6-7y", "45-49", "25"],
            ["8-9y", "50-53", "27"], ["10-11y", "54-57", "29"], ["12-13y", "58-61", "31"],
        ],
    },
    "free_size": {
        "label": "Free size / One size",
        "hint": "Stoles, caps, accessories",
        "unit": "",
        "columns": [],
        "options": _sizes("Free Size"),
        "guide": [],
    },
    "ram_rom": {
        "label": "Mobile — RAM / Storage",
        "hint": "Phones & tablets",
        "unit": "",
        "columns": [],
        "options": _sizes(
            "3GB / 32GB", "4GB / 64GB", "4GB / 128GB", "6GB / 128GB",
            "8GB / 128GB", "8GB / 256GB", "12GB / 256GB", "12GB / 512GB",
        ),
        "guide": [],
    },
    "custom": {
        "label": "Custom list",
        "hint": "Type your own option labels",
        "unit": "",
        "columns": [],
        "options": [],
        "guide": [],
    },
}

VALID_CHARTS = set(CHARTS.keys())
PRICE_MODES = ("extra", "absolute")


def charts_payload() -> Dict[str, Any]:
    """Shape served by GET /api/product-variant-charts."""
    return {
        "price_modes": [
            {"value": "extra", "label": "Base price + extra per option",
             "hint": "Type the base price once, then only the difference (XL = +50)."},
            {"value": "absolute", "label": "Full price per option",
             "hint": "Type the complete selling price for every option."},
        ],
        "charts": [
            {"value": k, **{kk: vv for kk, vv in v.items()}} for k, v in CHARTS.items()
        ],
    }


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def variant_price(v: Dict[str, Any], base_price: float, price_mode: str) -> float:
    """Selling price of one variant."""
    if price_mode == "absolute":
        return round(_f(v.get("price_abs")), 2)
    return round(base_price + _f(v.get("price_extra")), 2)


def normalize_variants(
    raw: Any,
    chart: Any,
    price_mode: Any,
    base_price: float,
) -> Tuple[List[Dict[str, Any]], str, str, Optional[int], Optional[float]]:
    """Clean a variant payload coming from the vendor / admin product form.

    Returns `(variants, chart, price_mode, total_stock, min_price)`.
    `total_stock` / `min_price` are None when the product has NO variants —
    the caller then leaves the product's own `stock` / `price` untouched.
    """
    chart = str(chart or "").strip()
    if chart not in VALID_CHARTS:
        chart = ""
    price_mode = str(price_mode or "extra").strip().lower()
    if price_mode not in PRICE_MODES:
        price_mode = "extra"

    if not isinstance(raw, list) or not raw:
        return [], "", price_mode, None, None

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue          # a size can only appear once per product
        seen.add(key)
        stock = max(0, _i(row.get("stock")))
        item = {
            "id": str(row.get("id") or "").strip() or f"v_{len(out) + 1}_{key.replace(' ', '_').replace('/', '-')}",
            "label": label,
            "sku": str(row.get("sku") or "").strip(),
            "stock": stock,
            "active": bool(row.get("active", True)),
        }
        if price_mode == "absolute":
            item["price_abs"] = round(_f(row.get("price_abs"), base_price), 2)
            item["price_extra"] = 0.0
        else:
            item["price_extra"] = round(_f(row.get("price_extra")), 2)
            item["price_abs"] = 0.0
        item["price"] = variant_price(item, base_price, price_mode)
        out.append(item)

    if not out:
        return [], "", price_mode, None, None

    if not chart:
        chart = "custom"

    active = [v for v in out if v["active"]]
    total_stock = sum(v["stock"] for v in active)
    # Product-level price = cheapest option the customer can actually buy;
    # fall back to the cheapest of ALL options when everything is sold out so
    # the listing never shows ₹0.
    buyable = [v for v in active if v["stock"] > 0] or active or out
    min_price = min(v["price"] for v in buyable)
    return out, chart, price_mode, total_stock, round(min_price, 2)


def apply_variants_to_payload(payload: Dict[str, Any], base_price: float) -> Dict[str, Any]:
    """Mutate a product create/update dict so variants + derived fields agree.

    Safe to call on payloads that carry no variant keys at all: it then
    leaves the document untouched (returns the same dict).
    """
    if not any(k in payload for k in ("variants", "variant_chart", "variant_price_mode")):
        return payload
    variants, chart, mode, total_stock, min_price = normalize_variants(
        payload.get("variants"),
        payload.get("variant_chart"),
        payload.get("variant_price_mode"),
        base_price,
    )
    payload["variants"] = variants
    payload["variant_chart"] = chart
    payload["variant_price_mode"] = mode
    payload["has_variants"] = len(variants) > 0
    if total_stock is not None:
        payload["stock"] = total_stock
    if min_price is not None:
        payload["price"] = min_price
        # Keep the typed base price so "extra" deltas survive an edit.
        payload["base_price"] = round(base_price, 2)
    return payload


def find_variant(product: Dict[str, Any], variant_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Locate a variant by id (or by label, for tolerant clients)."""
    if not variant_id:
        return None
    needle = str(variant_id).strip().lower()
    for v in (product.get("variants") or []):
        if str(v.get("id", "")).lower() == needle or str(v.get("label", "")).strip().lower() == needle:
            return v
    return None


def effective_line_price(product: Dict[str, Any], variant: Optional[Dict[str, Any]]) -> float:
    """Unit price for a cart / order line."""
    if variant:
        p = _f(variant.get("price"))
        if p > 0:
            return round(p, 2)
        base = _f(product.get("base_price"), _f(product.get("price")))
        return variant_price(variant, base, str(product.get("variant_price_mode") or "extra"))
    return round(_f(product.get("price")), 2)
