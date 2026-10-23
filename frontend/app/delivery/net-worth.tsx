// Delivery Partner — Money: where the cash came from, what is owed, Pay To
// Admin via Razorpay, and the Excel export.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator,
  TouchableOpacity, Alert, Modal, TextInput, Platform, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect } from "expo-router";
import { WebView } from "react-native-webview";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { useBranding } from "../../src/branding";
import { colors, spacing, radii, formatINR } from "../../src/theme";
import { DPHeader, DPTabBar, DPMoneyCard, DPEmpty } from "../../src/delivery-ui";
import { useTabSwipe } from "../../src/use-swipe-pager";
import { openRazorpayCheckout, buildRazorpayHtml, RazorpayResult } from "../../src/razorpay";

export default function DeliveryNetWorth() {
  const { user } = useAuth();
  const { app_name } = useBranding();
  const [nw, setNw] = useState<any>(null);
  const [txns, setTxns] = useState<any[]>([]);
  const [remits, setRemits] = useState<any[]>([]);
  const [tab, setTab] = useState<"summary" | "cash" | "payments">("summary");
  const swipe = useTabSwipe(["summary", "cash", "payments"] as const, tab, setTab);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Pay-to-admin
  const [payOpen, setPayOpen] = useState(false);
  const [payAmount, setPayAmount] = useState("");
  // Jun 2026 — settle the dues straight out of the rider's own wallet.
  const [walletOpen, setWalletOpen] = useState(false);
  const [walletAmount, setWalletAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [rzpHtml, setRzpHtml] = useState<string | null>(null);
  const [rzpResolve, setRzpResolve] = useState<((r: RazorpayResult) => void) | null>(null);

  const load = useCallback(async () => {
    try {
      const [n, t, r] = await Promise.all([
        api.get("/delivery-partner/me/net-worth"),
        api.get("/delivery-partner/me/cash-transactions"),
        api.get("/delivery-partner/me/remittances"),
      ]);
      setNw(n.data);
      setTxns((t.data as any)?.items || []);
      setRemits((r.data as any)?.items || []);
    } catch { /* empty state is valid */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Native Razorpay runs inside a WebView; web opens the checkout directly.
  const openNative = (html: string) =>
    new Promise<RazorpayResult>((resolve) => { setRzpResolve(() => resolve); setRzpHtml(html); });
  const onRzpMessage = (raw: string) => {
    let msg: any = {};
    try { msg = JSON.parse(raw); } catch { return; }
    setRzpHtml(null);
    const r: RazorpayResult = msg.type === "success"
      ? { ok: true, paymentId: msg.payment_id, orderId: msg.order_id, signature: msg.signature }
      : { ok: false, cancelled: msg.type === "cancel", error: msg.error };
    rzpResolve?.(r);
    setRzpResolve(null);
  };

  const pay = async () => {
    setErr("");
    const amt = Number(payAmount);
    const owed = Number(nw?.cash_in_hand || 0);
    if (!amt || amt <= 0) { setErr("Enter an amount"); return; }
    if (amt > owed) { setErr(`You are only holding ${formatINR(owed)} of Slangcart cash`); return; }
    setBusy(true);
    try {
      const { data: start } = await api.post<any>("/delivery-partner/remit/start", { amount: amt });
      let paymentId = "", signature = "", orderId = start.razorpay_order_id;
      if (start.is_mock) {
        await new Promise((r) => setTimeout(r, 800));
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
          if (!result.cancelled) setErr(result.error || "Payment was not completed.");
          setBusy(false);
          return;
        }
        paymentId = result.paymentId;
        signature = result.signature;
        orderId = result.orderId || orderId;
      }
      const { data: done } = await api.post<any>("/delivery-partner/remit/verify", {
        remit_id: start.remit_id,
        razorpay_order_id: orderId,
        razorpay_payment_id: paymentId,
        razorpay_signature: signature,
      });
      setPayOpen(false);
      setPayAmount("");
      await load();
      Alert.alert(
        "Cash paid in",
        `${formatINR(Number(done.amount))} received. ${done.orders_cleared} cash order(s) cleared.`,
      );
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setBusy(false); }
  };

  // Settle from the rider's own wallet — an internal set-off, no gateway.
  const payFromWallet = async () => {
    setErr("");
    const max = Number(nw?.payable_from_wallet || 0);
    const amt = Number(walletAmount || max);
    if (!amt || amt <= 0) { setErr("Enter an amount"); return; }
    if (amt > max + 0.009) { setErr(`Your wallet can only cover ${formatINR(max)}`); return; }
    setBusy(true);
    try {
      const { data } = await api.post<any>("/delivery-partner/remit/wallet", { amount: amt });
      setWalletOpen(false);
      setWalletAmount("");
      await load();
      Alert.alert(
        "Settled from wallet",
        `${formatINR(Number(data.amount))} cleared. ${data.orders_cleared} cash order(s) closed.`,
      );
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setBusy(false); }
  };

  const exportExcel = async () => {
    const base = process.env.EXPO_PUBLIC_BACKEND_URL || "";
    const url = `${base}/api/delivery-partner/me/export.xlsx`;
    try { await Linking.openURL(url); }
    catch { Alert.alert("Could not open", "Try again from a browser."); }
  };

  if (loading) {
    return (
      <SafeAreaView style={s.safe} edges={["top"]}>
        <ActivityIndicator color={colors.primary} style={{ marginTop: 60 }} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe} edges={["top"]} {...swipe}>
      <Stack.Screen options={{ headerShown: false }} />
      <DPHeader title="Money" subtitle="Cash collected and paid in" />

      <View style={s.tabRow}>
        {(["summary", "cash", "payments"] as const).map((t) => (
          <TouchableOpacity
            key={t}
            onPress={() => setTab(t)}
            style={[s.tabChip, tab === t && s.tabChipOn]}
            testID={`dp-money-tab-${t}`}
          >
            <Text style={[s.tabChipText, tab === t && s.tabChipTextOn]}>
              {t === "summary" ? "Summary" : t === "cash" ? "Cash ledger" : "Payments"}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView
        contentContainerStyle={{ paddingBottom: 30 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
            tintColor={colors.primary} />
        }
      >
        <DPMoneyCard
          cashInHand={Number(nw?.cash_in_hand || 0)}
          personalWallet={Number(nw?.personal_wallet || 0)}
          inSync={!!nw?.in_sync}
          payableFromWallet={Number(nw?.payable_from_wallet || 0)}
          remainingAfterWallet={Number(nw?.remaining_after_wallet ?? nw?.cash_in_hand ?? 0)}
          onPayWallet={() => setWalletOpen(true)}
          onPay={() => {
            setPayAmount(String(Number(nw?.remaining_after_wallet ?? nw?.cash_in_hand ?? 0)));
            setPayOpen(true);
          }}
        />

        {tab === "summary" ? (
          <>
            <Section title="Where the money came from">
              <Line label="Cash collected on deliveries" value={formatINR(nw?.cash_collected || 0)} />
              <Line label="Paid to Slangcart" value={`− ${formatINR(nw?.cash_remitted || 0)}`} />
              <View style={s.hr} />
              <Line label="Still owed to Slangcart" value={formatINR(nw?.cash_in_hand || 0)} bold />
              <Line label="Your wallet can settle" value={`− ${formatINR(nw?.payable_from_wallet || 0)}`} />
              <Line
                label="Left to pay online"
                value={formatINR(nw?.remaining_after_wallet ?? nw?.cash_in_hand ?? 0)}
                bold
              />
              <Line
                label="Books"
                value={nw?.in_sync ? "Balanced" : `Off by ${formatINR(nw?.unledgered_difference || 0)}`}
              />
            </Section>

            <Section title="Cash due, shop by shop">
              {(nw?.per_vendor || []).length === 0 ? (
                <Text style={s.muted}>Nothing pending — every cash order is cleared.</Text>
              ) : (
                (nw?.per_vendor || []).map((v: any) => (
                  <Line
                    key={v.vendor_id}
                    label={`${v.shop_name} · ${v.orders} order${v.orders === 1 ? "" : "s"}`}
                    value={formatINR(v.amount)}
                  />
                ))
              )}
            </Section>

            <Section title="Deliveries">
              <Line label="Completed" value={String(nw?.deliveries_completed || 0)} />
              <Line label="In progress" value={String(nw?.deliveries_in_progress || 0)} />
            </Section>

            <TouchableOpacity style={s.exportBtn} onPress={exportExcel} testID="dp-export">
              <Feather name="download" size={15} color={colors.primary} />
              <Text style={s.exportText}>Download everything as Excel</Text>
            </TouchableOpacity>
            <Text style={s.note}>{nw?.earnings_note || ""}</Text>
          </>
        ) : tab === "cash" ? (
          txns.length === 0 ? (
            <DPEmpty icon="file-text" title="No cash movements yet"
              body="Every rupee you collect and every payment you make shows up here." />
          ) : (
            txns.map((t) => (
              <View key={t.id} style={s.row} testID={`dp-cash-${t.id}`}>
                <Feather
                  name={t.direction === "in" ? "arrow-down-circle" : "arrow-up-circle"}
                  size={18}
                  color={t.direction === "in" ? colors.success : colors.primary}
                />
                <View style={{ flex: 1 }}>
                  <Text style={s.rowTitle} numberOfLines={2}>{t.description || t.type}</Text>
                  <Text style={s.rowSub}>
                    {new Date(t.created_at).toLocaleString()}
                    {t.reference_number ? ` · ${t.reference_number}` : ""}
                  </Text>
                </View>
                <Text style={[s.rowAmt, { color: t.direction === "in" ? colors.success : colors.primary }]}>
                  {t.direction === "in" ? "+" : "−"}{formatINR(Number(t.credit || t.debit || t.amount || 0))}
                </Text>
              </View>
            ))
          )
        ) : remits.length === 0 ? (
          <DPEmpty icon="credit-card" title="No payments yet"
            body="When you pay collected cash to Slangcart, each payment is receipted here." />
        ) : (
          remits.map((r) => (
            <View key={r.id} style={s.row} testID={`dp-remit-${r.id}`}>
              <Feather name="check-circle" size={18} color={colors.success} />
              <View style={{ flex: 1 }}>
                <Text style={s.rowTitle}>{formatINR(Number(r.amount || 0))} paid to Slangcart</Text>
                <Text style={s.rowSub}>
                  {new Date(r.paid_at).toLocaleString()}
                  {` · ${(r.settled_orders || []).length} order(s) cleared`}
                </Text>
                {(r.vendor_split || []).map((v: any, i: number) => (
                  <Text key={i} style={s.rowSplit}>
                    {v.shop_name}: {formatINR(v.amount)}
                  </Text>
                ))}
              </View>
            </View>
          ))
        )}
      </ScrollView>

      {/* Pay to Slangcart */}
      <Modal visible={payOpen} transparent animationType="slide" onRequestClose={() => setPayOpen(false)}>
        <View style={s.overlay}>
          <View style={s.sheet}>
            <View style={s.sheetHandle} />
            <Text style={s.sheetTitle}>Pay cash to Slangcart</Text>
            <Text style={s.sheetSub}>
              {`You are holding ${formatINR(Number(nw?.cash_in_hand || 0))}. Pay by card, UPI or netbanking — your cash orders clear instantly.`}
            </Text>
            <TextInput
              style={s.input}
              value={payAmount}
              onChangeText={setPayAmount}
              keyboardType="numeric"
              placeholder="Amount in ₹"
              placeholderTextColor={colors.textMuted}
              testID="dp-pay-amount"
            />
            {err ? <Text style={s.err}>{err}</Text> : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity style={[s.sheetBtn, { backgroundColor: colors.surfaceMuted }]}
                onPress={() => setPayOpen(false)}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.sheetBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]}
                onPress={pay}
                disabled={busy}
                testID="dp-pay-confirm"
              >
                {busy ? <ActivityIndicator color={colors.primaryFg} />
                  : <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Pay now</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Settle from my wallet (internal set-off — no gateway, no bank entry) */}
      <Modal visible={walletOpen} transparent animationType="slide" onRequestClose={() => setWalletOpen(false)}>
        <View style={s.overlay}>
          <View style={s.sheet}>
            <View style={s.sheetHandle} />
            <Text style={s.sheetTitle}>Settle from my wallet</Text>
            <Text style={s.sheetSub}>
              {`You owe ${formatINR(Number(nw?.cash_in_hand || 0))} and your wallet has ${formatINR(Number(nw?.personal_wallet || 0))}. `}
              {`Up to ${formatINR(Number(nw?.payable_from_wallet || 0))} can be settled straight from your wallet — no online payment needed.`}
            </Text>
            <TextInput
              style={s.input}
              value={walletAmount}
              onChangeText={setWalletAmount}
              keyboardType="numeric"
              placeholder={`Amount in ₹ (max ${Number(nw?.payable_from_wallet || 0)})`}
              placeholderTextColor={colors.textMuted}
              testID="dp-wallet-amount"
            />
            {err ? <Text style={s.err}>{err}</Text> : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity style={[s.sheetBtn, { backgroundColor: colors.surfaceMuted }]}
                onPress={() => setWalletOpen(false)}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.sheetBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]}
                onPress={payFromWallet}
                disabled={busy}
                testID="dp-wallet-confirm"
              >
                {busy ? <ActivityIndicator color={colors.primaryFg} />
                  : <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Settle now</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Native Razorpay checkout */}
      <Modal visible={!!rzpHtml} animationType="slide" onRequestClose={() => onRzpMessage('{"type":"cancel"}')}>
        <SafeAreaView style={{ flex: 1, backgroundColor: "#fff" }}>
          {rzpHtml ? (
            <WebView
              originWhitelist={["*"]}
              source={{ html: rzpHtml }}
              onMessage={(e) => onRzpMessage(e.nativeEvent.data)}
              javaScriptEnabled
              domStorageEnabled
              style={{ flex: 1 }}
            />
          ) : null}
        </SafeAreaView>
      </Modal>

      <DPTabBar />
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={s.section}>
      <Text style={s.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Line({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={s.lineRow}>
      <Text style={[s.lineLabel, bold && { color: colors.textMain, fontWeight: "800" }]}>{label}</Text>
      <Text style={[s.lineValue, bold && { fontWeight: "900" }]}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  tabRow: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.screen, marginBottom: 14 },
  tabChip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    minHeight: 36, justifyContent: "center",
  },
  tabChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabChipText: { fontSize: 12.5, fontWeight: "700", color: colors.textMain },
  tabChipTextOn: { color: colors.primaryFg },
  section: {
    marginHorizontal: spacing.screen, marginBottom: 12, padding: 14,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  sectionTitle: {
    fontSize: 10, letterSpacing: 1.2, fontWeight: "900",
    color: colors.textMuted, marginBottom: 10,
  },
  lineRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 5 },
  lineLabel: { flex: 1, fontSize: 13, color: colors.textMuted, fontWeight: "600" },
  lineValue: { fontSize: 13.5, color: colors.textMain, fontWeight: "800" },
  hr: { height: 1, backgroundColor: colors.border, marginVertical: 7 },
  muted: { fontSize: 13, color: colors.textMuted, fontWeight: "600" },
  row: {
    flexDirection: "row", alignItems: "center", gap: 11,
    marginHorizontal: spacing.screen, marginBottom: 8, padding: 12,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  rowTitle: { fontSize: 13.5, fontWeight: "700", color: colors.textMain },
  rowSub: { fontSize: 11.5, color: colors.textMuted, fontWeight: "600", marginTop: 2 },
  rowSplit: { fontSize: 11, color: colors.textMuted, fontWeight: "700", marginTop: 2 },
  rowAmt: { fontSize: 14, fontWeight: "900" },
  exportBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    marginHorizontal: spacing.screen, marginTop: 4,
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.button,
    paddingVertical: 13, minHeight: 46, backgroundColor: colors.surface,
  },
  exportText: { color: colors.primary, fontSize: 13.5, fontWeight: "800" },
  note: {
    fontSize: 11.5, color: colors.textMuted, fontWeight: "600",
    paddingHorizontal: spacing.screen, marginTop: 14, lineHeight: 17,
  },
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: 18, paddingBottom: Platform.OS === "ios" ? 34 : 22,
  },
  sheetHandle: {
    width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: 14,
  },
  sheetTitle: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  sheetSub: { fontSize: 12.5, color: colors.textMuted, fontWeight: "600", marginTop: 3, marginBottom: 14, lineHeight: 18 },
  input: {
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 13, paddingVertical: 12,
    fontSize: 15, color: colors.textMain, minHeight: 48,
  },
  err: { color: "#B3261E", fontSize: 12.5, fontWeight: "700", marginTop: 10 },
  sheetBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    borderRadius: radii.button, paddingVertical: 13, minHeight: 46,
  },
});
