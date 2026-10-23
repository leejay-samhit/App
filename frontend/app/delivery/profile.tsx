// Delivery Partner — Profile. Same profile screen buyers get (the vendor /
// service-provider entries are already hidden for riders inside it), wrapped
// with the rider's 3-tab bar.
import React from "react";
import { View, StyleSheet } from "react-native";
import ProfileScreen from "../(tabs)/profile";
import { DPTabBar, useDPSwipe } from "../../src/delivery-ui";
import { colors } from "../../src/theme";

export default function DeliveryProfile() {
  const swipe = useDPSwipe();
  return (
    <View style={s.wrap} {...swipe}>
      <ProfileScreen />
      <DPTabBar />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.background },
});
