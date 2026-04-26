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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Product = {
  id: string;
  name: string;
  price: number;
  image_url: string;
  description?: string;
};

export default function ShopScreen() {
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Product[]>("/products");
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <Text style={styles.overline}>SHOP</Text>
        <Text style={styles.h1}>Member store</Text>
        <Text style={styles.subtitle}>Exclusive products & rewards. Coming soon — preview catalog.</Text>

        <View style={styles.grid}>
          {items.map((p) => (
            <View key={p.id} style={styles.card} testID={`product-${p.id}`}>
              <Image source={{ uri: p.image_url }} style={styles.image} />
              <Text style={styles.name} numberOfLines={2}>{p.name}</Text>
              <View style={styles.cardFooter}>
                <Text style={styles.price}>{formatINR(p.price)}</Text>
                <TouchableOpacity style={styles.addBtn} testID={`product-add-${p.id}`}>
                  <Feather name="plus" size={16} color={colors.primaryFg} />
                </TouchableOpacity>
              </View>
            </View>
          ))}
        </View>

        <View style={styles.banner}>
          <Feather name="info" size={16} color={colors.textMuted} />
          <Text style={styles.bannerText}>Cart & checkout will be enabled in the next release.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  subtitle: { fontSize: 14, color: colors.textMuted, marginTop: 6, marginBottom: 24 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  card: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 18, overflow: "hidden", padding: 10 },
  image: { width: "100%", height: 130, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  name: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginTop: 10, minHeight: 34 },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
  price: { fontSize: 15, fontWeight: "800", color: colors.primary },
  addBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  banner: { flexDirection: "row", alignItems: "center", gap: 8, padding: 14, marginTop: 20, backgroundColor: colors.surfaceMuted, borderRadius: 14 },
  bannerText: { fontSize: 12, color: colors.textMuted },
});
