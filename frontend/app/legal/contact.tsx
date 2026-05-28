import { View, Text, ScrollView, StyleSheet, TouchableOpacity, Linking, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../../src/branding";
import { colors, spacing, radii } from "../../src/theme";

export default function Contact() {
  const router = useRouter();
  const b = useBranding();
  const name = b.business_name || b.app_name;
  const open = (url: string) => Linking.openURL(url).catch(() => Alert.alert("Unable to open"));
  const address = [b.business_address, b.business_city, b.business_state, b.business_pincode].filter(Boolean).join(", ");
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Contact us</Text>
      </View>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.p}>We’re here to help. Whether it’s a refund, KYC query, service booking issue or general feedback, reach us through any of the channels below.</Text>

        <View style={styles.card}>
          <View style={styles.iconBox}><Feather name="mail" size={18} color={colors.primary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardLabel}>Email</Text>
            <Text style={styles.cardValue}>{b.support_email || "support@example.com"}</Text>
          </View>
          <TouchableOpacity style={styles.cardBtn} onPress={() => open(`mailto:${b.support_email || "support@example.com"}`)}><Text style={styles.cardBtnText}>Email</Text></TouchableOpacity>
        </View>

        {b.support_phone ? null : null}

        <View style={styles.card}>
          <View style={styles.iconBox}><Feather name="message-circle" size={18} color={colors.primary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardLabel}>Raise a support ticket</Text>
            <Text style={styles.cardValue}>Fastest turnaround — we respond within 48 hours</Text>
          </View>
          <TouchableOpacity style={styles.cardBtn} onPress={() => router.push("/legal/support-ticket" as any)}><Text style={styles.cardBtnText}>Open</Text></TouchableOpacity>
        </View>

        <View style={styles.card}>
          <View style={styles.iconBox}><Feather name="search" size={18} color={colors.primary} /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.cardLabel}>Track my ticket</Text>
            <Text style={styles.cardValue}>Search by your email to check status & reply</Text>
          </View>
          <TouchableOpacity style={styles.cardBtn} onPress={() => router.push("/legal/track-ticket" as any)}><Text style={styles.cardBtnText}>Track</Text></TouchableOpacity>
        </View>

        {address ? (
          <View style={[styles.card, { alignItems: "flex-start" }]}>
            <View style={styles.iconBox}><Feather name="map-pin" size={18} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardLabel}>Registered office</Text>
              <Text style={styles.cardValue}>{address}{b.business_gst ? `\nGST: ${b.business_gst}` : ""}</Text>
            </View>
          </View>
        ) : null}

        <Text style={styles.footer}>We aim to respond within 24 business hours. For urgent KYC or withdrawal issues, use the “Support ticket” channel and mark priority as High.</Text>
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
  p: { fontSize: 13, color: colors.textMain, lineHeight: 20, marginBottom: 12 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 10 },
  iconBox: { width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  cardLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.5, textTransform: "uppercase" },
  cardValue: { fontSize: 13, color: colors.textMain, fontWeight: "600", marginTop: 2 },
  cardBtn: { paddingVertical: 8, paddingHorizontal: 14, borderRadius: radii.button, backgroundColor: colors.primary },
  cardBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  footer: { fontSize: 11, color: colors.textMuted, marginTop: 12, lineHeight: 16 },
});
