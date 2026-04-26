import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, TouchableOpacity, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, spacing } from "../../src/theme";

type AuditLog = {
  id: string;
  admin_email: string;
  admin_role: string;
  action: string;
  target_type: string;
  target_id: string;
  details: any;
  created_at: string;
};

const ICONS: Record<string, any> = {
  "user.block": "user-x",
  "user.unblock": "user-check",
  "user.update": "edit-2",
  "user.delete": "trash-2",
  "user.reset_password": "key",
  "wallet.credit": "plus-circle",
  "wallet.debit": "minus-circle",
  "wallet.freeze": "lock",
  "wallet.unfreeze": "unlock",
  "kyc.approve": "check-circle",
  "kyc.reject": "x-circle",
  "txn.refund": "rotate-ccw",
  "txn.status": "edit-2",
  "order.status": "package",
  "settings.update": "sliders",
  "export": "download",
};

export default function AdminAudit() {
  const router = useRouter();
  const [items, setItems] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<AuditLog[]>("/admin/audit-logs?limit=300");
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="audit-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Audit log</Text>
        <View style={{ width: 40 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.row} testID={`audit-${item.id}`}>
              <View style={styles.iconBox}>
                <Feather name={ICONS[item.action] || "activity"} size={14} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.action}>{item.action}</Text>
                <Text style={styles.who}>{item.admin_email} · {item.admin_role}</Text>
                {item.target_id ? <Text style={styles.target}>{item.target_type}: {item.target_id.slice(0, 12)}…</Text> : null}
                {item.details && Object.keys(item.details).length > 0 ? (
                  <Text style={styles.details} numberOfLines={2}>{JSON.stringify(item.details)}</Text>
                ) : null}
                <Text style={styles.time}>{new Date(item.created_at).toLocaleString()}</Text>
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No audit entries yet</Text>}
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
  row: { flexDirection: "row", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 12, marginBottom: 8, gap: 12 },
  iconBox: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  action: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  who: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  target: { fontSize: 11, color: colors.primary, marginTop: 2, fontFamily: "monospace" },
  details: { fontSize: 11, color: colors.textMuted, marginTop: 4, fontStyle: "italic" },
  time: { fontSize: 10, color: colors.textMuted, marginTop: 4 },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
});
