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
  const order = tabs.map((t) => t.key);
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
        const iconName: any = t?.icon || (key === "dashboard" ? "home" : key === "network" ? "git-branch" : key === "wallet" ? "credit-card" : key === "shop" ? "shopping-bag" : "user");
        return (
          <Tabs.Screen
            key={key}
            name={key}
            options={{
              title: t?.label || key,
              href: t?.visible === false ? null : undefined,
              tabBarIcon: ({ color, size }) => <Feather name={iconName} size={size} color={color} />,
            }}
          />
        );
      })}
    </Tabs>
  );
}
