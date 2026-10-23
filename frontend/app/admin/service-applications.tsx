import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { useTabSwipe } from "../../src/use-swipe-pager";

type App = { id: string; user_id: string; name?: string; email?: string; phone?: string; service_name: string; service_category: string; pincode: string; charge: number; description?: string; status: string; created_at: string; reject_reason?: string };

export default function AdminServiceApplications() {
  const router = useRouter();
  const [tab, setTab] = useState<"pending" | "approved" | "rejected">("pending");
const swipe = useTabSwipe(["pending", "approved", "rejected"] as const, tab, setTab);
  const [items, setItems] = useState<App[]>([]);
  const [counts, setCounts] = useState<any>({ pending: 0, approved: 0, rejected: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<App | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/admin/service-applications?status=${tab}`);
      setItems(data.items || []);
      setCounts(data.counts || {});
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [tab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const approve = async (a: App) => {
    setBusyId(a.id);
    try { await api.post(`/admin/service-applications/${a.id}/approve`); await load(); }
    catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setBusyId(null); }
  };
  const reject = async () => {
    if (!rejectFor) return;
    setBusyId(rejectFor.id);
    try {
      await api.post(`/admin/service-applications/${rejectFor.id}/reject`, { reason: reason.trim() || null });
      setRejectFor(null);
      setReason("");
      await load();
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setBusyId(null); }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} {...swipe}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.overline}>ADMIN</Text>
          <Text style={styles.title}>Service applications</Text>
        </View>
      </View>

      <View style={styles.tabRow}>
        {(["pending", "approved", "rejected"] as const).map((t) => (
          <TouchableOpacity key={t} style={[styles.tab, tab === t && styles.tabActive]} onPress={() => setTab(t)}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>{t.toUpperCase()} ({counts[t] ?? 0})</Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
        {items.length === 0 ? (
          <View style={styles.empty}><Feather name="inbox" size={28} color={colors.textMuted} /><Text style={styles.emptyText}>No {tab} applications.</Text></View>
        ) : items.map((a) => (
          <View key={a.id} style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={{ flex: 1 }}>
                <Text style={styles.appName}>{a.name || a.email || a.user_id.slice(0, 8)}</Text>
                <Text style={styles.appEmail}>{a.email}</Text>
              </View>
              <Text style={styles.appCharge}>{formatINR(a.charge)}</Text>
            </View>
            <View style={styles.row}><Feather name="briefcase" size={12} color={colors.textMuted} /><Text style={styles.rowText}>{a.service_name} · {a.service_category}</Text></View>
            <View style={styles.row}><Feather name="map-pin" size={12} color={colors.textMuted} /><Text style={styles.rowText}>Pincode {a.pincode}</Text></View>
            {a.phone ? <View style={styles.row}><Feather name="phone" size={12} color={colors.textMuted} /><Text style={styles.rowText}>{a.phone}</Text></View> : null}
            {a.description ? <Text style={styles.desc}>{a.description}</Text> : null}
            {a.reject_reason ? <Text style={styles.rejectReason}>Rejected: {a.reject_reason}</Text> : null}
            {tab === "pending" && (
              <View style={styles.actions}>
                <TouchableOpacity style={[styles.actBtn, styles.actReject, busyId === a.id && { opacity: 0.5 }]} onPress={() => setRejectFor(a)} disabled={busyId === a.id}>
                  <Feather name="x" size={14} color={colors.error} /><Text style={[styles.actText, { color: colors.error }]}>Reject</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.actBtn, styles.actApprove, busyId === a.id && { opacity: 0.5 }]} onPress={() => approve(a)} disabled={busyId === a.id}>
                  <Feather name="check" size={14} color={colors.primaryFg} /><Text style={[styles.actText, { color: colors.primaryFg }]}>Approve</Text>
                </TouchableOpacity>
              </View>
            )}
          </View>
        ))}
      </ScrollView>

      <Modal visible={!!rejectFor} transparent animationType="slide" onRequestClose={() => setRejectFor(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Reject application?</Text>
            <TextInput style={styles.modalInput} value={reason} onChangeText={setReason} placeholder="Reason (optional)" placeholderTextColor={colors.textMuted} multiline />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]} onPress={() => setRejectFor(null)}><Text style={{ fontWeight: "700", color: colors.textMain }}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity style={[styles.modalBtn, { backgroundColor: colors.error }]} onPress={reject}><Text style={{ fontWeight: "700", color: "#fff" }}>Reject</Text></TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  overline: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  tabRow: { flexDirection: "row", gap: 6, paddingHorizontal: spacing.screen, marginBottom: 8 },
  tab: { paddingVertical: 8, paddingHorizontal: 12, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabText: { fontSize: 11, fontWeight: "700", color: colors.textMain },
  tabTextActive: { color: colors.primaryFg },
  container: { padding: spacing.screen, paddingTop: 0, paddingBottom: 60 },
  empty: { padding: 40, alignItems: "center", gap: 8 },
  emptyText: { color: colors.textMuted, marginTop: 6 },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 10 },
  cardHeader: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 },
  appName: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  appEmail: { fontSize: 12, color: colors.textMuted, marginTop: 1 },
  appCharge: { fontSize: 16, fontWeight: "800", color: colors.primary },
  row: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
  rowText: { fontSize: 12, color: colors.textMain },
  desc: { fontSize: 12, color: colors.textMuted, marginTop: 8, lineHeight: 16 },
  rejectReason: { fontSize: 11, color: colors.error, marginTop: 6, fontWeight: "600" },
  actions: { flexDirection: "row", gap: 8, marginTop: 12 },
  actBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 10 },
  actApprove: { backgroundColor: colors.primary },
  actReject: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.error },
  actText: { fontSize: 13, fontWeight: "800" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20 },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain, marginBottom: 12 },
  modalInput: { backgroundColor: colors.surfaceMuted, borderRadius: 10, padding: 12, fontSize: 13, minHeight: 80, textAlignVertical: "top", color: colors.textMain },
  modalBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, alignItems: "center" },
});
