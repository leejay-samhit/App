/**
 * Change my mobile number (Nov-2026).
 *
 * The new number is only saved once a WhatsApp code proves the person holds
 * it. The account id never changes, so wallet, orders, KYC and chat history
 * all stay exactly where they are.
 */
import { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

export default function ChangeMobileScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth() as any;
  const [step, setStep] = useState<"number" | "code">("number");
  const [mobile, setMobile] = useState("");
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const current = (user as any)?.phone || "";

  const sendCode = async () => {
    const digits = mobile.replace(/\D/g, "").slice(-10);
    if (digits.length !== 10) {
      setError("Enter your 10-digit mobile number.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.post("/me/mobile/change/send-otp", { mobile: digits });
      setMobile(digits);
      setStep("code");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (otp.trim().length < 4) {
      setError("Enter the code from WhatsApp.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.post("/me/mobile/change/verify", { mobile, otp: otp.trim() });
      await refresh?.();
      Alert.alert("Number updated", `Your mobile number is now ${mobile}.`, [
        { text: "Done", onPress: () => router.back() },
      ]);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={10} testID="change-mobile-back">
          <Feather name="arrow-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Mobile number</Text>
        <View style={{ width: 40 }} />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.currentCard}>
            <Feather name="smartphone" size={18} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.currentLabel}>Registered number</Text>
              <Text style={styles.currentValue}>{current ? `+91 ${current}` : "Not set yet"}</Text>
            </View>
            {(user as any)?.phone_verified ? (
              <View style={styles.verifiedPill}>
                <Text style={styles.verifiedPillText}>VERIFIED</Text>
              </View>
            ) : null}
          </View>

          {step === "number" ? (
            <>
              <Text style={styles.label}>New mobile number</Text>
              <View style={styles.inputRow}>
                <Text style={styles.prefix}>+91</Text>
                <TextInput
                  value={mobile}
                  onChangeText={(v) => { setMobile(v.replace(/\D/g, "").slice(0, 10)); setError(""); }}
                  placeholder="10-digit number"
                  placeholderTextColor={colors.textMuted}
                  keyboardType="number-pad"
                  maxLength={10}
                  style={styles.input}
                  testID="change-mobile-input"
                />
              </View>
              <Text style={styles.hint}>
                We send a 6-digit code to this number on WhatsApp. Your wallet, orders and
                chats stay on this same account.
              </Text>
              {error ? <Text style={styles.error}>{error}</Text> : null}
              <TouchableOpacity
                onPress={sendCode}
                disabled={busy}
                style={[styles.primaryBtn, busy && { opacity: 0.6 }]}
                testID="change-mobile-send"
              >
                {busy ? <ActivityIndicator color={colors.primaryFg} /> : (
                  <Text style={styles.primaryBtnText}>Send code on WhatsApp</Text>
                )}
              </TouchableOpacity>
            </>
          ) : (
            <>
              <Text style={styles.label}>Enter the code sent to +91 {mobile}</Text>
              <TextInput
                value={otp}
                onChangeText={(v) => { setOtp(v.replace(/\D/g, "").slice(0, 6)); setError(""); }}
                placeholder="6-digit code"
                placeholderTextColor={colors.textMuted}
                keyboardType="number-pad"
                maxLength={6}
                style={[styles.input, styles.otpInput]}
                testID="change-mobile-otp"
              />
              {error ? <Text style={styles.error}>{error}</Text> : null}
              <TouchableOpacity
                onPress={verify}
                disabled={busy}
                style={[styles.primaryBtn, busy && { opacity: 0.6 }]}
                testID="change-mobile-verify"
              >
                {busy ? <ActivityIndicator color={colors.primaryFg} /> : (
                  <Text style={styles.primaryBtnText}>Verify and save</Text>
                )}
              </TouchableOpacity>
              <TouchableOpacity onPress={() => { setStep("number"); setOtp(""); setError(""); }} style={styles.linkBtn}>
                <Text style={styles.linkText}>Use a different number</Text>
              </TouchableOpacity>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  container: { padding: spacing.screen, gap: 12 },
  currentCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surface, borderRadius: radii.card, padding: 16,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
  },
  currentLabel: { fontSize: 11, letterSpacing: 1, color: colors.textMuted, fontWeight: "700" },
  currentValue: { fontSize: 16, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  verifiedPill: { backgroundColor: colors.surfaceMuted, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  verifiedPillText: { fontSize: 9, fontWeight: "900", color: colors.success, letterSpacing: 0.6 },
  label: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginTop: 8 },
  inputRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  prefix: {
    fontSize: 16, fontWeight: "800", color: colors.textMain,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 12, paddingVertical: 14,
    borderRadius: radii.input,
  },
  input: {
    flex: 1, backgroundColor: colors.surface, borderRadius: radii.input,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
    paddingHorizontal: 14, paddingVertical: 14, fontSize: 16,
    color: colors.textMain, minHeight: 48,
  },
  otpInput: { letterSpacing: 8, textAlign: "center", fontWeight: "800" },
  hint: { fontSize: 12, color: colors.textMuted, lineHeight: 18 },
  error: { fontSize: 12, color: colors.error, fontWeight: "600" },
  primaryBtn: {
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 15, alignItems: "center", marginTop: 8, minHeight: 48,
    justifyContent: "center",
  },
  primaryBtnText: { color: colors.primaryFg, fontSize: 15, fontWeight: "800" },
  linkBtn: { alignItems: "center", paddingVertical: 12 },
  linkText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
});
