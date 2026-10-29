import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, ScrollView, Alert, Modal, Platform } from "react-native";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { useBranding } from "../src/branding";
import { colors, radii, spacing, formatINR } from "../src/theme";
import { openRazorpayCheckout, buildRazorpayHtml, RazorpayResult } from "../src/razorpay";
import { SubscriptionHero, SubscriptionBenefits, SubscriptionSplit, SkipSubscriptionButton } from "../src/subscription";
import { SignupGateCard } from "../src/signup-gate-card";

type PayMethod = "upi" | "card" | "netbanking";

type PayConfig = {
  key_id: string;
  is_mock: boolean;
  payment_enabled?: boolean;
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
  const { app_name } = useBranding();
  const router = useRouter();

  // Aug-2026 — only TWO account types exist: Subscriber (Razorpay payment
  // successful) and Non-subscriber ("Continue without subscription").
  // The old UPI-manual / offline-cash subscription paths were removed, so this
  // screen no longer redirects to /payment-upi.

  const [config, setConfig] = useState<PayConfig | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [method, setMethod] = useState<PayMethod>("upi");
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [stage, setStage] = useState<"idle" | "creating-order" | "processing-payment" | "verifying" | "success" | "failure">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  // Oct-2026 owner rule — BOTH payment options stay locked until the mobile
  // number (mandatory) and invite code (optional) are confirmed.
  const [gatePassed, setGatePassed] = useState(false);
  // Native WebView Razorpay checkout state
  const [rzpVisible, setRzpVisible] = useState(false);
  const [rzpHtml, setRzpHtml] = useState<string>("");
  const rzpResolver = useRef<((r: RazorpayResult) => void) | null>(null);

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
    // Belt and braces: the button is already disabled in both of these
    // states, but a stale render must never start a checkout the backend
    // will refuse anyway.
    if (!gatePassed) {
      Alert.alert(
        "Verify your mobile number first",
        "Please confirm your mobile number in Step 1, then choose how to continue.",
      );
      return;
    }
    if (config.payment_enabled === false) {
      Alert.alert(
        "Online payment unavailable",
        "Online payment is being set up. You can continue free for now and pay later from your profile.",
      );
      return;
    }
    if (config.attempts_remaining <= 0) {
      Alert.alert(
        "Maximum attempts reached",
        `You've used all ${config.max_attempts} payment attempts. Please contact support.`,
      );
      return;
    }
    setErrorMsg(null);
    setStage("idle");
    // If live Razorpay keys are configured → open real Razorpay Checkout directly (no mock UI)
    if (!config.is_mock) {
      runLiveCheckout();
      return;
    }
    // Else show Razorpay-styled mock modal
    setCheckoutOpen(true);
  };

  // Native WebView resolves via onMessage → we stash a resolver in a ref
  const openNativeRazorpay = (html: string): Promise<RazorpayResult> => {
    return new Promise((resolve) => {
      rzpResolver.current = resolve;
      setRzpHtml(html);
      setRzpVisible(true);
    });
  };

  const closeNativeRazorpay = () => {
    setRzpVisible(false);
    setTimeout(() => setRzpHtml(""), 250);
  };

  const handleRzpMessage = (raw: string) => {
    let data: any = {};
    try { data = JSON.parse(raw); } catch { data = {}; }
    const resolver = rzpResolver.current;
    rzpResolver.current = null;
    closeNativeRazorpay();
    if (!resolver) return;
    if (data.type === "success") {
      resolver({ ok: true, paymentId: data.payment_id, orderId: data.order_id, signature: data.signature });
    } else if (data.type === "cancel") {
      resolver({ ok: false, cancelled: true });
    } else if (data.type === "failed" || data.type === "error") {
      resolver({ ok: false, error: data.error || "Payment failed", code: data.code });
    } else {
      resolver({ ok: false, error: "Unknown response" });
    }
  };

  // Real Razorpay Checkout flow (Web uses script; Native uses WebView)
  const runLiveCheckout = async () => {
    if (!config) return;
    setProcessing(true);
    setErrorMsg(null);
    setStage("creating-order");
    try {
      // 1) Create order
      const orderRes = await api.post<{ order_id: string; amount_paise: number; currency: string; key_id: string; is_mock: boolean }>(
        "/payment/create-order",
      );
      const orderId = orderRes.data.order_id;

      const rzpOpts = {
        orderId,
        amountPaise: orderRes.data.amount_paise,
        keyId: orderRes.data.key_id,
        name: app_name,
        description: config.description || "Registration fee",
        prefill: {
          name: config.prefill?.name || (user as any)?.name,
          email: config.prefill?.email || (user as any)?.email,
          contact: config.prefill?.contact || (user as any)?.phone,
        },
        themeColor: colors.primary,
      };

      // 2) Open checkout
      setStage("processing-payment");
      let result: RazorpayResult;
      if (Platform.OS === "web") {
        result = await openRazorpayCheckout(rzpOpts);
      } else {
        const html = buildRazorpayHtml(rzpOpts);
        result = await openNativeRazorpay(html);
      }

      if (!result.ok) {
        if (result.cancelled) {
          // User dismissed — treat as abandonment, do NOT count as failure attempt
          setProcessing(false);
          setStage("idle");
          return;
        }
        throw new Error(result.error || "Payment failed");
      }

      // 3) Verify
      setStage("verifying");
      const verifyRes = await api.post<{ approval_status?: string; auto_approved?: boolean; utr?: string }>(
        "/payment/verify",
        {
          razorpay_order_id: result.orderId || orderId,
          razorpay_payment_id: result.paymentId,
          razorpay_signature: result.signature,
        },
      );

      setStage("success");
      setCheckoutOpen(true); // show branded success UI for a moment
      await refresh();
      const approved = verifyRes.data?.approval_status === "approved" || verifyRes.data?.auto_approved;
      setTimeout(() => {
        setCheckoutOpen(false);
        if (approved) {
          router.replace("/(tabs)/dashboard" as any);
        } else {
          router.replace("/pending-approval" as any);
        }
      }, 1200);
    } catch (e) {
      const reason = formatApiError(e);
      setErrorMsg(reason);
      setStage("failure");
      setCheckoutOpen(true);
      try {
        const failRes = await api.post<{ attempts_used: number; attempts_remaining: number; archived: boolean }>(
          "/payment/failure",
          { reason },
        );
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
      const verifyRes = await api.post<{ approval_status?: string; auto_approved?: boolean }>(
        "/payment/verify",
        {
          razorpay_order_id: orderId,
          razorpay_payment_id: mockPaymentId,
          razorpay_signature: mockSignature,
        },
      );

      setStage("success");
      await refresh();
      const approved = verifyRes.data?.approval_status === "approved" || verifyRes.data?.auto_approved;
      // Brief success UI then route based on approval status
      setTimeout(() => {
        setCheckoutOpen(false);
        if (approved) {
          router.replace("/(tabs)/dashboard" as any);
        } else {
          router.replace("/pending-approval" as any);
        }
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
  // Online payment is only offered when the gateway can really take money:
  // live Razorpay keys, or sandbox with mock settlement still switched on.
  const payEnabled = config.payment_enabled !== false;

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={[styles.topRow, { justifyContent: "space-between" }]}>
          {/* A member who came here from inside the app can go back; a brand
              new account has nowhere to go but out. */}
          {(user as any)?.subscription_skipped || user?.registration_paid ? (
            <TouchableOpacity
              onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)/shop" as any))}
              style={styles.iconBtn}
              testID="payment-back"
            >
              <Feather name="arrow-left" size={18} color={colors.textMain} />
            </TouchableOpacity>
          ) : <View style={{ width: 44 }} />}
          <TouchableOpacity onPress={logout} style={styles.iconBtn} testID="payment-logout">
            <Feather name="log-out" size={18} color={colors.textMain} />
          </TouchableOpacity>
        </View>

        {/* Oct-2026 — the owner's registration wording, shown before the
            membership pitch so the purpose of the screen is unmistakable. */}
        <Text style={styles.regTitle}>Complete Your Registration</Text>
        <Text style={styles.regSub}>
          Verify your mobile number to continue setting up your {app_name} account.
        </Text>

        {/* Membership hero + the member benefits + where the money goes */}
        <SubscriptionHero amount={config.amount} appName={app_name} />        <SubscriptionBenefits />
        <SubscriptionSplit />

        {/* Step 1 — mandatory mobile verification (Truecaller or manual) */}
        <SignupGateCard onPassed={() => setGatePassed(true)} />

        {gatePassed && (
          <View style={styles.stepTwo} testID="payment-step-two">
            <Text style={styles.stepTwoLabel}>STEP 2 · CHOOSE HOW TO CONTINUE</Text>
            <Text style={styles.stepTwoSub}>
              Pay once for the member benefits, or continue free — both open your account.
            </Text>
          </View>
        )}

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
          disabled={attemptsLeft <= 0 || !gatePassed || !payEnabled}
          style={[styles.payBtn, (attemptsLeft <= 0 || !gatePassed || !payEnabled) && { opacity: 0.5 }]}
        >
          <Feather name={gatePassed && payEnabled ? "zap" : "lock"} size={18} color={colors.primaryFg} />
          <Text style={styles.payBtnText}> Pay {formatINR(config.amount)}</Text>
        </TouchableOpacity>
        {!payEnabled && (
          <Text style={styles.payDisabledNote}>
            Online payment is being set up. You can continue free for now and pay later from your profile.
          </Text>
        )}

        {/* Free entry — the ₹118 is a subscription, not a wall. Locked until
            the mobile number is confirmed, same as the paid option. */}
        {gatePassed ? (
          <SkipSubscriptionButton amount={config.amount} />
        ) : (
          <View style={styles.lockedSkip} testID="payment-skip-locked">
            <Feather name="lock" size={13} color={colors.textMuted} />
            <Text style={styles.lockedSkipText}>
              Verify your mobile number above to unlock both options
            </Text>
          </View>
        )}

        <Text style={styles.note}>
          🔒 Secured by Razorpay. {config.is_mock ? "Sandbox mode — no real charge." : "Your payment is processed securely."}
          {"\n"}Without the subscription you can still browse and shop — cashback, wallet and withdrawals stay locked.
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
                <Text style={styles.rzpMerchantName}>{app_name}</Text>
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
                  <TouchableOpacity onPress={config.is_mock ? runMockCheckout : runLiveCheckout} style={styles.rzpPrimaryBtn} testID="rzp-retry">
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
                <Text style={styles.rzpStageBody}>Please don&apos;t close this screen.</Text>
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

      {/* Native WebView Razorpay Checkout (iOS / Android) */}
      <Modal visible={rzpVisible} animationType="slide" onRequestClose={() => {
        const resolver = rzpResolver.current;
        rzpResolver.current = null;
        closeNativeRazorpay();
        if (resolver) resolver({ ok: false, cancelled: true });
      }}>
        <SafeAreaView style={{ flex: 1, backgroundColor: "#f5f7fb" }}>
          <View style={styles.rzpNativeHeader}>
            <TouchableOpacity
              onPress={() => {
                const resolver = rzpResolver.current;
                rzpResolver.current = null;
                closeNativeRazorpay();
                if (resolver) resolver({ ok: false, cancelled: true });
              }}
              style={styles.iconBtn}
              testID="rzp-webview-close"
            >
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.rzpNativeTitle}>Secure Payment</Text>
            <View style={{ width: 40 }} />
          </View>
          {Platform.OS !== "web" && rzpHtml ? (
            <WebView
              originWhitelist={["*"]}
              source={{ html: rzpHtml, baseUrl: "https://checkout.razorpay.com" }}
              javaScriptEnabled
              domStorageEnabled
              onMessage={(e) => handleRzpMessage(e.nativeEvent.data)}
              startInLoadingState
              style={{ flex: 1, backgroundColor: "#f5f7fb" }}
            />
          ) : (
            <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>
          )}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 40 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  topRow: { flexDirection: "row", justifyContent: "flex-end", marginBottom: 16 },
  iconBtn: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
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
  payBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 16, marginTop: 4 },
  payBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 16 },
  payDisabledNote: { color: colors.textMuted, fontSize: 12, textAlign: "center", marginTop: 8, lineHeight: 17 },
  // Locked stand-in for the "continue without subscription" button, shown
  // until the signup gate passes.
  lockedSkip: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    minHeight: 48, paddingVertical: 13, paddingHorizontal: 14, marginTop: 10,
    borderRadius: radii.input, borderWidth: 1, borderColor: colors.border,
    borderStyle: "dashed", backgroundColor: colors.surfaceMuted,
  },
  lockedSkipText: { flex: 1, fontSize: 12, color: colors.textMuted, fontWeight: "700" },
  regTitle: { fontSize: 22, fontWeight: "900", color: colors.textMain, marginTop: 4 },
  regSub: { fontSize: 14, color: colors.textMuted, lineHeight: 20, marginTop: 6, marginBottom: 14 },
  stepTwo: { marginTop: 14, gap: 4 },
  stepTwoLabel: { fontSize: 10.5, fontWeight: "900", color: colors.primary, letterSpacing: 0.6 },
  stepTwoSub: { fontSize: 13, color: colors.textMuted, lineHeight: 19 },
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

  // Native WebView header
  rzpNativeHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 16, paddingVertical: 10, backgroundColor: "#fff", borderBottomWidth: 1, borderBottomColor: colors.border },
  rzpNativeTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
});
