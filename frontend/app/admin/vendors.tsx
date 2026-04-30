import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, Alert, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Vendor = {
  id: string; email: string; name: string; shop_name?: string;
  vendor_status: string; total_sales: number; total_earnings: number;
  products_count: number; vendor_approved_at?: string;
};

export default function AdminVendorsList() {
  const router = useRouter();
  const [items, setItems] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: Vendor[] }>("/admin/vendors");
      setItems(data.items || []);
    } catch (e) { Alert.alert("Couldn't load", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const toggleSuspend = (v: Vendor) => {
    const action = v.vendor_status === "suspended" ? "reactivate" : "suspend";
    Alert.alert(`${action[0].toUpperCase() + action.slice(1)} ${v.shop_name || v.email}?`, "", [
      { text: "Cancel", style: "cancel" },
      { text: action[0].toUpperCase() + action.slice(1), style: action === "suspend" ? "destructive" : "default", onPress: async () => {
        setBusyId(v.id);
        try { await api.post(`/admin/vendors/${v.id}/${action}`); await load(); }
        catch (e) { Alert.alert("Failed", formatApiError(e)); }
        finally { setBusyId(null); }
      } }
    ]);
  };

  const renderItem = ({ item }: { item: Vendor }) => {
    const suspended = item.vendor_status === "suspended";
    return (
      <View style={styles.card}>
        <View style={[styles.statusDot, { backgroundColor: suspended ? "#B3261E" : "#1F6B44" }]} />
        <View style={{ flex: 1 }}>
          <Text style={styles.shop}>{item.shop_name || item.name}</Text>
          <Text style={styles.user}>{item.email}</Text>
          <View style={styles.statsRow}>
            <Text style={styles.stat}>{formatINR(item.total_earnings)} earned</Text>
            <Text style={styles.stat}>· {item.products_count} products</Text>
            <Text style={styles.stat}>· {formatINR(item.total_sales)} GMV</Text>
          </View>
        </View>
        <TouchableOpacity onPress={() => toggleSuspend(item)} disabled={busyId === item.id} style={[styles.actionBtn, { backgroundColor: suspended ? "#1F6B44" : "#B3261E" }]} testID={`vendors-toggle-${item.id}`}>
          {busyId === item.id ? <ActivityIndicator color="#fff" size="small" /> : <Feather name={suspended ? "play" : "pause"} size={14} color="#fff" />}
        </TouchableOpacity>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>All Vendors</Text>
        <TouchableOpacity onPress={() => router.push("/admin/vendor-applications" as any)} style={styles.iconBtn} testID="vendors-apps"><Feather name="file-text" size={20} color={colors.primary} /></TouchableOpacity>
      </View>
      {loading ? (
        <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.center}><Feather name="users" size={44} color={colors.textMuted} /><Text style={styles.empty}>No vendors yet.</Text></View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(it) => it.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
          ItemSeparatorComponent={() => <View style={{ height: 10 }} />}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  empty: { color: colors.textMuted, marginTop: 8 },
  card: { flexDirection: "row", alignItems: "center", padding: 12, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, gap: 10 },
  statusDot: { width: 10, height: 10, borderRadius: 5 },
  shop: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  user: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  statsRow: { flexDirection: "row", flexWrap: "wrap", marginTop: 4, gap: 4 },
  stat: { fontSize: 11, color: colors.textMuted, fontWeight: "600" },
  actionBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
});
