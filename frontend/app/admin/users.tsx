import { useCallback, useState } from "react";
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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type AdminUser = {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  referral_code: string;
  referred_by: string | null;
  registration_paid: boolean;
  direct_referrals_count: number;
  wallet_balance: number;
  total_earned: number;
  upi_id?: string | null;
  bank_account?: string | null;
  ifsc?: string | null;
  account_holder?: string | null;
  created_at: string;
};

type Stats = {
  total_users: number;
  paid_users: number;
  pending_payouts: number;
  total_revenue: number;
  total_referral_payouts: number;
};

export default function AdminUsers() {
  const { user: currentAdmin } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const canCreate = ["super_admin", "manager", "support"].includes(
    (currentAdmin as any)?.admin_role || "super_admin",
  );

  const load = useCallback(async () => {
    try {
      const [u, s] = await Promise.all([api.get<AdminUser[]>("/admin/users"), api.get<Stats>("/admin/stats")]);
      setUsers(u.data);
      setStats(s.data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const filtered = search.trim()
    ? users.filter((u) => {
        const q = search.toLowerCase();
        return u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || u.referral_code.toLowerCase().includes(q);
      })
    : users;

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

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
                <Stat label="Total users" value={String(stats.total_users)} />
                <Stat label="Paid" value={String(stats.paid_users)} />
                <Stat label="Revenue" value={formatINR(stats.total_revenue)} />
                <Stat label="Payouts paid" value={formatINR(stats.total_referral_payouts)} />
              </View>
            )}
            {canCreate && (
              <TouchableOpacity onPress={() => setCreateOpen(true)} style={styles.newUserBtn} testID="admin-user-new">
                <Feather name="user-plus" size={16} color={colors.primaryFg} />
                <Text style={styles.newUserBtnText}>  Add new user (offline-paid)</Text>
              </TouchableOpacity>
            )}
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
            <Text style={styles.sectionLabel}>{filtered.length} USERS</Text>
          </View>
        }
        data={filtered}
        keyExtractor={(u) => u.id}
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
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={styles.userAmount}>{formatINR(item.total_earned)}</Text>
              <View style={[styles.statusDot, { backgroundColor: item.registration_paid ? colors.success : colors.warning }]}>
                <Text style={styles.statusDotText}>{item.registration_paid ? "PAID" : "UNPAID"}</Text>
              </View>
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
  const [markPaid, setMarkPaid] = useState(true);
  const [saving, setSaving] = useState(false);

  const reset = () => { setName(""); setEmail(""); setPhone(""); setPassword(""); setSponsor(""); setMarkPaid(true); };

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
        mark_paid_offline: markPaid,
      });
      Alert.alert("User created", markPaid
        ? "Account created and marked as paid. It now awaits finance approval."
        : "Account created — awaiting payment + finance approval.");
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
          <Text style={nuStyles.sub}>Create a user account on behalf of a customer. The account will route to finance for approval.</Text>
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
            <View style={nuStyles.switchRow}>
              <View style={{ flex: 1 }}>
                <Text style={nuStyles.switchTitle}>Mark registration fee as paid (offline)</Text>
                <Text style={nuStyles.switchSub}>Turn ON if the customer has paid in cash / other channels. Turn OFF if they'll pay via the app.</Text>
              </View>
              <Switch value={markPaid} onValueChange={setMarkPaid} testID="new-user-mark-paid" />
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
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  sub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 12, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 16, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  switchTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  switchSub: { fontSize: 11, color: colors.textMuted, marginTop: 4, lineHeight: 16 },
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

function UserEditModal({ user, currentAdminId, onClose, onSaved }: { user: AdminUser | null; currentAdminId?: string; onClose: () => void; onSaved: () => void }) {
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
  const [adjustReason, setAdjustReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

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
    setUpi(u.upi_id || "");
    setBank(u.bank_account || "");
    setIfsc(u.ifsc || "");
    setHolder(u.account_holder || "");
    setNewPassword("");
    setMsg("");
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
        wallet_balance: walletBalance ? parseFloat(walletBalance) : undefined,
        registration_paid: registrationPaid,
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
    setMsg("");
    setDeleteConfirmText("");
    setConfirmDelete(true);
  };

  const performDelete = async () => {
    setBusy("delete");
    setMsg("");
    try {
      const res = await api.delete(`/admin/users/${user.id}`);
      const data: any = res.data || {};
      const summary = data.cascade || {};
      const total = Object.values(summary).reduce((a: number, b: any) => a + (Number(b) || 0), 0);
      const snapId = data.snapshot_id ? String(data.snapshot_id).slice(0, 8) : null;
      setConfirmDelete(false);
      setDeleteConfirmText("");
      setTimeout(() => {
        const msg = `User deleted${total ? ` · ${total} related records cleaned up` : ""}.${snapId ? `\n\nAuto-backup taken (#${snapId}). Restore from Admin → Data Backups if needed.` : ""}`;
        if (Platform.OS === "web") {
          (typeof window !== "undefined" ? window.alert : Alert.alert)(msg);
        } else {
          Alert.alert("User deleted", msg);
        }
        onSaved();
      }, 50);
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setBusy(null);
    }
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
              <Text style={modalStyles.label}>Registration paid</Text>
              <Switch
                value={registrationPaid}
                onValueChange={setRegistrationPaid}
                testID="edit-paid-switch"
              />
            </View>
            <Field label="Wallet balance (₹)">
              <TextInput
                testID="edit-wallet"
                value={walletBalance}
                onChangeText={setWalletBalance}
                keyboardType="numeric"
                style={modalStyles.input}
                placeholderTextColor={colors.textMuted}
              />
            </Field>

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
                    await api.post(`/admin/users/${user.id}/wallet`, { amount: parseFloat(adjustAmount), type: "credit", reason: adjustReason });
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
                    await api.post(`/admin/users/${user.id}/wallet`, { amount: parseFloat(adjustAmount), type: "debit", reason: adjustReason });
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

        {/* In-app delete confirmation — absolute overlay inside the parent (no nested Modal — that has RN-Web stacking quirks). Always opaque, always on top. */}
        {confirmDelete && (
          <View style={modalStyles.confirmOverlay} pointerEvents="auto">
            <TouchableOpacity activeOpacity={1} style={StyleSheet.absoluteFillObject} onPress={() => !busy && setConfirmDelete(false)} />
            <View style={modalStyles.confirmCard}>
              <View style={modalStyles.confirmIcon}>
                <Feather name="alert-triangle" size={26} color="#B3261E" />
              </View>
              <Text style={modalStyles.confirmTitle}>Delete {user.name}?</Text>
              <Text style={modalStyles.confirmBody}>
                This will permanently delete the user account and clean up all related records: cart, notifications,
                withdrawals, service bookings, vendor &amp; service applications, tickets, registrations, and downline
                sponsor links.{"\n\n"}
                Their <Text style={{ fontWeight: "800" }}>transactions and orders are kept</Text> for audit.{"\n\n"}
                <Text style={{ fontWeight: "800", color: colors.success }}>An automatic backup is taken first</Text> — restore from
                <Text style={{ fontWeight: "800" }}> Admin → Data Backups</Text> if needed.{"\n\n"}
                Type <Text style={{ fontWeight: "800", color: "#B3261E" }}>DELETE</Text> to confirm.
              </Text>
              <TextInput
                value={deleteConfirmText}
                onChangeText={(v) => setDeleteConfirmText(v.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 6))}
                placeholder="DELETE"
                placeholderTextColor={colors.textMuted}
                autoCapitalize="characters"
                style={modalStyles.confirmInput}
                testID="delete-confirm-input"
              />
              {!!msg && (
                <View style={{ flexDirection: "row", alignItems: "center", backgroundColor: "#FCE9E5", padding: 10, borderRadius: 10, marginTop: 10, gap: 8 }}>
                  <Feather name="x-circle" size={16} color="#B3261E" />
                  <Text style={{ color: "#B3261E", fontSize: 12, fontWeight: "700", flex: 1 }}>{msg}</Text>
                </View>
              )}
              <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
                <TouchableOpacity onPress={() => { setConfirmDelete(false); setDeleteConfirmText(""); }} disabled={busy === "delete"} style={[modalStyles.btn, { backgroundColor: colors.surfaceMuted }]} testID="delete-confirm-cancel">
                  <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={performDelete}
                  disabled={deleteConfirmText !== "DELETE" || busy === "delete"}
                  style={[modalStyles.btn, { backgroundColor: "#B3261E" }, (deleteConfirmText !== "DELETE" || busy === "delete") && { opacity: 0.5 }]}
                  testID="delete-confirm-go"
                >
                  {busy === "delete" ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Delete user</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        )}
      </SafeAreaView>
    </Modal>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ fontSize: 12, color: colors.textMuted, fontWeight: "600", marginBottom: 6 }}>{label}</Text>
      {children}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statCard}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 20 },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 20 },
  statCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: 14 },
  statValue: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  statLabel: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  searchWrap: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 16, gap: 8 },
  newUserBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14, marginBottom: 16 },
  newUserBtnText: { color: colors.primaryFg, fontSize: 14, fontWeight: "800" },
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
  userAmount: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  statusDot: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, marginTop: 4 },
  statusDotText: { color: colors.primaryFg, fontSize: 9, fontWeight: "800" },
  empty: { padding: 24, textAlign: "center", color: colors.textMuted },
});

const modalStyles = StyleSheet.create({
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
});
