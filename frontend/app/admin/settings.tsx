import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Settings = {
  registration_fee: number;
  payout_l1: number;
  payout_l2: number;
  payout_l3: number;
  directs_required: number;
};

const FIELDS: { key: keyof Settings; label: string; help: string; suffix?: string; integer?: boolean }[] = [
  { key: "registration_fee", label: "Registration fee", help: "One-time fee paid by every new user.", suffix: "₹" },
  { key: "directs_required", label: "Directs per cycle", help: "How many direct paid referrals trigger a Level 1 payout.", integer: true },
  { key: "payout_l1", label: "Level 1 payout", help: "Amount credited to direct sponsor each completed cycle.", suffix: "₹" },
  { key: "payout_l2", label: "Level 2 payout", help: "Amount credited per signup to grand-sponsor.", suffix: "₹" },
  { key: "payout_l3", label: "Level 3 payout", help: "Amount credited per signup to great-grand-sponsor.", suffix: "₹" },
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
      setForm({
        registration_fee: String(data.registration_fee),
        payout_l1: String(data.payout_l1),
        payout_l2: String(data.payout_l2),
        payout_l3: String(data.payout_l3),
        directs_required: String(data.directs_required),
      });
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onSave = async () => {
    setMsg("");
    setSaving(true);
    try {
      const payload: any = {};
      for (const f of FIELDS) {
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

  // Quick-projection: cost vs revenue per cycle
  const cycleCost = data.payout_l1 + data.directs_required * (data.payout_l2 + data.payout_l3);
  const cycleRevenue = data.directs_required * data.registration_fee;
  const margin = cycleRevenue - cycleCost;

  // Full-tree (3-level) projection from one sponsor's perspective
  const N = data.directs_required;
  const treeL1Count = N;
  const treeL2Count = N * N;
  const treeL3Count = N * N * N;
  const treeTotalNodes = treeL1Count + treeL2Count + treeL3Count;
  // Sponsor's earnings:
  // L1: one cycle bonus when their N directs all pay
  const earnL1 = data.payout_l1;
  // L2: ₹L2 per signup × number of grand-directs that pay
  const earnL2 = data.payout_l2 * treeL2Count;
  // L3: ₹L3 per signup × number of great-grand-directs that pay
  const earnL3 = data.payout_l3 * treeL3Count;
  const earnTotal = earnL1 + earnL2 + earnL3;
  // System-wide spend on registrations vs payouts in fully-built tree
  const treeRevenue = treeTotalNodes * data.registration_fee;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <Text style={styles.overline}>ADMIN</Text>
          <Text style={styles.h1}>Payout settings</Text>
          <Text style={styles.subtitle}>Tune the registration fee and 3-level commission structure. Applies to all new payouts.</Text>

          <View style={styles.summaryCard}>
            <Text style={styles.summaryLabel}>PER CYCLE PROJECTION ({data.directs_required} signups)</Text>
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

          {FIELDS.map((f) => (
            <View key={f.key} style={styles.field}>
              <Text style={styles.fieldLabel}>{f.label}</Text>
              <View style={styles.inputWrap}>
                {f.suffix && <Text style={styles.suffix}>{f.suffix}</Text>}
                <TextInput
                  testID={`settings-${f.key}`}
                  value={form[f.key]}
                  onChangeText={(t) => setForm((x) => ({ ...x, [f.key]: t }))}
                  keyboardType="numeric"
                  style={[styles.input, !!f.suffix && { paddingLeft: 32 }]}
                  placeholder="0"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
              <Text style={styles.fieldHelp}>{f.help}</Text>
            </View>
          ))}

          <Text style={[styles.sectionLabel, { marginTop: 8 }]}>1+{N} TREE PROJECTION</Text>
          <Text style={styles.sectionHelp}>
            One sponsor's potential earnings if their network fills 3 levels deep with {N} directs each.
          </Text>

          <View style={styles.treeWrap} testID="tree-projection">
            <View style={styles.treeRoot}>
              <View style={styles.treeAvatar}><Feather name="user" size={18} color={colors.primaryFg} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.treeRootName}>YOU</Text>
                <Text style={styles.treeRootSub}>Sponsor — earns from 3 levels below</Text>
              </View>
              <Text style={styles.treeRootEarn}>{formatINR(earnTotal)}</Text>
            </View>

            <TreeLevel
              level={1}
              count={treeL1Count}
              perSignup={data.payout_l1}
              levelLabel={`Cycle bonus when all ${N} pay`}
              total={earnL1}
              isCycle
              testID="tree-l1"
            />
            <TreeLevel
              level={2}
              count={treeL2Count}
              perSignup={data.payout_l2}
              levelLabel={`${data.payout_l2 ? "₹" + data.payout_l2 : "₹0"} × ${treeL2Count} grand-directs`}
              total={earnL2}
              testID="tree-l2"
            />
            <TreeLevel
              level={3}
              count={treeL3Count}
              perSignup={data.payout_l3}
              levelLabel={`${data.payout_l3 ? "₹" + data.payout_l3 : "₹0"} × ${treeL3Count} great-grand-directs`}
              total={earnL3}
              testID="tree-l3"
            />

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

function TreeLevel({ level, count, perSignup, levelLabel, total, isCycle, testID }: { level: number; count: number; perSignup: number; levelLabel: string; total: number; isCycle?: boolean; testID?: string }) {
  return (
    <View style={styles.treeLevelWrap} testID={testID}>
      <View style={styles.treeConnector} />
      <View style={styles.treeLevelCard}>
        <View style={styles.treeLevelHeader}>
          <View style={[styles.treeBadge, level === 1 ? styles.l1 : level === 2 ? styles.l2 : styles.l3]}>
            <Text style={styles.treeBadgeText}>L{level}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.treeLevelTitle}>{count.toLocaleString("en-IN")} {level === 1 ? "directs" : level === 2 ? "grand-directs" : "great-grand"}</Text>
            <Text style={styles.treeLevelSub}>{isCycle ? `One ₹${perSignup} cycle bonus` : levelLabel}</Text>
          </View>
          <Text style={styles.treeLevelEarn}>{formatINR(total)}</Text>
        </View>
        {/* Mini node row showing dots */}
        <View style={styles.treeNodes}>
          {Array.from({ length: Math.min(count, 12) }).map((_, i) => (
            <View key={i} style={[styles.treeNode, level === 1 && { backgroundColor: colors.success }, level === 2 && { backgroundColor: colors.brand500 }, level === 3 && { backgroundColor: colors.accent }]} />
          ))}
          {count > 12 && <Text style={styles.treeMore}>+{count - 12}</Text>}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6, marginBottom: 20 },
  summaryCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 18, marginBottom: 24 },
  summaryLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 2, fontWeight: "700", marginBottom: 12 },
  summaryRow: { flexDirection: "row", justifyContent: "space-between" },
  summaryStatLabel: { color: "rgba(255,255,255,0.6)", fontSize: 11 },
  summaryStatValue: { color: colors.primaryFg, fontSize: 18, fontWeight: "800", marginTop: 4, letterSpacing: -0.3 },
  field: { marginBottom: 16 },
  fieldLabel: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginBottom: 6 },
  inputWrap: { position: "relative" },
  suffix: { position: "absolute", left: 14, top: 14, fontSize: 16, color: colors.textMuted, fontWeight: "600", zIndex: 1 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 14, fontSize: 16, color: colors.textMain, fontWeight: "600" },
  fieldHelp: { fontSize: 11, color: colors.textMuted, marginTop: 6 },
  sectionHelp: { fontSize: 12, color: colors.textMuted, marginBottom: 14, lineHeight: 18 },
  treeWrap: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 24 },
  treeRoot: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.primary, padding: 14, borderRadius: 14 },
  treeAvatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" },
  treeRootName: { color: colors.primaryFg, fontSize: 14, fontWeight: "800", letterSpacing: 1.5 },
  treeRootSub: { color: "rgba(255,255,255,0.7)", fontSize: 11, marginTop: 2 },
  treeRootEarn: { color: colors.accent, fontSize: 16, fontWeight: "800", letterSpacing: -0.3 },
  treeLevelWrap: { alignItems: "center" },
  treeConnector: { width: 2, height: 20, backgroundColor: colors.border },
  treeLevelCard: { width: "100%", backgroundColor: colors.surfaceMuted, borderRadius: 14, padding: 12 },
  treeLevelHeader: { flexDirection: "row", alignItems: "center", gap: 10 },
  treeBadge: { width: 36, height: 36, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  l1: { backgroundColor: colors.success },
  l2: { backgroundColor: colors.brand500 },
  l3: { backgroundColor: colors.accent },
  treeBadgeText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  treeLevelTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  treeLevelSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  treeLevelEarn: { fontSize: 15, fontWeight: "800", color: colors.primary },
  treeNodes: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 10, alignItems: "center" },
  treeNode: { width: 8, height: 8, borderRadius: 4 },
  treeMore: { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginLeft: 4 },
  treeTotal: { flexDirection: "row", justifyContent: "space-between", marginTop: 16, paddingTop: 14, borderTopWidth: 1, borderTopColor: colors.border },
  treeTotalLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700" },
  treeTotalValue: { fontSize: 14, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  msg: { fontSize: 13, marginTop: 8, textAlign: "center" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 12 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
});
