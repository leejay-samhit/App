import { useState, useEffect, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Alert,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

export default function ProfileScreen() {
  const {
    user,
    logout,
    refresh,
    biometricAvailable,
    biometricReady,
    enableBiometric,
    disableBiometric,
  } = useAuth();
  const router = useRouter();
  const [upi, setUpi] = useState("");
  const [bank, setBank] = useState("");
  const [ifsc, setIfsc] = useState("");
  const [holder, setHolder] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [bioBusy, setBioBusy] = useState(false);

  const onToggleBiometric = useCallback(async () => {
    setBioBusy(true);
    try {
      if (biometricReady) {
        await disableBiometric();
        Alert.alert("Fingerprint login disabled", "You'll need to use your password to sign in next time.");
      } else {
        await enableBiometric();
        Alert.alert(
          "Fingerprint login enabled",
          "Next time, just tap 'Login with Fingerprint' on the login screen.",
        );
      }
    } catch (e: any) {
      Alert.alert("Couldn't update fingerprint login", e?.message || "Unknown error");
    } finally {
      setBioBusy(false);
    }
  }, [biometricReady, enableBiometric, disableBiometric]);

  useEffect(() => {
    setUpi(user?.upi_id || "");
    setBank(user?.bank_account || "");
    setIfsc(user?.ifsc || "");
    setHolder(user?.account_holder || "");
  }, [user]);

  const onSave = async () => {
    setSaving(true);
    setMsg("");
    try {
      await api.post("/users/me/bank", {
        upi_id: upi.trim() || null,
        bank_account: bank.trim() || null,
        ifsc: ifsc.trim() || null,
        account_holder: holder.trim() || null,
      });
      await refresh();
      setMsg("Saved successfully");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const onLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try { await refresh(); } finally { setRefreshing(false); }
  }, [refresh]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView
          contentContainerStyle={styles.container}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
        >
          <GradientCard variant="royal" style={{ marginBottom: spacing.cardPad, padding: 24 }}>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <View style={{ width: 64, height: 64, borderRadius: 32, backgroundColor: "rgba(255,255,255,0.2)", alignItems: "center", justifyContent: "center", marginRight: 16, borderWidth: 2, borderColor: "rgba(255,255,255,0.4)" }}>
                <Text style={{ fontSize: 28, fontWeight: "800", color: "#fff" }}>{(user?.name || "U").charAt(0).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.7)", fontWeight: "700" }}>PROFILE</Text>
                <Text style={{ fontSize: 22, fontWeight: "800", color: "#fff", letterSpacing: -0.5, marginTop: 4 }} numberOfLines={1}>{user?.name}</Text>
                <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 2 }} numberOfLines={1}>{user?.email}</Text>
              </View>
            </View>
            <View style={{ flexDirection: "row", marginTop: 16, gap: 8 }}>
              <View style={{ backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8 }}>
                <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.7)", fontWeight: "700", letterSpacing: 1 }}>REF CODE</Text>
                <Text style={{ fontSize: 14, fontWeight: "800", color: "#fff", letterSpacing: 1 }}>{user?.referral_code}</Text>
              </View>
              {(user as any)?.is_vendor && (
                <View style={{ backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, justifyContent: "center" }}>
                  <Text style={{ fontSize: 11, fontWeight: "700", color: "#fff", letterSpacing: 0.5 }}>🛍️ VENDOR</Text>
                </View>
              )}
            </View>
          </GradientCard>

          {/* ───── ACCOUNT GROUP ───── */}
          <Text style={styles.groupLabel}>ACCOUNT</Text>
          <View style={styles.groupCard}>
            <TouchableOpacity onPress={() => router.push("/kyc")} style={styles.rowItem} testID="profile-kyc-link">
              <View style={[styles.kycDot, { backgroundColor: (user as any)?.kyc_status === "approved" ? colors.success : (user as any)?.kyc_status === "pending" ? colors.warning : (user as any)?.kyc_status === "rejected" ? "#B3261E" : "#94A3B8" }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>KYC Verification</Text>
                <Text style={styles.kycSub}>{(user as any)?.kyc_status ? ((user as any).kyc_status as string).toUpperCase() : "NOT SUBMITTED"}</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/edit-address" as any)} style={styles.rowItem} testID="profile-address-link">
              <View style={[styles.kycDot, { backgroundColor: "#0EA5E9" }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>My Address</Text>
                <Text style={styles.kycSub}>{(user as any)?.address ? `${(user as any).address || ""}${(user as any).city ? ", " + (user as any).city : ""}`.slice(0, 50) || "NOT SET" : "NOT SET — TAP TO ADD"}</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/tickets" as any)} style={styles.rowItem} testID="profile-tickets-link">
              <View style={[styles.kycDot, { backgroundColor: colors.primary }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Support &amp; Help</Text>
                <Text style={styles.kycSub}>RAISE A TICKET · MY CONVERSATIONS</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/more" as any)} style={styles.rowItem} testID="profile-more-link">
              <View style={[styles.kycDot, { backgroundColor: colors.textMuted }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>More</Text>
                <Text style={styles.kycSub}>ABOUT · CONTACT · LEGAL &amp; POLICIES</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          </View>

          {/* ───── EARN MORE GROUP ───── */}
          <Text style={styles.groupLabel}>EARN MORE</Text>
          <View style={styles.groupCard}>
            <TouchableOpacity
              onPress={() => router.push((((user as any)?.is_vendor && (user as any)?.vendor_status === "approved") ? "/vendor/dashboard" : "/vendor/apply") as any)}
              style={styles.rowItem}
              testID="profile-vendor-link"
            >
              <View style={[styles.kycDot, { backgroundColor: ((user as any)?.is_vendor && (user as any)?.vendor_status === "approved") ? colors.success : (user as any)?.vendor_status === "pending" ? colors.warning : (user as any)?.vendor_status === "suspended" ? "#B3261E" : "#94A3B8" }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>{((user as any)?.is_vendor && (user as any)?.vendor_status === "approved") ? "Vendor Panel" : "Become a Vendor"}</Text>
                <Text style={styles.kycSub}>{(user as any)?.vendor_status ? ((user as any).vendor_status as string).toUpperCase() : "SELL ON OUR PLATFORM"}</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            {/* Service Provider entry — moved here from the Services tab banner. */}
            <TouchableOpacity
              onPress={() => router.push("/services/apply" as any)}
              style={styles.rowItem}
              testID="profile-service-provider-link"
            >
              <View style={[styles.kycDot, { backgroundColor: (user as any)?.service_provider_status === "approved" ? colors.success : (user as any)?.service_provider_status === "pending" ? colors.warning : (user as any)?.service_provider_status === "rejected" ? "#B3261E" : "#94A3B8" }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>
                  {(user as any)?.service_provider_status === "approved" ? "You're a Service Provider" : "Become a Service Provider"}
                </Text>
                <Text style={styles.kycSub}>
                  {(user as any)?.service_provider_status === "approved" ? "TAP TO UPDATE OR VIEW BOOKINGS"
                    : (user as any)?.service_provider_status === "pending" ? "APPLICATION UNDER REVIEW"
                    : (user as any)?.service_provider_status === "rejected" ? "APPLY AGAIN"
                    : "EARN — LIST YOUR SERVICE"}
                </Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            {/* Provider availability — only relevant when already an approved service provider. */}
            {(user as any)?.service_provider_status === "approved" ? (
              <>
                <View style={styles.rowDivider} />
                <TouchableOpacity
                  onPress={() => router.push("/service-availability" as any)}
                  style={styles.rowItem}
                  testID="profile-availability-link"
                >
                  {(() => {
                    const av = (user as any)?.availability_status || "available";
                    const c = av === "available" ? "#16A34A" : av === "busy" ? "#F59E0B" : "#9CA3AF";
                    return <View style={[styles.kycDot, { backgroundColor: c }]} />;
                  })()}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.kycTitle}>My Availability</Text>
                    <Text style={styles.kycSub}>
                      {((user as any)?.availability_status || "available").toUpperCase()} — TAP TO CHANGE
                    </Text>
                  </View>
                  <Feather name="chevron-right" size={18} color={colors.textMuted} />
                </TouchableOpacity>
              </>
            ) : null}
          </View>

          <Text style={styles.groupLabel}>PAYOUT DETAILS</Text>
          <View style={styles.payoutCard}>
            <Text style={styles.helperText}>Add UPI or bank details to enable withdrawals.</Text>

            <View style={styles.formGroup}>
              <Text style={styles.label}>UPI ID</Text>
              <TextInput testID="profile-upi" value={upi} onChangeText={setUpi} placeholder="name@upi" placeholderTextColor={colors.textMuted} autoCapitalize="none" style={styles.input} />
            </View>
            <View style={styles.formGroup}>
              <Text style={styles.label}>Bank account number</Text>
              <TextInput testID="profile-bank" value={bank} onChangeText={setBank} placeholder="XXXXXXXXXX" placeholderTextColor={colors.textMuted} keyboardType="numeric" style={styles.input} />
            </View>
            <View style={styles.formGroup}>
              <Text style={styles.label}>IFSC code</Text>
              <TextInput testID="profile-ifsc" value={ifsc} onChangeText={(t) => setIfsc(t.toUpperCase())} placeholder="HDFC0000123" placeholderTextColor={colors.textMuted} autoCapitalize="characters" style={styles.input} />
            </View>
            <View style={styles.formGroup}>
              <Text style={styles.label}>Account holder name</Text>
              <TextInput testID="profile-holder" value={holder} onChangeText={setHolder} placeholder="As per bank record" placeholderTextColor={colors.textMuted} style={styles.input} />
            </View>

            {msg ? <Text style={[styles.msg, { color: msg === "Saved successfully" ? colors.success : "#B3261E" }]} testID="profile-msg">{msg}</Text> : null}

            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.7 }]} testID="profile-save">
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={styles.saveBtnText}>Save details</Text>}
            </TouchableOpacity>
          </View>

          {/* Fingerprint / Biometric login card — only on supported devices */}
          {biometricAvailable ? (
            <View style={styles.bioCard}>
              <View style={styles.bioCardHead}>
                <View style={styles.bioIcon}>
                  <Feather name={biometricReady ? "shield" : "unlock"} size={18} color={colors.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.bioCardTitle}>
                    {biometricReady ? "Fingerprint login enabled" : "Fingerprint login"}
                  </Text>
                  <Text style={styles.bioCardSub}>
                    {biometricReady
                      ? "Tap your fingerprint to sign in next time — no password needed."
                      : "Skip typing your password — sign in with your phone's fingerprint or Face ID."}
                  </Text>
                </View>
              </View>
              <TouchableOpacity
                onPress={onToggleBiometric}
                disabled={bioBusy}
                style={[styles.bioToggleBtn, biometricReady && styles.bioToggleBtnOff, bioBusy && { opacity: 0.6 }]}
                testID="profile-toggle-biometric"
              >
                {bioBusy ? (
                  <ActivityIndicator size="small" color={biometricReady ? "#B3261E" : colors.primaryFg} />
                ) : (
                  <Text style={[styles.bioToggleBtnText, biometricReady && { color: "#B3261E" }]}>
                    {biometricReady ? "Disable Fingerprint Login" : "Enable Fingerprint Login"}
                  </Text>
                )}
              </TouchableOpacity>
            </View>
          ) : null}

          <TouchableOpacity onPress={onLogout} style={styles.logoutBtn} testID="profile-logout">
            <Feather name="log-out" size={16} color="#B3261E" />
            <Text style={styles.logoutText}>Logout</Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 60 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  subtitle: { fontSize: 14, color: colors.textMuted, marginTop: 4, marginBottom: 20 },
  codeCard: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.primary, borderRadius: radii.card, padding: 20, marginBottom: 28 },
  codeLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 2, fontWeight: "700" },
  code: { color: colors.primaryFg, fontSize: 26, fontWeight: "800", letterSpacing: 3, marginTop: 4 },
  kycCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 16, borderRadius: 16, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginBottom: 28 },
  // ─── Phase 2B UX polish: grouped settings list ───
  // Section labels above logical groups (ACCOUNT, EARN MORE).
  groupLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: spacing.sectionGap, marginBottom: 10, paddingHorizontal: 4 },
  // Group container: white card holding several rows separated by hairlines.
  // Replaces the previous pattern where each row was its own card with
  // marginBottom: 28 — created a "stranded" disconnected feel.
  groupCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, overflow: "hidden" },
  // Single row inside a groupCard.
  rowItem: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: spacing.cardPad, paddingVertical: 14 },
  // Hairline divider between rows in the same group.
  rowDivider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.border, marginLeft: spacing.cardPad + 22 /* dot + gap */ },
  kycDot: { width: 10, height: 10, borderRadius: 5 },
  kycTitle: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  kycSub: { fontSize: 11, color: colors.textMuted, marginTop: 2, letterSpacing: 1, fontWeight: "700" },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: spacing.sectionGap, marginBottom: 6 },
  // White card wrapping the entire payout-details form so it visually
  // belongs to the same group as the section label above (matches the
  // groupCard pattern used by ACCOUNT / EARN MORE).
  payoutCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: spacing.cardPad },
  helperText: { fontSize: 13, color: colors.textMuted, marginBottom: 16 },
  formGroup: { marginBottom: 14 },
  label: { fontSize: 12, color: colors.textMuted, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 15, color: colors.textMain },
  msg: { fontSize: 13, marginTop: 8 },
  saveBtn: { backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 16, alignItems: "center", marginTop: 16 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
  // Logout: subtle outlined button instead of naked text — clearer affordance
  // and visually anchors the bottom of the screen.
  logoutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: spacing.sectionGap, marginBottom: 8, paddingVertical: 14, borderRadius: radii.button, borderWidth: 1, borderColor: "#F2B8B5", backgroundColor: "#FFF6F5" },
  // Fingerprint / Biometric card
  bioCard: {
    marginTop: spacing.sectionGap,
    padding: 16,
    borderRadius: radii.card,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bioCardHead: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  bioIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  bioCardTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginBottom: 2 },
  bioCardSub: { fontSize: 12, color: colors.textMuted, lineHeight: 17 },
  bioToggleBtn: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: radii.button,
    backgroundColor: colors.primary,
    alignItems: "center",
  },
  bioToggleBtnOff: { backgroundColor: "#FFF6F5", borderWidth: 1, borderColor: "#F2B8B5" },
  bioToggleBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14, letterSpacing: 0.3 },
  logoutText: { color: "#B3261E", fontSize: 14, fontWeight: "700" },
});
