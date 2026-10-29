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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, TextInput,
  ActivityIndicator, Platform,
  Modal, Pressable, RefreshControl, Linking,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useFocusEffect, useRouter } from "expo-router";
import { Feather, MaterialCommunityIcons, MaterialIcons } from "@expo/vector-icons";
// Aug 2026 — removed useSafeAreaInsets to prevent double-padding gap.
// Parent screens already handle safe-area via <SafeAreaView edges={["top"]}>.
import { api, formatApiError, resolveImageUrl } from "./api";
import { colors, spacing } from "./theme";
import { SubscribeBanner } from "./subscription";
import { ShopLayoutRenderer } from "./shop-layout-renderer";
import {
  checkLocationPermission,
} from "./location";
import { captureCurrentPlace } from "./capture-location";
import { useAuth } from "./auth";
import { NoVendorsHero } from "./no-vendors-hero";
import { FadeSlideIn, ProductCardSkeleton } from "./anim";
import { useShopCart } from "./use-shop-cart";
import { ProductGridCard, productGridStyles } from "./product-grid-card";
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
  vendor_id?: string | null;
};

/** One grouped smart-search suggestion (see GET /api/products/search-suggest). */
type SearchSuggestion = {
  name: string;
  brand?: string;
  category?: string;
  min_price: number;
  max_price: number;
  listings: number;
  vendor_count: number;
  image?: string;
};


// ── Pure helpers ─────────────────────────────────────────────────────────

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
  // Aug 2026 — Removed `useSafeAreaInsets()` here.  The parent screens
  // already wrap ShopHome in <SafeAreaView edges={["top"]}> which reserves
  // the status-bar space; adding `insets.top` on top of that produced a
  // visible empty gap.  Header now uses a tiny 4-pixel padding only.
  // UPDATE 1 (June 2026) — Hide the current vendor's own products.
  const { user } = useAuth();
  const currentUserId = user?.id || null;

  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  // Aug 2026 — pull-to-refresh & live-update state.  refreshTick propagates
  // into ShopLayoutRenderer so admin publishes appear without app restart.
  const [refreshing, setRefreshing] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [search, setSearch] = useState("");
  const [searchSubmitted, setSearchSubmitted] = useState(false);
  // Jun 2026 — Smart-search typeahead.  Grouped by product name so the
  // same item sold by 6 vendors shows as ONE suggestion with a price band
  // and a "N sellers" hint; submitting still lists every vendor listing.
  const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([]);
  const [suggestOpen, setSuggestOpen] = useState(false);
  // How many admin shop-layout blocks resolved for this pincode (null = not
  // yet known). 0 → we fall back to a plain "All products near you" grid.
  const [layoutBlockCount, setLayoutBlockCount] = useState<number | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("all");
  // "More" tap opens an all-categories sheet
  const [allCatModalOpen, setAllCatModalOpen] = useState(false);
  // Admin-managed shop categories (fetched from /api/shop-categories).
  // Falls back to a hardcoded short list if the API fails.
  const [apiCategories, setApiCategories] = useState<ApiCategory[] | null>(null);
  // Jun 2026 — The category strip auto-scrolls to keep the active chip in
  // view. Horizontal swipes on this screen belong to the BOTTOM TAB pager
  // (Shop ⇄ Services ⇄ Dashboard …), so the home screen deliberately does
  // NOT claim them — categories are chosen by tapping a circle.
  const catStripRef = useRef<ScrollView | null>(null);
  // Jun 2026 — Search results and the home category grid now render the SAME
  // ProductGridCard as the category screen, wired to the same cart
  // controller. Previously search results used a flashier card with invented
  // discount/rating/review numbers and NO add button, so nothing could be
  // added to the cart from a search.
  // Jun 2026 — use the hook's OWN live count for the header badge. The
  // `cartCount` prop comes from the Shop tab, which only re-fetches on tab
  // focus, so the badge stayed stale right after an in-block "+" tap.
  const { cartCount: liveCartCount, cartQty, addedFlash, addToCart, decrement } = useShopCart();

  // ── Delivery address (live reverse-geocoded from user coords) ─────────
  // Jul 2026 — Shop is now LOCATION-FIRST.  We require GPS on mount and
  // send lat/lng + pincode to the products endpoint with strict_location
  // so only nearby-vendor products render.  Manual pincode entry has been
  // removed (see git history for the old free-text search UI).
  const [deliveryAddress, setDeliveryAddress] = useState<string>(defaultAddress);
  const [deliveryPincode, setDeliveryPincode] = useState<string>("");
  const [deliveryCoords, setDeliveryCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [permStatus, setPermStatus] = useState<"unknown" | "granted" | "denied" | "unsupported" | "prompt">("unknown");
  const [locModalOpen, setLocModalOpen] = useState(false);
  const [locBusy, setLocBusy] = useState(false);

  // Persisted cache key — survives reloads / logout-login on the same device.
  const ADDR_KEY  = "@app/deliveryAddress";
  const PIN_KEY   = "@app/deliveryPincode";
  const COORDS_KEY = "@app/deliveryCoords";

  // Hydrate cached address on mount, then try to refresh from current GPS.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cached = await AsyncStorage.getItem(ADDR_KEY);
        const cachedPin = await AsyncStorage.getItem(PIN_KEY);
        const cachedCoordsRaw = await AsyncStorage.getItem(COORDS_KEY);
        if (cached && !cancelled) setDeliveryAddress(cached);
        if (cachedPin && !cancelled) setDeliveryPincode(cachedPin);
        if (cachedCoordsRaw && !cancelled) {
          try {
            const cc = JSON.parse(cachedCoordsRaw);
            if (cc && typeof cc.lat === "number" && typeof cc.lng === "number") setDeliveryCoords(cc);
          } catch { /* ignore */ }
        }
      } catch { /* ignore */ }
      // Fire-and-forget refresh from current location.
      refreshLocation(false);
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persistAddress = useCallback(async (a: string, pin?: string, coords?: { lat: number; lng: number } | null) => {
    try {
      await AsyncStorage.setItem(ADDR_KEY, a);
      if (pin !== undefined) await AsyncStorage.setItem(PIN_KEY, pin);
      if (coords !== undefined) {
        if (coords) await AsyncStorage.setItem(COORDS_KEY, JSON.stringify(coords));
        else await AsyncStorage.removeItem(COORDS_KEY);
      }
    } catch { /* ignore */ }
  }, []);

  /**
   * Best-effort reverse-geocode of the current device location.
   * `silent=true` means "don't show errors — use cache if anything fails".
   * On web, `Location.reverseGeocodeAsync` isn't supported so we fall back
   * to plain "City near {lat},{lng}".
   *
   * Jul 2026 — Also captures lat/lng in deliveryCoords + updates
   * permStatus so the gate can react.
   */
  const refreshLocation = useCallback(async (interactive: boolean) => {
    setLocBusy(true);
    try {
      // Sep 2026 — ONE engine for customer + vendor maps
      // (src/capture-location.ts). It reads the device geocoder first (the
      // one that actually returns a pincode) and then validates through
      // /api/geo/resolve so we never store a pincode that doesn't exist.
      const place = await captureCurrentPlace();
      if (!place) {
        // Reflect the permission state so the location gate can react.
        const ps = await checkLocationPermission();
        setPermStatus(ps === "granted" ? "granted" : ps === "denied" ? "denied" : ps === "unsupported" ? "unsupported" : "prompt");
        if (interactive && ps === "granted") {
          alert("Couldn't read your GPS. Please try again in a moment.");
        }
        return;
      }
      setPermStatus("granted");
      setDeliveryCoords({ lat: place.lat, lng: place.lng });
      const display = place.label || `Near ${place.lat.toFixed(2)}, ${place.lng.toFixed(2)}`;
      setDeliveryAddress(display);
      setDeliveryPincode(place.pincode);
      persistAddress(display, place.pincode, { lat: place.lat, lng: place.lng });
      if (!place.pincode && place.rejectedPincode && interactive) {
        alert(
          `We couldn't verify the pincode ${place.rejectedPincode} for your spot, so we're matching shops by your GPS location instead.`,
        );
      }
    } finally { setLocBusy(false); }
  }, [persistAddress]);

  // Jul 2026 — Manual address entry was removed.  The shop is now
  // location-first (GPS or nothing).  If the user needs to change their
  // area, they should update their delivery address in Profile → Addresses
  // (that flow captures both pincode + lat/lng via the picker).

  // ── Data ───────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    try {
      // Jul 2026 — Location-first shop.  We only fetch products when
      // we have a real location signal (pincode or coords).  strict_location
      // ensures the backend returns [] if the signal doesn't match any
      // nearby vendor, so the customer sees an empty-state rather than
      // the global catalog.
      const params: Record<string, any> = { strict_location: "true" };
      if (deliveryPincode) params.pincode = deliveryPincode;
      if (deliveryCoords) { params.lat = deliveryCoords.lat; params.lng = deliveryCoords.lng; }
      // Dec 2026 — When user submitted a search, forward it as `q` to the
      // backend AND bump the limit so we don't miss deep-catalog hits.
      if (searchSubmitted && search.trim()) {
        params.q = search.trim();
        params.limit = 240;
      }
      // If we have NO location signal yet, skip the fetch entirely —
      // the LocationGate view is what the user sees.
      if (!deliveryPincode && !deliveryCoords) { setProducts([]); return; }
      const r = await api.get<any>("/products", { params });
      const list: Product[] = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      const inStock = list.filter((p) => p && p.is_in_stock !== false);
      // UPDATE 1 — Hide the current vendor's own products from themselves.
      const scoped = currentUserId
        ? inStock.filter((p) => !p.vendor_id || p.vendor_id !== currentUserId)
        : inStock;
      setProducts(scoped);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("ShopHome /products failed:", formatApiError(e));
    } finally { setLoading(false); }
  }, [currentUserId, deliveryPincode, deliveryCoords, searchSubmitted, search]);

  // Jun 2026 — Debounced typeahead. Fires 250 ms after the last keystroke
  // once 2+ characters are typed. Location params keep suggestions to
  // products a nearby vendor can actually deliver.
  useEffect(() => {
    const term = search.trim();
    if (searchSubmitted || term.length < 2) { setSuggestions([]); setSuggestOpen(false); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const params: Record<string, any> = { q: term, limit: 8 };
        if (deliveryPincode) params.pincode = deliveryPincode;
        if (deliveryCoords) { params.lat = deliveryCoords.lat; params.lng = deliveryCoords.lng; }
        const r = await api.get<{ items: SearchSuggestion[] }>("/products/search-suggest", { params });
        if (cancelled) return;
        const items = r.data?.items || [];
        setSuggestions(items);
        setSuggestOpen(items.length > 0);
      } catch {
        if (!cancelled) { setSuggestions([]); setSuggestOpen(false); }
      }
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [search, searchSubmitted, deliveryPincode, deliveryCoords]);

  // Admin-managed categories — fetched in parallel with products.
  //
  // 2026-06-10 — Two bugs fixed here:
  //   1. Initial render previously fell back to FALLBACK_CATEGORIES (a
  //      hardcoded list including "Sarees", "Men", "Women" etc.) for the
  //      ~200-300 ms window between mount and the first /shop-categories
  //      response. Result: user saw OLD icons flash, then the screen
  //      "corrected" itself once the API returned. The fix is to hydrate
  //      from a persisted AsyncStorage cache (last good API response) on
  //      mount, so the strip shows the REAL admin categories instantly
  //      and only ever transitions to "fresher real" data — never to
  //      "stale hardcoded" data.
  //
  //   2. If both cache + API fail (first install offline), we still
  //      DON'T fall back to the hardcoded list. Instead we render an
  //      empty strip so the user never sees obsolete category names.
  const SHOP_CATS_CACHE = "@app/shopCategoriesV1";
  const loadCategories = useCallback(async () => {
    try {
      const r = await api.get<{ items: ApiCategory[] }>("/shop-categories");
      const items = (r.data?.items || []).filter((c) => c.active !== false);
      items.sort((a, b) => (a.sort_order - b.sort_order) || a.name.localeCompare(b.name));
      setApiCategories(items);
      // Persist for next launch so the strip never flashes old icons.
      try { await AsyncStorage.setItem(SHOP_CATS_CACHE, JSON.stringify(items)); } catch { /* quota / disabled storage */ }
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("ShopHome /shop-categories failed:", formatApiError(e));
      // Don't clobber existing state on transient errors — keep whatever
      // we already had (likely the cache hydrated on mount).
    }
  }, []);

  // Hydrate from cache BEFORE the first network response so the very
  // first frame already shows the admin's real categories, not the
  // hardcoded fallback. The API call still runs immediately after and
  // overrides this with the freshest data.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cached = await AsyncStorage.getItem(SHOP_CATS_CACHE);
        if (!cached || cancelled) return;
        const parsed: ApiCategory[] = JSON.parse(cached);
        if (Array.isArray(parsed) && parsed.length > 0) setApiCategories(parsed);
      } catch { /* ignore cache miss / corruption */ }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => { load(); loadCategories(); }, [load, loadCategories]);
  // Reload categories whenever the shop home REGAINS focus so admin changes
  // (icon swap, rename, new category) show up immediately when the admin
  // pops back from /admin/shop-categories.
  //
  // Sep 2026 perf — the first focus fires on mount, right after the effect
  // above, so every single open of the Shop tab fetched the categories
  // twice. `firstFocus` skips that duplicate round-trip.
  const firstFocus = useRef(true);
  useFocusEffect(useCallback(() => {
    if (firstFocus.current) { firstFocus.current = false; return; }
    loadCategories();
  }, [loadCategories]));

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

  // Jul 2026 — Location gate.  We show a full-screen "Enable location to
  // browse products" screen when we haven't captured GPS yet.  Users
  // hydrating from a cached location fall through immediately (they've
  // shopped here before).  A hard-denied permission gets an "Open
  // Settings" CTA; an "undetermined" or first-open state gets a
  // "Turn on location" CTA that triggers the OS prompt.
  const hasLocation = !!(deliveryCoords || deliveryPincode);
  if (!hasLocation) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center", padding: 28 }}>
        <View style={{
          width: 88, height: 88, borderRadius: 44,
          backgroundColor: colors.brand100,
          alignItems: "center", justifyContent: "center", marginBottom: 20,
        }}>
          <Feather name="map-pin" size={38} color={colors.primary} />
        </View>
        <Text style={{ fontSize: 20, fontWeight: "900", color: colors.textMain, textAlign: "center", letterSpacing: -0.4 }}>
          Turn on location to shop
        </Text>
        <Text style={{ fontSize: 13, color: colors.textMuted, textAlign: "center", marginTop: 10, lineHeight: 20, maxWidth: 320 }}>
          Slangcart shows you products from vendors who actually deliver to
          you. We need your device location to find nearby shops — nothing
          is shared with anyone else.
        </Text>

        {permStatus === "denied" ? (
          <>
            <TouchableOpacity
              onPress={() => { try { Linking.openSettings(); } catch { /* ignore */ } }}
              style={{
                marginTop: 24, backgroundColor: colors.primary,
                paddingHorizontal: 24, paddingVertical: 13,
                borderRadius: 999, minWidth: 220,
                alignItems: "center", flexDirection: "row", justifyContent: "center", gap: 8,
              }}
              testID="loc-gate-open-settings"
            >
              <Feather name="settings" size={16} color={colors.primaryFg} />
              <Text style={{ color: colors.primaryFg, fontWeight: "800", fontSize: 15 }}>Open Settings</Text>
            </TouchableOpacity>
            <Text style={{ fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 12, maxWidth: 300 }}>
              You previously denied location. Enable it in your device
              Settings → Slangcart → Location, then come back and tap Retry.
            </Text>
            <TouchableOpacity
              onPress={() => refreshLocation(true)}
              disabled={locBusy}
              style={{ marginTop: 10, paddingHorizontal: 20, paddingVertical: 10 }}
              testID="loc-gate-retry"
            >
              <Text style={{ color: colors.primary, fontWeight: "800", fontSize: 14 }}>Retry</Text>
            </TouchableOpacity>
          </>
        ) : permStatus === "unsupported" ? (
          <Text style={{ marginTop: 24, fontSize: 13, color: colors.textMuted, textAlign: "center", maxWidth: 300 }}>
            Location isn't supported by this device / browser. Please open
            Slangcart on a phone with GPS to browse products.
          </Text>
        ) : (
          <TouchableOpacity
            onPress={() => refreshLocation(true)}
            disabled={locBusy}
            style={{
              marginTop: 24, backgroundColor: colors.primary,
              paddingHorizontal: 24, paddingVertical: 13,
              borderRadius: 999, minWidth: 220,
              alignItems: "center", flexDirection: "row", justifyContent: "center", gap: 8,
              opacity: locBusy ? 0.7 : 1,
            }}
            testID="loc-gate-enable"
          >
            {locBusy ? (
              <ActivityIndicator color={colors.primaryFg} />
            ) : (
              <>
                <Feather name="navigation" size={16} color={colors.primaryFg} />
                <Text style={{ color: colors.primaryFg, fontWeight: "800", fontSize: 15 }}>Turn on location</Text>
              </>
            )}
          </TouchableOpacity>
        )}
      </View>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      {/* 1. TOP HEADER — delivery + wishlist + cart */}
      {/* Aug 2026 — Removed the extra `insets.top` from paddingTop here.
          The parent screens (app/(tabs)/shop.tsx and app/admin/shop.tsx) already
          wrap this in <SafeAreaView edges={["top"]}> which reserves the
          status-bar space, so adding another `insets.top + 8` here was
          double-padding and produced a visible empty gap between the status
          bar and the "Deliver to …" row. Now we only add a small 4-pixel
          breathing room. */}
      <View style={[styles.headerWrap, { paddingTop: 4 }]}>
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
              {Math.max(liveCartCount, cartCount) > 0 ? (
                <View style={[styles.iconBadge, { backgroundColor: "#F59E0B" }]}><Text style={styles.iconBadgeText}>{Math.max(liveCartCount, cartCount) > 9 ? "9+" : Math.max(liveCartCount, cartCount)}</Text></View>
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

        {/* Jun 2026 — Grouped suggestion dropdown. One row per distinct
            product name (not per vendor listing), with the price band and
            seller count across nearby vendors. Tapping runs the full
            search, which lists EVERY published vendor listing. */}
        {suggestOpen && !searchSubmitted ? (
          <View style={styles.suggestPanel} testID="home-search-suggestions">
            {suggestions.map((s, i) => (
              <TouchableOpacity
                key={`sg-${i}-${s.name}`}
                style={[styles.suggestRow, i === suggestions.length - 1 && { borderBottomWidth: 0 }]}
                activeOpacity={0.7}
                onPress={() => {
                  setSearch(s.name);
                  setSuggestOpen(false);
                  setSearchSubmitted(true);
                }}
                testID={`home-suggest-${i}`}
              >
                {s.image ? (
                  <Image source={{ uri: resolveImageUrl(s.image) }} style={styles.suggestThumb} resizeMode="cover" />
                ) : (
                  <View style={[styles.suggestThumb, { alignItems: "center", justifyContent: "center" }]}>
                    <Feather name="package" size={14} color={colors.textMuted} />
                  </View>
                )}
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.suggestName} numberOfLines={1}>{s.name}</Text>
                  <Text style={styles.suggestMeta} numberOfLines={1}>
                    {s.min_price === s.max_price
                      ? `₹${Math.round(s.min_price)}`
                      : `₹${Math.round(s.min_price)} – ₹${Math.round(s.max_price)}`}
                    {s.vendor_count > 1 ? ` · ${s.vendor_count} sellers` : s.brand ? ` · ${s.brand}` : ""}
                  </Text>
                </View>
                <Feather name="arrow-up-left" size={14} color={colors.textMuted} />
              </TouchableOpacity>
            ))}
          </View>
        ) : null}
      </View>

      <ScrollView
        contentContainerStyle={{ paddingBottom: 32 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={async () => {
              // Aug 2026 — pull-to-refresh triggers ALL data reloads:
              //   • products list (live prices, new listings)
              //   • shop layout blocks (admin publishes appear instantly)
              //   • wallpapers / promos via ShopLayoutRenderer's refreshTick
              setRefreshing(true);
              setRefreshTick((n) => n + 1);
              try { await load(); } finally { setRefreshing(false); }
            }}
            tintColor={colors.primary}
          />
        }
      >
        <LocationBanner />
        {/* Free-tier upsell — hidden automatically for subscribed users. */}
        <View style={{ paddingHorizontal: spacing.screen, paddingTop: 6 }}>
          <SubscribeBanner compact />
        </View>
        {addedFlash ? (
          <View style={styles.addedFlash} pointerEvents="none">
            <Feather name="check-circle" size={13} color="#fff" />
            <Text style={styles.addedFlashText} numberOfLines={1}>{addedFlash}</Text>
          </View>
        ) : null}
        {searchSubmitted && search.trim() ? (
          // ── SEARCH RESULTS VIEW ─────────────────────────────────────
          <View style={{ paddingHorizontal: spacing.screen, paddingTop: spacing.screen }}>
            <View style={styles.searchResultHeader}>
              <Text style={styles.searchResultTitle}>
                Results for "<Text style={{ color: colors.primary }}>{search.trim()}</Text>"
              </Text>
              <Text style={styles.searchResultCount}>{filteredProducts.length} product{filteredProducts.length === 1 ? "" : "s"}</Text>
            </View>
            {loading ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, paddingHorizontal: 4 }}>
                {[...Array(6)].map((_, i) => <ProductCardSkeleton key={i} />)}
              </View>
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
              <View style={productGridStyles.wrap}>
                {filteredProducts.map((item, idx) => (
                  <ProductGridCard
                    key={`result-${item.id}`}
                    product={item as any}
                    qty={cartQty[item.id] || 0}
                    index={idx}
                    onOpen={(x) => router.push(`/product/${x.id}` as any)}
                    onAdd={addToCart}
                    onDecrement={decrement}
                  />
                ))}
              </View>
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
          ref={catStripRef}
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

          {/* Admin categories — strictly from /api/shop-categories (cache-hydrated).
              NEVER falls back to FALLBACK_CATEGORIES here because that
              caused old/stale category names (Sarees, Men, etc) to flash
              before the API returned. Empty array → render nothing until
              data arrives. Max 6 in the strip, rest live in the More
              modal. */}
          {(apiCategories || []).slice(0, 6).map((c: ApiCategory) => {
            const key = c.id || c.name;
            const label = c.name;
            const pack: CatIconPack = c.icon_pack || "feather";
            const iconName = c.icon_name || "shopping-bag";
            const color = c.color || "#E5F2EC";
            const imageUrl = c.image_url || null;
            const active = activeCategory === c.name;
            return (
              <TouchableOpacity
                key={key}
                style={styles.catItem}
                onPress={() => {
                  // 2026-06-10 — Tapping a category in the home strip
                  // now NAVIGATES to /shop-category/<name> instead of
                  // just locally filtering the list. The local-filter
                  // path used `p.category === activeCategory` which
                  // silently returned 0 products whenever the admin
                  // category name didn't exactly match the field on
                  // product docs (a common case after a rename or when
                  // products are stored with category_id but the strip
                  // uses category_name). The dedicated category screen
                  // is case-insensitive and falls through category_id /
                  // category_name / category, so it Just Works™ — same
                  // as the "More → tap" path that the user already
                  // confirmed shows products correctly.
                  // Oct-2026 — Recharge is not a browsable product grid.
                  // It has its own Service → State → Network → number flow,
                  // so it bypasses the generic category screen entirely.
                  if (/recharge/i.test(c.name)) {
                    router.push("/recharge" as any);
                    return;
                  }
                  router.push(
                    `${categoryRoutePrefix}/shop-category/${encodeURIComponent(c.name)}` as any,
                  );
                }}
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
          <View style={{ paddingHorizontal: spacing.screen, paddingTop: spacing.screen }}>
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
              // Jul 2026 — Category grid empty state.
              // If the WHOLE catalog for this delivery zone is empty (not
              // just this category), the parent path shows the hero.
              // Here we only reach when the user has already picked a
              // specific category and it happens to be empty for their
              // pincode — that's still a "no vendors here" moment, so
              // we render the hero when products (all cats) is also 0.
              products.length === 0 ? (
                <NoVendorsHero location={deliveryPincode || undefined} compact />
              ) : (
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
              )
            ) : (
              <View style={productGridStyles.wrap}>
                {filteredProducts.map((item, idx) => (
                  <ProductGridCard
                    key={`cat-${item.id}`}
                    product={item as any}
                    qty={cartQty[item.id] || 0}
                    index={idx}
                    onOpen={(x) => router.push(`/product/${x.id}` as any)}
                    onAdd={addToCart}
                    onDecrement={decrement}
                  />
                ))}
              </View>
            )}
          </View>
        ) : (
        <>
          <FadeSlideIn triggerKey={`shop-${refreshTick}-${loading ? "l" : "d"}`}>
            <ShopLayoutRenderer
              scope="home"
              category={activeCategory && activeCategory !== "all" ? activeCategory : undefined}
              pincode={deliveryPincode || undefined}
              lat={deliveryCoords?.lat}
              lng={deliveryCoords?.lng}
              refreshTick={refreshTick}
              onProductPress={(id) => router.push(`/product/${id}` as any)}
              onCategoryPress={(c) => {
                if (!c) router.push(`${categoryRoutePrefix}/shop` as any);
                else if (/recharge/i.test(c)) router.push("/recharge" as any);
                else router.push(`${categoryRoutePrefix}/shop-category/${encodeURIComponent(c)}` as any);
              }}
              // Jun 2026 BUGFIX: this used to POST /cart {quantity} — an
              // endpoint that doesn't exist (it's /cart/add {qty}) — so the
              // Add buttons inside admin layout blocks silently did nothing.
              // Now routed through the same cart controller as every other
              // product card.
              onAddToCart={(id) => {
                // Jun 2026 BUGFIX — the "+" on a layout-block card did
                // NOTHING when that product wasn't inside the screen's own
                // (location-limited) `products` list: `find` returned
                // undefined and we silently bailed. Cart add only needs the
                // id, so fall back to a stub.
                const p = products.find((x) => x.id === id);
                addToCart(p || ({ id, name: "Item" } as any));
              }}
              onBlocksResolved={setLayoutBlockCount}
            />
          </FadeSlideIn>
          {/* Jun 2026 — Fallback catalogue.  When an admin hasn't built any
              shop-layout block for this pincode the home used to render
              NOTHING but the search bar, even though nearby vendors had
              stock. Now we show a plain "All products near you" grid. */}
          {!loading && layoutBlockCount === 0 && products.length > 0 ? (
            <View style={{ paddingHorizontal: spacing.screen, paddingTop: 4 }}>
              <View style={styles.searchResultHeader}>
                <Text style={styles.searchResultTitle}>All products near you</Text>
                <Text style={styles.searchResultCount}>
                  {products.length} product{products.length === 1 ? "" : "s"}
                </Text>
              </View>
              <View style={productGridStyles.wrap}>
                {products.map((item, idx) => (
                  <ProductGridCard
                    key={`near-${item.id}`}
                    product={item as any}
                    qty={cartQty[item.id] || 0}
                    index={idx}
                    onOpen={(x) => router.push(`/product/${x.id}` as any)}
                    onAdd={addToCart}
                    onDecrement={decrement}
                  />
                ))}
              </View>
            </View>
          ) : null}
          {/* Jul 2026 — "No vendors nearby" hero card.  When the customer's
              location has zero deliverable products AND the initial /products
              fetch has completed, show the hero below the (mostly empty)
              layout so the customer immediately understands why and what
              to do next. */}
          {!loading && products.length === 0 ? (
            <FadeSlideIn delay={80}>
              <NoVendorsHero location={deliveryPincode || undefined} />
            </FadeSlideIn>
          ) : null}
        </>
        )}
          </>
        )}
      </ScrollView>

      {/* ── Delivery-location picker modal ─────────────────────────────
          Opens when the user taps the "Deliver to {city}" pill in the
          header.  Jul 2026 — Location-first shop: manual pincode entry
          has been removed.  The only way to set / refresh the location
          is via device GPS ("Use my current location"). */}
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
              <Text style={styles.modalTitle}>Delivery location</Text>
            </View>
            <Text style={styles.modalCurrent} numberOfLines={2}>
              Current: <Text style={{ fontWeight: "900", color: colors.textMain }}>{deliveryAddress}</Text>
            </Text>
            <Text style={{ fontSize: 12, color: colors.textMuted, marginTop: 8, lineHeight: 18 }}>
              We use your live GPS to show only products from vendors who
              actually deliver to your area. Tap the button below to
              refresh your position.
            </Text>

            <TouchableOpacity
              onPress={() => refreshLocation(true)}
              disabled={locBusy}
              style={[styles.modalPrimary, locBusy && { opacity: 0.7 }, { marginTop: 14 }]}
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

            {permStatus === "denied" ? (
              <TouchableOpacity
                onPress={() => { try { Linking.openSettings(); } catch { /* ignore */ } }}
                style={[styles.modalPrimary, { backgroundColor: colors.surfaceMuted, marginTop: 10 }]}
                testID="home-loc-open-settings"
              >
                <Feather name="settings" size={15} color={colors.textMain} />
                <Text style={[styles.modalPrimaryText, { color: colors.textMain }]}>Open Settings</Text>
              </TouchableOpacity>
            ) : null}

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
                      if (/recharge/i.test(c.name)) { router.push("/recharge" as any); return; }
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
  // 1. Header — uses spacing.screen so every Shop section aligns to the same
  // left/right rail. Phase: shop visual polish (2026-05-27).
  headerWrap: {
    backgroundColor: colors.background,
    paddingHorizontal: spacing.screen,
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

  // Jun 2026 — Smart-search suggestion dropdown (grouped by product name)
  suggestPanel: {
    marginTop: 8,
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
    ...Platform.select({
      ios: { shadowColor: "#0F2A1D", shadowOpacity: 0.08, shadowRadius: 10, shadowOffset: { width: 0, height: 3 } },
      android: { elevation: 3 },
    }),
  },
  suggestRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 12, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    minHeight: 52,
  },
  suggestThumb: {
    width: 36, height: 36, borderRadius: 8,
    backgroundColor: colors.surfaceMuted,
  },
  suggestName: { fontSize: 13.5, fontWeight: "700", color: colors.textMain },
  suggestMeta: { fontSize: 11.5, color: colors.textMuted, marginTop: 2 },


  // 3. Category circles — same `spacing.screen` left/right rail as the
  // header / banner / grid below, so the row of circles is visually
  // anchored. Was 12 — felt too tight against the screen edge.
  catScroll: { paddingHorizontal: spacing.screen, paddingVertical: 14, gap: spacing.gridGap },

  catItem: { alignItems: "center", width: 72 },
  catCircle: {
    width: 56, height: 56, borderRadius: 28,
    alignItems: "center", justifyContent: "center",
    marginBottom: 6,
  },
  catCircleActive: { backgroundColor: colors.primary },
  catCircleImg: { width: 56, height: 56, borderRadius: 28 },
  catLabel: { fontSize: 11.5, color: colors.textMain, fontWeight: "700", textAlign: "center" },

  // 4. Banner — anchored to the same rail.
  bannerWrap: { paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 4 },
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
  // Horizontal list common padding — same `spacing.screen` rail as the
  // section headers above (so the card aligns to the title), with the
  // canonical gridGap as inter-card spacing.
  hList: { paddingHorizontal: spacing.screen, paddingVertical: 4, gap: spacing.gridGap - 4 },

  // Jun 2026 — "Added to cart" confirmation strip, shown after tapping Add
  // on a search result or the home category grid.
  addedFlash: {
    flexDirection: "row", alignItems: "center", gap: 6,
    alignSelf: "center", marginTop: 8,
    backgroundColor: colors.primary,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    maxWidth: "90%",
  },
  addedFlashText: { fontSize: 11, fontWeight: "800", color: "#fff", letterSpacing: 0.2 },

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
    width: "46%",
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
  // Phase: shop visual polish (2026-05-27) — uses spacing.gridGap as the
  // canonical row gap so this 3-col grid stays vertically rhythmic with
  // the rest of the page. Horizontal padding intentionally omitted: the
  // outer scroll container already supplies it via styles.hList, keeping
  // the grid's first/last items flush with the section title above.
  allCatGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    paddingVertical: 6,
    rowGap: spacing.gridGap,
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
