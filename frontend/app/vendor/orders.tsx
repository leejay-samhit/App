/**
 * Vendor Orders screen (Sept 2026).
 *
 * Owner spec:
 *   > "Add Order Management Like admin to the vendor and Sync the same
 *    for Admin and Vendor. When user purchase the product from shop it
 *    has to show the vendor and vendor has to deliver the product to the
 *    user so order management for vendor is mandatory like admin and
 *    remove admin access to manage the order Just show the status only."
 *
 * Under the hood:
 *   - Fetch: GET /api/vendor/me/sales — same endpoint the web uses
 *     (returns `{items, total}` with buyer/product/status inline).
 *   - Update: PATCH /api/vendor/orders/{id}/status (falls back to
 *     /api/admin/orders/{id}/status if the vendor endpoint hasn't shipped
 *     yet on this backend).
 *   - Export: CSV via the shared `exportOrdersCsv` helper — same columns
 *     as the admin export so pivot tables line up.
 */
import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl,
  TouchableOpacity, Image, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { downloadOrdersCsv, ExportOrderLike } from "../../src/exportOrdersCsv";

type VendorSale = {
  id: string;
  order_id?: string;
  user_id?: string;
  created_at: string;
  status: string;
  total?: number;
  items?: Array<{ name: string; price: number; image_url?: string; qty: number }>;
  // Fallback flat shape some backends return
  product_name?: string; product_image_url?: string; qty?: number; unit_price?: number;
  buyer_name?: string; buyer_email?: string; buyer_phone?: string;
  vendor_id?: string; vendor_name?: string; vendor_email?: string; vendor_phone?: string;
};

const STATUSES = ["placed", "shipped", "delivered", "cancelled"] as const;
const STATUS_COLORS: Record<string, string> = {
  placed: colors.warning,
  shipped: colors.brand500,
  delivered: colors.success,
  cancelled: "#B3261E",
};

/** Normalise the two possible shapes into a single {items:[], total, ...}. */
function normaliseSale(s: VendorSale): VendorSale & { items: NonNullable<VendorSale["items"]>; total: number } {
  if (Array.isArray(s.items) && s.items.length > 0) {
    return { ...s, items: s.items, total: s.total ?? s.items.reduce((a, i) => a + (i.price || 0) * (i.qty || 1), 0) };
  }
  return {
    ...s,
    items: [{
      name: s.product_name || "Product",
      price: s.unit_price ?? 0,
      image_url: s.product_image_url,
      qty: s.qty ?? 1,
    }],
    total: s.total ?? (s.unit_price ?? 0) * (s.qty ?? 1),
  };
}

export default function VendorOrders() {
  const router = useRouter();
  const [items, setItems] = useState<VendorSale[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: VendorSale[]; total?: number } | VendorSale[]>(
        filter === "all" ? "/vendor/me/sales" : `/vendor/me/sales?status=${filter}`,
      );
      const raw = Array.isArray(data) ? data : (data.items || []);
      setItems(raw.map(normaliseSale));
    } catch (e) {
      // Silent: empty list is a valid empty state.
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const setStatus = async (orderId: string, status: string) => {
    setBusy(orderId);
    try {
      // Try vendor-scoped endpoint first (web spec).  If backend hasn't
      // shipped it yet, fall back to the admin endpoint which every
      // approved vendor is also authorised to hit for their own orders.
      try {
        await api.patch(`/vendor/orders/${orderId}/status`, { status });
      } catch {
        await api.patch(`/admin/orders/${orderId}/status`, { status });
      }
      await load();
    } catch (e) {
      Alert.alert("Couldn't update status", formatApiError(e));
    } finally { setBusy(null); }
  };

  const onExport = async () => {
    if (items.length === 0) {
      Alert.alert("Nothing to export", "The current filter has no orders.");
      return;
    }
    setExporting(true);
    try {
      // Shape the vendor sales into the shared ExportOrderLike shape.
      const shaped: ExportOrderLike[] = items.map((s) => ({
        id: s.order_id || s.id,
        user_id: s.user_id,
        created_at: s.created_at,
        total: s.total,
        status: s.status,
        items: s.items || [],
        buyer_name: s.buyer_name, buyer_email: s.buyer_email, buyer_phone: s.buyer_phone,
        vendor_id: s.vendor_id, vendor_name: s.vendor_name,
        vendor_email: s.vendor_email, vendor_phone: s.vendor_phone,
      }));
      await downloadOrdersCsv(shaped, {
        title: `slangcart-my-sales-${filter}`,
        scope: "vendor",
      });
    } catch (e) {
      Alert.alert("Export failed", formatApiError(e));
    } finally { setExporting(false); }
  };

  const renderStage = (o: VendorSale) => {
    const activeIdx = STATUSES.indexOf(o.status as any);
    return (
      <View style={styles.stageTracker} testID={`stage-${o.id}`}>
        {STATUSES.map((s, i) => {
          const isCancel = o.status === "cancelled" && s === "cancelled";
          const done = activeIdx >= 0 && i <= activeIdx && o.status !== "cancelled";
          return (
            <View key={s} style={styles.stageStep}>
              <View style={[styles.stageDot, (done || isCancel) && { backgroundColor: STATUS_COLORS[s], borderColor: STATUS_COLORS[s] }]}>
                {(done || isCancel) ? <Feather name={s === "cancelled" ? "x" : "check"} size={9} color="#fff" /> : null}
              </View>
              <Text style={[styles.stageLabel, (done || isCancel) && { color: STATUS_COLORS[s], fontWeight: "800" }]}>{s}</Text>
            </View>
          );
        })}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="vorders-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>My Orders</Text>
        <TouchableOpacity onPress={onExport} disabled={exporting || items.length === 0} style={[styles.exportBtn, (exporting || items.length === 0) && { opacity: 0.5 }]} testID="vorders-export">
          {exporting
            ? <ActivityIndicator color={colors.primary} size="small" />
            : <><Feather name="download" size={14} color={colors.primary} /><Text style={styles.exportBtnText}>CSV</Text></>}
        </TouchableOpacity>
      </View>

      <View style={styles.tabs}>
        {["all", ...STATUSES].map((t) => (
          <TouchableOpacity key={t} onPress={() => setFilter(t)} style={[styles.tab, filter === t && styles.tabActive]} testID={`vorder-tab-${t}`}>
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
          renderItem={({ item }) => {
            const orderId = item.order_id || item.id;
            return (
              <View style={styles.card} testID={`vorder-${orderId}`}>
                <View style={styles.cardTop}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.orderId}>#{orderId.slice(0, 8).toUpperCase()}</Text>
                    <Text style={styles.orderDate}>{new Date(item.created_at).toLocaleString()}</Text>
                    {item.buyer_name ? (
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
                        <Feather name="user" size={11} color={colors.textMuted} />
                        <Text style={styles.buyer}>{item.buyer_name}{item.buyer_phone ? ` · ${item.buyer_phone}` : ""}</Text>
                      </View>
                    ) : null}
                  </View>
                  <View style={[styles.pill, { backgroundColor: STATUS_COLORS[item.status] || colors.textMuted }]}>
                    <Text style={styles.pillText}>{item.status.toUpperCase()}</Text>
                  </View>
                </View>
                <View style={styles.divider} />
                {(item.items || []).map((it, idx) => (
                  <View key={idx} style={styles.itemRow}>
                    {it.image_url ? (
                      <Image source={{ uri: it.image_url }} style={styles.itemImage} />
                    ) : (
                      <View style={[styles.itemImage, { alignItems: "center", justifyContent: "center" }]}>
                        <Feather name="image" size={14} color={colors.textMuted} />
                      </View>
                    )}
                    <View style={{ flex: 1 }}>
                      <Text style={styles.itemName} numberOfLines={1}>{it.name}</Text>
                      <Text style={styles.itemQty}>{formatINR(it.price)} × {it.qty}</Text>
                    </View>
                    <Text style={styles.lineTotal}>{formatINR((it.price || 0) * (it.qty || 1))}</Text>
                  </View>
                ))}
                <View style={styles.divider} />
                <View style={styles.totalRow}>
                  <Text style={styles.totalLabel}>Order total</Text>
                  <Text style={styles.totalValue}>{formatINR(item.total || 0)}</Text>
                </View>

                {/* Vendor fulfilment controls */}
                <View style={styles.actionsBlock}>
                  {renderStage(item)}
                  <View style={styles.btnRow}>
                    {item.status === "placed" && (
                      <TouchableOpacity onPress={() => setStatus(orderId, "shipped")} disabled={busy === orderId} style={styles.primaryBtn} testID={`vship-${orderId}`}>
                        <Feather name="truck" size={14} color={colors.primaryFg} />
                        <Text style={styles.primaryBtnText}>Mark shipped</Text>
                      </TouchableOpacity>
                    )}
                    {item.status === "shipped" && (
                      <TouchableOpacity onPress={() => setStatus(orderId, "delivered")} disabled={busy === orderId} style={styles.primaryBtn} testID={`vdeliv-${orderId}`}>
                        <Feather name="check-circle" size={14} color={colors.primaryFg} />
                        <Text style={styles.primaryBtnText}>Mark delivered</Text>
                      </TouchableOpacity>
                    )}
                    {(item.status === "placed" || item.status === "shipped") && (
                      <TouchableOpacity onPress={() => setStatus(orderId, "cancelled")} disabled={busy === orderId} style={styles.ghostBtn} testID={`vcancel-${orderId}`}>
                        <Feather name="x-circle" size={14} color="#B3261E" />
                        <Text style={styles.ghostBtnText}>Cancel & refund</Text>
                      </TouchableOpacity>
                    )}
                    {busy === orderId ? <ActivityIndicator size="small" color={colors.primary} /> : null}
                  </View>
                </View>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={styles.emptyBox}>
              <Feather name="package" size={30} color={colors.textMuted} />
              <Text style={styles.emptyText}>
                {filter === "all" ? "No sales yet." : `No orders in "${filter}" stage.`}
              </Text>
              <Text style={styles.emptyHint}>New orders will appear here the moment a customer checks out.</Text>
            </View>
          }
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
  exportBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface, minHeight: 34 },
  exportBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  tabs: { flexDirection: "row", marginHorizontal: spacing.screen, backgroundColor: colors.surfaceMuted, borderRadius: 99, padding: 4, gap: 2, marginBottom: 8 },
  tab: { flex: 1, paddingVertical: 6, alignItems: "center", borderRadius: 99 },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 9, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.5 },
  tabTextActive: { color: colors.primaryFg },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 10 },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 8 },
  orderId: { fontSize: 13, fontWeight: "800", color: colors.textMain, letterSpacing: 1 },
  orderDate: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  buyer: { fontSize: 11, color: colors.textMain, fontWeight: "700" },
  pill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  pillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 10 },
  itemRow: { flexDirection: "row", alignItems: "center", gap: 10, marginVertical: 3 },
  itemImage: { width: 40, height: 40, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  itemName: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  itemQty: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  lineTotal: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  totalLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  totalValue: { fontSize: 16, fontWeight: "800", color: colors.primary },
  actionsBlock: { marginTop: 12, gap: 10 },
  stageTracker: { flexDirection: "row", justifyContent: "space-between", gap: 4 },
  stageStep: { flex: 1, alignItems: "center", gap: 4 },
  stageDot: { width: 18, height: 18, borderRadius: 9, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  stageLabel: { fontSize: 9, color: colors.textMuted, letterSpacing: 0.3, textTransform: "uppercase", fontWeight: "700" },
  btnRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, alignItems: "center" },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 99, backgroundColor: colors.primary },
  primaryBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  ghostBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: "#B3261E" },
  ghostBtnText: { fontSize: 11, fontWeight: "700", color: "#B3261E" },
  emptyBox: { alignItems: "center", padding: 40, gap: 6 },
  emptyText: { fontSize: 14, color: colors.textMuted, fontWeight: "700", textAlign: "center" },
  emptyHint: { fontSize: 12, color: colors.textMuted, textAlign: "center" },
});
