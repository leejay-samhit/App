/**
 * LocationBanner — small one-time dismissable banner shown at the top of
 * the Shop home asking the user to allow location access for a better
 * shopping experience.
 *
 * Behaviour:
 *  • Hidden on web (web shows a different reverse-geocode flow already).
 *  • Hidden if the OS permission is already granted.
 *  • Hidden permanently after the user taps "Allow" (and grants) — we
 *    set @location_banner_dismissed=1 in AsyncStorage.
 *  • Hidden after user taps the small "✕" close button (same flag).
 *
 * Non-blocking: it never prevents the user from using the app.
 */
import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Platform } from "react-native";
import { Feather } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { colors } from "./theme";
import { checkLocationPermission, requestLocationPermission } from "./location";

const DISMISS_KEY = "@app/locationBannerDismissed";

export function LocationBanner() {
  // null = not decided yet (don't render anything during the initial
  // hydration race). false = show banner. true = hide forever.
  const [hidden, setHidden] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  // Decide whether to render the banner on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Already dismissed?
        const flag = await AsyncStorage.getItem(DISMISS_KEY);
        if (flag === "1") { if (!cancelled) setHidden(true); return; }
        // Already granted?
        const status = await checkLocationPermission();
        if (cancelled) return;
        if (status === "granted") {
          setHidden(true);
        } else {
          setHidden(false);
        }
      } catch {
        if (!cancelled) setHidden(true); // fail safe — never spam the user
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const persistDismissal = useCallback(async () => {
    try { await AsyncStorage.setItem(DISMISS_KEY, "1"); } catch { /* ignore */ }
  }, []);

  const onAllow = useCallback(async () => {
    setBusy(true);
    try {
      const status = await requestLocationPermission();
      // Hide forever on grant; on denial, still hide so we don't keep
      // pestering the user (per UX spec: "after the allow stop showing").
      // If they want to grant later they can do it from device settings.
      if (status === "granted" || status === "denied") {
        await persistDismissal();
        setHidden(true);
      }
    } finally {
      setBusy(false);
    }
  }, [persistDismissal]);

  const onDismiss = useCallback(async () => {
    await persistDismissal();
    setHidden(true);
  }, [persistDismissal]);

  // Never render until we know the state; never render on web (the Shop
  // home already prompts for geolocation via the address modal).
  if (hidden !== false) return null;
  if (Platform.OS === "web") return null;

  return (
    <View style={styles.wrap}>
      <View style={styles.iconCircle}>
        <Feather name="navigation" size={14} color={colors.primary} />
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.title} numberOfLines={1}>For best shop experience</Text>
        <Text style={styles.sub} numberOfLines={2}>Allow location access — we'll match deals and delivery to your area.</Text>
      </View>
      <TouchableOpacity
        onPress={onAllow}
        disabled={busy}
        style={[styles.allowBtn, busy && { opacity: 0.7 }]}
        testID="location-banner-allow"
      >
        <Text style={styles.allowText}>{busy ? "…" : "Allow"}</Text>
      </TouchableOpacity>
      <TouchableOpacity
        onPress={onDismiss}
        style={styles.closeBtn}
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        testID="location-banner-close"
      >
        <Feather name="x" size={14} color={colors.textMuted} />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginHorizontal: 16, marginTop: 10,
    paddingHorizontal: 12, paddingVertical: 10,
    borderRadius: 14,
    backgroundColor: colors.brand100,
    borderWidth: 1, borderColor: colors.primary + "33",
  },
  iconCircle: {
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: "#ffffffCC",
    alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: 12.5, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  sub: { fontSize: 11, color: colors.textMuted, marginTop: 1, lineHeight: 14 },
  allowBtn: {
    paddingHorizontal: 12, paddingVertical: 8,
    backgroundColor: colors.primary,
    borderRadius: 999,
  },
  allowText: { fontSize: 12, fontWeight: "900", color: colors.primaryFg, letterSpacing: 0.3 },
  closeBtn: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: "center", justifyContent: "center",
  },
});
