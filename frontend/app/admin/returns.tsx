// Admin · Returns, pending refunds, financial errors & reconciliation.
// Phase 2 §21/§24 — problems are surfaced, never patched with fake money.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, RefreshControl, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, formatINR } from "../../src/theme";

const TABS = [
  { key: "returns", label: "Returns" },
  { key: "pending", label: "Refunds due" },
  { key: "errors", label: "Error register" },
  { key: "recon", label: "Reconciliation" },
] as const;

export default function AdminReturnsScreen() {
  const router = useRouter();
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("returns");
  const [rows, setRows] = useState<any[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [errors, setErrors] = useState<any[]>([]);
  const [recon, setRecon] = useState<any>(null);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<null | { title: string; body: string }>(null);

  const load = useCallback(async () => {
    try {
      if (tab === "returns" || tab === "pending") {
        const status = tab === "pending" ? "refund_pending" : "all";
        const { data } = await api.get(
          `/admin/returns?status=${status}&limit=200${q ? `&q=${encodeURIComponent(q)}` : ""}`,
        );
        setRows(data.items || []);
        setPendingCount(data.refund_pending_count || 0);
      } else if (tab === "errors") {
        const { data } = await api.get("/admin/financial-errors?status=open");
        setErrors(data.items || []);
      }
    } catch {
      /* keep last good data */
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [tab, q]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const runRecon = async () => {
    setBusy("recon");
    try {
      const { data } = await api.get("/admin/reconciliation");
      setRecon(data);
    } catch (e) {
      setMsg({ title: "Couldn't run reconciliation", body: formatApiError(e) });
    } finally {
      setBusy(null);
    }
  };

  const payRefund = async (r: any) => {
    setBusy(r.id);
    try {
      await api.post(`/admin/returns/${r.id}/refund`);
      setMsg({ title: "Refund paid", body: `${r.return_number} settled from the seller's balance.` });
      await load();
    } catch (e) {
      setMsg({ title: "Still blocked", body: formatApiError(e) });
    } finally {
      setBusy(null);
    }
  };

  const resolveError = async (e: any) => {
    setBusy(e.id);
    try {
      await api.post(`/admin/financial-errors/${e.id}/resolve`, { note: "Reviewed by admin" });
      await load();
    } catch (err) {
      setMsg({ title: "Couldn't resolve", body: formatApiError(err) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="admin-returns-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Returns & reconciliation</Text>
      </View>

      <View style={styles.tabs}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: spacing.screen, gap: 8 }}>
          {TABS.map((t) => (
            <TouchableOpacity
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[styles.tab, tab === t.key && styles.tabOn]}
              testID={`admin-returns-tab-${t.key}`}
            >
              <Text style={[styles.tabText, tab === t.key && styles.tabTextOn]}>
                {t.label}{t.key === "pending" && pendingCount ? ` (${pendingCount})` : ""}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      >
        {tab === "returns" ? (
          <View style={styles.searchWrap}>
            <Feather name="search" size={15} color={colors.textMuted} />
            <TextInput
              value={q}
              onChangeText={setQ}
              onSubmitEditing={() => { setLoading(true); load(); }}
              placeholder="Return / order number, customer, shop"
              placeholderTextColor={colors.textMuted}
              style={styles.searchInput}
              returnKeyType="search"
              testID="admin-returns-search"
            />
          </View>
        ) : null}

        {loading && tab !== "recon" ? (
          <ActivityIndicator color={colors.primary} style={{ marginTop: 30 }} />
        ) : null}

        {(tab === "returns" || tab === "pending") && !loading ? (
          rows.length === 0 ? <Text style={styles.empty}>Nothing here.</Text> : rows.map((r) => (
            <View key={r.id} style={styles.card} testID={`admin-return-${r.return_number}`}>
              <View style={{ flexDirection: "row" }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle}>{r.return_number}</Text>
                  <Text style={styles.cardMeta}>
                    Order {r.order_number} · {r.vendor_name || "Seller"} · {r.customer_email || "Customer"}
                  </Text>
                </View>
                <Text style={styles.amount}>{formatINR(r.refund_amount)}</Text>
              </View>
              <Text style={styles.statusLine}>{String(r.status).replace("_", " ")}</Text>
              {(r.items || []).map((i: any, idx: number) => (
                <Text key={idx} style={styles.itemLine}>{i.qty} × {i.name} · {formatINR(i.refund_amount)}</Text>
              ))}
              {r.status === "refund_pending" ? (
                <>
                  <Text style={styles.warn}>
                    Seller balance short by {formatINR(r.refund_needed || r.refund_amount)}. Nothing has
                    been deducted. Retry once they add money — no money is created here.
                  </Text>
                  <TouchableOpacity
                    onPress={() => payRefund(r)}
                    disabled={busy === r.id}
                    style={styles.btn}
                    testID={`admin-pay-${r.return_number}`}
                  >
                    {busy === r.id ? <ActivityIndicator size="small" color="#fff" /> : (
                      <Text style={styles.btnText}>Retry refund from seller balance</Text>
                    )}
                  </TouchableOpacity>
                </>
              ) : null}
              {r.refund_paid ? (
                <Text style={styles.okLine}>
                  {formatINR(r.refund_paid)} refunded · stock {r.inventory_restored ? "restored" : "pending"}
                  {r.cashback_reversed ? ` · cashback ${formatINR(r.cashback_reversed)} reversed` : ""}
                </Text>
              ) : null}
            </View>
          ))
        ) : null}

        {tab === "errors" && !loading ? (
          errors.length === 0 ? (
            <View style={styles.okBox}>
              <Feather name="check-circle" size={18} color="#166534" />
              <Text style={styles.okBoxText}>No open financial errors.</Text>
            </View>
          ) : errors.map((e) => (
            <View key={e.id} style={styles.card} testID={`admin-error-${e.id}`}>
              <Text style={styles.cardTitle}>{String(e.error_type || e.kind).replace(/_/g, " ")}</Text>
              <Text style={styles.cardMeta}>{String(e.created_at || "").slice(0, 19).replace("T", " ")}</Text>
              <Text style={styles.itemLine}>{e.detail}</Text>
              {e.expected_amount != null ? (
                <Text style={styles.itemLine}>
                  Expected {formatINR(e.expected_amount)} · actual {formatINR(e.actual_amount || 0)} ·
                  difference {formatINR(e.difference || 0)}
                </Text>
              ) : null}
              {e.order_id ? <Text style={styles.cardMeta}>Order {e.order_id}</Text> : null}
              {e.return_id ? <Text style={styles.cardMeta}>Return {e.return_id}</Text> : null}
              {e.vendor_id ? <Text style={styles.cardMeta}>Vendor {e.vendor_id}</Text> : null}
              <TouchableOpacity
                onPress={() => resolveError(e)}
                disabled={busy === e.id}
                style={[styles.btn, { backgroundColor: colors.surfaceMuted }]}
                testID={`admin-resolve-${e.id}`}
              >
                <Text style={[styles.btnText, { color: colors.textMain }]}>Mark reviewed</Text>
              </TouchableOpacity>
            </View>
          ))
        ) : null}

        {tab === "recon" ? (
          <>
            <TouchableOpacity onPress={runRecon} disabled={busy === "recon"} style={styles.btn} testID="admin-run-recon">
              {busy === "recon" ? <ActivityIndicator size="small" color="#fff" /> : (
                <Text style={styles.btnText}>Run full reconciliation</Text>
              )}
            </TouchableOpacity>
            {recon ? (
              <>
                <View style={[styles.okBox, !recon.all_balanced && { backgroundColor: "#FEF3C7" }]}>
                  <Feather
                    name={recon.all_balanced ? "check-circle" : "alert-triangle"}
                    size={18}
                    color={recon.all_balanced ? "#166534" : "#92400E"}
                  />
                  <Text style={styles.okBoxText}>
                    {recon.all_balanced
                      ? "Every check balanced."
                      : "Some checks need attention — details below."}
                    {"\n"}Open financial errors: {recon.open_financial_errors}
                  </Text>
                </View>
                {(recon.checks || []).map((c: any) => (
                  <View key={c.name} style={styles.card}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Feather
                        name={c.balanced ? "check-circle" : "alert-circle"}
                        size={14}
                        color={c.balanced ? "#166534" : "#B45309"}
                      />
                      <Text style={styles.cardTitle}>{String(c.name).replace(/_/g, " ")}</Text>
                    </View>
                    {c.formula ? <Text style={styles.cardMeta}>{c.formula}</Text> : null}
                    {Object.entries(c)
                      .filter(([k, v]) =>
                        !["name", "formula", "samples", "rows", "components", "note"].includes(k) &&
                        (typeof v === "number" || typeof v === "string" || typeof v === "boolean"))
                      .map(([k, v]) => (
                        <View key={k} style={styles.lineRow}>
                          <Text style={styles.lineLabel}>{k.replace(/_/g, " ")}</Text>
                          <Text style={styles.lineValue}>{String(v)}</Text>
                        </View>
                      ))}
                    {c.note ? <Text style={styles.noteLine}>{c.note}</Text> : null}
                  </View>
                ))}
              </>
            ) : (
              <Text style={styles.empty}>
                Run the check to re-derive every wallet, the treasury, inventory and GST from the ledger.
              </Text>
            )}
          </>
        ) : null}
      </ScrollView>

      <Modal visible={!!msg} transparent animationType="fade" onRequestClose={() => setMsg(null)}>
        <View style={styles.modalWrap}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>{msg?.title}</Text>
            <Text style={styles.modalBody}>{msg?.body}</Text>
            <TouchableOpacity onPress={() => setMsg(null)} style={styles.btn} testID="admin-msg-ok">
              <Text style={styles.btnText}>OK</Text>
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
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  tabs: { paddingVertical: 10, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: {
    paddingHorizontal: 13, paddingVertical: 8, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  tabOn: { backgroundColor: colors.brand100, borderColor: colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  tabTextOn: { color: colors.primary },
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceMuted,
    borderRadius: 10, paddingHorizontal: 12, minHeight: 44, marginBottom: 12,
  },
  searchInput: { flex: 1, color: colors.textMain, fontSize: 13 },
  empty: { textAlign: "center", marginTop: 30, color: colors.textMuted, lineHeight: 20 },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    padding: 14, marginBottom: 10, gap: 5,
  },
  cardTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain },
  cardMeta: { fontSize: 11, color: colors.textMuted },
  amount: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  statusLine: { fontSize: 11, fontWeight: "900", color: colors.primary, textTransform: "uppercase" },
  itemLine: { fontSize: 12, color: colors.textMain, lineHeight: 18 },
  warn: { fontSize: 12, color: colors.error, fontWeight: "700", lineHeight: 18 },
  okLine: { fontSize: 12, fontWeight: "700", color: colors.success },
  btn: {
    backgroundColor: colors.primary, borderRadius: 999, minHeight: 44, alignItems: "center",
    justifyContent: "center", paddingHorizontal: 16, marginTop: 8,
  },
  btnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },
  okBox: {
    flexDirection: "row", gap: 10, backgroundColor: "#DCFCE7", borderRadius: 12, padding: 14,
    alignItems: "center", marginTop: 12, marginBottom: 4,
  },
  okBoxText: { flex: 1, fontSize: 12, fontWeight: "700", color: colors.textMain, lineHeight: 18 },
  lineRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 2, gap: 10 },
  lineLabel: { fontSize: 12, color: colors.textMuted, flexShrink: 1 },
  lineValue: { fontSize: 12, fontWeight: "700", color: colors.textMain, maxWidth: "50%", textAlign: "right" },
  noteLine: { fontSize: 11, color: colors.textMuted, marginTop: 6, lineHeight: 16, fontStyle: "italic" },
  modalWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "center", padding: 24 },
  modalCard: { backgroundColor: colors.surface, borderRadius: 18, padding: 20 },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  modalBody: { fontSize: 13, color: colors.textMuted, marginTop: 6, lineHeight: 19 },
});
