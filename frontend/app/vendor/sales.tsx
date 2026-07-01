// Sales history — list past sales with filters.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, ActivityIndicator, Alert, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { colors, spacing, formatINR } from "../../src/theme";
import { listSales, cancelSale, refundSale, PosSale } from "../../src/vendor-pos-client";
import { formatApiError } from "../../src/api";

export default function VendorSalesHistory() {
  const router = useRouter();
  const [items, setItems] = useState<PosSale[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await listSales({ q: q || undefined, status: status || undefined, limit: 100 });
      setItems(r.items); setTotal(r.total);
    } catch (e) { Alert.alert("Load failed", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [q, status]);

  useEffect(() => { load(); }, [load]);

  const doCancel = (s: PosSale) => {
    Alert.alert("Cancel this sale?", `Invoice ${s.invoice_no} · ${formatINR(s.totals.grand_total)}`, [
      { text: "No", style: "cancel" },
      { text: "Yes, cancel", style: "destructive", onPress: async () => { try { await cancelSale(s.id); load(); } catch (e) { Alert.alert("Failed", formatApiError(e)); } } },
    ]);
  };
  const doRefund = (s: PosSale) => {
    Alert.alert("Refund this sale?", `Invoice ${s.invoice_no} will be marked refunded and stock restored.`, [
      { text: "No", style: "cancel" },
      { text: "Yes, refund", style: "destructive", onPress: async () => { try { await refundSale(s.id); load(); } catch (e) { Alert.alert("Failed", formatApiError(e)); } } },
    ]);
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Sales history</Text>
        <View style={{ flex: 1 }} />
        <TouchableOpacity onPress={() => router.push("/vendor/pos" as any)} style={styles.newBtn}><Feather name="plus" size={14} color="#fff" /><Text style={{ color: "#fff", fontWeight: "700", marginLeft: 4 }}>New</Text></TouchableOpacity>
      </View>
      <View style={{ padding: spacing.screen }}>
        <View style={styles.searchWrap}>
          <Feather name="search" size={16} color={colors.textMuted} />
          <TextInput value={q} onChangeText={setQ} onSubmitEditing={load} placeholder="Search invoice / customer / product" placeholderTextColor={colors.textMuted} style={styles.searchInput} returnKeyType="search" />
        </View>
        <View style={{ flexDirection: "row", marginTop: 8, gap: 6 }}>
          {["", "completed", "cancelled", "refunded"].map(s => (
            <TouchableOpacity key={s || "all"} onPress={() => setStatus(s)} style={[styles.chip, status === s && { backgroundColor: colors.brand100, borderColor: colors.primary }]}>
              <Text style={{ color: status === s ? colors.primary : colors.textMuted, fontWeight: "700", fontSize: 12 }}>{s || "All"}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingTop: 0 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      >
        <Text style={{ color: colors.textMuted, marginBottom: 8, fontSize: 12 }}>{total} sale{total === 1 ? "" : "s"}</Text>
        {loading ? <ActivityIndicator color={colors.primary} style={{ marginTop: 24 }} /> : items.length === 0 ? (
          <Text style={{ color: colors.textMuted, textAlign: "center", marginTop: 40 }}>No sales yet — tap “New” to ring up your first bill.</Text>
        ) : items.map(s => (
          <View key={s.id} style={styles.card}>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.inv}>{s.invoice_no}</Text>
                <Text style={styles.meta}>{new Date(s.created_at).toLocaleString("en-IN")} · {s.customer?.name}</Text>
              </View>
              <Text style={styles.amount}>{formatINR(s.totals.grand_total)}</Text>
            </View>
            <View style={{ flexDirection: "row", flexWrap: "wrap", marginTop: 6, gap: 6 }}>
              <View style={[styles.badge, s.status === "completed" ? { backgroundColor: "#DCFCE7" } : s.status === "cancelled" ? { backgroundColor: "#FEE2E2" } : { backgroundColor: "#FEF3C7" }]}>
                <Text style={[styles.badgeText, s.status === "completed" ? { color: "#166534" } : s.status === "cancelled" ? { color: "#991B1B" } : { color: "#92400E" }]}>{s.status}</Text>
              </View>
              <Text style={styles.meta2}>{(s.items || []).length} item{(s.items || []).length === 1 ? "" : "s"} · GST {formatINR(s.totals.gst_total)}</Text>
            </View>
            <View style={{ flexDirection: "row", marginTop: 10, gap: 8 }}>
              <TouchableOpacity onPress={() => router.push(`/vendor/invoices?open=${s.id}` as any)} style={styles.linkBtn}><Feather name="eye" size={13} color={colors.primary} /><Text style={styles.linkText}>View</Text></TouchableOpacity>
              {s.status === "completed" ? (
                <>
                  <TouchableOpacity onPress={() => doCancel(s)} style={styles.linkBtn}><Feather name="x-circle" size={13} color="#B91C1C" /><Text style={[styles.linkText, { color: "#B91C1C" }]}>Cancel</Text></TouchableOpacity>
                  <TouchableOpacity onPress={() => doRefund(s)} style={styles.linkBtn}><Feather name="corner-down-left" size={13} color="#B91C1C" /><Text style={[styles.linkText, { color: "#B91C1C" }]}>Refund</Text></TouchableOpacity>
                </>
              ) : null}
            </View>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { padding: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  newBtn: { flexDirection: "row", alignItems: "center", backgroundColor: colors.primary, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10 },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceMuted, borderRadius: 10, paddingHorizontal: 12, height: 40 },
  searchInput: { flex: 1, color: colors.textMain },
  chip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  card: { padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 8 },
  inv: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  meta2: { fontSize: 11, color: colors.textMuted },
  amount: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  badgeText: { fontSize: 10, fontWeight: "800", textTransform: "uppercase" },
  linkBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4, paddingHorizontal: 6 },
  linkText: { color: colors.primary, fontWeight: "700", fontSize: 12 },
});
