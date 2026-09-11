import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator,
  KeyboardAvoidingView, Platform, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Settings = {
  registration_fee: number;
  max_cashback_pct: number;
  default_cashback_pct: number;
  cashback_enabled: boolean;
  cashback_platform_funding_enabled: boolean;
  cashback_clawback_on_return: boolean;
  delivery_charge_enabled: boolean;
  delivery_charge_flat: number;
  delivery_free_threshold: number;
  delivery_cart_max: number;
};

type NumField = {
  key: keyof Settings;
  label: string;
  help: string;
  suffix?: string;
  integer?: boolean;
};

const CASHBACK_FIELDS: NumField[] = [
  {
    key: "default_cashback_pct",
    label: "Default cashback %",
    help: "Applied to products where the vendor has not set their own cashback. 0–10% only.",
    suffix: "%",
  },
];

const DELIVERY_FIELDS: NumField[] = [
  {
    key: "delivery_charge_flat",
    label: "Delivery charge per seller",
    help: "Charged once per seller in the cart when that seller's items are below the free-delivery threshold.",
    suffix: "₹",
  },
  {
    key: "delivery_free_threshold",
    label: "Free delivery above",
    help: "Per-seller item total that makes that seller's delivery free.",
    suffix: "₹",
  },
  {
    key: "delivery_cart_max",
    label: "Maximum cart delivery",
    help: "Hard cap on the delivery charged for the WHOLE cart, however many sellers it contains.",
    suffix: "₹",
  },
];

const TOGGLES: { key: keyof Settings; label: string; help: string }[] = [
  {
    key: "cashback_enabled",
    label: "Purchase cashback",
    help: "When off, no new cashback is created. Cashback already credited is untouched.",
  },
  {
    key: "cashback_platform_funding_enabled",
    label: "Slangcart may front cashback",
    help: "If a seller's wallet is short, Slangcart pays the customer now and recovers it from the seller later.",
  },
  {
    key: "cashback_clawback_on_return",
    label: "Claw back cashback on returns",
    help: "Cashback already paid is recovered when the order is returned. Shortfall is netted off the refund.",
  },
  {
    key: "delivery_charge_enabled",
    label: "Delivery charges",
    help: "When off, every order ships free and no delivery revenue is recorded.",
  },
];

const NUM_KEYS: (keyof Settings)[] = [
  "registration_fee",
  "default_cashback_pct",
  "delivery_charge_flat",
  "delivery_free_threshold",
  "delivery_cart_max",
];

export default function AdminSettings() {
  const [data, setData] = useState<Settings | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Settings>("/admin/settings");
      setData(data);
      const initial: Record<string, string> = {};
      NUM_KEYS.forEach((k) => { initial[k as string] = String((data as any)[k] ?? 0); });
      setForm(initial);
      const f: Record<string, boolean> = {};
      TOGGLES.forEach((t) => { f[t.key as string] = !!(data as any)[t.key]; });
      setFlags(f);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onSave = async () => {
    setMsg("");
    setSaving(true);
    try {
      const payload: any = { ...flags };
      for (const k of NUM_KEYS) {
        const raw = form[k as string];
        if (raw === undefined || raw === "") continue;
        const v = parseFloat(raw);
        if (Number.isNaN(v)) continue;
        payload[k] = v;
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

  const maxPct = Number(data.max_cashback_pct ?? 10);
  const defPct = parseFloat(form.default_cashback_pct || "0") || 0;
  const overMax = defPct > maxPct;
  const flat = parseFloat(form.delivery_charge_flat || "0") || 0;
  const threshold = parseFloat(form.delivery_free_threshold || "0") || 0;
  const cartMax = parseFloat(form.delivery_cart_max || "0") || 0;

  const renderNumber = (f: NumField) => (
    <View key={f.key as string} style={styles.field}>
      <Text style={styles.fieldLabel}>{f.label}</Text>
      <View style={styles.inputWrap}>
        {f.suffix ? <Text style={styles.suffix}>{f.suffix}</Text> : null}
        <TextInput
          testID={`settings-${f.key}`}
          value={form[f.key as string] || ""}
          onChangeText={(t) => setForm((x) => ({ ...x, [f.key as string]: t }))}
          keyboardType="numeric"
          style={[styles.input, !!f.suffix && { paddingLeft: 32 }]}
          placeholder="0"
          placeholderTextColor={colors.textMuted}
        />
      </View>
      <Text style={styles.fieldHelp}>{f.help}</Text>
    </View>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <Text style={styles.overline}>ADMIN</Text>
          <Text style={styles.h1}>Cashback &amp; delivery</Text>
          <Text style={styles.subtitle}>
            Purchase cashback is credited to the customer wallet only after a successful
            delivery. Delivery charges are calculated per seller and capped for the cart.
          </Text>

          <View style={styles.summaryCard} testID="settings-summary">
            <Text style={styles.summaryLabel}>PLATFORM CEILING</Text>
            <View style={styles.summaryRow}>
              <View>
                <Text style={styles.summaryStatLabel}>Max cashback</Text>
                <Text style={styles.summaryStatValue}>{maxPct}%</Text>
              </View>
              <View>
                <Text style={styles.summaryStatLabel}>On ₹1,000</Text>
                <Text style={[styles.summaryStatValue, { color: colors.accent }]}>
                  {formatINR((1000 * Math.min(defPct, maxPct)) / 100)}
                </Text>
              </View>
              <View>
                <Text style={styles.summaryStatLabel}>Cart delivery cap</Text>
                <Text style={styles.summaryStatValue}>{formatINR(cartMax)}</Text>
              </View>
            </View>
          </View>

          <Text style={styles.sectionLabel}>CASHBACK</Text>
          <Text style={styles.sectionHelp}>
            The backend rejects any cashback above {maxPct}% — vendor, product and campaign
            values are all clamped to the same ceiling.
          </Text>
          {CASHBACK_FIELDS.map(renderNumber)}
          {overMax ? (
            <View style={styles.warnBox} testID="settings-cashback-warn">
              <Feather name="alert-triangle" size={14} color="#B45309" />
              <Text style={styles.warnText}>
                {defPct}% is above the {maxPct}% platform ceiling — the server will reject this.
              </Text>
            </View>
          ) : null}

          <Text style={[styles.sectionLabel, { marginTop: 12 }]}>DELIVERY CHARGES</Text>
          <Text style={styles.sectionHelp}>
            Example with these values: a seller&apos;s items below {formatINR(threshold)} add
            {" "}{formatINR(flat)} delivery; {formatINR(threshold)} and above ships free. A
            multi-seller cart never pays more than {formatINR(cartMax)} in total.
          </Text>
          {DELIVERY_FIELDS.map(renderNumber)}

          <Text style={[styles.sectionLabel, { marginTop: 12 }]}>SWITCHES</Text>
          {TOGGLES.map((t) => (
            <View key={t.key as string} style={styles.toggleRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.fieldLabel}>{t.label}</Text>
                <Text style={styles.fieldHelp}>{t.help}</Text>
              </View>
              <Switch
                testID={`settings-toggle-${t.key}`}
                value={!!flags[t.key as string]}
                onValueChange={(v) => setFlags((x) => ({ ...x, [t.key as string]: v }))}
                trackColor={{ true: colors.primary, false: colors.border }}
              />
            </View>
          ))}

          <Text style={[styles.sectionLabel, { marginTop: 12 }]}>SUBSCRIPTION</Text>
          {renderNumber({
            key: "registration_fee",
            label: "Subscription fee",
            help: "One-time optional membership fee. Recognised in full as platform revenue (18% entry GST split out).",
            suffix: "₹",
          })}

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
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6, marginBottom: 20, lineHeight: 19 },
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
  fieldHelp: { fontSize: 11, color: colors.textMuted, marginTop: 6, lineHeight: 16 },
  toggleRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.card, padding: 14, marginBottom: 10,
  },
  warnBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FCD34D",
    borderRadius: radii.card, padding: 12, marginBottom: 14,
  },
  warnText: { flex: 1, fontSize: 12, color: "#78350F", fontWeight: "600", lineHeight: 17 },
  msg: { fontSize: 13, marginTop: 8, textAlign: "center" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 12 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
});
