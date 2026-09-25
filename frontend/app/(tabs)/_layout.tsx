import { Tabs, useRouter, useSegments } from "expo-router";
import { Platform, View } from "react-native";
import { useCallback } from "react";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors } from "../../src/theme";
import { useBranding } from "../../src/branding";
import { DesktopShell, useIsDesktop } from "../../src/desktop-shell";
import { useSwipePager } from "../../src/use-swipe-pager";
import { tabIcon, TAB_LABEL_STYLE } from "../../src/tab-bar-icon";

// Hardcoded visible-tab order per current UX spec:
// SHOP · SERVICES · DASHBOARD · CHAT · PROFILE
// Dashboard sits dead-center as the visual anchor. Declared at module scope
// so the swipe callbacks have a stable dependency.
const HARDCODED_ORDER = ["shop", "services", "dashboard", "chat", "profile"];

export default function TabsLayout() {
  const { tabs } = useBranding();
  const insets = useSafeAreaInsets();
  // Desktop web (≥ 1024 px) uses a permanent left sidebar instead of the
  // bottom tab bar. The tab bar itself is hidden by `tabBarStyle.display`.
  const isDesktop = useIsDesktop();
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
  // The screen route still exists so other in-app navigation (e.g. the
  // Wallet card on Dashboard pushes to /(tabs)/wallet) keeps working.
  const HARD_HIDDEN: Set<string> = new Set(["wallet", "shop-category/[name]"]);


  // ── Jun 2026 — WhatsApp-style swipe between the bottom tabs ───────────
  // A left/right flick anywhere on a tab screen moves to the neighbouring
  // tab, and React Navigation's "shift" animation slides the outgoing screen
  // out while the incoming one slides in from the opposite side.
  //
  // The gesture is deliberately scoped to the FIVE visible tabs: drilled-in
  // routes that live inside this group (shop-category/[name], wallet,
  // network) keep their own gestures, so a swipe there never yanks the user
  // out of the screen they're browsing.
  const router = useRouter();
  const segments = useSegments() as string[];
  const currentTab = segments[segments.length - 1] || "";
  const tabIndex = HARDCODED_ORDER.indexOf(currentTab);

  const goToTab = useCallback((dir: 1 | -1) => {
    if (tabIndex < 0) return;
    const next = HARDCODED_ORDER[tabIndex + dir];
    if (next) router.navigate(`/(tabs)/${next}` as any);
  }, [tabIndex, router]);

  const swipeHandlers = useSwipePager({
    onNext: () => goToTab(1),
    onPrev: () => goToTab(-1),
    enabled: !isDesktop && tabIndex >= 0,
  });

  // Every screen file under (tabs)/ must still be registered as a route, even
  // hidden ones. Build the full registration list = visible (in our order) +
  // hidden (so they're reachable via router.push()).
  // NOTE: `shop-category/[name]` is a child route registered as a hidden tab
  // so that the bottom tab bar STAYS VISIBLE when a user drills into a
  // shop category from the Shop tab (per user request — keep the side layout).
  // Only routes that actually exist as files may be registered — a stale
  // branding key (e.g. the retired MLM "network" tab still stored in the DB)
  // would otherwise register a phantom screen and warn on every render.
  const EXISTING_ROUTES = new Set([...HARDCODED_ORDER, "wallet", "shop-category/[name]"]);
  const allKeys = Array.from(new Set([
    ...HARDCODED_ORDER,
    ...tabs.map((t) => t.key).filter((k) => EXISTING_ROUTES.has(k)),
    "wallet",
    "shop-category/[name]",
  ]));
  const order = allKeys;
  const byKey = Object.fromEntries(tabs.map((t) => [t.key, t]));

  return (
    <DesktopShell>
      <View style={{ flex: 1 }} {...swipeHandlers}>
      <Tabs
        initialRouteName="shop"
        screenOptions={{
          headerShown: false,
          // Horizontal slide so a swipe (or a tab tap) reads as moving
          // sideways through the app, matching the reference video.
          animation: "shift",
          // Perf: never build a tab until it is first opened, and freeze it
          // the moment it loses focus so background screens cost nothing.
          lazy: true,
          freezeOnBlur: true,
          // Jun 2026 — paint each tab scene on the app background. Without
          // this the scene is transparent during the shift animation and the
          // dark root view flashed green between tabs.
          sceneStyle: { backgroundColor: colors.background },
          tabBarActiveTintColor: colors.primary,
          tabBarInactiveTintColor: colors.textMuted,
          tabBarHideOnKeyboard: true,
          tabBarStyle: isDesktop ? { display: "none" } : {
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
      {order.map((key) => {
        const t = byKey[key];
        const iconName: any = t?.icon || (key === "dashboard" ? "home" : key === "wallet" ? "credit-card" : key === "shop" ? "shopping-bag" : key === "services" ? "briefcase" : key === "chat" ? "message-circle" : "user");
        const label = t?.label || (key === "services" ? "Services" : key === "shop" ? "Shop" : key === "dashboard" ? "Dashboard" : key === "profile" ? "Profile" : key === "chat" ? "Chat" : key === "wallet" ? "Wallet" : key);
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
              tabBarIcon: tabIcon(iconName),
            }}
          />
        );
      })}
      </Tabs>
      </View>
    </DesktopShell>
  );
}
