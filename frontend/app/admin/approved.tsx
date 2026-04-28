import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity, Alert, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { downloadText } from "../../src/download";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type ApprovedRecord = {
  id: string;
  original_user_id: string;
  email?: string | null;
  name?: string | null;
  phone?: string | null;
  referral_code?: string | null;
  referred_by?: string | null;
  registration_paid?: boolean;
  payment_method?: string | null;
  wallet_balance_at_approval?: number;
  approver_role: string;
  approver_email?: string | null;
  auto_approved?: boolean;
  source?: string;
  approved_at: string;
};

type Tab = "all" | "auto" | "finance" | "super_admin" | "manager" | "support";

const TABS: { key: Tab; label: string; tint: string }[] = [
  { key: "all", label: "All", tint: colors.textMain },
  { key: "auto", label: "Auto (Finance)", tint: "#2E7D52" },
  { key: "super_admin", label: "Super admin", tint: "#143D2E" },
  { key: "manager", label: "Manager", tint: "#3D5A80" },
  { key: "support", label: "Support", tint: "#A07A2C" },
];

const ROLE_LABEL: Record<string, string> = {
  super_admin: "Super admin",
  manager: "Manager",
  support: "Support",
  finance: "Finance",
} as any;

export default function AdminApproved() {
  const router = useRouter();
  const { user } = useAuth();
  const role = (user as any)?.admin_role || "super_admin";
  const canExport = role === "super_admin" || role === "finance";
  const canDelete = role === "super_admin";

  const [tab, setTab] = useState<Tab>("all");
  const [items, setItems] = useState<ApprovedRecord[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: ApprovedRecord[]; counts: Record<string, number> }>(
        `/admin/approved-registrations${tab !== "all" ? `?role_filter=${tab}` : ""}`,
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
        `/admin/approved-registrations/export${tab !== "all" ? `?role_filter=${tab}` : ""}`,
        { responseType: "text" },
      );
      const data = (res.data as unknown) as string;
      const csv = typeof data === "string" ? data : "";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const filename = `approved-registrations-${tab}-${stamp}.csv`;
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

  const onDelete = (rec: ApprovedRecord) => {
    Alert.alert(
      "Remove archive record?",
      `This removes ONLY the archive entry for ${rec.email || rec.name}. The underlying user account stays active.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            setBusy(rec.id);
            try {
              await api.delete(`/admin/approved-registrations/${rec.id}`);
              await load();
            } catch (e) {
              Alert.alert("Failed", formatApiError(e));
            } finally { setBusy(null); }
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="approved-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Approved registrations</Text>
        {canExport ? (
          <TouchableOpacity onPress={onExport} style={styles.iconBtn} testID="approved-export">
            <Feather name="download" size={16} color={colors.primary} />
          </TouchableOpacity>
        ) : <View style={{ width: 36 }} />}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabsWrap}>
        {TABS.map((t) => {
          const active = tab === t.key;
          const n = counts[t.key] ?? 0;
          return (
            <TouchableOpacity key={t.key} onPress={() => setTab(t.key)} style={[styles.tab, active && { backgroundColor: t.tint, borderColor: t.tint }]} testID={`approved-tab-${t.key}`}>
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
            <View style={styles.card} testID={`approved-${item.id}`}>
              <View style={styles.cardTop}>
                <View style={[styles.avatar, { backgroundColor: item.auto_approved ? "#2E7D52" : colors.primary }]}>
                  <Text style={styles.avatarText}>{(item.name || item.email || "?").charAt(0).toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardName}>{item.name || "—"}</Text>
                  <Text style={styles.cardEmail}>{item.email || "—"}</Text>
                </View>
                <View style={[styles.pill, { backgroundColor: item.auto_approved ? "#2E7D52" : "#143D2E" }]}>
                  <Text style={styles.pillText}>{item.auto_approved ? "AUTO • FINANCE" : (ROLE_LABEL[item.approver_role] || item.approver_role).toUpperCase()}</Text>
                </View>
              </View>
              <View style={styles.meta}>
                {item.phone ? <Meta icon="phone" text={item.phone} /> : null}
                {item.referral_code ? <Meta icon="hash" text={item.referral_code} /> : null}
                {item.referred_by ? <Meta icon="user-plus" text={`sponsor ${item.referred_by}`} /> : null}
                {typeof item.wallet_balance_at_approval === "number" ? <Meta icon="dollar-sign" text={formatINR(item.wallet_balance_at_approval)} /> : null}
                {item.payment_method ? <Meta icon="credit-card" text={item.payment_method} /> : null}
                {item.source ? <Meta icon="user-check" text={item.source} /> : null}
              </View>
              <View style={styles.footer}>
                <Text style={styles.footerText}>{item.approver_email ? `By ${item.approver_email} · ` : ""}{new Date(item.approved_at).toLocaleString()}</Text>
                {canDelete && (
                  <TouchableOpacity onPress={() => onDelete(item)} disabled={busy === item.id} style={styles.deleteBtn} testID={`approved-${item.id}-delete`}>
                    {busy === item.id ? <ActivityIndicator color="#7A4A0E" size="small" /> : (
                      <>
                        <Feather name="archive" size={11} color="#7A4A0E" />
                        <Text style={styles.deleteBtnText}>  Remove</Text>
                      </>
                    )}
                  </TouchableOpacity>
                )}
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No approved records in this filter.</Text>}
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
  iconBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5, flex: 1, textAlign: "center" },
  tabsWrap: { paddingHorizontal: spacing.screen, paddingBottom: 8, gap: 8, flexDirection: "row" },
  tab: { flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingVertical: 8, borderRadius: 99, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, gap: 8 },
  tabText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  tabBadge: { backgroundColor: colors.surfaceMuted, borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2 },
  tabBadgeText: { fontSize: 10, fontWeight: "800", color: colors.textMain },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  cardName: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  cardEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 99, maxWidth: 150 },
  pillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.5, textAlign: "center" },
  meta: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 10 },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { fontSize: 11, color: colors.textMuted },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border },
  footerText: { fontSize: 11, color: colors.textMuted, flex: 1 },
  deleteBtn: { flexDirection: "row", alignItems: "center", paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8, backgroundColor: "#FFF4E5" },
  deleteBtnText: { fontSize: 11, fontWeight: "700", color: "#7A4A0E" },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
});
