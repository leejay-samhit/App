// Admin · Vendor Edit Requests — Nov 2026
//
// Admin lists pending vendor profile-change requests and can approve or
// reject each.  On approve, the backend applies the requested changes
// to the vendor's user doc AND cascades store_pincode/delivery_pincodes
// onto every product owned by that vendor.
import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator,
  Alert, RefreshControl, Modal, TextInput, ScrollView, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type EditRequest = {
  id: string;
  user_id: string; user_email?: string; user_name?: string; shop_name?: string;
  changes: Record<string, any>;
  current: Record<string, any>;
  note?: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  reject_reason?: string;
};

const STATUSES = ["pending", "approved", "rejected"] as const;

export default function AdminVendorEditRequests() {
  const router = useRouter();
  const [items, setItems] = useState<EditRequest[]>([]);
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("pending");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [detail, setDetail] = useState<EditRequest | null>(null);
  const [rejectFor, setRejectFor] = useState<EditRequest | null>(null);
  const [reason, setReason] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: EditRequest[] }>("/admin/vendor-edit-requests", { params: { status } });
      setItems(data.items || []);
    } catch (e) { Alert.alert("Couldn't load", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [status]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onApprove = async (r: EditRequest) => {
    setBusy(r.id);
    try {
      await api.post(`/admin/vendor-edit-requests/${r.id}/approve`);
      setDetail(null); await load();
    } catch (e) { Alert.alert("Couldn't approve", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const onConfirmReject = async () => {
    if (!rejectFor) return;
    setBusy(rejectFor.id);
    try {
      await api.post(`/admin/vendor-edit-requests/${rejectFor.id}/reject`, { reason: reason.trim() });
      setRejectFor(null); setDetail(null); setReason(""); await load();
    } catch (e) { Alert.alert("Couldn't reject", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const renderChangeRow = (key: string, before: any, after: any) => (
    <View key={key} style={styles.diffRow}>
      <Text style={styles.diffKey}>{key}</Text>
      <View style={styles.diffCells}>
        <View style={[styles.diffCell, { backgroundColor: "#FEF2F2" }]}>
          <Text style={styles.diffLabel}>WAS</Text>
          <Text style={styles.diffValue} numberOfLines={3}>{formatVal(before)}</Text>
        </View>
        <Feather name="arrow-right" size={12} color={colors.textMuted} />
        <View style={[styles.diffCell, { backgroundColor: "#F0FDF4" }]}>
          <Text style={styles.diffLabel}>NEW</Text>
          <Text style={styles.diffValue} numberOfLines={3}>{formatVal(after)}</Text>
        </View>
      </View>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Vendor Edit Requests</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={styles.tabsRow}>
        {STATUSES.map((s) => (
          <TouchableOpacity key={s} onPress={() => setStatus(s)} style={[styles.tab, status === s && styles.tabActive]} testID={`ver-tab-${s}`}>
            <Text style={[styles.tabText, status === s && styles.tabTextActive]}>{s[0].toUpperCase() + s.slice(1)}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); }} tintColor={colors.primary} />}
          renderItem={({ item }) => (
            <TouchableOpacity onPress={() => setDetail(item)} style={styles.card} activeOpacity={0.85}>
              <View style={{ flex: 1 }}>
                <Text style={styles.shop}>{item.shop_name || "Vendor"}</Text>
                <Text style={styles.user}>{item.user_name || item.user_email}</Text>
                <Text style={styles.meta}>{Object.keys(item.changes || {}).length} field(s) · {new Date(item.created_at).toLocaleDateString()}</Text>
                {item.note ? <Text style={styles.note} numberOfLines={2}>&ldquo;{item.note}&rdquo;</Text> : null}
                {item.reject_reason ? <Text style={[styles.note, { color: "#B3261E" }]} numberOfLines={2}>Rejected: {item.reject_reason}</Text> : null}
              </View>
              {item.status === "pending" ? (
                <View style={{ flexDirection: "row", gap: 6 }}>
                  <TouchableOpacity onPress={() => onApprove(item)} disabled={busy === item.id} style={[styles.actionBtn, { backgroundColor: "#1F6B44" }]}>
                    {busy === item.id ? <ActivityIndicator color="#fff" size="small" /> : <Feather name="check" size={16} color="#fff" />}
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => setRejectFor(item)} disabled={busy === item.id} style={[styles.actionBtn, { backgroundColor: "#B3261E" }]}>
                    <Feather name="x" size={16} color="#fff" />
                  </TouchableOpacity>
                </View>
              ) : null}
            </TouchableOpacity>
          )}
          ListEmptyComponent={<View style={styles.empty}><Feather name="check-circle" size={40} color={colors.textMuted} /><Text style={styles.emptyText}>No {status} edit requests</Text></View>}
        />
      )}

      {/* Detail modal */}
      <Modal visible={!!detail} animationType="slide" onRequestClose={() => setDetail(null)}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setDetail(null)} style={styles.iconBtn}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
            <Text style={styles.title}>Review changes</Text>
            <View style={{ width: 40 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}>
            {detail ? (
              <>
                <Text style={styles.shop}>{detail.shop_name}</Text>
                <Text style={styles.user}>{detail.user_email}</Text>
                {detail.note ? (
                  <View style={styles.noteBox}>
                    <Feather name="message-square" size={13} color="#1F5E9E" />
                    <Text style={styles.noteBoxText}>{detail.note}</Text>
                  </View>
                ) : null}
                <Text style={styles.section}>REQUESTED CHANGES</Text>
                {Object.keys(detail.changes || {}).map((k) =>
                  renderChangeRow(k, (detail.current || {})[k], (detail.changes || {})[k]),
                )}
                {detail.status === "pending" ? (
                  <View style={styles.detailActions}>
                    <TouchableOpacity onPress={() => setRejectFor(detail)} style={[styles.detailBtn, { backgroundColor: "#B3261E" }]}>
                      <Feather name="x" size={16} color="#fff" /><Text style={styles.detailBtnText}>  Reject</Text>
                    </TouchableOpacity>
                    <TouchableOpacity onPress={() => onApprove(detail)} disabled={busy === detail.id} style={[styles.detailBtn, { backgroundColor: colors.primary }]}>
                      {busy === detail.id ? <ActivityIndicator color="#fff" size="small" /> : <><Feather name="check" size={16} color="#fff" /><Text style={styles.detailBtnText}>  Approve</Text></>}
                    </TouchableOpacity>
                  </View>
                ) : null}
              </>
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </Modal>

      {/* Reject reason modal */}
      <Modal visible={!!rejectFor} animationType="fade" transparent onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.rejScrim}>
          <View style={styles.rejCard}>
            <Text style={styles.rejTitle}>Reject request</Text>
            <TextInput
              value={reason}
              onChangeText={setReason}
              placeholder="Reason (will be shown to the vendor)"
              placeholderTextColor={colors.textMuted}
              multiline
              style={styles.rejInput}
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <TouchableOpacity onPress={() => { setRejectFor(null); setReason(""); }} style={[styles.detailBtn, { flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border }]}>
                <Text style={[styles.detailBtnText, { color: colors.textMain }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onConfirmReject} disabled={!reason.trim() || !!busy} style={[styles.detailBtn, { flex: 1, backgroundColor: "#B3261E" }, (!reason.trim() || !!busy) && { opacity: 0.5 }]}>
                <Text style={[styles.detailBtnText, { color: "#fff" }]}>Confirm reject</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

function formatVal(v: any): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  tabsRow: { flexDirection: "row", padding: 8, gap: 6, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { flex: 1, paddingVertical: 8, borderRadius: 999, alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  tabTextActive: { color: "#fff" },
  card: { flexDirection: "row", alignItems: "center", gap: 10, padding: 14, backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  shop: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  user: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  note: { fontSize: 12, color: colors.textMain, marginTop: 6, fontStyle: "italic" },
  actionBtn: { width: 36, height: 36, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  empty: { alignItems: "center", marginTop: 60, gap: 8 },
  emptyText: { color: colors.textMuted, fontSize: 13, fontWeight: "600" },
  section: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1.5, marginTop: 18, marginBottom: 8 },
  noteBox: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, backgroundColor: "#E6F1FB", borderRadius: 10, marginTop: 10 },
  noteBoxText: { flex: 1, fontSize: 12.5, color: colors.textMain, lineHeight: 17 },
  diffRow: { marginBottom: 10 },
  diffKey: { fontSize: 12, fontWeight: "800", color: colors.textMuted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 },
  diffCells: { flexDirection: "row", alignItems: "center", gap: 6 },
  diffCell: { flex: 1, padding: 8, borderRadius: 8 },
  diffLabel: { fontSize: 9, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.5 },
  diffValue: { fontSize: 12, color: colors.textMain, fontWeight: "700", marginTop: 3 },
  detailActions: { flexDirection: "row", gap: 8, marginTop: 24 },
  detailBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", paddingVertical: 13, borderRadius: radii.button },
  detailBtnText: { color: "#fff", fontSize: 14, fontWeight: "800" },
  rejScrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: 20 },
  rejCard: { backgroundColor: colors.background, borderRadius: 16, padding: 16 },
  rejTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginBottom: 10 },
  rejInput: { minHeight: 90, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 10, textAlignVertical: "top", color: colors.textMain },
});
