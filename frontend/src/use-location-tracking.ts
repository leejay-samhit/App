/**
 * useLocationTracking
 *
 * Once a user (non-admin) has granted location permission, this hook
 * silently pings the backend with their current lat/lng every PING_INTERVAL.
 *
 * Behaviour:
 *   • First ping fires immediately (so the admin user list shows fresh data
 *     within seconds of login).
 *   • Subsequent pings every PING_INTERVAL_MS (5 seconds, per product spec).
 *   • Failures (offline, server down) are swallowed silently — we keep the
 *     LAST KNOWN coordinate cached in AsyncStorage so when the device comes
 *     back online the next successful ping carries up-to-date data, and
 *     admins can still see the last position from before disconnect.
 *   • Hook is auto-disabled when `enabled=false` (e.g. for admin users).
 *
 * Privacy: backend stores coords as `service_location` GeoJSON Point on the
 * user document, the same field used for nearby-worker search. There is no
 * separate trajectory table — only the latest position is persisted.
 */
import { useEffect, useRef } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState, AppStateStatus } from "react-native";
import { api } from "./api";
import { getCurrentCoords } from "./location";

const PING_INTERVAL_MS = 5_000;                  // 5-second cadence per spec
const LAST_KNOWN_KEY = "@app/lastKnownLocation"; // persisted between runs

export function useLocationTracking(enabled: boolean) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inFlightRef = useRef(false);
  const lastSentRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled) {
      // Make sure no stale timer survives a logout / role change.
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    let cancelled = false;

    const persistLastKnown = async (lat: number, lng: number, accuracy_m?: number) => {
      try {
        await AsyncStorage.setItem(
          LAST_KNOWN_KEY,
          JSON.stringify({ lat, lng, accuracy_m, at: Date.now() }),
        );
      } catch {
        // ignore — best-effort cache
      }
    };

    // Try to send the cached coords if we have any (handles the "captured the
    // last lat/long before data disconnected" requirement — when the device
    // reconnects, we flush the saved coord so the admin view stays accurate).
    const flushCached = async () => {
      try {
        const raw = await AsyncStorage.getItem(LAST_KNOWN_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (parsed?.lat == null || parsed?.lng == null) return;
        await api.post("/service/me/location", {
          lat: parsed.lat,
          lng: parsed.lng,
          accuracy_m: parsed.accuracy_m,
          sharing: true,
        });
      } catch {
        // still offline — leave the cache for next time.
      }
    };

    const tick = async () => {
      if (cancelled || inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const c = await getCurrentCoords();
        if (!c) return; // permission revoked or sensor unavailable
        // Persist BEFORE network call so we have a fallback if the request fails.
        persistLastKnown(c.lat, c.lng, c.accuracy_m);
        await api.post("/service/me/location", {
          lat: c.lat,
          lng: c.lng,
          accuracy_m: c.accuracy_m,
          sharing: true,
        });
        lastSentRef.current = Date.now();
      } catch {
        // Network failure — silently keep trying on next tick. The cached
        // last-known coord will be flushed when connectivity returns.
      } finally {
        inFlightRef.current = false;
      }
    };

    // Kick off an immediate first ping + try to flush any leftover cache.
    flushCached();
    tick();

    // Regular 5-second cadence.
    intervalRef.current = setInterval(tick, PING_INTERVAL_MS);

    // Foreground/background — when user returns to the app we ping right
    // away so the admin view reflects the position they're at right now.
    const onAppState = (s: AppStateStatus) => {
      if (s === "active") {
        flushCached();
        tick();
      }
    };
    const sub = AppState.addEventListener("change", onAppState);

    return () => {
      cancelled = true;
      sub.remove();
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled]);
}
