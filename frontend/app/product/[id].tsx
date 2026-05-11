// Product Detail — Amazon/Flipkart-style rich product page.
// Sections (matches spec): breadcrumb (Category > Brand > Vendor), image
// gallery (up to 10) with camera capture for user uploads, name +
// sub-features, price + styled summaries (price/protection/warranty/
// delivery), qty + Add-to-Cart + Buy-Now + Save + Ask-Vendor,
// product details panel (Brand/OS/RAM/CPU/Storage + extras), description,
// spec tabs, What's-in-the-Box, customer reviews with rating + photos.
import { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, ActivityIndicator,
  Alert, RefreshControl, TextInput, Modal, Pressable, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing, formatINR } from "../../src/theme";

/* ─── Types ─── */
type StyledText = { text?: string; bold?: boolean; font_size?: number | null; align?: "left" | "center" | "right" };
type Product = {
  id: string; name: string; price: number; image_url?: string; image_data_url?: string;
  description?: string; stock?: number; is_in_stock?: boolean; category?: string;
  brand?: string; vendor_id?: string;
  sub_features?: string[]; images?: string[];
  price_summary?: StyledText; protection_summary?: StyledText; warranty_summary?: StyledText; delivery_summary?: StyledText;
  attrs_brand?: string; attrs_os?: string; attrs_ram?: string; attrs_cpu_model?: string; attrs_cpu_speed?: string; attrs_storage?: string;
  extra_attrs?: Record<string, string>;
  spec_tabs?: { name: string; rows: { label: string; value: string }[] }[];
  whats_in_box?: { name: string; image_data_url: string }[];
};
type Review = { id: string; user_id: string; user_name: string; rating: number; title: string; body: string; images: string[]; verified_purchase: boolean; created_at: string };

const PROTECTION_DEFAULT = "Service Protection — covered by 1-year manufacturer warranty + 2-year extended option at checkout.";
const WARRANTY_DEFAULT = "1-year manufacturer warranty against defects. Free replacements within 7 days of delivery.";
const DELIVERY_DEFAULT = "Free delivery in 2-4 business days. Same-day delivery available in select pincodes.";

export default function ProductDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const [product, setProduct] = useState<Product | null>(null);
  const [vendor, setVendor] = useState<{ id: string; name: string; referral_code?: string } | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reviewStats, setReviewStats] = useState({ average: 0, total: 0, breakdown: {} as Record<string, number> });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeImageIdx, setActiveImageIdx] = useState(0);
  const [qty, setQty] = useState(1);
  const [adding, setAdding] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeSpecTab, setActiveSpecTab] = useState(0);
  // Modals
  const [askOpen, setAskOpen] = useState(false);
  const [askText, setAskText] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const [pRes, rRes, wRes] = await Promise.all([
        api.get<any>("/products"),
        api.get<{ reviews: Review[]; stats: any }>(`/products/${id}/reviews`).catch(() => ({ data: { reviews: [], stats: { average: 0, total: 0, breakdown: {} } } as any })),
        api.get<{ items: any[] }>("/me/wishlist").catch(() => ({ data: { items: [] } })),
      ]);
      const list: Product[] = Array.isArray(pRes.data) ? pRes.data : (pRes.data?.items || []);
      const p = list.find((x) => x.id === id) || null;
      setProduct(p);
      setReviews(rRes.data?.reviews || []);
      setReviewStats(rRes.data?.stats || { average: 0, total: 0, breakdown: {} });
      setSaved(!!(wRes.data?.items || []).some((x: any) => x.id === id));
      // Try to load vendor info (admin-only endpoint; ignore if non-admin user)
      if (p?.vendor_id) {
        try {
          const v = await api.get<{ suggestions: any[] }>("/vendors/suggest", { params: { q: "" } });
          const found = (v.data?.suggestions || []).find((s: any) => s.id === p.vendor_id);
          if (found) setVendor(found);
        } catch { /* not admin; not fatal */ }
      }
    } catch (e) { /* swallow */ }
    finally { setLoading(false); setRefreshing(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <SafeAreaView style={styles.safe} edges={["top"]}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  if (!product) return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}><TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity><Text style={styles.title}>Not found</Text><View style={{ width: 40 }} /></View>
      <View style={styles.center}><Feather name="alert-circle" size={28} color={colors.textMuted} /><Text style={styles.errText}>Product not found</Text></View>
    </SafeAreaView>
  );

  const inStock = product.is_in_stock ?? (product.stock || 0) > 0;
  const gallery: string[] = [
    ...(product.images || []).filter(Boolean),
    ...(product.image_data_url ? [product.image_data_url] : []),
    ...(product.image_url ? [product.image_url] : []),
  ].slice(0, 10);
  const heroImage = gallery[activeImageIdx] || gallery[0];
  const breadcrumb = [product.category, product.brand || product.attrs_brand, vendor?.name].filter(Boolean) as string[];

  const onAddToCart = async (alsoBuy: boolean = false) => {
    if (adding) return;
    setAdding(true);
    try {
      await api.post("/cart/add", { product_id: product.id, qty });
      if (alsoBuy) router.push("/checkout" as any);
      else Alert.alert("Added to cart", `${qty} × ${product.name}`, [
        { text: "Keep shopping", style: "cancel" },
        { text: "View cart", onPress: () => router.push("/cart" as any) },
      ]);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setAdding(false); }
  };

  const onToggleSave = async () => {
    try {
      const r = await api.post<{ saved: boolean }>(`/products/${product.id}/save`);
      setSaved(!!r.data?.saved);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
  };

  const onAskVendor = async () => {
    const t = askText.trim();
    if (!t) return;
    try {
      await api.post(`/products/${product.id}/questions`, { text: t });
      Alert.alert("Question posted", "Other customers can see this Q&A. Vendor will be notified.");
      setAskText(""); setAskOpen(false);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title} numberOfLines={1}>{product.name}</Text>
        <TouchableOpacity onPress={() => router.push("/cart" as any)} style={styles.iconBtn}><Feather name="shopping-cart" size={18} color={colors.textMain} /></TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: 130 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>
        {/* Breadcrumb: Category > Brand > Vendor */}
        {breadcrumb.length ? (
          <View style={styles.breadcrumb}>
            {breadcrumb.map((b, i) => (
              <View key={`b-${i}`} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                {i > 0 ? <Feather name="chevron-right" size={11} color={colors.textMuted} /> : null}
                <Text style={styles.crumbText}>{b}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* Hero image */}
        <View style={styles.heroWrap}>
          {heroImage ? <Image source={{ uri: heroImage }} style={styles.heroImg} resizeMode="cover" /> :
            <View style={[styles.heroImg, { alignItems: "center", justifyContent: "center" }]}><Feather name="image" size={40} color={colors.textMuted} /></View>}
          {!inStock ? <View style={styles.heroOOSBadge}><Text style={styles.heroOOSText}>SOLD OUT</Text></View> : null}
          <TouchableOpacity onPress={onToggleSave} style={styles.heartBtn} testID="save-btn">
            <Feather name={saved ? "heart" : "heart"} size={18} color={saved ? "#DC2626" : colors.textMain} fill={saved ? "#DC2626" : "none" as any} />
          </TouchableOpacity>
        </View>

        {/* Thumbnail strip */}
        {gallery.length > 1 ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.thumbsRow}>
            {gallery.map((src, i) => (
              <TouchableOpacity key={`thumb-${i}`} onPress={() => setActiveImageIdx(i)} style={[styles.thumb, i === activeImageIdx && styles.thumbActive]}>
                <Image source={{ uri: src }} style={styles.thumbImg} resizeMode="cover" />
              </TouchableOpacity>
            ))}
          </ScrollView>
        ) : null}

        <View style={styles.infoWrap}>
          <Text style={styles.productName}>{product.name}</Text>

          {/* Sub-features bullets */}
          {(product.sub_features || []).length ? (
            <View style={styles.bulletList}>
              {product.sub_features!.slice(0, 8).map((f, i) => (
                <View key={`f-${i}`} style={styles.bulletRow}>
                  <View style={styles.bulletDot} />
                  <Text style={styles.bulletText}>{f}</Text>
                </View>
              ))}
            </View>
          ) : null}

          {/* Price + rating row */}
          <View style={styles.priceRow}>
            <Text style={styles.price}>{formatINR(product.price)}</Text>
            {reviewStats.total > 0 ? (
              <View style={styles.ratingChip}>
                <Feather name="star" size={11} color="#F59E0B" />
                <Text style={styles.ratingChipText}>{reviewStats.average} · {reviewStats.total}</Text>
              </View>
            ) : null}
          </View>

          {/* Styled summary blocks */}
          <StyledBlock icon="dollar-sign" label="PRICE INFO" defaultText={`MRP ${formatINR(product.price * 1.25)} · You save ${Math.round(20)}%`} block={product.price_summary} />
          <StyledBlock icon="shield" label="SERVICE PROTECTION" defaultText={PROTECTION_DEFAULT} block={product.protection_summary} />
          <StyledBlock icon="award" label="WARRANTY" defaultText={WARRANTY_DEFAULT} block={product.warranty_summary} />
          <StyledBlock icon="truck" label="ESTIMATED DELIVERY" defaultText={DELIVERY_DEFAULT} block={product.delivery_summary} />

          {/* Qty stepper */}
          {inStock ? (
            <View style={styles.qtyCard}>
              <Text style={styles.qtyLabel}>QUANTITY</Text>
              <View style={styles.qtyRow}>
                <TouchableOpacity onPress={() => setQty((q) => Math.max(1, q - 1))} style={[styles.qtyBtn, qty <= 1 && { opacity: 0.4 }]} disabled={qty <= 1}><Feather name="minus" size={16} color={colors.textMain} /></TouchableOpacity>
                <Text style={styles.qtyText}>{qty}</Text>
                <TouchableOpacity onPress={() => setQty((q) => Math.min(product.stock || 99, q + 1))} style={[styles.qtyBtn, qty >= (product.stock || 99) && { opacity: 0.4 }]} disabled={qty >= (product.stock || 99)}><Feather name="plus" size={16} color={colors.textMain} /></TouchableOpacity>
                <View style={{ flex: 1 }} />
                <Text style={styles.qtySubLabel}>Subtotal</Text>
                <Text style={styles.qtySubAmount}>{formatINR(product.price * qty)}</Text>
              </View>
            </View>
          ) : null}

          {/* Action row: Save + Ask vendor */}
          <View style={styles.actionRow}>
            <TouchableOpacity onPress={onToggleSave} style={[styles.actionBtn, saved && { backgroundColor: "#FEE2E2", borderColor: "#FCA5A5" }]} testID="action-save">
              <Feather name="bookmark" size={14} color={saved ? "#B91C1C" : colors.primary} />
              <Text style={[styles.actionText, saved && { color: "#B91C1C" }]}>{saved ? "Saved" : "Save"}</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => setAskOpen(true)} style={styles.actionBtn} testID="action-ask">
              <Feather name="message-circle" size={14} color={colors.primary} />
              <Text style={styles.actionText}>Ask vendor</Text>
            </TouchableOpacity>
          </View>

          {/* Product Details panel */}
          <Text style={styles.sectionTitle}>Product Details</Text>
          <View style={styles.detailsCard}>
            <DetailRow label="Brand" value={product.attrs_brand || product.brand} />
            <DetailRow label="Operating System" value={product.attrs_os} />
            <DetailRow label="RAM" value={product.attrs_ram} />
            <DetailRow label="CPU Model" value={product.attrs_cpu_model} />
            <DetailRow label="CPU Speed" value={product.attrs_cpu_speed} />
            <DetailRow label="Storage" value={product.attrs_storage} />
            {Object.entries(product.extra_attrs || {}).map(([k, v]) => (
              <DetailRow key={k} label={k} value={v} />
            ))}
          </View>

          {/* Description */}
          {product.description ? (
            <>
              <Text style={styles.sectionTitle}>Description</Text>
              <View style={styles.descBox}><Text style={styles.descText}>{product.description}</Text></View>
            </>
          ) : null}

          {/* Spec tabs */}
          {(product.spec_tabs || []).length ? (
            <>
              <Text style={styles.sectionTitle}>Specifications</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
                {product.spec_tabs!.map((t, i) => (
                  <TouchableOpacity key={`st-${i}`} onPress={() => setActiveSpecTab(i)} style={[styles.specTab, i === activeSpecTab && styles.specTabActive]}>
                    <Text style={[styles.specTabText, i === activeSpecTab && { color: colors.primaryFg }]}>{t.name || `Tab ${i + 1}`}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <View style={styles.specPanel}>
                {(product.spec_tabs![activeSpecTab]?.rows || []).map((r, i) => (
                  <View key={`sr-${i}`} style={styles.specRow}>
                    <Text style={styles.specLabel}>{r.label}</Text>
                    <Text style={styles.specValue}>{r.value}</Text>
                  </View>
                ))}
              </View>
            </>
          ) : null}

          {/* What's in the Box */}
          {(product.whats_in_box || []).length ? (
            <>
              <Text style={styles.sectionTitle}>What's in the Box</Text>
              <View style={styles.boxGrid}>
                {product.whats_in_box!.map((b, i) => (
                  <View key={`wib-${i}`} style={styles.boxItem}>
                    <View style={styles.boxThumb}>
                      {b.image_data_url ? <Image source={{ uri: b.image_data_url }} style={styles.boxImg} resizeMode="cover" /> : <Feather name="package" size={24} color={colors.textMuted} />}
                    </View>
                    <Text style={styles.boxName} numberOfLines={2}>{b.name}</Text>
                  </View>
                ))}
              </View>
            </>
          ) : null}

          {/* Reviews */}
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 18 }}>
            <Text style={[styles.sectionTitle, { marginTop: 0 }]}>Customer Reviews ({reviewStats.total})</Text>
            <TouchableOpacity onPress={() => setReviewOpen(true)} style={styles.writeReviewBtn}>
              <Feather name="edit-3" size={12} color={colors.primaryFg} />
              <Text style={styles.writeReviewText}>Write</Text>
            </TouchableOpacity>
          </View>
          {reviewStats.total > 0 ? (
            <View style={styles.reviewStats}>
              <Text style={styles.reviewAvg}>{reviewStats.average}</Text>
              <View style={{ flexDirection: "row", gap: 1 }}>
                {[1, 2, 3, 4, 5].map((s) => (
                  <Feather key={s} name="star" size={13} color={s <= Math.round(reviewStats.average) ? "#F59E0B" : colors.border} />
                ))}
              </View>
              <Text style={styles.reviewMeta}>· {reviewStats.total} review{reviewStats.total === 1 ? "" : "s"}</Text>
            </View>
          ) : null}
          {reviews.length === 0 ? (
            <View style={styles.emptyReviews}>
              <Feather name="message-square" size={22} color={colors.textMuted} />
              <Text style={styles.emptyReviewsText}>Be the first to review this product</Text>
            </View>
          ) : reviews.slice(0, 10).map((r) => (
            <View key={r.id} style={styles.reviewCard}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <View style={styles.reviewAvatar}><Text style={styles.reviewAvatarText}>{r.user_name.substring(0, 1).toUpperCase()}</Text></View>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.reviewName}>{r.user_name}</Text>
                    {r.verified_purchase ? <View style={styles.verifiedPill}><Text style={styles.verifiedText}>VERIFIED</Text></View> : null}
                  </View>
                  <View style={{ flexDirection: "row", gap: 1, marginTop: 2 }}>
                    {[1, 2, 3, 4, 5].map((s) => <Feather key={s} name="star" size={11} color={s <= r.rating ? "#F59E0B" : colors.border} />)}
                  </View>
                </View>
              </View>
              {r.title ? <Text style={styles.reviewTitle}>{r.title}</Text> : null}
              {r.body ? <Text style={styles.reviewBody}>{r.body}</Text> : null}
              {(r.images || []).length ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, marginTop: 6 }}>
                  {r.images!.map((src, i) => <Image key={i} source={{ uri: src }} style={styles.reviewImg} resizeMode="cover" />)}
                </ScrollView>
              ) : null}
            </View>
          ))}
        </View>
      </ScrollView>

      {/* Sticky bottom CTA */}
      <View style={styles.stickyCta}>
        {inStock ? (
          <>
            <TouchableOpacity onPress={() => onAddToCart(false)} disabled={adding} style={[styles.cartBtn, adding && { opacity: 0.5 }]} testID="add-to-cart">
              {adding ? <ActivityIndicator color={colors.primary} size="small" /> : <><Feather name="shopping-bag" size={18} color={colors.primary} /><Text style={styles.cartBtnText}>Add to Cart</Text></>}
            </TouchableOpacity>
            <TouchableOpacity onPress={() => onAddToCart(true)} disabled={adding} style={[styles.buyBtn, adding && { opacity: 0.5 }]} testID="buy-now">
              <Feather name="zap" size={18} color={colors.primaryFg} /><Text style={styles.buyBtnText}>Buy Now</Text>
            </TouchableOpacity>
          </>
        ) : (
          <View style={[styles.buyBtn, { flex: 1, backgroundColor: "#B91C1C" }]}>
            <Feather name="alert-circle" size={18} color="#fff" /><Text style={styles.buyBtnText}>Sold out</Text>
          </View>
        )}
      </View>

      {/* Ask Vendor modal */}
      <Modal visible={askOpen} transparent animationType="slide" onRequestClose={() => setAskOpen(false)}>
        <Pressable style={styles.modalOverlay} onPress={() => setAskOpen(false)}>
          <Pressable style={styles.modalSheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.handle} />
            <Text style={styles.modalTitle}>Ask about this product</Text>
            <Text style={styles.modalSub}>Your question becomes part of public Q&A. The vendor will be notified.</Text>
            <TextInput style={styles.modalInput} value={askText} onChangeText={setAskText} multiline maxLength={600} placeholder="e.g. Does it support fast charging?" placeholderTextColor={colors.textMuted} testID="ask-input" />
            <View style={{ flexDirection: "row", gap: 10 }}>
              <TouchableOpacity onPress={() => setAskOpen(false)} style={styles.modalCancel}><Text style={styles.modalCancelText}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity onPress={onAskVendor} disabled={!askText.trim()} style={[styles.modalSend, !askText.trim() && { opacity: 0.5 }]} testID="ask-send">
                <Feather name="send" size={14} color={colors.primaryFg} /><Text style={styles.modalSendText}>Post question</Text>
              </TouchableOpacity>
            </View>
          </Pressable>
        </Pressable>
      </Modal>

      {/* Write Review modal */}
      <WriteReviewModal
        visible={reviewOpen}
        onClose={() => setReviewOpen(false)}
        productId={product.id}
        onPosted={() => { setReviewOpen(false); load(); }}
      />
    </SafeAreaView>
  );
}

/* ─── Sub-components ─── */

function StyledBlock({ icon, label, defaultText, block }: { icon: any; label: string; defaultText: string; block?: StyledText }) {
  const text = (block?.text || "").trim() || defaultText;
  if (!text) return null;
  return (
    <View style={styles.summaryBlock}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <Feather name={icon} size={12} color={colors.primary} />
        <Text style={styles.summaryLabel}>{label}</Text>
      </View>
      <Text style={{
        fontSize: block?.font_size || 13,
        color: colors.textMain,
        textAlign: (block?.align as any) || "left",
        fontWeight: block?.bold ? "900" : "600",
        lineHeight: 20,
      }}>{text}</Text>
    </View>
  );
}

function DetailRow({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

function WriteReviewModal({ visible, onClose, productId, onPosted }: { visible: boolean; onClose: () => void; productId: string; onPosted: () => void }) {
  const [rating, setRating] = useState(5);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [posting, setPosting] = useState(false);
  const [picking, setPicking] = useState(false);

  useEffect(() => { if (visible) { setRating(5); setTitle(""); setBody(""); setImages([]); } }, [visible]);

  const pickFromGallery = async () => {
    if (images.length >= 3) { Alert.alert("Max 3 photos"); return; }
    setPicking(true);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) { Alert.alert("Permission needed"); return; }
      const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.7 });
      if (!r.canceled && r.assets?.[0]?.uri) {
        const m = await ImageManipulator.manipulateAsync(r.assets[0].uri, [{ resize: { width: 900 } }], { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true });
        if (m.base64) setImages((prev) => [...prev, `data:image/jpeg;base64,${m.base64}`]);
      }
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setPicking(false); }
  };

  const captureFromCamera = async () => {
    if (images.length >= 3) { Alert.alert("Max 3 photos"); return; }
    setPicking(true);
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) { Alert.alert("Camera permission needed"); return; }
      const r = await ImagePicker.launchCameraAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.7 });
      if (!r.canceled && r.assets?.[0]?.uri) {
        const m = await ImageManipulator.manipulateAsync(r.assets[0].uri, [{ resize: { width: 900 } }], { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true });
        if (m.base64) setImages((prev) => [...prev, `data:image/jpeg;base64,${m.base64}`]);
      }
    } catch (e) { Alert.alert("Camera failed", formatApiError(e)); }
    finally { setPicking(false); }
  };

  const onPost = async () => {
    setPosting(true);
    try {
      await api.post(`/products/${productId}/reviews`, { rating, title: title.trim(), body: body.trim(), images });
      onPosted();
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setPosting(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.modalOverlay} onPress={onClose}>
        <Pressable style={[styles.modalSheet, { maxHeight: "92%" }]} onPress={(e) => e.stopPropagation()}>
          <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
            <View style={styles.handle} />
            <Text style={styles.modalTitle}>Write a review</Text>
            <ScrollView contentContainerStyle={{ paddingBottom: 12 }} keyboardShouldPersistTaps="handled">
              <Text style={styles.miniLabel}>Rating</Text>
              <View style={{ flexDirection: "row", gap: 6, marginBottom: 12 }}>
                {[1, 2, 3, 4, 5].map((s) => (
                  <TouchableOpacity key={s} onPress={() => setRating(s)} testID={`rate-${s}`}>
                    <Feather name="star" size={32} color={s <= rating ? "#F59E0B" : colors.border} />
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.miniLabel}>Title (optional)</Text>
              <TextInput style={styles.modalInput} value={title} onChangeText={setTitle} placeholder="Great product!" placeholderTextColor={colors.textMuted} maxLength={120} />
              <Text style={styles.miniLabel}>Your review</Text>
              <TextInput style={[styles.modalInput, { minHeight: 90, textAlignVertical: "top" }]} value={body} onChangeText={setBody} multiline placeholder="What did you like? What could be better?" placeholderTextColor={colors.textMuted} maxLength={2000} />
              <Text style={styles.miniLabel}>Photos (up to 3) — camera or gallery</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                {images.map((src, i) => (
                  <View key={i} style={styles.reviewPhotoWrap}>
                    <Image source={{ uri: src }} style={styles.reviewPhoto} resizeMode="cover" />
                    <TouchableOpacity onPress={() => setImages((prev) => prev.filter((_, j) => j !== i))} style={styles.reviewPhotoRemove}>
                      <Feather name="x" size={11} color="#fff" />
                    </TouchableOpacity>
                  </View>
                ))}
                {images.length < 3 ? (
                  <>
                    <TouchableOpacity onPress={pickFromGallery} disabled={picking} style={[styles.reviewPhotoAdd, picking && { opacity: 0.5 }]}>
                      {picking ? <ActivityIndicator size="small" color={colors.primary} /> : <><Feather name="image" size={20} color={colors.primary} /><Text style={styles.reviewPhotoAddText}>Gallery</Text></>}
                    </TouchableOpacity>
                    <TouchableOpacity onPress={captureFromCamera} disabled={picking} style={[styles.reviewPhotoAdd, { backgroundColor: colors.brand100 }, picking && { opacity: 0.5 }]} testID="review-camera">
                      <Feather name="camera" size={20} color={colors.primary} /><Text style={styles.reviewPhotoAddText}>Camera</Text>
                    </TouchableOpacity>
                  </>
                ) : null}
              </View>
              <View style={{ flexDirection: "row", gap: 10, marginTop: 4 }}>
                <TouchableOpacity onPress={onClose} style={styles.modalCancel}><Text style={styles.modalCancelText}>Cancel</Text></TouchableOpacity>
                <TouchableOpacity onPress={onPost} disabled={posting || !rating} style={[styles.modalSend, posting && { opacity: 0.5 }]} testID="review-post">
                  {posting ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <><Feather name="check" size={14} color={colors.primaryFg} /><Text style={styles.modalSendText}>Post review</Text></>}
                </TouchableOpacity>
              </View>
            </ScrollView>
          </KeyboardAvoidingView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/* ─── Styles ─── */
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  errText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  title: { flex: 1, fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  breadcrumb: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 4, paddingHorizontal: spacing.screen, paddingTop: 10, paddingBottom: 4 },
  crumbText: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  heroWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, position: "relative" },
  heroImg: { width: "100%", height: "100%" },
  heroOOSBadge: { position: "absolute", top: 16, left: 16, backgroundColor: "#B91C1C", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  heroOOSText: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.2 },
  heartBtn: { position: "absolute", top: 14, right: 14, width: 38, height: 38, borderRadius: 19, backgroundColor: "rgba(255,255,255,0.95)", alignItems: "center", justifyContent: "center" },
  thumbsRow: { gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 10 },
  thumb: { width: 52, height: 52, borderRadius: 8, overflow: "hidden", borderWidth: 2, borderColor: "transparent" },
  thumbActive: { borderColor: colors.primary },
  thumbImg: { width: "100%", height: "100%" },
  infoWrap: { padding: spacing.screen, gap: 10 },
  productName: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.5, lineHeight: 28 },
  bulletList: { marginTop: 2, gap: 4 },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  bulletDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.primary, marginTop: 7 },
  bulletText: { fontSize: 13, color: colors.textMain, flex: 1, lineHeight: 19 },
  priceRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  price: { fontSize: 26, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  ratingChip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, backgroundColor: "#FEF3C7" },
  ratingChipText: { fontSize: 11, fontWeight: "800", color: "#92400E" },
  summaryBlock: { backgroundColor: colors.surface, padding: 10, borderRadius: 10, borderWidth: 1, borderColor: colors.border },
  summaryLabel: { fontSize: 9, fontWeight: "900", letterSpacing: 1.2, color: colors.primary },
  qtyCard: { marginTop: 8, padding: 12, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border },
  qtyLabel: { fontSize: 10, fontWeight: "800", letterSpacing: 1, color: colors.textMuted, marginBottom: 8 },
  qtyRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  qtyBtn: { width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  qtyText: { fontSize: 16, fontWeight: "900", color: colors.textMain, minWidth: 26, textAlign: "center" },
  qtySubLabel: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.6, marginRight: 4 },
  qtySubAmount: { fontSize: 16, fontWeight: "900", color: colors.primary },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 6 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  actionText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  sectionTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4, marginTop: 14, marginBottom: 8 },
  detailsCard: { backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, paddingVertical: 4 },
  detailRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  detailLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "700", flex: 1 },
  detailValue: { fontSize: 13, color: colors.textMain, fontWeight: "700", textAlign: "right", flex: 1 },
  descBox: { backgroundColor: colors.surface, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  descText: { fontSize: 13, color: colors.textMain, lineHeight: 21 },
  specTab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  specTabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  specTabText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  specPanel: { backgroundColor: colors.surface, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginTop: 8 },
  specRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
  specLabel: { fontSize: 12, color: colors.textMuted, flex: 1 },
  specValue: { fontSize: 12, color: colors.textMain, fontWeight: "700", flex: 1, textAlign: "right" },
  boxGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  boxItem: { width: "31%", alignItems: "center", gap: 4 },
  boxThumb: { width: "100%", aspectRatio: 1, borderRadius: 10, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  boxImg: { width: "100%", height: "100%" },
  boxName: { fontSize: 10, color: colors.textMain, fontWeight: "700", textAlign: "center" },
  // Reviews
  writeReviewBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.primary },
  writeReviewText: { fontSize: 11, fontWeight: "800", color: colors.primaryFg },
  reviewStats: { flexDirection: "row", alignItems: "center", gap: 6, padding: 10, borderRadius: 10, backgroundColor: colors.brand100, marginBottom: 8 },
  reviewAvg: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.3 },
  reviewMeta: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  emptyReviews: { alignItems: "center", padding: 20, gap: 6 },
  emptyReviewsText: { fontSize: 12, color: colors.textMuted },
  reviewCard: { backgroundColor: colors.surface, padding: 12, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  reviewAvatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  reviewAvatarText: { fontSize: 12, fontWeight: "900", color: colors.primary },
  reviewName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  verifiedPill: { backgroundColor: "#DCFCE7", paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4 },
  verifiedText: { fontSize: 8, fontWeight: "900", color: "#065F46", letterSpacing: 0.6 },
  reviewTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  reviewBody: { fontSize: 12, color: colors.textMain, lineHeight: 18, marginTop: 2 },
  reviewImg: { width: 70, height: 70, borderRadius: 8 },
  // Sticky CTA
  stickyCta: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: spacing.screen, paddingTop: 10, paddingBottom: 18, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, flexDirection: "row", gap: 10 },
  cartBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 13, borderRadius: 999, borderWidth: 2, borderColor: colors.primary, backgroundColor: "#fff" },
  cartBtnText: { fontSize: 13, fontWeight: "900", color: colors.primary },
  buyBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 13, borderRadius: 999, backgroundColor: colors.primary },
  buyBtnText: { fontSize: 13, fontWeight: "900", color: colors.primaryFg },
  // Modal
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, maxHeight: "75%" },
  handle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 12 },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3, marginBottom: 4 },
  modalSub: { fontSize: 12, color: colors.textMuted, marginBottom: 14 },
  modalInput: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain, marginBottom: 10 },
  modalCancel: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 13, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  modalCancelText: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  modalSend: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 13, borderRadius: 999, backgroundColor: colors.primary },
  modalSendText: { fontSize: 13, fontWeight: "800", color: colors.primaryFg },
  miniLabel: { fontSize: 10, fontWeight: "800", letterSpacing: 1.2, color: colors.textMuted, marginBottom: 4, marginTop: 4 },
  reviewPhotoWrap: { position: "relative" },
  reviewPhoto: { width: 70, height: 70, borderRadius: 10 },
  reviewPhotoRemove: { position: "absolute", top: -4, right: -4, width: 18, height: 18, borderRadius: 9, backgroundColor: "#B91C1C", alignItems: "center", justifyContent: "center" },
  reviewPhotoAdd: { width: 70, height: 70, borderRadius: 10, borderWidth: 1.5, borderColor: colors.border, borderStyle: "dashed", alignItems: "center", justifyContent: "center", gap: 2 },
  reviewPhotoAddText: { fontSize: 9, fontWeight: "700", color: colors.primary },
});
