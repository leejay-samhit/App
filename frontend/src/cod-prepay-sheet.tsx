/**
 * CodPrepaySheet — the "some items can't be paid in cash" explainer.
 *
 * Shown when the bag MIXES cash-on-delivery items with prepaid-only ones.
 * The order can still be placed in one go: the prepaid-only part is settled
 * from the wallet now, the rest is collected in cash on delivery. The sheet
 * states the exact amount, names the items, and offers the two honest ways
 * forward — never a dead end.
 *
 * Purely informational: every rule it describes is enforced by the backend
 * when the order is placed.
 */
import React from "react";
import { Modal, Platform, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii, spacing, formatINR } from "./theme";

export type CodBlockedItem = {
  product_id?: string;
  name: string;
  qty?: number;
  amount: number;
  vendor_name?: string;
};

type Props = {
  visible: boolean;
  items: CodBlockedItem[];
  /** Total that must be settled up-front. */
  prepayDue: number;
  /** Wallet money available right now. */
  walletBalance: number;
  onClose: () => void;
  /** Settle the prepaid part from the wallet, rest stays cash. */
  onPayPartFromWallet: () => void;
  /** Pay the whole order online instead. */
  onPayAllOnline: () => void;
  /** Jump to the wallet to top up. */
  onTopUp: () => void;
};

export default function CodPrepaySheet({
  visible, items, prepayDue, walletBalance,
  onClose, onPayPartFromWallet, onPayAllOnline, onTopUp,
}: Props) {
  const enoughWallet = walletBalance >= prepayDue - 0.009;
  const shortBy = Math.max(0, prepayDue - walletBalance);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <TouchableOpacity style={StyleSheet.absoluteFill} activeOpacity={1} onPress={onClose} />
        <View style={styles.sheet} testID="cod-prepay-sheet">
          <View style={styles.grabber} />

          <View style={styles.headRow}>
            <View style={styles.iconBubble}>
              <Feather name="shopping-bag" size={18} color={colors.accent} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Part of this bag is prepaid-only</Text>
              <Text style={styles.subtitle}>
                {items.length === 1 ? "One item" : `${items.length} items`} in your bag can&apos;t be
                paid for in cash. Settle {formatINR(prepayDue)} now and the rest still goes cash on delivery.
              </Text>
            </View>
          </View>

          <View style={styles.amountCard}>
            <Text style={styles.amountLabel}>To pay now</Text>
            <Text style={styles.amountValue}>{formatINR(prepayDue)}</Text>
            <Text style={styles.amountHint}>
              {enoughWallet
                ? `Taken from your wallet · ${formatINR(walletBalance)} available`
                : `Your wallet has ${formatINR(walletBalance)} — ${formatINR(shortBy)} short`}
            </Text>
          </View>

          <Text style={styles.listLabel}>Prepaid-only items</Text>
          <ScrollView style={{ maxHeight: 168 }} contentContainerStyle={{ gap: 8 }}>
            {items.map((it, i) => (
              <View key={it.product_id || `${it.name}-${i}`} style={styles.itemRow}>
                <Feather name="credit-card" size={14} color={colors.textMuted} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.itemName} numberOfLines={1}>{it.name}</Text>
                  {it.vendor_name ? (
                    <Text style={styles.itemSeller} numberOfLines={1}>{it.vendor_name}</Text>
                  ) : null}
                </View>
                {it.qty && it.qty > 1 ? <Text style={styles.itemQty}>×{it.qty}</Text> : null}
                <Text style={styles.itemAmount}>{formatINR(it.amount)}</Text>
              </View>
            ))}
          </ScrollView>

          <View style={styles.actions}>
            {enoughWallet ? (
              <TouchableOpacity onPress={onPayPartFromWallet} style={styles.primaryBtn} testID="cod-prepay-wallet">
                <Feather name="check-circle" size={16} color={colors.primaryFg} />
                <Text style={styles.primaryBtnText}>
                  Pay {formatINR(prepayDue)} from wallet
                </Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity onPress={onTopUp} style={styles.primaryBtn} testID="cod-prepay-topup">
                <Feather name="plus-circle" size={16} color={colors.primaryFg} />
                <Text style={styles.primaryBtnText}>Add {formatINR(shortBy)} to wallet</Text>
              </TouchableOpacity>
            )}
            <TouchableOpacity onPress={onPayAllOnline} style={styles.secondaryBtn} testID="cod-prepay-online">
              <Feather name="smartphone" size={15} color={colors.textMain} />
              <Text style={styles.secondaryBtnText}>Pay the whole order online</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onClose} style={styles.ghostBtn} testID="cod-prepay-close">
              <Text style={styles.ghostBtnText}>Go back to the bag</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "#00000080", justifyContent: "flex-end",
    ...(Platform.OS === "web" ? ({ position: "fixed", inset: 0 } as any) : null),
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 26, borderTopRightRadius: 26,
    paddingHorizontal: spacing.screen, paddingTop: 10, paddingBottom: 26,
    gap: 14, maxHeight: "88%",
  },
  grabber: { alignSelf: "center", width: 42, height: 4, borderRadius: 2, backgroundColor: colors.border },
  headRow: { flexDirection: "row", gap: 12, alignItems: "flex-start", marginTop: 4 },
  iconBubble: {
    width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  title: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  subtitle: { fontSize: 12.5, color: colors.textMuted, lineHeight: 18, marginTop: 3 },

  amountCard: {
    backgroundColor: colors.surfaceMuted, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, padding: spacing.cardPad, gap: 2,
  },
  amountLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.4 },
  amountValue: { fontSize: 26, fontWeight: "900", color: colors.primary },
  amountHint: { fontSize: 11.5, color: colors.textMuted, marginTop: 2 },

  listLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.4 },
  itemRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, padding: 10,
  },
  itemName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  itemSeller: { fontSize: 11, color: colors.textMuted, marginTop: 1 },
  itemQty: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  itemAmount: { fontSize: 13, fontWeight: "900", color: colors.textMain },

  actions: { gap: 8 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 50, borderRadius: radii.button, backgroundColor: colors.primary,
  },
  primaryBtnText: { fontSize: 14.5, fontWeight: "900", color: colors.primaryFg },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  secondaryBtnText: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  ghostBtn: { minHeight: 40, alignItems: "center", justifyContent: "center" },
  ghostBtnText: { fontSize: 12.5, fontWeight: "700", color: colors.textMuted },
});
