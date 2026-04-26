import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  Share,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, formatINR, radii, spacing } from "../../src/theme";

type Dashboard = {
  wallet_balance: number;
  total_earned: number;
  direct_referrals: number;
  team_size: number;
  payouts_received: number;
  next_payout_in: number;
  directs_required: number;
  registration_paid: boolean;
  pending_withdrawals: number;
  referral_code: string;
};

export default function DashboardScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<Dashboard | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Dashboard>("/users/me/dashboard");
      setData(data);
    } catch (e) {
      // ignore
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const onShareCode = async () => {
    if (!data?.referral_code) return;
    try {
      await Share.share({
        message: `Join NetworkPay using my referral code: ${data.referral_code}`,
      });
    } catch {}
  };

  if (loading || !data) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} />
        </View>
      </SafeAreaView>
    );
  }

  const progressPct = ((data.directs_required - data.next_payout_in) / data.directs_required) * 100;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.greeting}>Hello,</Text>
            <Text style={styles.name} testID="dashboard-user-name">{user?.name}</Text>
          </View>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{(user?.name || "U").charAt(0).toUpperCase()}</Text>
          </View>
        </View>

        <View style={styles.heroCard}>
          <Text style={styles.heroLabel}>TOTAL EARNINGS</Text>
          <Text style={styles.heroAmount} testID="dashboard-total-earned">{formatINR(data.total_earned)}</Text>
          <View style={styles.heroBottom}>
            <View>
              <Text style={styles.heroSubLabel}>Wallet balance</Text>
              <Text style={styles.heroSubValue} testID="dashboard-wallet-balance">{formatINR(data.wallet_balance)}</Text>
            </View>
            <TouchableOpacity onPress={() => router.push("/(tabs)/wallet")} style={styles.withdrawBtn} testID="dashboard-withdraw-btn">
              <Text style={styles.withdrawBtnText}>Withdraw</Text>
              <Feather name="arrow-up-right" size={16} color={colors.accentFg} />
            </TouchableOpacity>
          </View>
        </View>

        <View style={styles.progressCard}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={styles.cardTitle}>Next payout</Text>
            <Text style={styles.cardSub}>{formatINR(400)}</Text>
          </View>
          <Text style={styles.progressInfo}>
            Refer <Text style={styles.bold}>{data.next_payout_in}</Text> more direct{data.next_payout_in === 1 ? "" : "s"} to unlock your next payout.
          </Text>
          <View style={styles.progressBar}>
            <View style={[styles.progressFill, { width: `${progressPct}%` }]} />
          </View>
        </View>

        <Text style={styles.sectionLabel}>YOUR NETWORK</Text>
        <View style={styles.bento}>
          <StatCard icon="user-plus" label="Direct referrals" value={String(data.direct_referrals)} testID="stat-direct" />
          <StatCard icon="users" label="Team size" value={String(data.team_size)} testID="stat-team" />
          <StatCard icon="award" label="Payouts" value={String(data.payouts_received)} testID="stat-payouts" />
          <StatCard icon="clock" label="Pending W/D" value={String(data.pending_withdrawals)} testID="stat-pending" />
        </View>

        <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
        <TouchableOpacity style={styles.shareCard} onPress={onShareCode} testID="dashboard-share-code">
          <View style={{ flex: 1 }}>
            <Text style={styles.shareLabel}>YOUR REFERRAL CODE</Text>
            <Text style={styles.shareCode}>{data.referral_code}</Text>
          </View>
          <View style={styles.shareIcon}>
            <Feather name="share-2" size={18} color={colors.primaryFg} />
          </View>
        </TouchableOpacity>

        <TouchableOpacity style={styles.quickRow} onPress={() => router.push("/(tabs)/profile")} testID="dashboard-update-upi">
          <View style={styles.quickIcon}><Feather name="credit-card" size={16} color={colors.primary} /></View>
          <Text style={styles.quickText}>Update bank / UPI details</Text>
          <Feather name="chevron-right" size={18} color={colors.textMuted} />
        </TouchableOpacity>

        <TouchableOpacity style={styles.quickRow} onPress={() => router.push("/(tabs)/network")} testID="dashboard-view-network">
          <View style={styles.quickIcon}><Feather name="git-branch" size={16} color={colors.primary} /></View>
          <Text style={styles.quickText}>View referral tree</Text>
          <Feather name="chevron-right" size={18} color={colors.textMuted} />
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function StatCard({ icon, label, value, testID }: { icon: any; label: string; value: string; testID?: string }) {
  return (
    <View style={styles.statCard} testID={testID}>
      <Feather name={icon} size={18} color={colors.primary} />
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 24 },
  greeting: { color: colors.textMuted, fontSize: 13 },
  name: { color: colors.textMain, fontSize: 22, fontWeight: "800", letterSpacing: -0.5 },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.primaryFg, fontWeight: "700", fontSize: 16 },
  heroCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 24, marginBottom: 16 },
  heroLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  heroAmount: { color: colors.primaryFg, fontSize: 44, fontWeight: "800", marginTop: 6, letterSpacing: -1.5 },
  heroBottom: { marginTop: 16, flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" },
  heroSubLabel: { color: "rgba(255,255,255,0.6)", fontSize: 12 },
  heroSubValue: { color: colors.primaryFg, fontSize: 18, fontWeight: "700", marginTop: 2 },
  withdrawBtn: { flexDirection: "row", alignItems: "center", backgroundColor: colors.accent, paddingHorizontal: 16, paddingVertical: 10, borderRadius: radii.button, gap: 4 },
  withdrawBtnText: { color: colors.accentFg, fontWeight: "700", fontSize: 13 },
  progressCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 20, marginBottom: 24 },
  cardTitle: { fontSize: 15, fontWeight: "700", color: colors.textMain },
  cardSub: { fontSize: 14, fontWeight: "700", color: colors.accent },
  progressInfo: { color: colors.textMuted, fontSize: 13, marginTop: 8, marginBottom: 12 },
  bold: { color: colors.textMain, fontWeight: "700" },
  progressBar: { height: 8, backgroundColor: colors.surfaceMuted, borderRadius: 99, overflow: "hidden" },
  progressFill: { height: "100%", backgroundColor: colors.success, borderRadius: 99 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  bento: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginBottom: 24 },
  statCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 18, padding: 16 },
  statValue: { fontSize: 24, fontWeight: "800", color: colors.textMain, marginTop: 8, letterSpacing: -0.5 },
  statLabel: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  shareCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 18, marginBottom: 12 },
  shareLabel: { fontSize: 10, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  shareCode: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: 2, marginTop: 4 },
  shareIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  quickRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 16, marginBottom: 10 },
  quickIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginRight: 12 },
  quickText: { flex: 1, color: colors.textMain, fontSize: 14, fontWeight: "600" },
});
