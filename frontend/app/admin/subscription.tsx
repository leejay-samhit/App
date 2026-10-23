// Admin → Membership. The ₹118 price, how it splits (GST / member cashback /
// platform / invite bonus), the member-only switches and the WhatsApp number
// used by priority support. Everything here is read by the paywall and by the
// money engine, so what the owner sets is exactly what the ledger books.
import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, TextInput, Switch, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { notify } from "../../src/notify";
import { CRYSTAL } from "../../src/subscription";

type Cfg = {
  price: number; gst: number; net: number; cashback_pct: number;
  member_cashback: number; invite_bonus: number; platform_revenue: number;
  platform_revenue_with_invite: number;
  benefits: { key: string; title: string; sub: string; free_text: string; enabled: boolean }[];
  free_reveals: boolean; zero_ads: boolean; priority_support: boolean;
  support_whatsapp: string; subscribers: number; non_subscribers: number;
};

export default function AdminSubscriptionScreen() {
  const router = useRouter();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [price, setPrice] = useState("");
  const [pct, setPct] = useState("");
  const [bonus, setBonus] = useState("");
  const [wa, setWa] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Cfg>("/admin/subscription/config");
      setCfg(data);
      setPrice(String(data.price ?? ""));
      setPct(String(data.cashback_pct ?? ""));
      setBonus(String(data.invite_bonus ?? ""));
      setWa(String(data.support_whatsapp ?? ""));
    } catch (e) {
      notify(formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = async (patch: Record<string, unknown>) => {
    setSaving(true);
    try {
      const { data } = await api.put<Cfg>("/admin/subscription/config", patch);
      setCfg(data);
      notify("Membership updated");
    } catch (e) {
      notify(formatApiError(e));
      load();
    } finally {
      setSaving(false);
    }
  };

  const saveNumbers = () => {
    const p = parseFloat(price || "0") || 0;
    const c = parseFloat(pct || "0") || 0;
    const b = parseFloat(bonus || "0") || 0;
    const net = p - Math.round((p * 18 / 118) * 100) / 100;
    const cash = Math.round((net * c / 100) * 100) / 100;
    if (b > net - cash + 0.009) {
      notify(`The invite bonus can't be more than the ${formatINR(net - cash)} the platform keeps`);
      return;
    }
    save({ price: p, cashback_pct: c, invite_bonus: b, support_whatsapp: wa });
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  const live = cfg!;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.back} testID="sub-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Membership</Text>
        <View style={{ width: 36 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView
          contentContainerStyle={styles.container}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          {/* Live split — the exact rupees the ledger books */}
          <LinearGradient
            colors={[CRYSTAL.g1, CRYSTAL.g2, CRYSTAL.g3]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.hero}
            testID="sub-split-hero"
          >
            <View style={styles.heroEdge} pointerEvents="none" />
            <Text style={styles.heroTag}>EVERY MEMBERSHIP OF {formatINR(live.price)}</Text>
            <View style={styles.heroRows}>
              {[
                ["Member wallet (instant cashback)", live.member_cashback, CRYSTAL.gold],
                ["GST ledger", live.gst, "#fff"],
                ["Platform revenue", live.platform_revenue, "#fff"],
                ["…of which invite bonus", live.invite_bonus, CRYSTAL.ice],
                ["Platform keeps with an inviter", live.platform_revenue_with_invite, "#fff"],
              ].map(([label, value, color]) => (
                <View key={String(label)} style={styles.heroRow}>
                  <Text style={styles.heroLabel}>{label as string}</Text>
                  <Text style={[styles.heroValue, { color: color as string }]}>{formatINR(Number(value))}</Text>
                </View>
              ))}
            </View>
            <View style={styles.heroStatRow}>
              <View style={styles.heroStat}>
                <Text style={styles.heroStatValue}>{live.subscribers}</Text>
                <Text style={styles.heroStatLabel}>MEMBERS</Text>
              </View>
              <View style={styles.heroStat}>
                <Text style={styles.heroStatValue}>{live.non_subscribers}</Text>
                <Text style={styles.heroStatLabel}>FREE ACCOUNTS</Text>
              </View>
            </View>
          </LinearGradient>

          {/* Numbers */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Price & split</Text>
            {[
              { id: "price", label: "Membership price (₹, GST inclusive)", value: price, set: setPrice, hint: "₹18 of every ₹118 is GST" },
              { id: "cashback", label: "Instant cashback %", value: pct, set: setPct, hint: "Share of the GST-free amount credited to the member's wallet" },
              { id: "bonus", label: "Invite bonus (₹)", value: bonus, set: setBonus, hint: "Paid out of the platform's share to the inviter's wallet" },
            ].map((f) => (
              <View key={f.id} style={styles.field}>
                <Text style={styles.fieldLabel}>{f.label}</Text>
                <TextInput
                  value={f.value}
                  onChangeText={f.set}
                  keyboardType="decimal-pad"
                  style={styles.input}
                  placeholderTextColor={colors.textMuted}
                  testID={`sub-input-${f.id}`}
                />
                <Text style={styles.fieldHint}>{f.hint}</Text>
              </View>
            ))}
            <View style={styles.field}>
              <Text style={styles.fieldLabel}>Priority support WhatsApp number</Text>
              <TextInput
                value={wa}
                onChangeText={setWa}
                keyboardType="phone-pad"
                placeholder="919154735888"
                style={styles.input}
                placeholderTextColor={colors.textMuted}
                testID="sub-input-whatsapp"
              />
              <Text style={styles.fieldHint}>Country code + number, no + or spaces</Text>
            </View>
            <TouchableOpacity
              onPress={saveNumbers}
              disabled={saving}
              style={[styles.saveBtn, saving && { opacity: 0.6 }]}
              testID="sub-save"
            >
              {saving ? <ActivityIndicator color={colors.primaryFg} size="small" />
                : <Feather name="check" size={16} color={colors.primaryFg} />}
              <Text style={styles.saveBtnText}>Save</Text>
            </TouchableOpacity>
          </View>

          {/* Member-only switches */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Member benefits</Text>
            {[
              { key: "free_reveals", label: "Unlimited service numbers free", help: "Members pay nothing to get a provider's number. Free accounts pay the phone-reveal fee.", value: live.free_reveals },
              { key: "zero_ads", label: "Zero ads", help: "Hide every promotional banner for members.", value: live.zero_ads },
              { key: "priority_support", label: "Real-time priority support", help: "Shows the WhatsApp support button to members.", value: live.priority_support },
            ].map((t) => (
              <View key={t.key} style={styles.toggleRow}>
                <View style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                  <Text style={styles.toggleLabel}>{t.label}</Text>
                  <Text style={styles.fieldHint}>{t.help}</Text>
                </View>
                <Switch
                  value={t.value}
                  onValueChange={(v) => save({ [t.key]: v })}
                  trackColor={{ true: colors.primary, false: colors.border }}
                  testID={`sub-toggle-${t.key}`}
                />
              </View>
            ))}
          </View>

          {/* What the member sees */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>What members see</Text>
            {(live.benefits || []).map((b) => (
              <View key={b.key} style={styles.benefitRow}>
                <Feather
                  name={b.enabled ? "check-circle" : "x-circle"}
                  size={15}
                  color={b.enabled ? colors.success : colors.textMuted}
                />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.benefitTitle}>{b.title}</Text>
                  <Text style={styles.fieldHint}>{b.sub}</Text>
                  <Text style={styles.benefitFree}>Free account: {b.free_text}</Text>
                </View>
              </View>
            ))}
          </View>

          <TouchableOpacity
            onPress={() => router.push("/admin/payout-structure" as any)}
            style={styles.linkCard}
            testID="sub-goto-payout"
          >
            <Feather name="sliders" size={18} color={colors.primary} />
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.linkTitle}>Payout structure, shop by shop</Text>
              <Text style={styles.fieldHint}>Cashback % and delivery charge per seller</Text>
            </View>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  back: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  container: { padding: spacing.screen, paddingBottom: 48 },

  hero: { borderRadius: 24, padding: 20, overflow: "hidden", marginBottom: 16 },
  heroEdge: {
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0, borderRadius: 24,
    borderWidth: 1, borderColor: CRYSTAL.border,
  },
  heroTag: { fontSize: 10, fontWeight: "900", color: CRYSTAL.gold, letterSpacing: 1.4 },
  heroRows: { marginTop: 12 },
  heroRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: "rgba(255,255,255,0.14)",
  },
  heroLabel: { fontSize: 12.5, color: CRYSTAL.ice, flex: 1, minWidth: 0 },
  heroValue: { fontSize: 14, fontWeight: "900" },
  heroStatRow: { flexDirection: "row", gap: 10, marginTop: 14 },
  heroStat: {
    flex: 1, backgroundColor: CRYSTAL.glass, borderRadius: 14, padding: 12,
    borderWidth: 1, borderColor: CRYSTAL.border,
  },
  heroStatValue: { fontSize: 20, fontWeight: "900", color: "#fff" },
  heroStatLabel: { fontSize: 9, fontWeight: "900", color: CRYSTAL.ice, letterSpacing: 1.2, marginTop: 2 },

  card: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 16, marginBottom: 14,
  },
  cardTitle: {
    fontSize: 11, fontWeight: "900", color: colors.textMuted, letterSpacing: 1.6,
    textTransform: "uppercase", marginBottom: 10,
  },
  field: { marginBottom: 14 },
  fieldLabel: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginBottom: 6 },
  fieldHint: { fontSize: 11.5, color: colors.textMuted, marginTop: 4, lineHeight: 16 },
  input: {
    minHeight: 46, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    paddingHorizontal: 14, fontSize: 15, color: colors.textMain, backgroundColor: colors.background,
  },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button, backgroundColor: colors.primary,
  },
  saveBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },

  toggleRow: {
    flexDirection: "row", alignItems: "center", paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  toggleLabel: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },

  benefitRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  benefitTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  benefitFree: { fontSize: 11, color: colors.error, marginTop: 3, fontWeight: "700" },

  linkCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 16,
  },
  linkTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
});
