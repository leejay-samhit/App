import { useCallback, useState } from "react";
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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Product = {
  id: string;
  name: string;
  price: number;
  image_url: string;
  description?: string;
};

export default function ShopScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Product[]>([]);
  const [cartCount, setCartCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([
        api.get<Product[]>("/products"),
        api.get<{ count: number }>("/cart"),
      ]);
      setItems(p.data);
      setCartCount(c.data.count || 0);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const addToCart = async (p: Product) => {
    setAdding(p.id);
    try {
      await api.post("/cart/add", { product_id: p.id, qty: 1 });
      const { data } = await api.get<{ count: number }>("/cart");
      setCartCount(data.count || 0);
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally {
      setAdding(null);
    }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>SHOP</Text>
            <Text style={styles.h1}>Member store</Text>
          </View>
          <TouchableOpacity onPress={() => router.push("/cart")} style={styles.cartBtn} testID="shop-cart-btn">
            <Feather name="shopping-cart" size={18} color={colors.textMain} />
            {cartCount > 0 && (
              <View style={styles.cartBadge}>
                <Text style={styles.cartBadgeText}>{cartCount > 9 ? "9+" : cartCount}</Text>
              </View>
            )}
          </TouchableOpacity>
        </View>
        <Text style={styles.subtitle}>Pay using your wallet earnings.</Text>

        <View style={styles.grid}>
          {items.map((p) => (
            <View key={p.id} style={styles.card} testID={`product-${p.id}`}>
              <Image source={{ uri: p.image_url }} style={styles.image} />
              <Text style={styles.name} numberOfLines={2}>{p.name}</Text>
              <View style={styles.cardFooter}>
                <Text style={styles.price}>{formatINR(p.price)}</Text>
                <TouchableOpacity
                  style={[styles.addBtn, adding === p.id && { opacity: 0.5 }]}
                  onPress={() => addToCart(p)}
                  disabled={adding === p.id}
                  testID={`product-add-${p.id}`}
                >
                  {adding === p.id ? (
                    <ActivityIndicator color={colors.primaryFg} size="small" />
                  ) : (
                    <Feather name="plus" size={16} color={colors.primaryFg} />
                  )}
                </TouchableOpacity>
              </View>
            </View>
          ))}
        </View>

        {cartCount > 0 && (
          <TouchableOpacity onPress={() => router.push("/cart")} style={styles.checkoutBar} testID="shop-go-checkout">
            <Feather name="shopping-cart" size={18} color={colors.accentFg} />
            <Text style={styles.checkoutBarText}>{cartCount} item{cartCount > 1 ? "s" : ""} in cart</Text>
            <Feather name="arrow-right" size={18} color={colors.accentFg} />
          </TouchableOpacity>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  cartBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  cartBadge: { position: "absolute", top: -2, right: -2, minWidth: 20, height: 20, borderRadius: 10, backgroundColor: colors.accent, alignItems: "center", justifyContent: "center", paddingHorizontal: 5 },
  cartBadgeText: { color: colors.accentFg, fontSize: 10, fontWeight: "800" },
  subtitle: { fontSize: 14, color: colors.textMuted, marginTop: 6, marginBottom: 24 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  card: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 18, overflow: "hidden", padding: 10 },
  image: { width: "100%", height: 130, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  name: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginTop: 10, minHeight: 34 },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
  price: { fontSize: 15, fontWeight: "800", color: colors.primary },
  addBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  checkoutBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, backgroundColor: colors.accent, paddingVertical: 14, borderRadius: radii.button, marginTop: 24 },
  checkoutBarText: { color: colors.accentFg, fontWeight: "700", fontSize: 15, flex: 1, textAlign: "center" },
});
