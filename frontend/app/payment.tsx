import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Image, ScrollView, Alert, Modal } from "react-native";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing, formatINR } from "../src/theme";

type PayMethod = "upi" | "card" | "netbanking";

type PayConfig = {
  key_id: string;
  is_mock: boolean;
  amount: number;
  amount_paise: number;
  currency: string;
  registration_paid: boolean;
  approval_status: string;
  attempts_used: number;
  attempts_remaining: number;
  max_attempts: number;
  prefill: { name?: string; email?: string; contact?: string };
  description: string;
};

export default function Payment() {
  const { user, refresh, logout } = useAuth();
  const router = useRouter();

  const [config, setConfig] = useState<PayConfig | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [method, setMethod] = useState<PayMethod>("upi");
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [stage, setStage] = useState<"idle" | "creating-order" | "processing-payment" | "verifying" | "success" | "failure">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadConfig = useCallback(async () => {
    try {
      const { data } = await api.get<PayConfig>("/payment/config");
      setConfig(data);
    } catch (e) {
      Alert.alert("Couldn't load payment info", formatApiError(e));
    } finally {
      setLoadingConfig(false);
    }
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  const onStartCheckout = () => {
    if (!config) return;
    if (config.attempts_remaining <= 0) {
      Alert.alert(
        "Maximum attempts reached",
        `You've used all ${config.max_attempts} payment attempts. Please contact support.`,
      );
      return;
    }
    setErrorMsg(null);
    setStage("idle");
    setCheckoutOpen(true);
  };

  const runMockCheckout = async () => {
    if (!config) return;
    setProcessing(true);
    setErrorMsg(null);
    try {
      // 1) Create order
      setStage("creating-order");
      const orderRes = await api.post<{ order_id: string; amount_paise: number; currency: string; key_id: string; is_mock: boolean }>(
        "/payment/create-order",
      );
      const orderId = orderRes.data.order_id;

      // 2) Simulate gateway checkout UX (2s)
      setStage("processing-payment");
      await new Promise((r) => setTimeout(r, 1800));

      // 3) Verify
      setStage("verifying");
      const mockPaymentId = `pay_MOCK_${Math.random().toString(36).slice(2, 14)}`;
      const mockSignature = `sig_MOCK_${Math.random().toString(36).slice(2, 20)}`;
      await api.post("/payment/verify", {
        razorpay_order_id: orderId,
        razorpay_payment_id: mockPaymentId,
        razorpay_signature: mockSignature,
      });

      setStage("success");
      await refresh();
      // Brief success UI then route to pending approval
      setTimeout(() => {
        setCheckoutOpen(false);
        router.replace("/pending-approval" as any);
      }, 1200);
    } catch (e) {
      // Record failure for the attempt counter + message
      const reason = formatApiError(e);
      setErrorMsg(reason);
      setStage("failure");
      try {
        const failRes = await api.post<{ attempts_used: number; attempts_remaining: number; archived: boolean }>(
          "/payment/failure",
          { reason },
        );
        // If archived after 3 strikes → refresh user so index.tsx can route them to pending-approval (showing "Rejected" UI).
        if (failRes.data.archived) {
          await refresh();
          setTimeout(async () => {
            setCheckoutOpen(false);
            router.replace("/pending-approval" as any);
          }, 1500);
        } else {
          await loadConfig();
        }
      } catch {
        // silent
      }
    } finally {
      setProcessing(false);
    }
  };

  const onMethodTap = (m: PayMethod) => {
    if (processing) return;
    setMethod(m);
  };

  if (loadingConfig || !config) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>
      </SafeAreaView>
    );
  }

  const attemptsLeft = config.attempts_remaining;
  const attemptsWarn = attemptsLeft <= 1;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.topRow}>
          <TouchableOpacity onPress={logout} style={styles.iconBtn} testID="payment-logout">
            <Feather name="log-out" size={18} color={colors.textMain} />
          </TouchableOpacity>
        </View>

        <Image
          source={{ uri: "https://images.pexels.com/photos/5849577/pexels-photo-5849577.jpeg" }}
          style={styles.hero}
        />
        <Text style={styles.overline}>ACTIVATION</Text>
        <Text style={styles.h1}>Complete your{"\n"}registration</Text>
        <Text style={styles.subtitle}>
          Pay the one-time {formatINR(config.amount)} activation fee to unlock your referral code and start earning.
        </Text>

        <View style={styles.amountCard}>
          <Text style={styles.amountLabel}>AMOUNT TO PAY</Text>
          <Text style={styles.amount}>{formatINR(config.amount)}</Text>
          <View style={styles.divider} />
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Account</Text>
            <Text style={styles.rowValue} numberOfLines={1}>{config.prefill.email || user?.email}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Your code</Text>
            <Text style={styles.rowValueMono}>{(user as any)?.referral_code}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Gateway</Text>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Feather name="shield" size={12} color={colors.primary} />
              <Text style={styles.rowValue}>Razorpay{config.is_mock ? " · Sandbox" : ""}</Text>
            </View>
          </View>
        </View>

        {attemptsWarn && (
          <View style={styles.warnBox}>
            <Feather name="alert-triangle" size={16} color={colors.warning} />
            <Text style={styles.warnText}>
              {attemptsLeft === 0
                ? `You have used all ${config.max_attempts} attempts.`
                : `${attemptsLeft} attempt${attemptsLeft === 1 ? "" : "s"} remaining before auto-rejection.`}
            </Text>
          </View>
        )}

        <TouchableOpacity
          testID="payment-pay-button"
          onPress={onStartCheckout}
          disabled={attemptsLeft <= 0}
          style={[styles.payBtn, attemptsLeft <= 0 && { opacity: 0.5 }]}
        >
          <Feather name="zap" size={18} color={colors.accentFg} />
          <Text style={styles.payBtnText}> Pay {formatINR(config.amount)}</Text>
        </TouchableOpacity>

        <Text style={styles.note}>
          🔒 Secured by Razorpay. {config.is_mock ? "Sandbox mode — no real charge." : "Your payment is processed securely."}
        </Text>
      </ScrollView>

      {/* Razorpay-style checkout modal */}
      <Modal visible={checkoutOpen} transparent animationType="slide" onRequestClose={() => !processing && setCheckoutOpen(false)}>
        <View style={styles.rzpOverlay}>
          <View style={styles.rzpSheet}>
            {/* Header */}
            <View style={styles.rzpHeader}>
              <View style={styles.rzpLogo}>
                <Text style={styles.rzpLogoText}>Razorpay</Text>
              </View>
              {!processing && (
                <TouchableOpacity onPress={() => setCheckoutOpen(false)} testID="rzp-close">
                  <Feather name="x" size={22} color={colors.textMain} />
                </TouchableOpacity>
              )}
            </View>

            {/* Merchant row */}
            <View style={styles.rzpMerchantRow}>
              <View style={styles.rzpMerchantIcon}>
                <Feather name="users" size={18} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rzpMerchantName}>NetworkPay</Text>
                <Text style={styles.rzpMerchantDesc}>{config.description}</Text>
              </View>
              <Text style={styles.rzpAmount}>{formatINR(config.amount)}</Text>
            </View>

            {/* Stage UI */}
            {stage === "success" ? (
              <View style={styles.rzpStage}>
                <View style={[styles.rzpStatusIcon, { backgroundColor: "#E6F4EE" }]}>
                  <Feather name="check" size={28} color={colors.success} />
                </View>
                <Text style={styles.rzpStageTitle}>Payment successful</Text>
                <Text style={styles.rzpStageBody}>Redirecting you to the approval screen…</Text>
              </View>
            ) : stage === "failure" ? (
              <View style={styles.rzpStage}>
                <View style={[styles.rzpStatusIcon, { backgroundColor: "#FCE9E5" }]}>
                  <Feather name="x" size={28} color="#B3261E" />
                </View>
                <Text style={styles.rzpStageTitle}>Payment failed</Text>
                <Text style={[styles.rzpStageBody, { textAlign: "center" }]}>
                  {errorMsg || "Something went wrong. Please try again."}
                </Text>
                {config.attempts_remaining > 0 ? (
                  <TouchableOpacity onPress={runMockCheckout} style={styles.rzpPrimaryBtn} testID="rzp-retry">
                    <Text style={styles.rzpPrimaryBtnText}>Try again ({config.attempts_remaining} left)</Text>
                  </TouchableOpacity>
                ) : (
                  <TouchableOpacity onPress={() => setCheckoutOpen(false)} style={[styles.rzpPrimaryBtn, { backgroundColor: "#B3261E" }]}>
                    <Text style={styles.rzpPrimaryBtnText}>Close</Text>
                  </TouchableOpacity>
                )}
              </View>
            ) : processing ? (
              <View style={styles.rzpStage}>
                <ActivityIndicator size="large" color={colors.primary} />
                <Text style={[styles.rzpStageTitle, { marginTop: 12 }]}>
                  {stage === "creating-order" && "Creating secure order…"}
                  {stage === "processing-payment" && "Processing your payment…"}
                  {stage === "verifying" && "Verifying payment…"}
                </Text>
                <Text style={styles.rzpStageBody}>Please don't close this screen.</Text>
              </View>
            ) : (
              <>
                {/* Method picker */}
                <Text style={styles.rzpMethodLabel}>PAYMENT METHOD</Text>
                <View style={styles.rzpMethodList}>
                  {([
                    { key: "upi", label: "UPI", hint: "GPay, PhonePe, Paytm", icon: "smartphone" },
                    { key: "card", label: "Card", hint: "Credit / Debit", icon: "credit-card" },
                    { key: "netbanking", label: "Net Banking", hint: "All major banks", icon: "globe" },
                  ] as { key: PayMethod; label: string; hint: string; icon: any }[]).map((m) => {
                    const active = method === m.key;
                    return (
                      <TouchableOpacity
                        key={m.key}
                        onPress={() => onMethodTap(m.key)}
                        style={[styles.rzpMethodRow, active && styles.rzpMethodRowActive]}
                        testID={`rzp-method-${m.key}`}
                      >
                        <View style={[styles.rzpMethodIcon, active && { backgroundColor: colors.primary }]}>
                          <Feather name={m.icon} size={16} color={active ? "#fff" : colors.textMain} />
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.rzpMethodTitle}>{m.label}</Text>
                          <Text style={styles.rzpMethodHint}>{m.hint}</Text>
                        </View>
                        <Feather name={active ? "check-circle" : "circle"} size={18} color={active ? colors.primary : colors.textMuted} />
                      </TouchableOpacity>
                    );
                  })}
                </View>

                <TouchableOpacity onPress={runMockCheckout} style={styles.rzpPrimaryBtn} testID="rzp-pay-now">
                  <Feather name="lock" size={15} color="#fff" />
                  <Text style={styles.rzpPrimaryBtnText}>  Pay {formatINR(config.amount)} via {method === "upi" ? "UPI" : method === "card" ? "Card" : "Net Banking"}</Text>
                </TouchableOpacity>

                {config.is_mock && (
                  <Text style={styles.rzpSandbox}>Sandbox mode — any tap simulates a successful payment.</Text>
                )}
              </>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 40 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  topRow: { flexDirection: "row", justifyContent: "flex-end", marginBottom: 16 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  hero: { width: "100%", height: 160, borderRadius: 20, marginBottom: 24 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.accent, fontWeight: "700", marginBottom: 10 },
  h1: { fontSize: 32, fontWeight: "800", color: colors.textMain, lineHeight: 38, letterSpacing: -1 },
  subtitle: { fontSize: 15, color: colors.textMuted, marginTop: 12, marginBottom: 24, lineHeight: 22 },
  amountCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 24, marginBottom: 16 },
  amountLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  amount: { fontSize: 44, fontWeight: "800", color: colors.primary, marginTop: 8, letterSpacing: -1.5 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 16 },
  row: { flexDirection: "row", justifyContent: "space-between", marginVertical: 4, alignItems: "center" },
  rowLabel: { color: colors.textMuted, fontSize: 13 },
  rowValue: { color: colors.textMain, fontSize: 13, fontWeight: "600", maxWidth: "60%" },
  rowValueMono: { color: colors.textMain, fontSize: 13, fontWeight: "700", letterSpacing: 1 },
  warnBox: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: "#FFF4E5", borderRadius: 14, padding: 14, marginBottom: 12 },
  warnText: { color: "#7A4A0E", fontSize: 12, fontWeight: "600", flex: 1 },
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.accent, borderRadius: radii.button, paddingVertical: 16, marginTop: 4 },
  payBtnText: { color: colors.accentFg, fontWeight: "800", fontSize: 16 },
  note: { textAlign: "center", color: colors.textMuted, fontSize: 12, marginTop: 16 },

  // Razorpay-style modal
  rzpOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  rzpSheet: { backgroundColor: "#fff", borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, paddingBottom: 32 },
  rzpHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  rzpLogo: { backgroundColor: "#0C2461", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6 },
  rzpLogoText: { color: "#fff", fontWeight: "800", fontSize: 13, letterSpacing: 0.3 },
  rzpMerchantRow: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: "#F5F7FB", padding: 12, borderRadius: 12, marginBottom: 16 },
  rzpMerchantIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  rzpMerchantName: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  rzpMerchantDesc: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  rzpAmount: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  rzpMethodLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginBottom: 8 },
  rzpMethodList: { gap: 8, marginBottom: 16 },
  rzpMethodRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 12, borderWidth: 1, borderColor: "#E5E7EB", backgroundColor: "#fff" },
  rzpMethodRowActive: { borderColor: colors.primary, backgroundColor: "#F5FBF8" },
  rzpMethodIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: "#F5F7FB", alignItems: "center", justifyContent: "center" },
  rzpMethodTitle: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rzpMethodHint: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  rzpPrimaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 14, marginTop: 4 },
  rzpPrimaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  rzpSandbox: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 10 },
  rzpStage: { alignItems: "center", paddingVertical: 28, paddingHorizontal: 8, minHeight: 220, justifyContent: "center" },
  rzpStatusIcon: { width: 56, height: 56, borderRadius: 28, alignItems: "center", justifyContent: "center", marginBottom: 12 },
  rzpStageTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  rzpStageBody: { fontSize: 13, color: colors.textMuted, marginTop: 6, textAlign: "center" },
});
