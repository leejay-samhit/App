/**
 * Admin · Users Tree
 *
 * Visualises the referral matrix as a collapsible hierarchy. Admin can:
 *   - See the entire downline starting from the seed admin (root)
 *   - Tap any node to expand/collapse its children
 *   - Search by name / email / referral code (auto-expands matching path)
 *   - Tap "View lineage" on any user to see who's above (upline) and below
 *     (direct downline) in a focused side-sheet.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type TreeNode = {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  admin_role?: string | null;
  referral_code: string;
  referred_by: string | null;
  registration_paid: boolean;
  approval_status: "pending" | "approved" | "rejected";
  is_blocked: boolean;
  direct_referrals_count: number;
  wallet_balance: number;
  total_earned: number;
  level: number;
  created_at: string;
  children: TreeNode[];
};

type Lineage = {
  user: TreeNode;
  upline: TreeNode[];
  downline: TreeNode[];
  downline_count: number;
};

const LEVEL_COLORS = [
  "#7C3AED", // L0 root - violet
  "#2563EB", // L1 - blue
  "#0891B2", // L2 - cyan
  "#059669", // L3 - emerald
  "#65A30D", // L4 - lime
  "#CA8A04", // L5 - amber
  "#EA580C", // L6 - orange
  "#DC2626", // L7 - red
  "#DB2777", // L8 - pink
  "#9333EA", // L9 - purple
  "#475569", // L10 - slate
];
const levelColor = (lvl: number) => LEVEL_COLORS[Math.min(Math.max(lvl, 0), LEVEL_COLORS.length - 1)];

export default function AdminUsersTree() {
  const router = useRouter();
  const [roots, setRoots] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const [lineageLoading, setLineageLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ depth: number; roots: TreeNode[] }>(
        "/admin/users/tree?depth=10",
      );
      setRoots(r.data.roots || []);
      // Auto-expand the root level for first-load convenience
      const initExp: Record<string, boolean> = {};
      (r.data.roots || []).forEach((n) => { initExp[n.id] = true; });
      setExpanded((prev) => ({ ...initExp, ...prev }));
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // ----- search match logic: finds matching nodes and returns a set of ids
  // (matches + every ancestor) so the tree expands the path automatically.
  const { matchSet, ancestorSet, totalMatches } = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return { matchSet: new Set<string>(), ancestorSet: new Set<string>(), totalMatches: 0 };
    const matches = new Set<string>();
    const ancestors = new Set<string>();
    const walk = (n: TreeNode, parents: string[]) => {
      const hit =
        n.name.toLowerCase().includes(q) ||
        (n.email || "").toLowerCase().includes(q) ||
        (n.referral_code || "").toLowerCase().includes(q);
      if (hit) {
        matches.add(n.id);
        parents.forEach((p) => ancestors.add(p));
      }
      n.children.forEach((c) => walk(c, [...parents, n.id]));
    };
    roots.forEach((r) => walk(r, []));
    return { matchSet: matches, ancestorSet: ancestors, totalMatches: matches.size };
  }, [roots, search]);

  // When a search is active, force-expand the ancestor chain
  const isExpanded = (id: string) => {
    if (search.trim() && ancestorSet.has(id)) return true;
    return !!expanded[id];
  };

  const toggle = (id: string) => setExpanded((s) => ({ ...s, [id]: !s[id] }));

  const openLineage = async (uid: string) => {
    setLineageLoading(true);
    setLineage({ user: null as any, upline: [], downline: [], downline_count: 0 });
    try {
      const r = await api.get<Lineage>(`/admin/users/${uid}/lineage`);
      setLineage(r.data);
    } catch { setLineage(null); }
    finally { setLineageLoading(false); }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  // Whether to dim a node (when search active and not part of match path)
  const isDimmed = (id: string) => {
    if (!search.trim()) return false;
    return !matchSet.has(id) && !ancestorSet.has(id);
  };

  const collapseAll = () => {
    const onlyRoots: Record<string, boolean> = {};
    roots.forEach((r) => { onlyRoots[r.id] = true; });
    setExpanded(onlyRoots);
  };

  const expandAll = () => {
    const all: Record<string, boolean> = {};
    const walk = (n: TreeNode) => { all[n.id] = true; n.children.forEach(walk); };
    roots.forEach(walk);
    setExpanded(all);
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="tree-back">
            <Feather name="chevron-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Network Tree</Text>
          </View>
          <TouchableOpacity onPress={() => { setRefreshing(true); load(); }} style={styles.iconBtn} testID="tree-refresh">
            <Feather name="refresh-cw" size={16} color={colors.textMuted} />
          </TouchableOpacity>
        </View>

        <Text style={styles.helper}>
          Tap a row to expand its downline. Tap the eye icon to see a user's
          full upline chain.
        </Text>

        <View style={styles.searchWrap}>
          <Feather name="search" size={16} color={colors.textMuted} style={{ marginLeft: 12 }} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search name, email, or referral code"
            placeholderTextColor={colors.textMuted}
            style={styles.searchInput}
            autoCapitalize="none"
            testID="tree-search"
          />
          {search ? (
            <TouchableOpacity onPress={() => setSearch("")} style={{ paddingHorizontal: 10 }}>
              <Feather name="x" size={16} color={colors.textMuted} />
            </TouchableOpacity>
          ) : null}
        </View>

        <View style={styles.toolbar}>
          <TouchableOpacity onPress={expandAll} style={styles.toolBtn} testID="tree-expand-all">
            <Feather name="maximize-2" size={13} color={colors.textMain} />
            <Text style={styles.toolBtnText}>Expand all</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={collapseAll} style={styles.toolBtn} testID="tree-collapse-all">
            <Feather name="minimize-2" size={13} color={colors.textMain} />
            <Text style={styles.toolBtnText}>Collapse</Text>
          </TouchableOpacity>
          {search.trim() ? (
            <View style={styles.matchPill}>
              <Text style={styles.matchPillText}>{totalMatches} match{totalMatches === 1 ? "" : "es"}</Text>
            </View>
          ) : null}
        </View>

        {roots.length === 0 ? (
          <Text style={styles.empty}>No users to display.</Text>
        ) : (
          <View style={styles.treeBox}>
            {roots.map((r) => (
              <NodeRow
                key={r.id}
                node={r}
                isExpanded={isExpanded}
                onToggle={toggle}
                isDimmed={isDimmed}
                isMatch={(id) => matchSet.has(id)}
                onLineage={openLineage}
              />
            ))}
          </View>
        )}
      </ScrollView>

      <LineageModal
        lineage={lineage}
        loading={lineageLoading}
        onClose={() => setLineage(null)}
      />
    </SafeAreaView>
  );
}

// ===== Tree node component =====================================================

function NodeRow({
  node,
  isExpanded,
  onToggle,
  isDimmed,
  isMatch,
  onLineage,
}: {
  node: TreeNode;
  isExpanded: (id: string) => boolean;
  onToggle: (id: string) => void;
  isDimmed: (id: string) => boolean;
  isMatch: (id: string) => boolean;
  onLineage: (uid: string) => void;
}) {
  const opened = isExpanded(node.id);
  const dim = isDimmed(node.id);
  const match = isMatch(node.id);
  const hasChildren = node.children && node.children.length > 0;
  const c = levelColor(node.level);
  const isAdmin = node.role === "admin";

  return (
    <View style={{ opacity: dim ? 0.32 : 1 }}>
      <TouchableOpacity
        activeOpacity={0.7}
        onPress={() => hasChildren && onToggle(node.id)}
        style={[
          styles.nodeRow,
          {
            paddingLeft: 12 + node.level * 14,
            backgroundColor: match ? "#FFF7E6" : "transparent",
          },
        ]}
        testID={`node-${node.id}`}
      >
        {/* Level rail */}
        <View style={[styles.levelRail, { backgroundColor: c }]} />

        {/* Expand chevron */}
        <View style={styles.chevronBox}>
          {hasChildren ? (
            <Feather
              name={opened ? "chevron-down" : "chevron-right"}
              size={16}
              color={colors.textMuted}
            />
          ) : (
            <View style={{ width: 16, height: 16 }} />
          )}
        </View>

        {/* Avatar */}
        <View style={[styles.avatar, { backgroundColor: c }]}>
          <Text style={styles.avatarText}>{(node.name || "?").charAt(0).toUpperCase()}</Text>
        </View>

        {/* Body */}
        <View style={{ flex: 1 }}>
          <View style={styles.row}>
            <Text style={styles.name} numberOfLines={1}>
              {node.name || "—"}
            </Text>
            {isAdmin ? (
              <View style={styles.adminBadge}>
                <Text style={styles.adminBadgeText}>{(node.admin_role || "ADMIN").toUpperCase()}</Text>
              </View>
            ) : null}
            {node.is_blocked ? (
              <View style={[styles.adminBadge, { backgroundColor: "#FEE2E2" }]}>
                <Text style={[styles.adminBadgeText, { color: "#B91C1C" }]}>BLOCKED</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.email} numberOfLines={1}>{node.email}</Text>
          <View style={styles.metaRow}>
            <View style={[styles.levelChip, { backgroundColor: c + "22", borderColor: c + "55" }]}>
              <Text style={[styles.levelChipText, { color: c }]}>L{node.level}</Text>
            </View>
            <View style={styles.metaItem}>
              <Feather name="hash" size={11} color={colors.textMuted} />
              <Text style={styles.metaText}>{node.referral_code}</Text>
            </View>
            <View style={styles.metaItem}>
              <Feather name="users" size={11} color={colors.textMuted} />
              <Text style={styles.metaText}>{node.direct_referrals_count}</Text>
            </View>
            <View
              style={[
                styles.statusDot,
                { backgroundColor: node.registration_paid ? colors.success : colors.warning },
              ]}
            >
              <Text style={styles.statusDotText}>
                {node.registration_paid ? "PAID" : "UNPAID"}
              </Text>
            </View>
          </View>
        </View>

        {/* Right side: total earned + actions */}
        <View style={{ alignItems: "flex-end" }}>
          <Text style={styles.amount}>{formatINR(node.total_earned)}</Text>
          <TouchableOpacity
            onPress={(e) => { e.stopPropagation && e.stopPropagation(); onLineage(node.id); }}
            style={styles.lineageBtn}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            testID={`lineage-${node.id}`}
          >
            <Feather name="git-branch" size={13} color={colors.primary} />
            <Text style={styles.lineageBtnText}>Lineage</Text>
          </TouchableOpacity>
        </View>
      </TouchableOpacity>

      {/* Children */}
      {opened && hasChildren ? (
        <View>
          {node.children.map((c2) => (
            <NodeRow
              key={c2.id}
              node={c2}
              isExpanded={isExpanded}
              onToggle={onToggle}
              isDimmed={isDimmed}
              isMatch={isMatch}
              onLineage={onLineage}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

// ===== Lineage side-sheet ======================================================

function LineageModal({
  lineage,
  loading,
  onClose,
}: {
  lineage: Lineage | null;
  loading: boolean;
  onClose: () => void;
}) {
  if (!lineage && !loading) return null;
  const visible = !!lineage || loading;

  const renderUserRow = (u: TreeNode | null | undefined, kind: "up" | "down" | "self") => {
    if (!u) return null;
    const c = levelColor(u.level ?? 0);
    return (
      <View key={`${kind}-${u.id}`} style={[styles.lineageRow, kind === "self" ? styles.lineageSelf : null]}>
        <View style={[styles.avatarSm, { backgroundColor: c }]}>
          <Text style={styles.avatarSmText}>{(u.name || "?").charAt(0).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.lineageName}>{u.name}{kind === "self" ? " (this user)" : ""}</Text>
          <Text style={styles.lineageEmail} numberOfLines={1}>{u.email}</Text>
          <Text style={styles.lineageMeta}>{u.referral_code} · {u.direct_referrals_count} directs</Text>
        </View>
        <View
          style={[
            styles.statusDot,
            { backgroundColor: u.registration_paid ? colors.success : colors.warning },
          ]}
        >
          <Text style={styles.statusDotText}>{u.registration_paid ? "PAID" : "UNPAID"}</Text>
        </View>
      </View>
    );
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <TouchableOpacity activeOpacity={1} style={styles.overlay} onPress={onClose}>
        <TouchableOpacity activeOpacity={1} style={styles.sheet} onPress={() => {}}>
          <View style={styles.sheetHandle} />
          {loading || !lineage?.user ? (
            <View style={{ paddingVertical: 36, alignItems: "center" }}>
              <ActivityIndicator color={colors.primary} />
            </View>
          ) : (
            <ScrollView contentContainerStyle={{ paddingBottom: 24 }} showsVerticalScrollIndicator={false}>
              <Text style={styles.sheetTitle}>Lineage</Text>
              <Text style={styles.sheetSub}>
                Who's above (sponsors / upline) and below (direct downline) for{" "}
                <Text style={{ fontWeight: "800", color: colors.textMain }}>
                  {lineage.user.name}
                </Text>.
              </Text>

              {/* Upline */}
              <Text style={styles.sectionLabel}>UPLINE · {lineage.upline.length} sponsor{lineage.upline.length === 1 ? "" : "s"} above</Text>
              {lineage.upline.length === 0 ? (
                <Text style={styles.emptyMini}>This user is at the root — no upline.</Text>
              ) : (
                <View>
                  {lineage.upline.map((u, i) => (
                    <View key={u.id} style={{ position: "relative" }}>
                      {renderUserRow(u, "up")}
                      {i < lineage.upline.length - 1 ? (
                        <Feather name="arrow-down" size={14} color={colors.textMuted}
                          style={{ alignSelf: "center", marginVertical: 2 }} />
                      ) : null}
                    </View>
                  ))}
                  <Feather name="arrow-down" size={14} color={colors.textMuted}
                    style={{ alignSelf: "center", marginVertical: 4 }} />
                </View>
              )}

              {/* Self */}
              {renderUserRow(lineage.user, "self")}

              {/* Downline */}
              <Text style={styles.sectionLabel}>
                DIRECT DOWNLINE · {lineage.downline_count} {lineage.downline_count === 1 ? "person" : "people"}
              </Text>
              {lineage.downline.length === 0 ? (
                <Text style={styles.emptyMini}>No directs yet.</Text>
              ) : (
                lineage.downline.map((u) => renderUserRow(u, "down"))
              )}

              <TouchableOpacity onPress={onClose} style={styles.sheetCloseBtn}>
                <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Close</Text>
              </TouchableOpacity>
            </ScrollView>
          )}
        </TouchableOpacity>
      </TouchableOpacity>
    </Modal>
  );
}

// ===== Styles ==================================================================

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.lg, paddingBottom: 60 },

  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 6 },
  backBtn: { padding: 6 },
  iconBtn: { padding: 8, borderRadius: radii.lg, backgroundColor: colors.surfaceMuted },
  overline: { fontSize: 11, fontWeight: "700", letterSpacing: 1, color: colors.textMuted },
  h1: { fontSize: 24, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  helper: { color: colors.textMuted, fontSize: 12, marginTop: 6, marginBottom: 12 },

  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.lg,
    height: 44,
    marginBottom: 10,
  },
  searchInput: { flex: 1, paddingHorizontal: 10, color: colors.textMain, fontSize: 14 },

  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  toolBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: radii.md, backgroundColor: colors.surfaceMuted,
  },
  toolBtnText: { color: colors.textMain, fontSize: 12, fontWeight: "700" },
  matchPill: {
    marginLeft: "auto",
    backgroundColor: "#FFF7E6", borderColor: "#F59E0B",
    borderWidth: 1, borderRadius: radii.full,
    paddingHorizontal: 10, paddingVertical: 4,
  },
  matchPillText: { fontSize: 11, color: "#92400E", fontWeight: "700" },

  empty: { textAlign: "center", color: colors.textMuted, paddingVertical: 30 },
  emptyMini: { color: colors.textMuted, fontSize: 13, paddingVertical: 8, paddingHorizontal: 4 },

  treeBox: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    paddingVertical: 4,
    borderWidth: 1, borderColor: colors.border,
  },
  nodeRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 10, paddingRight: 10, gap: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  levelRail: {
    width: 3, alignSelf: "stretch", borderRadius: 2, marginRight: 4,
  },
  chevronBox: { width: 18, alignItems: "center", justifyContent: "center" },
  avatar: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  avatarText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  row: { flexDirection: "row", alignItems: "center", gap: 6 },
  name: { fontSize: 15, fontWeight: "700", color: colors.textMain, flexShrink: 1 },
  email: { fontSize: 12, color: colors.textMuted, marginTop: 1 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 3 },
  metaText: { color: colors.textMuted, fontSize: 11, fontWeight: "600" },
  levelChip: {
    paddingHorizontal: 7, paddingVertical: 2,
    borderRadius: radii.full, borderWidth: 1,
  },
  levelChipText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4 },
  amount: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  statusDot: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
  statusDotText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.3 },
  adminBadge: {
    backgroundColor: "#EEF2FF", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
  adminBadgeText: { color: "#3730A3", fontSize: 9, fontWeight: "800", letterSpacing: 0.3 },
  lineageBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: 4, paddingHorizontal: 8, paddingVertical: 4,
    backgroundColor: colors.primary + "15",
    borderRadius: radii.full,
  },
  lineageBtnText: { fontSize: 11, color: colors.primary, fontWeight: "700" },

  // Lineage modal
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 18, maxHeight: "82%",
  },
  sheetHandle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, alignSelf: "center", marginBottom: 14,
  },
  sheetTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  sheetSub: { color: colors.textMuted, fontSize: 13, marginTop: 4, marginBottom: 12 },
  sectionLabel: {
    fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1,
    marginTop: 14, marginBottom: 8,
  },
  lineageRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 10,
    backgroundColor: colors.surface, borderRadius: radii.lg,
    marginBottom: 6,
    borderWidth: 1, borderColor: colors.border,
  },
  lineageSelf: {
    backgroundColor: colors.primary + "10",
    borderColor: colors.primary,
  },
  avatarSm: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
  },
  avatarSmText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  lineageName: { color: colors.textMain, fontWeight: "700", fontSize: 14 },
  lineageEmail: { color: colors.textMuted, fontSize: 11, marginTop: 1 },
  lineageMeta: { color: colors.textMuted, fontSize: 11, marginTop: 1 },
  sheetCloseBtn: {
    backgroundColor: colors.primary, paddingVertical: 12,
    borderRadius: radii.lg, alignItems: "center",
    marginTop: 16,
  },
});
