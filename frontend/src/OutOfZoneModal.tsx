// Out-of-delivery-zone modal — Nov 2026
//
// Replaces the plain Alert.alert() that customers saw when a checkout
// order got rejected by the backend's delivery-zone guard.  Presents:
//   • The list of ineligible products (with the vendor's pincode context)
//   • A big "Change delivery address" CTA (takes the user back to fill)
//   • A subtle "Remove these items" secondary that clears the cart
//     rows that can't ship
//   • Dismissable so the user can adjust inline
import React from "react";
import { View, Text, StyleSheet, Modal, TouchableOpacity, ScrollView } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii, spacing } from "./theme";

type Props = {
  visible: boolean;
  conflicts: string[];       // Human-readable rows from server
  onClose: () => void;
  onChangeAddress?: () => void;
  onRemoveItems?: () => void;
};

export default function OutOfZoneModal({
  visible, conflicts, onClose, onChangeAddress, onRemoveItems,
}: Props) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={styles.scrim}>
        <View style={styles.sheet} accessibilityLabel="Out of delivery zone">
          <View style={styles.grabber} />
          <View style={styles.iconRow}>
            <View style={styles.iconRing}>
              <Feather name="truck" size={22} color="#B45309" />
            </View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.title}>Some items can&apos;t be delivered</Text>
              <Text style={styles.sub}>
                Your shipping pincode is outside these vendors&apos; delivery zone.
              </Text>
            </View>
          </View>

          <ScrollView style={styles.listWrap} contentContainerStyle={{ paddingVertical: 4 }} showsVerticalScrollIndicator={false}>
            {conflicts.map((c, i) => (
              <View key={i} style={styles.itemRow}>
                <Feather name="alert-circle" size={13} color="#DC2626" />
                <Text style={styles.itemText}>{c}</Text>
              </View>
            ))}
          </ScrollView>

          <View style={styles.tips}>
            <Feather name="info" size={12} color={colors.textMuted} />
            <Text style={styles.tipsText}>
              Tip — change your shipping pincode to one that matches the vendor, or remove the items to continue.
            </Text>
          </View>

          <TouchableOpacity
            onPress={() => { onClose(); onChangeAddress?.(); }}
            style={styles.primaryBtn}
            testID="ooz-change-address"
          >
            <Feather name="edit-3" size={16} color={colors.primaryFg} />
            <Text style={styles.primaryBtnText}>  Change delivery address</Text>
          </TouchableOpacity>
          {onRemoveItems ? (
            <TouchableOpacity
              onPress={() => { onClose(); onRemoveItems?.(); }}
              style={styles.ghostBtn}
              testID="ooz-remove-items"
            >
              <Feather name="trash-2" size={14} color="#DC2626" />
              <Text style={styles.ghostBtnText}>  Remove ineligible items</Text>
            </TouchableOpacity>
          ) : null}
          <TouchableOpacity onPress={onClose} style={styles.closeBtn} testID="ooz-close">
            <Text style={styles.closeBtnText}>Keep shopping</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: spacing.screen, paddingBottom: 32,
    maxHeight: "82%",
  },
  grabber: {
    alignSelf: "center", width: 44, height: 4,
    backgroundColor: colors.border, borderRadius: 4,
    marginBottom: 12,
  },
  iconRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  iconRing: {
    width: 46, height: 46, borderRadius: 23,
    backgroundColor: "#FEF3C7",
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: "#F59E0B",
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain, letterSpacing: -0.3 },
  sub: { fontSize: 12, color: colors.textMuted, marginTop: 4, lineHeight: 16 },
  listWrap: {
    marginTop: 14,
    borderTopWidth: 1, borderTopColor: colors.border,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    marginBottom: 12,
  },
  itemRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border + "55",
  },
  itemText: { flex: 1, fontSize: 12.5, color: colors.textMain, lineHeight: 17 },
  tips: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    padding: 10,
    backgroundColor: colors.surfaceMuted, borderRadius: 10,
    marginBottom: 14,
  },
  tipsText: { flex: 1, fontSize: 11.5, color: colors.textMuted, lineHeight: 16 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary,
    paddingVertical: 14, borderRadius: radii.button,
  },
  primaryBtnText: { color: colors.primaryFg, fontSize: 14, fontWeight: "800" },
  ghostBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    paddingVertical: 12, marginTop: 8, borderRadius: radii.button,
    borderWidth: 1, borderColor: "#FCA5A5",
    backgroundColor: "#FEF2F2",
  },
  ghostBtnText: { color: "#DC2626", fontSize: 13, fontWeight: "800" },
  closeBtn: { alignItems: "center", justifyContent: "center", paddingVertical: 12, marginTop: 4 },
  closeBtnText: { color: colors.textMuted, fontSize: 12, fontWeight: "700" },
});
