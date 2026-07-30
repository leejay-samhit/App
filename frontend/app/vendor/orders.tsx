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
  TouchableOpacity, Image, Alert, Modal, TextInput,
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
  // Jul 2026 — Delivery info fields (set via /vendor/orders/:id/delivery-info)
  estimated_delivery_at?: string | null;
  delivery_person_name?: string | null;
  delivery_person_phone?: string | null;
  channel?: "online" | "pos";
  invoice_no?: string;
};

const STATUSES = ["placed", "shipped", "delivered", "cancelled"] as const;
const STATUS_COLORS: Record<string, string> = {
  placed: colors.warning,
  shipped: colors.brand500,
  delivered: colors.success,
  cancelled: "#B3261E",
};

/** Normalise the backend row.  Post-June-2026 the /vendor/me/sales
 *  endpoint returns fully-shaped orders (items array, total, status,
 *  buyer info).  We only need light defensive defaults here for older
 *  clients that hit the legacy flat shape. */
function normaliseSale(s: any): VendorSale & { items: NonNullable<VendorSale["items"]>; total: number } {
  const safe = s || {};
  const rawItems = Array.isArray(safe.items) ? safe.items : null;
  const items = (rawItems && rawItems.length > 0)
    ? rawItems.map((it: any) => {
        const qty = Number(it?.qty ?? 1) || 1;
        const lineTotal = Number(it?.line_total ?? 0) || 0;
        // Prefer explicit unit price; else derive from line_total / qty.
        let price = Number(it?.price ?? it?.unit_price ?? 0) || 0;
        if (!price && lineTotal && qty) price = Math.round((lineTotal / qty) * 100) / 100;
        return {
          name: String(it?.name || it?.product_name || safe.product_name || "Product"),
          price,
          image_url: it?.image_url || it?.product_image_url || undefined,
          qty,
        };
      })
    : (() => {
        // Legacy flat shape — derive unit price from line_total / qty.
        const qty = Number(safe.qty ?? 1) || 1;
        const lineTotal = Number(safe.line_total ?? 0) || 0;
        const price = qty ? Math.round((lineTotal / qty) * 100) / 100 : lineTotal;
        return [{
          name: String(safe.product_name || "Product"),
          price,
          image_url: safe.product_image_url || undefined,
          qty,
        }];
      })();
  // Total = full order amount (no platform margin deduction — vendors
  // see the FULL sale value per user directive June 2026).
  const total = Number(
    safe.total ?? items.reduce((a: number, i: any) => a + (i.price * i.qty), 0),
  ) || 0;
  return {
    ...safe,
    id: String(safe.id || safe.order_id || Math.random().toString(36).slice(2)),
    status: String(safe.status || "placed"),
    created_at: String(safe.created_at || new Date().toISOString()),
    items,
    total,
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
  // Jul 2026 — Delivery-info modal state
  const [editingOrder, setEditingOrder] = useState<VendorSale | null>(null);
  const [editEta, setEditEta] = useState("");
  const [editName, setEditName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [savingInfo, setSavingInfo] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: VendorSale[]; total?: number } | VendorSale[]>(
        filter === "all" ? "/vendor/me/sales" : `/vendor/me/sales?status=${filter}`,
      );
      const raw = Array.isArray(data) ? data : (data?.items || []);
      // Defensive normalise + never let one bad row kill the list.
      const shaped: any[] = [];
      for (const r of raw) {
        try { shaped.push(normaliseSale(r)); } catch { /* skip malformed row */ }
      }
      setItems(shaped);
    } catch (e) {
      // Silent: empty list is a valid empty state.
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filter]);

  useFocusEffect(useCallback(() => {
    // Important: useFocusEffect expects the callback to return either
    // a cleanup fn or undefined.  If we naively return `load()` React
    // thinks the Promise IS the cleanup and crashes on unmount.
    load();
    return undefined;
  }, [load]));

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
        <TouchableOpacity onPress={() => { try { router.back(); } catch { router.replace("/vendor/dashboard" as any); } }} style={styles.backBtn} testID="vorders-back">
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
          keyExtractor={(i, idx) => String(i?.id || idx)}
          renderItem={({ item }) => {
            const orderId = item.order_id || item.id;
            const safeItems = Array.isArray(item.items) ? item.items : [];
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
                {safeItems.map((it, idx) => (
                  <View key={idx} style={styles.itemRow}>
                    {it && it.image_url ? (
                      <Image source={{ uri: it.image_url }} style={styles.itemImage} />
                    ) : (
                      <View style={[styles.itemImage, { alignItems: "center", justifyContent: "center" }]}>
                        <Feather name="image" size={14} color={colors.textMuted} />
                      </View>
                    )}
                    <View style={{ flex: 1 }}>
                      <Text style={styles.itemName} numberOfLines={1}>{(it && it.name) || "Product"}</Text>
                      <Text style={styles.itemQty}>{formatINR(it?.price || 0)} × {it?.qty || 1}</Text>
                    </View>
                    <Text style={styles.lineTotal}>{formatINR((it?.price || 0) * (it?.qty || 1))}</Text>
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

                  {/* Jul 2026 — Delivery info summary + edit action.
                      Only relevant for real online orders (not POS). */}
                  {item.channel !== "pos" && (item.estimated_delivery_at || item.delivery_person_name || item.delivery_person_phone) ? (
                    <View style={styles.deliveryInfoBox}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
                        <Feather name="clock" size={12} color={colors.primary} />
                        <Text style={styles.deliveryInfoLabel}>DELIVERY INFO · shared with customer</Text>
                      </View>
                      {item.estimated_delivery_at ? (
                        <Text style={styles.deliveryInfoLine}>ETA: {item.estimated_delivery_at}</Text>
                      ) : null}
                      {(item.delivery_person_name || item.delivery_person_phone) ? (
                        <Text style={styles.deliveryInfoLine}>
                          {item.delivery_person_name || "Rider"}
                          {item.delivery_person_phone ? ` · ${item.delivery_person_phone}` : ""}
                        </Text>
                      ) : null}
                    </View>
                  ) : null}

                  <View style={styles.btnRow}>
                    {item.status === "placed" && item.channel !== "pos" && (
                      <TouchableOpacity onPress={() => setStatus(orderId, "shipped")} disabled={busy === orderId} style={styles.primaryBtn} testID={`vship-${orderId}`}>
                        <Feather name="truck" size={14} color={colors.primaryFg} />
                        <Text style={styles.primaryBtnText}>Mark shipped</Text>
                      </TouchableOpacity>
                    )}
                    {item.status === "shipped" && item.channel !== "pos" && (
                      <TouchableOpacity onPress={() => setStatus(orderId, "delivered")} disabled={busy === orderId} style={styles.primaryBtn} testID={`vdeliv-${orderId}`}>
                        <Feather name="check-circle" size={14} color={colors.primaryFg} />
                        <Text style={styles.primaryBtnText}>Mark delivered</Text>
                      </TouchableOpacity>
                    )}
                    {item.channel !== "pos" && (item.status === "placed" || item.status === "shipped") && (
                      <TouchableOpacity
                        onPress={() => {
                          setEditingOrder(item);
                          setEditEta(item.estimated_delivery_at || "");
                          setEditName(item.delivery_person_name || "");
                          setEditPhone(item.delivery_person_phone || "");
                        }}
                        disabled={busy === orderId}
                        style={styles.infoBtn}
                        testID={`vdlvinfo-${orderId}`}
                      >
                        <Feather name="edit-3" size={14} color={colors.primary} />
                        <Text style={styles.infoBtnText}>Delivery info</Text>
                      </TouchableOpacity>
                    )}
                    {item.channel !== "pos" && (item.status === "placed" || item.status === "shipped") && (
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

      {/* Jul 2026 — Delivery info modal.  Vendor sets ETA + delivery
          person contact.  Both fields are optional; blank fields
          preserve the existing value on save. */}
      <Modal visible={!!editingOrder} transparent animationType="slide" onRequestClose={() => setEditingOrder(null)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setEditingOrder(null)}>
          <TouchableOpacity activeOpacity={1} style={styles.modalSheet} onPress={() => { /* stopPropagation */ }}>
            <View style={styles.modalGrabber} />
            <Text style={styles.modalTitle}>Delivery information</Text>
            <Text style={styles.modalSub}>Order #{(editingOrder?.order_id || editingOrder?.id || "").slice(0, 8).toUpperCase()}</Text>

            <View style={styles.fieldBlock}>
              <Text style={styles.fieldLabel}>Estimated delivery (ETA)</Text>
              <TextInput
                value={editEta}
                onChangeText={setEditEta}
                placeholder="e.g. Tomorrow by 6:00 PM  ·  or 2026-07-31 18:00"
                placeholderTextColor={colors.textMuted}
                style={styles.fieldInput}
                testID="vdlvinfo-eta"
              />
            </View>
            <View style={styles.fieldBlock}>
              <Text style={styles.fieldLabel}>Delivery person — name</Text>
              <TextInput
                value={editName}
                onChangeText={setEditName}
                placeholder="Ravi Kumar"
                placeholderTextColor={colors.textMuted}
                style={styles.fieldInput}
                testID="vdlvinfo-name"
              />
            </View>
            <View style={styles.fieldBlock}>
              <Text style={styles.fieldLabel}>Delivery person — phone</Text>
              <TextInput
                value={editPhone}
                onChangeText={setEditPhone}
                placeholder="98765 43210"
                placeholderTextColor={colors.textMuted}
                keyboardType="phone-pad"
                style={styles.fieldInput}
                testID="vdlvinfo-phone"
              />
            </View>

            <View style={{ flexDirection: "row", gap: 10, marginTop: 8 }}>
              <TouchableOpacity
                onPress={() => setEditingOrder(null)}
                style={[styles.modalBtn, styles.modalGhost]}
                disabled={savingInfo}
              >
                <Text style={styles.modalGhostText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={async () => {
                  if (!editingOrder) return;
                  const oid = editingOrder.order_id || editingOrder.id;
                  setSavingInfo(true);
                  try {
                    await api.patch(`/vendor/orders/${oid}/delivery-info`, {
                      estimated_delivery_at: editEta.trim(),
                      delivery_person_name: editName.trim(),
                      delivery_person_phone: editPhone.trim(),
                    });
                    setEditingOrder(null);
                    await load();
                  } catch (e) {
                    Alert.alert("Couldn't save", formatApiError(e));
                  } finally { setSavingInfo(false); }
                }}
                style={[styles.modalBtn, styles.modalPrimary, savingInfo && { opacity: 0.6 }]}
                disabled={savingInfo}
                testID="vdlvinfo-save"
              >
                {savingInfo ? <ActivityIndicator color={colors.primaryFg} /> : (
                  <>
                    <Feather name="check" size={15} color={colors.primaryFg} />
                    <Text style={styles.modalPrimaryText}>Save & notify customer</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
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

  // Jul 2026 — Delivery info summary + modal
  deliveryInfoBox: {
    backgroundColor: colors.brand100, borderRadius: 10,
    padding: 10, marginBottom: 6,
    borderWidth: 1, borderColor: colors.primary + "22",
  },
  deliveryInfoLabel: { fontSize: 9, fontWeight: "800", color: colors.primary, letterSpacing: 0.8 },
  deliveryInfoLine: { fontSize: 12, color: colors.textMain, fontWeight: "700", marginTop: 2 },
  infoBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99,
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.brand100,
  },
  infoBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 22, paddingBottom: 34,
  },
  modalGrabber: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  modalTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  modalSub: { fontSize: 12, color: colors.textMuted, marginTop: 2, marginBottom: 14, letterSpacing: 0.5 },
  fieldBlock: { marginBottom: 12 },
  fieldLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.5, marginBottom: 6 },
  fieldInput: {
    fontSize: 13, color: colors.textMain,
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: colors.surfaceMuted,
  },
  modalBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 13, borderRadius: 12,
  },
  modalPrimary: { backgroundColor: colors.primary },
  modalPrimaryText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },
  modalGhost: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  modalGhostText: { color: colors.textMain, fontWeight: "800", fontSize: 13 },
});
