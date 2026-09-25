// Shared bottom-nav icon (Oct 2026).
//
// One component so the buyer tab bar and the admin tab bar look identical:
// the active tab gets a soft brand-tinted pill behind a slightly larger icon,
// inactive tabs stay flat and muted. Touch targets stay ≥ 44 px because the
// pill lives inside the tab item's own hit area.
import React from "react";
import { View, StyleSheet } from "react-native";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { colors } from "./theme";

export function TabBarIcon({
  name,
  focused,
  color,
  family = "feather",
}: {
  name: any;
  focused: boolean;
  color: string;
  family?: "feather" | "mci";
}) {
  const size = focused ? 21 : 20;
  return (
    <View style={[s.pill, focused && s.pillOn]}>
      {family === "mci"
        ? <MaterialCommunityIcons name={name} size={size + 1} color={color} />
        : <Feather name={name} size={size} color={color} />}
    </View>
  );
}

/** Drop-in `tabBarIcon` factory for <Tabs.Screen options={...} />. */
export const tabIcon = (name: any, family: "feather" | "mci" = "feather") =>
  ({ focused, color }: { focused: boolean; color: string }) => (
    <TabBarIcon name={name} focused={focused} color={color} family={family} />
  );

export const TAB_LABEL_STYLE = {
  fontSize: 11,
  fontWeight: "700" as const,
  marginTop: 3,
  letterSpacing: 0.1,
};

const s = StyleSheet.create({
  pill: {
    minWidth: 46,
    height: 30,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  pillOn: { backgroundColor: colors.brand100 },
});
