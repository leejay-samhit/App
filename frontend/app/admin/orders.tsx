import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity, Image, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { downloadOrdersCsv } from "../../src/exportOrdersCsv";

type AdminOrder = {
  id: string;
  user_id: string;
  total: number;
  status: string;
  created_at: string;
  items: { name: string; price: number; image_url: string; qty: number }[];
  // Optional buyer/vendor fields the backend may include for admin views.
  buyer_name?: string; buyer_email?: string; buyer_phone?: string;
  vendor_id?: string; vendor_name?: string; vendor_email?: string; vendor_phone?: string;
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
  const [exporting, setExporting] = useState(false);

  // Sept 2026 — Excel-style download.  Owner asked for the same export
  // on both admin + vendor order screens with these exact columns:
  //   User Name · Mobile · Product Name · Amount · Stage · Vendor Name
  //   · Vendor Mail · Vendor Mobile.
  // We generate CSV client-side (opens in Excel/Numbers/Sheets natively)
  // instead of a heavyweight XLSX lib.  Web dev's export endpoint returns
  // the same schema so admin + vendor stay in sync.
  const onExport = async () => {
    if (items.length === 0) {
      Alert.alert("Nothing to export", "The current filter has no orders.");
      return;
    }
    setExporting(true);
    try {
      await downloadOrdersCsv(items, {
        title: `slangcart-admin-orders-${filter}`,
        scope: "admin",
      });
    } catch (e) {
      Alert.alert("Export failed", formatApiError(e));
    } finally { setExporting(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="orders-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Orders</Text>
        <TouchableOpacity onPress={onExport} disabled={exporting || items.length === 0} style={[styles.exportBtn, (exporting || items.length === 0) && { opacity: 0.5 }]} testID="orders-export">
          {exporting
            ? <ActivityIndicator color={colors.primary} size="small" />
            : <><Feather name="download" size={14} color={colors.primary} /><Text style={styles.exportBtnText}>CSV</Text></>}
        </TouchableOpacity>
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
                {/* Sept 2026 — Admin is now READONLY on status. Vendors
                    control the fulfilment lifecycle from their own Orders
                    screen. This block just shows the current stage in a
                    non-interactive tracker. */}
                <View style={styles.stageTracker} testID={`order-stage-${item.id}`}>
                  {STATUSES.map((s, i) => {
                    const activeIdx = STATUSES.indexOf(item.status as any);
                    const done = activeIdx >= 0 && i <= activeIdx && item.status !== "cancelled";
                    const isCancelled = item.status === "cancelled" && s === "cancelled";
                    return (
                      <View key={s} style={styles.stageStep}>
                        <View style={[styles.stageDot, (done || isCancelled) && { backgroundColor: STATUS_COLORS[s] || colors.primary, borderColor: STATUS_COLORS[s] || colors.primary }]}>
                          {(done || isCancelled) ? <Feather name={s === "cancelled" ? "x" : "check"} size={9} color="#fff" /> : null}
                        </View>
                        <Text style={[styles.stageLabel, (done || isCancelled) && { color: STATUS_COLORS[s], fontWeight: "800" }]}>{s}</Text>
                      </View>
                    );
                  })}
                </View>
                {busy === item.id ? <ActivityIndicator size="small" color={colors.primary} /> : null}
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
  // Sept 2026 — Readonly stage-tracker for admin.
  exportBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface },
  exportBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  stageTracker: { flexDirection: "row", justifyContent: "space-between", flex: 1, gap: 4 },
  stageStep: { flex: 1, alignItems: "center", gap: 4 },
  stageDot: { width: 16, height: 16, borderRadius: 8, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  stageLabel: { fontSize: 9, color: colors.textMuted, letterSpacing: 0.3, textTransform: "uppercase", fontWeight: "700" },
});
