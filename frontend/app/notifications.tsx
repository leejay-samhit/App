import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "../src/api";
import { colors, radii, spacing } from "../src/theme";

type Notif = {
  id: string;
  kind: string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
};

const ICONS: Record<string, any> = {
  payout: "trending-up",
  referral: "user-plus",
  withdrawal: "arrow-up-right",
  order: "package",
  welcome: "gift",
};

export default function NotificationsScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Notif[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Notif[]>("/notifications/me");
      setItems(data);
      // Mark all as read
      await api.post("/notifications/me/read-all").catch(() => {});
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="notifs-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Activity</Text>
        <View style={{ width: 40 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Feather name="bell-off" size={32} color={colors.textMuted} />
          <Text style={styles.emptyTitle}>No activity yet</Text>
          <Text style={styles.emptyText}>Payouts, withdrawals and orders will show here.</Text>
        </View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.item} testID={`notif-${item.id}`}>
              <View style={[styles.iconBox, { backgroundColor: item.kind === "payout" ? colors.success : item.kind === "withdrawal" ? colors.accent : colors.brand500 }]}>
                <Feather name={ICONS[item.kind] || "bell"} size={16} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.itemTitle}>{item.title}</Text>
                <Text style={styles.itemBody}>{item.body}</Text>
                <Text style={styles.itemTime}>{new Date(item.created_at).toLocaleString()}</Text>
              </View>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.textMuted, marginTop: 4, textAlign: "center" },
  item: { flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 14, marginBottom: 8, gap: 12 },
  iconBox: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  itemTitle: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  itemBody: { fontSize: 13, color: colors.textMuted, marginTop: 2 },
  itemTime: { fontSize: 11, color: colors.textMuted, marginTop: 6 },
});
