/**
 * product-preview — a tiny in-memory cache that makes opening a product feel
 * instant.
 *
 * Jun 2026. Tapping a product card pushed /product/[id], which rendered a
 * blank screen with a spinner until GET /products/{id} came back — on a slow
 * connection that read as a white-screen freeze.
 *
 * Every card now drops what it ALREADY knows (name, price, cover image,
 * stock) here right before navigating, so the product screen paints the hero,
 * title and price on the very first frame and only the heavy parts
 * (description, specs, variants, reviews) fade in when the request lands.
 *
 * Deliberately module-level and bounded — it's a render accelerator, never a
 * source of truth. Values are overwritten by the API response.
 */
export type ProductPreview = {
  id: string;
  name: string;
  price: number;
  /** Already-resolved absolute/data URI so the <Image> can load immediately. */
  image?: string;
  stock?: number;
  is_in_stock?: boolean;
  has_variants?: boolean;
};

const MAX_ENTRIES = 60;
const cache = new Map<string, ProductPreview>();

export function setProductPreview(p: ProductPreview) {
  if (!p?.id) return;
  // Re-insert so the most recently viewed items stay at the tail (LRU-ish).
  cache.delete(p.id);
  cache.set(p.id, p);
  if (cache.size > MAX_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest) cache.delete(oldest);
  }
}

export function getProductPreview(id?: string | null): ProductPreview | null {
  if (!id) return null;
  return cache.get(id) || null;
}
