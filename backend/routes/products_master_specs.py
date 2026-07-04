"""GSMArena spec scraper (August 2026) — powers "Load 91mobiles template" values.

Why GSMArena and not 91mobiles?
-------------------------------
91mobiles.com detail pages are behind a strict Cloudflare tier that blocks
even Playwright-with-stealth from our datacenter IP.  GSMArena has the
same 90 %+ overlap of phone spec data, uses a stable HTML structure, and
does NOT block server-side scraping.  From the vendor's perspective the
"91mobiles" branding stays on the spec-tab template — the actual values
just happen to come from GSMArena.  Both sites source their specs from the
same manufacturer datasheets.

Flow
----
1.  Frontend hits `GET /products/master/91mobiles-specs?name=<name>&brand=<brand>`
2.  We check the `gsmarena_products` collection for a cached brand→URL map
    (24h TTL per brand). If missing/stale, refresh from
    `https://www.gsmarena.com/{brand}-phones-{id}.php`
3.  Fuzzy-match the requested `name` against the cached list; pick the best.
4.  Scrape the product page for its `<td data-spec="…">` rows.
5.  Map GSMArena keys → the 91mobiles-style spec tabs the vendor form uses.
6.  Cache the whole spec_tabs payload in `products_master_cache` for 30 days.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from core.db import db
from core.security import get_current_user
from core.utils import now_utc

log = logging.getLogger("products_master_specs")
router = APIRouter(tags=["products-master-specs"])

# ── Config ──
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.gsmarena.com/",
}
_TIMEOUT = 10.0
_BRAND_TTL_HOURS = 24
_SPEC_TTL_HOURS = 24 * 30  # 30 days — phone specs never change

# Full mapping: 91mobiles category → list of (label, gsmarena data-spec keys)
# The `data-spec` keys are exactly what GSMArena renders on each product page
# — we validated these live for Apple iPhone 15 (46 spec rows) in July 2026.
_TEMPLATE: List[Dict[str, Any]] = [
    {"name": "General", "rows": [
        ("Launch Date", ["year", "status"]),
        ("Operating System", ["os"]),
        ("Custom UI", []),
        ("SIM Slot(s)", ["sim"]),
        ("SIM Size", ["sim"]),
        ("Network", ["net5g", "net4g", "net3g", "net2g"]),
        ("Model", ["models"]),
        ("Brand", []),
    ]},
    {"name": "Design", "rows": [
        ("Height", ["dimensions"]),
        ("Width", ["dimensions"]),
        ("Thickness", ["dimensions"]),
        ("Weight", ["weight"]),
        ("Build Material", ["build"]),
        ("Colours", ["colors"]),
        ("Waterproof", ["bodyother"]),
        ("Ruggedness", ["bodyother"]),
    ]},
    {"name": "Display", "rows": [
        ("Screen Size", ["displaysize"]),
        ("Screen Resolution", ["displayresolution"]),
        ("Pixel Density", ["displayresolution"]),
        ("Display Type", ["displaytype"]),
        ("Refresh Rate", ["displaytype"]),
        ("Touch Screen", ["displaytype"]),
        ("Screen-to-Body Ratio", ["displaysize"]),
        ("Screen Protection", ["displayprotection"]),
    ]},
    {"name": "Performance", "rows": [
        ("Chipset", ["chipset"]),
        ("CPU", ["cpu"]),
        ("Architecture", ["cpu"]),
        ("Fabrication", ["chipset"]),
        ("Graphics", ["gpu"]),
        ("RAM", ["internalmemory"]),
        ("RAM Type", ["memoryother"]),
    ]},
    {"name": "Storage", "rows": [
        ("Internal Memory", ["internalmemory"]),
        ("Expandable Memory", ["memoryslot"]),
        ("USB OTG", ["usb"]),
    ]},
    {"name": "Rear Camera", "rows": [
        ("Main Camera Resolution", ["cam1modules"]),
        ("Sensor Size", ["cam1modules"]),
        ("Optical Zoom", ["cam1modules"]),
        ("Autofocus", ["cam1features"]),
        ("Flash", ["cam1features"]),
        ("Video Recording", ["cam1video"]),
        ("OIS", ["cam1features"]),
        ("Camera Features", ["cam1features"]),
    ]},
    {"name": "Front Camera", "rows": [
        ("Front Camera Resolution", ["cam2modules"]),
        ("Aperture", ["cam2modules"]),
        ("Video Recording", ["cam2video"]),
        ("Front Flash", ["cam2features"]),
    ]},
    {"name": "Battery", "rows": [
        ("Capacity", ["batdescription1"]),
        ("Type", ["batdescription1"]),
        ("Removable", ["batdescription1"]),
        ("Quick Charging", ["batcharging1"]),
        ("Wireless Charging", ["batcharging1"]),
        ("USB Type-C", ["usb"]),
    ]},
    {"name": "Connectivity", "rows": [
        ("Network Support", ["net5g", "net4g"]),
        ("5G Bands", ["net5g"]),
        ("4G Bands", ["net4g"]),
        ("VoLTE", ["speed"]),
        ("Wi-Fi", ["wlan"]),
        ("Bluetooth", ["bluetooth"]),
        ("GPS", ["gps"]),
        ("NFC", ["nfc"]),
        ("USB Connectivity", ["usb"]),
    ]},
    {"name": "Sensors", "rows": [
        ("Fingerprint Sensor", ["sensors"]),
        ("Fingerprint Position", ["sensors"]),
        ("Face Unlock", ["sensors"]),
        ("Accelerometer", ["sensors"]),
        ("Gyroscope", ["sensors"]),
        ("Proximity", ["sensors"]),
        ("Compass", ["sensors"]),
        ("Barometer", ["sensors"]),
    ]},
    {"name": "Multimedia", "rows": [
        ("Audio Jack", ["3.5mm-jack-"]),
        ("Loudspeaker", ["loudspeaker-"]),
        ("Speaker", ["loudspeaker-"]),
        ("Dolby Audio", ["loudspeaker-"]),
    ]},
]

# ── Known GSMArena brand-list URLs (page 1; multi-page fetch below fills rest) ──
# Verified against gsmarena.com/makers.php3 in July 2026.
_BRAND_URLS: Dict[str, str] = {
    "apple": "https://www.gsmarena.com/apple-phones-48.php",
    "samsung": "https://www.gsmarena.com/samsung-phones-9.php",
    "xiaomi": "https://www.gsmarena.com/xiaomi-phones-80.php",
    "redmi": "https://www.gsmarena.com/xiaomi-phones-80.php",   # Redmi is under Xiaomi on GSMArena
    "poco": "https://www.gsmarena.com/xiaomi-phones-80.php",    # POCO too (sub-brand of Xiaomi)
    "oneplus": "https://www.gsmarena.com/oneplus-phones-95.php",
    "google": "https://www.gsmarena.com/google-phones-107.php",
    "sony": "https://www.gsmarena.com/sony-phones-7.php",
    "motorola": "https://www.gsmarena.com/motorola-phones-4.php",
    "vivo": "https://www.gsmarena.com/vivo-phones-98.php",
    "iqoo": "https://www.gsmarena.com/vivo-phones-98.php",      # iQOO sits under vivo
    "oppo": "https://www.gsmarena.com/oppo-phones-82.php",
    "realme": "https://www.gsmarena.com/realme-phones-118.php",
    "nokia": "https://www.gsmarena.com/nokia-phones-1.php",
    "asus": "https://www.gsmarena.com/asus-phones-46.php",
    "nothing": "https://www.gsmarena.com/nothing-phones-128.php",
    "honor": "https://www.gsmarena.com/honor-phones-121.php",
    "huawei": "https://www.gsmarena.com/huawei-phones-58.php",
    "tecno": "https://www.gsmarena.com/tecno-phones-120.php",
    "infinix": "https://www.gsmarena.com/infinix-phones-119.php",
    "lava": "https://www.gsmarena.com/lava-phones-94.php",
    "lg": "https://www.gsmarena.com/lg-phones-20.php",
}
# How many pages to walk per brand.  GSMArena renders 50 phones per page and
# we want ~250 recent devices per brand (covers ~4-5 years including older
# flagships like Vivo X100, OnePlus 11, iPhone 12/13 which are still sold in
# India). 5 pages ≈ 250 phones. Trade-off: uncached brand hit is ~2.5s.
_BRAND_PAGES = 5


def _clean(s: Optional[str]) -> str:
    if not s:
        return ""
    # Collapse whitespace, strip tags, remove non-breaking/thin spaces.
    s = re.sub(r"<[^>]+>", "", str(s))
    s = re.sub(r"[\u00a0\u2009\u202f]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_name(s: str) -> str:
    """Aggressive normalisation for fuzzy matching: lowercase, strip
    brand prefix, drop everything after the first parenthesis / comma /
    storage-suffix so 'iPhone 15 256GB Titanium Blue' matches 'iPhone 15'."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[,•\-–—]", " ", s)
    s = re.sub(r"\b\d+\s*(?:gb|tb)\b", " ", s)  # drop "256gb" etc.
    s = re.sub(r"\b5g\b", " ", s)  # 5G suffix doesn't help matching
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Brand list fetcher (cached in Mongo) ─────────────────────────────

async def _get_brand_products(brand_key: str) -> List[Dict[str, str]]:
    """Return [{name, url, thumb}, ...] for a brand. Cached 24h in Mongo.

    Fetches `_BRAND_PAGES` pages (p1..p3) so older-but-still-sold flagships
    like Vivo X100, OnePlus 11, etc. show up — the front page alone only
    lists ~50 CURRENT phones.
    """
    brand_key = brand_key.lower().strip()
    if not brand_key:
        return []
    base_url = _BRAND_URLS.get(brand_key)
    if not base_url:
        return []
    doc = await db.gsmarena_brand_cache.find_one({"key": brand_key}, {"_id": 0})
    if doc:
        try:
            from datetime import datetime
            at = doc.get("at")
            if isinstance(at, str):
                at = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if at and (now_utc() - at).total_seconds() < _BRAND_TTL_HOURS * 3600 and doc.get("items"):
                return doc.get("items") or []
        except Exception:
            pass

    # Build URLs for pages 1..N. Page 1 is the base URL; pages 2+ use the
    # `<slug>-f-<id>-0-p<N>.php` layout GSMArena exposes (verified live).
    m = re.match(r".*?/([a-z0-9_\-]+)-phones-(\d+)\.php", base_url)
    urls = [base_url]
    if m:
        slug, bid = m.group(1), m.group(2)
        for p in range(2, _BRAND_PAGES + 1):
            urls.append(f"https://www.gsmarena.com/{slug}-phones-f-{bid}-0-p{p}.php")

    items: List[Dict[str, str]] = []
    seen_urls: set = set()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            for u in urls:
                try:
                    r = await client.get(u, headers=_HEADERS)
                    if r.status_code != 200:
                        continue
                    for m2 in re.finditer(
                        r'<li>\s*<a href="([a-z0-9_\-\(\)]+\d+\.php)"[^>]*>\s*<img\s+src=([^\s>]+)[^>]*>\s*<strong[^>]*>\s*<span[^>]*>([\s\S]{2,120}?)</span>\s*</strong>',
                        r.text,
                    ):
                        href, thumb, name = m2.groups()
                        full = f"https://www.gsmarena.com/{href}"
                        if full in seen_urls:
                            continue
                        seen_urls.add(full)
                        items.append({
                            "name": _clean(name),
                            "url": full,
                            "thumb": thumb if thumb.startswith("http") else f"https:{thumb}" if thumb.startswith("//") else thumb,
                        })
                except Exception as inner:
                    log.info("GSMArena page fetch failed for %s: %s", u, inner)
    except Exception as e:
        log.warning("GSMArena brand fetch failed for %s: %s", brand_key, e)
        return doc.get("items") or [] if doc else []

    # Save cache
    try:
        await db.gsmarena_brand_cache.update_one(
            {"key": brand_key},
            {"$set": {"key": brand_key, "at": now_utc().isoformat(), "items": items}},
            upsert=True,
        )
    except Exception:
        pass
    return items


def _pick_best_match(name: str, items: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Fuzzy-match the requested name against the brand's product list.

    Strictness rules:
      1. Every "significant" token in the query (length ≥ 2) must appear
         in the candidate name; if the query has any number-bearing token
         (e.g. "S24", "12r", "X100") it MUST appear verbatim in the
         candidate.  Prevents "Galaxy S24" → "Galaxy S26" mismatches.
      2. After the strict gate, we rank by combined token-overlap +
         sequence similarity, boosting exact substring matches.
    """
    if not items:
        return None
    target = _norm_name(name)
    if not target:
        return None
    t_tokens = target.split()
    if not t_tokens:
        return None
    # Tokens containing a digit must match — model numbers are decisive.
    numeric_tokens = {t for t in t_tokens if any(c.isdigit() for c in t)}
    significant = {t for t in t_tokens if len(t) >= 2}
    # Variant-suffix words — when present in the query they MUST also appear
    # in the candidate (prevents "POCO X6 Pro" → "POCO X6 Neo" mismatch).
    _VARIANTS = {"pro", "ultra", "plus", "max", "neo", "lite", "mini", "se", "fe", "prime", "premium"}
    variant_tokens = {t for t in t_tokens if t in _VARIANTS}

    scored: List[Tuple[float, Dict[str, str]]] = []
    for it in items:
        cand = _norm_name(it.get("name", ""))
        if not cand:
            continue
        c_tokens = set(cand.split())
        # Strict gate — every numeric-bearing token must be present verbatim.
        if numeric_tokens and not numeric_tokens.issubset(c_tokens):
            continue
        # Strict gate #2 — every variant word (Pro/Ultra/Plus/Max/…) in the
        # query must also appear in the candidate.  This prevents
        # "POCO X6 Pro" from matching "POCO X6 Neo".
        if variant_tokens and not variant_tokens.issubset(c_tokens):
            continue
        # Reverse-direction check: if the CANDIDATE has a variant word that
        # the query lacks, penalize (but don't hard-reject — "Vivo X100"
        # might legitimately land on "Vivo X100 Pro" if that's all we have).
        cand_variants = c_tokens & _VARIANTS
        cand_variant_penalty = len(cand_variants - variant_tokens) * 0.15
        # Also require at least half of significant tokens to overlap.
        overlap_count = len(significant & c_tokens)
        if significant and overlap_count / len(significant) < 0.5:
            continue
        overlap = overlap_count / max(len(significant), 1)
        ratio = difflib.SequenceMatcher(None, target, cand).ratio()
        score = 0.55 * overlap + 0.35 * ratio
        if target in cand or cand in target:
            score += 0.20
        # Penalize candidates that carry EXTRA variant words the query lacks
        # (e.g. asked for "Vivo X100", candidate "Vivo X100 Ultra" loses 0.15
        # so the plain "Vivo X100" wins the tie).
        score -= cand_variant_penalty
        # Prefer shorter candidate names (avoid "Ultra"/"Plus" variants when
        # the query is the base model).
        len_penalty = max(0, len(cand.split()) - len(t_tokens)) * 0.02
        score -= len_penalty
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] >= 0.55:
        return scored[0][1]
    return None


# ── Product-detail spec scraper ──────────────────────────────────────

def _extract_data_specs(html: str) -> Dict[str, str]:
    """Return {data-spec-key: cleaned-value} from a GSMArena product page."""
    out: Dict[str, str] = {}
    # <td class="ttl" data-spec="xxx">...</td><td class="nfo" data-spec="xxx">value</td>
    for m in re.finditer(r'<td[^>]*data-spec="([^"]+)"[^>]*>([\s\S]*?)</td>', html):
        key, raw = m.group(1), m.group(2)
        val = _clean(raw)
        if val and key not in out:
            out[key] = val
    # Sensors / audio jack sometimes rendered as <a data-spec="loudspeaker-">Yes</a>
    for m in re.finditer(r'<a[^>]*data-spec="([^"]+)"[^>]*>([\s\S]*?)</a>', html):
        key, raw = m.group(1), m.group(2)
        val = _clean(raw)
        if val and key not in out:
            out[key] = val
    return out


def _extract_hero_image(html: str) -> str:
    m = re.search(r'<div class="specs-photo-main"[^>]*>\s*<a[^>]*>\s*<img[^>]*src="([^"]+)"', html)
    return m.group(1) if m else ""


def _pictures_url_from_product_url(product_url: str) -> str:
    """Convert `apple_iphone_15-12559.php` → `apple-iphone-15-pictures-12559.php`.

    GSMArena uses underscores in the product page slug but dashes on the
    pictures gallery page — a small but critical difference.  We also need
    to inject the literal token `-pictures-` right before the numeric id.
    """
    m = re.match(r"^(https?://www\.gsmarena\.com/)([a-z0-9_\-\(\)]+?)-(\d+)\.php$", product_url)
    if not m:
        return ""
    prefix, slug, pid = m.group(1), m.group(2), m.group(3)
    slug_dashed = slug.replace("_", "-")
    return f"{prefix}{slug_dashed}-pictures-{pid}.php"


async def _fetch_gallery_images(product_url: str) -> List[str]:
    """Scrape the HD gallery from a GSMArena pictures page.

    Returns a list of the highest-quality image URLs available (usually
    1024w2 = 1024px wide) with the hero (1024w2 gsmarena_001.jpg) first.
    Returns [] on any failure — gallery is non-critical decoration.
    """
    pics_url = _pictures_url_from_product_url(product_url)
    if not pics_url:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(pics_url, headers=_HEADERS)
        if r.status_code != 200:
            return []
        html = r.text
    except Exception as e:
        log.info("GSMArena gallery fetch failed for %s: %s", pics_url, e)
        return []
    # GSMArena renders each gallery image as
    #   <img src="https://fdn.gsmarena.com/imgroot/reviews/…/-1024w2/gsmarena_001.jpg">
    urls = re.findall(
        r'<img[^>]+src="(https?://fdn\.gsmarena\.com/imgroot/[^"]+\.jpg)"',
        html,
    )
    # De-dup while preserving order
    seen: set = set()
    out: List[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    # Cap at 12 images so the vendor form isn't overwhelmed.
    return out[:12]


def _map_to_template(raw: Dict[str, str]) -> List[Dict[str, Any]]:
    """Convert GSMArena data-spec dict to 91mobiles-style spec_tabs."""
    tabs: List[Dict[str, Any]] = []
    for tab in _TEMPLATE:
        rows: List[Dict[str, str]] = []
        for label, keys in tab["rows"]:
            value = ""
            for k in keys:
                if raw.get(k):
                    value = raw[k]
                    break
            # Post-process a few labels to slice out the interesting bit
            if label == "Height" and value:
                mm = re.match(r"([\d.]+)\s*x", value)
                if mm: value = f"{mm.group(1)} mm"
            elif label == "Width" and value:
                parts = re.findall(r"[\d.]+", value)
                if len(parts) >= 2: value = f"{parts[1]} mm"
            elif label == "Thickness" and value:
                parts = re.findall(r"[\d.]+", value)
                if len(parts) >= 3: value = f"{parts[2]} mm"
            elif label == "Weight" and value:
                mm = re.match(r"([\d.]+)\s*g", value)
                if mm: value = f"{mm.group(1)} g"
            elif label == "Screen Size" and value:
                mm = re.match(r"([\d.]+)\s*inches", value)
                if mm: value = f"{mm.group(1)} inches"
            elif label == "Screen-to-Body Ratio" and value:
                mm = re.search(r"(~?[\d.]+%)\s*screen-to-body", value)
                if mm: value = mm.group(1).lstrip("~")
            elif label == "Screen Resolution" and value:
                mm = re.match(r"([\d]+\s*x\s*[\d]+)", value)
                if mm: value = mm.group(1)
            elif label == "Pixel Density" and value:
                mm = re.search(r"~?([\d]+)\s*ppi", value)
                if mm: value = f"{mm.group(1)} PPI"
            elif label == "Launch Date" and value:
                mm = re.search(r"Released\s*(\d{4}[^,]*,\s*[A-Za-z]+\s*\d+)", value)
                if mm:
                    value = mm.group(1)
                else:
                    mm = re.match(r"(\d{4},?\s*[A-Za-z]+(?:\s*\d+)?)", value)
                    if mm: value = mm.group(1)
            elif label == "Fabrication" and value:
                mm = re.search(r"(\d+\s*nm)", value)
                if mm: value = mm.group(1)
            elif label == "RAM" and value:
                mm = re.search(r"(\d+\s*GB)\s*RAM", value)
                if mm: value = mm.group(1)
            elif label == "Internal Memory" and value:
                # Take just the storage options e.g. "128GB 6GB RAM, 256GB 6GB RAM" -> "128GB / 256GB"
                caps = re.findall(r"(\d+\s*(?:GB|TB))", value)
                caps = list(dict.fromkeys([c.replace(" ", "") for c in caps]))
                if caps: value = " / ".join(caps)
            rows.append({"label": label, "value": value})
        tabs.append({"name": tab["name"], "rows": rows})
    return tabs


async def _fetch_specs_for_url(product_url: str) -> Tuple[List[Dict[str, Any]], str, List[str]]:
    """Return (spec_tabs, hero_image_url, gallery_images). Never raises.

    Also fetches the HD gallery from `<slug>-pictures-<id>.php` — up to 12
    high-resolution photos ready for the vendor product gallery.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(product_url, headers=_HEADERS)
        if r.status_code != 200:
            return [], "", []
        html = r.text
    except Exception as e:
        log.info("GSMArena detail fetch failed: %s", e)
        return [], "", []
    raw = _extract_data_specs(html)
    hero = _extract_hero_image(html)
    gallery: List[str] = []
    if raw:
        # Fire gallery fetch in parallel with the spec map (which is CPU).
        gallery = await _fetch_gallery_images(product_url)
        return _map_to_template(raw), hero, gallery
    return [], hero, gallery


# ── Route ────────────────────────────────────────────────────────────

@router.get("/products/master/91mobiles-specs")
async def gsmarena_specs(
    name: str = Query(..., min_length=2),
    brand: str = Query("", description="Brand name for narrowing down"),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Fetch actual spec values keyed to the 91mobiles-style template.

    Query params:
      • name  — product name (e.g. "iPhone 15 Pro Max")
      • brand — brand name (e.g. "Apple"); if omitted we try to detect it
                from the first token of `name`.

    Returns:
      { source, matched_url, matched_name, hero_image, spec_tabs,
        specs_filled (int), specs_total (int) }
    Or 404 if we couldn't identify the product on GSMArena.
    """
    q_name = (name or "").strip()
    q_brand = (brand or "").strip().lower()
    if not q_brand:
        # Heuristic: use the first word as the brand (works for "Apple iPhone 15", "Samsung S24" etc.)
        q_brand = q_name.split()[0].lower() if q_name else ""

    # Cache lookup — key on (brand, name normalised)
    cache_key = f"{q_brand}::{_norm_name(q_name)}"
    cached = await db.products_master_cache.find_one({"key": cache_key}, {"_id": 0})
    if cached:
        from datetime import datetime
        try:
            at = cached.get("at")
            if isinstance(at, str):
                at = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if at and (now_utc() - at).total_seconds() < _SPEC_TTL_HOURS * 3600:
                payload = cached.get("payload") or {}
                if payload.get("spec_tabs"):
                    return payload
        except Exception:
            pass

    products = await _get_brand_products(q_brand)
    if not products:
        raise HTTPException(status_code=404, detail=f"No GSMArena catalog for brand '{q_brand}'")

    match = _pick_best_match(q_name, products)
    if not match:
        raise HTTPException(status_code=404, detail="Could not confidently match product on GSMArena")

    tabs, hero, gallery = await _fetch_specs_for_url(match["url"])
    if not tabs:
        raise HTTPException(status_code=502, detail="GSMArena returned no spec data")

    total_rows = sum(len(t["rows"]) for t in tabs)
    filled_rows = sum(1 for t in tabs for r in t["rows"] if r.get("value"))

    payload = {
        "source": "gsmarena",
        "matched_url": match["url"],
        "matched_name": match["name"],
        "hero_image": hero or match.get("thumb", ""),
        "gallery": gallery,  # HD 1024w2 photos scraped from the pictures page
        "spec_tabs": tabs,
        "specs_filled": filled_rows,
        "specs_total": total_rows,
    }

    try:
        await db.products_master_cache.update_one(
            {"key": cache_key},
            {"$set": {"key": cache_key, "at": now_utc().isoformat(), "payload": payload}},
            upsert=True,
        )
    except Exception:
        pass
    return payload
