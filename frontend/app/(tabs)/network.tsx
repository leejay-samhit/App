import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

type Node = {
  id: string;
  name: string;
  email: string;
  referral_code: string;
  registration_paid: boolean;
  direct_referrals_count: number;
  created_at?: string;
  children: Node[];
};

export default function NetworkScreen() {
  const { user } = useAuth();
  const [tree, setTree] = useState<Node[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/users/me/network?depth=4");
      setTree(data.children || []);
    } catch {}
    finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <Text style={styles.overline}>YOUR DOWNLINE</Text>
        <Text style={styles.h1}>Referral tree</Text>
        <Text style={styles.subtitle}>The 1+4 network you've built so far.</Text>

        <View style={styles.rootCard}>
          <View style={styles.rootAvatar}><Text style={styles.rootAvatarText}>{(user?.name || "U").charAt(0).toUpperCase()}</Text></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.rootName}>{user?.name} (You)</Text>
            <Text style={styles.rootCode}>{user?.referral_code}</Text>
          </View>
          <View style={styles.rootBadge}>
            <Text style={styles.rootBadgeText}>{tree.length}/4</Text>
          </View>
        </View>

        {tree.length === 0 ? (
          <View style={styles.emptyCard}>
            <Feather name="git-branch" size={32} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>No referrals yet</Text>
            <Text style={styles.emptyText}>Share your code to start building your network.</Text>
          </View>
        ) : (
          <View style={styles.treeWrap}>
            {tree.map((node, idx) => (
              <TreeNode key={node.id} node={node} level={0} isLast={idx === tree.length - 1} />
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function TreeNode({ node, level }: { node: Node; level: number; isLast?: boolean }) {
  const [expanded, setExpanded] = useState(level < 1);
  const hasChildren = node.children && node.children.length > 0;
  return (
    <View style={[styles.nodeWrap, { marginLeft: level === 0 ? 0 : 16, borderLeftWidth: level === 0 ? 0 : 2, borderLeftColor: colors.border, paddingLeft: level === 0 ? 0 : 16 }]}>
      <TouchableOpacity
        style={styles.nodeCard}
        onPress={() => setExpanded((v) => !v)}
        disabled={!hasChildren}
        testID={`tree-node-${node.id}`}
      >
        <View style={[styles.dot, { backgroundColor: node.registration_paid ? colors.success : colors.warning }]} />
        <View style={{ flex: 1 }}>
          <Text style={styles.nodeName}>{node.name}</Text>
          <Text style={styles.nodeMeta}>{node.referral_code} · {node.direct_referrals_count} direct{node.direct_referrals_count === 1 ? "" : "s"}</Text>
        </View>
        {hasChildren && (
          <Feather name={expanded ? "chevron-down" : "chevron-right"} size={18} color={colors.textMuted} />
        )}
      </TouchableOpacity>
      {expanded && hasChildren && (
        <View style={{ marginTop: 8 }}>
          {node.children.map((child, idx) => (
            <TreeNode key={child.id} node={child} level={level + 1} isLast={idx === node.children.length - 1} />
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  subtitle: { fontSize: 14, color: colors.textMuted, marginTop: 6, marginBottom: 24 },
  rootCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.primary, borderRadius: radii.card, padding: 18, marginBottom: 20 },
  rootAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.15)", alignItems: "center", justifyContent: "center", marginRight: 12 },
  rootAvatarText: { color: colors.primaryFg, fontWeight: "700", fontSize: 16 },
  rootName: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
  rootCode: { color: "rgba(255,255,255,0.7)", fontSize: 12, letterSpacing: 1, marginTop: 2 },
  rootBadge: { backgroundColor: colors.accent, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 99 },
  rootBadgeText: { color: colors.accentFg, fontSize: 12, fontWeight: "800" },
  emptyCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 32, alignItems: "center" },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.textMuted, marginTop: 4, textAlign: "center" },
  treeWrap: { gap: 8 },
  nodeWrap: { marginBottom: 4 },
  nodeCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14 },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: 10 },
  nodeName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  nodeMeta: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
});
