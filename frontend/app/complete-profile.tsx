/**
 * Tell us your name — shown once, right after a brand-new mobile sign-in.
 *
 * Nov-2026. A mobile-only account starts with a placeholder name ("Slangcart
 * 1234"), so this collects the real name (and an optional email) before the
 * shop opens. No payment, no invite code.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

export default function CompleteProfileScreen() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    if (name.trim().length < 2 || busy) return;
    setBusy(true); setError("");
    try {
      await api.post("/auth/otp/complete-profile", {
        name: name.trim(),
        email: email.trim() || undefined,
      });
      await refresh();
      router.replace("/(tabs)/shop");
    } catch (e) {
      setError(formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        <View style={styles.iconWrap}>
          <Feather name="user" size={22} color={colors.primary} />
        </View>
        <Text style={styles.title}>What should we call you?</Text>
        <Text style={styles.sub}>
          Your number is verified. Add your name so vendors and delivery partners know who to
          look for.
        </Text>

        <View style={styles.field}>
          <Text style={styles.label}>Full name</Text>
          <TextInput
            value={name}
            onChangeText={(t) => { setName(t); setError(""); }}
            placeholder="e.g. Ravi Kumar"
            placeholderTextColor={colors.textMuted}
            style={styles.input}
            testID="profile-name-input"
            autoFocus
          />
        </View>
        <View style={styles.field}>
          <Text style={styles.label}>Email (optional)</Text>
          <TextInput
            value={email}
            onChangeText={(t) => { setEmail(t); setError(""); }}
            placeholder="you@example.com"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            keyboardType="email-address"
            style={styles.input}
            testID="profile-email-input"
          />
        </View>

        {error ? <Text style={styles.error} testID="profile-error">{error}</Text> : null}

        <TouchableOpacity
          onPress={save}
          disabled={name.trim().length < 2 || busy}
          style={[styles.primaryBtn, (name.trim().length < 2 || busy) && { opacity: 0.5 }]}
          testID="profile-save-btn"
          activeOpacity={0.85}
        >
          {busy ? <ActivityIndicator size="small" color={colors.primaryFg} />
            : <Text style={styles.primaryBtnText}>Start shopping</Text>}
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  body: { padding: spacing.screen, gap: 14, paddingBottom: 48 },
  iconWrap: {
    width: 48, height: 48, borderRadius: 24, marginTop: 12,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.brand100,
  },
  title: { fontSize: 24, fontWeight: "900", color: colors.textMain },
  sub: { fontSize: 13.5, color: colors.textMuted, lineHeight: 20 },
  field: { gap: 6 },
  label: { fontSize: 12, fontWeight: "800", color: colors.textMuted },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    backgroundColor: colors.surface, paddingHorizontal: 14, minHeight: 50,
    fontSize: 15, color: colors.textMain,
  },
  error: { fontSize: 12.5, color: colors.error, fontWeight: "700" },
  primaryBtn: {
    backgroundColor: colors.primary, borderRadius: radii.button, minHeight: 50,
    alignItems: "center", justifyContent: "center", marginTop: 4,
  },
  primaryBtnText: { color: colors.primaryFg, fontSize: 15, fontWeight: "900" },
});
