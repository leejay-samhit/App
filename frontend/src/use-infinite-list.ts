// Generic infinite-scroll hook for any GET endpoint that supports
// ?limit&offset pagination and returns a flat array of items.
//
// Usage:
//   const list = useInfiniteList<Txn>("/transactions/me", { pageSize: 20 });
//   <FlatList
//     data={list.items}
//     onEndReached={list.loadMore}
//     onEndReachedThreshold={0.5}
//     refreshing={list.refreshing}
//     onRefresh={list.refresh}
//     ListFooterComponent={list.loadingMore ? <Spinner/> : null}
//   />
//
// Why a flat array (not envelope) from the backend?
//   • Keeps endpoints backward-compatible — same response shape with/without
//     pagination params.
//   • `has_more` is inferred client-side: if the page came back with fewer
//     items than `pageSize`, we know we hit the end.
// This trade-off is correct for our scale (≤100k rows per collection).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export type InfiniteListOptions<TQuery extends object = object> = {
  pageSize?: number;
  /** Additional query params merged into every request. Re-evaluated on every
   *  render so consumers can pass derived state (e.g. status tab, search q). */
  params?: TQuery;
  /** Disable network calls until something is ready (e.g. auth). Default true. */
  enabled?: boolean;
  /** Reset the list whenever this string changes — typically the JSON of
   *  params, but consumers can pass a custom key for stricter control. */
  resetKey?: string;
};

export type InfiniteListReturn<T> = {
  items: T[];
  loading: boolean;       // initial load
  loadingMore: boolean;   // appending next page
  refreshing: boolean;    // pull-to-refresh in flight
  hasMore: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  loadMore: () => Promise<void>;
  /** Imperatively reset and reload (e.g. after creating a new row). */
  reload: () => Promise<void>;
  /** Imperatively mutate the local list (e.g. optimistic update). */
  setItems: React.Dispatch<React.SetStateAction<T[]>>;
};

export function useInfiniteList<T = any, Q extends object = object>(
  endpoint: string,
  options: InfiniteListOptions<Q> = {},
): InfiniteListReturn<T> {
  const { pageSize = 20, params, enabled = true } = options;
  const resetKey = options.resetKey ?? JSON.stringify(params || {});

  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Avoid stale-closure issues when `loadMore` is wired into onEndReached
  // (which captures the callback once and reuses it across renders).
  const offsetRef = useRef(0);
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(true);
  const paramsRef = useRef(params);
  paramsRef.current = params;

  const _fetchPage = useCallback(
    async (offset: number): Promise<T[]> => {
      const resp = await api.get<T[]>(endpoint, {
        params: { limit: pageSize, offset, ...(paramsRef.current || {}) },
      });
      return Array.isArray(resp.data) ? resp.data : [];
    },
    [endpoint, pageSize],
  );

  const _reset = useCallback(async () => {
    if (!enabled) return;
    setError(null);
    setLoading(true);
    offsetRef.current = 0;
    hasMoreRef.current = true;
    loadingRef.current = true;
    try {
      const page = await _fetchPage(0);
      setItems(page);
      offsetRef.current = page.length;
      const more = page.length === pageSize;
      hasMoreRef.current = more;
      setHasMore(more);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to load");
      setItems([]);
      setHasMore(false);
      hasMoreRef.current = false;
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, [enabled, _fetchPage, pageSize]);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setRefreshing(true);
    try { await _reset(); } finally { setRefreshing(false); }
  }, [enabled, _reset]);

  const loadMore = useCallback(async () => {
    if (!enabled) return;
    if (loadingRef.current || !hasMoreRef.current) return;
    loadingRef.current = true;
    setLoadingMore(true);
    try {
      const page = await _fetchPage(offsetRef.current);
      if (page.length > 0) {
        setItems((prev) => [...prev, ...page]);
        offsetRef.current += page.length;
      }
      const more = page.length === pageSize;
      hasMoreRef.current = more;
      setHasMore(more);
    } catch (e: any) {
      // Swallow append errors so the list doesn't blank out — surface via
      // the visible error string but keep the existing items intact.
      setError(e?.response?.data?.detail || e?.message || "Failed to load more");
    } finally {
      setLoadingMore(false);
      loadingRef.current = false;
    }
  }, [enabled, _fetchPage, pageSize]);

  // Initial load + reload whenever params or endpoint changes.
  useEffect(() => { _reset(); /* eslint-disable-next-line */ }, [endpoint, resetKey, enabled]);

  return {
    items, loading, loadingMore, refreshing, hasMore, error,
    refresh, loadMore, reload: _reset, setItems,
  };
}
