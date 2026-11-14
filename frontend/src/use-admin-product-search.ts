/**
 * useAdminProductSearch — server-side paged product picker data source.
 *
 * Nov 2026. The Shop Layout screen used to download the ENTIRE admin
 * catalogue before the product picker could open (23 sequential requests at
 * 5,700 SKUs), which froze the app with an "app not responding" dialog and
 * showed zero products until every page landed. The picker now queries the
 * server: 100 rows per page, debounced search, append-on-scroll — so it opens
 * instantly whether the shop has 100 products or 1,000,000.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export type PickerProduct = {
  id: string;
  name: string;
  price?: number;
  image_url?: string | null;
  category?: string;
  vendor_id?: string;
  vendor_name?: string;
  is_published?: boolean;
};

const PAGE = 100;

export function useAdminProductSearch(opts: { enabled: boolean; search: string; vendorId?: string }) {
  const { enabled, search, vendorId } = opts;
  const [items, setItems] = useState<PickerProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const seq = useRef(0);
  const [debounced, setDebounced] = useState(search);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchPage = useCallback(async (offset: number) => {
    const params: Record<string, any> = { limit: PAGE, offset };
    if (debounced.trim()) params.q = debounced.trim();
    if (vendorId) params.vendor_id = vendorId;
    const { data } = await api.get<any>("/admin/products", { params });
    const list: PickerProduct[] = Array.isArray(data) ? data : (data?.items || []);
    return {
      list,
      total: Number(Array.isArray(data) ? list.length : (data?.total ?? list.length)),
      hasMore: Array.isArray(data) ? list.length >= PAGE : Boolean(data?.has_more),
    };
  }, [debounced, vendorId]);

  useEffect(() => {
    if (!enabled) return;
    const reqId = ++seq.current;
    setLoading(true);
    fetchPage(0)
      .then((r) => {
        if (reqId !== seq.current) return;
        setItems(r.list);
        setTotal(r.total);
        setHasMore(r.hasMore);
      })
      .catch(() => { if (reqId === seq.current) { setItems([]); setTotal(0); setHasMore(false); } })
      .finally(() => { if (reqId === seq.current) setLoading(false); });
  }, [enabled, fetchPage]);

  const loadMore = useCallback(() => {
    if (loading || loadingMore || !hasMore) return;
    const reqId = seq.current;
    setLoadingMore(true);
    fetchPage(items.length)
      .then((r) => {
        if (reqId !== seq.current) return;
        setItems((cur) => {
          const seen = new Set(cur.map((x) => x.id));
          return [...cur, ...r.list.filter((x) => !seen.has(x.id))];
        });
        setHasMore(r.hasMore);
      })
      .catch(() => { /* the rows already shown stay usable */ })
      .finally(() => setLoadingMore(false));
  }, [loading, loadingMore, hasMore, items.length, fetchPage]);

  return { items, total, loading, loadingMore, hasMore, loadMore };
}
