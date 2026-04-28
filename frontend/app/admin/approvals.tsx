import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity,
  Modal, TextInput, Alert, KeyboardAvoidingView, Platform, ScrollView, Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type ApprovalUser = {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  approval_status: string;
  approval_reject_category?: string | null;
  approval_reject_reason?: string | null;
  approval_reviewed_at?: string | null;
  registration_paid?: boolean;
  created_at: string;
  sponsor_email?: string | null;
  sponsor_name?: string | null;
  kyc_status?: string;
  wallet_balance?: number;
};

type ApprovalDetail = ApprovalUser & {
  kyc_aadhaar?: string | null;
  kyc_pan?: string | null;
  kyc_aadhaar_front?: string | null;
  kyc_aadhaar_back?: string | null;
  kyc_pan_image?: string | null;
  kyc_selfie?: string | null;
  extra_docs?: {
    cibil_report?: string | null;
    bank_statement?: string | null;
    income_proof?: string | null;
    other?: string | null;
    submitted_at?: string | null;
  };
  sponsor?: { id: string; name: string; email: string; referral_code: string } | null;
};

const REJECT_REASONS: { key: string; label: string; requiresRemarks?: boolean }[] = [
  { key: "payment_unsuccessful", label: "Payment unsuccessful" },
  { key: "referral_code_mistake", label: "Referral code mistake" },
  { key: "other", label: "Other (enter remarks)", requiresRemarks: true },
];

export default function AdminApprovals() {
  const router = useRouter();
  const params = useLocalSearchParams<{ focus?: string }>();
  const [tab, setTab] = useState<"pending" | "approved" | "rejected">("pending");
  const [items, setItems] = useState<ApprovalUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [detailFor, setDetailFor] = useState<ApprovalDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<ApprovalUser | null>(null);
  const [rejectCat, setRejectCat] = useState<string>("payment_unsuccessful");
  const [rejectCustom, setRejectCustom] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<ApprovalUser[]>(`/admin/approvals?status=${tab}`);
      setItems(data);
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally { setLoading(false); setRefreshing(false); }
  }, [tab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Auto-open detail when ?focus=<id> is provided
  useEffect(() => {
    if (params.focus && typeof params.focus === "string") {
      openDetail({ id: params.focus } as ApprovalUser);
      // clear param
      router.setParams({ focus: undefined } as any);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.focus]);

  const openDetail = async (u: ApprovalUser) => {
    setDetailFor(u as any);
    setDetailLoading(true);
    try {
      const { data } = await api.get<ApprovalDetail>(`/admin/approvals/${u.id}`);
      setDetailFor(data);
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
      setDetailFor(null);
    } finally { setDetailLoading(false); }
  };

  const approve = async (id: string) => {
    setBusy(id);
    try {
      await api.post(`/admin/approvals/${id}/approve`);
      setDetailFor(null);
      await load();
    } catch (e) {
      Alert.alert("Approve failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const submitReject = async () => {
    if (!rejectFor) return;
    if (rejectCat === "other" && !rejectCustom.trim()) {
      Alert.alert("Remarks required", "Please enter remarks for this category.");
      return;
    }
    setBusy(rejectFor.id);
    try {
      await api.post(`/admin/approvals/${rejectFor.id}/reject`, {
        category: rejectCat,
        reason: rejectCustom.trim() || undefined,
      });
      setRejectFor(null);
      setRejectCat("payment_unsuccessful");
      setRejectCustom("");
      setDetailFor(null);
      await load();
      Alert.alert("Rejected", "User moved to the Rejected Registrations archive.");
    } catch (e) {
      Alert.alert("Reject failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const statusColor = (s: string) =>
    s === "approved" ? colors.success : s === "rejected" ? "#B3261E" : colors.warning;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="approvals-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Approvals</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={styles.tabs}>
        {(["pending", "approved", "rejected"] as const).map((t) => (
          <TouchableOpacity key={t} onPress={() => setTab(t)} style={[styles.tab, tab === t && styles.tabActive]} testID={`approvals-tab-${t}`}>
            <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>{t.toUpperCase()}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <TouchableOpacity onPress={() => openDetail(item)} style={styles.card} testID={`approval-${item.id}`}>
              <View style={styles.cardTop}>
                <View style={styles.avatar}><Text style={styles.avatarText}>{(item.name || "?").charAt(0).toUpperCase()}</Text></View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardName}>{item.name}</Text>
                  <Text style={styles.cardEmail}>{item.email}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: statusColor(item.approval_status) }]}>
                  <Text style={styles.pillText}>{item.approval_status.toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.metaRow}>
                <Feather name="user" size={11} color={colors.textMuted} />
                <Text style={styles.metaText}>via {item.sponsor_name || item.sponsor_email || "no sponsor"}</Text>
                <Feather name="clock" size={11} color={colors.textMuted} style={{ marginLeft: 12 }} />
                <Text style={styles.metaText}>{new Date(item.created_at).toLocaleString()}</Text>
              </View>
              {!item.registration_paid && (
                <View style={styles.unpaidRow}>
                  <Feather name="alert-circle" size={11} color="#B3261E" />
                  <Text style={styles.unpaidText}>Registration unpaid</Text>
                </View>
              )}
              {item.approval_reject_reason && (
                <Text style={styles.rejectText} numberOfLines={2}>Last reason: {item.approval_reject_reason}</Text>
              )}
              {item.approval_status === "pending" && (
                <View style={styles.cardActions}>
                  <TouchableOpacity
                    onPress={(e) => { e.stopPropagation(); approve(item.id); }}
                    disabled={busy === item.id}
                    style={[styles.miniBtn, { backgroundColor: colors.primary }]}
                    testID={`approval-${item.id}-approve`}
                  >
                    {busy === item.id ? <ActivityIndicator color={colors.primaryFg} size="small" /> : (
                      <>
                        <Feather name="check" size={14} color={colors.primaryFg} />
                        <Text style={[styles.miniBtnText, { color: colors.primaryFg }]}>Approve</Text>
                      </>
                    )}
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={(e) => { e.stopPropagation(); setRejectFor(item); }}
                    style={[styles.miniBtn, { backgroundColor: "#FCE9E5" }]}
                    testID={`approval-${item.id}-reject`}
                  >
                    <Feather name="x" size={14} color="#B3261E" />
                    <Text style={[styles.miniBtnText, { color: "#B3261E" }]}>Reject</Text>
                  </TouchableOpacity>
                </View>
              )}
            </TouchableOpacity>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No {tab} users</Text>}
        />
      )}

      {/* Detail modal */}
      <Modal visible={!!detailFor} animationType="slide" onRequestClose={() => setDetailFor(null)}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setDetailFor(null)} style={styles.backBtn} testID="approvals-detail-close">
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>User review</Text>
            <View style={{ width: 40 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}>
            {detailLoading || !detailFor ? (
              <View style={[styles.center, { padding: 40 }]}><ActivityIndicator color={colors.primary} /></View>
            ) : (
              <>
                <View style={styles.detailHeader}>
                  <View style={styles.bigAvatar}><Text style={styles.bigAvatarText}>{(detailFor.name || "?").charAt(0).toUpperCase()}</Text></View>
                  <Text style={styles.detailName}>{detailFor.name}</Text>
                  <Text style={styles.detailEmail}>{detailFor.email}{detailFor.phone ? ` · ${detailFor.phone}` : ""}</Text>
                  <View style={[styles.pill, { backgroundColor: statusColor(detailFor.approval_status), marginTop: 8 }]}>
                    <Text style={styles.pillText}>{detailFor.approval_status.toUpperCase()}</Text>
                  </View>
                </View>

                <View style={styles.kvCard}>
                  <KV label="Sponsor" value={detailFor.sponsor ? `${detailFor.sponsor.name} (${detailFor.sponsor.email})` : "No sponsor"} />
                  <KV label="Sponsor code" value={detailFor.sponsor?.referral_code || "—"} />
                  <KV label="Registration paid" value={detailFor.registration_paid ? "✓ Yes" : "✗ Not paid"} />
                  <KV label="KYC status" value={(detailFor.kyc_status || "none").toUpperCase()} />
                  <KV label="Wallet balance" value={`₹${detailFor.wallet_balance ?? 0}`} />
                  <KV label="Created" value={detailFor.created_at ? new Date(detailFor.created_at).toLocaleString() : "—"} />
                  {detailFor.approval_reject_reason && <KV label="Last rejection" value={detailFor.approval_reject_reason} />}
                </View>

                {(detailFor.kyc_aadhaar || detailFor.kyc_pan) && (
                  <>
                    <Text style={styles.docHeader}>KYC IDs</Text>
                    <View style={styles.kvCard}>
                      <KV label="Full name" value={detailFor.kyc_full_name as any || "—"} />
                      <KV label="Aadhaar" value={detailFor.kyc_aadhaar || "—"} />
                      <KV label="PAN" value={detailFor.kyc_pan || "—"} />
                    </View>
                  </>
                )}

                <Text style={styles.docHeader}>KYC DOCUMENTS</Text>
                <View style={styles.docGrid}>
                  <DocCard label="Aadhaar Front" image={detailFor.kyc_aadhaar_front} onZoom={setZoom} />
                  <DocCard label="Aadhaar Back" image={detailFor.kyc_aadhaar_back} onZoom={setZoom} />
                  <DocCard label="PAN" image={detailFor.kyc_pan_image} onZoom={setZoom} />
                  <DocCard label="Selfie" image={detailFor.kyc_selfie} onZoom={setZoom} />
                </View>

                {(detailFor.extra_docs && (detailFor.extra_docs.cibil_report || detailFor.extra_docs.bank_statement || detailFor.extra_docs.income_proof || detailFor.extra_docs.other)) ? (
                  <>
                    <Text style={styles.docHeader}>ADDITIONAL DOCUMENTS</Text>
                    <View style={styles.docGrid}>
                      <DocCard label="CIBIL Report" image={detailFor.extra_docs?.cibil_report} onZoom={setZoom} />
                      <DocCard label="Bank Statement" image={detailFor.extra_docs?.bank_statement} onZoom={setZoom} />
                      <DocCard label="Income Proof" image={detailFor.extra_docs?.income_proof} onZoom={setZoom} />
                      <DocCard label="Other" image={detailFor.extra_docs?.other} onZoom={setZoom} />
                    </View>
                    {detailFor.extra_docs?.submitted_at && (
                      <Text style={styles.metaText}>Submitted: {new Date(detailFor.extra_docs.submitted_at).toLocaleString()}</Text>
                    )}
                  </>
                ) : null}

                {detailFor.approval_status === "pending" && (
                  <View style={[styles.cardActions, { marginTop: 24 }]}>
                    <TouchableOpacity
                      onPress={() => setRejectFor(detailFor)}
                      style={[styles.miniBtn, { backgroundColor: "#FCE9E5", paddingVertical: 14 }]}
                      testID="detail-reject"
                    >
                      <Feather name="x" size={16} color="#B3261E" />
                      <Text style={[styles.miniBtnText, { color: "#B3261E", fontSize: 14 }]}>Reject</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      onPress={() => approve(detailFor.id)}
                      disabled={busy === detailFor.id}
                      style={[styles.miniBtn, { backgroundColor: colors.primary, paddingVertical: 14 }]}
                      testID="detail-approve"
                    >
                      {busy === detailFor.id ? <ActivityIndicator color={colors.primaryFg} /> : (
                        <>
                          <Feather name="check" size={16} color={colors.primaryFg} />
                          <Text style={[styles.miniBtnText, { color: colors.primaryFg, fontSize: 14 }]}>Approve</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  </View>
                )}
              </>
            )}
          </ScrollView>
        </SafeAreaView>
      </Modal>

      {/* Reject modal */}
      <Modal visible={!!rejectFor} transparent animationType="slide" onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Reject {rejectFor?.name}</Text>
            <Text style={styles.modalSub}>The user will be archived to the Rejected Registrations list and removed from active users.</Text>
            <Text style={styles.fieldLabel}>Category</Text>
            {REJECT_REASONS.map((r) => (
              <TouchableOpacity key={r.key} onPress={() => setRejectCat(r.key)} style={styles.reasonRow} testID={`reject-reason-${r.key}`}>
                <View style={[styles.radio, rejectCat === r.key && styles.radioActive]}>
                  {rejectCat === r.key && <View style={styles.radioDot} />}
                </View>
                <Text style={styles.reasonText}>{r.label}</Text>
              </TouchableOpacity>
            ))}
            <Text style={[styles.fieldLabel, { marginTop: 12 }]}>
              Remarks{rejectCat === "other" ? " (required)" : " (optional)"}
            </Text>
            <TextInput
              value={rejectCustom}
              onChangeText={setRejectCustom}
              placeholder={rejectCat === "other" ? "Type the reason" : "Any additional notes"}
              placeholderTextColor={colors.textMuted}
              style={styles.input}
              multiline
              testID="reject-remarks"
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
              <TouchableOpacity onPress={() => { setRejectFor(null); setRejectCat("payment_unsuccessful"); setRejectCustom(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={submitReject}
                disabled={!!busy || (rejectCat === "other" && !rejectCustom.trim())}
                style={[styles.modalBtn, { backgroundColor: "#B3261E" }, (!!busy || (rejectCat === "other" && !rejectCustom.trim())) && { opacity: 0.5 }]}
                testID="reject-submit"
              >
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Reject & archive</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Image zoom */}
      <Modal visible={!!zoom} transparent animationType="fade" onRequestClose={() => setZoom(null)}>
        <View style={styles.zoomOverlay}>
          <TouchableOpacity onPress={() => setZoom(null)} style={styles.zoomClose}>
            <Feather name="x" size={22} color="#fff" />
          </TouchableOpacity>
          {zoom ? <Image source={{ uri: zoom }} style={styles.zoomImg} resizeMode="contain" /> : null}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.kvRow}>
      <Text style={styles.kvLabel}>{label}</Text>
      <Text style={styles.kvValue} numberOfLines={2}>{value}</Text>
    </View>
  );
}

function DocCard({ label, image, onZoom }: { label: string; image?: string | null; onZoom: (uri: string) => void }) {
  return (
    <View style={styles.docCard}>
      <Text style={styles.docLabel}>{label}</Text>
      {image ? (
        <TouchableOpacity onPress={() => onZoom(image)} activeOpacity={0.85}>
          <Image source={{ uri: image }} style={styles.docImg} resizeMode="cover" />
        </TouchableOpacity>
      ) : (
        <View style={styles.docMissing}>
          <Feather name="image" size={20} color={colors.textMuted} />
          <Text style={styles.docMissingText}>Not uploaded</Text>
        </View>
      )}
    </View>
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
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 10 },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontSize: 14, fontWeight: "800" },
  cardName: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  cardEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  pillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 10, flexWrap: "wrap" },
  metaText: { fontSize: 11, color: colors.textMuted },
  unpaidRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  unpaidText: { color: "#B3261E", fontSize: 11, fontWeight: "700" },
  rejectText: { color: "#B3261E", fontSize: 11, marginTop: 6, fontStyle: "italic" },
  cardActions: { flexDirection: "row", gap: 8, marginTop: 12 },
  miniBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 10 },
  miniBtnText: { fontSize: 12, fontWeight: "800" },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
  detailHeader: { alignItems: "center", marginBottom: 16 },
  bigAvatar: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  bigAvatarText: { color: "#fff", fontSize: 24, fontWeight: "800" },
  detailName: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  detailEmail: { fontSize: 13, color: colors.textMuted, marginTop: 4 },
  kvCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, gap: 10, marginTop: 8 },
  kvRow: { flexDirection: "row", justifyContent: "space-between", gap: 12 },
  kvLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  kvValue: { fontSize: 13, color: colors.textMain, fontWeight: "700", textAlign: "right", flexShrink: 1 },
  docHeader: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: 20, marginBottom: 10 },
  docGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  docCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 10 },
  docLabel: { fontSize: 11, fontWeight: "700", color: colors.textMain, marginBottom: 6 },
  docImg: { width: "100%", height: 110, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  docMissing: { height: 80, alignItems: "center", justifyContent: "center", gap: 4, backgroundColor: colors.surfaceMuted, borderRadius: 8 },
  docMissingText: { fontSize: 11, color: colors.textMuted },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  modalSub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 14 },
  fieldLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginTop: 8, marginBottom: 6 },
  reasonRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8 },
  radio: { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  radioActive: { borderColor: colors.primary },
  radioDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary },
  reasonText: { fontSize: 14, color: colors.textMain, fontWeight: "600" },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 12, fontSize: 14, color: colors.textMain, marginTop: 8, minHeight: 60, textAlignVertical: "top" },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
  zoomOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.95)", alignItems: "center", justifyContent: "center" },
  zoomClose: { position: "absolute", top: 50, right: 20, width: 40, height: 40, borderRadius: 20, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", zIndex: 5 },
  zoomImg: { width: "100%", height: "100%" },
});
