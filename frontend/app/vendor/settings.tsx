// POS settings — mirrors /vendor/settings on the web.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Switch } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { colors, spacing } from "../../src/theme";
import { getPosSettings, updatePosSettings, PosSettings } from "../../src/vendor-pos-client";
import { formatApiError } from "../../src/api";

export default function VendorPosSettings() {
  const router = useRouter();
  const [s, setS] = useState<PosSettings | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => { (async () => { try { setS(await getPosSettings()); } catch (e) { Alert.alert("Load failed", formatApiError(e)); } })(); }, []);

  const save = useCallback(async () => {
    if (!s) return;
    setSaving(true);
    try {
      const updated = await updatePosSettings(s);
      setS(updated);
      Alert.alert("Saved", "Your POS settings are updated.");
    } catch (e) { Alert.alert("Save failed", formatApiError(e)); }
    finally { setSaving(false); }
  }, [s]);

  if (!s) return <SafeAreaView style={{ flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center" }}><ActivityIndicator color={colors.primary} /></SafeAreaView>;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>POS settings</Text>
      </View>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 120 }}>
          <Text style={styles.sectionLabel}>Business info (on invoice)</Text>
          <Field label="Business name" value={s.business_name} onChangeText={v => setS({ ...s, business_name: v })} />
          <Field label="Address" value={s.business_address} onChangeText={v => setS({ ...s, business_address: v })} multiline />
          <Field label="Phone" value={s.business_phone} onChangeText={v => setS({ ...s, business_phone: v })} keyboardType="phone-pad" />
          <Field label="Email" value={s.business_email} onChangeText={v => setS({ ...s, business_email: v })} keyboardType="email-address" />
          <Field label="GSTIN" value={s.business_gstin} onChangeText={v => setS({ ...s, business_gstin: v })} autoCapitalize="characters" />

          <Text style={styles.sectionLabel}>Invoice numbering</Text>
          <Field label="Prefix (e.g. INV)" value={s.invoice_prefix} onChangeText={v => setS({ ...s, invoice_prefix: (v || "").slice(0, 8).toUpperCase() })} />
          <Field label="Zero-padding width" value={String(s.invoice_pad)} onChangeText={v => setS({ ...s, invoice_pad: Math.max(1, Math.min(10, parseInt(v || "4", 10) || 4)) })} keyboardType="numeric" />

          <Text style={styles.sectionLabel}>Tax defaults</Text>
          <Field label="Default GST %" value={String(s.default_gst_pct ?? 0)} onChangeText={v => setS({ ...s, default_gst_pct: parseFloat(v || "0") })} keyboardType="numeric" />
          <View style={styles.rowBetween}>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowLabel}>Prices include GST by default</Text>
              <Text style={styles.rowHint}>MRP-style — server strips GST out.</Text>
            </View>
            <Switch value={s.gst_inclusive} onValueChange={v => setS({ ...s, gst_inclusive: v })} trackColor={{ true: colors.primary, false: colors.border }} />
          </View>

          <Text style={styles.sectionLabel}>Cash register</Text>
          <Field label="Opening balance (₹)" value={String(s.opening_balance ?? 0)} onChangeText={v => setS({ ...s, opening_balance: parseFloat(v || "0") })} keyboardType="numeric" />
        </ScrollView>
        <View style={styles.footer}>
          <TouchableOpacity onPress={save} disabled={saving} style={[styles.primary, saving && { opacity: 0.5 }]}>
            {saving ? <ActivityIndicator color="#fff" /> : <><Feather name="save" size={16} color="#fff" /><Text style={styles.primaryText}>Save changes</Text></>}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Field(p: { label: string; value: string; onChangeText: (v: string) => void; multiline?: boolean; keyboardType?: any; autoCapitalize?: any }) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.fieldLabel}>{p.label}</Text>
      <TextInput value={p.value} onChangeText={p.onChangeText} placeholderTextColor={colors.textMuted} multiline={p.multiline} keyboardType={p.keyboardType} autoCapitalize={p.autoCapitalize} style={[styles.input, p.multiline && { height: 70 }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { padding: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  sectionLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, textTransform: "uppercase", marginTop: 12, marginBottom: 6 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, color: colors.textMain, backgroundColor: colors.surface },
  rowBetween: { flexDirection: "row", alignItems: "center", padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, marginBottom: 8 },
  rowLabel: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rowHint: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: spacing.screen, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  primary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 14, borderRadius: 12 },
  primaryText: { color: "#fff", fontWeight: "800", fontSize: 15 },
});
