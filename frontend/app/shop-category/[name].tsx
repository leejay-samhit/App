// Dynamic Category Page — fully rendered from admin-managed `shop_layout`
// blocks where scope="category" and scope_category=<name>. Falls back to a
// plain product grid filtered by category if no admin layout exists.
import { useEffect, useState, useCallback } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, Image, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { ShopLayoutRenderer } from "../../src/shop-layout-renderer";

type Product = { id: string; name: string; price: number; image_url?: string; stock?: number; is_in_stock?: boolean; category?: string };

export default function ShopCategoryScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ name?: string }>();
  const category = String(params?.name || "");
  const [refreshing, setRefreshing] = useState(false);
  const [hasLayout, setHasLayout] = useState<boolean | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loadingProducts, setLoadingProducts] = useState(true);

  const load = useCallback(async () => {
    try {
      // Check if admin has configured a layout for this category
      const lay = await api.get<{ items: any[] }>("/shop-layout", { params: { scope: "category", category } });
      const blocks = lay.data?.items || [];
      setHasLayout(blocks.length > 0);
    } catch { setHasLayout(false); }
    try {
      // Always preload products for the fallback grid
      const r = await api.get<any>("/products");
      const list: Product[] = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setProducts(list.filter((p) => (p.category || "") === category));
    } catch (e) { /* silent */ }
    finally { setLoadingProducts(false); setRefreshing(false); }
  }, [category]);

  useEffect(() => { load(); }, [load]);

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
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      >
        {/* Admin-managed dynamic layout for this category */}
        <ShopLayoutRenderer
          scope="category"
          category={category}
          onProductPress={(id) => router.push(`/product/${id}` as any)}
          onCategoryPress={(c) => router.push(`/shop-category/${encodeURIComponent(c)}` as any)}
        />

        {/* Fallback / supplementary product grid */}
        {hasLayout === false ? (
          <Text style={styles.hint}>No custom layout for this category yet. Showing all products in this category.</Text>
        ) : null}
        {loadingProducts ? (
          <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
        ) : products.length === 0 ? (
          <View style={styles.emptyCard}>
            <Feather name="shopping-bag" size={28} color={colors.textMuted} />
            <Text style={styles.emptyText}>No products in {category}</Text>
          </View>
        ) : hasLayout === false ? (
          <View style={styles.gridWrap}>
            {products.map((p) => {
              const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
              return (
                <TouchableOpacity key={p.id} style={[styles.gridCard, !inStock && { opacity: 0.55 }]} activeOpacity={0.85} onPress={() => router.push(`/product/${p.id}` as any)}>
                  <Image source={{ uri: p.image_url }} style={styles.gridImg} resizeMode="cover" />
                  <View style={{ padding: 10 }}>
                    <Text style={styles.gridName} numberOfLines={2}>{p.name}</Text>
                    <Text style={styles.gridPrice}>{formatINR(p.price)}</Text>
                  </View>
                </TouchableOpacity>
              );
            })}
          </View>
        ) : null}
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
  gridPrice: { fontSize: 14, fontWeight: "900", color: colors.primary, marginTop: 4 },
});
