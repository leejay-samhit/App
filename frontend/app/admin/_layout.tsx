import { Tabs } from "expo-router";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "../../src/theme";
import { useAuth } from "../../src/auth";
import { SCOPED_ADMIN_ROLES } from "../../src/admin-roles";
import { tabIcon, TAB_LABEL_STYLE } from "../../src/tab-bar-icon";

/** Sep 2026 — scoped manager roles see ONLY their own section. */
const SCOPED_ROLES = SCOPED_ADMIN_ROLES;

/**
 * ╔════════════════════════════════════════════════════════════════════╗
 * ║ ⚠ BOTTOM NAV LOCK — DO NOT add new tabs here.                     ║
 * ║                                                                    ║
 * ║ The admin bottom navigation is permanently locked to exactly 6     ║
 * ║ tabs (Home · Users · Shop · Payouts · Wallet · More).              ║
 * ║                                                                    ║
 * ║ Jun 2026 — every time a new /app/admin/ screen was added it        ║
 * ║ auto-registered as a 7th tab (Recharge options was the latest).    ║
 * ║ So the hidden screens are now ONE list: add the file name to       ║
 * ║ HIDDEN below the moment you create the screen, and surface it      ║
 * ║ from /admin/more.tsx. Nothing else may appear in the bottom bar.   ║
 * ╚════════════════════════════════════════════════════════════════════╝
 */
// Reachable from /admin/more.tsx (or a direct link) — never in the tab bar.
const HIDDEN = [
  "transactions", "settings", "kyc", "orders", "audit", "roadmap", "admins",
  "approvals", "backups", "cashback", "backup-file", "reset-center",
  "products", "promo-banners", "shop-layout", "branding", "rejected",
  "approved", "tickets", "ticket", "payment-gateway", "vendor-applications",
  "vendor-edit-requests", "service-applications", "system-wallet", "vendors",
  "service-management", "area-mapping", "shop-categories", "legal-pages",
  "payments-pending", "shop-category/[name]", "chat", "my-wallet",
  "ai-tools", "service-analytics", "subcategories/[parentId]",
  // Finance Dashboard was merged into System Wallet (2026-05-30); the file
  // survives only as a redirect for old bookmarks.
  "finance-dashboard",
  "broadcast", "returns", "push-diagnostics", "delivery-partners",
  // Jun 2026 — owner's report: Recharge options was showing as a 7th tab.
  // It belongs in More only.
  "recharge-options",
];

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
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarHideOnKeyboard: true,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          height: 66 + bottomPad,
          paddingTop: 8,
          paddingBottom: bottomPad,
        },
        tabBarLabelStyle: TAB_LABEL_STYLE,
        tabBarItemStyle: { paddingVertical: 4 },
      }}
    >
      <Tabs.Screen name="home" options={tab(!scoped, { title: "Home", tabBarIcon: tabIcon("grid") })} />
      <Tabs.Screen name="users" options={tab(!scoped, { title: "Users", tabBarIcon: tabIcon("users") })} />
      <Tabs.Screen name="shop" options={tab(!scoped, { title: "Shop", tabBarIcon: tabIcon("shopping-bag") })} />
      <Tabs.Screen name="payouts" options={tab(!scoped, { title: "Payouts", tabBarIcon: tabIcon("currency-inr", "mci") })} />
      <Tabs.Screen name="wallet" options={tab(!scoped, { title: "Wallet", tabBarIcon: tabIcon("credit-card") })} />
      <Tabs.Screen name="more" options={tab(!scoped, { title: "More", tabBarIcon: tabIcon("more-horizontal") })} />
      <Tabs.Screen
        name="manager-home"
        options={tab(scoped, { title: "My section", tabBarIcon: tabIcon("grid") })}
      />
      {/* Scoped managers get Profile in place of the 6 full-admin tabs. */}
      <Tabs.Screen
        name="profile"
        options={tab(scoped, { title: "Profile", tabBarIcon: tabIcon("user") })}
      />
      {HIDDEN.map((name) => (
        <Tabs.Screen key={name} name={name} options={{ href: null }} />
      ))}
    </Tabs>
  );
}
