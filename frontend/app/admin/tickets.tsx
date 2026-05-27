import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, TextInput, ScrollView, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { downloadText } from "../../src/download";
import { colors, radii, spacing } from "../../src/theme";

type Ticket = {
  id: string; subject: string; category: string; priority: string; status: string;
  user_email?: string; user_name?: string; assigned_to_email?: string | null;
  message_count: number; last_message_at: string; last_message_preview: string;
  has_unread_admin: boolean; created_at: string; updated_at: string;
  is_guest?: boolean; guest_email?: string; guest_custom_category?: string | null;
};

const STATUSES = ["all", "open", "in_progress", "resolved", "closed"] as const;
const STATUS_META: Record<string, { label: string; bg: string; fg: string }> = {
  open: { label: "Open", bg: "#FFF4E5", fg: "#7A4A0E" },
  in_progress: { label: "In progress", bg: "#E6F1FB", fg: "#1F5E9E" },
  resolved: { label: "Resolved", bg: "#E6F4EE", fg: "#1F6B44" },
  closed: { label: "Closed", bg: "#F1F3F5", fg: "#667085" },
};
const PRIORITY_COLOR: Record<string, string> = { low: "#667085", normal: "#1F5E9E", high: "#C2410C", urgent: "#B3261E" };
const CATEGORY_ICON: Record<string, any> = { payment: "credit-card", withdrawal: "arrow-up-circle", account: "user", kyc: "shield", product: "shopping-bag", other: "help-circle" };

function timeAgo(iso: string): string {
  try {
    const d = new Date(iso); const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
  } catch { return ""; }
}

export default function AdminTickets() {
  const router = useRouter();
  const [items, setItems] = useState<Ticket[]>([]);
  const [counts, setCounts] = useState<{ open: number; in_progress: number; unread_admin: number }>({ open: 0, in_progress: 0, unread_admin: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const [q, setQ] = useState("");
  const [exportBusy, setExportBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (status !== "all") params.status = status;
      if (q.trim()) params.q = q.trim();
      const { data } = await api.get<{ items: Ticket[]; counts: any }>("/admin/tickets", { params });
      setItems(data.items || []);
      setCounts(data.counts || { open: 0, in_progress: 0, unread_admin: 0 });
    } catch (e) { Alert.alert("Couldn't load tickets", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [status, q]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onExport = async () => {
    setExportBusy(true);
    try {
      const { data } = await api.get<string>("/admin/tickets/export", { responseType: "text" as any });
      const ts = new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 14);
      await downloadText(`tickets_${ts}.csv`, data, "text/csv");
    } catch (e) { Alert.alert("Export failed", formatApiError(e)); }
    finally { setExportBusy(false); }
  };

  const renderItem = ({ item }: { item: Ticket }) => {
    const st = STATUS_META[item.status] || STATUS_META.open;
    return (
      <TouchableOpacity style={styles.card} onPress={() => router.push({ pathname: "/admin/ticket" as any, params: { id: item.id } })} testID={`admintix-row-${item.id}`}>
        <View style={styles.iconWrap}>
          <Feather name={CATEGORY_ICON[item.category] || "help-circle"} size={16} color={colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={styles.subject} numberOfLines={1}>{item.subject}</Text>
            {item.is_guest ? (
              <View style={styles.guestBadge}>
                <Feather name="user" size={9} color="#7A4A0E" />
                <Text style={styles.guestBadgeText}>{"  "}GUEST</Text>
              </View>
            ) : null}
            {item.has_unread_admin ? <View style={styles.dot} /> : null}
          </View>
          <Text style={styles.userRow} numberOfLines={1}>
            {item.is_guest
              ? `${item.guest_email || item.user_email}  ·  ${item.guest_custom_category || item.category}`
              : `${item.user_name || item.user_email}  ·  ${item.category}`}
          </Text>
          <Text style={styles.preview} numberOfLines={1}>{item.last_message_preview}</Text>
          <View style={styles.metaRow}>
            <View style={[styles.badge, { backgroundColor: st.bg }]}><Text style={[styles.badgeText, { color: st.fg }]}>{st.label}</Text></View>
            <View style={[styles.prioDot, { backgroundColor: PRIORITY_COLOR[item.priority] || "#667085" }]} />
            <Text style={styles.prioText}>{item.priority}</Text>
            <Text style={styles.time}>· {timeAgo(item.last_message_at)}</Text>
            <Text style={styles.time}>· {item.message_count}💬</Text>
          </View>
        </View>
        <Feather name="chevron-right" size={18} color={colors.textMuted} />
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Support Tickets</Text>
        <TouchableOpacity onPress={onExport} disabled={exportBusy} style={styles.iconBtn} testID="admintix-export">
          {exportBusy ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="download" size={20} color={colors.primary} />}
        </TouchableOpacity>
      </View>

      <View style={styles.statsRow}>
        <View style={styles.statCell}><Text style={styles.statNum}>{counts.open}</Text><Text style={styles.statLabel}>Open</Text></View>
        <View style={styles.statCell}><Text style={styles.statNum}>{counts.in_progress}</Text><Text style={styles.statLabel}>In progress</Text></View>
        <View style={styles.statCell}><Text style={[styles.statNum, { color: colors.primary }]}>{counts.unread_admin}</Text><Text style={styles.statLabel}>Unread</Text></View>
      </View>

      <View style={{ paddingHorizontal: spacing.screen }}>
        <TextInput style={styles.search} placeholder="Search subject, email, name..." placeholderTextColor={colors.textMuted} value={q} onChangeText={setQ} onSubmitEditing={load} returnKeyType="search" testID="admintix-search" />
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0 }} contentContainerStyle={styles.tabsRow}>
        {STATUSES.map((s) => (
          <TouchableOpacity key={s} onPress={() => setStatus(s)} style={[styles.tabChip, status === s && styles.tabChipActive]} testID={`admintix-tab-${s}`}>
            <Text style={[styles.tabChipText, status === s && { color: colors.primaryFg }]}>{s === "all" ? "All" : STATUS_META[s]?.label || s}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>
      ) : items.length === 0 ? (
        <View style={styles.center}><Feather name="inbox" size={44} color={colors.textMuted} /><Text style={styles.emptyText}>No tickets match.</Text></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(it) => it.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  statsRow: { flexDirection: "row", paddingHorizontal: spacing.screen, paddingTop: 12, gap: 8 },
  statCell: { flex: 1, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 12, alignItems: "center" },
  statNum: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  statLabel: { fontSize: 10, color: colors.textMuted, letterSpacing: 1, marginTop: 2, fontWeight: "700" },
  search: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 10, fontSize: 13, color: colors.textMain, marginTop: 12 },
  tabsRow: { paddingHorizontal: spacing.screen, paddingTop: 10, gap: 6 },
  tabChip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 18, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  tabChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  emptyText: { color: colors.textMuted, marginTop: 8 },
  card: { flexDirection: "row", gap: 12, padding: 12, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  iconWrap: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: "#F1F6F2" },
  subject: { fontSize: 13, fontWeight: "800", color: colors.textMain, flex: 1 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary },
  guestBadge: { flexDirection: "row", alignItems: "center", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, backgroundColor: "#FFF4E5", borderWidth: 1, borderColor: "#F5BB6A" },
  guestBadgeText: { fontSize: 9, fontWeight: "800", color: "#7A4A0E", letterSpacing: 0.5 },
  userRow: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  preview: { fontSize: 12, color: colors.textMain, marginTop: 4 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6 },
  badgeText: { fontSize: 10, fontWeight: "700" },
  prioDot: { width: 8, height: 8, borderRadius: 4 },
  prioText: { fontSize: 10, color: colors.textMuted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 },
  time: { fontSize: 10, color: colors.textMuted },
});
