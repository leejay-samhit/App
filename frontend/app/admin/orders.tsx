import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity, Image, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type AdminOrder = {
  id: string;
  user_id: string;
  total: number;
  status: string;
  created_at: string;
  items: { name: string; price: number; image_url: string; qty: number }[];
};

const STATUSES = ["placed", "shipped", "delivered", "cancelled"] as const;
const STATUS_COLORS: Record<string, string> = { placed: colors.warning, shipped: colors.brand500, delivered: colors.success, cancelled: "#B3261E" };

export default function AdminOrders() {
  const router = useRouter();
  const [items, setItems] = useState<AdminOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const url = filter === "all" ? "/admin/orders" : `/admin/orders?status=${filter}`;
      const { data } = await api.get<AdminOrder[]>(url);
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const setStatus = async (orderId: string, status: string) => {
    setBusy(orderId);
    try {
      await api.patch(`/admin/orders/${orderId}/status`, { status });
      await load();
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally { setBusy(null); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="orders-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Orders</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={styles.tabs}>
        {["all", ...STATUSES].map((t) => (
          <TouchableOpacity key={t} onPress={() => setFilter(t)} style={[styles.tab, filter === t && styles.tabActive]} testID={`order-tab-${t}`}>
            <Text style={[styles.tabText, filter === t && styles.tabTextActive]}>{t.toUpperCase()}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`order-${item.id}`}>
              <View style={styles.cardTop}>
                <View>
                  <Text style={styles.orderId}>#{item.id.slice(0, 8).toUpperCase()}</Text>
                  <Text style={styles.orderDate}>{new Date(item.created_at).toLocaleString()}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: STATUS_COLORS[item.status] || colors.textMuted }]}>
                  <Text style={styles.pillText}>{item.status.toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.divider} />
              {item.items.slice(0, 3).map((it, idx) => (
                <View key={idx} style={styles.itemRow}>
                  <Image source={{ uri: it.image_url }} style={styles.itemImage} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.itemName} numberOfLines={1}>{it.name}</Text>
                    <Text style={styles.itemQty}>{formatINR(it.price)} × {it.qty}</Text>
                  </View>
                </View>
              ))}
              <View style={styles.divider} />
              <View style={styles.totalRow}>
                <Text style={styles.totalLabel}>Order total</Text>
                <Text style={styles.totalValue}>{formatINR(item.total)}</Text>
              </View>

              <View style={styles.actions}>
                {item.status === "placed" && (
                  <TouchableOpacity onPress={() => setStatus(item.id, "shipped")} disabled={busy === item.id} style={styles.smallBtn} testID={`order-ship-${item.id}`}>
                    <Feather name="truck" size={14} color={colors.primary} />
                    <Text style={styles.smallBtnText}>Mark shipped</Text>
                  </TouchableOpacity>
                )}
                {item.status === "shipped" && (
                  <TouchableOpacity onPress={() => setStatus(item.id, "delivered")} disabled={busy === item.id} style={styles.smallBtn} testID={`order-deliver-${item.id}`}>
                    <Feather name="check-circle" size={14} color={colors.primary} />
                    <Text style={styles.smallBtnText}>Mark delivered</Text>
                  </TouchableOpacity>
                )}
                {(item.status === "placed" || item.status === "shipped") && (
                  <TouchableOpacity onPress={() => setStatus(item.id, "cancelled")} disabled={busy === item.id} style={[styles.smallBtn, { borderColor: "#B3261E" }]} testID={`order-cancel-${item.id}`}>
                    <Feather name="x-circle" size={14} color="#B3261E" />
                    <Text style={[styles.smallBtnText, { color: "#B3261E" }]}>Cancel & refund</Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No orders match this filter</Text>}
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
  tabs: { flexDirection: "row", marginHorizontal: spacing.screen, backgroundColor: colors.surfaceMuted, borderRadius: 99, padding: 4, gap: 2, marginBottom: 8 },
  tab: { flex: 1, paddingVertical: 6, alignItems: "center", borderRadius: 99 },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 9, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.5 },
  tabTextActive: { color: colors.primaryFg },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 10 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  orderId: { fontSize: 13, fontWeight: "800", color: colors.textMain, letterSpacing: 1 },
  orderDate: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  pillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 10 },
  itemRow: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 3 },
  itemImage: { width: 32, height: 32, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  itemName: { fontSize: 12, fontWeight: "600", color: colors.textMain },
  itemQty: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  totalLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  totalValue: { fontSize: 16, fontWeight: "800", color: colors.primary },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 12 },
  smallBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: colors.primary },
  smallBtnText: { fontSize: 11, fontWeight: "700", color: colors.primary },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
});
