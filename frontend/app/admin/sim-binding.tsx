// Admin · SIM binding (Oct 2026).
// Shows the server's own numbers and the security event tail. Nothing here is
// inferred: every row comes from `sim_bindings` / `sim_audit`.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Switch,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { notify } from "../../src/notify";
import { colors, spacing, radii } from "../../src/theme";

type Overview = {
  policy: {
    enforce_chat: boolean;
    required_level: string;
    allow_web_without_link: boolean;
    clamped_to_sim_presence: boolean;
    number_proof_available: boolean;
  };
  totals: {
    users: number;
    bindings: number;
    number_verified: number;
    needs_revalidation: number;
    rejected_attempts: number;
    by_sim_state: Record<string, number>;
  };
  recent_events: {
    id: string; user_id?: string; event: string; result: string;
    detail?: string; created_at: string;
  }[];
  notes: string[];
};

export default function AdminSimBinding() {
  const router = useRouter();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Overview>("/admin/sim-binding/overview");
      setData(res.data);
      setError("");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const patch = async (body: Record<string, unknown>) => {
    setSaving(true);
    try {
      await api.patch("/admin/sim-binding/policy", body);
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const t = data?.totals;
  const p = data?.policy;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "SIM binding", headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={12} testID="admin-sim-back">
          <Feather name="arrow-left" size={22} color={colors.primaryFg} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>SIM binding</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.primary} />}
      >
        {!!error && <Text style={styles.err}>{error}</Text>}

        {p?.clamped_to_sim_presence && (
          <View style={styles.warnBox}>
            <Text style={styles.warnText}>
              Number confirmation isn&apos;t configured, so the requirement is capped at “SIM present”. Add the Truecaller
              client ID to require confirmed numbers.
            </Text>
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Policy</Text>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Require verification for chat</Text>
            <Switch
              testID="admin-sim-enforce-chat-switch"
              value={!!p?.enforce_chat}
              disabled={saving || !p}
              onValueChange={(v) => {
                if (v) {
                  patch({ enforce_chat: true });
                  return;
                }
                // Turning this off opens chat for everyone — make it deliberate.
                notify(
                  "Turn verification off?",
                  "Every user will be able to chat without verifying a SIM until you switch this back on.",
                  [
                    { text: "Keep it on", style: "cancel" },
                    { text: "Turn off", style: "destructive", onPress: () => patch({ enforce_chat: false }) },
                  ],
                );
              }}
              trackColor={{ true: colors.brand500, false: colors.border }}
            />
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Let browsers chat without a linked phone</Text>
            <Switch
              testID="admin-sim-allow-web-switch"
              value={!!p?.allow_web_without_link}
              disabled={saving || !p}
              onValueChange={(v) => patch({ allow_web_without_link: v })}
              trackColor={{ true: colors.brand500, false: colors.border }}
            />
          </View>
          <Text style={styles.meta}>Required level: {p?.required_level || "—"}</Text>
          <Text style={styles.meta}>
            Number confirmation provider: {p?.number_proof_available ? "configured" : "not configured"}
          </Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Numbers</Text>
          <Row label="Users" value={t?.users} />
          <Row label="Phones checked" value={t?.bindings} />
          <Row label="Numbers confirmed" value={t?.number_verified} />
          <Row label="Needs re-check" value={t?.needs_revalidation} />
          <Row label="Rejected attempts" value={t?.rejected_attempts} />
          {Object.entries(t?.by_sim_state || {}).map(([k, v]) => (
            <Row key={k} label={k} value={v} />
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Recent security events</Text>
          {(data?.recent_events || []).length === 0 && <Text style={styles.meta}>Nothing recorded yet.</Text>}
          {(data?.recent_events || []).map((e) => (
            <View key={e.id} style={styles.event}>
              <Feather
                name={e.result === "ok" ? "check" : "x"}
                size={14}
                color={e.result === "ok" ? colors.success : colors.error}
              />
              <Text style={styles.eventText}>
                {e.event} · {e.result}
                {e.detail ? ` · ${e.detail}` : ""}
              </Text>
            </View>
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardTitle}>What this proves</Text>
          {(data?.notes || []).map((n) => (
            <Text key={n} style={styles.meta}>
              • {n}
            </Text>
          ))}
        </View>

        {loading && !data && <ActivityIndicator color={colors.primary} />}
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, value }: { label: string; value?: number }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value ?? "—"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    backgroundColor: colors.primary,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.screen,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  backBtn: { width: 44, height: 44, alignItems: "flex-start", justifyContent: "center" },
  headerTitle: { color: colors.primaryFg, fontSize: 18, fontWeight: "700" },
  body: { padding: spacing.screen, gap: spacing.md, paddingBottom: spacing.xl },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  cardTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  rowLabel: { fontSize: 14, color: colors.textMain, flex: 1 },
  rowValue: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  meta: { fontSize: 13, color: colors.textMuted, lineHeight: 19 },
  event: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  eventText: { fontSize: 12, color: colors.textMuted, flex: 1 },
  warnBox: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: spacing.md },
  warnText: { fontSize: 13, color: colors.textMain, lineHeight: 19 },
  err: { fontSize: 14, color: colors.error },
});
