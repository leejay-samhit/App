/**
 * LocationGate
 *
 * Industry-standard non-blocking design:
 *  1. On first mount we silently check the OS permission.
 *  2. If GRANTED → render children immediately and let
 *     `useLocationTracking` ping the backend every 30s in the background.
 *     We NEVER re-check permission afterwards. No "Checking…" spinner ever
 *     reappears, even when the app is backgrounded/foregrounded — that was
 *     causing the perceived "freeze every 30 seconds" the user complained
 *     about.
 *  3. If DENIED / UNDETERMINED → render a polite explanation card with an
 *     "Allow location access" button. Once the user grants it we flip
 *     `granted = true` and the card never appears again for the session.
 *  4. If the underlying tracking ping discovers the permission was revoked
 *     at the OS level (rare — user goes to Settings and turns it off), the
 *     hook's silent failure is fine — the user just stops appearing in
 *     admin views until they re-grant. We do NOT block the UI for this.
 *
 * Admin users skip the whole thing.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  Platform, Linking,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii } from "./theme";
import { useAuth } from "./auth";
import { checkLocationPermission, requestLocationPermission } from "./location";
import { useLocationTracking } from "./use-location-tracking";

type GateStatus = "initial" | "granted" | "blocked";

export function LocationGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  // Per spec (1c): all users EXCEPT admin require location tracking.
  // Non-authenticated users (no user) — we don't gate the login screen.
  const required = !!user && role !== "admin";

  // `initial` = first render only, while we ask the OS for current status.
  // We deliberately render children optimistically once we've decided —
  // see comment in evaluate().
  const [status, setStatus] = useState<GateStatus>("initial");
  const [requesting, setRequesting] = useState(false);

  const evaluate = useCallback(async () => {
    if (!required) {
      setStatus("granted");
      return;
    }
    const s = await checkLocationPermission();
    if (s === "granted") setStatus("granted");
    else setStatus("blocked");
  }, [required]);

  // RUN ONCE on mount per session. We intentionally do NOT subscribe to
  // AppState changes — re-checking on every foreground caused the
  // "Checking location…" spinner to flash every few seconds, which the
  // user perceived as the app freezing.
  useEffect(() => {
    evaluate();
  }, [evaluate]);

  const onGrant = useCallback(async () => {
    setRequesting(true);
    try {
      const result = await requestLocationPermission();
      if (result === "granted") {
        setStatus("granted");
      } else {
        setStatus("blocked");
      }
    } finally {
      setRequesting(false);
    }
  }, []);

  const onOpenSettings = useCallback(async () => {
    try {
      if (Platform.OS === "web") return;
      await Linking.openSettings();
    } catch {
      // ignore
    }
  }, []);

  // Background tracking — only when granted AND required.
  useLocationTracking(required && status === "granted");

  // Initial silent check — render NOTHING (transparent) for ~50ms while
  // we ask the OS. Avoids a visible spinner flash on slow devices.
  if (status === "initial" && required) {
    return <View style={{ flex: 1, backgroundColor: colors.background }} />;
  }

  if (status === "blocked") {
    return (
      <View style={styles.blocker}>
        <View style={styles.iconCircle}>
          <Feather name="map-pin" size={36} color={colors.primary} />
        </View>
        <Text style={styles.title}>Turn on location</Text>
        <Text style={styles.body}>
          Allow location access for the best experience — we'll match you with
          nearby providers and keep prices accurate for your area.
        </Text>
        <Text style={styles.bodySmall}>
          Your coordinates are used only to show nearby services and improve
          delivery estimates. You can change this anytime in your device settings.
        </Text>
        <TouchableOpacity
          onPress={onGrant}
          disabled={requesting}
          style={[styles.primaryBtn, requesting && { opacity: 0.7 }]}
          testID="location-gate-grant"
        >
          {requesting ? (
            <ActivityIndicator color={colors.primaryFg} />
          ) : (
            <>
              <Feather name="navigation" size={16} color={colors.primaryFg} />
              <Text style={styles.primaryBtnText}>Allow location access</Text>
            </>
          )}
        </TouchableOpacity>
        {Platform.OS !== "web" ? (
          <TouchableOpacity onPress={onOpenSettings} style={styles.secondaryBtn} testID="location-gate-settings">
            <Feather name="settings" size={14} color={colors.primary} />
            <Text style={styles.secondaryBtnText}>Open device settings</Text>
          </TouchableOpacity>
        ) : (
          <Text style={styles.hintWeb}>
            On web: click the lock / location icon in your browser address bar to allow access.
          </Text>
        )}
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  blocker: {
    flex: 1, alignItems: "center", justifyContent: "center",
    padding: 28, gap: 14,
    backgroundColor: colors.background,
  },
  iconCircle: {
    width: 86, height: 86, borderRadius: 43,
    backgroundColor: colors.primary + "15",
    alignItems: "center", justifyContent: "center",
    marginBottom: 4,
  },
  title: { fontSize: 20, fontWeight: "900", color: colors.textMain, textAlign: "center" },
  body: { fontSize: 14, color: colors.textMain, textAlign: "center", lineHeight: 20, maxWidth: 320 },
  bodySmall: { fontSize: 12, color: colors.textMuted, textAlign: "center", lineHeight: 17, maxWidth: 320 },
  checkingText: { color: colors.textMuted, fontSize: 12, marginTop: 12 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary,
    paddingVertical: 14, paddingHorizontal: 28,
    borderRadius: radii.button,
    marginTop: 8,
    minWidth: 240,
  },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14, letterSpacing: 0.2 },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, paddingHorizontal: 16,
  },
  secondaryBtnText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  hintWeb: { color: colors.textMuted, fontSize: 11, textAlign: "center", maxWidth: 280, marginTop: 6 },
});
