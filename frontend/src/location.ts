/**
 * Location helpers — wraps expo-location with a friendly API and graceful
 * web fallback. Used by both customers (request my coords once to find
 * nearby workers) and providers (broadcast coords every few minutes).
 */
import * as Location from "expo-location";
import { Platform } from "react-native";

export type Coords = { lat: number; lng: number; accuracy_m?: number };

/**
 * Request foreground location once. Returns `null` if permission is denied
 * or anything goes wrong. Web falls back to the browser geolocation API.
 */
export async function getCurrentCoords(): Promise<Coords | null> {
  try {
    if (Platform.OS === "web") {
      // Browser geolocation (works in Chrome / Safari etc. when on https/localhost)
      if (typeof navigator === "undefined" || !navigator.geolocation) return null;
      return await new Promise<Coords | null>((resolve) => {
        navigator.geolocation.getCurrentPosition(
          (p) => resolve({
            lat: p.coords.latitude,
            lng: p.coords.longitude,
            accuracy_m: p.coords.accuracy ?? undefined,
          }),
          () => resolve(null),
          { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
        );
      });
    }
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") return null;
    const pos = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return {
      lat: pos.coords.latitude,
      lng: pos.coords.longitude,
      accuracy_m: pos.coords.accuracy ?? undefined,
    };
  } catch {
    return null;
  }
}

export function formatDistance(km: number | null | undefined): string {
  if (km == null) return "";
  // Sub-1 km: show one decimal in km (e.g., 0.9 km — instead of "900 m")
  if (km < 1) {
    const v = Math.round(km * 10) / 10; // round to 1 decimal
    // If rounding crossed the 1-km boundary (e.g. 0.95 → 1.0), drop the decimal.
    if (v >= 1) return `${Math.round(km)} km`;
    // Edge case: 0.04 → 0 → show as "0.1 km" (so we never display "0 km")
    return `${(v < 0.1 ? 0.1 : v).toFixed(1)} km`;
  }
  // 1 km and beyond: round to whole number (e.g., 4 km, 5 km, 12 km)
  return `${Math.round(km)} km`;
}

export function formatActiveAgo(updatedAtIso: string | null | undefined): string {
  if (!updatedAtIso) return "";
  try {
    const t = new Date(updatedAtIso).getTime();
    const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (mins < 1) return "Active now";
    if (mins < 60) return `Active ${mins}m ago`;
    const hours = Math.round(mins / 60);
    if (hours < 24) return `Active ${hours}h ago`;
    return "";
  } catch {
    return "";
  }
}
