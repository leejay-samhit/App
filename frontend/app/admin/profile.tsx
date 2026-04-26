import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

export default function AdminProfile() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const onLogout = async () => {
    await logout();
    router.replace("/login");
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.container}>
        <Text style={styles.overline}>ADMIN ACCOUNT</Text>
        <Text style={styles.h1}>{user?.name}</Text>
        <Text style={styles.email}>{user?.email}</Text>

        <View style={styles.card}>
          <View style={styles.row}>
            <Feather name="shield" size={16} color={colors.primary} />
            <Text style={styles.rowText}>Role</Text>
            <Text style={styles.rowValue}>{user?.role}</Text>
          </View>
          <View style={styles.divider} />
          <View style={styles.row}>
            <Feather name="hash" size={16} color={colors.primary} />
            <Text style={styles.rowText}>Code</Text>
            <Text style={styles.rowValue}>{user?.referral_code}</Text>
          </View>
        </View>

        <TouchableOpacity onPress={onLogout} style={styles.logoutBtn} testID="admin-logout">
          <Feather name="log-out" size={16} color="#B3261E" />
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  email: { fontSize: 14, color: colors.textMuted, marginTop: 4, marginBottom: 24 },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 8 },
  row: { flexDirection: "row", alignItems: "center", padding: 14, gap: 12 },
  rowText: { flex: 1, fontSize: 14, color: colors.textMain, fontWeight: "600" },
  rowValue: { fontSize: 14, color: colors.textMuted, fontWeight: "700" },
  divider: { height: 1, backgroundColor: colors.border, marginHorizontal: 14 },
  logoutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 24, padding: 14, borderRadius: radii.button, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  logoutText: { color: "#B3261E", fontSize: 14, fontWeight: "700" },
});
