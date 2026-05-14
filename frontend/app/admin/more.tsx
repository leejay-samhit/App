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
  { icon: "credit-card", label: "Payment gateway (Razorpay)", route: "/admin/payment-gateway" },
  { icon: "shopping-bag", label: "Vendor applications", route: "/admin/vendor-applications" },
  { icon: "briefcase", label: "Service applications", route: "/admin/service-applications" },
  { icon: "grid", label: "Service Application Management", route: "/admin/service-management" },
  { icon: "map", label: "Distributor Network · Area Mapping", route: "/admin/area-mapping" },
  { icon: "dollar-sign", label: "System Wallet (treasury)", route: "/admin/system-wallet" },
  { icon: "users", label: "All vendors", route: "/admin/vendors" },
  { icon: "edit-3", label: "Branding & theme", route: "/admin/branding" },
  { icon: "hard-drive", label: "Data backups", route: "/admin/backups" },
  { icon: "map", label: "Product roadmap", route: "/admin/roadmap" },
  { icon: "user-check", label: "KYC review queue", route: "/admin/kyc" },
  { icon: "package", label: "Orders management", route: "/admin/orders" },
  { icon: "list", label: "Transactions", route: "/admin/transactions" },
  { icon: "file-text", label: "Admin audit log", route: "/admin/audit" },
  { icon: "sliders", label: "Payout structure", route: "/admin/settings" },
];

// Store-related items grouped together so admin can manage products + customer-facing shop UI in one place.
const STORE_ITEMS = [
  { icon: "package", label: "Products", route: "/admin/products", hint: "Manage catalog · stock · pricing" },
  { icon: "layout", label: "Shop layout", route: "/admin/shop-layout", hint: "12 block types · per-category layouts · live preview" },
  { icon: "grid", label: "Shop categories", route: "/admin/shop-categories", hint: "Rename · re-icon · upload image · delete" },
  { icon: "image", label: "Promo banners (legacy)", route: "/admin/promo-banners", hint: "Migrated into Shop layout → Banner slider" },
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
  const [wipeError, setWipeError] = useState<string | null>(null);

  // Full factory-reset state ("Reset app to zero")
  const [resetOpen, setResetOpen] = useState(false);
  const [resetPin, setResetPin] = useState("");
  const [resetPhrase, setResetPhrase] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

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
    setWipeError(null);
    if (!isPin(wipePin)) {
      setWipeError("PIN must be exactly 6 digits.");
      return;
    }
    setWipeBusy(true);
    try {
      const { data } = await api.post("/admin/system/wipe-users", {
        keep_admins: true,
        danger_pin: wipePin,
      });
      const snapId = data.snapshot_id ? String(data.snapshot_id).slice(0, 8) : null;
      setWipeOpen(false);
      setWipePin("");
      Alert.alert(
        "Wipe complete",
        `Deleted:\n• ${data.users_deleted} users\n• ${data.transactions_deleted} transactions\n• ${data.withdrawals_deleted} withdrawals\n• ${data.orders_deleted} orders\n• ${data.cart_items_deleted} cart items\n• ${data.notifications_deleted} notifications${snapId ? `\n\nAuto-backup taken (#${snapId}). Restore from Admin → Data Backups if needed.` : ""}`,
      );
    } catch (e) {
      setWipeError(formatApiError(e));
    } finally {
      setWipeBusy(false);
    }
  };

  const onLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const onFullReset = async () => {
    setResetError(null);
    if (!isPin(resetPin)) { setResetError("PIN must be exactly 6 digits."); return; }
    if (resetPhrase.trim().toUpperCase() !== "RESET") { setResetError('Please type RESET (in capitals) to confirm.'); return; }
    setResetBusy(true);
    try {
      const { data } = await api.post("/admin/system/wipe-all", {
        danger_pin: resetPin,
        confirm_phrase: resetPhrase.trim().toUpperCase(),
      });
      setResetOpen(false); setResetPin(""); setResetPhrase("");
      const s = data.summary || {};
      const total = Object.values(s).reduce((a: number, b: any) => a + (Number(b) || 0), 0);
      const snapId = data.snapshot_id ? String(data.snapshot_id).slice(0, 8) : null;
      Alert.alert(
        "App reset to zero",
        `${total} records cleared.\n\n• ${s.users_deleted || 0} users\n• ${s.transactions_deleted || 0} transactions\n• ${s.orders_deleted || 0} orders\n• ${s.withdrawals_deleted || 0} withdrawals\n• ${s.products_deleted || 0} products\n• ${s.tickets_deleted || 0} tickets\n• ${s.system_wallet_deposits_deleted || 0} system deposits\n\nSettings & super-admin login preserved.${snapId ? `\n\nFull pre-reset backup taken (#${snapId}). Restore from Admin → Data Backups if needed.` : ""}`,
      );
    } catch (e) {
      setResetError(formatApiError(e));
    } finally {
      setResetBusy(false);
    }
  };

  const isSuperAdmin = ((user as any)?.admin_role || "super_admin") === "super_admin";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.overline}>ADMIN</Text>
        <Text style={styles.h1}>More</Text>
        <Text style={styles.subtitle}>{user?.email} · {(user as any)?.admin_role || "super_admin"}</Text>

        <Text style={styles.sectionLabel}>STORE</Text>
        {STORE_ITEMS.map((it) => (
          <TouchableOpacity key={it.route} style={styles.row} onPress={() => router.push(it.route as any)} testID={`more-store-${it.icon}`}>
            <View style={styles.rowIcon}><Feather name={it.icon as any} size={16} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowText}>{it.label}</Text>
              <Text style={styles.rowHint}>{it.hint}</Text>
            </View>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ))}

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
            <TouchableOpacity onPress={() => { setWipeError(null); setWipePin(""); setWipeOpen(true); }} style={styles.dangerRow} testID="more-wipe-users">
              <View style={styles.dangerIcon}><Feather name="trash-2" size={16} color="#B3261E" /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.dangerText}>Wipe all users</Text>
                <Text style={styles.dangerHint}>Deletes every non-admin user + their transactions, orders, withdrawals, cart, and notifications.</Text>
              </View>
              <Feather name="alert-triangle" size={16} color="#B3261E" />
            </TouchableOpacity>

            <TouchableOpacity onPress={() => { setResetError(null); setResetPin(""); setResetPhrase(""); setResetOpen(true); }} style={[styles.dangerRow, { backgroundColor: "#FFE6E6", borderColor: "#B3261E", borderWidth: 2 }]} testID="more-reset-app">
              <View style={[styles.dangerIcon, { backgroundColor: "#B3261E" }]}><Feather name="zap" size={16} color="#fff" /></View>
              <View style={{ flex: 1 }}>
                <Text style={[styles.dangerText, { fontSize: 15 }]}>Reset app to zero</Text>
                <Text style={styles.dangerHint}>Deletes EVERYTHING — users, transactions, orders, products, services, vendors, tickets, audit log, deposits and snapshots. Settings &amp; super-admin login are preserved.</Text>
              </View>
              <Feather name="alert-octagon" size={18} color="#B3261E" />
            </TouchableOpacity>
          </>
        )}

        <TouchableOpacity onPress={onLogout} style={styles.logout} testID="more-logout">
          <Feather name="log-out" size={16} color="#B3261E" />
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>
      </ScrollView>

      <Modal
        visible={wipeOpen}
        transparent
        animationType="fade"
        statusBarTranslucent
        presentationStyle="overFullScreen"
        onRequestClose={() => setWipeOpen(false)}
      >
        <KeyboardAvoidingView
          style={[styles.modalOverlay, Platform.OS === "web" ? ({ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999 } as any) : null]}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <TouchableOpacity activeOpacity={1} style={{ flex: 1 }} onPress={() => setWipeOpen(false)} />
          <View style={styles.modalSheet}>
            <View style={styles.modalIconWrap}>
              <Feather name="alert-triangle" size={28} color="#B3261E" />
            </View>
            <Text style={styles.modalTitle}>Wipe all users?</Text>
            <Text style={styles.modalBody}>
              This will permanently delete every non-admin user account and all their related data
              (transactions, withdrawals, orders, cart, notifications).{"\n\n"}
              Admin accounts and the system audit log are kept.{"\n\n"}
              <Text style={{ fontWeight: "800", color: colors.success }}>An automatic backup is taken first</Text> — you can
              restore from <Text style={{ fontWeight: "800" }}>Admin → Data Backups</Text> if needed.{"\n\n"}
              Enter your <Text style={{ fontWeight: "800" }}>6-digit Danger PIN</Text> to confirm.
            </Text>
            <TextInput
              testID="wipe-pin-input"
              value={wipePin}
              onChangeText={(v) => { setWipeError(null); setWipePin(v.replace(/[^0-9]/g, "").slice(0, 6)); }}
              secureTextEntry
              keyboardType="number-pad"
              maxLength={6}
              placeholder="••••••"
              placeholderTextColor={colors.textMuted}
              style={[styles.modalInput, !!wipeError && { borderWidth: 2, borderColor: "#B3261E" }]}
              autoFocus
            />
            {!!wipeError && (
              <View style={{ flexDirection: "row", alignItems: "center", backgroundColor: "#FCE9E5", padding: 10, borderRadius: 10, marginTop: 10, gap: 8 }}>
                <Feather name="x-circle" size={16} color="#B3261E" />
                <Text style={{ color: "#B3261E", fontSize: 12, fontWeight: "700", flex: 1 }}>{wipeError}</Text>
              </View>
            )}
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

      {/* FULL RESET MODAL */}
      <Modal
        visible={resetOpen}
        transparent
        animationType="fade"
        statusBarTranslucent
        presentationStyle="overFullScreen"
        onRequestClose={() => setResetOpen(false)}
      >
        <KeyboardAvoidingView
          style={[styles.modalOverlay, Platform.OS === "web" ? ({ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999 } as any) : null]}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <TouchableOpacity activeOpacity={1} style={{ flex: 1 }} onPress={() => setResetOpen(false)} />
          <View style={styles.modalSheet}>
            <View style={[styles.modalIconWrap, { backgroundColor: "#FFE6E6", borderWidth: 2, borderColor: "#B3261E" }]}>
              <Feather name="alert-octagon" size={28} color="#B3261E" />
            </View>
            <Text style={styles.modalTitle}>Reset app to zero?</Text>
            <Text style={styles.modalBody}>
              This will permanently delete <Text style={{ fontWeight: "800", color: "#B3261E" }}>EVERYTHING</Text>:
              users, transactions, withdrawals, orders, products, services, vendors, tickets,
              audit logs, deposits and snapshots.{"\n\n"}
              Only <Text style={{ fontWeight: "800" }}>Settings</Text> (branding/payouts) and your
              <Text style={{ fontWeight: "800" }}> super-admin login</Text> are preserved.{"\n\n"}
              <Text style={{ fontWeight: "800", color: colors.success }}>An automatic full backup is taken first</Text> — the
              backup itself survives the reset and can be restored from <Text style={{ fontWeight: "800" }}>Admin → Data
              Backups</Text>.{"\n\n"}
              <Text style={{ color: "#B3261E", fontWeight: "800" }}>This action cannot be undone (without restoring the backup).</Text>
            </Text>
            <Text style={styles.label}>Type RESET to confirm</Text>
            <TextInput
              testID="reset-phrase-input"
              value={resetPhrase}
              onChangeText={(v) => { setResetError(null); setResetPhrase(v.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 5)); }}
              autoCapitalize="characters"
              placeholder="RESET"
              placeholderTextColor={colors.textMuted}
              style={[styles.modalInput, { letterSpacing: 6, fontSize: 18 }, !!resetError && { borderWidth: 2, borderColor: "#B3261E" }]}
            />
            <Text style={[styles.label, { marginTop: 14 }]}>6-digit Danger PIN</Text>
            <TextInput
              testID="reset-pin-input"
              value={resetPin}
              onChangeText={(v) => { setResetError(null); setResetPin(v.replace(/[^0-9]/g, "").slice(0, 6)); }}
              secureTextEntry
              keyboardType="number-pad"
              maxLength={6}
              placeholder="••••••"
              placeholderTextColor={colors.textMuted}
              style={[styles.modalInput, !!resetError && { borderWidth: 2, borderColor: "#B3261E" }]}
            />
            {!!resetError && (
              <View style={{ flexDirection: "row", alignItems: "center", backgroundColor: "#FCE9E5", padding: 10, borderRadius: 10, marginTop: 10, gap: 8 }}>
                <Feather name="x-circle" size={16} color="#B3261E" />
                <Text style={{ color: "#B3261E", fontSize: 12, fontWeight: "700", flex: 1 }}>{resetError}</Text>
              </View>
            )}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity onPress={() => { setResetOpen(false); setResetPin(""); setResetPhrase(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]} testID="reset-cancel">
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={onFullReset}
                disabled={!isPin(resetPin) || resetPhrase !== "RESET" || resetBusy}
                style={[styles.modalBtn, { backgroundColor: "#B3261E" }, (!isPin(resetPin) || resetPhrase !== "RESET" || resetBusy) && { opacity: 0.5 }]}
                testID="reset-confirm"
              >
                {resetBusy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Reset to zero</Text>}
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
  rowHint: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
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
  label: { fontSize: 11, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700", marginBottom: 6, textTransform: "uppercase" },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});
