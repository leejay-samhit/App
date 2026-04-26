import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

const ITEMS = [
  { icon: "user-check", label: "KYC review queue", route: "/admin/kyc" },
  { icon: "package", label: "Orders management", route: "/admin/orders" },
  { icon: "file-text", label: "Admin audit log", route: "/admin/audit" },
  { icon: "sliders", label: "Payout structure", route: "/admin/settings" },
];

const EXPORTS = [
  { kind: "users", label: "Users CSV", icon: "users" },
  { kind: "transactions", label: "Transactions CSV", icon: "list" },
  { kind: "withdrawals", label: "Withdrawals CSV", icon: "dollar-sign" },
  { kind: "orders", label: "Orders CSV", icon: "shopping-bag" },
] as const;

export default function More() {
  const router = useRouter();
  const { user, logout } = useAuth();

  const onExport = async (kind: string) => {
    try {
      const res = await api.get(`/admin/export/${kind}`, { responseType: "text" });
      const data = (res.data as unknown) as string;
      const lines = (typeof data === "string" ? data : "").split("\n").length - 1;
      Alert.alert("Export ready", `${lines} ${kind} rows exported.\n\nIn production this triggers a file download. Preview shows row count for now.`);
    } catch {
      Alert.alert("Export failed", "Please try again.");
    }
  };

  const onLogout = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.overline}>ADMIN</Text>
        <Text style={styles.h1}>More</Text>
        <Text style={styles.subtitle}>{user?.email} · {(user as any)?.admin_role || "super_admin"}</Text>

        <Text style={styles.sectionLabel}>OPERATIONS</Text>
        {ITEMS.map((it) => (
          <TouchableOpacity key={it.route} style={styles.row} onPress={() => router.push(it.route as any)} testID={`more-${it.icon}`}>
            <View style={styles.rowIcon}><Feather name={it.icon as any} size={16} color={colors.primary} /></View>
            <Text style={styles.rowText}>{it.label}</Text>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ))}

        <Text style={styles.sectionLabel}>EXPORT DATA</Text>
        {EXPORTS.map((e) => (
          <TouchableOpacity key={e.kind} style={styles.row} onPress={() => onExport(e.kind)} testID={`export-${e.kind}`}>
            <View style={styles.rowIcon}><Feather name={e.icon as any} size={16} color={colors.primary} /></View>
            <Text style={styles.rowText}>{e.label}</Text>
            <Feather name="download" size={16} color={colors.textMuted} />
          </TouchableOpacity>
        ))}

        <TouchableOpacity onPress={onLogout} style={styles.logout} testID="more-logout">
          <Feather name="log-out" size={16} color="#B3261E" />
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 60 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginTop: 6 },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6, marginBottom: 24 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12, marginTop: 12 },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8, gap: 12 },
  rowIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  rowText: { flex: 1, fontSize: 14, color: colors.textMain, fontWeight: "600" },
  logout: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 24, padding: 14, borderRadius: radii.button, backgroundColor: colors.surface, borderWidth: 1, borderColor: "#B3261E" },
  logoutText: { color: "#B3261E", fontSize: 14, fontWeight: "700" },
});
