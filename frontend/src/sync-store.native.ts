/**
 * Synchronous key/value store — native implementation (expo-sqlite kv-store).
 *
 * Metro picks this file on iOS/Android and the plain .ts on web, so the
 * expo-sqlite web worker never reaches the web bundle.
 */
import Storage from "expo-sqlite/kv-store";

export function syncGet(key: string): string | null {
  try {
    return Storage.getItemSync(key);
  } catch {
    return null;
  }
}

export function syncSet(key: string, value: string): void {
  try {
    Storage.setItemSync(key, value);
  } catch { /* storage unavailable — the in-memory palette still applies */ }
}
