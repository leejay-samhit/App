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
import { useCallback, useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Platform,
  Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { getCurrentCoords, formatActiveAgo, type Coords } from "../../src/location";

const BROADCAST_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes — balance between freshness and battery

export default function ProviderLocation() {
  const router = useRouter();
  const [meStatus, setMeStatus] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);
  const [coords, setCoords] = useState<Coords | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial load: fetch /service/me to know status + current sharing flag
  const loadMe = useCallback(async () => {
    try {
      const r = await api.get<any>("/service/me");
      setMeStatus(r.data?.service_status || null);
      // /auth/me returns the user object directly (no wrapper)
      const u = await api.get<any>("/auth/me");
      const sharingNow = !!u.data?.location_sharing;
      setSharing(sharingNow);
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

  const stopBroadcast = useCallback(async () => {
    setBusy(true);
    try {
      await api.post("/service/me/location", { lat: 0, lng: 0, sharing: false });
      setSharing(false);
      setCoords(null);
      setUpdatedAt(null);
    } catch (e) {
      Alert.alert("Could not stop sharing", formatApiError(e));
    } finally { setBusy(false); }
  }, []);

  // Auto-rebroadcast while sharing is ON & screen is focused
  useEffect(() => {
    if (!sharing) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }
    intervalRef.current = setInterval(() => {
      broadcastNow();
    }, BROADCAST_INTERVAL_MS);
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [sharing, broadcastNow]);

  const onToggle = async (next: boolean) => {
    if (next) {
      const ok = await broadcastNow();
      if (ok) setSharing(true);
    } else {
      await stopBroadcast();
    }
  };

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
            ? `When ON, customers nearby see you in their "nearby workers" feed with a live distance and an active indicator. We refresh your location every ${Math.round(BROADCAST_INTERVAL_MS / 60000)} minutes while this screen is open.`
            : `When ON, your approximate location is shared with admin so they can see where you're connecting from. Refreshes every ${Math.round(BROADCAST_INTERVAL_MS / 60000)} minutes while this screen is open. You can turn it OFF anytime.`}
        </Text>

        {/* Toggle card */}
        <View style={styles.toggleCard}>
          <View style={[styles.iconCircle, { backgroundColor: sharing ? "#ECFDF5" : colors.surfaceMuted }]}>
            <Feather name="navigation" size={26} color={sharing ? "#047857" : colors.textMuted} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.toggleTitle}>{sharing ? "Sharing live location" : "Sharing is OFF"}</Text>
            <Text style={styles.toggleSub}>
              {sharing
                ? updatedAt ? formatActiveAgo(updatedAt) : "Pinging now…"
                : "Customers won't see you in the nearby feed."}
            </Text>
          </View>
          <Switch
            value={sharing}
            onValueChange={onToggle}
            disabled={busy}
            trackColor={{ false: "#cbd5e1", true: "#10B98166" }}
            thumbColor={sharing ? "#10B981" : "#fff"}
            testID="provider-loc-toggle"
          />
        </View>

        {lastError ? (
          <View style={styles.errorBox}>
            <Feather name="alert-triangle" size={14} color={colors.error} />
            <Text style={styles.errorText} numberOfLines={4}>  {lastError}</Text>
          </View>
        ) : null}

        {sharing ? (
          <TouchableOpacity onPress={broadcastNow} disabled={busy} style={styles.refreshBtn}>
            {busy ? (
              <ActivityIndicator color={colors.primary} size="small" />
            ) : (
              <Feather name="refresh-cw" size={14} color={colors.primary} />
            )}
            <Text style={styles.refreshText}>  Refresh my location now</Text>
          </TouchableOpacity>
        ) : null}

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
