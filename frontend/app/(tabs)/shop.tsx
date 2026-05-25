import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Image,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  Alert,
  TextInput,
  Modal,
  Linking,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter, usePathname } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { ShopLayoutRenderer } from "../../src/shop-layout-renderer";
import { ShopHome } from "../../src/shop-home";
import { getCurrentCoords, formatDistance, formatActiveAgo } from "../../src/location";
import { useDoubleTapExit } from "../../src/use-double-tap-exit";

type Product = {
  id: string;
  name: string;
  price: number;
  image_url: string;
  description?: string;
  category?: string;
  stock?: number;
  is_in_stock?: boolean;
  interested_count?: number;
};
type ServiceCategory = {
  id: string;
  name: string;
  slug: string;
  icon: string;
  color: string;
  sort_order: number;
  active: boolean;
  provider_count: number;
};
type ServiceProvider = {
  id: string;
  name: string;
  phone?: string;
  email: string;
  referral_code: string;
  service_name: string;
  service_category: string;
  category_id?: string | null;
  service_languages?: string[];
  service_pincode: string;
  service_charge: number;
  service_description?: string;
  distance_km?: number | null;
  is_active?: boolean;
  location_updated_at?: string | null;
};
type Mode = "shop" | "services";

const LANG_LABELS: Record<string, string> = { en: "English", te: "Telugu", hi: "Hindi", ta: "Tamil" };
const LANG_ORDER = ["en", "te", "hi", "ta"];

export default function ShopScreen() {
  const router = useRouter();
  // Shop is the user's landing tab — apply double-tap-back-to-exit pattern
  // so hardware back at the root doesn't immediately close the app.
  useDoubleTapExit();
  // Detect which tab we're rendering for. Both /shop and /services route to
  // this same component (services.tsx re-exports the default). Pathname tells
  // us which mode to lock — this also hides the Shop/Services toggle pills.
  const pathname = usePathname();
  const lockedMode: Mode = pathname && pathname.includes("/services") ? "services" : "shop";
  const [mode, setMode] = useState<Mode>(lockedMode);
  // Keep mode synced if the tab changes while screen is mounted (rare, but safe)
  useEffect(() => { setMode(lockedMode); }, [lockedMode]);

  // ---- Shop state ----
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [cartCount, setCartCount] = useState(0);
  // New: search + category filter + remembered interest registrations
  const [shopSearch, setShopSearch] = useState("");
  const [shopCategory, setShopCategory] = useState<string | null>(null); // null = "All"
  const [interestedSet, setInterestedSet] = useState<Set<string>>(new Set());
  const [registeringInterest, setRegisteringInterest] = useState<string | null>(null);
  // Visual-only favourites (saved in-memory; persistence comes when wishlist
  // backend lands).
  const [favSet, setFavSet] = useState<Set<string>>(new Set());
  const toggleFav = useCallback((id: string) => {
    setFavSet((s) => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }, []);

  // ---- Services state ----
  const [services, setServices] = useState<ServiceProvider[]>([]);
  const [servicesLoading, setServicesLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [pincodeQ, setPincodeQ] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null); // null = "all"
  const [languageQ, setLanguageQ] = useState<string | null>(null);
  // Language picker modal (replaces inline chips per UX redesign)
  const [langModalOpen, setLangModalOpen] = useState(false);
  const [myCoords, setMyCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [categories, setCategories] = useState<ServiceCategory[]>([]);
  const [myStatus, setMyStatus] = useState<string | null>(null);
  const [contactOf, setContactOf] = useState<ServiceProvider | null>(null);
  const [bookingId, setBookingId] = useState<string | null>(null);

  const loadShop = useCallback(async () => {
    try {
      // Backend returns a raw array; older code expected `{items: [...]}`. Handle both.
      const { data } = await api.get<any>("/products");
      const list: Product[] = Array.isArray(data) ? data : (data?.items || []);
      setItems(list);
      try {
        const cart = await api.get<any>("/cart");
        const cItems = Array.isArray(cart.data) ? cart.data : (cart.data?.items || []);
        setCartCount(cItems.reduce((s: number, i: any) => s + (i.qty || i.quantity || 0), 0));
      } catch { /* cart may 401 for guests */ }
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Register interest in an out-of-stock product so vendor knows demand exists.
  const registerInterest = useCallback(async (p: Product) => {
    if (interestedSet.has(p.id) || registeringInterest === p.id) return;
    setRegisteringInterest(p.id);
    try {
      const { data } = await api.post<{ ok: boolean; interested_count: number; already_registered: boolean }>(
        `/products/${p.id}/interested`,
      );
      setInterestedSet((s) => new Set([...Array.from(s), p.id]));
      // Update local count immediately so user sees the bump
      setItems((prev) => prev.map((it) => (it.id === p.id ? { ...it, interested_count: data.interested_count } : it)));
      if (!data.already_registered) {
        Alert.alert(
          "We hear you!",
          `Thanks — ${data.interested_count} customer${data.interested_count === 1 ? "" : "s"} now interested. We've notified the seller to restock.`,
        );
      }
    } catch (e) {
      Alert.alert("Couldn't register", formatApiError(e));
    } finally {
      setRegisteringInterest(null);
    }
  }, [interestedSet, registeringInterest]);

  const loadServices = useCallback(async () => {
    setServicesLoading(true);
    try {
      const params: Record<string, string> = {};
      if (searchQ) params.q = searchQ;
      if (pincodeQ) params.pincode = pincodeQ;
      if (categoryId) params.category_id = categoryId;
      if (languageQ) params.language = languageQ;
      if (myCoords) {
        params.lat = String(myCoords.lat);
        params.lng = String(myCoords.lng);
      }
      const { data } = await api.get<{ items: ServiceProvider[] }>("/services", { params });
      setServices(data.items || []);
      const cats = await api.get<{ categories: ServiceCategory[] }>("/services/categories");
      setCategories(cats.data.categories || []);
      const mine = await api.get<{ service_status: string | null }>("/service/me");
      setMyStatus(mine.data.service_status || null);
    } catch (e) {
      console.warn(e);
    } finally {
      setServicesLoading(false);
      // Also clear the pull-to-refresh spinner — earlier versions only
      // toggled `servicesLoading`, leaving the RefreshControl stuck.
      setRefreshing(false);
    }
  }, [searchQ, pincodeQ, categoryId, languageQ, myCoords]);

  const useMyLocation = useCallback(async () => {
    if (myCoords) {
      // toggle off
      setMyCoords(null);
      return;
    }
    setLocating(true);
    try {
      const c = await getCurrentCoords();
      if (!c) {
        Alert.alert(
          "Location unavailable",
          Platform.OS === "web"
            ? "Your browser blocked location access. Allow it in the address-bar lock icon and try again."
            : "Permission denied or GPS off. Enable Location Services and try again.",
        );
        return;
      }
      setMyCoords({ lat: c.lat, lng: c.lng });
    } finally {
      setLocating(false);
    }
  }, [myCoords]);

  useFocusEffect(useCallback(() => {
    if (mode === "shop") loadShop();
    else loadServices();
  }, [mode, loadShop, loadServices]));

  // Phase E: Real-time-ish stock sync — poll the shop list every 30s while the
  // tab is focused so vendor stock changes appear without the customer having
  // to manually refresh. Stops when the user switches away from the Shop tab
  // or the screen unmounts.
  useFocusEffect(useCallback(() => {
    if (mode !== "shop") return;
    const id = setInterval(() => { loadShop(); }, 30000);
    return () => clearInterval(id);
  }, [mode, loadShop]));

  useEffect(() => {
    if (mode === "services") {
      const t = setTimeout(loadServices, 300);
      return () => clearTimeout(t);
    }
  }, [searchQ, pincodeQ, categoryId, languageQ, myCoords, mode, loadServices]);

  const addToCart = async (p: Product) => {
    setAdding(p.id);
    try {
      await api.post("/cart/add", { product_id: p.id, qty: 1 });
      setCartCount((c) => c + 1);
    } catch (e) {
      Alert.alert("Could not add", formatApiError(e));
    } finally {
      setAdding(null);
    }
  };

  const bookService = async (provider: ServiceProvider) => {
    Alert.alert(
      `Book ${provider.service_name}?`,
      `${provider.name} • ₹${provider.service_charge} will be deducted from your wallet.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Book now",
          onPress: async () => {
            setBookingId(provider.id);
            try {
              await api.post(`/services/${provider.id}/book`, { notes: null });
              Alert.alert("Booked", `Your booking is confirmed. ${provider.name} has been notified.`);
              setContactOf(null);
            } catch (e) {
              Alert.alert("Booking failed", formatApiError(e));
            } finally {
              setBookingId(null);
            }
          },
        },
      ],
    );
  };

  const callOrCopy = (phone?: string) => {
    if (!phone) return;
    const url = `tel:${phone}`;
    Linking.openURL(url).catch(() => Alert.alert("Phone", phone));
  };

  if (loading && mode === "shop") {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  // ============ Shop Home Screen (redesigned 2026-06) ============
  // Per user spec: a complete UI redesign of the Shop tab only. Services
  // mode below is untouched. This branch short-circuits the legacy
  // shop-mode rendering and delegates to the dedicated <ShopHome />
  // component which contains its own header, search, banner & sections.
  if (mode === "shop") {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <ShopHome
          cartCount={cartCount}
          wishlistCount={0}
        />
      </SafeAreaView>
    );
  }

  // ============ Render (services mode — unchanged) ============
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); mode === "shop" ? loadShop() : loadServices(); }}
          />
        }
        keyboardShouldPersistTaps="handled"
        stickyHeaderIndices={[0]}
      >
        {/* Top header — refactored 2026-06 per user bug report.
            Previous implementation used position:absolute on the cart which
            overflowed off-screen on certain Android devices (see screenshot).
            Now uses a clean flex row, exactly per spec:
              <Row flexDirection=row width=100% paddingHorizontal=16>
                <SearchBox flex:1 minWidth:0 height:52 />
                <CartButton width:52 height:52 marginLeft:12 />
              </Row>
            `minWidth: 0` on the flex child is the critical fix that prevents
            wrapping on Android — without it RN never lets the search bar
            shrink below its intrinsic content width. */}
        <View style={styles.topHeader}>
          {mode === "shop" ? (
            <>
              <View style={styles.shopSearch}>
                <Feather name="search" size={16} color={colors.textMuted} />
                <TextInput
                  style={styles.shopSearchInput}
                  placeholder="Search for products"
                  placeholderTextColor={colors.textMuted}
                  value={shopSearch}
                  onChangeText={setShopSearch}
                  returnKeyType="search"
                />
                {shopSearch.length > 0 ? (
                  <TouchableOpacity onPress={() => setShopSearch("")}>
                    <Feather name="x-circle" size={18} color={colors.textMuted} />
                  </TouchableOpacity>
                ) : null}
              </View>
              <TouchableOpacity
                onPress={() => router.push("/cart")}
                style={styles.cartIconBtn}
                testID="shop-cart-btn"
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              >
                <Feather name="shopping-cart" size={22} color={colors.primaryFg} />
                {cartCount > 0 && (
                  <View style={styles.cartBadgeTop}>
                    <Text style={styles.cartBadgeTopText}>{cartCount > 9 ? "9+" : cartCount}</Text>
                  </View>
                )}
              </TouchableOpacity>
            </>
          ) : (
            <>
              <View style={styles.servicesTitleWrap}>
                <Text style={styles.topHeaderEyebrow}>SERVICES</Text>
                <Text style={styles.topHeaderTitle}>Find local talent</Text>
              </View>
              {/* Language filter removed per user request — services list now
                  shows all providers sorted by nearest GPS distance. */}
            </>
          )}
        </View>

        {/* === SHOP === */}
        {mode === "shop" && (() => {
          // Build category list from the products we have
          const cats = Array.from(
            new Set(items.map((p) => (p.category || "").trim()).filter(Boolean)),
          );
          const q = shopSearch.trim().toLowerCase();
          const filtered = items.filter((p) => {
            if (shopCategory && (p.category || "") !== shopCategory) return false;
            if (q && !p.name.toLowerCase().includes(q) && !(p.description || "").toLowerCase().includes(q)) return false;
            return true;
          });
          const inStock = filtered.filter((p) => (p.is_in_stock ?? (p.stock || 0) > 0));
          const outStock = filtered.filter((p) => !(p.is_in_stock ?? (p.stock || 0) > 0));

          // Department tile colour palette (rotated)
          const deptColours = ["#E8F5E9", "#FFF3E0", "#E3F2FD", "#FCE4EC", "#F3E5F5", "#FFFDE7"];
          const deptIcons: Record<string, any> = {
            default: "shopping-bag",
            grocery: "shopping-cart",
            food: "coffee",
            electronics: "smartphone",
            fashion: "user",
            beauty: "heart",
            home: "home",
            kids: "gift",
            books: "book",
          };
          const iconFor = (c: string) => {
            const k = (c || "").toLowerCase();
            for (const key of Object.keys(deptIcons)) if (k.includes(key)) return deptIcons[key];
            return deptIcons.default;
          };
          const countFor = (c: string) => items.filter((p) => (p.category || "") === c).length;

          // Tiny deterministic mock rating from product id (for visual parity with
          // the reference; replace with real ratings when the backend lands).
          const mockRating = (id: string) => {
            let h = 0;
            for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
            return (4 + (h % 9) / 10).toFixed(1); // 4.0 → 4.8
          };

          const renderProductCard = (p: Product, opts: { oos?: boolean; lowStock?: boolean }) => {
            const isFav = favSet.has(p.id);
            return (
              <View key={p.id} style={[styles.cardNew, opts.oos && styles.cardOOS]} testID={`product-${p.id}`}>
                <View style={styles.cardImageWrap}>
                  <Image source={{ uri: p.image_url }} style={[styles.cardImageNew, opts.oos && { opacity: 0.5 }]} />
                  <TouchableOpacity
                    onPress={() => toggleFav(p.id)}
                    style={styles.heartBtn}
                    testID={`fav-${p.id}`}
                  >
                    <Feather name="heart" size={14} color={isFav ? "#E11D48" : colors.textMuted} />
                  </TouchableOpacity>
                  {opts.lowStock && !opts.oos && (
                    <View style={styles.lowStockPill}><Text style={styles.lowStockText}>Only {p.stock} left</Text></View>
                  )}
                  {opts.oos && (
                    <>
                      <View style={styles.oosOverlay} pointerEvents="none">
                        <Text style={styles.oosOverlayText}>SOLD OUT</Text>
                      </View>
                      {(p.interested_count || 0) > 0 && (
                        <View style={styles.interestBadge}>
                          <Feather name="users" size={10} color="#fff" />
                          <Text style={styles.interestBadgeText}>{p.interested_count}</Text>
                        </View>
                      )}
                    </>
                  )}
                </View>
                <View style={styles.cardBody}>
                  <View style={styles.ratingRow}>
                    <Feather name="star" size={11} color="#F59E0B" />
                    <Text style={styles.ratingText}>{mockRating(p.id)}</Text>
                    {p.category ? <Text style={styles.cardCategoryDot}> · {p.category}</Text> : null}
                  </View>
                  <Text style={styles.cardTitle} numberOfLines={2}>{p.name}</Text>
                  <View style={styles.cardFooterNew}>
                    <Text style={styles.cardPrice}>{formatINR(p.price)}</Text>
                    {/* Out-of-stock items keep the "Notify me" bell so customers
                        can register interest. In-stock items NO LONGER show an
                        Add-to-Cart pill at the bottom — the user reported the
                        pill cluttered the grid. Customers add to cart from the
                        product detail page (tap the card). */}
                    {opts.oos ? (
                      <TouchableOpacity
                        style={[
                          styles.cardCta,
                          { backgroundColor: interestedSet.has(p.id) ? colors.primary : "#F3F4F6" },
                          registeringInterest === p.id && { opacity: 0.6 },
                        ]}
                        onPress={() => registerInterest(p)}
                        disabled={interestedSet.has(p.id) || registeringInterest === p.id}
                        testID={`interest-${p.id}`}
                      >
                        {registeringInterest === p.id
                          ? <ActivityIndicator color={colors.primary} size="small" />
                          : <Feather
                              name={interestedSet.has(p.id) ? "check" : "bell"}
                              size={14}
                              color={interestedSet.has(p.id) ? colors.primaryFg : colors.primary}
                            />}
                      </TouchableOpacity>
                    ) : null}
                  </View>
                </View>
              </View>
            );
          };

          return (
            <>
              {/* Search bar moved to the sticky top header — no inline search here */}

              {/* Hero banner — the renderer's banner_slider block now owns the
                  swipeable carousel (replaces the legacy <PromoCarousel/>).
                  Admin curates slides via Admin → Store → Shop layout. */}

              {/* Admin-managed shop layout: 12 dynamic block types */}
              <ShopLayoutRenderer
                scope="home"
                onProductPress={(productId) => router.push(`/product/${productId}` as any)}
                onCategoryPress={(c) => router.push(`/shop-category/${encodeURIComponent(c)}` as any)}
                onAddToCart={(productId) => {
                  const p = items.find((x) => x.id === productId);
                  if (p) addToCart(p);
                }}
              />

              {/* Departments — tiled cards (matches reference image 2) */}
              {cats.length > 0 && (
                <View style={styles.shopSectionHeader}>
                  <Text style={styles.shopSectionTitle}>Departments</Text>
                  {shopCategory && (
                    <TouchableOpacity onPress={() => setShopCategory(null)}>
                      <Text style={styles.seeAllLink}>Clear filter</Text>
                    </TouchableOpacity>
                  )}
                </View>
              )}
              {cats.length > 0 && (
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={styles.deptRow}
                >
                  {cats.map((c, i) => {
                    const active = shopCategory === c;
                    return (
                      <TouchableOpacity
                        key={c}
                        style={[styles.deptTile, active && styles.deptTileActive]}
                        onPress={() => router.push(`/shop-category/${encodeURIComponent(c)}` as any)}
                        onLongPress={() => setShopCategory((cur) => (cur === c ? null : c))}
                        testID={`dept-${c}`}
                      >
                        <View style={[styles.deptIconCircle, { backgroundColor: deptColours[i % deptColours.length] }, active && { backgroundColor: colors.primary + "20" }]}>
                          <Feather name={iconFor(c) as any} size={20} color={active ? colors.primary : colors.textMain} />
                        </View>
                        <Text style={[styles.deptLabel, active && { color: colors.primary }]} numberOfLines={1}>{c}</Text>
                        <Text style={styles.deptCount}>{countFor(c)} item{countFor(c) === 1 ? "" : "s"}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </ScrollView>
              )}

              {/* Auto product grid removed — admin curates products via Shop Layout content boxes.
                  Vendor products are still managed in /admin/products and shown in their own dashboards. */}

              {cartCount > 0 && (
                <TouchableOpacity onPress={() => router.push("/cart")} style={styles.checkoutBar} testID="goto-cart">
                  <Feather name="shopping-cart" size={18} color={colors.accentFg} />
                  <Text style={styles.checkoutBarText}>{cartCount} item{cartCount > 1 ? "s" : ""} in cart</Text>
                  <Feather name="arrow-right" size={18} color={colors.accentFg} />
                </TouchableOpacity>
              )}
            </>
          );
        })()}

        {/* === SERVICES === */}
        {mode === "services" && (
          <>
            {/* Apply CTA banner removed — entry moved to Profile under "Become a Vendor" */}

            {/* Filters */}
            <View style={styles.filterRow}>
              <View style={styles.searchBox}>
                <Feather name="search" size={14} color={colors.textMuted} />
                <TextInput
                  style={styles.searchInput}
                  placeholder="Service or name"
                  placeholderTextColor={colors.textMuted}
                  value={searchQ}
                  onChangeText={setSearchQ}
                />
              </View>
              <View style={[styles.searchBox, { width: 100 }]}>
                <Feather name="map-pin" size={14} color={colors.textMuted} />
                <TextInput
                  style={styles.searchInput}
                  placeholder="Pincode"
                  placeholderTextColor={colors.textMuted}
                  value={pincodeQ}
                  onChangeText={setPincodeQ}
                  keyboardType="numeric"
                  maxLength={6}
                />
              </View>
            </View>
            <TouchableOpacity
              onPress={useMyLocation}
              disabled={locating}
              style={[styles.locBtn, myCoords && styles.locBtnActive]}
              testID="services-use-location"
            >
              {locating ? (
                <ActivityIndicator size="small" color={myCoords ? colors.primaryFg : colors.primary} />
              ) : (
                <Feather name={myCoords ? "navigation" : "navigation-2"} size={14} color={myCoords ? colors.primaryFg : colors.primary} />
              )}
              <Text style={[styles.locBtnText, myCoords && styles.locBtnTextActive]}>
                {myCoords ? "  Showing nearby workers (tap to clear)" : "  Use my location for nearby-first results"}
              </Text>
            </TouchableOpacity>

            {categories.length > 0 && (
              <View style={styles.categoryGridSection}>
                <View style={styles.sectionHeaderRow}>
                  <Text style={styles.sectionTitle}>Browse by category</Text>
                  {categoryId ? (
                    <TouchableOpacity onPress={() => setCategoryId(null)}>
                      <Text style={styles.clearLink}>Clear</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
                <View style={styles.categoryGrid}>
                  {categories.map((c) => {
                    const sel = categoryId === c.id;
                    return (
                      <TouchableOpacity
                        key={c.id}
                        style={[
                          styles.catTile,
                          sel ? { borderColor: c.color, backgroundColor: c.color + "15" } : null,
                        ]}
                        onPress={() => setCategoryId(sel ? null : c.id)}
                        activeOpacity={0.7}
                      >
                        <View style={[styles.catIconWrap, { backgroundColor: c.color + "20" }]}>
                          <Feather name={c.icon as any} size={22} color={c.color} />
                        </View>
                        <Text style={styles.catTileText} numberOfLines={2}>{c.name}</Text>
                        {c.provider_count > 0 ? (
                          <View style={[styles.catCountPill, { backgroundColor: c.color }]}>
                            <Text style={styles.catCountText}>{c.provider_count}</Text>
                          </View>
                        ) : null}
                      </TouchableOpacity>
                    );
                  })}
                  {/* Language tile removed — moved to small icon button at top-right of services header */}
                </View>
              </View>
            )}

            {/* Language picker modal sheet (opens from Browse-by-category Language tile) */}
            <Modal visible={langModalOpen} transparent animationType="slide" onRequestClose={() => setLangModalOpen(false)}>
              <View style={styles.langModalOverlay}>
                <TouchableOpacity style={{ flex: 1 }} activeOpacity={1} onPress={() => setLangModalOpen(false)} />
                <View style={styles.langModalSheet}>
                  <View style={styles.langModalHandle} />
                  <Text style={styles.langModalTitle}>Filter by language</Text>
                  <Text style={styles.langModalSub}>Show service providers who speak…</Text>

                  <TouchableOpacity
                    style={[styles.langOptionRow, !languageQ && styles.langOptionRowActive]}
                    onPress={() => { setLanguageQ(null); setLangModalOpen(false); }}
                  >
                    <View style={styles.langOptionIconWrap}><Feather name="globe" size={18} color={colors.primary} /></View>
                    <Text style={[styles.langOptionText, !languageQ && styles.langOptionTextActive]}>All languages</Text>
                    {!languageQ && <Feather name="check" size={18} color={colors.primary} />}
                  </TouchableOpacity>

                  {LANG_ORDER.map((code) => {
                    const active = languageQ === code;
                    return (
                      <TouchableOpacity
                        key={code}
                        style={[styles.langOptionRow, active && styles.langOptionRowActive]}
                        onPress={() => { setLanguageQ(code); setLangModalOpen(false); }}
                        testID={`lang-option-${code}`}
                      >
                        <View style={styles.langOptionIconWrap}>
                          <Text style={{ fontSize: 12, fontWeight: "900", color: colors.primary }}>{code.toUpperCase()}</Text>
                        </View>
                        <Text style={[styles.langOptionText, active && styles.langOptionTextActive]}>{LANG_LABELS[code]}</Text>
                        {active && <Feather name="check" size={18} color={colors.primary} />}
                      </TouchableOpacity>
                    );
                  })}

                  <TouchableOpacity
                    style={styles.langModalClose}
                    onPress={() => setLangModalOpen(false)}
                  >
                    <Text style={styles.langModalCloseText}>Close</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </Modal>

            {/* Language chips removed — now accessed via the small globe icon in top-right */}

            {/* Provider list now lives inside a slide-up modal opened by tapping a category. */}
            <Modal
              visible={!!categoryId}
              transparent
              animationType="slide"
              onRequestClose={() => setCategoryId(null)}
            >
              <View style={styles.providerSheetOverlay}>
                <View style={styles.providerSheetContainer}>
                  {/* Sheet header */}
                  <View style={styles.providerSheetHeader}>
                    <TouchableOpacity onPress={() => setCategoryId(null)} style={styles.providerSheetBack} testID="provider-sheet-close">
                      <Feather name="arrow-left" size={20} color={colors.textMain} />
                    </TouchableOpacity>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.providerSheetEyebrow}>SERVICE PROVIDERS</Text>
                      <Text style={styles.providerSheetTitle} numberOfLines={1}>
                        {categories.find((c) => c.id === categoryId)?.name || "Providers"}
                      </Text>
                    </View>
                    <TouchableOpacity
                      onPress={() => setLangModalOpen(true)}
                      style={[styles.cartIconBtn, languageQ && { backgroundColor: colors.brand100, borderColor: colors.primary }, { width: 36, height: 36, borderRadius: 18 }]}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                    >
                      <Feather name="globe" size={16} color={languageQ ? colors.primary : colors.textMain} />
                    </TouchableOpacity>
                  </View>

                  <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
                    {servicesLoading && services.length === 0 ? (
                      <View style={[styles.center, { paddingVertical: 40 }]}>
                        <ActivityIndicator color={colors.primary} />
                      </View>
                    ) : services.length === 0 ? (
                      <View style={styles.emptyCard}>
                        <Feather name="briefcase" size={28} color={colors.textMuted} />
                        <Text style={styles.emptyText}>No service providers found.</Text>
                        <Text style={styles.emptySubtext}>Try a different pincode or language — or be the first to list yours!</Text>
                      </View>
                    ) : (
                      services.map((s) => (
                        <TouchableOpacity
                          key={s.id}
                          style={styles.serviceCard}
                          onPress={() => router.push(`/services/${s.id}`)}
                          testID={`service-card-${s.id}`}
                        >
                          <View style={styles.serviceAvatar}>
                            <Text style={styles.serviceAvatarText}>{(s.name || "?")[0].toUpperCase()}</Text>
                          </View>
                          <View style={{ flex: 1 }}>
                            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                              <Text style={styles.serviceName} numberOfLines={1}>{s.name}</Text>
                              {s.is_active ? (
                                <View style={styles.activeDot}>
                                  <View style={styles.activeDotInner} />
                                  <Text style={styles.activeDotText}>LIVE</Text>
                                </View>
                              ) : null}
                            </View>
                            <Text style={styles.serviceTitle} numberOfLines={1}>{s.service_name}</Text>
                            <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                              <View style={styles.tag}><Text style={styles.tagText}>{s.service_category}</Text></View>
                              {/* Pincode + distance shown together (distance only when location is enabled) */}
                              <View style={styles.tag}>
                                <Feather name="map-pin" size={10} color={colors.textMuted} />
                                <Text style={styles.tagText}> {s.service_pincode}</Text>
                                {s.distance_km != null ? (
                                  <>
                                    <Text style={[styles.tagText, { color: colors.textMuted, marginHorizontal: 2 }]}>·</Text>
                                    <Feather name="navigation" size={10} color="#047857" />
                                    <Text style={[styles.tagText, { color: "#047857", fontWeight: "800" }]}> {formatDistance(s.distance_km)}</Text>
                                  </>
                                ) : null}
                              </View>
                              {(s.service_languages || []).map((lc) => (
                                <View key={lc} style={[styles.tag, { backgroundColor: "#EEF2FF", borderColor: "#C7D2FE" }]}>
                                  <Feather name="globe" size={9} color="#3730A3" />
                                  <Text style={[styles.tagText, { color: "#3730A3" }]}> {LANG_LABELS[lc] || lc}</Text>
                                </View>
                              ))}
                            </View>
                            {s.is_active && s.location_updated_at ? (
                              <Text style={styles.activeAgo}>{formatActiveAgo(s.location_updated_at)}</Text>
                            ) : null}
                          </View>
                          <View style={{ alignItems: "flex-end" }}>
                            <Text style={styles.servicePrice}>{formatINR(s.service_charge || 0)}</Text>
                            <Feather name="chevron-right" size={18} color={colors.textMuted} />
                          </View>
                        </TouchableOpacity>
                      ))
                    )}
                  </ScrollView>
                </View>
              </View>
            </Modal>
          </>
        )}
      </ScrollView>

      {/* Contact / book modal */}
      <Modal visible={!!contactOf} transparent animationType="slide" onRequestClose={() => setContactOf(null)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setContactOf(null)}>
          <TouchableOpacity activeOpacity={1} style={styles.modalSheet} onPress={() => {}}>
            {contactOf && (
              <>
                <View style={styles.modalHandle} />
                <Text style={styles.modalTitle}>{contactOf.name}</Text>
                <Text style={styles.modalSubtitle}>{contactOf.service_name} · {contactOf.service_category}</Text>
                {contactOf.service_description ? <Text style={styles.modalDesc}>{contactOf.service_description}</Text> : null}

                <View style={styles.modalRow}>
                  <Feather name="phone" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>{contactOf.phone || "—"}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Feather name="mail" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>{contactOf.email}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Feather name="hash" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>Ref: {contactOf.referral_code}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Feather name="map-pin" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>Pincode {contactOf.service_pincode}</Text>
                </View>
                <View style={[styles.modalRow, { marginBottom: 14 }]}>
                  <Feather name="dollar-sign" size={14} color={colors.textMuted} />
                  <Text style={[styles.modalRowText, { fontWeight: "800", color: colors.primary }]}>{formatINR(contactOf.service_charge || 0)}</Text>
                </View>

                <View style={{ flexDirection: "row", gap: 10 }}>
                  <TouchableOpacity style={[styles.modalBtn, styles.modalBtnGhost]} onPress={() => callOrCopy(contactOf.phone)}>
                    <Feather name="phone" size={14} color={colors.primary} />
                    <Text style={[styles.modalBtnText, { color: colors.primary }]}>Call</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={[styles.modalBtn, styles.modalBtnPrimary, bookingId === contactOf.id && { opacity: 0.6 }]} onPress={() => bookService(contactOf)} disabled={bookingId === contactOf.id}>
                    <Feather name="check-circle" size={14} color="#fff" />
                    <Text style={[styles.modalBtnText, { color: "#fff" }]}>{bookingId === contactOf.id ? "Booking..." : "Book & Pay"}</Text>
                  </TouchableOpacity>
                </View>
              </>
            )}
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { paddingHorizontal: 12, paddingTop: spacing.screen, paddingBottom: 60 },
  pillRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  pill: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  pillTextActive: { color: colors.primaryFg },

  cartBtn: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  cartBadge: { position: "absolute", top: -2, right: -2, minWidth: 20, height: 20, borderRadius: 10, alignItems: "center", justifyContent: "center", paddingHorizontal: 5 },
  cartBadgeText: { fontSize: 10, fontWeight: "800" },
  // Slim top header — uses ABSOLUTE positioning for the cart so it can
  // never wrap below the search bar on any device (Android Expo Go quirk).
  // Top header — refactored 2026-06. Clean flex row, NO absolute positioning.
  // Per user bug report: previous absolute-positioned cart was overflowing
  // off the right edge on certain Android devices. This implementation
  // exactly follows the spec the user provided:
  //   <Row width=100% flexDirection=row paddingHorizontal=16>
  //     <SearchBox flex:1 minWidth:0 height:52 />
  //     <CartBtn 52x52 marginLeft:12 />
  //   </Row>
  topHeader: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 12,
    backgroundColor: colors.background,
  },
  servicesTitleWrap: {
    flex: 1,
    minWidth: 0,
    marginRight: 12,
  },
  topHeaderEyebrow: { fontSize: 10, letterSpacing: 1.6, color: colors.textMuted, fontWeight: "800" },
  topHeaderTitle: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.6, marginTop: 2 },
  // Language picker modal sheet
  langModalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  langModalSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 28, borderTopRightRadius: 28,
    paddingHorizontal: 20, paddingTop: 12, paddingBottom: 28,
  },
  langModalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  langModalTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  langModalSub: { fontSize: 12, color: colors.textMuted, marginTop: 4, marginBottom: 14 },
  langOptionRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 12, paddingHorizontal: 12,
    borderRadius: 14,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: 8,
  },
  langOptionRowActive: { backgroundColor: colors.brand100, borderColor: colors.primary },
  langOptionIconWrap: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  langOptionText: { flex: 1, fontSize: 14, fontWeight: "700", color: colors.textMain },
  langOptionTextActive: { color: colors.primary },
  langModalClose: {
    marginTop: 8, paddingVertical: 12,
    borderRadius: 12, alignItems: "center",
    backgroundColor: colors.surfaceMuted,
  },
  langModalCloseText: { color: colors.textMain, fontWeight: "800", fontSize: 14 },
  // Provider sheet (slide-up modal for category drill-down)
  providerSheetOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)" },
  providerSheetContainer: {
    flex: 1, marginTop: 60,
    backgroundColor: colors.background,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    overflow: "hidden",
  },
  providerSheetHeader: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingTop: 16, paddingBottom: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  providerSheetBack: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  providerSheetEyebrow: { fontSize: 9, letterSpacing: 1.4, color: colors.textMuted, fontWeight: "800" },
  providerSheetTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4, marginTop: 1 },
  cartIconBtn: {
    // 52×52 fixed-size cart/language button — exactly matches search bar
    // height so they sit on a single visual baseline. `flexShrink: 0`
    // guarantees the button never compresses on narrow screens.
    width: 52,
    height: 52,
    marginLeft: 12,
    flexShrink: 0,
    borderRadius: 18,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({
      ios: {
        shadowColor: colors.primary,
        shadowOpacity: 0.18,
        shadowRadius: 6,
        shadowOffset: { width: 0, height: 2 },
      },
      android: { elevation: 2 },
      default: { boxShadow: "0px 2px 6px rgba(15,42,29,0.12)" as any },
    }),
  },
  // Legacy absolute-positioned variant kept only to avoid breaking other
  // imports of this stylesheet — no longer referenced in JSX.
  cartIconBtnAbs: {
    width: 52, height: 52, borderRadius: 18,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  cartBadgeTop: {
    position: "absolute", top: -5, right: -5,
    minWidth: 18, height: 18, borderRadius: 9,
    backgroundColor: colors.accent,
    alignItems: "center", justifyContent: "center",
    paddingHorizontal: 4,
    borderWidth: 2, borderColor: colors.background,
  },
  cartBadgeTopText: { fontSize: 10, fontWeight: "900", color: colors.accentFg, letterSpacing: -0.3 },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  card: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 18, overflow: "hidden", padding: 10 },
  image: { width: "100%", height: 130, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  name: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginTop: 10, minHeight: 34 },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
  price: { fontSize: 15, fontWeight: "800", color: colors.primary },
  addBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  checkoutBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, backgroundColor: colors.accent, paddingVertical: 14, borderRadius: radii.button, marginTop: 24 },
  checkoutBarText: { color: colors.accentFg, fontWeight: "700", fontSize: 15, flex: 1, textAlign: "center" },

  applyCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 14, backgroundColor: colors.primary, marginBottom: 14 },
  filterRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  searchBox: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10, height: 38 },
  searchInput: { flex: 1, fontSize: 13, color: colors.textMain, paddingVertical: 0 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "600", color: colors.textMain },
  chipTextActive: { color: colors.primaryFg },

  // Service category grid
  categoryGridSection: { marginBottom: 14 },
  sectionHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  sectionTitle: { fontSize: 13, fontWeight: "800", letterSpacing: 0.3, color: colors.textMain, textTransform: "uppercase" },
  clearLink: { fontSize: 12, fontWeight: "700", color: colors.primary },
  categoryGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  catTile: {
    width: "31.5%",
    aspectRatio: 1,
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 6,
    paddingVertical: 10,
    position: "relative",
  },
  catIconWrap: {
    width: 44, height: 44, borderRadius: 12,
    alignItems: "center", justifyContent: "center", marginBottom: 6,
  },
  catTileText: {
    fontSize: 11, fontWeight: "700", color: colors.textMain,
    textAlign: "center", lineHeight: 14,
  },
  catCountPill: {
    position: "absolute", top: 6, right: 6,
    minWidth: 20, height: 20, borderRadius: 10,
    paddingHorizontal: 6, alignItems: "center", justifyContent: "center",
  },
  catCountText: { color: "#fff", fontSize: 10, fontWeight: "800" },

  // Language filter row
  langRow: {
    flexDirection: "row", alignItems: "center", flexWrap: "wrap",
    gap: 6, marginBottom: 14,
  },
  langLabel: { fontSize: 12, fontWeight: "700", color: colors.textMuted, marginRight: 4 },
  langChip: {
    paddingVertical: 5, paddingHorizontal: 10, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  langChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  langChipText: { fontSize: 11, fontWeight: "700", color: colors.textMuted },
  langChipTextActive: { color: colors.primaryFg },

  // Location button + active badge
  locBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    paddingVertical: 10, paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: colors.primary + "15",
    borderWidth: 1, borderColor: colors.primary + "44",
    marginBottom: 14,
  },
  locBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  locBtnText: { fontSize: 12, fontWeight: "700", color: colors.primary },
  locBtnTextActive: { color: colors.primaryFg },
  activeDot: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#ECFDF5",
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1, borderColor: "#A7F3D0",
  },
  activeDotInner: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#10B981" },
  activeDotText: { fontSize: 9, fontWeight: "800", color: "#047857", letterSpacing: 0.4 },
  activeAgo: { fontSize: 10, color: colors.textMuted, marginTop: 2 },

  serviceCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 10 },
  serviceAvatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  serviceAvatarText: { fontSize: 16, fontWeight: "800", color: colors.primary },
  serviceName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  serviceTitle: { fontSize: 12, color: colors.textMuted, marginTop: 1 },
  tag: { flexDirection: "row", alignItems: "center", paddingVertical: 2, paddingHorizontal: 8, backgroundColor: colors.surfaceMuted, borderRadius: 999 },
  tagText: { fontSize: 10, fontWeight: "600", color: colors.textMuted },
  servicePrice: { fontSize: 15, fontWeight: "800", color: colors.primary },

  emptyCard: { padding: 30, alignItems: "center", gap: 8 },
  emptyText: { fontSize: 14, fontWeight: "700", color: colors.textMain, marginTop: 8 },
  emptySubtext: { fontSize: 12, color: colors.textMuted, textAlign: "center" },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 22, paddingBottom: Platform.OS === "ios" ? 36 : 22 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  modalSubtitle: { fontSize: 13, color: colors.textMuted, marginTop: 2, marginBottom: 8 },
  modalDesc: { fontSize: 13, color: colors.textMain, marginBottom: 12, lineHeight: 18 },
  modalRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6 },
  modalRowText: { fontSize: 13, color: colors.textMain },
  modalBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 12 },
  modalBtnPrimary: { backgroundColor: colors.primary },
  modalBtnGhost: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  modalBtnText: { fontSize: 14, fontWeight: "800" },

  // ============================================================
  //  Phase B — New Customer Shop UI (search, banner, categories,
  //  product cards with stock-aware states)
  // ============================================================
  shopSearch: {
    // CRITICAL: `flex: 1 + minWidth: 0` is the only reliable way to make a
    // flex child shrink properly on Android. Without `minWidth: 0` Android
    // pushes the cart button off the right edge of the screen because the
    // search bar refuses to shrink below its intrinsic content width.
    flex: 1,
    minWidth: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    height: 52,
    paddingHorizontal: 16,
    borderRadius: 18,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    ...Platform.select({
      ios: {
        shadowColor: "#0F2A1D",
        shadowOpacity: 0.05,
        shadowRadius: 6,
        shadowOffset: { width: 0, height: 1 },
      },
      android: { elevation: 1 },
      default: { boxShadow: "0px 1px 6px rgba(15,42,29,0.05)" as any },
    }),
  },
  shopSearchInput: {
    flex: 1, fontSize: 14, color: colors.textMain, paddingVertical: 0,
    fontWeight: "500",
    minWidth: 0,
  },
  searchFilterBtn: {
    width: 30, height: 30, borderRadius: 8,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },

  // ---- Hero banner (matches reference image 2) ----
  heroBanner: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: "#F0F9F2",
    borderRadius: 24,
    padding: 18,
    marginBottom: 18,
    overflow: "hidden",
    minHeight: 150,
  },
  heroEyebrow: {
    fontSize: 10, fontWeight: "800", letterSpacing: 1.4,
    color: colors.primary, marginBottom: 6, textTransform: "uppercase",
  },
  heroTitle: {
    fontSize: 22, fontWeight: "900", color: colors.textMain,
    lineHeight: 26, letterSpacing: -0.6,
  },
  heroTitleAccent: { color: colors.primary, fontSize: 28, lineHeight: 32 },
  heroSub: {
    fontSize: 11, color: colors.textMuted, marginTop: 6, lineHeight: 15,
  },
  heroBtn: {
    marginTop: 12, alignSelf: "flex-start",
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.primary,
    paddingVertical: 9, paddingHorizontal: 16,
    borderRadius: 999,
  },
  heroBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  heroBlob: {
    width: 100, height: 100, borderRadius: 50,
    backgroundColor: "#D4ECDA",
    alignItems: "center", justifyContent: "center",
  },

  // ---- Section headers ----
  shopSectionHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 10,
  },
  shopSectionTitle: {
    fontSize: 15, fontWeight: "800", color: colors.textMain,
    letterSpacing: -0.2,
  },
  shopSectionCount: {
    fontSize: 11, fontWeight: "700", color: colors.textMuted,
  },
  seeAllLink: { fontSize: 11, fontWeight: "700", color: colors.primary },

  // ---- Department tiles (matches reference image 2) ----
  deptRow: { gap: 10, paddingRight: 4, paddingBottom: 6 },
  deptTile: {
    width: 96,
    paddingVertical: 12, paddingHorizontal: 8,
    borderRadius: 16,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center",
    gap: 6,
  },
  deptTileActive: { borderColor: colors.primary, borderWidth: 2 },
  deptIconCircle: {
    width: 50, height: 50, borderRadius: 25,
    alignItems: "center", justifyContent: "center",
  },
  deptLabel: { fontSize: 11, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  deptCount: { fontSize: 9, fontWeight: "600", color: colors.textMuted },

  // ---- Product cards ----
  cardNew: {
    flexBasis: "48%", flexGrow: 1,
    backgroundColor: colors.surface,
    borderRadius: 18,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.border,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 2 },
      default: {},
    }),
  },
  cardOOS: { borderColor: "#E8E3DC" },
  cardImageWrap: {
    position: "relative",
    aspectRatio: 1,
    backgroundColor: colors.surfaceMuted,
  },
  cardImageNew: { width: "100%", height: "100%" },
  cardBody: { padding: 12, gap: 5 },
  ratingRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  ratingText: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  cardCategoryDot: { fontSize: 10, fontWeight: "600", color: colors.textMuted },
  cardTitle: {
    fontSize: 13, fontWeight: "700", color: colors.textMain,
    lineHeight: 17, minHeight: 34,
  },
  cardFooterNew: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: 4,
  },
  cardPrice: { fontSize: 15, fontWeight: "800", color: colors.primary, letterSpacing: -0.3 },
  cardCta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.primary, minWidth: 64,
  },
  cardCtaText: { fontSize: 12, fontWeight: "800", color: "#fff", letterSpacing: -0.2 },

  // ---- Heart button (matches reference) ----
  heartBtn: {
    position: "absolute", top: 8, right: 8,
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: "rgba(255,255,255,0.95)",
    alignItems: "center", justifyContent: "center",
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.08, shadowRadius: 4, shadowOffset: { width: 0, height: 2 } },
      android: { elevation: 2 },
      default: {},
    }),
  },

  // ---- Stock pills + overlays ----
  lowStockPill: {
    position: "absolute", top: 8, left: 8,
    paddingVertical: 4, paddingHorizontal: 8,
    backgroundColor: "#F59E0B",
    borderRadius: 999,
  },
  lowStockText: { fontSize: 9, fontWeight: "800", color: "#fff", letterSpacing: 0.4 },
  oosOverlay: {
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.4)",
  },
  oosOverlayText: {
    fontSize: 13, fontWeight: "900", color: colors.textMain,
    letterSpacing: 2,
    backgroundColor: "rgba(255,255,255,0.85)",
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4,
    overflow: "hidden",
  },
  interestBadge: {
    position: "absolute", bottom: 8, left: 8,
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 3, paddingHorizontal: 8,
    backgroundColor: colors.primary,
    borderRadius: 999,
  },
  interestBadgeText: { fontSize: 10, fontWeight: "800", color: "#fff" },

  outOfStockHint: {
    fontSize: 12, color: colors.textMuted,
    marginBottom: 12, lineHeight: 16,
  },

  shopEmpty: {
    paddingVertical: 36, alignItems: "center",
    gap: 6,
    backgroundColor: colors.surface,
    borderRadius: 18, borderWidth: 1, borderColor: colors.border,
    marginBottom: 12,
  },
  shopEmptyTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  shopEmptySub: { fontSize: 12, color: colors.textMuted, textAlign: "center", paddingHorizontal: 20 },
});
