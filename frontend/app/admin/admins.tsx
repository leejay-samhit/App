import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity,
  Modal, TextInput, Alert, KeyboardAvoidingView, Platform, ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

type AdminUser = {
  id: string;
  name: string;
  email: string;
  phone?: string | null;
  role: string;
  admin_role?: string | null;
  is_blocked?: boolean;
  block_reason?: string | null;
  created_at?: string;
};

type SubRole = "super_admin" | "manager" | "support" | "finance";

const ROLES: { key: SubRole; label: string; tint: string; desc: string }[] = [
  { key: "super_admin", label: "Super Admin", tint: "#143D2E", desc: "Full access — settings, payouts, admin management" },
  { key: "manager", label: "Manager", tint: "#1E6B4F", desc: "All operational access; cannot edit settings or admins" },
  { key: "support", label: "Support", tint: "#A07A2C", desc: "Operational access; cannot edit settings or admins" },
  { key: "finance", label: "Finance", tint: "#3D5A80", desc: "Withdrawals only — approve / reject / mark paid. No user mods." },
];

export default function AdminAdmins() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = ((user as any)?.admin_role || "super_admin") === "super_admin";

  const [items, setItems] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");
  const [createRole, setCreateRole] = useState<SubRole>("manager");

  const [promoteOpen, setPromoteOpen] = useState(false);
  const [promoteEmail, setPromoteEmail] = useState("");
  const [promoteRole, setPromoteRole] = useState<SubRole>("manager");

  const [editFor, setEditFor] = useState<AdminUser | null>(null);
  const [editRole, setEditRole] = useState<SubRole>("manager");

  // Danger PIN (6-digit) — gates Wipe + Restore
  const [pinStatus, setPinStatus] = useState<{ is_set: boolean; format: string } | null>(null);
  const [pinOpen, setPinOpen] = useState(false);
  const [pinCurrent, setPinCurrent] = useState("");
  const [pinNew, setPinNew] = useState("");
  const [pinNew2, setPinNew2] = useState("");

  const isPin = (p: string) => /^[0-9]{6}$/.test(p);
  const pinNewOk = isPin(pinNew);
  const pinMatches = !!pinNew && pinNew === pinNew2;
  const pinCurrentOk = !pinStatus?.is_set || isPin(pinCurrent);

  const load = useCallback(async () => {
    try {
      const [adminsRes, pinRes] = await Promise.all([
        api.get<AdminUser[]>("/admin/admins"),
        isSuper ? api.get<{ is_set: boolean; format: string }>("/admin/danger-pin") : Promise.resolve({ data: null as any }),
      ]);
      setItems(adminsRes.data);
      if (pinRes.data) setPinStatus(pinRes.data);
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isSuper]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onSetDangerPin = async () => {
    if (!pinNewOk) {
      Alert.alert("Invalid PIN", "PIN must be exactly 6 digits (0–9).");
      return;
    }
    if (!pinMatches) {
      Alert.alert("Mismatch", "The two new PIN entries don't match.");
      return;
    }
    if (pinStatus?.is_set && !pinCurrentOk) {
      Alert.alert("Current PIN required", "Enter your current 6-digit Danger PIN.");
      return;
    }
    setBusy("danger-pin");
    try {
      await api.post("/admin/danger-pin", {
        new_pin: pinNew,
        current_pin: pinStatus?.is_set ? pinCurrent : undefined,
      });
      setPinOpen(false);
      setPinCurrent(""); setPinNew(""); setPinNew2("");
      await load();
      Alert.alert("Saved", "Danger PIN updated.");
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const onCreate = async () => {
    if (!name.trim() || !email.trim() || password.length < 6) {
      Alert.alert("Missing fields", "Name, email, and a 6+ char password are required.");
      return;
    }
    setBusy("create");
    try {
      await api.post("/admin/admins", {
        name: name.trim(),
        email: email.trim().toLowerCase(),
        password,
        admin_role: createRole,
        phone: phone.trim() || undefined,
      });
      setCreateOpen(false);
      setName(""); setEmail(""); setPassword(""); setPhone(""); setCreateRole("manager");
      await load();
      Alert.alert("Admin created", `${email.trim()} has been added as ${createRole}.`);
    } catch (e) {
      Alert.alert("Create failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const onPromote = async () => {
    if (!promoteEmail.trim()) return;
    setBusy("promote");
    try {
      // Find the user by email via /admin/users
      const { data: users } = await api.get<AdminUser[]>("/admin/users");
      const target = users.find((u) => (u.email || "").toLowerCase() === promoteEmail.trim().toLowerCase());
      if (!target) throw new Error("User not found");
      await api.post(`/admin/users/${target.id}/promote`, { admin_role: promoteRole });
      setPromoteOpen(false);
      setPromoteEmail(""); setPromoteRole("manager");
      await load();
      Alert.alert("Promoted", `${target.email} is now ${promoteRole}.`);
    } catch (e: any) {
      Alert.alert("Promote failed", e?.message?.includes("User not found") ? "No user with that email." : formatApiError(e));
    } finally { setBusy(null); }
  };

  const onChangeRole = async () => {
    if (!editFor) return;
    setBusy(editFor.id);
    try {
      await api.patch(`/admin/users/${editFor.id}`, { admin_role: editRole });
      setEditFor(null);
      await load();
    } catch (e) {
      Alert.alert("Update failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const onDemote = (a: AdminUser) => {
    Alert.alert(
      "Demote admin?",
      `${a.email} will lose all admin access and become a regular user.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Demote",
          style: "destructive",
          onPress: async () => {
            setBusy(a.id);
            try {
              await api.post(`/admin/users/${a.id}/demote`);
              await load();
            } catch (e) {
              Alert.alert("Demote failed", formatApiError(e));
            } finally { setBusy(null); }
          },
        },
      ]
    );
  };

  const onToggleBlock = async (a: AdminUser) => {
    setBusy(a.id);
    try {
      if (a.is_blocked) {
        await api.post(`/admin/users/${a.id}/unblock`);
      } else {
        await api.post(`/admin/users/${a.id}/block`, { reason: "Suspended by super_admin" });
      }
      await load();
    } catch (e) {
      Alert.alert("Action failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const roleMeta = (r?: string | null) => ROLES.find((x) => x.key === r) || ROLES[1];

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="admins-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Admin access</Text>
        <View style={{ width: 40 }} />
      </View>

      {!isSuper && (
        <View style={styles.warnBox}>
          <Feather name="info" size={14} color={colors.textMuted} />
          <Text style={styles.warnText}>Only a super_admin can create, promote, or demote admins.</Text>
        </View>
      )}

      <View style={styles.actions}>
        <TouchableOpacity
          onPress={() => setCreateOpen(true)}
          disabled={!isSuper}
          style={[styles.actionBtn, { backgroundColor: colors.primary }, !isSuper && { opacity: 0.4 }]}
          testID="admins-create"
        >
          <Feather name="user-plus" size={16} color={colors.primaryFg} />
          <Text style={[styles.actionText, { color: colors.primaryFg }]}>New admin</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setPromoteOpen(true)}
          disabled={!isSuper}
          style={[styles.actionBtn, { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border }, !isSuper && { opacity: 0.4 }]}
          testID="admins-promote"
        >
          <Feather name="trending-up" size={16} color={colors.textMain} />
          <Text style={[styles.actionText, { color: colors.textMain }]}>Promote user</Text>
        </TouchableOpacity>
      </View>

      {isSuper && (
        <TouchableOpacity
          onPress={() => setPinOpen(true)}
          style={styles.superPwdRow}
          testID="danger-pin-row"
        >
          <View style={[styles.superPwdIcon, { backgroundColor: pinStatus?.is_set ? "#E6F4EE" : "#FFF4E5" }]}>
            <Feather name={pinStatus?.is_set ? "shield" : "shield-off"} size={16} color={pinStatus?.is_set ? colors.success : colors.warning} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.superPwdTitle}>Danger PIN (6 digits)</Text>
            <Text style={styles.superPwdSub}>
              {pinStatus?.is_set ? "Set — required to Wipe users or Restore backups" : "Not set — required to enable Wipe / Restore"}
            </Text>
          </View>
          <Feather name="chevron-right" size={18} color={colors.textMuted} />
        </TouchableOpacity>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => {
            const meta = roleMeta(item.admin_role);
            const isSelf = item.id === (user as any)?.id;
            return (
              <View style={styles.card} testID={`admin-${item.id}`}>
                <View style={styles.cardTop}>
                  <View style={[styles.avatar, { backgroundColor: meta.tint }]}>
                    <Text style={styles.avatarText}>{(item.name || "?").charAt(0).toUpperCase()}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.cardName}>{item.name}{isSelf ? " (you)" : ""}</Text>
                    <Text style={styles.cardEmail}>{item.email}</Text>
                  </View>
                  <View style={[styles.pill, { backgroundColor: meta.tint }]}>
                    <Text style={styles.pillText}>{meta.label.toUpperCase()}</Text>
                  </View>
                </View>
                <Text style={styles.cardDesc}>{meta.desc}</Text>
                {item.is_blocked ? (
                  <View style={styles.blockedRow}>
                    <Feather name="alert-octagon" size={12} color="#B3261E" />
                    <Text style={styles.blockedText}>Suspended{item.block_reason ? ` · ${item.block_reason}` : ""}</Text>
                  </View>
                ) : null}
                {isSuper && !isSelf && (
                  <View style={styles.cardActions}>
                    <TouchableOpacity
                      onPress={() => { setEditFor(item); setEditRole((item.admin_role as SubRole) || "manager"); }}
                      style={[styles.miniBtn, { backgroundColor: colors.surfaceMuted }]}
                      disabled={busy === item.id}
                      testID={`admin-${item.id}-role`}
                    >
                      <Feather name="shield" size={13} color={colors.textMain} />
                      <Text style={styles.miniBtnText}>Change role</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      onPress={() => onToggleBlock(item)}
                      style={[styles.miniBtn, { backgroundColor: item.is_blocked ? "#E6F4EE" : "#FFF4E5" }]}
                      disabled={busy === item.id}
                      testID={`admin-${item.id}-suspend`}
                    >
                      <Feather name={item.is_blocked ? "unlock" : "lock"} size={13} color={item.is_blocked ? colors.success : colors.warning} />
                      <Text style={[styles.miniBtnText, { color: item.is_blocked ? colors.success : colors.warning }]}>
                        {item.is_blocked ? "Unsuspend" : "Suspend"}
                      </Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      onPress={() => onDemote(item)}
                      style={[styles.miniBtn, { backgroundColor: "#FCE9E5" }]}
                      disabled={busy === item.id}
                      testID={`admin-${item.id}-demote`}
                    >
                      {busy === item.id ? <ActivityIndicator color="#B3261E" size="small" /> : (
                        <>
                          <Feather name="user-minus" size={13} color="#B3261E" />
                          <Text style={[styles.miniBtnText, { color: "#B3261E" }]}>Demote</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            );
          }}
          ListEmptyComponent={<Text style={styles.empty}>No admins yet</Text>}
        />
      )}

      {/* Create admin modal */}
      <Modal visible={createOpen} transparent animationType="slide" onRequestClose={() => setCreateOpen(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>New admin</Text>
            <Text style={styles.modalSub}>Creates a new account that can sign in to the admin panel.</Text>
            <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 460 }}>
              <Text style={styles.fieldLabel}>Full name</Text>
              <TextInput value={name} onChangeText={setName} placeholder="e.g. Riya Sharma" placeholderTextColor={colors.textMuted} style={styles.input} testID="new-admin-name" />
              <Text style={styles.fieldLabel}>Email</Text>
              <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="riya@company.com" placeholderTextColor={colors.textMuted} style={styles.input} testID="new-admin-email" />
              <Text style={styles.fieldLabel}>Password (min 6 chars)</Text>
              <TextInput value={password} onChangeText={setPassword} secureTextEntry placeholder="Set a strong password" placeholderTextColor={colors.textMuted} style={styles.input} testID="new-admin-password" />
              <Text style={styles.fieldLabel}>Phone (optional)</Text>
              <TextInput value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholder="+91 ..." placeholderTextColor={colors.textMuted} style={styles.input} testID="new-admin-phone" />
              <Text style={styles.fieldLabel}>Role</Text>
              <View style={styles.roleRow}>
                {ROLES.map((r) => (
                  <TouchableOpacity
                    key={r.key}
                    onPress={() => setCreateRole(r.key)}
                    style={[styles.roleChip, createRole === r.key && { backgroundColor: r.tint, borderColor: r.tint }]}
                    testID={`new-admin-role-${r.key}`}
                  >
                    <Text style={[styles.roleChipText, createRole === r.key && { color: "#fff" }]}>{r.label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.roleHint}>{ROLES.find((r) => r.key === createRole)?.desc}</Text>
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => setCreateOpen(false)} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onCreate} disabled={busy === "create"} style={[styles.modalBtn, { backgroundColor: colors.primary }, busy === "create" && { opacity: 0.5 }]} testID="new-admin-submit">
                {busy === "create" ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Create admin</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Promote modal */}
      <Modal visible={promoteOpen} transparent animationType="slide" onRequestClose={() => setPromoteOpen(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Promote user to admin</Text>
            <Text style={styles.modalSub}>Enter the email of an existing user to grant them admin access.</Text>
            <Text style={styles.fieldLabel}>User email</Text>
            <TextInput value={promoteEmail} onChangeText={setPromoteEmail} autoCapitalize="none" keyboardType="email-address" placeholder="user@example.com" placeholderTextColor={colors.textMuted} style={styles.input} testID="promote-email" />
            <Text style={styles.fieldLabel}>Role</Text>
            <View style={styles.roleRow}>
              {ROLES.map((r) => (
                <TouchableOpacity
                  key={r.key}
                  onPress={() => setPromoteRole(r.key)}
                  style={[styles.roleChip, promoteRole === r.key && { backgroundColor: r.tint, borderColor: r.tint }]}
                  testID={`promote-role-${r.key}`}
                >
                  <Text style={[styles.roleChipText, promoteRole === r.key && { color: "#fff" }]}>{r.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => setPromoteOpen(false)} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onPromote} disabled={busy === "promote"} style={[styles.modalBtn, { backgroundColor: colors.primary }, busy === "promote" && { opacity: 0.5 }]} testID="promote-submit">
                {busy === "promote" ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Promote</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Edit role modal */}
      <Modal visible={!!editFor} transparent animationType="slide" onRequestClose={() => setEditFor(null)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Change role</Text>
            <Text style={styles.modalSub}>{editFor?.email}</Text>
            <View style={[styles.roleRow, { marginTop: 14 }]}>
              {ROLES.map((r) => (
                <TouchableOpacity
                  key={r.key}
                  onPress={() => setEditRole(r.key)}
                  style={[styles.roleChip, editRole === r.key && { backgroundColor: r.tint, borderColor: r.tint }]}
                  testID={`edit-role-${r.key}`}
                >
                  <Text style={[styles.roleChipText, editRole === r.key && { color: "#fff" }]}>{r.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.roleHint}>{ROLES.find((r) => r.key === editRole)?.desc}</Text>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
              <TouchableOpacity onPress={() => setEditFor(null)} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onChangeRole} disabled={!!busy} style={[styles.modalBtn, { backgroundColor: colors.primary }, !!busy && { opacity: 0.5 }]} testID="edit-role-submit">
                {busy ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Save</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
      {/* Danger PIN modal */}
      <Modal visible={pinOpen} transparent animationType="slide" onRequestClose={() => setPinOpen(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>{pinStatus?.is_set ? "Rotate" : "Set"} Danger PIN</Text>
            <Text style={styles.modalSub}>A single 6-digit numeric PIN. Required to Wipe users or Restore backups.</Text>
            <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 460 }}>
              {pinStatus?.is_set && (
                <>
                  <Text style={styles.fieldLabel}>Current Danger PIN</Text>
                  <TextInput
                    value={pinCurrent}
                    onChangeText={(v) => setPinCurrent(v.replace(/[^0-9]/g, "").slice(0, 6))}
                    secureTextEntry
                    keyboardType="number-pad"
                    maxLength={6}
                    placeholder="••••••"
                    placeholderTextColor={colors.textMuted}
                    style={[styles.input, styles.pinInput]}
                    testID="danger-pin-current"
                  />
                </>
              )}
              <Text style={styles.fieldLabel}>New Danger PIN</Text>
              <TextInput
                value={pinNew}
                onChangeText={(v) => setPinNew(v.replace(/[^0-9]/g, "").slice(0, 6))}
                secureTextEntry
                keyboardType="number-pad"
                maxLength={6}
                placeholder="6 digits"
                placeholderTextColor={colors.textMuted}
                style={[styles.input, styles.pinInput]}
                testID="danger-pin-new"
              />
              <Text style={styles.fieldLabel}>Repeat new PIN</Text>
              <TextInput
                value={pinNew2}
                onChangeText={(v) => setPinNew2(v.replace(/[^0-9]/g, "").slice(0, 6))}
                secureTextEntry
                keyboardType="number-pad"
                maxLength={6}
                placeholder="Repeat"
                placeholderTextColor={colors.textMuted}
                style={[styles.input, styles.pinInput]}
                testID="danger-pin-new2"
              />

              <View style={styles.rulesBox}>
                <Text style={styles.rulesTitle}>Rules</Text>
                <Rule label="Exactly 6 digits (0–9)" got={pinNewOk ? 1 : 0} need={1} />
                <Rule label="Both new entries match" got={pinMatches ? 1 : 0} need={1} />
              </View>
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => { setPinOpen(false); setPinCurrent(""); setPinNew(""); setPinNew2(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={onSetDangerPin}
                disabled={!pinNewOk || !pinMatches || (!!pinStatus?.is_set && !pinCurrentOk) || busy === "danger-pin"}
                style={[styles.modalBtn, { backgroundColor: colors.primary }, (!pinNewOk || !pinMatches || (!!pinStatus?.is_set && !pinCurrentOk) || busy === "danger-pin") && { opacity: 0.5 }]}
                testID="danger-pin-save"
              >
                {busy === "danger-pin" ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Save PIN</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

function Rule({ label, got, need }: { label: string; got: number; need: number }) {
  const ok = got === need;
  return (
    <View style={styles.ruleRow}>
      <Feather name={ok ? "check-circle" : "circle"} size={14} color={ok ? colors.success : colors.textMuted} />
      <Text style={[styles.ruleText, ok && { color: colors.textMain, fontWeight: "700" }]}>{label} <Text style={styles.ruleCount}>({got}/{need})</Text></Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  warnBox: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceMuted, marginHorizontal: spacing.screen, padding: 12, borderRadius: 12 },
  warnText: { color: colors.textMuted, fontSize: 12 },
  actions: { flexDirection: "row", gap: 10, padding: spacing.screen, paddingBottom: 8 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: radii.button },
  actionText: { fontSize: 14, fontWeight: "800" },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 16, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatar: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  avatarText: { color: "#fff", fontSize: 16, fontWeight: "800" },
  cardName: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  cardEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 99 },
  pillText: { color: "#fff", fontSize: 10, fontWeight: "800", letterSpacing: 1 },
  cardDesc: { fontSize: 12, color: colors.textMuted, marginTop: 10, lineHeight: 18 },
  blockedRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8 },
  blockedText: { color: "#B3261E", fontSize: 12, fontWeight: "700" },
  cardActions: { flexDirection: "row", gap: 6, marginTop: 12 },
  miniBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingVertical: 10, borderRadius: 10 },
  miniBtnText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  modalSub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 12, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain },
  pinInput: { textAlign: "center", letterSpacing: 8, fontSize: 22, fontWeight: "700", paddingVertical: 16 },
  roleRow: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  roleChip: { paddingHorizontal: 14, paddingVertical: 10, borderRadius: 99, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  roleChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  roleHint: { fontSize: 11, color: colors.textMuted, marginTop: 8 },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
  superPwdRow: { flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: spacing.screen, padding: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 8 },
  superPwdIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  superPwdTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  superPwdSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  rulesBox: { marginTop: 16, padding: 12, backgroundColor: colors.surfaceMuted, borderRadius: 12, gap: 6 },
  rulesTitle: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginBottom: 4 },
  ruleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  ruleText: { fontSize: 12, color: colors.textMuted },
  ruleCount: { color: colors.textMuted, fontWeight: "600" },
});
