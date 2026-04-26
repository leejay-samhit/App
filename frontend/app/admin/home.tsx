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

type NewUser = {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  created_at: string;
  approval_status?: string;
  sponsor_email?: string | null;
  sponsor_name?: string | null;
  registration_paid?: boolean;
};

export default function AdminHome() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState(7);
  const [error, setError] = useState<string | null>(null);
  const [newToday, setNewToday] = useState<NewUser[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!user) return; // wait for auth hydration
    setError(null);
    try {
      const [aRes, todayRes, pendingRes] = await Promise.all([
        api.get<Analytics>(`/admin/analytics?days=${period}`),
        api.get<NewUser[]>("/admin/approvals/today"),
        api.get<NewUser[]>("/admin/approvals?status=pending"),
      ]);
      setData(aRes.data);
      setNewToday(todayRes.data || []);
      setPendingCount((pendingRes.data || []).length);
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
          <KPI icon="user-plus" label="New today" value={String(k.new_users_today)} testID="kpi-new-today" onPress={() => router.push("/admin/approvals" as any)} />
          <KPI icon="calendar" label="New this month" value={String(k.new_users_month)} testID="kpi-new-month" />
          <KPI icon="check-circle" label="Paid today" value={String(k.paid_users_today)} testID="kpi-paid-today" />
          <KPI icon="shopping-bag" label="Orders" value={String(k.orders_count)} testID="kpi-orders" />
        </View>

        {/* Approval queue summary */}
        <TouchableOpacity onPress={() => router.push("/admin/approvals" as any)} style={styles.approvalsBanner} testID="approvals-banner">
          <View style={[styles.approvalsIcon, { backgroundColor: pendingCount > 0 ? "#FFF4E5" : "#E6F4EE" }]}>
            <Feather name={pendingCount > 0 ? "alert-circle" : "check-circle"} size={18} color={pendingCount > 0 ? colors.warning : colors.success} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.approvalsTitle}>{pendingCount > 0 ? `${pendingCount} pending approval${pendingCount === 1 ? "" : "s"}` : "Approvals all caught up"}</Text>
            <Text style={styles.approvalsSub}>Review users before they enter the payout tree.</Text>
          </View>
          <Feather name="chevron-right" size={18} color={colors.textMuted} />
        </TouchableOpacity>

        {/* New today carousel */}
        {newToday.length > 0 && (
          <>
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionLabel}>NEW TODAY</Text>
              <TouchableOpacity onPress={() => router.push("/admin/approvals" as any)} testID="new-today-all">
                <Text style={styles.linkText}>See all →</Text>
              </TouchableOpacity>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingRight: spacing.screen, gap: 10 }}>
              {newToday.map((u) => (
                <TouchableOpacity
                  key={u.id}
                  onPress={() => router.push(`/admin/approvals?focus=${u.id}` as any)}
                  style={styles.userCard}
                  testID={`new-today-${u.id}`}
                >
                  <View style={styles.userTop}>
                    <View style={styles.userAvatar}><Text style={styles.userAvatarText}>{(u.name || "?").charAt(0).toUpperCase()}</Text></View>
                    <View style={[styles.statusPill, {
                      backgroundColor: u.approval_status === "approved" ? colors.success
                        : u.approval_status === "rejected" ? "#B3261E"
                        : colors.warning,
                    }]}>
                      <Text style={styles.statusPillText}>{(u.approval_status || "PENDING").toUpperCase()}</Text>
                    </View>
                  </View>
                  <Text style={styles.userName} numberOfLines={1}>{u.name}</Text>
                  <Text style={styles.userEmail} numberOfLines={1}>{u.email}</Text>
                  {u.sponsor_email ? (
                    <Text style={styles.userMeta} numberOfLines={1}>via {u.sponsor_name || u.sponsor_email}</Text>
                  ) : (
                    <Text style={styles.userMeta}>No sponsor</Text>
                  )}
                  <View style={styles.userTimeRow}>
                    <Feather name="clock" size={10} color={colors.textMuted} />
                    <Text style={styles.userTime}>{new Date(u.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</Text>
                    {!u.registration_paid && (
                      <View style={styles.unpaidBadge}><Text style={styles.unpaidBadgeText}>UNPAID</Text></View>
                    )}
                  </View>
                  {u.approval_status === "pending" && (
                    <View style={styles.userActions}>
                      <TouchableOpacity
                        onPress={async (e) => {
                          e.stopPropagation();
                          setBusyId(u.id);
                          try {
                            await api.post(`/admin/approvals/${u.id}/approve`);
                            await load();
                          } catch {}
                          finally { setBusyId(null); }
                        }}
                        disabled={busyId === u.id}
                        style={[styles.userMiniBtn, { backgroundColor: colors.primary }]}
                        testID={`new-today-${u.id}-approve`}
                      >
                        {busyId === u.id ? <ActivityIndicator size="small" color={colors.primaryFg} /> : (
                          <>
                            <Feather name="check" size={12} color={colors.primaryFg} />
                            <Text style={[styles.userMiniBtnText, { color: colors.primaryFg }]}>Approve</Text>
                          </>
                        )}
                      </TouchableOpacity>
                      <TouchableOpacity
                        onPress={(e) => {
                          e.stopPropagation();
                          router.push(`/admin/approvals?focus=${u.id}` as any);
                        }}
                        style={[styles.userMiniBtn, { backgroundColor: colors.surfaceMuted }]}
                        testID={`new-today-${u.id}-review`}
                      >
                        <Feather name="eye" size={12} color={colors.textMain} />
                        <Text style={styles.userMiniBtnText}>Review</Text>
                      </TouchableOpacity>
                    </View>
                  )}
                </TouchableOpacity>
              ))}
            </ScrollView>
          </>
        )}

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

function KPI({ icon, label, value, testID, onPress }: { icon: any; label: string; value: string; testID?: string; onPress?: () => void }) {
  const Wrap: any = onPress ? TouchableOpacity : View;
  return (
    <Wrap activeOpacity={0.75} onPress={onPress} style={styles.kpiCard} testID={testID}>
      <View style={styles.kpiIcon}><Feather name={icon} size={14} color={colors.primary} /></View>
      <Text style={styles.kpiValue}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </Wrap>
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
  approvalsBanner: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 16 },
  approvalsIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  approvalsTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  approvalsSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  sectionHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  linkText: { fontSize: 12, color: colors.primary, fontWeight: "700" },
  userCard: { width: 220, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 12 },
  userTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  userAvatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  userAvatarText: { color: "#fff", fontSize: 13, fontWeight: "800" },
  statusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 99 },
  statusPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  userName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  userEmail: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  userMeta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  userTimeRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6 },
  userTime: { fontSize: 10, color: colors.textMuted },
  unpaidBadge: { backgroundColor: "#FCE9E5", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, marginLeft: "auto" },
  unpaidBadgeText: { color: "#B3261E", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  userActions: { flexDirection: "row", gap: 6, marginTop: 10 },
  userMiniBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 8, borderRadius: 8 },
  userMiniBtnText: { fontSize: 11, fontWeight: "700", color: colors.textMain },
});
