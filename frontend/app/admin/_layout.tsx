import { Tabs } from "expo-router";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "../../src/theme";
import { useAuth } from "../../src/auth";
import { SCOPED_ADMIN_ROLES } from "../../src/admin-roles";

/** Sep 2026 — scoped manager roles see ONLY their own section. */
const SCOPED_ROLES = SCOPED_ADMIN_ROLES;

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
  const { user } = useAuth();
  // A promoted Products / Layout / Order / Vendor-Service manager is NOT a
  // full admin: their tab bar is just their own section + profile, and the
  // backend blocks everything else (core/security.ADMIN_AREAS).
  const scoped = SCOPED_ROLES.includes(String((user as any)?.admin_role || ""));
  const tab = (visible: boolean, options: any) => (visible ? options : { href: null });
  return (
    <Tabs
      initialRouteName={scoped ? "manager-home" : "shop"}
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
      <Tabs.Screen name="home" options={tab(!scoped, { title: "Home", tabBarIcon: ({ color, size }: any) => <Feather name="grid" size={size} color={color} /> })} />
      <Tabs.Screen name="users" options={tab(!scoped, { title: "Users", tabBarIcon: ({ color, size }: any) => <Feather name="users" size={size} color={color} /> })} />
      <Tabs.Screen name="shop" options={tab(!scoped, { title: "Shop", tabBarIcon: ({ color, size }: any) => <Feather name="shopping-bag" size={size} color={color} /> })} />
      <Tabs.Screen name="payouts" options={tab(!scoped, { title: "Payouts", tabBarIcon: ({ color, size }: any) => <MaterialCommunityIcons name="currency-inr" size={size} color={color} /> })} />
      <Tabs.Screen name="wallet" options={tab(!scoped, { title: "Wallet", tabBarIcon: ({ color, size }: any) => <Feather name="credit-card" size={size} color={color} /> })} />
      <Tabs.Screen name="more" options={tab(!scoped, { title: "More", tabBarIcon: ({ color, size }: any) => <Feather name="more-horizontal" size={size} color={color} /> })} />
      <Tabs.Screen
        name="manager-home"
        options={tab(scoped, { title: "My section", tabBarIcon: ({ color, size }: any) => <Feather name="grid" size={size} color={color} /> })}
      />
      <Tabs.Screen name="transactions" options={{ href: null }} />
      <Tabs.Screen name="settings" options={{ href: null }} />
      <Tabs.Screen
        name="profile"
        options={tab(scoped, { title: "Profile", tabBarIcon: ({ color, size }: any) => <Feather name="user" size={size} color={color} /> })}
      />
      <Tabs.Screen name="kyc" options={{ href: null }} />
      <Tabs.Screen name="orders" options={{ href: null }} />
      <Tabs.Screen name="audit" options={{ href: null }} />
      <Tabs.Screen name="roadmap" options={{ href: null }} />
      <Tabs.Screen name="admins" options={{ href: null }} />
      <Tabs.Screen name="approvals" options={{ href: null }} />
      <Tabs.Screen name="backups" options={{ href: null }} />
      <Tabs.Screen name="cashback" options={{ href: null }} />
      <Tabs.Screen name="backup-file" options={{ href: null }} />
      <Tabs.Screen name="reset-center" options={{ href: null }} />
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
      {/* Sep 2026 — Phase 2 returns/reconciliation + push diagnostics.
         Reachable from /admin/more.tsx; hidden so the bottom nav stays
         locked to the 6 tabs. */}
      <Tabs.Screen name="returns" options={{ href: null }} />
      <Tabs.Screen name="push-diagnostics" options={{ href: null }} />
    </Tabs>
  );
}
