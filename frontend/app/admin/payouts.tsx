import { useCallback, useState, useEffect } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, KeyboardAvoidingView, Platform, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useInfiniteList } from "../../src/use-infinite-list";
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
  reference_number?: string | null;
  rejection_reason?: string | null;
};

type Digest = {
  pending: number;
  processing: number;
  pending_amount: number;
  processing_amount: number;
  settled_today: number;
  settled_today_amount: number;
  oldest_pending_age_hours: number | null;
};

export default function AdminPayouts() {
  // Allow `?tab=pending|processing|success|rejected` so the Admin → Users
  // tiles (Withdrawal Pending, Settled) can deep-link straight into the
  // correct list without an extra tap.
  const params = useLocalSearchParams<{ tab?: string }>();
  const initialTabRaw = (Array.isArray(params.tab) ? params.tab[0] : params.tab) || "pending";
  const allowedTabs = ["pending", "processing", "success", "rejected"] as const;
  const initialTab = (allowedTabs.includes(initialTabRaw as any)
    ? initialTabRaw
    : "pending") as (typeof allowedTabs)[number];

  const [digest, setDigest] = useState<Digest | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [tab, setTab] = useState<"pending" | "processing" | "success" | "rejected">(initialTab);

  // Phase 1 Session C — infinite scroll over the withdrawal queue. Re-renders
  // when `tab` changes (resetKey embeds the current status filter).
  const list = useInfiniteList<Withdrawal>("/admin/withdrawals", {
    pageSize: 20,
    params: { status: tab },
  });
  // Aliases so the (large) JSX below stays readable.
  const items = list.items;
  const loading = list.loading;

  // Keep tab in sync if the user re-enters the route with a different
  // ?tab= param (e.g. taps Settled then later Withdrawal Pending tile).
  useEffect(() => {
    if (allowedTabs.includes(initialTabRaw as any) && initialTabRaw !== tab) {
      setTab(initialTabRaw as any);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTabRaw]);

  const [busy, setBusy] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Modal states
  const [rejectFor, setRejectFor] = useState<Withdrawal | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [completeFor, setCompleteFor] = useState<Withdrawal | null>(null);
  const [completeRef, setCompleteRef] = useState("");
  const [instantFor, setInstantFor] = useState<Withdrawal | null>(null);
  const [instantRef, setInstantRef] = useState("");
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchPrefix, setBatchPrefix] = useState("");

  const load = useCallback(async () => {
    // Reload the paginated withdrawal list + refresh the digest counters
    // (settled_today, oldest_pending_age etc.) in parallel. The list reload
    // is owned by useInfiniteList; we only need to fetch the digest here.
    try {
      const dg = await api.get<Digest>("/admin/withdrawals/digest");
      setDigest(dg.data);
    } catch { /* digest is non-critical */ }
    await list.reload();
    setRefreshing(false);
  }, [list]);

  // First focus shows the spinner; subsequent focus re-fetches in the
  // background so pull-to-refresh on a populated list still works.
  useFocusEffect(useCallback(() => { load(); /* eslint-disable-next-line */ }, []));

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const onApprove = async (w: Withdrawal) => {
    setBusy(w.id);
    try { await api.post(`/admin/withdrawals/${w.id}/approve`); await load(); }
    catch (e) { Alert.alert("Couldn't approve", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const onConfirmReject = async () => {
    if (!rejectFor) return;
    setBusy(rejectFor.id);
    try {
      await api.post(`/admin/withdrawals/${rejectFor.id}/reject`, { reason: rejectReason.trim() });
      setRejectFor(null); setRejectReason(""); await load();
    } catch (e) { Alert.alert("Couldn't reject", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const onConfirmComplete = async () => {
    if (!completeFor) return;
    setBusy(completeFor.id);
    try {
      await api.post(`/admin/withdrawals/${completeFor.id}/complete`, { reference_number: completeRef.trim() });
      setCompleteFor(null); setCompleteRef(""); await load();
    } catch (e) { Alert.alert("Couldn't complete", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const onConfirmInstant = async () => {
    if (!instantFor) return;
    setBusy(instantFor.id);
    try {
      await api.post(`/admin/withdrawals/${instantFor.id}/approve-and-complete`, { reference_number: instantRef.trim() });
      setInstantFor(null); setInstantRef(""); await load();
    } catch (e) { Alert.alert("Couldn't settle", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const onConfirmBatch = async () => {
    if (selected.size === 0) return;
    setBusy("batch");
    try {
      const { data } = await api.post<{ settled_count: number; skipped_count: number }>("/admin/withdrawals/batch/complete", {
        ids: Array.from(selected),
        reference_prefix: batchPrefix.trim() || undefined,
      });
      Alert.alert("Batch complete", `Settled: ${data.settled_count}\nSkipped: ${data.skipped_count}`);
      setBatchOpen(false); setBatchPrefix(""); setSelected(new Set()); setSelectMode(false);
      await load();
    } catch (e) { Alert.alert("Batch failed", formatApiError(e)); }
    finally { setBusy(null); }
  };

  const statusColor = (s: string) =>
    s === "success" || s === "approved" ? colors.success
    : s === "rejected" ? "#B3261E"
    : s === "processing" ? colors.brand500
    : colors.warning;

  const renderItem = ({ item }: { item: Withdrawal }) => (
    <TouchableOpacity
      activeOpacity={selectMode ? 0.7 : 1}
      onPress={() => { if (selectMode) toggleSelect(item.id); }}
      style={[styles.card, selectMode && selected.has(item.id) && { borderColor: colors.primary, borderWidth: 2 }]}
      testID={`payout-${item.id}`}
    >
      <View style={styles.cardTop}>
        <View style={{ flexDirection: "row", alignItems: "flex-start", flex: 1 }}>
          {selectMode && (
            <View style={[styles.checkbox, selected.has(item.id) && styles.checkboxOn]}>
              {selected.has(item.id) ? <Feather name="check" size={14} color="#fff" /> : null}
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.amount}>{formatINR(item.amount)}</Text>
            <Text style={styles.subText} numberOfLines={1}>{item.user_name} · {item.user_email}</Text>
          </View>
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
        {item.reference_number ? <Text style={styles.metaText}>UTR / Ref: <Text style={styles.bold}>{item.reference_number}</Text></Text> : null}
        {item.rejection_reason ? <Text style={[styles.metaText, { color: "#B3261E" }]}>Reason: {item.rejection_reason}</Text> : null}
      </View>
      {!selectMode && item.status === "pending" && (
        <View style={styles.actions}>
          <TouchableOpacity onPress={() => { setRejectFor(item); setRejectReason(""); }} style={[styles.actionBtn, { backgroundColor: colors.surfaceMuted }]} testID={`payout-reject-${item.id}`}>
            <Feather name="x" size={15} color={colors.textMain} />
            <Text style={{ color: colors.textMain, fontWeight: "700" }}> Reject</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => onApprove(item)} disabled={busy === item.id} style={[styles.actionBtn, { backgroundColor: colors.primary }]} testID={`payout-approve-${item.id}`}>
            {busy === item.id ? <ActivityIndicator size="small" color="#fff" /> : <><Feather name="check" size={15} color={colors.primaryFg} /><Text style={{ color: colors.primaryFg, fontWeight: "700" }}> Approve</Text></>}
          </TouchableOpacity>
          <TouchableOpacity onPress={() => { setInstantFor(item); setInstantRef(""); }} style={[styles.actionBtn, { backgroundColor: colors.success }]} testID={`payout-instant-${item.id}`}>
            <MaterialCommunityIcons name="lightning-bolt" size={15} color="#fff" />
            <Text style={{ color: "#fff", fontWeight: "700" }}> Pay now</Text>
          </TouchableOpacity>
        </View>
      )}
      {!selectMode && item.status === "processing" && (
        <View style={styles.actions}>
          <TouchableOpacity onPress={() => { setCompleteFor(item); setCompleteRef(""); }} style={[styles.actionBtn, { backgroundColor: colors.success }]} testID={`payout-complete-${item.id}`}>
            <Feather name="check-circle" size={16} color="#fff" />
            <Text style={{ color: "#fff", fontWeight: "700" }}> Mark paid (with UTR)</Text>
          </TouchableOpacity>
        </View>
      )}
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.overline}>ADMIN · FINANCE</Text>
        <Text style={styles.h1}>Withdrawals</Text>

        {/* Daily digest banner */}
        {digest && (digest.pending + digest.processing > 0 || digest.settled_today > 0) && (
          <View style={[styles.digestRow, digest.oldest_pending_age_hours && digest.oldest_pending_age_hours > 24 ? { borderColor: "#B3261E" } : null]}>
            <View style={styles.digestCell}>
              <Text style={styles.digestNum}>{digest.pending}</Text>
              <Text style={styles.digestLabel}>PENDING</Text>
              <Text style={styles.digestSub}>{formatINR(digest.pending_amount)}</Text>
            </View>
            <View style={styles.digestCell}>
              <Text style={[styles.digestNum, { color: colors.brand500 }]}>{digest.processing}</Text>
              <Text style={styles.digestLabel}>PROCESSING</Text>
              <Text style={styles.digestSub}>{formatINR(digest.processing_amount)}</Text>
            </View>
            <View style={styles.digestCell}>
              <Text style={[styles.digestNum, { color: colors.success }]}>{digest.settled_today}</Text>
              <Text style={styles.digestLabel}>TODAY ✅</Text>
              <Text style={styles.digestSub}>{formatINR(digest.settled_today_amount)}</Text>
            </View>
          </View>
        )}
        {digest?.oldest_pending_age_hours && digest.oldest_pending_age_hours > 24 ? (
          <View style={styles.digestAlert}>
            <Feather name="alert-triangle" size={14} color="#B3261E" />
            <Text style={styles.digestAlertText}>{Math.floor(digest.oldest_pending_age_hours)}h old request waiting — please action soon.</Text>
          </View>
        ) : null}

        {/* ── Quick Actions (moved from admin Home) ─────────────────────
            Consolidated here per user spec — admin can access KYC, Orders,
            Audit, Settings, and Approvals directly from this screen instead
            of bouncing back to Home. */}
        <Text style={styles.quickLabel}>QUICK ACTIONS</Text>
        <View style={styles.quickGrid}>
          <QuickActionTile icon="user-check" label="KYC queue"     route="/admin/kyc" testID="qa-kyc" />
          <QuickActionTile icon="package"    label="Orders"        route="/admin/orders" testID="qa-orders" />
          <QuickActionTile icon="file-text"  label="Audit log"     route="/admin/audit" testID="qa-audit" />
          <QuickActionTile icon="sliders"    label="Settings"      route="/admin/settings" testID="qa-settings" />
          <QuickActionTile icon="user-plus"  label="Approvals"     route="/admin/approvals" testID="qa-approvals" />
          <QuickActionTile icon="list"       label="Transactions"  route="/admin/transactions" testID="qa-transactions" />
        </View>

        <View style={styles.tabs}>
          {(["pending", "processing", "success", "rejected"] as const).map((t) => (
            <TouchableOpacity key={t} onPress={() => { setTab(t); setSelectMode(false); setSelected(new Set()); }} style={[styles.tab, tab === t && styles.tabActive]} testID={`payouts-tab-${t}`}>
              <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>{t.toUpperCase()}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Tab-total banner — shows the sum of the items in the currently
            active tab so admin can see "all-time Settled = ₹X" without
            mental math. Drives the deep-link from Admin → Users tiles. */}
        {!loading ? (
          <View style={[styles.tabTotalRow, { borderColor: (tab === "success" ? colors.success : tab === "pending" ? "#E57A44" : colors.primary) + "55" }]}>
            <Feather
              name={tab === "success" ? "check-circle" : tab === "pending" ? "clock" : tab === "rejected" ? "slash" : "loader"}
              size={14}
              color={tab === "success" ? colors.success : tab === "pending" ? "#E57A44" : colors.primary}
            />
            <Text style={styles.tabTotalLabel}>
              {tab === "success" ? "Settled total" : tab === "pending" ? "Pending total" : tab === "processing" ? "Processing total" : "Rejected total"}
              {"  ·  "}
              <Text style={{ color: colors.textMuted, fontWeight: "700" }}>{items.length} txn{items.length === 1 ? "" : "s"}</Text>
            </Text>
            <Text style={styles.tabTotalAmount}>
              {formatINR(items.reduce((s, w) => s + Number(w.amount || 0), 0))}
            </Text>
          </View>
        ) : null}

        {/* Batch select toolbar */}
        {(tab === "pending" || tab === "processing") && (
          <View style={styles.toolbarRow}>
            {!selectMode ? (
              <TouchableOpacity onPress={() => setSelectMode(true)} style={styles.toolbarBtn} testID="payouts-select-mode">
                <Feather name="check-square" size={14} color={colors.primary} />
                <Text style={styles.toolbarBtnText}>  Select multiple</Text>
              </TouchableOpacity>
            ) : (
              <>
                <TouchableOpacity onPress={() => { setSelectMode(false); setSelected(new Set()); }} style={styles.toolbarBtn} testID="payouts-cancel-select">
                  <Feather name="x" size={14} color={colors.textMain} />
                  <Text style={[styles.toolbarBtnText, { color: colors.textMain }]}>  Cancel</Text>
                </TouchableOpacity>
                <Text style={styles.toolbarSelected}>{selected.size} selected</Text>
                <TouchableOpacity
                  onPress={() => { if (selected.size === 0) { Alert.alert("Pick at least one"); return; } setBatchOpen(true); }}
                  disabled={selected.size === 0}
                  style={[styles.toolbarBtnPrimary, selected.size === 0 && { opacity: 0.5 }]}
                  testID="payouts-batch-settle"
                >
                  <Feather name="zap" size={14} color="#fff" />
                  <Text style={styles.toolbarBtnPrimaryText}>  Settle selected</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        )}
      </View>

      {loading && items.length === 0 ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={renderItem}
          onEndReached={list.loadMore}
          onEndReachedThreshold={0.5}
          ListFooterComponent={list.loadingMore ? (
            <View style={{ paddingVertical: 16, alignItems: "center" }}>
              <ActivityIndicator color={colors.primary} size="small" />
            </View>
          ) : (!list.hasMore && items.length > 0 ? (
            <Text style={{ textAlign: "center", color: colors.textMuted, paddingVertical: 12, fontSize: 12 }}>
              End of list · {items.length} loaded
            </Text>
          ) : null)}
          ListEmptyComponent={<Text style={styles.empty}>No {tab} payouts.</Text>}
        />
      )}

      {/* Reject modal — with reason */}
      <Modal visible={!!rejectFor} animationType="slide" transparent onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView style={styles.modalBackdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Reject withdrawal?</Text>
            <Text style={styles.modalBody}>{rejectFor?.user_email} · {rejectFor && formatINR(rejectFor.amount)} will be refunded to wallet.</Text>
            <Text style={styles.label}>Reason (visible to user)</Text>
            <TextInput style={styles.input} value={rejectReason} onChangeText={setRejectReason} placeholder="e.g. Invalid UPI ID, please re-submit" placeholderTextColor={colors.textMuted} multiline />
            <View style={styles.modalActions}>
              <TouchableOpacity onPress={() => { setRejectFor(null); setRejectReason(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]} testID="reject-cancel"><Text style={[styles.modalBtnText, { color: colors.textMain }]}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onConfirmReject} disabled={busy === rejectFor?.id} style={[styles.modalBtn, { backgroundColor: "#B3261E" }]} testID="reject-confirm">
                {busy === rejectFor?.id ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnText, { color: "#fff" }]}>Reject &amp; refund</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Complete modal — with UTR */}
      <Modal visible={!!completeFor} animationType="slide" transparent onRequestClose={() => setCompleteFor(null)}>
        <KeyboardAvoidingView style={styles.modalBackdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Mark as paid</Text>
            <Text style={styles.modalBody}>{completeFor?.user_email} · {completeFor && formatINR(completeFor.amount)}</Text>
            <Text style={styles.label}>UTR / Reference number (optional)</Text>
            <TextInput style={styles.input} value={completeRef} onChangeText={setCompleteRef} placeholder="e.g. 123456789012 or UTR-XYZ" placeholderTextColor={colors.textMuted} autoCapitalize="characters" />
            <View style={styles.modalActions}>
              <TouchableOpacity onPress={() => { setCompleteFor(null); setCompleteRef(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}><Text style={[styles.modalBtnText, { color: colors.textMain }]}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onConfirmComplete} disabled={busy === completeFor?.id} style={[styles.modalBtn, { backgroundColor: colors.success }]} testID="complete-confirm">
                {busy === completeFor?.id ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnText, { color: "#fff" }]}>Mark paid</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Pay now (instant) modal */}
      <Modal visible={!!instantFor} animationType="slide" transparent onRequestClose={() => setInstantFor(null)}>
        <KeyboardAvoidingView style={styles.modalBackdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 4 }}>
              <MaterialCommunityIcons name="lightning-bolt" size={20} color={colors.success} />
              <Text style={[styles.modalTitle, { marginLeft: 6 }]}>Instant settle</Text>
            </View>
            <Text style={styles.modalBody}>Skip the processing step — go directly to ✅ Success.{"\n\n"}{instantFor?.user_email} · {instantFor && formatINR(instantFor.amount)}</Text>
            <Text style={styles.label}>UTR / Reference number (optional)</Text>
            <TextInput style={styles.input} value={instantRef} onChangeText={setInstantRef} placeholder="e.g. 123456789012" placeholderTextColor={colors.textMuted} autoCapitalize="characters" />
            <View style={styles.modalActions}>
              <TouchableOpacity onPress={() => { setInstantFor(null); setInstantRef(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}><Text style={[styles.modalBtnText, { color: colors.textMain }]}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onConfirmInstant} disabled={busy === instantFor?.id} style={[styles.modalBtn, { backgroundColor: colors.success }]} testID="instant-confirm">
                {busy === instantFor?.id ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnText, { color: "#fff" }]}>Pay now ✅</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Batch settle modal */}
      <Modal visible={batchOpen} animationType="slide" transparent onRequestClose={() => setBatchOpen(false)}>
        <KeyboardAvoidingView style={styles.modalBackdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Batch settle {selected.size} payouts</Text>
            <Text style={styles.modalBody}>All selected withdrawals (pending or processing) will be marked as ✅ Success in one go.</Text>
            <Text style={styles.label}>Reference prefix (optional)</Text>
            <TextInput style={styles.input} value={batchPrefix} onChangeText={setBatchPrefix} placeholder="e.g. BATCH-2025-04-30" placeholderTextColor={colors.textMuted} autoCapitalize="characters" />
            <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 6 }}>Each withdrawal will get its own UTR like &quot;{batchPrefix || "..."}-abcd1234&quot;.</Text>
            <View style={styles.modalActions}>
              <TouchableOpacity onPress={() => setBatchOpen(false)} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}><Text style={[styles.modalBtnText, { color: colors.textMain }]}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onConfirmBatch} disabled={busy === "batch"} style={[styles.modalBtn, { backgroundColor: colors.success }]} testID="batch-confirm">
                {busy === "batch" ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnText, { color: "#fff" }]}>Settle all</Text>}
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
  header: { padding: spacing.screen, paddingBottom: 8 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 28, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 14 },
  digestRow: { flexDirection: "row", borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, padding: 10, marginBottom: 10 },
  digestCell: { flex: 1, alignItems: "center" },
  digestNum: { fontSize: 22, fontWeight: "800", color: colors.warning, letterSpacing: -0.5 },
  digestLabel: { fontSize: 9, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 2 },
  digestSub: { fontSize: 11, color: colors.textMain, marginTop: 2, fontWeight: "700" },
  digestAlert: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 10, backgroundColor: "#FCE9E5", marginBottom: 10 },
  digestAlertText: { fontSize: 12, color: "#B3261E", fontWeight: "700", flex: 1 },
  tabs: { flexDirection: "row", backgroundColor: colors.surfaceMuted, borderRadius: radii.button, padding: 4, gap: 4 },
  tabTotalRow: { marginTop: 10, flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10 },
  tabTotalLabel: { flex: 1, fontSize: 12, fontWeight: "800", color: colors.textMain, letterSpacing: 0.3 },
  tabTotalAmount: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3, fontVariant: ["tabular-nums"] },
  tab: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 99 },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 11, fontWeight: "700", color: colors.textMuted, letterSpacing: 1 },
  tabTextActive: { color: colors.primaryFg },
  toolbarRow: { flexDirection: "row", alignItems: "center", marginTop: 10, gap: 8 },
  toolbarBtn: { flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 7, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  toolbarBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  toolbarSelected: { fontSize: 12, fontWeight: "700", color: colors.textMain, marginLeft: "auto" },
  toolbarBtnPrimary: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 16, backgroundColor: colors.success },
  toolbarBtnPrimaryText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 10 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  amount: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  subText: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, marginLeft: 8 },
  pillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 10 },
  metaText: { fontSize: 12, color: colors.textMuted, marginVertical: 2 },
  bold: { color: colors.textMain, fontWeight: "700" },
  actions: { flexDirection: "row", gap: 6, marginTop: 12, flexWrap: "wrap" },
  actionBtn: { flex: 1, minWidth: 100, flexDirection: "row", alignItems: "center", justifyContent: "center", paddingVertical: 10, borderRadius: radii.button },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
  checkbox: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: colors.border, marginRight: 10, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  checkboxOn: { backgroundColor: colors.primary, borderColor: colors.primary },

  // Modal styles
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.background, borderTopLeftRadius: 22, borderTopRightRadius: 22, padding: spacing.screen },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  modalBody: { fontSize: 13, color: colors.textMuted, marginTop: 6, lineHeight: 18 },
  label: { fontSize: 11, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 16, marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain, minHeight: 46 },
  modalActions: { flexDirection: "row", gap: 8, marginTop: 18 },
  modalBtn: { flex: 1, paddingVertical: 13, borderRadius: radii.button, alignItems: "center" },
  modalBtnText: { fontWeight: "800", fontSize: 13 },

  // Quick actions (moved from admin Home)
  quickLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: 16, marginBottom: 8 },
  quickGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 },
  quickCard: {
    flexBasis: "31%", flexGrow: 1,
    flexDirection: "column", alignItems: "center", gap: 6,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 14,
    paddingVertical: 12, paddingHorizontal: 8,
  },
  quickIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  quickLabelText: { fontSize: 11, fontWeight: "700", color: colors.textMain, textAlign: "center" },
});

function QuickActionTile({ icon, label, route, testID }: { icon: any; label: string; route: string; testID?: string }) {
  const r = useRouter();
  return (
    <TouchableOpacity style={styles.quickCard} onPress={() => r.push(route as any)} testID={testID}>
      <View style={styles.quickIcon}><Feather name={icon} size={16} color={colors.primary} /></View>
      <Text style={styles.quickLabelText}>{label}</Text>
    </TouchableOpacity>
  );
}
