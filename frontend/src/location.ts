/**
 * Location helpers — wraps expo-location with a friendly API and graceful
 * web fallback. Used by both customers (request my coords once to find
 * nearby workers) and providers (broadcast coords every few minutes).
 */
import * as Location from "expo-location";
import { Platform } from "react-native";

export type Coords = { lat: number; lng: number; accuracy_m?: number };
export type PermStatus = "granted" | "denied" | "undetermined" | "unsupported";

/**
 * Request foreground location permission. On web returns "granted" only after
 * the user accepts the browser prompt (we detect via a probe getCurrentCoords
 * call inside requestAndGetCoords). For native we use expo-location.
 */
export async function checkLocationPermission(): Promise<PermStatus> {
  if (Platform.OS === "web") {
    if (typeof navigator === "undefined" || !("permissions" in navigator)) {
      // Some browsers don't support Permissions API — treat as undetermined.
      return typeof navigator !== "undefined" && (navigator as any).geolocation ? "undetermined" : "unsupported";
    }
    try {
      const result = await (navigator as any).permissions.query({ name: "geolocation" as any });
      const s = (result?.state || "prompt") as string;
      if (s === "granted") return "granted";
      if (s === "denied") return "denied";
      return "undetermined";
    } catch {
      return "undetermined";
    }
  }
  try {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status === "granted") return "granted";
    if (status === "denied") return "denied";
    return "undetermined";
  } catch {
    return "unsupported";
  }
}

/**
 * Trigger the OS permission prompt (or browser prompt on web).
 * Returns the resulting status.
 */
export async function requestLocationPermission(): Promise<PermStatus> {
  if (Platform.OS === "web") {
    // The only way to trigger the browser prompt is to actually call
    // getCurrentPosition. We probe it and infer the result.
    if (typeof navigator === "undefined" || !navigator.geolocation) return "unsupported";
    return await new Promise<PermStatus>((resolve) => {
      navigator.geolocation.getCurrentPosition(
        () => resolve("granted"),
        (err) => resolve(err && err.code === 1 ? "denied" : "undetermined"),
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
      );
    });
  }
  try {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status === "granted") return "granted";
    if (status === "denied") return "denied";
    return "undetermined";
  } catch {
    return "unsupported";
  }
}

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

/**
 * Battery-friendly coordinate read for the periodic background ping.
 *
 * `getCurrentCoords()` forces a FRESH sensor fix every call, which is fine
 * once (checkout, "use my location") but ruinous when called on a timer —
 * it wakes the GPS/Wi-Fi scan chip every time. This variant reuses the fix
 * the OS already has (free, no radio wake) and only pays for a real fix
 * when that cached one is older than `maxAgeMs`.
 *
 * It also never triggers a permission PROMPT — it only reads the current
 * grant, so it is safe to call silently in the background.
 */
export async function getTrackingCoords(maxAgeMs = 5 * 60 * 1000): Promise<Coords | null> {
  if (Platform.OS === "web") return getCurrentCoords();
  try {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status !== "granted") return null;
    const cached = await Location.getLastKnownPositionAsync({ maxAge: maxAgeMs });
    const pos = cached || await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    if (!pos?.coords) return null;
    return {
      lat: pos.coords.latitude,
      lng: pos.coords.longitude,
      accuracy_m: pos.coords.accuracy ?? undefined,
    };
  } catch {
    return null;
  }
}

/** Straight-line metres between two coordinates (haversine). */
export function metresBetween(a: Coords, b: Coords): number {
  const R = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLng = ((b.lng - a.lng) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
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
