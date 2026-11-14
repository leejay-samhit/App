/**
 * fetchAllPages — walk a paginated list endpoint until the server says there
 * is nothing left.
 *
 * Nov 2026. Several screens used to ask for ONE page with a big `limit`
 * (`/admin/products?limit=500`, `/products?limit=240`) and silently showed
 * only that slice — so a 1,500-SKU catalogue looked like 240 or 300 products
 * and the admin could not find the rest. Every one of those screens now walks
 * the pages instead.
 *
 * The walk is bounded by `maxItems` so a 100k catalogue can never exhaust a
 * phone's memory; callers that need true unlimited browsing use numbered
 * pages (see the admin/vendor product grids) rather than loading everything.
 */
import { api } from "./api";

export async function fetchAllPages<T = any>(opts: {
  path: string;
  params?: Record<string, any>;
  pageSize?: number;
  maxItems?: number;
  onProgress?: (loaded: number, total: number) => void;
}): Promise<{ items: T[]; total: number; truncated: boolean }> {
  const { path, params = {}, pageSize = 250, maxItems = 20000, onProgress } = opts;
  const out: T[] = [];
  const seen = new Set<string>();
  let offset = 0;
  let total = 0;

  // Hard page ceiling as a second safety net against a server that keeps
  // reporting has_more (a bad filter, a clock skew) — never an infinite loop.
  for (let page = 0; page < 400; page++) {
    const { data } = await api.get<any>(path, {
      params: { ...params, limit: pageSize, offset },
    });
    const batch: any[] = Array.isArray(data) ? data : (data?.items || data?.products || []);
    total = Number(data?.total ?? batch.length);

    for (const row of batch) {
      // De-dupe defensively: a concurrent insert can shift the window and
      // repeat a row across two pages.
      const key = row?.id;
      if (key && seen.has(key)) continue;
      if (key) seen.add(key);
      out.push(row);
    }
    onProgress?.(out.length, total);

    const hasMore = Array.isArray(data)
      ? batch.length >= pageSize
      : Boolean(data?.has_more);
    offset += pageSize;
    if (!hasMore || batch.length === 0 || out.length >= maxItems) {
      return { items: out, total: total || out.length, truncated: out.length >= maxItems && hasMore };
    }
  }
  return { items: out, total: total || out.length, truncated: true };
}
