import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Txn = {
  id: string;
  user_id: string;
  type: string;
  amount: number;
  status: string;
  description?: string;
  created_at: string;
};

export default function AdminTxns() {
  const [items, setItems] = useState<Txn[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Txn[]>("/admin/transactions");
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <FlatList
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        ListHeaderComponent={
          <View>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Transactions</Text>
            <Text style={styles.sub}>{items.length} total</Text>
          </View>
        }
        data={items}
        keyExtractor={(i) => i.id}
        renderItem={({ item }) => (
          <View style={styles.row} testID={`txn-${item.id}`}>
            <View style={styles.iconBox}>
              <Feather
                name={item.type === "referral_payout" ? "trending-up" : item.type === "withdrawal" ? "arrow-up-right" : "credit-card"}
                size={16}
                color={colors.primary}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>{item.description || item.type}</Text>
              <Text style={styles.meta}>{new Date(item.created_at).toLocaleString()}</Text>
            </View>
            <Text style={[styles.amount, { color: item.amount >= 0 ? colors.success : "#B3261E" }]}>
              {item.amount >= 0 ? "+" : ""}{formatINR(item.amount)}
            </Text>
          </View>
        )}
        ListEmptyComponent={<Text style={styles.empty}>No transactions yet</Text>}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  sub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 20 },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8 },
  iconBox: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginRight: 12 },
  title: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  amount: { fontSize: 14, fontWeight: "800" },
  empty: { padding: 24, textAlign: "center", color: colors.textMuted },
});
