import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Image,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";

type CartLine = {
  id: string;
  product_id: string;
  qty: number;
  product: { name: string; price: number; image_url: string };
  line_total: number;
};

export default function CartScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [items, setItems] = useState<CartLine[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: CartLine[]; total: number }>("/cart");
      setItems(data.items);
      setTotal(data.total);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const remove = async (productId: string) => {
    try {
      await api.post("/cart/remove", { product_id: productId });
      await load();
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    }
  };

  const checkout = async () => {
    setSubmitting(true);
    try {
      await api.post("/orders/checkout");
      await refresh();
      Alert.alert("Order placed!", "Your order has been placed and ₹" + total + " deducted from wallet.", [
        { text: "View orders", onPress: () => router.replace("/orders") },
      ]);
    } catch (e) {
      Alert.alert("Checkout failed", formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  const balance = user?.wallet_balance || 0;
  const canPay = balance >= total && total > 0;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="cart-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Your cart</Text>
        <View style={{ width: 40 }} />
      </View>

      {items.length === 0 ? (
        <View style={styles.empty}>
          <Feather name="shopping-cart" size={36} color={colors.textMuted} />
          <Text style={styles.emptyTitle}>Cart is empty</Text>
          <Text style={styles.emptyText}>Add products from the shop tab.</Text>
          <TouchableOpacity onPress={() => router.replace("/(tabs)/shop")} style={styles.emptyBtn} testID="cart-go-shop">
            <Text style={styles.emptyBtnText}>Browse shop</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <>
          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingTop: 8, paddingBottom: 20 }}>
            {items.map((it) => (
              <View key={it.id} style={styles.line} testID={`cart-line-${it.product_id}`}>
                <Image source={{ uri: it.product.image_url }} style={styles.image} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName} numberOfLines={2}>{it.product.name}</Text>
                  <Text style={styles.lineQty}>{formatINR(it.product.price)} × {it.qty}</Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.lineTotal}>{formatINR(it.line_total)}</Text>
                  <TouchableOpacity onPress={() => remove(it.product_id)} testID={`cart-remove-${it.product_id}`} style={styles.removeBtn}>
                    <Feather name="trash-2" size={14} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              </View>
            ))}
          </ScrollView>

          <View style={styles.footer}>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Wallet balance</Text>
              <Text style={styles.rowValue}>{formatINR(balance)}</Text>
            </View>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Total</Text>
              <Text style={styles.totalValue}>{formatINR(total)}</Text>
            </View>
            {!canPay && total > 0 && (
              <Text style={styles.warning}>Insufficient wallet balance — refer more friends to earn!</Text>
            )}
            <TouchableOpacity
              onPress={checkout}
              disabled={!canPay || submitting}
              style={[styles.payBtn, (!canPay || submitting) && { opacity: 0.5 }]}
              testID="cart-checkout"
            >
              {submitting ? (
                <ActivityIndicator color={colors.primaryFg} />
              ) : (
                <>
                  <Feather name="check-circle" size={18} color={colors.primaryFg} />
                  <Text style={styles.payBtnText}>Pay with wallet</Text>
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
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40, gap: 8 },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  emptyBtn: { marginTop: 16, backgroundColor: colors.primary, paddingHorizontal: 20, paddingVertical: 12, borderRadius: radii.button },
  emptyBtnText: { color: colors.primaryFg, fontWeight: "700" },
  line: { flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 12, marginBottom: 10, gap: 12 },
  image: { width: 60, height: 60, borderRadius: 10, backgroundColor: colors.surfaceMuted },
  lineName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  lineQty: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  lineTotal: { fontSize: 14, fontWeight: "800", color: colors.primary },
  removeBtn: { padding: 6, marginTop: 4 },
  footer: { padding: spacing.screen, paddingTop: 16, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginVertical: 4 },
  rowLabel: { fontSize: 13, color: colors.textMuted },
  rowValue: { fontSize: 14, color: colors.textMain, fontWeight: "700" },
  totalValue: { fontSize: 22, fontWeight: "800", color: colors.primary, letterSpacing: -0.5 },
  warning: { color: "#B3261E", fontSize: 12, marginTop: 8 },
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 14 },
  payBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
});
