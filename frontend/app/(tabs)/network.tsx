import { useCallback, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

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

/** Flatten a tree into a list with depth annotation. */
function flatten(nodes: Node[], depth = 1): Array<Node & { _depth: number }> {
  const out: Array<Node & { _depth: number }> = [];
  for (const n of nodes) {
    out.push({ ...n, _depth: depth });
    if (n.children?.length) out.push(...flatten(n.children, depth + 1));
  }
  return out;
}

export default function NetworkScreen() {
  const { user } = useAuth();
  const [tree, setTree] = useState<Node[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [listOpen, setListOpen] = useState<null | "direct" | "indirect">(null);

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

  // Counts (memoized)
  const { directList, indirectList, directCount, indirectCount } = useMemo(() => {
    const all = flatten(tree);
    const directs = all.filter((n) => n._depth === 1);
    const indirects = all.filter((n) => n._depth > 1);
    return {
      directList: directs,
      indirectList: indirects,
      directCount: directs.length,
      indirectCount: indirects.length,
    };
  }, [tree]);

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
        <GradientCard variant="emerald" style={{ marginBottom: 20, padding: 22 }}>
          <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.7)", fontWeight: "700" }}>YOUR DOWNLINE</Text>
          <Text style={{ fontSize: 28, fontWeight: "800", color: "#fff", letterSpacing: -1, marginTop: 6 }}>Referral tree</Text>
          <Text style={{ fontSize: 13, color: "rgba(255,255,255,0.85)", marginTop: 6 }}>Tap a card to view the full list.</Text>
          <View style={{ flexDirection: "row", marginTop: 16, gap: 12 }}>
            <TouchableOpacity
              onPress={() => directCount > 0 && setListOpen("direct")}
              activeOpacity={0.7}
              style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10 }}
              testID="downline-direct-card"
            >
              <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.6 }}>DIRECT JOINS</Text>
              <Text style={{ fontSize: 22, fontWeight: "800", color: "#fff", marginTop: 3 }}>{directCount}</Text>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 3, marginTop: 4 }}>
                <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>View list</Text>
                <Feather name="chevron-right" size={11} color="#fff" />
              </View>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => indirectCount > 0 && setListOpen("indirect")}
              activeOpacity={0.7}
              style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10 }}
              testID="downline-indirect-card"
            >
              <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.6 }}>INDIRECT (L2-L4)</Text>
              <Text style={{ fontSize: 22, fontWeight: "800", color: "#fff", marginTop: 3 }}>{indirectCount}</Text>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 3, marginTop: 4 }}>
                <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>View list</Text>
                <Feather name="chevron-right" size={11} color="#fff" />
              </View>
            </TouchableOpacity>
          </View>
        </GradientCard>

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

      {/* ─── List drilldown modal ─── */}
      <Modal visible={!!listOpen} transparent animationType="slide" onRequestClose={() => setListOpen(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>
                {listOpen === "direct" ? `Direct joins · ${directCount}` : `Indirect (L2-L4) · ${indirectCount}`}
              </Text>
              <TouchableOpacity onPress={() => setListOpen(null)} style={styles.modalClose}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>
            <ScrollView contentContainerStyle={{ paddingBottom: 28 }}>
              {(listOpen === "direct" ? directList : indirectList).map((n) => (
                <View key={n.id} style={styles.listRow}>
                  <View style={[styles.listDot, { backgroundColor: n.registration_paid ? colors.success : colors.warning }]} />
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.listName} numberOfLines={1}>{n.name}</Text>
                    <Text style={styles.listMeta}>{n.referral_code} · {n.direct_referrals_count} direct{n.direct_referrals_count === 1 ? "" : "s"}{listOpen === "indirect" ? ` · L${n._depth}` : ""}</Text>
                  </View>
                  <View style={[styles.listBadge, { backgroundColor: n.registration_paid ? colors.success + "22" : colors.warning + "22" }]}>
                    <Text style={[styles.listBadgeText, { color: n.registration_paid ? colors.success : colors.warning }]}>{n.registration_paid ? "PAID" : "PEND"}</Text>
                  </View>
                </View>
              ))}
              {((listOpen === "direct" ? directList : indirectList).length === 0) ? (
                <View style={styles.emptyCard}>
                  <Feather name="users" size={28} color={colors.textMuted} />
                  <Text style={styles.emptyTitle}>No {listOpen === "direct" ? "directs" : "indirects"} yet</Text>
                </View>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>
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
  // Drilldown modal
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.background, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 24, height: "82%" },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 8 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border, marginBottom: 4 },
  modalTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  modalClose: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },
  listRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 12, paddingHorizontal: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  listDot: { width: 10, height: 10, borderRadius: 5 },
  listName: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  listMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  listBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  listBadgeText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.5 },
});
