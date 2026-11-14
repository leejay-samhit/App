/**
 * Verify your mobile number (Nov-2026).
 *
 * Replaces the old /payment screen in the sign-up path. A Google or email
 * account with no mobile number yet lands here once; the number is proven
 * with a WhatsApp code and the shop opens. There is NO fee, no membership and
 * no invite code anywhere in this flow.
 */
import React, { useEffect } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { MobileOtpCard } from "../src/mobile-otp-card";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

export default function VerifyMobileScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();

  useEffect(() => {
    // Already verified (or arrived by a stale link) — don't make them repeat it.
    if (user?.phone) router.replace("/(tabs)/shop");
  }, [user?.phone, router]);

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
        <View style={styles.hero}>
          <View style={styles.heroIcon}>
            <Feather name="smartphone" size={22} color={colors.primary} />
          </View>
          <Text style={styles.heroTitle}>One last step</Text>
          <Text style={styles.heroSub}>
            Add the mobile number your orders and deliveries will use. We verify it with a
            WhatsApp code so nobody else can claim it.
          </Text>
        </View>

        <MobileOtpCard
          mode="gate"
          onVerified={async () => {
            await refresh();
            router.replace("/(tabs)/shop");
          }}
        />

        <View style={styles.reassure}>
          <Feather name="shield" size={14} color={colors.success} />
          <Text style={styles.reassureText}>
            Free to join — no registration fee and no membership needed.
          </Text>
        </View>

        <TouchableOpacity
          onPress={() => router.replace("/(tabs)/shop")}
          style={styles.skipBtn}
          testID="verify-mobile-skip"
        >
          <Text style={styles.skipText}>I&apos;ll do this later</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  body: { padding: spacing.screen, gap: 16, paddingBottom: 48 },
  hero: { gap: 8, paddingTop: 12 },
  heroIcon: {
    width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.brand100,
  },
  heroTitle: { fontSize: 24, fontWeight: "900", color: colors.textMain },
  heroSub: { fontSize: 13.5, color: colors.textMuted, lineHeight: 20 },
  reassure: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: radii.button, padding: 12,
  },
  reassureText: { flex: 1, fontSize: 12.5, color: colors.textMain, fontWeight: "700" },
  skipBtn: { minHeight: 44, alignItems: "center", justifyContent: "center" },
  skipText: { fontSize: 13, fontWeight: "800", color: colors.textMuted },
});
