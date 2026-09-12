/**
 * useLocationTracking
 *
 * Keeps the backend's copy of the customer's position fresh enough for
 * "which sellers deliver to me" without draining the battery.
 *
 * Battery rules (Nov 2026 — owner reported heavy drain):
 *   • FOREGROUND ONLY. The timer is torn down the moment the app is
 *     backgrounded and rebuilt when it comes back. Previously a 30-second
 *     timer kept firing while the phone was in the user's pocket, waking
 *     the GPS + the radio ~120 times an hour, all day.
 *   • The cadence is 5 minutes, not 30 seconds. A shopper's delivery
 *     eligibility does not change twice a minute.
 *   • Coordinates come from the OS's LAST KNOWN fix (free) and only pay
 *     for a real sensor fix when that is older than 5 minutes.
 *   • The network POST is skipped unless the user actually MOVED (≥ 150 m)
 *     or the server copy is older than 20 minutes.
 *   • Failures are swallowed; the last coordinate stays cached in
 *     AsyncStorage and is flushed on the next successful tick.
 *
 * Privacy: only the latest position is persisted server-side
 * (`service_location` GeoJSON point) — there is no trajectory history.
 */
import { useEffect, useRef } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState, AppStateStatus } from "react-native";
import { api } from "./api";
import { getTrackingCoords, metresBetween, Coords } from "./location";

const PING_INTERVAL_MS = 5 * 60 * 1000;   // 5 min while the app is open
const MAX_SILENCE_MS = 20 * 60 * 1000;    // force a refresh after 20 min
const MIN_MOVE_M = 150;                   // below this, nothing changed
const LAST_KNOWN_KEY = "@app/lastKnownLocation";

export function useLocationTracking(enabled: boolean) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const inFlightRef = useRef(false);
  const lastSentRef = useRef<number>(0);
  const lastSentCoordRef = useRef<Coords | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const persistLastKnown = async (c: Coords) => {
      try {
        await AsyncStorage.setItem(LAST_KNOWN_KEY, JSON.stringify({ ...c, at: Date.now() }));
      } catch { /* best-effort cache */ }
    };

    const post = async (c: Coords) => {
      await api.post("/service/me/location", {
        lat: c.lat,
        lng: c.lng,
        accuracy_m: c.accuracy_m,
        sharing: true,
      });
      lastSentRef.current = Date.now();
      lastSentCoordRef.current = c;
    };

    // If an earlier tick captured coords but the network was down, flush the
    // cached coordinate once we're back online.
    const flushCached = async () => {
      if (lastSentRef.current) return;      // already in sync this session
      try {
        const raw = await AsyncStorage.getItem(LAST_KNOWN_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (parsed?.lat == null || parsed?.lng == null) return;
        await post({ lat: parsed.lat, lng: parsed.lng, accuracy_m: parsed.accuracy_m });
      } catch { /* still offline — try again next tick */ }
    };

    const tick = async () => {
      // Never run the sensor while the app is not on screen.
      if (cancelled || inFlightRef.current || AppState.currentState !== "active") return;
      inFlightRef.current = true;
      try {
        const c = await getTrackingCoords(PING_INTERVAL_MS);
        if (!c) return;                    // permission not granted / sensor off
        persistLastKnown(c);
        const prev = lastSentCoordRef.current;
        const stale = Date.now() - lastSentRef.current > MAX_SILENCE_MS;
        if (prev && !stale && metresBetween(prev, c) < MIN_MOVE_M) return;
        await post(c);
      } catch {
        // Offline / server hiccup — the cached coord is flushed next time.
      } finally {
        inFlightRef.current = false;
      }
    };

    const start = () => {
      if (intervalRef.current) return;
      intervalRef.current = setInterval(tick, PING_INTERVAL_MS);
    };
    const stop = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    flushCached();
    tick();
    start();

    const sub = AppState.addEventListener("change", (s: AppStateStatus) => {
      if (s === "active") {
        // Fresh position for the screen the user is about to look at.
        flushCached();
        tick();
        start();
      } else {
        // Backgrounded / phone locked — no timers, no GPS, no radio.
        stop();
      }
    });

    return () => {
      cancelled = true;
      sub.remove();
      stop();
    };
  }, [enabled]);
}
