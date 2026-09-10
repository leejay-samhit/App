import { Tabs } from "expo-router";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "../../src/theme";

/**
 * ╔════════════════════════════════════════════════════════════════════╗
 * ║ ⚠ BOTTOM NAV LOCK — DO NOT add new tabs here.                     ║
 * ║                                                                    ║
 * ║ The admin bottom navigation is permanently locked to exactly 6     ║
 * ║ tabs (Home · Users · Shop · Payouts · Wallet · More).              ║
 * ║                                                                    ║
 * ║ When you add a NEW screen under /app/admin/, you MUST register     ║
 * ║ it below with `options={{ href: null }}` — otherwise Expo Router   ║
 * ║ will auto-add it as a 7th tab and break the locked layout.         ║
 * ║                                                                    ║
 * ║ Surface new screens through /admin/more.tsx instead (or via the    ║
 * ║ relevant tab screen). NEVER add another <Tabs.Screen> without      ║
 * ║ href:null unless you are intentionally replacing one of the 6.    ║
 * ╚════════════════════════════════════════════════════════════════════╝
 */
export default function AdminLayout() {
  const insets = useSafeAreaInsets();
  // Lift the tab bar above the device's navigation buttons (Android 3-button
  // nav bar / gesture pill / iOS home indicator) with a comfortable gap.
  const bottomPad = Math.max(insets.bottom, Platform.OS === "ios" ? 28 : 18);
  return (
    <Tabs
      initialRouteName="shop"
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarHideOnKeyboard: true,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          height: 62 + bottomPad,
          paddingTop: 10,
          paddingBottom: bottomPad,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600", marginTop: 2 },
        tabBarItemStyle: { paddingVertical: 4 },
      }}
    >
      <Tabs.Screen name="home" options={{ title: "Home", tabBarIcon: ({ color, size }) => <Feather name="grid" size={size} color={color} /> }} />
      <Tabs.Screen name="users" options={{ title: "Users", tabBarIcon: ({ color, size }) => <Feather name="users" size={size} color={color} /> }} />
      <Tabs.Screen name="shop" options={{ title: "Shop", tabBarIcon: ({ color, size }) => <Feather name="shopping-bag" size={size} color={color} /> }} />
      <Tabs.Screen name="payouts" options={{ title: "Payouts", tabBarIcon: ({ color, size }) => <MaterialCommunityIcons name="currency-inr" size={size} color={color} /> }} />
      <Tabs.Screen name="wallet" options={{ title: "Wallet", tabBarIcon: ({ color, size }) => <Feather name="credit-card" size={size} color={color} /> }} />
      <Tabs.Screen name="more" options={{ title: "More", tabBarIcon: ({ color, size }) => <Feather name="more-horizontal" size={size} color={color} /> }} />
      <Tabs.Screen name="transactions" options={{ href: null }} />
      <Tabs.Screen name="settings" options={{ href: null }} />
      <Tabs.Screen name="profile" options={{ href: null }} />
      <Tabs.Screen name="kyc" options={{ href: null }} />
      <Tabs.Screen name="orders" options={{ href: null }} />
      <Tabs.Screen name="audit" options={{ href: null }} />
      <Tabs.Screen name="roadmap" options={{ href: null }} />
      <Tabs.Screen name="admins" options={{ href: null }} />
      <Tabs.Screen name="approvals" options={{ href: null }} />
      <Tabs.Screen name="backups" options={{ href: null }} />
      <Tabs.Screen name="backup-file" options={{ href: null }} />
      <Tabs.Screen name="products" options={{ href: null }} />
      <Tabs.Screen name="promo-banners" options={{ href: null }} />
      <Tabs.Screen name="shop-layout" options={{ href: null }} />
      <Tabs.Screen name="branding" options={{ href: null }} />
      <Tabs.Screen name="rejected" options={{ href: null }} />
      <Tabs.Screen name="approved" options={{ href: null }} />
      <Tabs.Screen name="tickets" options={{ href: null }} />
      <Tabs.Screen name="ticket" options={{ href: null }} />
      <Tabs.Screen name="payment-gateway" options={{ href: null }} />
      <Tabs.Screen name="vendor-applications" options={{ href: null }} />
      <Tabs.Screen name="vendor-edit-requests" options={{ href: null }} />
      <Tabs.Screen name="service-applications" options={{ href: null }} />
      <Tabs.Screen name="system-wallet" options={{ href: null }} />
      <Tabs.Screen name="vendors" options={{ href: null }} />
      <Tabs.Screen name="users-tree" options={{ href: null }} />
      <Tabs.Screen name="service-management" options={{ href: null }} />
      <Tabs.Screen name="area-mapping" options={{ href: null }} />
      <Tabs.Screen name="shop-categories" options={{ href: null }} />
      <Tabs.Screen name="legal-pages" options={{ href: null }} />
      <Tabs.Screen name="payments-pending" options={{ href: null }} />
      <Tabs.Screen name="shop-category/[name]" options={{ href: null }} />
      <Tabs.Screen name="chat" options={{ href: null }} />
      <Tabs.Screen name="my-wallet" options={{ href: null }} />
      {/* June 2026 — newly added admin screens hidden from bottom tab bar.
         They are reachable from /admin/more.tsx so the bottom nav stays
         locked to: Home · Users · Shop · Payouts · Wallet · More. */}
      <Tabs.Screen name="ai-tools" options={{ href: null }} />
      <Tabs.Screen name="service-analytics" options={{ href: null }} />
      <Tabs.Screen name="subcategories/[parentId]" options={{ href: null }} />
      {/* Finance Dashboard was merged into System Wallet (2026-05-30). The
         file still exists as a redirect for old bookmarks — keep it hidden
         from the locked 6-tab bottom nav. */}
      <Tabs.Screen name="finance-dashboard" options={{ href: null }} />
      {/* June 2026 — user requested Broadcast be removed from the bottom
         tab strip; keep it reachable only via /admin/broadcast direct
         URL if needed. */}
      <Tabs.Screen name="broadcast" options={{ href: null }} />
    </Tabs>
  );
}
