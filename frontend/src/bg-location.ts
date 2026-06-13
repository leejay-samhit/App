// ----------------------------------------------------------------------------
// Provider background location heartbeat (June 2026)
// ----------------------------------------------------------------------------
// Goal: keep every approved service provider's `service_location` fresh on the
// backend so customers see accurate "nearby-first" distances even when the
// provider hasn't opened the app in a day. Cadence ≈ 30 minutes.
//
// How it works:
// 1. We register a `TaskManager` task named `PROVIDER_LOCATION_TASK_V1` at
//    module load (must be at module top level so it survives JS-engine
//    restarts inside the background context).
// 2. When a provider logs in / toggles availability to "available" or "busy"
//    we call `startBackgroundProviderLocation()`. That asks for foreground +
//    background location permission and then calls
//    `Location.startLocationUpdatesAsync` with `timeInterval: 30 min` and
//    `distanceInterval: 250 m` — whichever comes first.
// 3. The OS wakes the app every ~30 min (or when the provider moves >250 m)
//    and hands a location batch to the task. The task POSTs
//    `{lat, lng, accuracy_m, sharing: true}` to `/api/service/me/location`.
// 4. If the network call fails (offline / token expired) the task silently
//    returns — the next OS-scheduled tick will try again. The server keeps
//    showing the *last successful* location to customer searches, which is
//    exactly the "offline = show last known" UX the user asked for.
// 5. On logout or availability = "offline" we call
//    `stopBackgroundProviderLocation()` which unregisters the task.
//
// IMPORTANT: this whole module is no-op on web (no TaskManager) and requires
// a native/dev build to actually run — Expo Go does NOT support background
// location updates.
// ----------------------------------------------------------------------------

import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";

const TASK_NAME = "PROVIDER_LOCATION_TASK_V1";
const LAST_PUSH_KEY = "bg_location_last_push_at_v1";
const LAST_FIX_KEY = "bg_location_last_fix_v1";

// ── Tuning knobs ────────────────────────────────────────────────────────────
// 30 min cadence, but the OS may dilate this. distanceInterval ensures we
// also report when the provider moves between two fixed intervals.
const TIME_INTERVAL_MS = 30 * 60 * 1000;   // 30 minutes
const DISTANCE_INTERVAL_M = 250;            // 250 metres

// ── Task definition (must run at module load) ───────────────────────────────
// We can't import `api` here because the background JS engine has no React
// context — we use plain `fetch` instead and read the token from AsyncStorage.
//
// Guard so we never re-define the task on Fast Refresh (RN web HMR).
if (Platform.OS !== "web" && !TaskManager.isTaskDefined(TASK_NAME)) {
  TaskManager.defineTask(TASK_NAME, async ({ data, error }: any) => {
    if (error) {
      // Permission revoked, GPS off, etc. The OS will keep calling us as
      // long as the task is registered — nothing actionable here.
      return;
    }
    try {
      const locs: Array<any> = (data && data.locations) || [];
      if (!locs.length) return;
      // Always send the freshest fix in the batch.
      const fix = locs[locs.length - 1];
      const coords = fix?.coords;
      if (!coords?.latitude || !coords?.longitude) return;

      // Persist locally so the UI can render "Last fix N min ago" even when
      // the provider is fully offline / network call is failing.
      try {
        await AsyncStorage.setItem(LAST_FIX_KEY, JSON.stringify({
          lat: coords.latitude,
          lng: coords.longitude,
          accuracy_m: coords.accuracy ?? null,
          ts: new Date().toISOString(),
        }));
      } catch { /* non-fatal */ }

      const token = await AsyncStorage.getItem("auth_token");
      if (!token) return; // logged out — bail; we'll be unregistered soon

      const base = process.env.EXPO_PUBLIC_BACKEND_URL;
      if (!base) return;

      // Soft-coalesce: don't hammer the server more than once per 5 min
      // even if the OS delivers a burst of fixes.
      try {
        const lastPushRaw = await AsyncStorage.getItem(LAST_PUSH_KEY);
        const last = lastPushRaw ? parseInt(lastPushRaw, 10) : 0;
        if (last && Date.now() - last < 5 * 60 * 1000) return;
      } catch { /* non-fatal */ }

      const res = await fetch(`${base}/api/service/me/location`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          lat: coords.latitude,
          lng: coords.longitude,
          accuracy_m: coords.accuracy ?? null,
          sharing: true,
        }),
      });
      if (res.ok) {
        try { await AsyncStorage.setItem(LAST_PUSH_KEY, String(Date.now())); } catch {}
      }
      // If !res.ok (401, 5xx, offline) — drop silently; next tick will retry.
    } catch {
      // Background tasks must never throw — swallow everything.
    }
  });
}

// ── Public API ──────────────────────────────────────────────────────────────

/**
 * Ask for foreground + background location permission and start the
 * 30-minute heartbeat. Safe to call multiple times — it's idempotent.
 * Returns the final permission state so callers can decide what to render.
 */
export async function startBackgroundProviderLocation(): Promise<{
  ok: boolean;
  reason?: "web" | "permission_fg" | "permission_bg" | "services_off" | "platform";
}> {
  if (Platform.OS === "web") return { ok: false, reason: "web" };

  try {
    // 1. Foreground permission first (required to even prompt for background).
    const fg = await Location.requestForegroundPermissionsAsync();
    if (fg.status !== "granted") return { ok: false, reason: "permission_fg" };

    // 2. Make sure location services are enabled.
    const enabled = await Location.hasServicesEnabledAsync();
    if (!enabled) return { ok: false, reason: "services_off" };

    // 3. Background permission (Android 10+ / iOS Always).
    const bg = await Location.requestBackgroundPermissionsAsync();
    if (bg.status !== "granted") return { ok: false, reason: "permission_bg" };

    // 4. Already running? bail without restarting.
    const running = await Location.hasStartedLocationUpdatesAsync(TASK_NAME).catch(() => false);
    if (running) return { ok: true };

    await Location.startLocationUpdatesAsync(TASK_NAME, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: TIME_INTERVAL_MS,
      distanceInterval: DISTANCE_INTERVAL_M,
      pausesUpdatesAutomatically: false,
      showsBackgroundLocationIndicator: false,
      foregroundService: {
        notificationTitle: "NetworkPay is sharing your location",
        notificationBody: "We update your pin every 30 minutes so nearby customers can find you.",
        notificationColor: "#143D2E",
      },
      // iOS: defer up to ~30 min between deliveries to save battery.
      activityType: Location.ActivityType.OtherNavigation,
      deferredUpdatesInterval: TIME_INTERVAL_MS,
      deferredUpdatesDistance: DISTANCE_INTERVAL_M,
    });
    return { ok: true };
  } catch (_e) {
    return { ok: false, reason: "platform" };
  }
}

/**
 * Stop the heartbeat. Idempotent — safe to call on logout even if the
 * task was never started (e.g. customer accounts).
 */
export async function stopBackgroundProviderLocation(): Promise<void> {
  if (Platform.OS === "web") return;
  try {
    const running = await Location.hasStartedLocationUpdatesAsync(TASK_NAME).catch(() => false);
    if (running) {
      await Location.stopLocationUpdatesAsync(TASK_NAME);
    }
  } catch { /* non-fatal */ }
}

/**
 * Cached last successful fix — useful for showing "Last updated N min ago"
 * even when the device is offline. Falls back to null if we've never
 * captured a location.
 */
export async function getCachedLastFix(): Promise<{
  lat: number; lng: number; accuracy_m: number | null; ts: string;
} | null> {
  try {
    const raw = await AsyncStorage.getItem(LAST_FIX_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/**
 * Force one foreground fix immediately and push to server. Used as the
 * "kick" when the provider first toggles Available so customers don't have
 * to wait up to 30 min for the first heartbeat.
 */
export async function pushLocationNow(): Promise<boolean> {
  if (Platform.OS === "web") return false;
  try {
    const fg = await Location.getForegroundPermissionsAsync();
    if (fg.status !== "granted") return false;
    const enabled = await Location.hasServicesEnabledAsync();
    if (!enabled) return false;
    const pos = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    const token = await AsyncStorage.getItem("auth_token");
    const base = process.env.EXPO_PUBLIC_BACKEND_URL;
    if (!token || !base) return false;
    const res = await fetch(`${base}/api/service/me/location`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy ?? null,
        sharing: true,
      }),
    });
    if (res.ok) {
      try {
        await AsyncStorage.setItem(LAST_FIX_KEY, JSON.stringify({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy_m: pos.coords.accuracy ?? null,
          ts: new Date().toISOString(),
        }));
        await AsyncStorage.setItem(LAST_PUSH_KEY, String(Date.now()));
      } catch {}
      return true;
    }
    return false;
  } catch {
    return false;
  }
}
