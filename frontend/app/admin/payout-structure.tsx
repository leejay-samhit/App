// Admin → Payout structure, shop by shop. Cashback % and delivery charge used
// to be one number for every seller; each shop can now carry its own, and a
// shop with no override quietly follows the platform default.
//
// Changing a rate only affects FUTURE orders — every existing order froze its
// own cashback % and delivery charge at checkout, so no past money moves.
import { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, TextInput, Modal, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { notify } from "../../src/notify";

type Row = {
  vendor_id: string; shop_name: string; email?: string; pincode?: string;
  approved: boolean;
  cashback_pct: number | null;
  delivery_charge_flat: number | null;
  delivery_free_threshold: number | null;
  effective_cashback_pct: number;
  effective_delivery_flat: number;
  effective_free_threshold: number;
  has_override: boolean;
};

type Defaults = {
  cashback_pct: number; delivery_charge_flat: number; delivery_free_threshold: number;
  max_cashback_pct: number; delivery_cart_max: number; cashback_enabled?: boolean;
};

export default function AdminPayoutStructureScreen() {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>([]);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState<Row | null>(null);
  const [cb, setCb] = useState("");
  const [flat, setFlat] = useState("");
  const [free, setFree] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/payout-structure/vendors");
      setRows(data?.vendors || []);
      setDefaults(data?.defaults || null);
    } catch (e) {
      notify(formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      (r.shop_name || "").toLowerCase().includes(needle)
      || (r.email || "").toLowerCase().includes(needle)
      || (r.pincode || "").includes(needle));
  }, [rows, q]);

  const open = (r: Row) => {
    setEdit(r);
    setCb(r.cashback_pct == null ? "" : String(r.cashback_pct));
    setFlat(r.delivery_charge_flat == null ? "" : String(r.delivery_charge_flat));
    setFree(r.delivery_free_threshold == null ? "" : String(r.delivery_free_threshold));
  };

  const save = async () => {
    if (!edit) return;
    const body: Record<string, unknown> = { clear: [] as string[] };
    const clear: string[] = [];
    const num = (v: string) => (v.trim() === "" ? null : parseFloat(v));
    const c = num(cb), f = num(flat), t = num(free);
    if (c == null) clear.push("cashback_pct"); else body.cashback_pct = c;
    if (f == null) clear.push("delivery_charge_flat"); else body.delivery_charge_flat = f;
    if (t == null) clear.push("delivery_free_threshold"); else body.delivery_free_threshold = t;
    body.clear = clear;
    if (c != null && defaults && c > defaults.max_cashback_pct) {
      notify(`Cashback cannot be above ${defaults.max_cashback_pct}%`);
      return;
    }
    setBusy(true);
    try {
      await api.put(`/admin/payout-structure/vendors/${edit.vendor_id}`, body);
      notify(`${edit.shop_name} updated — applies to new orders`);
      setEdit(null);
      load();
    } catch (e) {
      notify(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.back} testID="ps-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Payout structure</Text>
        <View style={{ width: 36 }} />
      </View>

      {defaults ? (
        <View style={styles.defaultsBar}>
          <Text style={styles.defaultsText}>
            Platform default · cashback {defaults.cashback_pct}% · delivery{" "}
            {formatINR(defaults.delivery_charge_flat)} · free above{" "}
            {formatINR(defaults.delivery_free_threshold)}
          </Text>
          <TouchableOpacity onPress={() => router.push("/admin/settings" as any)} testID="ps-defaults">
            <Text style={styles.defaultsLink}>Change default</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {defaults && defaults.cashback_enabled === false ? (
        <View style={styles.warnBar} testID="payout-cashback-off-warning">
          <Feather name="alert-triangle" size={15} color="#8A5A00" />
          <Text style={styles.warnText}>
            Purchase cashback is switched OFF platform-wide, so these rates pay 0% at
            checkout. Turn it on in Platform defaults.
          </Text>
        </View>
      ) : null}

      <View style={styles.searchWrap}>
        <Feather name="search" size={16} color={colors.textMuted} />
        <TextInput
          value={q}
          onChangeText={setQ}
          placeholder="Search shop, email or pincode"
          placeholderTextColor={colors.textMuted}
          style={styles.search}
          testID="ps-search"
        />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.container}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          {filtered.length === 0 ? (
            <Text style={styles.empty}>No shops match that search.</Text>
          ) : filtered.map((r) => (
            <TouchableOpacity
              key={r.vendor_id}
              onPress={() => open(r)}
              style={styles.row}
              testID={`ps-row-${r.vendor_id}`}
            >
              <View style={{ flex: 1, minWidth: 0 }}>
                <View style={styles.rowHead}>
                  <Text style={styles.rowName} numberOfLines={1}>{r.shop_name}</Text>
                  {r.has_override ? (
                    <View style={styles.ownBadge}><Text style={styles.ownBadgeText}>OWN RATE</Text></View>
                  ) : (
                    <View style={styles.defBadge}><Text style={styles.defBadgeText}>DEFAULT</Text></View>
                  )}
                </View>
                <Text style={styles.rowSub} numberOfLines={1}>
                  cashback {r.effective_cashback_pct}% · delivery {formatINR(r.effective_delivery_flat)} ·
                  free above {formatINR(r.effective_free_threshold)}
                </Text>
                {r.pincode ? <Text style={styles.rowMeta}>PIN {r.pincode}</Text> : null}
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      <Modal visible={!!edit} transparent animationType="slide" statusBarTranslucent onRequestClose={() => setEdit(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.sheetWrap}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>{edit?.shop_name}</Text>
            <Text style={styles.sheetSub}>
              Leave a box empty to follow the platform default. New rates apply to new
              orders only — orders already placed keep what the customer was promised.
            </Text>
            {[
              { label: `Cashback % (max ${defaults?.max_cashback_pct ?? 10})`, value: cb, set: setCb, def: defaults?.cashback_pct, id: "cb" },
              { label: "Delivery charge (₹)", value: flat, set: setFlat, def: defaults?.delivery_charge_flat, id: "flat" },
              { label: "Free delivery above (₹)", value: free, set: setFree, def: defaults?.delivery_free_threshold, id: "free" },
            ].map((f) => (
              <View key={f.id} style={styles.field}>
                <Text style={styles.fieldLabel}>{f.label}</Text>
                <TextInput
                  value={f.value}
                  onChangeText={f.set}
                  keyboardType="decimal-pad"
                  placeholder={`Default ${f.def ?? 0}`}
                  placeholderTextColor={colors.textMuted}
                  style={styles.input}
                  testID={`ps-input-${f.id}`}
                />
              </View>
            ))}
            <View style={styles.sheetRow}>
              <TouchableOpacity onPress={() => setEdit(null)} style={[styles.sheetBtn, styles.sheetGhost]} testID="ps-cancel">
                <Text style={styles.sheetGhostText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={save}
                disabled={busy}
                style={[styles.sheetBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]}
                testID="ps-save"
              >
                {busy ? <ActivityIndicator color={colors.primaryFg} size="small" />
                  : <Text style={styles.sheetBtnText}>Save</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingTop: 40 },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  back: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },

  defaultsBar: {
    paddingHorizontal: spacing.screen, paddingVertical: 10, backgroundColor: colors.brand100,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12,
  },
  defaultsText: { fontSize: 11.5, color: colors.primary, fontWeight: "700", flex: 1, minWidth: 0 },
  defaultsLink: { fontSize: 11.5, fontWeight: "900", color: colors.primary, textDecorationLine: "underline" },

  warnBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: spacing.screen, marginTop: 12, padding: 12,
    borderRadius: radii.card, backgroundColor: "#FFF7E6",
    borderWidth: 1, borderColor: colors.warning,
  },
  warnText: { flex: 1, fontSize: 11.5, fontWeight: "700", color: "#8A5A00", lineHeight: 16 },

  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8, margin: spacing.screen,
    marginBottom: 8, paddingHorizontal: 14, minHeight: 46,
    backgroundColor: colors.surface, borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.border,
  },
  search: { flex: 1, fontSize: 14, color: colors.textMain },

  container: { paddingHorizontal: spacing.screen, paddingBottom: 48 },
  empty: { fontSize: 13, color: colors.textMuted, textAlign: "center", marginTop: 32 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 10,
  },
  rowHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowName: { fontSize: 14, fontWeight: "800", color: colors.textMain, flexShrink: 1 },
  rowSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 3, lineHeight: 16 },
  rowMeta: { fontSize: 10.5, color: colors.textMuted, marginTop: 2 },
  ownBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: colors.primary },
  ownBadgeText: { fontSize: 9, fontWeight: "900", color: colors.primaryFg, letterSpacing: 0.8 },
  defBadge: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  defBadgeText: { fontSize: 9, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.8 },

  sheetWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 20, paddingBottom: 32,
  },
  sheetTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  sheetSub: { fontSize: 12, color: colors.textMuted, marginTop: 6, lineHeight: 17, marginBottom: 12 },
  field: { marginBottom: 12 },
  fieldLabel: { fontSize: 12.5, fontWeight: "800", color: colors.textMain, marginBottom: 6 },
  input: {
    minHeight: 46, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    paddingHorizontal: 14, fontSize: 15, color: colors.textMain, backgroundColor: colors.background,
  },
  sheetRow: { flexDirection: "row", gap: 10, marginTop: 8 },
  sheetBtn: { flex: 1, minHeight: 48, borderRadius: radii.button, alignItems: "center", justifyContent: "center" },
  sheetGhost: { backgroundColor: colors.surfaceMuted },
  sheetGhostText: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  sheetBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },
});
