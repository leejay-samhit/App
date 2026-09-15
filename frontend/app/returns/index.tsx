// My returns — status + full stage timeline (Phase 2, Jun-2026).
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator,
  RefreshControl, Modal, ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, spacing, formatINR } from "../../src/theme";

type Stage = { stage: string; at: string; by_name?: string; by_role?: string; note?: string };
type ReturnDoc = {
  id: string;
  return_number: string;
  order_number?: string;
  vendor_name?: string | null;
  items: { name: string; qty: number; refund_amount: number }[];
  refund_amount: number;
  refund_paid?: number;
  cashback_reversed?: number;
  status: string;
  refund_status?: string;
  inventory_restored?: boolean;
  reason?: string;
  decision_note?: string;
  created_at: string;
  timeline?: Stage[];
};

const META: Record<string, { label: string; color: string; bg: string; icon: any }> = {
  requested: { label: "Awaiting seller", color: "#92400E", bg: "#FEF3C7", icon: "clock" },
  approved: { label: "Approved · send it back", color: "#1E40AF", bg: "#DBEAFE", icon: "check" },
  returned: { label: "Item received", color: "#5B21B6", bg: "#EDE9FE", icon: "package" },
  refund_pending: { label: "Refund pending", color: "#92400E", bg: "#FEF3C7", icon: "alert-circle" },
  refunded: { label: "Refunded", color: "#166534", bg: "#DCFCE7", icon: "check-circle" },
  completed: { label: "Completed", color: "#166534", bg: "#DCFCE7", icon: "check-circle" },
  rejected: { label: "Declined", color: "#991B1B", bg: "#FEE2E2", icon: "x-circle" },
};

const STAGE_COPY: Record<string, string> = {
  delivered: "Order delivered",
  return_eligible: "Return window open",
  requested: "Return requested",
  vendor_review: "Seller reviewing",
  approved: "Return approved",
  rejected: "Return declined",
  returned: "Product returned",
  refund_pending: "Refund pending",
  refund_processed: "Refund processed",
  inventory_restored: "Stock restored",
  completed: "Completed",
};

function when(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
  });
}

export default function MyReturnsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<ReturnDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [open, setOpen] = useState<ReturnDoc | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: ReturnDoc[] }>("/returns/me");
      setItems(data.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="returns-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>My returns</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />
          }
          ListEmptyComponent={
            <View style={styles.emptyWrap}>
              <Feather name="rotate-ccw" size={28} color={colors.textMuted} />
              <Text style={styles.empty}>
                No returns yet. You can return a delivered item within 7 days from My orders.
              </Text>
            </View>
          }
          renderItem={({ item }) => {
            const m = META[item.status] || META.requested;
            return (
              <TouchableOpacity
                onPress={() => setOpen(item)}
                activeOpacity={0.85}
                style={styles.card}
                testID={`return-card-${item.return_number}`}
              >
                <View style={styles.cardTop}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.retNo}>{item.return_number}</Text>
                    <Text style={styles.meta}>
                      Order {item.order_number} · {item.vendor_name || "Seller"} · {when(item.created_at)}
                    </Text>
                  </View>
                  <Text style={styles.amount}>{formatINR(item.refund_amount)}</Text>
                </View>
                <View style={[styles.badge, { backgroundColor: m.bg }]}>
                  <Feather name={m.icon} size={11} color={m.color} />
                  <Text style={[styles.badgeText, { color: m.color }]}>{m.label}</Text>
                </View>
                <Text style={styles.itemsLine} numberOfLines={2}>
                  {(item.items || []).map((i) => `${i.qty} × ${i.name}`).join(", ")}
                </Text>
                {item.status === "refunded" || item.status === "completed" ? (
                  <Text style={styles.paidLine}>
                    {formatINR(item.refund_paid || 0)} credited to your wallet
                    {(item.cashback_reversed || 0) > 0.009
                      ? ` · ${formatINR(item.cashback_reversed || 0)} cashback reversed` : ""}
                  </Text>
                ) : null}
                {item.status === "rejected" && item.decision_note ? (
                  <Text style={styles.rejectLine}>Seller said: {item.decision_note}</Text>
                ) : null}
              </TouchableOpacity>
            );
          }}
        />
      )}

      <Modal visible={!!open} animationType="slide" onRequestClose={() => setOpen(null)}>
        <SafeAreaView style={styles.safe} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setOpen(null)} style={styles.iconBtn} testID="return-detail-close">
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>{open?.return_number}</Text>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen }}>
            <View style={styles.block}>
              <Text style={styles.blockTitle}>Refund</Text>
              <Line label="Items" value={formatINR(open?.refund_amount || 0)} />
              {(open?.cashback_reversed || 0) > 0.009 ? (
                <Line label="Cashback reversed" value={`− ${formatINR(open?.cashback_reversed || 0)}`} />
              ) : null}
              <Line label="Credited to wallet" value={formatINR(open?.refund_paid || 0)} bold />
              <Line label="Stock restored" value={open?.inventory_restored ? "Yes" : "Not yet"} />
              {open?.reason ? <Line label="Reason" value={open.reason} /> : null}
            </View>

            <View style={styles.block}>
              <Text style={styles.blockTitle}>Every step</Text>
              {(open?.timeline || []).map((s, idx) => (
                <View key={`${s.stage}-${idx}`} style={styles.stageRow}>
                  <View style={styles.stageDot} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.stageName}>{STAGE_COPY[s.stage] || s.stage}</Text>
                    <Text style={styles.stageMeta}>
                      {when(s.at)}{s.by_name ? ` · ${s.by_name}` : ""}
                    </Text>
                    {s.note ? <Text style={styles.stageNote}>{s.note}</Text> : null}
                  </View>
                </View>
              ))}
            </View>
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function Line({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={styles.lineRow}>
      <Text style={styles.lineLabel}>{label}</Text>
      <Text style={[styles.lineValue, bold && { fontWeight: "900" }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  iconBtn: { padding: 8, minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  emptyWrap: { alignItems: "center", marginTop: 60, gap: 12, paddingHorizontal: 24 },
  empty: { color: colors.textMuted, textAlign: "center", lineHeight: 20 },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14,
    padding: 14, marginBottom: 10, gap: 8,
  },
  cardTop: { flexDirection: "row", alignItems: "flex-start" },
  retNo: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 3 },
  amount: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  badge: {
    flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start",
    paddingHorizontal: 9, paddingVertical: 4, borderRadius: 999,
  },
  badgeText: { fontSize: 10, fontWeight: "900", textTransform: "uppercase", letterSpacing: 0.4 },
  itemsLine: { fontSize: 12, color: colors.textMain },
  paidLine: { fontSize: 12, fontWeight: "700", color: colors.success },
  rejectLine: { fontSize: 12, color: colors.error },
  block: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14,
    padding: 16, marginBottom: 12,
  },
  blockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 10 },
  lineRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4, gap: 12 },
  lineLabel: { fontSize: 13, color: colors.textMuted },
  lineValue: { fontSize: 13, fontWeight: "700", color: colors.textMain, flexShrink: 1, textAlign: "right" },
  stageRow: { flexDirection: "row", gap: 10, paddingVertical: 7 },
  stageDot: {
    width: 9, height: 9, borderRadius: 999, backgroundColor: colors.primary, marginTop: 5,
  },
  stageName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  stageMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  stageNote: { fontSize: 11, color: colors.textMain, marginTop: 3, fontStyle: "italic" },
});
