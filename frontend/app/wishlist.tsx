// Wishlist — grid of products the current user has saved via the heart icon
// on the product detail page (POST /api/products/{id}/save toggles).
// Tapping a tile opens the product detail; the heart removes it from the list.
import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image,
  ActivityIndicator, RefreshControl, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing, formatINR } from "../src/theme";

type Product = {
  id: string; name: string; price: number;
  image_url?: string; image_data_url?: string;
  brand?: string; category?: string; stock?: number;
};

export default function WishlistScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: Product[]; count: number }>("/me/wishlist");
      setItems(r.data?.items || []);
    } catch (e) {
      Alert.alert("Couldn't load wishlist", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onRemove = async (p: Product) => {
    setRemoving(p.id);
    try {
      // The /save endpoint is a toggle — calling it on an already-saved item
      // removes it from the wishlist.
      await api.post(`/products/${p.id}/save`);
      setItems((prev) => prev.filter((x) => x.id !== p.id));
    } catch (e) {
      Alert.alert("Couldn't remove", formatApiError(e));
    } finally {
      setRemoving(null);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <Header onBack={() => router.back()} count={0} />
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Header onBack={() => router.back()} count={items.length} />

      {items.length === 0 ? (
        <ScrollView
          contentContainerStyle={styles.emptyWrap}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          <View style={styles.emptyIcon}>
            <Feather name="heart" size={40} color={colors.primary} />
          </View>
          <Text style={styles.emptyTitle}>Your wishlist is empty</Text>
          <Text style={styles.emptySub}>
            Tap the heart on any product to save it here for later.
          </Text>
          <TouchableOpacity onPress={() => router.push("/(tabs)/shop" as any)} style={styles.shopBtn} testID="wishlist-go-shop">
            <Feather name="shopping-bag" size={16} color={colors.primaryFg} />
            <Text style={styles.shopBtnText}>Browse the shop</Text>
          </TouchableOpacity>
        </ScrollView>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          <Text style={styles.headerNote}>
            {items.length} saved item{items.length === 1 ? "" : "s"} · pull to refresh
          </Text>
          <View style={styles.grid}>
            {items.map((p) => {
              const oos = (p.stock || 0) === 0;
              const cover = p.image_url || p.image_data_url || "";
              return (
                <TouchableOpacity
                  key={p.id}
                  activeOpacity={0.85}
                  onPress={() => router.push(`/product/${p.id}` as any)}
                  style={styles.card}
                  testID={`wishlist-card-${p.id}`}
                >
                  <View style={styles.imgWrap}>
                    {cover
                      ? <Image source={{ uri: cover }} style={styles.img} />
                      : <View style={[styles.img, { backgroundColor: colors.surfaceMuted }]} />}
                    {oos ? (
                      <View style={styles.oosOverlay} pointerEvents="none">
                        <Text style={styles.oosText}>SOLD OUT</Text>
                      </View>
                    ) : null}
                    <TouchableOpacity
                      onPress={() => onRemove(p)}
                      style={styles.heartBtn}
                      hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                      testID={`wishlist-remove-${p.id}`}
                    >
                      {removing === p.id
                        ? <ActivityIndicator color="#fff" size="small" />
                        : <Feather name="heart" size={14} color="#fff" />}
                    </TouchableOpacity>
                  </View>
                  <View style={styles.body}>
                    {p.brand ? <Text style={styles.brand} numberOfLines={1}>{p.brand}</Text> : (p.category ? <Text style={styles.brand} numberOfLines={1}>{p.category}</Text> : null)}
                    <Text style={styles.name} numberOfLines={2}>{p.name}</Text>
                    <Text style={styles.price}>{formatINR(p.price)}</Text>
                    <TouchableOpacity
                      onPress={() => router.push(`/product/${p.id}` as any)}
                      style={styles.viewBtn}
                      testID={`wishlist-view-${p.id}`}
                    >
                      <Feather name="external-link" size={12} color={colors.primary} />
                      <Text style={styles.viewBtnText}>View product</Text>
                    </TouchableOpacity>
                  </View>
                </TouchableOpacity>
              );
            })}
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function Header({ onBack, count }: { onBack: () => void; count: number }) {
  return (
    <View style={styles.header}>
      <TouchableOpacity onPress={onBack} style={styles.iconBtn} testID="wishlist-back">
        <Feather name="arrow-left" size={20} color={colors.textMain} />
      </TouchableOpacity>
      <View style={{ flex: 1, alignItems: "center" }}>
        <Text style={styles.title}>Wishlist</Text>
        {count > 0 ? <Text style={styles.subTitle}>{count} saved</Text> : null}
      </View>
      <View style={styles.iconBtnSpacer} />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },

  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  subTitle: { fontSize: 11, color: colors.textMuted, marginTop: 1, fontWeight: "600" },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  iconBtnSpacer: { width: 40 },

  headerNote: { fontSize: 11, color: colors.textMuted, marginBottom: 10, fontWeight: "600" },

  // Empty state
  emptyWrap: { padding: 32, alignItems: "center", justifyContent: "center", minHeight: "100%" },
  emptyIcon: {
    width: 80, height: 80, borderRadius: 40,
    backgroundColor: colors.primary + "14",
    alignItems: "center", justifyContent: "center", marginBottom: 16,
  },
  emptyTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  emptySub: { fontSize: 13, color: colors.textMuted, textAlign: "center", marginTop: 6, maxWidth: 280 },
  shopBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 12, paddingHorizontal: 20,
    backgroundColor: colors.primary, borderRadius: radii.button, marginTop: 22,
  },
  shopBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },

  // Grid
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  card: {
    flexBasis: "48%", flexGrow: 1,
    backgroundColor: colors.surface, borderRadius: 18, overflow: "hidden",
    borderWidth: 1, borderColor: colors.border,
  },
  imgWrap: { position: "relative", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  img: { width: "100%", height: "100%" },
  body: { padding: 12, gap: 3 },
  brand: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.6, textTransform: "uppercase" },
  name: { fontSize: 13, fontWeight: "700", color: colors.textMain, lineHeight: 17, minHeight: 34 },
  price: { fontSize: 15, fontWeight: "800", color: colors.primary, marginTop: 2 },
  viewBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5,
    paddingVertical: 8, borderRadius: 10,
    borderWidth: 1, borderColor: colors.primary,
    marginTop: 8,
  },
  viewBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },

  heartBtn: {
    position: "absolute", top: 8, right: 8,
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: "#E11D48",
    alignItems: "center", justifyContent: "center",
  },
  oosOverlay: {
    position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.5)",
  },
  oosText: {
    fontSize: 12, fontWeight: "900", color: colors.textMain, letterSpacing: 2,
    backgroundColor: "rgba(255,255,255,0.9)",
    paddingHorizontal: 10, paddingVertical: 3, borderRadius: 4, overflow: "hidden",
  },
});
