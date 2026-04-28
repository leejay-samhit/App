import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, FlatList, Image, TouchableOpacity, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "../src/api";
import { colors, radii, spacing, formatINR } from "../src/theme";

type Order = {
  id: string;
  total: number;
  status: string;
  created_at: string;
  items: { name: string; price: number; image_url: string; qty: number }[];
};

export default function OrdersScreen() {
  const router = useRouter();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Order[]>("/orders/me");
      setOrders(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="orders-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>My orders</Text>
        <View style={{ width: 40 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : orders.length === 0 ? (
        <View style={styles.empty}>
          <Feather name="package" size={36} color={colors.textMuted} />
          <Text style={styles.emptyTitle}>No orders yet</Text>
          <Text style={styles.emptyText}>Your purchases will appear here.</Text>
        </View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
          data={orders}
          keyExtractor={(o) => o.id}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`order-${item.id}`}>
              <View style={styles.cardTop}>
                <View>
                  <Text style={styles.orderId}>#{item.id.slice(0, 8).toUpperCase()}</Text>
                  <Text style={styles.orderDate}>{new Date(item.created_at).toLocaleString()}</Text>
                </View>
                <View style={styles.statusPill}>
                  <Text style={styles.statusPillText}>{item.status.toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.divider} />
              {item.items.map((it, idx) => (
                <View key={idx} style={styles.itemRow}>
                  <Image source={{ uri: it.image_url }} style={styles.itemImage} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.itemName} numberOfLines={1}>{it.name}</Text>
                    <Text style={styles.itemQty}>{formatINR(it.price)} × {it.qty}</Text>
                  </View>
                  <Text style={styles.itemTotal}>{formatINR(it.price * it.qty)}</Text>
                </View>
              ))}
              <View style={styles.divider} />
              <View style={styles.totalRow}>
                <Text style={styles.totalLabel}>Paid via wallet</Text>
                <Text style={styles.totalValue}>{formatINR(item.total)}</Text>
              </View>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40, gap: 6 },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 12 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  orderId: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: 1 },
  orderDate: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  statusPill: { backgroundColor: colors.success, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  statusPillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 12 },
  itemRow: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 4 },
  itemImage: { width: 36, height: 36, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  itemName: { fontSize: 13, fontWeight: "600", color: colors.textMain },
  itemQty: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  itemTotal: { fontSize: 13, fontWeight: "700", color: colors.primary },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  totalLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  totalValue: { fontSize: 18, fontWeight: "800", color: colors.primary, letterSpacing: -0.3 },
});
