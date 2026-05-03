import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../../src/branding";
import { colors, spacing } from "../../src/theme";

export default function Privacy() {
  const router = useRouter();
  const b = useBranding();
  const name = b.business_name || b.app_name;
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Privacy Policy</Text>
      </View>
      <ScrollView contentContainerStyle={styles.container}>

        <Text style={styles.p}>Last updated: 1 May 2026. {name} respects your privacy. This Privacy Policy explains the information we collect, how we use it, and your choices.</Text>

        <Text style={styles.h2}>1. Information we collect</Text>
        <Text style={styles.p}>• Account details: name, email, mobile, password (hashed), referral code.{"\n"}• KYC data you submit for withdrawals: full name, Aadhaar number (masked in our UI), PAN, photo.{"\n"}• Transaction data: wallet credits/debits, withdrawal history, service bookings, Razorpay order & payment references.{"\n"}• Device & usage data: IP address, device model, OS version, crash logs, session timestamps.{"\n"}• Location: if you list a service, your pincode is stored; we do not collect GPS coordinates.</Text>

        <Text style={styles.h2}>2. How we use your data</Text>
        <Text style={styles.p}>• To verify your identity and process withdrawals (legitimate interest / legal obligation).{"\n"}• To compute reward eligibility and credit your wallet.{"\n"}• To connect customers and service providers in the marketplace.{"\n"}• To prevent fraud, abuse and duplicate accounts.{"\n"}• To send transactional notifications about your account.</Text>

        <Text style={styles.h2}>3. Sharing your data</Text>
        <Text style={styles.p}>We do not sell your personal data. We share it only with:{"\n"}• Razorpay — for payment collection, in accordance with their privacy policy at razorpay.com/privacy.{"\n"}• Your approved sponsor and the admin team — your name, pincode and referral code only.{"\n"}• Government authorities — when compelled by valid legal process.{"\n"}• Infrastructure providers (Emergent, MongoDB Atlas) — under strict confidentiality.</Text>

        <Text style={styles.h2}>4. Data retention</Text>
        <Text style={styles.p}>We retain account and transaction data for at least 7 years as required by the Income Tax Act, 1961. Marketing preferences and device data are retained for up to 24 months from your last session. You may request deletion of your account after settling all balances — see Section 7.</Text>

        <Text style={styles.h2}>5. Security</Text>
        <Text style={styles.p}>Passwords are stored using bcrypt. All data in transit is protected by TLS 1.2+. KYC images are stored as base-64 blobs in our database and are only accessible to authorised admins. We never store your full Aadhaar / PAN in logs or backups unencrypted.</Text>

        <Text style={styles.h2}>6. Children’s privacy</Text>
        <Text style={styles.p}>{name} is not directed at children under 18. We do not knowingly collect data from minors.</Text>

        <Text style={styles.h2}>7. Your rights</Text>
        <Text style={styles.p}>You can (a) access a copy of your data, (b) correct inaccuracies from Settings → Profile, (c) withdraw consent, (d) request deletion of your account. Email {b.support_email || "support@example.com"} with your request and we will respond within 30 days.</Text>

        <Text style={styles.h2}>8. Grievance officer</Text>
        <Text style={styles.p}>In accordance with the Information Technology Act, 2000, the details of the grievance officer are:{"\n"}Email: {b.support_email || "support@example.com"}{"\n"}{b.support_phone ? `Phone: ${b.support_phone}\n` : ""}Address: {b.business_address || "registered office"}{b.business_city ? `, ${b.business_city}` : ""}{b.business_state ? `, ${b.business_state}` : ""}{b.business_pincode ? ` - ${b.business_pincode}` : ""}</Text>

        <Text style={styles.h2}>9. Updates</Text>
        <Text style={styles.p}>We may update this policy. Material changes will be notified inside the app. The latest version will always be available at this screen and on our website.</Text>
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
