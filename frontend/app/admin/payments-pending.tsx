// Admin / Finance — review pending UPI manual payments. Approve fires the
// same activation flow as Razorpay verify (commission cascade + archive).
import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  RefreshControl,
  TextInput,
  Modal,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Payment = {
  id: string;
  user_id: string;
  user_name: string;
  user_email: string;
  user_phone?: string;
  user_referral_code?: string;
  user_referred_by?: string;
  amount: number;
  utr: string;
  app_used: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  created_at: string;
  note?: string | null;
};

const STATUS_TABS: { key: "PENDING" | "APPROVED" | "REJECTED"; label: string }[] = [
  { key: "PENDING",  label: "Pending"  },
  { key: "APPROVED", label: "Approved" },
  { key: "REJECTED", label: "Rejected" },
];

export default function AdminPendingPayments() {
  const router = useRouter();
  const [status, setStatus] = useState<"PENDING" | "APPROVED" | "REJECTED">("PENDING");
  const [items, setItems] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<Payment | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: Payment[] }>(`/admin/payments/pending?status=${status}`);
      setItems(data.items || []);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [status]);
  useEffect(() => { load(); }, [load]);

  const approve = (p: Payment) => {
    Alert.alert(
      "Approve payment?",
      `Activating ${p.user_name} (${p.user_email}) for ${formatINR(p.amount)}.\nUTR · ${p.utr}\n\nThis will fire the L1–L10 commission cascade and cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Approve",
          style: "default",
          onPress: async () => {
            setBusyId(p.id);
            try {
              await api.post(`/admin/payments/${p.id}/approve`, { note: "" });
              Alert.alert("Approved", `${p.user_name} is now active.`);
              await load();
            } catch (e) { Alert.alert("Failed", formatApiError(e)); }
            finally { setBusyId(null); }
          },
        },
      ],
    );
  };

  const submitReject = async () => {
    if (!rejectFor) return;
    if (rejectReason.trim().length < 3) { Alert.alert("Reason required", "Tell the user why (min 3 chars)."); return; }
    setBusyId(rejectFor.id);
    try {
      await api.post(`/admin/payments/${rejectFor.id}/reject`, { reason: rejectReason.trim() });
      setRejectFor(null);
      setRejectReason("");
      await load();
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setBusyId(null); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={22} color={colors.textMain} /></TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>UPI Payments</Text>
          <Text style={styles.subtle}>Manual approval queue</Text>
        </View>
      </View>

      {/* Status tabs */}
      <View style={styles.tabRow}>
        {STATUS_TABS.map((t) => {
          const active = t.key === status;
          return (
            <TouchableOpacity
              key={t.key}
              onPress={() => setStatus(t.key)}
              style={[styles.tab, active && styles.tabActive]}
              testID={`payments-tab-${t.key}`}
            >
              <Text style={[styles.tabLabel, active && { color: "#fff" }]}>{t.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.center}>
          <Feather name="inbox" size={36} color={colors.textMuted} />
          <Text style={styles.emptyText}>No {status.toLowerCase()} payments</Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {items.map((p) => (
            <View key={p.id} style={styles.card}>
              <View style={styles.cardHeader}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.userName} numberOfLines={1}>{p.user_name}</Text>
                  <Text style={styles.userMeta} numberOfLines={1}>{p.user_email} · {p.user_phone || "no phone"}</Text>
                  <Text style={styles.userMeta} numberOfLines={1}>code {p.user_referral_code} · ref {p.user_referred_by || "—"}</Text>
                </View>
                <View style={styles.amountBox}>
                  <Text style={styles.amount}>{formatINR(p.amount)}</Text>
                  <Text style={styles.amountSub}>{p.app_used.toUpperCase()}</Text>
                </View>
              </View>

              <View style={styles.utrRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.utrLabel}>UTR / REFERENCE</Text>
                  <Text style={styles.utrValue} selectable>{p.utr}</Text>
                </View>
                <Text style={styles.dateText}>{new Date(p.created_at).toLocaleString()}</Text>
              </View>

              {p.note ? (
                <View style={styles.noteBox}>
                  <Feather name="message-circle" size={12} color={colors.textMuted} />
                  <Text style={styles.noteText} numberOfLines={4}>{p.note}</Text>
                </View>
              ) : null}

              {p.status === "PENDING" ? (
                <View style={styles.actionsRow}>
                  <TouchableOpacity
                    onPress={() => approve(p)}
                    disabled={busyId === p.id}
                    style={[styles.approveBtn, busyId === p.id && { opacity: 0.5 }]}
                    testID={`approve-${p.id}`}
                  >
                    <Feather name="check" size={14} color="#fff" />
                    <Text style={styles.approveText}>{busyId === p.id ? "Approving…" : "Approve & activate"}</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => { setRejectFor(p); setRejectReason(""); }}
                    disabled={busyId === p.id}
                    style={styles.rejectBtn}
                    testID={`reject-${p.id}`}
                  >
                    <Feather name="x" size={14} color="#B3261E" />
                    <Text style={styles.rejectText}>Reject</Text>
                  </TouchableOpacity>
                </View>
              ) : (
                <View style={[styles.statusBadge, p.status === "APPROVED" ? styles.badgeOK : styles.badgeBad]}>
                  <Feather name={p.status === "APPROVED" ? "check-circle" : "x-circle"} size={12} color={p.status === "APPROVED" ? "#0F766E" : "#B3261E"} />
                  <Text style={[styles.statusBadgeText, { color: p.status === "APPROVED" ? "#0F766E" : "#B3261E" }]}>{p.status}</Text>
                </View>
              )}
            </View>
          ))}
        </ScrollView>
      )}

      {/* Reject reason modal */}
      <Modal visible={!!rejectFor} transparent animationType="slide" onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <View style={styles.modalBg}>
            <View style={styles.modalSheet}>
              <View style={styles.modalHandle} />
              <Text style={styles.modalTitle}>Reject payment</Text>
              <Text style={styles.modalSub}>{rejectFor?.user_name} · UTR {rejectFor?.utr}</Text>
              <TextInput
                value={rejectReason}
                onChangeText={setRejectReason}
                multiline
                maxLength={500}
                placeholder="Reason (the user will see this)"
                placeholderTextColor={colors.textMuted}
                style={styles.rejectInput}
                testID="reject-reason"
              />
              <TouchableOpacity onPress={submitReject} disabled={!!busyId} style={[styles.rejectConfirmBtn, !!busyId && { opacity: 0.5 }]} testID="reject-confirm">
                <Text style={styles.rejectConfirmText}>{busyId ? "Rejecting…" : "Reject payment"}</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setRejectFor(null)} style={{ paddingVertical: 10, alignItems: "center" }}>
                <Text style={{ color: colors.textMuted, fontWeight: "700" }}>Cancel</Text>
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.screen, paddingVertical: 8, gap: 12 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  subtle: { fontSize: 11, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.5 },
  tabRow: { flexDirection: "row", paddingHorizontal: spacing.screen, gap: 6, paddingBottom: 10 },
  tab: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabLabel: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  emptyText: { fontSize: 13, color: colors.textMuted, fontWeight: "700" },
  list: { padding: spacing.screen, gap: 12, paddingBottom: 60 },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14 },
  cardHeader: { flexDirection: "row", gap: 10 },
  userName: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  userMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2, fontVariant: ["tabular-nums"] },
  amountBox: { alignItems: "flex-end" },
  amount: { fontSize: 18, fontWeight: "900", color: colors.primary, fontVariant: ["tabular-nums"] },
  amountSub: { fontSize: 9, color: colors.textMuted, fontWeight: "800", letterSpacing: 0.5, marginTop: 2 },
  utrRow: { flexDirection: "row", alignItems: "flex-end", marginTop: 10, paddingTop: 10, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  utrLabel: { fontSize: 9, color: colors.textMuted, fontWeight: "800", letterSpacing: 0.5 },
  utrValue: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginTop: 2, fontVariant: ["tabular-nums"] },
  dateText: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  noteBox: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: 10, padding: 10, borderRadius: 10, backgroundColor: colors.surfaceMuted },
  noteText: { flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 17 },
  actionsRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  approveBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: "#0F766E", paddingVertical: 11, borderRadius: 999 },
  approveText: { color: "#fff", fontWeight: "900", fontSize: 12, letterSpacing: 0.3 },
  rejectBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 16, paddingVertical: 11, borderRadius: 999, borderWidth: 1, borderColor: "#B3261E44", backgroundColor: "#FFE4E4" },
  rejectText: { color: "#B3261E", fontWeight: "900", fontSize: 12 },
  statusBadge: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, marginTop: 10 },
  badgeOK:  { backgroundColor: "#E6F8F1" },
  badgeBad: { backgroundColor: "#FFE4E4" },
  statusBadgeText: { fontSize: 10, fontWeight: "900", letterSpacing: 0.5 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.background, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 18, paddingTop: 8, paddingBottom: 24 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 10 },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  modalSub: { fontSize: 12, color: colors.textMuted, fontWeight: "700", marginTop: 4 },
  rejectInput: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 12, minHeight: 90, marginTop: 12, fontSize: 13, color: colors.textMain, textAlignVertical: "top", backgroundColor: colors.surface },
  rejectConfirmBtn: { marginTop: 14, paddingVertical: 13, borderRadius: 999, backgroundColor: "#B3261E", alignItems: "center" },
  rejectConfirmText: { color: "#fff", fontWeight: "900", fontSize: 13, letterSpacing: 0.3 },
});
