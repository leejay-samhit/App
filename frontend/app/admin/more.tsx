import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "../../src/api";
import { useAuth } from "../../src/auth";
import { downloadText } from "../../src/download";
import { colors, radii, spacing } from "../../src/theme";

const ITEMS = [
  { icon: "message-circle", label: "Chat (team + users)", route: "/admin/chat" },
  { icon: "shield", label: "Admin access", route: "/admin/admins" },
  { icon: "user-check", label: "User approvals", route: "/admin/approvals" },
  { icon: "check-circle", label: "Approved registrations", route: "/admin/approved" },
  { icon: "user-x", label: "Rejected registrations", route: "/admin/rejected" },
  { icon: "message-square", label: "Support tickets", route: "/admin/tickets" },
  { icon: "credit-card", label: "Payment gateway (Razorpay)", route: "/admin/payment-gateway" },
  { icon: "shopping-bag", label: "Vendor applications", route: "/admin/vendor-applications" },
  { icon: "truck", label: "Delivery partners", route: "/admin/delivery-partners" },
  { icon: "edit-3", label: "Vendor edit requests", route: "/admin/vendor-edit-requests" },
  { icon: "briefcase", label: "Service applications", route: "/admin/service-applications" },
  { icon: "grid", label: "Service Application Management", route: "/admin/service-management" },
  { icon: "bar-chart-2", label: "Service Analytics", route: "/admin/service-analytics" },
  // Finance Dashboard merged into System Wallet (single Treasury page) on 2026-05-30.
  // AI Tools removed from More menu — now inline inside Service Application Management editor.
  { icon: "map", label: "Distributor Network · Area Mapping", route: "/admin/area-mapping" },
  { icon: "briefcase", label: "System Wallet · Treasury (7-Group)", route: "/admin/system-wallet" },
  { icon: "users", label: "All vendors", route: "/admin/vendors" },
  { icon: "edit-3", label: "Branding & theme", route: "/admin/branding" },
  { icon: "smartphone", label: "Recharge options", route: "/admin/recharge-options" },
  { icon: "hard-drive", label: "Data backups", route: "/admin/backups" },
  { icon: "gift", label: "Cashback & Excel reports", route: "/admin/cashback" },
  { icon: "map", label: "Product roadmap", route: "/admin/roadmap" },
  { icon: "user-check", label: "KYC review queue", route: "/admin/kyc" },
  { icon: "package", label: "Orders management", route: "/admin/orders" },
  { icon: "rotate-ccw", label: "Returns · refunds · reconciliation", route: "/admin/returns" },
  { icon: "bell", label: "Push notification diagnostics", route: "/admin/push-diagnostics" },
  { icon: "shield", label: "SIM binding & chat access", route: "/admin/sim-binding" },
  { icon: "list", label: "Transactions", route: "/admin/transactions" },
  { icon: "file-text", label: "Admin audit log", route: "/admin/audit" },
  { icon: "award", label: "Membership (₹118 subscription)", route: "/admin/subscription" },
  { icon: "sliders", label: "Payout structure (shop by shop)", route: "/admin/payout-structure" },
  { icon: "settings", label: "Platform defaults", route: "/admin/settings" },
  { icon: "credit-card", label: "UPI Payments (pending)", route: "/admin/payments-pending" },
  { icon: "file-text", label: "Legal pages (editable)", route: "/admin/legal-pages" },
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

        <Text style={styles.sectionLabel}>STORE</Text>
        <View style={styles.tileGrid}>
          {STORE_ITEMS.map((it) => (
            <TouchableOpacity
              key={it.route}
              style={styles.tile}
              onPress={() => router.push(it.route as any)}
              testID={`more-store-${it.icon}`}
            >
              <View style={[styles.tileIcon, { backgroundColor: colors.brand100 }]}>
                <Feather name={it.icon as any} size={22} color={colors.primary} />
              </View>
              <Text style={styles.tileLabel} numberOfLines={2}>{it.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.sectionLabel}>OPERATIONS</Text>
        <View style={styles.tileGrid}>
          {ITEMS.map((it) => (
            <TouchableOpacity
              key={it.route}
              style={styles.tile}
              onPress={() => router.push(it.route as any)}
              testID={`more-${it.icon}`}
            >
              <View style={[styles.tileIcon, { backgroundColor: colors.brand100 }]}>
                <Feather name={it.icon as any} size={22} color={colors.primary} />
              </View>
              <Text style={styles.tileLabel} numberOfLines={2}>{it.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.sectionLabel}>EXPORT DATA</Text>
        <View style={styles.tileGrid}>
          {EXPORTS.map((e) => (
            <TouchableOpacity
              key={e.kind}
              style={styles.tile}
              onPress={() => onExport(e.kind)}
              testID={`export-${e.kind}`}
            >
              <View style={[styles.tileIcon, { backgroundColor: "#E0F2FE" }]}>
                <Feather name={e.icon as any} size={22} color="#0369A1" />
              </View>
              <Text style={styles.tileLabel} numberOfLines={2}>{e.label}</Text>
              <Feather name="download" size={11} color={colors.textMuted} style={{ position: "absolute", top: 6, right: 6 }} />
            </TouchableOpacity>
          ))}
        </View>

        {isSuperAdmin && (
          <>
            <Text style={[styles.sectionLabel, { color: "#B3261E" }]}>DANGER ZONE</Text>

            {/* Sep 2026 — the three blind red buttons (wipe all users / reset
                shop products / reset app to zero) are replaced by ONE guided
                Reset centre. It makes you pick the exact account or shop,
                forces a backup FILE download, and only then unlocks the
                wipe — the owner's rule: nothing is destroyed without a
                restorable file in hand. */}
            <TouchableOpacity
              onPress={() => router.push("/admin/reset-center" as any)}
              style={[styles.dangerRow, { backgroundColor: "#FFE6E6", borderColor: "#B3261E", borderWidth: 2 }]}
              testID="more-reset-center"
            >
              <View style={[styles.dangerIcon, { backgroundColor: "#B3261E" }]}><Feather name="zap" size={16} color="#fff" /></View>
              <View style={{ flex: 1 }}>
                <Text style={[styles.dangerText, { fontSize: 15 }]}>Reset centre</Text>
                <Text style={styles.dangerHint}>
                  Reset ONE customer, clear ONE shop, or reset the whole app to zero.
                  Every option downloads a restorable backup file first.
                </Text>
              </View>
              <Feather name="chevron-right" size={18} color="#B3261E" />
            </TouchableOpacity>
          </>
        )}

        <TouchableOpacity onPress={onLogout} style={styles.logout} testID="more-logout">
          <Feather name="log-out" size={16} color="#B3261E" />
          <Text style={styles.logoutText}>Logout</Text>
        </TouchableOpacity>
      </ScrollView>


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
  // Grid/tile layout — replaces list rows for OPERATIONS/STORE/EXPORT.
  tileGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 4 },
  tile: { width: "31.5%", aspectRatio: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 10, alignItems: "center", justifyContent: "center", gap: 6 },
  tileIcon: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  tileLabel: { fontSize: 11, color: colors.textMain, fontWeight: "700", textAlign: "center", lineHeight: 14 },
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
