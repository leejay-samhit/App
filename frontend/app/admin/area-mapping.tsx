/**
 * Admin · Distributor Network — Area Mapping
 *
 * Two-pane workflow:
 *  1. List of distributors with their assigned-pincode counts
 *  2. Tap a distributor → bottom sheet to view / add / remove pincode
 *     mappings (autocomplete-search by pincode prefix or district name).
 *
 * Exclusive territory: each pincode can only be mapped to ONE distributor.
 * The backend silently reassigns when admin assigns a pincode that's
 * already held by someone else; we surface that count in a confirmation.
 */
import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Modal,
  Alert,
  Platform,
  KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type Distributor = {
  id: string;
  name: string;
  email: string;
  phone?: string;
  referral_code: string;
  pincode_count: number;
};

type PincodeRow = {
  pincode: string;
  district?: string;
  state?: string;
  office?: string;
  region?: string;
  assigned_to?: { distributor_id: string; distributor_name?: string; distributor_email?: string } | null;
};

type AssignedRow = PincodeRow & { distributor_id: string };

export default function AdminAreaMapping() {
  const router = useRouter();
  const [items, setItems] = useState<Distributor[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [drillTo, setDrillTo] = useState<Distributor | null>(null);
  const [promoteOpen, setPromoteOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: Distributor[] }>("/admin/distributors");
      setItems(r.data.items || []);
    } catch (e) { console.warn(e); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
            <Feather name="chevron-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN · DISTRIBUTOR NETWORK</Text>
            <Text style={styles.title}>Area Mapping</Text>
          </View>
        </View>

        <Text style={styles.helper}>
          Map distributors to pincodes for area-wise coverage. Each pincode is
          exclusive — assigning it to one distributor removes it from any
          previous holder. Pre-loaded with all India pincodes.
        </Text>

        <TouchableOpacity onPress={() => setPromoteOpen(true)} style={styles.newBtn}>
          <Feather name="user-plus" size={16} color={colors.primaryFg} />
          <Text style={styles.newBtnText}>  Promote a user to Distributor</Text>
        </TouchableOpacity>

        <Text style={styles.sectionLabel}>{items.length} DISTRIBUTOR{items.length === 1 ? "" : "S"}</Text>
        {items.length === 0 ? (
          <View style={styles.empty}>
            <Feather name="users" size={28} color={colors.textMuted} />
            <Text style={styles.emptyText}>No distributors yet — promote a user above to get started.</Text>
          </View>
        ) : (
          <View style={styles.list}>
            {items.map((d) => (
              <TouchableOpacity key={d.id} style={styles.row} onPress={() => setDrillTo(d)}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{(d.name || "?")[0].toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>{d.name}</Text>
                  <Text style={styles.rowMeta}>{d.email} · {d.referral_code}</Text>
                </View>
                <View style={styles.countPill}>
                  <Feather name="map-pin" size={11} color={colors.primary} />
                  <Text style={styles.countText}>  {d.pincode_count}</Text>
                </View>
                <Feather name="chevron-right" size={18} color={colors.textMuted} />
              </TouchableOpacity>
            ))}
          </View>
        )}
      </ScrollView>

      <PromoteSheet
        visible={promoteOpen}
        onClose={() => setPromoteOpen(false)}
        onDone={() => { setPromoteOpen(false); load(); }}
      />

      <AreaEditor
        distributor={drillTo}
        onClose={() => setDrillTo(null)}
        onChanged={load}
      />
    </SafeAreaView>
  );
}

// ============================================================================
// Promote user → distributor sheet
// ============================================================================
function PromoteSheet({ visible, onClose, onDone }: { visible: boolean; onClose: () => void; onDone: () => void }) {
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const search = useCallback(async () => {
    if (!q.trim()) { setUsers([]); return; }
    setBusy(true);
    try {
      const r = await api.get<any[]>("/admin/users");
      const ql = q.toLowerCase();
      const matches = (r.data || []).filter(
        (u: any) =>
          !u.is_distributor && u.role !== "admin" &&
          ((u.name || "").toLowerCase().includes(ql) ||
           (u.email || "").toLowerCase().includes(ql) ||
           (u.referral_code || "").toLowerCase().includes(ql) ||
           (u.phone || "").includes(ql)),
      );
      setUsers(matches.slice(0, 30));
    } catch (e) { console.warn(e); }
    finally { setBusy(false); }
  }, [q]);

  const promote = async (u: any) => {
    try {
      await api.post(`/admin/users/${u.id}/distributor`, { is_distributor: true });
      Alert.alert("Promoted", `${u.name} is now a distributor.`);
      onDone();
    } catch (e) { Alert.alert("Could not promote", formatApiError(e)); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <TouchableOpacity activeOpacity={1} onPress={onClose} style={styles.modalBackdrop}>
          <TouchableOpacity activeOpacity={1} onPress={() => {}} style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Promote user to Distributor</Text>
            <View style={styles.searchRow}>
              <Feather name="search" size={16} color={colors.textMuted} />
              <TextInput
                style={styles.searchInput}
                value={q}
                onChangeText={setQ}
                onSubmitEditing={search}
                placeholder="Search name / email / referral / phone"
                placeholderTextColor={colors.textMuted}
                returnKeyType="search"
              />
              <TouchableOpacity onPress={search} disabled={busy} style={styles.searchBtn}>
                {busy ? <ActivityIndicator color={colors.primaryFg} size="small" /> : <Text style={styles.searchBtnText}>Search</Text>}
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 460 }}>
              {users.length === 0 ? (
                <Text style={styles.emptyMini}>Type and search for users to promote.</Text>
              ) : users.map((u) => (
                <TouchableOpacity key={u.id} style={styles.userRow} onPress={() => promote(u)}>
                  <View style={styles.avatarSm}><Text style={styles.avatarSmText}>{(u.name || "?")[0].toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName}>{u.name}</Text>
                    <Text style={styles.rowMeta}>{u.email} · {u.referral_code}</Text>
                  </View>
                  <Feather name="user-plus" size={16} color={colors.primary} />
                </TouchableOpacity>
              ))}
            </ScrollView>
          </TouchableOpacity>
        </TouchableOpacity>
      </KeyboardAvoidingView>
    </Modal>
  );
}

// ============================================================================
// Area editor — drill into one distributor
// ============================================================================
function AreaEditor({
  distributor,
  onClose,
  onChanged,
}: {
  distributor: Distributor | null;
  onClose: () => void;
  onChanged: () => void;
}) {
  const visible = !!distributor;
  const [areas, setAreas] = useState<AssignedRow[]>([]);
  const [loadingAreas, setLoadingAreas] = useState(false);
  const [pinSearch, setPinSearch] = useState("");
  const [pinResults, setPinResults] = useState<PincodeRow[]>([]);
  const [stagedPins, setStagedPins] = useState<string[]>([]);
  const [savingAdd, setSavingAdd] = useState(false);

  const loadAreas = useCallback(async () => {
    if (!distributor) return;
    setLoadingAreas(true);
    try {
      const r = await api.get<{ items: AssignedRow[] }>(`/admin/distributors/${distributor.id}/areas`);
      setAreas(r.data.items || []);
    } finally { setLoadingAreas(false); }
  }, [distributor]);

  const searchPincodes = useCallback(async (text: string) => {
    setPinSearch(text);
    if (!text.trim() || text.trim().length < 2) { setPinResults([]); return; }
    try {
      const r = await api.get<{ items: PincodeRow[] }>("/admin/pincodes/search", { params: { q: text.trim(), limit: 30 } });
      setPinResults(r.data.items || []);
    } catch { setPinResults([]); }
  }, []);

  // Reset on open
  const onShow = () => {
    setStagedPins([]);
    setPinSearch("");
    setPinResults([]);
    loadAreas();
  };

  const togglePin = (p: string) => {
    setStagedPins((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]);
  };

  const submitAdd = async () => {
    if (!distributor || stagedPins.length === 0) return;
    setSavingAdd(true);
    try {
      const r = await api.post(`/admin/distributors/${distributor.id}/areas`, { pincodes: stagedPins });
      const reassigned = r.data?.reassigned || 0;
      Alert.alert(
        "Saved",
        `Added ${r.data?.new_assignments} new pincode(s)${reassigned ? `, reassigned ${reassigned} from other distributor(s)` : ""}.`,
      );
      setStagedPins([]);
      setPinResults([]);
      setPinSearch("");
      await loadAreas();
      onChanged();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setSavingAdd(false); }
  };

  const remove = async (pin: string) => {
    if (!distributor) return;
    Alert.alert("Unassign pincode", `Remove ${pin} from ${distributor.name}'s territory?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Remove", style: "destructive",
        onPress: async () => {
          try {
            await api.delete(`/admin/distributors/${distributor.id}/areas/${pin}`);
            await loadAreas();
            onChanged();
          } catch (e) { Alert.alert("Could not remove", formatApiError(e)); }
        },
      },
    ]);
  };

  const demote = async () => {
    if (!distributor) return;
    Alert.alert(
      "Remove distributor status?",
      `${distributor.name} will lose all ${areas.length} pincode mapping(s) and stop being a distributor. This cannot be undone except by re-promoting.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Demote", style: "destructive",
          onPress: async () => {
            try {
              await api.post(`/admin/users/${distributor.id}/distributor`, { is_distributor: false });
              onChanged();
              onClose();
            } catch (e) { Alert.alert("Could not demote", formatApiError(e)); }
          },
        },
      ],
    );
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} onShow={onShow}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <TouchableOpacity activeOpacity={1} onPress={onClose} style={styles.modalBackdrop}>
          <TouchableOpacity activeOpacity={1} onPress={() => {}} style={[styles.modalSheet, { maxHeight: "92%" }]}>
            <View style={styles.modalHandle} />
            {distributor ? (
              <>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <View style={styles.avatar}><Text style={styles.avatarText}>{(distributor.name || "?")[0].toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.modalTitle}>{distributor.name}</Text>
                    <Text style={styles.rowMeta}>{distributor.email} · {areas.length} pincode{areas.length === 1 ? "" : "s"}</Text>
                  </View>
                  <TouchableOpacity onPress={demote} style={styles.demoteBtn}>
                    <Feather name="user-x" size={14} color={colors.error} />
                  </TouchableOpacity>
                </View>

                <ScrollView style={{ marginTop: 14 }} keyboardShouldPersistTaps="handled">
                  {/* Add area pane */}
                  <Text style={styles.sectionLabel}>ADD PINCODES</Text>
                  <View style={styles.searchRow}>
                    <Feather name="search" size={16} color={colors.textMuted} />
                    <TextInput
                      style={styles.searchInput}
                      value={pinSearch}
                      onChangeText={searchPincodes}
                      placeholder="6-digit pincode or district / state name"
                      placeholderTextColor={colors.textMuted}
                      autoCapitalize="words"
                    />
                  </View>
                  {pinResults.length > 0 ? (
                    <View style={{ marginTop: 8 }}>
                      {pinResults.map((p) => {
                        const sel = stagedPins.includes(p.pincode);
                        const taken = p.assigned_to && p.assigned_to.distributor_id !== distributor.id;
                        return (
                          <TouchableOpacity
                            key={p.pincode}
                            style={[styles.pinResult, sel && styles.pinResultSel]}
                            onPress={() => togglePin(p.pincode)}
                          >
                            <Feather name={sel ? "check-circle" : "circle"} size={16} color={sel ? colors.primary : colors.textMuted} />
                            <View style={{ flex: 1 }}>
                              <Text style={styles.pinTitle}>{p.pincode} · {p.district}, {p.state}</Text>
                              <Text style={styles.pinSub}>{p.office}{taken ? ` · currently with ${p.assigned_to?.distributor_name}` : ""}</Text>
                            </View>
                            {taken ? (
                              <View style={styles.warnPill}>
                                <Text style={styles.warnPillText}>WILL REASSIGN</Text>
                              </View>
                            ) : null}
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  ) : pinSearch.trim().length >= 2 ? (
                    <Text style={styles.emptyMini}>No matches.</Text>
                  ) : null}

                  {stagedPins.length > 0 ? (
                    <TouchableOpacity onPress={submitAdd} disabled={savingAdd} style={[styles.assignBtn, savingAdd && { opacity: 0.6 }]}>
                      {savingAdd ? (
                        <ActivityIndicator color={colors.primaryFg} size="small" />
                      ) : (
                        <Text style={styles.assignBtnText}>Assign {stagedPins.length} pincode{stagedPins.length === 1 ? "" : "s"} to {distributor.name}</Text>
                      )}
                    </TouchableOpacity>
                  ) : null}

                  {/* Existing areas */}
                  <Text style={[styles.sectionLabel, { marginTop: 24 }]}>CURRENT TERRITORIES</Text>
                  {loadingAreas ? (
                    <ActivityIndicator color={colors.primary} style={{ marginTop: 14 }} />
                  ) : areas.length === 0 ? (
                    <Text style={styles.emptyMini}>No pincodes assigned yet.</Text>
                  ) : (
                    areas.map((a) => (
                      <View key={a.pincode} style={styles.areaRow}>
                        <View style={styles.areaPin}><Text style={styles.areaPinText}>{a.pincode}</Text></View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.pinTitle}>{a.district || "—"}, {a.state || "—"}</Text>
                          <Text style={styles.pinSub} numberOfLines={1}>{a.office || ""}</Text>
                        </View>
                        <TouchableOpacity onPress={() => remove(a.pincode)} style={styles.removeBtn}>
                          <Feather name="x" size={14} color={colors.error} />
                        </TouchableOpacity>
                      </View>
                    ))
                  )}
                  <View style={{ height: 30 }} />
                </ScrollView>
              </>
            ) : null}
          </TouchableOpacity>
        </TouchableOpacity>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.lg, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 6 },
  backBtn: { padding: 6 },
  overline: { fontSize: 11, fontWeight: "700", letterSpacing: 1, color: colors.textMuted },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  helper: { color: colors.textMuted, fontSize: 12, marginTop: 6, marginBottom: 16, lineHeight: 17 },
  newBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 13, marginBottom: 16,
  },
  newBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  sectionLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginBottom: 8 },
  empty: { alignItems: "center", padding: 40, gap: 8 },
  emptyText: { color: colors.textMuted, fontSize: 13, textAlign: "center" },
  emptyMini: { color: colors.textMuted, fontSize: 12, marginTop: 8 },
  list: { backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 12, paddingHorizontal: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  avatar: {
    width: 38, height: 38, borderRadius: 19,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.primary,
  },
  avatarText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  avatarSm: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.primary,
  },
  avatarSmText: { color: colors.primaryFg, fontWeight: "800", fontSize: 12 },
  rowName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rowMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  countPill: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.primary + "15",
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
  },
  countText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: colors.bg, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 18, maxHeight: "88%",
  },
  modalHandle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, alignSelf: "center", marginBottom: 14,
  },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: 10, paddingHorizontal: 10,
    height: 44, marginTop: 12,
  },
  searchInput: { flex: 1, color: colors.textMain, fontSize: 14 },
  searchBtn: { backgroundColor: colors.primary, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 8 },
  searchBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 12 },
  userRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  pinResult: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 10,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, marginBottom: 6,
  },
  pinResultSel: { backgroundColor: colors.primary + "10", borderColor: colors.primary },
  pinTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  pinSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  warnPill: { backgroundColor: "#FEF3C7", paddingHorizontal: 6, paddingVertical: 3, borderRadius: 4 },
  warnPillText: { color: "#92400E", fontSize: 9, fontWeight: "800", letterSpacing: 0.4 },
  assignBtn: {
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 13, alignItems: "center", marginTop: 12,
  },
  assignBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  areaRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 10,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, marginBottom: 6,
  },
  areaPin: {
    backgroundColor: colors.primary + "15",
    paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6,
  },
  areaPinText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  removeBtn: { padding: 6 },
  demoteBtn: { padding: 6, backgroundColor: colors.error + "15", borderRadius: 8 },
});
