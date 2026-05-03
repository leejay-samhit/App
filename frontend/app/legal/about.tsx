import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../../src/branding";
import { colors, spacing } from "../../src/theme";

export default function About() {
  const router = useRouter();
  const b = useBranding();
  const name = b.business_name || b.app_name;
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>About us</Text>
      </View>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.h2}>Who we are</Text>
        <Text style={styles.p}>{name} is a technology platform that lets members build a peer-to-peer network, run a services marketplace in their neighbourhood, and earn reward points which can be redeemed through our in-app wallet.</Text>

        <Text style={styles.h2}>What we offer</Text>
        <Text style={styles.p}>• A reward-tracking wallet for approved members.{"\n"}• A services marketplace where verified local professionals (electricians, tutors, plumbers and more) list their services with pincode and charge.{"\n"}• An optional member-only store for digital and physical goods priced in wallet balance.{"\n"}• Transparent earnings history and admin-reviewed withdrawal to UPI / bank.</Text>

        <Text style={styles.h2}>Our principles</Text>
        <Text style={styles.p}>• Reward only for verified activity — every new member is admin-reviewed.{"\n"}• No guaranteed income; all reward tiers are clearly disclosed inside the app.{"\n"}• Full KYC — members submit Aadhaar / PAN before withdrawing.{"\n"}• No forced purchases or mandatory recruitment beyond the one-time registration.</Text>

        <Text style={styles.h2}>Contact</Text>
        <Text style={styles.p}>{b.business_address || "Address will be displayed here once added in Admin → Branding."}{b.business_city ? `, ${b.business_city}` : ""}{b.business_state ? `, ${b.business_state}` : ""}{b.business_pincode ? ` - ${b.business_pincode}` : ""}{b.business_gst ? `\nGST: ${b.business_gst}` : ""}</Text>
        <Text style={styles.p}>Email: {b.support_email || "support@example.com"}{b.support_phone ? `\nPhone: ${b.support_phone}` : ""}</Text>

        <Text style={styles.footer}>Last updated: 1 May 2026</Text>
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
