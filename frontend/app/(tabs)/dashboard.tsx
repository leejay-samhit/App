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
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";
import Animated, { FadeInDown } from "react-native-reanimated";
import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, formatINR, radii, spacing } from "../../src/theme";

type Tier = { name: string; min: number; color: string; icon: string };

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
  unread_notifications: number;
  tier: Tier;
  level_payouts: { l1: number; l2: number; l3: number };
};

type Notif = {
  id: string;
  kind: string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
};

export default function DashboardScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<Dashboard | null>(null);
  const [recentNotifs, setRecentNotifs] = useState<Notif[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, n] = await Promise.all([
        api.get<Dashboard>("/users/me/dashboard"),
        api.get<Notif[]>("/notifications/me"),
      ]);
      setData(d.data);
      setRecentNotifs(n.data.slice(0, 3));
    } catch {}
    finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onShareCode = async () => {
    if (!data?.referral_code) return;
    try {
      await Share.share({
        message: `Hi! Join NetworkPay using my referral code *${data.referral_code}* and earn ₹400 for every 4 friends you bring. Sign up: networkpay.app/r/${data.referral_code}`,
      });
    } catch {}
  };

  const onCopyCode = async () => {
    if (!data?.referral_code) return;
    await Clipboard.setStringAsync(data.referral_code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading || !data) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  const progressPct = ((data.directs_required - data.next_payout_in) / data.directs_required) * 100;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        showsVerticalScrollIndicator={false}
      >
        <Animated.View entering={FadeInDown.duration(400)} style={styles.headerRow}>
          <View>
            <Text style={styles.greeting}>Hello,</Text>
            <Text style={styles.name} testID="dashboard-user-name">{user?.name}</Text>
          </View>
          <View style={styles.headerActions}>
            <TouchableOpacity onPress={() => router.push("/notifications")} style={styles.bellBtn} testID="dashboard-bell">
              <Feather name="bell" size={18} color={colors.textMain} />
              {data.unread_notifications > 0 && (
                <View style={styles.bellDot}>
                  <Text style={styles.bellDotText}>{data.unread_notifications > 9 ? "9+" : data.unread_notifications}</Text>
                </View>
              )}
            </TouchableOpacity>
            <View style={styles.avatar}><Text style={styles.avatarText}>{(user?.name || "U").charAt(0).toUpperCase()}</Text></View>
          </View>
        </Animated.View>

        <Animated.View entering={FadeInDown.duration(400).delay(80)} style={styles.tierPill}>
          <Feather name={data.tier.icon as any} size={14} color={colors.primary} />
          <Text style={styles.tierText}>{data.tier.name.toUpperCase()} TIER</Text>
          <View style={styles.tierDivider} />
          <Text style={styles.tierTeam}>{data.team_size} in network</Text>
        </Animated.View>

        {/* Approval status banner — only show if not approved */}
        {(user as any)?.approval_status && (user as any).approval_status !== "approved" && (
          <TouchableOpacity
            onPress={() => router.push("/extra-docs" as any)}
            style={[styles.approvalBanner, { backgroundColor: (user as any).approval_status === "rejected" ? "#FCE9E5" : "#FFF4E5", borderColor: (user as any).approval_status === "rejected" ? "#F2B8B5" : "#FFD79A" }]}
            testID="dashboard-approval-banner"
          >
            <Feather
              name={(user as any).approval_status === "rejected" ? "alert-triangle" : "clock"}
              size={18}
              color={(user as any).approval_status === "rejected" ? "#B3261E" : colors.warning}
            />
            <View style={{ flex: 1 }}>
              <Text style={[styles.approvalBannerTitle, { color: (user as any).approval_status === "rejected" ? "#B3261E" : "#7A5B12" }]}>
                {(user as any).approval_status === "rejected" ? "Approval rejected" : "Approval pending"}
              </Text>
              <Text style={styles.approvalBannerSub} numberOfLines={2}>
                {(user as any).approval_status === "rejected"
                  ? `${(user as any).approval_reject_reason || "Please upload additional documents to re-verify."} Tap to upload.`
                  : "Your account is awaiting admin approval. Withdrawals are disabled until approved."}
              </Text>
            </View>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        )}

        <Animated.View entering={FadeInDown.duration(450).delay(120)} style={styles.heroCard}>
          <View style={styles.heroDecor} />
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
        </Animated.View>

        <Animated.View entering={FadeInDown.duration(450).delay(180)} style={styles.progressCard}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
            <Text style={styles.cardTitle}>Next L1 payout</Text>
            <Text style={styles.cardSub}>{formatINR(data.level_payouts.l1)}</Text>
          </View>
          <Text style={styles.progressInfo}>
            Refer <Text style={styles.bold}>{data.next_payout_in}</Text> more direct{data.next_payout_in === 1 ? "" : "s"} to unlock your next payout.
          </Text>
          <View style={styles.progressBar}>
            <View style={[styles.progressFill, { width: `${progressPct}%` }]} />
          </View>
          <View style={styles.levelsRow}>
            <View style={styles.levelChip}><Text style={styles.levelChipLabel}>L1</Text><Text style={styles.levelChipValue}>{formatINR(data.level_payouts.l1)}</Text></View>
            <View style={styles.levelChip}><Text style={styles.levelChipLabel}>L2</Text><Text style={styles.levelChipValue}>{formatINR(data.level_payouts.l2)}</Text></View>
            <View style={styles.levelChip}><Text style={styles.levelChipLabel}>L3</Text><Text style={styles.levelChipValue}>{formatINR(data.level_payouts.l3)}</Text></View>
          </View>
        </Animated.View>

        <Animated.View entering={FadeInDown.duration(450).delay(240)}>
          <Text style={styles.sectionLabel}>YOUR NETWORK</Text>
          <View style={styles.bento}>
            <StatCard icon="user-plus" label="Direct referrals" value={String(data.direct_referrals)} testID="stat-direct" onPress={() => router.push("/(tabs)/network")} />
            <StatCard icon="users" label="Team size" value={String(data.team_size)} testID="stat-team" onPress={() => router.push("/(tabs)/network")} />
            <StatCard icon="award" label="Payouts" value={String(data.payouts_received)} testID="stat-payouts" onPress={() => router.push("/(tabs)/wallet")} />
            <StatCard icon="clock" label="Pending W/D" value={String(data.pending_withdrawals)} testID="stat-pending" onPress={() => router.push("/(tabs)/wallet")} />
          </View>
        </Animated.View>

        <Animated.View entering={FadeInDown.duration(450).delay(300)}>
          <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
          <View style={styles.codeCard}>
            <View style={{ flex: 1 }}>
              <Text style={styles.codeLabel}>YOUR REFERRAL CODE</Text>
              <Text style={styles.codeValue}>{data.referral_code}</Text>
            </View>
            <TouchableOpacity onPress={onCopyCode} style={styles.codeIconBtn} testID="dashboard-copy-code">
              <Feather name={copied ? "check" : "copy"} size={16} color={colors.primaryFg} />
            </TouchableOpacity>
            <TouchableOpacity onPress={onShareCode} style={[styles.codeIconBtn, { backgroundColor: colors.accent }]} testID="dashboard-share-code">
              <Feather name="share-2" size={16} color={colors.accentFg} />
            </TouchableOpacity>
          </View>

          <TouchableOpacity style={styles.quickRow} onPress={() => router.push("/(tabs)/profile")} testID="dashboard-update-upi">
            <View style={styles.quickIcon}><Feather name="credit-card" size={16} color={colors.primary} /></View>
            <Text style={styles.quickText}>Update bank / UPI details</Text>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>

          <TouchableOpacity style={styles.quickRow} onPress={() => router.push("/orders")} testID="dashboard-orders">
            <View style={styles.quickIcon}><Feather name="package" size={16} color={colors.primary} /></View>
            <Text style={styles.quickText}>My orders</Text>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        </Animated.View>

        {recentNotifs.length > 0 && (
          <Animated.View entering={FadeInDown.duration(450).delay(360)}>
            <View style={styles.feedHeader}>
              <Text style={styles.sectionLabel}>RECENT ACTIVITY</Text>
              <TouchableOpacity onPress={() => router.push("/notifications")} testID="dashboard-view-all-notifs">
                <Text style={styles.viewAll}>View all</Text>
              </TouchableOpacity>
            </View>
            {recentNotifs.map((n) => (
              <View key={n.id} style={styles.feedItem}>
                <View style={[styles.feedDot, { backgroundColor: n.kind === "payout" ? colors.success : n.kind === "withdrawal" ? colors.accent : colors.primary }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.feedTitle}>{n.title}</Text>
                  <Text style={styles.feedBody} numberOfLines={2}>{n.body}</Text>
                </View>
              </View>
            ))}
          </Animated.View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function StatCard({ icon, label, value, testID, onPress }: { icon: any; label: string; value: string; testID?: string; onPress?: () => void }) {
  const Wrap: any = onPress ? TouchableOpacity : View;
  return (
    <Wrap activeOpacity={0.75} onPress={onPress} style={styles.statCard} testID={testID}>
      <View style={styles.statIconWrap}><Feather name={icon} size={16} color={colors.primary} /></View>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
      {onPress ? (
        <View style={styles.statChev}>
          <Feather name="chevron-right" size={12} color={colors.textMuted} />
        </View>
      ) : null}
    </Wrap>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 16 },
  headerActions: { flexDirection: "row", alignItems: "center", gap: 10 },
  greeting: { color: colors.textMuted, fontSize: 13 },
  name: { color: colors.textMain, fontSize: 22, fontWeight: "800", letterSpacing: -0.5 },
  bellBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  bellDot: { position: "absolute", top: -2, right: -2, minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  bellDotText: { color: colors.accentFg, fontSize: 10, fontWeight: "800" },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.primaryFg, fontWeight: "700", fontSize: 16 },
  tierPill: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", backgroundColor: colors.brand100, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 99, marginBottom: 20, gap: 8 },
  tierText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 1.5 },
  tierDivider: { width: 1, height: 12, backgroundColor: colors.primary, opacity: 0.2 },
  tierTeam: { fontSize: 11, color: colors.primary, fontWeight: "600" },
  approvalBanner: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 14, borderWidth: 1, marginBottom: 16 },
  approvalBannerTitle: { fontSize: 13, fontWeight: "800" },
  approvalBannerSub: { fontSize: 11, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  heroCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 24, marginBottom: 16, overflow: "hidden" },
  heroDecor: { position: "absolute", right: -40, top: -40, width: 160, height: 160, borderRadius: 80, backgroundColor: "rgba(229,122,68,0.18)" },
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
  levelsRow: { flexDirection: "row", gap: 8, marginTop: 16 },
  levelChip: { flex: 1, backgroundColor: colors.surfaceMuted, paddingVertical: 10, borderRadius: 12, alignItems: "center" },
  levelChipLabel: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 1 },
  levelChipValue: { fontSize: 13, fontWeight: "800", color: colors.primary, marginTop: 2 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  bento: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginBottom: 24 },
  statCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 18, padding: 16, position: "relative" },
  statIconWrap: { width: 32, height: 32, borderRadius: 10, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  statValue: { fontSize: 24, fontWeight: "800", color: colors.textMain, marginTop: 12, letterSpacing: -0.5 },
  statLabel: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  statChev: { position: "absolute", top: 14, right: 14, width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },
  codeCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 12, gap: 10 },
  codeLabel: { fontSize: 10, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  codeValue: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: 2, marginTop: 4 },
  codeIconBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  quickRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 16, marginBottom: 10 },
  quickIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginRight: 12 },
  quickText: { flex: 1, color: colors.textMain, fontSize: 14, fontWeight: "600" },
  feedHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 12 },
  viewAll: { color: colors.primary, fontSize: 12, fontWeight: "700", marginBottom: 12 },
  feedItem: { flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8, gap: 10, alignItems: "flex-start" },
  feedDot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  feedTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  feedBody: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
});
