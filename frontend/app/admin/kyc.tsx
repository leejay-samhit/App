import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity,
  Modal, TextInput, Alert, KeyboardAvoidingView, Platform, Image, ScrollView,
} from "react-native";
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
  has_aadhaar_front?: boolean;
  has_aadhaar_back?: boolean;
  has_pan_image?: boolean;
  has_selfie?: boolean;
};

type KYCDetail = KYCUser & {
  aadhaar_front?: string | null;
  aadhaar_back?: string | null;
  pan_image?: string | null;
  selfie?: string | null;
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
  const [detailFor, setDetailFor] = useState<KYCDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [zoom, setZoom] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<KYCUser[]>(`/admin/kyc?status=${tab}`);
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [tab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openDetail = async (u: KYCUser) => {
    setDetailFor({ ...u });
    setDetailLoading(true);
    try {
      const { data } = await api.get<KYCDetail>(`/admin/kyc/${u.id}`);
      setDetailFor(data);
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
      setDetailFor(null);
    } finally { setDetailLoading(false); }
  };

  const approve = async (u: KYCUser) => {
    setBusy(u.id);
    try {
      await api.post(`/admin/kyc/${u.id}/approve`);
      setDetailFor(null);
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
      setDetailFor(null);
      await load();
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally { setBusy(null); }
  };

  const docCount = (u: KYCUser) =>
    (u.has_aadhaar_front ? 1 : 0) + (u.has_aadhaar_back ? 1 : 0) + (u.has_pan_image ? 1 : 0) + (u.has_selfie ? 1 : 0);

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
            <TouchableOpacity onPress={() => openDetail(item)} activeOpacity={0.7} style={styles.card} testID={`kyc-${item.id}`}>
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

              <View style={styles.docRow}>
                <Feather name="paperclip" size={12} color={colors.textMuted} />
                <Text style={styles.docText}>{docCount(item)} document{docCount(item) === 1 ? "" : "s"} attached</Text>
                <Feather name="chevron-right" size={16} color={colors.textMuted} style={{ marginLeft: "auto" }} />
              </View>
            </TouchableOpacity>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No {tab} KYC submissions</Text>}
        />
      )}

      {/* Reject modal */}
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

      {/* Detail modal — full screen for image review */}
      <Modal visible={!!detailFor} animationType="slide" onRequestClose={() => setDetailFor(null)}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setDetailFor(null)} style={styles.backBtn} testID="kyc-detail-close">
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>KYC details</Text>
            <View style={{ width: 40 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}>
            {detailFor ? (
              <>
                <Text style={styles.detailName}>{detailFor.name}</Text>
                <Text style={styles.detailMeta}>{detailFor.email}</Text>
                <View style={[styles.pill, { backgroundColor: detailFor.kyc_status === "approved" ? colors.success : detailFor.kyc_status === "rejected" ? "#B3261E" : colors.warning, alignSelf: "flex-start", marginTop: 8 }]}>
                  <Text style={styles.pillText}>{(detailFor.kyc_status || "").toUpperCase()}</Text>
                </View>

                <View style={styles.detailBox}>
                  <Text style={styles.kvLabel}>Full name</Text>
                  <Text style={styles.kvValue}>{detailFor.kyc_full_name || "—"}</Text>
                  <Text style={styles.kvLabel}>Aadhaar</Text>
                  <Text style={styles.kvValue}>{detailFor.kyc_aadhaar || "—"}</Text>
                  <Text style={styles.kvLabel}>PAN</Text>
                  <Text style={styles.kvValue}>{detailFor.kyc_pan || "—"}</Text>
                  {detailFor.kyc_reject_reason ? <Text style={[styles.rejectText, { marginTop: 10 }]}>Reason: {detailFor.kyc_reject_reason}</Text> : null}
                </View>

                <Text style={styles.docHeader}>DOCUMENTS</Text>
                {detailLoading ? (
                  <View style={[styles.center, { padding: 20 }]}><ActivityIndicator color={colors.primary} /></View>
                ) : (
                  <View style={{ gap: 12 }}>
                    <DocCard label="Aadhaar — Front" image={detailFor.aadhaar_front} onZoom={setZoom} />
                    <DocCard label="Aadhaar — Back" image={detailFor.aadhaar_back} onZoom={setZoom} />
                    <DocCard label="PAN" image={detailFor.pan_image} onZoom={setZoom} />
                    <DocCard label="Selfie" image={detailFor.selfie} onZoom={setZoom} />
                  </View>
                )}

                {detailFor.kyc_status === "pending" && (
                  <View style={[styles.actions, { marginTop: 24 }]}>
                    <TouchableOpacity onPress={() => setRejectFor(detailFor)} style={[styles.actionBtn, { backgroundColor: colors.surfaceMuted }]} testID={`kyc-detail-reject-${detailFor.id}`}>
                      <Feather name="x" size={16} color={colors.textMain} />
                      <Text style={{ color: colors.textMain, fontWeight: "700" }}>Reject</Text>
                    </TouchableOpacity>
                    <TouchableOpacity onPress={() => approve(detailFor)} disabled={busy === detailFor.id} style={[styles.actionBtn, { backgroundColor: colors.primary }, busy === detailFor.id && { opacity: 0.5 }]} testID={`kyc-detail-approve-${detailFor.id}`}>
                      {busy === detailFor.id ? <ActivityIndicator color={colors.primaryFg} /> : (
                        <>
                          <Feather name="check" size={16} color={colors.primaryFg} />
                          <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Approve</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  </View>
                )}
              </>
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </Modal>

      {/* Zoom modal */}
      <Modal visible={!!zoom} transparent animationType="fade" onRequestClose={() => setZoom(null)}>
        <View style={styles.zoomOverlay}>
          <TouchableOpacity onPress={() => setZoom(null)} style={styles.zoomClose} testID="kyc-zoom-close">
            <Feather name="x" size={22} color="#fff" />
          </TouchableOpacity>
          {zoom ? <Image source={{ uri: zoom }} style={styles.zoomImg} resizeMode="contain" /> : null}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function DocCard({ label, image, onZoom }: { label: string; image?: string | null; onZoom: (uri: string) => void }) {
  return (
    <View style={styles.docCard}>
      <Text style={styles.docLabel}>{label}</Text>
      {image ? (
        <TouchableOpacity onPress={() => onZoom(image)} activeOpacity={0.85}>
          <Image source={{ uri: image }} style={styles.docImg} resizeMode="cover" />
          <View style={styles.docZoomHint}>
            <Feather name="zoom-in" size={12} color="#fff" />
            <Text style={styles.docZoomText}>Tap to enlarge</Text>
          </View>
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
  docRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border },
  docText: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  modalSub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 16 },
  modalInput: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain, minHeight: 80, textAlignVertical: "top" },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
  detailName: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  detailMeta: { fontSize: 13, color: colors.textMuted, marginTop: 2 },
  detailBox: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginTop: 16 },
  docHeader: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: 20, marginBottom: 10 },
  docCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 12 },
  docLabel: { fontSize: 12, fontWeight: "700", color: colors.textMain, marginBottom: 8 },
  docImg: { width: "100%", height: 180, borderRadius: 10, backgroundColor: colors.surfaceMuted },
  docZoomHint: { position: "absolute", right: 8, bottom: 8, flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "rgba(0,0,0,0.6)", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 99 },
  docZoomText: { color: "#fff", fontSize: 10, fontWeight: "700" },
  docMissing: { height: 100, alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.surfaceMuted, borderRadius: 10 },
  docMissingText: { fontSize: 12, color: colors.textMuted },
  actions: { flexDirection: "row", gap: 8 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: radii.button },
  zoomOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.95)", alignItems: "center", justifyContent: "center" },
  zoomClose: { position: "absolute", top: 50, right: 20, width: 40, height: 40, borderRadius: 20, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", zIndex: 5 },
  zoomImg: { width: "100%", height: "100%" },
});
