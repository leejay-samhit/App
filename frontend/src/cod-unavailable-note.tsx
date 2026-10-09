/**
 * CodUnavailableNote — compact inline note for a prepaid-only item.
 *
 * Rev 2 (Oct-2026): the first version was a full bottom sheet with an icon
 * bubble, a paragraph and a scrolling item list — far too heavy for what is
 * really a one-line fact. The owner asked for a small note, so this is a
 * single slim strip that sits right above the Place Order button:
 *
 *     ⓘ  Cash on Delivery not available on this item.   [Pay online]
 *
 * It never dead-ends — the inline action switches the order to online
 * payment — and it does not steal the screen or need dismissing.
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii } from "./theme";

type Props = {
  /** Prepaid-only item names, used to name a single item precisely. */
  items: string[];
  /** Switch the order to a prepaid method. */
  onPayOnline: () => void;
};

export default function CodUnavailableNote({ items, onPayOnline }: Props) {
  const many = items.length > 1;
  return (
    <View style={styles.note} testID="cod-unavailable-note">
      <Feather name="info" size={14} color={colors.accent} style={styles.icon} />
      <View style={{ flex: 1 }}>
        <Text style={styles.text}>
          Cash on Delivery not available on {many ? `${items.length} items` : "this item"}.
        </Text>
        {many ? (
          <Text style={styles.sub} numberOfLines={1}>{items.join(", ")}</Text>
        ) : null}
      </View>
      <TouchableOpacity onPress={onPayOnline} style={styles.action} testID="cod-note-pay-online">
        <Text style={styles.actionText}>Pay online</Text>
        <Feather name="arrow-right" size={12} color={colors.primaryFg} />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  note: {
    flexDirection: "row", alignItems: "center", gap: 9,
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.accent,
    paddingVertical: 10, paddingHorizontal: 12,
    marginBottom: 10,
  },
  icon: { marginTop: 1 },
  text: { fontSize: 12.5, lineHeight: 17, fontWeight: "800", color: colors.textMain },
  sub: { fontSize: 11, color: colors.textMuted, marginTop: 2, fontWeight: "600" },
  action: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.primary,
    paddingHorizontal: 11, paddingVertical: 8, borderRadius: 999,
  },
  actionText: { fontSize: 11.5, fontWeight: "900", color: colors.primaryFg },
});
