// Dynamic Category Page — fully rendered from admin-managed `shop_layout`
// blocks where scope="category" and scope_category=<name>. Falls back to a
// plain product grid filtered by category if no admin layout exists.
import { useEffect, useState, useCallback, useMemo } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { colors, radii, spacing } from "../../../src/theme";
import { ShopLayoutRenderer } from "../../../src/shop-layout-renderer";
import { useAuth } from "../../../src/auth";
import { useDeliveryLocation } from "../../../src/use-delivery-location";
import { useSwipePager } from "../../../src/use-swipe-pager";
import { useShopCart } from "../../../src/use-shop-cart";
import { ProductGridCard, productGridStyles } from "../../../src/product-grid-card";
import { NoVendorsHero } from "../../../src/no-vendors-hero";
import { ProductCardSkeleton } from "../../../src/anim";
import { cachedGet } from "../../../src/cachedGet";

type Product = { id: string; name: string; price: number; image_url?: string; stock?: number; is_in_stock?: boolean; category?: string; sub_category?: string; vendor_id?: string | null };

export default function ShopCategoryScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ name?: string }>();
  const category = String(params?.name || "");
  // UPDATE 1 — Hide the current vendor's own products from themselves.
  const { user } = useAuth();
  const currentUserId = user?.id || null;
  // Aug 2026 → Jul 2026 — Read the customer's delivery location so category
  // pages honour the same strict location gate as the main shop.
  const { pincode: deliveryPincode, coords: deliveryCoords, hasLocation } = useDeliveryLocation();
  const [refreshing, setRefreshing] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  // Aug 2026 — Bumped on every pull-to-refresh; passed down to
  // ShopLayoutRenderer so it re-fetches its admin-managed blocks live.
  const [refreshTick, setRefreshTick] = useState(0);
  // Sept 2026 — Cascading sub-category filter.  When the user taps a
  // sub-category chip at the top of the category screen, we filter the
  // product grid to only products that carry that sub_category value.
  // "" means "show everything in this category".
  const [selectedSub, setSelectedSub] = useState<string>("");
  // Nov 2026 — admin-managed subcategories (from `/shop-categories/{id}/subcategories`
  // once we've resolved the parent by name).  Falls back to the distinct
  // `product.sub_category` values if the admin hasn't split the tree yet.
  const [adminSubs, setAdminSubs] = useState<{ id: string; name: string }[]>([]);
  // Jun 2026 — Sibling categories at the same tree depth, used by the
  // left/right swipe gesture to hop between categories without going back.
  const [siblings, setSiblings] = useState<string[]>([]);

  const load = useCallback(async (options?: { silent?: boolean }) => {
    // Dec 2026 — Latency killer.  Previously each mount fired 3 sequential
    // network calls (layout → tree → products) and every subcategory chip
    // tap re-fetched /products from scratch, so the grid flashed empty for
    // 500-1500ms every time.
    //
    // New flow:
    //   • cachedGet with SWR — cached copy paints instantly, network
    //     revalidates in the background and updates state via `onFresh`.
    //   • All three calls fire in parallel — no waterfall.
    //   • Subcategory chip tap is 100% client-side (see filtered useMemo
    //     below) — zero network round-trip.
    if (!options?.silent) setLoadingProducts(true);
    // NOTE (Jun 2026): we used to also fetch /shop-layout here just to set a
    // `hasLayout` flag that nothing read. <ShopLayoutRenderer> fetches its own
    // blocks, so that was a duplicate request on every category open — removed.

    // Skip products fetch entirely when no location signals — hero card
    // handles the empty state.
    if (!deliveryPincode && !deliveryCoords) {
      setProducts([]); setLoadingProducts(false); setRefreshing(false); return;
    }

    // Products — 60 s TTL.  Fetch WITHOUT subcategory filter — the chip
    // strip narrows client-side so tapping between chips is instant.
    const params: Record<string, any> = { category, limit: 240, strict_location: "true" };
    if (deliveryPincode) params.pincode = deliveryPincode;
    if (deliveryCoords) { params.lat = deliveryCoords.lat; params.lng = deliveryCoords.lng; }
    const applyList = (data: any) => {
      const list: Product[] = Array.isArray(data) ? data : (data?.items || []);
      setProducts(
        list.filter((p: any) => {
          if (currentUserId && p.vendor_id && p.vendor_id === currentUserId) return false;
          return true;
        }),
      );
      setLoadingProducts(false);
      setRefreshing(false);
    };
    cachedGet<any>("/products", {
      ttlMs: 60_000,
      params,
      onFresh: applyList,
    }).then((cached) => {
      if (cached) applyList(cached);
    }).catch(() => { setLoadingProducts(false); setRefreshing(false); });
  }, [category, currentUserId, deliveryPincode, deliveryCoords]);

  // Dec 2026 — Client-side subcategory filter.  Zero network calls on
  // chip tap.  Cascades product.sub_category (case-insensitive).
  const filtered = useMemo(() => {
    if (!selectedSub) return products;
    const target = selectedSub.trim().toLowerCase();
    return products.filter((p) => (p.sub_category || "").trim().toLowerCase() === target
      || (p.category || "").trim().toLowerCase() === target);
  }, [products, selectedSub]);

  // Nov 2026 — resolve the parent category by name and fetch its admin-
  // managed subcategories so we can show REAL nested chips.
  // Dec 2026 — Uses cachedGet with 10 min TTL so switching between
  // categories doesn't re-fetch the tree every time.
  useEffect(() => {
    let cancelled = false;
    const apply = (tree: any) => {
      if (cancelled || !tree) return;
      const walk = (nodes: any[], target: string): any | null => {
        const t = target.trim().toLowerCase();
        for (const n of nodes) {
          if ((n.name || "").trim().toLowerCase() === t) return n;
          const inner = walk(n.children || [], target);
          if (inner) return inner;
        }
        return null;
      };
      const node = walk(tree.items || [], category);
      const subs = (node?.children || []).map((c: any) => ({ id: c.id, name: c.name }));
      setAdminSubs(subs);

      // Jun 2026 — Find the list this category belongs to (its parent's
      // children, or the tree root) so swiping can move to the neighbour.
      const findSiblings = (nodes: any[]): string[] | null => {
        const t = category.trim().toLowerCase();
        if (nodes.some((n) => (n.name || "").trim().toLowerCase() === t)) {
          return nodes.map((n) => String(n.name || "")).filter(Boolean);
        }
        for (const n of nodes) {
          const found = findSiblings(n.children || []);
          if (found) return found;
        }
        return null;
      };
      setSiblings(findSiblings(tree.items || []) || []);
    };
    cachedGet<{ items: any[] }>("/shop-categories/tree", {
      ttlMs: 600_000,
      onFresh: apply,
    }).then((cached) => { if (cached) apply(cached); });
    return () => { cancelled = true; };
  }, [category]);

  useEffect(() => { load(); }, [load]);

  // Jun 2026 — Shared cart controller (same optimistic add / stepper
  // behaviour as search results and the home grid).
  const { cartCount, cartQty, addedFlash, addToCart: onAddToCart, decrement: onDecrement } = useShopCart();

  // Jun 2026 — SWIPE NAVIGATION.  A left/right flick walks a single
  // conceptual list: [All, sub-1, sub-2, …] for the current category.
  // Sub-category hops are instant (client-side filter, zero network), and
  // once you flick past either end you land on the neighbouring sibling
  // category — so browsing the whole catalogue never needs a back-tap.
  const subNames = useMemo<string[]>(() => (
    adminSubs.length > 0
      ? adminSubs.map((s) => s.name)
      : Array.from(new Set(products.map((p) => (p.sub_category || "").trim()).filter(Boolean)))
          .sort((a, b) => a.localeCompare(b))
  ), [adminSubs, products]);

  const swipeStep = useCallback((dir: 1 | -1) => {
    const chain = ["", ...subNames];
    const nextIdx = chain.indexOf(selectedSub) + dir;
    if (nextIdx >= 0 && nextIdx < chain.length) {
      setSelectedSub(chain[nextIdx]);
      return;
    }
    const ci = siblings.findIndex((s) => s.trim().toLowerCase() === category.trim().toLowerCase());
    const neighbour = ci >= 0 ? siblings[ci + dir] : undefined;
    if (neighbour) {
      router.replace(`/shop-category/${encodeURIComponent(neighbour)}` as any);
    }
  }, [subNames, selectedSub, siblings, category, router]);

  const swipeHandlers = useSwipePager({
    onNext: () => swipeStep(1),
    onPrev: () => swipeStep(-1),
  });

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerEyebrow}>
            {siblings.length > 1 || subNames.length > 0 ? "SWIPE ↔ CATEGORY" : "CATEGORY"}
          </Text>
          <Text style={styles.headerTitle} numberOfLines={1}>{category || "All"}</Text>
        </View>
        <TouchableOpacity onPress={() => router.push("/cart")} style={styles.iconBtn} testID="cat-cart-btn">
          <Feather name="shopping-cart" size={18} color={colors.textMain} />
          {cartCount > 0 ? (
            <View style={styles.cartBadge}>
              <Text style={styles.cartBadgeText}>{cartCount > 99 ? "99+" : String(cartCount)}</Text>
            </View>
          ) : null}
        </TouchableOpacity>
      </View>
      {/* Dec 2026 — Inline "added" strip; auto-fades in 1.6 s.  No blocking Alert. */}
      {addedFlash ? (
        <View style={styles.addedFlash} pointerEvents="none">
          <Feather name="check-circle" size={13} color="#fff" />
          <Text style={styles.addedFlashText} numberOfLines={1}>{addedFlash}</Text>
        </View>
      ) : null}

      <View style={{ flex: 1 }} {...swipeHandlers}>
      <ScrollView
        contentContainerStyle={{ paddingBottom: 80 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); setRefreshTick(t => t + 1); load(); }} tintColor={colors.primary} />}
      >
        {/* Sept 2026 — Cascading sub-category chip strip.  Auto-computed
            from `sub_category` values of products in this category.  When
            a chip is selected we filter the fallback product grid, and
            for admin-layout blocks the ShopLayoutRenderer still shows the
            merchandised layout above (unaffected by sub-filter — layout
            targets the parent category, not sub-cats).  Tapping "All"
            clears the filter. */}
        {(() => {
          // Nov 2026 — Prefer admin-managed subcategory list (real tree).
          // Fall back to distinct product.sub_category values if the
          // admin hasn't structured the tree yet.
          const subs = subNames;
          if (subs.length === 0) return null;
          return (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: spacing.screen, paddingVertical: 6, gap: 6 }}
              testID="sub-category-strip"
            >
              <TouchableOpacity
                onPress={() => setSelectedSub("")}
                style={[styles.subChip, selectedSub === "" && styles.subChipActive]}
                testID="sub-chip-all"
              >
                <Text style={[styles.subChipText, selectedSub === "" && styles.subChipTextActive]}>All</Text>
                <View style={[styles.subChipCount, selectedSub === "" && styles.subChipCountActive]}>
                  <Text style={[styles.subChipCountText, selectedSub === "" && styles.subChipCountTextActive]}>{products.length}</Text>
                </View>
              </TouchableOpacity>
              {subs.map((s) => {
                const isActive = selectedSub === s;
                // Count based on current in-memory products (approximate
                // because server-side filter reloads on chip tap).
                const count = products.filter((p) => (p.sub_category || "").trim().toLowerCase() === s.toLowerCase()).length;
                return (
                  <TouchableOpacity
                    key={s}
                    onPress={() => setSelectedSub(isActive ? "" : s)}
                    style={[styles.subChip, isActive && styles.subChipActive]}
                    testID={`sub-chip-${s}`}
                  >
                    <Text style={[styles.subChipText, isActive && styles.subChipTextActive]} numberOfLines={1}>{s}</Text>
                    {count > 0 ? (
                      <View style={[styles.subChipCount, isActive && styles.subChipCountActive]}>
                        <Text style={[styles.subChipCountText, isActive && styles.subChipCountTextActive]}>{count}</Text>
                      </View>
                    ) : null}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          );
        })()}

        {/* Admin-managed dynamic layout for this category.
            Aug 2026 — Fixed padding parity: this ScrollView no longer applies
            `padding: spacing.screen` around the ENTIRE content — the
            ShopLayoutRenderer manages its own section-level padding just
            like the Shop home screen does.  refreshTick propagates the
            parent's pull-to-refresh into the renderer so admin changes
            appear live without app close/reopen. */}
        <ShopLayoutRenderer
          scope="category"
          category={category}
          pincode={deliveryPincode || undefined}
          lat={deliveryCoords?.lat}
          lng={deliveryCoords?.lng}
          refreshTick={refreshTick}
          onProductPress={(id) => router.push(`/product/${id}` as any)}
          onCategoryPress={(c) => router.push(`/shop-category/${encodeURIComponent(c)}` as any)}
          // Jun 2026 — Add buttons inside admin layout blocks were dead here
          // (the prop was never passed). Wired to the shared cart controller.
          onAddToCart={(id) => {
            const p = products.find((x) => x.id === id);
            if (p) onAddToCart(p);
          }}
        />

        {/* Product grid — Dec 2026: ALWAYS renders below the admin's
            layout blocks (not gated by hasLayout).  Admin can drop
            banners without the grid disappearing, and the empty state
            uses the same location-aware NoVendorsHero regardless of
            whether a sub-filter is active. */}
        <View style={{ paddingHorizontal: spacing.screen, paddingTop: spacing.screen }}>
        {loadingProducts ? (
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10, paddingHorizontal: 4 }}>
            {[...Array(6)].map((_, i) => <ProductCardSkeleton key={i} index={i} />)}
          </View>
        ) : products.length === 0 ? (
          !hasLocation ? (
            <View style={styles.emptyCard}>
              <Feather name="map-pin" size={24} color={colors.textMuted} />
              <Text style={styles.emptyText}>Turn on location to see products in your area</Text>
            </View>
          ) : (
            <NoVendorsHero location={deliveryPincode || undefined} compact />
          )
        ) : (
          (() => {
            // Dec 2026 — subcategory filter is applied client-side.
            if (filtered.length === 0) {
              // A sub-filter is active but has no matches.  Show the
              // hero card (matches "we're not live here yet" pattern
              // the user requested) with a compact Clear-filter chip.
              return (
                <View>
                  <NoVendorsHero location={deliveryPincode || undefined} compact />
                  {selectedSub ? (
                    <TouchableOpacity
                      onPress={() => setSelectedSub("")}
                      style={styles.clearFilterCta}
                      testID="clear-subcategory-filter"
                    >
                      <Feather name="x-circle" size={13} color={colors.primary} />
                      <Text style={styles.clearFilterText}>Clear "{selectedSub}" filter</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
              );
            }
            return (
              <View style={productGridStyles.wrap}>
                {filtered.map((p, idx) => (
                  <ProductGridCard
                    key={p.id}
                    product={p}
                    qty={cartQty[p.id] || 0}
                    index={idx}
                    onOpen={(x) => router.push(`/product/${x.id}` as any)}
                    onAdd={onAddToCart}
                    onDecrement={onDecrement}
                  />
                ))}
              </View>
            );
          })()
        )}
        </View>
      </ScrollView>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  headerEyebrow: { fontSize: 10, letterSpacing: 1.6, color: colors.textMuted, fontWeight: "800" },
  headerTitle: { fontSize: 20, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  center: { paddingVertical: 40, alignItems: "center" },
  hint: { fontSize: 11, color: colors.textMuted, marginVertical: 10, fontStyle: "italic", textAlign: "center" },
  emptyCard: { backgroundColor: colors.surface, borderRadius: radii.card, padding: 28, alignItems: "center", borderWidth: 1, borderColor: colors.border, gap: 6 },
  emptyText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  // Dec 2026 — Compact "clear sub-category" CTA shown below the
  // NoVendorsHero when a sub-filter is active but has no results.
  clearFilterCta: {
    flexDirection: "row", alignItems: "center", gap: 6,
    alignSelf: "center", marginTop: 10,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.brand100 || colors.surface,
    borderWidth: 1, borderColor: colors.primary + "33",
  },
  clearFilterText: { fontSize: 12, color: colors.primary, fontWeight: "800", letterSpacing: 0.2 },
  // Dec 2026 — Cart badge + inline added flash strip
  cartBadge: {
    position: "absolute", top: -2, right: -2,
    minWidth: 18, height: 18, borderRadius: 9,
    backgroundColor: "#DC2626", alignItems: "center", justifyContent: "center",
    paddingHorizontal: 4, borderWidth: 2, borderColor: colors.background || "#fff",
  },
  cartBadgeText: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 0.2 },
  addedFlash: {
    flexDirection: "row", alignItems: "center", gap: 6,
    alignSelf: "center", marginTop: 4, marginBottom: 2,
    backgroundColor: colors.primary,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    maxWidth: "90%",
  },
  addedFlashText: { fontSize: 11, fontWeight: "700", color: "#fff", letterSpacing: 0.2 },

  // Sept 2026 — Sub-category chip strip at top of the category screen.
  subChip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, minHeight: 34 },
  subChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  subChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain, letterSpacing: 0.2, maxWidth: 140 },
  subChipTextActive: { color: colors.primaryFg },
  subChipCount: { backgroundColor: colors.surfaceMuted, minWidth: 20, paddingHorizontal: 5, paddingVertical: 1, borderRadius: 999, alignItems: "center" },
  subChipCountActive: { backgroundColor: "rgba(255,255,255,0.25)" },
  subChipCountText: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.2 },
  subChipCountTextActive: { color: colors.primaryFg },
});
