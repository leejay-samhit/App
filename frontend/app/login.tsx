import { useState, useEffect, useRef } from "react";
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
  useWindowDimensions,
} from "react-native";
import { useRouter, Link } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../src/auth";
import { isScopedAdmin } from "../src/admin-roles";
import { useBranding } from "../src/branding";
import { colors, radii, spacing, useResponsiveContainer } from "../src/theme";
import { formatApiError } from "../src/api";
import { GradientCard } from "../src/gradient-card";
import { FestivalStrip } from "../src/festival-decor";
import { GoogleSignInButton } from "../src/google-signin-button";
import { MobileOtpCard } from "../src/mobile-otp-card";
import Animated, { FadeInDown } from "react-native-reanimated";

/** Failed fingerprint scans allowed before the password form opens itself. */
const MAX_BIO_TRIES = 3;

export default function Login() {
  const {
    login,
    setSession,
    sessionEndReason,
    clearSessionEnd,
    biometricAvailable,
    biometricReady,
    biometricEmailHint,
    loginWithBiometric,
    disableBiometric,
  } = useAuth();
  const { app_name, tagline, login_subtitle } = useBranding();
  const router = useRouter();
  const wideColumn = useResponsiveContainer();
  // Small Android phones (≤ 360 dp) get a tighter banner so the three
  // sign-in options stay above the fold without scrolling.
  const { width: screenW } = useWindowDimensions();
  const compact = screenW <= 360;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [bioLoading, setBioLoading] = useState(false);
  const [error, setError] = useState("");
  // Nov-2026 — mobile sign-in with a WhatsApp code.
  // Which sign-in door the user picked: null = show all three options.
  const [method, setMethod] = useState<null | "email" | "otp">(null);
  const [showPassword, setShowPassword] = useState(false);
  // When biometric is enabled the password form is hidden. User can tap
  // "Use a different account" to force-disable biometric and unlock the
  // password fields. Tracked separately from biometricReady so we don't
  // accidentally flicker the UI mid-disable.
  const [forcePassword, setForcePassword] = useState(false);
  // Fingerprint attempt budget — after MAX_BIO_TRIES failed scans the
  // password form is revealed automatically instead of looping the sheet.
  const [bioTries, setBioTries] = useState(0);

  // Auto-prompt fingerprint when the login screen mounts AND the user has
  // previously enabled biometric. We only do this once per mount so it
  // doesn't re-trigger after a user cancels. Skipped on web (no support).
  const autoPromptedRef = useRef(false);
  useEffect(() => {
    if (Platform.OS === "web") return;
    if (!biometricReady) return;
    if (autoPromptedRef.current) return;
    autoPromptedRef.current = true;
    // Fire and forget — onBiometric handles its own loading + errors.
    // The splash overlay is gone (Sep 2026) so the OS biometric sheet can
    // come up on the next frame instead of after a 350ms wait.
    const t = setTimeout(() => { onBiometric(); }, 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [biometricReady]);

  // When biometric is enabled, the password form is hidden by default.
  // Showing it requires explicit "Use a different account" confirmation.
  const showPasswordForm = !biometricReady || forcePassword;

  // Friendly banner shown when the user landed here because their session
  // was ended remotely (signed in on another device, refresh token expired,
  // explicit admin kick, etc.). Reset on next successful login or when
  // dismissed.
  const sessionBanner =
    sessionEndReason === "session_revoked"
      ? "You’ve been signed in on another device. Please log in again."
      : sessionEndReason === "refresh_failed"
      ? "Your session has expired. Please log in again."
      : sessionEndReason === "account_blocked"
      ? "This account is locked and under review. Contact support if you need help."
      : null;

  // Signs the session returned by /auth/otp/verify into the app.
  const applySession = async (data: any) => {
    if (!data?.token || !data?.user) return;
    await setSession(data.token, data.user, data.refresh_token ?? null);
    // A brand-new mobile account still has the placeholder name — ask for the
    // real one once before dropping them into the shop.
    if (data.needs_profile) router.replace("/complete-profile" as any);
    else navigateAfter(data.user);
  };

  const navigateAfter = (u: any) => {
    if (u.role === "admin") router.replace(isScopedAdmin(u) ? "/admin/manager-home" : "/admin/home");
    else if (u.is_delivery_partner_approved) router.replace("/delivery/dashboard" as any);
    // Oct-2026 — a seller's Shop/Services tabs are hidden, so his home is
    // the Vendor panel rather than the buyer-side shop.
    else if (u.is_vendor && u.is_vendor_approved) router.replace("/vendor/dashboard" as any);
    // Nov-2026 — the ₹118 gate is gone. A customer with no mobile number yet
    // verifies it once over WhatsApp; everyone else goes straight to the shop.
    else if (!u.phone) router.replace("/verify-mobile" as any);
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
      setBioTries(0);
      navigateAfter(u);
    } catch (e: any) {
      // 3 scan attempts, then the password form opens by itself so nobody
      // is stuck tapping a fingerprint that won't read (owner request).
      const tries = bioTries + 1;
      setBioTries(tries);
      const left = MAX_BIO_TRIES - tries;
      if (left > 0) {
        setError(`${e?.message || "Fingerprint login failed"} (${left} attempt${left === 1 ? "" : "s"} left)`);
      } else {
        setError(`${e?.message || "Fingerprint didn't work"} — please sign in with your password.`);
        setForcePassword(true);
      }
    } finally {
      setBioLoading(false);
    }
  };

  // "Use a different account" — requires explicit confirmation because it
  // wipes the cached biometric session. After confirmation, the password
  // form replaces the fingerprint UI so the user can sign in as someone
  // else. This is the ONLY in-app path to unlock the password form when
  // biometric is enabled.
  const onUseDifferentAccount = () => {
    Alert.alert(
      "Switch account?",
      "Fingerprint login will be disabled and the saved session for " +
        (biometricEmailHint || "this account") +
        " will be removed from this phone. Continue?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Yes, switch",
          style: "destructive",
          onPress: async () => {
            try {
              await disableBiometric();
              autoPromptedRef.current = true; // don't re-prompt after disable
              setForcePassword(true);
              setError("");
            } catch (e: any) {
              Alert.alert("Could not switch account", e?.message || "Try again");
            }
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
      >
        <ScrollView contentContainerStyle={[styles.container, wideColumn]} keyboardShouldPersistTaps="handled">
          <Animated.View entering={FadeInDown.duration(400)}>
            <GradientCard variant="emerald" style={[styles.heroBrand, compact && styles.heroBrandCompact]}>
              <View style={styles.brandRow}>
                <View style={styles.logoBox}>
                  <Feather name="git-merge" size={22} color={colors.primary} />
                </View>
                <Text style={[styles.brandText, { color: "#fff" }]} numberOfLines={1}>{app_name}</Text>
              </View>
              <Text style={styles.heroOverline}>WELCOME BACK</Text>
              <Text style={[styles.heroH1, compact && styles.heroH1Compact]} allowFontScaling={false}>
                {login_subtitle}
              </Text>
              <Text style={styles.heroTagline}>{tagline}</Text>
              {/* Festive decoration — nothing renders on the normal theme. */}
              <FestivalStrip compact />
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
          {/* ── Three equal ways in (Nov-2026) ─────────────────────────
              Google, WhatsApp code and email + password all sit together as
              compact choices. Email opens into its form on demand instead of
              dominating the screen. Hidden while the fingerprint card is the
              primary login. */}
          {showPasswordForm ? (
            method === null ? (
              <View style={styles.methodStack}>
                {/* Jun-2027 centre pass — all three options are identical
                    rows with the icon+label centred as one group, the way
                    "Continue with Google" is laid out. Same height, radius,
                    border and spacing on every screen. */}
                <GoogleSignInButton onError={setError} label="Continue with Google" />

                <TouchableOpacity
                  onPress={() => { setError(""); setMethod("otp"); }}
                  style={styles.methodBtn}
                  testID="login-otp-open"
                  activeOpacity={0.85}
                  accessibilityRole="button"
                >
                  <Feather name="message-circle" size={18} color={colors.primary} />
                  <Text style={styles.methodBtnText} numberOfLines={1}>Continue with Mobile Number</Text>
                </TouchableOpacity>

                <TouchableOpacity
                  onPress={() => { setError(""); setMethod("email"); }}
                  style={styles.methodBtn}
                  testID="login-email-open"
                  activeOpacity={0.85}
                  accessibilityRole="button"
                >
                  <Feather name="mail" size={18} color={colors.primary} />
                  <Text style={styles.methodBtnText} numberOfLines={1}>Sign in with Email &amp; Password</Text>
                </TouchableOpacity>

                {error ? <Text style={styles.error} testID="login-error">{error}</Text> : null}
              </View>
            ) : method === "email" ? (
              <View style={styles.methodPanel}>
                <View style={styles.formGroup}>
                  <Text style={styles.label}>Email</Text>
                  <TextInput
                    testID="login-email-input"
                    value={email}
                    onChangeText={setEmail}
                    autoCapitalize="none"
                    autoComplete="email"
                    keyboardType="email-address"
                    placeholder="you@example.com"
                    placeholderTextColor={colors.textMuted}
                    style={styles.input}
                  />
                </View>
                <View style={styles.formGroup}>
                  <Text style={styles.label}>Password</Text>
                  <View style={styles.passwordRow}>
                    <TextInput
                      testID="login-password-input"
                      value={password}
                      onChangeText={setPassword}
                      secureTextEntry={!showPassword}
                      autoComplete="password"
                      placeholder="Your password"
                      placeholderTextColor={colors.textMuted}
                      style={[styles.input, { flex: 1, paddingRight: 46 }]}
                      onSubmitEditing={onSubmit}
                      returnKeyType="go"
                    />
                    <TouchableOpacity
                      onPress={() => setShowPassword((v) => !v)}
                      style={styles.eyeBtn}
                      hitSlop={10}
                      testID="login-password-toggle"
                    >
                      <Feather name={showPassword ? "eye-off" : "eye"} size={18} color={colors.textMuted} />
                    </TouchableOpacity>
                  </View>
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

                <TouchableOpacity
                  onPress={() => { setMethod(null); setError(""); }}
                  style={styles.otpToggleBtn}
                  testID="login-email-close"
                >
                  <Text style={styles.otpToggleText}>Back to all sign-in options</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <View style={styles.methodPanel}>
                <MobileOtpCard
                  mode="login"
                  onVerified={async (data: any) => {
                    await applySession(data);
                  }}
                />
                <TouchableOpacity
                  onPress={() => { setMethod(null); setError(""); }}
                  style={styles.otpToggleBtn}
                  testID="login-otp-close"
                >
                  <Text style={styles.otpToggleText}>Back to all sign-in options</Text>
                </TouchableOpacity>
              </View>
            )
          ) : null}

          {/* Biometric login — when enabled, this is the PRIMARY login. The
              password form is hidden above. User must explicitly tap "Use a
              different account" below to switch accounts. */}
          {biometricReady ? (
            <View style={styles.bioPrimaryCard}>
              <View style={styles.bioIconBig}>
                <Feather name="unlock" size={32} color={colors.primary} />
              </View>
              <Text style={styles.bioPrimaryTitle}>Welcome back</Text>
              {biometricEmailHint ? (
                <Text style={styles.bioPrimarySub}>{biometricEmailHint}</Text>
              ) : null}
              {error ? (
                <Text style={[styles.error, { marginTop: 4 }]} testID="login-error">{error}</Text>
              ) : null}
              <TouchableOpacity
                testID="login-biometric-button"
                style={[styles.bioBtn, bioLoading && { opacity: 0.6 }, { marginTop: 12, alignSelf: "stretch" }]}
                onPress={onBiometric}
                disabled={bioLoading}
              >
                {bioLoading ? (
                  <ActivityIndicator color={colors.primary} size="small" />
                ) : (
                  <>
                    <Feather name="unlock" size={18} color={colors.primary} />
                    <Text style={styles.bioBtnText}>Login with Fingerprint</Text>
                  </>
                )}
              </TouchableOpacity>
              <TouchableOpacity
                onPress={onUseDifferentAccount}
                style={styles.bioSwitchLink}
                testID="login-switch-account"
              >
                <Text style={styles.bioSwitchText}>Use a different account</Text>
              </TouchableOpacity>
            </View>
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

          <View style={styles.legalRow}>
            <Link href={"/legal/terms" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Terms</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/privacy" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Privacy</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/refund" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Refund</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/contact" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>Contact</Text></TouchableOpacity></Link>
            <Text style={styles.muted}> · </Text>
            <Link href={"/legal/about" as any} asChild><TouchableOpacity><Text style={styles.legalLink}>About</Text></TouchableOpacity></Link>
          </View>
          </Animated.View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: {
    padding: spacing.screen, paddingTop: spacing.lg, paddingBottom: 40,
    // Short content (the three sign-in options) sits balanced in the middle
    // of a tall screen instead of leaving a big empty block underneath;
    // taller content (open email form + keyboard) simply scrolls as before.
    flexGrow: 1, justifyContent: "center",
  },
  heroBrand: { padding: 24, marginBottom: 20 },
  heroBrandCompact: { padding: 18, marginBottom: 16 },
  heroOverline: { fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.7)", fontWeight: "700", marginTop: 20 },
  heroH1: { fontSize: 30, fontWeight: "800", color: "#fff", lineHeight: 36, letterSpacing: -0.8, marginTop: 6 },
  heroH1Compact: { fontSize: 25, lineHeight: 30 },
  heroTagline: { fontSize: 13, color: "rgba(255,255,255,0.85)", marginTop: 8, lineHeight: 18 },
  brandRow: { flexDirection: "row", alignItems: "center", minHeight: 38 },
  logoBox: {
    width: 38,
    height: 38,
    borderRadius: 12,
    backgroundColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
    marginRight: 10,
  },
  brandText: {
    flexShrink: 1, fontSize: 18, lineHeight: 22, fontWeight: "800",
    color: colors.textMain, letterSpacing: -0.3,
    ...(Platform.OS === "android" ? { includeFontPadding: false } : null),
  },
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
  methodStack: { gap: 12 },
  methodPanel: { marginTop: 4 },
  // Matches GoogleSignInButton exactly: same height, radius, border,
  // padding, and the icon + label centred as one group.
  methodBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    minHeight: 54, borderRadius: radii.button, paddingHorizontal: 16, paddingVertical: 14,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  methodBtnText: {
    fontSize: 15, fontWeight: "700", color: colors.textMain, letterSpacing: -0.2,
  },
  passwordRow: { flexDirection: "row", alignItems: "center" },
  eyeBtn: { position: "absolute", right: 12, height: 44, width: 32, alignItems: "center", justifyContent: "center" },
  otpBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    minHeight: 50, borderRadius: radii.button, marginTop: 12,
    borderWidth: 1.5, borderColor: colors.primary, backgroundColor: colors.surface,
  },
  otpBtnText: { fontSize: 14.5, fontWeight: "900", color: colors.primary },
  otpToggleBtn: { minHeight: 44, alignItems: "center", justifyContent: "center", marginTop: 4 },
  otpToggleText: { fontSize: 12.5, fontWeight: "800", color: colors.textMuted },

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
  // Prominent fingerprint card shown as the PRIMARY login when biometric
  // is enabled. Hides the password form entirely.
  bioPrimaryCard: {
    marginTop: 24,
    padding: 24,
    borderRadius: radii.card,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
  },
  bioIconBig: {
    width: 64, height: 64, borderRadius: 32,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
    marginBottom: 12,
  },
  bioPrimaryTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  bioPrimarySub: { fontSize: 13, color: colors.textMuted, fontWeight: "700", marginTop: 4 },
  bioSwitchLink: { marginTop: 14, paddingVertical: 8 },
  bioSwitchText: { fontSize: 13, fontWeight: "700", color: colors.textMuted, textDecorationLine: "underline" },
  footerRow: { flexDirection: "row", justifyContent: "center", alignItems: "center", marginTop: 20 },
  legalRow: {
    flexDirection: "row", flexWrap: "wrap", alignItems: "center", justifyContent: "center",
    marginTop: 10, columnGap: 2, rowGap: 4,
  },
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
