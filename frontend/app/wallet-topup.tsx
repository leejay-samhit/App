/**
 * Add money to the Slangcart wallet.
 *
 * "Add money" used to open the ₹118 SUBSCRIPTION screen (/payment), which is
 * a different product entirely. This is the real top-up: type an amount (or
 * tap a preset), pay with Razorpay, wallet credited. Server enforces the
 * ₹5,000-per-top-up ceiling; this screen mirrors it so the user is never sent
 * to a gateway for an amount that will be rejected.
 */
import { useCallback, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Platform, Modal, KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { WebView } from "react-native-webview";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { useBranding } from "../src/branding";
import { colors, radii, spacing, formatINR } from "../src/theme";
import { GradientCard } from "../src/gradient-card";
import { openRazorpayCheckout, buildRazorpayHtml, RazorpayResult } from "../src/razorpay";

type TopupConfig = {
  min_amount: number;
  max_amount: number;
  presets: number[];
  balance: number;
  wallet_frozen: boolean;
  key_id: string;
  is_mock: boolean;
};

export default function WalletTopupScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const { app_name } = useBranding();
  const [config, setConfig] = useState<TopupConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ amount: number; balance: number } | null>(null);
  // Sep 2026 — an unfinished top-up the customer may already have PAID for.
  const [pendingRecovery, setPendingRecovery] = useState<
    { payment_id: string; razorpay_order_id?: string } | null
  >(null);
  const [recovering, setRecovering] = useState(false);
  // Native Razorpay lives in a WebView modal (same pattern as /payment).
  const [rzpHtml, setRzpHtml] = useState("");
  const [rzpVisible, setRzpVisible] = useState(false);
  const rzpResolver = useRef<((r: RazorpayResult) => void) | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<TopupConfig>("/wallet/topup/config");
      setConfig(data);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Any top-up left open from a previous visit is offered for recovery, so a
  // customer who was charged is never stuck without a way to claim it.
  useFocusEffect(useCallback(() => {
    let alive = true;
    api.get<{ items: any[] }>("/wallet/topup/pending")
      .then(({ data }) => {
        if (!alive) return;
        const row = (data.items || [])[0];
        if (row) setPendingRecovery({ payment_id: row.id, razorpay_order_id: row.razorpay_order_id });
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []));

  /** Ask the server to ask Razorpay. Returns true when the wallet was credited. */
  const tryRecover = async (
    payment_id: string, razorpay_order_id?: string, razorpay_payment_id?: string,
  ): Promise<boolean> => {
    try {
      const { data } = await api.post<{ ok: boolean; amount: number; balance: number }>(
        "/wallet/topup/recover",
        { payment_id, razorpay_order_id, razorpay_payment_id },
      );
      if (!data?.ok) return false;
      await refresh();
      setAmount("");
      setError("");
      setPendingRecovery(null);
      setDone({ amount: data.amount, balance: data.balance });
      return true;
    } catch {
      return false;
    }
  };

  const recoverNow = async () => {
    if (!pendingRecovery || recovering) return;
    setRecovering(true);
    setError("");
    const ok = await tryRecover(pendingRecovery.payment_id, pendingRecovery.razorpay_order_id);
    if (!ok) {
      setError(
        "Razorpay has no successful payment for that attempt yet. If your bank shows a debit, " +
        "it will either auto-refund or our team can release it — nothing is lost.",
      );
    }
    setRecovering(false);
  };

  const value = Number(amount || 0);
  const min = config?.min_amount ?? 10;
  const max = config?.max_amount ?? 5000;
  const invalid = !value || value < min || value > max;

  const openNative = (html: string): Promise<RazorpayResult> =>
    new Promise((resolve) => {
      rzpResolver.current = resolve;
      setRzpHtml(html);
      setRzpVisible(true);
    });

  const onRzpMessage = (raw: string) => {
    let data: any = {};
    try { data = JSON.parse(raw); } catch { data = {}; }
    const resolve = rzpResolver.current;
    rzpResolver.current = null;
    setRzpVisible(false);
    setTimeout(() => setRzpHtml(""), 250);
    if (!resolve) return;
    // Jun 2026 — buildRazorpayHtml posts {type:"success"|"cancel"|"failed"},
    // NOT {ok:true}. The old check read `data.ok`, so a successful native
    // top-up was reported back as a cancel and the customer had to recover
    // the payment by hand.
    if (data.type === "success") {
      resolve({ ok: true, paymentId: data.payment_id, orderId: data.order_id, signature: data.signature });
    } else if (data.type === "cancel") {
      resolve({ ok: false, cancelled: true });
    } else {
      resolve({ ok: false, error: data.error || "Payment failed", code: data.code });
    }
  };

  const pay = async () => {
    if (!config || invalid || busy) return;
    setError("");
    setBusy(true);
    try {
      const { data: start } = await api.post<{
        payment_id: string; razorpay_order_id: string; amount: number; amount_paise: number;
        key_id: string; is_mock: boolean; description: string;
        prefill: { name?: string; email?: string; contact?: string };
      }>("/wallet/topup/start", { amount: value });

      let paymentId = "";
      let signature = "";
      let orderId = start.razorpay_order_id;

      if (start.is_mock) {
        // Test mode — no live keys configured yet. Simulate the gateway so
        // the whole flow (and the wallet credit) is still exercised.
        await new Promise((r) => setTimeout(r, 900));
        paymentId = `pay_MOCK_${Math.random().toString(36).slice(2, 14)}`;
        signature = `sig_MOCK_${Math.random().toString(36).slice(2, 20)}`;
      } else {
        const opts = {
          orderId,
          amountPaise: start.amount_paise,
          keyId: start.key_id,
          name: app_name,
          description: start.description,
          prefill: {
            name: start.prefill?.name || (user as any)?.name,
            email: start.prefill?.email || (user as any)?.email,
            contact: start.prefill?.contact || (user as any)?.phone,
          },
          themeColor: colors.primary,
        };
        const result = Platform.OS === "web"
          ? await openRazorpayCheckout(opts)
          : await openNative(buildRazorpayHtml(opts));
        if (!result.ok) {
          if (result.cancelled) { setBusy(false); return; }
          // Sep 2026 — a failed/ambiguous checkout callback is NOT proof the
          // money wasn't taken (app switch to a UPI app, killed webview,
          // blocked popup). Ask the SERVER to ask Razorpay before telling the
          // customer it failed. This is what turned "Razorpay successful but
          // wallet not credited" into a silent loss.
          const recovered = await tryRecover(
            start.payment_id, orderId, (result as any).paymentId || "",
          );
          if (recovered) return;
          setError(
            (result.error || "We could not confirm that payment.") +
            " If your bank shows a debit, tap “Recover payment” — nothing is lost.",
          );
          setPendingRecovery({ payment_id: start.payment_id, razorpay_order_id: orderId });
          setBusy(false);
          return;
        }
        paymentId = result.paymentId;
        signature = result.signature;
        orderId = result.orderId || orderId;
      }

      try {
        const { data: verified } = await api.post<{ amount: number; balance: number }>(
          "/wallet/topup/verify",
          {
            payment_id: start.payment_id,
            razorpay_order_id: orderId,
            razorpay_payment_id: paymentId,
            razorpay_signature: signature,
          },
        );
        await refresh();
        setAmount("");
        setDone({ amount: verified.amount, balance: verified.balance });
      } catch (verifyErr) {
        // Verify itself failed (signature, network, stale attempt) — the
        // money may still have been captured, so recover before failing.
        const recovered = await tryRecover(start.payment_id, orderId, paymentId);
        if (!recovered) {
          setError(
            formatApiError(verifyErr) +
            " If your money was debited, tap “Recover payment”.",
          );
          setPendingRecovery({ payment_id: start.payment_id, razorpay_order_id: orderId });
        }
      }
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.screen}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={10} testID="topup-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Add money</Text>
        <View style={{ width: 40 }} />
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
          <GradientCard style={styles.balanceCard}>
            <Text style={styles.balanceLabel}>WALLET BALANCE</Text>
            <Text style={styles.balanceValue} testID="topup-balance">{formatINR(config?.balance ?? 0)}</Text>
            <Text style={styles.balanceHint}>Use it for orders, and get cashback back into it</Text>
          </GradientCard>

          {config?.wallet_frozen ? (
            <View style={styles.frozen} testID="topup-frozen">
              <Feather name="lock" size={14} color="#B3261E" />
              <Text style={styles.frozenText}>
                Your wallet is frozen, so money can&apos;t be added right now. Please contact support.
              </Text>
            </View>
          ) : null}

          <Text style={styles.sectionLabel}>ENTER AMOUNT</Text>
          <View style={styles.amountBox}>
            <Text style={styles.rupee}>₹</Text>
            <TextInput
              value={amount}
              onChangeText={(t) => { setAmount(t.replace(/[^0-9]/g, "")); setError(""); setDone(null); }}
              placeholder="0"
              placeholderTextColor={colors.textMuted}
              keyboardType="number-pad"
              style={styles.amountInput}
              maxLength={6}
              testID="topup-amount"
            />
          </View>
          <Text style={styles.limitHint} testID="topup-limit">
            You can add {formatINR(min)} to {formatINR(max)} in one go
          </Text>

          <View style={styles.presetRow}>
            {(config?.presets || []).map((p) => (
              <TouchableOpacity
                key={p}
                style={[styles.preset, value === p && styles.presetActive]}
                onPress={() => { setAmount(String(p)); setError(""); setDone(null); }}
                testID={`topup-preset-${p}`}
              >
                <Text style={[styles.presetText, value === p && styles.presetTextActive]}>+{formatINR(p)}</Text>
              </TouchableOpacity>
            ))}
          </View>

          {value > max ? (
            <Text style={styles.error} testID="topup-over-limit">
              The most you can add at once is {formatINR(max)}.
            </Text>
          ) : null}
          {error ? <Text style={styles.error} testID="topup-error">{error}</Text> : null}
          {pendingRecovery ? (
            <View style={styles.recoverBox}>
              <Text style={styles.recoverTitle}>Paid but not credited?</Text>
              <Text style={styles.recoverBody}>
                We have an unfinished top-up for you. Tap below and we will check directly with
                Razorpay — if the payment went through, your wallet is credited instantly. It is
                safe to tap more than once; you can never be credited twice.
              </Text>
              <TouchableOpacity
                onPress={recoverNow}
                disabled={recovering}
                style={styles.recoverBtn}
                testID="topup-recover"
              >
                {recovering ? <ActivityIndicator size="small" color={colors.primaryFg} /> : (
                  <Text style={styles.recoverBtnText}>Recover payment</Text>
                )}
              </TouchableOpacity>
            </View>
          ) : null}

          {done ? (
            <View style={styles.success} testID="topup-success">
              <Feather name="check-circle" size={16} color={colors.success} />
              <Text style={styles.successText}>
                {formatINR(done.amount)} added. New balance {formatINR(done.balance)}.
              </Text>
            </View>
          ) : null}

          {config?.is_mock ? (
            <View style={styles.note} testID="topup-mock-note">
              <Feather name="info" size={13} color={colors.textMuted} />
              <Text style={styles.noteText}>
                Payments are in test mode until live Razorpay keys are added in
                Admin → Payment gateway. The wallet still credits so you can try the flow.
              </Text>
            </View>
          ) : null}
        </ScrollView>

        <View style={styles.footer}>
          <TouchableOpacity
            style={[styles.payBtn, (invalid || busy || config?.wallet_frozen) && styles.payBtnOff]}
            onPress={pay}
            disabled={invalid || busy || !!config?.wallet_frozen}
            testID="topup-pay"
          >
            {busy ? (
              <ActivityIndicator color={colors.accentFg} />
            ) : (
              <>
                <Feather name="plus-circle" size={16} color={colors.accentFg} />
                <Text style={styles.payBtnText}>
                  {value > 0 ? `Add ${formatINR(value)}` : "Add money"}
                </Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      <Modal visible={rzpVisible} animationType="slide" onRequestClose={() => onRzpMessage('{"type":"cancel"}')}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => onRzpMessage('{"type":"cancel"}')} style={styles.backBtn} hitSlop={10}>
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Secure payment</Text>
            <View style={{ width: 40 }} />
          </View>
          {rzpHtml ? (
            <WebView
              originWhitelist={["*"]}
              source={{ html: rzpHtml }}
              onMessage={(e) => onRzpMessage(e.nativeEvent.data)}
              javaScriptEnabled
              domStorageEnabled
            />
          ) : null}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  body: { padding: spacing.md, paddingBottom: 32 },
  balanceCard: { padding: spacing.md, borderRadius: radii.card },
  balanceLabel: { fontSize: 10, fontWeight: "800", letterSpacing: 0.6, color: "rgba(255,255,255,0.85)" },
  balanceValue: { fontSize: 30, fontWeight: "800", color: "#fff", marginTop: 4 },
  balanceHint: { fontSize: 11, fontWeight: "600", color: "rgba(255,255,255,0.85)", marginTop: 4 },
  frozen: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: spacing.md,
    backgroundColor: "#FCE9E5", borderRadius: radii.card, padding: 12,
  },
  frozenText: { flex: 1, fontSize: 12, color: "#B3261E", fontWeight: "600", lineHeight: 17 },
  sectionLabel: {
    fontSize: 11, fontWeight: "800", letterSpacing: 0.6, color: colors.textMuted,
    marginTop: spacing.lg, marginBottom: 8,
  },
  amountBox: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface,
    borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: spacing.md, paddingVertical: 10,
  },
  rupee: { fontSize: 26, fontWeight: "800", color: colors.textMuted },
  amountInput: { flex: 1, fontSize: 30, fontWeight: "800", color: colors.textMain, paddingVertical: 6 },
  limitHint: { fontSize: 11.5, color: colors.textMuted, fontWeight: "600", marginTop: 8 },
  presetRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: spacing.md },
  preset: {
    paddingHorizontal: 14, minHeight: 44, justifyContent: "center", borderRadius: 22,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  presetActive: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  presetText: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  presetTextActive: { color: colors.primary },
  error: { marginTop: spacing.md, fontSize: 12.5, color: "#B3261E", fontWeight: "700", lineHeight: 18 },
  // Recovery for a top-up that was paid but never credited (Sep 2026).
  recoverBox: {
    marginTop: spacing.md, backgroundColor: "#FEF3C7", borderRadius: 14, padding: 14,
  },
  recoverTitle: { fontSize: 13, fontWeight: "900", color: "#92400E" },
  recoverBody: { fontSize: 12, color: "#78350F", marginTop: 4, lineHeight: 18 },
  recoverBtn: {
    marginTop: 10, backgroundColor: colors.primary, borderRadius: 999, minHeight: 46,
    alignItems: "center", justifyContent: "center", paddingHorizontal: 16,
  },
  recoverBtnText: { color: colors.primaryFg, fontWeight: "900", fontSize: 13 },

  success: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: spacing.md,
    backgroundColor: colors.surface, borderRadius: radii.card, padding: 12,
    borderWidth: 1, borderColor: colors.success,
  },
  successText: { flex: 1, fontSize: 12.5, color: colors.textMain, fontWeight: "700" },
  note: {
    flexDirection: "row", alignItems: "flex-start", gap: 8, marginTop: spacing.lg,
    backgroundColor: colors.surfaceMuted, borderRadius: radii.card, padding: 12,
  },
  noteText: { flex: 1, fontSize: 11.5, color: colors.textMuted, fontWeight: "600", lineHeight: 17 },
  footer: {
    padding: spacing.md, borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  payBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 50, borderRadius: radii.input, backgroundColor: colors.primary,
  },
  payBtnOff: { opacity: 0.45 },
  payBtnText: { fontSize: 15, fontWeight: "800", color: colors.accentFg },
});
