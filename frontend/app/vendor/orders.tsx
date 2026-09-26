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
import { useSwipePager } from "../../src/use-swipe-pager";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, ScrollView,
  TouchableOpacity, Image, Alert, Modal, TextInput, Linking, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { OrderTimeline } from "../../src/order-timeline";
import { FadeSlideIn, ListRowSkeleton } from "../../src/anim";
import { downloadOrdersCsv, ExportOrderLike } from "../../src/exportOrdersCsv";

type VendorSale = {
  id: string;
  order_id?: string;
  // Jun 2026 — human order number + wallet/COD split from the split checkout
  order_number?: string;
  cod_due?: number;
  wallet_paid?: number;
  user_id?: string;
  created_at: string;
  status: string;
  total?: number;
  items?: Array<{ product_id?: string; name: string; price: number; image_url?: string; qty: number }>;
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
  // Dec 2026 — Delivery-address block (from checkout).  Includes optional
  // GPS coords so the vendor can tap "Open in Google Maps" and route to
  // the customer's exact location.
  shipping_address?: {
    name?: string; phone?: string;
    line1?: string; line2?: string;
    city?: string; state?: string; pincode?: string;
    latitude?: number | null; longitude?: number | null;
    district?: string;
  };
};

const STATUSES = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered", "cancelled"] as const;
// Status tab order — also the sequence the left/right swipe walks through.
const VORDER_TABS: string[] = ["all", ...STATUSES];
const STATUS_COLORS: Record<string, string> = {
  placed: colors.warning,
  confirmed: "#8B5CF6",
  shipped: colors.brand500,
  out_for_delivery: "#0EA5E9",
  delivered: colors.success,
  cancelled: "#B3261E",
};
const STATUS_LABEL: Record<string, string> = {
  all: "All", placed: "Placed", confirmed: "Confirmed", shipped: "Shipped",
  out_for_delivery: "On the way", delivered: "Delivered", cancelled: "Cancelled",
};
// Jun 2026 — the seller walks the parcel through five stages, so each card
// shows exactly ONE "next step" button instead of a wall of options.
const NEXT_STAGE: Record<string, { next: string; label: string; icon: any }> = {
  placed:           { next: "confirmed",        label: "Confirm order",    icon: "check" },
  confirmed:        { next: "shipped",          label: "Mark shipped",     icon: "package" },
  shipped:          { next: "out_for_delivery", label: "Out for delivery", icon: "truck" },
  out_for_delivery: { next: "delivered",        label: "Mark delivered",   icon: "check-circle" },
};
/** Still in flight — cash outstanding, editable, cancellable. */
const OPEN_STATUSES = ["placed", "confirmed", "shipped", "out_for_delivery"];

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
          product_id: it?.product_id || undefined,
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
          product_id: (safe as any).product_id || undefined,
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
  // Jun 2026 — One shared swipe behaviour across the app.
  const stepFilter = useCallback((dir: 1 | -1) => {
    const next = VORDER_TABS.indexOf(filter) + dir;
    if (next < 0 || next >= VORDER_TABS.length) return;
    setFilter(VORDER_TABS[next]);
  }, [filter]);
  const swipeHandlers = useSwipePager({
    onNext: () => stepFilter(1),
    onPrev: () => stepFilter(-1),
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  // Jul 2026 — Delivery-info modal state
  const [editingOrder, setEditingOrder] = useState<VendorSale | null>(null);
  const [editEta, setEditEta] = useState("");
  const [editName, setEditName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [savingInfo, setSavingInfo] = useState(false);
  // Oct 2026 — when admin maps a delivery partner to this shop, the rider owns
  // every stage after "Confirm order". The seller can still accept or cancel.
  const [dpPartners, setDpPartners] = useState<{ id: string; name: string; phone: string }[]>([]);
  const dpManaged = dpPartners.length > 0;
  // Oct 2026 — tapping a line used to push /product/{id}. For a historical
  // order whose product was edited or deleted that dead-ends (and on a real
  // device the native screen closed the app), so the line detail is now a
  // sheet built from the ORDER ROW itself — it can never 404.
  const [itemSheet, setItemSheet] = useState<{ item: any; order: any } | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: VendorSale[]; total?: number } | VendorSale[]>(
        filter === "all" ? "/vendor/me/sales" : `/vendor/me/sales?status=${filter}`,
      );      const raw = Array.isArray(data) ? data : (data?.items || []);
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
    api.get("/vendor/me/delivery-partners")
      .then(({ data }) => setDpPartners((data as any)?.partners || []))
      .catch(() => setDpPartners([]));
    return undefined;
  }, [load]));

  const setStatus = async (orderId: string, status: string) => {
    setBusy(orderId);
    try {
      await api.patch(`/vendor/orders/${orderId}/status`, { status });
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

  const renderStage = (o: VendorSale) => (
    <OrderTimeline status={String(o.status || "placed")} testID={`stage-${o.id}`} />
  );

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

      {/* Oct 2026 — the 7 status labels no longer fight for room in a fixed
          row (they used to run together as "PLACEDCONFIRMEDSHIPPED"). Each
          is a properly padded chip on a horizontal rail. */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabsWrap}
        contentContainerStyle={styles.tabs}
      >
        {VORDER_TABS.map((t) => (
          <TouchableOpacity key={t} onPress={() => setFilter(t)} style={[styles.tab, filter === t && styles.tabActive]} testID={`vorder-tab-${t}`}>
            <Text style={[styles.tabText, filter === t && styles.tabTextActive]}>{STATUS_LABEL[t] || t}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Jun 2026 — Same left/right swipe as everywhere else in the app:
          flick the list body to move through the status tabs. */}
      <View style={{ flex: 1 }} {...swipeHandlers}>
      {dpManaged ? (
        <View style={styles.dpBanner} testID="vorder-dp-banner">
          <Feather name="truck" size={15} color={colors.primary} />
          <Text style={styles.dpBannerText}>
            {`Deliveries are handled by ${dpPartners.map((p) => p.name).join(", ")}. You accept the order — they mark it shipped and delivered.`}
          </Text>
        </View>
      ) : null}
      {loading ? (
        <View style={{ paddingHorizontal: spacing.screen, paddingTop: 6 }}>
          {[...Array(5)].map((_, i) => <ListRowSkeleton key={i} />)}
        </View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i, idx) => String(i?.id || idx)}
          renderItem={({ item, index }) => {
            const orderId = item.order_id || item.id;
            const safeItems = Array.isArray(item.items) ? item.items : [];
            return (
              <FadeSlideIn delay={Math.min(index, 6) * 40}>
              <View style={styles.card} testID={`vorder-${orderId}`}>
                <View style={styles.cardTop}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.orderId}>{item.order_number || `#${orderId.slice(0, 8).toUpperCase()}`}</Text>
                    <Text style={styles.orderDate}>{new Date(item.created_at).toLocaleString()}</Text>
                    {item.buyer_name ? (
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 }}>
                        <Feather name="user" size={11} color={colors.textMuted} />
                        <Text style={styles.buyer}>{item.buyer_name}{item.buyer_phone ? ` · ${item.buyer_phone}` : ""}</Text>
                      </View>
                    ) : null}
                  </View>
                  <View style={[styles.pill, { backgroundColor: STATUS_COLORS[item.status] || colors.textMuted }]}>
                    <Text style={styles.pillText}>{(STATUS_LABEL[item.status] || item.status).toUpperCase()}</Text>
                  </View>
                </View>
                <View style={styles.divider} />
                {safeItems.map((it, idx) => (
                  <TouchableOpacity
                    key={idx}
                    style={styles.itemRow}
                    activeOpacity={0.6}
                    onPress={() => setItemSheet({ item: it || {}, order: item })}
                    testID={`vendor-order-item-${idx}`}
                  >
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
                    <Feather name="chevron-right" size={16} color={colors.textMuted} style={{ marginLeft: 4 }} />
                  </TouchableOpacity>
                ))}
                <View style={styles.divider} />
                <View style={styles.totalRow}>
                  <Text style={styles.totalLabel}>Order total</Text>
                  <Text style={styles.totalValue}>{formatINR(item.total || 0)}</Text>
                </View>
                {/* Jun 2026 — Wallet+COD combos: tell the rider exactly how
                    much cash to collect (0 means fully prepaid). */}
                {Number(item.cod_due || 0) > 0 && OPEN_STATUSES.includes(item.status) ? (
                  <View style={styles.codRow}>
                    <Feather name="dollar-sign" size={12} color="#92400E" />
                    <Text style={styles.codRowText}>
                      Collect {formatINR(Number(item.cod_due))} in cash
                      {Number(item.wallet_paid || 0) > 0
                        ? ` · ${formatINR(Number(item.wallet_paid))} already paid online`
                        : ""}
                    </Text>
                  </View>
                ) : null}

                {/* Dec 2026 — Customer delivery address + Google Maps CTA.
                    Only rendered for online orders (POS has no shipping
                    address).  When the customer shared GPS at checkout
                    we render a "Open in Maps" button that routes to the
                    exact lat/lng; otherwise it falls back to an address
                    search query, which Maps still resolves accurately in
                    most cases. */}
                {item.channel !== "pos" && item.shipping_address ? (() => {
                  const addr = item.shipping_address!;
                  const hasCoords = typeof addr.latitude === "number" && typeof addr.longitude === "number"
                    && !Number.isNaN(addr.latitude as any) && !Number.isNaN(addr.longitude as any);
                  const addrLine = [addr.line1, addr.line2, addr.city, addr.state, addr.pincode].filter(Boolean).join(", ");
                  const openMaps = async () => {
                    // Prefer geo: URI on mobile so it opens the native map
                    // app; fall back to https://maps.google.com on web.
                    let url = "";
                    if (hasCoords) {
                      const lat = addr.latitude; const lng = addr.longitude;
                      url = Platform.select({
                        ios: `https://maps.apple.com/?ll=${lat},${lng}&q=${encodeURIComponent(addr.name || "Delivery")}`,
                        android: `geo:${lat},${lng}?q=${lat},${lng}(${encodeURIComponent(addr.name || "Delivery")})`,
                        default: `https://www.google.com/maps?q=${lat},${lng}`,
                      }) as string;
                    } else if (addrLine) {
                      url = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addrLine)}`;
                    } else {
                      Alert.alert("No address available", "This order has no shipping address to open on the map.");
                      return;
                    }
                    try {
                      const ok = await Linking.canOpenURL(url);
                      if (!ok && Platform.OS === "android") {
                        // Fallback for Android when geo: isn't registered
                        await Linking.openURL(`https://www.google.com/maps?q=${addr.latitude},${addr.longitude}`);
                        return;
                      }
                      await Linking.openURL(url);
                    } catch (e: any) {
                      Alert.alert("Couldn't open Maps", e?.message || "Try copying the address instead.");
                    }
                  };
                  return (
                    <View style={styles.addrBox}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
                        <Feather name="map-pin" size={12} color={colors.primary} />
                        <Text style={styles.addrLabel}>DELIVER TO · customer address</Text>
                      </View>
                      {addr.name || addr.phone ? (
                        <Text style={styles.addrLine} numberOfLines={1}>
                          {addr.name || "—"}{addr.phone ? ` · ${addr.phone}` : ""}
                        </Text>
                      ) : null}
                      {addrLine ? (
                        <Text style={styles.addrLine2} numberOfLines={2}>{addrLine}</Text>
                      ) : null}
                      {hasCoords ? (
                        <TouchableOpacity onPress={openMaps} style={styles.gpsChip} testID={`vendor-order-map-${orderId}`}>
                          <Feather name="navigation" size={12} color="#fff" />
                          <Text style={styles.gpsChipText}>
                            GPS · {Number(addr.latitude).toFixed(5)}, {Number(addr.longitude).toFixed(5)}
                          </Text>
                          <Feather name="external-link" size={11} color="#fff" />
                        </TouchableOpacity>
                      ) : addrLine ? (
                        <TouchableOpacity onPress={openMaps} style={[styles.gpsChip, { backgroundColor: colors.textMain }]} testID={`vendor-order-map-${orderId}`}>
                          <Feather name="map" size={12} color="#fff" />
                          <Text style={styles.gpsChipText}>Open in Maps</Text>
                          <Feather name="external-link" size={11} color="#fff" />
                        </TouchableOpacity>
                      ) : null}
                    </View>
                  );
                })() : null}

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
                    {item.channel !== "pos" && NEXT_STAGE[item.status]
                      && !(dpManaged && item.status !== "placed") && (
                      <TouchableOpacity
                        onPress={() => setStatus(orderId, NEXT_STAGE[item.status].next)}
                        disabled={busy === orderId}
                        style={styles.primaryBtn}
                        testID={`vnext-${orderId}`}
                      >
                        <Feather name={NEXT_STAGE[item.status].icon} size={14} color={colors.primaryFg} />
                        <Text style={styles.primaryBtnText}>{NEXT_STAGE[item.status].label}</Text>
                      </TouchableOpacity>
                    )}
                    {dpManaged && item.channel !== "pos" && item.status !== "placed"
                      && OPEN_STATUSES.includes(item.status) ? (
                      <View style={styles.dpLockBox} testID={`vdplock-${orderId}`}>
                        <Feather name="truck" size={13} color={colors.textMuted} />
                        <Text style={styles.dpLockText} numberOfLines={2}>
                          {`${dpPartners[0]?.name || "Your delivery partner"} moves this order from here`}
                        </Text>
                      </View>
                    ) : null}
                    {item.channel !== "pos" && OPEN_STATUSES.includes(item.status) && !dpManaged && (
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
                    {item.channel !== "pos" && OPEN_STATUSES.includes(item.status) && (
                      <TouchableOpacity onPress={() => setStatus(orderId, "cancelled")} disabled={busy === orderId} style={styles.ghostBtn} testID={`vcancel-${orderId}`}>
                        <Feather name="x-circle" size={14} color="#B3261E" />
                        <Text style={styles.ghostBtnText}>Cancel & refund</Text>
                      </TouchableOpacity>
                    )}
                    {busy === orderId ? <ActivityIndicator size="small" color={colors.primary} /> : null}
                  </View>
                </View>
              </View>
              </FadeSlideIn>
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
      </View>

      {/* Oct 2026 — order-line detail. Built from the order row, so it works
          for deleted / unpublished products and POS lines too. */}
      <Modal visible={!!itemSheet} transparent animationType="slide" onRequestClose={() => setItemSheet(null)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setItemSheet(null)}>
          <TouchableOpacity activeOpacity={1} style={styles.modalSheet} onPress={() => { /* keep open */ }}>
            <View style={styles.sheetHandle} />
            <View style={styles.sheetTop}>
              {itemSheet?.item?.image_url ? (
                <Image source={{ uri: itemSheet.item.image_url }} style={styles.sheetImage} />
              ) : (
                <View style={[styles.sheetImage, { alignItems: "center", justifyContent: "center" }]}>
                  <Feather name="image" size={20} color={colors.textMuted} />
                </View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={styles.sheetName}>{itemSheet?.item?.name || "Product"}</Text>
                <Text style={styles.sheetMeta}>
                  {`${formatINR(itemSheet?.item?.price || 0)} × ${itemSheet?.item?.qty || 1}`}
                </Text>
                <Text style={styles.sheetTotal}>
                  {formatINR((itemSheet?.item?.price || 0) * (itemSheet?.item?.qty || 1))}
                </Text>
              </View>
            </View>
            <View style={styles.divider} />
            <SheetRow label="Order" value={itemSheet?.order?.order_number || "—"} />
            <SheetRow label="Status" value={(STATUS_LABEL[itemSheet?.order?.status] || itemSheet?.order?.status || "—")} />
            <SheetRow label="Customer" value={itemSheet?.order?.buyer_name || "—"} />
            {itemSheet?.item?.variant_label ? (
              <SheetRow label="Variant" value={itemSheet.item.variant_label} />
            ) : null}
            <SheetRow label="Order total" value={formatINR(itemSheet?.order?.total || 0)} />
            {itemSheet?.item?.product_id ? (
              <TouchableOpacity
                style={styles.sheetLink}
                onPress={() => {
                  const pid = itemSheet.item.product_id;
                  setItemSheet(null);
                  router.push(`/vendor/dashboard?product=${pid}` as any);
                }}
                testID="vorder-item-open-catalogue"
              >
                <Feather name="package" size={14} color={colors.primary} />
                <Text style={styles.sheetLinkText}>Open in my catalogue</Text>
              </TouchableOpacity>
            ) : null}
            <TouchableOpacity
              style={[styles.modalBtn, { backgroundColor: colors.primary, marginTop: 10 }]}
              onPress={() => setItemSheet(null)}
              testID="vorder-item-close"
            >
              <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Close</Text>
            </TouchableOpacity>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>


      {/* Jul 2026 — Delivery info modal.  Vendor sets ETA + delivery
          person contact.  Both fields are optional; blank fields
          preserve the existing value on save. */}
      <Modal visible={!!editingOrder} transparent animationType="slide" onRequestClose={() => setEditingOrder(null)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setEditingOrder(null)}>
          <TouchableOpacity activeOpacity={1} style={styles.modalSheet} onPress={() => { /* stopPropagation */ }}>
            <View style={styles.modalGrabber} />
            <Text style={styles.modalTitle}>Delivery information</Text>
            <Text style={styles.modalSub}>Order {editingOrder?.order_number || `#${(editingOrder?.order_id || editingOrder?.id || "").slice(0, 8).toUpperCase()}`}</Text>

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

function SheetRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.sheetRow}>
      <Text style={styles.sheetRowLabel}>{label}</Text>
      <Text style={styles.sheetRowValue} numberOfLines={2}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  sheetHandle: {
    width: 42, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: 14,
  },
  sheetTop: { flexDirection: "row", gap: 12, alignItems: "center" },
  sheetImage: {
    width: 64, height: 64, borderRadius: 12, backgroundColor: colors.surfaceMuted,
  },
  sheetName: { fontSize: 15.5, fontWeight: "900", color: colors.textMain },
  sheetMeta: { fontSize: 12, color: colors.textMuted, fontWeight: "700", marginTop: 3 },
  sheetTotal: { fontSize: 17, fontWeight: "900", color: colors.textMain, marginTop: 4 },
  sheetRow: {
    flexDirection: "row", justifyContent: "space-between", gap: 14, paddingVertical: 7,
  },
  sheetRowLabel: { fontSize: 12.5, color: colors.textMuted, fontWeight: "700" },
  sheetRowValue: { flex: 1, fontSize: 12.5, color: colors.textMain, fontWeight: "800", textAlign: "right" },
  sheetLink: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    marginTop: 12, borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingVertical: 12, minHeight: 46,
  },
  sheetLinkText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  exportBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface, minHeight: 34 },
  exportBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  // flexGrow:0 — without it the rail stretches to fill the screen.
  tabsWrap: { flexGrow: 0, flexShrink: 0, maxHeight: 48 },
  tabs: { paddingHorizontal: spacing.screen, gap: 8, alignItems: "center" },
  tab: {
    paddingHorizontal: 14, paddingVertical: 9, borderRadius: 99, minHeight: 36,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabText: { fontSize: 12.5, fontWeight: "700", color: colors.textMain },
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
  codRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, paddingVertical: 8, paddingHorizontal: 10, borderRadius: 10, backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FDE68A" },
  codRowText: { flex: 1, fontSize: 11, fontWeight: "800", color: "#92400E" },

  totalLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  totalValue: { fontSize: 16, fontWeight: "800", color: colors.primary },
  actionsBlock: { marginTop: 12, gap: 10 },
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
  // Dec 2026 — Customer delivery address + Google Maps CTA (see orders card)
  addrBox: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: 10,
    padding: 10,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  addrLabel: { fontSize: 9, fontWeight: "800", color: colors.primary, letterSpacing: 0.8 },
  addrLine: { fontSize: 13, color: colors.textMain, fontWeight: "800", marginTop: 2 },
  addrLine2: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 2, lineHeight: 17 },
  gpsChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999,
    backgroundColor: colors.primary, alignSelf: "flex-start", marginTop: 8,
  },
  gpsChipText: { fontSize: 11, fontWeight: "800", color: "#fff", letterSpacing: 0.3 },
  infoBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 99,
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.brand100,
  },
  infoBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  dpBanner: {
    flexDirection: "row", alignItems: "center", gap: 9,
    marginHorizontal: spacing.screen, marginTop: 8, padding: 11,
    backgroundColor: colors.brand100, borderRadius: 14,
  },
  dpBannerText: { flex: 1, fontSize: 11.5, fontWeight: "700", color: colors.textMain, lineHeight: 16 },
  dpLockBox: {
    flexDirection: "row", alignItems: "center", gap: 6, flex: 1,
    paddingHorizontal: 11, paddingVertical: 9, borderRadius: 999,
    backgroundColor: colors.surfaceMuted, minHeight: 36,
  },
  dpLockText: { flex: 1, fontSize: 11, fontWeight: "700", color: colors.textMuted },

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
