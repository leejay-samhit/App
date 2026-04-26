import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl, TouchableOpacity, Dimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import Svg, { Rect, Line, Text as SvgText, Path } from "react-native-svg";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { useAuth } from "../../src/auth";

type Analytics = {
  kpis: {
    new_users_today: number;
    new_users_month: number;
    paid_users_today: number;
    total_revenue: number;
    system_wallet: number;
    total_payouts: number;
    success_txns: number;
    failed_txns: number;
    pending_txns: number;
    refunded_txns: number;
    orders_count: number;
    orders_revenue: number;
  };
  daily_users: { date: string; value: number }[];
  daily_revenue: { date: string; value: number }[];
  daily_txns: { date: string; value: number }[];
};

export default function AdminHome() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState(7);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return; // wait for auth hydration
    setError(null);
    try {
      const { data } = await api.get<Analytics>(`/admin/analytics?days=${period}`);
      setData(data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to load analytics");
    }
    finally { setLoading(false); setRefreshing(false); }
  }, [period, user]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading && !data) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  if (error && !data) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <Feather name="alert-triangle" size={32} color={colors.warning} />
          <Text style={{ marginTop: 12, color: colors.textMain, fontWeight: "700" }}>Couldn't load dashboard</Text>
          <Text style={{ marginTop: 4, color: colors.textMuted, fontSize: 13, textAlign: "center", paddingHorizontal: 32 }}>{error}</Text>
          <TouchableOpacity onPress={() => { setLoading(true); load(); }} style={{ marginTop: 20, backgroundColor: colors.primary, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 99 }} testID="home-retry">
            <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Retry</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  if (!data) return null;

  const k = data.kpis;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <View>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Overview</Text>
            <Text style={styles.subtitle}>Hi {user?.name}, here's how the network is performing.</Text>
          </View>
        </View>

        <View style={styles.heroCard}>
          <Text style={styles.heroLabel}>TOTAL REVENUE</Text>
          <Text style={styles.heroValue}>{formatINR(k.total_revenue)}</Text>
          <View style={styles.heroRow}>
            <View>
              <Text style={styles.heroSubLabel}>System wallet</Text>
              <Text style={styles.heroSubValue}>{formatINR(k.system_wallet)}</Text>
            </View>
            <View>
              <Text style={styles.heroSubLabel}>Paid out</Text>
              <Text style={styles.heroSubValue}>{formatINR(k.total_payouts)}</Text>
            </View>
            <View>
              <Text style={styles.heroSubLabel}>Margin</Text>
              <Text style={[styles.heroSubValue, { color: colors.accentFg }]}>{formatINR(k.total_revenue - k.total_payouts)}</Text>
            </View>
          </View>
        </View>

        <View style={styles.kpiGrid}>
          <KPI icon="user-plus" label="New today" value={String(k.new_users_today)} testID="kpi-new-today" />
          <KPI icon="calendar" label="New this month" value={String(k.new_users_month)} testID="kpi-new-month" />
          <KPI icon="check-circle" label="Paid today" value={String(k.paid_users_today)} testID="kpi-paid-today" />
          <KPI icon="shopping-bag" label="Orders" value={String(k.orders_count)} testID="kpi-orders" />
        </View>

        <Text style={styles.sectionLabel}>TRANSACTION STATUS</Text>
        <View style={styles.txnRow}>
          <TxnPill label="Success" value={k.success_txns} color={colors.success} />
          <TxnPill label="Pending" value={k.pending_txns} color={colors.warning} />
          <TxnPill label="Failed" value={k.failed_txns} color="#B3261E" />
          <TxnPill label="Refunded" value={k.refunded_txns} color={colors.accent} />
        </View>

        <View style={styles.periodTabs}>
          {[7, 14, 30].map((d) => (
            <TouchableOpacity key={d} onPress={() => setPeriod(d)} style={[styles.periodTab, period === d && styles.periodTabActive]} testID={`period-${d}`}>
              <Text style={[styles.periodTabText, period === d && styles.periodTabTextActive]}>{d}D</Text>
            </TouchableOpacity>
          ))}
        </View>

        <BarChart title="Daily revenue" data={data.daily_revenue} valueFormatter={(v) => formatINR(v)} color={colors.primary} />
        <BarChart title="Daily new users" data={data.daily_users} color={colors.accent} />
        <BarChart title="Daily transactions" data={data.daily_txns} color={colors.brand500} />

        <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
        <View style={styles.quickGrid}>
          <QuickAction icon="user-check" label="KYC queue" onPress={() => router.push("/admin/kyc")} testID="qa-kyc" />
          <QuickAction icon="package" label="Orders" onPress={() => router.push("/admin/orders")} testID="qa-orders" />
          <QuickAction icon="file-text" label="Audit log" onPress={() => router.push("/admin/audit")} testID="qa-audit" />
          <QuickAction icon="sliders" label="Settings" onPress={() => router.push("/admin/settings")} testID="qa-settings" />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function KPI({ icon, label, value, testID }: { icon: any; label: string; value: string; testID?: string }) {
  return (
    <View style={styles.kpiCard} testID={testID}>
      <View style={styles.kpiIcon}><Feather name={icon} size={14} color={colors.primary} /></View>
      <Text style={styles.kpiValue}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
}

function TxnPill({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={styles.txnPill}>
      <View style={[styles.txnDot, { backgroundColor: color }]} />
      <Text style={styles.txnPillValue}>{value}</Text>
      <Text style={styles.txnPillLabel}>{label}</Text>
    </View>
  );
}

function QuickAction({ icon, label, onPress, testID }: { icon: any; label: string; onPress: () => void; testID?: string }) {
  return (
    <TouchableOpacity style={styles.quickCard} onPress={onPress} testID={testID}>
      <View style={styles.quickIcon}><Feather name={icon} size={16} color={colors.primary} /></View>
      <Text style={styles.quickLabel}>{label}</Text>
    </TouchableOpacity>
  );
}

function BarChart({ title, data, color, valueFormatter }: { title: string; data: { date: string; value: number }[]; color: string; valueFormatter?: (v: number) => string }) {
  const w = Dimensions.get("window").width - spacing.screen * 2 - 32;
  const h = 140;
  const padTop = 18;
  const padBottom = 22;
  const max = Math.max(1, ...data.map((d) => d.value));
  const barW = data.length ? (w - 8) / data.length - 4 : 0;

  return (
    <View style={styles.chartCard}>
      <Text style={styles.chartTitle}>{title}</Text>
      <Text style={styles.chartMax}>peak {valueFormatter ? valueFormatter(max) : max}</Text>
      <Svg width={w} height={h + padTop + padBottom}>
        {/* baseline */}
        <Line x1={0} y1={h + padTop} x2={w} y2={h + padTop} stroke={colors.border} strokeWidth={1} />
        {data.map((d, i) => {
          const bh = (d.value / max) * h;
          const x = i * (barW + 4) + 4;
          const y = h + padTop - bh;
          return (
            <Rect key={i} x={x} y={y} width={barW} height={bh} fill={color} rx={4} />
          );
        })}
        {/* end labels */}
        {data.length > 0 && (
          <>
            <SvgText x={4} y={h + padTop + 16} fontSize={10} fill={colors.textMuted}>
              {data[0].date.slice(5)}
            </SvgText>
            <SvgText x={w - 28} y={h + padTop + 16} fontSize={10} fill={colors.textMuted}>
              {data[data.length - 1].date.slice(5)}
            </SvgText>
          </>
        )}
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { marginBottom: 20 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginTop: 6 },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6 },
  heroCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 20, marginBottom: 16 },
  heroLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  heroValue: { color: colors.primaryFg, fontSize: 36, fontWeight: "800", letterSpacing: -1, marginTop: 6 },
  heroRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 16 },
  heroSubLabel: { color: "rgba(255,255,255,0.6)", fontSize: 11 },
  heroSubValue: { color: colors.primaryFg, fontSize: 15, fontWeight: "700", marginTop: 4 },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 24 },
  kpiCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 12 },
  kpiIcon: { width: 28, height: 28, borderRadius: 8, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  kpiValue: { fontSize: 22, fontWeight: "800", color: colors.textMain, marginTop: 8, letterSpacing: -0.5 },
  kpiLabel: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12, marginTop: 8 },
  txnRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 24 },
  txnPill: { flexBasis: "48%", flexGrow: 1, flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 12, gap: 8 },
  txnDot: { width: 8, height: 8, borderRadius: 4 },
  txnPillValue: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  txnPillLabel: { fontSize: 12, color: colors.textMuted, marginLeft: "auto" },
  periodTabs: { flexDirection: "row", backgroundColor: colors.surfaceMuted, borderRadius: 99, padding: 4, gap: 4, marginBottom: 16, alignSelf: "flex-start" },
  periodTab: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 99 },
  periodTabActive: { backgroundColor: colors.primary },
  periodTabText: { fontSize: 11, fontWeight: "700", color: colors.textMuted, letterSpacing: 1 },
  periodTabTextActive: { color: colors.primaryFg },
  chartCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 12 },
  chartTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  chartMax: { fontSize: 11, color: colors.textMuted, marginTop: 2, marginBottom: 8 },
  quickGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  quickCard: { flexBasis: "48%", flexGrow: 1, flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14 },
  quickIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  quickLabel: { fontSize: 13, fontWeight: "700", color: colors.textMain, flex: 1 },
});
