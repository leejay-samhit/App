// Delivery Partner — order management for MAPPED shops only.
// confirmed → shipped → on the way → delivered, plus the delivery info the
// customer sees. The server owns all money side-effects.
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, SectionList, RefreshControl, ActivityIndicator,
  TouchableOpacity, Alert, Linking, Modal, TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, radii, formatINR } from "../../src/theme";
import { DPHeader, DPTabBar, DPStatusFilter, DPEmpty } from "../../src/delivery-ui";

// The only forward moves a rider can make, in order (see NEXT below).
const LABELS: Record<string, string> = {
  placed: "New", confirmed: "Confirmed", shipped: "Shipped",
  out_for_delivery: "On the way", delivered: "Delivered",
  cancelled: "Cancelled", returned: "Returned", refunded: "Refunded",
};
const NEXT: Record<string, string> = {
  placed: "confirmed", confirmed: "shipped",
  shipped: "out_for_delivery", out_for_delivery: "delivered",
};
const PILL: Record<string, string> = {
  placed: "#B45309", confirmed: "#1D4ED8", shipped: "#7C3AED",
  out_for_delivery: "#0E7490", delivered: "#15803D",
};

export default function DeliveryOrders() {
  const router = useRouter();
  const params = useLocalSearchParams<{ status?: string; vendor_id?: string }>();
  const [status, setStatus] = useState(String(params.status || "all"));
  const vendorId = params.vendor_id ? String(params.vendor_id) : "";
  const [items, setItems] = useState<any[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState("");
  // Delivery info sheet
  const [infoFor, setInfoFor] = useState<any | null>(null);
  const [riderName, setRiderName] = useState("");
  const [riderPhone, setRiderPhone] = useState("");

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (status !== "all") qs.set("status", status);
      if (vendorId) qs.set("vendor_id", vendorId);
      const { data } = await api.get(`/delivery-partner/me/orders?${qs.toString()}`);
      setItems((data as any)?.items || []);
      setCounts((data as any)?.counts || {});
    } catch { setItems([]); }
    finally { setLoading(false); setRefreshing(false); }
  }, [status, vendorId]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Oct 2026 — riders think shop-by-shop, so the list is grouped retailer-wise
  // with a sticky header per shop showing how many orders are still open there.
  const sections = useMemo(() => {
    const byShop = new Map<string, { title: string; vendorId: string; data: any[] }>();
    for (const o of items) {
      const key = o.vendor_id || o.vendor_name || "shop";
      if (!byShop.has(key)) {
        byShop.set(key, {
          title: o.vendor_name || "Shop",
          vendorId: o.vendor_id || "",
          data: [],
        });
      }
      byShop.get(key)!.data.push(o);
    }
    return Array.from(byShop.values()).sort((a, b) => b.data.length - a.data.length);
  }, [items]);

  const advance = async (o: any, to: string) => {
    setBusy(o.id);
    try {
      await api.patch(`/delivery-partner/orders/${o.id}/status`, { status: to });
      if (to === "delivered" && Number(o.cash_to_collect || 0) > 0) {
        Alert.alert(
          "Cash collected",
          `${formatINR(Number(o.cash_to_collect))} has been added to the cash you owe Slangcart. Pay it in from the Money tab.`,
        );
      }
      await load();
    } catch (e) {
      Alert.alert("Could not update", formatApiError(e));
    } finally { setBusy(""); }
  };

  const saveInfo = async () => {
    if (!infoFor) return;
    setBusy(infoFor.id);
    try {
      await api.patch(`/delivery-partner/orders/${infoFor.id}/status`, {
        status: infoFor.status === "placed" ? "confirmed" : infoFor.status,
        delivery_person_name: riderName,
        delivery_person_phone: riderPhone,
      });
      setInfoFor(null);
      await load();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(""); }
  };

  const renderItem = ({ item: o }: { item: any }) => {
    const next = NEXT[o.status];
    const addr = o.shipping_address || {};
    return (
      <View style={s.card} testID={`dp-order-${o.id}`}>
        <View style={s.cardTop}>
          <View style={{ flex: 1 }}>
            <Text style={s.orderNo}>{o.order_number}</Text>
            <Text style={s.shop} numberOfLines={1}>{o.vendor_name || "Shop"}</Text>
          </View>
          <View style={[s.pill, { backgroundColor: PILL[o.status] || colors.textMuted }]}>
            <Text style={s.pillText}>{(LABELS[o.status] || o.status).toUpperCase()}</Text>
          </View>
        </View>

        <View style={s.divider} />

        <View style={s.line}>
          <Feather name="user" size={13} color={colors.textMuted} />
          <Text style={s.lineText} numberOfLines={1}>{o.buyer_name}</Text>
          {o.buyer_phone ? (
            <TouchableOpacity
              onPress={() => Linking.openURL(`tel:${o.buyer_phone}`)}
              style={s.callBtn}
              testID={`dp-call-${o.id}`}
            >
              <Feather name="phone" size={13} color={colors.primary} />
              <Text style={s.callText}>Call</Text>
            </TouchableOpacity>
          ) : null}
        </View>
        <View style={s.line}>
          <Feather name="map-pin" size={13} color={colors.textMuted} />
          <Text style={s.lineText} numberOfLines={2}>
            {[addr.line1, addr.line2, addr.city, addr.pincode].filter(Boolean).join(", ") || "—"}
          </Text>
        </View>
        <View style={s.line}>
          <Feather name="shopping-cart" size={13} color={colors.textMuted} />
          <Text style={s.lineText}>
            {formatINR(o.total || 0)}
            {Number(o.cash_to_collect || 0) > 0
              ? ` · collect ${formatINR(Number(o.cash_to_collect))} cash`
              : " · fully prepaid"}
          </Text>
        </View>

        {Number(o.cash_to_collect || 0) > 0 && o.status !== "delivered" ? (
          <View style={s.cashStrip}>
            <Feather name="dollar-sign" size={12} color="#92400E" />
            <Text style={s.cashStripText}>
              Collect {formatINR(Number(o.cash_to_collect))} in cash on delivery
            </Text>
          </View>
        ) : null}

        <View style={s.actions}>
          {next ? (
            <TouchableOpacity
              style={[s.primaryBtn, busy === o.id && { opacity: 0.5 }]}
              disabled={busy === o.id}
              onPress={() => advance(o, next)}
              testID={`dp-advance-${o.id}`}
            >
              {busy === o.id ? (
                <ActivityIndicator color={colors.primaryFg} size="small" />
              ) : (
                <>
                  <Feather name="arrow-right-circle" size={14} color={colors.primaryFg} />
                  <Text style={s.primaryBtnText}>Mark {LABELS[next]}</Text>
                </>
              )}
            </TouchableOpacity>
          ) : (
            <View style={s.doneBox}>
              <Feather name="check" size={13} color={colors.success} />
              <Text style={s.doneText}>{LABELS[o.status] || o.status}</Text>
            </View>
          )}
          {o.status !== "delivered" ? (
            <TouchableOpacity
              style={s.ghostBtn}
              onPress={() => {
                setInfoFor(o);
                setRiderName(o.delivery_person_name || "");
                setRiderPhone(o.delivery_person_phone || "");
              }}
              testID={`dp-info-${o.id}`}
            >
              <Feather name="edit-3" size={13} color={colors.primary} />
              <Text style={s.ghostBtnText}>Delivery info</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <DPHeader
        title="Orders"
        subtitle={vendorId ? "One shop" : "From the shops mapped to you"}
      />
      {vendorId ? (
        <TouchableOpacity
          style={s.clearFilter}
          onPress={() => router.replace("/delivery/orders" as any)}
          testID="dp-clear-shop-filter"
        >
          <Feather name="x" size={12} color={colors.primary} />
          <Text style={s.clearFilterText}>Show all shops</Text>
        </TouchableOpacity>
      ) : null}
      <TouchableOpacity
        style={s.customerSwitch}
        onPress={() => router.push("/delivery/customers" as any)}
        testID="dp-orders-customer-view"
      >
        <Feather name="users" size={13} color={colors.primary} />
        <Text style={s.customerSwitchText}>Deliver customer-wise instead</Text>
        <Feather name="chevron-right" size={15} color={colors.primary} />
      </TouchableOpacity>
      <DPStatusFilter value={status} counts={counts} onChange={setStatus} />
      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(o) => o.id}
          renderItem={renderItem}
          stickySectionHeadersEnabled
          renderSectionHeader={({ section }) => (
            <View style={s.shopHeader}>
              <Feather name="home" size={13} color={colors.primary} />
              <Text style={s.shopHeaderText} numberOfLines={1}>{section.title}</Text>
              <Text style={s.shopHeaderCount}>
                {`${section.data.length} order${section.data.length === 1 ? "" : "s"}`}
              </Text>
              {!vendorId && section.vendorId ? (
                <TouchableOpacity
                  onPress={() => router.push(`/delivery/orders?vendor_id=${section.vendorId}` as any)}
                  testID={`dp-only-shop-${section.vendorId}`}
                  style={s.onlyBtn}
                >
                  <Text style={s.onlyBtnText}>Only this shop</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          )}
          contentContainerStyle={{ paddingBottom: 24 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
              tintColor={colors.primary} />
          }
          ListEmptyComponent={
            <DPEmpty
              icon="package"
              title="Nothing here"
              body="Orders from the shops admin mapped to you show up here as customers place them."
            />
          }
        />
      )}

      <Modal visible={!!infoFor} transparent animationType="slide"
        onRequestClose={() => setInfoFor(null)}>
        <View style={s.overlay}>
          <View style={s.sheet}>
            <View style={s.sheetHandle} />
            <Text style={s.sheetTitle}>Delivery information</Text>
            <Text style={s.sheetSub}>The customer sees this on their order tracking.</Text>
            <TextInput style={s.input} value={riderName} onChangeText={setRiderName}
              placeholder="Your name" placeholderTextColor={colors.textMuted}
              testID="dp-info-name" />
            <TextInput style={s.input} value={riderPhone} onChangeText={setRiderPhone}
              placeholder="Contact number" keyboardType="phone-pad"
              placeholderTextColor={colors.textMuted} testID="dp-info-phone" />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity style={[s.sheetBtn, { backgroundColor: colors.surfaceMuted }]}
                onPress={() => setInfoFor(null)}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[s.sheetBtn, { backgroundColor: colors.primary }]}
                onPress={saveInfo} testID="dp-info-save">
                <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Save</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <DPTabBar />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  shopHeader: {
    flexDirection: "row", alignItems: "center", gap: 7,
    paddingHorizontal: spacing.screen, paddingVertical: 9,
    backgroundColor: colors.background,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  shopHeaderText: { flex: 1, fontSize: 13, fontWeight: "800", color: colors.textMain },
  shopHeaderCount: { fontSize: 11.5, fontWeight: "700", color: colors.textMuted },
  onlyBtn: {
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, minHeight: 30, justifyContent: "center",
  },
  onlyBtnText: { fontSize: 11, fontWeight: "700", color: colors.primary },
  card: {
    marginHorizontal: spacing.screen, marginBottom: 12, padding: 13,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  cardTop: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  orderNo: { fontSize: 14.5, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  shop: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 1 },
  pill: { paddingHorizontal: 9, paddingVertical: 4, borderRadius: 999 },
  pillText: { color: "#fff", fontSize: 9, fontWeight: "900", letterSpacing: 0.6 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 10 },
  line: { flexDirection: "row", alignItems: "center", gap: 7, marginBottom: 6 },
  lineText: { flex: 1, fontSize: 12.5, color: colors.textMain, fontWeight: "600" },
  callBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 7 },
  callText: { color: colors.primary, fontSize: 12, fontWeight: "800" },
  cashStrip: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4,
    backgroundColor: "#FEF3C7", borderRadius: 8, paddingHorizontal: 9, paddingVertical: 7,
  },
  cashStripText: { flex: 1, color: "#92400E", fontSize: 11.5, fontWeight: "800" },
  actions: { flexDirection: "row", gap: 8, marginTop: 11 },
  primaryBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.primary, borderRadius: 999, paddingVertical: 11, minHeight: 44,
  },
  primaryBtnText: { color: colors.primaryFg, fontSize: 13, fontWeight: "800" },
  ghostBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5,
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 13, minHeight: 44,
  },
  ghostBtnText: { color: colors.primary, fontSize: 12.5, fontWeight: "800" },
  doneBox: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.surfaceMuted, borderRadius: 999, paddingVertical: 11, minHeight: 44,
  },
  doneText: { color: colors.textMain, fontSize: 13, fontWeight: "800" },
  clearFilter: {
    flexDirection: "row", alignItems: "center", gap: 5,
    marginHorizontal: spacing.screen, marginBottom: 10, alignSelf: "flex-start",
    paddingHorizontal: 11, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.surfaceMuted, minHeight: 36,
  },
  clearFilterText: { color: colors.primary, fontSize: 12, fontWeight: "800" },
  customerSwitch: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: spacing.screen, marginBottom: 8, paddingHorizontal: 12,
    minHeight: 44, borderRadius: radii.card, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  customerSwitchText: { flex: 1, color: colors.primary, fontSize: 12.5, fontWeight: "800" },

  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: 18, paddingBottom: Platform.OS === "ios" ? 34 : 22,
  },
  sheetHandle: {
    width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: 14,
  },
  sheetTitle: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  sheetSub: { fontSize: 12.5, color: colors.textMuted, fontWeight: "600", marginTop: 3, marginBottom: 14 },
  input: {
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 13, paddingVertical: 12,
    fontSize: 14, color: colors.textMain, marginBottom: 10, minHeight: 46,
  },
  sheetBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    borderRadius: radii.button, paddingVertical: 13, minHeight: 46,
  },
});
