// Login activity — every device signed in to this account (Sep 2026).
//
// Rows come from GET /api/users/me/login-history (written on every sign-in by
// backend/core/login_history.py). A user can sign a single device out, or
// every device except this one. New devices also raise a bell/push alert.
import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing } from "../src/theme";

type Entry = {
  id: string;
  device_label?: string;
  platform?: string;
  ip?: string | null;
  method?: string;
  created_at: string;
  is_new_device?: boolean;
  is_current?: boolean;
  is_active?: boolean;
};

const ICON: Record<string, any> = { ios: "smartphone", android: "smartphone", web: "monitor" };

const when = (iso: string) => {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
  });
};

export default function LoginHistoryScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: Entry[] }>("/users/me/login-history");
      setItems(data?.items || []);
    } catch (e) {
      Alert.alert("Couldn't load login activity", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const signOutOne = async (e: Entry) => {
    setBusy(e.id);
    try {
      await api.post(`/users/me/login-history/${e.id}/revoke`);
      await load();
    } catch (err) {
      Alert.alert("Couldn't sign that device out", formatApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const signOutOthers = async () => {
    setBusy("others");
    try {
      const { data } = await api.post<{ signed_out: number }>("/users/me/login-history/revoke-others");
      await load();
      Alert.alert(
        "Done",
        data?.signed_out ? `Signed out ${data.signed_out} other device(s).` : "No other devices were signed in.",
      );
    } catch (err) {
      Alert.alert("Couldn't sign other devices out", formatApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const activeCount = items.filter((i) => i.is_active).length;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="login-history-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Login activity</Text>
        <View style={{ width: 40 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          <View style={styles.summary}>
            <Feather name="shield" size={18} color={colors.primary} />
            <Text style={styles.summaryText}>
              {activeCount} device{activeCount === 1 ? "" : "s"} signed in right now. You’re alerted
              whenever your account is used on a device for the first time.
            </Text>
          </View>

          {items.length === 0 ? (
            <Text style={styles.empty}>No login activity recorded yet.</Text>
          ) : null}

          {items.map((e) => (
            <View key={e.id} style={styles.row} testID={`login-row-${e.id}`}>
              <View style={styles.icon}>
                <Feather name={ICON[e.platform || "web"] || "monitor"} size={17} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <View style={styles.titleRow}>
                  <Text style={styles.device} numberOfLines={1}>{e.device_label || "Unknown device"}</Text>
                  {e.is_current ? (
                    <View style={styles.pillNow}><Text style={styles.pillNowText}>THIS DEVICE</Text></View>
                  ) : e.is_active ? (
                    <View style={styles.pillActive}><Text style={styles.pillActiveText}>SIGNED IN</Text></View>
                  ) : null}
                </View>
                <Text style={styles.meta}>
                  {when(e.created_at)}
                  {e.ip ? ` · ${e.ip}` : ""}
                  {e.method === "google" ? " · Google" : ""}
                </Text>
                {e.is_new_device ? (
                  <Text style={styles.newDevice}>New device at the time — you were alerted</Text>
                ) : null}
              </View>
              {!e.is_current && e.is_active ? (
                <TouchableOpacity
                  onPress={() => signOutOne(e)}
                  disabled={busy !== null}
                  style={[styles.signOut, busy !== null && { opacity: 0.5 }]}
                  testID={`login-signout-${e.id}`}
                >
                  {busy === e.id ? (
                    <ActivityIndicator size="small" color="#B3261E" />
                  ) : (
                    <Text style={styles.signOutText}>Sign out</Text>
                  )}
                </TouchableOpacity>
              ) : null}
            </View>
          ))}

          <TouchableOpacity
            onPress={signOutOthers}
            disabled={busy !== null || activeCount < 2}
            style={[styles.bigBtn, (busy !== null || activeCount < 2) && { opacity: 0.5 }]}
            testID="login-signout-others"
          >
            {busy === "others" ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Feather name="log-out" size={16} color="#fff" />
            )}
            <Text style={styles.bigBtnText}>Sign out all other devices</Text>
          </TouchableOpacity>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.screen,
    paddingVertical: 10, backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, textAlign: "center", fontSize: 16, fontWeight: "800", color: colors.textMain },
  summary: {
    flexDirection: "row", gap: 10, alignItems: "flex-start", padding: 14, marginBottom: 14,
    backgroundColor: colors.brand100, borderRadius: radii.lg,
  },
  summaryText: { flex: 1, fontSize: 12.5, lineHeight: 18, color: colors.textMain },
  empty: { fontSize: 13, color: colors.textMuted, marginBottom: 16 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12, padding: 14, marginBottom: 10,
    backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    minHeight: 68,
  },
  icon: {
    width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted,
  },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  device: { flexShrink: 1, fontSize: 14, fontWeight: "800", color: colors.textMain },
  meta: { fontSize: 11.5, color: colors.textMuted, marginTop: 3 },
  newDevice: { fontSize: 11, color: colors.warning, marginTop: 3, fontWeight: "700" },
  pillNow: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: colors.primary },
  pillNowText: { fontSize: 8.5, fontWeight: "900", color: colors.primaryFg, letterSpacing: 0.6 },
  pillActive: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: colors.surfaceMuted },
  pillActiveText: { fontSize: 8.5, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.6 },
  signOut: { minHeight: 44, paddingHorizontal: 10, justifyContent: "center" },
  signOutText: { fontSize: 12.5, fontWeight: "800", color: "#B3261E" },
  bigBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, borderRadius: radii.lg, minHeight: 50, marginTop: 6,
  },
  bigBtnText: { fontSize: 14, fontWeight: "800", color: "#fff" },
});
