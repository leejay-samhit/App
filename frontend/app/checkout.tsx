// Checkout — shipping address form + payment method selection (Wallet / COD)
// + sticky Place Order button. Posts to /api/orders/checkout which decrements
// stock atomically and either debits the wallet (wallet) or marks the order
// `paid_via: "cod"` for cash-on-delivery.
import { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, Alert,
  ActivityIndicator, KeyboardAvoidingView, Platform, Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";

type CartItem = { id: string; product_id: string; qty: number; product: { name: string; price: number; image_url: string }; line_total: number };

const ADDRESS_KEY = "@checkout-address-v1";

export default function CheckoutScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [items, setItems] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [placing, setPlacing] = useState(false);
  const [walletBalance, setWalletBalance] = useState<number>(0);
  // Address fields
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [pincode, setPincode] = useState("");
  // Payment method
  const [paymentMethod, setPaymentMethod] = useState<"wallet" | "cod">("wallet");

  const load = useCallback(async () => {
    try {
      const [cRes, meRes] = await Promise.all([
        api.get<{ items: CartItem[] }>("/cart"),
        api.get<any>("/auth/me"),
      ]);
      setItems(cRes.data?.items || []);
      const bal = Number(meRes.data?.wallet_balance || 0);
      setWalletBalance(bal);
    } catch (e) { /* swallow */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    // Hydrate saved address from last checkout (one-tap reuse)
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(ADDRESS_KEY);
        if (raw) {
          const a = JSON.parse(raw);
          setName(a.name || user?.name || "");
          setPhone(a.phone || user?.phone || "");
          setLine1(a.line1 || "");
          setLine2(a.line2 || "");
          setCity(a.city || "");
          setStateName(a.state || "");
          setPincode(a.pincode || "");
        } else {
          setName(user?.name || "");
          setPhone(user?.phone || "");
        }
      } catch { /* ignore */ }
    })();
  }, [load, user]);

  const total = items.reduce((s, i) => s + ((i.line_total) || (i.product?.price || 0) * (i.qty || 1)), 0);
  const canAffordWallet = walletBalance >= total;

  const onPlaceOrder = async () => {
    // Validate
    const missing: string[] = [];
    if (!name.trim()) missing.push("Name");
    if (!phone.trim()) missing.push("Phone");
    if (!line1.trim()) missing.push("Address line 1");
    if (!city.trim()) missing.push("City");
    if (!stateName.trim()) missing.push("State");
    if (!pincode.trim() || pincode.length < 5) missing.push("Pincode (5-6 digits)");
    if (missing.length) {
      Alert.alert("Please complete the address", missing.join(", "));
      return;
    }
    if (paymentMethod === "wallet" && !canAffordWallet) {
      Alert.alert("Insufficient wallet balance", `You need ₹${total.toFixed(0)} but your wallet has ₹${walletBalance.toFixed(0)}. Switch to Cash on Delivery or top up your wallet.`);
      return;
    }
    if (items.length === 0) {
      Alert.alert("Cart is empty"); return;
    }
    setPlacing(true);
    try {
      const shipping_address = {
        name: name.trim(), phone: phone.trim(),
        line1: line1.trim(), line2: line2.trim(),
        city: city.trim(), state: stateName.trim(),
        pincode: pincode.trim(),
      };
      // Persist address for next time
      try { await AsyncStorage.setItem(ADDRESS_KEY, JSON.stringify(shipping_address)); } catch { /* ignore */ }
      const r = await api.post<any>("/orders/checkout", { payment_method: paymentMethod, shipping_address });
      Alert.alert(
        "Order placed! 🎉",
        paymentMethod === "cod"
          ? `Pay ₹${total.toFixed(0)} cash to the delivery agent on arrival.`
          : `₹${total.toFixed(0)} debited from your wallet.`,
        [{ text: "View orders", onPress: () => router.replace("/orders" as any) }],
      );
    } catch (e) { Alert.alert("Checkout failed", formatApiError(e)); }
    finally { setPlacing(false); }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  if (items.length === 0) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.headerRow}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
          <Text style={styles.title}>Checkout</Text>
          <View style={{ width: 40 }} />
        </View>
        <View style={styles.center}>
          <Feather name="shopping-cart" size={32} color={colors.textMuted} />
          <Text style={styles.emptyText}>Your cart is empty</Text>
          <TouchableOpacity onPress={() => router.replace("/shop" as any)} style={styles.primaryBtn}>
            <Text style={styles.primaryBtnText}>Browse Shop</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Checkout</Text>
        <View style={{ width: 40 }} />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={20}>
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 130 }} keyboardShouldPersistTaps="handled">
          {/* Order summary — Sept 2026 refresh: bigger thumbnails,
              clearer qty × unit-price arithmetic, sticky spacing. */}
          <Text style={styles.sectionLabel}>ORDER SUMMARY ({items.length} {items.length === 1 ? "item" : "items"})</Text>
          {items.map((it) => {
            const p = it.product || {} as any;
            const img = p.image_url;
            const nm = p.name || "Product";
            const price = p.price || 0;
            const line = it.line_total || price * (it.qty || 1);
            return (
              <View key={it.id} style={styles.lineItem}>
                {img ? (
                  <Image source={{ uri: img }} style={styles.thumb} resizeMode="cover" />
                ) : (
                  <View style={[styles.thumb, styles.thumbEmpty]}>
                    <Feather name="image" size={20} color={colors.textMuted} />
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineName} numberOfLines={2}>{nm}</Text>
                  <View style={styles.lineMetaRow}>
                    <View style={styles.qtyBadge}>
                      <Text style={styles.qtyBadgeText}>× {it.qty}</Text>
                    </View>
                    <Text style={styles.lineUnit}>{formatINR(price)} each</Text>
                  </View>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.lineTotal}>{formatINR(line)}</Text>
                </View>
              </View>
            );
          })}
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalAmount}>{formatINR(total)}</Text>
          </View>

          {/* Shipping address */}
          <Text style={styles.sectionLabel}>SHIPPING ADDRESS</Text>
          <Text style={styles.sublabel}>Full name *</Text>
          <TextInput style={styles.input} value={name} onChangeText={setName} placeholder="John Doe" placeholderTextColor={colors.textMuted} testID="addr-name" />
          <Text style={styles.sublabel}>Phone number *</Text>
          <TextInput style={styles.input} value={phone} onChangeText={setPhone} placeholder="9876543210" placeholderTextColor={colors.textMuted} keyboardType="phone-pad" maxLength={15} testID="addr-phone" />
          <Text style={styles.sublabel}>Address line 1 *</Text>
          <TextInput style={styles.input} value={line1} onChangeText={setLine1} placeholder="House / flat number, street" placeholderTextColor={colors.textMuted} maxLength={120} testID="addr-line1" />
          <Text style={styles.sublabel}>Address line 2 (optional)</Text>
          <TextInput style={styles.input} value={line2} onChangeText={setLine2} placeholder="Landmark, area" placeholderTextColor={colors.textMuted} maxLength={120} testID="addr-line2" />
          <View style={{ flexDirection: "row", gap: 10 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.sublabel}>City *</Text>
              <TextInput style={styles.input} value={city} onChangeText={setCity} placeholder="Bangalore" placeholderTextColor={colors.textMuted} testID="addr-city" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.sublabel}>State *</Text>
              <TextInput style={styles.input} value={stateName} onChangeText={setStateName} placeholder="Karnataka" placeholderTextColor={colors.textMuted} testID="addr-state" />
            </View>
          </View>
          <Text style={styles.sublabel}>Pincode *</Text>
          <TextInput style={styles.input} value={pincode} onChangeText={setPincode} placeholder="560001" placeholderTextColor={colors.textMuted} keyboardType="number-pad" maxLength={6} testID="addr-pincode" />

          {/* Payment method */}
          <Text style={styles.sectionLabel}>PAYMENT METHOD</Text>
          <TouchableOpacity
            onPress={() => setPaymentMethod("wallet")}
            style={[styles.paymentOption, paymentMethod === "wallet" && styles.paymentOptionActive, !canAffordWallet && { opacity: 0.6 }]}
            testID="pay-wallet"
          >
            <View style={styles.radio}>{paymentMethod === "wallet" ? <View style={styles.radioDot} /> : null}</View>
            <Feather name="credit-card" size={20} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.paymentTitle}>Wallet</Text>
              <Text style={styles.paymentSub}>Balance: {formatINR(walletBalance)} · Instant payment</Text>
              {!canAffordWallet ? <Text style={styles.paymentWarn}>Need {formatINR(total - walletBalance)} more</Text> : null}
            </View>
          </TouchableOpacity>

          <TouchableOpacity
            onPress={() => setPaymentMethod("cod")}
            style={[styles.paymentOption, paymentMethod === "cod" && styles.paymentOptionActive]}
            testID="pay-cod"
          >
            <View style={styles.radio}>{paymentMethod === "cod" ? <View style={styles.radioDot} /> : null}</View>
            <Feather name="tag" size={20} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.paymentTitle}>Cash on Delivery</Text>
              <Text style={styles.paymentSub}>Pay cash to the delivery agent on arrival</Text>
            </View>
          </TouchableOpacity>
        </ScrollView>

        {/* Sticky Place Order */}
        <View style={styles.stickyCta}>
          <View style={{ flex: 1 }}>
            <Text style={styles.stickyLabel}>{paymentMethod === "cod" ? "Pay on delivery" : "Total"}</Text>
            <Text style={styles.stickyAmount}>{formatINR(total)}</Text>
          </View>
          <TouchableOpacity
            onPress={onPlaceOrder}
            disabled={placing}
            style={[styles.placeBtn, placing && { opacity: 0.6 }]}
            testID="place-order"
          >
            {placing ? (
              <ActivityIndicator color={colors.primaryFg} />
            ) : (
              <>
                <Feather name="check-circle" size={18} color={colors.primaryFg} />
                <Text style={styles.placeBtnText}>Place Order</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  emptyText: { fontSize: 14, fontWeight: "700", color: colors.textMain, marginTop: 6 },
  primaryBtn: { marginTop: 12, paddingHorizontal: 18, paddingVertical: 10, borderRadius: 999, backgroundColor: colors.primary },
  primaryBtnText: { fontSize: 13, fontWeight: "800", color: colors.primaryFg },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  sectionLabel: { fontSize: 11, fontWeight: "800", letterSpacing: 1.4, color: colors.textMuted, marginTop: 18, marginBottom: 8 },
  // Line items
  lineItem: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  thumb: { width: 68, height: 68, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  thumbEmpty: { alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, borderStyle: "dashed" },
  lineName: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  lineMetaRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6 },
  qtyBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6, backgroundColor: colors.primary + "1A" },
  qtyBadgeText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.3 },
  lineUnit: { fontSize: 11, color: colors.textMuted, fontWeight: "600" },
  lineQty: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  lineTotal: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  totalRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12, backgroundColor: colors.brand100, borderRadius: 12, marginTop: 4 },
  totalLabel: { fontSize: 12, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  totalAmount: { fontSize: 19, fontWeight: "900", color: colors.primary, letterSpacing: -0.4 },
  // Address fields
  sublabel: { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginTop: 8, marginBottom: 4 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  // Payment options
  paymentOption: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 2, borderColor: colors.border, marginBottom: 8 },
  paymentOptionActive: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.primary, alignItems: "center", justifyContent: "center" },
  radioDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: colors.primary },
  paymentTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  paymentSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  paymentWarn: { fontSize: 11, fontWeight: "700", color: "#B91C1C", marginTop: 2 },
  // Sticky CTA
  stickyCta: { position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.screen, paddingTop: 12, paddingBottom: 20, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, gap: 14 },
  stickyLabel: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.8 },
  stickyAmount: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  placeBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 20, paddingVertical: 14, borderRadius: 999, backgroundColor: colors.primary },
  placeBtnText: { fontSize: 14, fontWeight: "900", color: colors.primaryFg, letterSpacing: -0.2 },
});
