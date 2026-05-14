/**
 * ShopHome — Premium e-commerce home screen.
 *
 * Pure UI component. Reads products from /api/products, otherwise stateless.
 * Self-contained: includes its OWN sticky header (delivery + wishlist + cart),
 * search bar, category circles, banner, and 3 horizontal product/category
 * sections. The parent <ShopScreen> just renders <ShopHome /> for shop mode.
 *
 * Design language:
 *  • White clean background
 *  • Green accent (colors.primary)
 *  • Rounded corners (16-22px on cards, 14-18px on chips)
 *  • Soft shadows / elevation only where it adds depth
 *  • Mobile-first responsive flex layout — no fixed widths
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, TextInput,
  ActivityIndicator, FlatList, Platform, useWindowDimensions,
} from "react-native";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, formatApiError } from "./api";
import { colors } from "./theme";

// ── Types ────────────────────────────────────────────────────────────────
type Product = {
  id: string;
  name: string;
  price: number;
  image_url?: string | null;
  image_data_url?: string | null;
  images?: string[];
  category?: string;
  is_in_stock?: boolean;
  stock?: number;
  rating?: number;
  interested_count?: number;
};

// ── Pure helpers ─────────────────────────────────────────────────────────
const formatINR = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;
const seededRating = (id: string) => {
  // Stable pseudo-rating so the same product always shows the same stars.
  let h = 0; for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return Number((3.8 + ((Math.abs(h) % 12) / 10)).toFixed(1)); // 3.8 – 4.9
};
const seededDiscount = (id: string) => {
  let h = 0; for (let i = 0; i < id.length; i++) h = (h * 17 + id.charCodeAt(i)) | 0;
  return 10 + (Math.abs(h) % 50); // 10 – 59 %
};
const productImage = (p: Product) =>
  (p.images && p.images[0]) || p.image_data_url || p.image_url || null;

// Hardcoded category circles per spec.
const CATEGORIES: { key: string; label: string; icon: any; color: string }[] = [
  { key: "all",         label: "All",         icon: "grid",         color: "#E5F2EC" },
  { key: "Sarees",      label: "Sarees",      icon: "feather",      color: "#FCE7F3" },
  { key: "Men",         label: "Men",         icon: "user",         color: "#DBEAFE" },
  { key: "Women",       label: "Women",       icon: "user",         color: "#FDE68A" },
  { key: "Electronics", label: "Electronics", icon: "smartphone",   color: "#E0E7FF" },
  { key: "Home",        label: "Home",        icon: "home",         color: "#FFEDD5" },
  { key: "Beauty",      label: "Beauty",      icon: "heart",        color: "#FCE7F3" },
  { key: "More",        label: "More",        icon: "more-horizontal", color: "#F3F4F6" },
];

// Popular Categories — bigger tiles, curated.
const POPULAR_CATEGORIES = [
  { key: "Sarees",      label: "Sarees",      sub: "From ₹299",    icon: "feather",  color: "#FCE7F3" },
  { key: "Men",         label: "Men's wear",  sub: "Trending",     icon: "user",     color: "#DBEAFE" },
  { key: "Electronics", label: "Electronics", sub: "Top deals",    icon: "cpu",      color: "#E0E7FF" },
  { key: "Home",        label: "Home",        sub: "New arrivals", icon: "home",     color: "#FFEDD5" },
  { key: "Beauty",      label: "Beauty",      sub: "Up to 70% off",icon: "heart",    color: "#FEE2E2" },
];

// ── ShopHome ─────────────────────────────────────────────────────────────
export function ShopHome({
  cartCount = 0,
  wishlistCount = 0,
  deliveryAddress = "Mumbai, India",
}: {
  cartCount?: number;
  wishlistCount?: number;
  deliveryAddress?: string;
}) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [bannerIdx, setBannerIdx] = useState(0);

  // ── Data ───────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<any>("/products");
      const list: Product[] = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setProducts(list.filter((p) => p && p.is_in_stock !== false));
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("ShopHome /products failed:", formatApiError(e));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Derived collections per section ───────────────────────────────────
  const filteredProducts = useMemo(() => {
    let arr = products;
    if (activeCategory !== "all") {
      arr = arr.filter((p) => (p.category || "").toLowerCase() === activeCategory.toLowerCase());
    }
    const q = search.trim().toLowerCase();
    if (q) arr = arr.filter((p) => p.name.toLowerCase().includes(q));
    return arr;
  }, [products, activeCategory, search]);

  const dealsOfTheDay = useMemo(() => filteredProducts.slice(0, 12), [filteredProducts]);
  const bestSellers = useMemo(() => {
    // Cheap heuristic: products with the most "interested_count" first.
    return [...filteredProducts]
      .sort((a, b) => (b.interested_count || 0) - (a.interested_count || 0))
      .slice(0, 12);
  }, [filteredProducts]);

  // ── Banner slides (single banner area, 2 slides for the dots) ────────
  const banners = useMemo(() => ([
    {
      key: "fresh",
      title: "Fresh Styles for Every You",
      subtitle: "Up to 60% Off",
      cta: "Shop Now",
      target: "/shop-category/Clothes",
      gradient: ["#0D7C56", "#10B981"],
    },
    {
      key: "tech",
      title: "Smart Picks for Smart Lives",
      subtitle: "Electronics under ₹999",
      cta: "Explore",
      target: "/shop-category/Electronics",
      gradient: ["#0F766E", "#22D3EE"],
    },
  ]), []);

  // ── Tiny helper renderers ─────────────────────────────────────────────
  const ProductCard = useCallback(({ p, badge, compact }: { p: Product; badge?: string; compact?: boolean }) => {
    const img = productImage(p);
    const disc = seededDiscount(p.id);
    const mrp = Math.round(p.price * (100 / (100 - disc)));
    const rating = p.rating || seededRating(p.id);
    const W = compact ? 150 : 168;
    return (
      <TouchableOpacity
        activeOpacity={0.82}
        onPress={() => router.push(`/product/${p.id}` as any)}
        style={[styles.pCard, { width: W }]}
        testID={`home-product-${p.id}`}
      >
        <View style={styles.pImageWrap}>
          {img ? (
            <Image source={{ uri: img }} style={styles.pImage} resizeMode="cover" />
          ) : (
            <View style={[styles.pImage, styles.pImagePlaceholder]}>
              <Feather name="image" size={28} color={colors.textMuted} />
            </View>
          )}
          <View style={styles.pDiscountBadge}>
            <Text style={styles.pDiscountText}>-{disc}%</Text>
          </View>
          <TouchableOpacity
            style={styles.pHeart}
            onPress={() => router.push(`/product/${p.id}` as any)}
            hitSlop={{ top: 4, bottom: 4, left: 4, right: 4 }}
          >
            <Feather name="heart" size={14} color="#EF4444" />
          </TouchableOpacity>
          {badge ? (
            <View style={styles.pTopBadge}>
              <Feather name="award" size={10} color="#92400E" />
              <Text style={styles.pTopBadgeText}>{badge}</Text>
            </View>
          ) : null}
        </View>
        <View style={styles.pBody}>
          <Text style={styles.pName} numberOfLines={2}>{p.name}</Text>
          <View style={styles.pPriceRow}>
            <Text style={styles.pPrice}>{formatINR(p.price)}</Text>
            <Text style={styles.pMrp}>{formatINR(mrp)}</Text>
          </View>
          <View style={styles.pRatingRow}>
            <View style={styles.pRatingChip}>
              <Text style={styles.pRatingText}>{rating}</Text>
              <Feather name="star" size={9} color="#fff" />
            </View>
            <Text style={styles.pRatingCount}>·  {12 + (Math.abs(p.id.length) % 40)}k reviews</Text>
          </View>
        </View>
      </TouchableOpacity>
    );
  }, [router]);

  const SectionHeader = useCallback(({ icon, title, onViewAll }: { icon: any; title: string; onViewAll?: () => void }) => (
    <View style={styles.sectionHeader}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Feather name={icon} size={16} color={colors.primary} />
        <Text style={styles.sectionTitle}>{title}</Text>
      </View>
      {onViewAll ? (
        <TouchableOpacity onPress={onViewAll} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
          <Text style={styles.viewAll}>View All</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  ), []);

  // Active banner gradient. RN doesn't ship gradients out-of-the-box; we
  // approximate with a solid colour from the slide's palette so we don't
  // need to install a new dependency. Looks great with the white bg.
  const activeBanner = banners[bannerIdx % banners.length];

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {/* 1. TOP HEADER — delivery + wishlist + cart */}
      <View style={[styles.headerWrap, { paddingTop: insets.top + 8 }]}>
        <View style={styles.headerRow}>
          <TouchableOpacity style={styles.deliveryBlock} activeOpacity={0.7}>
            <Feather name="map-pin" size={13} color={colors.primary} />
            <View style={{ flexShrink: 1 }}>
              <Text style={styles.deliveryEyebrow}>Deliver to</Text>
              <Text style={styles.deliveryAddress} numberOfLines={1}>
                {deliveryAddress}  <Feather name="chevron-down" size={11} color={colors.textMain} />
              </Text>
            </View>
          </TouchableOpacity>
          <View style={styles.headerIconRow}>
            <TouchableOpacity
              style={styles.iconBtn}
              onPress={() => router.push("/wishlist" as any)}
              testID="home-wishlist-btn"
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Feather name="heart" size={19} color={colors.textMain} />
              {wishlistCount > 0 ? (
                <View style={styles.iconBadge}><Text style={styles.iconBadgeText}>{wishlistCount > 9 ? "9+" : wishlistCount}</Text></View>
              ) : null}
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.iconBtn, styles.cartIconBtnHome]}
              onPress={() => router.push("/cart" as any)}
              testID="home-cart-btn"
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            >
              <Feather name="shopping-cart" size={19} color={colors.primaryFg} />
              {cartCount > 0 ? (
                <View style={[styles.iconBadge, { backgroundColor: "#F59E0B" }]}><Text style={styles.iconBadgeText}>{cartCount > 9 ? "9+" : cartCount}</Text></View>
              ) : null}
            </TouchableOpacity>
          </View>
        </View>

        {/* 2. SEARCH BAR — full width with search button on the right */}
        <View style={styles.searchRow}>
          <View style={styles.searchBox}>
            <Feather name="search" size={15} color={colors.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search for sarees, mobiles, more…"
              placeholderTextColor={colors.textMuted}
              returnKeyType="search"
              style={styles.searchInput}
            />
          </View>
          <TouchableOpacity
            style={styles.searchBtn}
            onPress={() => router.push(`/shop-search?q=${encodeURIComponent(search)}` as any)}
            testID="home-search-btn"
          >
            <Feather name="search" size={16} color={colors.primaryFg} />
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ paddingBottom: 32 }}
        showsVerticalScrollIndicator={false}
      >
        {/* 3. HORIZONTAL CATEGORY SCROLL — circular icons */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.catScroll}
        >
          {CATEGORIES.map((c) => {
            const active = activeCategory === c.key;
            return (
              <TouchableOpacity
                key={c.key}
                style={styles.catItem}
                onPress={() => {
                  setActiveCategory(c.key);
                  if (c.key === "More") router.push("/shop-category/All" as any);
                }}
                activeOpacity={0.75}
                testID={`home-cat-${c.key}`}
              >
                <View style={[styles.catCircle, { backgroundColor: c.color }, active && styles.catCircleActive]}>
                  <Feather name={c.icon} size={20} color={active ? colors.primaryFg : colors.textMain} />
                </View>
                <Text style={[styles.catLabel, active && { color: colors.primary, fontWeight: "800" }]}>{c.label}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        {/* 4. SINGLE MAIN BANNER */}
        <View style={styles.bannerWrap}>
          <View style={[styles.banner, { backgroundColor: activeBanner.gradient[0] }]}>
            {/* Decorative blob — pure RN, no extra deps */}
            <View style={[styles.bannerBlob, { backgroundColor: activeBanner.gradient[1] + "55" }]} />
            <View style={styles.bannerLeft}>
              <Text style={styles.bannerEyebrow}>{activeBanner.subtitle}</Text>
              <Text style={styles.bannerTitle}>{activeBanner.title}</Text>
              <TouchableOpacity
                style={styles.bannerCta}
                onPress={() => router.push(activeBanner.target as any)}
                testID="home-banner-cta"
              >
                <Text style={styles.bannerCtaText}>{activeBanner.cta}</Text>
                <Feather name="arrow-right" size={13} color={colors.primary} />
              </TouchableOpacity>
            </View>
            <View style={styles.bannerRight}>
              <Feather name="shopping-bag" size={84} color="#ffffff55" />
            </View>
          </View>
          <View style={styles.bannerDots}>
            {banners.map((_, i) => (
              <TouchableOpacity
                key={i}
                onPress={() => setBannerIdx(i)}
                style={[styles.bannerDot, i === bannerIdx && styles.bannerDotActive]}
              />
            ))}
          </View>
        </View>

        {/* 5. DEAL OF THE DAY */}
        <SectionHeader
          icon="zap"
          title="Deal of the Day"
          onViewAll={() => router.push("/shop-category/All" as any)}
        />
        {loading ? (
          <View style={styles.loadingRow}><ActivityIndicator color={colors.primary} /></View>
        ) : dealsOfTheDay.length === 0 ? (
          <Text style={styles.emptyText}>No deals right now. Check back soon!</Text>
        ) : (
          <FlatList
            data={dealsOfTheDay}
            keyExtractor={(p) => `deal-${p.id}`}
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.hList}
            ItemSeparatorComponent={() => <View style={{ width: 12 }} />}
            renderItem={({ item }) => <ProductCard p={item} />}
          />
        )}

        {/* 6. POPULAR CATEGORIES */}
        <SectionHeader
          icon="grid"
          title="Popular Categories"
          onViewAll={() => router.push("/shop-category/All" as any)}
        />
        <FlatList
          data={POPULAR_CATEGORIES}
          keyExtractor={(c) => `popcat-${c.key}`}
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.hList}
          ItemSeparatorComponent={() => <View style={{ width: 12 }} />}
          renderItem={({ item }) => (
            <TouchableOpacity
              activeOpacity={0.82}
              onPress={() => router.push(`/shop-category/${encodeURIComponent(item.key)}` as any)}
              style={styles.popCatCard}
              testID={`home-popcat-${item.key}`}
            >
              <View style={[styles.popCatIcon, { backgroundColor: item.color }]}>
                <Feather name={item.icon as any} size={26} color={colors.textMain} />
              </View>
              <Text style={styles.popCatTitle} numberOfLines={1}>{item.label}</Text>
              <Text style={styles.popCatSub} numberOfLines={1}>{item.sub}</Text>
            </TouchableOpacity>
          )}
        />

        {/* 7. BEST SELLERS */}
        <SectionHeader
          icon="trending-up"
          title="Best Sellers"
          onViewAll={() => router.push("/shop-category/All" as any)}
        />
        {loading ? (
          <View style={styles.loadingRow}><ActivityIndicator color={colors.primary} /></View>
        ) : bestSellers.length === 0 ? (
          <Text style={styles.emptyText}>Building our best-seller list — come back soon.</Text>
        ) : (
          <FlatList
            data={bestSellers}
            keyExtractor={(p) => `best-${p.id}`}
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.hList}
            ItemSeparatorComponent={() => <View style={{ width: 12 }} />}
            renderItem={({ item }) => <ProductCard p={item} badge="Best Seller" compact />}
          />
        )}
      </ScrollView>
    </View>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  // 1. Header
  headerWrap: {
    backgroundColor: colors.background,
    paddingHorizontal: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border + "55",
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    width: "100%",
    minHeight: 44,
  },
  deliveryBlock: {
    flex: 1, minWidth: 0,
    flexDirection: "row", alignItems: "center", gap: 6,
    marginRight: 10,
  },
  deliveryEyebrow: { fontSize: 10.5, color: colors.textMuted, letterSpacing: 0.5, fontWeight: "700" },
  deliveryAddress: { fontSize: 13.5, color: colors.textMain, fontWeight: "800" },
  headerIconRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    flexShrink: 0,
  },
  iconBtn: {
    width: 40, height: 40, borderRadius: 14,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
    position: "relative",
  },
  cartIconBtnHome: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  iconBadge: {
    position: "absolute", top: -4, right: -4,
    minWidth: 17, height: 17, borderRadius: 9,
    backgroundColor: "#EF4444",
    alignItems: "center", justifyContent: "center",
    paddingHorizontal: 4,
    borderWidth: 2, borderColor: colors.background,
  },
  iconBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff", letterSpacing: -0.2 },

  // 2. Search
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginTop: 12,
  },
  searchBox: {
    flex: 1, minWidth: 0,
    flexDirection: "row", alignItems: "center", gap: 10,
    height: 48, paddingHorizontal: 14,
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1, borderColor: colors.border,
    ...Platform.select({
      ios: { shadowColor: "#0F2A1D", shadowOpacity: 0.04, shadowRadius: 6, shadowOffset: { width: 0, height: 1 } },
      android: { elevation: 0 },
    }),
  },
  searchInput: {
    flex: 1, minWidth: 0,
    fontSize: 13.5, color: colors.textMain,
    paddingVertical: 0,
    fontWeight: "500",
  },
  searchBtn: {
    width: 48, height: 48, borderRadius: 16,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
    flexShrink: 0,
    ...Platform.select({
      ios: { shadowColor: colors.primary, shadowOpacity: 0.2, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } },
      android: { elevation: 2 },
    }),
  },

  // 3. Category circles
  catScroll: { paddingHorizontal: 12, paddingVertical: 14, gap: 0 },
  catItem: { alignItems: "center", width: 72, marginHorizontal: 2 },
  catCircle: {
    width: 56, height: 56, borderRadius: 28,
    alignItems: "center", justifyContent: "center",
    marginBottom: 6,
  },
  catCircleActive: { backgroundColor: colors.primary },
  catLabel: { fontSize: 11.5, color: colors.textMain, fontWeight: "700", textAlign: "center" },

  // 4. Banner
  bannerWrap: { paddingHorizontal: 16, paddingTop: 4, paddingBottom: 4 },
  banner: {
    flexDirection: "row", alignItems: "center",
    minHeight: 150,
    padding: 18,
    borderRadius: 22,
    overflow: "hidden",
    position: "relative",
  },
  bannerBlob: {
    position: "absolute",
    width: 220, height: 220, borderRadius: 110,
    right: -60, top: -60,
  },
  bannerLeft: { flex: 1, minWidth: 0, gap: 6, zIndex: 1 },
  bannerEyebrow: { fontSize: 12, color: "#ffffff", opacity: 0.85, fontWeight: "800", letterSpacing: 0.5 },
  bannerTitle: { fontSize: 20, color: "#ffffff", fontWeight: "900", lineHeight: 24 },
  bannerCta: {
    marginTop: 10,
    alignSelf: "flex-start",
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: 999,
    backgroundColor: "#ffffff",
  },
  bannerCtaText: { color: colors.primary, fontWeight: "900", fontSize: 12.5, letterSpacing: 0.3 },
  bannerRight: { width: 100, alignItems: "center", justifyContent: "center", zIndex: 1 },
  bannerDots: {
    flexDirection: "row", justifyContent: "center", alignItems: "center",
    gap: 6, marginTop: 10,
  },
  bannerDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.border },
  bannerDotActive: { width: 18, backgroundColor: colors.primary },

  // Section headers
  sectionHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 16, marginTop: 18, marginBottom: 8,
  },
  sectionTitle: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  viewAll: { fontSize: 12, fontWeight: "800", color: colors.primary },

  // Horizontal list common padding
  hList: { paddingHorizontal: 16, paddingVertical: 4 },

  // Product card
  pCard: {
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1, borderColor: colors.border + "AA",
    overflow: "hidden",
    ...Platform.select({
      ios: { shadowColor: "#0F2A1D", shadowOpacity: 0.05, shadowRadius: 8, shadowOffset: { width: 0, height: 2 } },
      android: { elevation: 1 },
    }),
  },
  pImageWrap: { width: "100%", aspectRatio: 1, position: "relative", backgroundColor: "#F3F4F6" },
  pImage: { width: "100%", height: "100%" },
  pImagePlaceholder: { alignItems: "center", justifyContent: "center" },
  pDiscountBadge: {
    position: "absolute", top: 8, left: 8,
    paddingHorizontal: 7, paddingVertical: 3,
    borderRadius: 6,
    backgroundColor: "#EF4444",
  },
  pDiscountText: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 0.3 },
  pHeart: {
    position: "absolute", top: 8, right: 8,
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: "#ffffffEE",
    alignItems: "center", justifyContent: "center",
  },
  pTopBadge: {
    position: "absolute", bottom: 8, left: 8,
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 7, paddingVertical: 3,
    borderRadius: 6,
    backgroundColor: "#FEF3C7",
  },
  pTopBadgeText: { fontSize: 9.5, fontWeight: "900", color: "#92400E", letterSpacing: 0.2 },
  pBody: { padding: 10, gap: 4 },
  pName: { fontSize: 12.5, color: colors.textMain, fontWeight: "700", lineHeight: 16 },
  pPriceRow: { flexDirection: "row", alignItems: "baseline", gap: 6 },
  pPrice: { fontSize: 14.5, color: colors.textMain, fontWeight: "900" },
  pMrp: { fontSize: 11, color: colors.textMuted, textDecorationLine: "line-through" },
  pRatingRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 },
  pRatingChip: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 5, paddingVertical: 1.5,
    borderRadius: 4,
    backgroundColor: "#0F8B5C",
  },
  pRatingText: { fontSize: 10, fontWeight: "900", color: "#fff" },
  pRatingCount: { fontSize: 10, color: colors.textMuted, fontWeight: "600" },

  // Popular category card
  popCatCard: {
    width: 132,
    backgroundColor: colors.surface,
    borderRadius: 16,
    borderWidth: 1, borderColor: colors.border + "AA",
    padding: 12,
    alignItems: "center",
    gap: 6,
    ...Platform.select({
      ios: { shadowColor: "#0F2A1D", shadowOpacity: 0.05, shadowRadius: 8, shadowOffset: { width: 0, height: 2 } },
      android: { elevation: 1 },
    }),
  },
  popCatIcon: {
    width: 56, height: 56, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
  },
  popCatTitle: { fontSize: 13, fontWeight: "900", color: colors.textMain, textAlign: "center" },
  popCatSub: { fontSize: 11, color: colors.textMuted, fontWeight: "600" },

  // Misc
  loadingRow: { paddingVertical: 24, alignItems: "center" },
  emptyText: { fontSize: 12.5, color: colors.textMuted, paddingHorizontal: 16, paddingVertical: 12 },
});
