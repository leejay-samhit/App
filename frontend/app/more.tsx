// User-side "More" screen — consolidates Legal & Policies, About, Contact,
// and other secondary navigation that doesn't belong on the main tabs.
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useBranding } from "../src/branding";
import { colors, spacing } from "../src/theme";

type Tile = { key: string; label: string; icon: any; route: string; desc?: string };

const TILES: Tile[] = [
  { key: "about",      label: "About us",              icon: "info",       route: "/legal/about" },
  { key: "contact",    label: "Contact us",            icon: "phone",      route: "/legal/contact" },
  { key: "terms",      label: "Terms & Conditions",    icon: "file-text",  route: "/legal/terms" },
  { key: "privacy",    label: "Privacy Policy",        icon: "shield",     route: "/legal/privacy" },
  { key: "refund",     label: "Refund / Cancellation", icon: "rotate-ccw", route: "/legal/refund" },
];

export default function MoreScreen() {
  const router = useRouter();
  const b = useBranding();
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.overline}>{b.app_name?.toUpperCase()}</Text>
          <Text style={styles.title}>More</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.sectionLabel}>LEGAL & POLICIES</Text>
        <View style={styles.tileGrid}>
          {TILES.map((t) => (
            <TouchableOpacity
              key={t.key}
              style={styles.tile}
              onPress={() => router.push(t.route as any)}
              testID={`more-${t.key}`}
            >
              <View style={styles.tileIcon}>
                <Feather name={t.icon} size={22} color={colors.primary} />
              </View>
              <Text style={styles.tileLabel} numberOfLines={2}>{t.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
        <Text style={styles.footer}>{b.app_name} · v1.0</Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 12, gap: 12 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  overline: { fontSize: 10, color: colors.textMuted, fontWeight: "800", letterSpacing: 1.6 },
  title: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.5 },
  container: { padding: spacing.screen, paddingBottom: 60 },
  sectionLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "900", letterSpacing: 1, marginBottom: 10 },
  tileGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tile: { width: "31.5%", aspectRatio: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 10, alignItems: "center", justifyContent: "center", gap: 6 },
  tileIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  tileLabel: { fontSize: 11, color: colors.textMain, fontWeight: "700", textAlign: "center", lineHeight: 14 },
  footer: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 30, fontWeight: "700" },
});
