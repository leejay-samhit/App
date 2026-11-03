// Subscription (₹118 membership) UI kit — Jun-2026 "green crystal glass".
//
// One payment of ₹118: ₹18 is GST, ₹50 comes straight back into the member's
// wallet, and the rest is the platform's. Everything a member gets — and
// everything a free account does NOT — is described by the backend
// (`GET /subscription/config`) so the paywall can never promise a number the
// ledger would not actually book.
//
// The look: a layered green crystal-glass hero (LinearGradient + translucent
// highlight/glow Views — no backdrop-filter, which React Native has no answer
// for), gold accents on the money, and a deliberately flat, grey, locked
// treatment for the free state so the difference reads at one glance.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert, Modal, Linking, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import { api } from "./api";
import { useAuth } from "./auth";
import { colors, radii, formatINR } from "./theme";
import { useBranding, useFestival } from "./branding";

// ── crystal palette (subscription surfaces only — the rest of the app keeps
// the house green from theme.ts) ───────────────────────────────────────────
// Oct-2026 — the membership card's emerald/gold "crystal" look is part of the
// Slangcart brand, so it stays put on the default theme. Under a festival
// theme the gradient follows the festival's hero colours instead, otherwise a
// bright green slab sits in the middle of a Deepavali home screen. The glass
// highlights, gold and ice tints are shared by both looks.
export const CRYSTAL = {
  g1: "#10B981",
  g2: "#0B6B4F",
  g3: "#042F2E",
  border: "rgba(255,255,255,0.25)",
  highlight: "rgba(255,255,255,0.40)",
  glass: "rgba(255,255,255,0.12)",
  glassStrong: "rgba(255,255,255,0.18)",
  gold: "#FCD34D",
  ice: "#D1FAE5",
  iceDim: "#A7F3D0",
};

/** Hook: the three gradient stops for the membership card. */
function useCrystalGradient(): [string, string, string] {
  const { gradient } = useBranding();
  const festival = useFestival();
  if (festival && gradient?.start && gradient?.middle && gradient?.end) {
    return [gradient.middle, gradient.start, gradient.end];
  }
  return [CRYSTAL.g1, CRYSTAL.g2, CRYSTAL.g3];
}

export type Benefit = {
  key: string;
  icon: keyof typeof Feather.glyphMap;
  title: string;
  sub: string;
  free_text: string;
  whatsapp?: string;
};

export type SubscriptionConfig = {
  price: number;
  gst: number;
  net: number;
  cashback_pct: number;
  member_cashback: number;
  invite_bonus: number;
  platform_revenue: number;
  benefits: Benefit[];
  support_whatsapp: string;
  app_name: string;
  is_subscriber: boolean;
  subscription_skipped: boolean;
};

const FALLBACK: SubscriptionConfig = {
  price: 118, gst: 18, net: 100, cashback_pct: 50, member_cashback: 50,
  invite_bonus: 25, platform_revenue: 50, benefits: [], support_whatsapp: "",
  app_name: "Slangcart", is_subscriber: false, subscription_skipped: false,
};

// ── shared config (one fetch per app session, refreshable) ────────────────
const Ctx = createContext<{
  config: SubscriptionConfig;
  loading: boolean;
  reload: () => Promise<void>;
} | null>(null);

export function SubscriptionProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [config, setConfig] = useState<SubscriptionConfig>(FALLBACK);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const { data } = await api.get<SubscriptionConfig>("/subscription/config");
      if (data) setConfig({ ...FALLBACK, ...data });
    } catch {
      // keep whatever we had — the paywall still renders with FALLBACK
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { reload(); }, [reload]);

  const value = useMemo(() => ({ config, loading, reload }), [config, loading, reload]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Membership state + the live ₹ split. Safe to call anywhere under AuthProvider. */
export function useSubscription() {
  const ctx = useContext(Ctx);
  const { user } = useAuth();
  const isMember = !!user?.registration_paid;
  const isAdmin = (user as any)?.role === "admin";
  return {
    config: ctx?.config ?? FALLBACK,
    loading: ctx?.loading ?? false,
    reload: ctx?.reload ?? (async () => {}),
    isMember,
    isAdmin,
    // Admins are never upsold.
    showUpsell: !!user && !isAdmin && !isMember,
  };
}

// ── atoms ────────────────────────────────────────────────────────────────

/** The glass layers every crystal surface shares. */
function CrystalSkin({ radius = 24 }: { radius?: number }) {
  return (
    <>
      <View pointerEvents="none" style={[styles.skinGlow, { borderRadius: radius }]} />
      <View pointerEvents="none" style={[styles.skinSheen, { borderTopLeftRadius: radius, borderTopRightRadius: radius }]} />
      <View pointerEvents="none" style={[styles.skinEdge, { borderRadius: radius }]} />
    </>
  );
}

export function MemberBadge({ small }: { small?: boolean }) {
  return (
    <View style={[styles.badge, small && styles.badgeSmall]} testID="member-badge">
      <Feather name="award" size={small ? 10 : 12} color={CRYSTAL.g3} />
      <Text style={[styles.badgeText, small && { fontSize: 9 }]}>  MEMBER</Text>
    </View>
  );
}

export function FreeBadge({ small }: { small?: boolean }) {
  return (
    <View style={[styles.freeBadge, small && styles.badgeSmall]} testID="free-badge">
      <Feather name="lock" size={small ? 10 : 12} color={colors.textMuted} />
      <Text style={[styles.freeBadgeText, small && { fontSize: 9 }]}>  FREE ACCOUNT</Text>
    </View>
  );
}

/**
 * Green crystal-glass hero. `variant="paywall"` sells the subscription;
 * `variant="member"` congratulates someone who already paid.
 */
export function SubscriptionHero({
  amount,
  appName,
  variant = "paywall",
}: { amount?: number; appName?: string; variant?: "paywall" | "member" }) {
  const { config } = useSubscription();
  const price = amount ?? config.price;
  const member = variant === "member";
  const grad = useCrystalGradient();
  return (
    <LinearGradient
      colors={grad}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.hero}
      testID="subscription-hero"
    >
      <CrystalSkin />
      <View style={styles.heroTagRow}>
        <View style={styles.heroTag}>
          <Feather name={member ? "check-circle" : "award"} size={11} color={CRYSTAL.gold} />
          <Text style={styles.heroTagText}>  {member ? "ACTIVE MEMBERSHIP" : "MEMBERSHIP"}</Text>
        </View>
        {appName ? <Text style={styles.heroBrand}>{appName.toUpperCase()}</Text> : null}
      </View>

      {member ? (
        <>
          <Text style={styles.heroTitleBig}>You&apos;re a member</Text>
          <Text style={styles.heroSub}>
            Unlimited service numbers, zero ads, priority support and cashback on every
            delivered order — all active on this account.
          </Text>
        </>
      ) : (
        <>
          <View style={styles.heroPriceRow}>
            <Text style={styles.heroAmount}>{formatINR(price)}</Text>
            <View style={styles.heroOnce}>
              <Text style={styles.heroOnceText}>ONE TIME</Text>
            </View>
          </View>
          <Text style={styles.heroTitle}>
            Become a member and get {formatINR(config.member_cashback)} back instantly
          </Text>
          <Text style={styles.heroSub}>
            {formatINR(config.member_cashback)} of your {formatINR(price)} lands in your
            wallet the moment the payment succeeds.
          </Text>
        </>
      )}

      <View style={styles.heroPillRow}>
        <View style={styles.heroPill}>
          <Feather name="zap" size={11} color={CRYSTAL.gold} />
          <Text style={styles.heroPillText}>  {Math.round(config.cashback_pct)}% back instantly</Text>
        </View>
        <View style={styles.heroPill}>
          <Feather name="phone-call" size={11} color={CRYSTAL.ice} />
          <Text style={styles.heroPillText}>  Unlimited numbers</Text>
        </View>
        <View style={styles.heroPill}>
          <Feather name="slash" size={11} color={CRYSTAL.ice} />
          <Text style={styles.heroPillText}>  Zero ads</Text>
        </View>
      </View>
    </LinearGradient>
  );
}

/**
 * The benefit list. On the paywall it shows member-vs-free side by side so the
 * gap is obvious; for a member every row reads as unlocked.
 */
export function SubscriptionBenefits({ compact }: { compact?: boolean }) {
  const { config, isMember } = useSubscription();
  const all = config.benefits?.length ? config.benefits : [];
  const rows = compact ? all.slice(0, 3) : all;
  if (!rows.length) return null;
  return (
    <View style={styles.benefitsCard} testID="subscription-benefits">
      <View style={styles.benefitsHead}>
        <Text style={styles.benefitsTitle}>What you get</Text>
        {isMember ? <MemberBadge small /> : <FreeBadge small />}
      </View>
      {rows.map((b, i) => (
        <View key={b.key || b.title} style={[styles.benefitRow, i === rows.length - 1 && { borderBottomWidth: 0 }]}>
          <View style={[styles.benefitIcon, isMember && styles.benefitIconOn]}>
            <Feather name={b.icon} size={15} color={isMember ? "#fff" : colors.primary} />
          </View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={styles.benefitTitle}>{b.title}</Text>
            <Text style={styles.benefitSub}>{b.sub}</Text>
            {!isMember && b.free_text ? (
              <View style={styles.freeRow}>
                <Feather name="x" size={11} color={colors.error} />
                <Text style={styles.freeRowText}>  Without membership: {b.free_text}</Text>
              </View>
            ) : null}
          </View>
          <Feather
            name={isMember ? "check-circle" : "lock"}
            size={16}
            color={isMember ? colors.success : colors.textMuted}
          />
        </View>
      ))}
      {compact && all.length > rows.length ? (
        <Text style={styles.benefitMore}>+{all.length - rows.length} more member benefits</Text>
      ) : null}
    </View>
  );
}

/** The ₹118 broken down exactly as the ledger books it. */
export function SubscriptionSplit() {
  const { config } = useSubscription();
  const rows: [string, number, boolean][] = [
    ["Straight back to your wallet", config.member_cashback, true],
    ["GST", config.gst, false],
    ["Platform", config.platform_revenue, false],
  ];
  return (
    <View style={styles.splitCard} testID="subscription-split">
      <Text style={styles.benefitsTitle}>Where your {formatINR(config.price)} goes</Text>
      {rows.map(([label, value, hero]) => (
        <View key={label} style={styles.splitRow}>
          <Text style={[styles.splitLabel, hero && { color: colors.textMain, fontWeight: "800" }]}>{label}</Text>
          <Text style={[styles.splitValue, hero && { color: colors.success }]}>{formatINR(value)}</Text>
        </View>
      ))}
      {config.invite_bonus > 0 ? (
        <Text style={styles.splitNote}>
          Invite a friend and {formatINR(config.invite_bonus)} of the platform&apos;s share comes to
          your wallet when they subscribe.
        </Text>
      ) : null}
    </View>
  );
}

/**
 * "Continue without subscription" — records the choice on the server so the
 * user is never sent back to the payment wall on the next launch.
 */
export function SkipSubscriptionButton({ amount }: { amount: number }) {
  const router = useRouter();
  const { refresh } = useAuth();
  const { config } = useSubscription();
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const go = async () => {
    setBusy(true);
    try {
      await api.post("/payment/skip-subscription");
      await refresh();
      router.replace("/(tabs)/shop" as any);
    } catch (e: any) {
      // Surface the real reason (e.g. the mobile-verification gate returning
      // 403) instead of blaming the connection.
      const detail = e?.response?.data?.detail || e?.data?.detail || e?.message;
      Alert.alert(
        "Could not continue",
        typeof detail === "string" && detail
          ? detail
          : "Please check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <TouchableOpacity
        onPress={() => setConfirmOpen(true)}
        disabled={busy}
        style={styles.skipBtn}
        testID="skip-subscription"
      >
        {busy ? <ActivityIndicator color={colors.primary} size="small" /> : (
          <>
            <Feather name="arrow-right-circle" size={16} color={colors.primary} />
            <Text style={styles.skipBtnText}>Continue Without Fee</Text>
          </>
        )}
      </TouchableOpacity>

      <Modal visible={confirmOpen} transparent animationType="fade" statusBarTranslucent onRequestClose={() => setConfirmOpen(false)}>
        <View style={styles.confirmOverlay}>
          <View style={styles.confirmSheet}>
            <View style={styles.confirmIcon}>
              <Feather name="info" size={22} color={colors.primary} />
            </View>
            <Text style={styles.confirmTitle}>Continue without the fee?</Text>
            <Text style={styles.confirmBody}>
              You can browse and shop for free. The {formatINR(config.member_cashback)} instant
              cashback, free service-provider numbers, zero ads, priority support, referral
              bonus and the ability to apply as a seller, service provider or delivery
              partner all stay locked — activate anytime from your Profile.
            </Text>
            <View style={styles.confirmRow}>
              <TouchableOpacity
                onPress={() => setConfirmOpen(false)}
                style={[styles.confirmBtn, styles.confirmBtnGhost]}
                testID="skip-cancel"
              >
                <Text style={styles.confirmBtnGhostText}>Not now</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => { setConfirmOpen(false); go(); }}
                style={[styles.confirmBtn, { backgroundColor: colors.primary }]}
                testID="skip-confirm"
              >
                <Text style={styles.confirmBtnText}>Continue free</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

/** In-app upsell banner for free accounts (Shop / Dashboard / Wallet / Profile). */
export function SubscribeBanner({ compact }: { compact?: boolean }) {
  const router = useRouter();
  const { config, showUpsell } = useSubscription();
  const grad = useCrystalGradient();
  if (!showUpsell) return null;
  return (
    <TouchableOpacity
      onPress={() => router.push("/payment" as any)}
      activeOpacity={0.9}
      style={styles.bannerWrap}
      testID="subscribe-banner"
    >
      <LinearGradient
        colors={grad}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.banner}
      >
        <CrystalSkin radius={18} />
        <View style={styles.bannerIcon}>
          <Feather name="award" size={18} color={CRYSTAL.gold} />
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={styles.bannerTitle} numberOfLines={1}>
            Become a member · {formatINR(config.price)}
          </Text>
          <Text style={styles.bannerSub} numberOfLines={compact ? 2 : 3}>
            {formatINR(config.member_cashback)} back instantly, unlimited service numbers free,
            zero ads, priority support on WhatsApp.
          </Text>
        </View>
        <View style={styles.bannerCta}>
          <Text style={styles.bannerCtaText}>Join</Text>
        </View>
      </LinearGradient>
    </TouchableOpacity>
  );
}

/** Status card for Profile — crystal for a member, flat grey for a free account. */
export function MembershipCard() {
  const router = useRouter();
  const { config, isMember, isAdmin } = useSubscription();
  const grad = useCrystalGradient();
  if (isAdmin) return null;
  if (!isMember) {
    return (
      <View style={styles.flatCard} testID="membership-card-free">
        <View style={styles.flatHead}>
          <FreeBadge />
          <Text style={styles.flatPrice}>{formatINR(config.price)} one time</Text>
        </View>
        <Text style={styles.flatTitle}>You&apos;re on a free account</Text>
        <Text style={styles.flatSub}>
          Members get {formatINR(config.member_cashback)} back instantly, every service
          provider&apos;s number free, zero ads and priority support.
        </Text>
        <TouchableOpacity
          onPress={() => router.push("/payment" as any)}
          style={styles.flatBtn}
          testID="membership-upgrade"
        >
          <Feather name="award" size={15} color={colors.primaryFg} />
          <Text style={styles.flatBtnText}>Become a member</Text>
        </TouchableOpacity>
      </View>
    );
  }
  return (
    <LinearGradient
      colors={grad}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.memberCard}
      testID="membership-card-member"
    >
      <CrystalSkin radius={20} />
      <View style={styles.heroTagRow}>
        <MemberBadge />
        <Feather name="check-circle" size={16} color={CRYSTAL.gold} />
      </View>
      <Text style={styles.memberTitle}>Membership active</Text>
      <Text style={styles.memberSub}>
        Unlimited service numbers · zero ads · priority support · referral bonus
        {config.invite_bonus > 0 ? ` of ${formatINR(config.invite_bonus)}` : ""}
      </Text>
      <PrioritySupportButton />
    </LinearGradient>
  );
}

/** WhatsApp priority support — members only. */
export function PrioritySupportButton({ onLockedPress }: { onLockedPress?: () => void }) {
  const router = useRouter();
  const { config, isMember } = useSubscription();
  const number = (config.support_whatsapp || "").replace(/\D/g, "");

  const open = () => {
    if (!isMember) {
      if (onLockedPress) return onLockedPress();
      return router.push("/payment" as any);
    }
    if (!number) {
      Alert.alert("Support unavailable", "The support number is not configured yet.");
      return;
    }
    const text = encodeURIComponent("Hi, I'm a member and need help with");
    const url = `https://wa.me/${number}?text=${text}`;
    Linking.openURL(url).catch(() => Alert.alert("Could not open WhatsApp", url));
  };

  return (
    <TouchableOpacity
      onPress={open}
      style={[styles.waBtn, !isMember && styles.waBtnLocked]}
      testID="priority-support-btn"
    >
      <Feather name={isMember ? "message-circle" : "lock"} size={15} color={isMember ? "#fff" : colors.textMuted} />
      <Text style={[styles.waBtnText, !isMember && { color: colors.textMuted }]}>
        {isMember ? "Priority support on WhatsApp" : "Priority support — members only"}
      </Text>
    </TouchableOpacity>
  );
}

/** Locked-feature card for free accounts (wallet / earnings / apply screens). */
export function SubscriptionLocked({ feature }: { feature: string }) {
  const router = useRouter();
  const { config } = useSubscription();
  return (
    <View style={styles.lockedCard} testID="subscription-locked">
      <View style={styles.lockedIcon}>
        <Feather name="lock" size={22} color={colors.primary} />
      </View>
      <Text style={styles.lockedTitle}>{feature} is for members</Text>
      <Text style={styles.lockedSub}>
        Become a member for {formatINR(config.price)} — {formatINR(config.member_cashback)} comes
        straight back to your wallet, and {feature.toLowerCase()} unlocks immediately.
      </Text>
      <TouchableOpacity
        onPress={() => router.push("/payment" as any)}
        style={styles.lockedBtn}
        testID="subscription-locked-cta"
      >
        <Feather name="award" size={15} color={colors.primaryFg} />
        <Text style={styles.lockedBtnText}>Become a member · {formatINR(config.price)}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  // ── crystal skin layers ────────────────────────────────────────────────
  skinGlow: {
    position: "absolute", top: -72, right: -48, width: 200, height: 200,
    borderRadius: 100, backgroundColor: "rgba(255,255,255,0.14)",
  },
  skinSheen: {
    position: "absolute", top: 0, left: 0, right: 0, height: 64,
    backgroundColor: "rgba(255,255,255,0.07)",
  },
  skinEdge: {
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
    borderWidth: 1, borderColor: CRYSTAL.border,
  },

  hero: { borderRadius: 24, padding: 24, overflow: "hidden", marginBottom: 16 },
  heroTagRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  heroTag: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, backgroundColor: CRYSTAL.glassStrong,
    borderWidth: 1, borderColor: CRYSTAL.border,
  },
  heroTagText: { fontSize: 10, fontWeight: "900", color: CRYSTAL.gold, letterSpacing: 1.6 },
  heroBrand: { fontSize: 10, fontWeight: "800", color: "rgba(255,255,255,0.65)", letterSpacing: 1.4 },
  heroPriceRow: { flexDirection: "row", alignItems: "flex-end", gap: 8, marginTop: 16 },
  heroAmount: { fontSize: 48, fontWeight: "900", color: "#fff", letterSpacing: -1.8, lineHeight: 52 },
  heroOnce: {
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
    backgroundColor: CRYSTAL.glassStrong, borderWidth: 1, borderColor: CRYSTAL.border,
    marginBottom: 8,
  },
  heroOnceText: { fontSize: 9, fontWeight: "900", color: "#fff", letterSpacing: 1.2 },
  heroTitle: { fontSize: 16, fontWeight: "800", color: "#fff", marginTop: 8, lineHeight: 22 },
  heroTitleBig: { fontSize: 26, fontWeight: "900", color: "#fff", marginTop: 16, letterSpacing: -0.6 },
  heroSub: { fontSize: 12.5, color: CRYSTAL.ice, marginTop: 6, lineHeight: 18 },
  heroPillRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 16 },
  heroPill: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999, backgroundColor: CRYSTAL.glass,
    borderWidth: 1, borderColor: CRYSTAL.border,
  },
  heroPillText: { fontSize: 11, color: "#fff", fontWeight: "700" },

  badge: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, backgroundColor: CRYSTAL.gold,
  },
  badgeSmall: { paddingHorizontal: 8, paddingVertical: 4 },
  badgeText: { fontSize: 10, fontWeight: "900", color: CRYSTAL.g3, letterSpacing: 1.2 },
  freeBadge: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, backgroundColor: colors.surfaceMuted,
    borderWidth: 1, borderColor: colors.border,
  },
  freeBadgeText: { fontSize: 10, fontWeight: "900", color: colors.textMuted, letterSpacing: 1.2 },

  benefitsCard: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 20, padding: 16, marginBottom: 16,
  },
  benefitsHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8,
  },
  benefitsTitle: {
    fontSize: 11, fontWeight: "900", color: colors.textMuted, letterSpacing: 1.6,
    textTransform: "uppercase",
  },
  benefitRow: {
    flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  benefitIcon: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  benefitIconOn: { backgroundColor: CRYSTAL.g1 },
  benefitTitle: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  benefitSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  freeRow: { flexDirection: "row", alignItems: "center", marginTop: 4 },
  freeRowText: { fontSize: 11, fontWeight: "700", color: colors.textMuted },
  benefitMore: { fontSize: 11, fontWeight: "800", color: colors.primary, marginTop: 10 },

  splitCard: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 20, padding: 16, marginBottom: 16,
  },
  splitRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  splitLabel: { fontSize: 13, color: colors.textMuted, flex: 1, minWidth: 0 },
  splitValue: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  splitNote: { fontSize: 11.5, color: colors.textMuted, marginTop: 10, lineHeight: 16 },

  skipBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button, borderWidth: 1.5, borderColor: colors.primary,
    backgroundColor: "transparent", marginTop: 12,
  },
  skipBtnText: { fontSize: 14, fontWeight: "800", color: colors.primary },

  confirmOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", padding: 24 },
  confirmSheet: { width: "100%", maxWidth: 420, backgroundColor: colors.surface, borderRadius: 24, padding: 22 },
  confirmIcon: {
    width: 48, height: 48, borderRadius: 24, backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center", alignSelf: "center", marginBottom: 12,
  },
  confirmTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain, textAlign: "center" },
  confirmBody: { fontSize: 13, color: colors.textMuted, textAlign: "center", marginTop: 8, lineHeight: 19 },
  confirmRow: { flexDirection: "row", gap: 10, marginTop: 18 },
  confirmBtn: { flex: 1, minHeight: 48, borderRadius: radii.button, alignItems: "center", justifyContent: "center" },
  confirmBtnGhost: { backgroundColor: colors.surfaceMuted },
  confirmBtnGhostText: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  confirmBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },

  bannerWrap: { marginBottom: 16 },
  banner: {
    flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 18, padding: 14,
    overflow: "hidden",
  },
  bannerIcon: {
    width: 38, height: 38, borderRadius: 19, backgroundColor: CRYSTAL.glassStrong,
    alignItems: "center", justifyContent: "center", flexShrink: 0,
    borderWidth: 1, borderColor: CRYSTAL.border,
  },
  bannerTitle: { fontSize: 14, fontWeight: "900", color: "#fff" },
  bannerSub: { fontSize: 11.5, color: CRYSTAL.ice, marginTop: 2, lineHeight: 16 },
  bannerCta: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
    backgroundColor: CRYSTAL.gold, flexShrink: 0,
  },
  bannerCtaText: { fontSize: 12, fontWeight: "900", color: CRYSTAL.g3 },

  memberCard: { borderRadius: 20, padding: 18, overflow: "hidden", marginBottom: 16 },
  memberTitle: { fontSize: 18, fontWeight: "900", color: "#fff", marginTop: 12 },
  memberSub: { fontSize: 12, color: CRYSTAL.ice, marginTop: 4, lineHeight: 17 },

  flatCard: {
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
    borderRadius: 20, padding: 18, marginBottom: 16,
  },
  flatHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  flatPrice: { fontSize: 12, fontWeight: "800", color: colors.textMuted },
  flatTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, marginTop: 12 },
  flatSub: { fontSize: 12, color: colors.textMuted, marginTop: 4, lineHeight: 17 },
  flatBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button, backgroundColor: colors.primary, marginTop: 14,
  },
  flatBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },

  waBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button, marginTop: 16,
    backgroundColor: "#25D366",
  },
  waBtnLocked: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  waBtnText: { fontSize: 13.5, fontWeight: "800", color: "#fff" },

  lockedCard: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 20, padding: 20, alignItems: "center", marginBottom: 16,
  },
  lockedIcon: {
    width: 52, height: 52, borderRadius: 26, backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center", marginBottom: 12,
  },
  lockedTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, textAlign: "center" },
  lockedSub: { fontSize: 12.5, color: colors.textMuted, textAlign: "center", marginTop: 8, lineHeight: 18 },
  lockedBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, paddingHorizontal: 20, borderRadius: radii.button,
    backgroundColor: colors.primary, marginTop: 16,
  },
  lockedBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },
});

export const SUBSCRIPTION_PLATFORM = Platform.OS;
