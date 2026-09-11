// /app/frontend/src/desktop-shell.tsx
// ─────────────────────────────────────────────────────────────────────────────
// DesktopShell — wraps the (tabs) navigator on wide-viewport (≥ 1024 px)
// browsers with a permanent left sidebar and a slim top app bar, giving the
// Expo-built web build a true "web app" feel instead of a tall phone bezel.
//
// Design intent
// • Same data + same screens as the mobile app (no separate routes), only the
//   chrome is different. The same router pushes/back work everywhere.
// • Mobile / tablet (< 1024 px) — render `children` directly so the bottom
//   tab bar (and any safe-area logic) keeps behaving exactly as before.
// • Desktop (≥ 1024 px) — flex row: 260 px sidebar on the left, top bar
//   above the content, content fills the rest. Bottom tab bar is hidden by
//   the parent (`(tabs)/_layout.tsx`) on desktop via `tabBarStyle.display`.
// ─────────────────────────────────────────────────────────────────────────────
import React, { useState, useCallback } from "react";
import {
  View, Text, TouchableOpacity, StyleSheet, Image, ScrollView,
  useWindowDimensions, Platform, TextInput,
} from "react-native";
import { usePathname, useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { colors } from "./theme";
import { useBranding } from "./branding";
import { useAuth } from "./auth";

const SIDEBAR_W = 260;
const TOPBAR_H = 60;
export const DESKTOP_BREAKPOINT = 1024;

/** Returns true when the current viewport is wide enough for the sidebar UI. */
export function useIsDesktop() {
  const { width } = useWindowDimensions();
  return Platform.OS === "web" && width >= DESKTOP_BREAKPOINT;
}

type NavItem = {
  key: string;
  label: string;
  icon: any;
  path: string;     // expo-router push target
  match: RegExp;    // marks the item active when current pathname matches
};

export function DesktopShell({ children }: { children: React.ReactNode }) {
  const isDesktop = useIsDesktop();
  const pathname = usePathname();
  const router = useRouter();
  const branding = useBranding();
  const { user, logout } = useAuth();
  const [query, setQuery] = useState("");

  // Build the nav list from the same five primary tabs the mobile bar shows.
  // Order: Dashboard · Shop · Services · Chat · Wallet · Network · Profile.
  // (Wallet is hidden on the mobile tab bar but it's a high-value shortcut
  // on a desktop screen so we surface it in the sidebar.)
  const items: NavItem[] = [
    { key: "dashboard", label: "Dashboard", icon: "home", path: "/(tabs)/dashboard", match: /\/dashboard/ },
    { key: "shop",      label: "Shop",      icon: "shopping-bag", path: "/(tabs)/shop", match: /\/shop|\/shop-category/ },
    { key: "services",  label: "Services",  icon: "briefcase", path: "/(tabs)/services", match: /\/services/ },
    { key: "chat",      label: "Slang-Connect", icon: "message-circle", path: "/(tabs)/chat", match: /\/chat/ },
    { key: "wallet",    label: "Wallet",    icon: "credit-card", path: "/(tabs)/wallet", match: /\/wallet/ },
    { key: "orders",    label: "My orders", icon: "package", path: "/orders", match: /\/orders/ },
    { key: "profile",   label: "Profile",   icon: "user", path: "/(tabs)/profile", match: /\/profile/ },
  ];

  // Admin-only shortcuts — only render for users with role=admin.
  const isAdmin = user?.role === "admin";
  const adminItems: NavItem[] = isAdmin ? [
    { key: "admin-overview", label: "Admin · Overview", icon: "shield",   path: "/admin", match: /\/admin$/ },
    { key: "admin-users",    label: "Users",            icon: "users",    path: "/admin/users", match: /\/admin\/users/ },
    { key: "admin-products", label: "Products",         icon: "package",  path: "/admin/products", match: /\/admin\/products/ },
    { key: "admin-orders",   label: "Orders",           icon: "shopping-cart", path: "/admin/orders", match: /\/admin\/orders/ },
    { key: "admin-broadcast", label: "Broadcast",       icon: "radio",    path: "/admin/broadcast", match: /\/admin\/broadcast/ },
    { key: "admin-branding", label: "Branding",         icon: "edit-3",   path: "/admin/branding", match: /\/admin\/branding/ },
  ] : [];

  // When on a phone-sized viewport we render children verbatim — the existing
  // mobile bottom-tab navigation continues to work as designed. Hook calls
  // below MUST be declared above this early-return (React rules-of-hooks).
  const onNav = useCallback((path: string) => {
    router.push(path as any);
  }, [router]);

  // Handler for the top-bar search box. We jump to /shop with the search
  // query as a deep link — Shop screen reads ?q from the URL.
  const onSearchSubmit = useCallback(() => {
    if (!query.trim()) return;
    router.push(`/(tabs)/shop?q=${encodeURIComponent(query.trim())}` as any);
  }, [query, router]);

  if (!isDesktop) return <>{children}</>;

  return (
    <View style={styles.root}>
      {/* ── Left sidebar ────────────────────────────────────────────── */}
      <View style={styles.sidebar}>
        <TouchableOpacity onPress={() => onNav("/(tabs)/dashboard")} style={styles.brand} activeOpacity={0.85}>
          {branding.logo_b64 ? (
            <Image source={{ uri: branding.logo_b64 }} style={styles.brandLogo} resizeMode="contain" />
          ) : (
            <View style={[styles.brandLogo, { backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" }]}>
              <Text style={{ color: "#fff", fontWeight: "900" }}>{(branding.app_name || "S")[0]}</Text>
            </View>
          )}
          <Text style={styles.brandName} numberOfLines={1}>{branding.app_name || "Slangcart"}</Text>
        </TouchableOpacity>

        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingVertical: 6 }} showsVerticalScrollIndicator={false}>
          <Text style={styles.sectionLabel}>Main</Text>
          {items.map((it) => {
            const active = it.match.test(pathname || "");
            return (
              <TouchableOpacity
                key={it.key}
                onPress={() => onNav(it.path)}
                style={[styles.navItem, active && styles.navItemActive]}
                activeOpacity={0.85}
                testID={`desktop-nav-${it.key}`}
              >
                <Feather name={it.icon} size={18} color={active ? colors.primary : colors.textMuted} />
                <Text style={[styles.navLabel, active && styles.navLabelActive]}>{it.label}</Text>
                {active ? <View style={styles.activeDot} /> : null}
              </TouchableOpacity>
            );
          })}

          {adminItems.length > 0 ? (
            <>
              <Text style={styles.sectionLabel}>Admin</Text>
              {adminItems.map((it) => {
                const active = it.match.test(pathname || "");
                return (
                  <TouchableOpacity
                    key={it.key}
                    onPress={() => onNav(it.path)}
                    style={[styles.navItem, active && styles.navItemActive]}
                    activeOpacity={0.85}
                    testID={`desktop-nav-${it.key}`}
                  >
                    <Feather name={it.icon} size={16} color={active ? colors.primary : colors.textMuted} />
                    <Text style={[styles.navLabel, active && styles.navLabelActive, { fontSize: 13 }]}>{it.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </>
          ) : null}
        </ScrollView>

        {/* User footer */}
        <View style={styles.userCard}>
          <View style={styles.userAvatar}>
            {user?.profile_image ? (
              <Image source={{ uri: user.profile_image }} style={{ width: "100%", height: "100%" }} />
            ) : (
              <Text style={{ color: colors.primary, fontWeight: "800" }}>{(user?.name || "?")[0]?.toUpperCase()}</Text>
            )}
          </View>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={styles.userName} numberOfLines={1}>{user?.name || "Guest"}</Text>
            <Text style={styles.userSub} numberOfLines={1}>#{user?.referral_code || ""}</Text>
          </View>
          <TouchableOpacity onPress={logout} style={styles.logoutBtn} testID="desktop-logout">
            <Feather name="log-out" size={16} color={colors.textMuted} />
          </TouchableOpacity>
        </View>
      </View>

      {/* ── Right column: top bar + content ─────────────────────────── */}
      <View style={styles.right}>
        <View style={styles.topbar}>
          <View style={styles.searchWrap}>
            <Feather name="search" size={16} color={colors.textMuted} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={onSearchSubmit}
              placeholder="Search products, services…"
              placeholderTextColor={colors.textMuted}
              style={styles.searchInput}
              returnKeyType="search"
              testID="desktop-search"
            />
          </View>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 14 }}>
            <TouchableOpacity onPress={() => router.push("/notifications" as any)} style={styles.topbarIconBtn}>
              <Feather name="bell" size={18} color={colors.textMain} />
            </TouchableOpacity>
            <TouchableOpacity onPress={() => router.push("/cart" as any)} style={styles.topbarIconBtn}>
              <Feather name="shopping-cart" size={18} color={colors.textMain} />
            </TouchableOpacity>
          </View>
        </View>

        {/* The Expo-router (tabs) navigator. Its bottom tab bar is hidden on
            desktop by the parent layout (`tabBarStyle.display: 'none'`). */}
        <View style={{ flex: 1 }}>{children}</View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, flexDirection: "row", backgroundColor: colors.background },
  sidebar: {
    width: SIDEBAR_W,
    backgroundColor: colors.surface,
    borderRightWidth: 1,
    borderRightColor: colors.border,
    paddingTop: 18,
  },
  brand: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 18,
    marginBottom: 6,
  },
  brandLogo: { width: 32, height: 32, borderRadius: 8 },
  brandName: { flex: 1, fontSize: 17, fontWeight: "800", color: colors.textMain },
  sectionLabel: {
    fontSize: 10,
    fontWeight: "800",
    color: colors.textMuted,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    paddingHorizontal: 18,
    marginTop: 14,
    marginBottom: 6,
  },
  navItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginHorizontal: 10,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderRadius: 10,
  },
  navItemActive: { backgroundColor: colors.brand100 },
  navLabel: { flex: 1, fontSize: 14, color: colors.textMuted, fontWeight: "600" },
  navLabelActive: { color: colors.textMain, fontWeight: "800" },
  activeDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.primary },
  userCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 12,
    margin: 10,
    borderRadius: 12,
    backgroundColor: colors.surfaceMuted,
  },
  userAvatar: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
  },
  userName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  userSub: { fontSize: 11, color: colors.textMuted, marginTop: 1 },
  logoutBtn: { padding: 6 },
  right: { flex: 1 },
  topbar: {
    height: TOPBAR_H,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  searchWrap: {
    flex: 1,
    maxWidth: 520,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surfaceMuted,
    borderRadius: 10,
    paddingHorizontal: 14,
    height: 38,
  },
  searchInput: { flex: 1, color: colors.textMain, fontSize: 14, outlineStyle: "none" as any },
  topbarIconBtn: { padding: 8, borderRadius: 8 },
});
