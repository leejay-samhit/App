import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator,
  KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Settings = {
  registration_fee: number;
  directs_required: number;
  payout_l1: number;
  payout_l2: number;
  payout_l3: number;
  payout_l4: number;
  payout_l5: number;
  payout_l6: number;
  payout_l7: number;
  payout_l8: number;
  payout_l9: number;
  payout_l10: number;
};

const LEVEL_KEYS = ["payout_l1","payout_l2","payout_l3","payout_l4","payout_l5","payout_l6","payout_l7","payout_l8","payout_l9","payout_l10"] as const;

const TOP_FIELDS = [
  { key: "registration_fee" as const, label: "Registration fee", help: "One-time fee paid by every new user.", suffix: "₹", integer: false },
  { key: "directs_required" as const, label: "Directs per cycle", help: "How many direct paid referrals trigger a Level 1 payout.", integer: true },
];

export default function AdminSettings() {
  const [data, setData] = useState<Settings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Settings>("/admin/settings");
      setData(data);
      const initial: Record<string, string> = {
        registration_fee: String(data.registration_fee ?? 0),
        directs_required: String(data.directs_required ?? 4),
      };
      LEVEL_KEYS.forEach((k) => { initial[k] = String((data as any)[k] ?? 0); });
      setForm(initial);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onSave = async () => {
    setMsg("");
    setSaving(true);
    try {
      const payload: any = {};
      const all = [
        ...TOP_FIELDS.map((f) => ({ key: f.key as string, integer: !!f.integer })),
        ...LEVEL_KEYS.map((k) => ({ key: k as string, integer: false })),
      ];
      for (const f of all) {
        const raw = form[f.key];
        if (raw === undefined || raw === "") continue;
        const v = f.integer ? parseInt(raw, 10) : parseFloat(raw);
        if (Number.isNaN(v)) continue;
        payload[f.key] = v;
      }
      const { data } = await api.put<Settings>("/admin/settings", payload);
      setData(data);
      setMsg("Saved successfully");
      setTimeout(() => setMsg(""), 2500);
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  if (loading || !data) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  // Per-cycle (1 sponsor + N directs paying ₹fee each):
  // Revenue: directs_required × fee
  // Costs: L1 cycle bonus (1×) + L2..L10 = sum of payouts per signup × N (only L2..L10 paid per signup)
  const N = data.directs_required;
  const levelVals = LEVEL_KEYS.map((k) => Number((data as any)[k]) || 0);
  const cycleCost = levelVals[0] + N * levelVals.slice(1).reduce((a, b) => a + b, 0);
  const cycleRevenue = N * data.registration_fee;
  const margin = cycleRevenue - cycleCost;

  // 10-level tree projection from one sponsor's perspective: each level has N^level nodes
  const counts = Array.from({ length: 10 }, (_, i) => Math.pow(N, i + 1));
  // Sponsor's earnings per level (sponsor's perspective):
  // L1 = single cycle bonus when N directs all pay
  // L2..L10 = perSignup × count at that level
  const earnPerLevel = levelVals.map((v, idx) => idx === 0 ? v : v * counts[idx]);
  const earnTotal = earnPerLevel.reduce((a, b) => a + b, 0);
  const treeTotalNodes = counts.reduce((a, b) => a + b, 0);
  const treeRevenue = treeTotalNodes * data.registration_fee;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <Text style={styles.overline}>ADMIN</Text>
          <Text style={styles.h1}>Payout settings</Text>
          <Text style={styles.subtitle}>Tune the registration fee and 10-level commission structure. Set any level to 0 to disable it.</Text>

          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>PER CYCLE PROJECTION ({N} signups)</Text>
            <View style={styles.summaryRow}>
              <View>
                <Text style={styles.summaryStatLabel}>Revenue</Text>
                <Text style={styles.summaryStatValue}>{formatINR(cycleRevenue)}</Text>
              </View>
              <View>
                <Text style={styles.summaryStatLabel}>Payouts</Text>
                <Text style={[styles.summaryStatValue, { color: colors.accent }]}>{formatINR(cycleCost)}</Text>
              </View>
              <View>
                <Text style={styles.summaryStatLabel}>Margin</Text>
                <Text style={[styles.summaryStatValue, { color: margin >= 0 ? colors.success : "#B3261E" }]}>
                  {margin >= 0 ? "+" : ""}{formatINR(margin)}
                </Text>
              </View>
            </View>
          </View>

          <Text style={styles.sectionLabel}>BASE</Text>
          {TOP_FIELDS.map((f) => (
            <View key={f.key} style={styles.field}>
              <Text style={styles.fieldLabel}>{f.label}</Text>
              <View style={styles.inputWrap}>
                {(f as any).suffix && <Text style={styles.suffix}>{(f as any).suffix}</Text>}
                <TextInput
                  testID={`settings-${f.key}`}
                  value={form[f.key] || ""}
                  onChangeText={(t) => setForm((x) => ({ ...x, [f.key]: t }))}
                  keyboardType="numeric"
                  style={[styles.input, !!(f as any).suffix && { paddingLeft: 32 }]}
                  placeholder="0"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
              <Text style={styles.fieldHelp}>{f.help}</Text>
            </View>
          ))}

          <Text style={[styles.sectionLabel, { marginTop: 12 }]}>LEVEL PAYOUTS (10 LEVELS)</Text>
          <Text style={styles.sectionHelp}>Level 1 is a cycle bonus paid once every {N} directs. Levels 2–10 are paid per qualifying signup down the tree.</Text>

          {LEVEL_KEYS.map((k, idx) => {
            const lvl = idx + 1;
            const help = lvl === 1
              ? `Cycle bonus paid every ${N} directs.`
              : `Per signup at level ${lvl} (${lvl === 2 ? "grand" : lvl === 3 ? "great-grand" : `${lvl - 1} levels deep`}).`;
            return (
              <View key={k} style={styles.levelRow}>
                <View style={[styles.levelBadge, lvl === 1 && { backgroundColor: colors.success }, lvl === 2 && { backgroundColor: colors.brand500 }, lvl === 3 && { backgroundColor: colors.accent }, lvl >= 4 && { backgroundColor: colors.primary, opacity: Math.max(0.4, 1 - (lvl - 4) * 0.07) }]}>
                  <Text style={styles.levelBadgeText}>L{lvl}</Text>
                </View>
                <View style={styles.levelInputWrap}>
                  <Text style={styles.levelSuffix}>₹</Text>
                  <TextInput
                    testID={`settings-${k}`}
                    value={form[k] || ""}
                    onChangeText={(t) => setForm((x) => ({ ...x, [k]: t }))}
                    keyboardType="numeric"
                    style={styles.levelInput}
                    placeholder="0"
                    placeholderTextColor={colors.textMuted}
                  />
                </View>
                <Text style={styles.levelHelp} numberOfLines={2}>{help}</Text>
              </View>
            );
          })}

          <Text style={[styles.sectionLabel, { marginTop: 16 }]}>1+{N} TREE PROJECTION (10 LEVELS)</Text>
          <Text style={styles.sectionHelp}>One sponsor's potential earnings if their network fills 10 levels deep with {N} directs each.</Text>

          <View style={styles.treeWrap} testID="tree-projection">
            <View style={styles.treeRoot}>
              <View style={styles.treeAvatar}><Feather name="user" size={18} color={colors.primaryFg} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.treeRootName}>YOU</Text>
                <Text style={styles.treeRootSub}>Sponsor — earns from up to 10 levels below</Text>
              </View>
              <Text style={styles.treeRootEarn}>{formatINR(earnTotal)}</Text>
            </View>

            {Array.from({ length: 10 }).map((_, idx) => {
              const lvl = idx + 1;
              const c = counts[idx];
              const v = levelVals[idx];
              const earn = earnPerLevel[idx];
              const sub = lvl === 1
                ? `One ₹${v} cycle bonus when all ${N} directs pay`
                : v > 0
                  ? `₹${v} × ${c.toLocaleString("en-IN")} signups`
                  : `(disabled — ₹0)`;
              return (
                <View key={lvl} style={styles.treeLevelWrap} testID={`tree-l${lvl}`}>
                  <View style={styles.treeConnector} />
                  <View style={styles.treeLevelCard}>
                    <View style={styles.treeLevelHeader}>
                      <View style={[styles.treeBadge, lvl === 1 && styles.l1, lvl === 2 && styles.l2, lvl === 3 && styles.l3, lvl >= 4 && styles.lDeep]}>
                        <Text style={styles.treeBadgeText}>L{lvl}</Text>
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.treeLevelTitle}>{c.toLocaleString("en-IN")} users</Text>
                        <Text style={styles.treeLevelSub} numberOfLines={1}>{sub}</Text>
                      </View>
                      <Text style={[styles.treeLevelEarn, v === 0 && { color: colors.textMuted }]}>{formatINR(earn)}</Text>
                    </View>
                  </View>
                </View>
              );
            })}

            <View style={styles.treeTotal}>
              <View>
                <Text style={styles.treeTotalLabel}>NETWORK SIZE</Text>
                <Text style={styles.treeTotalValue}>{treeTotalNodes.toLocaleString("en-IN")} users</Text>
              </View>
              <View>
                <Text style={styles.treeTotalLabel}>SYSTEM REVENUE</Text>
                <Text style={styles.treeTotalValue}>{formatINR(treeRevenue)}</Text>
              </View>
              <View>
                <Text style={styles.treeTotalLabel}>SPONSOR EARNS</Text>
                <Text style={[styles.treeTotalValue, { color: colors.success }]}>{formatINR(earnTotal)}</Text>
              </View>
            </View>
          </View>

          {msg ? (
            <Text style={[styles.msg, { color: msg === "Saved successfully" ? colors.success : "#B3261E" }]} testID="settings-msg">
              {msg}
            </Text>
          ) : null}

          <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.7 }]} testID="settings-save">
            {saving ? <ActivityIndicator color={colors.primaryFg} /> : (
              <>
                <Feather name="save" size={16} color={colors.primaryFg} />
                <Text style={styles.saveBtnText}>Save changes</Text>
              </>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6, marginBottom: 20 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  sectionHelp: { fontSize: 12, color: colors.textMuted, marginBottom: 14, lineHeight: 18 },
  summaryCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 18, marginBottom: 24 },
  summaryLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 2, fontWeight: "700", marginBottom: 12 },
  summaryRow: { flexDirection: "row", justifyContent: "space-between" },
  summaryStatLabel: { color: "rgba(255,255,255,0.6)", fontSize: 11 },
  summaryStatValue: { color: colors.primaryFg, fontSize: 18, fontWeight: "800", marginTop: 4, letterSpacing: -0.3 },
  field: { marginBottom: 14 },
  fieldLabel: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginBottom: 6 },
  inputWrap: { position: "relative" },
  suffix: { position: "absolute", left: 14, top: 14, fontSize: 16, color: colors.textMuted, fontWeight: "600", zIndex: 1 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 14, fontSize: 16, color: colors.textMain, fontWeight: "600" },
  fieldHelp: { fontSize: 11, color: colors.textMuted, marginTop: 6 },
  levelRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 },
  levelBadge: { width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.primary },
  levelBadgeText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  levelInputWrap: { width: 120, position: "relative" },
  levelSuffix: { position: "absolute", left: 12, top: 12, fontSize: 14, color: colors.textMuted, fontWeight: "700", zIndex: 1 },
  levelInput: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 12, paddingLeft: 26, paddingVertical: 11, fontSize: 14, color: colors.textMain, fontWeight: "700" },
  levelHelp: { flex: 1, fontSize: 11, color: colors.textMuted, lineHeight: 16 },
  treeWrap: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 24 },
  treeRoot: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.primary, padding: 14, borderRadius: 14 },
  treeAvatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" },
  treeRootName: { color: colors.primaryFg, fontSize: 14, fontWeight: "800", letterSpacing: 1.5 },
  treeRootSub: { color: "rgba(255,255,255,0.7)", fontSize: 11, marginTop: 2 },
  treeRootEarn: { color: colors.accent, fontSize: 16, fontWeight: "800", letterSpacing: -0.3 },
  treeLevelWrap: { alignItems: "center" },
  treeConnector: { width: 2, height: 14, backgroundColor: colors.border },
  treeLevelCard: { width: "100%", backgroundColor: colors.surfaceMuted, borderRadius: 12, padding: 10 },
  treeLevelHeader: { flexDirection: "row", alignItems: "center", gap: 10 },
  treeBadge: { width: 32, height: 32, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  l1: { backgroundColor: colors.success },
  l2: { backgroundColor: colors.brand500 },
  l3: { backgroundColor: colors.accent },
  lDeep: { backgroundColor: colors.primary, opacity: 0.7 },
  treeBadgeText: { color: "#fff", fontWeight: "800", fontSize: 11 },
  treeLevelTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  treeLevelSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  treeLevelEarn: { fontSize: 14, fontWeight: "800", color: colors.primary },
  treeTotal: { flexDirection: "row", justifyContent: "space-between", marginTop: 16, paddingTop: 14, borderTopWidth: 1, borderTopColor: colors.border },
  treeTotalLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700" },
  treeTotalValue: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  msg: { fontSize: 13, marginTop: 8, textAlign: "center" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 12 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
});
