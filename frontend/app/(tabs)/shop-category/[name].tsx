// Dynamic Category Page — fully rendered from admin-managed `shop_layout`
// blocks where scope="category" and scope_category=<name>. Falls back to a
// plain product grid filtered by category if no admin layout exists.
import { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, Image, ActivityIndicator, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../../src/api";
import { colors, radii, spacing, formatINR } from "../../../src/theme";
import { ShopLayoutRenderer } from "../../../src/shop-layout-renderer";
import { useAuth } from "../../../src/auth";

type Product = { id: string; name: string; price: number; image_url?: string; stock?: number; is_in_stock?: boolean; category?: string; sub_category?: string; vendor_id?: string | null };

export default function ShopCategoryScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ name?: string }>();
  const category = String(params?.name || "");
  // UPDATE 1 — Hide the current vendor's own products from themselves.
  const { user } = useAuth();
  const currentUserId = user?.id || null;
  const [refreshing, setRefreshing] = useState(false);
  const [hasLayout, setHasLayout] = useState<boolean | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [addingId, setAddingId] = useState<string | null>(null);
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

  const load = useCallback(async () => {
    try {
      // Check if admin has configured a layout for this category
      const lay = await api.get<{ items: any[] }>("/shop-layout", { params: { scope: "category", category } });
      const blocks = lay.data?.items || [];
      setHasLayout(blocks.length > 0);
    } catch { setHasLayout(false); }
    try {
      // ── Nov 2026 — Server-side cascade filter ──
      // Passing `?category=<name>` triggers the backend to walk the
      // category tree (parent + all descendants) and return every
      // matching product in a single query — instant compared to
      // downloading the full catalogue and filtering client-side.
      // When a sub-category chip is selected, further narrow by that
      // slug on the backend as well.
      const params: Record<string, any> = { category, limit: 120 };
      if (selectedSub) params.subcategory = selectedSub;
      const r = await api.get<any>("/products", { params });
      const list: Product[] = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setProducts(
        list.filter((p: any) => {
          // Belt-and-braces: still hide the vendor's own products from
          // themselves even though the server cascade already did the
          // category work.
          if (currentUserId && p.vendor_id && p.vendor_id === currentUserId) return false;
          return true;
        }),
      );
    } catch (e) { /* silent */ }
    finally { setLoadingProducts(false); setRefreshing(false); }
  }, [category, currentUserId, selectedSub]);

  // Nov 2026 — resolve the parent category by name and fetch its admin-
  // managed subcategories so we can show REAL nested chips.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const tree = await api.get<{ items: any[] }>("/shop-categories/tree");
        if (cancelled) return;
        const walk = (nodes: any[], target: string): any | null => {
          const t = target.trim().toLowerCase();
          for (const n of nodes) {
            if ((n.name || "").trim().toLowerCase() === t) return n;
            const inner = walk(n.children || [], target);
            if (inner) return inner;
          }
          return null;
        };
        const node = walk(tree.data?.items || [], category);
        const subs = (node?.children || []).map((c: any) => ({ id: c.id, name: c.name }));
        setAdminSubs(subs);
      } catch {
        setAdminSubs([]);
      }
    })();
    return () => { cancelled = true; };
  }, [category]);

  useEffect(() => { load(); }, [load]);

  const onAddToCart = async (p: Product) => {
    if (addingId) return;
    setAddingId(p.id);
    try {
      await api.post("/cart/add", { product_id: p.id, qty: 1 });
      Alert.alert("Added to cart", `${p.name} added.`, [
        { text: "Keep shopping", style: "cancel" },
        { text: "View cart", onPress: () => router.push("/cart" as any) },
      ]);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setAddingId(null); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerEyebrow}>CATEGORY</Text>
          <Text style={styles.headerTitle} numberOfLines={1}>{category || "All"}</Text>
        </View>
        <TouchableOpacity onPress={() => router.push("/cart")} style={styles.iconBtn}>
          <Feather name="shopping-cart" size={18} color={colors.textMain} />
        </TouchableOpacity>
      </View>

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
          const subs: string[] = adminSubs.length > 0
            ? adminSubs.map((s) => s.name)
            : Array.from(new Set(products.map((p) => (p.sub_category || "").trim()).filter(Boolean)))
                .sort((a, b) => a.localeCompare(b));
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
          refreshTick={refreshTick}
          onProductPress={(id) => router.push(`/product/${id}` as any)}
          onCategoryPress={(c) => router.push(`/shop-category/${encodeURIComponent(c)}` as any)}
        />

        {/* Fallback / supplementary product grid — wrapped in horizontal
            padding so it matches Shop-home's card sections. */}
        <View style={{ paddingHorizontal: spacing.screen, paddingTop: spacing.screen }}>
        {/* Aug 2026 — Flash-of-empty fix: only render the empty state
            AFTER we've confirmed the admin has NO layout for this category
            AND the product query has finished.  Previously the "No products"
            card briefly flashed while ShopLayoutRenderer was still fetching
            its blocks — hasLayout was still `null` and products was still `[]`. */}
        {loadingProducts || hasLayout === null ? (
          <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
        ) : hasLayout === false && products.length === 0 ? (
          <View style={styles.emptyCard}>
            <Feather name="shopping-bag" size={28} color={colors.textMuted} />
            <Text style={styles.emptyText}>No products in {category}</Text>
          </View>
        ) : hasLayout === false ? (
          (() => {
            // Nov 2026 — server already filtered by subcategory when
            // `selectedSub` is set (see load()).  Show products as-is.
            const filtered = products;
            if (filtered.length === 0) {
              return (
                <View style={styles.emptyCard}>
                  <Feather name="filter" size={24} color={colors.textMuted} />
                  <Text style={styles.emptyText}>
                    {selectedSub ? `No products in "${selectedSub}"` : `No products in ${category}`}
                  </Text>
                  {selectedSub ? (
                    <TouchableOpacity onPress={() => setSelectedSub("")} style={{ marginTop: 4 }}>
                      <Text style={{ fontSize: 12, color: colors.primary, fontWeight: "700" }}>Clear filter</Text>
                    </TouchableOpacity>
                  ) : null}
                </View>
              );
            }
            return (
              <View style={styles.gridWrap}>
                {filtered.map((p) => {
              const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
              return (
                <View key={p.id} style={[styles.gridCard, !inStock && { opacity: 0.55 }]}>
                  <TouchableOpacity activeOpacity={0.85} onPress={() => router.push(`/product/${p.id}` as any)}>
                    <Image source={{ uri: p.image_url }} style={styles.gridImg} resizeMode="cover" />
                  </TouchableOpacity>
                  <View style={{ padding: 10 }}>
                    <TouchableOpacity activeOpacity={0.85} onPress={() => router.push(`/product/${p.id}` as any)}>
                      <Text style={styles.gridName} numberOfLines={2}>{p.name}</Text>
                    </TouchableOpacity>
                    <View style={styles.gridFooter}>
                      <Text style={styles.gridPrice}>{formatINR(p.price)}</Text>
                      {inStock ? (
                        <TouchableOpacity
                          style={[styles.addBtn, addingId === p.id && { opacity: 0.6 }]}
                          onPress={() => onAddToCart(p)}
                          disabled={addingId === p.id}
                          testID={`add-${p.id}`}
                        >
                          {addingId === p.id
                            ? <ActivityIndicator color="#fff" size="small" />
                            : (
                              <>
                                <Feather name="shopping-bag" size={12} color="#fff" />
                                <Text style={styles.addBtnText}>Add</Text>
                              </>
                            )}
                        </TouchableOpacity>
                      ) : (
                        <View style={[styles.addBtn, { backgroundColor: "#B91C1C" }]}>
                          <Text style={styles.addBtnText}>SOLD OUT</Text>
                        </View>
                      )}
                    </View>
                  </View>
                </View>
              );
            })}
              </View>
            );
          })()
        ) : null}
        </View>
      </ScrollView>
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
  gridWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  gridCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  gridImg: { width: "100%", aspectRatio: 1.1, backgroundColor: colors.surfaceMuted },
  gridName: { fontSize: 12, fontWeight: "700", color: colors.textMain, minHeight: 30, lineHeight: 15 },
  gridPrice: { fontSize: 14, fontWeight: "900", color: colors.primary },
  gridFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.primary, minHeight: 28 },
  addBtnText: { fontSize: 11, fontWeight: "800", color: "#fff", letterSpacing: 0.3 },
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
