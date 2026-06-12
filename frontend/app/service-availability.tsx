// Service-provider availability toggle screen.
// Provider chooses one of Available / Busy / Offline.
// This is independent of GPS — it's a manual "I'm taking jobs / I'm not"
// flag the provider controls themselves. Shown next to their card on the
// services tab as a colored dot.
import { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

type Status = "available" | "busy" | "offline";

const OPTIONS: { key: Status; label: string; sub: string; color: string; icon: any }[] = [
  { key: "available", label: "Available", sub: "Customers can see you & call you immediately", color: "#16A34A", icon: "check-circle" },
  { key: "busy",      label: "Busy",      sub: "You're on a job — show a yellow dot to customers", color: "#F59E0B", icon: "clock"        },
  { key: "offline",   label: "Offline",   sub: "Temporarily not taking new requests",          color: "#6B7280", icon: "power"        },
];

export default function ServiceAvailability() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [status, setStatus] = useState<Status>("available");
  const [saving, setSaving] = useState<Status | null>(null);

  useEffect(() => {
    const cur = ((user as any)?.availability_status as Status) || "available";
    setStatus(cur);
  }, [user]);

  const onPick = async (s: Status) => {
    if (s === status) return;
    setSaving(s);
    try {
      await api.patch("/services/me/availability", { status: s });
      setStatus(s);
      try { await refresh(); } catch {}
    } catch (e) {
      Alert.alert("Couldn't update", formatApiError(e));
    } finally {
      setSaving(null);
    }
  };

  if (!user?.is_service_provider && (user as any)?.service_status !== "approved") {
    return (
      <SafeAreaView style={st.safe} edges={["top"]}>
        <View style={st.center}>
          <Feather name="alert-circle" size={32} color={colors.textMuted} />
          <Text style={st.empty}>Only approved service providers can use this screen.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <TouchableOpacity onPress={() => router.back()} style={st.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={st.title}>My Availability</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={{ padding: spacing.screen, gap: 12 }}>
        <Text style={st.hint}>
          Toggle your status so customers know whether they can reach you.
          This is separate from your nearby-area visibility.
        </Text>

        {OPTIONS.map((o) => {
          const active = status === o.key;
          const isBusy = saving === o.key;
          return (
            <TouchableOpacity
              key={o.key}
              onPress={() => onPick(o.key)}
              disabled={isBusy}
              style={[st.row, active && st.rowActive]}
              testID={`avail-${o.key}`}
            >
              <View style={[st.dot, { backgroundColor: o.color }]}>
                <Feather name={o.icon} size={14} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[st.rowTitle, active && { color: o.color }]}>{o.label}</Text>
                <Text style={st.rowSub}>{o.sub}</Text>
              </View>
              {isBusy ? (
                <ActivityIndicator color={o.color} />
              ) : active ? (
                <Feather name="check" size={20} color={o.color} />
              ) : null}
            </TouchableOpacity>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, padding: 24 },
  empty: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  hint: { fontSize: 12, color: colors.textMuted, lineHeight: 18, marginBottom: 4 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 14,
    backgroundColor: colors.surface,
    padding: 14, borderRadius: radii.card,
    borderWidth: 2, borderColor: colors.border,
  },
  rowActive: { borderColor: colors.primary },
  dot: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: "center", justifyContent: "center",
  },
  rowTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  rowSub: { fontSize: 11, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
});
