/**
 * NoVendorsHero — beautiful full-bleed hero card shown when the
 * customer's current location has no delivering vendors.
 *
 * Two-CTA layout:
 *   1) Primary  → "Become a vendor here" (routes to /vendor/apply)
 *   2) Ghost    → "Contact support" (opens mailto:support@slangcart.com)
 *
 * Designed to be dropped straight into a ScrollView / FlatList
 * ListEmptyComponent slot.  Keeps its own vertical rhythm so callers
 * don't need to add margins.
 */
import React from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, Linking, Platform,
} from "react-native";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { colors, radii } from "./theme";

export const SUPPORT_EMAIL = "support@slangcart.com";

type Props = {
  /** Pincode / area label shown in the sub-title.  Optional. */
  location?: string;
  /** Optional override CTA. */
  onBecomeVendor?: () => void;
  /** Reduce top padding when embedded inside another list. Default false. */
  compact?: boolean;
};

export function NoVendorsHero({ location, onBecomeVendor, compact }: Props) {
  const router = useRouter();

  const goToVendorApply = () => {
    if (onBecomeVendor) return onBecomeVendor();
    try { router.push("/vendor/apply" as any); } catch { /* ignore */ }
  };

  const contactSupport = () => {
    try {
      Linking.openURL(
        `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent("Interested in selling on Slangcart")}&body=${encodeURIComponent(
          `Hi Slangcart team,\n\nI would like to become a vendor and add my products${location ? ` around ${location}` : ""}.\n\nPlease share the onboarding details.\n\nThanks`,
        )}`,
      );
    } catch { /* ignore */ }
  };

  return (
    <View style={[styles.wrap, compact && { paddingTop: 0 }]} testID="no-vendors-hero">
      <View style={styles.card}>
        {/* Decorative accent strip */}
        <View style={styles.accent} />

        <View style={styles.iconBubble}>
          <MaterialCommunityIcons name="storefront-outline" size={30} color={colors.primary} />
        </View>

        <Text style={styles.eyebrow}>WE'RE NOT LIVE HERE YET</Text>
        <Text style={styles.title}>
          {location ? `No stores serving ${location} yet` : "No stores serving your area yet"}
        </Text>
        <Text style={styles.body}>
          Nobody is delivering to your pincode right now. If you'd love to sell
          in this area, apply to become a vendor and start listing your
          products — we'll help you set up your storefront in minutes.
        </Text>

        <View style={styles.perksRow}>
          <View style={styles.perk}>
            <Feather name="zap" size={14} color={colors.primary} />
            <Text style={styles.perkText}>Zero setup fee</Text>
          </View>
          <View style={styles.perk}>
            <Feather name="map-pin" size={14} color={colors.primary} />
            <Text style={styles.perkText}>Own your pincode</Text>
          </View>
          <View style={styles.perk}>
            <Feather name="trending-up" size={14} color={colors.primary} />
            <Text style={styles.perkText}>Live in 24 hrs</Text>
          </View>
        </View>

        <TouchableOpacity onPress={goToVendorApply} style={styles.primaryBtn} testID="no-vendors-become-vendor">
          <Feather name="briefcase" size={16} color={colors.primaryFg} />
          <Text style={styles.primaryBtnText}>Become a vendor here</Text>
          <Feather name="arrow-right" size={16} color={colors.primaryFg} />
        </TouchableOpacity>

        <TouchableOpacity onPress={contactSupport} style={styles.ghostBtn} testID="no-vendors-contact">
          <Feather name="mail" size={14} color={colors.primary} />
          <Text style={styles.ghostBtnText}>Contact us · {SUPPORT_EMAIL}</Text>
        </TouchableOpacity>

        {/* ─── Oct-2026: Refer-a-Retailer earning pitch ───
            Sits under the "become a vendor" CTA so a customer who can't
            shop here yet still has something valuable to do: introduce any
            shop owner they know and earn from it. */}
        <View style={styles.referBlock}>
          <View style={styles.referBadge}>
            <Feather name="gift" size={12} color={colors.accentFg} />
            <Text style={styles.referBadgeText}>EARN WITH US</Text>
          </View>
          <Text style={styles.referTitle}>Refer any retailer{"\n"}and earn with us</Text>
          <Text style={styles.referBody}>
            Know a shop owner? Invite them to sell on Slangcart. When their
            store goes live, you keep earning a share of what they sell —
            month after month.
          </Text>
          <View style={styles.referSteps}>
            <ReferStep n="1" text="Share your invite with any shop owner" />
            <ReferStep n="2" text="They list their products and go live" />
            <ReferStep n="3" text="You earn as their store keeps selling" />
          </View>
          <TouchableOpacity onPress={goToVendorApply} style={styles.referBtn} testID="no-vendors-refer-retailer">
            <Feather name="user-plus" size={16} color={colors.accentFg} />
            <Text style={styles.referBtnText}>Refer a retailer now</Text>
            <Feather name="arrow-right" size={16} color={colors.accentFg} />
          </TouchableOpacity>
        </View>

        <Text style={styles.smallPrint}>
          For more information, write to us at
          {" "}<Text style={styles.smallPrintEmail}>{SUPPORT_EMAIL}</Text>
        </Text>
      </View>
    </View>
  );
}

function ReferStep({ n, text }: { n: string; text: string }) {
  return (
    <View style={styles.referStep}>
      <View style={styles.referStepDot}>
        <Text style={styles.referStepNum}>{n}</Text>
      </View>
      <Text style={styles.referStepText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: 16, paddingTop: 24, paddingBottom: 16, alignItems: "stretch" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: 24,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    overflow: "hidden",
    ...Platform.select({
      ios: {
        shadowColor: "#0F2A1D",
        shadowOpacity: 0.08,
        shadowRadius: 18,
        shadowOffset: { width: 0, height: 8 },
      },
      android: { elevation: 3 },
      default: { boxShadow: "0px 8px 20px rgba(15,42,29,0.08)" as any },
    }),
  },
  accent: {
    position: "absolute", top: 0, left: 0, right: 0, height: 6,
    backgroundColor: colors.primary,
  },
  iconBubble: {
    width: 68, height: 68, borderRadius: 34,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
    marginTop: 6, marginBottom: 16,
  },
  eyebrow: {
    fontSize: 10, letterSpacing: 1.6, fontWeight: "800",
    color: colors.primary, textAlign: "center", marginBottom: 6,
  },
  title: {
    fontSize: 20, fontWeight: "900",
    color: colors.textMain, textAlign: "center",
    letterSpacing: -0.4, marginBottom: 10,
  },
  body: {
    fontSize: 13, color: colors.textMuted,
    textAlign: "center", lineHeight: 20,
    marginBottom: 18, maxWidth: 340,
  },
  perksRow: {
    flexDirection: "row", flexWrap: "wrap",
    justifyContent: "center", gap: 8, marginBottom: 20,
  },
  perk: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brand100,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999,
  },
  perkText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  primaryBtn: {
    width: "100%", flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary,
    paddingVertical: 14, borderRadius: 12,
    marginBottom: 10,
  },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "900", fontSize: 14, letterSpacing: -0.2 },
  ghostBtn: {
    width: "100%", flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceMuted,
  },
  ghostBtnText: { color: colors.primary, fontWeight: "800", fontSize: 12 },
  smallPrint: {
    marginTop: 12, fontSize: 11, color: colors.textMuted,
    textAlign: "center", maxWidth: 320, lineHeight: 16,
  },
  smallPrintEmail: { color: colors.primary, fontWeight: "800" },
  // ─── Refer-a-Retailer earning pitch (Oct-2026) ───
  referBlock: {
    width: "100%", marginTop: 18, padding: 18,
    borderRadius: radii.card,
    backgroundColor: colors.brand100,
    borderWidth: 1, borderColor: colors.primary,
    alignItems: "center",
  },
  referBadge: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.accent,
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, marginBottom: 10,
  },
  referBadgeText: {
    fontSize: 10, fontWeight: "900", letterSpacing: 1.2,
    color: colors.accentFg,
  },
  referTitle: {
    fontSize: 24, lineHeight: 30, fontWeight: "900",
    color: colors.primary, textAlign: "center",
    letterSpacing: -0.6, marginBottom: 8,
  },
  referBody: {
    fontSize: 13, lineHeight: 20, color: colors.textMain,
    textAlign: "center", marginBottom: 14, maxWidth: 320,
  },
  referSteps: { width: "100%", gap: 10, marginBottom: 16 },
  referStep: { flexDirection: "row", alignItems: "center", gap: 10 },
  referStepDot: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  referStepNum: { fontSize: 12, fontWeight: "900", color: colors.primaryFg },
  referStepText: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.textMain, lineHeight: 18 },
  referBtn: {
    width: "100%", flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.accent,
    paddingVertical: 15, borderRadius: 12,
  },
  referBtnText: { color: colors.accentFg, fontWeight: "900", fontSize: 15, letterSpacing: -0.2 },
});
