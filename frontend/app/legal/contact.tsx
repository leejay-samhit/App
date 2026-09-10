// Contact us — ONE screen used both pre-login (login footer link) and
// post-login (Profile → More). The text is admin-editable via
// Admin → Legal pages (kind "contact_us"); the two action cards below it
// are app functionality (support tickets) and stay in code.
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import LegalPageView from "../../src/legal-page-view";
import { colors, radii } from "../../src/theme";

export default function Contact() {
  const router = useRouter();
  return (
    <LegalPageView
      kind="contact_us"
      title="Contact us"
      footer={
        <View style={styles.wrap}>
          <TouchableOpacity
            style={styles.card}
            onPress={() => router.push("/legal/support-ticket" as any)}
            testID="contact-open-ticket"
          >
            <View style={styles.iconBox}><Feather name="message-circle" size={18} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardLabel}>Raise a support ticket</Text>
              <Text style={styles.cardValue}>Fastest turnaround — we respond within 48 hours</Text>
            </View>
            <View style={styles.cardBtn}><Text style={styles.cardBtnText}>Open</Text></View>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.card}
            onPress={() => router.push("/legal/track-ticket" as any)}
            testID="contact-track-ticket"
          >
            <View style={styles.iconBox}><Feather name="search" size={18} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.cardLabel}>Track my ticket</Text>
              <Text style={styles.cardValue}>Search by your email to check status & reply</Text>
            </View>
            <View style={styles.cardBtn}><Text style={styles.cardBtnText}>Track</Text></View>
          </TouchableOpacity>
        </View>
      }
    />
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 16, gap: 10 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, minHeight: 48 },
  iconBox: { width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  cardLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.5, textTransform: "uppercase" },
  cardValue: { fontSize: 13, color: colors.textMain, fontWeight: "600", marginTop: 2 },
  cardBtn: { paddingVertical: 8, paddingHorizontal: 14, borderRadius: radii.button, backgroundColor: colors.primary },
  cardBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
});
