import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, Alert, RefreshControl, Modal, TextInput, ScrollView, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type Application = {
  id: string; user_id: string; user_email: string; user_name: string;
  shop_name: string; gst_number?: string; pan_number?: string;
  bank_name?: string; bank_account?: string; bank_ifsc?: string;
  description?: string; status: string; rejection_reason?: string;
  created_at: string;
};

const STATUSES = ["pending", "approved", "rejected"] as const;

export default function AdminVendorApps() {
  const router = useRouter();
  const [items, setItems] = useState<Application[]>([]);
  const [counts, setCounts] = useState<{ pending: number; approved: number; rejected: number; suspended: number }>({ pending: 0, approved: 0, rejected: 0, suspended: 0 });
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("pending");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<Application | null>(null);
  const [reason, setReason] = useState("");
  const [detail, setDetail] = useState<Application | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: Application[]; counts: any }>("/admin/vendor-applications", { params: { status } });
      setItems(data.items || []); setCounts(data.counts);
    } catch (e) { Alert.alert("Couldn't load", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [status]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onApprove = async (a: Application) => {
    setBusyId(a.id);
    try { await api.post(`/admin/vendor-applications/${a.id}/approve`); await load(); }
    catch (e) { Alert.alert("Couldn't approve", formatApiError(e)); }
    finally { setBusyId(null); }
  };

  const onConfirmReject = async () => {
    if (!rejectFor) return;
    setBusyId(rejectFor.id);
    try {
      await api.post(`/admin/vendor-applications/${rejectFor.id}/reject`, { reason: reason.trim() });
      setRejectFor(null); setReason(""); await load();
    } catch (e) { Alert.alert("Couldn't reject", formatApiError(e)); }
    finally { setBusyId(null); }
  };

  const renderItem = ({ item }: { item: Application }) => (
    <View style={styles.card}>
      <TouchableOpacity onPress={() => setDetail(item)} style={{ flex: 1 }}>
        <Text style={styles.shop}>{item.shop_name}</Text>
        <Text style={styles.user}>{item.user_name || item.user_email}</Text>
        <Text style={styles.meta}>{new Date(item.created_at).toLocaleDateString()}{item.gst_number ? ` · GST ${item.gst_number}` : ""}</Text>
        {item.status === "rejected" && item.rejection_reason ? <Text style={styles.rejReason} numberOfLines={2}>Reason: {item.rejection_reason}</Text> : null}
      </TouchableOpacity>
      {item.status === "pending" && (
        <View style={{ flexDirection: "row", gap: 6 }}>
          <TouchableOpacity onPress={() => onApprove(item)} disabled={busyId === item.id} style={[styles.actionBtn, { backgroundColor: "#1F6B44" }]} testID={`vapp-approve-${item.id}`}>
            {busyId === item.id ? <ActivityIndicator color="#fff" size="small" /> : <Feather name="check" size={16} color="#fff" />}
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setRejectFor(item)} disabled={busyId === item.id} style={[styles.actionBtn, { backgroundColor: "#B3261E" }]} testID={`vapp-reject-${item.id}`}>
            <Feather name="x" size={16} color="#fff" />
          </TouchableOpacity>
        </View>
      )}
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Vendor Applications</Text>
        <TouchableOpacity onPress={() => router.push("/admin/vendors" as any)} style={styles.iconBtn} testID="vapp-vendors"><Feather name="users" size={20} color={colors.primary} /></TouchableOpacity>
      </View>

      <View style={styles.tabsRow}>
        {STATUSES.map((s) => (
          <TouchableOpacity key={s} onPress={() => setStatus(s)} style={[styles.tabChip, status === s && styles.tabChipActive]} testID={`vapp-tab-${s}`}>
            <Text style={[styles.tabChipText, status === s && { color: colors.primaryFg }]}>{s} ({(counts as any)[s] || 0})</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.center}><Feather name="inbox" size={44} color={colors.textMuted} /><Text style={styles.emptyText}>No {status} applications.</Text></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(it) => it.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        />
      )}

      {/* Reject modal */}
      <Modal visible={!!rejectFor} animationType="slide" transparent onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView style={styles.modalBackdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Reject application?</Text>
            <Text style={styles.modalBody}>{rejectFor?.shop_name} · {rejectFor?.user_email}</Text>
            <TextInput style={[styles.input, { marginTop: 12 }]} value={reason} onChangeText={setReason} placeholder="Reason for rejection (optional)" placeholderTextColor={colors.textMuted} multiline />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 16 }}>
              <TouchableOpacity onPress={() => { setRejectFor(null); setReason(""); }} style={[styles.modalBtn, { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border }]}><Text style={[styles.modalBtnText, { color: colors.textMain }]}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onConfirmReject} disabled={busyId === rejectFor?.id} style={[styles.modalBtn, { backgroundColor: "#B3261E" }]} testID="vapp-reject-confirm">
                {busyId === rejectFor?.id ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnText, { color: "#fff" }]}>Reject</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Detail modal */}
      <Modal visible={!!detail} animationType="slide" onRequestClose={() => setDetail(null)}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setDetail(null)} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
            <Text style={styles.title}>Application detail</Text>
            <View style={{ width: 40 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen }}>
            {detail && (
              <>
                <DetailRow label="Shop name" value={detail.shop_name} />
                <DetailRow label="Applicant" value={`${detail.user_name || ""} \u00b7 ${detail.user_email}`} />
                <DetailRow label="Status" value={detail.status} />
                {detail.gst_number ? <DetailRow label="GST" value={detail.gst_number} /> : null}
                {detail.pan_number ? <DetailRow label="PAN" value={detail.pan_number} /> : null}
                {detail.bank_name ? <DetailRow label="Bank" value={detail.bank_name} /> : null}
                {detail.bank_account ? <DetailRow label="Account #" value={detail.bank_account} /> : null}
                {detail.bank_ifsc ? <DetailRow label="IFSC" value={detail.bank_ifsc} /> : null}
                {detail.description ? <DetailRow label="Description" value={detail.description} /> : null}
                <DetailRow label="Submitted" value={new Date(detail.created_at).toLocaleString()} />
                {detail.status === "rejected" && detail.rejection_reason ? <DetailRow label="Rejection reason" value={detail.rejection_reason} /> : null}
              </>
            )}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={styles.detLabel}>{label}</Text>
      <Text style={styles.detValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  tabsRow: { flexDirection: "row", padding: spacing.screen, gap: 6 },
  tabChip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 18, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  tabChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain, textTransform: "capitalize" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  emptyText: { color: colors.textMuted, marginTop: 8 },
  card: { flexDirection: "row", alignItems: "center", padding: 12, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, gap: 8 },
  shop: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  user: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  rejReason: { fontSize: 11, color: "#B3261E", marginTop: 6, fontStyle: "italic" },
  actionBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.background, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: spacing.screen },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  modalBody: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  modalBtn: { flex: 1, paddingVertical: 12, borderRadius: radii.button, alignItems: "center" },
  modalBtnText: { fontWeight: "800", fontSize: 13 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 12, minHeight: 80, textAlignVertical: "top", color: colors.textMain },
  detLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginBottom: 4 },
  detValue: { fontSize: 14, color: colors.textMain, fontWeight: "600" },
});
