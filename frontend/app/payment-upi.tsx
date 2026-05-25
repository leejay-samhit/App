// UPI Manual Payment screen (Feb-2026). Replaces the Razorpay flow when
// `branding.payment_methods.razorpay_enabled=false`. Shows Google Pay /
// PhonePe / Paytm buttons that open the same `upi://pay?…` deep link.
// After paying, the user types/pastes the UTR and submits → backend creates
// a PENDING row → user sees "Awaiting approval" until admin verifies.
import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  TextInput,
  Linking,
  Platform,
  KeyboardAvoidingView,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { useBranding } from "../src/branding";
import { colors, radii, spacing, formatINR } from "../src/theme";
import { useSmsUtrListener, isSmsConsentAvailable } from "../src/sms-utr";

type Config = {
  methods_enabled: { razorpay: boolean; upi_manual: boolean };
  amount: number;
  currency: string;
  payee_upi_id: string;
  payee_name: string;
  deeplink_prefix: string;
  pending_payment: any | null;
  registration_paid: boolean;
};

const APPS: { key: "gpay" | "phonepe" | "paytm"; label: string; pkg: string; icon: any; tint: string }[] = [
  { key: "gpay",    label: "Google Pay", pkg: "tez://upi/pay",          icon: "smartphone",    tint: "#1A73E8" },
  { key: "phonepe", label: "PhonePe",    pkg: "phonepe://pay",          icon: "credit-card",   tint: "#5F259F" },
  { key: "paytm",   label: "Paytm",      pkg: "paytmmp://pay",          icon: "smartphone",    tint: "#00BAF2" },
];

export default function UpiManualPayment() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const brand = useBranding();
  const [cfg, setCfg] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [utr, setUtr] = useState("");
  const [appUsed, setAppUsed] = useState<"gpay" | "phonepe" | "paytm" | "other">("other");
  const [note, setNote] = useState("");
  const [smsAuto, setSmsAuto] = useState<null | { utr: string; at: number }>(null);
  const [smsEnabled, setSmsEnabled] = useState<boolean>(true);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Config>("/payment/upi-config");
      setCfg(data);
      if (data.pending_payment?.utr) setUtr(data.pending_payment.utr);
      if (data.pending_payment?.app_used) setAppUsed(data.pending_payment.app_used);
    } catch (e) {
      Alert.alert("Could not load payment options", formatApiError(e));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // Poll for status update so user sees "Approved" the moment admin approves.
  useEffect(() => {
    if (!cfg?.pending_payment || cfg.pending_payment.status !== "PENDING") return;
    const t = setInterval(async () => {
      try {
        const { data } = await api.get<{ payment: any; registration_paid: boolean }>("/payment/upi-manual/status");
        if (data.registration_paid) {
          await refresh();
          router.replace("/(tabs)/dashboard" as any);
        } else if (data.payment?.status === "REJECTED") {
          setCfg((c) => c ? { ...c, pending_payment: data.payment } : c);
          clearInterval(t);
        }
      } catch {}
    }, 6000);
    return () => clearInterval(t);
  }, [cfg?.pending_payment?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- SMS User Consent auto-detect (Android only) ----
  // Listens for an incoming bank SMS for ~5 min after user opens the screen
  // (or taps a UPI app button). When a UTR is detected we auto-fill the input.
  const smsSupported = isSmsConsentAvailable();
  const smsListenerEnabled =
    smsEnabled && smsSupported && !cfg?.registration_paid && !loading;

  useSmsUtrListener(
    smsListenerEnabled,
    ({ utr: detected }) => {
      // Don't overwrite if the user has already typed/submitted the exact same UTR.
      if (detected && detected !== utr) {
        setUtr(detected);
        setSmsAuto({ utr: detected, at: Date.now() });
        try { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); } catch {}
      }
    },
    () => { /* silent; consent timeout / user cancelled */ },
  );


  const openUpiApp = async (appKey: typeof APPS[number]["key"]) => {
    if (!cfg?.deeplink_prefix) {
      Alert.alert(
        "Payment temporarily unavailable",
        "The merchant UPI account is being set up. Please try again in a few minutes or contact support.",
      );
      return;
    }
    setAppUsed(appKey);
    // Try the generic upi:// deep link first (most reliable). App-specific
    // schemes can be tried as a fallback but most chooser dialogs include all
    // installed UPI apps when you open the generic upi:// URL.
    const url = cfg.deeplink_prefix + `&tn=${encodeURIComponent("Registration fee")}`;
    try {
      const can = await Linking.canOpenURL(url);
      if (can) {
        await Linking.openURL(url);
      } else if (Platform.OS === "web") {
        Alert.alert("Open on mobile", "UPI payments are only supported on a mobile device. Please open the app on your phone to continue.");
      } else {
        Alert.alert("No UPI app found", "Please install Google Pay / PhonePe / Paytm to continue.");
      }
    } catch (e) {
      Alert.alert("Could not open UPI app", String((e as any)?.message || e));
    }
  };

  const copyUpiId = async () => {
    if (!cfg?.payee_upi_id) return;
    await Clipboard.setStringAsync(cfg.payee_upi_id);
    Alert.alert("Copied", `${cfg.payee_upi_id} is on your clipboard.`);
  };

  const submit = async () => {
    if (utr.trim().length < 8) { Alert.alert("UTR too short", "Please enter the UTR (8–22 alphanumeric characters)."); return; }
    setSubmitting(true);
    try {
      await api.post("/payment/upi-manual", {
        utr:      utr.trim().toUpperCase(),
        app_used: appUsed,
        note:     note.trim() || undefined,
      });
      await load();
      Alert.alert("Submitted", "Your payment is pending admin approval. You'll be notified once verified (usually within a few hours).");
    } catch (e) { Alert.alert("Could not submit", formatApiError(e)); }
    finally { setSubmitting(false); }
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }
  if (!cfg) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><Text>Failed to load.</Text></View></SafeAreaView>;
  }
  if (cfg.registration_paid) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <Feather name="check-circle" size={56} color={colors.success} />
          <Text style={styles.h1}>You're already paid</Text>
          <TouchableOpacity onPress={() => router.replace("/(tabs)/dashboard" as any)} style={styles.primaryBtn}>
            <Text style={styles.primaryBtnText}>Go to dashboard</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const pending = cfg.pending_payment;
  const isPending  = pending?.status === "PENDING";
  const isRejected = pending?.status === "REJECTED";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">

          {/* Header */}
          <View style={styles.header}>
            <Text style={styles.eyebrow}>{(brand.app_name || "App").toUpperCase()}</Text>
            <Text style={styles.h1}>Pay {formatINR(cfg.amount)} to activate</Text>
            <Text style={styles.subtle}>UPI manual payment · approval by admin</Text>
          </View>

          {/* Pending banner */}
          {isPending ? (
            <View style={[styles.banner, { backgroundColor: "#FFF7E6", borderColor: "#B85F0044" }]}>
              <Feather name="clock" size={18} color="#B85F00" />
              <View style={{ flex: 1 }}>
                <Text style={[styles.bannerTitle, { color: "#B85F00" }]}>Awaiting admin approval</Text>
                <Text style={styles.bannerSub}>UTR · {pending.utr}{pending.app_used ? ` · ${pending.app_used.toUpperCase()}` : ""}</Text>
                <Text style={[styles.bannerSub, { fontStyle: "italic", marginTop: 4 }]}>You can update the UTR below if you submitted the wrong one.</Text>
              </View>
            </View>
          ) : isRejected ? (
            <View style={[styles.banner, { backgroundColor: "#FFE4E4", borderColor: "#B3261E44" }]}>
              <Feather name="alert-triangle" size={18} color="#B3261E" />
              <View style={{ flex: 1 }}>
                <Text style={[styles.bannerTitle, { color: "#B3261E" }]}>Previous submission rejected</Text>
                <Text style={styles.bannerSub}>{pending.rejection_reason || "Please re-submit with the correct UTR."}</Text>
              </View>
            </View>
          ) : null}

          {/* Step 1 — pay via UPI app */}
          <View style={styles.step}>
            <View style={styles.stepHeader}>
              <View style={styles.stepNum}><Text style={styles.stepNumText}>1</Text></View>
              <Text style={styles.stepTitle}>Pay {formatINR(cfg.amount)} via your UPI app</Text>
            </View>
            <Text style={styles.subtle}>Tap any app — the same UPI request opens. After paying, copy the UTR from the success screen.</Text>
            <View style={styles.appsRow}>
              {APPS.map((a) => (
                <TouchableOpacity key={a.key} onPress={() => openUpiApp(a.key)} style={[styles.appBtn, { borderColor: a.tint + "55" }]} testID={`pay-${a.key}`}>
                  <View style={[styles.appIcon, { backgroundColor: a.tint + "1A" }]}>
                    <Feather name={a.icon} size={22} color={a.tint} />
                  </View>
                  <Text style={[styles.appLabel, { color: a.tint }]}>{a.label}</Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Payee identity — name only (UPI ID intentionally hidden from end user) */}
            <View style={styles.upiIdRow}>
              <View style={[styles.payeeAvatar, { backgroundColor: colors.primary + "22" }]}>
                <Feather name="user" size={18} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.upiIdLabel}>Paying to</Text>
                <Text style={styles.upiIdValue}>{cfg.payee_name || brand.app_name || "App"}</Text>
              </View>
              <View style={styles.verifiedBadge}>
                <Feather name="check-circle" size={12} color={colors.success} />
                <Text style={styles.verifiedText}>Verified merchant</Text>
              </View>
            </View>
          </View>

          {/* Step 2 — submit UTR */}
          <View style={styles.step}>
            <View style={styles.stepHeader}>
              <View style={styles.stepNum}><Text style={styles.stepNumText}>2</Text></View>
              <Text style={styles.stepTitle}>Submit the UTR for approval</Text>
            </View>
            <Text style={styles.subtle}>After your UPI app shows "Payment Successful", paste the UTR / Transaction ID below. Admin will verify against the bank statement.</Text>

            {/* SMS auto-detect status (Android only) */}
            {smsSupported && !cfg.registration_paid ? (
              <View style={[styles.smsRow, smsAuto && styles.smsRowActive]}>
                <Feather
                  name={smsAuto ? "check-circle" : smsListenerEnabled ? "radio" : "bell-off"}
                  size={16}
                  color={smsAuto ? colors.success : smsListenerEnabled ? colors.primary : colors.textMuted}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.smsTitle}>
                    {smsAuto ? "UTR auto-filled from SMS" : smsListenerEnabled ? "Auto-fill UTR from bank SMS" : "SMS auto-fill paused"}
                  </Text>
                  <Text style={styles.smsSub}>
                    {smsAuto
                      ? `Detected ${smsAuto.utr} — please verify before submitting.`
                      : smsListenerEnabled
                        ? "When your bank SMS arrives, tap Allow on the system prompt and the UTR will fill itself."
                        : "Re-enable to listen for incoming bank SMS."}
                  </Text>
                </View>
                <TouchableOpacity onPress={() => setSmsEnabled((v) => !v)} style={styles.smsToggle} testID="sms-toggle">
                  <Text style={styles.smsToggleText}>{smsListenerEnabled ? "Off" : "On"}</Text>
                </TouchableOpacity>
              </View>
            ) : null}

            <Text style={styles.label}>UTR / Reference Number</Text>
            <TextInput
              value={utr}
              onChangeText={(t) => setUtr(t.replace(/[^A-Za-z0-9]/g, "").toUpperCase().slice(0, 22))}
              placeholder="e.g. 312345678901"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="characters"
              maxLength={22}
              editable={!submitting}
              style={styles.input}
              testID="utr-input"
            />

            <Text style={styles.label}>I paid via</Text>
            <View style={styles.pillRow}>
              {(["gpay","phonepe","paytm","other"] as const).map((k) => (
                <TouchableOpacity
                  key={k}
                  onPress={() => setAppUsed(k)}
                  style={[styles.pill, appUsed === k && styles.pillActive]}
                  testID={`appused-${k}`}
                >
                  <Text style={[styles.pillText, appUsed === k && { color: "#fff" }]}>
                    {k === "gpay" ? "G Pay" : k === "phonepe" ? "PhonePe" : k === "paytm" ? "Paytm" : "Other"}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.label}>Note for admin (optional)</Text>
            <TextInput
              value={note}
              onChangeText={setNote}
              placeholder="Anything that may help verify (e.g. payer name if different)"
              placeholderTextColor={colors.textMuted}
              multiline
              maxLength={300}
              editable={!submitting}
              style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]}
              testID="note-input"
            />

            <TouchableOpacity onPress={submit} disabled={submitting} style={[styles.primaryBtn, submitting && { opacity: 0.6 }]} testID="submit-utr">
              <Feather name={isPending ? "refresh-cw" : "send"} size={16} color="#fff" />
              <Text style={styles.primaryBtnText}>{submitting ? "Submitting…" : isPending ? "Update UTR" : "Submit for approval"}</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.fineprint}>
            • Your account stays in PENDING until admin verifies the UTR against the bank statement.{"\n"}
            • Do NOT pay any amount other than {formatINR(cfg.amount)}.{"\n"}
            • If your payment fails, the bank will auto-refund within 1–3 working days.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 14 },
  container: { padding: spacing.screen, paddingBottom: 80 },
  header: { marginBottom: 16 },
  eyebrow: { fontSize: 11, fontWeight: "900", color: colors.textMuted, letterSpacing: 1.6 },
  h1: { fontSize: 26, fontWeight: "900", color: colors.textMain, letterSpacing: -0.5, marginTop: 6 },
  subtle: { fontSize: 13, color: colors.textMuted, lineHeight: 19, marginTop: 6 },

  banner: { flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 14, borderRadius: 14, borderWidth: 1, marginBottom: 14 },
  bannerTitle: { fontSize: 14, fontWeight: "900" },
  bannerSub:   { fontSize: 12, color: colors.textMuted, marginTop: 2 },

  step: { padding: 16, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, marginBottom: 14 },
  stepHeader: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 },
  stepNum: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  stepNumText: { color: "#fff", fontWeight: "900", fontSize: 13 },
  stepTitle: { fontSize: 15, fontWeight: "900", color: colors.textMain, flex: 1 },

  appsRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  appBtn: { flex: 1, alignItems: "center", paddingVertical: 12, gap: 8, borderRadius: 14, borderWidth: 1.5, backgroundColor: colors.surface },
  appIcon: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  appLabel: { fontSize: 12, fontWeight: "900", letterSpacing: 0.3 },

  upiIdRow: { flexDirection: "row", alignItems: "center", marginTop: 14, padding: 12, borderRadius: 12, backgroundColor: colors.surfaceMuted, gap: 12 },
  upiIdLabel: { fontSize: 10, color: colors.textMuted, fontWeight: "800", letterSpacing: 0.5 },
  upiIdValue: { fontSize: 16, fontWeight: "900", color: colors.textMain, marginTop: 2 },
  upiIdName:  { fontSize: 11, color: colors.textMuted, fontWeight: "700", marginTop: 2 },
  payeeAvatar: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center" },
  verifiedBadge: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, backgroundColor: colors.success + "1A" },
  verifiedText: { fontSize: 10, fontWeight: "800", color: colors.success, letterSpacing: 0.2 },

  label: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 0.5, marginTop: 12, marginBottom: 6 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, fontWeight: "700", color: colors.textMain, backgroundColor: colors.surface, fontVariant: ["tabular-nums"] },

  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { fontSize: 12, fontWeight: "800", color: colors.textMain },

  primaryBtn: { marginTop: 16, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 14, borderRadius: 999 },
  primaryBtnText: { color: "#fff", fontWeight: "900", fontSize: 14, letterSpacing: 0.3 },

  fineprint: { fontSize: 11, color: colors.textMuted, lineHeight: 17, marginTop: 16, fontStyle: "italic" },

  smsRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginTop: 12, padding: 12, borderRadius: 12,
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  smsRowActive: { backgroundColor: "#E7F8EE", borderColor: "#16A34A55" },
  smsTitle: { fontSize: 12, fontWeight: "900", color: colors.textMain, letterSpacing: 0.2 },
  smsSub:   { fontSize: 11, color: colors.textMuted, lineHeight: 15, marginTop: 2 },
  smsToggle:{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  smsToggleText: { fontSize: 11, fontWeight: "900", color: colors.textMain, letterSpacing: 0.4 },
});
