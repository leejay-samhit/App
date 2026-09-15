// Seller · Net Worth + sales ledgers + Excel (Phase 2, Jun-2026).
// Every figure comes from the backend ledger — nothing is added up here.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, spacing, formatINR } from "../../src/theme";
import { downloadServerFile } from "../../src/download";

type NetWorth = {
  shop_name?: string;
  available_balance: number;
  ledger_credits: number;
  ledger_debits: number;
  ledger_balance: number;
  pending_withdrawals: number;
  pending_balance: number;
  in_sync: boolean;
  unledgered_difference: number;
  breakdown: Record<string, number>;
  offline: { turnover: number; gst: number; profit: number; bills: number };
  returns: { open: number; refund_pending_amount: number; refund_pending_count: number };
  outstanding_to_platform: number;
  reconciliation: { formula: string; computed: number; stored: number; difference: number; balanced: boolean };
};

const TABS = [
  { key: "summary", label: "Net worth" },
  { key: "cod", label: "Cash on delivery" },
  { key: "wallet", label: "Wallet" },
  { key: "online", label: "Online" },
  { key: "returns", label: "Returns" },
  { key: "offline", label: "Counter sales" },
] as const;

export default function VendorNetWorthScreen() {
  const router = useRouter();
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("summary");
  const [nw, setNw] = useState<NetWorth | null>(null);
  const [ledger, setLedger] = useState<any>(null);
  const [offline, setOffline] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [orderQ, setOrderQ] = useState("");
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (from) qs.set("date_from", from);
      if (to) qs.set("date_to", to);
      if (orderQ) qs.set("order_id", orderQ);
      const [a, b, c] = await Promise.all([
        api.get<NetWorth>("/vendor/me/net-worth"),
        api.get(`/vendor/me/sales-ledger?${qs.toString()}`),
        api.get(`/vendor/me/offline-ledger?${qs.toString()}`),
      ]);
      setNw(a.data); setLedger(b.data); setOffline(c.data);
    } catch {
      /* keep last good data */
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [from, to, orderQ]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const download = async () => {
    setDownloading(true);
    const qs = new URLSearchParams();
    if (from) qs.set("date_from", from);
    if (to) qs.set("date_to", to);
    if (orderQ) qs.set("order_id", orderQ);
    await downloadServerFile({
      path: `/vendor/me/net-worth/export?${qs.toString()}`,
      filename: `slangcart-net-worth-${new Date().toISOString().slice(0, 10)}.xlsx`,
      mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    setDownloading(false);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="networth-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Net worth</Text>
        <View style={{ flex: 1 }} />
        <TouchableOpacity onPress={download} disabled={downloading} style={styles.xlBtn} testID="networth-export">
          {downloading ? <ActivityIndicator size="small" color="#fff" /> : (
            <>
              <Feather name="download" size={13} color="#fff" />
              <Text style={styles.xlBtnText}>Excel</Text>
            </>
          )}
        </TouchableOpacity>
      </View>

      <View style={styles.tabs}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: spacing.screen, gap: 8 }}>
          {TABS.map((t) => (
            <TouchableOpacity
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[styles.tab, tab === t.key && styles.tabOn]}
              testID={`networth-tab-${t.key}`}
            >
              <Text style={[styles.tabText, tab === t.key && styles.tabTextOn]}>{t.label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          {tab === "summary" && nw ? (
            <>
              <View style={styles.hero}>
                <Text style={styles.heroLabel}>Available balance</Text>
                <Text style={styles.heroValue} testID="networth-available">{formatINR(nw.available_balance)}</Text>
                <View style={styles.heroRow}>
                  <HeroChip label="Cash to collect (COD)" value={formatINR(nw.pending_balance)} />
                  <HeroChip label="Pending withdrawal" value={formatINR(nw.pending_withdrawals)} />
                </View>
                <TouchableOpacity
                  onPress={() => router.push("/vendor/dashboard" as any)}
                  style={styles.heroLink}
                  testID="networth-withdraw"
                >
                  <Text style={styles.heroLinkText}>Withdraw from Dashboard</Text>
                  <Feather name="arrow-right" size={13} color={colors.primary} />
                </TouchableOpacity>
              </View>

              <Section title="Where the money came from and went">
                <Line label="Opening balance" value={formatINR(nw.breakdown.opening || 0)} />
                <Line label="Sales credited" value={formatINR(nw.breakdown.sales || 0)} />
                <Line label="Delivery charges paid to Slangcart" value={`− ${formatINR(nw.breakdown.delivery_charges || 0)}`} />
                <Line label="Refunds paid on returns" value={`− ${formatINR(nw.breakdown.refunds || 0)}`} />
                <Line label="Withdrawals" value={`− ${formatINR(nw.breakdown.withdrawals || 0)}`} />
                <Line label="Cashback funded" value={`− ${formatINR(nw.breakdown.cashback_funded || 0)}`} />
                {nw.breakdown.adjustments ? (
                  <Line label="Adjustments" value={formatINR(nw.breakdown.adjustments)} />
                ) : null}
                <View style={styles.divider} />
                <Line label="Ledger balance" value={formatINR(nw.ledger_balance)} bold />
              </Section>

              <Section title="Returns">
                <Line label="Open returns" value={String(nw.returns.open)} />
                <Line label="Refunds waiting on your balance" value={formatINR(nw.returns.refund_pending_amount)} />
                <TouchableOpacity onPress={() => router.push("/vendor/returns" as any)} style={styles.inlineLink} testID="networth-open-returns">
                  <Text style={styles.inlineLinkText}>Open Returns</Text>
                  <Feather name="arrow-right" size={13} color={colors.primary} />
                </TouchableOpacity>
              </Section>

              <Section title="Counter (offline) sales">
                <Line label="Turnover" value={formatINR(nw.offline.turnover)} />
                <Line label="GST collected" value={formatINR(nw.offline.gst)} />
                <Line label="Profit" value={formatINR(nw.offline.profit)} />
                <Line label="Bills" value={String(nw.offline.bills)} />
              </Section>

              <View style={[styles.recon, nw.reconciliation.balanced ? styles.reconOk : styles.reconBad]}>
                <Feather
                  name={nw.reconciliation.balanced ? "check-circle" : "alert-triangle"}
                  size={16}
                  color={nw.reconciliation.balanced ? "#166534" : "#92400E"}
                />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.reconTitle, { color: nw.reconciliation.balanced ? "#166534" : "#92400E" }]}>
                    {nw.reconciliation.balanced ? "Every rupee accounted for" : "Ledger difference found"}
                  </Text>
                  <Text style={styles.reconBody}>{nw.reconciliation.formula}</Text>
                  {!nw.reconciliation.balanced ? (
                    <Text style={styles.reconBody}>
                      Difference {formatINR(nw.reconciliation.difference)} — reported, never hidden.
                    </Text>
                  ) : null}
                </View>
              </View>
            </>
          ) : null}

          {tab !== "summary" ? (
            <View style={styles.filters}>
              <TextInput value={from} onChangeText={setFrom} placeholder="From YYYY-MM-DD" placeholderTextColor={colors.textMuted} style={styles.filterInput} testID="networth-from" />
              <TextInput value={to} onChangeText={setTo} placeholder="To YYYY-MM-DD" placeholderTextColor={colors.textMuted} style={styles.filterInput} testID="networth-to" />
              <TouchableOpacity onPress={() => { setLoading(true); load(); }} style={styles.applyBtn} testID="networth-apply">
                <Feather name="filter" size={14} color="#fff" />
              </TouchableOpacity>
            </View>
          ) : null}

          {tab === "cod" && ledger?.cod ? (
            <>
              <Totals rows={[
                ["Item amount", ledger.cod.item_amount],
                ["Delivery charge", ledger.cod.delivery_charge],
                ["Cash to collect", ledger.cod.cash_to_collect],
              ]} count={ledger.cod.count} />
              {ledger.cod.rows.map((r: any) => (
                <LedgerCard key={r.order_id} r={r} lines={[
                  ["Customer", r.customer],
                  ["Item amount", formatINR(r.item_amount)],
                  ["Delivery charge", formatINR(r.delivery_charge)],
                  ["Cash due", formatINR(r.cod_amount)],
                  ["Settlement", r.settlement_status],
                  ["Transaction", r.transaction_id || "—"],
                ]} />
              ))}
            </>
          ) : null}

          {tab === "wallet" && ledger?.wallet ? (
            <>
              <Totals rows={[
                ["Wallet paid", ledger.wallet.wallet_amount],
                ["Credited to you", ledger.wallet.vendor_credit],
                ["Delivery charge", ledger.wallet.delivery_charge],
                ["Paid to treasury", ledger.wallet.treasury_deduction],
              ]} count={ledger.wallet.count} />
              {ledger.wallet.rows.map((r: any) => (
                <LedgerCard key={r.order_id} r={r} lines={[
                  ["Wallet amount", formatINR(r.wallet_amount)],
                  ["Your credit", formatINR(r.vendor_credit)],
                  ["Delivery charge", formatINR(r.delivery_charge)],
                  ["Treasury deduction", formatINR(r.treasury_deduction)],
                  ["Remaining with you", formatINR(r.remaining_vendor_amount)],
                  ["Transaction", r.transaction_id || "—"],
                ]} />
              ))}
            </>
          ) : null}

          {tab === "online" && ledger?.online ? (
            <>
              <Totals rows={[
                ["Item amount", ledger.online.item_amount],
                ["Delivery charge", ledger.online.delivery_charge],
                ["Credited to you", ledger.online.vendor_credit],
              ]} count={ledger.online.count} />
              {ledger.online.rows.map((r: any) => (
                <LedgerCard key={r.order_id} r={r} lines={[
                  ["Item amount", formatINR(r.item_amount)],
                  ["Delivery charge", formatINR(r.delivery_charge)],
                  ["Razorpay payment", r.razorpay_payment_id || "—"],
                  ["Your credit", formatINR(r.vendor_credit)],
                  ["Settlement", r.settlement_status],
                  ["Transaction", r.transaction_id || "—"],
                ]} />
              ))}
            </>
          ) : null}

          {tab === "returns" && ledger?.returns ? (
            <>
              <Totals rows={[
                ["Original amount", ledger.returns.original_amount],
                ["Refunded", ledger.returns.refund_amount],
              ]} count={ledger.returns.count} />
              {ledger.returns.rows.map((r: any, i: number) => (
                <View key={`${r.return_id}-${i}`} style={styles.card}>
                  <Text style={styles.cardTitle}>{r.return_number} · {r.product}</Text>
                  <Line label="Original order" value={r.original_order_number} />
                  <Line label="Qty" value={String(r.qty)} />
                  <Line label="Original amount" value={formatINR(r.original_amount)} />
                  <Line label="Refund amount" value={formatINR(r.refund_amount)} />
                  <Line label="Original payment" value={r.original_payment_method || "—"} />
                  <Line label="Debited from you" value={formatINR(r.vendor_debit)} />
                  <Line label="Credited to customer" value={formatINR(r.customer_credit)} />
                  <Line label="Stock restored" value={r.inventory_restored ? "Yes" : "Not yet"} />
                  <Line label="Transaction" value={r.transaction_id || "—"} />
                </View>
              ))}
            </>
          ) : null}

          {tab === "offline" && offline ? (
            <>
              {(["cash", "upi", "card"] as const).map((mode) => (
                <View key={mode}>
                  <Text style={styles.groupLabel}>{mode.toUpperCase()} · {formatINR(offline[mode]?.amount || 0)} · GST {formatINR(offline[mode]?.gst || 0)}</Text>
                  {(offline[mode]?.rows || []).length === 0 ? (
                    <Text style={styles.emptySmall}>No {mode} sales in this range.</Text>
                  ) : offline[mode].rows.map((r: any, i: number) => (
                    <View key={`${r.raw_id}-${i}`} style={styles.card}>
                      <Text style={styles.cardTitle}>{r.sale_id}</Text>
                      <Line label="Product" value={r.product || "—"} />
                      <Line label="Qty" value={String(r.qty)} />
                      <Line label="Amount" value={formatINR(r.amount)} />
                      <Line label="GST" value={formatINR(r.gst)} />
                      {r.reference ? <Line label="Reference" value={r.reference} /> : null}
                      <Line label="Payment status" value={r.payment_status} />
                      <Line label="Net worth impact" value={formatINR(r.net_worth_impact)} />
                    </View>
                  ))}
                </View>
              ))}
            </>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function HeroChip({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.heroChip}>
      <Text style={styles.heroChipLabel}>{label}</Text>
      <Text style={styles.heroChipValue}>{value}</Text>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.block}>
      <Text style={styles.blockTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Line({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={styles.lineRow}>
      <Text style={styles.lineLabel}>{label}</Text>
      <Text style={[styles.lineValue, bold && { fontWeight: "900" }]} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function Totals({ rows, count }: { rows: [string, number][]; count: number }) {
  return (
    <View style={styles.totals}>
      <Text style={styles.totalsCount}>{count} row{count === 1 ? "" : "s"}</Text>
      {rows.map(([l, v]) => (
        <View key={l} style={styles.lineRow}>
          <Text style={styles.lineLabel}>{l}</Text>
          <Text style={styles.lineValue}>{formatINR(v || 0)}</Text>
        </View>
      ))}
    </View>
  );
}

function LedgerCard({ r, lines }: { r: any; lines: [string, string][] }) {
  return (
    <View style={styles.card}>
      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <Text style={[styles.cardTitle, { flex: 1 }]}>{r.order_number}</Text>
        <Text style={styles.cardAmount}>{formatINR(r.total)}</Text>
      </View>
      <Text style={styles.cardMeta}>
        {String(r.payment_method || "").replace("_", " + ")} · {r.status} ·{" "}
        {r.created_at ? String(r.created_at).slice(0, 10) : ""}
      </Text>
      {lines.map(([l, v]) => <Line key={l} label={l} value={v} />)}
    </View>
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
  xlBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary,
    paddingHorizontal: 14, minHeight: 40, borderRadius: 999, justifyContent: "center",
  },
  xlBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 12 },
  tabs: { paddingVertical: 10, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: {
    paddingHorizontal: 13, paddingVertical: 8, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  tabOn: { backgroundColor: colors.brand100, borderColor: colors.primary },
  tabText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  tabTextOn: { color: colors.primary },
  hero: { backgroundColor: colors.primary, borderRadius: 18, padding: 20 },
  heroLabel: { color: "rgba(255,255,255,0.8)", fontSize: 12, fontWeight: "700" },
  heroValue: { color: colors.primaryFg, fontSize: 32, fontWeight: "900", marginTop: 4 },
  heroRow: { flexDirection: "row", gap: 10, marginTop: 14 },
  heroChip: { flex: 1, backgroundColor: "rgba(255,255,255,0.14)", borderRadius: 12, padding: 10 },
  heroChipLabel: { color: "rgba(255,255,255,0.85)", fontSize: 10, fontWeight: "700" },
  heroChipValue: { color: colors.primaryFg, fontSize: 15, fontWeight: "900", marginTop: 3 },
  heroLink: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 14, backgroundColor: colors.surface, alignSelf: "flex-start", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999 },
  heroLinkText: { color: colors.primary, fontWeight: "800", fontSize: 12 },
  block: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14,
    padding: 16, marginTop: 12,
  },
  blockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 10 },
  lineRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, gap: 12 },
  lineLabel: { fontSize: 12, color: colors.textMuted, flexShrink: 1 },
  lineValue: { fontSize: 12, fontWeight: "700", color: colors.textMain, maxWidth: "55%", textAlign: "right" },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 8 },
  inlineLink: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10 },
  inlineLinkText: { color: colors.primary, fontWeight: "800", fontSize: 12 },
  recon: { flexDirection: "row", gap: 10, borderRadius: 14, padding: 14, marginTop: 12, alignItems: "flex-start" },
  reconOk: { backgroundColor: "#DCFCE7" },
  reconBad: { backgroundColor: "#FEF3C7" },
  reconTitle: { fontSize: 13, fontWeight: "900" },
  reconBody: { fontSize: 11, color: colors.textMain, marginTop: 3, lineHeight: 16 },
  filters: { flexDirection: "row", gap: 8, marginBottom: 12 },
  filterInput: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10,
    minHeight: 44, color: colors.textMain, backgroundColor: colors.surface, fontSize: 12,
  },
  applyBtn: {
    backgroundColor: colors.primary, width: 48, minHeight: 44, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
  },
  totals: {
    backgroundColor: colors.brand100, borderRadius: 12, padding: 14, marginBottom: 12,
  },
  totalsCount: { fontSize: 11, fontWeight: "900", color: colors.primary, marginBottom: 6 },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    padding: 12, marginBottom: 8,
  },
  cardTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain },
  cardAmount: { fontSize: 14, fontWeight: "900", color: colors.textMain },
  cardMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2, marginBottom: 6 },
  groupLabel: {
    fontSize: 12, fontWeight: "900", color: colors.primary, marginTop: 10, marginBottom: 8,
    letterSpacing: 0.5,
  },
  emptySmall: { fontSize: 12, color: colors.textMuted, marginBottom: 10 },
});
