// All past recharges, newest first — each one repeatable in a tap.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator, TouchableOpacity,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api } from "../src/api";
import { colors, spacing, radii, formatINR } from "../src/theme";
import { RechargeHistoryRow, useRepeatRecharge, type RechargeRow } from "../src/recharge-history";
import { RazorpayWebViewModal } from "../src/recharge-pay";

export default function RechargeHistoryScreen() {
  const router = useRouter();
  const [items, setItems] = useState<RechargeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: RechargeRow[] }>("/recharge/history");
      setItems(data.items || []);
    } catch { setItems([]); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const { repeat, paying, rzpHtml, handleMessage, cancel } = useRepeatRecharge(load);
  const spent = items.reduce((t, r) => t + Number(r.amount || 0), 0);

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} style={s.backBtn} testID="recharge-history-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Recharge history</Text>
          <Text style={s.sub}>
            {items.length
              ? `${items.length} recharge${items.length === 1 ? "" : "s"} · ${formatINR(spent)} total`
              : "Your past recharges"}
          </Text>
        </View>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 50 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 32 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
              tintColor={colors.primary} />
          }
          renderItem={({ item }) => (
            <RechargeHistoryRow row={item} onRepeat={repeat} busy={paying === item.product_id} />
          )}
          ListEmptyComponent={
            <View style={s.empty}>
              <Feather name="smartphone" size={22} color={colors.textMuted} />
              <Text style={s.emptyTitle}>No recharges yet</Text>
              <Text style={s.emptyBody}>Your mobile and DTH recharges will show up here, ready to repeat.</Text>
              <TouchableOpacity onPress={() => router.replace("/recharge" as any)} style={s.cta}>
                <Text style={s.ctaText}>Recharge now</Text>
              </TouchableOpacity>
            </View>
          }
        />
      )}
      <RazorpayWebViewModal html={rzpHtml} onMessage={handleMessage} onCancel={cancel} />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.screen, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  sub: { fontSize: 11.5, fontWeight: "600", color: colors.textMuted, marginTop: 1 },
  empty: { alignItems: "center", paddingTop: 60, gap: 8 },
  emptyTitle: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  emptyBody: { fontSize: 12.5, color: colors.textMuted, textAlign: "center", paddingHorizontal: 30, lineHeight: 18 },
  cta: {
    marginTop: 10, minHeight: 44, paddingHorizontal: 20, borderRadius: radii.card,
    backgroundColor: colors.primary, alignItems: "center", justifyContent: "center",
  },
  ctaText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13.5 },
});
