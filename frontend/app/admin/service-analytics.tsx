// Admin: Service Analytics dashboard.
// Pulls /api/admin/service-analytics and renders compact KPIs for provider
// availability, top categories, phone-reveal revenue (30d / lifetime) and
// service application funnel.
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, TextInput, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Analytics = {
  availability: { available: number; busy: number; offline: number; unset: number };
  categories: Array<{ id: string; name: string; icon?: string; color?: string; provider_count: number; active: boolean }>;
  reveal_stats: { count_30d: number; amount_30d: number; fee_30d: number; gst_30d: number; count_lifetime: number };
  applications: { pending: number; approved: number; rejected: number };
  generated_at: string;
};

export default function ServiceAnalytics() {
  const router = useRouter();
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // June 2026 — pincode live-data filter (admin can scope KPIs to one area).
  const [pincode, setPincode] = useState("");
  const [appliedPincode, setAppliedPincode] = useState<string>("");
  // Sep 2026 — global unlock fee (phone reveal + provider chat).
  const [feeDraft, setFeeDraft] = useState("");
  const [feeSaved, setFeeSaved] = useState<{ fee: number; gst_pct: number; total: number } | null>(null);
  const [savingFee, setSavingFee] = useState(false);

  const loadFee = useCallback(async () => {
    try {
      const { data } = await api.get<any>("/admin/settings");
      const fee = Number(data?.phone_reveal_fee ?? 1);
      const gst = Number(data?.phone_reveal_gst_pct ?? 18);
      setFeeSaved({ fee, gst_pct: gst, total: Math.round((fee + (fee * gst) / 100) * 100) / 100 });
      setFeeDraft(String(fee));
    } catch { /* non-fatal */ }
  }, []);

  const saveFee = useCallback(async () => {
    const value = Number(feeDraft);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      Alert.alert("Enter 0 to 100", "The unlock fee must be between ₹0 and ₹100.");
      return;
    }
    setSavingFee(true);
    try {
      await api.put("/admin/settings", { phone_reveal_fee: value });
      await loadFee();
      Alert.alert(
        "Saved",
        value === 0
          ? "Phone numbers and provider chat are now free for customers."
          : `Customers will pay ₹${value} + GST to unlock a provider's number and chat.`,
      );
    } catch (e) {
      Alert.alert("Couldn't save", formatApiError(e));
    } finally {
      setSavingFee(false);
    }
  }, [feeDraft, loadFee]);

  const load = useCallback(async () => {
    try {
      setErr(null);
      const q = appliedPincode ? `?pincode=${encodeURIComponent(appliedPincode)}` : "";
      const { data } = await api.get<Analytics>(`/admin/service-analytics${q}`);
      setData(data);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [appliedPincode]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadFee(); }, [loadFee]);

  if (loading) {
    return <SafeAreaView style={s.safe}><View style={s.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }
  if (err || !data) {
    return (
      <SafeAreaView style={s.safe}>
        <View style={s.center}>
          <Feather name="alert-circle" size={24} color={"#B3261E"} />
          <Text style={s.errTxt}>{err || "No data"}</Text>
          <TouchableOpacity onPress={() => { setLoading(true); load(); }} style={s.btn}>
            <Text style={s.btnTxt}>Retry</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const total = data.availability.available + data.availability.busy + data.availability.offline + data.availability.unset;
  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} style={s.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={s.title}>Service Analytics</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        {/* June 2026 — pincode live filter */}
        <View style={s.filterBar}>
          <View style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Feather name="map-pin" size={14} color={colors.textMuted} />
            <TextInput
              style={s.pinInput}
              value={pincode}
              onChangeText={setPincode}
              placeholder="Filter by pincode (e.g. 500001)"
              placeholderTextColor={colors.textMuted}
              keyboardType="numeric"
              maxLength={6}
              returnKeyType="search"
              onSubmitEditing={() => { setLoading(true); setAppliedPincode(pincode.trim()); }}
              testID="analytics-pincode"
            />
          </View>
          {appliedPincode ? (
            <TouchableOpacity
              onPress={() => { setPincode(""); setAppliedPincode(""); setLoading(true); }}
              style={s.clearBtn}
            >
              <Feather name="x" size={13} color="#fff" />
              <Text style={s.clearBtnText}>{"  "}Clear</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              onPress={() => { setLoading(true); setAppliedPincode(pincode.trim()); }}
              style={s.applyBtn}
              disabled={!pincode.trim()}
            >
              <Feather name="filter" size={13} color="#fff" />
              <Text style={s.clearBtnText}>{"  "}Apply</Text>
            </TouchableOpacity>
          )}
        </View>
        {appliedPincode ? (
          <Text style={s.scopeLine}>Showing live data scoped to pincode {appliedPincode}</Text>
        ) : null}

        {/* Sep 2026 — Unlock fee control (owner ask). One global amount for
            revealing a provider's phone AND starting a chat with them. Set
            ₹0 to make both free; GST is added on top at checkout time. */}
        <Text style={s.section}>UNLOCK FEE (PHONE + CHAT)</Text>
        <View style={s.feeCard}>
          <View style={{ flex: 1 }}>
            <Text style={s.feeHint}>
              Customers pay this once per provider to see the number and to chat.
              {feeSaved?.gst_pct ? ` GST ${feeSaved.gst_pct}% is added on top` : ""}
              {feeSaved ? ` → customer pays ${formatINR(feeSaved.total)}.` : "."}
            </Text>
            <Text style={s.feeHintMuted}>Set 0 to make chat and phone free for everyone. Max ₹100.</Text>
          </View>
          <View style={s.feeInputRow}>
            <Text style={s.feeCurrency}>₹</Text>
            <TextInput
              style={s.feeInput}
              value={feeDraft}
              onChangeText={(v) => setFeeDraft(v.replace(/[^0-9.]/g, "").slice(0, 6))}
              keyboardType="decimal-pad"
              placeholder="0"
              placeholderTextColor={colors.textMuted}
              testID="analytics-fee-input"
            />
            <TouchableOpacity
              onPress={saveFee}
              disabled={savingFee || feeDraft.trim() === ""}
              style={[s.feeSaveBtn, (savingFee || feeDraft.trim() === "") && { opacity: 0.5 }]}
              testID="analytics-fee-save"
            >
              {savingFee ? <ActivityIndicator color="#fff" size="small" /> : <Feather name="check" size={15} color="#fff" />}
              <Text style={s.clearBtnText}>{"  "}Save</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Provider availability KPIs */}
        <Text style={s.section}>PROVIDER AVAILABILITY</Text>
        <View style={s.kpiRow}>
          {([
            { k: "available", l: "Available", c: "#16A34A" },
            { k: "busy", l: "Busy", c: "#F59E0B" },
            { k: "offline", l: "Offline", c: "#6B7280" },
            { k: "unset", l: "Unset", c: "#9CA3AF" },
          ] as const).map((b) => {
            const v = (data.availability as any)[b.k] || 0;
            const pct = total > 0 ? Math.round((v / total) * 100) : 0;
            return (
              <View key={b.k} style={[s.kpiCard, { borderTopColor: b.c }]}>
                <Text style={s.kpiNum}>{v}</Text>
                <Text style={s.kpiLabel}>{b.l}</Text>
                <Text style={s.kpiSub}>{pct}%</Text>
              </View>
            );
          })}
        </View>

        {/* Phone-reveal revenue */}
        <Text style={s.section}>PHONE-REVEAL REVENUE</Text>
        <View style={s.bigCard}>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <View>
              <Text style={s.bigLabel}>Last 30 days</Text>
              <Text style={s.bigNum}>{formatINR(data.reveal_stats.amount_30d)}</Text>
              <Text style={s.bigSub}>{data.reveal_stats.count_30d} reveals</Text>
            </View>
            <View>
              <Text style={[s.bigLabel, { textAlign: "right" }]}>Lifetime</Text>
              <Text style={[s.bigNum, { textAlign: "right", color: colors.textMuted, fontSize: 18 }]}>{data.reveal_stats.count_lifetime}</Text>
              <Text style={[s.bigSub, { textAlign: "right" }]}>reveals</Text>
            </View>
          </View>
          <View style={s.div} />
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={s.feeRow}>Base fees collected</Text>
            <Text style={s.feeRowVal}>{formatINR(data.reveal_stats.fee_30d)}</Text>
          </View>
          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
            <Text style={s.feeRow}>GST collected</Text>
            <Text style={s.feeRowVal}>{formatINR(data.reveal_stats.gst_30d)}</Text>
          </View>
        </View>

        {/* Application funnel */}
        <Text style={s.section}>SERVICE APPLICATIONS</Text>
        <View style={s.kpiRow}>
          {([
            { k: "pending", l: "Pending", c: "#F59E0B" },
            { k: "approved", l: "Approved", c: "#16A34A" },
            { k: "rejected", l: "Rejected", c: "#B3261E" },
          ] as const).map((b) => (
            <View key={b.k} style={[s.kpiCard, { borderTopColor: b.c }]}>
              <Text style={s.kpiNum}>{(data.applications as any)[b.k] || 0}</Text>
              <Text style={s.kpiLabel}>{b.l}</Text>
            </View>
          ))}
        </View>

        {/* Top categories */}
        <Text style={s.section}>TOP CATEGORIES BY PROVIDERS</Text>
        {data.categories.slice(0, 12).map((c) => (
          <View key={c.id} style={s.catRow}>
            <View style={[s.catIcon, { backgroundColor: (c.color || colors.primary) + "22" }]}>
              <Feather name={(c.icon || "briefcase") as any} size={16} color={c.color || colors.primary} />
            </View>
            <Text style={s.catName} numberOfLines={1}>{c.name}{!c.active ? " · disabled" : ""}</Text>
            <Text style={s.catCount}>{c.provider_count}</Text>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10, padding: 20 },
  errTxt: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  btn: { paddingHorizontal: 18, paddingVertical: 10, backgroundColor: colors.primary, borderRadius: 999, marginTop: 10 },
  btnTxt: { color: "#fff", fontWeight: "800" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  section: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "900", marginTop: 22, marginBottom: 8 },
  kpiRow: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  kpiCard: {
    flexGrow: 1, minWidth: 80,
    backgroundColor: colors.surface,
    borderRadius: 14, padding: 12,
    borderTopWidth: 4,
    borderRightWidth: 1, borderBottomWidth: 1, borderLeftWidth: 1,
    borderColor: colors.border,
    borderTopColor: colors.primary,
  },
  kpiNum: { fontSize: 22, fontWeight: "900", color: colors.textMain },
  kpiLabel: { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginTop: 2 },
  kpiSub: { fontSize: 10, fontWeight: "700", color: colors.textMuted, marginTop: 2 },
  bigCard: { padding: 16, borderRadius: radii.card, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  bigLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  bigNum: { fontSize: 24, color: colors.primary, fontWeight: "900", marginTop: 4 },
  bigSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  div: { height: 1, backgroundColor: colors.border, marginVertical: 12 },
  feeRow: { fontSize: 12, color: colors.textMuted },
  feeRowVal: { fontSize: 13, color: colors.textMain, fontWeight: "700" },
  catRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  catIcon: { width: 32, height: 32, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  catName: { flex: 1, fontSize: 13, color: colors.textMain, fontWeight: "700" },
  catCount: { fontSize: 13, fontWeight: "900", color: colors.primary },
  // June 2026 — pincode filter bar
  // Sep 2026 — unlock fee editor.
  feeCard: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 16, gap: 10,
  },
  feeHint: { fontSize: 12.5, color: colors.textMain, lineHeight: 18 },
  feeHintMuted: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  feeInputRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  feeCurrency: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  feeInput: {
    flex: 1, minHeight: 46, borderRadius: radii.input, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surfaceMuted,
    paddingHorizontal: 12, fontSize: 16, fontWeight: "800", color: colors.textMain,
  },
  feeSaveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    paddingHorizontal: 16, minHeight: 46, borderRadius: radii.button,
    backgroundColor: colors.primary,
  },
  filterBar: { flexDirection: "row", gap: 8, alignItems: "center" },
  pinInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 11,
    borderWidth: 1, borderColor: colors.border,
    fontSize: 13, color: colors.textMain,
  },
  applyBtn: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.primary,
    paddingHorizontal: 14, paddingVertical: 11,
    borderRadius: radii.input,
  },
  clearBtn: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: "#B45309",
    paddingHorizontal: 14, paddingVertical: 11,
    borderRadius: radii.input,
  },
  clearBtnText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  scopeLine: { fontSize: 10, color: colors.primary, fontWeight: "700", marginTop: 6 },
});
