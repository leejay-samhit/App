// Cash register summary — mirrors /vendor/cash on the web.
// Shows today's cash breakdown by payment mode, opening balance,
// expected close, and receipt count.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { colors, spacing, formatINR } from "../../src/theme";
import { getCashSummary, PosCashSummary, getStatement, PosStatementRow, localDateStr } from "../../src/vendor-pos-client";
import { formatApiError } from "../../src/api";

const MODE_LABEL: Record<string, string> = {
  cash: "Cash", upi: "UPI", debit: "Debit", credit: "Credit",
  netbank: "Net Bank", wallet: "Wallet", credit_sale: "Credit sale",
};

export default function VendorCash() {
  const router = useRouter();
  const [data, setData] = useState<PosCashSummary | null>(null);
  const [stmt, setStmt] = useState<PosStatementRow[]>([]);
  const [running, setRunning] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      // Jun 2026 — LOCAL date, not UTC: `toISOString()` rolled the day back
      // for every bill rung up before 05:30 IST, leaving the cash summary
      // blank for the vendor's morning trade.
      const today = localDateStr();
      const [c, s] = await Promise.all([
        getCashSummary(today),
        getStatement(today, today),
      ]);
      setData(c); setStmt(s.items); setRunning(s.running_balance);
    } catch (e) { Alert.alert("Load failed", formatApiError(e)); }
    finally { setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (!data) return <SafeAreaView style={{ flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center" }}><ActivityIndicator color={colors.primary} /></SafeAreaView>;

  const modes = Object.entries(data.by_mode || {});

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Cash register</Text>
          <Text style={styles.sub}>Today · {data.date}</Text>
        </View>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      >
        <View style={styles.grandCard}>
          <Text style={styles.grandLabel}>Expected close</Text>
          <Text style={styles.grandValue}>{formatINR(data.expected_close)}</Text>
          <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 12 }}>
            <Kv label="Opening" value={formatINR(data.opening_balance)} />
            <Kv label="Cash received" value={formatINR(data.cash_received)} />
          </View>
          {/* Jun 2026 — day turnover across ALL modes + bill count. The old
              card only showed the cash slice, so a UPI-heavy day looked
              like the vendor had sold nothing. */}
          <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 12 }}>
            <Kv label="Collected (all modes)" value={formatINR(data.total_collected ?? 0)} />
            <Kv label="Bills today" value={String(data.bills ?? 0)} />
          </View>
        </View>

        <Text style={styles.sectionLabel}>Breakdown by mode</Text>
        {modes.length === 0 ? <Text style={{ color: colors.textMuted }}>No payments yet today.</Text> : modes.map(([m, v]) => (
          <View key={m} style={styles.modeRow}>
            <View>
              <Text style={styles.modeLabel}>{MODE_LABEL[m] || m}</Text>
              <Text style={styles.modeMeta}>{v.count} payment{v.count === 1 ? "" : "s"}</Text>
            </View>
            <Text style={styles.modeAmount}>{formatINR(v.amount)}</Text>
          </View>
        ))}

        <Text style={styles.sectionLabel}>Today's statement · running ₹ {formatINR(running)}</Text>
        {stmt.length === 0 ? <Text style={{ color: colors.textMuted }}>No sales yet today.</Text> : stmt.map(r => (
          <View key={r.id} style={styles.stmtRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.stmtInv}>{r.invoice_no}</Text>
              <Text style={styles.stmtMeta}>{r.customer} · {new Date(r.created_at).toLocaleTimeString("en-IN")}</Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={styles.stmtAmt}>+ {formatINR(r.amount)}</Text>
              <Text style={styles.stmtRun}>bal {formatINR(r.running)}</Text>
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

function Kv({ label, value }: { label: string; value: string }) {
  // Rendered on the dark-green hero card — needs light-on-dark colours.
  return (
    <View>
      <Text style={{ fontSize: 11, color: "rgba(255,255,255,0.8)" }}>{label}</Text>
      <Text style={{ fontSize: 14, fontWeight: "800", color: "#fff", marginTop: 2 }}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { padding: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  sub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  grandCard: { padding: 18, backgroundColor: colors.primary, borderRadius: 16, marginBottom: 12 },
  grandLabel: { color: "rgba(255,255,255,0.85)", fontSize: 12, fontWeight: "700" },
  grandValue: { color: "#fff", fontSize: 30, fontWeight: "900", marginTop: 4 },
  sectionLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, textTransform: "uppercase", marginTop: 16, marginBottom: 6 },
  modeRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 6 },
  modeLabel: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  modeMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  modeAmount: { fontSize: 16, fontWeight: "900", color: colors.primary },
  stmtRow: { flexDirection: "row", alignItems: "center", padding: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, marginBottom: 6 },
  stmtInv: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  stmtMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  stmtAmt: { fontSize: 14, fontWeight: "800", color: "#166534" },
  stmtRun: { fontSize: 10, color: colors.textMuted, marginTop: 2 },
});
