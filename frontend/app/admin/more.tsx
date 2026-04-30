import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert, Modal, TextInput, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { downloadText } from "../../src/download";
import { colors, radii, spacing } from "../../src/theme";

const ITEMS = [
  { icon: "shield", label: "Admin access", route: "/admin/admins" },
  { icon: "user-check", label: "User approvals", route: "/admin/approvals" },
  { icon: "check-circle", label: "Approved registrations", route: "/admin/approved" },
  { icon: "user-x", label: "Rejected registrations", route: "/admin/rejected" },
  { icon: "message-square", label: "Support tickets", route: "/admin/tickets" },
  { icon: "package", label: "Products", route: "/admin/products" },
  { icon: "edit-3", label: "Branding & theme", route: "/admin/branding" },
  { icon: "hard-drive", label: "Data backups", route: "/admin/backups" },
  { icon: "map", label: "Product roadmap", route: "/admin/roadmap" },
  { icon: "user-check", label: "KYC review queue", route: "/admin/kyc" },
  { icon: "package", label: "Orders management", route: "/admin/orders" },
  { icon: "list", label: "Transactions", route: "/admin/transactions" },
  { icon: "file-text", label: "Admin audit log", route: "/admin/audit" },
  { icon: "sliders", label: "Payout structure", route: "/admin/settings" },
];

const EXPORTS = [
  { kind: "users", label: "Users CSV", icon: "users" },
  { kind: "transactions", label: "Transactions CSV", icon: "list" },
  { kind: "withdrawals", label: "Withdrawals CSV", icon: "trending-down" },
  { kind: "orders", label: "Orders CSV", icon: "shopping-bag" },
] as const;

export default function More() {
  const router = useRouter();
  const { user, logout } = useAuth();
  const [wipeOpen, setWipeOpen] = useState(false);
  const [wipePin, setWipePin] = useState("");
  const [wipeBusy, setWipeBusy] = useState(false);

  const isPin = (p: string) => /^[0-9]{6}$/.test(p);

  const onExport = async (kind: string) => {
    try {
      const res = await api.get(`/admin/export/${kind}`, { responseType: "text" });
      const data = (res.data as unknown) as string;
      const csv = typeof data === "string" ? data : "";
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      const filename = `${kind}-${stamp}.csv`;
      const out = await downloadText({ filename, content: csv, mimeType: "text/csv" });
      if (out.ok) {
        const lines = csv.split("\n").length - 1;
        Alert.alert(
          "Export ready",
          `${lines} ${kind} row${lines === 1 ? "" : "s"} exported.${out.method === "browser" ? "\n\nCheck your browser's Downloads folder." : ""}`,
        );
      }
    } catch {
      Alert.alert("Export failed", "Please try again.");
    }
  };

  const onWipe = async () => {
    if (!isPin(wipePin)) {
      Alert.alert("Invalid PIN", "PIN must be exactly 6 digits.");
      return;
    }
    setWipeBusy(true);
    try {
      const { data } = await api.post("/admin/system/wipe-users", {
        keep_admins: true,
        danger_pin: wipePin,
      });
      setWipeOpen(false);
      setWipePin("");
      Alert.alert(
        "Wipe complete",
        `Deleted:\n• ${data.users_deleted} users\n• ${data.transactions_deleted} transactions\n• ${data.withdrawals_deleted} withdrawals\n• ${data.orders_deleted} orders\n• ${data.cart_items_deleted} cart items\n• ${data.notifications_deleted} notifications`,
      );
    } catch (e) {
      Alert.alert("Wipe failed", formatApiError(e));
    } finally {
      setWipeBusy(false);
    }
  };

  const onLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const isSuperAdmin = ((user as any)?.admin_role || "super_admin") === "super_admin";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.overline}>ADMIN</Text>
        <Text style={styles.h1}>More</Text>
        <Text style={styles.subtitle}>{user?.email} · {(user as any)?.admin_role || "super_admin"}</Text>

        <Text style={styles.sectionLabel}>OPERATIONS</Text>
        {ITEMS.map((it) => (
          <TouchableOpacity key={it.route} style={styles.row} onPress={() => router.push(it.route as any)} testID={`more-${it.icon}`}>
            <View style={styles.rowIcon}><Feather name={it.icon as any} size={16} color={colors.primary} /></View>
            <Text style={styles.rowText}>{it.label}</Text>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ))}

        <Text style={styles.sectionLabel}>EXPORT DATA</Text>
        {EXPORTS.map((e) => (
          <TouchableOpacity key={e.kind} style={styles.row} onPress={() => onExport(e.kind)} testID={`export-${e.kind}`}>
            <View style={styles.rowIcon}><Feather name={e.icon as any} size={16} color={colors.primary} /></View>
            <Text style={styles.rowText}>{e.label}</Text>
            <Feather name="download" size={16} color={colors.textMuted} />
          </TouchableOpacity>
        ))}

        {isSuperAdmin && (
          <>
            <Text style={[styles.sectionLabel, { color: "#B3261E" }]}>DANGER ZONE</Text>
            <TouchableOpacity onPress={() => setWipeOpen(true)} style={styles.dangerRow} testID="more-wipe-users">
              <View style={styles.dangerIcon}><Feather name="trash-2" size={16} color="#B3261E" /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.dangerText}>Wipe all users</Text>
                <Text style={styles.dangerHint}>Deletes every non-admin user + their transactions, orders, withdrawals, cart, and notifications.</Text>
              </View>
              <Feather name="alert-triangle" size={16} color="#B3261E" />
            </TouchableOpacity>
          </>
        )}

        <TouchableOpacity onPress={onLogout} style={styles.logout} testID="more-logout">
          <Feather name="log-out" size={16} color="#B3261E" />
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>
      </ScrollView>

      <Modal visible={wipeOpen} transparent animationType="slide" onRequestClose={() => setWipeOpen(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <View style={styles.modalIconWrap}>
              <Feather name="alert-triangle" size={28} color="#B3261E" />
            </View>
            <Text style={styles.modalTitle}>Wipe all users?</Text>
            <Text style={styles.modalBody}>
              This will permanently delete every non-admin user account and all their related data
              (transactions, withdrawals, orders, cart, notifications).{"\n\n"}
              Admin accounts and the system audit log are kept.{"\n\n"}
              Enter your <Text style={{ fontWeight: "800" }}>6-digit Danger PIN</Text> to confirm.
            </Text>
            <TextInput
              testID="wipe-pin-input"
              value={wipePin}
              onChangeText={(v) => setWipePin(v.replace(/[^0-9]/g, "").slice(0, 6))}
              secureTextEntry
              keyboardType="number-pad"
              maxLength={6}
              placeholder="••••••"
              placeholderTextColor={colors.textMuted}
              style={styles.modalInput}
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => { setWipeOpen(false); setWipePin(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]} testID="wipe-cancel">
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={onWipe}
                disabled={!isPin(wipePin) || wipeBusy}
                style={[styles.modalBtn, { backgroundColor: "#B3261E" }, (!isPin(wipePin) || wipeBusy) && { opacity: 0.5 }]}
                testID="wipe-confirm"
              >
                {wipeBusy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Yes, wipe</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 60 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginTop: 6 },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6, marginBottom: 24 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12, marginTop: 12 },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8, gap: 12 },
  rowIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  rowText: { flex: 1, fontSize: 14, color: colors.textMain, fontWeight: "600" },
  dangerRow: { flexDirection: "row", alignItems: "center", backgroundColor: "#FCE9E5", borderWidth: 1, borderColor: "#F2B8B5", borderRadius: 14, padding: 14, marginBottom: 8, gap: 12 },
  dangerIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  dangerText: { fontSize: 14, color: "#B3261E", fontWeight: "800" },
  dangerHint: { fontSize: 11, color: "#7A1F18", marginTop: 2, lineHeight: 16 },
  logout: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 24, padding: 14, borderRadius: radii.button, backgroundColor: colors.surface, borderWidth: 1, borderColor: "#B3261E" },
  logoutText: { color: "#B3261E", fontSize: 14, fontWeight: "700" },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalIconWrap: { width: 56, height: 56, borderRadius: 28, backgroundColor: "#FCE9E5", alignItems: "center", justifyContent: "center", alignSelf: "center", marginBottom: 12 },
  modalTitle: { fontSize: 22, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  modalBody: { fontSize: 13, color: colors.textMuted, marginTop: 10, marginBottom: 14, lineHeight: 20, textAlign: "center" },
  modalInput: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 16, color: colors.textMain, fontWeight: "800", letterSpacing: 4, textAlign: "center" },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});
