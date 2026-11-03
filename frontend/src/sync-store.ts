/**
 * Synchronous key/value store — web implementation.
 *
 * Used by theme.ts to read the active palette at import time, BEFORE any
 * screen builds its StyleSheet. Must stay synchronous for that reason.
 * The native counterpart lives in sync-store.native.ts; keeping them in
 * separate files is what stops expo-sqlite from entering the web bundle.
 */
export function syncGet(key: string): string | null {
  try {
    return (globalThis as any)?.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function syncSet(key: string, value: string): void {
  try {
    (globalThis as any)?.localStorage?.setItem(key, value);
  } catch { /* private mode / quota — the in-memory palette still applies */ }
}
