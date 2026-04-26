import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type AdminUser = {
  id: string;
  name: string;
  email: string;
  role: string;
  referral_code: string;
  referred_by: string | null;
  registration_paid: boolean;
  direct_referrals_count: number;
  wallet_balance: number;
  total_earned: number;
  created_at: string;
};

type Stats = {
  total_users: number;
  paid_users: number;
  pending_payouts: number;
  total_revenue: number;
  total_referral_payouts: number;
};

export default function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [u, s] = await Promise.all([api.get<AdminUser[]>("/admin/users"), api.get<Stats>("/admin/stats")]);
      setUsers(u.data);
      setStats(s.data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <FlatList
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        ListHeaderComponent={
          <View>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Users</Text>
            {stats && (
              <View style={styles.statsGrid}>
                <Stat label="Total users" value={String(stats.total_users)} />
                <Stat label="Paid" value={String(stats.paid_users)} />
                <Stat label="Revenue" value={formatINR(stats.total_revenue)} />
                <Stat label="Payouts paid" value={formatINR(stats.total_referral_payouts)} />
              </View>
            )}
            <Text style={styles.sectionLabel}>ALL USERS</Text>
          </View>
        }
        data={users}
        keyExtractor={(u) => u.id}
        renderItem={({ item }) => (
          <View style={styles.userRow} testID={`admin-user-${item.id}`}>
            <View style={styles.avatar}><Text style={styles.avatarText}>{item.name.charAt(0).toUpperCase()}</Text></View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={styles.userName}>{item.name}</Text>
                {item.role === "admin" && <View style={styles.adminBadge}><Text style={styles.adminBadgeText}>ADMIN</Text></View>}
              </View>
              <Text style={styles.userEmail}>{item.email}</Text>
              <View style={styles.userMeta}>
                <Feather name="hash" size={11} color={colors.textMuted} />
                <Text style={styles.userMetaText}>{item.referral_code}</Text>
                <Feather name="users" size={11} color={colors.textMuted} style={{ marginLeft: 8 }} />
                <Text style={styles.userMetaText}>{item.direct_referrals_count} directs</Text>
              </View>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={styles.userAmount}>{formatINR(item.total_earned)}</Text>
              <View style={[styles.statusDot, { backgroundColor: item.registration_paid ? colors.success : colors.warning }]}>
                <Text style={styles.statusDotText}>{item.registration_paid ? "PAID" : "UNPAID"}</Text>
              </View>
            </View>
          </View>
        )}
        ListEmptyComponent={<Text style={styles.empty}>No users yet</Text>}
      />
    </SafeAreaView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statCard}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 20 },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 28 },
  statCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 14 },
  statValue: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  statLabel: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  userRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 12, marginBottom: 10, gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.primary, fontWeight: "800" },
  userName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  adminBadge: { backgroundColor: colors.accent, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  adminBadgeText: { color: colors.accentFg, fontSize: 9, fontWeight: "800" },
  userEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  userMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  userMetaText: { fontSize: 11, color: colors.textMuted },
  userAmount: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  statusDot: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, marginTop: 4 },
  statusDotText: { color: colors.primaryFg, fontSize: 9, fontWeight: "800" },
  empty: { padding: 24, textAlign: "center", color: colors.textMuted },
});
