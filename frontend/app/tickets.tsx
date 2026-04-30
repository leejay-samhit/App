import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing } from "../src/theme";

type Ticket = {
  id: string;
  subject: string;
  category: string;
  priority: string;
  status: string;
  message_count: number;
  last_message_at: string;
  last_message_by: string;
  last_message_preview: string;
  has_unread_user: boolean;
  created_at: string;
  updated_at: string;
};

const STATUS_META: Record<string, { label: string; bg: string; fg: string }> = {
  open: { label: "Open", bg: "#FFF4E5", fg: "#7A4A0E" },
  in_progress: { label: "In progress", bg: "#E6F1FB", fg: "#1F5E9E" },
  resolved: { label: "Resolved", bg: "#E6F4EE", fg: "#1F6B44" },
  closed: { label: "Closed", bg: "#F1F3F5", fg: "#667085" },
};

const CATEGORY_ICON: Record<string, any> = {
  payment: "credit-card",
  withdrawal: "arrow-up-circle",
  account: "user",
  kyc: "shield",
  product: "shopping-bag",
  other: "help-circle",
};

function timeAgo(iso: string): string {
  try {
    const d = new Date(iso);
    const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const days = Math.floor(h / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  } catch { return ""; }
}

export default function MyTicketsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setErr(null);
      const { data } = await api.get<{ items: Ticket[] }>("/tickets/me");
      setItems(data.items || []);
    } catch (e) { setErr(formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  const renderItem = ({ item }: { item: Ticket }) => {
    const st = STATUS_META[item.status] || STATUS_META.open;
    return (
      <TouchableOpacity
        style={styles.card}
        onPress={() => router.push({ pathname: "/ticket" as any, params: { id: item.id } })}
        testID={`ticket-row-${item.id}`}
      >
        <View style={styles.iconWrap}>
          <Feather name={CATEGORY_ICON[item.category] || "help-circle"} size={18} color={colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Text style={styles.subject} numberOfLines={1}>{item.subject}</Text>
            {item.has_unread_user && <View style={styles.dot} />}
          </View>
          <Text style={styles.preview} numberOfLines={2}>
            {item.last_message_by === "admin" ? "Support: " : "You: "}{item.last_message_preview}
          </Text>
          <View style={styles.metaRow}>
            <View style={[styles.badge, { backgroundColor: st.bg }]}>
              <Text style={[styles.badgeText, { color: st.fg }]}>{st.label}</Text>
            </View>
            <Text style={styles.time}>· {timeAgo(item.last_message_at)}</Text>
            <Text style={styles.time}>· {item.message_count} msg</Text>
          </View>
        </View>
        <Feather name="chevron-right" size={18} color={colors.textMuted} />
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="tickets-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Support</Text>
        <TouchableOpacity onPress={() => router.push("/ticket-new" as any)} style={styles.iconBtn} testID="tickets-new">
          <Feather name="plus" size={22} color={colors.primary} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>
      ) : err ? (
        <View style={styles.center}><Text style={{ color: "#B3261E" }}>{err}</Text></View>
      ) : items.length === 0 ? (
        <View style={styles.center}>
          <Feather name="message-circle" size={48} color={colors.textMuted} />
          <Text style={styles.emptyTitle}>No tickets yet</Text>
          <Text style={styles.emptyBody}>Raise a ticket and our team will get back to you.</Text>
          <TouchableOpacity onPress={() => router.push("/ticket-new" as any)} style={styles.primaryBtn} testID="tickets-empty-new">
            <Feather name="plus" size={16} color={colors.primaryFg} />
            <Text style={styles.primaryBtnText}>  New ticket</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(it) => it.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  card: { flexDirection: "row", gap: 12, padding: 14, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  iconWrap: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: "#F1F6F2" },
  subject: { fontSize: 14, fontWeight: "800", color: colors.textMain, flex: 1 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primary },
  preview: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, flexWrap: "wrap" },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  badgeText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  time: { fontSize: 11, color: colors.textMuted },
  emptyTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 12 },
  emptyBody: { fontSize: 13, color: colors.textMuted, marginTop: 6, textAlign: "center" },
  primaryBtn: { flexDirection: "row", alignItems: "center", backgroundColor: colors.primary, paddingHorizontal: 20, paddingVertical: 12, borderRadius: radii.button, marginTop: 20 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 14 },
});
