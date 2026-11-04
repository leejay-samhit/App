// Product Detail — Amazon/Flipkart-style rich product page.
// Sections (matches spec): breadcrumb (Category > Brand > Vendor), image
// gallery (up to 10) with camera capture for user uploads, name +
// sub-features, price + styled summaries (price/protection/warranty/
// delivery), qty + Add-to-Cart + Buy-Now + Save + Ask-Vendor,
// product details panel (Brand/OS/RAM/CPU/Storage + extras), description,
// spec tabs, What's-in-the-Box, customer reviews with rating + photos.
import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, ActivityIndicator,
  Alert, RefreshControl, TextInput, Modal, Pressable, KeyboardAvoidingView, Platform,
  NativeSyntheticEvent, NativeScrollEvent,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError, resolveImageUrl } from "../../src/api";
import { ProductImage } from "../../src/product-image";
import { sanitizeProduct } from "../../src/product-shape";
import { notify } from "../../src/notify";
import { handleChatGateError } from "../../src/sim-verification";
import { useAuth } from "../../src/auth";
import { useContentWidth } from "../../src/content-width";
import { getProductPreview } from "../../src/product-preview";
import { colors, radii, spacing, formatINR, withAlpha } from "../../src/theme";
import { useShopMoneyConfig, effectiveCashbackPct, cashbackAmount } from "../../src/cashback";
import { ProductRail, type Rail } from "../../src/product-rail";
import { useRechargePay, RazorpayWebViewModal, accountIsValid } from "../../src/recharge-pay";

/* ─── Types ─── */
type StyledText = { text?: string; bold?: boolean; font_size?: number | null; align?: "left" | "center" | "right" };
/** One size / RAM-ROM option as served by GET /api/products/{id}. */
type VariantOpt = { id: string; label: string; price: number; stock: number; in_stock: boolean };

type Product = {
  id: string; name: string; price: number; image_url?: string; image_data_url?: string;
  description?: string; stock?: number; is_in_stock?: boolean; category?: string;
  brand?: string; vendor_id?: string;
  sub_features?: string[]; images?: string[];
  // Jun 2026 — variants
  variants?: VariantOpt[];
  has_variants?: boolean;
  variant_chart?: string;
  variant_guide?: { label: string; unit: string; columns: string[]; guide: string[][] } | null;
  price_summary?: StyledText; protection_summary?: StyledText; warranty_summary?: StyledText; delivery_summary?: StyledText;
  attrs_brand?: string; attrs_os?: string; attrs_ram?: string; attrs_cpu_model?: string; attrs_cpu_speed?: string; attrs_storage?: string;
  extra_attrs?: Record<string, string>;
  spec_tabs?: { name: string; rows: { label: string; value: string }[] }[];
  whats_in_box?: { name: string; image_data_url: string }[];
  // Jun 2026 — a Recharge plan pays online straight from this page: no cart,
  // no address, no delivery.
  subcategory?: string; sub_category?: string;
  recharge_kind?: "mobile" | "dth" | string;
  recharge_network?: string; recharge_state?: string;
  highlights?: { data?: string; validity?: string; calls?: string };
};
type Review = { id: string; user_id: string; user_name: string; rating: number; title: string; body: string; images: string[]; verified_purchase: boolean; created_at: string; helpful_count?: number; voted_helpful?: boolean };

// Note: previously this file had default-text fallbacks for the styled
// summary sections (PRICE INFO / SERVICE PROTECTION / WARRANTY / DELIVERY).
// These were removed per product requirement: sections must only appear in
// the customer-facing product view if the admin/vendor explicitly filled
// them in. Empty sections are now hidden entirely.

export default function ProductDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  // Jun 2026 — when the shopper arrives from the Recharge screen the number
  // and circle he already typed travel with him, so "Pay online" here needs
  // no re-typing (and never asks for an address).
  const params = useLocalSearchParams<{
    rchKind?: string; rchAccount?: string; rchState?: string; rchNetwork?: string;
  }>();
  const { user } = useAuth();
  // ── Jun 2026 — INSTANT OPEN ────────────────────────────────────────────
  // The card the customer tapped already knows the name, price and cover
  // image, and stashed them in the preview cache. We seed state with that
  // so this screen paints real content on its first frame; the full doc
  // (variants, description, specs, reviews) replaces it when it lands.
  const previewRef = useRef(getProductPreview(id));
  const preview = previewRef.current;
  const [product, setProduct] = useState<Product | null>(
    preview
      ? {
          id: preview.id, name: preview.name, price: preview.price,
          image_url: preview.image, stock: preview.stock,
          is_in_stock: preview.is_in_stock, has_variants: preview.has_variants,
        }
      : null,
  );
  const [vendor, setVendor] = useState<{ id: string; name: string; referral_code?: string } | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  // Oct-2026 — exactly TWO suggestion rails: same-subcategory siblings and a
  // "picked for you" rail built from this shopper's own search / cart /
  // purchase history. Never admin-curated.
  const [rails, setRails] = useState<Rail[]>([]);
  // Oct-2026 BUGFIX — this used to be called AFTER the "loading" and
  // "not found" early returns, so the hook count changed between the
  // loading render and the loaded render and React threw "Rendered more
  // hooks than during the previous render", blanking the whole screen.
  // Hooks must run unconditionally, so it lives up here with the rest.
  const moneyCfg = useShopMoneyConfig();
  const [reviewStats, setReviewStats] = useState({ average: 0, total: 0, breakdown: {} as Record<string, number> });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeImageIdx, setActiveImageIdx] = useState(0);
  const heroScrollRef = useRef<ScrollView>(null);
  const insets = useSafeAreaInsets();
  // Width of the column this screen paints into (capped on tablets).
  const windowWidth = useContentWidth();
  // The hero is an inset card, so a gallery "page" is the CARD width.
  const heroW = windowWidth - spacing.screen * 2;
  const [qty, setQty] = useState(1);
  // Jun 2026 — variants
  const [variantId, setVariantId] = useState<string | null>(null);
  const [sizeError, setSizeError] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeSpecTab, setActiveSpecTab] = useState(0);
  // Modals
  const [askOpen, setAskOpen] = useState(false);
  const [askText, setAskText] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  // ── Recharge plan: pay online, no cart / address (Jun 2026) ──────────
  const isRecharge = !!(
    product?.recharge_kind || /^recharge$/i.test(String(product?.category || ""))
    || params.rchKind
  );
  const rechargeKind: "mobile" | "dth" =
    (product?.recharge_kind as any) || (params.rchKind as any) || "mobile";
  const [rechargeOpen, setRechargeOpen] = useState(false);
  const [rechargeAccount, setRechargeAccount] = useState(String(params.rchAccount || ""));
  const [payMode, setPayMode] = useState<"online" | "wallet" | "split">("online");
  // Read the balance fresh when the sheet opens — the cached auth user can be
  // stale, and offering "pay from wallet" against a stale number is worse
  // than not offering it at all.
  const [walletBalance, setWalletBalance] = useState(
    Math.round(Number((user as any)?.wallet_balance || 0) * 100) / 100,
  );
  React.useEffect(() => {
    if (!rechargeOpen) return;
    api.get<{ wallet_balance?: number; wallet_frozen?: boolean }>("/auth/me")
      .then(({ data }) => {
        setWalletBalance(
          data?.wallet_frozen ? 0 : Math.round(Number(data?.wallet_balance || 0) * 100) / 100,
        );
      })
      .catch(() => {});
  }, [rechargeOpen]);
  const walletCovers = !!product && walletBalance + 0.009 >= Number(product?.price || 0);
  const rechargeReady = accountIsValid(rechargeKind, rechargeAccount);
  const { pay: payRecharge, payFromWallet, paying: rechargePaying, rzpHtml, handleMessage, cancel: cancelRzp } =
    useRechargePay(() => setRechargeOpen(false));

  const load = useCallback(async () => {
    if (!id) return;
    try {
      // Fetch the single product directly — the new public /products/{id}
      // endpoint returns the FULL doc (incl. extended fields with safe
      // defaults for legacy products). Reviews + wishlist are best-effort.
      const [pRes, rRes, wRes] = await Promise.all([
        api.get<any>(`/products/${id}`),
        api.get<{ reviews: Review[]; stats: any }>(`/products/${id}/reviews`).catch(() => ({ data: { reviews: [], stats: { average: 0, total: 0, breakdown: {} } } as any })),
        api.get<{ items: any[] }>("/me/wishlist").catch(() => ({ data: { items: [] } })),
      ]);
      // Jun 2026 — Coerce the document into the shapes this screen was
      // written for BEFORE it hits state. Imported catalogues (Shopify /
      // DeoDap JSON) ship objects where strings are expected, which threw
      // mid-render and closed the Android release build.
      const p: Product | null = (pRes.data && pRes.data.id)
        ? (sanitizeProduct(pRes.data) as Product)
        : null;
      setProduct(p);
      setReviews(rRes.data?.reviews || []);
      // Best-effort — a rail failure must never blank the product page.
      api.get<{ rails: Rail[] }>(`/products/${id}/rails`)
        .then((rr) => setRails(rr.data?.rails || []))
        .catch(() => setRails([]));
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

  // Only block the whole screen when we have NOTHING to show. With a preview
  // in hand we render straight away and let the details hydrate in place.
  if (loading && !product) return <SafeAreaView style={styles.safe} edges={["top"]}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  if (!product) return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}><TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity><Text style={styles.title}>Not found</Text><View style={{ width: 40 }} /></View>
      <View style={styles.center}><Feather name="alert-circle" size={28} color={colors.textMuted} /><Text style={styles.errText}>Product not found</Text></View>
    </SafeAreaView>
  );

  // True while the full document is still in flight but we're already
  // showing the preview (name / price / cover image).
  const hydrating = loading;

  // ── Jun 2026 — Variants (size / RAM-ROM) ───────────────────────────────
  // Products with options are unbuyable until the customer picks one, and
  // the price / stock / subtotal all follow the selection.
  const variants: VariantOpt[] = Array.isArray(product.variants) ? product.variants : [];
  const hasVariants = variants.length > 0;
  const selected = hasVariants ? (variants.find((v) => v.id === variantId) || null) : null;
  const unitPrice = selected ? selected.price : product.price;
  // Purchase cashback shown before buying (paid after delivery).
  const cashbackPct = effectiveCashbackPct(product, moneyCfg);
  const cashbackValue = cashbackAmount(unitPrice, cashbackPct, moneyCfg.max_cashback_pct);
  const maxQty = selected ? selected.stock : (product.stock || 99);
  const inStock = hasVariants
    ? variants.some((v) => v.in_stock)
    : (product.is_in_stock ?? (product.stock || 0) > 0);
  // Jun 2026 fix — the COVER image (`image_url`) used to be pushed to the END
  // of the gallery, so slide 1 was a random gallery photo instead of the cover
  // the vendor chose.  Cover now leads; duplicates are de-duped; relative
  // `/api/products/.../image` paths are resolved against the backend base so
  // lazy-loaded thumbnails actually render.
  //
  // Jun 2026 (crash fix) — a Shopify-CSV→JSON import stores `images` as
  // OBJECTS (`{"src": …, "position": 2}`).  Feeding one of those to
  // `resolveImageUrl` threw `startsWith is not a function` while the hero
  // card was rendering, which closed the Android release build the moment
  // a shopper tapped an imported product.  Every entry is now flattened to
  // a URL string first, and any entry that can't be is dropped.
  const pickUrl = (entry: any): string => {
    if (typeof entry === "string") return entry.trim();
    if (entry && typeof entry === "object") {
      for (const k of ["src", "url", "image_url", "image", "href", "data_url"]) {
        if (typeof entry[k] === "string" && entry[k].trim()) return entry[k].trim();
      }
    }
    return "";
  };
  const rawGallery: any[] = Array.isArray(product.images) ? product.images : [];
  const gallery: string[] = Array.from(new Set([
    pickUrl(product.image_url),
    pickUrl((product as any).image_data_url),
    ...rawGallery.map(pickUrl),
  ].filter(Boolean)))
    .map((u) => resolveImageUrl(u))
    .filter(Boolean)
    .slice(0, 15);
  const breadcrumb = [product.category, product.brand || product.attrs_brand, vendor?.name].filter(Boolean) as string[];

  const onAddToCart = async (alsoBuy: boolean = false) => {
    if (adding) return;
    if (hasVariants && !selected) {
      // Nudge instead of failing: highlight the picker and scroll to it.
      setSizeError(true);
      Alert.alert("Choose a size", "Please select a size before adding this item.");
      return;
    }
    setAdding(true);
    try {
      await api.post("/cart/add", {
        product_id: product.id,
        qty,
        ...(selected ? { variant_id: selected.id } : {}),
      });
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
      const resp = await api.post<{ thread_id?: string }>(`/products/${product.id}/questions`, { text: t });
      const threadId = resp.data?.thread_id;
      setAskText(""); setAskOpen(false);
      if (threadId) {
        // Route straight into the chat so the customer can continue
        // the conversation and see the vendor's reply (June 2026 fix
        // — previously the message vanished into public Q&A only).
        router.push(`/chat/${threadId}` as any);
      } else {
        Alert.alert(
          "Question posted",
          "The vendor has been notified. Their reply will appear in your Chat inbox.",
        );
      }
    } catch (e) {
      if (handleChatGateError(e, (p) => router.push(p as any))) return;
      notify("Failed", formatApiError(e));
    }
  };

  const onToggleHelpful = async (rev: Review) => {
    if (!product) return;
    if (rev.user_id === user?.id) {
      Alert.alert("Not allowed", "You can't mark your own review as helpful.");
      return;
    }
    // Optimistic toggle
    const prev = [...reviews];
    setReviews((rs) => rs.map((r) => r.id === rev.id ? {
      ...r,
      voted_helpful: !r.voted_helpful,
      helpful_count: (r.helpful_count || 0) + (r.voted_helpful ? -1 : 1),
    } : r));
    try {
      const res = await api.post<{ voted_helpful: boolean; helpful_count: number }>(`/products/${product.id}/reviews/${rev.id}/helpful`);
      setReviews((rs) => rs.map((r) => r.id === rev.id ? {
        ...r,
        voted_helpful: !!res.data?.voted_helpful,
        helpful_count: res.data?.helpful_count ?? r.helpful_count,
      } : r));
    } catch (e) {
      setReviews(prev); // rollback
      Alert.alert("Couldn't update vote", formatApiError(e));
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title} numberOfLines={1}>{product.name}</Text>
        <TouchableOpacity onPress={() => router.push("/cart" as any)} style={styles.iconBtn}><Feather name="shopping-cart" size={18} color={colors.textMain} /></TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ paddingBottom: 150 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>
        {/* UPDATE 1 (June 2026) — Owner-facing notice: if a vendor lands on
            their own product page (via a direct link or a notification), let
            them know they can edit it via the Vendor panel — they can't buy
            their own inventory. */}
        {product.vendor_id && user?.id && product.vendor_id === user.id ? (
          <TouchableOpacity onPress={() => router.push("/vendor/dashboard" as any)} style={styles.ownerBanner} activeOpacity={0.85}>
            <Feather name="user-check" size={16} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.ownerBannerTitle}>This is your product</Text>
              <Text style={styles.ownerBannerSub}>Tap to edit in your Vendor dashboard.</Text>
            </View>
            <Feather name="chevron-right" size={18} color={colors.primary} />
          </TouchableOpacity>
        ) : null}
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

        {/* ── HERO CARD (Sep 2026 redesign) ─────────────────────────────
            The gallery used to be a full-bleed square with resizeMode
            "cover", which sliced the sides off phone photos (the owner's
            screenshot showed two handsets cut in half). It is now an inset
            white card the same width as every other box on the page, and
            each slide is CONTAINED inside it with breathing room, so no
            product is ever cropped. Pages are card-width, not screen-width,
            so paging lands dead centre. */}
        <View style={styles.heroCard}>
          <View style={styles.heroCanvas}>
            {gallery.length ? (
              <ScrollView
                ref={heroScrollRef}
                horizontal
                pagingEnabled
                showsHorizontalScrollIndicator={false}
                onMomentumScrollEnd={(e: NativeSyntheticEvent<NativeScrollEvent>) => {
                  const w = e.nativeEvent.layoutMeasurement.width || heroW;
                  const idx = Math.round(e.nativeEvent.contentOffset.x / w);
                  const clamped = Math.max(0, Math.min(idx, gallery.length - 1));
                  if (clamped !== activeImageIdx) setActiveImageIdx(clamped);
                }}
                scrollEventThrottle={16}
                style={StyleSheet.absoluteFill}
              >
                {gallery.map((src, i) => (
                  <View key={`hero-${i}`} style={{ width: heroW, height: "100%", padding: 14 }}>
                    <ProductImage
                      uri={src}
                      name={product.name}
                      style={{ width: "100%", height: "100%" }}
                      containerStyle={{ width: "100%", height: "100%" }}
                      resizeMode="contain"
                      testID={`hero-img-${i}`}
                    />
                  </View>
                ))}
              </ScrollView>
            ) : (
              <View style={[styles.heroImg, { alignItems: "center", justifyContent: "center" }]}>
                <Feather name="image" size={40} color={colors.textMuted} />
              </View>
            )}
            {!inStock ? <View style={styles.heroOOSBadge}><Text style={styles.heroOOSText}>SOLD OUT</Text></View> : null}
            <TouchableOpacity onPress={onToggleSave} style={styles.heartBtn} testID="save-btn">
              <Feather name="heart" size={18} color={saved ? "#DC2626" : colors.textMain} />
            </TouchableOpacity>
            {/* Page indicator dots */}
            {gallery.length > 1 ? (
              <View style={styles.heroDots}>
                {gallery.map((_, i) => (
                  <View key={`dot-${i}`} style={[styles.heroDot, i === activeImageIdx && styles.heroDotActive]} />
                ))}
              </View>
            ) : null}
            {/* Page counter chip */}
            {gallery.length > 1 ? (
              <View style={styles.heroCounter}>
                <Text style={styles.heroCounterText}>{activeImageIdx + 1}/{gallery.length}</Text>
              </View>
            ) : null}
          </View>

          {/* Thumbnail strip — lives INSIDE the hero card so it shares the
              card's left edge instead of floating on the page background. */}
          {gallery.length > 1 ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.thumbsRow}>
              {gallery.map((src, i) => (
                <TouchableOpacity
                  key={`thumb-${i}`}
                  onPress={() => {
                    setActiveImageIdx(i);
                    heroScrollRef.current?.scrollTo({ x: i * heroW, animated: true });
                  }}
                  style={[styles.thumb, i === activeImageIdx && styles.thumbActive]}
                >
                  <ProductImage uri={src} compact style={styles.thumbImg} containerStyle={styles.thumbImg} resizeMode="cover" />
                </TouchableOpacity>
              ))}
            </ScrollView>
          ) : null}
        </View>

        <View style={styles.infoWrap}>
          {/* ── TITLE + PRICE CARD ─────────────────────────────────────
              Name, highlights, price and rating now live in one card so
              they share the page's left edge and read as a single block
              instead of floating text. */}
          <View style={styles.card}>
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

            {/* Price + rating row.
                Jun 2026 — headline price follows the chosen size; before a
                size is picked we show "from ₹X" (the cheapest option) so
                the customer is never surprised at checkout. The "from"
                prefix is a small muted line ABOVE the amount, so the
                number itself always starts on the same baseline. */}
            <View style={styles.priceRow}>
              <View style={{ flexShrink: 1 }}>
                {hasVariants && !selected ? <Text style={styles.priceFrom}>STARTING FROM</Text> : null}
                <Text style={styles.price}>
                  {hasVariants && !selected ? formatINR(product.price) : formatINR(unitPrice)}
                </Text>
              </View>
              {reviewStats.total > 0 ? (
                <View style={styles.ratingChip}>
                  <Feather name="star" size={11} color="#F59E0B" />
                  <Text style={styles.ratingChipText}>{reviewStats.average} · {reviewStats.total}</Text>
                </View>
              ) : null}
            </View>

            {/* ── Purchase cashback (Jun-2026) ────────────────────────────
                Shown directly under the price so the customer knows the
                benefit BEFORE buying. The exact amount is recalculated and
                paid by the server after a successful delivery. */}
            {cashbackPct > 0 ? (
              <View style={styles.cashbackRow} testID="product-cashback">
                <View style={styles.cashbackIcon}>
                  <Feather name="gift" size={12} color="#15803D" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cashbackTitle}>
                    Cashback {cashbackPct}% · {formatINR(cashbackValue)}
                  </Text>
                  <Text style={styles.cashbackSub}>
                    Credited to your Slangcart wallet after successful delivery
                  </Text>
                </View>
              </View>
            ) : null}
          </View>

          {/* Styled summary blocks — only show those the admin/vendor filled in */}
          <StyledBlock icon="tag" label="PRICE INFO" block={product.price_summary} />
          <StyledBlock icon="shield" label="SERVICE PROTECTION" block={product.protection_summary} />
          <StyledBlock icon="award" label="WARRANTY" block={product.warranty_summary} />
          <StyledBlock icon="truck" label="ESTIMATED DELIVERY" block={product.delivery_summary} />

          {/* ── Size / option picker (Jun 2026) ────────────────────────
              Out-of-stock options are struck through and unselectable so a
              customer can never order a size the vendor doesn't have. The
              "Size guide" sheet shows real measurements (chest / length in
              inches, foot length in cm) — the #1 reason shoppers abandon
              fashion carts is fit uncertainty. */}
          {/* While the full doc hydrates, a product we KNOW has options shows
              a placeholder card instead of popping in later — no layout jump. */}
          {hydrating && product.has_variants && !hasVariants ? (
            <View style={styles.sizeCard}>
              <View style={styles.sizeHeadRow}>
                <Text style={styles.qtyLabel}>SELECT SIZE</Text>
              </View>
              <View style={styles.sizeWrap}>
                {[0, 1, 2, 3].map((i) => (
                  <View key={`sk-${i}`} style={[styles.sizeChip, { backgroundColor: colors.surfaceMuted, borderColor: colors.border, width: 54 }]} />
                ))}
              </View>
              <Text style={styles.sizeMeta}>Loading options…</Text>
            </View>
          ) : null}

          {hasVariants ? (
            <View style={[styles.sizeCard, sizeError && !selected && { borderColor: "#DC2626" }]}>
              <View style={styles.sizeHeadRow}>
                <Text style={styles.qtyLabel}>
                  {product.variant_chart === "ram_rom" ? "RAM / STORAGE" : "SELECT SIZE"}
                </Text>
                {product.variant_guide?.guide?.length ? (
                  <TouchableOpacity onPress={() => setGuideOpen(true)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} testID="size-guide-open">
                    <Text style={styles.sizeGuideLink}>Size guide</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
              <View style={styles.sizeWrap}>
                {variants.map((v) => {
                  const isSel = selected?.id === v.id;
                  return (
                    <TouchableOpacity
                      key={v.id}
                      disabled={!v.in_stock}
                      onPress={() => { setVariantId(v.id); setQty(1); setSizeError(false); }}
                      style={[
                        styles.sizeChip,
                        isSel && styles.sizeChipSel,
                        !v.in_stock && styles.sizeChipOOS,
                      ]}
                      testID={`size-${v.id}`}
                    >
                      <Text style={[
                        styles.sizeChipText,
                        isSel && { color: colors.primary },
                        !v.in_stock && styles.sizeChipTextOOS,
                      ]}>{v.label}</Text>
                      {/* Price hint per option — the shopper can compare
                          without tapping through every chip. */}
                      {v.in_stock ? (
                        <Text style={[styles.sizeChipPrice, isSel && { color: colors.primary }]}>{formatINR(v.price)}</Text>
                      ) : (
                        <Text style={styles.sizeChipPriceOOS}>Sold out</Text>
                      )}
                    </TouchableOpacity>
                  );
                })}
              </View>
              {selected ? (
                <Text style={styles.sizeMeta}>
                  {formatINR(selected.price)}
                  {selected.stock <= 5 ? `  ·  only ${selected.stock} left` : "  ·  in stock"}
                </Text>
              ) : (
                <Text style={[styles.sizeMeta, sizeError && { color: "#DC2626", fontWeight: "800" }]}>
                  {sizeError ? "Pick a size to continue" : "Pick a size to see its price and stock"}
                </Text>
              )}
            </View>
          ) : null}

          {/* Qty stepper — a recharge plan is bought once, never by the
              dozen, so the stepper is hidden for those. */}
          {isRecharge && (product.highlights?.data || product.highlights?.validity || product.highlights?.calls) ? (
            <View style={styles.rchTagRow} testID="recharge-highlights">
              {([
                ["wifi", product.highlights?.data],
                ["calendar", product.highlights?.validity],
                ["phone-call", product.highlights?.calls],
              ] as [any, string | undefined][]).filter(([, v]) => !!v).map(([icon, v]) => (
                <View key={String(v)} style={styles.rchTag}>
                  <Feather name={icon} size={12} color={colors.primary} />
                  <Text style={styles.rchTagText}>{v}</Text>
                </View>
              ))}
            </View>
          ) : null}
          {inStock && !isRecharge ? (
            <View style={styles.qtyCard}>
              <Text style={styles.qtyLabel}>QUANTITY</Text>
              <View style={styles.qtyRow}>
                <TouchableOpacity onPress={() => setQty((q) => Math.max(1, q - 1))} style={[styles.qtyBtn, qty <= 1 && { opacity: 0.4 }]} disabled={qty <= 1}><Feather name="minus" size={16} color={colors.textMain} /></TouchableOpacity>
                <Text style={styles.qtyText}>{qty}</Text>
                <TouchableOpacity onPress={() => setQty((q) => Math.min(maxQty || 99, q + 1))} style={[styles.qtyBtn, qty >= (maxQty || 99) && { opacity: 0.4 }]} disabled={qty >= (maxQty || 99)}><Feather name="plus" size={16} color={colors.textMain} /></TouchableOpacity>
                <View style={{ flex: 1 }} />
                <Text style={styles.qtySubLabel}>Subtotal</Text>
                <Text style={styles.qtySubAmount}>{formatINR(unitPrice * qty)}</Text>
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

          {/* Product Details panel — only render if there's data */}
          {(() => {
            const detailRows: [string, string | undefined][] = [
              ["Brand", product.attrs_brand || product.brand],
              ["Operating System", product.attrs_os],
              ["RAM", product.attrs_ram],
              ["CPU Model", product.attrs_cpu_model],
              ["CPU Speed", product.attrs_cpu_speed],
              ["Storage", product.attrs_storage],
              ...Object.entries(product.extra_attrs || {}).map(([k, v]) => [k, v] as [string, string]),
            ];
            const visible = detailRows.filter(([, v]) => !!v && String(v).trim() !== "");
            if (visible.length === 0) return null;
            return (
              <>
                <Text style={styles.sectionTitle}>Product Details</Text>
                <View style={styles.tableCard}>
                  {visible.map(([k, v]) => <DetailRow key={k} label={k} value={v} />)}
                </View>
              </>
            );
          })()}

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
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingBottom: 2 }}>
                {product.spec_tabs!.map((t, i) => (
                  <TouchableOpacity key={`st-${i}`} onPress={() => setActiveSpecTab(i)} style={[styles.specTab, i === activeSpecTab && styles.specTabActive]}>
                    <Text style={[styles.specTabText, i === activeSpecTab && { color: colors.primaryFg }]}>{t.name || `Tab ${i + 1}`}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <View style={[styles.tableCard, { marginTop: 10 }]}>
                {(product.spec_tabs![activeSpecTab]?.rows || []).map((r, i) => (
                  <DetailRow key={`sr-${i}`} label={r.label} value={r.value} />
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
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 }}>
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
              {/* Helpful vote */}
              <View style={styles.helpfulRow}>
                <TouchableOpacity
                  onPress={() => onToggleHelpful(r)}
                  style={[styles.helpfulBtn, r.voted_helpful && styles.helpfulBtnActive]}
                  hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                  testID={`helpful-${r.id}`}
                >
                  <Feather name="thumbs-up" size={12} color={r.voted_helpful ? colors.primaryFg : colors.primary} />
                  <Text style={[styles.helpfulText, r.voted_helpful && { color: colors.primaryFg }]}>
                    {r.voted_helpful ? "Helpful" : "Helpful?"}{(r.helpful_count || 0) > 0 ? `  ·  ${r.helpful_count}` : ""}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          ))}
        </View>

        {/* Oct-2026 — the only two suggestion rails on this screen */}
        {rails.map((r) => (
          <ProductRail key={r.key} rail={r} />
        ))}
        <View style={{ height: 8 }} />
      </ScrollView>

      {/* Sticky bottom CTA */}
      <View style={[styles.stickyCta, { paddingBottom: Math.max(insets.bottom, 12) + 4 }]}>
        {hydrating ? (
          /* Jun 2026 — the page is live from the preview, but we don't know
             the real stock / options yet, so the buy actions stay inert for
             the fraction of a second the request takes. */
          <View style={[styles.buyBtn, { flex: 1, backgroundColor: colors.surfaceMuted }]}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={[styles.buyBtnText, { color: colors.textMuted }]}>Loading…</Text>
          </View>
        ) : isRecharge ? (
          /* A recharge is paid for on the spot — nothing ships, so the cart
             and the address step are skipped entirely. */
          <TouchableOpacity
            onPress={() => setRechargeOpen(true)}
            style={[styles.buyBtn, { flex: 1 }]}
            testID="recharge-pay-online"
          >
            <Feather name="zap" size={18} color={colors.primaryFg} />
            <Text style={styles.buyBtnText}>Pay online · {formatINR(product.price)}</Text>
          </TouchableOpacity>
        ) : inStock ? (
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

      {/* Recharge — number + how to pay. Nothing else a plan needs. */}
      <Modal visible={rechargeOpen} transparent animationType="slide" onRequestClose={() => setRechargeOpen(false)}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <Pressable style={styles.sheetOverlay} onPress={() => setRechargeOpen(false)}>
            <Pressable style={styles.rechargeSheet} onPress={() => {}}>
              <View style={styles.sheetGrab} />
              <ScrollView
                keyboardShouldPersistTaps="handled"
                showsVerticalScrollIndicator={false}
                bounces={false}
              >
                <Text style={styles.guideTitle}>
                  {rechargeKind === "mobile" ? "Recharge a mobile number" : "Recharge a DTH box"}
                </Text>
                <Text style={styles.rechargeSub} numberOfLines={2}>
                  {product.name} · {formatINR(product.price)}
                </Text>
                <View style={styles.rechargeInputRow}>
                  {rechargeKind === "mobile" ? (
                    <Text style={styles.rechargeCc}>+91</Text>
                  ) : (
                    <Feather name="tv" size={16} color={colors.textMuted} />
                  )}
                  <TextInput
                    value={rechargeAccount}
                    onChangeText={(v) => setRechargeAccount(
                      rechargeKind === "mobile" ? v.replace(/\D+/g, "").slice(0, 10) : v.slice(0, 24),
                    )}
                    placeholder={rechargeKind === "mobile" ? "9876543210" : "Subscriber / customer ID"}
                    placeholderTextColor={colors.textMuted}
                    keyboardType={rechargeKind === "mobile" ? "number-pad" : "default"}
                    style={styles.rechargeInput}
                    returnKeyType="done"
                    testID="recharge-sheet-account"
                  />
                  {rechargeReady ? (
                    <Feather name="check-circle" size={17} color={colors.success} />
                  ) : null}
                </View>

                {/* How to pay — wallet first when it can cover the plan */}
                <Text style={styles.rchPayLabel}>PAY WITH</Text>
                {[
                  { key: "online" as const, label: "Pay online", note: "UPI, card or netbanking", on: true },
                  {
                    key: "wallet" as const,
                    label: `Slangcart wallet · ${formatINR(walletBalance)}`,
                    note: walletCovers
                      ? "Instant — nothing to pay online"
                      : `Short by ${formatINR(Math.max(0, product.price - walletBalance))}`,
                    on: walletCovers,
                  },
                  {
                    key: "split" as const,
                    label: `Wallet ${formatINR(walletBalance)} + ${formatINR(Math.max(0, product.price - walletBalance))} online`,
                    note: "Use the wallet balance and pay the rest",
                    on: !walletCovers && walletBalance > 0.5,
                  },
                ].filter((o) => o.on).map((o) => (
                  <TouchableOpacity
                    key={o.key}
                    onPress={() => setPayMode(o.key)}
                    style={[styles.rchPayRow, payMode === o.key && styles.rchPayRowOn]}
                    testID={`recharge-pay-mode-${o.key}`}
                  >
                    <Feather
                      name={payMode === o.key ? "check-circle" : "circle"}
                      size={17}
                      color={payMode === o.key ? colors.primary : colors.textMuted}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.rchPayTitle}>{o.label}</Text>
                      <Text style={styles.rchPayNote}>{o.note}</Text>
                    </View>
                  </TouchableOpacity>
                ))}

                <Text style={styles.rechargeNote}>
                  No delivery address needed — the recharge is applied to this number.
                </Text>
              </ScrollView>

              {/* Sticky action: always visible, even with the keyboard up */}
              <TouchableOpacity
                onPress={() => {
                  const args = {
                    kind: rechargeKind,
                    productId: product.id,
                    planName: product.name,
                    account: rechargeAccount,
                    state: String(params.rchState || product.recharge_state || "") || undefined,
                    network: String(params.rchNetwork || product.recharge_network || "") || undefined,
                    prefill: { name: (user as any)?.name, email: (user as any)?.email, contact: rechargeAccount },
                  };
                  if (payMode === "wallet") return payFromWallet(args);
                  return payRecharge({ ...args, walletAmount: payMode === "split" ? walletBalance : 0 });
                }}
                disabled={!!rechargePaying || !rechargeReady}
                style={[
                  styles.buyBtn,
                  { marginTop: 12 },
                  (!!rechargePaying || !rechargeReady) && { opacity: 0.5 },
                ]}
                testID="recharge-sheet-pay"
              >
                {rechargePaying ? <ActivityIndicator color={colors.primaryFg} size="small" /> : (
                  <>
                    <Feather name={payMode === "online" ? "zap" : "credit-card"} size={18} color={colors.primaryFg} />
                    <Text style={styles.buyBtnText}>
                      {payMode === "wallet"
                        ? `Pay ${formatINR(product.price)} from wallet`
                        : `Pay ${formatINR(payMode === "split" ? Math.max(0, product.price - walletBalance) : product.price)}`}
                    </Text>
                  </>
                )}
              </TouchableOpacity>
            </Pressable>
          </Pressable>
        </KeyboardAvoidingView>
      </Modal>
      <RazorpayWebViewModal html={rzpHtml} onMessage={handleMessage} onCancel={cancelRzp} />

      {/* Ask Vendor modal */}
      {/* Size-guide sheet — real measurements so shoppers order the right
          fit instead of guessing (Jun 2026). */}
      <Modal visible={guideOpen} transparent animationType="slide" onRequestClose={() => setGuideOpen(false)}>
        <Pressable style={styles.sheetOverlay} onPress={() => setGuideOpen(false)}>
          <Pressable style={styles.guideSheet} onPress={() => {}}>
            <View style={styles.guideHead}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.guideTitle}>Size guide</Text>
                <Text style={styles.guideSub} numberOfLines={1}>{product.variant_guide?.label || ""}</Text>
              </View>
              <TouchableOpacity onPress={() => setGuideOpen(false)} style={styles.iconBtn} testID="size-guide-close">
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 420 }} contentContainerStyle={{ paddingBottom: 16 }}>
              <View style={[styles.guideRow, styles.guideRowHead]}>
                {(product.variant_guide?.columns || []).map((c) => (
                  <Text key={`gc-${c}`} style={[styles.guideCell, styles.guideCellHead]} numberOfLines={2}>{c}</Text>
                ))}
              </View>
              {(product.variant_guide?.guide || []).map((row, ri) => {
                const isSel = selected && String(row[0]).toLowerCase() === selected.label.toLowerCase();
                return (
                  <View key={`gr-${ri}`} style={[styles.guideRow, isSel && { backgroundColor: colors.brand100 }]}>
                    {row.map((cell, ci) => (
                      <Text key={`gcell-${ri}-${ci}`} style={[styles.guideCell, ci === 0 && { fontWeight: "800" }]}>{cell}</Text>
                    ))}
                  </View>
                );
              })}
              <Text style={styles.guideNote}>
                Measurements are of the garment, in {product.variant_guide?.unit === "cm" ? "centimetres" : "inches"}.
                If you are between two sizes we recommend the larger one.
              </Text>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>

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

function StyledBlock({ icon, label, block }: { icon: any; label: string; block?: StyledText }) {
  const text = (block?.text || "").trim();
  // Per user requirement: only render this section if the admin/vendor
  // explicitly provided text. Empty blocks must NOT appear with a default
  // placeholder in the user-facing product view.
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
  // Sep 2026 alignment rule — short values sit right-aligned on the same
  // line as their label; long ones (SIM strings, network band lists) STACK
  // under the label, left-aligned, instead of wrapping into a ragged
  // right-hand column. Empty values render an em dash so a row never looks
  // broken (the owner's screenshot had a blank "Custom UI" row).
  const text = (value ?? "").trim();
  const stacked = text.length > 24;
  if (!text) {
    return (
      <View style={styles.detailRow}>
        <Text style={styles.detailLabel}>{label}</Text>
        <Text style={[styles.detailValue, { color: colors.textMuted, fontWeight: "600" }]}>—</Text>
      </View>
    );
  }
  if (stacked) {
    return (
      <View style={styles.detailRowStacked}>
        <Text style={styles.detailLabel}>{label}</Text>
        <Text style={styles.detailValueStacked}>{text}</Text>
      </View>
    );
  }
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{text}</Text>
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
  ownerBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginHorizontal: spacing.screen, marginTop: 10,
    paddingVertical: 12, paddingHorizontal: 14,
    borderRadius: 12, borderWidth: 1,
    borderColor: colors.primary + "40",
    backgroundColor: colors.primary + "10",
  },
  ownerBannerTitle: { fontSize: 13, fontWeight: "800", color: colors.primary },
  ownerBannerSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  // ── HERO CARD (Sep 2026) ─────────────────────────────────────────────
  // Inset, elevated, and the SAME width as every other box on the page, so
  // the whole screen shares one left/right edge. Photos are contained on a
  // soft wash instead of being cropped to fill.
  heroCard: {
    marginHorizontal: spacing.screen, marginTop: 10,
    backgroundColor: colors.surface,
    borderRadius: 20, borderWidth: 1, borderColor: colors.border,
    paddingBottom: 4, overflow: "hidden",
    ...Platform.select({
      ios: { shadowColor: "#0F172A", shadowOpacity: 0.06, shadowRadius: 12, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 2 },
      default: {},
    }),
  },
  heroCanvas: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, position: "relative", overflow: "hidden" },
  heroImg: { width: "100%", height: "100%" },
  heroDots: {
    position: "absolute", left: 0, right: 0, bottom: 12,
    flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6,
  },
  heroDot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: withAlpha(colors.primary, 0.25),
  },
  heroDotActive: {
    width: 18, height: 6, borderRadius: 3,
    backgroundColor: colors.primary,
  },
  heroCounter: {
    position: "absolute", right: 12, bottom: 12,
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: "rgba(17,24,39,0.62)",
  },
  heroCounterText: { color: "#FFFFFF", fontSize: 11, fontWeight: "800", letterSpacing: 0.3 },
  heroOOSBadge: { position: "absolute", top: 14, left: 14, backgroundColor: "#B91C1C", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  heroOOSText: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.2 },
  heartBtn: {
    position: "absolute", top: 12, right: 12,
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "rgba(255,255,255,0.94)",
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  thumbsRow: { gap: 8, paddingHorizontal: 12, paddingTop: 12, paddingBottom: 12 },
  thumb: { width: 48, height: 48, borderRadius: 10, overflow: "hidden", borderWidth: 2, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  thumbActive: { borderColor: colors.primary },
  thumbImg: { width: "100%", height: "100%" },
  infoWrap: { paddingHorizontal: spacing.screen, paddingTop: 12, paddingBottom: 8, gap: 12 },
  // ── ONE BOX RECIPE for every section on the page ─────────────────────
  card: {
    backgroundColor: colors.surface, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, padding: 16,
  },
  productName: { fontSize: 20, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4, lineHeight: 27 },
  bulletList: { marginTop: 8, gap: 4 },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  bulletDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: colors.primary, marginTop: 7 },
  bulletText: { fontSize: 13, color: colors.textMain, flex: 1, lineHeight: 19 },
  priceRow: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-between", marginTop: 12, gap: 8 },
  cashbackRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginTop: 12, padding: 10,
    backgroundColor: "#F0FDF4", borderWidth: 1, borderColor: "#BBF7D0",
    borderRadius: 12,
  },
  cashbackIcon: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: "#DCFCE7", alignItems: "center", justifyContent: "center",
  },
  cashbackTitle: { fontSize: 13, fontWeight: "800", color: "#15803D" },
  cashbackSub: { fontSize: 11, color: "#166534", marginTop: 2 },
  priceFrom: { fontSize: 9.5, fontWeight: "900", letterSpacing: 1.1, color: colors.textMuted, marginBottom: 2 },
  price: { fontSize: 26, fontWeight: "900", color: colors.primary, letterSpacing: -0.6 },
  ratingChip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, backgroundColor: "#FEF3C7" },
  ratingChipText: { fontSize: 11, fontWeight: "800", color: "#92400E" },
  summaryBlock: { backgroundColor: colors.surface, padding: 14, borderRadius: 16, borderWidth: 1, borderColor: colors.border },
  summaryLabel: { fontSize: 9, fontWeight: "900", letterSpacing: 1.2, color: colors.primary },
  // ── Jun 2026 — Size / option picker + size-guide sheet ──────────────
  sizeCard: {
    padding: 16, backgroundColor: colors.surface,
    borderRadius: 16, borderWidth: 1, borderColor: colors.border,
  },
  sizeHeadRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  sizeGuideLink: { fontSize: 12, fontWeight: "800", color: colors.primary, textDecorationLine: "underline" },
  sizeWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
  // Chips: selected = green outline + light-green tint (not a filled slab),
  // so a wrapped grid of them stays calm and the price hint stays readable.
  sizeChip: {
    minWidth: 92, minHeight: 52, paddingHorizontal: 14, paddingVertical: 8,
    alignItems: "center", justifyContent: "center", gap: 1,
    borderRadius: 12, borderWidth: 1.5, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  sizeChipSel: { backgroundColor: colors.brand100, borderColor: colors.primary },
  sizeChipOOS: { backgroundColor: colors.surfaceMuted, borderColor: colors.border, borderStyle: "dashed", opacity: 0.6 },
  sizeChipText: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  sizeChipTextOOS: { color: colors.textMuted, textDecorationLine: "line-through" },
  sizeChipPrice: { fontSize: 11, fontWeight: "700", color: colors.textMuted },
  sizeChipPriceOOS: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.3 },
  sizeMeta: { fontSize: 12, color: colors.textMuted, marginTop: 12, fontWeight: "600" },
  sheetOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  guideSheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingHorizontal: 16, paddingTop: 14, paddingBottom: 24,
  },
  guideHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  guideTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  // Jun 2026 — recharge pay sheet (no cart, no address).
  rechargeSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingHorizontal: spacing.screen, paddingTop: 10, paddingBottom: 26,
    maxHeight: "86%",
  },
  sheetGrab: {
    width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: 12,
  },
  rchPayLabel: {
    fontSize: 10, fontWeight: "900", letterSpacing: 0.7, color: colors.textMuted,
    marginTop: 16, marginBottom: 6,
  },
  rchPayRow: {
    flexDirection: "row", alignItems: "center", gap: 10, padding: 11, marginBottom: 7,
    borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.background,
  },
  rchPayRowOn: { borderColor: colors.primary, backgroundColor: colors.surfaceMuted },
  rchPayTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  rchPayNote: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  rchTagRow: { flexDirection: "row", flexWrap: "wrap", gap: 7, marginTop: 10 },
  rchTag: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 9,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  rchTagText: { fontSize: 11.5, fontWeight: "800", color: colors.textMain },
  rechargeSub: { fontSize: 12.5, color: colors.textMuted, fontWeight: "700", marginTop: 4 },
  rechargeInputRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: 14,
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.card,
    paddingHorizontal: 12, minHeight: 50, backgroundColor: colors.background,
  },
  rechargeCc: { fontSize: 14, fontWeight: "800", color: colors.textMuted },
  rechargeInput: { flex: 1, fontSize: 15, fontWeight: "700", color: colors.textMain },
  rechargeNote: { fontSize: 11, color: colors.textMuted, marginTop: 8, lineHeight: 15 },

  guideSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  guideRow: {
    flexDirection: "row", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: colors.border,
    paddingVertical: 10, gap: 6,
  },
  guideRowHead: { backgroundColor: colors.surfaceMuted, borderTopLeftRadius: 8, borderTopRightRadius: 8, paddingHorizontal: 6 },
  guideCell: { flex: 1, fontSize: 12, color: colors.textMain, textAlign: "center" },
  guideCellHead: { fontSize: 10.5, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.3 },
  guideNote: { fontSize: 11.5, color: colors.textMuted, marginTop: 14, lineHeight: 17 },
  qtyCard: { padding: 16, backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border },
  qtyLabel: { fontSize: 10, fontWeight: "900", letterSpacing: 1.1, color: colors.textMuted, marginBottom: 8 },
  qtyRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  qtyBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  qtyText: { fontSize: 16, fontWeight: "900", color: colors.textMain, minWidth: 32, textAlign: "center" },
  qtySubLabel: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.6, marginRight: 6 },
  qtySubAmount: { fontSize: 17, fontWeight: "900", color: colors.primary, letterSpacing: -0.3 },
  actionRow: { flexDirection: "row", gap: 10 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 46, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  actionText: { fontSize: 12.5, fontWeight: "800", color: colors.primary },
  sectionTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4, marginTop: 6, marginBottom: 2 },
  // Key-value table card — rows are divided, the last row has no divider so
  // the card never ends on a stray line.
  tableCard: { backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 16, paddingVertical: 4 },
  detailRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: colors.border },
  detailRowStacked: { paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 3 },
  detailLabel: { fontSize: 12.5, color: colors.textMuted, fontWeight: "700" },
  detailValue: { fontSize: 13, color: colors.textMain, fontWeight: "700", textAlign: "right", flexShrink: 1 },
  detailValueStacked: { fontSize: 13, color: colors.textMain, fontWeight: "700", textAlign: "left", lineHeight: 19 },
  descBox: { backgroundColor: colors.surface, padding: 16, borderRadius: 16, borderWidth: 1, borderColor: colors.border },
  descText: { fontSize: 13.5, color: colors.textMain, lineHeight: 22 },
  specTab: { paddingHorizontal: 16, minHeight: 40, alignItems: "center", justifyContent: "center", borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  specTabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  specTabText: { fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  boxGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  boxItem: { width: "31%", alignItems: "center", gap: 4 },
  boxThumb: { width: "100%", aspectRatio: 1, borderRadius: 10, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  boxImg: { width: "100%", height: "100%" },
  boxName: { fontSize: 10, color: colors.textMain, fontWeight: "700", textAlign: "center" },
  // Reviews
  writeReviewBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 14, minHeight: 36, justifyContent: "center", borderRadius: 999, backgroundColor: colors.primary },
  writeReviewText: { fontSize: 11, fontWeight: "800", color: colors.primaryFg },
  reviewStats: { flexDirection: "row", alignItems: "center", gap: 6, padding: 14, borderRadius: 16, backgroundColor: colors.brand100 },
  reviewAvg: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.3 },
  reviewMeta: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  emptyReviews: { alignItems: "center", paddingVertical: 28, paddingHorizontal: 16, gap: 8, backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border, borderStyle: "dashed" },
  emptyReviewsText: { fontSize: 12, color: colors.textMuted },
  reviewCard: { backgroundColor: colors.surface, padding: 16, borderRadius: 16, borderWidth: 1, borderColor: colors.border },
  reviewAvatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  reviewAvatarText: { fontSize: 12, fontWeight: "900", color: colors.primary },
  reviewName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  verifiedPill: { backgroundColor: "#DCFCE7", paddingHorizontal: 5, paddingVertical: 1, borderRadius: 4 },
  verifiedText: { fontSize: 8, fontWeight: "900", color: "#065F46", letterSpacing: 0.6 },
  reviewTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  reviewBody: { fontSize: 12, color: colors.textMain, lineHeight: 18, marginTop: 2 },
  reviewImg: { width: 70, height: 70, borderRadius: 8 },
  helpfulRow: { flexDirection: "row", alignItems: "center", marginTop: 10 },
  helpfulBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.primary,
    backgroundColor: colors.primary + "10",
  },
  helpfulBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  helpfulText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
  // Sticky CTA — elevated so page content clearly slides beneath it, with
  // the home-indicator inset handled by the screen (see insets.bottom).
  stickyCta: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    paddingHorizontal: spacing.screen, paddingTop: 12,
    backgroundColor: colors.surface,
    borderTopWidth: 1, borderTopColor: colors.border,
    flexDirection: "row", gap: 12,
    ...Platform.select({
      ios: { shadowColor: "#0F172A", shadowOpacity: 0.08, shadowRadius: 12, shadowOffset: { width: 0, height: -3 } },
      android: { elevation: 12 },
      default: {},
    }),
  },
  cartBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 50, borderRadius: 999, borderWidth: 1.5, borderColor: colors.primary, backgroundColor: colors.surface },
  cartBtnText: { fontSize: 13.5, fontWeight: "900", color: colors.primary },
  buyBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, minHeight: 50, borderRadius: 999, backgroundColor: colors.primary },
  buyBtnText: { fontSize: 13.5, fontWeight: "900", color: colors.primaryFg },
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
