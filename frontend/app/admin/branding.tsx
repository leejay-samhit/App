import { useEffect, useState } from "react";
import { View, Text, Image, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator, Alert, Switch, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useBranding, useBrandingActions, type Branding } from "../../src/branding";
import { colors, radii, spacing } from "../../src/theme";

const COLOR_FIELDS: { key: keyof Branding["colors"]; label: string }[] = [
  { key: "primary", label: "Primary" },
  { key: "primaryFg", label: "Primary text" },
  { key: "accent", label: "Accent" },
  { key: "accentFg", label: "Accent text" },
  { key: "background", label: "Background" },
  { key: "surface", label: "Surface" },
  { key: "surfaceMuted", label: "Surface muted" },
  { key: "textMain", label: "Main text" },
  { key: "textMuted", label: "Muted text" },
  { key: "border", label: "Borders" },
];


export default function AdminBranding() {
  const router = useRouter();
  const branding = useBranding();
  const { setBranding } = useBrandingActions();

  const [draft, setDraft] = useState<Branding>(branding);
  const [saving, setSaving] = useState(false);

  // keep local draft synced when remote branding changes (e.g. after reset)
  useEffect(() => { setDraft(branding); }, [branding]);

  const setColor = (k: keyof Branding["colors"], v: string) => {
    setDraft((d) => ({ ...d, colors: { ...d.colors, [k]: v } }));
  };

  const setText = (k: keyof Branding, v: string) => {
    setDraft((d) => ({ ...d, [k]: v } as Branding));
  };


  const moveTab = (index: number, dir: -1 | 1) => {
    setDraft((d) => {
      const tabs = [...d.tabs];
      const j = index + dir;
      if (j < 0 || j >= tabs.length) return d;
      [tabs[index], tabs[j]] = [tabs[j], tabs[index]];
      return { ...d, tabs };
    });
  };

  const toggleTab = (index: number) => {
    setDraft((d) => {
      const tabs = d.tabs.map((t, i) => i === index ? { ...t, visible: !t.visible } : t);
      return { ...d, tabs };
    });
  };

  const onSave = async () => {
    setSaving(true);
    try {
      const { data } = await api.put<Branding>("/admin/branding", {
        app_name: draft.app_name,
        tagline: draft.tagline,
        login_subtitle: draft.login_subtitle,
        payment_hero: draft.payment_hero,
        pending_hero: draft.pending_hero,
        colors: draft.colors,
        font: draft.font,
        tabs: draft.tabs,
        // ⬇️ THIS WAS MISSING — the whole reason payee_upi_id wasn't
        // saving. Without this key in the PUT body the backend never
        // received the UPI ID / payee name / toggles changes.
        payment_methods: draft.payment_methods,
        // ─── Premium theme extensions (June 2026) ───
        gradient: draft.gradient,
        button_style: draft.button_style,
        home_banner_b64: draft.home_banner_b64 ?? "",
      });
      setBranding(data);
      Alert.alert("Saved", "Branding updated. Users will see the new theme on next refresh.");
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally { setSaving(false); }
  };

  const onReset = () => {
    Alert.alert("Reset to defaults?", "All branding will revert to the original Slangcart theme.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Reset", style: "destructive", onPress: async () => {
          setSaving(true);
          try {
            const { data } = await api.post<Branding>("/admin/branding/reset");
            setBranding(data);
            setDraft(data);
          } catch (e) {
            Alert.alert("Reset failed", formatApiError(e));
          } finally { setSaving(false); }
        },
      },
    ]);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>Branding</Text>
          <TouchableOpacity onPress={onReset} style={styles.iconBtn} testID="branding-reset">
            <Feather name="rotate-ccw" size={16} color={colors.textMain} />
          </TouchableOpacity>
        </View>

        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {/* Live preview */}
          <View style={[styles.previewCard, { backgroundColor: draft.colors.surface, borderColor: draft.colors.border }]}>
            <Text style={[styles.previewTitle, { color: draft.colors.textMain }]}>{draft.app_name}</Text>
            <Text style={[styles.previewSub, { color: draft.colors.textMuted }]}>{draft.tagline}</Text>
            <View style={[styles.previewBtn, { backgroundColor: draft.colors.primary }]}>
              <Text style={[styles.previewBtnText, { color: draft.colors.primaryFg }]}>Primary CTA</Text>
            </View>
            <View style={[styles.previewBtn, { backgroundColor: draft.colors.accent, marginTop: 8 }]}>
              <Text style={[styles.previewBtnText, { color: draft.colors.accentFg }]}>Accent CTA</Text>
            </View>
          </View>

          {/* Text */}
          <SectionHeader icon="type" label="App text" />
          <Field label="App name" value={draft.app_name} onChangeText={(v) => setText("app_name", v)} testID="branding-app-name" />
          <Field label="Tagline" value={draft.tagline} onChangeText={(v) => setText("tagline", v)} multiline testID="branding-tagline" />
          <Field label="Login subtitle (large heading)" value={draft.login_subtitle} onChangeText={(v) => setText("login_subtitle", v)} testID="branding-login-sub" />
          <Field label="Payment hero" value={draft.payment_hero} onChangeText={(v) => setText("payment_hero", v)} testID="branding-payment-hero" />
          <Field label="Pending-approval hero" value={draft.pending_hero} onChangeText={(v) => setText("pending_hero", v)} testID="branding-pending-hero" />

          {/* Colors */}
          <SectionHeader icon="droplet" label="Colors" />
          {COLOR_FIELDS.map((f) => (
            <View key={f.key} style={styles.colorRow}>
              <View style={[styles.swatch, { backgroundColor: draft.colors[f.key] }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.fieldLabel}>{f.label}</Text>
                <TextInput
                  value={draft.colors[f.key]}
                  onChangeText={(v) => setColor(f.key, v)}
                  autoCapitalize="characters"
                  placeholder="#RRGGBB"
                  style={styles.hexInput}
                  maxLength={9}
                  testID={`branding-color-${f.key}`}
                />
              </View>
            </View>
          ))}

          {/* Payment methods (Feb-2026) — Razorpay toggle + Manual UPI config */}
          <SectionHeader icon="credit-card" label="Payment methods" />
          <Text style={styles.helper}>
            Toggle Razorpay (advanced) or manual UPI flow. UPI ID is used in the deep link upi://pay?pa=…
          </Text>
          <View style={styles.splashRow}>
            <Text style={styles.fieldLabel}>Razorpay enabled</Text>
            <Switch
              value={!!draft.payment_methods?.razorpay_enabled}
              onValueChange={(v) => setDraft((d) => ({ ...d, payment_methods: { ...(d.payment_methods || {}), razorpay_enabled: v } }))}
              trackColor={{ false: colors.border, true: colors.primary }}
              testID="branding-pm-razorpay"
            />
          </View>
          <View style={styles.splashRow}>
            <Text style={styles.fieldLabel}>UPI manual enabled</Text>
            <Switch
              value={draft.payment_methods?.upi_manual_enabled !== false}
              onValueChange={(v) => setDraft((d) => ({ ...d, payment_methods: { ...(d.payment_methods || {}), upi_manual_enabled: v } }))}
              trackColor={{ false: colors.border, true: colors.primary }}
              testID="branding-pm-upimanual"
            />
          </View>
          <Field label="Payee UPI ID" value={draft.payment_methods?.payee_upi_id || ""}
                 onChangeText={(v) => setDraft((d) => ({ ...d, payment_methods: { ...(d.payment_methods || {}), payee_upi_id: v.trim() } }))}
                 placeholder="e.g. slangcart@hdfcbank" testID="branding-pm-upiid" />

          {/* Live VPA-class hint: shown only when admin has typed a UPI ID. */}
          {draft.payment_methods?.payee_upi_id ? (() => {
            const PERSONAL = new Set(["ybl","ibl","axl","axisb","okhdfcbank","okaxis","oksbi","okicici","paytm","ptaxis","ptyes","ptsbi","pthdfc","apl","waicici","waaxis","wasbi","cred","jupiteraxis","jupaxis","upi","rapl"]);
            const vpa = draft.payment_methods.payee_upi_id;
            const suffix = vpa.includes("@") ? vpa.split("@").pop()!.toLowerCase().trim() : "";
            const isPersonal = PERSONAL.has(suffix);
            return (
              <View style={[styles.vpaHint, { backgroundColor: isPersonal ? "#FEF3C7" : "#DCFCE7", borderColor: isPersonal ? "#FDE68A" : "#86EFAC" }]}>
                <Text style={[styles.vpaHintText, { color: isPersonal ? "#78350F" : "#14532D" }]}>
                  {isPersonal
                    ? `⚠ Personal VPA detected (@${suffix}). PhonePe / GPay may block direct-pay buttons — users will see QR + Copy-UPI-ID only. To enable direct-pay buttons, switch to a merchant VPA (e.g. ...@hdfcbank, ...@icici, ...@razorpay).`
                    : `✓ Merchant-style VPA (@${suffix}). Direct-pay buttons (GPay / PhonePe / Paytm) will be visible to users.`}
                </Text>
              </View>
            );
          })() : null}

          <Field label="Payee Display Name" value={draft.payment_methods?.payee_name || ""}
                 onChangeText={(v) => setDraft((d) => ({ ...d, payment_methods: { ...(d.payment_methods || {}), payee_name: v } }))}
                 placeholder={draft.app_name || "Slangcart"} testID="branding-pm-payeename" />

          {/* ─── Premium theme (June 2026) — gradient, button style, banner ─── */}
          <SectionHeader icon="layers" label="Premium theme" />
          <Text style={styles.helper}>
            Controls the gradient hero (login / register / payment) and the global button style.
          </Text>

          {/* Gradient preview */}
          {(() => {
            const g = draft.gradient || {};
            return (
              <View style={[styles.splashPreview, {
                backgroundColor: g.start || "#0A0E27",
                borderColor: g.glow || colors.primary,
                borderWidth: 1,
              }]}>
                <View style={{ alignItems: "center" }}>
                  <Text style={{ color: "#fff", fontWeight: "900", fontSize: 18 }}>Preview</Text>
                  <Text style={{ color: "#C7D2FE", fontSize: 11, marginTop: 4 }}>Hero gradient</Text>
                </View>
              </View>
            );
          })()}

          {(["start", "middle", "end", "glow"] as const).map((k) => (
            <Field
              key={k}
              label={`Gradient ${k} colour (#hex)`}
              value={(draft.gradient || {})[k] || ""}
              placeholder={k === "start" ? "#0A0E27" : k === "middle" ? "#1E2A78" : k === "end" ? "#5B21B6" : "#06B6D4"}
              onChangeText={(v) =>
                setDraft((d) => ({
                  ...d,
                  gradient: { ...(d.gradient || {}), [k]: v.trim() },
                }))
              }
              testID={`branding-gradient-${k}`}
            />
          ))}

          <Text style={styles.helper}>Button shape</Text>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
            {(["rounded", "pill", "square"] as const).map((bs) => (
              <TouchableOpacity
                key={bs}
                onPress={() => setDraft((d) => ({ ...d, button_style: bs }))}
                style={{
                  flex: 1, paddingVertical: 11,
                  borderRadius: bs === "pill" ? 999 : bs === "rounded" ? 14 : 4,
                  alignItems: "center",
                  backgroundColor: draft.button_style === bs ? colors.primary : colors.surface,
                  borderWidth: 1,
                  borderColor: draft.button_style === bs ? colors.primary : colors.border,
                }}
                testID={`branding-btnstyle-${bs}`}
              >
                <Text
                  style={{
                    fontWeight: "800",
                    fontSize: 12,
                    color: draft.button_style === bs ? "#fff" : colors.textMain,
                    textTransform: "capitalize",
                  }}
                >
                  {bs}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <Field
            label="Home banner (image URL or data: URI, max 800KB)"
            value={draft.home_banner_b64 || ""}
            placeholder="https://… or data:image/png;base64,…"
            onChangeText={(v) => setDraft((d) => ({ ...d, home_banner_b64: v.trim() || null }))}
            testID="branding-home-banner"
          />
          {draft.home_banner_b64 ? (
            <Image
              source={{ uri: draft.home_banner_b64 }}
              style={{ width: "100%", height: 140, borderRadius: 14, marginTop: 8, backgroundColor: colors.surfaceMuted }}
              resizeMode="cover"
            />
          ) : null}

          {/* Tabs */}
          <SectionHeader icon="grid" label="Bottom navigation" />
          <Text style={styles.helper}>Reorder with the up/down arrows. Toggle visibility to hide a tab. At least one tab must remain visible.</Text>
          {draft.tabs.map((t, i) => (
            <View key={t.key} style={styles.tabRow}>
              <View style={styles.tabIconWrap}>
                <Feather name={t.icon as any} size={16} color={colors.textMain} />
              </View>
              <View style={{ flex: 1 }}>
                <TextInput
                  value={t.label}
                  onChangeText={(v) => setDraft((d) => ({ ...d, tabs: d.tabs.map((tt, j) => j === i ? { ...tt, label: v } : tt) }))}
                  style={styles.tabLabelInput}
                  testID={`branding-tab-${t.key}-label`}
                />
                <Text style={styles.tabKeyText}>{t.key}</Text>
              </View>
              <TouchableOpacity onPress={() => moveTab(i, -1)} disabled={i === 0} style={[styles.iconBtn, i === 0 && { opacity: 0.3 }]} testID={`branding-tab-${t.key}-up`}>
                <Feather name="arrow-up" size={14} color={colors.textMain} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => moveTab(i, 1)} disabled={i === draft.tabs.length - 1} style={[styles.iconBtn, i === draft.tabs.length - 1 && { opacity: 0.3 }]} testID={`branding-tab-${t.key}-down`}>
                <Feather name="arrow-down" size={14} color={colors.textMain} />
              </TouchableOpacity>
              <Switch value={t.visible} onValueChange={() => toggleTab(i)} testID={`branding-tab-${t.key}-visible`} />
            </View>
          ))}

          <View style={{ height: 80 }} />
        </ScrollView>

        <View style={styles.footer}>
          <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.6 }]} testID="branding-save">
            {saving ? <ActivityIndicator color={colors.primaryFg} /> : (
              <>
                <Feather name="check" size={16} color={colors.primaryFg} />
                <Text style={styles.saveBtnText}>  Save branding</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function SectionHeader({ icon, label }: { icon: any; label: string }) {
  return (
    <View style={styles.sectionHeader}>
      <Feather name={icon} size={14} color={colors.textMuted} />
      <Text style={styles.sectionLabel}>{label.toUpperCase()}</Text>
    </View>
  );
}

function Field({ label, value, onChangeText, multiline, testID }: { label: string; value: string; onChangeText: (v: string) => void; multiline?: boolean; testID?: string }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput value={value} onChangeText={onChangeText} multiline={multiline} style={[styles.input, multiline && { minHeight: 60, paddingTop: 12 }]} testID={testID} />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  iconBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  content: { padding: spacing.screen, paddingTop: 8, paddingBottom: 80 },
  previewCard: { borderWidth: 1, borderRadius: radii.card, padding: 20, marginBottom: 20 },
  previewTitle: { fontSize: 22, fontWeight: "800" },
  previewSub: { fontSize: 13, marginTop: 4, marginBottom: 16 },
  previewBtn: { paddingVertical: 12, alignItems: "center", borderRadius: radii.button },
  previewBtnText: { fontWeight: "800", fontSize: 14 },
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 18, marginBottom: 10 },
  sectionLabel: { fontSize: 11, letterSpacing: 1.5, fontWeight: "800", color: colors.textMuted },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, padding: 12, fontSize: 14, color: colors.textMain },
  helper: { fontSize: 12, color: colors.textMuted, marginBottom: 10 },
  vpaHint: { marginTop: -6, marginBottom: 12, padding: 10, borderRadius: 10, borderWidth: 1 },
  vpaHintText: { fontSize: 11, lineHeight: 16, fontWeight: "700" },
  colorRow: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 10 },
  swatch: { width: 36, height: 36, borderRadius: 10, borderWidth: 1, borderColor: colors.border },
  hexInput: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingVertical: 8, paddingHorizontal: 12, fontSize: 13, color: colors.textMain, fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }) },
  fontList: { gap: 8 },
  fontRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  fontRowActive: { borderColor: colors.primary, backgroundColor: "#F5FBF8" },
  fontLabel: { fontSize: 14, color: colors.textMain, fontWeight: "700" },
  tabRow: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, marginBottom: 8 },
  tabIconWrap: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  tabLabelInput: { fontSize: 13, color: colors.textMain, fontWeight: "700", paddingVertical: 0 },
  tabKeyText: { fontSize: 10, color: colors.textMuted, marginTop: 1 },
  footer: { padding: spacing.screen, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.background },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  // Splash uploader
  splashPreview: { width: 90, height: 160, borderRadius: 12, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  splashRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
});
