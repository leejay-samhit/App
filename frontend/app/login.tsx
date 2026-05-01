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
import { useBranding } from "../src/branding";
import { colors, radii, spacing } from "../src/theme";
import { formatApiError } from "../src/api";
import { signInWithGoogle } from "../src/google";
import { GradientCard } from "../src/gradient-card";
import Animated, { FadeInDown } from "react-native-reanimated";

export default function Login() {
  const { login, setSession } = useAuth();
  const { app_name, tagline, login_subtitle } = useBranding();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [error, setError] = useState("");

  const navigateAfter = (u: any) => {
    if (u.role === "admin") router.replace("/admin/home");
    else if (!u.registration_paid) router.replace("/payment");
    else router.replace("/(tabs)/dashboard");
  };

  const onSubmit = async () => {
    if (!email || !password) {
      setError("Please enter email and password");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const u = await login(email.trim(), password);
      navigateAfter(u);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  const onGoogle = async () => {
    setError("");
    setGoogleLoading(true);
    try {
      // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
      const res = await signInWithGoogle();
      if (res.ok && res.token && res.user) {
        await setSession(res.token, res.user);
        navigateAfter(res.user);
      } else if (!res.cancelled) {
        setError(res.error || "Google sign-in failed");
      }
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <Animated.View entering={FadeInDown.duration(400)}>
            <GradientCard variant="emerald" style={styles.heroBrand}>
              <View style={styles.brandRow}>
                <View style={styles.logoBox}>
                  <Feather name="git-merge" size={22} color={colors.primary} />
                </View>
                <Text style={[styles.brandText, { color: "#fff" }]}>{app_name}</Text>
              </View>
              <Text style={styles.heroOverline}>WELCOME BACK</Text>
              <Text style={styles.heroH1}>{login_subtitle}</Text>
              <Text style={styles.heroTagline}>{tagline}</Text>
            </GradientCard>
          </Animated.View>

          <Animated.View entering={FadeInDown.duration(400).delay(120)}>
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

          <View style={styles.dividerRow}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>OR</Text>
            <View style={styles.dividerLine} />
          </View>

          <TouchableOpacity
            testID="login-google-button"
            style={[styles.googleBtn, googleLoading && { opacity: 0.7 }]}
            onPress={onGoogle}
            disabled={googleLoading || loading}
          >
            {googleLoading ? (
              <ActivityIndicator color={colors.textMain} />
            ) : (
              <>
                <View style={styles.googleIcon}>
                  <Text style={styles.googleG}>G</Text>
                </View>
                <Text style={styles.googleBtnText}>Continue with Google</Text>
              </>
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
          </Animated.View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingTop: spacing.lg, paddingBottom: 60 },
  heroBrand: { padding: 28, marginBottom: 28 },
  heroOverline: { fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.7)", fontWeight: "700", marginTop: 28 },
  heroH1: { fontSize: 32, fontWeight: "800", color: "#fff", lineHeight: 38, letterSpacing: -1, marginTop: 8 },
  heroTagline: { fontSize: 13, color: "rgba(255,255,255,0.85)", marginTop: 10, lineHeight: 18 },
  brandRow: { flexDirection: "row", alignItems: "center" },
  logoBox: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
    marginRight: 10,
  },
  brandText: { fontSize: 18, fontWeight: "800", color: colors.textMain, letterSpacing: -0.3 },
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
  dividerRow: { flexDirection: "row", alignItems: "center", marginVertical: 18, gap: 10 },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerText: { fontSize: 11, fontWeight: "700", color: colors.textMuted, letterSpacing: 2 },
  googleBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.button, paddingVertical: 14 },
  googleIcon: { width: 22, height: 22, borderRadius: 11, backgroundColor: "#fff", borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  googleG: { fontSize: 13, fontWeight: "900", color: "#4285F4" },
  googleBtnText: { color: colors.textMain, fontWeight: "700", fontSize: 15 },
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
