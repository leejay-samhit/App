// Subscription (₹118 joining) UI kit — Aug-2026.
//
// The ₹118 is a SUBSCRIPTION, not a hard gate: a user can enter the app for
// free ("Continue without subscription") and browse + shop, but wallet,
// cashback, referral earnings and withdrawals stay locked until they pay.
//
// Everything subscription-related lives here so the payment screens, the
// in-app upsell banner and the locked states never drift apart.
import { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert, Modal } from "react-native";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { LinearGradient } from "expo-linear-gradient";
import { api } from "./api";
import { useAuth } from "./auth";
import { colors, radii, formatINR } from "./theme";

export const SUBSCRIPTION_BENEFITS: { icon: keyof typeof Feather.glyphMap; title: string; sub: string }[] = [
  { icon: "gift",        title: "Instant 50% cashback",        sub: "Get half of your joining amount back straight away" },
  { icon: "headphones",  title: "Real-time priority support",  sub: "Our team answers you first, faster" },
  { icon: "slash",       title: "Zero ads",                    sub: "A clean, distraction-free app" },
  { icon: "shopping-bag",title: "Better shopping experience",  sub: "Member-only deals and smoother checkout" },
  { icon: "star",        title: "Our priority customer",       sub: "Faster delivery handling and order help" },
  { icon: "percent",     title: "Higher cashback offers",      sub: "Member-only cashback deals on vendor products" },
  { icon: "truck",       title: "Delivery perks",              sub: "Member-only free-delivery offers" },
  { icon: "award",       title: "One payment, lifetime free",  sub: "Pay once — no renewals (T&C apply)" },
];

/** Gradient hero used at the top of both payment screens. */
export function SubscriptionHero({ amount, appName }: { amount: number; appName?: string }) {
  return (
    <LinearGradient
      colors={["#0A0E27", "#1E2A78", "#5B21B6"]}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.hero}
    >
      <View style={styles.heroGlow} pointerEvents="none" />
      <View style={styles.heroTagRow}>
        <View style={styles.heroTag}>
          <Feather name="award" size={11} color="#A5F3FC" />
          <Text style={styles.heroTagText}>  SUBSCRIPTION</Text>
        </View>
        {appName ? <Text style={styles.heroBrand}>{appName.toUpperCase()}</Text> : null}
      </View>
      <Text style={styles.heroAmount}>{formatINR(amount)}</Text>
      <Text style={styles.heroTitle}>Complete your registration with {formatINR(amount)}</Text>
      <Text style={styles.heroSub}>…and get more benefits — one payment, lifetime free (T&amp;C apply)</Text>
      <View style={styles.heroPillRow}>
        <View style={styles.heroPill}>
          <Feather name="shield" size={11} color="#A5F3FC" />
          <Text style={styles.heroPillText}>  Secure payment</Text>
        </View>
        <View style={styles.heroPill}>
          <Feather name="zap" size={11} color="#A5F3FC" />
          <Text style={styles.heroPillText}>  Instant 50% cashback</Text>
        </View>
      </View>
    </LinearGradient>
  );
}

/** The 8-benefit card. */
export function SubscriptionBenefits({ compact }: { compact?: boolean }) {
  const rows = compact ? SUBSCRIPTION_BENEFITS.slice(0, 4) : SUBSCRIPTION_BENEFITS;
  return (
    <View style={styles.benefitsCard} testID="subscription-benefits">
      <Text style={styles.benefitsTitle}>What you get</Text>
      {rows.map((b, i) => (
        <View key={b.title} style={[styles.benefitRow, i === rows.length - 1 && { borderBottomWidth: 0 }]}>
          <View style={styles.benefitIcon}>
            <Feather name={b.icon} size={15} color={colors.primary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.benefitTitle}>{b.title}</Text>
            <Text style={styles.benefitSub}>{b.sub}</Text>
          </View>
          <Feather name="check" size={15} color={colors.success} />
        </View>
      ))}
      {compact ? (
        <Text style={styles.benefitMore}>+{SUBSCRIPTION_BENEFITS.length - rows.length} more benefits</Text>
      ) : null}
    </View>
  );
}

/**
 * "Continue without subscription" — records the choice on the server so the
 * user is never sent back to the payment wall on the next launch, then drops
 * them into the Shop tab.
 */
export function SkipSubscriptionButton({ amount }: { amount: number }) {
  const router = useRouter();
  const { refresh } = useAuth();
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const go = async () => {
    setBusy(true);
    try {
      await api.post("/payment/skip-subscription");
      await refresh();
      router.replace("/(tabs)/shop" as any);
    } catch {
      Alert.alert("Could not continue", "Please check your connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  // In-app confirm sheet (not Alert.alert) so it behaves identically on
  // native and on the web preview.
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
            <Text style={styles.skipBtnText}>Continue without subscription</Text>
          </>
        )}
      </TouchableOpacity>

      <Modal visible={confirmOpen} transparent animationType="fade" statusBarTranslucent onRequestClose={() => setConfirmOpen(false)}>
        <View style={styles.confirmOverlay}>
          <View style={styles.confirmSheet}>
            <View style={styles.confirmIcon}>
              <Feather name="info" size={22} color={colors.primary} />
            </View>
            <Text style={styles.confirmTitle}>Continue without subscription?</Text>
            <Text style={styles.confirmBody}>
              You can browse and shop for free. Member-only cashback offers, delivery
              perks and priority support stay locked until you complete the {formatINR(amount)}
              subscription — you can activate it anytime from your Profile.
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

/**
 * In-app upsell banner shown to free (unsubscribed) users. Rendered on the
 * Shop / Dashboard / Wallet / Profile screens.
 */
export function SubscribeBanner({ compact }: { compact?: boolean }) {
  const router = useRouter();
  const { user } = useAuth();
  if (!user || (user as any).role === "admin" || user.registration_paid) return null;
  return (
    <TouchableOpacity
      onPress={() => router.push("/payment" as any)}
      activeOpacity={0.9}
      style={styles.bannerWrap}
      testID="subscribe-banner"
    >
      <LinearGradient
        colors={["#1E2A78", "#5B21B6"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={styles.banner}
      >
        <View style={styles.bannerIcon}>
          <Feather name="award" size={18} color="#A5F3FC" />
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={styles.bannerTitle} numberOfLines={1}>Activate subscription · ₹118</Text>
          <Text style={styles.bannerSub} numberOfLines={compact ? 1 : 2}>
            Instant 50% cashback, unlimited cashback, bank withdrawals, zero ads and priority support.
          </Text>
        </View>
        <View style={styles.bannerCta}>
          <Text style={styles.bannerCtaText}>Activate</Text>
        </View>
      </LinearGradient>
    </TouchableOpacity>
  );
}

/** Locked-feature card for free users (wallet / earnings screens). */
export function SubscriptionLocked({ feature }: { feature: string }) {
  const router = useRouter();
  return (
    <View style={styles.lockedCard} testID="subscription-locked">
      <View style={styles.lockedIcon}>
        <Feather name="lock" size={22} color={colors.primary} />
      </View>
      <Text style={styles.lockedTitle}>{feature} is a member feature</Text>
      <Text style={styles.lockedSub}>
        Complete your ₹118 subscription to unlock cashback, wallet and bank withdrawals.
        One payment, lifetime free (T&amp;C apply).
      </Text>
      <TouchableOpacity
        onPress={() => router.push("/payment" as any)}
        style={styles.lockedBtn}
        testID="subscription-locked-cta"
      >
        <Feather name="award" size={15} color={colors.primaryFg} />
        <Text style={styles.lockedBtnText}>Activate for ₹118</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  hero: { borderRadius: 24, padding: 22, overflow: "hidden", marginBottom: 16 },
  heroGlow: {
    position: "absolute", top: -60, right: -40, width: 180, height: 180,
    borderRadius: 90, backgroundColor: "rgba(34,211,238,0.18)",
  },
  heroTagRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  heroTag: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, backgroundColor: "rgba(255,255,255,0.14)",
  },
  heroTagText: { fontSize: 10, fontWeight: "900", color: "#A5F3FC", letterSpacing: 1.6 },
  heroBrand: { fontSize: 10, fontWeight: "800", color: "rgba(255,255,255,0.6)", letterSpacing: 1.4 },
  heroAmount: { fontSize: 46, fontWeight: "900", color: "#fff", letterSpacing: -1.5, marginTop: 14 },
  heroTitle: { fontSize: 15, fontWeight: "800", color: "#fff", marginTop: 6, lineHeight: 21 },
  heroSub: { fontSize: 12, color: "#C7D2FE", marginTop: 4, lineHeight: 17 },
  heroPillRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 16 },
  heroPill: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999, backgroundColor: "rgba(255,255,255,0.12)",
  },
  heroPillText: { fontSize: 11, color: "#E0E7FF", fontWeight: "700" },

  benefitsCard: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 20, padding: 16, marginBottom: 16,
  },
  benefitsTitle: {
    fontSize: 11, fontWeight: "900", color: colors.textMuted, letterSpacing: 1.6,
    textTransform: "uppercase", marginBottom: 6,
  },
  benefitRow: {
    flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 11,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  benefitIcon: {
    width: 34, height: 34, borderRadius: 17, backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  benefitTitle: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  benefitSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  benefitMore: { fontSize: 11, fontWeight: "800", color: colors.primary, marginTop: 10 },

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

  bannerWrap: { marginBottom: 14 },
  banner: { flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 18, padding: 14 },
  bannerIcon: {
    width: 38, height: 38, borderRadius: 19, backgroundColor: "rgba(255,255,255,0.14)",
    alignItems: "center", justifyContent: "center", flexShrink: 0,
  },
  bannerTitle: { fontSize: 14, fontWeight: "900", color: "#fff" },
  bannerSub: { fontSize: 11.5, color: "#C7D2FE", marginTop: 2, lineHeight: 16 },
  bannerCta: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: "#fff", flexShrink: 0 },
  bannerCtaText: { fontSize: 12, fontWeight: "900", color: "#1E2A78" },

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
