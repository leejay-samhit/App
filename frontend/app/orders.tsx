// My Orders — customer-facing order list + tap-to-invoice preview.
// Refresh June 2026 per user request:
//   • Show ALL orders (not just shipped).
//   • Filter chips at the top for quick status navigation.
//   • Tap any card → full-screen invoice preview with print/share.
import { useCallback, useMemo, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Image, TouchableOpacity, ActivityIndicator,
  RefreshControl, Modal, Platform, Share,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { useSwipePager } from "../src/use-swipe-pager";
import { api, formatApiError, resolveImageUrl } from "../src/api";
import { colors, radii, spacing, formatINR } from "../src/theme";
import { OrderTimeline } from "../src/order-timeline";
import { notify } from "../src/notify";
import { handleChatGateError } from "../src/sim-verification";
import { FadeSlideIn, ListRowSkeleton } from "../src/anim";

type OrderItem = { name: string; price: number; image_url: string; qty: number };
type Order = {
  id: string;
  order_number?: string;
  vendor_id?: string | null;
  vendor_name?: string | null;
  group_id?: string;
  split_index?: number;
  split_count?: number;
  total: number;
  wallet_paid?: number;
  online_paid?: number;
  cod_due?: number;
  status: string;
  created_at: string;
  items: OrderItem[];
  paid_via?: string;
  payment_status?: string;
  shipping_address?: {
    line1?: string; line2?: string; city?: string;
    state?: string; pincode?: string; phone?: string;
  };
  // Jul 2026 — Delivery info fields set by the vendor
  estimated_delivery_at?: string | null;
  status_history?: { status: string; at: string; by_name?: string; by_role?: string }[];
  delivery_person_name?: string | null;
  delivery_person_phone?: string | null;
  delivery_info_updated_at?: string | null;
  // Phase 2 — server-computed return state (7-day window from delivery).
  return_eligible?: boolean;
  return_minutes_left?: number;
  return_window_expired?: boolean;
  return_deadline?: string | null;
  has_returns?: boolean;
  returns?: { id: string; return_number: string; status: string }[];
  display_status?: string;
  can_cancel?: boolean;
};

const PAY_LABEL: Record<string, string> = {
  wallet: "Wallet",
  cod: "Cash on delivery",
  wallet_cod: "Wallet + Cash",
  online: "Paid online",
  wallet_online: "Wallet + Online",
};
// Progress steps shown on every live (non-cancelled) order card.
// Jun 2026 — five stages so the buyer can actually follow the parcel.
const STEPS = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"] as const;

const STATUS_META: Record<string, { color: string; label: string; icon: any }> = {
  placed:           { color: "#F59E0B", label: "Placed",     icon: "clock" },
  confirmed:        { color: "#8B5CF6", label: "Confirmed",  icon: "check" },
  shipped:          { color: "#3B82F6", label: "Shipped",    icon: "package" },
  out_for_delivery: { color: "#0EA5E9", label: "On the way", icon: "truck" },
  delivered:        { color: "#10B981", label: "Delivered",  icon: "check-circle" },
  cancelled:        { color: "#EF4444", label: "Cancelled",  icon: "x-circle" },
  // Phase 2 — a delivered order past its 7-day return window is simply done.
  completed:        { color: "#166534", label: "Completed",  icon: "check-circle" },
  returned:         { color: "#8B5CF6", label: "Returned",   icon: "rotate-ccw" },
};
const FILTERS = ["all", "placed", "confirmed", "shipped", "out_for_delivery", "delivered", "cancelled"] as const;

/** "11 Jun, 4:05 pm" — compact enough for a timeline row. */
function shortWhen(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
  });
}

export default function OrdersScreen() {
  const router = useRouter();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  // Jun 2026 — Swipe left/right to move through the status filters, using
  // the same gesture as the bottom tab bar.
  const filterStripRef = useRef<FlatList<(typeof FILTERS)[number]> | null>(null);
  const stepFilter = useCallback((dir: 1 | -1) => {
    const next = FILTERS.indexOf(filter) + dir;
    if (next < 0 || next >= FILTERS.length) return;
    setFilter(FILTERS[next]);
    filterStripRef.current?.scrollToIndex({ index: next, animated: true, viewPosition: 0.5 });
  }, [filter]);
  const swipeHandlers = useSwipePager({
    onNext: () => stepFilter(1),
    onPrev: () => stepFilter(-1),
  });
  const [preview, setPreview] = useState<Order | null>(null);
  const [chatBusy, setChatBusy] = useState<string | null>(null);
  const [reorderBusy, setReorderBusy] = useState<string | null>(null);

  // Jun 2026 — One-tap Reorder. The backend re-adds whatever is still
  // buyable and tells us what it had to skip (delisted / out of stock /
  // seller no longer delivers here), then we drop the shopper in the bag.
  const reorder = useCallback(async (o: Order) => {
    setReorderBusy(o.id);
    try {
      const { data } = await api.post<{
        added: { name: string; qty: number }[];
        skipped: { name: string; reason: string }[];
      }>(`/orders/${o.id}/reorder`);
      const added = data?.added || [];
      const skipped = data?.skipped || [];
      const lines = [
        `${added.length} item${added.length === 1 ? "" : "s"} added to your bag.`,
        ...(skipped.length
          ? ["", "Couldn't add:", ...skipped.map((s) => `• ${s.name} — ${s.reason}`)]
          : []),
      ];
      notify("Added to bag", lines.join("\n"), [
        { text: "Keep shopping", style: "cancel" },
        { text: "Open bag", onPress: () => router.push("/cart" as any) },
      ]);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail && typeof detail === "object" && detail.code === "reorder_unavailable") {
        const skipped = Array.isArray(detail.skipped) ? detail.skipped : [];
        notify(
          "Can't reorder this",
          [detail.message, "", ...skipped.map((s: any) => `• ${s.name} — ${s.reason}`)].join("\n"),
        );
      } else {
        notify("Couldn't reorder", formatApiError(e));
      }
    } finally { setReorderBusy(null); }
  }, [router]);

  // Jun 2026 — One-tap "Ask this seller". A purchase is proof of
  // relationship, so the backend opens (or reuses) a direct thread with
  // that order's vendor without the usual chat-request handshake.
  const askSeller = useCallback(async (o: Order) => {
    setChatBusy(o.id);
    try {
      const { data } = await api.post<{ thread_id?: string }>(`/orders/${o.id}/chat-vendor`);
      if (data?.thread_id) router.push(`/chat/${data.thread_id}` as any);
      else notify("Couldn't open chat", "Try again in a moment.");
    } catch (e) {
      if (handleChatGateError(e, (p) => router.push(p as any))) return;
      notify("Couldn't open chat", formatApiError(e));
    } finally { setChatBusy(null); }
  }, [router]);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Order[]>("/orders/me");
      setOrders(Array.isArray(data) ? data : []);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  const filtered = useMemo(
    () => filter === "all" ? orders : orders.filter((o) => (o.status || "placed") === filter),
    [orders, filter],
  );

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = { all: orders.length };
    for (const o of orders) {
      const s = o.status || "placed";
      counts[s] = (counts[s] || 0) + 1;
    }
    return counts;
  }, [orders]);

  const shareInvoice = async (o: Order) => {
    const lines = [
      `INVOICE · Slangcart`,
      `Order ${o.order_number || "#" + o.id.slice(0, 8).toUpperCase()}`,
      o.vendor_name ? `Seller: ${o.vendor_name}` : "",
      `Date: ${new Date(o.created_at).toLocaleString("en-IN")}`,
      `Status: ${(o.status || "placed").toUpperCase()}`,
      "",
      ...o.items.map((it, i) =>
        `${i + 1}. ${it.name}  ${it.qty} × ${formatINR(it.price)}  = ${formatINR(it.price * it.qty)}`
      ),
      "",
      `Total: ${formatINR(o.total)}`,
      Number(o.wallet_paid || 0) > 0 ? `Paid from wallet: ${formatINR(Number(o.wallet_paid))}` : "",
      Number(o.cod_due || 0) > 0 ? `Cash on delivery: ${formatINR(Number(o.cod_due))}` : "",
    ].filter(Boolean).join("\n");
    try { await Share.share({ message: lines }); } catch {}
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="orders-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>My orders</Text>
        <TouchableOpacity
          onPress={() => router.push("/returns" as any)}
          style={styles.backBtn}
          testID="orders-my-returns"
        >
          <Feather name="rotate-ccw" size={18} color={colors.primary} />
        </TouchableOpacity>
      </View>

      {/* Filter chips */}
      <FlatList
        ref={filterStripRef}
        horizontal
        showsHorizontalScrollIndicator={false}
        // Keep the strip at its natural height — without this the horizontal
        // list stretches to fill the column and swallows the order cards.
        style={styles.chipStripOuter}
        contentContainerStyle={styles.chipStrip}
        data={FILTERS}
        keyExtractor={(k) => k}
        renderItem={({ item: f }) => {
          const active = filter === f;
          const meta = STATUS_META[f];
          const label = f === "all" ? "All" : (meta?.label || f);
          const count = statusCounts[f] || 0;
          return (
            <TouchableOpacity
              onPress={() => setFilter(f)}
              style={[styles.chip, active && (meta ? { backgroundColor: meta.color, borderColor: meta.color } : styles.chipActive)]}
              testID={`order-filter-${f}`}
            >
              {meta ? <Feather name={meta.icon} size={11} color={active ? "#fff" : meta.color} /> : null}
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
              {count > 0 ? (
                <View style={[styles.countPill, active && { backgroundColor: "rgba(255,255,255,0.25)" }]}>
                  <Text style={[styles.countPillText, active && { color: "#fff" }]}>{count}</Text>
                </View>
              ) : null}
            </TouchableOpacity>
          );
        }}
      />

      {/* Jun 2026 — Swipe surface: a left/right flick anywhere in the list
          body steps through the status filters. */}
      <View style={{ flex: 1 }} {...swipeHandlers}>
      {loading ? (
        <View style={{ paddingHorizontal: spacing.screen, paddingTop: 6 }}>
          {[...Array(5)].map((_, i) => <ListRowSkeleton key={i} />)}
        </View>
      ) : filtered.length === 0 ? (
        <View style={styles.empty}>
          <Feather name="package" size={36} color={colors.textMuted} />
          <Text style={styles.emptyTitle}>No orders {filter !== "all" ? `(${filter})` : "yet"}</Text>
          <Text style={styles.emptyText}>
            {filter === "all"
              ? "Your purchases will appear here."
              : `You don't have any ${filter} orders right now.`}
          </Text>
        </View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
          data={filtered}
          keyExtractor={(o) => o.id}
          renderItem={({ item, index }) => {
            const meta = STATUS_META[item.display_status || item.status || "placed"]
              || STATUS_META[item.status || "placed"] || STATUS_META.placed;
            const totalItems = (item.items || []).reduce((a, i) => a + (i.qty || 0), 0);
            const orderRef = item.order_number || `#${item.id.slice(0, 8).toUpperCase()}`;
            const codDue = Number(item.cod_due || 0);
            const walletPaid = Number(item.wallet_paid || 0);
            const onlinePaid = Number(item.online_paid || 0);
            const cancelled = (item.status || "") === "cancelled";
            // Jun 2026 — GROUP HEADER. Sibling orders from one checkout are
            // adjacent in this newest-first list, so we stamp a summary row
            // above the first card of each multi-seller group.
            const isGroupStart = (item.split_count || 1) > 1
              && (index === 0 || filtered[index - 1]?.group_id !== item.group_id);
            const group = isGroupStart
              ? filtered.filter((o) => o.group_id === item.group_id)
              : [];
            return (
              <FadeSlideIn delay={Math.min(index, 6) * 40}>
              {isGroupStart ? (
                <View style={styles.groupHeader} testID={`order-group-${item.group_id}`}>
                  <View style={styles.groupIcon}>
                    <Feather name="layers" size={13} color={colors.primary} />
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.groupTitle}>
                      1 checkout · {item.split_count} sellers
                    </Text>
                    <Text style={styles.groupSub}>
                      {formatINR(group.reduce((a, o) => a + Number(o.total || 0), 0))} total
                      {" · "}each seller ships and updates separately
                    </Text>
                  </View>
                  <Text style={styles.groupCount}>
                    {group.length}/{item.split_count}
                  </Text>
                </View>
              ) : null}
              <View style={styles.card} testID={`order-${item.id}`}>
                {/* Seller row — the anchor of every card now that a single
                    checkout splits into one order per vendor. */}
                <View style={styles.sellerRow}>
                  <View style={styles.sellerAvatar}>
                    <Feather name="home" size={13} color={colors.primary} />
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.sellerName} numberOfLines={1}>
                      {item.vendor_name || "Slangcart Seller"}
                    </Text>
                    <Text style={styles.orderRef}>
                      {orderRef}
                      {(item.split_count || 1) > 1 ? `  ·  Order ${item.split_index} of ${item.split_count}` : ""}
                    </Text>
                  </View>
                  <View style={[styles.statusPill, { backgroundColor: meta.color }]}>
                    <Feather name={meta.icon} size={9} color="#fff" />
                    <Text style={styles.statusPillText}>{meta.label}</Text>
                  </View>
                </View>

                {/* Step tracker — shared with the seller card (Oct 2026) so
                    the two views can never look different. */}
                {!cancelled ? (
                  <>
                    <View style={styles.trackRow}>
                      <OrderTimeline
                        status={String(item.status || "placed")}
                        testID={`order-track-${item.id}`}
                      />
                    </View>
                    {/* Jun 2026 — live status line: what happened last, when,
                        and who moved it. Full timeline lives in the modal. */}
                    {(() => {
                      const hist = item.status_history || [];
                      const last = hist.length ? hist[hist.length - 1] : null;
                      const when = shortWhen(last?.at);
                      if (!when && !item.estimated_delivery_at) return null;
                      return (
                        <Text style={styles.trackNow} testID={`order-track-now-${item.id}`}>
                          {meta.label}
                          {when ? ` · ${when}` : ""}
                          {last?.by_name && last.by_role !== "customer" ? ` · by ${last.by_name}` : ""}
                        </Text>
                      );
                    })()}
                  </>
                ) : null}

                {/* Thumbnail strip + amount */}
                <TouchableOpacity
                  style={styles.bodyRow}
                  onPress={() => setPreview(item)}
                  activeOpacity={0.8}
                  testID={`order-open-${item.id}`}
                >
                  <View style={styles.thumbRow}>
                    {(item.items || []).slice(0, 3).map((it, idx) => (
                      <View key={idx} style={styles.thumbWrap}>
                        {it.image_url ? (
                          <Image source={{ uri: resolveImageUrl(it.image_url) }} style={styles.thumb} />
                        ) : (
                          <View style={[styles.thumb, { alignItems: "center", justifyContent: "center" }]}>
                            <Feather name="image" size={12} color={colors.textMuted} />
                          </View>
                        )}
                      </View>
                    ))}
                    {(item.items?.length || 0) > 3 ? (
                      <View style={[styles.thumbWrap, styles.thumbMore]}>
                        <Text style={styles.thumbMoreText}>+{(item.items || []).length - 3}</Text>
                      </View>
                    ) : null}
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.itemsLine} numberOfLines={1}>
                      {totalItems} item{totalItems === 1 ? "" : "s"}
                    </Text>
                    <Text style={styles.orderDate}>
                      {new Date(item.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}
                    </Text>
                  </View>
                  <Text style={styles.orderTotal}>{formatINR(item.total)}</Text>
                </TouchableOpacity>

                {/* Payment breakdown — Wallet / Cash / combo */}
                <View style={styles.payRow}>
                  <Feather name={codDue > 0 ? "dollar-sign" : "check-circle"} size={11} color={codDue > 0 ? "#B45309" : "#059669"} />
                  <Text style={styles.payText}>
                    {PAY_LABEL[item.paid_via || "wallet"] || (item.paid_via || "").toUpperCase()}
                    {walletPaid > 0 && codDue > 0
                      ? `  ·  ${formatINR(walletPaid)} paid, ${formatINR(codDue)} on delivery`
                      : codDue > 0 ? `  ·  ${formatINR(codDue)} due on delivery`
                      : walletPaid > 0 && onlinePaid > 0
                        ? `  ·  ${formatINR(walletPaid)} wallet + ${formatINR(onlinePaid)} online`
                        : "  ·  Paid"}
                  </Text>
                </View>

                {/* Jul 2026 — Vendor-provided delivery info (ETA + rider).
                    Rendered here so the customer sees the update instantly
                    without opening the invoice modal. */}
                {(item.estimated_delivery_at || item.delivery_person_name || item.delivery_person_phone) ? (
                  <View style={styles.dlvBox}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
                      <Feather name="truck" size={12} color="#3B82F6" />
                      <Text style={styles.dlvLabel}>DELIVERY UPDATE</Text>
                    </View>
                    {item.estimated_delivery_at ? (
                      <Text style={styles.dlvLine}>Arrives by <Text style={{ fontWeight: "900" }}>{item.estimated_delivery_at}</Text></Text>
                    ) : null}
                    {(item.delivery_person_name || item.delivery_person_phone) ? (
                      <TouchableOpacity
                        onPress={() => {
                          if (item.delivery_person_phone) {
                            try { require("react-native").Linking.openURL(`tel:${item.delivery_person_phone}`); } catch { /* ignore */ }
                          }
                        }}
                        activeOpacity={0.7}
                      >
                        <Text style={styles.dlvLine}>
                          Delivered by <Text style={{ fontWeight: "900" }}>{item.delivery_person_name || "Rider"}</Text>
                          {item.delivery_person_phone ? (
                            <Text style={{ color: "#3B82F6", fontWeight: "800" }}>  ·  📞 {item.delivery_person_phone}</Text>
                          ) : null}
                        </Text>
                      </TouchableOpacity>
                    ) : null}
                  </View>
                ) : null}

                {/* Jun 2026 — Action row: Reorder + Ask this seller + Invoice.
                    Cancel stays gated to "placed" with no vendor action. */}
                <View style={styles.actionRow}>
                  <TouchableOpacity
                    onPress={() => reorder(item)}
                    disabled={reorderBusy === item.id}
                    style={styles.reorderBtn}
                    testID={`reorder-${item.id}`}
                  >
                    {reorderBusy === item.id
                      ? <ActivityIndicator size="small" color={colors.primary} />
                      : <Feather name="rotate-ccw" size={13} color={colors.primary} />}
                    <Text style={styles.reorderBtnText}>Reorder</Text>
                  </TouchableOpacity>
                  {item.vendor_id ? (
                    <TouchableOpacity
                      onPress={() => askSeller(item)}
                      disabled={chatBusy === item.id}
                      style={styles.askBtn}
                      testID={`ask-seller-${item.id}`}
                    >
                      {chatBusy === item.id
                        ? <ActivityIndicator size="small" color={colors.primary} />
                        : <Feather name="message-circle" size={13} color={colors.primary} />}
                      <Text style={styles.askBtnText}>Ask this seller</Text>
                    </TouchableOpacity>
                  ) : null}
                  <TouchableOpacity
                    onPress={() => setPreview(item)}
                    style={styles.invoiceBtn}
                    testID={`invoice-btn-${item.id}`}
                  >
                    <Feather name="file-text" size={13} color={colors.primaryFg} />
                    <Text style={styles.invoiceBtnText}>Invoice</Text>
                  </TouchableOpacity>
                </View>

                {/* Phase 2 — a DELIVERED order inside the 7-day window offers
                    Return (never Cancel). Past the window it just reads
                    Completed, and the button disappears. */}
                {item.return_eligible ? (
                  <TouchableOpacity
                    onPress={() => router.push(`/returns/new?order_id=${item.id}` as any)}
                    style={styles.returnBtn}
                    testID={`user-return-${item.id}`}
                  >
                    <Feather name="rotate-ccw" size={13} color={colors.primary} />
                    <Text style={styles.returnBtnText}>
                      {`Return items · ${Math.max(0, Number(item.return_minutes_left || 0))} min left`}
                    </Text>
                  </TouchableOpacity>
                ) : null}
                {item.has_returns ? (
                  <TouchableOpacity
                    onPress={() => router.push("/returns" as any)}
                    style={styles.returnBtn}
                    testID={`user-view-returns-${item.id}`}
                  >
                    <Feather name="file-text" size={13} color={colors.primary} />
                    <Text style={styles.returnBtnText}>
                      View return{(item.returns || []).length > 1 ? "s" : ""}
                    </Text>
                  </TouchableOpacity>
                ) : null}

                {item.status === "placed" && !item.delivery_info_updated_at ? (
                  <TouchableOpacity
                    onPress={() => {
                      notify(
                        "Cancel this order?",
                        walletPaid + onlinePaid > 0
                          ? `${formatINR(walletPaid + onlinePaid)} will be refunded to your wallet.`
                          : "This cash-on-delivery order will be cancelled.",
                        [
                          { text: "Keep order", style: "cancel" },
                          {
                            text: "Cancel order", style: "destructive",
                            onPress: async () => {
                              try {
                                await api.post(`/orders/${item.id}/cancel`);
                                await load();
                              } catch (err) {
                                notify("Couldn't cancel", formatApiError(err));
                              }
                            },
                          },
                        ],
                      );
                    }}
                    style={styles.cancelBtn}
                    testID={`user-cancel-${item.id}`}
                  >
                    <Feather name="x-circle" size={13} color="#B3261E" />
                    <Text style={styles.cancelBtnText}>Cancel order</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
              </FadeSlideIn>
            );
          }}
        />
      )}
      </View>


      {/* Full-screen invoice preview */}
      <Modal visible={!!preview} animationType="slide" onRequestClose={() => setPreview(null)}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.previewHeader}>
            <TouchableOpacity onPress={() => setPreview(null)} style={styles.backBtn} testID="invoice-close">
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>Invoice</Text>
            <TouchableOpacity
              onPress={() => preview && shareInvoice(preview)}
              style={styles.shareBtn}
              testID="invoice-share"
            >
              <Feather name={Platform.OS === "ios" ? "share" : "share-2"} size={18} color={colors.primary} />
            </TouchableOpacity>
          </View>
          {preview ? (
            <FlatList
              contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
              data={preview.items || []}
              keyExtractor={(_, i) => String(i)}
              ListHeaderComponent={
                <View>
                  {/* Brand header */}
                  <View style={styles.invHead}>
                    <Text style={styles.invBrand}>SLANGCART</Text>
                    <Text style={styles.invBrandSub}>Tax Invoice · {new Date(preview.created_at).toLocaleDateString("en-IN")}</Text>
                  </View>
                  <View style={styles.invMetaCard}>
                    <View style={styles.metaCell}>
                      <Text style={styles.metaLabel}>ORDER</Text>
                      <Text style={styles.metaValue}>{preview.order_number || `#${preview.id.slice(0, 8).toUpperCase()}`}</Text>
                    </View>
                    <View style={styles.metaCell}>
                      <Text style={styles.metaLabel}>SELLER</Text>
                      <Text style={styles.metaValue}>{preview.vendor_name || "Slangcart Seller"}</Text>
                    </View>
                    <View style={styles.metaCell}>
                      <Text style={styles.metaLabel}>DATE</Text>
                      <Text style={styles.metaValue}>{new Date(preview.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</Text>
                    </View>
                    <View style={styles.metaCell}>
                      <Text style={styles.metaLabel}>STATUS</Text>
                      <View style={[styles.miniPill, { backgroundColor: (STATUS_META[preview.status || "placed"] || STATUS_META.placed).color }]}>
                        <Text style={styles.miniPillText}>{(STATUS_META[preview.status || "placed"] || STATUS_META.placed).label}</Text>
                      </View>
                    </View>
                    <View style={styles.metaCell}>
                      <Text style={styles.metaLabel}>PAYMENT</Text>
                      <Text style={styles.metaValue}>{PAY_LABEL[preview.paid_via || "wallet"] || (preview.paid_via || "WALLET").toUpperCase()}</Text>
                    </View>
                  </View>

                  {/* Jun 2026 — live tracking timeline: every stage with the
                      exact time it happened and who moved it. */}
                  {(preview.status || "placed") !== "cancelled" ? (
                    <View style={styles.timelineBox} testID="order-timeline">
                      <Text style={styles.addrLabel}>TRACKING</Text>
                      {preview.estimated_delivery_at ? (
                        <Text style={styles.timelineEta}>
                          Arrives by <Text style={{ fontWeight: "900" }}>{preview.estimated_delivery_at}</Text>
                        </Text>
                      ) : null}
                      {STEPS.map((s, i) => {
                        const curIdx = STEPS.indexOf((preview.status || "placed") as any);
                        const done = i <= curIdx;
                        const entry = (preview.status_history || []).filter((h) => h.status === s).pop();
                        const m = STATUS_META[s];
                        return (
                          <View key={s} style={styles.tlRow}>
                            <View style={styles.tlRail}>
                              <View style={[styles.tlDot, done && { backgroundColor: m.color, borderColor: m.color }]}>
                                {done ? <Feather name="check" size={9} color="#fff" /> : null}
                              </View>
                              {i < STEPS.length - 1 ? (
                                <View style={[styles.tlLine, i < curIdx && { backgroundColor: m.color }]} />
                              ) : null}
                            </View>
                            <View style={{ flex: 1, paddingBottom: 14 }}>
                              <Text style={[styles.tlTitle, !done && { color: colors.textMuted, fontWeight: "600" }]}>
                                {m.label}
                              </Text>
                              <Text style={styles.tlMeta}>
                                {entry
                                  ? `${shortWhen(entry.at)}${entry.by_name && entry.by_role !== "customer" ? ` · ${entry.by_name}` : ""}`
                                  : done ? "Done" : "Pending"}
                              </Text>
                            </View>
                          </View>
                        );
                      })}
                    </View>
                  ) : null}

                  {preview.shipping_address ? (
                    <View style={styles.addrBox}>
                      <Text style={styles.addrLabel}>DELIVER TO</Text>
                      <Text style={styles.addrLine}>
                        {[preview.shipping_address.line1, preview.shipping_address.line2].filter(Boolean).join(", ")}
                      </Text>
                      <Text style={styles.addrLine}>
                        {[preview.shipping_address.city, preview.shipping_address.state, preview.shipping_address.pincode].filter(Boolean).join(", ")}
                      </Text>
                      {preview.shipping_address.phone ? (
                        <Text style={styles.addrLine}>📞 {preview.shipping_address.phone}</Text>
                      ) : null}
                    </View>
                  ) : null}

                  <Text style={styles.section}>ITEMS</Text>
                </View>
              }
              renderItem={({ item, index }) => (
                <View style={styles.lineRow}>
                  {item.image_url ? (
                    <Image source={{ uri: resolveImageUrl(item.image_url) }} style={styles.lineImg} />
                  ) : (
                    <View style={[styles.lineImg, { alignItems: "center", justifyContent: "center" }]}>
                      <Feather name="image" size={16} color={colors.textMuted} />
                    </View>
                  )}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.lineName}>{index + 1}. {item.name}</Text>
                    <Text style={styles.lineDetail}>{formatINR(item.price)} × {item.qty}</Text>
                  </View>
                  <Text style={styles.lineAmt}>{formatINR(item.price * item.qty)}</Text>
                </View>
              )}
              ListFooterComponent={
                <View style={styles.footerBox}>
                  <View style={styles.divider} />
                  {(() => {
                    const w = Number(preview.wallet_paid || 0);
                    const on = Number(preview.online_paid || 0);
                    const cod = Number(preview.cod_due || 0);
                    // Only worth breaking down when more than one source paid.
                    if ([w, on, cod].filter((x) => x > 0).length < 2) return null;
                    return (
                      <View style={{ gap: 6, marginBottom: 10 }}>
                        {w > 0 ? (
                          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                            <Text style={styles.lineDetail}>Paid from wallet</Text>
                            <Text style={styles.lineAmt}>{formatINR(w)}</Text>
                          </View>
                        ) : null}
                        {on > 0 ? (
                          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                            <Text style={styles.lineDetail}>Paid online (Razorpay)</Text>
                            <Text style={styles.lineAmt}>{formatINR(on)}</Text>
                          </View>
                        ) : null}
                        {cod > 0 ? (
                          <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                            <Text style={styles.lineDetail}>Cash on delivery</Text>
                            <Text style={[styles.lineAmt, { color: "#B45309" }]}>{formatINR(cod)}</Text>
                          </View>
                        ) : null}
                      </View>
                    );
                  })()}
                  <View style={styles.grandRow}>
                    <Text style={styles.grandLabel}>Grand Total</Text>
                    <Text style={styles.grandValue}>{formatINR(preview.total)}</Text>
                  </View>
                  {Number(preview.cod_due || 0) > 0 ? (
                    <View style={styles.codBanner}>
                      <Feather name="dollar-sign" size={13} color="#92400E" />
                      <Text style={styles.codBannerText}>
                        Hand {formatINR(Number(preview.cod_due))} in cash to the delivery agent
                      </Text>
                    </View>
                  ) : null}
                  <Text style={styles.thanks}>Thank you for shopping with Slangcart 💚</Text>
                </View>
              }
            />
          ) : null}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 4 },
  previewHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  shareBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  chipStripOuter: { flexGrow: 0, flexShrink: 0 },
  chipStrip: { paddingHorizontal: spacing.screen, paddingVertical: 8, gap: 6 },
  chip: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 99, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  chipTextActive: { color: "#fff" },
  countPill: { minWidth: 20, paddingHorizontal: 5, paddingVertical: 1, backgroundColor: colors.brand100, borderRadius: 99, alignItems: "center" },
  countPillText: { fontSize: 10, fontWeight: "800", color: colors.textMain },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40, gap: 6 },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.textMuted, textAlign: "center" },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 10 },
  // Jun 2026 — "1 checkout · N sellers" group summary row
  groupHeader: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8, padding: 12, borderRadius: 14, backgroundColor: colors.brand100, borderWidth: 1, borderColor: colors.primary },
  groupIcon: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  groupTitle: { fontSize: 13, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  groupSub: { fontSize: 10, fontWeight: "700", color: colors.textMuted, marginTop: 2 },
  groupCount: { fontSize: 12, fontWeight: "900", color: colors.primary },
  // Jun 2026 — Redesigned order card
  sellerRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  sellerAvatar: { width: 30, height: 30, borderRadius: 15, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  sellerName: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  orderRef: { fontSize: 10, color: colors.textMuted, fontWeight: "700", marginTop: 2, letterSpacing: 0.4 },
  trackRow: { marginTop: 14, marginBottom: 4 },
  trackSeg: { flex: 1 },
  trackDotRow: { flexDirection: "row", alignItems: "center" },
  trackDot: { width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  trackLine: { flex: 1, height: 2, backgroundColor: colors.border, marginHorizontal: 3 },
  trackLabel: { fontSize: 8.5, color: colors.textMuted, fontWeight: "700", marginTop: 5, letterSpacing: 0.1 },
  trackNow: { fontSize: 10.5, color: colors.textMuted, fontWeight: "700", marginTop: 8, marginLeft: 2 },
  // Jun 2026 — vertical tracking timeline inside the order modal
  timelineBox: { marginTop: 12, padding: 12, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border },
  timelineEta: { fontSize: 12, color: colors.textMain, marginTop: 6, marginBottom: 10 },
  tlRow: { flexDirection: "row", gap: 10, marginTop: 8 },
  tlRail: { width: 18, alignItems: "center" },
  tlDot: {
    width: 18, height: 18, borderRadius: 9, borderWidth: 1.5,
    borderColor: colors.border, backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  tlLine: { flex: 1, width: 2, backgroundColor: colors.border, marginVertical: 2, minHeight: 16 },
  tlTitle: { fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  tlMeta: { fontSize: 10.5, color: colors.textMuted, marginTop: 2 },
  bodyRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 12 },
  itemsLine: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  payRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border },
  payText: { fontSize: 11, color: colors.textMuted, fontWeight: "700", flex: 1 },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 10 },
  askBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 11, borderRadius: 10, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface, minHeight: 44 },
  askBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  reorderBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 11, borderRadius: 10, borderWidth: 1, borderColor: colors.primary + "55", backgroundColor: colors.primary + "12", minHeight: 44 },
  reorderBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },

  invoiceBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 11, borderRadius: 10, backgroundColor: colors.primary, minHeight: 44 },
  invoiceBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 6 },
  orderId: { fontSize: 13, fontWeight: "800", color: colors.textMain, letterSpacing: 0.5 },
  orderDate: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  orderTotal: { fontSize: 16, fontWeight: "900", color: colors.primary },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 3, borderRadius: 99 },
  statusPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  thumbRow: { flexDirection: "row", gap: 6 },
  thumbWrap: { width: 40, height: 40 },
  thumb: { width: 40, height: 40, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  thumbMore: { alignItems: "center", justifyContent: "center", backgroundColor: colors.brand100, borderRadius: 8 },
  thumbMoreText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  metaRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border },  metaText: { fontSize: 11, color: colors.textMuted, fontWeight: "600" },
  viewBtn: { flexDirection: "row", alignItems: "center", gap: 2 },
  viewBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  // Jul 2026 — Vendor-provided delivery update box (customer view)
  dlvBox: {
    marginTop: 10, padding: 10, borderRadius: 10,
    backgroundColor: "#EFF6FF", borderWidth: 1, borderColor: "#DBEAFE",
  },
  dlvLabel: { fontSize: 9, fontWeight: "800", color: "#1D4ED8", letterSpacing: 0.8 },
  dlvLine: { fontSize: 12, color: colors.textMain, marginTop: 2, lineHeight: 18 },
  // Jul 2026 — User cancel-order button (gated to placed + no vendor action)
  cancelBtn: {
    marginTop: 10, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: 10,
    borderWidth: 1, borderColor: "#FCA5A5", backgroundColor: "#FEF2F2",
  },
  cancelBtnText: { fontSize: 12, fontWeight: "800", color: "#B3261E" },
  // Phase 2 — Return items (delivered, inside the 7-day window).
  returnBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: 8, minHeight: 44, borderRadius: 999, borderWidth: 1,
    borderColor: colors.primary, backgroundColor: colors.brand100, paddingHorizontal: 14,
  },
  returnBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  // Invoice preview styles
  invHead: { alignItems: "center", marginTop: 8, marginBottom: 14, paddingVertical: 14, borderBottomWidth: 2, borderBottomColor: colors.primary },
  invBrand: { fontSize: 28, fontWeight: "900", color: colors.primary, letterSpacing: 3 },
  invBrandSub: { fontSize: 12, color: colors.textMuted, marginTop: 4, fontWeight: "600", letterSpacing: 1 },
  invMetaCard: { flexDirection: "row", flexWrap: "wrap", backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 12 },
  metaCell: { width: "50%", paddingVertical: 6 },
  metaLabel: { fontSize: 9, color: colors.textMuted, fontWeight: "800", letterSpacing: 1 },
  metaValue: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 3 },
  miniPill: { alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 99, marginTop: 3 },
  miniPillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  addrBox: { marginTop: 12, padding: 12, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border },
  addrLabel: { fontSize: 9, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginBottom: 6 },
  addrLine: { fontSize: 13, color: colors.textMain, fontWeight: "600", lineHeight: 18 },
  section: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginTop: 16, marginBottom: 8 },
  lineRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  lineImg: { width: 42, height: 42, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  lineName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  lineDetail: { fontSize: 11, color: colors.textMuted, marginTop: 3 },
  lineAmt: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  footerBox: { marginTop: 8 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 10 },
  grandRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 14, backgroundColor: colors.brand100, borderRadius: radii.card },
  grandLabel: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  grandValue: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  thanks: { textAlign: "center", fontSize: 12, color: colors.textMuted, marginTop: 18, fontStyle: "italic" },
  codBanner: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, padding: 12, borderRadius: 12, backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FDE68A" },
  codBannerText: { flex: 1, fontSize: 12, fontWeight: "800", color: "#92400E" },
});
