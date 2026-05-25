import { Tabs } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "../../src/theme";
import { useBranding } from "../../src/branding";

export default function TabsLayout() {
  const { tabs } = useBranding();
  const insets = useSafeAreaInsets();
  // Lift the tab bar comfortably above the device's navigation buttons
  // (Android 3-button nav / gesture pill, iOS home indicator).
  const bottomPad = Math.max(insets.bottom, Platform.OS === "ios" ? 28 : 18);
  // Use the configured ordering / labels but render every screen file (Tabs requires every
  // child to map to an actual file in /app/(tabs)). We use `href: null` to hide invisible
  // tabs from the bar without unmounting the route.
  // Force Dashboard to the center of the tab bar (per UX requirement).
  // We reorder the visible tabs so dashboard sits at the middle index, while
  // keeping the rest in their configured order around it. This works even if
  // the admin re-ordered tabs via branding.
  // Hard-hide certain tabs from the bottom bar regardless of branding (per UX requirement).
  // The screen route still exists so other in-app navigation (e.g. Withdraw button on
  // Dashboard pushes to /(tabs)/wallet, Next L1 Payout card pushes to /(tabs)/network)
  // keeps working.
  const HARD_HIDDEN: Set<string> = new Set(["wallet", "network", "shop-category/[name]"]);

  // Hardcoded visible-tab order per current UX spec:
  // SHOP · SERVICES · DASHBOARD · CHAT · PROFILE
  // Dashboard sits dead-center as the visual anchor.
  const HARDCODED_ORDER = ["shop", "services", "dashboard", "chat", "profile"];

  // Every screen file under (tabs)/ must still be registered as a route, even
  // hidden ones. Build the full registration list = visible (in our order) +
  // hidden (so they're reachable via router.push()).
  // NOTE: `shop-category/[name]` is a child route registered as a hidden tab
  // so that the bottom tab bar STAYS VISIBLE when a user drills into a
  // shop category from the Shop tab (per user request — keep the side layout).
  const allKeys = Array.from(new Set([...HARDCODED_ORDER, ...tabs.map((t) => t.key), "wallet", "network", "shop-category/[name]"]));
  const order = allKeys;
  const byKey = Object.fromEntries(tabs.map((t) => [t.key, t]));

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.primary,
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
      {order.map((key) => {
        const t = byKey[key];
        const iconName: any = t?.icon || (key === "dashboard" ? "home" : key === "network" ? "git-branch" : key === "wallet" ? "credit-card" : key === "shop" ? "shopping-bag" : key === "services" ? "briefcase" : key === "chat" ? "message-circle" : "user");
        const label = t?.label || (key === "services" ? "Services" : key === "shop" ? "Shop" : key === "dashboard" ? "Dashboard" : key === "profile" ? "Profile" : key === "chat" ? "Chat" : key === "network" ? "Network" : key === "wallet" ? "Wallet" : key);
        const isHidden = HARD_HIDDEN.has(key) || t?.visible === false;
        return (
          <Tabs.Screen
            key={key}
            name={key}
            options={isHidden ? {
              title: label,
              // Render an empty button so the tab is registered as a route
              // (other screens can still navigate to it) but it never appears
              // in the bottom bar.
              tabBarButton: () => null,
              tabBarItemStyle: { display: "none" },
            } : {
              title: label,
              tabBarIcon: ({ color, size }) => <Feather name={iconName} size={size} color={color} />,
            }}
          />
        );
      })}
    </Tabs>
  );
}
