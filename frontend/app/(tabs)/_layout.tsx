import { Tabs } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { Platform } from "react-native";
import { colors } from "../../src/theme";
import { useBranding } from "../../src/branding";

export default function TabsLayout() {
  const { tabs } = useBranding();
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
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          height: Platform.OS === "ios" ? 88 : 64,
          paddingTop: 8,
          paddingBottom: Platform.OS === "ios" ? 28 : 10,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
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
