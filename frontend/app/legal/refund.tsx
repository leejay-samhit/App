import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../../src/branding";
import { colors, spacing } from "../../src/theme";

export default function Refund() {
  const router = useRouter();
  const b = useBranding();
  const name = b.business_name || b.app_name;
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Refund & Cancellation</Text>
      </View>
      <ScrollView contentContainerStyle={styles.container}>

        <Text style={styles.p}>Last updated: 1 May 2026. This policy governs refunds and cancellations for all purchases made on {name}.</Text>

        <Text style={styles.h2}>1. Registration fee</Text>
        <Text style={styles.p}>The one-time registration fee unlocks access to the platform, the wallet, and the referral programme. Because this fee is used to provision your account immediately, it is <Text style={{ fontWeight: "800" }}>non-refundable</Text> once your account is activated. If your registration is rejected by our finance team during review, the full amount is refunded to the source account within 5–7 working days.</Text>

        <Text style={styles.h2}>2. Services marketplace bookings</Text>
        <Text style={styles.p}>• A booking may be cancelled by the customer within 2 hours of placing it, provided the service provider has not yet confirmed or dispatched. A full wallet refund will be processed instantly.{"\n"}• After 2 hours or after provider confirmation, cancellation is subject to provider discretion. If the service is not delivered, contact support within 48 hours of the scheduled date for a review and wallet refund.{"\n"}• If the customer is unavailable at the agreed time, the provider may mark the booking “no-show” and retain the charge.{"\n"}• Platform fees are non-refundable on completed bookings.</Text>

        <Text style={styles.h2}>3. In-app shop purchases</Text>
        <Text style={styles.p}>Physical goods: return request must be raised within 7 days of delivery. Items must be unused, in original packaging, with tags intact. Upon verification, we refund the full amount to your wallet within 5 business days.{"\n"}Digital goods: once delivered/unlocked, no refunds are permitted except where a technical defect prevents access.</Text>

        <Text style={styles.h2}>4. Wallet withdrawals</Text>
        <Text style={styles.p}>A withdrawal request to your UPI / bank is reviewed by the finance team and typically settles within 1–5 business days. Once paid, the withdrawal cannot be reversed. If a withdrawal is rejected by the admin, the locked amount is released back to your wallet instantly.</Text>

        <Text style={styles.h2}>5. Chargebacks & fraud</Text>
        <Text style={styles.p}>If we detect fraud, chargeback abuse, or a reversed payment, we may freeze your wallet, claw back any reward credited as a result of that transaction, and suspend your account pending investigation.</Text>

        <Text style={styles.h2}>6. How to request a refund</Text>
        <Text style={styles.p}>Raise a support ticket at Profile → Support, or email {b.support_email || "support@example.com"}. Please include your order ID, payment ID / UTR, and a short description. We aim to resolve all refund requests within 7 working days.</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: spacing.screen, paddingBottom: 12 },
  backBtn: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  container: { paddingHorizontal: spacing.screen, paddingBottom: 40 },
  h2: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginTop: 18, marginBottom: 6 },
  p: { fontSize: 13, color: colors.textMain, lineHeight: 20, marginBottom: 8 },
});
