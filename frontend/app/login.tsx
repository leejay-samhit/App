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
} from "react-native";
import { useRouter, Link } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../src/auth";
import { useBranding } from "../src/branding";
import { colors, radii, spacing } from "../src/theme";
import { formatApiError } from "../src/api";
import { GradientCard } from "../src/gradient-card";
import Animated, { FadeInDown } from "react-native-reanimated";

export default function Login() {
  const {
    login,
    sessionEndReason,
    clearSessionEnd,
    biometricAvailable,
    biometricReady,
    biometricEmailHint,
    loginWithBiometric,
  } = useAuth();
  const { app_name, tagline, login_subtitle } = useBranding();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [bioLoading, setBioLoading] = useState(false);
  const [error, setError] = useState("");

  // Friendly banner shown when the user landed here because their session
  // was ended remotely (signed in on another device, refresh token expired,
  // explicit admin kick, etc.). Reset on next successful login or when
  // dismissed.
  const sessionBanner =
    sessionEndReason === "session_revoked"
      ? "You’ve been signed in on another device. Please log in again."
      : sessionEndReason === "refresh_failed"
      ? "Your session has expired. Please log in again."
      : null;

  const navigateAfter = (u: any) => {
    if (u.role === "admin") router.replace("/admin/home");
    else if (!u.registration_paid) router.replace("/payment");
    // Approved customers land directly on the Shop tab so they can start
    // browsing immediately. Dashboard is one tap away via the bottom nav.
    else router.replace("/(tabs)/shop");
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

  const onBiometric = async () => {
    setError("");
    setBioLoading(true);
    try {
      const u = await loginWithBiometric();
      navigateAfter(u);
    } catch (e: any) {
      setError(e?.message || "Fingerprint login failed");
    } finally {
      setBioLoading(false);
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
          {sessionBanner ? (
            <View style={styles.sessionBanner} testID="session-end-banner">
              <Feather name="info" size={16} color="#92400E" />
              <Text style={styles.sessionBannerText} numberOfLines={2}>{sessionBanner}</Text>
              <TouchableOpacity
                onPress={clearSessionEnd}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                testID="session-end-banner-dismiss"
              >
                <Feather name="x" size={16} color="#92400E" />
              </TouchableOpacity>
            </View>
          ) : null}
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

          {/* Biometric login — only rendered on devices that support it AND
              where the user previously opted in. Falls back gracefully on
              web / unsupported devices. */}
          {biometricReady ? (
            <>
              <View style={styles.bioDivider}>
                <View style={styles.bioLine} />
                <Text style={styles.bioDividerText}>or</Text>
                <View style={styles.bioLine} />
              </View>
              <TouchableOpacity
                testID="login-biometric-button"
                style={[styles.bioBtn, bioLoading && { opacity: 0.6 }]}
                onPress={onBiometric}
                disabled={bioLoading || loading}
              >
                {bioLoading ? (
                  <ActivityIndicator color={colors.primary} size="small" />
                ) : (
                  <>
                    <Feather name="unlock" size={18} color={colors.primary} />
                    <Text style={styles.bioBtnText}>
                      Login with Fingerprint
                    </Text>
                  </>
                )}
              </TouchableOpacity>
              {biometricEmailHint ? (
                <Text style={styles.bioHint}>Welcome back, {biometricEmailHint}</Text>
              ) : null}
            </>
          ) : biometricAvailable ? (
            <Text style={styles.bioEnableHint}>
              Tip: After login, enable Fingerprint from Profile for faster
              access next time.
            </Text>
          ) : null}

          <View style={styles.footerRow}>
            <Text style={styles.muted}>New here?</Text>
            <Link href="/register" asChild>
              <TouchableOpacity testID="go-to-register">
                <Text style={styles.link}> Create an account</Text>
              </TouchableOpacity>
            </Link>
          </View>

          <View style={[styles.footerRow, { marginTop: 8, flexWrap: "wrap", justifyContent: "center" }]}>
            <Link href={"/legal/terms" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Terms</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/privacy" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Privacy</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/refund" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Refund</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/contact" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Contact</Text></TouchableOpacity></Link>
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
  // Biometric ("Login with Fingerprint") UI
  bioDivider: { flexDirection: "row", alignItems: "center", marginTop: 16, marginBottom: 6 },
  bioLine: { flex: 1, height: 1, backgroundColor: colors.border },
  bioDividerText: { marginHorizontal: 12, fontSize: 12, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.5 },
  bioBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.primary,
    borderRadius: radii.button,
    paddingVertical: 14,
    marginTop: 6,
  },
  bioBtnText: { color: colors.primary, fontWeight: "800", fontSize: 15, letterSpacing: 0.3 },
  bioHint: { fontSize: 12, color: colors.textMuted, textAlign: "center", marginTop: 8 },
  bioEnableHint: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 14, lineHeight: 16, fontStyle: "italic" },
  footerRow: { flexDirection: "row", justifyContent: "center", marginTop: 24 },
  muted: { color: colors.textMuted, fontSize: 14 },
  link: { color: colors.primary, fontWeight: "700", fontSize: 14 },
  legalLink: { color: colors.textMuted, fontSize: 12, fontWeight: "600", textDecorationLine: "underline" },
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
  // Phase 1 Session B — banner shown when the user was kicked out involuntarily
  // (signed in on another device, refresh expired, etc.). Amber warning style.
  sessionBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: "#FEF3C7",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginBottom: 14,
  },
  sessionBannerText: { flex: 1, fontSize: 12.5, color: "#92400E", fontWeight: "600", lineHeight: 17 },
});
