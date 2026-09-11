// Checkout — shipping address form + payment method selection (Wallet / COD)
// + sticky Place Order button. Posts to /api/orders/checkout which decrements
// stock atomically and either debits the wallet (wallet) or marks the order
// `paid_via: "cod"` for cash-on-delivery.
import { useEffect, useRef, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity,
  ActivityIndicator, KeyboardAvoidingView, Platform, Image, Modal, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import AsyncStorage from "@react-native-async-storage/async-storage";
import Slider from "@react-native-community/slider";
import { WebView } from "react-native-webview";
import { api, formatApiError, resolveImageUrl } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";
import { useShopMoneyConfig, effectiveCashbackPct, cashbackAmount } from "../src/cashback";
import { notify } from "../src/notify";
import OutOfZoneModal from "../src/OutOfZoneModal";
import { useDeliveryLocation } from "../src/use-delivery-location";
import { openRazorpayCheckout, buildRazorpayHtml, RazorpayResult } from "../src/razorpay";

type CartItem = { id: string; product_id: string; qty: number; product: { name: string; price: number; image_url: string; vendor_id?: string | null; vendor_name?: string | null }; line_total: number };

const ADDRESS_KEY = "@checkout-address-v1";

export default function CheckoutScreen() {
  const moneyCfg = useShopMoneyConfig();
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
        notify(
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
      notify("Couldn't capture location", e?.message || "Try again in a moment.");
    } finally { setGpsBusy(false); }
  };
  // Payment method — Jun 2026 adds the "wallet_cod" combo where the
  // wallet covers part of the bill and cash covers the rest, plus the
  // Razorpay "online" / "wallet_online" options.
  const [paymentMethod, setPaymentMethod] = useState<"wallet" | "cod" | "wallet_cod" | "online" | "wallet_online">("wallet");
  // How much of the bill the wallet should cover in combo mode.
  const [walletSplit, setWalletSplit] = useState(0);
  const [splitTouched, setSplitTouched] = useState(false);
  // Razorpay WebView (native only) — resolved through a ref'd promise.
  const [rzpHtml, setRzpHtml] = useState("");
  const [rzpVisible, setRzpVisible] = useState(false);
  const rzpResolver = useRef<((r: RazorpayResult) => void) | null>(null);
  const [payStage, setPayStage] = useState<"idle" | "creating" | "paying" | "verifying" | "placing">("idle");
  // A Razorpay payment that was captured but whose order never got placed
  // (app closed / network drop). We offer to finish it instead of charging again.
  const [pendingPay, setPendingPay] = useState<
    { payment_id: string; online_amount: number; wallet_amount: number; total: number } | null
  >(null);

  const load = useCallback(async () => {
    try {
      const [cRes, meRes, pRes] = await Promise.all([
        api.get<{ items: CartItem[] }>("/cart"),
        api.get<any>("/auth/me"),
        api.get<any>("/orders/payment/pending").catch(() => ({ data: { pending: null } })),
      ]);
      setItems(cRes.data?.items || []);
      const bal = Number(meRes.data?.wallet_balance || 0);
      setWalletBalance(bal);
      setPendingPay(pRes.data?.pending || null);
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

  const goodsTotal = items.reduce((s, i) => s + ((i.line_total) || (i.product?.price || 0) * (i.qty || 1)), 0);
  // Jun 2026 — one order per SELLER. Show the split before paying so the
  // buyer knows exactly how many orders/deliveries to expect.
  const sellerGroups: { key: string; name: string; lines: CartItem[]; subTotal: number }[] = [];
  items.forEach((it) => {
    const key = it.product?.vendor_id || "__slangcart__";
    let g = sellerGroups.find((x) => x.key === key);
    if (!g) {
      g = { key, name: it.product?.vendor_name || "Slangcart Store", lines: [], subTotal: 0 };
      sellerGroups.push(g);
    }
    g.lines.push(it);
    g.subTotal += it.line_total || (it.product?.price || 0) * (it.qty || 1);
  });
  const multiSeller = sellerGroups.length > 1;

  // ── Delivery charges (Jun-2026) ──────────────────────────────────────
  // Mirrors core/delivery_charges.py: priced per seller from that seller's
  // own subtotal, then capped for the whole cart. The server recomputes
  // and is authoritative — this is so the buyer sees the same figure.
  const deliveryRows = sellerGroups.map((g) => {
    const allFree = g.lines.every((l) => !!l.product?.free_delivery);
    if (!moneyCfg.delivery_charge_enabled || allFree) return { key: g.key, charge: 0, free: true };
    if (moneyCfg.delivery_free_threshold > 0 && g.subTotal >= moneyCfg.delivery_free_threshold - 0.009) {
      return { key: g.key, charge: 0, free: true };
    }
    return { key: g.key, charge: moneyCfg.delivery_charge_flat, free: moneyCfg.delivery_charge_flat <= 0 };
  });
  const deliveryRaw = Math.round(deliveryRows.reduce((a, r) => a + r.charge, 0) * 100) / 100;
  const deliveryCapped = moneyCfg.delivery_cart_max > 0 && deliveryRaw > moneyCfg.delivery_cart_max;
  const deliveryTotal = deliveryCapped ? moneyCfg.delivery_cart_max : deliveryRaw;
  // Cashback promised on this basket — paid after successful delivery.
  const cashbackTotal = Math.round(items.reduce((a, i) => a + cashbackAmount(
    i.line_total || (i.product?.price || 0) * (i.qty || 1),
    effectiveCashbackPct(i.product || {}, moneyCfg),
    moneyCfg.max_cashback_pct,
  ), 0) * 100) / 100;
  // Everything the buyer owes: goods + delivery.
  const total = Math.round((goodsTotal + deliveryTotal) * 100) / 100;

  const canAffordWallet = walletBalance >= total;
  // Jun 2026 — Wallet+COD combo maths. `maxWalletUsable` is the most the
  // wallet can contribute; the slider defaults to that (auto-max) and the
  // buyer can drag it down to ₹0 to pay more in cash.
  const maxWalletUsable = Math.min(walletBalance, total);
  const comboMode = paymentMethod === "wallet_cod" || paymentMethod === "wallet_online";
  // In the ONLINE combo the gateway must have at least ₹1 left to collect —
  // otherwise the wallet covers everything and there is nothing to pay
  // online (that's just the plain Wallet option).
  const comboMax = Math.floor(
    paymentMethod === "wallet_online" ? Math.max(0, Math.min(maxWalletUsable, total - 1)) : maxWalletUsable,
  );
  const walletPart = comboMode
    ? Math.max(0, Math.min(Math.round(walletSplit), comboMax))
    : paymentMethod === "wallet" ? total : 0;
  const cashPart = Math.max(0, Math.round((total - walletPart) * 100) / 100);
  // "Pay online" total — the slice Razorpay must collect.
  const onlinePart = paymentMethod === "online" ? total : paymentMethod === "wallet_online" ? cashPart : 0;

  // Auto-max the wallet the first time a combo option is selected.  For the
  // ONLINE combo, when the wallet could cover the whole bill, default to a
  // 50/50 split instead of "everything-but-₹1" (which is just the Wallet
  // option with extra steps).
  const comboDefault = paymentMethod === "wallet_online" && maxWalletUsable >= total
    ? Math.floor(total / 2)
    : comboMax;
  useEffect(() => {
    if (comboMode && !splitTouched) {
      setWalletSplit(comboDefault);
    }
  }, [comboMode, comboDefault, splitTouched]);

  // ── Razorpay plumbing ─────────────────────────────────────────────────
  // Web opens Razorpay's JS checkout directly; native renders their hosted
  // page inside a WebView and resolves through this ref'd promise.
  const openNativeRazorpay = (html: string): Promise<RazorpayResult> =>
    new Promise((resolve) => {
      rzpResolver.current = resolve;
      setRzpHtml(html);
      setRzpVisible(true);
    });

  const handleRzpMessage = (raw: string) => {
    let data: any = {};
    try { data = JSON.parse(raw); } catch { data = {}; }
    const resolver = rzpResolver.current;
    rzpResolver.current = null;
    setRzpVisible(false);
    setTimeout(() => setRzpHtml(""), 250);
    if (!resolver) return;
    if (data.type === "success") {
      resolver({ ok: true, paymentId: data.payment_id, orderId: data.order_id, signature: data.signature });
    } else if (data.type === "cancel") {
      resolver({ ok: false, cancelled: true });
    } else {
      resolver({ ok: false, error: data.error || "Payment failed", code: data.code });
    }
  };

  /** Run the Razorpay leg and return the verified attempt id (or null if
   *  the shopper backed out). Throws with a readable message on failure. */
  const collectOnlinePayment = async (): Promise<string | null> => {
    setPayStage("creating");
    const { data: start } = await api.post<{
      payment_id: string; razorpay_order_id: string; amount_paise: number;
      key_id: string; is_mock: boolean; description?: string;
      prefill?: { name?: string; email?: string; contact?: string };
    }>("/orders/payment/start", {
      wallet_amount: paymentMethod === "wallet_online" ? walletPart : 0,
    });

    let result: RazorpayResult;
    setPayStage("paying");
    if (start.is_mock) {
      // Sandbox mode (no Razorpay keys configured yet) — simulate the
      // gateway round-trip so the rest of the flow is exercised for real.
      await new Promise((r) => setTimeout(r, 1200));
      result = {
        ok: true,
        paymentId: `pay_MOCK_${Math.random().toString(36).slice(2, 14)}`,
        orderId: start.razorpay_order_id,
        signature: `sig_MOCK_${Math.random().toString(36).slice(2, 20)}`,
      };
    } else {
      const opts = {
        orderId: start.razorpay_order_id,
        amountPaise: start.amount_paise,
        keyId: start.key_id,
        name: "Slangcart",
        description: start.description || "Slangcart order",
        prefill: {
          name: start.prefill?.name || name,
          email: start.prefill?.email || (user as any)?.email,
          contact: start.prefill?.contact || phone,
        },
        themeColor: colors.primary,
      };
      result = Platform.OS === "web"
        ? await openRazorpayCheckout(opts)
        : await openNativeRazorpay(buildRazorpayHtml(opts));
    }

    if (!result.ok) {
      if (result.cancelled) return null;
      throw new Error(result.error || "Payment failed");
    }

    setPayStage("verifying");
    await api.post("/orders/payment/verify", {
      payment_id: start.payment_id,
      razorpay_order_id: result.orderId || start.razorpay_order_id,
      razorpay_payment_id: result.paymentId,
      razorpay_signature: result.signature,
    });
    return start.payment_id;
  };

  const announcePlaced = (data: any) => {
    const splitCount = Number(data?.split_count || 1);
    const codDue = Number(data?.cod_due || 0);
    const walletUsed = Number(data?.wallet_paid || 0);
    const onlineUsed = Number(data?.online_paid || 0);
    const lines: string[] = [];
    if (splitCount > 1) {
      lines.push(`Split into ${splitCount} orders — one per seller, each tracked separately.`);
    }
    if (walletUsed > 0) lines.push(`₹${walletUsed.toFixed(0)} debited from your wallet.`);
    if (onlineUsed > 0) lines.push(`₹${onlineUsed.toFixed(0)} paid online.`);
    if (codDue > 0) lines.push(`₹${codDue.toFixed(0)} to pay in cash on delivery.`);
    notify(
      splitCount > 1 ? `${splitCount} orders placed! 🎉` : "Order placed! 🎉",
      lines.join("\n") || `₹${Number(data?.grand_total || total).toFixed(0)} confirmed.`,
      [{ text: "View orders", onPress: () => router.replace("/orders" as any) }],
    );
  };

  const addressMissing = () => {
    const missing: string[] = [];
    if (!name.trim()) missing.push("Name");
    if (!phone.trim()) missing.push("Phone");
    if (!line1.trim()) missing.push("Address line 1");
    if (!city.trim()) missing.push("City");
    if (!stateName.trim()) missing.push("State");
    if (!pincode.trim() || pincode.length < 5) missing.push("Pincode (5-6 digits)");
    return missing;
  };

  /** Finish a checkout whose Razorpay money was already captured. */
  const resumePendingPayment = async () => {
    if (!pendingPay) return;
    const missing = addressMissing();
    if (missing.length) {
      notify("Please complete the address", missing.join(", "));
      return;
    }
    setPlacing(true);
    setPayStage("placing");
    try {
      const r = await api.post<any>("/orders/checkout", {
        payment_method: pendingPay.wallet_amount > 0 ? "wallet_online" : "online",
        wallet_amount: pendingPay.wallet_amount > 0 ? pendingPay.wallet_amount : undefined,
        payment_id: pendingPay.payment_id,
        shipping_address: {
          name: name.trim(), phone: phone.trim(),
          line1: line1.trim(), line2: line2.trim(),
          city: city.trim(), state: stateName.trim(),
          pincode: pincode.trim(),
          latitude: gpsLat, longitude: gpsLng,
          district: gpsDistrict || undefined,
        },
      });
      setPendingPay(null);
      announcePlaced(r.data);
    } catch (e) {
      notify("Couldn't complete the order", formatApiError(e));
    } finally { setPlacing(false); setPayStage("idle"); }
  };

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
      notify("Please complete the address", missing.join(", "));
      return;
    }
    if (paymentMethod === "wallet" && !canAffordWallet) {
      notify("Insufficient wallet balance", `You need ₹${total.toFixed(0)} but your wallet has ₹${walletBalance.toFixed(0)}. Switch to Cash on Delivery or top up your wallet.`);
      return;
    }
    if (paymentMethod === "wallet_cod" && walletPart <= 0) {
      notify("Nothing from wallet", "Drag the slider up to use wallet money, or pick Cash on Delivery.");
      return;
    }
    if (paymentMethod === "wallet_online" && walletPart <= 0) {
      notify("Nothing from wallet", "Drag the slider up to use wallet money, or pay the full amount online.");
      return;
    }
    if (items.length === 0) {
      notify("Cart is empty"); return;
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

      // Online methods collect the money FIRST, then place the order with
      // the verified payment id.  A dismissed Razorpay sheet aborts quietly.
      let paymentId: string | null = null;
      const needsGateway = paymentMethod === "online" || (paymentMethod === "wallet_online" && onlinePart > 0);
      if (needsGateway) {
        paymentId = await collectOnlinePayment();
        if (!paymentId) {
          setPayStage("idle");
          setPlacing(false);
          return;
        }
      }

      setPayStage("placing");
      const effectiveMethod = paymentMethod === "wallet_online" && !needsGateway ? "wallet" : paymentMethod;
      const r = await api.post<any>("/orders/checkout", {
        payment_method: effectiveMethod,
        wallet_amount: comboMode && effectiveMethod !== "wallet" ? walletPart : undefined,
        payment_id: paymentId || undefined,
        shipping_address,
      });
      // Jun 2026 — checkout now returns one order per vendor.
      announcePlaced(r.data);
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
        notify("Checkout failed", formatApiError(e));
      }
    }
    finally { setPlacing(false); setPayStage("idle"); }
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
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: comboMode ? 300 : 130 }} keyboardShouldPersistTaps="handled">
          {pendingPay ? (
            <View style={styles.pendingPayBox} testID="pending-payment-banner">
              <Feather name="alert-circle" size={18} color="#B45309" />
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.pendingPayTitle}>
                  {formatINR(pendingPay.online_amount)} already paid
                </Text>
                <Text style={styles.pendingPaySub}>
                  Your last payment went through but the order wasn&apos;t placed. Finish it now —
                  you won&apos;t be charged again.
                </Text>
              </View>
              <TouchableOpacity
                onPress={resumePendingPayment}
                disabled={placing}
                style={styles.pendingPayBtn}
                testID="pending-payment-resume"
              >
                <Text style={styles.pendingPayBtnText}>Finish</Text>
              </TouchableOpacity>
            </View>
          ) : null}
          {/* Order summary — Sept 2026 refresh: bigger thumbnails,
              clearer qty × unit-price arithmetic, sticky spacing. */}
          <Text style={styles.sectionLabel}>ORDER SUMMARY ({items.length} {items.length === 1 ? "item" : "items"})</Text>
          {multiSeller ? (
            <View style={styles.splitNotice} testID="checkout-split-notice">
              <Feather name="git-branch" size={15} color={colors.primary} />
              <Text style={styles.splitNoticeText}>
                {sellerGroups.length} sellers in this bag — we&apos;ll place {sellerGroups.length} separate
                orders so each seller ships and updates you independently.
              </Text>
            </View>
          ) : null}
          {sellerGroups.map((g, gi) => (
            <View key={g.key} testID={`checkout-seller-${g.key}`}>
              {multiSeller ? (
                <View style={styles.sellerHeader}>
                  <View style={styles.sellerBadge}>
                    <Text style={styles.sellerBadgeText}>ORDER {gi + 1}</Text>
                  </View>
                  <Text style={styles.sellerName} numberOfLines={1}>{g.name}</Text>
                  <Text style={styles.sellerSub}>{formatINR(g.subTotal)}</Text>
                </View>
              ) : null}
              {g.lines.map((it) => {
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
            </View>
          ))}
          <View style={styles.breakdownRow}>
            <Text style={styles.breakdownLabel}>Items subtotal</Text>
            <Text style={styles.breakdownValue}>{formatINR(goodsTotal)}</Text>
          </View>
          <View style={styles.breakdownRow} testID="checkout-delivery-row">
            <Text style={styles.breakdownLabel}>
              Delivery{deliveryCapped ? ` (capped at ${formatINR(moneyCfg.delivery_cart_max)})` : ""}
            </Text>
            <Text style={[styles.breakdownValue, deliveryTotal <= 0 && { color: colors.success }]}>
              {deliveryTotal <= 0 ? "FREE" : formatINR(deliveryTotal)}
            </Text>
          </View>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalAmount}>{formatINR(total)}</Text>
          </View>
          {cashbackTotal > 0 ? (
            <View style={styles.cashbackBanner} testID="checkout-cashback">
              <Feather name="gift" size={14} color="#15803D" />
              <Text style={styles.cashbackBannerText}>
                {formatINR(cashbackTotal)} cashback to your wallet after successful delivery
              </Text>
            </View>
          ) : null}

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

          {/* Jun 2026 — Wallet + Cash combo. Slider starts at the max
              usable wallet amount (auto-max) and can be dragged down so
              the buyer decides how much cash to hand over on delivery. */}
          <TouchableOpacity
            onPress={() => setPaymentMethod("wallet_cod")}
            disabled={maxWalletUsable <= 0}
            style={[
              styles.paymentOption,
              paymentMethod === "wallet_cod" && styles.paymentOptionActive,
              maxWalletUsable <= 0 && { opacity: 0.5 },
            ]}
            testID="pay-wallet-cod"
          >
            <View style={styles.radio}>{paymentMethod === "wallet_cod" ? <View style={styles.radioDot} /> : null}</View>
            <Feather name="pie-chart" size={20} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.paymentTitle}>Wallet + Cash on Delivery</Text>
              <Text style={styles.paymentSub}>
                {maxWalletUsable <= 0
                  ? "Add wallet money to use this option"
                  : "Use part of your wallet, pay the rest in cash"}
              </Text>
            </View>
          </TouchableOpacity>

          {/* Jun 2026 — Razorpay online payment (UPI / Card / Netbanking). */}
          <TouchableOpacity
            onPress={() => setPaymentMethod("online")}
            style={[
              styles.paymentOption,
              (paymentMethod === "online" || paymentMethod === "wallet_online") && styles.paymentOptionActive,
            ]}
            testID="pay-online"
          >
            <View style={styles.radio}>
              {(paymentMethod === "online" || paymentMethod === "wallet_online") ? <View style={styles.radioDot} /> : null}
            </View>
            <Feather name="smartphone" size={20} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.paymentTitle}>Pay Online</Text>
              <Text style={styles.paymentSub}>UPI, cards & netbanking · secured by Razorpay</Text>
            </View>
          </TouchableOpacity>

          {(paymentMethod === "online" || paymentMethod === "wallet_online") && maxWalletUsable > 0 ? (
            <View style={styles.walletToggleRow} testID="online-use-wallet-row">
              <Feather name="credit-card" size={16} color={colors.primary} />
              <Text style={styles.walletToggleText}>
                Use my wallet balance too ({formatINR(walletBalance)})
              </Text>
              <Switch
                value={paymentMethod === "wallet_online"}
                onValueChange={(on) => {
                  setSplitTouched(false);
                  setPaymentMethod(on ? "wallet_online" : "online");
                }}
                trackColor={{ true: colors.primary, false: colors.border }}
                testID="online-use-wallet"
              />
            </View>
          ) : null}

          {comboMode ? (
            <View style={styles.splitBox} testID="wallet-split-box">
              <View style={styles.splitRow}>
                <View style={styles.splitCell}>
                  <Text style={styles.splitLabel}>FROM WALLET</Text>
                  <Text style={styles.splitValueWallet} testID="split-wallet-amount">{formatINR(walletPart)}</Text>
                </View>
                <View style={styles.splitDivider} />
                <View style={[styles.splitCell, { alignItems: "flex-end" }]}>
                  <Text style={styles.splitLabel}>
                    {paymentMethod === "wallet_online" ? "PAY ONLINE" : "CASH ON DELIVERY"}
                  </Text>
                  <Text style={styles.splitValueCash} testID="split-cash-amount">{formatINR(cashPart)}</Text>
                </View>
              </View>

              <Slider
                style={{ width: "100%", height: 40 }}
                minimumValue={0}
                maximumValue={Math.max(1, comboMax)}
                step={1}
                value={walletPart}
                onValueChange={(v: number) => { setSplitTouched(true); setWalletSplit(v); }}
                minimumTrackTintColor={colors.primary}
                maximumTrackTintColor={colors.border}
                thumbTintColor={colors.primary}
                testID="wallet-split-slider"
              />

              <View style={styles.splitQuickRow}>
                {[0, 0.25, 0.5, 0.75, 1].map((f) => {
                  // Percentages are of the BILL (so 50% is exactly half the
                  // order), clamped to what the wallet can legally cover.
                  const amt = Math.min(comboMax, Math.floor(total * f));
                  const active = walletPart === amt;
                  return (
                    <TouchableOpacity
                      key={f}
                      onPress={() => { setSplitTouched(true); setWalletSplit(amt); }}
                      style={[styles.splitChip, active && styles.splitChipActive]}
                      testID={`split-chip-${f}`}
                    >
                      <Text style={[styles.splitChipText, active && styles.splitChipTextActive]}>
                        {f === 0 ? "₹0" : f === 1 ? "Max" : `${f * 100}%`}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
              <Text style={styles.splitHint}>
                Wallet balance {formatINR(walletBalance)} · drag to change the split
                {paymentMethod === "wallet_online" ? " · at least ₹1 is paid online" : ""}
              </Text>
            </View>
          ) : null}
        </ScrollView>

        {/* Sticky Place Order */}
        <View style={styles.stickyCta}>
          <View style={{ flex: 1 }}>
            <Text style={styles.stickyLabel}>
              {paymentMethod === "cod" ? "PAY ON DELIVERY"
                : paymentMethod === "wallet_cod" ? `WALLET ${formatINR(walletPart)} + CASH`
                : paymentMethod === "wallet_online" ? `WALLET ${formatINR(walletPart)} + ONLINE`
                : paymentMethod === "online" ? "PAY ONLINE" : "TOTAL"}
            </Text>
            <Text style={styles.stickyAmount}>
              {comboMode ? formatINR(cashPart) : formatINR(total)}
            </Text>
            {comboMode ? (
              <Text style={styles.stickySub}>of {formatINR(total)} total</Text>
            ) : null}
          </View>
          <TouchableOpacity
            onPress={onPlaceOrder}
            disabled={placing}
            style={[styles.placeBtn, placing && { opacity: 0.6 }]}
            testID="place-order"
          >
            {placing ? (
              <>
                <ActivityIndicator color={colors.primaryFg} />
                {payStage !== "idle" ? (
                  <Text style={styles.placeBtnText}>
                    {payStage === "creating" ? "Starting…"
                      : payStage === "paying" ? "Paying…"
                      : payStage === "verifying" ? "Verifying…" : "Placing…"}
                  </Text>
                ) : null}
              </>
            ) : (
              <>
                <Feather name={onlinePart > 0 ? "lock" : "check-circle"} size={18} color={colors.primaryFg} />
                <Text style={styles.placeBtnText}>
                  {onlinePart > 0 ? `Pay ${formatINR(onlinePart)}` : "Place Order"}
                </Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      {/* Razorpay hosted checkout (native only — web opens their JS modal) */}
      <Modal visible={rzpVisible} animationType="slide" onRequestClose={() => handleRzpMessage('{"type":"cancel"}')}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.headerRow}>
            <TouchableOpacity
              onPress={() => handleRzpMessage('{"type":"cancel"}')}
              style={styles.iconBtn}
              testID="rzp-close"
            >
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>Secure payment</Text>
            <View style={{ width: 40 }} />
          </View>
          {rzpHtml ? (
            <WebView
              originWhitelist={["*"]}
              source={{ html: rzpHtml }}
              onMessage={(e) => handleRzpMessage(e.nativeEvent.data)}
              javaScriptEnabled
              domStorageEnabled
              style={{ flex: 1 }}
            />
          ) : null}
        </SafeAreaView>
      </Modal>
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
  // Jun 2026 — multi-seller split preview
  splitNotice: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.primary + "10", borderRadius: 14,
    borderWidth: 1, borderColor: colors.primary + "40",
    padding: 12, marginBottom: 12,
  },
  splitNoticeText: { flex: 1, fontSize: 11.5, color: colors.textMain, fontWeight: "600", lineHeight: 16 },
  walletToggleRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 12, paddingVertical: 8, marginBottom: 8,
    borderRadius: 12, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  walletToggleText: { flex: 1, fontSize: 12, fontWeight: "700", color: colors.textMain },
  pendingPayBox: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "#FEF3C7", borderColor: "#FCD34D", borderWidth: 1,
    borderRadius: 14, padding: 12, marginBottom: 4,
  },
  pendingPayTitle: { fontSize: 13, fontWeight: "900", color: "#92400E" },
  pendingPaySub: { fontSize: 11, color: "#92400E", marginTop: 2, lineHeight: 15 },
  pendingPayBtn: { backgroundColor: "#92400E", borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8 },
  pendingPayBtnText: { color: "#fff", fontSize: 12, fontWeight: "900" },
  sellerHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8, paddingHorizontal: 2 },
  sellerBadge: { backgroundColor: colors.primary, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  sellerBadgeText: { fontSize: 9.5, fontWeight: "900", color: colors.primaryFg, letterSpacing: 0.6 },
  sellerName: { flex: 1, fontSize: 12, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  sellerSub: { fontSize: 12, fontWeight: "800", color: colors.primary },

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
  breakdownRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 7 },
  breakdownLabel: { fontSize: 13, color: colors.textMuted, fontWeight: "600" },
  breakdownValue: { fontSize: 13, color: colors.textMain, fontWeight: "800" },
  cashbackBanner: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, padding: 10, backgroundColor: "#F0FDF4", borderWidth: 1, borderColor: "#BBF7D0", borderRadius: 12 },
  cashbackBannerText: { flex: 1, fontSize: 12, fontWeight: "700", color: "#15803D" },
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
  stickySub: { fontSize: 10, color: colors.textMuted, fontWeight: "600", marginTop: 1 },
  // Jun 2026 — Wallet + COD split panel
  splitBox: { padding: 14, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primary, marginTop: 2 },
  splitRow: { flexDirection: "row", alignItems: "center" },
  splitCell: { flex: 1, gap: 3 },
  splitDivider: { width: 1, height: 34, backgroundColor: colors.border, marginHorizontal: 10 },
  splitLabel: { fontSize: 9, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.9 },
  splitValueWallet: { fontSize: 20, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  splitValueCash: { fontSize: 20, fontWeight: "900", color: "#B45309", letterSpacing: -0.5 },
  splitQuickRow: { flexDirection: "row", gap: 6, marginTop: 4 },
  splitChip: { flex: 1, paddingVertical: 8, borderRadius: 999, alignItems: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, minHeight: 34 },
  splitChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  splitChipText: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  splitChipTextActive: { color: colors.primaryFg },
  splitHint: { fontSize: 10, color: colors.textMuted, marginTop: 10, textAlign: "center", fontWeight: "600" },
  stickyAmount: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  placeBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 20, paddingVertical: 14, borderRadius: 999, backgroundColor: colors.primary },
  placeBtnText: { fontSize: 14, fontWeight: "900", color: colors.primaryFg, letterSpacing: -0.2 },
});
