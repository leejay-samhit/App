// POS billing screen — mirrors the web /vendor/pos flow.
// Users add products from their catalogue, tweak qty/discount/GST inline,
// split the payment across cash / UPI / card, then POST to
// /api/vendor/me/pos/sales. Server recomputes totals and decrements stock.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, Modal, ActivityIndicator, Alert, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing, formatINR } from "../../src/theme";
import { matchDeviceCode } from "../../src/device-identity";
import {
  PosSaleItem, PosPayment, PosCustomer, PosPaymentMode,
  computeBillTotals, createSale, getPosSettings, peekInvoiceNo, PosSettings,
} from "../../src/vendor-pos-client";

type Product = { id: string; name: string; price: number; stock: number; category?: string; hsn?: string; unit?: string; gst_pct?: number };

const PAY_MODES: { key: PosPaymentMode; label: string; icon: any }[] = [
  { key: "cash", label: "Cash", icon: "dollar-sign" },
  { key: "upi", label: "UPI", icon: "smartphone" },
  { key: "debit", label: "Debit", icon: "credit-card" },
  { key: "credit", label: "Credit", icon: "credit-card" },
  { key: "netbank", label: "Net Bank", icon: "globe" },
  { key: "credit_sale", label: "Credit Sale", icon: "clock" },
];

export default function VendorPOS() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [q, setQ] = useState("");
  const [cart, setCart] = useState<PosSaleItem[]>([]);
  const [customer, setCustomer] = useState<PosCustomer>({ kind: "walkin", name: "Walk-in Customer" });
  const [gstIncl, setGstIncl] = useState(false);
  const [billDisc, setBillDisc] = useState("");
  const [payments, setPayments] = useState<PosPayment[]>([{ mode: "cash", amount: 0 }]);
  const [notes, setNotes] = useState("");
  const [invoiceNo, setInvoiceNo] = useState<string>("");
  const [settings, setSettings] = useState<PosSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [payOpen, setPayOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [{ data: p }, s, inv] = await Promise.all([
        api.get<Product[]>("/vendor/me/products"),
        getPosSettings(),
        peekInvoiceNo(),
      ]);
      setProducts((p as any).items || (p as any) || []);
      setSettings(s);
      setGstIncl(s.gst_inclusive);
      setInvoiceNo(inv);
    } catch (e) { Alert.alert("Load failed", formatApiError(e)); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return products.map(p => ({ p, hit: null as any }));
    // Oct 2026 — POS search now also matches serial numbers and IMEIs,
    // including every per-unit code, so a phone shop can bill by scanning
    // the box instead of remembering the product name.
    const out: { p: Product; hit: { code: string; label: string } | null }[] = [];
    for (const p of products) {
      if ((p.name || "").toLowerCase().includes(s)) { out.push({ p, hit: null }); continue; }
      const hit = matchDeviceCode(p as any, q);
      if (hit) out.push({ p, hit });
    }
    return out;
  }, [q, products]);

  const addToCart = (p: Product) => {
    setCart(prev => {
      const idx = prev.findIndex(i => i.product_id === p.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = { ...next[idx], qty: next[idx].qty + 1 };
        return next;
      }
      return [...prev, {
        product_id: p.id, name: p.name, hsn: p.hsn || null, unit: p.unit || "pc",
        qty: 1, price: p.price, discount: null, gst_pct: p.gst_pct ?? settings?.default_gst_pct ?? 0,
      }];
    });
  };
  const updateLine = (i: number, patch: Partial<PosSaleItem>) => setCart(c => c.map((it, ix) => ix === i ? { ...it, ...patch } : it));
  const removeLine = (i: number) => setCart(c => c.filter((_, ix) => ix !== i));

  const totals = useMemo(() => computeBillTotals([...cart], { gst_inclusive: gstIncl, bill_discount: billDisc || null, round_off: true }), [cart, gstIncl, billDisc]);

  const totalPaid = useMemo(() => payments.reduce((s, p) => s + (Number(p.amount) || 0), 0), [payments]);

  const submit = async () => {
    if (cart.length === 0) { Alert.alert("Empty cart", "Add at least one item."); return; }
    if (Math.abs(totalPaid - totals.grand_total) > 0.5) {
      Alert.alert("Payment mismatch", `Payments total ₹${totalPaid.toFixed(2)} but bill is ₹${totals.grand_total.toFixed(2)}.`); return;
    }
    setBusy(true);
    try {
      const sale = await createSale({
        items: cart, payments, customer, gst_inclusive: gstIncl,
        bill_discount: billDisc || null, round_off: true, notes,
      });
      // Web-compatible: skip button-Alert (RN-Web no-op) and navigate straight
      // to the invoice preview so the user sees confirmation + can print/share.
      setCart([]); setPayments([{ mode: "cash", amount: 0 }]); setBillDisc(""); setNotes("");
      setPayOpen(false);
      load();
      router.push(`/vendor/invoices?open=${sale.id}` as any);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (typeof detail === "object" && detail?.error === "stock_insufficient") {
        const names = (detail.items || []).map((r: any) => `${r.name} (need ${r.requested}, have ${r.available})`).join("\n");
        Alert.alert("Not enough stock", names);
      } else Alert.alert("Save failed", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>Cloud POS</Text>
          <Text style={styles.sub}>Next invoice · {invoiceNo || "—"}</Text>
        </View>
        <TouchableOpacity onPress={() => router.push("/vendor/settings" as any)} style={styles.iconBtn}><Feather name="settings" size={18} color={colors.textMain} /></TouchableOpacity>
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 200 }} keyboardShouldPersistTaps="handled">
          {/* Search + product list */}
          <View style={styles.searchWrap}>
            <Feather name="search" size={16} color={colors.textMuted} />
            <TextInput
              value={q}
              onChangeText={setQ}
              placeholder="Search name, serial number or IMEI…"
              placeholderTextColor={colors.textMuted}
              style={styles.searchInput}
              autoCapitalize="none"
              autoCorrect={false}
              testID="pos-search"
            />
            {q ? (
              <TouchableOpacity onPress={() => setQ("")} style={styles.clearBtn} testID="pos-search-clear">
                <Feather name="x" size={15} color={colors.textMuted} />
              </TouchableOpacity>
            ) : null}
          </View>
          {q.trim() && filtered.length === 0 ? (
            <Text style={styles.noMatch} testID="pos-no-match">
              No product matches “{q.trim()}”. Serial numbers and IMEIs are searched too — check the product's Device Identity.
            </Text>
          ) : null}
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
            {filtered.slice(0, 30).map(({ p, hit }) => (
              <TouchableOpacity
                key={p.id}
                onPress={() => addToCart(p)}
                style={styles.prodChip}
                testID={`pos-product-${p.id}`}
              >
                <Text style={styles.prodName} numberOfLines={1}>{p.name}</Text>
                <Text style={styles.prodMeta}>{formatINR(p.price)} · stock {p.stock}</Text>
                {hit ? (
                  <Text style={styles.prodHit} numberOfLines={1}>{hit.label}: {hit.code}</Text>
                ) : null}
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Cart */}
          <View style={{ marginTop: 20 }}>
            <Text style={styles.section}>Cart · {cart.length} item{cart.length === 1 ? "" : "s"}</Text>
            {cart.length === 0 ? <Text style={styles.emptyHint}>Tap a product above to start ringing up.</Text> : cart.map((it, i) => (
              <View key={i} style={styles.cartRow}>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                    <Text style={styles.cartName} numberOfLines={2}>{it.name}</Text>
                    <TouchableOpacity onPress={() => removeLine(i)} style={styles.removeBtn}>
                      <Feather name="x" size={14} color="#B91C1C" />
                    </TouchableOpacity>
                  </View>

                  {/* Row 1 — Qty stepper + line total */}
                  <View style={styles.rowMain}>
                    <View style={styles.qtyStepper}>
                      <TouchableOpacity onPress={() => updateLine(i, { qty: Math.max(1, it.qty - 1) })} style={styles.qtyBtn}>
                        <Feather name="minus" size={12} color={colors.textMain} />
                      </TouchableOpacity>
                      <TextInput
                        value={String(it.qty)}
                        onChangeText={(v) => updateLine(i, { qty: Math.max(0, parseFloat(v || "0")) })}
                        keyboardType="numeric"
                        style={styles.qtyInput}
                        selectTextOnFocus
                      />
                      <TouchableOpacity onPress={() => updateLine(i, { qty: it.qty + 1 })} style={styles.qtyBtn}>
                        <Feather name="plus" size={12} color={colors.textMain} />
                      </TouchableOpacity>
                    </View>
                    <Text style={styles.lineTotalBig}>{formatINR(it.line_total || 0)}</Text>
                  </View>

                  {/* Row 2 — Price / Disc / GST — labelled + roomy */}
                  <View style={styles.fieldRow}>
                    <View style={styles.field}>
                      <Text style={styles.fieldLabelSm}>Price ₹</Text>
                      <TextInput
                        value={String(it.price)}
                        onChangeText={(v) => updateLine(i, { price: parseFloat(v || "0") })}
                        keyboardType="numeric"
                        style={styles.fieldInput}
                        selectTextOnFocus
                      />
                    </View>
                    <View style={styles.field}>
                      <Text style={styles.fieldLabelSm}>Disc</Text>
                      <TextInput
                        value={it.discount || ""}
                        onChangeText={(v) => updateLine(i, { discount: v })}
                        style={styles.fieldInput}
                        placeholder="0"
                        placeholderTextColor={colors.textMuted}
                      />
                    </View>
                    <View style={styles.field}>
                      <Text style={styles.fieldLabelSm}>GST %</Text>
                      <TextInput
                        value={String(it.gst_pct ?? 0)}
                        onChangeText={(v) => updateLine(i, { gst_pct: parseFloat(v || "0") })}
                        keyboardType="numeric"
                        style={styles.fieldInput}
                        selectTextOnFocus
                      />
                    </View>
                  </View>
                </View>
              </View>
            ))}
          </View>

          {/* Customer + notes + bill disc + gst toggle */}
          <View style={{ marginTop: 20 }}>
            <Text style={styles.section}>Customer & bill</Text>
            <TextInput value={customer.name} onChangeText={(v) => setCustomer({ ...customer, name: v || "Walk-in Customer", kind: v ? "named" : "walkin" })} placeholder="Customer name" placeholderTextColor={colors.textMuted} style={styles.input} />
            <TextInput value={customer.phone || ""} onChangeText={(v) => setCustomer({ ...customer, phone: v || null, kind: "named" })} placeholder="Phone (optional)" keyboardType="phone-pad" placeholderTextColor={colors.textMuted} style={styles.input} />
            <TextInput value={customer.gstin || ""} onChangeText={(v) => setCustomer({ ...customer, gstin: v || null })} placeholder="GSTIN (optional)" placeholderTextColor={colors.textMuted} style={styles.input} autoCapitalize="characters" />
            <TextInput value={billDisc} onChangeText={setBillDisc} placeholder="Bill discount (e.g. 5% or 50)" placeholderTextColor={colors.textMuted} style={styles.input} />
            <TextInput value={notes} onChangeText={setNotes} placeholder="Notes (optional)" placeholderTextColor={colors.textMuted} style={[styles.input, { height: 60 }]} multiline />
            <TouchableOpacity onPress={() => setGstIncl(v => !v)} style={styles.toggleRow}>
              <Feather name={gstIncl ? "check-square" : "square"} size={18} color={colors.primary} />
              <Text style={{ marginLeft: 8, color: colors.textMain }}>Prices include GST</Text>
            </TouchableOpacity>
          </View>

          {/* Totals card */}
          <View style={styles.totalsCard}>
            <Row label="Subtotal" value={formatINR(totals.subtotal)} />
            <Row label="GST" value={formatINR(totals.gst_total)} />
            {totals.discount_total > 0 ? <Row label="Item discounts" value={`- ${formatINR(totals.discount_total)}`} /> : null}
            {totals.bill_discount > 0 ? <Row label="Bill discount" value={`- ${formatINR(totals.bill_discount)}`} /> : null}
            {totals.round_off !== 0 ? <Row label="Round off" value={formatINR(totals.round_off)} /> : null}
            <View style={{ height: 1, backgroundColor: colors.border, marginVertical: 8 }} />
            <Row label="Grand total" value={formatINR(totals.grand_total)} bold />
          </View>
        </ScrollView>

        <View style={styles.footer}>
          <TouchableOpacity onPress={() => { setPayments([{ mode: "cash", amount: totals.grand_total }]); setPayOpen(true); }} disabled={cart.length === 0} style={[styles.primary, cart.length === 0 && { opacity: 0.4 }]}>
            <Feather name="credit-card" size={18} color="#fff" />
            <Text style={styles.primaryText}>Take payment · {formatINR(totals.grand_total)}</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      {/* Payment modal — split across modes */}
      <Modal visible={payOpen} transparent animationType="slide" onRequestClose={() => setPayOpen(false)}>
        <View style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" }}>
          <View style={styles.payCard}>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <Text style={styles.section}>Payment · {formatINR(totals.grand_total)}</Text>
              <View style={{ flex: 1 }} />
              <TouchableOpacity onPress={() => setPayOpen(false)} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 320 }}>
              {payments.map((p, i) => (
                <View key={i} style={styles.payRow}>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                    {PAY_MODES.map(m => (
                      <TouchableOpacity key={m.key} onPress={() => setPayments(pp => pp.map((x, ix) => ix === i ? { ...x, mode: m.key } : x))} style={[styles.modePill, p.mode === m.key && { backgroundColor: colors.brand100 }]}>
                        <Feather name={m.icon} size={12} color={p.mode === m.key ? colors.primary : colors.textMuted} />
                        <Text style={[styles.modeLabel, p.mode === m.key && { color: colors.primary, fontWeight: "800" }]}>{m.label}</Text>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>
                  <View style={{ flexDirection: "row", alignItems: "center", marginTop: 6 }}>
                    <TextInput value={String(p.amount)} onChangeText={(v) => setPayments(pp => pp.map((x, ix) => ix === i ? { ...x, amount: parseFloat(v || "0") } : x))} keyboardType="numeric" style={[styles.input, { flex: 1, marginBottom: 0 }]} placeholder="Amount" />
                    <TouchableOpacity onPress={() => setPayments(pp => pp.filter((_, ix) => ix !== i))} style={styles.iconBtn}><Feather name="trash-2" size={14} color="#B91C1C" /></TouchableOpacity>
                  </View>
                  <TextInput value={p.reference || ""} onChangeText={(v) => setPayments(pp => pp.map((x, ix) => ix === i ? { ...x, reference: v } : x))} placeholder="Reference (optional)" style={styles.input} placeholderTextColor={colors.textMuted} />
                </View>
              ))}
              <TouchableOpacity onPress={() => setPayments(pp => [...pp, { mode: "upi", amount: Math.max(0, totals.grand_total - totalPaid) }])} style={styles.addPayBtn}>
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={{ color: colors.primary, fontWeight: "700", marginLeft: 6 }}>Add split</Text>
              </TouchableOpacity>
            </ScrollView>
            <Text style={{ marginTop: 8, color: Math.abs(totalPaid - totals.grand_total) < 0.5 ? "#0F6E4F" : "#B91C1C", fontWeight: "700" }}>
              Paid {formatINR(totalPaid)} of {formatINR(totals.grand_total)}
            </Text>
            <TouchableOpacity onPress={submit} disabled={busy} style={[styles.primary, busy && { opacity: 0.5 }, { marginTop: 12 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <><Feather name="check-circle" size={16} color="#fff" /><Text style={styles.primaryText}>Save & print</Text></>}
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 }}>
      <Text style={{ color: colors.textMuted, fontWeight: bold ? "800" : "500" }}>{label}</Text>
      <Text style={{ color: colors.textMain, fontWeight: bold ? "900" : "600", fontSize: bold ? 16 : 14 }}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { padding: 8, borderRadius: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  sub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceMuted, borderRadius: 10, paddingHorizontal: 12, height: 40 },
  searchInput: { flex: 1, color: colors.textMain },
  prodChip: { minWidth: 140, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 10, marginRight: 8 },
  prodName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  prodMeta: { fontSize: 11, color: colors.textMuted, marginTop: 3 },
  prodHit: { fontSize: 10.5, color: colors.primary, fontWeight: "700", marginTop: 3 },
  clearBtn: { width: 28, height: 28, alignItems: "center", justifyContent: "center" },
  noMatch: { fontSize: 12, color: colors.textMuted, marginTop: 10, lineHeight: 17 },
  section: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginBottom: 8 },
  emptyHint: { color: colors.textMuted, fontSize: 12 },
  cartRow: { padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 8 },
  cartName: { fontSize: 14, fontWeight: "700", color: colors.textMain, flex: 1, paddingRight: 6 },
  removeBtn: { width: 28, height: 28, borderRadius: 14, backgroundColor: "#FEE2E2", alignItems: "center", justifyContent: "center" },
  qtyRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6, flexWrap: "wrap" },
  qtyBtn: { width: 30, height: 30, borderRadius: 6, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  qtyInput: { width: 48, height: 34, borderWidth: 1, borderColor: colors.border, borderRadius: 6, paddingHorizontal: 6, textAlign: "center", color: colors.textMain, fontWeight: "700" },
  qtyStepper: { flexDirection: "row", alignItems: "center", gap: 4 },
  rowMain: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10 },
  lineTotalBig: { fontSize: 16, fontWeight: "900", color: colors.primary },
  fieldRow: { flexDirection: "row", gap: 8, marginTop: 10 },
  field: { flex: 1 },
  fieldLabelSm: { fontSize: 10, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.5, marginBottom: 4 },
  fieldInput: { height: 38, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10, color: colors.textMain, fontWeight: "600", backgroundColor: colors.surface },
  priceInput: { width: 66, height: 30, borderWidth: 1, borderColor: colors.border, borderRadius: 6, paddingHorizontal: 6, color: colors.textMain },
  discInput: { width: 56, height: 30, borderWidth: 1, borderColor: colors.border, borderRadius: 6, paddingHorizontal: 6, color: colors.textMain },
  gstInput: { width: 50, height: 30, borderWidth: 1, borderColor: colors.border, borderRadius: 6, paddingHorizontal: 6, color: colors.textMain },
  lineTotal: { marginTop: 4, fontSize: 13, fontWeight: "700", color: colors.primary },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 8, color: colors.textMain, backgroundColor: colors.surface },
  toggleRow: { flexDirection: "row", alignItems: "center", marginTop: 4 },
  totalsCard: { marginTop: 16, padding: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12 },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, padding: spacing.screen, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  primary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 14, borderRadius: 12 },
  primaryText: { color: "#fff", fontWeight: "800", fontSize: 15 },
  payCard: { backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16 },
  payRow: { padding: 10, backgroundColor: colors.surfaceMuted, borderRadius: 10, marginBottom: 8 },
  modePill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.surface, marginRight: 6 },
  modeLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  addPayBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", padding: 8 },
});
