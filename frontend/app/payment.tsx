import { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Image } from "react-native";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";

export default function Payment() {
  const { user, refresh, logout } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onPay = async () => {
    setError("");
    setLoading(true);
    try {
      // Simulate UPI flow with delay
      await new Promise((r) => setTimeout(r, 1200));
      await api.post("/payment/register-fee");
      await refresh();
      router.replace("/(tabs)/dashboard");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.container}>
        <View style={styles.topRow}>
          <TouchableOpacity onPress={logout} style={styles.iconBtn} testID="payment-logout">
            <Feather name="log-out" size={18} color={colors.textMain} />
          </TouchableOpacity>
        </View>

        <View style={styles.content}>
          <Image
            source={{ uri: "https://images.pexels.com/photos/5849577/pexels-photo-5849577.jpeg" }}
            style={styles.hero}
          />
          <Text style={styles.overline}>ACTIVATION</Text>
          <Text style={styles.h1}>One-time{"\n"}registration fee</Text>
          <Text style={styles.subtitle}>
            Activate your referral code & start earning ₹400 per 4 successful referrals.
          </Text>

          <View style={styles.amountCard}>
            <Text style={styles.amountLabel}>AMOUNT TO PAY</Text>
            <Text style={styles.amount}>{formatINR(100)}</Text>
            <View style={styles.divider} />
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Account</Text>
              <Text style={styles.rowValue}>{user?.email}</Text>
            </View>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Your code</Text>
              <Text style={styles.rowValueMono}>{user?.referral_code}</Text>
            </View>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Method</Text>
              <Text style={styles.rowValue}>UPI · Mocked</Text>
            </View>
          </View>

          {error ? <Text style={styles.error} testID="payment-error">{error}</Text> : null}

          <TouchableOpacity
            testID="payment-pay-button"
            onPress={onPay}
            disabled={loading}
            style={[styles.payBtn, loading && { opacity: 0.7 }]}
          >
            {loading ? (
              <ActivityIndicator color={colors.accentFg} />
            ) : (
              <>
                <Feather name="zap" size={18} color={colors.accentFg} />
                <Text style={styles.payBtnText}> Pay {formatINR(100)} via UPI</Text>
              </>
            )}
          </TouchableOpacity>

          <Text style={styles.note}>
            This is a simulated payment for the MVP. No real charge will occur.
          </Text>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { flex: 1, padding: spacing.screen },
  topRow: { flexDirection: "row", justifyContent: "flex-end", marginBottom: 16 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  content: { flex: 1 },
  hero: { width: "100%", height: 160, borderRadius: 20, marginBottom: 24 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.accent, fontWeight: "700", marginBottom: 10 },
  h1: { fontSize: 32, fontWeight: "800", color: colors.textMain, lineHeight: 38, letterSpacing: -1 },
  subtitle: { fontSize: 15, color: colors.textMuted, marginTop: 12, marginBottom: 24, lineHeight: 22 },
  amountCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 24, marginBottom: 20 },
  amountLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  amount: { fontSize: 44, fontWeight: "800", color: colors.primary, marginTop: 8, letterSpacing: -1.5 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 16 },
  row: { flexDirection: "row", justifyContent: "space-between", marginVertical: 4 },
  rowLabel: { color: colors.textMuted, fontSize: 13 },
  rowValue: { color: colors.textMain, fontSize: 13, fontWeight: "600" },
  rowValueMono: { color: colors.textMain, fontSize: 13, fontWeight: "700", letterSpacing: 1 },
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.accent, borderRadius: radii.button, paddingVertical: 16, marginTop: 8 },
  payBtnText: { color: colors.accentFg, fontWeight: "700", fontSize: 16 },
  note: { textAlign: "center", color: colors.textMuted, fontSize: 12, marginTop: 16 },
  error: { color: "#B3261E", marginBottom: 8, fontSize: 13, textAlign: "center" },
});
