import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity, Alert, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { downloadText } from "../../src/download";
import { colors, radii, spacing } from "../../src/theme";

type RejectedRecord = {
  id: string;
  original_user_id: string;
  email?: string | null;
  name?: string | null;
  phone?: string | null;
  referral_code?: string | null;
  referred_by?: string | null;
  category: string;
  remarks?: string | null;
  registration_paid?: boolean;
  payment_method?: string | null;
  payment_attempts?: number;
  rejected_at: string;
  rejected_by: string;
};

type Tab = "all" | "payment_unsuccessful" | "referral_code_mistake" | "other";

const TABS: { key: Tab; label: string; tint: string }[] = [
  { key: "all", label: "All", tint: colors.textMain },
  { key: "payment_unsuccessful", label: "Payment", tint: "#B3261E" },
  { key: "referral_code_mistake", label: "Referral", tint: "#A07A2C" },
  { key: "other", label: "Other", tint: "#3D5A80" },
];

const CATEGORY_LABELS: Record<string, string> = {
  payment_unsuccessful: "Payment unsuccessful",
  referral_code_mistake: "Referral code mistake",
  other: "Other",
};

export default function AdminRejected() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user as any)?.admin_role || "super_admin";
  const canExport = role === "super_admin" || role === "finance";
  const canDelete = role === "super_admin";

  const [tab, setTab] = useState<Tab>("all");
  const [items, setItems] = useState<RejectedRecord[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: RejectedRecord[]; counts: Record<string, number> }>(
        `/admin/rejected-registrations${tab !== "all" ? `?category=${tab}` : ""}`,
      );
      setItems(data.items);
      setCounts(data.counts || {});
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [tab]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onExport = async () => {
    try {
      const res = await api.get(
        `/admin/rejected-registrations/export${tab !== "all" ? `?category=${tab}` : ""}`,
        { responseType: "text" },
      );
      const data = (res.data as unknown) as string;
      const csv = typeof data === "string" ? data : "";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const filename = `rejected-registrations-${tab}-${stamp}.csv`;
      const out = await downloadText({ filename, content: csv, mimeType: "text/csv" });
      if (out.ok) {
        const lines = csv.split("\n").length - 1;
        Alert.alert(
          "Export ready",
          `${lines} record${lines === 1 ? "" : "s"} exported.${out.method === "browser" ? "\n\nCheck your browser's Downloads folder." : ""}`,
        );
      }
    } catch (e) {
      Alert.alert("Export failed", formatApiError(e));
    }
  };

  const onDelete = (rec: RejectedRecord) => {
    Alert.alert(
      "Delete permanently?",
      `This will permanently remove ${rec.email || rec.name || "this record"} from the archive. The action cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setBusy(rec.id);
            try {
              await api.delete(`/admin/rejected-registrations/${rec.id}`);
              await load();
            } catch (e) {
              Alert.alert("Delete failed", formatApiError(e));
            } finally { setBusy(null); }
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="rejected-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Rejected registrations</Text>
        {canExport ? (
          <TouchableOpacity onPress={onExport} style={styles.exportBtn} testID="rejected-export">
            <Feather name="download" size={16} color={colors.primary} />
          </TouchableOpacity>
        ) : <View style={{ width: 40 }} />}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabsWrap}>
        {TABS.map((t) => {
          const active = tab === t.key;
          const n = counts[t.key] ?? 0;
          return (
            <TouchableOpacity key={t.key} onPress={() => setTab(t.key)} style={[styles.tab, active && { backgroundColor: t.tint, borderColor: t.tint }]} testID={`rejected-tab-${t.key}`}>
              <Text style={[styles.tabText, active && { color: "#fff" }]}>{t.label}</Text>
              <View style={[styles.tabBadge, active && { backgroundColor: "rgba(255,255,255,0.2)" }]}>
                <Text style={[styles.tabBadgeText, active && { color: "#fff" }]}>{n}</Text>
              </View>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`rejected-${item.id}`}>
              <View style={styles.cardTop}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{(item.name || item.email || "?").charAt(0).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardName}>{item.name || "—"}</Text>
                  <Text style={styles.cardEmail}>{item.email || "—"}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: item.category === "payment_unsuccessful" ? "#B3261E" : item.category === "referral_code_mistake" ? "#A07A2C" : "#3D5A80" }]}>
                  <Text style={styles.pillText}>{CATEGORY_LABELS[item.category] || item.category}</Text>
                </View>
              </View>
              <View style={styles.meta}>
                {item.phone ? <Meta icon="phone" text={item.phone} /> : null}
                {item.referral_code ? <Meta icon="hash" text={item.referral_code} /> : null}
                {item.referred_by ? <Meta icon="user-plus" text={`sponsor ${item.referred_by}`} /> : null}
                {typeof item.payment_attempts === "number" ? <Meta icon="repeat" text={`${item.payment_attempts} attempt${item.payment_attempts === 1 ? "" : "s"}`} /> : null}
              </View>
              {item.remarks ? (
                <View style={styles.remarkBox}>
                  <Text style={styles.remarkLabel}>REMARKS</Text>
                  <Text style={styles.remarkText}>{item.remarks}</Text>
                </View>
              ) : null}
              <View style={styles.footer}>
                <Text style={styles.footerText}>Rejected {new Date(item.rejected_at).toLocaleString()}</Text>
                {canDelete && (
                  <TouchableOpacity onPress={() => onDelete(item)} disabled={busy === item.id} style={styles.deleteBtn} testID={`rejected-${item.id}-delete`}>
                    {busy === item.id ? <ActivityIndicator color="#B3261E" size="small" /> : (
                      <>
                        <Feather name="trash-2" size={12} color="#B3261E" />
                        <Text style={styles.deleteBtnText}>  Delete</Text>
                      </>
                    )}
                  </TouchableOpacity>
                )}
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No rejected records in this category</Text>}
        />
      )}
    </SafeAreaView>
  );
}

function Meta({ icon, text }: { icon: any; text: string }) {
  return (
    <View style={styles.metaItem}>
      <Feather name={icon} size={11} color={colors.textMuted} />
      <Text style={styles.metaText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  exportBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabsWrap: { paddingHorizontal: spacing.screen, paddingBottom: 8, gap: 8, flexDirection: "row" },
  tab: { flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, gap: 8 },
  tabText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  tabBadge: { backgroundColor: colors.surfaceMuted, borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  tabBadgeText: { fontSize: 10, fontWeight: "800", color: colors.textMain },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  cardName: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  cardEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 99, maxWidth: 130 },
  pillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.5, textAlign: "center" },
  meta: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 10 },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { fontSize: 11, color: colors.textMuted },
  remarkBox: { marginTop: 10, padding: 10, backgroundColor: colors.surfaceMuted, borderRadius: 10 },
  remarkLabel: { fontSize: 9, letterSpacing: 1, color: colors.textMuted, fontWeight: "800" },
  remarkText: { fontSize: 12, color: colors.textMain, marginTop: 4, lineHeight: 18 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border },
  footerText: { fontSize: 11, color: colors.textMuted },
  deleteBtn: { flexDirection: "row", alignItems: "center", paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8, backgroundColor: "#FCE9E5" },
  deleteBtnText: { fontSize: 11, fontWeight: "700", color: "#B3261E" },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
});
