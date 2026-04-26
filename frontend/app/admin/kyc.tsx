import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity, Modal, TextInput, Alert, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type KYCUser = {
  id: string;
  name: string;
  email: string;
  kyc_status: string;
  kyc_full_name?: string;
  kyc_aadhaar?: string;
  kyc_pan?: string;
  kyc_submitted_at?: string;
  kyc_reject_reason?: string;
};

export default function AdminKYC() {
  const router = useRouter();
  const [items, setItems] = useState<KYCUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<"pending" | "approved" | "rejected">("pending");
  const [rejectFor, setRejectFor] = useState<KYCUser | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<KYCUser[]>(`/admin/kyc?status=${tab}`);
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [tab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const approve = async (u: KYCUser) => {
    setBusy(u.id);
    try {
      await api.post(`/admin/kyc/${u.id}/approve`);
      await load();
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally { setBusy(null); }
  };

  const submitReject = async () => {
    if (!rejectFor || !reason.trim()) return;
    setBusy(rejectFor.id);
    try {
      await api.post(`/admin/kyc/${rejectFor.id}/reject`, { reason: reason.trim() });
      setRejectFor(null);
      setReason("");
      await load();
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally { setBusy(null); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="kyc-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>KYC review</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={styles.tabs}>
        {(["pending", "approved", "rejected"] as const).map((t) => (
          <TouchableOpacity key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.tabActive]} testID={`kyc-tab-${t}`}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>{t.toUpperCase()}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`kyc-${item.id}`}>
              <View style={styles.cardTop}>
                <View>
                  <Text style={styles.cardName}>{item.name}</Text>
                  <Text style={styles.cardEmail}>{item.email}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: item.kyc_status === "approved" ? colors.success : item.kyc_status === "rejected" ? "#B3261E" : colors.warning }]}>
                  <Text style={styles.pillText}>{item.kyc_status.toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.divider} />
              <View>
                <Text style={styles.kvLabel}>Full name</Text>
                <Text style={styles.kvValue}>{item.kyc_full_name || "—"}</Text>
                <Text style={styles.kvLabel}>Aadhaar</Text>
                <Text style={styles.kvValue}>{item.kyc_aadhaar || "—"}</Text>
                <Text style={styles.kvLabel}>PAN</Text>
                <Text style={styles.kvValue}>{item.kyc_pan || "—"}</Text>
                {item.kyc_submitted_at ? <Text style={styles.metaText}>Submitted: {new Date(item.kyc_submitted_at).toLocaleString()}</Text> : null}
                {item.kyc_reject_reason ? <Text style={styles.rejectText}>Rejected: {item.kyc_reject_reason}</Text> : null}
              </View>
              {item.kyc_status === "pending" && (
                <View style={styles.actions}>
                  <TouchableOpacity onPress={() => setRejectFor(item)} style={[styles.actionBtn, { backgroundColor: colors.surfaceMuted }]} testID={`kyc-reject-${item.id}`}>
                    <Feather name="x" size={16} color={colors.textMain} />
                    <Text style={{ color: colors.textMain, fontWeight: "700" }}>Reject</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => approve(item)} disabled={busy === item.id} style={[styles.actionBtn, { backgroundColor: colors.primary }, busy === item.id && { opacity: 0.5 }]} testID={`kyc-approve-${item.id}`}>
                    {busy === item.id ? <ActivityIndicator color={colors.primaryFg} /> : (
                      <>
                        <Feather name="check" size={16} color={colors.primaryFg} />
                        <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Approve</Text>
                      </>
                    )}
                  </TouchableOpacity>
                </View>
              )}
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No {tab} KYC submissions</Text>}
        />
      )}

      <Modal visible={!!rejectFor} transparent animationType="slide" onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Reject KYC</Text>
            <Text style={styles.modalSub}>{rejectFor?.name} · {rejectFor?.email}</Text>
            <TextInput
              testID="kyc-reject-reason"
              value={reason}
              onChangeText={setReason}
              placeholder="Enter rejection reason"
              placeholderTextColor={colors.textMuted}
              style={styles.modalInput}
              multiline
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => { setRejectFor(null); setReason(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={submitReject} disabled={!reason.trim() || !!busy} style={[styles.modalBtn, { backgroundColor: "#B3261E" }, (!reason.trim() || !!busy) && { opacity: 0.5 }]} testID="kyc-reject-submit">
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "700" }}>Reject</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  tabs: { flexDirection: "row", marginHorizontal: spacing.screen, backgroundColor: colors.surfaceMuted, borderRadius: 99, padding: 4, gap: 4, marginBottom: 8 },
  tab: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 99 },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 11, fontWeight: "700", color: colors.textMuted, letterSpacing: 1 },
  tabTextActive: { color: colors.primaryFg },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 10 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  cardName: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  cardEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  pillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 12 },
  kvLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "600", marginTop: 6 },
  kvValue: { fontSize: 14, color: colors.textMain, fontWeight: "700" },
  metaText: { fontSize: 11, color: colors.textMuted, marginTop: 8 },
  rejectText: { fontSize: 12, color: "#B3261E", marginTop: 6, fontStyle: "italic" },
  actions: { flexDirection: "row", gap: 8, marginTop: 14 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: radii.button },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  modalSub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 16 },
  modalInput: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain, minHeight: 80, textAlignVertical: "top" },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});
