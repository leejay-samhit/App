import { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
  Alert,
} from "react-native";
import { useRouter, Link } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";
import { formatApiError } from "../src/api";

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async () => {
    if (!email || !password) {
      setError("Please enter email and password");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const u = await login(email.trim(), password);
      if (u.role === "admin") router.replace("/admin/users");
      else if (!u.registration_paid) router.replace("/payment");
      else router.replace("/(tabs)/dashboard");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.brandRow}>
            <View style={styles.logoBox}>
              <Feather name="git-merge" size={22} color={colors.primaryFg} />
            </View>
            <Text style={styles.brandText}>NetworkPay</Text>
          </View>

          <Text style={styles.overline}>WELCOME BACK</Text>
          <Text style={styles.h1}>Sign in to{"\n"}your network</Text>
          <Text style={styles.subtitle}>
            Track your referrals, earnings and grow your team.
          </Text>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Email</Text>
            <TextInput
              testID="login-email-input"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
              placeholder="you@example.com"
              placeholderTextColor={colors.textMuted}
              style={styles.input}
            />
          </View>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Password</Text>
            <TextInput
              testID="login-password-input"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              placeholder="Your password"
              placeholderTextColor={colors.textMuted}
              style={styles.input}
            />
          </View>

          {error ? <Text style={styles.error} testID="login-error">{error}</Text> : null}

          <TouchableOpacity
            testID="login-submit-button"
            style={[styles.primaryBtn, loading && { opacity: 0.7 }]}
            onPress={onSubmit}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color={colors.primaryFg} />
            ) : (
              <Text style={styles.primaryBtnText}>Sign in</Text>
            )}
          </TouchableOpacity>

          <View style={styles.footerRow}>
            <Text style={styles.muted}>New here?</Text>
            <Link href="/register" asChild>
              <TouchableOpacity testID="go-to-register">
                <Text style={styles.link}> Create an account</Text>
              </TouchableOpacity>
            </Link>
          </View>

          <View style={styles.helperBox}>
            <Feather name="info" size={14} color={colors.textMuted} />
            <Text style={styles.helperText}>
              Admin demo: admin@app.com / Admin@123
            </Text>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingTop: spacing.lg, paddingBottom: 60 },
  brandRow: { flexDirection: "row", alignItems: "center", marginBottom: 40 },
  logoBox: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 10,
  },
  brandText: { fontSize: 18, fontWeight: "700", color: colors.textMain, letterSpacing: -0.3 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  h1: { fontSize: 36, fontWeight: "800", color: colors.textMain, lineHeight: 42, letterSpacing: -1 },
  subtitle: { fontSize: 15, color: colors.textMuted, marginTop: 12, marginBottom: 32, lineHeight: 22 },
  formGroup: { marginBottom: 18 },
  label: { fontSize: 12, color: colors.textMuted, marginBottom: 6, fontWeight: "600" },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.input,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 15,
    color: colors.textMain,
  },
  primaryBtn: {
    backgroundColor: colors.primary,
    borderRadius: radii.button,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 12,
  },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 16 },
  footerRow: { flexDirection: "row", justifyContent: "center", marginTop: 24 },
  muted: { color: colors.textMuted, fontSize: 14 },
  link: { color: colors.primary, fontWeight: "700", fontSize: 14 },
  error: { color: "#B3261E", marginBottom: 8, fontSize: 13 },
  helperBox: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceMuted,
    padding: 12,
    borderRadius: 12,
    marginTop: 24,
    gap: 8,
  },
  helperText: { color: colors.textMuted, fontSize: 12 },
});
