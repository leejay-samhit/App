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
  msg: { fontSize: 13, marginTop: 8, textAlign: "center" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 12 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
});
