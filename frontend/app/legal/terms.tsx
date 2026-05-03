import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../../src/branding";
import { colors, spacing } from "../../src/theme";

export default function Terms() {
  const router = useRouter();
  const b = useBranding();
  const name = b.business_name || b.app_name;
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Terms & Conditions</Text>
      </View>
      <ScrollView contentContainerStyle={styles.container}>

        <Text style={styles.p}>Last updated: 1 May 2026. By accessing or using the {name} platform you agree to these Terms. If you do not agree, please do not use the service.</Text>

        <Text style={styles.h2}>1. Eligibility</Text>
        <Text style={styles.p}>You must be at least 18 years of age, legally competent to enter a contract in India, and registered with a verified mobile number and email address. Members from countries where our service is not offered are not permitted to register.</Text>

        <Text style={styles.h2}>2. Account & Registration</Text>
        <Text style={styles.p}>Registration is subject to a one-time non-refundable fee displayed at the time of sign-up. Your account is personal — you may not sell, lease, transfer or let anyone else use it. You are responsible for the accuracy of the data you provide and for maintaining the confidentiality of your password.</Text>

        <Text style={styles.h2}>3. Referral & Reward Programme</Text>
        <Text style={styles.p}>{name} runs an optional reward programme that credits wallet points when you introduce new verified members. All reward amounts, eligibility conditions and payout frequencies are shown inside the app under Settings → Payout levels, and are subject to change with notice. Rewards have no cash value outside the platform until a withdrawal is admin-approved.{"\n"}• We do not guarantee any minimum earnings.{"\n"}• Reward eligibility depends solely on verified, paid member introductions — never on a time-bound target.{"\n"}• We reserve the right to claw back rewards obtained by fraud, chargebacks, or duplicate accounts.</Text>

        <Text style={styles.h2}>4. Services Marketplace</Text>
        <Text style={styles.p}>Approved members may list services (e.g. electrician, tutor, plumber) with a pincode and fixed charge. Bookings are processed through the member’s wallet. {name} charges a platform fee from each booking which is disclosed on the booking screen.</Text>

        <Text style={styles.h2}>5. Wallet, Withdrawals & Taxes</Text>
        <Text style={styles.p}>The in-app wallet is a record of reward and marketplace balances and is not a deposit, investment or prepaid instrument. Withdrawals to your UPI / bank are reviewed by our finance team and settle in 1–5 business days. We may withhold tax deducted at source (TDS) where applicable. You are responsible for reporting and paying all taxes on amounts received.</Text>

        <Text style={styles.h2}>6. Prohibited Conduct</Text>
        <Text style={styles.p}>You agree not to: (a) create fake or duplicate accounts; (b) misrepresent the platform to recruit members; (c) use the platform for money laundering, gambling or any unlawful purpose; (d) scrape, reverse-engineer or attack our servers; (e) post misleading service listings. Violation may result in account suspension and forfeiture of wallet balance.</Text>

        <Text style={styles.h2}>7. Intellectual Property</Text>
        <Text style={styles.p}>The {name} name, logo, UI, and software are owned by us. You receive a limited, revocable, non-transferable licence to use the app for personal, non-commercial purposes.</Text>

        <Text style={styles.h2}>8. Disclaimer</Text>
        <Text style={styles.p}>The service is provided “as is”. {name} does not warrant uninterrupted availability, error-free operation, or that the service will meet your requirements. We are not liable for indirect, incidental, consequential, or punitive damages.</Text>

        <Text style={styles.h2}>9. Governing Law & Jurisdiction</Text>
        <Text style={styles.p}>These Terms are governed by the laws of India. Courts at {b.business_city || "the registered office location"} shall have exclusive jurisdiction for any dispute.</Text>

        <Text style={styles.h2}>10. Changes</Text>
        <Text style={styles.p}>We may update these Terms from time to time. Material changes will be notified inside the app. Continued use after the change constitutes acceptance.</Text>

        <Text style={styles.footer}>Questions? Email {b.support_email || "support@example.com"}.</Text>
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
  footer: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 24, marginBottom: 8 },
});
