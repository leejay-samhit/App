// Delivery Partner — Wallet: delivery earnings and bank settlement.
// The COD cash pot is deliberately NOT here (it is Slangcart's money and
// lives in /delivery/net-worth). Only what the rider has actually earned.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator,
  TouchableOpacity, Modal, TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, radii, formatINR } from "../../src/theme";
import { DPHeader, DPTabBar, DPEmpty } from "../../src/delivery-ui";

const LABELS: Record<string, string> = {
  dp_delivery_commission: "Delivery earning",
  dp_delivery_commission_reversal: "Earning reversed",
  withdrawal_hold: "Withdrawal requested",
  withdrawal: "Withdrawal paid",
  withdrawal_reversal: "Withdrawal returned",
  admin_credit: "Credited by Slangcart",
  admin_debit: "Debited by Slangcart",
};

export default function DeliveryWallet() {
  const router = useRouter();
  const [w, setW] = useState<any>(null);
  const [txns, setTxns] = useState<any[]>([]);
  const [totals, setTotals] = useState<{ earned: number; withdrawn: number }>({ earned: 0, withdrawn: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [okMsg, setOkMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([
        api.get("/delivery-partner/me/wallet"),
        api.get("/delivery-partner/me/wallet-transactions"),
      ]);
      setW(a.data);
      const d = b.data as any;
      setTxns(d?.items || []);
      setTotals({ earned: Number(d?.total_earned || 0), withdrawn: Number(d?.total_withdrawn || 0) });
    } catch { /* empty state is valid */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const submit = async () => {
    setErr("");
    const amt = Number(amount);
    const avail = Number(w?.available || 0);
    const min = Number(w?.min_withdrawal || 0);
    if (!amt || amt <= 0) { setErr("Enter an amount"); return; }
    if (amt < min) { setErr(`Minimum withdrawal is ${formatINR(min)}`); return; }
    if (amt > avail) { setErr(`You only have ${formatINR(avail)} available`); return; }
    setBusy(true);
    try {
      await api.post("/withdrawals", { amount: amt });
      setOpen(false);
      setAmount("");
      setOkMsg("Withdrawal requested — Slangcart will settle it to your bank.");
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setBusy(false); }
  };

  const available = Number(w?.available || 0);
  const pending = Number(w?.pending_withdrawals || 0);

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <DPHeader title="My wallet" subtitle="Your delivery earnings" />
      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 50 }} />
      ) : (
        <ScrollView
          contentContainerStyle={{ paddingBottom: 30 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }}
              tintColor={colors.primary} />
          }
        >
          <View style={s.hero}>
            <Text style={s.heroLabel}>AVAILABLE TO WITHDRAW</Text>
            <Text style={s.heroValue} testID="dp-wallet-available">{formatINR(available)}</Text>
            <View style={s.heroRow}>
              <View style={s.chip}>
                <Text style={s.chipLabel}>EARNED</Text>
                <Text style={s.chipValue}>{formatINR(totals.earned)}</Text>
              </View>
              <View style={s.chip}>
                <Text style={s.chipLabel}>IN PROGRESS</Text>
                <Text style={s.chipValue}>{formatINR(pending)}</Text>
              </View>
            </View>
            <TouchableOpacity
              style={[s.cta, !w?.can_withdraw && { opacity: 0.55 }]}
              disabled={!w?.can_withdraw}
              onPress={() => { setErr(""); setOkMsg(""); setOpen(true); }}
              testID="dp-wallet-withdraw"
            >
              <Feather name="arrow-up-right" size={15} color={colors.primary} />
              <Text style={s.ctaText}>Withdraw to bank</Text>
            </TouchableOpacity>
            {w?.withdraw_blocked_reason ? (
              <Text style={s.heroNote}>{w.withdraw_blocked_reason}</Text>
            ) : null}
          </View>

          {okMsg ? (
            <View style={s.okBox}>
              <Feather name="check-circle" size={14} color={colors.success} />
              <Text style={s.okText}>{okMsg}</Text>
            </View>
          ) : null}

          <TouchableOpacity
            style={s.cashCard}
            onPress={() => router.push("/delivery/net-worth" as any)}
            testID="dp-wallet-cash-link"
          >
            <Feather name="dollar-sign" size={15} color="#92400E" />
            <View style={{ flex: 1 }}>
              <Text style={s.cashTitle}>{`Cash you owe Slangcart · ${formatINR(Number(w?.cash_in_hand || 0))}`}</Text>
              <Text style={s.cashSub}>{w?.cash_note || ""}</Text>
            </View>
            <Feather name="chevron-right" size={17} color={colors.textMuted} />
          </TouchableOpacity>

          <Text style={s.section}>EARNINGS & SETTLEMENTS</Text>
          {txns.length === 0 ? (
            <DPEmpty
              icon="file-text"
              title="Nothing yet"
              body="Your delivery earnings and bank settlements will be listed here."
            />
          ) : (
            txns.map((t) => {
              const credit = Number(t.credit || 0);
              const debit = Number(t.debit || 0);
              const isCredit = credit > 0.009;
              return (
                <View key={t.id} style={s.row} testID={`dp-wtxn-${t.id}`}>
                  <View style={[s.rowIcon, { backgroundColor: isCredit ? colors.brand100 : colors.surfaceMuted }]}>
                    <Feather
                      name={isCredit ? "arrow-down-left" : "arrow-up-right"}
                      size={14}
                      color={isCredit ? colors.success : colors.textMuted}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.rowTitle} numberOfLines={1}>
                      {LABELS[t.type] || t.type}
                    </Text>
                    <Text style={s.rowMeta} numberOfLines={2}>
                      {t.description || t.order_number || ""}
                    </Text>
                    <Text style={s.rowDate}>
                      {t.created_at ? new Date(t.created_at).toLocaleString() : ""}
                    </Text>
                  </View>
                  <Text style={[s.rowAmt, { color: isCredit ? colors.success : colors.textMain }]}>
                    {`${isCredit ? "+" : "−"} ${formatINR(isCredit ? credit : debit)}`}
                  </Text>
                </View>
              );
            })
          )}
        </ScrollView>
      )}

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={s.overlay}>
          <View style={s.sheet}>
            <View style={s.sheetHandle} />
            <Text style={s.sheetTitle}>Withdraw to bank</Text>
            <Text style={s.sheetSub}>
              {`Available ${formatINR(available)} · minimum ${formatINR(Number(w?.min_withdrawal || 0))}`}
            </Text>
            <TextInput
              style={s.input}
              value={amount}
              onChangeText={setAmount}
              keyboardType="numeric"
              placeholder="Amount"
              placeholderTextColor={colors.textMuted}
              testID="dp-wallet-amount"
            />
            {err ? <Text style={s.err}>{err}</Text> : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity
                style={[s.sheetBtn, { backgroundColor: colors.surfaceMuted }]}
                onPress={() => setOpen(false)}
              >
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.sheetBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]}
                onPress={submit}
                disabled={busy}
                testID="dp-wallet-submit"
              >
                {busy ? <ActivityIndicator color={colors.primaryFg} />
                  : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Request</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      <DPTabBar />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  hero: {
    marginHorizontal: spacing.screen, marginTop: 12, padding: 16,
    backgroundColor: colors.primary, borderRadius: radii.card,
  },
  heroLabel: { fontSize: 9.5, letterSpacing: 1.3, fontWeight: "900", color: "#B9CFC4" },
  heroValue: { fontSize: 32, fontWeight: "900", color: colors.primaryFg, letterSpacing: -1, marginTop: 4 },
  heroRow: { flexDirection: "row", gap: 10, marginTop: 14 },
  chip: { flex: 1, backgroundColor: "#1F5240", borderRadius: 12, padding: 10 },
  chipLabel: { fontSize: 9, letterSpacing: 0.9, fontWeight: "900", color: "#B9CFC4" },
  chipValue: { fontSize: 15, fontWeight: "800", color: colors.primaryFg, marginTop: 2 },
  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    marginTop: 14, backgroundColor: colors.primaryFg, borderRadius: 999,
    paddingVertical: 12, minHeight: 46,
  },
  ctaText: { color: colors.primary, fontWeight: "800", fontSize: 13.5 },
  heroNote: { fontSize: 11, color: "#D8E5DE", fontWeight: "600", marginTop: 9, lineHeight: 16 },
  okBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: spacing.screen, marginTop: 12, padding: 11,
    backgroundColor: colors.brand100, borderRadius: 12,
  },
  okText: { flex: 1, fontSize: 12, fontWeight: "700", color: colors.textMain },
  cashCard: {
    flexDirection: "row", alignItems: "center", gap: 11,
    marginHorizontal: spacing.screen, marginTop: 12, padding: 12,
    backgroundColor: "#FEF3C7", borderRadius: radii.card, minHeight: 56,
  },
  cashTitle: { fontSize: 13, fontWeight: "800", color: "#78350F" },
  cashSub: { fontSize: 11, color: "#92400E", fontWeight: "600", marginTop: 2, lineHeight: 15 },
  section: {
    fontSize: 10, letterSpacing: 1.4, fontWeight: "900", color: colors.textMuted,
    paddingHorizontal: spacing.screen, marginTop: 24, marginBottom: 10,
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 11,
    marginHorizontal: spacing.screen, marginBottom: 8, padding: 12,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  rowIcon: {
    width: 32, height: 32, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
  },
  rowTitle: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  rowMeta: { fontSize: 11, color: colors.textMuted, fontWeight: "600", marginTop: 2, lineHeight: 15 },
  rowDate: { fontSize: 10, color: colors.textMuted, fontWeight: "600", marginTop: 3 },
  rowAmt: { fontSize: 14, fontWeight: "900" },
  overlay: { flex: 1, backgroundColor: "#00000066", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: spacing.screen, paddingBottom: Platform.OS === "ios" ? 34 : spacing.screen,
  },
  sheetHandle: {
    width: 42, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: 12,
  },
  sheetTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  sheetSub: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 4, marginBottom: 12 },
  input: {
    backgroundColor: colors.surfaceMuted, borderRadius: radii.input,
    paddingHorizontal: 13, paddingVertical: 12, fontSize: 15,
    color: colors.textMain, minHeight: 48,
  },
  err: { color: colors.error, fontSize: 12, fontWeight: "700", marginTop: 9 },
  sheetBtn: {
    flex: 1, borderRadius: radii.button, paddingVertical: 13,
    alignItems: "center", justifyContent: "center", minHeight: 48,
  },
});
