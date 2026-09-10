/**
 * Scoped manager home (Sep 2026).
 *
 * When an admin promotes a user to Products / Shop Layout / Order or
 * Vendor & Service Manager, they must see ONLY their own section — not the
 * full admin panel. This screen is the entire panel for those roles: it
 * lists exactly the links their role covers, and the admin tab bar is
 * reduced to this screen plus their profile (see app/admin/_layout.tsx).
 *
 * The backend enforces the same boundary (core/security.ADMIN_AREAS), so
 * typing another admin URL by hand gets a 403 rather than data.
 */
import React from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

type Link = { label: string; hint: string; icon: any; href: string };

const ROLE_TITLE: Record<string, string> = {
  products_manager: "Products Manager",
  layout_manager: "Shop Layout Manager",
  order_manager: "Order Manager",
  vendor_service_manager: "Vendor & Service Manager",
};

const ROLE_LINKS: Record<string, Link[]> = {
  products_manager: [
    { label: "Products", hint: "Add, edit, price and publish every product", icon: "package", href: "/admin/products" },
    { label: "Categories", hint: "Shop categories and sub-categories", icon: "list", href: "/admin/shop-categories" },
    { label: "AI tools", hint: "Generate product copy and specs", icon: "cpu", href: "/admin/ai-tools" },
    { label: "Shop live preview", hint: "See the store exactly as customers do", icon: "eye", href: "/admin/shop" },
  ],
  layout_manager: [
    { label: "Shop layout", hint: "Build the home screen — banners, sliders, grids", icon: "layout", href: "/admin/shop-layout" },
    { label: "Shop live preview", hint: "Cross-check the layout you published, live", icon: "eye", href: "/admin/shop" },
    { label: "Promo banners", hint: "Offer strips and promo artwork", icon: "image", href: "/admin/promo-banners" },
  ],
  order_manager: [
    { label: "Orders", hint: "Track, update status, download order data", icon: "shopping-cart", href: "/admin/orders" },
  ],
  vendor_service_manager: [
    { label: "User approvals", hint: "Pending registrations waiting on you", icon: "user-check", href: "/admin/approvals" },
    { label: "Approved registrations", hint: "Everyone you've approved", icon: "check-circle", href: "/admin/approved" },
    { label: "Rejected registrations", hint: "Rejected applications", icon: "x-circle", href: "/admin/rejected" },
    { label: "Vendor applications", hint: "New shops asking to join", icon: "briefcase", href: "/admin/vendor-applications" },
    { label: "Vendor edit requests", hint: "Shop detail changes needing approval", icon: "edit-3", href: "/admin/vendor-edit-requests" },
    { label: "All vendors", hint: "Every shop, with status and controls", icon: "shopping-bag", href: "/admin/vendors" },
    { label: "Service applications", hint: "New service providers", icon: "tool", href: "/admin/service-applications" },
    { label: "Service management", hint: "Categories, providers, availability", icon: "sliders", href: "/admin/service-management" },
    { label: "Service analytics", hint: "Reveals, chats and the unlock fee", icon: "bar-chart-2", href: "/admin/service-analytics" },
    { label: "KYC review queue", hint: "Documents waiting for verification", icon: "shield", href: "/admin/kyc" },
  ],
};

export default function ManagerHome() {
  const router = useRouter();
  const { user } = useAuth();
  const role = String((user as any)?.admin_role || "");
  const links = ROLE_LINKS[role] || [];

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.header}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>{ROLE_TITLE[role] || "Admin"}</Text>
          <Text style={s.sub}>{user?.name || user?.email}</Text>
        </View>
        <View style={s.badge}><Text style={s.badgeText}>LIMITED ACCESS</Text></View>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}>
        <Text style={s.label}>YOUR SECTION</Text>
        {links.map((l) => (
          <TouchableOpacity
            key={l.href}
            onPress={() => router.push(l.href as any)}
            style={s.row}
            testID={`manager-link-${l.href.split("/").pop()}`}
          >
            <View style={s.icon}><Feather name={l.icon} size={17} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={s.rowTitle}>{l.label}</Text>
              <Text style={s.rowHint}>{l.hint}</Text>
            </View>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ))}
        {!links.length ? (
          <Text style={s.rowHint}>No section assigned yet — ask a super admin to set your role.</Text>
        ) : null}
        <Text style={s.footNote}>
          You have access to this section only. Other admin areas are hidden and blocked
          for your account.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.screen, paddingVertical: 14,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  sub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  badge: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, backgroundColor: colors.brand100 },
  badgeText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.8, color: colors.primary },
  label: { fontSize: 10, fontWeight: "900", letterSpacing: 1.1, color: colors.textMuted, marginBottom: 10 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12, padding: 14, marginBottom: 10,
    backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    minHeight: 64,
  },
  icon: {
    width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted,
  },
  rowTitle: { fontSize: 14.5, fontWeight: "800", color: colors.textMain },
  rowHint: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  footNote: { fontSize: 11.5, color: colors.textMuted, lineHeight: 17, marginTop: 8 },
});
