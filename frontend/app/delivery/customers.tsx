// Delivery Partner — CUSTOMER-WISE delivery run (Jun 2026 owner request).
//
// The shop-wise list ("My shops") answers "what does this seller owe me?".
// This screen answers the question the rider actually has at the doorstep:
// "everything this one customer ordered, from every shop, in one card".
// One tap moves ALL of that customer's orders forward, and the shop-wise
// list updates automatically because both views read the same orders.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator,
  TouchableOpacity, Alert, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, radii, formatINR } from "../../src/theme";
import { DPHeader, DPTabBar, DPEmpty } from "../../src/delivery-ui";

const PILL: Record<string, string> = {
  placed: "#B45309", confirmed: "#1D4ED8", shipped: "#7C3AED",
  out_for_delivery: "#0E7490", delivered: "#15803D",
};

/** Orders of ONE customer, bucketed per shop — the rider hands over seller by
 *  seller, so the cash figure has to be readable per shop as well. */
function groupByShop(orders: any[]) {
  const map = new Map<string, { shop_name: string; orders: any[]; value: number; cash: number }>();
  for (const o of orders || []) {
    const key: string = o.shop_name || "Shop";
    const g = map.get(key) || { shop_name: key, orders: [] as any[], value: 0, cash: 0 };
    g.orders.push(o);
    g.value = Math.round((g.value + Number(o.total || 0)) * 100) / 100;
    g.cash = Math.round((g.cash + Number(o.cash_to_collect || 0)) * 100) / 100;
    map.set(key, g);
  }
  return [...map.values()].sort((a, b) => b.cash - a.cash);
}

export default function DeliveryCustomers() {
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/delivery-partner/me/customers?status=open");
      setItems((data as any)?.items || []);
    } catch { setItems([]); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const run = async (c: any, status?: string) => {
    setBusy(c.user_id);
    try {
      const { data } = await api.post<any>(
        `/delivery-partner/customers/${c.user_id}/advance`,
        status ? { status } : {},
      );
      await load();
      const cash = Number(data.cash_collected || 0);
      Alert.alert(
        `${data.updated} order${data.updated === 1 ? "" : "s"} updated`,
        [
          data.skipped?.length ? `${data.skipped.length} skipped (already done).` : "",
          data.failed?.length ? `${data.failed.length} could not be moved.` : "",
          cash > 0
            ? `${formatINR(cash)} cash added to what you owe Slangcart — pay it in from Money.`
            : "",
        ].filter(Boolean).join("\n") || "All set.",
      );
    } catch (e) {
      Alert.alert("Could not update", formatApiError(e));
    } finally { setBusy(""); }
  };

  const confirmAllDelivered = (c: any) =>
    Alert.alert(
      "Mark all delivered?",
      `${c.open_count} order${c.open_count === 1 ? "" : "s"} for ${c.name}` +
      (c.cash_to_collect > 0
        ? `. Collect ${formatINR(c.cash_to_collect)} in cash before you confirm.`
        : "."),
      [
        { text: "Not yet", style: "cancel" },
        { text: "Delivered", style: "default", onPress: () => run(c, "delivered") },
      ],
    );

  if (loading) {
    return (
      <SafeAreaView style={s.safe} edges={["top"]}>
        <ActivityIndicator color={colors.primary} style={{ marginTop: 60 }} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <DPHeader title="Customers" subtitle="All orders of one customer, together" />

      <View style={s.switchRow}>
        <TouchableOpacity
          style={[s.switchChip, s.switchChipOn]}
          testID="dp-view-customers"
        >
          <Feather name="users" size={13} color={colors.primaryFg} />
          <Text style={[s.switchText, { color: colors.primaryFg }]}>Customer-wise</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={s.switchChip}
          onPress={() => router.push("/delivery/orders" as any)}
          testID="dp-view-shops"
        >
          <Feather name="shopping-bag" size={13} color={colors.textMain} />
          <Text style={s.switchText}>Shop-wise</Text>
        </TouchableOpacity>
      </View>

      <ScrollView
        contentContainerStyle={{ paddingBottom: 30 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={colors.primary} />
        }
      >
        {items.length === 0 ? (
          <DPEmpty
            icon="users"
            title="No open deliveries"
            body="When customers of your mapped shops place orders, every customer shows up here with all their orders together."
          />
        ) : (
          items.map((c) => {
            const expanded = !!open[c.user_id];
            return (
              <View key={c.user_id} style={s.card} testID={`dp-customer-${c.user_id}`}>
                <View style={s.cardTop}>
                  <View style={s.avatar}>
                    <Text style={s.avatarText}>{(c.name || "C").slice(0, 1).toUpperCase()}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.name} numberOfLines={1}>{c.name}</Text>
                    <Text style={s.meta}>
                      {`${c.open_count} open · ${c.item_count} item${c.item_count === 1 ? "" : "s"} · ${c.shops.length} shop${c.shops.length === 1 ? "" : "s"}`}
                    </Text>
                  </View>
                  {c.phone ? (
                    <TouchableOpacity
                      onPress={() => Linking.openURL(`tel:${c.phone}`)}
                      style={s.callBtn}
                      testID={`dp-customer-call-${c.user_id}`}
                    >
                      <Feather name="phone" size={14} color={colors.primary} />
                    </TouchableOpacity>
                  ) : null}
                </View>

                {c.address ? (
                  <View style={s.line}>
                    <Feather name="map-pin" size={13} color={colors.textMuted} />
                    <Text style={s.lineText} numberOfLines={2}>
                      {c.address}{c.pincode ? ` · ${c.pincode}` : ""}
                    </Text>
                  </View>
                ) : null}

                <View style={s.statRow}>
                  <View style={s.stat}>
                    <Text style={s.statLabel}>ORDER VALUE</Text>
                    <Text style={s.statValue}>{formatINR(c.order_value)}</Text>
                  </View>
                  <View style={s.stat}>
                    <Text style={s.statLabel}>CASH TO COLLECT</Text>
                    <Text style={[s.statValue, c.cash_to_collect > 0 && { color: colors.primary }]}>
                      {formatINR(c.cash_to_collect)}
                    </Text>
                  </View>
                </View>

                {/* Which shops this doorstep covers, at a glance. */}
                <View style={s.shopStrip}>
                  {groupByShop(c.orders).map((g) => (
                    <View key={g.shop_name} style={s.shopChip}>
                      <Text style={s.shopChipName} numberOfLines={1}>{g.shop_name}</Text>
                      <Text style={s.shopChipCount}>{g.orders.length}</Text>
                    </View>
                  ))}
                </View>

                <View style={s.actionRow}>
                  {c.next_status && c.next_status !== "delivered" ? (
                    <TouchableOpacity
                      style={[s.actionBtn, busy === c.user_id && { opacity: 0.5 }]}
                      disabled={!!busy}
                      onPress={() => run(c)}
                      testID={`dp-customer-next-${c.user_id}`}
                    >
                      {busy === c.user_id ? <ActivityIndicator color={colors.primaryFg} size="small" /> : (
                        <>
                          <Feather name="arrow-right-circle" size={15} color={colors.primaryFg} />
                          <Text style={s.actionText}>{`All → ${c.next_label}`}</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  ) : null}
                  <TouchableOpacity
                    style={[s.actionBtn, s.actionDone, busy === c.user_id && { opacity: 0.5 }]}
                    disabled={!!busy}
                    onPress={() => confirmAllDelivered(c)}
                    testID={`dp-customer-deliver-${c.user_id}`}
                  >
                    <Feather name="check-circle" size={15} color={colors.primaryFg} />
                    <Text style={s.actionText}>Mark all delivered</Text>
                  </TouchableOpacity>
                </View>
                <TouchableOpacity
                  style={s.expandBtn}
                  onPress={() => setOpen((o) => ({ ...o, [c.user_id]: !expanded }))}
                  testID={`dp-customer-expand-${c.user_id}`}
                >
                  <Text style={s.expandText}>
                    {expanded ? "Hide orders" : `Show ${c.order_count} order${c.order_count === 1 ? "" : "s"}`}
                  </Text>
                  <Feather name={expanded ? "chevron-up" : "chevron-down"} size={15} color={colors.primary} />
                </TouchableOpacity>

                {/* Shop-wise inside the doorstep: the rider still has to hand
                    over per seller, so the orders are grouped by shop with a
                    running cash figure for each. */}
                {expanded ? (
                  <View style={{ gap: 10 }}>
                    {groupByShop(c.orders).map((g) => (
                      <View key={g.shop_name} style={s.shopBlock}>
                        <View style={s.shopHead}>
                          <Feather name="shopping-bag" size={12} color={colors.textMuted} />
                          <Text style={s.shopName} numberOfLines={1}>{g.shop_name}</Text>
                          <Text style={s.shopMeta}>
                            {g.orders.length} · {formatINR(g.value)}
                          </Text>
                        </View>
                        {g.cash > 0 ? (
                          <Text style={s.shopCash}>{`Collect ${formatINR(g.cash)} cash for this shop`}</Text>
                        ) : null}
                        {g.orders.map((o: any) => (
                          <View key={o.id} style={s.orderRow} testID={`dp-customer-order-${o.id}`}>
                            <View style={s.orderLeft}>
                              <Text style={s.orderNo} numberOfLines={1}>{o.order_number}</Text>
                              {(o.items || []).slice(0, 3).map((i: any, idx: number) => (
                                <Text key={idx} style={s.orderItem} numberOfLines={1}>
                                  {`${i.qty} × ${i.name}`}
                                </Text>
                              ))}
                            </View>
                            <View style={s.orderRight}>
                              <View style={[s.pill, { backgroundColor: PILL[o.status] || colors.textMuted }]}>
                                <Text style={s.pillText}>{(o.status_label || o.status).toUpperCase()}</Text>
                              </View>
                              <Text style={s.orderAmt}>{formatINR(o.total)}</Text>
                              {o.cash_to_collect > 0 ? (
                                <Text style={s.orderCash}>{`COD ${formatINR(o.cash_to_collect)}`}</Text>
                              ) : (
                                <Text style={s.orderPaid}>Prepaid</Text>
                              )}
                            </View>
                          </View>
                        ))}
                      </View>
                    ))}
                  </View>
                ) : null}

              </View>
            );
          })
        )}
      </ScrollView>
      <DPTabBar />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  switchRow: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.screen, paddingBottom: 10 },
  switchChip: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12,
    minHeight: 36, borderRadius: 18, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, justifyContent: "center",
  },
  switchChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  switchText: { fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  card: {
    marginHorizontal: spacing.screen, marginBottom: 10, padding: 13,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, gap: 10,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 10 },
  avatar: {
    width: 38, height: 38, borderRadius: 19, backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  avatarText: { fontSize: 15, fontWeight: "900", color: colors.primary },
  name: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  meta: { fontSize: 11.5, color: colors.textMuted, fontWeight: "600", marginTop: 1 },
  callBtn: {
    width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted,
  },
  line: { flexDirection: "row", alignItems: "flex-start", gap: 7 },
  lineText: { flex: 1, fontSize: 12.5, color: colors.textMain, fontWeight: "600", lineHeight: 17 },
  statRow: { flexDirection: "row", gap: 8 },
  stat: {
    flex: 1, backgroundColor: colors.surfaceMuted, borderRadius: 10, padding: 9,
  },
  statLabel: { fontSize: 9, letterSpacing: 0.7, fontWeight: "900", color: colors.textMuted },
  statValue: {
    fontSize: 15, fontWeight: "900", color: colors.textMain, marginTop: 2,
    fontVariant: ["tabular-nums"],
  },
  expandBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 44, borderRadius: 10, backgroundColor: colors.surfaceMuted,
  },
  expandText: { fontSize: 12.5, fontWeight: "800", color: colors.primary },
  orderRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 10,
    borderRadius: 10, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  orderLeft: { flex: 1, minWidth: 0, gap: 2 },
  orderRight: { width: 104, alignItems: "flex-end", gap: 3 },
  orderNo: { fontSize: 12.5, fontWeight: "900", color: colors.textMain },
  orderItem: { fontSize: 11, color: colors.textMuted, fontWeight: "600" },
  orderAmt: { fontSize: 13.5, fontWeight: "900", color: colors.textMain, fontVariant: ["tabular-nums"] },
  orderCash: { fontSize: 10.5, fontWeight: "900", color: colors.primary, fontVariant: ["tabular-nums"] },
  orderPaid: { fontSize: 10.5, fontWeight: "800", color: colors.textMuted },
  // Shop grouping inside one customer
  shopStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  shopChip: {
    flexDirection: "row", alignItems: "center", gap: 6, maxWidth: "100%",
    paddingHorizontal: 9, paddingVertical: 5, borderRadius: 14,
    backgroundColor: colors.surfaceMuted,
  },
  shopChipName: { flexShrink: 1, fontSize: 11, fontWeight: "800", color: colors.textMain },
  shopChipCount: {
    fontSize: 10, fontWeight: "900", color: colors.primaryFg, overflow: "hidden",
    backgroundColor: colors.primary, borderRadius: 8, minWidth: 16,
    textAlign: "center", paddingHorizontal: 4, paddingVertical: 1,
  },
  shopBlock: { gap: 6 },
  shopHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  shopName: { flex: 1, fontSize: 11.5, fontWeight: "900", color: colors.textMain },
  shopMeta: { fontSize: 11, fontWeight: "800", color: colors.textMuted, fontVariant: ["tabular-nums"] },
  shopCash: { fontSize: 10.5, fontWeight: "800", color: colors.primary },
  pill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  pillText: { fontSize: 8.5, fontWeight: "900", color: "#FFFFFF", letterSpacing: 0.5 },
  actionRow: { flexDirection: "row", gap: 8 },
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, minHeight: 44, borderRadius: 10, backgroundColor: colors.primary,
  },
  actionDone: { backgroundColor: colors.success },
  actionText: { fontSize: 12.5, fontWeight: "800", color: colors.primaryFg },
});
