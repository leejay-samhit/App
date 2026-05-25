import { useCallback, useEffect, useState } from "react";
import { View, Text, Image, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator, Alert, Switch, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { useBranding, useBrandingActions, FONT_OPTIONS, type Branding } from "../../src/branding";
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

const TAB_ICON_OPTIONS = [
  "home", "git-branch", "users", "credit-card", "shopping-bag", "user",
  "grid", "pie-chart", "bar-chart-2", "settings",
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

  const setFont = (f: Branding["font"]) => setDraft((d) => ({ ...d, font: f }));

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
        splash_image: draft.splash_image,
        splash_duration_ms: draft.splash_duration_ms,
        splash_bg: draft.splash_bg,
        // ⬇️ THIS WAS MISSING — the whole reason payee_upi_id wasn't
        // saving. Without this key in the PUT body the backend never
        // received the UPI ID / payee name / toggles changes.
        payment_methods: draft.payment_methods,
      });
      setBranding(data);
      Alert.alert("Saved", "Branding updated. Users will see the new theme on next refresh.");
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally { setSaving(false); }
  };

  const onReset = () => {
    Alert.alert("Reset to defaults?", "All branding will revert to the original NetworkPay theme.", [
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

          {/* Font */}
          <SectionHeader icon="bold" label="Font" />
          <View style={styles.fontList}>
            {FONT_OPTIONS.map((f) => (
              <TouchableOpacity key={f.key} onPress={() => setFont(f.key)} style={[styles.fontRow, draft.font === f.key && styles.fontRowActive]} testID={`branding-font-${f.key}`}>
                <Feather name={draft.font === f.key ? "check-circle" : "circle"} size={18} color={draft.font === f.key ? colors.primary : colors.textMuted} />
                <Text style={styles.fontLabel}>{f.label}</Text>
              </TouchableOpacity>
            ))}
          </View>

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
                 placeholder="e.g. kiran@ibl" testID="branding-pm-upiid" />
          <Field label="Payee Display Name" value={draft.payment_methods?.payee_name || ""}
                 onChangeText={(v) => setDraft((d) => ({ ...d, payment_methods: { ...(d.payment_methods || {}), payee_name: v } }))}
                 placeholder={draft.app_name || "NetworkRupay"} testID="branding-pm-payeename" />

          {/* Splash overlay (admin-uploaded launch image + duration) */}
          <SectionHeader icon="image" label="App launch splash" />
          <Text style={styles.helper}>
            Shown for {Math.round((draft.splash_duration_ms || 5000) / 1000)}s when users open the app.
            Recommended size: 1080 × 1920 px (9:16 portrait, ≤500 KB).
          </Text>
          <View style={styles.splashPreviewWrap}>
            <View style={[styles.splashPreview, { backgroundColor: draft.splash_bg || draft.colors.primary }]}>
              {draft.splash_image ? (
                <Image source={{ uri: draft.splash_image }} style={styles.splashPreviewImg} resizeMode="contain" />
              ) : (
                <Text style={styles.splashPreviewFallback}>{draft.app_name || "Launch image"}</Text>
              )}
            </View>
            <View style={{ flex: 1, gap: 8 }}>
              <TouchableOpacity
                onPress={async () => {
                  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
                  if (!perm.granted) { Alert.alert("Permission needed", "Allow photo access to choose a splash image."); return; }
                  const res = await ImagePicker.launchImageLibraryAsync({
                    mediaTypes: ImagePicker.MediaTypeOptions.Images,
                    quality: 0.85,
                    aspect: [9, 16],
                    allowsEditing: true,
                  });
                  if (res.canceled || !res.assets?.[0]?.uri) return;
                  // Compress + base64 encode (≤500KB target).
                  const manip = await ImageManipulator.manipulateAsync(
                    res.assets[0].uri,
                    [{ resize: { width: 1080 } }],
                    { compress: 0.75, format: ImageManipulator.SaveFormat.JPEG, base64: true },
                  );
                  if (!manip.base64) return;
                  const dataUri = `data:image/jpeg;base64,${manip.base64}`;
                  setDraft((d) => ({ ...d, splash_image: dataUri }));
                }}
                style={styles.splashBtn}
                testID="branding-splash-pick"
              >
                <Feather name="upload" size={14} color={colors.primary} />
                <Text style={styles.splashBtnText}>{draft.splash_image ? "Replace image" : "Upload image"}</Text>
              </TouchableOpacity>
              {draft.splash_image ? (
                <TouchableOpacity
                  onPress={() => setDraft((d) => ({ ...d, splash_image: null }))}
                  style={[styles.splashBtn, { backgroundColor: "#FFF7E6", borderColor: "#B85F0044" }]}
                  testID="branding-splash-clear"
                >
                  <Feather name="trash-2" size={14} color="#B85F00" />
                  <Text style={[styles.splashBtnText, { color: "#B85F00" }]}>Remove</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
          <View style={styles.splashRow}>
            <Text style={styles.fieldLabel}>Duration (seconds)</Text>
            <TextInput
              value={String(Math.round((draft.splash_duration_ms || 5000) / 1000))}
              onChangeText={(v) => {
                const sec = Math.max(1, Math.min(10, parseInt(v.replace(/\D/g, "") || "0", 10) || 0));
                setDraft((d) => ({ ...d, splash_duration_ms: sec * 1000 }));
              }}
              keyboardType="number-pad"
              style={styles.splashInput}
              testID="branding-splash-duration"
              maxLength={2}
            />
          </View>
          <View style={styles.splashRow}>
            <Text style={styles.fieldLabel}>Background colour</Text>
            <TextInput
              value={draft.splash_bg || draft.colors.primary}
              onChangeText={(v) => setDraft((d) => ({ ...d, splash_bg: v }))}
              autoCapitalize="characters"
              style={styles.splashInput}
              placeholder="#143D2E"
              placeholderTextColor={colors.textMuted}
              testID="branding-splash-bg"
            />
          </View>

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
  splashPreviewWrap: { flexDirection: "row", gap: 12, marginBottom: 12 },
  splashPreview: { width: 90, height: 160, borderRadius: 12, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  splashPreviewImg: { width: "100%", height: "100%" },
  splashPreviewFallback: { fontSize: 11, color: "#fff", fontWeight: "800", textAlign: "center", paddingHorizontal: 6 },
  splashBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, paddingHorizontal: 12, borderRadius: 10, borderWidth: 1, borderColor: colors.primary + "55", backgroundColor: colors.brand100 },
  splashBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  splashRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  splashInput: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, fontSize: 13, fontWeight: "700", color: colors.textMain, backgroundColor: colors.surface, minWidth: 110, textAlign: "center" },
});
