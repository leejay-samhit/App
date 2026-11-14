/**
 * /payment — kept only as a redirect (Nov-2026).
 *
 * The ₹118 registration/membership screen is gone: joining Slangcart is free
 * and no role application asks for money. Old deep links, notifications and
 * saved shortcuts that still point here land on the mobile-number
 * verification step instead (or straight on the shop if that's already done).
 *
 * Historical ₹118 receipts are untouched and still visible in the wallet
 * transaction history.
 */
import React, { useEffect } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "../src/auth";
import { colors, spacing } from "../src/theme";

export default function RegistrationPaymentRedirect() {
  const router = useRouter();
  const { user } = useAuth();

  useEffect(() => {
    const t = setTimeout(() => {
      if (!user) router.replace("/login");
      else if (!user.phone) router.replace("/verify-mobile" as any);
      else router.replace("/(tabs)/shop");
    }, 350);
    return () => clearTimeout(t);
  }, [user, router]);

  return (
    <View style={styles.wrap} testID="payment-redirect">
      <ActivityIndicator size="small" color={colors.primary} />
      <Text style={styles.text}>Slangcart is free to join — taking you in…</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1, alignItems: "center", justifyContent: "center",
    gap: 12, padding: spacing.screen, backgroundColor: colors.background,
  },
  text: { fontSize: 13.5, fontWeight: "700", color: colors.textMuted, textAlign: "center" },
});
