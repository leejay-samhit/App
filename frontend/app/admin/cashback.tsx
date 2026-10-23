import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, TextInput, Modal, Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { notify } from "../../src/notify";
import { downloadServerFile } from "../../src/download";
import { DateRangeFilter } from "../../src/date-range-picker";
import { useTabSwipe } from "../../src/use-swipe-pager";

type PendingRow = {
  order_id: string;
  order_number?: string;
  amount: number;
  customer_name?: string;
  customer_phone?: string;
  vendor_name?: string;
  vendor_phone?: string;
  vendor_wallet_balance?: number;
  created_at?: string;
};

type GroupRow = { key: string; label: string; credits: number; debits: number; net: number; count: number };

export default function AdminCashbackScreen() {
  const router = useRouter();
  const [tab, setTab] = useState<"pending" | "outstanding" | "export">("pending");
const swipe = useTabSwipe(["pending", "outstanding", "export"] as const, tab, setTab);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<PendingRow[]>([]);
  const [pendingTotal, setPendingTotal] = useState(0);
  const [outstanding, setOutstanding] = useState<any[]>([]);
  const [outstandingTotal, setOutstandingTotal] = useState(0);
  // Oct-2026 — Excel download + manual recovery (cash / UPI deposit).
  const [dlBusy, setDlBusy] = useState<string | null>(null);
  const [recoverFor, setRecoverFor] = useState<any | null>(null);
  const [recoverAmount, setRecoverAmount] = useState("");
  const [recoverMsg, setRecoverMsg] = useState("");
  const [recoverBusy, setRecoverBusy] = useState(false);
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [summaryTotal, setSummaryTotal] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [groupKey, setGroupKey] = useState("");

  const load = useCallback(async () => {
    try {
      const [p, o, s] = await Promise.all([
        api.get("/admin/cashback/pending"),
        api.get("/admin/cashback/outstanding"),
        api.get("/admin/wallet/groupwise-summary"),
      ]);
      setPending(p.data?.items || []);
      setPendingTotal(Number(p.data?.total_amount || 0));
      setOutstanding(o.data?.vendors || []);
      setOutstandingTotal(Number(o.data?.total || 0));
      setGroups(s.data?.groups || []);
      setSummaryTotal(s.data?.total || null);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const reloadSummary = useCallback(async () => {
    const qs = new URLSearchParams();
    if (dateFrom.trim()) qs.set("date_from", dateFrom.trim());
    if (dateTo.trim()) qs.set("date_to", dateTo.trim());
    if (groupKey) qs.set("group", groupKey);
    try {
      const { data } = await api.get(`/admin/wallet/groupwise-summary?${qs.toString()}`);
      setGroups(data?.groups || []);
      setSummaryTotal(data?.total || null);
    } catch (e) {
      notify("Could not load summary", formatApiError(e));
    }
  }, [dateFrom, dateTo, groupKey]);

  const onFund = async (orderId: string) => {
    setBusy(orderId);
    try {
      const { data } = await api.post(`/admin/cashback/${orderId}/fund`);
      notify("Cashback released", `${formatINR(data?.amount || 0)} credited to the customer wallet (funded by ${data?.funded_by}).`);
      await load();
    } catch (e) {
      notify("Could not release cashback", formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const onExport = async () => {
    const qs = new URLSearchParams();
    if (dateFrom.trim()) qs.set("date_from", dateFrom.trim());
    if (dateTo.trim()) qs.set("date_to", dateTo.trim());
    if (groupKey) qs.set("group", groupKey);
    setBusy("export");
    try {
      await downloadServerFile({
        path: `/admin/wallet/export/groupwise?${qs.toString()}`,
        filename: `slangcart-wallet-${groupKey || "all"}.xlsx`,
        mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      notify("Excel downloaded", "Group-wise wallet report saved to your device.");
    } catch (e) {
      notify("Export failed", formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const onDownloadOutstanding = async (status: "all" | "open" | "settled") => {
    setDlBusy(status);
    try {
      const r = await downloadServerFile({
        path: `/admin/cashback/outstanding/export?status=${status}`,
        filename: `seller-cashback-${status}.csv`,
        mimeType: "text/csv",
      });
      if (r.ok) notify("Downloaded", "Open it in Excel or Google Sheets.");
    } catch (e) {
      notify("Download failed", formatApiError(e));
    } finally {
      setDlBusy(null);
    }
  };

  const onRecover = async () => {
    if (!recoverFor) return;
    const amt = parseFloat(recoverAmount);
    if (!amt || amt <= 0) { setRecoverMsg("Enter the amount to collect."); return; }
    setRecoverBusy(true);
    setRecoverMsg("");
    try {
      const { data } = await api.post(
        `/admin/cashback/outstanding/${recoverFor.vendor_id}/recover`,
        { amount: amt, note: "Shop earnings wallet recovery" },
      );
      setRecoverFor(null);
      notify(
        "Recovered from wallet",
        `${formatINR(data.applied)} moved from the seller's shop earnings wallet to the treasury`
        + `${data.unapplied > 0 ? ` · ${formatINR(data.unapplied)} could not be collected yet` : ""}.`,
      );
      load();
    } catch (e) {
      setRecoverMsg(formatApiError(e));
    } finally {
      setRecoverBusy(false);
    }
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} {...swipe}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.head}>
          <TouchableOpacity onPress={() => router.back()} hitSlop={10} testID="cashback-back">
            <Feather name="chevron-left" size={24} color={colors.textMain} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Cashback &amp; reports</Text>
          </View>
        </View>

        <View style={styles.tabRow}>
          {([
            ["pending", "Pending", pending.length],
            ["outstanding", "Outstanding", outstanding.length],
            ["export", "Excel", 0],
          ] as const).map(([key, label, count]) => (
            <TouchableOpacity
              key={key}
              onPress={() => setTab(key as any)}
              style={[styles.tab, tab === key && styles.tabActive]}
              testID={`cashback-tab-${key}`}
            >
              <Text style={[styles.tabText, tab === key && styles.tabTextActive]}>
                {label}{count ? ` (${count})` : ""}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {tab === "pending" ? (
          <>
            <View style={styles.statCard}>
              <Text style={styles.statLabel}>CASHBACK WAITING TO BE FUNDED</Text>
              <Text style={styles.statValue} testID="cashback-pending-total">{formatINR(pendingTotal)}</Text>
              <Text style={styles.statHelp}>
                These orders were delivered but the seller wallet could not cover the
                cashback. Release it to pay the customer now — the amount becomes
                recoverable from the seller.
              </Text>
            </View>
            {pending.length === 0 ? (
              <Text style={styles.empty}>Nothing pending. Every delivered order has paid its cashback.</Text>
            ) : pending.map((r) => (
              <View key={r.order_id} style={styles.row} testID={`cashback-row-${r.order_id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{r.order_number || r.order_id.slice(0, 8)} · {formatINR(r.amount)}</Text>
                  <Text style={styles.rowSub}>
                    {r.customer_name || "Customer"}
                    {r.customer_phone ? ` · ${r.customer_phone}` : ""}
                  </Text>
                  <Text style={styles.rowSub}>
                    Seller: {r.vendor_name || "—"}
                    {r.vendor_phone ? ` · ${r.vendor_phone}` : ""}
                    {` · wallet ${formatINR(r.vendor_wallet_balance || 0)}`}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={() => onFund(r.order_id)}
                  disabled={busy === r.order_id}
                  style={[styles.actionBtn, busy === r.order_id && { opacity: 0.6 }]}
                  testID={`cashback-fund-${r.order_id}`}
                >
                  {busy === r.order_id
                    ? <ActivityIndicator size="small" color={colors.primaryFg} />
                    : <Text style={styles.actionBtnText}>Release</Text>}
                </TouchableOpacity>
              </View>
            ))}
          </>
        ) : null}

        {tab === "outstanding" ? (
          <>
            <View style={styles.statCard}>
              <Text style={styles.statLabel}>RECOVERABLE FROM SELLERS</Text>
              <Text style={styles.statValue} testID="cashback-outstanding-total">{formatINR(outstandingTotal)}</Text>
              <Text style={styles.statHelp}>
                Cashback Slangcart paid customers on a seller&apos;s behalf. It is settled
                when the seller adds money or from their next sales settlement.
              </Text>
            </View>
            {/* Oct-2026 — Excel download so the owner can track who is
                pending and who has cleared outside the app. */}
            <View style={styles.dlRow}>
              {(["all", "open", "settled"] as const).map((st) => (
                <TouchableOpacity
                  key={st}
                  onPress={() => onDownloadOutstanding(st)}
                  disabled={dlBusy !== null}
                  style={[styles.dlBtn, dlBusy === st && { opacity: 0.55 }]}
                  testID={`cashback-outstanding-export-${st}`}
                >
                  {dlBusy === st
                    ? <ActivityIndicator size="small" color={colors.primary} />
                    : <Feather name="download" size={13} color={colors.primary} />}
                  <Text style={styles.dlBtnText}>
                    {st === "all" ? "All" : st === "open" ? "Pending" : "Cleared"}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {outstanding.length === 0 ? (
              <Text style={styles.empty}>No seller owes Slangcart any cashback.</Text>
            ) : outstanding.map((v) => (
              <TouchableOpacity
                key={v.vendor_id}
                style={styles.row}
                onPress={() => { setRecoverFor(v); setRecoverAmount(String(v.recoverable_now ?? v.outstanding)); setRecoverMsg(""); }}
                testID={`cashback-recover-open-${v.vendor_id}`}
                activeOpacity={0.8}
              >
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{v.vendor_name || v.vendor_id.slice(0, 8)}</Text>
                  <Text style={styles.rowSub}>
                    {v.orders} item{v.orders === 1 ? "" : "s"} · wallet {formatINR(Number(v.wallet_balance || 0))} · tap to collect
                  </Text>
                  {Number(v.advance_outstanding || 0) > 0 ? (
                    <Text style={styles.rowSub}>
                      cashback {formatINR(Number(v.cashback_outstanding || 0))} · refunds we paid{" "}
                      {formatINR(Number(v.advance_outstanding || 0))}
                    </Text>
                  ) : null}
                </View>
                <Text style={styles.rowAmount}>{formatINR(v.outstanding)}</Text>
                <Feather name="chevron-right" size={16} color={colors.textMuted} />
              </TouchableOpacity>
            ))}
          </>
        ) : null}

        {tab === "export" ? (
          <>
            <Text style={styles.sectionLabel}>FILTERS</Text>
            <View style={styles.filterRow}>
              <DateRangeFilter
                value={{ from: dateFrom, to: dateTo }}
                onChange={(r) => { setDateFrom(r.from); setDateTo(r.to); }}
                testID="export-date"
              />
            </View>

            <Text style={styles.sectionLabel}>TRANSACTION GROUP</Text>
            <View style={styles.chipWrap}>
              <TouchableOpacity
                onPress={() => setGroupKey("")}
                style={[styles.chip, groupKey === "" && styles.chipActive]}
                testID="export-group-all"
              >
                <Text style={[styles.chipText, groupKey === "" && styles.chipTextActive]}>All groups</Text>
              </TouchableOpacity>
              {groups.map((g) => (
                <TouchableOpacity
                  key={g.key}
                  onPress={() => setGroupKey(g.key)}
                  style={[styles.chip, groupKey === g.key && styles.chipActive]}
                  testID={`export-group-${g.key}`}
                >
                  <Text style={[styles.chipText, groupKey === g.key && styles.chipTextActive]}>
                    {g.label} ({g.count})
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <TouchableOpacity onPress={reloadSummary} style={styles.ghostBtn} testID="export-apply">
              <Feather name="filter" size={14} color={colors.primary} />
              <Text style={styles.ghostBtnText}>Apply filters</Text>
            </TouchableOpacity>

            <Text style={styles.sectionLabel}>WHAT THE EXCEL WILL CONTAIN</Text>
            {groups.map((g) => (
              <View key={g.key} style={styles.row}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle}>{g.label}</Text>
                  <Text style={styles.rowSub}>
                    {g.count} txns · Cr {formatINR(g.credits)} · Dr {formatINR(g.debits)}
                  </Text>
                </View>
                <Text style={[styles.rowAmount, g.net < 0 && { color: "#B3261E" }]}>{formatINR(g.net)}</Text>
              </View>
            ))}
            {summaryTotal ? (
              <View style={styles.totalBox} testID="export-total">
                <Text style={styles.totalLabel}>
                  {summaryTotal.count} transactions · Credits {formatINR(summaryTotal.credits)} ·
                  Debits {formatINR(summaryTotal.debits)}
                </Text>
                <Text style={styles.totalValue}>Net {formatINR(summaryTotal.net)}</Text>
              </View>
            ) : null}

            <TouchableOpacity
              onPress={onExport}
              disabled={busy === "export"}
              style={[styles.primaryBtn, busy === "export" && { opacity: 0.7 }]}
              testID="export-download"
            >
              {busy === "export" ? <ActivityIndicator color={colors.primaryFg} /> : (
                <>
                  <Feather name="download" size={16} color={colors.primaryFg} />
                  <Text style={styles.primaryBtnText}>Download group-wise Excel</Text>
                </>
              )}
            </TouchableOpacity>
            <Text style={styles.statHelp}>
              One sheet per group plus Customer / Vendor / Admin wallet sheets. Every row
              carries its permanent short ID (TXNA1, ORD1 …) and each sheet ends with a
              Group Summary: opening balance, credits, debits, net, count, closing balance.
            </Text>
          </>
        ) : null}
      </ScrollView>

      {/* Jun-2026 — ONE recovery process: pull it from the seller's shop
          earnings wallet. The old "cash received" / "UPI deposit" entries
          asked the admin to type money that had not necessarily moved and
          could be entered twice. */}
      <Modal visible={!!recoverFor} transparent animationType="slide" onRequestClose={() => setRecoverFor(null)}>
        <Pressable style={styles.recBackdrop} onPress={() => setRecoverFor(null)} />
        <View style={styles.recSheet} testID="cashback-recover-sheet">
          <View style={styles.recGrab} />
          <Text style={styles.recTitle}>Shop earnings wallet recovery</Text>
          <Text style={styles.recSub}>
            {recoverFor?.vendor_name || "Seller"} owes {formatINR(Number(recoverFor?.outstanding || 0))}
            {Number(recoverFor?.advance_outstanding || 0) > 0
              ? ` — ${formatINR(Number(recoverFor?.cashback_outstanding || 0))} cashback + ${formatINR(Number(recoverFor?.advance_outstanding || 0))} refunds we paid`
              : ""}
          </Text>

          <View style={styles.recWalletCard} testID="recover-wallet-card">
            <View style={styles.recWalletRow}>
              <Text style={styles.recWalletLabel}>Seller wallet balance</Text>
              <Text style={styles.recWalletValue} testID="recover-wallet-balance">
                {formatINR(Number(recoverFor?.wallet_balance || 0))}
              </Text>
            </View>
            <View style={styles.recWalletRow}>
              <Text style={styles.recWalletLabel}>Can be collected now</Text>
              <Text style={[styles.recWalletValue, { color: colors.primary }]} testID="recover-collectable">
                {formatINR(Number(recoverFor?.recoverable_now || 0))}
              </Text>
            </View>
          </View>

          <Text style={styles.fieldLabel}>Amount to collect (₹)</Text>
          <TextInput
            value={recoverAmount}
            onChangeText={setRecoverAmount}
            keyboardType="decimal-pad"
            style={styles.input}
            placeholderTextColor={colors.textMuted}
            testID="recover-amount"
          />
          <Text style={styles.recNote}>
            This moves the money out of the seller&apos;s shop earnings wallet into the
            System Wallet treasury — one wallet debit, one treasury credit, nothing
            typed twice. Whatever is left is recovered automatically from his next sale.
          </Text>

          {recoverMsg ? <Text style={styles.recError}>{recoverMsg}</Text> : null}

          <TouchableOpacity
            onPress={onRecover}
            disabled={recoverBusy || Number(recoverFor?.recoverable_now || 0) <= 0}
            style={[styles.primaryBtn, (recoverBusy || Number(recoverFor?.recoverable_now || 0) <= 0) && { opacity: 0.6 }]}
            testID="recover-submit"
          >
            {recoverBusy
              ? <ActivityIndicator color={colors.primaryFg} />
              : <><Feather name="check-circle" size={16} color={colors.primaryFg} />
                  <Text style={styles.primaryBtnText}>Collect from wallet</Text></>}
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setRecoverFor(null)} style={styles.recCancel} testID="recover-cancel">
            <Text style={styles.recCancelText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 48 },
  head: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 16 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  h1: { fontSize: 24, fontWeight: "800", color: colors.textMain, letterSpacing: -0.6 },
  tabRow: { flexDirection: "row", gap: 8, marginBottom: 16 },
  tab: { flex: 1, paddingVertical: 10, alignItems: "center", borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabText: { fontSize: 12, fontWeight: "800", color: colors.textMuted },
  tabTextActive: { color: colors.primaryFg },
  statCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 16, marginBottom: 16 },
  statLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 1.6, fontWeight: "700" },
  statValue: { color: colors.primaryFg, fontSize: 28, fontWeight: "800", marginTop: 4, letterSpacing: -1 },
  statHelp: { color: "rgba(255,255,255,0.82)", fontSize: 11, marginTop: 8, lineHeight: 16 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8, marginTop: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 12, marginBottom: 8 },
  rowTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  rowSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  rowAmount: { fontSize: 14, fontWeight: "800", color: colors.primary },
  actionBtn: { backgroundColor: colors.primary, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 999, minWidth: 76, alignItems: "center" },
  actionBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 12 },
  empty: { fontSize: 13, color: colors.textMuted, textAlign: "center", paddingVertical: 24 },
  filterRow: { marginHorizontal: -spacing.screen },
  fieldLabel: { fontSize: 12, fontWeight: "700", color: colors.textMain, marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 12, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 11, fontWeight: "700", color: colors.textMuted },
  chipTextActive: { color: colors.primaryFg },
  ghostBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, marginTop: 12, borderRadius: radii.button, borderWidth: 1, borderColor: colors.primary },
  ghostBtnText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  totalBox: { backgroundColor: colors.surfaceMuted, borderRadius: radii.card, padding: 14, marginTop: 4 },
  totalLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  totalValue: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 16 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  // Excel download row on the Outstanding tab
  dlRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  dlBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, minHeight: 42, borderRadius: 10,
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface,
  },
  dlBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  recWalletCard: {
    marginTop: 4, marginBottom: 14, padding: 12, borderRadius: radii.card,
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
    gap: 6,
  },
  recWalletRow: { flexDirection: "row", justifyContent: "space-between", gap: 10 },
  recWalletLabel: { fontSize: 12.5, color: colors.textMuted, fontWeight: "600" },
  recWalletValue: { fontSize: 13.5, color: colors.textMain, fontWeight: "800" },
  // Manual-recovery bottom sheet
  recBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  recSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: 20, paddingTop: 10, paddingBottom: 28,
  },
  recGrab: { alignSelf: "center", width: 44, height: 4, borderRadius: 2, backgroundColor: colors.border, marginBottom: 16 },
  recTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  recSub: { fontSize: 13, color: colors.textMuted, marginTop: 3, marginBottom: 16, fontWeight: "600" },
  recNote: { fontSize: 11, lineHeight: 16, color: colors.textMuted, marginTop: 8 },
  recError: { fontSize: 12.5, color: "#B3261E", fontWeight: "700", marginTop: 10 },
  recCancel: { alignItems: "center", paddingVertical: 14, marginTop: 4 },
  recCancelText: { fontSize: 13, fontWeight: "700", color: colors.textMuted },
});
