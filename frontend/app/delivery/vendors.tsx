// Delivery Partner — the shops admin mapped to this rider.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator,
  TouchableOpacity, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, spacing, radii, formatINR } from "../../src/theme";
import { DPHeader, DPTabBar, DPEmpty, useDPSwipe } from "../../src/delivery-ui";

export default function DeliveryVendors() {
  const swipe = useDPSwipe();
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/delivery-partner/me/vendors");
      setItems((data as any)?.items || []);
    } catch { setItems([]); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={s.safe} edges={["top"]} {...swipe}>
      <Stack.Screen options={{ headerShown: false }} />
      <DPHeader title="My shops" subtitle={`${items.length} mapped by admin`} />
      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(v) => v.vendor_id}
          contentContainerStyle={{ paddingBottom: 24 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
              tintColor={colors.primary} />
          }
          ListEmptyComponent={
            <DPEmpty
              icon="shopping-bag"
              title="No shops mapped yet"
              body="Admin decides which shops you deliver for. As soon as that's done they appear here with their orders."
            />
          }
          renderItem={({ item: v }) => (
            <TouchableOpacity
              style={s.card}
              onPress={() => router.push(`/delivery/orders?vendor_id=${v.vendor_id}` as any)}
              testID={`dp-vendor-${v.vendor_id}`}
            >
              <View style={s.top}>
                <View style={s.icon}>
                  <Feather name="shopping-bag" size={16} color={colors.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.name} numberOfLines={1}>{v.shop_name}</Text>
                  <Text style={s.meta}>
                    {v.pincode ? `Pincode ${v.pincode}` : "—"}
                  </Text>
                </View>
                <Feather name="chevron-right" size={18} color={colors.textMuted} />
              </View>
              {v.address ? (
                <Text style={s.addr} numberOfLines={2}>{v.address}</Text>
              ) : null}
              <View style={s.chipRow}>
                <View style={s.chip}>
                  <Text style={s.chipLabel}>OPEN ORDERS</Text>
                  <Text style={s.chipValue}>{v.open_orders}</Text>
                </View>
                <View style={s.chip}>
                  <Text style={s.chipLabel}>CASH HELD</Text>
                  <Text style={s.chipValue}>{formatINR(v.cash_to_remit || 0)}</Text>
                </View>
                {v.phone ? (
                  <TouchableOpacity
                    style={s.callBtn}
                    onPress={() => Linking.openURL(`tel:${v.phone}`)}
                    testID={`dp-vendor-call-${v.vendor_id}`}
                  >
                    <Feather name="phone" size={14} color={colors.primary} />
                    <Text style={s.callText}>Call shop</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            </TouchableOpacity>
          )}
        />
      )}
      <DPTabBar />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  card: {
    marginHorizontal: spacing.screen, marginBottom: 12, padding: 13,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  top: { flexDirection: "row", alignItems: "center", gap: 11 },
  icon: {
    width: 36, height: 36, borderRadius: 11, backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  name: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  meta: { fontSize: 11.5, color: colors.textMuted, fontWeight: "600", marginTop: 1 },
  addr: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 9, lineHeight: 17 },
  chipRow: { flexDirection: "row", gap: 8, marginTop: 11, alignItems: "center" },
  chip: {
    backgroundColor: colors.surfaceMuted, borderRadius: 10,
    paddingHorizontal: 11, paddingVertical: 7,
  },
  chipLabel: { fontSize: 8.5, letterSpacing: 0.8, fontWeight: "900", color: colors.textMuted },
  chipValue: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginTop: 1 },
  callBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, marginLeft: "auto",
    paddingHorizontal: 11, minHeight: 44, justifyContent: "center",
  },
  callText: { color: colors.primary, fontSize: 12.5, fontWeight: "800" },
});
