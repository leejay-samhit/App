// Phase 3 — Full-screen takeover shown when the backend reports
// `block_level: "hard_block"` (root + Play Integrity FAIL_VERDICT or
// SSL pin mismatch). The user cannot proceed past this screen until they
// switch to a clean device or contact support.
//
// "read_only" block_level is NOT handled here — those users still see the
// full UI and only get rejected when they try a financial action (withdraw
// or pay). That gives them visibility into their balance / history so
// they're not flying blind while resolving the device issue.
import React from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Linking } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { colors, radii, spacing } from "./theme";
import type { IntegrityVerdict } from "./tamper-detection";

const REASON_LABELS: Record<string, string> = {
  "root_jailbreak":  "Device appears to be rooted or jailbroken",
  "play_integrity":  "Google Play Integrity check failed",
  "emulator":        "Running on an emulator / simulator",
  "developer_mode":  "Android developer mode is enabled",
  "ssl_pin":         "Secure connection check failed",
  "apk_signature":   "App package signature is invalid",
};

const _humanReason = (raw: string): string => {
  const [name] = raw.split(":");
  return REASON_LABELS[name] || name;
};

type Props = {
  verdict: IntegrityVerdict;
  onRetry: () => void;
  supportEmail?: string;
};

export default function TamperBlockedScreen({ verdict, onRetry, supportEmail = "support@networkpay.in" }: Props) {
  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.scroll} bounces={false}>
        <View style={styles.iconWrap}>
          <Feather name="shield-off" size={56} color="#B3261E" />
        </View>
        <Text style={styles.title}>Security check failed</Text>
        <Text style={styles.subtitle}>
          We can’t open the app on this device because it didn’t pass our security checks.
          This protects your account and money from being tampered with.
        </Text>

        <View style={styles.card}>
          <Text style={styles.cardLabel}>WHY THIS HAPPENED</Text>
          {verdict.reasons.length > 0 ? verdict.reasons.map((r) => (
            <View key={r} style={styles.reasonRow}>
              <Feather name="alert-octagon" size={14} color="#B3261E" />
              <Text style={styles.reasonText}>{_humanReason(r)}</Text>
            </View>
          )) : (
            <Text style={styles.reasonText}>No specific reason was reported.</Text>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.cardLabel}>WHAT YOU CAN DO</Text>
          <Text style={styles.helpText}>• Use the official app from Google Play / App Store (not a side-loaded APK).</Text>
          <Text style={styles.helpText}>• If your device is rooted / jailbroken, switch to a stock device.</Text>
          <Text style={styles.helpText}>• Disable Android Developer Options if enabled.</Text>
          <Text style={styles.helpText}>• Update your device’s operating system.</Text>
        </View>

        <TouchableOpacity style={styles.primaryBtn} onPress={onRetry} testID="tamper-retry">
          <Feather name="refresh-cw" size={16} color="#fff" />
          <Text style={styles.primaryBtnText}>Try again</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.secondaryBtn}
          onPress={() => Linking.openURL(`mailto:${supportEmail}?subject=Security%20block%20on%20app`)}
          testID="tamper-support"
        >
          <Feather name="mail" size={14} color={colors.primary} />
          <Text style={styles.secondaryBtnText}>Contact support · {supportEmail}</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#FFF7F5" },
  scroll: { padding: spacing.screen, paddingTop: 32, paddingBottom: 40 },
  iconWrap: {
    alignSelf: "center",
    width: 96, height: 96, borderRadius: 48,
    backgroundColor: "#FEE4E2",
    alignItems: "center", justifyContent: "center",
    marginBottom: 18,
  },
  title: { fontSize: 24, fontWeight: "900", color: "#7A271A", textAlign: "center", marginBottom: 10 },
  subtitle: { fontSize: 14, lineHeight: 20, color: "#6B7280", textAlign: "center", marginBottom: 22, paddingHorizontal: 4 },
  card: {
    backgroundColor: "#fff",
    borderRadius: radii.lg,
    borderWidth: 1, borderColor: "#FDE68A",
    padding: 14,
    marginBottom: 14,
  },
  cardLabel: { fontSize: 11, fontWeight: "900", color: "#92400E", letterSpacing: 0.6, marginBottom: 8 },
  reasonRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  reasonText: { flex: 1, fontSize: 13, color: "#7A271A", fontWeight: "600" },
  helpText: { fontSize: 13, color: "#374151", lineHeight: 20, marginVertical: 1 },
  primaryBtn: {
    backgroundColor: "#B3261E",
    paddingVertical: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 8,
  },
  primaryBtnText: { color: "#fff", fontWeight: "900", fontSize: 15 },
  secondaryBtn: {
    paddingVertical: 12, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: 4,
  },
  secondaryBtnText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
});
