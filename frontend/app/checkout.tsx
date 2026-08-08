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
import { api, formatApiError, resolveImageUrl } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";
import OutOfZoneModal from "../src/OutOfZoneModal";
import { useDeliveryLocation } from "../src/use-delivery-location";

type CartItem = { id: string; product_id: string; qty: number; product: { name: string; price: number; image_url: string }; line_total: number };

const ADDRESS_KEY = "@checkout-address-v1";

export default function CheckoutScreen() {
  const router = useRouter();
  const { user } = useAuth();
  // Dec 2026 — shared delivery-location hook so coords captured on the
  // Shop tab auto-flow into checkout.  Previously the customer had to
  // tap "Use current location" AGAIN here (many didn't), which meant
  // the backend never received lat/lng and the radius-mode delivery
  // check always failed — surfacing as "Some items can't be delivered"
  // even when the user was clearly within the vendor's radius.
  const deliveryLoc = useDeliveryLocation();
  const [items, setItems] = useState<CartItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [placing, setPlacing] = useState(false);
  const [walletBalance, setWalletBalance] = useState<number>(0);
  // Nov 2026 — Out-of-delivery-zone modal state (replaces plain Alert).
  const [oozOpen, setOozOpen] = useState(false);
  const [oozConflicts, setOozConflicts] = useState<string[]>([]);
  // Address fields
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [pincode, setPincode] = useState("");
  // Sept 2026 — Geospatial GPS capture for delivery-radius verification.
  const [gpsLat, setGpsLat] = useState<number | null>(null);
  const [gpsLng, setGpsLng] = useState<number | null>(null);
  const [gpsDistrict, setGpsDistrict] = useState<string>("");
  const [gpsBusy, setGpsBusy] = useState(false);

  const captureAddressGps = async () => {
    setGpsBusy(true);
    try {
      const Location = await import("expo-location");
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        Alert.alert(
          "Location required",
          perm.canAskAgain
            ? "Grant location permission to auto-fill your address."
            : "Location is blocked. Open Settings to enable it for this app.",
        );
        return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const { latitude, longitude } = pos.coords;
      setGpsLat(latitude);
      setGpsLng(longitude);
      // Nov 2026 — Prefer our own /geo/reverse (Nominatim) — it returns
      // pincode reliably, whereas device-side reverseGeocodeAsync often
      // omits `postalCode` on Android.  Always OVERWRITE the address
      // fields so the "Use current" tap feels definitive (per user
      // directive — one tap should apply and persist).
      let filled = false;
      try {
        const r = await api.get<any>("/geo/reverse", { params: { lat: latitude, lng: longitude } });
        const d = r.data || {};
        if (d.pincode) { setPincode(d.pincode); filled = true; }
        if (d.state) { setStateName(d.state); filled = true; }
        if (d.city || d.area) { setCity(d.city || d.area); filled = true; }
        if (d.district) setGpsDistrict(d.district);
        const line = [d.area, d.city].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(", ");
        if (line) setLine1(line);
      } catch { /* fall through to device reverse-geocode */ }
      if (!filled) {
        try {
          const rev = await Location.reverseGeocodeAsync({ latitude, longitude });
          if (rev && rev.length > 0) {
            const r0 = rev[0];
            if (r0.postalCode) setPincode(r0.postalCode);
            if (r0.region) setStateName(r0.region);
            if (r0.city) setCity(r0.city);
            setGpsDistrict((r0.subregion || r0.district || ""));
            const parts = [r0.name, r0.street].filter(Boolean);
            if (parts.length > 0) setLine1(parts.join(", "));
          }
        } catch { /* reverse geocode best-effort */ }
      }
      // Persist the freshly-captured address so the next visit hydrates
      // it automatically without another GPS prompt.
      try {
        const snapshot = {
          name: user?.name || "",
          phone: user?.phone || "",
          line1: line1 || "",
          line2, city, state: stateName, pincode,
          latitude, longitude,
        };
        // Delay persist by a tick so useState updates settle.
        setTimeout(() => AsyncStorage.setItem(ADDRESS_KEY, JSON.stringify(snapshot)).catch(() => {}), 200);
      } catch { /* ignore */ }
    } catch (e: any) {
      Alert.alert("Couldn't capture location", e?.message || "Try again in a moment.");
    } finally { setGpsBusy(false); }
  };
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
          // Sept 2026 — Hydrate previously-captured GPS so a repeat
          // buyer doesn't have to re-grant permission.
          if (typeof a.latitude === "number") setGpsLat(a.latitude);
          if (typeof a.longitude === "number") setGpsLng(a.longitude);
          if (a.district) setGpsDistrict(a.district);
        } else {
          setName(user?.name || "");
          setPhone(user?.phone || "");
        }
      } catch { /* ignore */ }
    })();
  }, [load, user]);

  // Dec 2026 — When the checkout-local address snapshot has NO lat/lng
  // (e.g. the customer entered the address by hand on this page but had
  // already granted GPS on the Shop tab), copy the shared coords over so
  // the backend's radius-mode delivery check has data to work with.
  useEffect(() => {
    if (gpsLat !== null && gpsLng !== null) return;
    if (deliveryLoc.coords && typeof deliveryLoc.coords.lat === "number" && typeof deliveryLoc.coords.lng === "number") {
      setGpsLat(deliveryLoc.coords.lat);
      setGpsLng(deliveryLoc.coords.lng);
    }
  }, [deliveryLoc.coords, gpsLat, gpsLng]);

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
      // Sept 2026 — Geospatial extras.  If the user captured GPS via the
      // "Use current location" flow, forward lat/lng + district to the
      // backend so `/orders/checkout` can run the second delivery-radius
      // verification.  Missing coords are OK — backend falls back to
      // pincode-exact matching.
      const shipping_address = {
        name: name.trim(), phone: phone.trim(),
        line1: line1.trim(), line2: line2.trim(),
        city: city.trim(), state: stateName.trim(),
        pincode: pincode.trim(),
        latitude: gpsLat, longitude: gpsLng,
        district: gpsDistrict || undefined,
      };
      // Persist address (with GPS) for next time
      try { await AsyncStorage.setItem(ADDRESS_KEY, JSON.stringify(shipping_address)); } catch { /* ignore */ }
      const r = await api.post<any>("/orders/checkout", { payment_method: paymentMethod, shipping_address });
      Alert.alert(
        "Order placed! 🎉",
        paymentMethod === "cod"
          ? `Pay ₹${total.toFixed(0)} cash to the delivery agent on arrival.`
          : `₹${total.toFixed(0)} debited from your wallet.`,
        [{ text: "View orders", onPress: () => router.replace("/orders" as any) }],
      );
    } catch (e: any) {
      // Nov 2026 — Out-of-delivery-zone handling.  Server returns detail={
      //   code: "out_of_delivery_zone", message: "...", conflicts: [...] }
      const detail = e?.response?.data?.detail;
      if (detail && typeof detail === "object" && detail.code === "out_of_delivery_zone") {
        // Nov 2026 — Show the redesigned bottom-sheet modal instead of
        // the plain Alert.  Gives the customer clear next-steps (change
        // address vs remove ineligible items).
        const list = Array.isArray(detail.conflicts) ? detail.conflicts : [];
        setOozConflicts(list);
        setOozOpen(true);
      } else {
        Alert.alert("Checkout failed", formatApiError(e));
      }
    }
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
            const img = resolveImageUrl(p.image_url);
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

          {/* Nov 2026 — Big prominent "Use current location" CTA.
              Previously buried as a small chip in the section header.
              One tap auto-fills every shipping field (line1, city,
              state, pincode) from the device GPS + Nominatim, and
              persists the snapshot to AsyncStorage so the next visit
              hydrates it automatically without another GPS prompt.
              User can still edit any field manually afterwards. */}
          <TouchableOpacity
            onPress={captureAddressGps}
            disabled={gpsBusy}
            activeOpacity={0.85}
            style={[styles.gpsCard, (gpsLat !== null && gpsLng !== null) && styles.gpsCardActive]}
            testID="checkout-gps"
          >
            <View style={[styles.gpsIconRing, (gpsLat !== null && gpsLng !== null) && { backgroundColor: colors.brand100 }]}>
              {gpsBusy
                ? <ActivityIndicator color={colors.primary} />
                : <Feather name="crosshair" size={22} color={colors.primary} />}
            </View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.gpsCardTitle}>
                {gpsLat !== null && gpsLng !== null ? "Using current location" : "Use my current location"}
              </Text>
              <Text style={styles.gpsCardSub} numberOfLines={2}>
                {gpsLat !== null && gpsLng !== null
                  ? `${gpsDistrict ? gpsDistrict + " · " : ""}Auto-filled below.  Tap to refresh.`
                  : "One tap to auto-fill your delivery address."}
              </Text>
            </View>
            <Feather
              name={gpsLat !== null && gpsLng !== null ? "refresh-cw" : "chevron-right"}
              size={18}
              color={colors.primary}
            />
          </TouchableOpacity>
          {gpsLat !== null && gpsLng !== null ? (
            <View style={styles.gpsCoordChip} testID="checkout-gps-chip">
              <Feather name="check" size={11} color={colors.success || "#16A34A"} />
              <Text style={styles.gpsCoordText}>
                GPS · {gpsLat.toFixed(5)}, {gpsLng.toFixed(5)}
              </Text>
            </View>
          ) : null}
          <View style={{ height: 8 }} />
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
      {/* Nov 2026 — Out-of-delivery-zone bottom sheet */}
      <OutOfZoneModal
        visible={oozOpen}
        conflicts={oozConflicts}
        onClose={() => setOozOpen(false)}
        onChangeAddress={() => {
          // Focus the pincode field so the user can adjust immediately.
          setPincode("");
        }}
      />
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
  // Sept 2026 — GPS capture chip on the checkout address form.
  gpsBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface, minHeight: 30 },
  // Nov 2026 — Prominent GPS CTA card
  gpsCard: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 14, marginTop: 4,
    borderRadius: 16, borderWidth: 1, borderColor: colors.primary,
    backgroundColor: colors.brand100,
  },
  gpsCardActive: { backgroundColor: colors.surface, borderColor: colors.primary },
  gpsIconRing: {
    width: 46, height: 46, borderRadius: 23,
    backgroundColor: "#fff",
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: colors.primary,
  },
  gpsCardTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  gpsCardSub: { fontSize: 12, color: colors.textMuted, marginTop: 3, lineHeight: 16 },
  gpsBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.3 },
  gpsCoordChip: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: (colors.success || "#16A34A") + "1A", paddingHorizontal: 8, paddingVertical: 5, borderRadius: 6, alignSelf: "flex-start", marginTop: 4, marginBottom: 4 },
  gpsCoordText: { fontSize: 10, color: colors.success || "#16A34A", fontWeight: "800", letterSpacing: 0.3 },
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
