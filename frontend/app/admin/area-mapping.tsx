/**
 * Admin · Distributor Network — Area Mapping (v2)
 *
 * Improvements over v1:
 *  • Polished UI: stats strip, search filter, glanceable cards
 *  • Bulk-paste pincodes (multi-line textarea, comma/space/newline delimited)
 *  • One-click "Assign whole State / District" via region search
 *  • Multi-select bulk delete in current territories
 *  • Web-safe custom confirm modals (replaces Alert.alert which doesn't render
 *    on the web preview, root-cause of the "delete not working" report)
 */
import { useCallback, useMemo, useState } from "react";
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
  Platform,
  KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

// ============================================================================
// Types
// ============================================================================
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

type Stats = {
  distributors: number;
  mapped: number;
  master: number;
};

// ============================================================================
// Lightweight web-safe Confirm modal (replaces Alert.alert)
// ============================================================================
type ConfirmState = {
  visible: boolean;
  title: string;
  message?: string;
  confirmText?: string;
  destructive?: boolean;
  onConfirm?: () => void | Promise<void>;
};

function useConfirm() {
  const [state, setState] = useState<ConfirmState>({ visible: false, title: "" });
  const ask = (s: Omit<ConfirmState, "visible">) => setState({ ...s, visible: true });
  const close = () => setState((p) => ({ ...p, visible: false }));
  return { state, ask, close };
}

function ConfirmModal({ state, onClose }: { state: ConfirmState; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const handleConfirm = async () => {
    try {
      setBusy(true);
      await state.onConfirm?.();
      onClose();
    } finally { setBusy(false); }
  };
  return (
    <Modal visible={state.visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.confirmBackdrop}>
        <View style={styles.confirmBox}>
          <Text style={styles.confirmTitle}>{state.title}</Text>
          {state.message ? <Text style={styles.confirmMsg}>{state.message}</Text> : null}
          <View style={styles.confirmRow}>
            <TouchableOpacity onPress={onClose} style={[styles.confirmBtn, styles.confirmBtnGhost]} disabled={busy}>
              <Text style={styles.confirmBtnGhostText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={handleConfirm}
              disabled={busy}
              style={[styles.confirmBtn, state.destructive ? styles.confirmBtnDanger : styles.confirmBtnPrimary, busy && { opacity: 0.6 }]}
            >
              {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                <Text style={styles.confirmBtnText}>{state.confirmText || "Confirm"}</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// Toast (web + native) – tiny inline banner inside modals
function useBanner() {
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const show = (kind: "ok" | "err", text: string) => {
    setMsg({ kind, text });
    setTimeout(() => setMsg(null), 3500);
  };
  return { msg, show };
}

// ============================================================================
// Main Screen
// ============================================================================
export default function AdminAreaMapping() {
  const router = useRouter();
  const [items, setItems] = useState<Distributor[]>([]);
  const [stats, setStats] = useState<Stats>({ distributors: 0, mapped: 0, master: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [drillTo, setDrillTo] = useState<Distributor | null>(null);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [filterQ, setFilterQ] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: Distributor[] }>("/admin/distributors");
      const list = r.data.items || [];
      setItems(list);
      const mapped = list.reduce((s, d) => s + (d.pincode_count || 0), 0);
      // master count -- best effort, ignore failure
      let master = 0;
      try {
        const m = await api.get<{ items: any[]; total: number }>("/admin/pincodes/search", { params: { q: "1", limit: 1 } });
        master = m.data.total ?? 0;
      } catch { /* ignored */ }
      // We track mapped + distributors counts; master may not reflect grand total when search filters.
      setStats({ distributors: list.length, mapped, master: master || mapped });
    } catch (e) { console.warn(e); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const filtered = useMemo(() => {
    const q = filterQ.trim().toLowerCase();
    if (!q) return items;
    return items.filter((d) =>
      (d.name || "").toLowerCase().includes(q) ||
      (d.email || "").toLowerCase().includes(q) ||
      (d.referral_code || "").toLowerCase().includes(q) ||
      (d.phone || "").includes(q),
    );
  }, [items, filterQ]);

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
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
            <Feather name="chevron-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN · DISTRIBUTOR NETWORK</Text>
            <Text style={styles.title}>Area Mapping</Text>
          </View>
        </View>

        {/* Stats strip */}
        <View style={styles.statsRow}>
          <View style={[styles.statCard, { backgroundColor: colors.primary + "15" }]}>
            <Feather name="users" size={16} color={colors.primary} />
            <Text style={styles.statValue}>{stats.distributors}</Text>
            <Text style={styles.statLabel}>Distributors</Text>
          </View>
          <View style={[styles.statCard, { backgroundColor: "#FBBF2415" }]}>
            <Feather name="map-pin" size={16} color="#B45309" />
            <Text style={styles.statValue}>{stats.mapped.toLocaleString()}</Text>
            <Text style={styles.statLabel}>Mapped</Text>
          </View>
          <View style={[styles.statCard, { backgroundColor: "#10B98115" }]}>
            <Feather name="map" size={16} color="#047857" />
            <Text style={styles.statValue}>{(stats.master || stats.mapped).toLocaleString()}</Text>
            <Text style={styles.statLabel}>India Total</Text>
          </View>
        </View>

        {/* Promote CTA */}
        <TouchableOpacity onPress={() => setPromoteOpen(true)} style={styles.newBtn}>
          <Feather name="user-plus" size={16} color={colors.primaryFg} />
          <Text style={styles.newBtnText}>  Promote a user to Distributor</Text>
        </TouchableOpacity>

        {/* Filter */}
        {items.length > 0 ? (
          <View style={styles.searchRow}>
            <Feather name="search" size={16} color={colors.textMuted} />
            <TextInput
              style={styles.searchInput}
              value={filterQ}
              onChangeText={setFilterQ}
              placeholder="Filter distributors by name / email / code"
              placeholderTextColor={colors.textMuted}
            />
            {filterQ.length > 0 ? (
              <TouchableOpacity onPress={() => setFilterQ("")} style={{ padding: 4 }}>
                <Feather name="x" size={14} color={colors.textMuted} />
              </TouchableOpacity>
            ) : null}
          </View>
        ) : null}

        <Text style={styles.sectionLabel}>
          {filtered.length} OF {items.length} DISTRIBUTOR{items.length === 1 ? "" : "S"}
        </Text>
        {items.length === 0 ? (
          <View style={styles.empty}>
            <Feather name="users" size={28} color={colors.textMuted} />
            <Text style={styles.emptyText}>No distributors yet — promote a user above to get started.</Text>
          </View>
        ) : (
          <View style={styles.list}>
            {filtered.map((d) => (
              <TouchableOpacity key={d.id} style={styles.row} onPress={() => setDrillTo(d)}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{(d.name || "?")[0].toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>{d.name}</Text>
                  <Text style={styles.rowMeta} numberOfLines={1}>{d.email} · {d.referral_code}</Text>
                </View>
                <View style={styles.countPill}>
                  <Feather name="map-pin" size={11} color={colors.primary} />
                  <Text style={styles.countText}>  {d.pincode_count}</Text>
                </View>
                <Feather name="chevron-right" size={18} color={colors.textMuted} />
              </TouchableOpacity>
            ))}
            {filtered.length === 0 ? (
              <Text style={styles.emptyMini}>No distributors match your filter.</Text>
            ) : null}
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
// Promote-user sheet
// ============================================================================
function PromoteSheet({ visible, onClose, onDone }: { visible: boolean; onClose: () => void; onDone: () => void }) {
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const banner = useBanner();

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
      banner.show("ok", `${u.name} promoted to distributor.`);
      setTimeout(onDone, 600);
    } catch (e) { banner.show("err", formatApiError(e)); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <TouchableOpacity activeOpacity={1} onPress={onClose} style={styles.modalBackdrop}>
          <TouchableOpacity activeOpacity={1} onPress={() => {}} style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Promote user to Distributor</Text>
            {banner.msg ? (
              <View style={[styles.banner, banner.msg.kind === "ok" ? styles.bannerOk : styles.bannerErr]}>
                <Text style={[styles.bannerText, banner.msg.kind === "ok" ? { color: "#065F46" } : { color: "#7F1D1D" }]}>
                  {banner.msg.text}
                </Text>
              </View>
            ) : null}
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
// Area Editor — drill into one distributor
// ============================================================================
type Tab = "search" | "paste" | "region";

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
  const [tab, setTab] = useState<Tab>("search");
  const [areas, setAreas] = useState<AssignedRow[]>([]);
  const [loadingAreas, setLoadingAreas] = useState(false);

  // Search-tab state
  const [pinSearch, setPinSearch] = useState("");
  const [pinResults, setPinResults] = useState<PincodeRow[]>([]);

  // Paste-tab state
  const [pasteText, setPasteText] = useState("");

  // Region-tab state
  const [regionState, setRegionState] = useState("");
  const [regionDistrict, setRegionDistrict] = useState("");
  const [regionResults, setRegionResults] = useState<PincodeRow[]>([]);
  const [regionBusy, setRegionBusy] = useState(false);

  // Shared selection / save state
  const [stagedPins, setStagedPins] = useState<string[]>([]);
  const [savingAdd, setSavingAdd] = useState(false);

  // Bulk-remove state on territories
  const [removeMode, setRemoveMode] = useState(false);
  const [selectedRemove, setSelectedRemove] = useState<string[]>([]);
  const [removingBulk, setRemovingBulk] = useState(false);

  const confirm = useConfirm();
  const banner = useBanner();

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
    setTab("search");
    setStagedPins([]);
    setPinSearch("");
    setPinResults([]);
    setPasteText("");
    setRegionState("");
    setRegionDistrict("");
    setRegionResults([]);
    setRemoveMode(false);
    setSelectedRemove([]);
    loadAreas();
  };

  const togglePin = (p: string) =>
    setStagedPins((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  // Parse pasted text into valid 6-digit pincodes
  const pastedPins = useMemo(() => {
    const pins = pasteText
      .split(/[\s,;\n\r\t]+/)
      .map((s) => s.trim())
      .filter((s) => /^\d{6}$/.test(s));
    return Array.from(new Set(pins));
  }, [pasteText]);

  const stagePastedAll = () => setStagedPins(pastedPins);

  const fetchRegion = async () => {
    if (!regionState.trim() && !regionDistrict.trim()) {
      banner.show("err", "Enter a state or district.");
      return;
    }
    setRegionBusy(true);
    try {
      const params: any = { limit: 5000 };
      if (regionState.trim()) params.state = regionState.trim();
      if (regionDistrict.trim()) params.district = regionDistrict.trim();
      const r = await api.get<{ items: PincodeRow[] }>("/admin/pincodes/in-region", { params });
      setRegionResults(r.data.items || []);
      if ((r.data.items || []).length === 0) banner.show("err", "No pincodes found in that region.");
    } catch (e) { banner.show("err", formatApiError(e)); }
    finally { setRegionBusy(false); }
  };

  const stageRegionAll = () => setStagedPins(regionResults.map((r) => r.pincode));

  const submitAdd = async () => {
    if (!distributor || stagedPins.length === 0) return;
    setSavingAdd(true);
    try {
      const r = await api.post(`/admin/distributors/${distributor.id}/areas`, { pincodes: stagedPins });
      const reassigned = r.data?.reassigned || 0;
      const newAssign = r.data?.new_assignments || 0;
      banner.show("ok", `Added ${newAssign} new pincode(s)${reassigned ? `, reassigned ${reassigned}` : ""}.`);
      setStagedPins([]);
      setPinResults([]);
      setPinSearch("");
      setPasteText("");
      setRegionResults([]);
      await loadAreas();
      onChanged();
    } catch (e) {
      banner.show("err", formatApiError(e));
    } finally { setSavingAdd(false); }
  };

  // Single remove (web-safe)
  const removeOne = (pin: string) => {
    if (!distributor) return;
    confirm.ask({
      title: "Unassign pincode?",
      message: `Remove ${pin} from ${distributor.name}'s territory.`,
      confirmText: "Remove",
      destructive: true,
      onConfirm: async () => {
        try {
          await api.delete(`/admin/distributors/${distributor.id}/areas/${pin}`);
          banner.show("ok", `Removed ${pin}.`);
          await loadAreas();
          onChanged();
        } catch (e) { banner.show("err", formatApiError(e)); }
      },
    });
  };

  // Bulk remove
  const removeBulk = () => {
    if (!distributor || selectedRemove.length === 0) return;
    confirm.ask({
      title: `Remove ${selectedRemove.length} pincode(s)?`,
      message: `These will be unassigned from ${distributor.name}.`,
      confirmText: "Remove",
      destructive: true,
      onConfirm: async () => {
        setRemovingBulk(true);
        try {
          const r = await api.post(`/admin/distributors/${distributor.id}/areas/bulk-unassign`, { pincodes: selectedRemove });
          banner.show("ok", `Removed ${r.data.removed} pincode(s).`);
          setSelectedRemove([]);
          setRemoveMode(false);
          await loadAreas();
          onChanged();
        } catch (e) { banner.show("err", formatApiError(e)); }
        finally { setRemovingBulk(false); }
      },
    });
  };

  const demote = () => {
    if (!distributor) return;
    confirm.ask({
      title: "Remove distributor status?",
      message: `${distributor.name} will lose all ${areas.length} pincode mapping(s) and stop being a distributor.`,
      confirmText: "Demote",
      destructive: true,
      onConfirm: async () => {
        try {
          await api.post(`/admin/users/${distributor.id}/distributor`, { is_distributor: false });
          onChanged();
          onClose();
        } catch (e) { banner.show("err", formatApiError(e)); }
      },
    });
  };

  // Group territories by state for nicer display
  const groupedAreas = useMemo(() => {
    const map = new Map<string, AssignedRow[]>();
    for (const a of areas) {
      const k = a.state || "—";
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(a);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [areas]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} onShow={onShow}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <TouchableOpacity activeOpacity={1} onPress={onClose} style={styles.modalBackdrop}>
          <TouchableOpacity activeOpacity={1} onPress={() => {}} style={[styles.modalSheet, { maxHeight: "94%" }]}>
            <View style={styles.modalHandle} />
            {distributor ? (
              <>
                {/* Header */}
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

                {/* Inline banner */}
                {banner.msg ? (
                  <View style={[styles.banner, banner.msg.kind === "ok" ? styles.bannerOk : styles.bannerErr]}>
                    <Text style={[styles.bannerText, banner.msg.kind === "ok" ? { color: "#065F46" } : { color: "#7F1D1D" }]}>
                      {banner.msg.text}
                    </Text>
                  </View>
                ) : null}

                {/* Tabs */}
                <View style={styles.tabRow}>
                  {(["search", "paste", "region"] as Tab[]).map((t) => (
                    <TouchableOpacity
                      key={t}
                      onPress={() => { setTab(t); setStagedPins([]); }}
                      style={[styles.tab, tab === t && styles.tabActive]}
                    >
                      <Text style={[styles.tabText, tab === t && styles.tabTextActive]}>
                        {t === "search" ? "Search" : t === "paste" ? "Bulk Paste" : "By Region"}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>

                <ScrollView style={{ marginTop: 6 }} keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 12 }}>
                  {/* SEARCH TAB */}
                  {tab === "search" ? (
                    <>
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
                                  <Text style={styles.pinSub} numberOfLines={1}>{p.office || ""}{taken ? ` · currently with ${p.assigned_to?.distributor_name}` : ""}</Text>
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
                      ) : (
                        <Text style={styles.emptyMini}>Type 2+ characters to search.</Text>
                      )}
                    </>
                  ) : null}

                  {/* PASTE TAB */}
                  {tab === "paste" ? (
                    <>
                      <Text style={styles.helperLine}>Paste pincodes (comma, space, or newline separated). Only valid 6-digit codes will be staged.</Text>
                      <TextInput
                        style={styles.textarea}
                        value={pasteText}
                        onChangeText={setPasteText}
                        placeholder="e.g.&#10;110001, 110002&#10;110003 110004&#10;560001"
                        placeholderTextColor={colors.textMuted}
                        multiline
                        numberOfLines={6}
                      />
                      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 6 }}>
                        <Text style={styles.helperLine}>{pastedPins.length} valid · {stagedPins.length} staged</Text>
                        <TouchableOpacity
                          onPress={stagePastedAll}
                          disabled={pastedPins.length === 0}
                          style={[styles.smallBtn, pastedPins.length === 0 && { opacity: 0.5 }]}
                        >
                          <Text style={styles.smallBtnText}>Stage all valid</Text>
                        </TouchableOpacity>
                      </View>
                    </>
                  ) : null}

                  {/* REGION TAB */}
                  {tab === "region" ? (
                    <>
                      <Text style={styles.helperLine}>Enter a state and/or district to fetch all matching pincodes at once.</Text>
                      <View style={{ flexDirection: "row", gap: 8 }}>
                        <TextInput
                          style={[styles.searchRow, styles.regionInput]}
                          value={regionState}
                          onChangeText={setRegionState}
                          placeholder="State (e.g. Karnataka)"
                          placeholderTextColor={colors.textMuted}
                        />
                        <TextInput
                          style={[styles.searchRow, styles.regionInput]}
                          value={regionDistrict}
                          onChangeText={setRegionDistrict}
                          placeholder="District (optional)"
                          placeholderTextColor={colors.textMuted}
                        />
                      </View>
                      <TouchableOpacity onPress={fetchRegion} disabled={regionBusy} style={styles.smallBtnPrimary}>
                        {regionBusy ? <ActivityIndicator color="#fff" size="small" /> : (
                          <Text style={styles.smallBtnPrimaryText}>Fetch pincodes</Text>
                        )}
                      </TouchableOpacity>
                      {regionResults.length > 0 ? (
                        <View style={{ marginTop: 10 }}>
                          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <Text style={styles.helperLine}>{regionResults.length} found · {regionResults.filter((r) => r.assigned_to && r.assigned_to.distributor_id !== distributor.id).length} held by others</Text>
                            <TouchableOpacity onPress={stageRegionAll} style={styles.smallBtn}>
                              <Text style={styles.smallBtnText}>Stage all {regionResults.length}</Text>
                            </TouchableOpacity>
                          </View>
                          {regionResults.slice(0, 100).map((p) => {
                            const taken = p.assigned_to && p.assigned_to.distributor_id !== distributor.id;
                            return (
                              <View key={p.pincode} style={[styles.pinResult, { paddingVertical: 7 }]}>
                                <View style={{ flex: 1 }}>
                                  <Text style={styles.pinTitle}>{p.pincode} · {p.district}</Text>
                                  <Text style={styles.pinSub} numberOfLines={1}>{p.office || ""}</Text>
                                </View>
                                {taken ? (
                                  <View style={styles.warnPill}>
                                    <Text style={styles.warnPillText}>HELD</Text>
                                  </View>
                                ) : null}
                              </View>
                            );
                          })}
                          {regionResults.length > 100 ? (
                            <Text style={styles.emptyMini}>+ {regionResults.length - 100} more (will all be staged on tap)</Text>
                          ) : null}
                        </View>
                      ) : null}
                    </>
                  ) : null}

                  {/* Existing territories */}
                  <View style={{ marginTop: 22, flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                    <Text style={styles.sectionLabel}>CURRENT TERRITORIES ({areas.length})</Text>
                    {areas.length > 0 ? (
                      <TouchableOpacity
                        onPress={() => { setRemoveMode((v) => !v); setSelectedRemove([]); }}
                        style={styles.smallBtnGhost}
                      >
                        <Feather name={removeMode ? "x" : "trash-2"} size={12} color={colors.error} />
                        <Text style={[styles.smallBtnGhostText, { color: colors.error }]}>
                          {"  "}{removeMode ? "Cancel" : "Bulk remove"}
                        </Text>
                      </TouchableOpacity>
                    ) : null}
                  </View>
                  {loadingAreas ? (
                    <ActivityIndicator color={colors.primary} style={{ marginTop: 14 }} />
                  ) : areas.length === 0 ? (
                    <Text style={styles.emptyMini}>No pincodes assigned yet.</Text>
                  ) : (
                    groupedAreas.map(([state, rows]) => (
                      <View key={state} style={{ marginTop: 8 }}>
                        <Text style={styles.groupHeader}>{state.toUpperCase()} · {rows.length}</Text>
                        {rows.map((a) => {
                          const sel = selectedRemove.includes(a.pincode);
                          return (
                            <TouchableOpacity
                              key={a.pincode}
                              activeOpacity={removeMode ? 0.7 : 1}
                              onPress={() => {
                                if (!removeMode) return;
                                setSelectedRemove((prev) =>
                                  prev.includes(a.pincode) ? prev.filter((x) => x !== a.pincode) : [...prev, a.pincode]
                                );
                              }}
                              style={[styles.areaRow, removeMode && sel && { borderColor: colors.error, backgroundColor: colors.error + "10" }]}
                            >
                              {removeMode ? (
                                <Feather name={sel ? "check-square" : "square"} size={16} color={sel ? colors.error : colors.textMuted} />
                              ) : (
                                <View style={styles.areaPin}><Text style={styles.areaPinText}>{a.pincode}</Text></View>
                              )}
                              <View style={{ flex: 1 }}>
                                {removeMode ? (
                                  <Text style={styles.pinTitle}>{a.pincode}</Text>
                                ) : null}
                                <Text style={removeMode ? styles.pinSub : styles.pinTitle}>{a.district || "—"}</Text>
                                <Text style={styles.pinSub} numberOfLines={1}>{a.office || ""}</Text>
                              </View>
                              {!removeMode ? (
                                <TouchableOpacity onPress={() => removeOne(a.pincode)} style={styles.removeBtn}>
                                  <Feather name="x" size={14} color={colors.error} />
                                </TouchableOpacity>
                              ) : null}
                            </TouchableOpacity>
                          );
                        })}
                      </View>
                    ))
                  )}
                  <View style={{ height: 60 }} />
                </ScrollView>

                {/* Sticky action footer */}
                {stagedPins.length > 0 ? (
                  <View style={styles.footer}>
                    <Text style={styles.footerCount}>{stagedPins.length} staged</Text>
                    <TouchableOpacity onPress={submitAdd} disabled={savingAdd} style={[styles.assignBtn, savingAdd && { opacity: 0.6 }]}>
                      {savingAdd ? (
                        <ActivityIndicator color={colors.primaryFg} size="small" />
                      ) : (
                        <Text style={styles.assignBtnText}>Assign {stagedPins.length}</Text>
                      )}
                    </TouchableOpacity>
                  </View>
                ) : removeMode && selectedRemove.length > 0 ? (
                  <View style={styles.footer}>
                    <Text style={styles.footerCount}>{selectedRemove.length} selected</Text>
                    <TouchableOpacity
                      onPress={removeBulk}
                      disabled={removingBulk}
                      style={[styles.assignBtn, { backgroundColor: colors.error }, removingBulk && { opacity: 0.6 }]}
                    >
                      {removingBulk ? (
                        <ActivityIndicator color="#fff" size="small" />
                      ) : (
                        <Text style={styles.assignBtnText}>Remove {selectedRemove.length}</Text>
                      )}
                    </TouchableOpacity>
                  </View>
                ) : null}
              </>
            ) : null}
          </TouchableOpacity>
        </TouchableOpacity>
      </KeyboardAvoidingView>
      <ConfirmModal state={confirm.state} onClose={confirm.close} />
    </Modal>
  );
}

// ============================================================================
// Styles
// ============================================================================
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.lg, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  backBtn: { padding: 6 },
  overline: { fontSize: 11, fontWeight: "700", letterSpacing: 1, color: colors.textMuted },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },

  statsRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  statCard: { flex: 1, padding: 12, borderRadius: radii.md, alignItems: "flex-start" },
  statValue: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 6 },
  statLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "600", marginTop: 2 },

  newBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 13, marginBottom: 12,
  },
  newBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },

  sectionLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginBottom: 8, marginTop: 8 },
  empty: { alignItems: "center", padding: 40, gap: 8 },
  emptyText: { color: colors.textMuted, fontSize: 13, textAlign: "center" },
  emptyMini: { color: colors.textMuted, fontSize: 12, marginTop: 8, textAlign: "center" },

  list: { backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 14, paddingHorizontal: 14,
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
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999,
  },
  countText: { fontSize: 12, fontWeight: "800", color: colors.primary },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: colors.bg, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 18, maxHeight: "92%",
  },
  modalHandle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, alignSelf: "center", marginBottom: 14,
  },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },

  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: 10, paddingHorizontal: 10,
    height: 44, marginTop: 12, marginBottom: 4,
  },
  searchInput: { flex: 1, color: colors.textMain, fontSize: 14, outlineStyle: "none" as any },
  searchBtn: { backgroundColor: colors.primary, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 8 },
  searchBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 12 },

  // Tabs
  tabRow: { flexDirection: "row", marginTop: 12, gap: 6, backgroundColor: colors.surfaceMuted, padding: 4, borderRadius: 10 },
  tab: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 7 },
  tabActive: { backgroundColor: colors.surface },
  tabText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  tabTextActive: { color: colors.textMain },

  // Paste / region helpers
  helperLine: { fontSize: 11, color: colors.textMuted, marginTop: 8, marginBottom: 6 },
  textarea: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, padding: 10, minHeight: 110, color: colors.textMain, fontSize: 13,
    textAlignVertical: "top", marginTop: 4,
    outlineStyle: "none" as any,
  },
  regionInput: {
    flex: 1, marginTop: 8, paddingHorizontal: 10, fontSize: 13, color: colors.textMain,
  },
  smallBtn: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primary,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
  },
  smallBtnText: { color: colors.primary, fontSize: 11, fontWeight: "700" },
  smallBtnPrimary: {
    backgroundColor: colors.primary, paddingVertical: 10, borderRadius: 10,
    alignItems: "center", marginTop: 8,
  },
  smallBtnPrimaryText: { color: colors.primaryFg, fontSize: 13, fontWeight: "800" },
  smallBtnGhost: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 8, paddingVertical: 5,
    borderRadius: 6, backgroundColor: colors.error + "10",
  },
  smallBtnGhostText: { fontSize: 11, fontWeight: "700" },

  // Pincode result rows
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

  // Group header
  groupHeader: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, marginBottom: 4, marginTop: 6 },

  // Areas (bottom list)
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

  // Sticky footer
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 12, paddingHorizontal: 18,
    backgroundColor: colors.bg,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  footerCount: { flex: 1, fontSize: 12, fontWeight: "700", color: colors.textMuted },
  assignBtn: {
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 12, paddingHorizontal: 20, alignItems: "center", justifyContent: "center",
  },
  assignBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  demoteBtn: { padding: 6, backgroundColor: colors.error + "15", borderRadius: 8 },

  userRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },

  // Banner
  banner: { padding: 8, borderRadius: 8, marginTop: 10 },
  bannerOk: { backgroundColor: "#D1FAE5" },
  bannerErr: { backgroundColor: "#FEE2E2" },
  bannerText: { fontSize: 12, fontWeight: "600" },

  // Confirm modal
  confirmBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", padding: 24 },
  confirmBox: { backgroundColor: colors.bg, borderRadius: 14, padding: 20, width: "100%", maxWidth: 380 },
  confirmTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  confirmMsg: { fontSize: 13, color: colors.textMuted, marginTop: 8, lineHeight: 18 },
  confirmRow: { flexDirection: "row", justifyContent: "flex-end", gap: 8, marginTop: 18 },
  confirmBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: 8, minWidth: 90, alignItems: "center" },
  confirmBtnGhost: { backgroundColor: colors.surfaceMuted },
  confirmBtnGhostText: { color: colors.textMain, fontWeight: "700", fontSize: 13 },
  confirmBtnPrimary: { backgroundColor: colors.primary },
  confirmBtnDanger: { backgroundColor: colors.error },
  confirmBtnText: { color: "#fff", fontWeight: "800", fontSize: 13 },
});
