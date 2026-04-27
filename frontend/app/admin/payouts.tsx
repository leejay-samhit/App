import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Withdrawal = {
  id: string;
  user_name: string;
  user_email: string;
  amount: number;
  status: "pending" | "approved" | "processing" | "success" | "rejected";
  upi_id?: string | null;
  bank_account?: string | null;
  ifsc?: string | null;
  created_at: string;
  estimated_completion_at?: string | null;
  completed_at?: string | null;
};

export default function AdminPayouts() {
  const [items, setItems] = useState<Withdrawal[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<"pending" | "processing" | "success" | "rejected">("pending");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Withdrawal[]>(`/admin/withdrawals?status=${tab}`);
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [tab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const action = async (id: string, type: "approve" | "reject" | "complete") => {
    try {
      await api.post(`/admin/withdrawals/${id}/${type}`);
      await load();
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    }
  };

  const statusColor = (s: string) =>
    s === "success" || s === "approved" ? colors.success
    : s === "rejected" ? "#B3261E"
    : s === "processing" ? colors.brand500
    : colors.warning;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.overline}>ADMIN · FINANCE</Text>
        <Text style={styles.h1}>Withdrawals</Text>
        <View style={styles.tabs}>
          {(["pending", "processing", "success", "rejected"] as const).map((t) => (
            <TouchableOpacity key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.tabActive]} testID={`payouts-tab-${t}`}>
              <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>{t.toUpperCase()}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 0, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`payout-${item.id}`}>
              <View style={styles.cardTop}>
                <View>
                  <Text style={styles.amount}>{formatINR(item.amount)}</Text>
                  <Text style={styles.subText}>{item.user_name} · {item.user_email}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: statusColor(item.status) }]}>
                  <Text style={styles.pillText}>{item.status.toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.divider} />
              <View>
                {item.upi_id ? <Text style={styles.metaText}>UPI: <Text style={styles.bold}>{item.upi_id}</Text></Text> : null}
                {item.bank_account ? <Text style={styles.metaText}>Bank: <Text style={styles.bold}>{item.bank_account}</Text> ({item.ifsc})</Text> : null}
                <Text style={styles.metaText}>Requested: {new Date(item.created_at).toLocaleString()}</Text>
                {item.estimated_completion_at && <Text style={styles.metaText}>ETA: {new Date(item.estimated_completion_at).toLocaleString()}</Text>}
                {item.completed_at && <Text style={styles.metaText}>Paid: {new Date(item.completed_at).toLocaleString()}</Text>}
              </View>
              {item.status === "pending" && (
                <View style={styles.actions}>
                  <TouchableOpacity onPress={() => action(item.id, "reject")} style={[styles.actionBtn, { backgroundColor: colors.surfaceMuted }]} testID={`payout-reject-${item.id}`}>
                    <Feather name="x" size={16} color={colors.textMain} />
                    <Text style={{ color: colors.textMain, fontWeight: "700" }}>Reject</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => action(item.id, "approve")} style={[styles.actionBtn, { backgroundColor: colors.primary }]} testID={`payout-approve-${item.id}`}>
                    <Feather name="check" size={16} color={colors.primaryFg} />
                    <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Approve</Text>
                  </TouchableOpacity>
                </View>
              )}
              {item.status === "processing" && (
                <View style={styles.actions}>
                  <TouchableOpacity onPress={() => action(item.id, "complete")} style={[styles.actionBtn, { backgroundColor: colors.success }]} testID={`payout-complete-${item.id}`}>
                    <Feather name="check-circle" size={16} color="#fff" />
                    <Text style={{ color: "#fff", fontWeight: "700" }}>Mark paid</Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No {tab} payouts</Text>}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { padding: spacing.screen, paddingBottom: 8 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 16 },
  tabs: { flexDirection: "row", backgroundColor: colors.surfaceMuted, borderRadius: radii.button, padding: 4, gap: 4 },
  tab: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 99 },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 11, fontWeight: "700", color: colors.textMuted, letterSpacing: 1 },
  tabTextActive: { color: colors.primaryFg },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 10 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  amount: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  subText: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  pillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 12 },
  metaText: { fontSize: 12, color: colors.textMuted, marginVertical: 2 },
  bold: { color: colors.textMain, fontWeight: "700" },
  actions: { flexDirection: "row", gap: 8, marginTop: 14 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: radii.button },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
});
