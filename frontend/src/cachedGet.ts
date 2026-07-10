/**
 * Simple stale-while-revalidate cache for common GET calls (Sept 2026).
 *
 * Owner complaint: "App is very very slow and some time Showing network
 * error … Store in cache and Recall immediately whenever required".
 *
 * Design (deliberately tiny — no swr/react-query dependency):
 *   1. In-memory `Map<url, { data, at }>`; TTL is per-caller configurable.
 *   2. Consumers call `cachedGet(url)` — if a fresh copy exists, return
 *      IT synchronously via a Promise that resolves in a microtask AND
 *      fire an async revalidate in the background. When the fresh copy
 *      lands we notify listeners so screens re-render.
 *   3. Persistent copy in AsyncStorage keyed by URL — survives app kill.
 *      Only touched on cold-start read + write-through so the hot path
 *      stays fast.
 *   4. Network failures fall back to the last-known cached value, so
 *      "Network error" toasts stop appearing when the device flickers.
 *
 * Not a full SWR — no dedupe of concurrent requests, no cache
 * invalidation on mutation. Consumers can call `bustCache(url)` after
 * a POST/PATCH to force the next `cachedGet` to hit network.
 */

import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "./api";

type Entry<T> = { data: T; at: number };

const _mem: Map<string, Entry<any>> = new Map();
const STORAGE_PREFIX = "__cg_";

// URL patterns we PROACTIVELY hydrate from AsyncStorage on the first
// cachedGet call — the rest lazy-load.
const _hydrated: Set<string> = new Set();

async function hydrateOnce<T>(url: string): Promise<Entry<T> | null> {
  if (_hydrated.has(url)) return _mem.get(url) as Entry<T> | null;
  _hydrated.add(url);
  try {
    const raw = await AsyncStorage.getItem(STORAGE_PREFIX + url);
    if (raw) {
      const parsed = JSON.parse(raw) as Entry<T>;
      _mem.set(url, parsed);
      return parsed;
    }
  } catch { /* corrupt entry — ignore */ }
  return null;
}

async function persist<T>(url: string, entry: Entry<T>) {
  try { await AsyncStorage.setItem(STORAGE_PREFIX + url, JSON.stringify(entry)); }
  catch { /* out-of-space / private-mode — best-effort */ }
}

/**
 * Get a cached copy of a URL, with stale-while-revalidate.
 *
 * @param url path relative to `/api` (e.g. "/orders/me")
 * @param ttlMs  Consider the cache "fresh" for this many ms. Default 60s.
 * @param onFresh optional callback fired with the revalidated response.
 * @returns the freshest data we can serve immediately (may be stale).
 *          Callers should ALSO consume `onFresh` to update UI when
 *          the background revalidation lands.
 */
export async function cachedGet<T = any>(
  url: string,
  opts: {
    ttlMs?: number;
    onFresh?: (data: T) => void;
    params?: Record<string, any>;
  } = {},
): Promise<T | null> {
  const ttl = opts.ttlMs ?? 60_000;
  // Include params in the cache key so different query variants don't collide.
  const key = opts.params ? `${url}?${JSON.stringify(opts.params)}` : url;

  const hydrated = await hydrateOnce<T>(key);
  const now = Date.now();
  const entry = _mem.get(key) as Entry<T> | undefined;
  const isFresh = entry && (now - entry.at) < ttl;

  // Background revalidate — do this regardless so we're up-to-date next time.
  // (Even when fresh, kick a revalidate if the caller passed onFresh so the
  // UI can react to server-side changes.)
  const shouldRevalidate = !isFresh || Boolean(opts.onFresh);
  const revalidate = async () => {
    try {
      const r = await api.get(url, { params: opts.params });
      const newEntry = { data: r.data as T, at: Date.now() };
      _mem.set(key, newEntry);
      persist(key, newEntry).catch(() => {});
      if (opts.onFresh) opts.onFresh(r.data as T);
    } catch { /* silent — cached copy remains */ }
  };
  if (shouldRevalidate) {
    revalidate();
  }

  return (entry?.data ?? hydrated?.data ?? null) as T | null;
}

/** Invalidate a specific cached URL (or by prefix). Call this after any POST/PATCH. */
export function bustCache(urlOrPrefix: string) {
  for (const k of Array.from(_mem.keys())) {
    if (k === urlOrPrefix || k.startsWith(urlOrPrefix)) {
      _mem.delete(k);
      AsyncStorage.removeItem(STORAGE_PREFIX + k).catch(() => {});
    }
  }
}

/** Full nuke — used on logout. */
export async function clearAllCache() {
  _mem.clear();
  _hydrated.clear();
  try {
    const keys = await AsyncStorage.getAllKeys();
    const ours = keys.filter(k => k.startsWith(STORAGE_PREFIX));
    if (ours.length > 0) await AsyncStorage.multiRemove(ours);
  } catch { /* best-effort */ }
}
