/**
 * CodUnavailableModal — shown when the buyer picked Cash on Delivery but at
 * least one item in the bag is prepaid-only (the seller switched COD off for
 * that product).
 *
 * The sheet never dead-ends: the primary action switches the order to online
 * payment, and the item names are listed so the buyer can remove them
 * instead.
 */
import React from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, TouchableOpacity, ScrollView,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii } from "./theme";

type Props = {
  visible: boolean;
  items: string[];
  onClose: () => void;
  /** Switch the order to a prepaid method and keep the buyer in flow. */
  onPayOnline: () => void;
};

export default function CodUnavailableModal({ visible, items, onClose, onPayOnline }: Props) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={styles.backdrop} onPress={onClose} testID="cod-modal-backdrop" />
      <View style={styles.sheet} testID="cod-unavailable-modal">
        <View style={styles.grabber} />

        <View style={styles.iconBubble}>
          <Feather name="credit-card" size={26} color={colors.accent} />
        </View>

        <Text style={styles.eyebrow}>CASH ON DELIVERY NOT AVAILABLE</Text>
        <Text style={styles.title}>This item can&apos;t be delivered as COD</Text>
        <Text style={styles.body}>
          The seller ships this item only against a prepaid order. Please make the
          payment for the item and its delivery to place the order.
        </Text>

        {items.length > 0 ? (
          <View style={styles.listCard}>
            <Text style={styles.listLabel}>PREPAID-ONLY ITEMS</Text>
            <ScrollView style={{ maxHeight: 132 }}>
              {items.map((name, i) => (
                <View key={`${name}-${i}`} style={styles.listRow}>
                  <Feather name="package" size={13} color={colors.textMuted} />
                  <Text style={styles.listText} numberOfLines={2}>{name}</Text>
                </View>
              ))}
            </ScrollView>
          </View>
        ) : null}

        <TouchableOpacity onPress={onPayOnline} style={styles.primaryBtn} testID="cod-modal-pay-online">
          <Feather name="shield" size={16} color={colors.primaryFg} />
          <Text style={styles.primaryBtnText}>Pay online &amp; place order</Text>
          <Feather name="arrow-right" size={16} color={colors.primaryFg} />
        </TouchableOpacity>

        <TouchableOpacity onPress={onClose} style={styles.ghostBtn} testID="cod-modal-review-bag">
          <Feather name="shopping-bag" size={14} color={colors.primary} />
          <Text style={styles.ghostBtnText}>Review my bag instead</Text>
        </TouchableOpacity>

        <Text style={styles.footNote}>
          Your money is held securely and released to the seller only after delivery.
        </Text>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 26, borderTopRightRadius: 26,
    paddingHorizontal: 22, paddingTop: 10, paddingBottom: 30,
    alignItems: "center",
  },
  grabber: {
    width: 44, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginBottom: 18,
  },
  iconBubble: {
    width: 62, height: 62, borderRadius: 31,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border,
    marginBottom: 14,
  },
  eyebrow: {
    fontSize: 10, letterSpacing: 1.4, fontWeight: "900",
    color: colors.accent, marginBottom: 6, textAlign: "center",
  },
  title: {
    fontSize: 19, lineHeight: 25, fontWeight: "900",
    color: colors.textMain, textAlign: "center",
    letterSpacing: -0.4, marginBottom: 8,
  },
  body: {
    fontSize: 13, lineHeight: 20, color: colors.textMuted,
    textAlign: "center", marginBottom: 16, maxWidth: 330,
  },
  listCard: {
    width: "100%", backgroundColor: colors.surfaceMuted,
    borderRadius: radii.input, borderWidth: 1, borderColor: colors.border,
    padding: 12, marginBottom: 18,
  },
  listLabel: {
    fontSize: 10, fontWeight: "900", letterSpacing: 1.1,
    color: colors.textMuted, marginBottom: 8,
  },
  listRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  listText: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.textMain },
  primaryBtn: {
    width: "100%", flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary,
    minHeight: 52, paddingVertical: 15, borderRadius: 14,
    marginBottom: 10,
  },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "900", fontSize: 15, letterSpacing: -0.2 },
  ghostBtn: {
    width: "100%", flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 48, paddingVertical: 13, borderRadius: 14,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  ghostBtnText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  footNote: {
    marginTop: 14, fontSize: 11, lineHeight: 16,
    color: colors.textMuted, textAlign: "center", maxWidth: 300,
  },
});
