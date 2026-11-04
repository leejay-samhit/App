/**
 * sanitizeProduct — defensive shape-coercion for a product document.
 *
 * Jun 2026. Products imported from a Shopify CSV→JSON conversion (and from
 * the DeoDap catalogue) do not match the Slangcart schema field-for-field:
 *
 *   images        → array of OBJECTS `{src, position}` instead of strings
 *   sub_features  → a single comma string instead of an array
 *   extra_attrs   → values that are numbers / nested objects
 *   spec_tabs     → missing `rows`, or not an array at all
 *   description   → occasionally an object (HTML body wrapper)
 *   price / stock → numeric strings
 *
 * React Native cannot render an object inside <Text>, and `.map()` /
 * `.startsWith()` on the wrong type throws mid-render — which closed the
 * Android release build the instant a shopper tapped an imported product
 * card.  Every product document is passed through here on arrival so the
 * screen only ever sees the shapes it was written for.  Nothing is
 * dropped that can be salvaged; unusable values become empty.
 */

/** Pull a usable URL out of a string OR a Shopify-style image object. */
export function pickImageUrl(entry: unknown): string {
  if (typeof entry === "string") return entry.trim();
  if (entry && typeof entry === "object") {
    const o = entry as Record<string, unknown>;
    for (const k of ["src", "url", "image_url", "image", "href", "data_url"]) {
      const v = o[k];
      if (typeof v === "string" && v.trim()) return v.trim();
    }
  }
  return "";
}

/** Shopify ships an `Image Position`; honour it, then file order. */
function orderedGallery(images: unknown): string[] {
  if (!Array.isArray(images)) return [];
  const positioned: { pos: number; i: number; url: string }[] = [];
  const plain: { i: number; url: string }[] = [];
  images.forEach((entry, i) => {
    const url = pickImageUrl(entry);
    if (!url) return;
    let pos: number | null = null;
    if (entry && typeof entry === "object") {
      const o = entry as Record<string, unknown>;
      for (const k of ["position", "image_position", "Image Position", "sort_order"]) {
        const n = Number(o[k]);
        if (o[k] !== undefined && o[k] !== null && Number.isFinite(n)) { pos = n; break; }
      }
    }
    if (pos === null) plain.push({ i, url });
    else positioned.push({ pos, i, url });
  });
  positioned.sort((a, b) => (a.pos - b.pos) || (a.i - b.i));
  const all = [...positioned.map((p) => p.url), ...plain.map((p) => p.url)];
  return Array.from(new Set(all));
}

function toText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    for (const k of ["text", "value", "body_html", "body", "html"]) {
      if (typeof o[k] === "string") return o[k] as string;
    }
    return "";
  }
  return "";
}

function toStringArray(v: unknown, splitOn = ","): string[] {
  if (Array.isArray(v)) return v.map(toText).filter(Boolean);
  if (typeof v === "string" && v.trim()) {
    return v.split(splitOn).map((s) => s.trim()).filter(Boolean);
  }
  return [];
}

function toNumber(v: unknown, fallback = 0): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  const n = Number(String(v ?? "").replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(n) ? n : fallback;
}

export function sanitizeProduct<T extends Record<string, any>>(raw: T | null | undefined): T | null {
  if (!raw || typeof raw !== "object") return null;
  const p: Record<string, any> = { ...raw };

  p.name = toText(p.name) || "Product";
  p.image_url = pickImageUrl(p.image_url);
  p.image_data_url = pickImageUrl(p.image_data_url);
  p.images = orderedGallery(p.images);
  p.description = toText(p.description);
  p.brand = toText(p.brand);
  p.category = toText(p.category);
  p.sub_category = toText(p.sub_category);
  p.sub_features = toStringArray(p.sub_features);
  p.price = toNumber(p.price);
  p.stock = toNumber(p.stock);

  // Flat key/value detail rows: values must be printable text.
  const extras = p.extra_attrs;
  const flatExtras: Record<string, string> = {};
  if (extras && typeof extras === "object" && !Array.isArray(extras)) {
    Object.entries(extras).forEach(([k, v]) => {
      const text = toText(v);
      if (text) flatExtras[toText(k) || k] = text;
    });
  } else if (Array.isArray(extras)) {
    extras.forEach((row: any) => {
      const k = toText(row?.key ?? row?.label ?? row?.name);
      const v = toText(row?.value);
      if (k && v) flatExtras[k] = v;
    });
  }
  p.extra_attrs = flatExtras;

  p.spec_tabs = (Array.isArray(p.spec_tabs) ? p.spec_tabs : [])
    .map((t: any) => ({
      name: toText(t?.name),
      rows: (Array.isArray(t?.rows) ? t.rows : [])
        .map((r: any) => ({ label: toText(r?.label), value: toText(r?.value) }))
        .filter((r: any) => r.label || r.value),
    }))
    .filter((t: any) => t.rows.length > 0 || t.name);

  p.whats_in_box = (Array.isArray(p.whats_in_box) ? p.whats_in_box : [])
    .map((b: any) => ({ name: toText(b?.name), image_data_url: pickImageUrl(b?.image_data_url) }))
    .filter((b: any) => b.name || b.image_data_url);

  p.variants = (Array.isArray(p.variants) ? p.variants : []).filter(
    (v: any) => v && typeof v === "object",
  );

  return p as T;
}
