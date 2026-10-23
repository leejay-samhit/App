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
  const [allPins, setAllPins] = useState<string[]>([]);
  const [pinFilter, setPinFilter] = useState<Set<string>>(new Set());
  // Jun 2026 — shops come in two flavours now: normal parcel shops (mapped as
  // before) and RECHARGE sellers, who are mapped operator-wise.
  const [mapKind, setMapKind] = useState<"normal" | "recharge">("normal");
  const [scopes, setScopes] = useState<Record<string, { kinds: string[]; networks: string[] }>>({});
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
    setAllPins([]);
    setPinFilter(new Set());
    try {
      const { data } = await api.get(`/admin/delivery-partners/${dp.id}/vendors`);
      const d = data as any;
      setVendors(d?.vendors || []);
      setPicked(new Set(d?.mapped_vendor_ids || []));
      setScopes(d?.mapped_scopes || {});
      setMapKind("normal");
      setAllPins(d?.all_pincodes || []);
      // Pre-select the PINs the rider said he covers so the admin instantly
      // sees the shops that actually match his area.
      const riderPins: string[] = (d?.dp_pincodes || []).filter((p: string) =>
        (d?.all_pincodes || []).includes(p));
      setPinFilter(new Set(riderPins));
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
        recharge_scopes: scopes,
      });
      setMapFor(null);
      await load();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setMapBusy(false); }
  };

  const shown = vendors.filter((v) => {
    if (!!v.is_recharge !== (mapKind === "recharge")) return false;
    const q = search.trim().toLowerCase();
    const pins: string[] = v.pincodes || [];
    const hitSearch = !q
      || String(v.shop || "").toLowerCase().includes(q)
      || String(v.email || "").toLowerCase().includes(q)
      || pins.some((p) => p.includes(q));
    const hitPin = pinFilter.size === 0 || pins.some((p) => pinFilter.has(p));
    return hitSearch && hitPin;
  });

  const togglePin = (p: string) => {
    const next = new Set(pinFilter);
    if (next.has(p)) next.delete(p); else next.add(p);
    setPinFilter(next);
  };
  const selectAllShown = () => {
    const next = new Set(picked);
    shown.forEach((v) => next.add(v.id));
    setPicked(next);
  };
  const clearShown = () => {
    const next = new Set(picked);
    shown.forEach((v) => next.delete(v.id));
    setPicked(next);
  };

  // Recharge scope helpers — an empty list means "every type this seller
  // sells", so the admin only has to tick what he wants to restrict to.
  const scopeOf = (vid: string) => scopes[vid] || { kinds: [], networks: [] };
  const toggleScope = (
    vid: string, field: "kinds" | "networks", value: string, vendor?: any,
  ) => {
    const cur = scopeOf(vid);
    const list = cur[field].includes(value)
      ? cur[field].filter((x) => x !== value)
      : [...cur[field], value];
    const next = { ...cur, [field]: list };
    // Un-ticking "DTH" must also drop the DTH operators that were ticked,
    // otherwise the saved scope would contradict itself.
    if (field === "kinds" && list.length > 0 && vendor) {
      const allowed = new Set(
        (vendor.recharge_networks || [])
          .filter((n: any) => list.includes(n.kind))
          .map((n: any) => n.slug),
      );
      next.networks = cur.networks.filter((n) => allowed.has(n));
    }
    setScopes({ ...scopes, [vid]: next });
  };
  const recCount = vendors.filter((v) => v.is_recharge).length;

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
          <View style={s.tabRow}>
            {(["normal", "recharge"] as const).map((k) => {
              const on = mapKind === k;
              return (
                <TouchableOpacity
                  key={k}
                  style={[s.tabChip, on && s.tabChipOn]}
                  onPress={() => setMapKind(k)}
                  testID={`adp-mapkind-${k}`}
                >
                  <Text style={[s.tabText, on && s.tabTextOn]}>
                    {k === "normal"
                      ? `Normal shops (${vendors.length - recCount})`
                      : `Recharge shops (${recCount})`}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
          <Text style={s.mapHint}>
            {mapKind === "recharge"
              ? `Pick the recharge sellers and the operators this rider handles. Tick nothing under a seller and he gets every recharge of that shop. ${picked.size} selected.`
              : `Pick the shops this rider delivers for. He only ever sees orders from these shops. ${picked.size} selected.`}
          </Text>
          <TextInput
            style={s.search}
            value={search}
            onChangeText={setSearch}
            placeholder="Search shop name, email or pincode"
            placeholderTextColor={colors.textMuted}
            testID="adp-map-search"
          />
          {allPins.length > 0 ? (
            <View>
              <Text style={s.filterLabel}>Filter by pincode</Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={s.pinRow}
              >
                <TouchableOpacity
                  style={[s.pinChip, pinFilter.size === 0 && s.pinChipOn]}
                  onPress={() => setPinFilter(new Set())}
                  testID="adp-pin-all"
                >
                  <Text style={[s.pinText, pinFilter.size === 0 && s.pinTextOn]}>All</Text>
                </TouchableOpacity>
                {allPins.map((p) => {
                  const on = pinFilter.has(p);
                  return (
                    <TouchableOpacity
                      key={p}
                      style={[s.pinChip, on && s.pinChipOn]}
                      onPress={() => togglePin(p)}
                      testID={`adp-pin-${p}`}
                    >
                      <Text style={[s.pinText, on && s.pinTextOn]}>{p}</Text>
                    </TouchableOpacity>
                  );
                })}
              </ScrollView>
            </View>
          ) : null}
          <View style={s.bulkRow}>
            <Text style={s.bulkCount}>{`${shown.length} shop${shown.length === 1 ? "" : "s"} shown`}</Text>
            <TouchableOpacity onPress={selectAllShown} style={s.bulkBtn} testID="adp-select-all">
              <Feather name="check-square" size={13} color={colors.primary} />
              <Text style={s.bulkText}>Select all</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={clearShown} style={s.bulkBtn} testID="adp-clear-all">
              <Feather name="square" size={13} color={colors.textMuted} />
              <Text style={[s.bulkText, { color: colors.textMuted }]}>Clear</Text>
            </TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ paddingBottom: 90 }}>
            {shown.map((v) => {
              const on = picked.has(v.id);
              const sc = scopeOf(v.id);
              return (
                <View key={v.id}>
                <TouchableOpacity
                  style={[s.vendorRow, on && s.vendorRowOn]}
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
                    <Text style={s.meta} numberOfLines={1}>
                      {(v.pincodes || []).length
                        ? `PIN ${(v.pincodes || []).join(", ")}`
                        : v.email}
                    </Text>
                  </View>
                </TouchableOpacity>
                {on && v.is_recharge ? (
                  <View style={s.scopeBox} testID={`adp-scope-${v.id}`}>
                    <Text style={s.filterLabel}>Recharge type</Text>
                    <View style={s.scopeChips}>
                      {(v.recharge_kinds || []).map((k: string) => {
                        const kOn = sc.kinds.includes(k);
                        return (
                          <TouchableOpacity
                            key={k}
                            style={[s.pinChip, kOn && s.pinChipOn]}
                            onPress={() => toggleScope(v.id, "kinds", k, v)}
                            testID={`adp-kind-${v.id}-${k}`}
                          >
                            <Text style={[s.pinText, kOn && s.pinTextOn]}>
                              {k === "mobile" ? "Mobile recharge" : "DTH recharge"}
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                    <Text style={s.filterLabel}>Operators</Text>
                    <View style={s.scopeChips}>
                      {(v.recharge_networks || [])
                        .filter((n: any) => sc.kinds.length === 0 || sc.kinds.includes(n.kind))
                        .map((n: any) => {
                        const nOn = sc.networks.includes(n.slug);
                        return (
                          <TouchableOpacity
                            key={n.slug}
                            style={[s.pinChip, nOn && s.pinChipOn]}
                            onPress={() => toggleScope(v.id, "networks", n.slug)}
                            testID={`adp-net-${v.id}-${n.slug}`}
                          >
                            <Text style={[s.pinText, nOn && s.pinTextOn]}>{n.name}</Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                    <Text style={s.meta}>
                      {sc.kinds.length === 0 && sc.networks.length === 0
                        ? "Gets every recharge order of this shop."
                        : `Gets only ${sc.kinds.length ? sc.kinds.map((k) => k === "mobile" ? "Mobile" : "DTH").join(" + ") : "any type"}`
                          + (sc.networks.length ? ` · ${sc.networks.length} operator${sc.networks.length === 1 ? "" : "s"}` : "")}
                    </Text>
                  </View>
                ) : null}
                </View>
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
  vendorRowOn: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  filterLabel: {
    fontSize: 11.5, fontWeight: "700", color: colors.textMuted,
    paddingHorizontal: spacing.screen, marginBottom: 6, letterSpacing: 0.3,
  },
  pinRow: { paddingHorizontal: spacing.screen, gap: 8, paddingBottom: 4 },
  scopeChips: {
    flexDirection: "row", flexWrap: "wrap", gap: 8,
    paddingHorizontal: spacing.screen, paddingBottom: 8,
  },
  scopeBox: {
    marginHorizontal: spacing.screen, marginTop: -4, marginBottom: 10,
    paddingVertical: 10, backgroundColor: colors.surfaceMuted,
    borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
  },
  pinChip: {
    paddingHorizontal: 13, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    minHeight: 34, justifyContent: "center",
  },
  pinChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  pinText: { fontSize: 12.5, fontWeight: "700", color: colors.textMain },
  pinTextOn: { color: colors.primaryFg },
  bulkRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.screen, paddingVertical: 10,
  },
  bulkCount: { flex: 1, fontSize: 12, fontWeight: "700", color: colors.textMuted },
  bulkBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, minHeight: 34,
  },
  bulkText: { fontSize: 12, fontWeight: "700", color: colors.primary },
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
