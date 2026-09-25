// Delivery Partner — Chat. Renders the same thread list buyers get, but with
// the rider's 3-tab bar instead of the Shop/Services bar.
import React from "react";
import { View, StyleSheet } from "react-native";
import ChatListScreen from "../(tabs)/chat";
import { DPTabBar } from "../../src/delivery-ui";
import { colors } from "../../src/theme";

export default function DeliveryChat() {
  return (
    <View style={s.wrap}>
      <ChatListScreen />
      <DPTabBar />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.background },
});
