// Product detail page — opens when a customer taps any product card on the
// Shop tab, category page, or any shop-layout block. Big image gallery, full
// description, sticky "Add to Cart" CTA at the bottom. Out-of-stock products
// show "Notify me" instead of Add to Cart.
import { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, ActivityIndicator,
  Alert, Dimensions, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Product = {
  id: string;
  name: string;
  price: number;
  description?: string;
  image_url?: string;
  image_data_url?: string;
  images?: string[];
  stock?: number;
  is_in_stock?: boolean;
  category?: string;
  interested_count?: number;
};

const { width: screenWidth } = Dimensions.get("window");

export default function ProductDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [product, setProduct] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [qty, setQty] = useState(1);
  const [interested, setInterested] = useState(false);
  const [registeringInterest, setRegisteringInterest] = useState(false);
  const [activeImageIdx, setActiveImageIdx] = useState(0);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      // The catalog endpoint returns ALL products; we filter client-side.
      // (Avoids creating a brand-new /products/{id} route in this iteration.)
      const r = await api.get<any>("/products");
      const list: Product[] = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      const p = list.find((x) => x.id === id) || null;
      setProduct(p);
    } catch (e) { Alert.alert("Couldn't load product", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const inStock = product ? (product.is_in_stock ?? (product.stock || 0) > 0) : false;
  const images: string[] = product
    ? [product.image_data_url, product.image_url, ...(product.images || [])].filter(Boolean) as string[]
    : [];
  const heroImage = images[activeImageIdx] || images[0];

  const onAddToCart = async () => {
    if (!product || adding) return;
    setAdding(true);
    try {
      await api.post("/cart/add", { product_id: product.id, qty });
      Alert.alert("Added to cart", `${qty} × ${product.name}`, [
        { text: "Keep shopping", style: "cancel" },
        { text: "View cart", onPress: () => router.push("/cart" as any) },
      ]);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setAdding(false); }
  };

  const onBuyNow = async () => {
    if (!product || adding) return;
    setAdding(true);
    try {
      await api.post("/cart/add", { product_id: product.id, qty });
      router.push("/cart" as any);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setAdding(false); }
  };

  const onNotifyMe = async () => {
    if (!product || registeringInterest) return;
    setRegisteringInterest(true);
    try {
      await api.post(`/products/${product.id}/interest`);
      setInterested(true);
      Alert.alert("You're on the waitlist", "We'll notify you when this product is back in stock.");
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setRegisteringInterest(false); }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  if (!product) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.headerRow}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title} numberOfLines={1}>Product</Text>
          <View style={{ width: 40 }} />
        </View>
        <View style={styles.center}>
          <Feather name="alert-circle" size={28} color={colors.textMuted} />
          <Text style={styles.notFoundText}>Product not found</Text>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
            <Text style={styles.backBtnText}>Go back</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {/* Header */}
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title} numberOfLines={1}>{product.name}</Text>
        <TouchableOpacity onPress={() => router.push("/cart" as any)} style={styles.iconBtn}>
          <Feather name="shopping-cart" size={18} color={colors.textMain} />
        </TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={{ paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      >
        {/* Hero image gallery */}
        <View style={styles.heroWrap}>
          {heroImage ? (
            <Image source={{ uri: heroImage }} style={styles.heroImg} resizeMode="cover" />
          ) : (
            <View style={[styles.heroImg, { alignItems: "center", justifyContent: "center" }]}>
              <Feather name="image" size={40} color={colors.textMuted} />
            </View>
          )}
          {!inStock ? (
            <View style={styles.heroOOSBadge}>
              <Text style={styles.heroOOSText}>SOLD OUT</Text>
            </View>
          ) : null}
        </View>

        {/* Thumbnails (if multiple images) */}
        {images.length > 1 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.thumbsRow}>
            {images.map((src, i) => (
              <TouchableOpacity
                key={`thumb-${i}`}
                onPress={() => setActiveImageIdx(i)}
                style={[styles.thumb, i === activeImageIdx && styles.thumbActive]}
              >
                <Image source={{ uri: src }} style={styles.thumbImg} resizeMode="cover" />
              </TouchableOpacity>
            ))}
          </ScrollView>
        ) : null}

        {/* Info */}
        <View style={styles.infoWrap}>
          {product.category ? (
            <View style={styles.categoryPill}>
              <Feather name="tag" size={10} color={colors.primary} />
              <Text style={styles.categoryText}>{product.category}</Text>
            </View>
          ) : null}

          <Text style={styles.productName}>{product.name}</Text>

          <View style={styles.priceRow}>
            <Text style={styles.price}>{formatINR(product.price)}</Text>
            <View style={styles.ratingChip}>
              <Feather name="star" size={11} color="#F59E0B" />
              <Text style={styles.ratingChipText}>4.5</Text>
            </View>
          </View>

          {/* Stock indicator */}
          <View style={[styles.stockChip, inStock ? styles.stockOk : styles.stockOut]}>
            <Feather name={inStock ? "check-circle" : "alert-circle"} size={13} color={inStock ? "#065F46" : "#B91C1C"} />
            <Text style={[styles.stockText, { color: inStock ? "#065F46" : "#B91C1C" }]}>
              {inStock
                ? ((product.stock || 0) <= 5 ? `Only ${product.stock} left!` : "In stock · Ships in 2-4 days")
                : "Sold out · Tap 'Notify me' below"}
            </Text>
          </View>

          {/* Description */}
          {product.description ? (
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>DESCRIPTION</Text>
              <Text style={styles.description}>{product.description}</Text>
            </View>
          ) : null}

          {/* Quantity stepper */}
          {inStock ? (
            <View style={styles.section}>
              <Text style={styles.sectionLabel}>QUANTITY</Text>
              <View style={styles.qtyRow}>
                <TouchableOpacity
                  onPress={() => setQty((q) => Math.max(1, q - 1))}
                  style={[styles.qtyBtn, qty <= 1 && { opacity: 0.4 }]}
                  disabled={qty <= 1}
                  testID="qty-minus"
                >
                  <Feather name="minus" size={16} color={colors.textMain} />
                </TouchableOpacity>
                <Text style={styles.qtyText}>{qty}</Text>
                <TouchableOpacity
                  onPress={() => setQty((q) => Math.min(product.stock || 99, q + 1))}
                  style={[styles.qtyBtn, qty >= (product.stock || 99) && { opacity: 0.4 }]}
                  disabled={qty >= (product.stock || 99)}
                  testID="qty-plus"
                >
                  <Feather name="plus" size={16} color={colors.textMain} />
                </TouchableOpacity>
                <View style={{ flex: 1 }} />
                <Text style={styles.subtotalLabel}>Subtotal</Text>
                <Text style={styles.subtotal}>{formatINR(product.price * qty)}</Text>
              </View>
            </View>
          ) : null}

          {/* Trust badges */}
          <View style={styles.trustRow}>
            <View style={styles.trustBadge}>
              <Feather name="truck" size={14} color={colors.primary} />
              <Text style={styles.trustText}>Free delivery on orders over ₹999</Text>
            </View>
            <View style={styles.trustBadge}>
              <Feather name="shield" size={14} color={colors.primary} />
              <Text style={styles.trustText}>Secure wallet checkout</Text>
            </View>
            <View style={styles.trustBadge}>
              <Feather name="rotate-ccw" size={14} color={colors.primary} />
              <Text style={styles.trustText}>7-day easy returns</Text>
            </View>
          </View>
        </View>
      </ScrollView>

      {/* Sticky bottom CTA — the previously-missing Add-to-Cart! */}
      <View style={styles.stickyCta}>
        {inStock ? (
          <>
            <TouchableOpacity
              onPress={onAddToCart}
              disabled={adding}
              style={[styles.addToCartBtn, adding && { opacity: 0.6 }]}
              testID="add-to-cart"
            >
              {adding ? (
                <ActivityIndicator color={colors.primary} size="small" />
              ) : (
                <>
                  <Feather name="shopping-bag" size={18} color={colors.primary} />
                  <Text style={styles.addToCartText}>Add to Cart</Text>
                </>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              onPress={onBuyNow}
              disabled={adding}
              style={[styles.buyNowBtn, adding && { opacity: 0.6 }]}
              testID="buy-now"
            >
              <Feather name="zap" size={18} color={colors.primaryFg} />
              <Text style={styles.buyNowText}>Buy Now</Text>
            </TouchableOpacity>
          </>
        ) : (
          <TouchableOpacity
            onPress={onNotifyMe}
            disabled={interested || registeringInterest}
            style={[styles.notifyBtn, { backgroundColor: interested ? "#065F46" : colors.primary }, (interested || registeringInterest) && { opacity: 0.85 }]}
            testID="notify-me"
          >
            {registeringInterest ? (
              <ActivityIndicator color={colors.primaryFg} size="small" />
            ) : (
              <>
                <Feather name={interested ? "check" : "bell"} size={18} color={colors.primaryFg} />
                <Text style={styles.notifyText}>{interested ? "You're on the waitlist" : "Notify me when back"}</Text>
              </>
            )}
          </TouchableOpacity>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  notFoundText: { fontSize: 14, fontWeight: "700", color: colors.textMain, marginTop: 6 },
  backBtn: { marginTop: 10, paddingHorizontal: 18, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.primary },
  backBtnText: { fontSize: 13, fontWeight: "800", color: colors.primaryFg },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  title: { flex: 1, fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  // Hero
  heroWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, position: "relative" },
  heroImg: { width: "100%", height: "100%" },
  heroOOSBadge: { position: "absolute", top: 16, left: 16, backgroundColor: "#B91C1C", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  heroOOSText: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.2 },
  // Thumbs
  thumbsRow: { gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 10 },
  thumb: { width: 56, height: 56, borderRadius: 10, overflow: "hidden", borderWidth: 2, borderColor: "transparent" },
  thumbActive: { borderColor: colors.primary },
  thumbImg: { width: "100%", height: "100%" },
  // Info
  infoWrap: { padding: spacing.screen, gap: 14 },
  categoryPill: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", backgroundColor: colors.brand100, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999 },
  categoryText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  productName: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.5, lineHeight: 28 },
  priceRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  price: { fontSize: 26, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  ratingChip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, backgroundColor: "#FEF3C7" },
  ratingChipText: { fontSize: 11, fontWeight: "800", color: "#92400E" },
  stockChip: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  stockOk: { backgroundColor: "#DCFCE7" },
  stockOut: { backgroundColor: "#FEE2E2" },
  stockText: { fontSize: 12, fontWeight: "800" },
  section: { marginTop: 6 },
  sectionLabel: { fontSize: 11, fontWeight: "800", letterSpacing: 1.2, color: colors.textMuted, marginBottom: 6 },
  description: { fontSize: 14, color: colors.textMain, lineHeight: 22 },
  // Qty stepper
  qtyRow: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border },
  qtyBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  qtyText: { fontSize: 16, fontWeight: "900", color: colors.textMain, minWidth: 28, textAlign: "center" },
  subtotalLabel: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.8, marginRight: 6 },
  subtotal: { fontSize: 17, fontWeight: "900", color: colors.primary, letterSpacing: -0.3 },
  // Trust badges
  trustRow: { gap: 6, marginTop: 4 },
  trustBadge: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  trustText: { fontSize: 12, color: colors.textMain, fontWeight: "600" },
  // Sticky CTA
  stickyCta: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: spacing.screen, paddingTop: 12, paddingBottom: 20, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, flexDirection: "row", gap: 10 },
  addToCartBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderRadius: 999, borderWidth: 2, borderColor: colors.primary, backgroundColor: "#fff" },
  addToCartText: { fontSize: 14, fontWeight: "900", color: colors.primary, letterSpacing: -0.2 },
  buyNowBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderRadius: 999, backgroundColor: colors.primary },
  buyNowText: { fontSize: 14, fontWeight: "900", color: colors.primaryFg, letterSpacing: -0.2 },
  notifyBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, borderRadius: 999 },
  notifyText: { fontSize: 14, fontWeight: "900", color: colors.primaryFg, letterSpacing: -0.2 },
});
