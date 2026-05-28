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
import { useRouter, Link, useLocalSearchParams } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";
import { formatApiError } from "../src/api";

export default function Register() {
  const { register } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ ref?: string }>();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [referral, setReferral] = useState((params.ref as string) || "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async () => {
    if (!name || !email || !password) {
      setError("Name, email and password are required");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await register({
        name: name.trim(),
        email: email.trim(),
        password,
        phone: phone.trim() || undefined,
        referral_code: referral.trim() || undefined,
      });
      router.replace("/payment");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="register-back">
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>

          {/* Premium gradient hero — Deep Blue + Purple + Cyan glow (June 2026) */}
          <LinearGradient
            colors={["#0A0E27", "#1E2A78", "#5B21B6"]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.gradHero}
          >
            <View style={styles.gradGlow} pointerEvents="none" />
            <Text style={styles.gradOverline}>JOIN THE NETWORK</Text>
            <Text style={styles.gradH1}>Create your{"\n"}account</Text>
            <Text style={styles.gradSub}>
              Refer 4 friends to unlock recurring rewards.
            </Text>
          </LinearGradient>

          <View style={styles.formGroup}>
            <Text style={styles.label}>Full name</Text>
            <TextInput testID="register-name-input" value={name} onChangeText={setName} placeholder="Rajesh Kumar" placeholderTextColor={colors.textMuted} style={styles.input} />
          </View>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Email</Text>
            <TextInput testID="register-email-input" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="you@example.com" placeholderTextColor={colors.textMuted} style={styles.input} />
          </View>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Phone (optional)</Text>
            <TextInput testID="register-phone-input" value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="+91 98765 43210" placeholderTextColor={colors.textMuted} style={styles.input} />
          </View>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Password</Text>
            <TextInput testID="register-password-input" value={password} onChangeText={setPassword} secureTextEntry placeholder="Min 6 characters" placeholderTextColor={colors.textMuted} style={styles.input} />
          </View>
          <View style={styles.formGroup}>
            <Text style={styles.label}>Referral code (optional)</Text>
            <TextInput testID="register-referral-input" value={referral} onChangeText={(t) => setReferral(t.toUpperCase())} autoCapitalize="characters" placeholder="e.g. ABC123" placeholderTextColor={colors.textMuted} style={styles.input} />
          </View>

          {error ? <Text style={styles.error} testID="register-error">{error}</Text> : null}

          <TouchableOpacity testID="register-submit-button" style={[styles.primaryBtn, loading && { opacity: 0.7 }]} onPress={onSubmit} disabled={loading}>
            {loading ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={styles.primaryBtnText}>Continue to payment</Text>}
          </TouchableOpacity>

          <View style={styles.footerRow}>
            <Text style={styles.muted}>Already have an account?</Text>
            <Link href="/login" asChild>
              <TouchableOpacity testID="go-to-login"><Text style={styles.link}> Sign in</Text></TouchableOpacity>
            </Link>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingTop: 16, paddingBottom: 60 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginBottom: 18 },
  // Premium gradient hero (June 2026)
  gradHero: {
    borderRadius: 24, padding: 22, marginBottom: 22,
    overflow: "hidden", position: "relative",
    shadowColor: "#5B21B6", shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.30, shadowRadius: 28, elevation: 10,
  },
  gradGlow: { position: "absolute", top: -60, right: -40, width: 200, height: 200, borderRadius: 100, backgroundColor: "#06B6D4", opacity: 0.18 },
  gradOverline: { fontSize: 10, fontWeight: "900", color: "#A5F3FC", letterSpacing: 2 },
  gradH1: { fontSize: 32, fontWeight: "900", color: "#fff", letterSpacing: -0.5, marginTop: 10 },
  gradSub: { fontSize: 12, color: "#C7D2FE", marginTop: 6, lineHeight: 18 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 10 },
  h1: { fontSize: 34, fontWeight: "800", color: colors.textMain, lineHeight: 40, letterSpacing: -1 },
  subtitle: { fontSize: 15, color: colors.textMuted, marginTop: 12, marginBottom: 28, lineHeight: 22 },
  formGroup: { marginBottom: 16 },
  label: { fontSize: 12, color: colors.textMuted, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 15, color: colors.textMain },
  primaryBtn: { backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 16, alignItems: "center", marginTop: 12 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 16 },
  footerRow: { flexDirection: "row", justifyContent: "center", marginTop: 24 },
  muted: { color: colors.textMuted, fontSize: 14 },
  link: { color: colors.primary, fontWeight: "700", fontSize: 14 },
  error: { color: "#B3261E", marginBottom: 8, fontSize: 13 },
});
