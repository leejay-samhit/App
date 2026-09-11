import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, FlatList, ScrollView, Modal, ActivityIndicator, RefreshControl, TouchableOpacity, Image, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError, resolveImageUrl } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { downloadOrdersCsv } from "../../src/exportOrdersCsv";

type AdminOrder = {
  id: string;
  order_number?: string;
  user_id: string;
  total: number;
  status: string;
  created_at: string;
  items: { name: string; price: number; image_url: string; qty: number; variant_label?: string | null }[];
  // Buyer / vendor identity — attached server-side (_attach_order_parties).
  buyer_name?: string; buyer_email?: string; buyer_phone?: string;
  vendor_id?: string; vendor_name?: string; vendor_email?: string; vendor_phone?: string;
  wallet_paid?: number; online_paid?: number; cod_due?: number; paid_via?: string; payment_status?: string;
  split_index?: number | string; split_count?: number | string;
  shipping_address?: Record<string, any>;
};

const STATUSES = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered", "cancelled"] as const;
const STATUS_COLORS: Record<string, string> = {
  placed: colors.warning, confirmed: "#8B5CF6", shipped: colors.brand500,
  out_for_delivery: "#0EA5E9", delivered: colors.success, cancelled: "#B3261E",
};
const STATUS_LABEL: Record<string, string> = {
  all: "All", placed: "Placed", confirmed: "Confirmed", shipped: "Shipped",
  out_for_delivery: "On the way", delivered: "Delivered", cancelled: "Cancelled",
};

export default function AdminOrders() {
  const router = useRouter();
  const [items, setItems] = useState<AdminOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [detailFor, setDetailFor] = useState<AdminOrder | null>(null);

  const load = useCallback(async () => {
    try {
      const url = filter === "all" ? "/admin/orders" : `/admin/orders?status=${filter}`;
      const { data } = await api.get<AdminOrder[]>(url);
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

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
            <Text style={[styles.tabText, filter === t && styles.tabTextActive]}>{(STATUS_LABEL[t] || t).toUpperCase()}</Text>
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
            <TouchableOpacity
              style={styles.card}
              testID={`order-${item.id}`}
              activeOpacity={0.85}
              onPress={() => setDetailFor(item)}
            >
              <View style={styles.cardTop}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.orderId}>{item.order_number || `#${item.id.slice(0, 8).toUpperCase()}`}</Text>
                  <Text style={styles.orderDate}>{new Date(item.created_at).toLocaleString()}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: STATUS_COLORS[item.status] || colors.textMuted }]}>
                  <Text style={styles.pillText}>{(STATUS_LABEL[item.status] || item.status).toUpperCase()}</Text>
                </View>
              </View>

              {/* Who bought it · who ships it (owner request, Sep 2026) */}
              <View style={styles.partyRow}>
                <View style={styles.party}>
                  <Feather name="user" size={11} color={colors.textMuted} />
                  <Text style={styles.partyText} numberOfLines={1}>
                    {item.buyer_name || "Customer"}{item.buyer_phone ? ` · ${item.buyer_phone}` : ""}
                  </Text>
                </View>
                <View style={styles.party}>
                  <Feather name="shopping-bag" size={11} color={colors.textMuted} />
                  <Text style={styles.partyText} numberOfLines={1}>
                    {item.vendor_name || "Unassigned seller"}
                  </Text>
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
              <Text style={styles.tapHint}>TAP FOR FULL DETAILS</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No orders match this filter</Text>}
        />
      )}

      <OrderDetailSheet order={detailFor} onClose={() => setDetailFor(null)} />
    </SafeAreaView>
  );
}

/**
 * Order details sheet (Sep 2026, owner request).
 *
 * Opens on a card tap: hero preview of the first product, every line item,
 * the customer (full phone — the admin needs to call), the seller, the
 * payment split (wallet vs cash) and the delivery address. Sibling
 * sub-orders from the same multi-vendor checkout are listed too.
 */
function OrderDetailSheet({ order, onClose }: { order: AdminOrder | null; onClose: () => void }) {
  const [detail, setDetail] = useState<AdminOrder | null>(null);
  const [siblings, setSiblings] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!order) { setDetail(null); setSiblings([]); return; }
    setDetail(order);
    setLoading(true);
    api.get<{ order: AdminOrder; siblings: any[] }>(`/admin/orders/${order.id}`)
      .then(({ data }) => { setDetail(data.order); setSiblings(data.siblings || []); })
      .catch(() => { /* keep the row data we already have */ })
      .finally(() => setLoading(false));
  }, [order?.id]);

  if (!order) return null;
  const o = detail || order;
  const addr = o.shipping_address || {};
  const hero = o.items?.[0];
  const walletPaid = Number(o.wallet_paid || 0);
  const onlinePaid = Number(o.online_paid || 0);
  const codDue = Number(o.cod_due || 0);

  return (
    <Modal visible animationType="slide" onRequestClose={onClose} transparent={false}>
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose} style={styles.backBtn} testID="order-detail-close">
            <Feather name="x" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>{o.order_number || `#${o.id.slice(0, 8).toUpperCase()}`}</Text>
          <View style={{ width: 40, alignItems: "center" }}>
            {loading ? <ActivityIndicator size="small" color={colors.primary} /> : null}
          </View>
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}>
          {/* HERO */}
          <View style={styles.heroCard}>
            {hero?.image_url ? (
              <Image source={{ uri: resolveImageUrl(hero.image_url) }} style={styles.heroImage} resizeMode="contain" />
            ) : (
              <View style={[styles.heroImage, styles.heroPlaceholder]}>
                <Feather name="image" size={28} color={colors.textMuted} />
              </View>
            )}
            <Text style={styles.heroName} numberOfLines={2}>{hero?.name || "Order"}</Text>
            <Text style={styles.heroMeta}>
              {(o.items?.length || 0)} item{(o.items?.length || 0) === 1 ? "" : "s"} · {formatINR(o.total)}
            </Text>
            <View style={[styles.pill, { backgroundColor: STATUS_COLORS[o.status] || colors.textMuted, marginTop: 8 }]}>
              <Text style={styles.pillText}>{(STATUS_LABEL[o.status] || o.status).toUpperCase()}</Text>
            </View>
          </View>

          {/* CUSTOMER */}
          <Text style={styles.sectionLabel}>CUSTOMER</Text>
          <View style={styles.box}>
            <DetailRow label="Name" value={o.buyer_name || addr.name || "—"} />
            <DetailRow label="Phone" value={o.buyer_phone || addr.phone || "—"} />
            <DetailRow label="Email" value={o.buyer_email || "—"} />
          </View>

          {/* SELLER */}
          <Text style={styles.sectionLabel}>SELLER</Text>
          <View style={styles.box}>
            <DetailRow label="Shop" value={o.vendor_name || "—"} />
            <DetailRow label="Phone" value={o.vendor_phone || "—"} />
            <DetailRow label="Email" value={o.vendor_email || "—"} />
          </View>

          {/* PAYMENT */}
          <Text style={styles.sectionLabel}>PAYMENT</Text>
          <View style={styles.box}>
            <DetailRow label="Method" value={(o.paid_via || "—").toUpperCase().replace("_", " + ")} />
            <DetailRow label="Paid from wallet" value={formatINR(walletPaid)} />
            <DetailRow label="Paid online" value={formatINR(onlinePaid)} />
            <DetailRow label="Cash on delivery" value={formatINR(codDue)} />
            <DetailRow label="Order total" value={formatINR(o.total)} />
          </View>

          {/* ITEMS */}
          <Text style={styles.sectionLabel}>ITEMS</Text>
          <View style={styles.box}>
            {(o.items || []).map((it, idx) => (
              <View key={idx} style={styles.itemRow}>
                {it.image_url ? (
                  <Image source={{ uri: resolveImageUrl(it.image_url) }} style={styles.itemImage} />
                ) : (
                  <View style={[styles.itemImage, styles.heroPlaceholder]}>
                    <Feather name="image" size={12} color={colors.textMuted} />
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text style={styles.itemName} numberOfLines={2}>{it.name}</Text>
                  <Text style={styles.itemQty}>
                    {formatINR(it.price)} × {it.qty}{it.variant_label ? ` · ${it.variant_label}` : ""}
                  </Text>
                </View>
                <Text style={styles.itemLine}>{formatINR(Number(it.price) * Number(it.qty))}</Text>
              </View>
            ))}
          </View>

          {/* ADDRESS */}
          <Text style={styles.sectionLabel}>DELIVERY ADDRESS</Text>
          <View style={styles.box}>
            <Text style={styles.addrText}>
              {[addr.line1, addr.line2, addr.city, addr.state, addr.pincode].filter(Boolean).join(", ") || "No address on this order"}
            </Text>
          </View>

          {siblings.length > 0 ? (
            <>
              <Text style={styles.sectionLabel}>SAME CHECKOUT ({siblings.length + 1} SELLERS)</Text>
              <View style={styles.box}>
                {siblings.map((s) => (
                  <DetailRow
                    key={s.id}
                    label={`${s.order_number || s.id.slice(0, 8)} · ${s.vendor_name || "Seller"}`}
                    value={`${formatINR(s.total)} · ${String(s.status).toUpperCase()}`}
                  />
                ))}
              </View>
            </>
          ) : null}
        </ScrollView>
      </SafeAreaView>
    </Modal>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  const stacked = String(value).length > 26;
  return (
    <View style={[styles.detailRow, stacked && { flexDirection: "column", alignItems: "flex-start", gap: 2 }]}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={[styles.detailValue, stacked && { textAlign: "left" }]} selectable>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  heroCard: {
    backgroundColor: colors.surface, borderRadius: 20, borderWidth: 1, borderColor: colors.border,
    padding: 16, alignItems: "center", marginBottom: 16,
  },
  heroImage: { width: "100%", height: 180, borderRadius: 14, backgroundColor: colors.surfaceMuted },
  heroPlaceholder: { alignItems: "center", justifyContent: "center" },
  heroName: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginTop: 12, textAlign: "center" },
  heroMeta: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  sectionLabel: { fontSize: 10, fontWeight: "900", letterSpacing: 1, color: colors.textMuted, marginBottom: 8 },
  box: {
    backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    padding: 14, marginBottom: 16, gap: 10,
  },
  detailRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  detailLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "700" },
  detailValue: { flex: 1, fontSize: 13, color: colors.textMain, fontWeight: "700", textAlign: "right" },
  itemLine: { fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  addrText: { fontSize: 13, color: colors.textMain, lineHeight: 19 },
  partyRow: { gap: 4, marginTop: 10 },
  party: { flexDirection: "row", alignItems: "center", gap: 6 },
  partyText: { flex: 1, fontSize: 11.5, color: colors.textMain, fontWeight: "600" },
  tapHint: { fontSize: 9, fontWeight: "800", letterSpacing: 0.8, color: colors.textMuted, marginTop: 10, textAlign: "right" },
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
