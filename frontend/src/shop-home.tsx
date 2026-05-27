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
  Modal, Pressable,
} from "react-native";
import * as Location from "expo-location";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useFocusEffect, useRouter } from "expo-router";
import { Feather, MaterialCommunityIcons, MaterialIcons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { api, formatApiError } from "./api";
import { colors } from "./theme";
import { ShopLayoutRenderer } from "./shop-layout-renderer";
import { getCurrentCoords } from "./location";
import { LocationBanner } from "./location-banner";

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

// Hardcoded category circles per spec — used as fallback when the
// admin-managed /api/shop-categories endpoint is unreachable. In normal
// operation the strip is populated by the API (with the "More" pill always
// appended as a UI control to open the full-list modal).
type CatIconPack = "feather" | "mci" | "mat";
const FALLBACK_CATEGORIES: {
  key: string; label: string;
  icon: string; pack: CatIconPack; color: string;
}[] = [
  { key: "all",         label: "All",         icon: "grid-view",     pack: "mat",     color: "#E5F2EC" },
  { key: "Sarees",      label: "Sarees",      icon: "hanger",        pack: "mci",     color: "#FCE7F3" },
  { key: "Men",         label: "Men",         icon: "human-male",    pack: "mci",     color: "#DBEAFE" },
  { key: "Women",       label: "Women",       icon: "human-female",  pack: "mci",     color: "#FDE68A" },
  { key: "Electronics", label: "Electronics", icon: "tv",            pack: "mci",     color: "#E0E7FF" },
  { key: "Home",        label: "Home",        icon: "sofa",          pack: "mci",     color: "#FFEDD5" },
  { key: "Beauty",      label: "Beauty",      icon: "lipstick",      pack: "mci",     color: "#FCE7F3" },
];

// Shape returned by /api/shop-categories
type ApiCategory = {
  id: string;
  name: string;
  slug: string;
  icon_pack: CatIconPack;
  icon_name: string;
  image_url: string | null;
  color: string;
  sort_order: number;
  active: boolean;
};

// Tiny helper to render whichever icon pack a category requests.
function CatIcon({ icon, pack, size, color }: { icon: string; pack: CatIconPack; size: number; color: string }) {
  if (pack === "mci") return <MaterialCommunityIcons name={icon as any} size={size} color={color} />;
  if (pack === "mat") return <MaterialIcons name={icon as any} size={size} color={color} />;
  return <Feather name={icon as any} size={size} color={color} />;
}

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
  deliveryAddress: defaultAddress = "Set your location",
  categoryRoutePrefix = "",
}: {
  cartCount?: number;
  wishlistCount?: number;
  deliveryAddress?: string;
  /**
   * Optional prefix for category navigation. When ShopHome is embedded
   * inside the admin tabs (admin/shop.tsx), pass "/admin" so tapping a
   * category card pushes /admin/shop-category/<name> (keeping the admin
   * bottom-tab bar). User-side leaves this empty so it pushes
   * /shop-category/<name> inside the (tabs) group.
   */
  categoryRoutePrefix?: string;
}) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();

  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [searchSubmitted, setSearchSubmitted] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [bannerIdx, setBannerIdx] = useState(0);
  // "More" tap opens an all-categories sheet
  const [allCatModalOpen, setAllCatModalOpen] = useState(false);
  // Admin-managed shop categories (fetched from /api/shop-categories).
  // Falls back to a hardcoded short list if the API fails.
  const [apiCategories, setApiCategories] = useState<ApiCategory[] | null>(null);

  // ── Delivery address (live reverse-geocoded from user coords) ─────────
  const [deliveryAddress, setDeliveryAddress] = useState<string>(defaultAddress);
  const [locModalOpen, setLocModalOpen] = useState(false);
  const [locBusy, setLocBusy] = useState(false);
  const [manualAddress, setManualAddress] = useState<string>("");

  // Persisted cache key — survives reloads / logout-login on the same device.
  const ADDR_KEY = "@app/deliveryAddress";

  // Hydrate cached address on mount, then try to refresh from current GPS.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cached = await AsyncStorage.getItem(ADDR_KEY);
        if (cached && !cancelled) setDeliveryAddress(cached);
      } catch { /* ignore */ }
      // Fire-and-forget refresh from current location.
      refreshLocation(false);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persistAddress = useCallback(async (a: string) => {
    try { await AsyncStorage.setItem(ADDR_KEY, a); } catch { /* ignore */ }
  }, []);

  /**
   * Best-effort reverse-geocode of the current device location.
   * `silent=true` means "don't show errors — use cache if anything fails".
   * On web, `Location.reverseGeocodeAsync` isn't supported so we fall back
   * to plain "City near {lat},{lng}".
   */
  const refreshLocation = useCallback(async (interactive: boolean) => {
    setLocBusy(true);
    try {
      const c = await getCurrentCoords();
      if (!c) {
        if (interactive) alert("Couldn't read your GPS. Please check location permission in your device settings.");
        return;
      }
      let nice = "";
      if (Platform.OS !== "web") {
        try {
          const places = await Location.reverseGeocodeAsync({ latitude: c.lat, longitude: c.lng });
          if (places && places[0]) {
            const p = places[0];
            const city = p.city || p.subregion || p.district || "";
            const region = p.region || p.country || "";
            nice = [city, region].filter(Boolean).join(", ");
          }
        } catch { /* fall through */ }
      }
      if (!nice) nice = `Near ${c.lat.toFixed(2)}, ${c.lng.toFixed(2)}`;
      setDeliveryAddress(nice);
      persistAddress(nice);
    } finally { setLocBusy(false); }
  }, [persistAddress]);

  const onSaveManualAddress = useCallback(() => {
    const v = manualAddress.trim();
    if (!v) return;
    setDeliveryAddress(v);
    persistAddress(v);
    setLocModalOpen(false);
    setManualAddress("");
  }, [manualAddress, persistAddress]);

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

  // Admin-managed categories — fetched in parallel with products. Falls
  // back to FALLBACK_CATEGORIES on any error so the strip is never empty.
  const loadCategories = useCallback(async () => {
    try {
      const r = await api.get<{ items: ApiCategory[] }>("/shop-categories");
      const items = (r.data?.items || []).filter((c) => c.active !== false);
      items.sort((a, b) => (a.sort_order - b.sort_order) || a.name.localeCompare(b.name));
      setApiCategories(items);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("ShopHome /shop-categories failed:", formatApiError(e));
      setApiCategories(null);
    }
  }, []);

  useEffect(() => { load(); loadCategories(); }, [load, loadCategories]);
  // Reload categories whenever the shop home regains focus so admin
  // changes (icon swap, rename, new category) show up immediately
  // when the admin pops back from /admin/shop-categories.
  useFocusEffect(useCallback(() => { loadCategories(); }, [loadCategories]));

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
          <TouchableOpacity
            style={styles.deliveryBlock}
            activeOpacity={0.7}
            onPress={() => setLocModalOpen(true)}
            testID="home-delivery-btn"
          >
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

        {/* 2. SEARCH BAR — full width with search button on the right.
            Submitting (keyboard return OR tapping the green button) flips
            `searchSubmitted=true` and the screen swaps to a dedicated
            search-results grid below. Clearing the input resets it. */}
        <View style={styles.searchRow}>
          <View style={styles.searchBox}>
            {searchSubmitted ? (
              <TouchableOpacity
                onPress={() => { setSearch(""); setSearchSubmitted(false); }}
                hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
              >
                <Feather name="arrow-left" size={16} color={colors.textMain} />
              </TouchableOpacity>
            ) : (
              <Feather name="search" size={15} color={colors.textMuted} />
            )}
            <TextInput
              value={search}
              onChangeText={(t) => {
                setSearch(t);
                if (!t.trim()) setSearchSubmitted(false);
              }}
              onSubmitEditing={() => { if (search.trim()) setSearchSubmitted(true); }}
              placeholder="Search for sarees, mobiles, more…"
              placeholderTextColor={colors.textMuted}
              returnKeyType="search"
              style={styles.searchInput}
              testID="home-search-input"
            />
            {search.length > 0 ? (
              <TouchableOpacity
                onPress={() => { setSearch(""); setSearchSubmitted(false); }}
                hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
              >
                <Feather name="x-circle" size={16} color={colors.textMuted} />
              </TouchableOpacity>
            ) : null}
          </View>
          <TouchableOpacity
            style={styles.searchBtn}
            onPress={() => { if (search.trim()) setSearchSubmitted(true); }}
            disabled={!search.trim()}
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
        <LocationBanner />
        {searchSubmitted && search.trim() ? (
          // ── SEARCH RESULTS VIEW ─────────────────────────────────────
          <View style={{ paddingHorizontal: 16, paddingTop: 16 }}>
            <View style={styles.searchResultHeader}>
              <Text style={styles.searchResultTitle}>
                Results for "<Text style={{ color: colors.primary }}>{search.trim()}</Text>"
              </Text>
              <Text style={styles.searchResultCount}>{filteredProducts.length} product{filteredProducts.length === 1 ? "" : "s"}</Text>
            </View>
            {loading ? (
              <View style={styles.loadingRow}><ActivityIndicator color={colors.primary} /></View>
            ) : filteredProducts.length === 0 ? (
              <View style={styles.emptyResultsWrap}>
                <View style={[styles.iconRound, { backgroundColor: colors.brand100 }]}>
                  <Feather name="search" size={28} color={colors.primary} />
                </View>
                <Text style={styles.emptyResultsTitle}>No results found</Text>
                <Text style={styles.emptyResultsSub}>
                  We couldn't find anything matching "{search.trim()}".
                  Try a different keyword or browse the categories above.
                </Text>
                <TouchableOpacity
                  style={styles.bannerCta}
                  onPress={() => { setSearch(""); setSearchSubmitted(false); }}
                >
                  <Text style={[styles.bannerCtaText, { color: colors.primary }]}>Back to home</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <FlatList
                data={filteredProducts}
                keyExtractor={(p) => `result-${p.id}`}
                numColumns={2}
                scrollEnabled={false}
                columnWrapperStyle={{ gap: 12, marginBottom: 12 }}
                renderItem={({ item }) => (
                  <View style={{ flex: 1 }}>
                    <ProductCard p={item} />
                  </View>
                )}
              />
            )}
          </View>
        ) : (
          // ── DEFAULT HOME VIEW ───────────────────────────────────────
          <>
        {/* 3. HORIZONTAL CATEGORY SCROLL — circular icons. Data comes from
            /api/shop-categories (admin-managed). The first chip is always
            "All" (resets filter); the last is always "More" which opens
            the full-list modal. Strip is capped at 6 admin categories so
            "More" stays visible — the full list is in the modal. */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.catScroll}
        >
          {/* Always-visible "All" pill (resets filter) */}
          <TouchableOpacity
            key="all"
            style={styles.catItem}
            onPress={() => setActiveCategory("all")}
            activeOpacity={0.75}
            testID="home-cat-all"
          >
            <View style={[
              styles.catCircle,
              { backgroundColor: "#E5F2EC" },
              activeCategory === "all" && styles.catCircleActive,
            ]}>
              <MaterialIcons name="grid-view" size={22} color={activeCategory === "all" ? colors.primaryFg : colors.textMain} />
            </View>
            <Text style={[styles.catLabel, activeCategory === "all" && { color: colors.primary, fontWeight: "800" }]}>All</Text>
          </TouchableOpacity>

          {/* Admin categories (max 6 in the strip — rest live in the More modal) */}
          {(apiCategories || FALLBACK_CATEGORIES.filter((c) => c.key !== "all")).slice(0, 6).map((c: any) => {
            const key = c.id ? c.name : c.key;
            const label = c.name || c.label || "";
            const pack: CatIconPack = c.icon_pack || c.pack || "feather";
            const iconName = c.icon_name || c.icon || "shopping-bag";
            const color = c.color || "#E5F2EC";
            const imageUrl = c.image_url || null;
            const active = activeCategory === key;
            return (
              <TouchableOpacity
                key={c.id || key}
                style={styles.catItem}
                onPress={() => setActiveCategory(key)}
                activeOpacity={0.75}
                testID={`home-cat-${key}`}
              >
                <View style={[styles.catCircle, { backgroundColor: color }, active && styles.catCircleActive]}>
                  {imageUrl ? (
                    <Image source={{ uri: imageUrl }} style={styles.catCircleImg} />
                  ) : (
                    <CatIcon icon={iconName} pack={pack} size={22} color={active ? colors.primaryFg : colors.textMain} />
                  )}
                </View>
                <Text style={[styles.catLabel, active && { color: colors.primary, fontWeight: "800" }]} numberOfLines={1}>{label}</Text>
              </TouchableOpacity>
            );
          })}

          {/* Always-visible "More" pill (opens the full grid modal) */}
          <TouchableOpacity
            key="more"
            style={styles.catItem}
            onPress={() => setAllCatModalOpen(true)}
            activeOpacity={0.75}
            testID="home-cat-More"
          >
            <View style={[styles.catCircle, { backgroundColor: "#F3F4F6" }]}>
              <MaterialCommunityIcons name="dots-grid" size={22} color={colors.textMain} />
            </View>
            <Text style={styles.catLabel}>More</Text>
          </TouchableOpacity>
        </ScrollView>

        {/* When the user taps any category in the strip above (e.g. "Electronics",
            "Fashion", "House Accessories"), we show a clean filtered product grid
            INSIDE this same screen — instead of the admin layout blocks below.
            This delivers the marketplace-app behaviour users expect: tap chip →
            products appear instantly, no need to first tap "All" or drill into a
            new screen. The category strip stays pinned at top so the user can
            switch between categories smoothly. */}
        {activeCategory && activeCategory !== "all" ? (
          <View style={{ paddingHorizontal: 16, paddingTop: 16 }}>
            <View style={styles.searchResultHeader}>
              <Text style={styles.searchResultTitle}>
                <Text style={{ color: colors.primary }}>{activeCategory}</Text>
              </Text>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={styles.searchResultCount}>
                  {filteredProducts.length} product{filteredProducts.length === 1 ? "" : "s"}
                </Text>
                <TouchableOpacity
                  onPress={() => setActiveCategory("all")}
                  hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                  testID="home-cat-clear"
                >
                  <Feather name="x-circle" size={18} color={colors.textMuted} />
                </TouchableOpacity>
              </View>
            </View>

            {loading ? (
              // Skeleton: 6 placeholder cards that match the real grid shape,
              // so the layout doesn't pop when products arrive.
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <View key={`sk-${i}`} style={styles.skelCard}>
                    <View style={styles.skelImage} />
                    <View style={styles.skelLineLong} />
                    <View style={styles.skelLineShort} />
                  </View>
                ))}
              </View>
            ) : filteredProducts.length === 0 ? (
              <View style={styles.emptyResultsWrap}>
                <View style={[styles.iconRound, { backgroundColor: colors.brand100 }]}>
                  <Feather name="package" size={28} color={colors.primary} />
                </View>
                <Text style={styles.emptyResultsTitle}>No products in {activeCategory}</Text>
                <Text style={styles.emptyResultsSub}>
                  This category doesn't have anything listed yet. Browse other categories or check back soon.
                </Text>
                <TouchableOpacity style={styles.bannerCta} onPress={() => setActiveCategory("all")}>
                  <Text style={[styles.bannerCtaText, { color: colors.primary }]}>Show all categories</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <FlatList
                data={filteredProducts}
                keyExtractor={(p) => `cat-${p.id}`}
                numColumns={2}
                scrollEnabled={false}
                columnWrapperStyle={{ gap: 12, marginBottom: 12 }}
                renderItem={({ item }) => (
                  <View style={{ flex: 1 }}>
                    <ProductCard p={item} />
                  </View>
                )}
              />
            )}
          </View>
        ) : (
        <ShopLayoutRenderer
          scope="home"
          category={activeCategory && activeCategory !== "all" ? activeCategory : undefined}
          onProductPress={(id) => router.push(`/product/${id}` as any)}
          onCategoryPress={(c) => {
            if (!c) router.push(`${categoryRoutePrefix}/shop` as any);
            else router.push(`${categoryRoutePrefix}/shop-category/${encodeURIComponent(c)}` as any);
          }}
          onAddToCart={async (id) => {
            try {
              await api.post("/cart", { product_id: id, quantity: 1 });
            } catch (e) { /* eslint-disable-next-line no-console */ console.warn("add to cart failed:", formatApiError(e)); }
          }}
        />
        )}
          </>
        )}
      </ScrollView>

      {/* ── Delivery-location picker modal ─────────────────────────────
          Opens when the user taps the "Deliver to {city}" pill in the
          header. Offers two paths:
            1. Auto-detect via device GPS + reverse geocoding
            2. Manual text entry (saved to AsyncStorage)
          Selected address is persisted locally so it survives reloads. */}
      <Modal
        visible={locModalOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setLocModalOpen(false)}
      >
        <Pressable style={styles.modalScrim} onPress={() => setLocModalOpen(false)}>
          <Pressable style={styles.modalSheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.modalGrabber} />
            <View style={styles.modalHeader}>
              <Feather name="map-pin" size={18} color={colors.primary} />
              <Text style={styles.modalTitle}>Set delivery location</Text>
            </View>
            <Text style={styles.modalCurrent} numberOfLines={2}>
              Current: <Text style={{ fontWeight: "900", color: colors.textMain }}>{deliveryAddress}</Text>
            </Text>

            <TouchableOpacity
              onPress={() => refreshLocation(true)}
              disabled={locBusy}
              style={[styles.modalPrimary, locBusy && { opacity: 0.7 }]}
              testID="home-loc-use-current"
            >
              {locBusy ? (
                <ActivityIndicator color={colors.primaryFg} />
              ) : (
                <>
                  <Feather name="navigation" size={15} color={colors.primaryFg} />
                  <Text style={styles.modalPrimaryText}>Use my current location</Text>
                </>
              )}
            </TouchableOpacity>

            <View style={styles.modalDividerRow}>
              <View style={styles.modalDividerLine} />
              <Text style={styles.modalDividerText}>OR ENTER MANUALLY</Text>
              <View style={styles.modalDividerLine} />
            </View>

            <View style={styles.modalInputRow}>
              <TextInput
                value={manualAddress}
                onChangeText={setManualAddress}
                placeholder="e.g. Andheri West, Mumbai"
                placeholderTextColor={colors.textMuted}
                style={styles.modalInput}
                returnKeyType="done"
                onSubmitEditing={onSaveManualAddress}
                testID="home-loc-manual-input"
              />
              <TouchableOpacity
                onPress={onSaveManualAddress}
                style={[styles.modalSaveBtn, !manualAddress.trim() && { opacity: 0.4 }]}
                disabled={!manualAddress.trim()}
                testID="home-loc-save"
              >
                <Feather name="check" size={16} color={colors.primaryFg} />
              </TouchableOpacity>
            </View>

            <TouchableOpacity
              onPress={() => setLocModalOpen(false)}
              style={styles.modalClose}
            >
              <Text style={styles.modalCloseText}>Close</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>

      {/* ── All-Categories picker modal ─────────────────────────────────
          Opens when the user taps the "More" circle in the horizontal
          category strip. Shows every category in a 3-column grid with
          a colourful icon tile. Tap one to filter the home view; the
          modal closes automatically and the active filter is shown
          in the strip. Tap the scrim to dismiss. */}
      <Modal
        visible={allCatModalOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setAllCatModalOpen(false)}
      >
        <Pressable style={styles.modalScrim} onPress={() => setAllCatModalOpen(false)}>
          <Pressable
            style={[styles.modalSheet, { maxHeight: "85%" }]}
            onPress={(e) => e.stopPropagation()}
          >
            <View style={styles.modalGrabber} />
            <View style={styles.modalHeader}>
              <MaterialCommunityIcons name="view-grid" size={18} color={colors.primary} />
              <Text style={styles.modalTitle}>All categories</Text>
            </View>
            <Text style={styles.modalCurrent}>
              Pick a category to explore — we'll show products tailored just for it.
            </Text>

            <ScrollView
              showsVerticalScrollIndicator={false}
              contentContainerStyle={styles.allCatGrid}
            >
              {/* "All products" row at the top */}
              <TouchableOpacity
                style={[styles.allCatItem, activeCategory === "all" && styles.allCatItemActive]}
                onPress={() => {
                  setActiveCategory("all");
                  setAllCatModalOpen(false);
                }}
                activeOpacity={0.75}
                testID="all-cat-all"
              >
                <View style={[styles.allCatIconCircle, { backgroundColor: "#E5F2EC" }]}>
                  <MaterialIcons name="grid-view" size={24} color={colors.primary} />
                </View>
                <Text style={styles.allCatLabel} numberOfLines={1}>All</Text>
              </TouchableOpacity>

              {(apiCategories || FALLBACK_CATEGORIES.filter((c) => c.key !== "all").map((c) => ({
                id: c.key,
                name: c.label,
                slug: c.key.toLowerCase(),
                icon_pack: c.pack,
                icon_name: c.icon,
                image_url: null,
                color: c.color,
                sort_order: 0,
                active: true,
              } as ApiCategory))).map((c) => {
                const active = activeCategory === c.name;
                return (
                  <TouchableOpacity
                    key={`all-${c.id}`}
                    style={[styles.allCatItem, active && styles.allCatItemActive]}
                    onPress={() => {
                      setActiveCategory(c.name);
                      setAllCatModalOpen(false);
                      router.push(`${categoryRoutePrefix}/shop-category/${encodeURIComponent(c.name)}` as any);
                    }}
                    activeOpacity={0.75}
                    testID={`all-cat-${c.slug}`}
                  >
                    <View style={[styles.allCatIconCircle, { backgroundColor: c.color }]}>
                      {c.image_url ? (
                        <Image source={{ uri: c.image_url }} style={styles.allCatIconImg} />
                      ) : (
                        <CatIcon icon={c.icon_name} pack={c.icon_pack as CatIconPack} size={24} color={colors.textMain} />
                      )}
                    </View>
                    <Text style={styles.allCatLabel} numberOfLines={1}>{c.name}</Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            <TouchableOpacity
              onPress={() => setAllCatModalOpen(false)}
              style={styles.modalClose}
            >
              <Text style={styles.modalCloseText}>Close</Text>
            </TouchableOpacity>
          </Pressable>
        </Pressable>
      </Modal>
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
  catCircleImg: { width: 56, height: 56, borderRadius: 28 },
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

  // Search results view
  searchResultHeader: {
    flexDirection: "row", alignItems: "baseline", justifyContent: "space-between",
    marginBottom: 12,
  },
  searchResultTitle: { fontSize: 15, fontWeight: "900", color: colors.textMain, flexShrink: 1 },
  searchResultCount: { fontSize: 11.5, color: colors.textMuted, fontWeight: "700" },
  emptyResultsWrap: {
    alignItems: "center", paddingVertical: 36, gap: 12,
  },
  iconRound: {
    width: 76, height: 76, borderRadius: 38,
    alignItems: "center", justifyContent: "center",
  },
  emptyResultsTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  emptyResultsSub: {
    fontSize: 13, color: colors.textMuted, textAlign: "center",
    lineHeight: 18, maxWidth: 280,
  },

  // ── Category-filter skeleton placeholders (shown while products load
  //    after a category tap). Match the ProductCard footprint so the grid
  //    doesn't jump when real data swaps in.
  skelCard: {
    width: "48%",
    backgroundColor: colors.surface,
    borderRadius: 14,
    padding: 10,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  skelImage: {
    width: "100%",
    height: 130,
    backgroundColor: colors.surfaceMuted,
    borderRadius: 10,
    marginBottom: 8,
  },
  skelLineLong: {
    height: 11,
    width: "85%",
    backgroundColor: colors.surfaceMuted,
    borderRadius: 4,
    marginBottom: 6,
  },
  skelLineShort: {
    height: 11,
    width: "55%",
    backgroundColor: colors.surfaceMuted,
    borderRadius: 4,
  },

  // ── Delivery-location picker modal ─────────────────────────────────
  modalScrim: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "flex-end",
  },
  modalSheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: 18, paddingTop: 8, paddingBottom: 28,
    gap: 14,
  },
  modalGrabber: {
    alignSelf: "center", width: 38, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginBottom: 4,
  },
  modalHeader: { flexDirection: "row", alignItems: "center", gap: 8 },
  modalTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  modalCurrent: { fontSize: 12.5, color: colors.textMuted, lineHeight: 17 },
  modalPrimary: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary,
    paddingVertical: 13, paddingHorizontal: 18,
    borderRadius: 14,
  },
  modalPrimaryText: { color: colors.primaryFg, fontWeight: "900", fontSize: 13.5, letterSpacing: 0.2 },
  modalDividerRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  modalDividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  modalDividerText: { fontSize: 10, fontWeight: "900", color: colors.textMuted, letterSpacing: 1 },
  modalInputRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  modalInput: {
    flex: 1, minWidth: 0,
    height: 46, paddingHorizontal: 14, fontSize: 13.5,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, borderRadius: 14,
    color: colors.textMain, fontWeight: "500",
  },
  modalSaveBtn: {
    width: 46, height: 46, borderRadius: 14,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  modalClose: { alignItems: "center", paddingVertical: 6 },
  modalCloseText: { color: colors.textMuted, fontSize: 12.5, fontWeight: "700" },

  // ── All-Categories grid (in the "More" modal) ─────────────────────
  // 3-column responsive grid with `flexBasis: "31%"` so the tiles wrap
  // cleanly on phones of every width. The gap is achieved with row +
  // margin since gap on FlexWrap isn't supported on every RN version.
  allCatGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    paddingVertical: 6,
    rowGap: 12,
  },
  allCatItem: {
    flexBasis: "31%",
    alignItems: "center",
    paddingVertical: 8,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "transparent",
  },
  allCatItemActive: {
    borderColor: colors.primary,
    backgroundColor: colors.brand100,
  },
  allCatIconCircle: {
    width: 54, height: 54, borderRadius: 27,
    alignItems: "center", justifyContent: "center",
    marginBottom: 6,
    overflow: "hidden",
  },
  allCatIconImg: { width: 54, height: 54, borderRadius: 27 },
  allCatLabel: {
    fontSize: 11.5,
    fontWeight: "800",
    color: colors.textMain,
    textAlign: "center",
    paddingHorizontal: 4,
  },
});
