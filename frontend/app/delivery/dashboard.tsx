// Delivery Partner dashboard — money first, then today's work.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator,
  TouchableOpacity,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, spacing, radii, formatINR } from "../../src/theme";
import { DPHeader, DPTabBar, DPMoneyCard, DPEmpty } from "../../src/delivery-ui";

export default function DeliveryDashboard() {
  const router = useRouter();
  const [nw, setNw] = useState<any>(null);
  const [shops, setShops] = useState<any[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [denied, setDenied] = useState(false);

  const load = useCallback(async () => {
    try {
      const [n, v, o] = await Promise.all([
        api.get("/delivery-partner/me/net-worth"),
        api.get("/delivery-partner/me/vendors"),
        api.get("/delivery-partner/me/orders?limit=1"),
      ]);
      setNw(n.data);
      setShops((v.data as any)?.items || []);
      setCounts((o.data as any)?.counts || {});
      setDenied(false);
    } catch (e: any) {
      if (e?.response?.status === 403) setDenied(true);
    } finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const live = (counts.confirmed || 0) + (counts.shipped || 0) + (counts.out_for_delivery || 0);

  if (loading) {
    return (
      <SafeAreaView style={s.safe} edges={["top"]}>
        <ActivityIndicator color={colors.primary} style={{ marginTop: 60 }} />
      </SafeAreaView>
    );
  }
  if (denied) {
    return (
      <SafeAreaView style={s.safe} edges={["top"]}>
        <Stack.Screen options={{ headerShown: false }} />
        <DPEmpty
          icon="lock"
          title="Not a delivery partner yet"
          body="Once admin approves your application this dashboard opens up."
        />
        <TouchableOpacity style={s.link} onPress={() => router.replace("/(tabs)/dashboard" as any)}>
          <Text style={s.linkText}>Back to app</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <DPHeader title="Delivery" subtitle={nw?.name || ""} />
      <ScrollView
        contentContainerStyle={{ paddingBottom: 30 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={colors.primary} />
        }
      >
        <DPMoneyCard
          cashInHand={Number(nw?.cash_in_hand || 0)}
          personalWallet={Number(nw?.personal_wallet || 0)}
          inSync={!!nw?.in_sync}
          onPay={() => router.push("/delivery/net-worth" as any)}
        />

        <View style={s.statRow}>
          <TouchableOpacity
            style={s.stat}
            onPress={() => router.push("/delivery/wallet" as any)}
            testID="dp-stat-wallet"
          >
            <Feather name="credit-card" size={17} color={colors.success} />
            <Text style={s.statValue}>{formatINR(Number(nw?.personal_wallet || 0))}</Text>
            <Text style={s.statLabel}>MY WALLET</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={s.stat}
            onPress={() => router.push("/delivery/orders" as any)}
            testID="dp-stat-live"
          >
            <Feather name="truck" size={17} color={colors.primary} />
            <Text style={s.statValue}>{live}</Text>
            <Text style={s.statLabel}>ON THE ROAD</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={s.stat}
            onPress={() => router.push("/delivery/orders?status=delivered" as any)}
            testID="dp-stat-done"
          >
            <Feather name="check-circle" size={17} color={colors.success} />
            <Text style={s.statValue}>{nw?.deliveries_completed || 0}</Text>
            <Text style={s.statLabel}>DELIVERED</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={s.stat}
            onPress={() => router.push("/delivery/vendors" as any)}
            testID="dp-stat-shops"
          >
            <Feather name="shopping-bag" size={17} color="#1F5E9E" />
            <Text style={s.statValue}>{shops.length}</Text>
            <Text style={s.statLabel}>MY SHOPS</Text>
          </TouchableOpacity>
        </View>

        <Text style={s.section}>SHOPS I DELIVER FOR</Text>
        {shops.length === 0 ? (
          <DPEmpty
            icon="shopping-bag"
            title="No shops mapped yet"
            body="Admin maps the shops you deliver for. They'll appear here as soon as that's done."
          />
        ) : (
          shops.slice(0, 5).map((v) => (
            <TouchableOpacity
              key={v.vendor_id}
              style={s.shopRow}
              onPress={() => router.push(`/delivery/orders?vendor_id=${v.vendor_id}` as any)}
              testID={`dp-shop-${v.vendor_id}`}
            >
              <View style={s.shopIcon}>
                <Feather name="shopping-bag" size={15} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.shopName} numberOfLines={1}>{v.shop_name}</Text>
                <Text style={s.shopMeta}>
                  {v.open_orders} open
                  {v.cash_to_remit > 0 ? ` · ${formatINR(v.cash_to_remit)} cash held` : ""}
                </Text>
              </View>
              <Feather name="chevron-right" size={17} color={colors.textMuted} />
            </TouchableOpacity>
          ))
        )}
        {shops.length > 5 ? (
          <TouchableOpacity style={s.link} onPress={() => router.push("/delivery/vendors" as any)}>
            <Text style={s.linkText}>See all {shops.length} shops</Text>
          </TouchableOpacity>
        ) : null}

        <Text style={s.note}>{nw?.earnings_note || ""}</Text>
      </ScrollView>
      <DPTabBar />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  statRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, paddingHorizontal: spacing.screen },
  stat: {
    flexBasis: "47%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, padding: 12, gap: 3, minHeight: 84,
    justifyContent: "center",
  },
  statValue: { fontSize: 19, fontWeight: "900", color: colors.textMain, letterSpacing: -0.5 },
  statLabel: { fontSize: 9, letterSpacing: 0.8, fontWeight: "900", color: colors.textMuted },
  section: {
    fontSize: 10, letterSpacing: 1.4, fontWeight: "900", color: colors.textMuted,
    paddingHorizontal: spacing.screen, marginTop: 24, marginBottom: 10,
  },
  shopRow: {
    flexDirection: "row", alignItems: "center", gap: 11,
    marginHorizontal: spacing.screen, marginBottom: 8, padding: 12,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, minHeight: 56,
  },
  shopIcon: {
    width: 34, height: 34, borderRadius: 10, backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  shopName: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  shopMeta: { fontSize: 11.5, color: colors.textMuted, fontWeight: "600", marginTop: 1 },
  link: { alignItems: "center", paddingVertical: 14, minHeight: 44, justifyContent: "center" },
  linkText: { color: colors.primary, fontWeight: "800", fontSize: 13.5 },
  note: {
    fontSize: 11.5, color: colors.textMuted, fontWeight: "600",
    paddingHorizontal: spacing.screen, marginTop: 18, lineHeight: 17,
  },
});
