import { useCallback, useState, useEffect } from "react";
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
import { cachedGet } from "../../src/cachedGet";
import { useAuth } from "../../src/auth";
import { useBranding } from "../../src/branding";
import { colors, formatINR, radii, spacing } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { Skeleton, SkeletonCard, SkeletonRow } from "../../src/skeleton";
import { Sparkline, DonutProgress, BarChart } from "../../src/charts";
import { openWhatsApp, buildWelcomeMessage, DEFAULT_SUPPORT_WHATSAPP } from "../../src/whatsapp";
import { startBackgroundProviderLocation, stopBackgroundProviderLocation, pushLocationNow } from "../../src/bg-location";

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
  earnings_per_day?: number[];
  day_labels?: string[];
  level_breakdown?: Record<string, number>;
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
  const branding = useBranding();
  // Admin-configurable WhatsApp support number (falls back to the default
  // we wired into the helper). Branding service can later expose
  // `support_whatsapp` so admin can edit it via the admin panel.
  const supportWhatsapp = (branding as any)?.support_whatsapp || DEFAULT_SUPPORT_WHATSAPP;
  const appName = branding?.app_name || "Slangcart";
  const router = useRouter();
  const [data, setData] = useState<Dashboard | null>(null);
  const [recentNotifs, setRecentNotifs] = useState<Notif[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  // When the user taps the Total Earnings card body, expand to reveal
  // all the secondary dashboard sections. Withdraw button stays out of
  // the toggle area.
  const [expanded, setExpanded] = useState(false);
  // Vendor-only stats — populated only when current user is an approved vendor
  const [vendorStats, setVendorStats] = useState<{
    today_earnings: number; today_orders: number; total_earnings: number;
    products_count: number; published_count: number;
  } | null>(null);
  const [pendingQA, setPendingQA] = useState<number>(0);
  // Sept 2026 — My-orders inline hero (owner ask). Top ~3 orders shown
  // right on dashboard so users don't have to drill into a subpage.
  const [myOrders, setMyOrders] = useState<any[] | null>(null);
  // ─── Service Provider availability quick-toggle (June 2026) ───
  // When the logged-in user is an approved Service Provider we show a
  // prominent Available / Busy / Offline strip on the Dashboard so they
  // can flip status in one tap (vs. drilling into Profile → Availability).
  const { refresh: refreshUser } = useAuth();
  const [availSaving, setAvailSaving] = useState<"available" | "busy" | "offline" | null>(null);
  const isProvider = !!(user as any)?.is_service_provider || (user as any)?.service_status === "approved";
  const availStatus: "available" | "busy" | "offline" =
    (((user as any)?.availability_status as "available" | "busy" | "offline") || "available");

  const setAvailability = useCallback(async (s: "available" | "busy" | "offline") => {
    if (s === availStatus) return;
    setAvailSaving(s);
    try {
      await api.patch("/services/me/availability", { status: s });
      try { await refreshUser(); } catch {}
      // Tie the 30-min background location heartbeat to availability:
      //   Available / Busy → start tracker + push a fresh fix right away so
      //                      customers see the new distance immediately.
      //   Offline          → stop the tracker (we won't be shown in search
      //                      anyway, so save the user's battery).
      if (s === "offline") {
        stopBackgroundProviderLocation().catch(() => {});
      } else {
        startBackgroundProviderLocation().catch(() => {});
        pushLocationNow().catch(() => {});
      }
    } catch (e: any) {
      // Soft-fail — keep the previous state visually
    } finally {
      setAvailSaving(null);
    }
  }, [availStatus, refreshUser]);

  // On mount (and whenever provider/availability flips) make sure the
  // background tracker reflects the current state. Critical for cold app
  // launches and post-install upgrades where the OS-level registration may
  // have been cleared.
  useEffect(() => {
    if (!isProvider) {
      stopBackgroundProviderLocation().catch(() => {});
      return;
    }
    if (availStatus === "offline") {
      stopBackgroundProviderLocation().catch(() => {});
    } else {
      // Idempotent — won't restart if already running.
      startBackgroundProviderLocation().catch(() => {});
    }
  }, [isProvider, availStatus]);

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
    // Vendor stats fetched separately so a non-vendor 403 doesn't disrupt
    // the main dashboard load. Silent on error.
    try {
      const [vs, vq] = await Promise.all([
        api.get<any>("/vendor/me/stats"),
        api.get<{ pending_count: number }>("/vendor/me/questions").catch(() => ({ data: { pending_count: 0 } as any })),
      ]);
      setVendorStats(vs.data || null);
      setPendingQA(vq.data?.pending_count || 0);
    } catch {
      // not an approved vendor — hide the card entirely
      setVendorStats(null);
      setPendingQA(0);
    }
    // Sept 2026 — Recent orders for the inline hero card. Uses the
    // stale-while-revalidate cache so the card paints instantly on
    // repeat mounts and self-updates when the network responds.
    try {
      const cached = await cachedGet<any[]>("/orders/me", {
        ttlMs: 30_000,
        onFresh: (fresh) => setMyOrders(Array.isArray(fresh) ? fresh.slice(0, 3) : []),
      });
      if (Array.isArray(cached)) setMyOrders(cached.slice(0, 3));
    } catch {
      setMyOrders([]);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onShareCode = async () => {
    if (!data?.referral_code) return;
    try {
      await Share.share({
        message: `Hi! Join Slangcart using my referral code *${data.referral_code}* and earn ₹400 for every 4 friends you bring. Sign up: slangcart.com/r/${data.referral_code}`,
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
        <View style={{ padding: spacing.screen, gap: 14 }}>
          <Skeleton width="50%" height={14} />
          <View style={{ height: 4 }} />
          <Skeleton width="70%" height={26} />
          <View style={{ height: 16 }} />
          <SkeletonCard height={170} />
          <SkeletonCard height={110} />
          <View style={{ flexDirection: "row", gap: 10 }}>
            <SkeletonCard height={92} style={{ flex: 1 }} />
            <SkeletonCard height={92} style={{ flex: 1 }} />
          </View>
          <SkeletonRow />
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

        <Animated.View entering={FadeInDown.duration(400).delay(80)} style={{ height: 6 }} />

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

        {/* WhatsApp welcome card — added 2026-06-10.
            Lets the user tap once to open WhatsApp with a pre-filled
            "Hi Slangcart, I just registered as <name>" message going to
            the admin support number. Free (uses wa.me URL scheme), works
            on every device with WhatsApp installed. */}
        <TouchableOpacity
          onPress={() => openWhatsApp(
            buildWelcomeMessage({
              name: user?.name,
              referral_code: user?.referral_code,
              app_name: appName,
            }),
            supportWhatsapp,
          )}
          activeOpacity={0.85}
          style={styles.waCard}
          testID="dashboard-whatsapp-welcome"
        >
          <View style={styles.waIconWrap}>
            <Feather name="message-circle" size={22} color="#FFFFFF" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.waTitle}>Chat with us on WhatsApp</Text>
            <Text style={styles.waSub} numberOfLines={2}>
              Send your welcome message & get instant support from our team.
            </Text>
          </View>
          <Feather name="chevron-right" size={20} color="#FFFFFF" />
        </TouchableOpacity>

        {/* === Compact Total Earnings card === */}
        {/* The card body is tappable: it toggles the expanded sections.
            The Withdraw button is OUTSIDE the toggle area so taps go to wallet. */}
        <Animated.View entering={FadeInDown.duration(450).delay(120)}>
          <GradientCard variant="emerald" style={styles.heroCardCompact}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
              <TouchableOpacity
                activeOpacity={0.85}
                style={{ flex: 1 }}
                onPress={() => setExpanded((e) => !e)}
                testID="dashboard-earnings-toggle"
              >
                <Text style={styles.heroLabelCompact}>TOTAL EARNINGS</Text>
                <Text style={styles.heroAmountCompact} testID="dashboard-total-earned">
                  {formatINR(data.total_earned)}
                </Text>
                <View style={styles.heroSubRow}>
                  <Feather name="credit-card" size={11} color="rgba(255,255,255,0.85)" />
                  <Text style={styles.heroSubText} testID="dashboard-wallet-balance">
                    Wallet {formatINR(data.wallet_balance)}
                  </Text>
                  <View style={styles.expandPill}>
                    <Feather name={expanded ? "chevron-up" : "chevron-down"} size={11} color="#fff" />
                    <Text style={styles.expandPillText}>{expanded ? "Hide" : "Details"}</Text>
                  </View>
                </View>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => router.push("/(tabs)/wallet")}
                style={styles.withdrawBtnCompact}
                testID="dashboard-withdraw-btn"
              >
                <Feather name="arrow-up-right" size={14} color={colors.accentFg} />
                <Text style={styles.withdrawBtnText}>Withdraw</Text>
              </TouchableOpacity>
            </View>
          </GradientCard>
        </Animated.View>

        {/* === Vendor Panel preview — only visible for approved vendors === */}
        {vendorStats ? (
          <Animated.View entering={FadeInDown.duration(380).delay(30)}>
            <TouchableOpacity
              activeOpacity={0.9}
              onPress={() => router.push("/vendor/dashboard" as any)}
              style={styles.vendorPreview}
              testID="dashboard-vendor-preview"
            >
              <View style={styles.vendorPreviewHead}>
                <View style={styles.vendorPreviewIcon}>
                  <Feather name="briefcase" size={16} color={colors.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.vendorPreviewEyebrow}>VENDOR PANEL</Text>
                  <Text style={styles.vendorPreviewTitle}>Today {formatINR(vendorStats.today_earnings)}</Text>
                </View>
                {pendingQA > 0 ? (
                  <View style={styles.vendorPreviewBadge}>
                    <Feather name="message-circle" size={11} color="#fff" />
                    <Text style={styles.vendorPreviewBadgeText}>{pendingQA}</Text>
                  </View>
                ) : null}
                <Feather name="chevron-right" size={18} color={colors.textMuted} />
              </View>
              <View style={styles.vendorPreviewStats}>
                <VendorMini icon="package" label="Today orders" value={String(vendorStats.today_orders)} />
                <VendorMini icon="trending-up" label="Lifetime" value={formatINR(vendorStats.total_earnings)} />
                <VendorMini icon="box" label="Products" value={`${vendorStats.published_count}/${vendorStats.products_count}`} />
              </View>
              {pendingQA > 0 ? (
                <View style={styles.vendorPreviewAlert}>
                  <Feather name="alert-circle" size={11} color="#B45309" />
                  <Text style={styles.vendorPreviewAlertText}>
                    {pendingQA} customer question{pendingQA === 1 ? "" : "s"} awaiting reply
                  </Text>
                </View>
              ) : null}
            </TouchableOpacity>
          </Animated.View>
        ) : null}

        {/* === Service Provider availability quick-toggle === */}
        {/* June 2026 — Approved providers see this prominent strip on the
            Dashboard so they can flip Available / Busy / Offline in one tap.
            Offline = hidden from customer search, Busy = badge + still bookable,
            Available = normal listing.
            We tolerate two slightly different "approved" shapes from auth/me:
            `is_service_provider:true` (modern) and `service_status:"approved"`
            (legacy). */}
        {isProvider ? (
          <Animated.View entering={FadeInDown.duration(380).delay(60)}>
            <View style={styles.availCard}>
              <View style={styles.availHead}>
                <View style={[styles.availIcon, {
                  backgroundColor: availStatus === "available" ? "#DCFCE7" : availStatus === "busy" ? "#FEF3C7" : "#E5E7EB",
                }]}>
                  <Feather
                    name={availStatus === "available" ? "check-circle" : availStatus === "busy" ? "clock" : "power"}
                    size={16}
                    color={availStatus === "available" ? "#16A34A" : availStatus === "busy" ? "#B45309" : "#374151"}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.availEyebrow}>MY AVAILABILITY</Text>
                  <Text style={styles.availTitle}>
                    {availStatus === "available" ? "Available — customers can find you"
                      : availStatus === "busy" ? "Busy — still bookable, may delay"
                      : "Offline — hidden from search"}
                  </Text>
                </View>
              </View>
              <View style={styles.availPickerRow}>
                {(["available", "busy", "offline"] as const).map((opt) => {
                  const active = availStatus === opt;
                  const saving = availSaving === opt;
                  const meta = opt === "available"
                    ? { c: "#16A34A", bg: "#DCFCE7", label: "Available" }
                    : opt === "busy"
                    ? { c: "#B45309", bg: "#FEF3C7", label: "Busy" }
                    : { c: "#374151", bg: "#E5E7EB", label: "Offline" };
                  return (
                    <TouchableOpacity
                      key={opt}
                      onPress={() => setAvailability(opt)}
                      disabled={!!availSaving}
                      activeOpacity={0.85}
                      style={[
                        styles.availPickerBtn,
                        active && { backgroundColor: meta.bg, borderColor: meta.c },
                      ]}
                      testID={`dashboard-avail-${opt}`}
                    >
                      {saving ? (
                        <ActivityIndicator size="small" color={meta.c} />
                      ) : (
                        <>
                          <View style={[styles.availDot, { backgroundColor: meta.c }]} />
                          <Text style={[styles.availPickerText, active && { color: meta.c, fontWeight: "900" }]}>
                            {meta.label}
                          </Text>
                        </>
                      )}
                    </TouchableOpacity>
                  );
                })}
              </View>
            </View>
          </Animated.View>
        ) : null}

        {/* === Expanded sections — only when user taps Total Earnings === */}
        {expanded && (<>
        <Animated.View entering={FadeInDown.duration(350).delay(40)}>
          <TouchableOpacity
            activeOpacity={0.85}
            onPress={() => router.push("/(tabs)/network" as any)}
            style={styles.progressCard}
            testID="dashboard-next-payout-card"
          >
            <View style={{ flexDirection: "row", alignItems: "center", gap: 16 }}>
              <DonutProgress
                value={data.directs_required - data.next_payout_in}
                max={data.directs_required}
                size={104}
                strokeWidth={12}
                color={colors.primary}
                label={`${data.direct_referrals % data.directs_required}/${data.directs_required}`}
                sublabel="DIRECTS"
              />
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                  <Text style={styles.cardTitle}>Next L1 payout</Text>
                  <Feather name="chevron-right" size={18} color={colors.textMuted} />
                </View>
                <Text style={styles.bigPrice}>{formatINR(data.level_payouts.l1)}</Text>
                <Text style={styles.progressInfo}>
                  Refer <Text style={styles.bold}>{data.next_payout_in}</Text> more direct{data.next_payout_in === 1 ? "" : "s"} to unlock.
                </Text>
              </View>
            </View>
            <View style={styles.levelsRow}>
              <View style={styles.levelChip}><Text style={styles.levelChipLabel}>L1</Text><Text style={styles.levelChipValue}>{formatINR(data.level_payouts.l1)}</Text></View>
              <View style={styles.levelChip}><Text style={styles.levelChipLabel}>L2</Text><Text style={styles.levelChipValue}>{formatINR(data.level_payouts.l2)}</Text></View>
              <View style={styles.levelChip}><Text style={styles.levelChipLabel}>L3</Text><Text style={styles.levelChipValue}>{formatINR(data.level_payouts.l3)}</Text></View>
            </View>
          </TouchableOpacity>
        </Animated.View>

        {/* Sparkline - earnings last 7 days */}
        {Array.isArray(data.earnings_per_day) && data.earnings_per_day.length > 0 && (
          <Animated.View entering={FadeInDown.duration(450).delay(220)} style={styles.chartCard}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
              <View>
                <Text style={styles.chartLabel}>LAST 7 DAYS</Text>
                <Text style={styles.chartTitle}>Earnings trend</Text>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.chartTotal}>{formatINR(data.earnings_per_day.reduce((a, b) => a + b, 0))}</Text>
                <Text style={styles.chartTotalLabel}>total this week</Text>
              </View>
            </View>
            <View style={{ marginTop: 14 }}>
              <Sparkline data={data.earnings_per_day} width={300} height={88} strokeColor={colors.primary} fillFrom="rgba(20,61,46,0.28)" fillTo="rgba(20,61,46,0.0)" />
              <View style={styles.dayLabelsRow}>
                {(data.day_labels || []).map((d, i) => (
                  <Text key={i} style={styles.dayLabel}>{d}</Text>
                ))}
              </View>
            </View>
          </Animated.View>
        )}

        {/* Bar chart - level breakdown */}
        {data.level_breakdown && Object.values(data.level_breakdown).some((v) => (v as number) > 0) && (
          <Animated.View entering={FadeInDown.duration(450).delay(260)} style={styles.chartCard}>
            <Text style={styles.chartLabel}>EARNINGS BY LEVEL</Text>
            <Text style={styles.chartTitle}>Where it's coming from</Text>
            <View style={{ marginTop: 14, alignItems: "center" }}>
              <BarChart
                data={Object.values(data.level_breakdown) as number[]}
                labels={["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10"]}
                width={320}
                height={170}
                color={colors.primary}
              />
            </View>
          </Animated.View>
        )}

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

          {/* Sept 2026 — Inline recent-orders hero. Shows the top 3
              orders with product image + status pill directly on the
              dashboard, per owner request. */}
          {myOrders && myOrders.length > 0 ? (
            <View style={styles.orderHeroBox}>
              <View style={styles.orderHeroHeader}>
                <Text style={styles.sectionLabel}>MY ORDERS</Text>
                <TouchableOpacity onPress={() => router.push("/orders")} testID="dashboard-orders-viewall">
                  <Text style={styles.viewAll}>View all</Text>
                </TouchableOpacity>
              </View>
              {myOrders.slice(0, 3).map((o: any) => {
                const items: any[] = Array.isArray(o.items) ? o.items : [];
                const first = items[0] || {};
                const more = Math.max(0, items.length - 1);
                const status = String(o.status || "placed");
                const statusColors: Record<string, string> = {
                  placed: colors.warning || "#F59E0B",
                  shipped: colors.brand500 || colors.primary,
                  delivered: colors.success || "#16A34A",
                  cancelled: "#B91C1C",
                };
                return (
                  <TouchableOpacity
                    key={o.id}
                    style={styles.orderHeroCard}
                    onPress={() => router.push({ pathname: "/orders", params: { highlight: o.id } } as any)}
                    testID={`order-hero-${o.id}`}
                  >
                    {first.image_url ? (
                      <Image source={{ uri: first.image_url }} style={styles.orderHeroThumb} />
                    ) : (
                      <View style={[styles.orderHeroThumb, { alignItems: "center", justifyContent: "center" }]}>
                        <Feather name="image" size={16} color={colors.textMuted} />
                      </View>
                    )}
                    <View style={{ flex: 1 }}>
                      <Text style={styles.orderHeroName} numberOfLines={1}>{first.name || "Order"}</Text>
                      {more > 0 ? (
                        <Text style={styles.orderHeroMore}>+ {more} more item{more > 1 ? "s" : ""} — tap for details</Text>
                      ) : (
                        <Text style={styles.orderHeroMore}>{first.qty || 1} × {formatINR(first.price || 0)}</Text>
                      )}
                      <View style={styles.orderHeroBottom}>
                        <View style={[styles.orderHeroPill, { backgroundColor: statusColors[status] || colors.textMuted }]}>
                          <Text style={styles.orderHeroPillText}>{status.toUpperCase()}</Text>
                        </View>
                        <Text style={styles.orderHeroTotal}>{formatINR(o.total || 0)}</Text>
                      </View>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </View>
          ) : null}

          <TouchableOpacity style={styles.quickRow} onPress={() => router.push("/wishlist" as any)} testID="dashboard-wishlist">
            <View style={styles.quickIcon}><Feather name="heart" size={16} color={colors.primary} /></View>
            <Text style={styles.quickText}>My wishlist</Text>
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
        </>)}
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

function VendorMini({ icon, label, value }: { icon: any; label: string; value: string }) {
  return (
    <View style={styles.vendorMini}>
      <Feather name={icon} size={12} color={colors.primary} />
      <View style={{ flex: 1 }}>
        <Text style={styles.vendorMiniLabel} numberOfLines={1}>{label}</Text>
        <Text style={styles.vendorMiniValue} numberOfLines={1}>{value}</Text>
      </View>
    </View>
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
  approvalBannerTitle: { fontSize: 14, fontWeight: "800" } as any,
  approvalBannerSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  // WhatsApp welcome card — Bright green to look like WhatsApp's own brand.
  waCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
    borderRadius: 14,
    backgroundColor: "#25D366",
    marginBottom: 16,
    shadowColor: "#25D366",
    shadowOpacity: 0.25,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  waIconWrap: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: "rgba(255,255,255,0.18)",
    alignItems: "center", justifyContent: "center",
  },
  waTitle: { fontSize: 15, fontWeight: "900", color: "#FFFFFF", letterSpacing: 0.2 },
  waSub: { fontSize: 12, color: "rgba(255,255,255,0.95)", marginTop: 2 },
  approvalBannerTitle: { fontSize: 13, fontWeight: "800" },
  approvalBannerSub: { fontSize: 11, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  heroCard: { marginBottom: 16, padding: 24 },
  // ---- New compact total earnings card ----
  heroCardCompact: { marginBottom: spacing.sectionGap, padding: spacing.cardPad, borderRadius: 18 },
  heroLabelCompact: { color: "rgba(255,255,255,0.75)", fontSize: 10, letterSpacing: 1.6, fontWeight: "800" },
  heroAmountCompact: { color: colors.primaryFg, fontSize: 26, fontWeight: "900", marginTop: 2, letterSpacing: -0.8 },
  heroSubRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  heroSubText: { color: "rgba(255,255,255,0.85)", fontSize: 11, fontWeight: "700" },
  expandPill: {
    flexDirection: "row", alignItems: "center", gap: 3,
    marginLeft: 6,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.18)",
  },
  expandPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.4 },
  withdrawBtnCompact: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.accent,
    paddingHorizontal: 12, paddingVertical: 9,
    borderRadius: 999,
  },
  heroDecor: { position: "absolute", right: -40, top: -40, width: 160, height: 160, borderRadius: 80, backgroundColor: "rgba(229,122,68,0.18)" },
  heroLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  heroAmount: { color: colors.primaryFg, fontSize: 44, fontWeight: "800", marginTop: 6, letterSpacing: -1.5 },
  heroBottom: { marginTop: 16, flexDirection: "row", justifyContent: "space-between", alignItems: "flex-end" },
  heroSubLabel: { color: "rgba(255,255,255,0.6)", fontSize: 12 },
  heroSubValue: { color: colors.primaryFg, fontSize: 18, fontWeight: "700", marginTop: 2 },
  withdrawBtn: { flexDirection: "row", alignItems: "center", backgroundColor: colors.accent, paddingHorizontal: 16, paddingVertical: 10, borderRadius: radii.button, gap: 4 },
  withdrawBtnText: { color: colors.accentFg, fontWeight: "700", fontSize: 13 },
  bigPrice: { fontSize: 24, fontWeight: "800", color: colors.primary, marginTop: 4, letterSpacing: -0.5 },
  chartCard: { backgroundColor: colors.surface, borderRadius: radii.card, padding: 16, marginBottom: 16, borderWidth: 1, borderColor: colors.border },
  chartLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800" },
  chartTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  chartTotal: { fontSize: 18, fontWeight: "800", color: colors.primary, letterSpacing: -0.5 },
  chartTotalLabel: { fontSize: 10, color: colors.textMuted, marginTop: 2, fontWeight: "600" },
  dayLabelsRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 6, paddingHorizontal: 4 },
  dayLabel: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  progressCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: spacing.cardPad, marginBottom: spacing.sectionGap },
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
  // Sept 2026 — Inline "My orders" hero card cluster.
  orderHeroBox: { marginTop: 10 },
  orderHeroHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  orderHeroCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  orderHeroThumb: { width: 56, height: 56, borderRadius: 10, backgroundColor: colors.surfaceMuted },
  orderHeroName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  orderHeroMore: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  orderHeroBottom: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 6 },
  orderHeroPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  orderHeroPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.6 },
  orderHeroTotal: { fontSize: 14, fontWeight: "900", color: colors.primary },
  feedItem: { flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8, gap: 10, alignItems: "flex-start" },
  feedDot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  feedTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  feedBody: { fontSize: 12, color: colors.textMuted, marginTop: 2 },

  // ─── Vendor Panel preview (only for approved vendors) ───
  vendorPreview: {
    marginTop: 14,
    backgroundColor: colors.surface,
    borderRadius: 18, padding: 14,
    borderWidth: 1, borderColor: colors.primary + "33",
    overflow: "hidden",
  },
  vendorPreviewHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  vendorPreviewIcon: {
    width: 36, height: 36, borderRadius: 12,
    backgroundColor: colors.primary + "14",
    alignItems: "center", justifyContent: "center",
  },
  vendorPreviewEyebrow: { fontSize: 9, letterSpacing: 1.5, fontWeight: "800", color: colors.primary },
  vendorPreviewTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain, marginTop: 1, letterSpacing: -0.3 },
  vendorPreviewBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#E11D48",
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
  },
  vendorPreviewBadgeText: { fontSize: 11, fontWeight: "800", color: "#fff" },

  vendorPreviewStats: {
    flexDirection: "row", gap: 8,
    marginTop: 12,
  },
  vendorMini: {
    flex: 1, flexDirection: "row", gap: 6, alignItems: "center",
    backgroundColor: colors.surfaceMuted,
    paddingHorizontal: 10, paddingVertical: 9,
    borderRadius: 10,
  },
  vendorMiniLabel: { fontSize: 9, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.4, textTransform: "uppercase" },
  vendorMiniValue: { fontSize: 12, fontWeight: "800", color: colors.textMain, marginTop: 1 },

  vendorPreviewAlert: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 10, paddingVertical: 8, paddingHorizontal: 10,
    backgroundColor: "#FEF3C7", borderRadius: 10,
  },
  vendorPreviewAlertText: { fontSize: 11, fontWeight: "700", color: "#92400E", flex: 1 },
  // ── Service Provider availability quick-toggle (June 2026) ──
  availCard: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
    padding: 14,
    marginTop: 14,
  },
  availHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  availIcon: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  availEyebrow: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800" },
  availTitle: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 2 },
  availPickerRow: { flexDirection: "row", gap: 8 },
  availPickerBtn: {
    flex: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6,
    paddingVertical: 10, paddingHorizontal: 8,
    borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1, borderColor: colors.border,
  },
  availDot: { width: 8, height: 8, borderRadius: 4 },
  availPickerText: { fontSize: 12, color: colors.textMuted, fontWeight: "700" },
});
