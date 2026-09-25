// Admin — Delivery Partners: approve applications and map shops to riders.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator,
  TouchableOpacity, Alert, Modal, TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, radii, formatINR } from "../../src/theme";

export default function AdminDeliveryPartners() {
  const router = useRouter();
  const [tab, setTab] = useState<"pending" | "partners">("pending");
  const [apps, setApps] = useState<any[]>([]);
  const [partners, setPartners] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState("");
  // Vendor mapping sheet
  const [mapFor, setMapFor] = useState<any | null>(null);
  const [vendors, setVendors] = useState<any[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [mapBusy, setMapBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, p] = await Promise.all([
        api.get("/admin/delivery-partners/applications?status=pending"),
        api.get("/admin/delivery-partners"),
      ]);
      setApps((a.data as any)?.items || []);
      setPartners((p.data as any)?.items || []);
    } catch { /* empty state is valid */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const decide = async (app: any, approve: boolean) => {
    setBusy(app.id);
    try {
      await api.post(
        `/admin/delivery-partners/applications/${app.id}/${approve ? "approve" : "reject"}`,
        { note: "" },
      );
      await load();
    } catch (e) {
      Alert.alert("Could not update", formatApiError(e));
    } finally { setBusy(""); }
  };

  const openMapping = async (dp: any) => {
    setMapFor(dp);
    setSearch("");
    setVendors([]);
    try {
      const { data } = await api.get(`/admin/delivery-partners/${dp.id}/vendors`);
      setVendors((data as any)?.vendors || []);
      setPicked(new Set((data as any)?.mapped_vendor_ids || []));
    } catch (e) {
      Alert.alert("Could not load shops", formatApiError(e));
      setMapFor(null);
    }
  };

  const saveMapping = async () => {
    if (!mapFor) return;
    setMapBusy(true);
    try {
      await api.put(`/admin/delivery-partners/${mapFor.id}/vendors`, {
        vendor_ids: Array.from(picked),
      });
      setMapFor(null);
      await load();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setMapBusy(false); }
  };

  const shown = vendors.filter((v) =>
    !search.trim() || String(v.shop || "").toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} style={s.iconBtn} testID="adp-back">
          <Feather name="chevron-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={s.headerTitle}>Delivery partners</Text>
      </View>

      <View style={s.tabRow}>
        <TouchableOpacity onPress={() => setTab("pending")}
          style={[s.tabChip, tab === "pending" && s.tabChipOn]} testID="adp-tab-pending">
          <Text style={[s.tabText, tab === "pending" && s.tabTextOn]}>
            Applications{apps.length ? ` ${apps.length}` : ""}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => setTab("partners")}
          style={[s.tabChip, tab === "partners" && s.tabChipOn]} testID="adp-tab-partners">
          <Text style={[s.tabText, tab === "partners" && s.tabTextOn]}>
            Partners{partners.length ? ` ${partners.length}` : ""}
          </Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingBottom: 40 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
              tintColor={colors.primary} />
          }
        >
          {tab === "pending" ? (
            apps.length === 0 ? (
              <Text style={s.empty}>No applications waiting.</Text>
            ) : (
              apps.map((a) => (
                <View key={a.id} style={s.card} testID={`adp-app-${a.id}`}>
                  <Text style={s.name}>{a.full_name}</Text>
                  <Text style={s.meta}>{a.email}{a.phone ? ` · ${a.phone}` : ""}</Text>
                  <View style={s.hr} />
                  <Row label="Vehicle" value={`${a.vehicle_type || "—"}${a.vehicle_number ? ` · ${a.vehicle_number}` : ""}`} />
                  <Row label="Radius" value={`${a.delivery_radius_km || 0} km`} />
                  <Row label="Pincodes" value={(a.pincodes || []).join(", ") || "—"} />
                  <Row label="Area" value={[a.city, a.state].filter(Boolean).join(", ") || "—"} />
                  {a.address ? <Row label="Address" value={a.address} /> : null}
                  <View style={s.actions}>
                    <TouchableOpacity
                      style={[s.approveBtn, busy === a.id && { opacity: 0.5 }]}
                      disabled={busy === a.id}
                      onPress={() => decide(a, true)}
                      testID={`adp-approve-${a.id}`}
                    >
                      {busy === a.id ? <ActivityIndicator color={colors.primaryFg} size="small" />
                        : <Text style={s.approveText}>Approve</Text>}
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={s.rejectBtn}
                      disabled={busy === a.id}
                      onPress={() => decide(a, false)}
                      testID={`adp-reject-${a.id}`}
                    >
                      <Text style={s.rejectText}>Reject</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ))
            )
          ) : partners.length === 0 ? (
            <Text style={s.empty}>No delivery partners yet.</Text>
          ) : (
            partners.map((p) => (
              <View key={p.id} style={s.card} testID={`adp-partner-${p.id}`}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <View style={[s.dot, {
                    backgroundColor: p.is_delivery_partner_approved ? colors.success : colors.warning,
                  }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.name}>{p.name || p.email}</Text>
                    <Text style={s.meta}>
                      {(p.dp_status || "pending").toUpperCase()}
                      {p.dp_phone ? ` · ${p.dp_phone}` : ""}
                    </Text>
                  </View>
                </View>
                <View style={s.hr} />
                <Row label="Shops mapped" value={String(p.mapped_vendor_count || 0)} />
                <Row label="Cash in hand" value={formatINR(p.cash_in_hand || 0)} />
                <Row label="Pincodes" value={(p.dp_pincodes || []).join(", ") || "—"} />
                {p.is_delivery_partner_approved ? (
                  <TouchableOpacity
                    style={s.mapBtn}
                    onPress={() => openMapping(p)}
                    testID={`adp-map-${p.id}`}
                  >
                    <Feather name="link" size={14} color={colors.primary} />
                    <Text style={s.mapText}>Map shops to this rider</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            ))
          )}
        </ScrollView>
      )}

      <Modal visible={!!mapFor} animationType="slide" onRequestClose={() => setMapFor(null)}>
        <SafeAreaView style={s.safe} edges={["top"]}>
          <View style={s.header}>
            <TouchableOpacity onPress={() => setMapFor(null)} style={s.iconBtn} testID="adp-map-close">
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={s.headerTitle} numberOfLines={1}>
              {mapFor?.name || mapFor?.email}
            </Text>
          </View>
          <Text style={s.mapHint}>
            {`Pick the shops this rider delivers for. He only ever sees orders from these shops. ${picked.size} selected.`}
          </Text>
          <TextInput
            style={s.search}
            value={search}
            onChangeText={setSearch}
            placeholder="Search shops"
            placeholderTextColor={colors.textMuted}
            testID="adp-map-search"
          />
          <ScrollView contentContainerStyle={{ paddingBottom: 90 }}>
            {shown.map((v) => {
              const on = picked.has(v.id);
              return (
                <TouchableOpacity
                  key={v.id}
                  style={s.vendorRow}
                  onPress={() => {
                    const next = new Set(picked);
                    if (on) next.delete(v.id); else next.add(v.id);
                    setPicked(next);
                  }}
                  testID={`adp-pick-${v.id}`}
                >
                  <Feather
                    name={on ? "check-square" : "square"}
                    size={19}
                    color={on ? colors.primary : colors.textMuted}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={s.vendorName} numberOfLines={1}>{v.shop}</Text>
                    <Text style={s.meta}>{v.pincode ? `Pincode ${v.pincode}` : v.email}</Text>
                  </View>
                </TouchableOpacity>
              );
            })}
            {shown.length === 0 ? <Text style={s.empty}>No shops match.</Text> : null}
          </ScrollView>
          <View style={s.mapFooter}>
            <TouchableOpacity
              style={[s.saveBtn, mapBusy && { opacity: 0.6 }]}
              onPress={saveMapping}
              disabled={mapBusy}
              testID="adp-map-save"
            >
              {mapBusy ? <ActivityIndicator color={colors.primaryFg} />
                : <Text style={s.saveText}>Save mapping ({picked.size})</Text>}
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.row}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={s.rowValue}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 8, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 17, fontWeight: "800", color: colors.textMain, flex: 1 },
  tabRow: { flexDirection: "row", gap: 8, padding: spacing.screen, paddingBottom: 12 },
  tabChip: {
    paddingHorizontal: 15, paddingVertical: 9, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    minHeight: 38, justifyContent: "center",
  },
  tabChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  tabTextOn: { color: colors.primaryFg },
  card: {
    marginHorizontal: spacing.screen, marginBottom: 12, padding: 14,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  dot: { width: 9, height: 9, borderRadius: 5 },
  name: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  meta: { fontSize: 11.5, color: colors.textMuted, fontWeight: "600", marginTop: 2 },
  hr: { height: 1, backgroundColor: colors.border, marginVertical: 10 },
  row: { flexDirection: "row", justifyContent: "space-between", gap: 12, paddingVertical: 4 },
  rowLabel: { fontSize: 12.5, color: colors.textMuted, fontWeight: "600" },
  rowValue: { flex: 1, fontSize: 12.5, color: colors.textMain, fontWeight: "700", textAlign: "right" },
  actions: { flexDirection: "row", gap: 9, marginTop: 13 },
  approveBtn: {
    flex: 1, backgroundColor: colors.primary, borderRadius: 999,
    paddingVertical: 12, alignItems: "center", justifyContent: "center", minHeight: 44,
  },
  approveText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13.5 },
  rejectBtn: {
    paddingHorizontal: 20, borderRadius: 999, borderWidth: 1, borderColor: "#B3261E",
    alignItems: "center", justifyContent: "center", minHeight: 44,
  },
  rejectText: { color: "#B3261E", fontWeight: "800", fontSize: 13.5 },
  mapBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: 12, borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingVertical: 11, minHeight: 44,
  },
  mapText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  empty: { textAlign: "center", color: colors.textMuted, fontWeight: "600", marginTop: 34, fontSize: 13.5 },
  mapHint: {
    fontSize: 12.5, color: colors.textMuted, fontWeight: "600",
    paddingHorizontal: spacing.screen, paddingTop: 12, lineHeight: 18,
  },
  search: {
    marginHorizontal: spacing.screen, marginVertical: 12,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 13, paddingVertical: 11,
    fontSize: 14, color: colors.textMain, minHeight: 46,
  },
  vendorRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginHorizontal: spacing.screen, marginBottom: 8, padding: 12,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, minHeight: 56,
  },
  vendorName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  mapFooter: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    padding: spacing.screen, paddingBottom: Platform.OS === "ios" ? 30 : spacing.screen,
    backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border,
  },
  saveBtn: {
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 14, alignItems: "center", justifyContent: "center", minHeight: 48,
  },
  saveText: { color: colors.primaryFg, fontWeight: "800", fontSize: 15 },
});
