// Analytics screen — mirrors /vendor/analytics on the web.
// KPI cards + top-sold / top-revenue / top-gst / least-sold + tiny daily bar chart.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert, Dimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { colors, spacing, formatINR } from "../../src/theme";
import { getAnalytics, getDashboard, PosAnalytics, PosDashboard } from "../../src/vendor-pos-client";
import { formatApiError } from "../../src/api";

const DAYS_OPTIONS = [7, 15, 30, 60, 90];

export default function VendorAnalytics() {
  const router = useRouter();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<PosAnalytics | null>(null);
  const [dash, setDash] = useState<PosDashboard | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, d] = await Promise.all([getAnalytics(days), getDashboard()]);
      setData(a); setDash(d);
    } catch (e) { Alert.alert("Load failed", formatApiError(e)); }
    finally { setLoading(false); }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const maxDay = data ? Math.max(1, ...data.daily.map(d => d.turnover)) : 1;
  const chartW = Dimensions.get("window").width - spacing.screen * 2 - 24;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Analytics</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
        {/* Today + Month KPIs */}
        {dash ? (
          <View style={{ flexDirection: "row", gap: 10, marginBottom: 12 }}>
            <Kpi title="Today" bills={dash.today.bills} turnover={dash.today.turnover} gst={dash.today.gst} profit={dash.today.profit} />
            <Kpi title="This month" bills={dash.month.bills} turnover={dash.month.turnover} gst={dash.month.gst} profit={dash.month.profit} />
          </View>
        ) : null}

        {/* Day filter */}
        <View style={{ flexDirection: "row", gap: 6, marginBottom: 10 }}>
          {DAYS_OPTIONS.map(d => (
            <TouchableOpacity key={d} onPress={() => setDays(d)} style={[styles.chip, days === d && { backgroundColor: colors.brand100, borderColor: colors.primary }]}>
              <Text style={{ color: days === d ? colors.primary : colors.textMuted, fontWeight: "700", fontSize: 12 }}>{d}d</Text>
            </TouchableOpacity>
          ))}
        </View>

        {loading || !data ? <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} /> : (
          <>
            {/* Daily bar chart (SVG-free — uses View widths) */}
            <Text style={styles.sectionLabel}>Daily turnover · last {data.days} days</Text>
            <View style={styles.chartCard}>
              {data.daily.length === 0 ? <Text style={{ color: colors.textMuted }}>No sales in this range.</Text> :
                data.daily.slice(-30).map(d => (
                  <View key={d.date} style={styles.barRow}>
                    <Text style={styles.barLabel}>{d.date.slice(5)}</Text>
                    <View style={{ flex: 1, height: 10, backgroundColor: colors.surfaceMuted, borderRadius: 4, overflow: "hidden" }}>
                      <View style={{ width: `${Math.max(2, (d.turnover / maxDay) * 100)}%`, height: "100%", backgroundColor: colors.primary }} />
                    </View>
                    <Text style={styles.barAmt}>{formatINR(d.turnover)}</Text>
                  </View>
                ))
              }
            </View>

            <RankList title="Top sold (qty)" rows={data.top_sold} field="qty" fmt={(v) => `${v} pcs`} />
            <RankList title="Top revenue" rows={data.top_revenue} field="revenue" fmt={formatINR} />
            <RankList title="Highest GST" rows={data.top_gst} field="gst" fmt={formatINR} />
            <RankList title="Least sold" rows={data.least_sold} field="qty" fmt={(v) => `${v} pcs`} />
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Kpi({ title, bills, turnover, gst, profit }: { title: string; bills: number; turnover: number; gst: number; profit: number }) {
  return (
    <View style={{ flex: 1, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12 }}>
      <Text style={{ fontSize: 11, color: colors.textMuted, fontWeight: "800", textTransform: "uppercase", letterSpacing: 1 }}>{title}</Text>
      <Text style={{ fontSize: 20, fontWeight: "900", color: colors.textMain, marginTop: 6 }}>{formatINR(turnover)}</Text>
      <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 4 }}>{bills} bill{bills === 1 ? "" : "s"} · GST {formatINR(gst)}</Text>
      <Text style={{ fontSize: 11, color: profit >= 0 ? "#166534" : "#B91C1C", marginTop: 2 }}>Profit {formatINR(profit)}</Text>
    </View>
  );
}

function RankList({ title, rows, field, fmt }: { title: string; rows: any[]; field: string; fmt: (v: number) => string }) {
  return (
    <View style={{ marginTop: 16 }}>
      <Text style={styles.sectionLabel}>{title}</Text>
      {rows.length === 0 ? <Text style={{ color: colors.textMuted }}>No data.</Text> : rows.slice(0, 10).map((r, i) => (
        <View key={r.product_id + i} style={styles.rankRow}>
          <Text style={styles.rankIdx}>{i + 1}.</Text>
          <Text style={styles.rankName} numberOfLines={1}>{r.name}</Text>
          <Text style={styles.rankAmt}>{fmt(r[field] || 0)}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { padding: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  sectionLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 6 },
  chartCard: { padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12 },
  barRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  barLabel: { width: 44, fontSize: 10, color: colors.textMuted },
  barAmt: { width: 74, fontSize: 10, color: colors.textMain, textAlign: "right", fontWeight: "700" },
  rankRow: { flexDirection: "row", alignItems: "center", padding: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, marginBottom: 4 },
  rankIdx: { width: 22, fontSize: 11, color: colors.textMuted, fontWeight: "800" },
  rankName: { flex: 1, fontSize: 13, color: colors.textMain, fontWeight: "700" },
  rankAmt: { fontSize: 13, color: colors.primary, fontWeight: "800" },
});
