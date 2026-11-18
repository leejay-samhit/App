import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  ActivityIndicator,
  RefreshControl,
  TouchableOpacity,
  Modal,
  ScrollView,
  TextInput,
  KeyboardAvoidingView,
  Platform,
  Alert,
  Switch,
  Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { useInfiniteList } from "../../src/use-infinite-list";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { formatActiveAgo } from "../../src/location";
import { downloadText } from "../../src/download";
import { SourceTabs } from "../../src/source-tabs";

// Per-source badge styling for the roster rows + category tabs.
const SOURCE_META: Record<string, { short: string; icon: any; color: string }> = {
  razorpay:     { short: "RAZORPAY",   icon: "credit-card", color: "#0369A1" },
  upi_manual:   { short: "UPI MANUAL", icon: "smartphone",  color: "#7C3AED" },
  offline_cash: { short: "OFFLINE",    icon: "tag",         color: "#B45309" },
  unknown:      { short: "UNKNOWN",    icon: "help-circle", color: "#6B7280" },
};

// Standard registration fee — used purely to render the GST hint inside the
// admin "Add new user" modal. The actual fee comes from settings on save.
const REG_FEE_HINT = 118;

type AdminUser = {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  referral_code: string;
  referred_by: string | null;
  registration_paid: boolean;
  registration_source?: string | null;
  referral_enabled?: boolean;
  referral_switch_note?: string | null;
  referral_switch_at?: string | null;
  referral_switch_by?: string | null;
  direct_referrals_count: number;
  wallet_balance: number;
  total_earned: number;
  upi_id?: string | null;
  bank_account?: string | null;
  ifsc?: string | null;
  account_holder?: string | null;
  created_at: string;
  // Location (Phase 2 GPS)
  location_sharing?: boolean;
  location_updated_at?: string | null;
  service_location?: { type?: string; coordinates?: [number, number] } | null;
  // ─── Placement audit trail (Feb-2026) ───
  sponsor_id?: string | null;
  referral_owner_id?: string | null;
  referral_owner_code?: string | null;
  original_sponsor_id?: string | null;
  original_sponsor_code?: string | null;
  original_referral_code?: string | null;
  placement_history?: Array<{
    type: string;
    old_sponsor_id?: string | null;
    old_sponsor_code?: string | null;
    old_sponsor_email?: string | null;
    new_sponsor_id?: string | null;
    new_sponsor_code?: string | null;
    new_sponsor_email?: string | null;
    reason?: string;
    changed_by_admin_id?: string;
    changed_by_admin_email?: string;
    changed_at?: string;
  }>;
  placement_realigned_at?: string | null;
  placement_realigned_reason?: string | null;
};

type Stats = {
  total_users: number;
  paid_users: number;
  pending_payouts: number;
  total_revenue: number;
  total_referral_payouts: number;
  total_pending_withdrawals_amount?: number;
  total_completed_withdrawals_amount?: number;
};

export default function AdminUsers() {
  const router = useRouter();
  const { user: currentAdmin } = useAuth();
  const [stats, setStats] = useState<Stats | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  // Debounced search — fires the server-side ?q= filter 350ms after the
  // last keystroke so we don't slam the API on every character typed.
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(id);
  }, [search]);

  // Phase 1 Session C — infinite scrolling for the user roster.
  // Server-side `q` re-evaluates the result set whenever the debounced
  // search changes; the hook auto-resets to page 0 on each new key.
  // Join-source category tab (June-2026): razorpay / upi_manual /
  // offline_cash / unpaid — resolved server-side so the counts are true DB
  // figures, not "whatever happened to be on the loaded page".
  const [sourceTab, setSourceTab] = useState<string>("all");
  const [sourceCounts, setSourceCounts] = useState<Record<string, number> | null>(null);
  const [exporting, setExporting] = useState(false);

  const list = useInfiniteList<AdminUser>("/admin/users", {
    pageSize: 20,
    params: {
      ...(debouncedSearch ? { q: debouncedSearch } : {}),
      ...(sourceTab !== "all" ? { source: sourceTab } : {}),
    },
  });
  const users = list.items;          // <-- alias so existing JSX keeps reading `users`
  const filtered = users;            // server-side filtering — client filter no longer needed
  const loading = list.loading;

  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AdminUser | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const canCreate = ["super_admin", "manager", "support"].includes(
    (currentAdmin as any)?.admin_role || "super_admin",
  );

  const load = useCallback(async () => {
    // Stats is one small object — keep a separate /admin/stats fetch.
    // The user roster reload is owned by useInfiniteList.
    try {
      const s = await api.get<Stats>("/admin/stats");
      setStats(s.data);
    } catch { /* stats are nice-to-have */ }
    try {
      const c = await api.get<Record<string, number>>("/admin/users/source-counts");
      setSourceCounts(c.data);
    } catch { /* counts are nice-to-have */ }
    await list.reload();
    setRefreshing(false);
  }, [list]);

  useFocusEffect(useCallback(() => { load(); /* eslint-disable-next-line */ }, []));

  // Aug-2026 — only two account types exist. "Legacy" only appears while
  // historical UPI-manual / offline joinings still exist in the DB.
  const sourceTabsData = [
    { key: "all",            label: "All",            icon: "users" as any,       count: sourceCounts?.all },
    { key: "subscriber",     label: "Subscribers",    icon: "award" as any,       count: sourceCounts?.subscriber },
    { key: "non_subscriber", label: "No subscription", icon: "clock" as any,      count: sourceCounts?.non_subscriber },
    { key: "legacy",         label: "Legacy",         icon: "archive" as any,     count: sourceCounts?.legacy },
  ].filter((t) => t.key !== "legacy" || !!(sourceCounts?.legacy && sourceCounts.legacy > 0));

  const onDownloadUsers = async () => {
    setExporting(true);
    try {
      const res = await api.get("/admin/export/users", {
        params: sourceTab !== "all" ? { source: sourceTab } : {},
        responseType: "text",
      });
      const csv = typeof res.data === "string" ? res.data : "";
      const stamp = new Date().toISOString().slice(0, 10);
      const out = await downloadText({
        filename: `users-${sourceTab}-${stamp}.csv`,
        content: "\uFEFF" + csv,
        mimeType: "text/csv",
      });
      if (out.ok) {
        const lines = Math.max(0, csv.trim().split("\n").length - 1);
        Alert.alert(
          "Download ready",
          `${lines} user${lines === 1 ? "" : "s"} exported.${out.method === "browser" ? "\n\nCheck your browser's Downloads folder." : ""}`,
        );
      }
    } catch {
      Alert.alert("Download failed", "Please try again.");
    } finally {
      setExporting(false);
    }
  };

  if (loading && users.length === 0) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <FlatList
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        ListHeaderComponent={
          <View>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Users</Text>
            {stats && (
              <View style={styles.statsGrid}>
                <Stat
                  label="Total users"
                  value={String(stats.total_users)}
                  hint="View approvals"
                  onPress={() => router.push("/admin/approvals" as any)}
                  testID="stat-total-users"
                />
                <Stat
                  label="Settled"
                  value={formatINR(stats.total_completed_withdrawals_amount || 0)}
                  hint="View payouts"
                  onPress={() => router.push("/admin/payouts?tab=success" as any)}
                  testID="stat-settled"
                />
                <Stat
                  label="Revenue"
                  value={formatINR(stats.total_revenue)}
                  hint="Registration fees"
                  onPress={() => router.push("/admin/transactions?type=registration_fee" as any)}
                  testID="stat-revenue"
                />
                <Stat
                  label="Withdrawal pending"
                  value={formatINR(stats.total_pending_withdrawals_amount || 0)}
                  hint="Open payouts"
                  onPress={() => router.push("/admin/payouts?tab=pending" as any)}
                  testID="stat-pending-withdrawals"
                />
              </View>
            )}
            {canCreate && (
              <TouchableOpacity onPress={() => setCreateOpen(true)} style={styles.newUserBtn} testID="admin-user-new">
                <Feather name="user-plus" size={16} color={colors.primaryFg} />
                <Text style={styles.newUserBtnText}>  Add new user</Text>
              </TouchableOpacity>
            )}
            <SourceTabs
              tabs={sourceTabsData}
              value={sourceTab}
              onChange={setSourceTab}
              testIDPrefix="users-source"
            />
            <View style={styles.searchRow}>
              <View style={styles.searchWrap}>
                <Feather name="search" size={16} color={colors.textMuted} style={{ marginLeft: 12 }} />
                <TextInput
                  value={search}
                  onChangeText={setSearch}
                  placeholder="Search by name, email or code"
                  placeholderTextColor={colors.textMuted}
                  style={styles.searchInput}
                  testID="admin-users-search"
                />
              </View>
              <TouchableOpacity
                onPress={onDownloadUsers}
                disabled={exporting}
                style={styles.downloadBtn}
                testID="admin-users-download"
              >
                {exporting ? <ActivityIndicator color={colors.primaryFg} size="small" /> : (
                  <>
                    <Feather name="download" size={14} color={colors.primaryFg} />
                    <Text style={styles.downloadBtnText}>CSV</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
            <Text style={styles.sectionLabel}>
              {filtered.length} USER{filtered.length === 1 ? "" : "S"}
              {debouncedSearch ? ` · matching “${debouncedSearch}”` : ""}
              {list.loading ? " · loading…" : ""}
            </Text>
          </View>
        }
        data={filtered}
        keyExtractor={(u) => u.id}
        onEndReached={list.loadMore}
        onEndReachedThreshold={0.5}
        ListFooterComponent={list.loadingMore ? (
          <View style={{ paddingVertical: 16, alignItems: "center" }}>
            <ActivityIndicator color={colors.primary} size="small" />
          </View>
        ) : (!list.hasMore && filtered.length > 0 ? (
          <Text style={{ textAlign: "center", color: colors.textMuted, paddingVertical: 12, fontSize: 12 }}>
            End of list · {filtered.length} loaded
          </Text>
        ) : null)}
        renderItem={({ item }) => (
          <TouchableOpacity onPress={() => setEditing(item)} style={styles.userRow} testID={`admin-user-${item.id}`}>
            <View style={styles.avatar}><Text style={styles.avatarText}>{item.name.charAt(0).toUpperCase()}</Text></View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={styles.userName}>{item.name}</Text>
                {item.role === "admin" && <View style={styles.adminBadge}><Text style={styles.adminBadgeText}>ADMIN</Text></View>}
              </View>
              <Text style={styles.userEmail}>{item.email}</Text>
              <View style={styles.userMeta}>
                <Feather name="hash" size={11} color={colors.textMuted} />
                <Text style={styles.userMetaText}>{item.referral_code}</Text>
                <Feather name="users" size={11} color={colors.textMuted} style={{ marginLeft: 8 }} />
                <Text style={styles.userMetaText}>{item.direct_referrals_count} directs</Text>
              </View>
              {item.registration_paid ? (() => {
                const m = SOURCE_META[item.registration_source || "unknown"] || SOURCE_META.unknown;
                return (
                  <View style={[styles.srcBadge, { backgroundColor: m.color + "18", borderColor: m.color + "44" }]}>
                    <Feather name={m.icon} size={9} color={m.color} />
                    <Text style={[styles.srcBadgeText, { color: m.color }]}>{m.short}</Text>
                  </View>
                );
              })() : null}
              {item.location_sharing && item.service_location?.coordinates ? (
                <TouchableOpacity
                  onPress={(e) => {
                    e.stopPropagation && e.stopPropagation();
                    const [lng, lat] = item.service_location!.coordinates!;
                    const url = `https://www.google.com/maps?q=${lat},${lng}`;
                    if (Platform.OS === "web") {
                      // open in new tab
                      try { (globalThis as any).open?.(url, "_blank"); } catch {}
                    } else {
                      Linking.openURL(url);
                    }
                  }}
                  style={styles.locChip}
                >
                  <Feather name="navigation" size={10} color="#047857" />
                  <Text style={styles.locChipText}>
                    {" "}{item.service_location.coordinates[1].toFixed(3)}, {item.service_location.coordinates[0].toFixed(3)}
                    {item.location_updated_at ? `  ·  ${formatActiveAgo(item.location_updated_at)}` : ""}
                  </Text>
                  <Feather name="external-link" size={10} color="#047857" style={{ marginLeft: 4 }} />
                </TouchableOpacity>
              ) : null}
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={styles.userAmount}>{formatINR(item.total_earned)}</Text>
              {(item as any).is_blocked ? (
                <View style={[styles.statusDot, { backgroundColor: colors.error }]}>
                  <Text style={styles.statusDotText}>LOCKED</Text>
                </View>
              ) : null}
            </View>
            <Feather name="chevron-right" size={16} color={colors.textMuted} style={{ marginLeft: 4 }} />
          </TouchableOpacity>
        )}
        ListEmptyComponent={<Text style={styles.empty}>No users match</Text>}
      />

      <UserEditModal
        user={editing}
        currentAdminId={currentAdmin?.id}
        onClose={() => setEditing(null)}
        onSaved={async () => { setEditing(null); await load(); }}
        onRequestDelete={(u) => {
          // Close edit modal first, THEN open the confirmation as a clean
          // sibling Modal so it portals to body root and renders cleanly on web.
          setEditing(null);
          setTimeout(() => setPendingDelete(u), 250);
        }}
      />

      <DeleteConfirmModal
        user={pendingDelete}
        onClose={() => setPendingDelete(null)}
        onDeleted={async () => { setPendingDelete(null); await load(); }}
      />

      <NewUserModal
        visible={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={async () => { setCreateOpen(false); await load(); }}
      />
    </SafeAreaView>
  );
}

function NewUserModal({ visible, onClose, onCreated }: { visible: boolean; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [sponsor, setSponsor] = useState("");

  const [saving, setSaving] = useState(false);

  const reset = () => {
    setName(""); setEmail(""); setPhone(""); setPassword(""); setSponsor("");

  };

  const onSubmit = async () => {
    if (!name.trim() || !email.trim() || password.length < 6) {
      Alert.alert("Missing fields", "Name, email, and a 6+ char password are required.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/admin/users/create", {
        name: name.trim(),
        email: email.trim().toLowerCase(),
        password,
        phone: phone.trim() || undefined,
        referral_code: sponsor.trim().toUpperCase() || undefined,
        mark_paid_offline: false,
      });
      Alert.alert(
        "User created",
        "Account created as a Non-subscriber. They can sign in and shop now, and activate the ₹118 subscription from inside the app.",
      );
      reset();
      onCreated();
    } catch (e) {
      Alert.alert("Create failed", formatApiError(e));
    } finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={nuStyles.overlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={nuStyles.sheet}>
          <Text style={nuStyles.title}>Add new user</Text>
          <Text style={nuStyles.sub}>Create a user account on behalf of a customer. They start as a Non-subscriber and can activate the ₹118 subscription in the app.</Text>
          <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 460 }}>
            <Text style={nuStyles.fieldLabel}>Full name</Text>
            <TextInput value={name} onChangeText={setName} placeholder="e.g. Aman Verma" placeholderTextColor={colors.textMuted} style={nuStyles.input} testID="new-user-name" />
            <Text style={nuStyles.fieldLabel}>Email</Text>
            <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="user@email.com" placeholderTextColor={colors.textMuted} style={nuStyles.input} testID="new-user-email" />
            <Text style={nuStyles.fieldLabel}>Password (min 6 chars)</Text>
            <TextInput value={password} onChangeText={setPassword} secureTextEntry placeholder="Temporary password" placeholderTextColor={colors.textMuted} style={nuStyles.input} testID="new-user-password" />
            <Text style={nuStyles.fieldLabel}>Phone (optional)</Text>
            <TextInput value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="+91 ..." placeholderTextColor={colors.textMuted} style={nuStyles.input} testID="new-user-phone" />
            <Text style={nuStyles.fieldLabel}>Sponsor referral code (optional)</Text>
            <TextInput value={sponsor} onChangeText={(v) => setSponsor(v.toUpperCase())} autoCapitalize="characters" placeholder="e.g. NET5XY9Z" placeholderTextColor={colors.textMuted} style={[nuStyles.input, { letterSpacing: 1 }]} testID="new-user-sponsor" />
            <View style={nuStyles.infoRow}>
              <Feather name="info" size={14} color={colors.primary} />
              <Text style={nuStyles.infoText}>
                The account is created as a <Text style={{ fontWeight: "900" }}>Non-subscriber</Text>.
                They can sign in and shop right away, and activate the ₹{REG_FEE_HINT} subscription
                themselves from Shop, Dashboard or Profile — so every rupee of revenue and GST comes
                from a real Razorpay collection.
              </Text>
            </View>
          </ScrollView>
          <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
            <TouchableOpacity onPress={() => { reset(); onClose(); }} style={[nuStyles.btn, { backgroundColor: colors.surfaceMuted }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onSubmit} disabled={saving} style={[nuStyles.btn, { backgroundColor: colors.primary }, saving && { opacity: 0.5 }]} testID="new-user-submit">
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Create user</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const nuStyles = StyleSheet.create({
  infoRow: { flexDirection: "row", gap: 10, alignItems: "flex-start", backgroundColor: colors.brand100, borderRadius: 12, padding: 12, marginTop: 12 },
  infoText: { flex: 1, fontSize: 11.5, color: colors.textMain, lineHeight: 17 },
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  sub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 12, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 16, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  switchTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  switchSub: { fontSize: 11, color: colors.textMuted, marginTop: 4, lineHeight: 16 },
  sourceBlock: {
    marginTop: 4,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  sourceRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10 },
  sourceChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.primary + "44",
    backgroundColor: colors.primary + "0A",
  },
  sourceChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  sourceChipText: { fontSize: 12, fontWeight: "700", color: colors.primary },
  btn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
  // Absolute overlay rendered inside the parent's SafeAreaView. Always opaque, always covers the parent.
  confirmOverlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.75)", justifyContent: "center", alignItems: "center", padding: 18, zIndex: 9999, ...(Platform.OS === "web" ? ({ position: "fixed" } as any) : {}) },
  // Centered card (was a bottom-sheet — center is more reliable on small viewports + form sheets)
  confirmCard: { width: "100%", maxWidth: 420, backgroundColor: colors.surface, borderRadius: 22, padding: 22, shadowColor: "#000", shadowOffset: { width: 0, height: 12 }, shadowOpacity: 0.35, shadowRadius: 28, elevation: 30 },
  confirmIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: "#FCE9E5", alignItems: "center", justifyContent: "center", alignSelf: "center", marginBottom: 12 },
  confirmTitle: { fontSize: 19, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  confirmBody: { fontSize: 13, color: colors.textMuted, marginTop: 10, marginBottom: 14, lineHeight: 20, textAlign: "center" },
  confirmInput: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 17, color: colors.textMain, fontWeight: "800", letterSpacing: 6, textAlign: "center", borderWidth: 1.5, borderColor: colors.border },
});

function UserEditModal({ user, currentAdminId, onClose, onSaved, onRequestDelete }: { user: AdminUser | null; currentAdminId?: string; onClose: () => void; onSaved: () => void; onRequestDelete: (u: AdminUser) => void }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [walletBalance, setWalletBalance] = useState("");
  const [registrationPaid, setRegistrationPaid] = useState(true);
  const [upi, setUpi] = useState("");
  const [bank, setBank] = useState("");
  const [ifsc, setIfsc] = useState("");
  const [holder, setHolder] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [adjustAmount, setAdjustAmount] = useState("");
  const [adjustPot, setAdjustPot] = useState<"wallet_balance" | "vendor_earnings" | "dp_cash_in_hand">("wallet_balance");
  const [adjustReason, setAdjustReason] = useState("");
  // ─── Placement realignment state ───
  const [realignCode, setRealignCode] = useState("");
  const [realignReason, setRealignReason] = useState("");
  const [showPlacementHistory, setShowPlacementHistory] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  // ── Admin Approved (referral payments) switch — note is mandatory ───
  const [referralEnabled, setReferralEnabled] = useState(false);
  const [pendingReferral, setPendingReferral] = useState<boolean | null>(null);
  const [referralNote, setReferralNote] = useState("");
  const [referralBusy, setReferralBusy] = useState(false);
  // Password reveal / reset (super admin only, audited server-side).
  // MUST stay above the `if (!user) return null` bail-out below — declaring
  // these after it made the hook count change between renders and crashed
  // the screen ("Rendered more hooks than during the previous render") the
  // moment an admin tapped a user row.
  const [shownPassword, setShownPassword] = useState<string | null>(null);
  const [pwNote, setPwNote] = useState("");
  const [pwBusy, setPwBusy] = useState<"" | "show" | "reset">("");
  // Jun 2026 — wallet credits are funded from COMPANY NET WORTH (the
  // Direct-Added / UTR deposit route was removed), so the admin needs to see
  // how much the company actually has before handing money out.
  const [netWorth, setNetWorth] = useState<number | null>(null);
  useEffect(() => {
    if (!user) { setNetWorth(null); return; }
    let alive = true;
    api.get<{ master: { net_worth: number } }>("/admin/finance/net-worth")
      .then(({ data }) => { if (alive) setNetWorth(Number(data?.master?.net_worth ?? 0)); })
      .catch(() => { if (alive) setNetWorth(null); });
    return () => { alive = false; };
  }, [user?.id]);

  // Reset form when user changes
  if (user && (name === "" || email === "" || (user.email !== email && msg === ""))) {
    // initialize on first open per user
  }

  const init = (u: AdminUser) => {
    setName(u.name);
    setEmail(u.email);
    setPhone(u.phone || "");
    setRole((u.role as any) || "user");
    setWalletBalance(String(u.wallet_balance ?? 0));
    setRegistrationPaid(!!u.registration_paid);
    setReferralEnabled(!!u.referral_enabled);
    setPendingReferral(null);
    setReferralNote("");
    setUpi(u.upi_id || "");
    setBank(u.bank_account || "");
    setIfsc(u.ifsc || "");
    setHolder(u.account_holder || "");
    setNewPassword("");
    setMsg("");
    setShownPassword(null);
    setPwNote("");
  };

  // initialize once when user becomes set
  const [initFor, setInitFor] = useState<string | null>(null);
  if (user && initFor !== user.id) {
    init(user);
    setInitFor(user.id);
  }
  if (!user && initFor !== null) setInitFor(null);

  if (!user) return null;

  const onSave = async () => {
    setMsg("");
    setSaving(true);
    try {
      const payload: any = {
        name: name.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        role,
        // wallet_balance is INTENTIONALLY OMITTED — it can only be changed via
        // the credit/debit endpoint which goes through the System Wallet.
        upi_id: upi.trim() || undefined,
        bank_account: bank.trim() || undefined,
        ifsc: ifsc.trim() || undefined,
        account_holder: holder.trim() || undefined,
      };
      // strip undefined
      Object.keys(payload).forEach((k) => payload[k] === undefined && delete payload[k]);
      await api.patch(`/admin/users/${user.id}`, payload);
      onSaved();
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const submitReferralSwitch = async () => {
    if (pendingReferral === null) return;
    if (referralNote.trim().length < 3) {
      setMsg("Please write a short note (minimum 3 characters).");
      return;
    }
    setReferralBusy(true);
    try {
      const { data } = await api.post(`/admin/users/${user.id}/referral-approval`, {
        enabled: pendingReferral,
        note: referralNote.trim(),
      });
      setReferralEnabled(!!data.referral_enabled);
      const cb = data?.clawback;
      Alert.alert(
        pendingReferral ? "Referral payments ON" : "Referral payments OFF",
        pendingReferral
          ? (data.commissions_triggered
              ? "The upline cascade has been credited."
              : (data.reason || "Payouts start once the member subscribes."))
          : `No future commission will be paid.${cb?.clawed_back_count ? `\n\nClawed back ₹${cb.clawed_back_amount} from ${cb.clawed_back_count} upline${cb.clawed_back_count === 1 ? "" : "s"}.` : ""}`,
      );
      setPendingReferral(null);
      setReferralNote("");
      onSaved();
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setReferralBusy(false);
    }
  };

  const onResetPassword = async () => {
    if (newPassword.length < 6) {
      setMsg("Password must be at least 6 characters");
      return;
    }
    setBusy("reset");
    try {
      await api.post(`/admin/users/${user.id}/reset-password`, { new_password: newPassword });
      setNewPassword("");
      setMsg("Password reset successfully");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const onDelete = () => {
    if (!user) return;
    onRequestDelete(user);
  };

  // Password reveal / reset (super admin only, audited server-side).
  const revealPassword = async () => {
    setPwBusy("show"); setPwNote("");
    try {
      const { data } = await api.get<any>(`/admin/users/${user.id}/password`);
      setShownPassword(data.password);
    } catch (e: any) {
      setShownPassword(null);
      setPwNote(formatApiError(e));
    } finally { setPwBusy(""); }
  };

  const resetPassword = async () => {
    setPwBusy("reset"); setPwNote("");
    try {
      const { data } = await api.post<any>(`/admin/users/${user.id}/password/reset-reveal`, {});
      setShownPassword(data.password);
      setPwNote("New password set — share it with the user.");
    } catch (e: any) {
      setPwNote(formatApiError(e));
    } finally { setPwBusy(""); }
  };

  const isSelf = currentAdminId === user.id;

  return (
    <Modal visible animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={modalStyles.safe} edges={["top"]}>
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
          <View style={modalStyles.header}>
            <TouchableOpacity onPress={onClose} style={modalStyles.iconBtn} testID="user-edit-close">
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={modalStyles.title}>Edit user</Text>
            <View style={{ width: 40 }} />
          </View>

          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
            <View style={modalStyles.codePill}>
              <Text style={modalStyles.codePillLabel}>REFERRAL CODE</Text>
              <Text style={modalStyles.codePillValue}>{user.referral_code}</Text>
            </View>

            <Text style={modalStyles.section}>BASIC DETAILS</Text>
            <Field label="Name"><TextInput testID="edit-name" value={name} onChangeText={setName} style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>
            <Field label="Email"><TextInput testID="edit-email" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none" style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>
            <Field label="Phone"><TextInput testID="edit-phone" value={phone} onChangeText={setPhone} keyboardType="phone-pad" style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>

            {/* ── Sep 2026 — PASSWORD (owner request) ──────────────────
                Logins stay bcrypt-hashed; a super admin can read the
                password back because we also keep an encrypted copy from the
                moment it is set. Accounts whose password predates this get a
                clear message and the one-tap reset instead. */}
            <Text style={modalStyles.section}>PASSWORD</Text>
            <View style={modalStyles.pwCard}>
              {shownPassword ? (
                <View style={modalStyles.pwRow}>
                  <Text style={modalStyles.pwValue} selectable testID="edit-password-value">{shownPassword}</Text>
                  <TouchableOpacity onPress={() => setShownPassword(null)} style={modalStyles.pwHide}>
                    <Feather name="eye-off" size={15} color={colors.textMuted} />
                  </TouchableOpacity>
                </View>
              ) : (
                <Text style={modalStyles.labelHint}>
                  {pwNote || "Hidden. Tap “Show password” to reveal it, or set a new one and share it with the user."}
                </Text>
              )}
              <View style={modalStyles.pwBtnRow}>
                <TouchableOpacity
                  onPress={revealPassword}
                  disabled={pwBusy !== ""}
                  style={[modalStyles.pwBtn, pwBusy !== "" && { opacity: 0.5 }]}
                  testID="edit-password-show"
                >
                  {pwBusy === "show" ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="eye" size={14} color={colors.primary} />}
                  <Text style={modalStyles.pwBtnText}>Show password</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={resetPassword}
                  disabled={pwBusy !== ""}
                  style={[modalStyles.pwBtn, modalStyles.pwBtnSolid, pwBusy !== "" && { opacity: 0.5 }]}
                  testID="edit-password-reset"
                >
                  {pwBusy === "reset" ? <ActivityIndicator size="small" color="#fff" /> : <Feather name="refresh-cw" size={14} color="#fff" />}
                  <Text style={[modalStyles.pwBtnText, { color: "#fff" }]}>Reset &amp; reveal</Text>
                </TouchableOpacity>
              </View>
            </View>

            <Text style={modalStyles.section}>ROLE & STATUS</Text>
            <View style={modalStyles.row}>
              <Text style={modalStyles.label}>Admin role</Text>
              <Switch
                value={role === "admin"}
                onValueChange={(v) => setRole(v ? "admin" : "user")}
                disabled={isSelf}
                testID="edit-role-switch"
              />
            </View>
            <View style={modalStyles.row}>
              <Text style={modalStyles.label}>Paid status</Text>
              <View
                style={[
                  modalStyles.paidPill,
                  { backgroundColor: registrationPaid ? colors.success + "1A" : colors.warning + "1A",
                    borderColor: registrationPaid ? colors.success + "55" : colors.warning + "55" },
                ]}
                testID="edit-paid-status"
              >
                <Feather
                  name={registrationPaid ? "check-circle" : "x-circle"}
                  size={12}
                  color={registrationPaid ? colors.success : colors.warning}
                />
                <Text style={[modalStyles.paidPillText, { color: registrationPaid ? colors.success : colors.warning }]}>
                  {registrationPaid ? `₹${REG_FEE_HINT} PAID` : "NO — not paid"}
                </Text>
              </View>
            </View>
            <View style={[modalStyles.row, { alignItems: "flex-start" }]}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={modalStyles.label}>Admin Approved · referral payments</Text>
                <Text style={modalStyles.labelHint}>
                  ON = referral commissions are credited to this member&apos;s upline.
                  OFF = refund done — commissions already paid are clawed back and no future
                  payment is made. A note is required for every change. Paid status is never
                  affected.
                </Text>
                {user.referral_switch_note ? (
                  <Text style={modalStyles.switchNote} testID="edit-referral-note">
                    Last note: “{user.referral_switch_note}”
                    {user.referral_switch_at ? ` · ${new Date(user.referral_switch_at).toLocaleDateString()}` : ""}
                    {user.referral_switch_by ? ` · ${user.referral_switch_by}` : ""}
                  </Text>
                ) : null}
              </View>
              <Switch
                value={!!referralEnabled}
                onValueChange={(v) => { setPendingReferral(v); setReferralNote(""); }}
                testID="edit-referral-switch"
              />
            </View>
            <Field label="Wallet balance (read-only)">
              <View style={[modalStyles.input, { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.surfaceMuted, opacity: 0.85 }]} testID="edit-wallet-readonly">
                <Text style={{ fontSize: 16, fontWeight: "800", color: colors.textMain }}>₹{Number(walletBalance || 0).toLocaleString("en-IN")}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Feather name="lock" size={12} color={colors.textMuted} />
                  <Text style={{ fontSize: 10, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.5 }}>READ-ONLY</Text>
                </View>
              </View>
              <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 6, lineHeight: 16 }}>
                Wallet balance can&apos;t be edited directly. Use <Text style={{ fontWeight: "800", color: colors.primary }}>Wallet adjust ⤵</Text> below to credit/debit — a credit is paid out of <Text style={{ fontWeight: "800", color: colors.primary }}>Company Net Worth</Text> and a debit returns the money to it.
              </Text>
            </Field>

            <Text style={modalStyles.section}>PLACEMENT & UPLINE</Text>
            <View style={modalStyles.placementCard}>
              <View style={modalStyles.placementRow}>
                <Text style={modalStyles.placementLabel}>Signed up with code</Text>
                <Text style={modalStyles.placementValue}>{user.original_referral_code || user.referred_by || "—"}</Text>
              </View>
              <View style={modalStyles.placementRow}>
                <Text style={modalStyles.placementLabel}>Original upline</Text>
                <Text style={modalStyles.placementValue}>{user.original_sponsor_code || user.referred_by || "—"}</Text>
              </View>
              <View style={modalStyles.placementRow}>
                <Text style={modalStyles.placementLabel}>Current upline</Text>
                <Text style={[modalStyles.placementValue, { color: colors.primary }]}>{user.referred_by || "—"}</Text>
              </View>
              <View style={modalStyles.placementRow}>
                <Text style={modalStyles.placementLabel}>Commission owner</Text>
                <Text style={modalStyles.placementValue}>{user.referral_owner_code || "—"}</Text>
              </View>
              {user.placement_realigned_at ? (
                <View style={[modalStyles.placementRealigned]}>
                  <Feather name="alert-circle" size={12} color="#B85F00" />
                  <View style={{ flex: 1 }}>
                    <Text style={modalStyles.placementRealignedTitle}>Realigned {new Date(user.placement_realigned_at).toLocaleDateString()}</Text>
                    <Text style={modalStyles.placementRealignedReason}>Reason: {user.placement_realigned_reason || "—"}</Text>
                  </View>
                </View>
              ) : null}
              {(user.placement_history || []).length > 0 ? (
                <>
                  <TouchableOpacity onPress={() => setShowPlacementHistory((v) => !v)} style={modalStyles.placementHistoryToggle}>
                    <Feather name={showPlacementHistory ? "chevron-up" : "chevron-down"} size={12} color={colors.primary} />
                    <Text style={modalStyles.placementHistoryToggleText}>
                      {showPlacementHistory ? "Hide" : "Show"} placement history ({(user.placement_history || []).length})
                    </Text>
                  </TouchableOpacity>
                  {showPlacementHistory ? (
                    <View style={{ marginTop: 6 }}>
                      {(user.placement_history || []).map((h, i) => (
                        <View key={i} style={modalStyles.placementHistoryRow}>
                          <Text style={modalStyles.placementHistoryDate}>{h.changed_at ? new Date(h.changed_at).toLocaleString() : "—"}</Text>
                          <Text style={modalStyles.placementHistoryMove}>
                            {h.old_sponsor_code || "—"} → <Text style={{ color: colors.primary, fontWeight: "800" }}>{h.new_sponsor_code || "—"}</Text>
                          </Text>
                          <Text style={modalStyles.placementHistoryReason}>Reason: {h.reason || "—"}</Text>
                          {h.changed_by_admin_email ? (
                            <Text style={modalStyles.placementHistoryBy}>by {h.changed_by_admin_email}</Text>
                          ) : null}
                        </View>
                      ))}
                    </View>
                  ) : null}
                </>
              ) : null}
              <Text style={modalStyles.placementHint}>Move user to new upline (no money recalculation):</Text>
              <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                <View style={{ flex: 1 }}>
                  <TextInput
                    placeholder="New sponsor code (e.g. 7RKOZM)"
                    value={realignCode}
                    onChangeText={(t) => setRealignCode(t.toUpperCase())}
                    autoCapitalize="characters"
                    style={modalStyles.input}
                    placeholderTextColor={colors.textMuted}
                    testID="realign-code"
                  />
                </View>
              </View>
              <TextInput
                placeholder="Reason for realignment (required)"
                value={realignReason}
                onChangeText={setRealignReason}
                style={[modalStyles.input, { marginTop: 6, minHeight: 50, textAlignVertical: "top" }]}
                placeholderTextColor={colors.textMuted}
                multiline
                testID="realign-reason"
              />
              <TouchableOpacity
                onPress={async () => {
                  if (!realignCode.trim()) { setMsg("Enter new sponsor code"); return; }
                  if (realignReason.trim().length < 3) { setMsg("Reason must be at least 3 chars"); return; }
                  setBusy("realign");
                  try {
                    await api.post(`/admin/users/${user.id}/realign`, {
                      new_sponsor_code: realignCode.trim().toUpperCase(),
                      reason: realignReason.trim(),
                    });
                    setRealignCode(""); setRealignReason("");
                    Alert.alert("Realigned", "User placement updated successfully.");
                    onSaved();
                  } catch (e) { setMsg(formatApiError(e)); setBusy(null); }
                }}
                disabled={busy === "realign"}
                style={[modalStyles.realignBtn, busy === "realign" && { opacity: 0.5 }]}
                testID="realign-submit"
              >
                <Feather name="git-pull-request" size={14} color="#fff" />
                <Text style={modalStyles.realignBtnText}>{busy === "realign" ? "Realigning…" : "Realign placement"}</Text>
              </TouchableOpacity>
            </View>

            <Text style={modalStyles.section}>PAYOUT DETAILS</Text>
            <Field label="UPI ID"><TextInput testID="edit-upi" value={upi} onChangeText={setUpi} autoCapitalize="none" style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>
            <Field label="Bank account"><TextInput testID="edit-bank" value={bank} onChangeText={setBank} keyboardType="numeric" style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>
            <Field label="IFSC"><TextInput testID="edit-ifsc" value={ifsc} onChangeText={(t) => setIfsc(t.toUpperCase())} autoCapitalize="characters" style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>
            <Field label="Account holder"><TextInput testID="edit-holder" value={holder} onChangeText={setHolder} style={modalStyles.input} placeholderTextColor={colors.textMuted} /></Field>

            <Text style={modalStyles.section}>QUICK ACTIONS</Text>
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 12 }}>
              <TouchableOpacity
                onPress={async () => {
                  setBusy("block");
                  try {
                    if (user.role === "admin" && (user as any).is_blocked !== true) {
                      Alert.alert("Cannot block admin", "Demote to user first.");
                      setBusy(null); return;
                    }
                    if ((user as any).is_blocked) {
                      await api.post(`/admin/users/${user.id}/unblock`);
                    } else {
                      await api.post(`/admin/users/${user.id}/block`, { reason: "Blocked by admin" });
                    }
                    onSaved();
                  } catch (e) { setMsg(formatApiError(e)); setBusy(null); }
                }}
                disabled={isSelf || busy === "block"}
                style={[modalStyles.qaBtn, (isSelf || busy === "block") && { opacity: 0.5 }]}
                testID="edit-block-toggle"
              >
                <Feather name={(user as any).is_blocked ? "user-check" : "user-x"} size={14} color={(user as any).is_blocked ? colors.success : "#B3261E"} />
                <Text style={[modalStyles.qaBtnText, { color: (user as any).is_blocked ? colors.success : "#B3261E" }]}>
                  {(user as any).is_blocked ? "Unblock" : "Block"}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={async () => {
                  setBusy("freeze");
                  try {
                    await api.post(`/admin/users/${user.id}/wallet/freeze`);
                    onSaved();
                  } catch (e) { setMsg(formatApiError(e)); setBusy(null); }
                }}
                disabled={busy === "freeze"}
                style={[modalStyles.qaBtn, busy === "freeze" && { opacity: 0.5 }]}
                testID="edit-freeze-toggle"
              >
                <Feather name={(user as any).wallet_frozen ? "unlock" : "lock"} size={14} color={colors.primary} />
                <Text style={modalStyles.qaBtnText}>{(user as any).wallet_frozen ? "Unfreeze" : "Freeze"} wallet</Text>
              </TouchableOpacity>
            </View>

            <Text style={modalStyles.section}>WALLET ADJUST</Text>
            {/* Oct-2026 — a seller's money lives in shop earnings and a
                rider's in cash-in-hand. Neither was shown here, so every
                debit on them failed with "Cannot debit beyond available
                balance". All three pots are now visible and selectable. */}
            <View style={{ flexDirection: "row", gap: 6, marginBottom: 10 }}>
              {([
                { key: "wallet_balance",  label: "Wallet",         value: Number((user as any).wallet_balance || 0) },
                { key: "vendor_earnings", label: "Shop earnings",  value: Number((user as any).vendor_earnings || 0) },
                { key: "dp_cash_in_hand", label: "Rider cash",    value: Number((user as any).dp_cash_in_hand || 0) },
              ] as const).map((p) => {
                const on = adjustPot === p.key;
                return (
                  <TouchableOpacity
                    key={p.key}
                    onPress={() => setAdjustPot(p.key)}
                    style={{
                      flex: 1, paddingVertical: 9, paddingHorizontal: 8, borderRadius: 10,
                      borderWidth: 1,
                      borderColor: on ? colors.primary : colors.border,
                      backgroundColor: on ? colors.brand100 : colors.surface,
                      alignItems: "center",
                    }}
                    testID={`adjust-pot-${p.key}`}
                  >
                    <Text style={{ fontSize: 9.5, fontWeight: "900", letterSpacing: 0.3, color: on ? colors.primary : colors.textMuted }}>
                      {p.label.toUpperCase()}
                    </Text>
                    <Text style={{ fontSize: 13, fontWeight: "900", color: on ? colors.textMain : colors.textMuted, marginTop: 2 }}>
                      ₹{p.value.toLocaleString("en-IN")}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>
            <View style={{ backgroundColor: colors.surfaceMuted, borderRadius: 12, padding: 10, marginBottom: 10, flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Feather name="briefcase" size={13} color={colors.primary} />
              <Text style={{ fontSize: 11.5, color: colors.textMuted, fontWeight: "600", flex: 1, lineHeight: 16 }} testID="adjust-networth-note">
                Funded from <Text style={{ fontWeight: "800", color: colors.textMain }}>Company Net Worth</Text>
                {netWorth != null
                  ? (netWorth < 0
                      ? ` · overdrawn by ₹${Math.abs(netWorth).toLocaleString("en-IN")}`
                      : ` · available ₹${netWorth.toLocaleString("en-IN")}`)
                  : ""}
              </Text>
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 8 }}>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 11, color: colors.textMuted, fontWeight: "600", marginBottom: 4 }}>Amount (₹)</Text>
                <TextInput testID="edit-adjust-amount" value={adjustAmount} onChangeText={setAdjustAmount} keyboardType="numeric" style={modalStyles.input} placeholderTextColor={colors.textMuted} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 11, color: colors.textMuted, fontWeight: "600", marginBottom: 4 }}>Reason</Text>
                <TextInput testID="edit-adjust-reason" value={adjustReason} onChangeText={setAdjustReason} style={modalStyles.input} placeholder="e.g. Bonus" placeholderTextColor={colors.textMuted} />
              </View>
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 16 }}>
              <TouchableOpacity
                onPress={async () => {
                  if (!adjustAmount || !adjustReason) { setMsg("Enter amount and reason"); return; }
                  setBusy("credit");
                  try {
                    await api.post(`/admin/users/${user.id}/wallet`, { amount: parseFloat(adjustAmount), type: "credit", reason: adjustReason, wallet: adjustPot });
                    setAdjustAmount(""); setAdjustReason("");
                    onSaved();
                  } catch (e) { setMsg(formatApiError(e)); setBusy(null); }
                }}
                disabled={busy === "credit"}
                style={[modalStyles.qaBtn, { borderColor: colors.success }, busy === "credit" && { opacity: 0.5 }]}
                testID="edit-credit"
              >
                <Feather name="plus-circle" size={14} color={colors.success} />
                <Text style={[modalStyles.qaBtnText, { color: colors.success }]}>Credit</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={async () => {
                  if (!adjustAmount || !adjustReason) { setMsg("Enter amount and reason"); return; }
                  setBusy("debit");
                  try {
                    await api.post(`/admin/users/${user.id}/wallet`, { amount: parseFloat(adjustAmount), type: "debit", reason: adjustReason, wallet: adjustPot });
                    setAdjustAmount(""); setAdjustReason("");
                    onSaved();
                  } catch (e) { setMsg(formatApiError(e)); setBusy(null); }
                }}
                disabled={busy === "debit"}
                style={[modalStyles.qaBtn, { borderColor: "#B3261E" }, busy === "debit" && { opacity: 0.5 }]}
                testID="edit-debit"
              >
                <Feather name="minus-circle" size={14} color="#B3261E" />
                <Text style={[modalStyles.qaBtnText, { color: "#B3261E" }]}>Debit</Text>
              </TouchableOpacity>
            </View>

            <Text style={modalStyles.section}>KYC STATUS</Text>
            <View style={modalStyles.kycRow}>
              <View style={[modalStyles.kycPill, { backgroundColor: (user as any).kyc_status === "approved" ? colors.success : (user as any).kyc_status === "rejected" ? "#B3261E" : (user as any).kyc_status === "pending" ? colors.warning : colors.textMuted }]}>
                <Text style={modalStyles.kycPillText}>{((user as any).kyc_status || "none").toUpperCase()}</Text>
              </View>
              <Text style={modalStyles.kycName}>{(user as any).kyc_full_name || "Not submitted"}</Text>
            </View>
            {(user as any).kyc_status === "pending" && (
              <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                <TouchableOpacity
                  onPress={async () => { setBusy("kyc-approve"); try { await api.post(`/admin/kyc/${user.id}/approve`); onSaved(); } catch (e) { setMsg(formatApiError(e)); setBusy(null); } }}
                  disabled={busy === "kyc-approve"}
                  style={[modalStyles.qaBtn, busy === "kyc-approve" && { opacity: 0.5 }]}
                  testID="edit-kyc-approve"
                >
                  <Feather name="check" size={14} color={colors.primary} />
                  <Text style={modalStyles.qaBtnText}>Approve KYC</Text>
                </TouchableOpacity>
              </View>
            )}

            <Text style={modalStyles.section}>RESET PASSWORD</Text>
            <Field label="New password (min 6 chars)">
              <TextInput
                testID="edit-new-password"
                value={newPassword}
                onChangeText={setNewPassword}
                secureTextEntry
                style={modalStyles.input}
                placeholder="Set a new password"
                placeholderTextColor={colors.textMuted}
              />
            </Field>
            <TouchableOpacity
              onPress={onResetPassword}
              disabled={!newPassword || busy === "reset"}
              style={[modalStyles.secondaryBtn, (!newPassword || busy === "reset") && { opacity: 0.5 }]}
              testID="edit-reset-password"
            >
              {busy === "reset" ? <ActivityIndicator color={colors.primary} /> : (
                <>
                  <Feather name="key" size={14} color={colors.primary} />
                  <Text style={modalStyles.secondaryBtnText}>Reset password</Text>
                </>
              )}
            </TouchableOpacity>

            {msg ? (
              <Text style={[modalStyles.msg, { color: msg.includes("success") ? colors.success : "#B3261E" }]} testID="edit-msg">{msg}</Text>
            ) : null}

            <TouchableOpacity onPress={onSave} disabled={saving} style={[modalStyles.saveBtn, saving && { opacity: 0.7 }]} testID="edit-save">
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : (
                <>
                  <Feather name="save" size={16} color={colors.primaryFg} />
                  <Text style={modalStyles.saveBtnText}>Save changes</Text>
                </>
              )}
            </TouchableOpacity>

            <TouchableOpacity
              onPress={onDelete}
              disabled={isSelf || busy === "delete"}
              style={[modalStyles.deleteBtn, (isSelf || busy === "delete") && { opacity: 0.5 }]}
              testID="edit-delete"
            >
              <Feather name="trash-2" size={14} color="#B3261E" />
              <Text style={modalStyles.deleteBtnText}>{isSelf ? "Cannot delete yourself" : "Delete user"}</Text>
            </TouchableOpacity>
          </ScrollView>
        </KeyboardAvoidingView>

        {/* Mandatory note before the Admin Approved switch is applied */}
        <Modal
          visible={pendingReferral !== null}
          transparent
          animationType="fade"
          statusBarTranslucent
          onRequestClose={() => setPendingReferral(null)}
        >
          <View style={modalStyles.noteOverlay}>
            <View style={modalStyles.noteSheet}>
              <Text style={modalStyles.noteTitle}>
                {pendingReferral ? "Turn referral payments ON" : "Turn referral payments OFF"}
              </Text>
              <Text style={modalStyles.noteBody}>
                {pendingReferral
                  ? "The upline cascade will be credited for this member. Write why you are enabling it — the note is saved with your name and appears in the Users CSV."
                  : "This is treated as REFUND DONE: commissions already paid for this member are clawed back and no future commission is paid. Paid status stays unchanged. Write the reason — it is saved with your name and appears in the Users CSV."}
              </Text>
              <TextInput
                value={referralNote}
                onChangeText={setReferralNote}
                placeholder={pendingReferral ? "e.g. Razorpay payment verified — enable payouts" : "e.g. Refund paid back to customer on 12 Sep"}
                placeholderTextColor={colors.textMuted}
                multiline
                maxLength={500}
                style={modalStyles.noteInput}
                testID="referral-note-input"
              />
              <View style={modalStyles.noteRow}>
                <TouchableOpacity
                  onPress={() => { setPendingReferral(null); setReferralNote(""); }}
                  style={[modalStyles.noteBtn, { backgroundColor: colors.surfaceMuted }]}
                  testID="referral-note-cancel"
                >
                  <Text style={{ color: colors.textMain, fontWeight: "800" }}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={submitReferralSwitch}
                  disabled={referralBusy || referralNote.trim().length < 3}
                  style={[
                    modalStyles.noteBtn,
                    { backgroundColor: pendingReferral ? colors.primary : "#B3261E" },
                    (referralBusy || referralNote.trim().length < 3) && { opacity: 0.5 },
                  ]}
                  testID="referral-note-submit"
                >
                  {referralBusy ? <ActivityIndicator color="#fff" /> : (
                    <Text style={{ color: "#fff", fontWeight: "800" }}>
                      {pendingReferral ? "Enable payments" : "Disable & claw back"}
                    </Text>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </Modal>
  );
}

// Standalone top-level confirmation Modal — rendered by the parent screen, NOT
// nested inside the Edit modal. This avoids the RN-Web stacking-context bug
// where a parent Modal's transform animation traps `position:fixed` overlays
// (causing the "popup not clearly visible / overlap" issue).
function DeleteConfirmModal({ user, onClose, onDeleted }: { user: AdminUser | null; onClose: () => void; onDeleted: () => Promise<void> | void }) {
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const reset = () => { setConfirmText(""); setErr(null); setBusy(false); };
  const handleClose = () => { reset(); onClose(); };

  const handleDelete = async () => {
    if (!user) return;
    setBusy(true); setErr(null);
    try {
      const res = await api.delete(`/admin/users/${user.id}`);
      const data: any = res.data || {};
      const summary = data.cascade || {};
      const total = Object.values(summary).reduce((a: number, b: any) => a + (Number(b) || 0), 0);
      const snapId = data.snapshot_id ? String(data.snapshot_id).slice(0, 8) : null;
      reset();
      const msg = `User deleted${total ? ` · ${total} related records cleaned up` : ""}.${snapId ? `\n\nAuto-backup taken (#${snapId}). Restore from Admin → Data Backups if needed.` : ""}`;
      if (Platform.OS === "web") {
        (typeof window !== "undefined" ? window.alert : Alert.alert)(msg);
      } else {
        Alert.alert("User deleted", msg);
      }
      await onDeleted();
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
    }
  };

  // role tag for header (User / Admin / Finance / Support)
  const roleTag = (() => {
    if (!user) return "";
    if (user.role !== "admin") return "User";
    const ar = (user as any).admin_role || "admin";
    if (ar === "super_admin") return "Super Admin";
    if (ar === "finance") return "Finance Admin";
    if (ar === "support") return "Support Admin";
    if (ar === "manager") return "Manager Admin";
    return "Admin";
  })();

  return (
    <Modal
      visible={!!user}
      transparent
      animationType="fade"
      statusBarTranslucent
      onRequestClose={handleClose}
    >
      <View style={dcStyles.backdrop}>
        <TouchableOpacity activeOpacity={1} style={StyleSheet.absoluteFillObject} onPress={() => !busy && handleClose()} />
        <View style={dcStyles.card}>
          <View style={dcStyles.icon}>
            <Feather name="alert-triangle" size={26} color="#B3261E" />
          </View>
          <Text style={dcStyles.tag}>{roleTag.toUpperCase()}</Text>
          <Text style={dcStyles.title}>Delete {user?.name || "user"}?</Text>
          <Text style={dcStyles.body}>
            This will permanently delete the account and clean up all related records: cart, notifications, withdrawals,
            service bookings, vendor &amp; service applications, tickets, registrations, and downline sponsor links.{"\n\n"}
            Their <Text style={{ fontWeight: "800" }}>transactions and orders are kept</Text> for audit.{"\n\n"}
            <Text style={{ fontWeight: "800", color: colors.success }}>An automatic backup is taken first</Text> — restore from
            <Text style={{ fontWeight: "800" }}> Admin → Data Backups</Text> if needed.{"\n\n"}
            Type <Text style={{ fontWeight: "800", color: "#B3261E" }}>DELETE</Text> to confirm.
          </Text>
          <TextInput
            value={confirmText}
            onChangeText={(v) => { setErr(null); setConfirmText(v.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 6)); }}
            placeholder="DELETE"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="characters"
            style={dcStyles.input}
            testID="delete-confirm-input"
            editable={!busy}
          />
          {err && (
            <View style={dcStyles.errBox}>
              <Feather name="x-circle" size={16} color="#B3261E" />
              <Text style={dcStyles.errText}>{err}</Text>
            </View>
          )}
          <View style={dcStyles.btnRow}>
            <TouchableOpacity onPress={handleClose} disabled={busy} style={[dcStyles.btn, { backgroundColor: colors.surfaceMuted }]} testID="delete-confirm-cancel">
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={handleDelete}
              disabled={confirmText !== "DELETE" || busy}
              style={[dcStyles.btn, { backgroundColor: "#B3261E" }, (confirmText !== "DELETE" || busy) && { opacity: 0.5 }]}
              testID="delete-confirm-go"
            >
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Delete user</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const dcStyles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", justifyContent: "center", alignItems: "center", padding: 18 },
  card: { width: "100%", maxWidth: 420, backgroundColor: colors.surface, borderRadius: 22, padding: 22, shadowColor: "#000", shadowOffset: { width: 0, height: 12 }, shadowOpacity: 0.35, shadowRadius: 28, elevation: 30 },
  icon: { width: 56, height: 56, borderRadius: 28, backgroundColor: "#FCE9E5", alignItems: "center", justifyContent: "center", alignSelf: "center", marginBottom: 12 },
  tag: { fontSize: 10, fontWeight: "800", color: "#B3261E", letterSpacing: 1.5, textAlign: "center", marginBottom: 4 },
  title: { fontSize: 19, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  body: { fontSize: 13, color: colors.textMuted, marginTop: 10, marginBottom: 14, lineHeight: 20, textAlign: "center" },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 17, color: colors.textMain, fontWeight: "800", letterSpacing: 6, textAlign: "center", borderWidth: 1.5, borderColor: colors.border },
  errBox: { flexDirection: "row", alignItems: "center", backgroundColor: "#FCE9E5", padding: 10, borderRadius: 10, marginTop: 10, gap: 8 },
  errText: { color: "#B3261E", fontSize: 12, fontWeight: "700", flex: 1 },
  btnRow: { flexDirection: "row", gap: 10, marginTop: 14 },
  btn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ fontSize: 12, color: colors.textMuted, fontWeight: "600", marginBottom: 6 }}>{label}</Text>
      {children}
    </View>
  );
}

function Stat({ label, value, hint, onPress, testID }: {
  label: string;
  value: string;
  hint?: string;
  onPress?: () => void;
  testID?: string;
}) {
  const body = (
    <>
      <Text style={styles.statValue} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
      {onPress ? (
        <View style={styles.statHintRow}>
          <Text style={styles.statHint}>{hint || "Open"}</Text>
          <Feather name="chevron-right" size={11} color={colors.primary} />
        </View>
      ) : null}
    </>
  );
  if (onPress) {
    return (
      <TouchableOpacity
        onPress={onPress}
        activeOpacity={0.7}
        style={[styles.statCard, styles.statCardTappable]}
        testID={testID}
      >
        {body}
      </TouchableOpacity>
    );
  }
  return <View style={styles.statCard} testID={testID}>{body}</View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 20 },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 20 },
  statCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 14 },
  statCardTappable: { borderColor: colors.primary + "40" },
  statValue: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  statLabel: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  statHintRow: { flexDirection: "row", alignItems: "center", gap: 2, marginTop: 6 },
  statHint: { fontSize: 10, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  searchRow: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginBottom: 16 },
  downloadBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 14, minHeight: 44, borderRadius: 12, backgroundColor: colors.primary },
  downloadBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  srcBadge: { flexDirection: "row", alignItems: "center", alignSelf: "flex-start", gap: 4, marginTop: 4, paddingHorizontal: 7, paddingVertical: 2, borderRadius: 6, borderWidth: 1 },
  srcBadgeText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.5 },
  searchWrap: { flex: 1, flexDirection: "row", alignItems: "center", minHeight: 44, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, gap: 8 },
  newUserBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14, marginBottom: 16 },
  newUserBtnText: { color: colors.primaryFg, fontSize: 14, fontWeight: "800" },
  treeBtn: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.primary + "10",
    borderRadius: radii.lg,
    paddingVertical: 12, paddingHorizontal: 14,
    marginBottom: 14,
    borderWidth: 1, borderColor: colors.primary + "33",
  },
  treeBtnText: { color: colors.primary, fontSize: 13, fontWeight: "700" },
  searchInput: { flex: 1, paddingVertical: 12, paddingHorizontal: 8, fontSize: 14, color: colors.textMain },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  userRow: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 12, marginBottom: 10, gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.primary, fontWeight: "800" },
  userName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  adminBadge: { backgroundColor: colors.accent, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  adminBadgeText: { color: colors.accentFg, fontSize: 9, fontWeight: "800" },
  userEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  userMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  userMetaText: { fontSize: 11, color: colors.textMuted },
  locChip: {
    flexDirection: "row", alignItems: "center",
    alignSelf: "flex-start",
    backgroundColor: "#ECFDF5",
    borderWidth: 1, borderColor: "#A7F3D0",
    paddingHorizontal: 6, paddingVertical: 3,
    borderRadius: 8,
    marginTop: 4,
  },
  locChipText: { fontSize: 10, color: "#047857", fontWeight: "700" },
  userAmount: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  statusDot: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, marginTop: 4 },
  statusDotText: { color: colors.primaryFg, fontSize: 9, fontWeight: "800" },
  empty: { padding: 24, textAlign: "center", color: colors.textMuted },
});

const modalStyles = StyleSheet.create({
  pwCard: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 12, gap: 10, marginBottom: 8,
  },
  pwRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  pwValue: {
    flex: 1, fontSize: 16, fontWeight: "800", color: colors.textMain,
    letterSpacing: 1, backgroundColor: colors.surfaceMuted,
    paddingVertical: 10, paddingHorizontal: 12, borderRadius: 10,
  },
  pwHide: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  pwBtnRow: { flexDirection: "row", gap: 8 },
  pwBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 44, borderRadius: radii.button, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceMuted,
  },
  pwBtnSolid: { backgroundColor: colors.primary, borderColor: colors.primary },
  pwBtnText: { fontSize: 12.5, fontWeight: "800", color: colors.primary },
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  codePill: { backgroundColor: colors.primary, padding: 14, borderRadius: 16, marginBottom: 24, alignItems: "center" },
  codePillLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 2, fontWeight: "700" },
  codePillValue: { color: colors.primaryFg, fontSize: 24, fontWeight: "800", letterSpacing: 3, marginTop: 4 },
  section: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: 8, marginBottom: 10 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 10, paddingHorizontal: 4 },
  label: { fontSize: 14, color: colors.textMain, fontWeight: "600" },
  labelHint: { fontSize: 11, color: colors.textMuted, marginTop: 4, lineHeight: 16 },
  paidPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1 },
  paidPillText: { fontSize: 11, fontWeight: "900", letterSpacing: 0.3 },
  switchNote: { fontSize: 11, color: colors.primary, marginTop: 6, fontStyle: "italic", lineHeight: 16 },
  noteOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", padding: 24 },
  noteSheet: { width: "100%", maxWidth: 440, backgroundColor: colors.surface, borderRadius: 22, padding: 20 },
  noteTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  noteBody: { fontSize: 12.5, color: colors.textMuted, marginTop: 6, lineHeight: 18 },
  noteInput: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain, minHeight: 90, textAlignVertical: "top", marginTop: 14 },
  noteRow: { flexDirection: "row", gap: 10, marginTop: 14 },
  noteBtn: { flex: 1, minHeight: 48, borderRadius: radii.button, alignItems: "center", justifyContent: "center" },
  msg: { fontSize: 13, marginTop: 12, textAlign: "center" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 14, borderRadius: radii.button, marginTop: 16 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
  secondaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand100, paddingVertical: 12, borderRadius: radii.button, marginTop: 6 },
  secondaryBtnText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  qaBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 99, borderWidth: 1, borderColor: colors.primary },
  qaBtnText: { fontSize: 12, fontWeight: "700", color: colors.primary },
  kycRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8 },
  kycPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  kycPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  kycName: { fontSize: 14, color: colors.textMain, fontWeight: "600", flex: 1 },
  deleteBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 14, borderRadius: radii.button, marginTop: 12, borderWidth: 1, borderColor: "#B3261E" },
  deleteBtnText: { color: "#B3261E", fontWeight: "700", fontSize: 14 },
  // Placement / realignment section
  placementCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 10 },
  placementRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  placementLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  placementValue: { fontSize: 13, color: colors.textMain, fontWeight: "800", fontVariant: ["tabular-nums"] },
  placementRealigned: { flexDirection: "row", alignItems: "flex-start", gap: 8, backgroundColor: "#FFF7E6", borderWidth: 1, borderColor: "#B85F0044", borderRadius: 10, padding: 10, marginTop: 10 },
  placementRealignedTitle: { fontSize: 12, fontWeight: "800", color: "#B85F00" },
  placementRealignedReason: { fontSize: 11, color: "#7A4A00", marginTop: 2 },
  placementHistoryToggle: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 8, paddingVertical: 6 },
  placementHistoryToggleText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  placementHistoryRow: { backgroundColor: colors.surfaceMuted, borderRadius: 8, padding: 8, marginBottom: 6 },
  placementHistoryDate: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  placementHistoryMove: { fontSize: 12, color: colors.textMain, marginTop: 2, fontWeight: "700" },
  placementHistoryReason: { fontSize: 11, color: colors.textMain, marginTop: 2 },
  placementHistoryBy: { fontSize: 10, color: colors.textMuted, marginTop: 2, fontStyle: "italic" },
  placementHint: { fontSize: 11, color: colors.textMuted, marginTop: 12, fontStyle: "italic" },
  realignBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: "#7C3AED", paddingVertical: 12, borderRadius: radii.button, marginTop: 8 },
  realignBtnText: { color: "#fff", fontWeight: "800", fontSize: 13, letterSpacing: 0.3 },
});
