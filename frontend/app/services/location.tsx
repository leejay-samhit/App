/**
 * Service Provider · Live Location
 *
 * Approved providers come here to opt-in to live-location sharing so they
 * appear in the customer's "nearby workers" feed. While this screen is open,
 * we re-broadcast their coordinates every BROADCAST_INTERVAL_MS to keep
 * `is_active` true on the customer side.
 *
 * Privacy first: location is only persisted while the toggle is ON. Turning
 * the toggle OFF clears the stored coordinates immediately and removes the
 * provider from nearby search results.
 */
import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { getCurrentCoords, formatActiveAgo, type Coords } from "../../src/location";

export default function ProviderLocation() {
  const router = useRouter();
  const [meStatus, setMeStatus] = useState<string | null>(null);
  // `sharing` is now ALWAYS true for non-admin users — the toggle was
  // removed (2026-06) and the global LocationGate/useLocationTracking hook
  // handles the 5-second background pings. We keep the `sharing` state only
  // so existing JSX/styles render without changes.
  const [sharing] = useState(true);
  const [coords, setCoords] = useState<Coords | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);

  // Initial load: fetch /service/me to know status + current sharing flag
  const loadMe = useCallback(async () => {
    try {
      const r = await api.get<any>("/service/me");
      setMeStatus(r.data?.service_status || null);
      // /auth/me returns the user object directly (no wrapper)
      const u = await api.get<any>("/auth/me");
      setUpdatedAt(u.data?.location_updated_at || null);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { loadMe(); }, [loadMe]));

  const broadcastNow = useCallback(async (): Promise<boolean> => {
    setBusy(true);
    setLastError(null);
    try {
      const c = await getCurrentCoords();
      if (!c) {
        const msg = Platform.OS === "web"
          ? "Browser blocked location access. Allow it via the address-bar lock icon and try again."
          : "Permission denied or GPS off. Enable Location Services in your device settings and try again.";
        setLastError(msg);
        Alert.alert("Location unavailable", msg);
        return false;
      }
      setCoords(c);
      const r = await api.post("/service/me/location", {
        lat: c.lat, lng: c.lng, accuracy_m: c.accuracy_m, sharing: true,
      });
      setUpdatedAt(r.data?.updated_at || new Date().toISOString());
      setLastError(null);
      return true;
    } catch (e) {
      const msg = formatApiError(e);
      setLastError(msg);
      Alert.alert("Could not update location", msg);
      return false;
    } finally { setBusy(false); }
  }, []);

  // The previous 5-minute broadcast interval on this screen has been REMOVED.
  // The global useLocationTracking hook now pings the backend every 5
  // seconds for all non-admin users, so a per-screen timer would only cause
  // duplicate pings. The "Refresh now" button still does an immediate push
  // on demand via `broadcastNow`.

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  if (meStatus !== "approved" && false) {
    // gate removed 2025-06: any user can broadcast
    return null;
  }

  // Customers and providers see slightly different helper copy.
  const isProvider = meStatus === "approved";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
            <Feather name="chevron-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>Live Location</Text>
        </View>

        <Text style={styles.helper}>
          {isProvider
            ? "Customers see you in their \"nearby workers\" feed with a live distance. Your location updates automatically every few seconds in the background while the app is open."
            : "Your approximate location is shared with admin to help match you with nearby providers. Updates automatically every few seconds while the app is open."}
        </Text>

        {/* Toggle card — toggle hidden per product spec (2026-06).
            Location is now ALWAYS-ON for all non-admin users (enforced by the
            global LocationGate + useLocationTracking hook). This card now
            simply shows the user the current sharing status — read-only. */}
        <View style={styles.toggleCard}>
          <View style={[styles.iconCircle, { backgroundColor: "#ECFDF5" }]}>
            <Feather name="navigation" size={26} color="#047857" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.toggleTitle}>Live location is ON</Text>
            <Text style={styles.toggleSub}>
              {updatedAt ? formatActiveAgo(updatedAt) : "Pinging now…"}
            </Text>
          </View>
          <View style={styles.statusPill}>
            <View style={styles.statusDot} />
            <Text style={styles.statusPillText}>ACTIVE</Text>
          </View>
        </View>

        {lastError ? (
          <View style={styles.errorBox}>
            <Feather name="alert-triangle" size={14} color={colors.error} />
            <Text style={styles.errorText} numberOfLines={4}>  {lastError}</Text>
          </View>
        ) : null}

        {/* Always-on: a manual "refresh now" affordance for users who want to
            push their position immediately without waiting for the 5-second
            background tick. */}
        <TouchableOpacity onPress={broadcastNow} disabled={busy} style={styles.refreshBtn}>
          {busy ? (
            <ActivityIndicator color={colors.primary} size="small" />
          ) : (
            <Feather name="refresh-cw" size={14} color={colors.primary} />
          )}
          <Text style={styles.refreshText}>  Refresh my location now</Text>
        </TouchableOpacity>

        {coords ? (
          <View style={styles.coordsCard}>
            <Text style={styles.coordsLabel}>LAST PING</Text>
            <Text style={styles.coordsRow}>{coords.lat.toFixed(5)}, {coords.lng.toFixed(5)}</Text>
            {coords.accuracy_m != null ? (
              <Text style={styles.coordsAccuracy}>±{Math.round(coords.accuracy_m)} m accuracy</Text>
            ) : null}
          </View>
        ) : null}

        <View style={styles.privacyBox}>
          <Feather name="shield" size={16} color={colors.textMuted} />
          <View style={{ flex: 1 }}>
            <Text style={styles.privacyTitle}>Privacy</Text>
            <Text style={styles.privacyText}>
              Location is only stored while sharing is ON. Turning it OFF
              clears your coordinates immediately. We never broadcast your
              precise address — only an approximate distance to customers.
            </Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 12 },
  container: { padding: spacing.lg, paddingBottom: 40 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 },
  backBtn: { padding: 6 },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  helper: { color: colors.textMuted, fontSize: 12, marginTop: 4, marginBottom: 16, lineHeight: 17 },
  toggleCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 16, borderRadius: radii.lg,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  iconCircle: {
    width: 50, height: 50, borderRadius: 25,
    alignItems: "center", justifyContent: "center",
  },
  toggleTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  toggleSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  statusPill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999,
    backgroundColor: "#ECFDF5",
    borderWidth: 1, borderColor: "#A7F3D0",
  },
  statusDot: { width: 7, height: 7, borderRadius: 3.5, backgroundColor: "#10B981" },
  statusPillText: { fontSize: 10.5, fontWeight: "900", color: "#047857", letterSpacing: 0.5 },
  errorBox: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.error + "15",
    borderWidth: 1, borderColor: colors.error + "55",
    borderRadius: 12, padding: 10,
    marginTop: 10,
  },
  errorText: { color: colors.error, fontSize: 12, fontWeight: "700", flex: 1 },
  refreshBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    paddingVertical: 11, marginTop: 12,
    borderRadius: radii.button,
    backgroundColor: colors.primary + "12",
    borderWidth: 1, borderColor: colors.primary + "33",
  },
  refreshText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  coordsCard: {
    marginTop: 12, padding: 14, borderRadius: radii.lg,
    backgroundColor: colors.surfaceMuted,
  },
  coordsLabel: { fontSize: 10, fontWeight: "800", letterSpacing: 1, color: colors.textMuted },
  coordsRow: { fontSize: 14, fontWeight: "700", color: colors.textMain, marginTop: 4 },
  coordsAccuracy: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  privacyBox: {
    flexDirection: "row", gap: 10, marginTop: 18,
    padding: 12, borderRadius: radii.lg,
    backgroundColor: colors.surfaceMuted,
  },
  privacyTitle: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  privacyText: { fontSize: 11, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  emptyText: { color: colors.textMuted, fontSize: 13, textAlign: "center", maxWidth: 280 },
  primaryBtn: {
    backgroundColor: colors.primary, paddingVertical: 12, paddingHorizontal: 22,
    borderRadius: radii.button, marginTop: 8,
  },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800" },
});
