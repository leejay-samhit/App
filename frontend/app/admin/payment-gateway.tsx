import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator, Alert, KeyboardAvoidingView, Platform, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type GatewayInfo = {
  key_id: string;
  key_secret_masked: string;
  is_test_mode: boolean;
  is_mock: boolean;
  source: "db" | "env" | "none";
  has_db_override: boolean;
  has_env_fallback: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
};

export default function AdminPaymentGateway() {
  const router = useRouter();
  const [info, setInfo] = useState<GatewayInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [keyId, setKeyId] = useState("");
  const [keySecret, setKeySecret] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<GatewayInfo>("/admin/payment-gateway");
      setInfo(data);
    } catch (e) {
      Alert.alert("Couldn't load", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onSave = async () => {
    if (!keyId.trim() || !keySecret.trim()) {
      Alert.alert("Missing fields", "Please enter both Key ID and Key Secret.");
      return;
    }
    setSaving(true);
    setTestResult(null);
    try {
      await api.put("/admin/payment-gateway", { key_id: keyId.trim(), key_secret: keySecret.trim() });
      Alert.alert("Saved", "Razorpay credentials updated and verified.");
      setKeyId(""); setKeySecret(""); setShowSecret(false);
      await load();
    } catch (e) {
      Alert.alert("Couldn't save", formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await api.post<{ ok: boolean; order_id?: string; status?: string; error?: string }>("/admin/payment-gateway/test");
      if (data.ok) setTestResult({ ok: true, msg: `Razorpay reached. Test order ${data.order_id} (${data.status}).` });
      else setTestResult({ ok: false, msg: data.error || "Razorpay rejected the request." });
    } catch (e) {
      setTestResult({ ok: false, msg: formatApiError(e) });
    } finally {
      setTesting(false);
    }
  };

  const onReset = () => {
    Alert.alert("Reset to .env credentials?", "This clears the keys saved here and falls back to environment configuration. App will not lose payments already processed.", [
      { text: "Cancel", style: "cancel" },
      { text: "Reset", style: "destructive", onPress: async () => {
        setResetting(true);
        try {
          await api.delete("/admin/payment-gateway");
          await load();
        } catch (e) { Alert.alert("Couldn't reset", formatApiError(e)); }
        finally { setResetting(false); }
      }},
    ]);
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View></SafeAreaView>;
  }

  const isLive = info && !info.is_mock;
  const sourceLabel = info?.source === "db" ? "From admin panel" : info?.source === "env" ? "From .env file" : "Not configured (mock mode)";
  const sourceColor = info?.source === "db" ? "#1F6B44" : info?.source === "env" ? "#1F5E9E" : "#7A4A0E";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="paygw-back">
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>Payment Gateway</Text>
          <View style={{ width: 40 }} />
        </View>
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          {/* Status card */}
          <View style={[styles.statusCard, { backgroundColor: isLive ? "#E6F4EE" : "#FFF4E5" }]}>
            <MaterialCommunityIcons name={isLive ? "check-decagram" : "alert-circle"} size={28} color={isLive ? "#1F6B44" : "#7A4A0E"} />
            <View style={{ flex: 1, marginLeft: 12 }}>
              <Text style={[styles.statusTitle, { color: isLive ? "#1F6B44" : "#7A4A0E" }]}>
                {isLive ? (info?.is_test_mode ? "Live (Test Mode)" : "Live (Production)") : "Mock mode"}
              </Text>
              <Text style={styles.statusBody}>
                {isLive
                  ? `Razorpay is processing real ${info?.is_test_mode ? "test" : "live"} payments through these keys.`
                  : "No keys configured. Payments are simulated."}
              </Text>
            </View>
          </View>

          {/* Current configuration */}
          <Text style={styles.sectionLabel}>CURRENT CONFIGURATION</Text>
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Source</Text>
              <Text style={[styles.rowValue, { color: sourceColor, fontWeight: "800" }]}>{sourceLabel}</Text>
            </View>
            <View style={styles.divider} />
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Key ID</Text>
              <Text style={styles.rowValueMono} numberOfLines={1}>{info?.key_id || "—"}</Text>
            </View>
            <View style={styles.divider} />
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Key Secret</Text>
              <Text style={styles.rowValueMono}>{info?.key_secret_masked || "—"}</Text>
            </View>
            {info?.updated_at && (
              <>
                <View style={styles.divider} />
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Last updated</Text>
                  <Text style={styles.rowValue} numberOfLines={1}>{new Date(info.updated_at).toLocaleString()}</Text>
                </View>
                {info?.updated_by ? (
                  <>
                    <View style={styles.divider} />
                    <View style={styles.row}>
                      <Text style={styles.rowLabel}>By</Text>
                      <Text style={styles.rowValue} numberOfLines={1}>{info.updated_by}</Text>
                    </View>
                  </>
                ) : null}
              </>
            )}
          </View>

          {/* Test connection */}
          <TouchableOpacity onPress={onTest} disabled={testing || info?.is_mock} style={[styles.secondaryBtn, (testing || info?.is_mock) && { opacity: 0.6 }]} testID="paygw-test">
            {testing ? <ActivityIndicator color={colors.primary} /> : <><Feather name="zap" size={16} color={colors.primary} /><Text style={styles.secondaryBtnText}>  Test connection</Text></>}
          </TouchableOpacity>
          {testResult && (
            <View style={[styles.testResult, { backgroundColor: testResult.ok ? "#E6F4EE" : "#FCE9E5" }]}>
              <Feather name={testResult.ok ? "check-circle" : "x-circle"} size={16} color={testResult.ok ? "#1F6B44" : "#B3261E"} />
              <Text style={[styles.testResultText, { color: testResult.ok ? "#1F6B44" : "#B3261E" }]}>{testResult.msg}</Text>
            </View>
          )}

          {/* Update form */}
          <Text style={styles.sectionLabel}>UPDATE CREDENTIALS</Text>
          <Text style={styles.helper}>Get your keys from Razorpay Dashboard → Account & Settings → API Keys. Use rzp_test_… for testing or rzp_live_… for production.</Text>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Key ID</Text>
            <TextInput
              style={styles.input}
              value={keyId}
              onChangeText={setKeyId}
              placeholder="rzp_test_xxxxxxxxxxxxxx"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="none"
              autoCorrect={false}
              testID="paygw-key-id"
            />
          </View>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Key Secret</Text>
            <View style={{ position: "relative" }}>
              <TextInput
                style={[styles.input, { paddingRight: 48 }]}
                value={keySecret}
                onChangeText={setKeySecret}
                placeholder="Enter the secret shown on Razorpay dashboard"
                placeholderTextColor={colors.textMuted}
                secureTextEntry={!showSecret}
                autoCapitalize="none"
                autoCorrect={false}
                testID="paygw-key-secret"
              />
              <TouchableOpacity onPress={() => setShowSecret((v) => !v)} style={styles.eyeBtn} testID="paygw-toggle-secret">
                <Feather name={showSecret ? "eye-off" : "eye"} size={18} color={colors.textMuted} />
              </TouchableOpacity>
            </View>
          </View>

          <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.primaryBtn, saving && { opacity: 0.7 }]} testID="paygw-save">
            {saving ? <ActivityIndicator color={colors.primaryFg} /> : <><Feather name="save" size={16} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Save &amp; Verify</Text></>}
          </TouchableOpacity>

          {info?.has_db_override && (
            <TouchableOpacity onPress={onReset} disabled={resetting} style={[styles.dangerBtn, resetting && { opacity: 0.6 }]} testID="paygw-reset">
              {resetting ? <ActivityIndicator color="#B3261E" /> : <><Feather name="rotate-ccw" size={16} color="#B3261E" /><Text style={styles.dangerBtnText}>  Reset to .env keys</Text></>}
            </TouchableOpacity>
          )}

          <Text style={styles.note}>🔒 The Key Secret is stored encrypted-at-rest in the database. Only super admins can read or change these credentials.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  statusCard: { flexDirection: "row", alignItems: "center", borderRadius: radii.card, padding: 16, marginBottom: 24 },
  statusTitle: { fontSize: 16, fontWeight: "800" },
  statusBody: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  sectionLabel: { fontSize: 11, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 8, marginBottom: 8 },
  helper: { fontSize: 12, color: colors.textMuted, marginBottom: 12, lineHeight: 18 },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 16 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 6 },
  rowLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  rowValue: { fontSize: 13, color: colors.textMain, maxWidth: "60%", textAlign: "right" },
  rowValueMono: { fontSize: 13, color: colors.textMain, fontWeight: "700", letterSpacing: 0.5, maxWidth: "60%", textAlign: "right" },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 4 },
  formGroup: { marginBottom: 14 },
  label: { fontSize: 12, color: colors.textMuted, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 14, color: colors.textMain },
  eyeBtn: { position: "absolute", right: 8, top: 0, bottom: 0, width: 40, alignItems: "center", justifyContent: "center" },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 15, marginTop: 8 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  secondaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.primary, borderRadius: radii.button, paddingVertical: 13, marginBottom: 12 },
  secondaryBtnText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  dangerBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "#B3261E", borderRadius: radii.button, paddingVertical: 13, marginTop: 10 },
  dangerBtnText: { color: "#B3261E", fontWeight: "800", fontSize: 13 },
  testResult: { flexDirection: "row", alignItems: "center", padding: 10, borderRadius: 10, marginBottom: 12, gap: 8 },
  testResultText: { fontSize: 12, fontWeight: "600", flex: 1 },
  note: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 24, lineHeight: 16 },
});
