// Seller · Returns review — approve, receive, refund (Phase 2, Jun-2026).
// Money never moves from this screen's maths: the backend debits the seller
// wallet and credits the customer, and refuses if the balance is short.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, TextInput,
  ActivityIndicator, RefreshControl, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, formatINR } from "../../src/theme";
import { useTabSwipe } from "../../src/use-swipe-pager";

type ReturnDoc = {
  id: string;
  return_number: string;
  order_number?: string;
  customer_name?: string | null;
  customer_email?: string | null;
  items: { name: string; qty: number; refund_amount: number; unit_price: number }[];
  item_refund: number;
  refund_amount: number;
  refund_needed?: number;
  refund_paid?: number;
  cashback_reversal_expected?: number;
  status: string;
  reason?: string;
  comments?: string;
  created_at: string;
  inventory_restored?: boolean;
};

const TABS = [
  { key: "requested", label: "To review" },
  { key: "approved", label: "Approved" },
  { key: "returned", label: "Received" },
  { key: "refund_pending", label: "Refund due" },
  { key: "completed", label: "Done" },
  { key: "all", label: "All" },
] as const;

const META: Record<string, { label: string; color: string; bg: string }> = {
  requested: { label: "Needs review", color: "#92400E", bg: "#FEF3C7" },
  approved: { label: "Approved", color: "#1E40AF", bg: "#DBEAFE" },
  returned: { label: "Item received", color: "#5B21B6", bg: "#EDE9FE" },
  refund_pending: { label: "Refund pending", color: "#991B1B", bg: "#FEE2E2" },
  refunded: { label: "Refunded", color: "#166534", bg: "#DCFCE7" },
  completed: { label: "Completed", color: "#166534", bg: "#DCFCE7" },
  rejected: { label: "Declined", color: "#991B1B", bg: "#FEE2E2" },
};

export default function VendorReturnsScreen() {
  const router = useRouter();
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("requested");
const swipe = useTabSwipe(TABS.map((t) => t.key), tab, setTab);
  const [items, setItems] = useState<ReturnDoc[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [reject, setReject] = useState<ReturnDoc | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [msg, setMsg] = useState<null | { title: string; body: string }>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: ReturnDoc[]; counts: Record<string, number> }>(
        `/vendor/me/returns?status=${tab}`,
      );
      setItems(data.items || []);
      setCounts(data.counts || {});
    } catch {
      setItems([]);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [tab]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const act = async (r: ReturnDoc, path: string, body?: any, success?: string) => {
    setBusy(r.id);
    try {
      await api.post(`/vendor/me/returns/${r.id}/${path}`, body || {});
      if (success) setMsg({ title: "Done", body: success });
      await load();
    } catch (e) {
      setMsg({ title: "Couldn't complete that", body: formatApiError(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} {...swipe}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="vendor-returns-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Returns</Text>
        <View style={{ flex: 1 }} />
        {counts.requested ? (
          <View style={styles.headerPill}>
            <Text style={styles.headerPillText}>{counts.requested} to review</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.tabs}>
        <FlatList
          horizontal
          showsHorizontalScrollIndicator={false}
          data={TABS as any}
          keyExtractor={(t: any) => t.key}
          contentContainerStyle={{ paddingHorizontal: spacing.screen, gap: 8 }}
          renderItem={({ item: t }: any) => (
            <TouchableOpacity
              onPress={() => setTab(t.key)}
              style={[styles.tab, tab === t.key && styles.tabOn]}
              testID={`vendor-returns-tab-${t.key}`}
            >
              <Text style={[styles.tabText, tab === t.key && styles.tabTextOn]}>
                {t.label}{counts[t.key] ? ` (${counts[t.key]})` : ""}
              </Text>
            </TouchableOpacity>
          )}
        />
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />
          }
          ListEmptyComponent={<Text style={styles.empty}>Nothing here right now.</Text>}
          renderItem={({ item }) => {
            const m = META[item.status] || META.requested;
            const working = busy === item.id;
            return (
              <View style={styles.card} testID={`vendor-return-${item.return_number}`}>
                <View style={{ flexDirection: "row" }}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.retNo}>{item.return_number}</Text>
                    <Text style={styles.meta}>
                      Order {item.order_number} · {item.customer_name || item.customer_email || "Customer"}
                    </Text>
                  </View>
                  <Text style={styles.amount}>{formatINR(item.refund_amount)}</Text>
                </View>
                <View style={[styles.badge, { backgroundColor: m.bg }]}>
                  <Text style={[styles.badgeText, { color: m.color }]}>{m.label}</Text>
                </View>
                {(item.items || []).map((i, idx) => (
                  <Text key={idx} style={styles.itemLine}>
                    {i.qty} × {i.name} · {formatINR(i.refund_amount)}
                  </Text>
                ))}
                {item.reason ? <Text style={styles.reason}>Reason: {item.reason}</Text> : null}
                {item.comments ? <Text style={styles.reason}>“{item.comments}”</Text> : null}
                {item.status === "refund_pending" ? (
                  <Text style={styles.warn}>
                    Add {formatINR(item.refund_needed || item.refund_amount)} to your balance, then
                    pay the refund. Nothing has been deducted.
                  </Text>
                ) : null}

                <View style={styles.actions}>
                  {item.status === "requested" ? (
                    <>
                      <TouchableOpacity
                        onPress={() => act(item, "approve", { note: "" }, "Return approved. Ask the buyer to hand the item back.")}
                        disabled={working}
                        style={[styles.btn, styles.btnPrimary]}
                        testID={`ret-approve-${item.return_number}`}
                      >
                        {working ? <ActivityIndicator size="small" color="#fff" /> : (
                          <>
                            <Feather name="check" size={13} color="#fff" />
                            <Text style={styles.btnPrimaryText}>Approve</Text>
                          </>
                        )}
                      </TouchableOpacity>
                      <TouchableOpacity
                        onPress={() => { setReject(item); setRejectNote(""); }}
                        disabled={working}
                        style={[styles.btn, styles.btnGhost]}
                        testID={`ret-reject-${item.return_number}`}
                      >
                        <Feather name="x" size={13} color={colors.error} />
                        <Text style={[styles.btnGhostText, { color: colors.error }]}>Decline</Text>
                      </TouchableOpacity>
                    </>
                  ) : null}
                  {item.status === "approved" ? (
                    <TouchableOpacity
                      onPress={() => act(item, "received", { note: "" }, "Marked as received. Pay the refund next.")}
                      disabled={working}
                      style={[styles.btn, styles.btnPrimary]}
                      testID={`ret-received-${item.return_number}`}
                    >
                      {working ? <ActivityIndicator size="small" color="#fff" /> : (
                        <>
                          <Feather name="package" size={13} color="#fff" />
                          <Text style={styles.btnPrimaryText}>Item received</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  ) : null}
                  {item.status === "returned" || item.status === "refund_pending" ? (
                    <TouchableOpacity
                      onPress={() => act(item, "refund", {}, "Refund paid and stock restored.")}
                      disabled={working}
                      style={[styles.btn, styles.btnPrimary]}
                      testID={`ret-refund-${item.return_number}`}
                    >
                      {working ? <ActivityIndicator size="small" color="#fff" /> : (
                        <>
                          <Feather name="corner-down-left" size={13} color="#fff" />
                          <Text style={styles.btnPrimaryText}>
                            Pay refund {formatINR(item.refund_needed || item.refund_amount)}
                          </Text>
                        </>
                      )}
                    </TouchableOpacity>
                  ) : null}
                  {item.status === "completed" || item.status === "refunded" ? (
                    <Text style={styles.doneLine}>
                      {formatINR(item.refund_paid || 0)} refunded · stock {item.inventory_restored ? "restored" : "pending"}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          }}
        />
      )}

      <Modal visible={!!reject} transparent animationType="fade" onRequestClose={() => setReject(null)}>
        <View style={styles.modalWrap}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Decline this return?</Text>
            <Text style={styles.modalBody}>
              The buyer sees your reason. No money moves and stock is unchanged.
            </Text>
            <TextInput
              value={rejectNote}
              onChangeText={setRejectNote}
              placeholder="Why are you declining?"
              placeholderTextColor={colors.textMuted}
              style={styles.input}
              testID="ret-reject-note"
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity onPress={() => setReject(null)} style={[styles.btn, styles.btnGhost, { flex: 1 }]}>
                <Text style={styles.btnGhostText}>Keep it open</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={async () => {
                  const r = reject!; setReject(null);
                  await act(r, "reject", { note: rejectNote }, "Return declined.");
                }}
                style={[styles.btn, { flex: 1, backgroundColor: colors.error }]}
                testID="ret-reject-confirm"
              >
                <Text style={styles.btnPrimaryText}>Decline</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <Modal visible={!!msg} transparent animationType="fade" onRequestClose={() => setMsg(null)}>
        <View style={styles.modalWrap}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>{msg?.title}</Text>
            <Text style={styles.modalBody}>{msg?.body}</Text>
            <TouchableOpacity
              onPress={() => setMsg(null)}
              style={[styles.btn, styles.btnPrimary, { marginTop: 8 }]}
              testID="ret-msg-ok"
            >
              <Text style={styles.btnPrimaryText}>OK</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  iconBtn: { padding: 8, minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  headerPill: { backgroundColor: "#FEF3C7", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  headerPillText: { fontSize: 11, fontWeight: "900", color: "#92400E" },
  tabs: { paddingVertical: 10, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: {
    paddingHorizontal: 13, paddingVertical: 8, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  tabOn: { backgroundColor: colors.brand100, borderColor: colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  tabTextOn: { color: colors.primary },
  empty: { textAlign: "center", marginTop: 50, color: colors.textMuted },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14,
    padding: 14, marginBottom: 10, gap: 7,
  },
  retNo: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 3 },
  amount: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  badge: { alignSelf: "flex-start", paddingHorizontal: 9, paddingVertical: 4, borderRadius: 999 },
  badgeText: { fontSize: 10, fontWeight: "900", textTransform: "uppercase", letterSpacing: 0.4 },
  itemLine: { fontSize: 12, color: colors.textMain },
  reason: { fontSize: 12, color: colors.textMuted },
  warn: { fontSize: 12, color: colors.error, fontWeight: "700", lineHeight: 18 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4 },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingHorizontal: 14, minHeight: 44, borderRadius: 999,
  },
  btnPrimary: { backgroundColor: colors.primary },
  btnPrimaryText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },
  btnGhost: { backgroundColor: colors.surfaceMuted },
  btnGhostText: { color: colors.textMain, fontWeight: "800", fontSize: 13 },
  doneLine: { fontSize: 12, fontWeight: "700", color: colors.success },
  modalWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "center", padding: 24 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 18, padding: 20 },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  modalBody: { fontSize: 13, color: colors.textMuted, marginTop: 6, lineHeight: 19 },
  input: {
    marginTop: 12, borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    paddingHorizontal: 12, minHeight: 46, color: colors.textMain, backgroundColor: colors.surface,
  },
});
