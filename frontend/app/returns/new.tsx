// Request a product return — Phase 2 (Jun-2026).
// The server decides what is returnable (Sep-2026: a 10-MINUTE window from
// delivery, plus remaining units) and what the refund will be; this screen
// only collects the choice and counts the window down live.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, formatINR } from "../../src/theme";

type Line = {
  product_id: string;
  variant_id?: string | null;
  variant_label?: string;
  name: string;
  qty: number;
  returned_qty: number;
  returnable_qty: number;
  unit_price: number;
  line_total: number;
  cashback_pct: number;
};
type State = {
  return_window_minutes: number;
  return_deadline?: string | null;
  seconds_left: number;
  minutes_left: number;
  return_eligible: boolean;
  window_expired: boolean;
  items: Line[];
};

const REASONS = [
  "Damaged on arrival",
  "Wrong item delivered",
  "Not as described",
  "Missing parts",
  "Size / fit issue",
  "Quality not satisfactory",
  "Changed my mind",
];

export default function NewReturnScreen() {
  const router = useRouter();
  const { order_id } = useLocalSearchParams<{ order_id?: string }>();
  const [state, setState] = useState<State | null>(null);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState<Record<string, number>>({});
  const [reason, setReason] = useState("");
  const [comments, setComments] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<null | { return_number: string; refund_amount: number }>(null);

  const load = useCallback(async () => {
    if (!order_id) return;
    try {
      const { data } = await api.get<State>(`/orders/${order_id}/return-state`);
      setState(data);
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [order_id]);

  useEffect(() => { load(); }, [load]);

  // The window is minutes long, so it has to tick. Seed from the server's
  // `seconds_left` (never the device clock) and count down locally.
  const [secondsLeft, setSecondsLeft] = useState(0);
  useEffect(() => {
    setSecondsLeft(Number(state?.seconds_left || 0));
  }, [state?.seconds_left]);
  const ticking = secondsLeft > 0;
  useEffect(() => {
    if (!ticking) return;
    const t = setInterval(() => setSecondsLeft((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [ticking]);

  const key = (l: Line) => `${l.product_id}|${l.variant_id || ""}`;
  const bump = (l: Line, delta: number) => {
    setErr("");
    setPicked((prev) => {
      const k = key(l);
      const next = Math.max(0, Math.min(l.returnable_qty, (prev[k] || 0) + delta));
      return { ...prev, [k]: next };
    });
  };

  const chosen = (state?.items || []).filter((l) => (picked[key(l)] || 0) > 0);
  const refund = chosen.reduce((sum, l) => sum + l.unit_price * (picked[key(l)] || 0), 0);
  const cashbackBack = chosen.reduce(
    (sum, l) => sum + (l.unit_price * (picked[key(l)] || 0) * (l.cashback_pct || 0)) / 100, 0,
  );

  const submit = async () => {
    if (!chosen.length) { setErr("Pick at least one item to return."); return; }
    if (!reason) { setErr("Tell the seller why you're returning it."); return; }
    setBusy(true); setErr("");
    try {
      const { data } = await api.post<{ return_number: string; refund_amount: number }>("/returns", {
        order_id,
        items: chosen.map((l) => ({
          product_id: l.product_id, variant_id: l.variant_id || null, qty: picked[key(l)],
        })),
        reason,
        comments,
      });
      setDone({ return_number: data.return_number, refund_amount: data.refund_amount });
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="return-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Return items</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : !state ? (
        <Text style={styles.empty}>{err || "Order not found."}</Text>
      ) : !state.return_eligible ? (
        <View style={{ padding: spacing.screen }}>
          <View style={styles.infoCard}>
            <Feather name="clock" size={18} color={colors.textMuted} />
            <Text style={styles.infoText}>
              {state.window_expired
                ? `The ${state.return_window_minutes}-minute return window for this order has closed. The order is now complete.`
                : "There are no items left to return on this order."}
            </Text>
          </View>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 140 }}>
          <View style={styles.windowPill}>
            <Feather name="refresh-ccw" size={13} color={colors.primary} />
            <Text style={styles.windowText}>
              {secondsLeft > 0
                ? `${Math.floor(secondsLeft / 60)}m ${String(secondsLeft % 60).padStart(2, "0")}s left to return`
                : "Return window closed"}
            </Text>
          </View>

          <Text style={styles.sectionLabel}>What are you sending back?</Text>
          {state.items.map((l) => {
            const q = picked[key(l)] || 0;
            const locked = l.returnable_qty <= 0;
            return (
              <View key={key(l)} style={[styles.row, locked && { opacity: 0.5 }]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName} numberOfLines={2}>{l.name}</Text>
                  <Text style={styles.rowMeta}>
                    {formatINR(l.unit_price)} each · bought {l.qty}
                    {l.returned_qty > 0 ? ` · ${l.returned_qty} already returned` : ""}
                    {l.variant_label ? ` · ${l.variant_label}` : ""}
                  </Text>
                </View>
                {locked ? (
                  <Text style={styles.lockedText}>Returned</Text>
                ) : (
                  <View style={styles.stepper}>
                    <TouchableOpacity
                      onPress={() => bump(l, -1)}
                      style={styles.stepBtn}
                      testID={`ret-minus-${l.product_id}`}
                    >
                      <Feather name="minus" size={16} color={colors.textMain} />
                    </TouchableOpacity>
                    <Text style={styles.stepQty} testID={`ret-qty-${l.product_id}`}>{q}</Text>
                    <TouchableOpacity
                      onPress={() => bump(l, 1)}
                      style={styles.stepBtn}
                      testID={`ret-plus-${l.product_id}`}
                    >
                      <Feather name="plus" size={16} color={colors.textMain} />
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            );
          })}

          <Text style={styles.sectionLabel}>Reason</Text>
          <View style={styles.chipWrap}>
            {REASONS.map((r) => (
              <TouchableOpacity
                key={r}
                onPress={() => { setReason(r); setErr(""); }}
                style={[styles.chip, reason === r && styles.chipOn]}
                testID={`ret-reason-${r.slice(0, 6)}`}
              >
                <Text style={[styles.chipText, reason === r && styles.chipTextOn]}>{r}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.sectionLabel}>Anything else? (optional)</Text>
          <TextInput
            value={comments}
            onChangeText={setComments}
            placeholder="Tell the seller what happened"
            placeholderTextColor={colors.textMuted}
            multiline
            style={styles.textArea}
            testID="ret-comments"
          />

          <View style={styles.summary}>
            <Text style={styles.summaryTitle}>Refund you will receive</Text>
            <Row label="Items being returned" value={formatINR(refund)} />
            {cashbackBack > 0.009 ? (
              <Row label="Cashback to be reversed" value={`− ${formatINR(cashbackBack)}`} muted />
            ) : null}
            <Row label="Delivery charge" value="Not refundable" muted />
            <View style={styles.divider} />
            <Row label="Credited to your wallet" value={formatINR(Math.max(0, refund - cashbackBack))} bold />
            <Text style={styles.summaryNote}>
              The seller reviews your request first. Once they receive the item, the refund lands in
              your Slangcart wallet and the stock goes back on their shelf.
            </Text>
          </View>

          {err ? <Text style={styles.err} testID="ret-error">{err}</Text> : null}
        </ScrollView>
      )}

      {state?.return_eligible ? (
        <View style={styles.footer}>
          <TouchableOpacity
            onPress={submit}
            disabled={busy || !chosen.length}
            style={[styles.cta, (busy || !chosen.length) && { opacity: 0.5 }]}
            testID="ret-submit"
          >
            {busy ? <ActivityIndicator color={colors.primaryFg} /> : (
              <Text style={styles.ctaText}>
                Request return{chosen.length ? ` · ${formatINR(refund)}` : ""}
              </Text>
            )}
          </TouchableOpacity>
        </View>
      ) : null}

      <Modal visible={!!done} transparent animationType="fade">
        <View style={styles.modalWrap}>
          <View style={styles.modalCard}>
            <Feather name="check-circle" size={34} color={colors.success} />
            <Text style={styles.modalTitle}>Return requested</Text>
            <Text style={styles.modalBody}>
              {done?.return_number} · {formatINR(done?.refund_amount || 0)}{"\n"}
              The seller has been notified. You can follow every step under My returns.
            </Text>
            <TouchableOpacity
              onPress={() => { setDone(null); router.replace("/returns" as any); }}
              style={styles.cta}
              testID="ret-done"
            >
              <Text style={styles.ctaText}>Track my return</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ label, value, bold, muted }: { label: string; value: string; bold?: boolean; muted?: boolean }) {
  return (
    <View style={styles.sumRow}>
      <Text style={[styles.sumLabel, muted && { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.sumValue, bold && { fontWeight: "900", fontSize: 15 }, muted && { color: colors.textMuted }]}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  iconBtn: { padding: 8, minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  empty: { textAlign: "center", marginTop: 40, color: colors.textMuted },
  infoCard: {
    flexDirection: "row", gap: 10, backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border, borderRadius: 14, padding: 16, alignItems: "center",
  },
  infoText: { flex: 1, fontSize: 13, color: colors.textMain, lineHeight: 19 },
  windowPill: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    backgroundColor: colors.brand100, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
  },
  windowText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  sectionLabel: {
    fontSize: 12, fontWeight: "800", color: colors.textMuted, marginTop: 20, marginBottom: 8,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 12, marginBottom: 8,
  },
  rowName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rowMeta: { fontSize: 11, color: colors.textMuted, marginTop: 3 },
  lockedText: { fontSize: 11, fontWeight: "800", color: colors.textMuted },
  stepper: {
    flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceMuted,
    borderRadius: 999, padding: 2,
  },
  stepBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  stepQty: { minWidth: 24, textAlign: "center", fontWeight: "900", color: colors.textMain },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: 999, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brand100, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  chipTextOn: { color: colors.primary },
  textArea: {
    minHeight: 84, borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    backgroundColor: colors.surface, padding: 12, color: colors.textMain, textAlignVertical: "top",
  },
  summary: {
    marginTop: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 14, padding: 16,
  },
  summaryTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain, marginBottom: 10 },
  sumRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  sumLabel: { fontSize: 13, color: colors.textMain },
  sumValue: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 8 },
  summaryNote: { fontSize: 11, color: colors.textMuted, marginTop: 10, lineHeight: 17 },
  err: { color: colors.error, fontSize: 12, fontWeight: "700", marginTop: 12 },
  footer: {
    padding: spacing.screen, borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  cta: {
    backgroundColor: colors.primary, borderRadius: 999, paddingVertical: 15, alignItems: "center",
    minHeight: 48, justifyContent: "center",
  },
  ctaText: { color: colors.primaryFg, fontWeight: "900", fontSize: 15 },
  modalWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "center", padding: 24 },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 18, padding: 22, alignItems: "center", gap: 10,
  },
  modalTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  modalBody: { fontSize: 13, color: colors.textMuted, textAlign: "center", lineHeight: 19, marginBottom: 8 },
});
