// Delivery Partner — Profile. Same profile screen buyers get (the vendor /
// service-provider entries are already hidden for riders inside it), wrapped
// with the rider's 3-tab bar.
import React from "react";
import { View, StyleSheet } from "react-native";
import ProfileScreen from "../(tabs)/profile";
import { DPTabBar } from "../../src/delivery-ui";
import { colors } from "../../src/theme";

export default function DeliveryProfile() {
  return (
    <View style={s.wrap}>
      <ProfileScreen />
      <DPTabBar />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.background },
});
