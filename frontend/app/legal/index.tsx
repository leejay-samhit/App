import { View, Text, ScrollView, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../../src/branding";
import { colors, spacing } from "../../src/theme";

const LINKS = [
  { key: "about", label: "About us", icon: "info", desc: "Who we are and what we do" },
  { key: "terms", label: "Terms & Conditions", icon: "file-text", desc: "Rules for using the platform" },
  { key: "privacy", label: "Privacy Policy", icon: "shield", desc: "How we handle your data" },
  { key: "refund", label: "Refund & Cancellation", icon: "rotate-ccw", desc: "Returns, refunds and cancellations" },
  { key: "contact", label: "Contact us", icon: "phone", desc: "Get in touch with support" },
];

export default function LegalIndex() {
  const router = useRouter();
  const b = useBranding();
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.overline}>{b.app_name?.toUpperCase()}</Text>
          <Text style={styles.title}>Legal & Policies</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={styles.container}>
        {LINKS.map((l) => (
          <TouchableOpacity key={l.key} style={styles.row} onPress={() => router.push(("/legal/" + l.key) as any)}>
            <View style={styles.iconBox}><Feather name={l.icon as any} size={18} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTitle}>{l.label}</Text>
              <Text style={styles.rowDesc}>{l.desc}</Text>
            </View>
            <Feather name="chevron-right" size={20} color={colors.textMuted} />
          </TouchableOpacity>
        ))}
        <Text style={styles.footerNote}>Last updated: 1 May 2026 · © {b.business_name || b.app_name}</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", gap: 10, padding: spacing.screen, paddingBottom: 12 },
  backBtn: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  overline: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  container: { paddingHorizontal: spacing.screen, paddingBottom: 40 },
  row: { flexDirection: "row", alignItems: "center", gap: 14, padding: 16, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 10 },
  iconBox: { width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  rowTitle: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rowDesc: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  footerNote: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 20 },
});
