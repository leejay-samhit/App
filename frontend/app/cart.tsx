import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Image,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError, resolveImageUrl } from "../src/api";
import { ProductImage } from "../src/product-image";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";
import { notify } from "../src/notify";

type CartLine = {
  id: string;
  product_id: string;
  qty: number;
  product: { name: string; price: number; image_url: string; vendor_id?: string | null; vendor_name?: string | null };
  line_total: number;
  // Jun 2026 — which size / RAM-ROM option this row is for
  variant_id?: string;
  variant_label?: string;
  unit_price?: number;
  variant_stock?: number | null;
};

// Jun 2026 — the bag now prices delivery with the SAME engine checkout uses,
// so "Shipping: FREE" can never contradict the amount charged a tap later.
type DeliveryQuote = {
  enabled: boolean;
  total: number;
  free: boolean;
  add_more_for_free: number;
  hint: string;
  per_seller?: { vendor_name: string; charge: number; free: boolean }[];
};

export default function CartScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [items, setItems] = useState<CartLine[]>([]);
  const [total, setTotal] = useState(0);
  const [delivery, setDelivery] = useState<DeliveryQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [busyLine, setBusyLine] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: CartLine[]; total: number; delivery?: DeliveryQuote; payable_total?: number }>("/cart");
      const safeItems = Array.isArray(data.items) ? data.items : [];
      setItems(safeItems);
      // Defensive: if backend total comes back as 0/undefined for any reason, compute it
      // locally from the line_totals so the user never sees an incorrect ₹0 with items present.
      const localTotal = safeItems.reduce((sum, it) => {
        const lt = typeof it.line_total === "number" ? it.line_total : ((it.unit_price ?? it.product?.price) || 0) * (it.qty || 0);
        return sum + (lt || 0);
      }, 0);
      setTotal(Number(data.total) > 0 ? Number(data.total) : localTotal);
      setDelivery(data.delivery || null);
      // Jun 2026 — the footer shows the live wallet balance. Reading it off a
      // stale auth snapshot made the bag claim "₹0 / wallet short by ₹3" for
      // shoppers who actually had money, so pull /auth/me every time the bag
      // opens.
      await refresh();
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [refresh]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  const remove = async (productId: string, variantId?: string) => {
    try {
      // Pass the variant so removing "Size L" doesn't wipe "Size M" too.
      await api.post("/cart/remove", { product_id: productId, variant_id: variantId || null });
      await load();
    } catch (e) {
      notify("Error", formatApiError(e));
    }
  };

  // Jun 2026 — inline qty stepper. `delta` is ±1; the backend caps the row
  // at available stock and deletes it when the qty hits zero.
  const adjust = async (line: CartLine, delta: 1 | -1) => {
    const key = `${line.product_id}-${line.variant_id || ""}`;
    if (busyLine) return;
    setBusyLine(key);
    try {
      await api.post("/cart/adjust", {
        product_id: line.product_id,
        variant_id: line.variant_id || null,
        delta,
      });
      await load();
    } catch (e) {
      notify("Couldn't update quantity", formatApiError(e));
    } finally { setBusyLine(null); }
  };

  const checkout = async () => {
    // Cart -> Checkout screen (address + payment method live there).
    router.push("/checkout" as any);
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  const balance = user?.wallet_balance || 0;
  // Delivery is priced per seller by the server; the bag shows the same
  // number checkout will charge.
  const shipping = Number(delivery?.total || 0);
  const payable = Math.round((total + shipping) * 100) / 100;
  const canPay = balance >= payable && payable > 0;

  // Jun 2026 — checkout splits into ONE order per seller, so the bag shows
  // the same grouping up-front: no surprise "why did I get 2 orders?".
  const sellerGroups: { key: string; name: string; lines: CartLine[]; subTotal: number }[] = [];
  items.forEach((it) => {
    const key = it.product?.vendor_id || "__slangcart__";
    let g = sellerGroups.find((x) => x.key === key);
    if (!g) {
      g = { key, name: it.product?.vendor_name || "Slangcart Store", lines: [], subTotal: 0 };
      sellerGroups.push(g);
    }
    g.lines.push(it);
    g.subTotal += it.line_total || 0;
  });
  const multiSeller = sellerGroups.length > 1;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="cart-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ alignItems: "center" }}>
          <Text style={styles.title}>Your bag</Text>
          {items.length > 0 && (
            <Text style={styles.titleSub}>{items.length} item{items.length === 1 ? "" : "s"}</Text>
          )}
        </View>
        <View style={{ width: 40 }} />
      </View>

      {items.length === 0 ? (
        <View style={styles.empty}>
          <View style={styles.emptyIconCircle}>
            <Feather name="shopping-bag" size={28} color={colors.primary} />
          </View>
          <Text style={styles.emptyTitle}>Your bag is empty</Text>
          <Text style={styles.emptyText}>Browse the shop and add a few favourites — wallet earnings cover the bill.</Text>
          <TouchableOpacity onPress={() => router.replace("/(tabs)/shop")} style={styles.emptyBtn} testID="cart-go-shop">
            <Feather name="shopping-bag" size={16} color={colors.primaryFg} />
            <Text style={styles.emptyBtnText}>Browse shop</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <>
          <ScrollView
            contentContainerStyle={{ padding: spacing.screen, paddingTop: 8, paddingBottom: 20 }}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
          >
            {multiSeller ? (
              <View style={styles.splitNotice} testID="cart-split-notice">
                <Feather name="git-branch" size={15} color={colors.primary} />
                <Text style={styles.splitNoticeText}>
                  Items from {sellerGroups.length} sellers — this will be placed as{" "}
                  {sellerGroups.length} separate orders, each tracked and delivered on its own.
                </Text>
              </View>
            ) : null}

            {sellerGroups.map((g) => (
              <View key={g.key} testID={`cart-seller-${g.key}`}>
                {multiSeller ? (
                  <View style={styles.sellerHeader}>
                    <Feather name="shopping-bag" size={13} color={colors.primary} />
                    <Text style={styles.sellerName} numberOfLines={1}>{g.name}</Text>
                    <Text style={styles.sellerSub}>{formatINR(g.subTotal)}</Text>
                  </View>
                ) : null}
                {g.lines.map((it) => (
              <View key={it.id} style={styles.line} testID={`cart-line-${it.product_id}${it.variant_id ? `-${it.variant_id}` : ""}`}>
                <ProductImage uri={it.product.image_url} name={it.product.name} compact style={styles.image} resizeMode="cover" />
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName} numberOfLines={2}>{it.product.name}</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    {/* Jun 2026 — inline qty stepper (no remove-and-re-add). */}
                    <View style={styles.stepper}>
                      <TouchableOpacity
                        onPress={() => adjust(it, -1)}
                        disabled={!!busyLine}
                        style={styles.stepBtn}
                        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                        testID={`qty-minus-${it.product_id}`}
                      >
                        <Feather name={it.qty <= 1 ? "trash-2" : "minus"} size={13} color={colors.primary} />
                      </TouchableOpacity>
                      {busyLine === `${it.product_id}-${it.variant_id || ""}` ? (
                        <ActivityIndicator size="small" color={colors.primary} style={{ width: 30 }} />
                      ) : (
                        <Text style={styles.stepQty} testID={`qty-value-${it.product_id}`}>{it.qty}</Text>
                      )}
                      <TouchableOpacity
                        onPress={() => adjust(it, 1)}
                        disabled={!!busyLine}
                        style={styles.stepBtn}
                        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                        testID={`qty-plus-${it.product_id}`}
                      >
                        <Feather name="plus" size={13} color={colors.primary} />
                      </TouchableOpacity>
                    </View>
                    {/* Jun 2026 — show the chosen size / RAM-ROM so the
                        shopper can confirm the fit before paying. */}
                    {it.variant_label ? (
                      <View style={styles.variantPill}>
                        <Text style={styles.variantPillText}>{it.variant_label}</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.lineUnit}>{formatINR(it.unit_price ?? it.product.price)} each</Text>
                </View>
                <View style={{ alignItems: "flex-end", justifyContent: "space-between" }}>
                  <TouchableOpacity onPress={() => remove(it.product_id, it.variant_id)} testID={`cart-remove-${it.product_id}`} style={styles.removeBtn}>
                    <Feather name="x" size={14} color={colors.textMuted} />
                  </TouchableOpacity>
                  <Text style={styles.lineTotal}>{formatINR(it.line_total)}</Text>
                </View>
              </View>
                ))}
              </View>
            ))}

            <View style={styles.summaryCard}>
              <Text style={styles.summaryHeader}>Bag summary</Text>
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Sub-total</Text>
                <Text style={styles.summaryValue}>{formatINR(total)}</Text>
              </View>
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Shipping</Text>
                {shipping > 0 ? (
                  <Text style={styles.summaryValue} testID="cart-shipping-value">{formatINR(shipping)}</Text>
                ) : (
                  <Text style={[styles.summaryValue, { color: colors.primary }]} testID="cart-shipping-value">FREE</Text>
                )}
              </View>
              {shipping > 0 && (delivery?.add_more_for_free || 0) > 0 ? (
                <Text style={styles.freeHint} testID="cart-free-delivery-hint">
                  Add {formatINR(delivery!.add_more_for_free)} more to your bag to get free delivery.
                </Text>
              ) : null}
              <View style={[styles.summaryRow, { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 10, marginTop: 6 }]}>
                <Text style={styles.totalLabel}>Total</Text>
                <Text style={styles.totalValue} testID="cart-total-value">{formatINR(payable)}</Text>
              </View>
            </View>
          </ScrollView>

          <View style={styles.footer}>
            <View style={styles.walletRow}>
              <Feather name="credit-card" size={16} color={colors.primary} />
              <Text style={styles.walletLabel}>Wallet balance</Text>
              <Text style={styles.walletValue}>{formatINR(balance)}</Text>
            </View>
            {!canPay && payable > 0 && (
              <Text style={styles.warning}>
                Wallet short by {formatINR(payable - balance)} — you can still pay Cash on Delivery at checkout.
              </Text>
            )}
            <TouchableOpacity
              onPress={checkout}
              disabled={total <= 0 || submitting}
              style={[styles.payBtn, (total <= 0 || submitting) && { opacity: 0.5 }]}
              testID="cart-checkout"
            >
              {submitting ? (
                <ActivityIndicator color={colors.primaryFg} />
              ) : (
                <>
                  <Feather name="arrow-right-circle" size={18} color={colors.primaryFg} />
                  <Text style={styles.payBtnText}>Proceed to Checkout · {formatINR(payable)}</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        </>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  titleSub: { fontSize: 11, color: colors.textMuted, fontWeight: "700", marginTop: 1 },

  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40, gap: 8 },
  emptyIconCircle: { width: 72, height: 72, borderRadius: 36, backgroundColor: colors.primary + "15", alignItems: "center", justifyContent: "center", marginBottom: 8 },
  emptyTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  emptyText: { fontSize: 13, color: colors.textMuted, textAlign: "center", maxWidth: 260 },
  emptyBtn: { marginTop: 16, flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.primary, paddingHorizontal: 22, paddingVertical: 12, borderRadius: radii.button },
  emptyBtnText: { color: colors.primaryFg, fontWeight: "800" },

  line: { flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 12, marginBottom: 10, gap: 12 },

  // Jun 2026 — multi-seller split grouping
  splitNotice: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.primary + "10", borderRadius: 14,
    borderWidth: 1, borderColor: colors.primary + "40",
    padding: 12, marginBottom: 12,
  },
  splitNoticeText: { flex: 1, fontSize: 11.5, color: colors.textMain, fontWeight: "600", lineHeight: 16 },
  sellerHeader: { flexDirection: "row", alignItems: "center", gap: 7, marginBottom: 8, paddingHorizontal: 2 },
  sellerName: { flex: 1, fontSize: 12, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  sellerSub: { fontSize: 12, fontWeight: "800", color: colors.primary },
  image: { width: 72, height: 72, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  lineName: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginBottom: 6 },
  qtyPill: { alignSelf: "flex-start", backgroundColor: colors.surfaceMuted, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  // Jun 2026 — inline qty stepper
  stepper: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.primary + "10",
    borderRadius: 999, borderWidth: 1, borderColor: colors.primary + "40",
  },
  stepBtn: { width: 30, height: 30, alignItems: "center", justifyContent: "center" },
  stepQty: { minWidth: 30, textAlign: "center", fontSize: 13, fontWeight: "900", color: colors.textMain },
  variantPill: {
    backgroundColor: colors.primary, borderRadius: 999,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  variantPillText: { fontSize: 10.5, fontWeight: "900", color: colors.primaryFg, letterSpacing: 0.3 },
  qtyPillText: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.4 },
  lineUnit: { fontSize: 11, color: colors.textMuted, marginTop: 6, fontWeight: "600" },
  lineTotal: { fontSize: 15, fontWeight: "800", color: colors.primary },
  removeBtn: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },

  summaryCard: {
    marginTop: 8,
    backgroundColor: colors.surface,
    borderRadius: 18, borderWidth: 1, borderColor: colors.border,
    padding: 16,
  },
  summaryHeader: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginBottom: 10, letterSpacing: -0.2 },
  summaryRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 4 },
  summaryLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  summaryValue: { fontSize: 13, color: colors.textMain, fontWeight: "700" },
  totalLabel: { fontSize: 13, color: colors.textMain, fontWeight: "800" },
  totalValue: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.6 },

  footer: { padding: spacing.screen, paddingTop: 14, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  walletRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10, paddingHorizontal: 12, backgroundColor: colors.primary + "10", borderRadius: 12, marginBottom: 8 },
  walletLabel: { flex: 1, fontSize: 12, color: colors.textMain, fontWeight: "700" },
  walletValue: { fontSize: 13, color: colors.primary, fontWeight: "800" },
  warning: { color: "#B3261E", fontSize: 11, marginTop: 4, marginBottom: 6, fontWeight: "600" },
  freeHint: { fontSize: 11.5, color: colors.primary, fontWeight: "700", marginTop: 2, lineHeight: 16 },

  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 6 },
  payBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14, letterSpacing: -0.2 },
});
