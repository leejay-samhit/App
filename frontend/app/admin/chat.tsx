// Admin → Chat. TWO groups (Sep 2026, owner request):
//
//   1. "Message users" — the normal chat list (same screen users see), so
//      the admin can still text anybody. Unchanged behaviour.
//   2. "Chat records"  — SUPER-ADMIN-ONLY read-only audit of every
//      conversation on the platform, including messages users deleted,
//      plus a .txt export for legal/court requests. No replying here.
//
// Non-super admins never see the second group and get the plain chat list.
import { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import ChatListScreen from "../(tabs)/chat";
import ChatRecords from "../../src/chat-audit";
import { useAuth } from "../../src/auth";
import { colors, spacing } from "../../src/theme";

type Group = "messages" | "records";

const GROUPS: { key: Group; label: string; icon: any }[] = [
  { key: "messages", label: "Message users", icon: "message-circle" },
  { key: "records",  label: "Chat records",  icon: "shield" },
];

export default function AdminChat() {
  const { user } = useAuth();
  const isSuperAdmin = ((user as any)?.admin_role || "super_admin") === "super_admin";
  const [group, setGroup] = useState<Group>("messages");

  if (!isSuperAdmin) return <ChatListScreen />;

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={styles.switcherSafe}>
        <View style={styles.switcher}>
          {GROUPS.map((g) => {
            const active = g.key === group;
            return (
              <TouchableOpacity
                key={g.key}
                onPress={() => setGroup(g.key)}
                style={[styles.segment, active && styles.segmentActive]}
                testID={`admin-chat-group-${g.key}`}
              >
                <Feather name={g.icon} size={14} color={active ? colors.primaryFg : colors.textMain} />
                <Text style={[styles.segmentText, active && { color: colors.primaryFg }]} numberOfLines={1}>
                  {g.label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
      </SafeAreaView>
      <View style={{ flex: 1 }}>
        {group === "messages" ? <ChatListScreen /> : <ChatRecords />}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  switcherSafe: { backgroundColor: colors.background },
  switcher: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.screen, paddingTop: 8, paddingBottom: 4 },
  segment: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 44, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  segmentActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  segmentText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
});
