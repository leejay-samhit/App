// Invoices — like /vendor/invoices on the web. Same data as sales but
// with a full-screen invoice preview + share + print.
//
// June 2026 redesign per user request:
//   • Professional invoice layout (brand header, meta card, line-item table,
//     totals ladder, thank-you footer) — no more "plain text" look.
//   • Print button using expo-print to render a matching HTML invoice
//     to a system printer / PDF viewer / share sheet.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal,
  ActivityIndicator, Alert, Share, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import * as Print from "expo-print";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { listSales, getSale, PosSale, getPosSettings, PosSettings } from "../../src/vendor-pos-client";
import { formatApiError } from "../../src/api";
import { FadeSlideIn, ListRowSkeleton } from "../../src/anim";

export default function VendorInvoices() {
  const router = useRouter();
  const { open } = useLocalSearchParams<{ open?: string }>();
  const [items, setItems] = useState<(PosSale & { _channel?: "pos" | "online" })[]>([]);
  const [settings, setSettings] = useState<PosSettings | null>(null);
  const [preview, setPreview] = useState<(PosSale & { _channel?: "pos" | "online" }) | null>(null);
  const [loading, setLoading] = useState(true);
  const [printing, setPrinting] = useState(false);
  const [channel, setChannel] = useState<"all" | "pos" | "online">("all");

  const load = useCallback(async () => {
    try {
      // Jul 2026 — Merge POS + online sales into the invoices list so
      // vendors have a single place to review every sale document.
      // Online sales come from /api/vendor/me/sales (which now also
      // includes POS rows tagged with `channel: "pos"`, but here we
      // just want the online rows to avoid double-counting).
      const [posRes, s, onlineRes] = await Promise.all([
        listSales({ limit: 200, status: "completed" }),
        getPosSettings(),
        (async () => {
          try {
            const { api } = await import("../../src/api");
            const r = await api.get<{ items: any[] }>("/vendor/me/sales");
            return r.data?.items || [];
          } catch { return []; }
        })(),
      ]);
      // Online sales are order-shaped — reshape to PosSale-compatible.
      const onlineOnly = (onlineRes as any[]).filter((o) => o.channel !== "pos");
      const onlineAsInvoice = onlineOnly.map((o: any) => {
        const items = Array.isArray(o.items) ? o.items : [];
        const total = Number(o.total || 0);
        return {
          id: o.order_id || o.id,
          vendor_id: "",
          invoice_no: `ORD-${String(o.order_id || o.id).slice(0, 8).toUpperCase()}`,
          created_at: o.created_at,
          status: (o.status === "cancelled" ? "cancelled" : "completed") as any,
          customer: {
            name: o.buyer_name || "Customer",
            phone: o.buyer_phone || "",
            email: o.buyer_email || "",
            gstin: "",
          },
          gst_inclusive: true,
          totals: {
            subtotal: total,
            gst_total: 0,
            grand_total: total,
            round_off: 0,
          },
          notes: "",
          items: items.map((it: any) => ({
            product_id: "",
            name: it.name || "Item",
            price: Number(it.price || 0),
            qty: Number(it.qty || 1),
            gst_pct: 0,
            gst_amount: 0,
            line_total: Number(it.price || 0) * Number(it.qty || 1),
          })),
          payments: [{ mode: (o.paid_via || "wallet"), amount: total, reference: "" }],
          _channel: "online" as const,
        };
      });
      const posWithTag = (posRes.items || []).map((s) => ({ ...s, _channel: "pos" as const }));
      const merged = [...posWithTag, ...onlineAsInvoice]
        .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setItems(merged);
      setSettings(s);
      if (open) {
        try {
          const one = await getSale(String(open));
          setPreview({ ...one, _channel: "pos" });
        } catch { /* ignore */ }
      }
    } catch (e) { Alert.alert("Load failed", formatApiError(e)); }
    finally { setLoading(false); }
  }, [open]);

  useEffect(() => { load(); }, [load]);

  const shareInvoice = async (s: PosSale) => {
    const lines = [
      `${settings?.business_name || "Invoice"}`,
      `Invoice ${s.invoice_no} · ${new Date(s.created_at).toLocaleString("en-IN")}`,
      `Customer: ${s.customer?.name}${s.customer?.phone ? " · " + s.customer.phone : ""}`,
      "",
      ...s.items.map((it, i) => `${i + 1}. ${it.name}  ${it.qty} x ${formatINR(it.price)}  = ${formatINR(it.line_total || 0)}`),
      "",
      `Subtotal: ${formatINR(s.totals.subtotal)}`,
      `GST: ${formatINR(s.totals.gst_total)}`,
      `Grand total: ${formatINR(s.totals.grand_total)}`,
    ].join("\n");
    try { await Share.share({ message: lines }); } catch {}
  };

  // ── Print / PDF export ──────────────────────────────────────────────
  // We hand-render an HTML invoice matching the on-screen preview and
  // pass it to expo-print. iOS/Android open the system print dialog
  // (which can save PDF, share, or spool to a paired printer). Web
  // opens a new tab with the print preview.
  const buildInvoiceHtml = (s: PosSale): string => {
    const biz = settings?.business_name || "Slangcart";
    const bizAddr = settings?.business_address || "";
    const bizPhone = settings?.business_phone || "";
    const bizGst = settings?.business_gstin || "";
    const cust = s.customer || {};
    const rows = (s.items || []).map((it, i) => `
      <tr>
        <td style="padding:8px;border-bottom:1px solid #EEE;">${i + 1}</td>
        <td style="padding:8px;border-bottom:1px solid #EEE;">${escapeHtml(it.name)}</td>
        <td style="padding:8px;border-bottom:1px solid #EEE;text-align:right;">${it.qty}</td>
        <td style="padding:8px;border-bottom:1px solid #EEE;text-align:right;">${formatINR(it.price)}</td>
        <td style="padding:8px;border-bottom:1px solid #EEE;text-align:right;">${formatINR(it.line_total || 0)}</td>
      </tr>
    `).join("");
    const payments = (s.payments || []).map(
      (p) => `${p.mode.toUpperCase()} — ${formatINR(p.amount)}${p.reference ? " · " + escapeHtml(p.reference) : ""}`,
    ).join("<br/>");

    return `<!doctype html><html><head><meta charset="utf-8"/>
      <title>Invoice ${s.invoice_no}</title>
      <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; color: #111; padding: 32px; max-width: 720px; margin: 0 auto; }
        h1 { font-size: 32px; margin: 0; color: #10B981; letter-spacing: 3px; }
        h2 { font-size: 14px; letter-spacing: 1px; color: #666; margin: 24px 0 8px; }
        .brand-head { text-align: center; border-bottom: 2px solid #10B981; padding-bottom: 16px; margin-bottom: 16px; }
        .biz-line { color: #666; font-size: 12px; margin-top: 4px; }
        .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 12px; background: #F9FAFB; border-radius: 8px; margin-bottom: 16px; }
        .meta-cell b { display: block; color: #6B7280; font-size: 10px; letter-spacing: 1px; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 8px; background: #F3F4F6; font-size: 11px; letter-spacing: 1px; text-transform: uppercase; color: #6B7280; }
        .totals { margin-top: 12px; margin-left: auto; width: 260px; }
        .totals-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
        .totals-grand { border-top: 2px solid #111; margin-top: 6px; padding-top: 8px; font-weight: 900; font-size: 18px; }
        .thanks { text-align: center; margin-top: 32px; color: #6B7280; font-style: italic; font-size: 12px; }
      </style></head><body>
      <div class="brand-head">
        <h1>${escapeHtml(biz).toUpperCase()}</h1>
        <div class="biz-line">${escapeHtml(bizAddr)}</div>
        <div class="biz-line">${escapeHtml(bizPhone)}${bizGst ? " · GSTIN " + escapeHtml(bizGst) : ""}</div>
      </div>
      <div class="meta">
        <div class="meta-cell"><b>INVOICE</b>${escapeHtml(s.invoice_no)}</div>
        <div class="meta-cell"><b>DATE</b>${new Date(s.created_at).toLocaleString("en-IN")}</div>
        <div class="meta-cell"><b>BILL TO</b>${escapeHtml(cust.name || "Walk-in")}${cust.phone ? " · " + escapeHtml(cust.phone) : ""}</div>
        <div class="meta-cell"><b>GSTIN</b>${escapeHtml(cust.gstin || "—")}</div>
      </div>
      <h2>ITEMS</h2>
      <table>
        <thead><tr><th>#</th><th>Item</th><th style="text-align:right;">Qty</th><th style="text-align:right;">Price</th><th style="text-align:right;">Total</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="totals">
        <div class="totals-row"><span>Subtotal</span><span>${formatINR(s.totals.subtotal)}</span></div>
        <div class="totals-row"><span>GST</span><span>${formatINR(s.totals.gst_total)}</span></div>
        ${s.totals.discount_total > 0 ? `<div class="totals-row"><span>Item disc.</span><span>-${formatINR(s.totals.discount_total)}</span></div>` : ""}
        ${s.totals.bill_discount > 0 ? `<div class="totals-row"><span>Bill disc.</span><span>-${formatINR(s.totals.bill_discount)}</span></div>` : ""}
        ${s.totals.round_off !== 0 ? `<div class="totals-row"><span>Round-off</span><span>${formatINR(s.totals.round_off)}</span></div>` : ""}
        <div class="totals-row totals-grand"><span>Grand Total</span><span>${formatINR(s.totals.grand_total)}</span></div>
      </div>
      ${payments ? `<h2>PAYMENTS</h2><div style="font-size:13px;color:#374151;">${payments}</div>` : ""}
      ${s.notes ? `<h2>NOTES</h2><div style="font-size:13px;color:#374151;">${escapeHtml(s.notes)}</div>` : ""}
      <div class="thanks">Thank you for your business!</div>
      </body></html>`;
  };

  const escapeHtml = (str: string): string =>
    String(str || "").replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" } as any)[ch] || ch,
    );

  const printInvoice = async (s: PosSale) => {
    setPrinting(true);
    try {
      const html = buildInvoiceHtml(s);
      if (Platform.OS === "web") {
        // Web: open printable HTML in a new window.
        try {
          const w = window.open("", "_blank");
          if (w) {
            w.document.write(html);
            w.document.close();
            w.focus();
            setTimeout(() => w.print(), 400);
          } else {
            Alert.alert("Popup blocked", "Please allow popups to print the invoice.");
          }
        } catch (e) {
          Alert.alert("Print failed", formatApiError(e));
        }
      } else {
        await Print.printAsync({ html });
      }
    } catch (e) {
      Alert.alert("Print failed", formatApiError(e));
    } finally {
      setPrinting(false);
    }
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Invoices</Text>
      </View>
      {/* Jul 2026 — Channel filter (POS / Online / All) */}
      <View style={{ flexDirection: "row", marginHorizontal: spacing.screen, backgroundColor: colors.surfaceMuted, borderRadius: 99, padding: 4, gap: 2, marginBottom: 8 }}>
        {(["all", "pos", "online"] as const).map((t) => (
          <TouchableOpacity
            key={t}
            onPress={() => setChannel(t)}
            style={{
              flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 99,
              backgroundColor: channel === t ? colors.primary : "transparent",
            }}
            testID={`inv-tab-${t}`}
          >
            <Text style={{ fontSize: 11, fontWeight: "800", color: channel === t ? colors.primaryFg : colors.textMuted, letterSpacing: 0.6 }}>
              {t === "all" ? "ALL" : t === "pos" ? "POS · NEW" : "ONLINE SHOP"}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}>
        {loading ? (
          <View>{[...Array(5)].map((_, i) => <ListRowSkeleton key={i} />)}</View>
        ) : (() => {
            const filtered = channel === "all" ? items : items.filter((s) => s._channel === channel);
            if (filtered.length === 0) return <Text style={{ color: colors.textMuted, textAlign: "center", marginTop: 40 }}>No invoices in this view.</Text>;
            return filtered.map((s, idx) => (
              <FadeSlideIn key={`${s._channel}-${s.id}`} delay={Math.min(idx, 6) * 40}>
              <TouchableOpacity onPress={() => setPreview(s)} style={styles.card} activeOpacity={0.85}>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.inv} numberOfLines={1}>{s.invoice_no}</Text>
                    <View style={{
                      paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                      backgroundColor: s._channel === "online" ? "#3B82F620" : "#10B98120",
                    }}>
                      <Text style={{
                        fontSize: 9, fontWeight: "800", letterSpacing: 0.6,
                        color: s._channel === "online" ? "#1D4ED8" : "#047857",
                      }}>{s._channel === "online" ? "ONLINE" : "POS"}</Text>
                    </View>
                  </View>
                  <Text style={styles.meta}>{new Date(s.created_at).toLocaleString("en-IN")} · {s.customer?.name || "Walk-in"}</Text>
                </View>
                <Text style={styles.amount}>{formatINR(s.totals.grand_total)}</Text>
              </TouchableOpacity>
              </FadeSlideIn>
            ));
          })()
        }
      </ScrollView>

      <Modal visible={!!preview} animationType="slide" onRequestClose={() => setPreview(null)}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.previewHeader}>
            <TouchableOpacity onPress={() => setPreview(null)} style={styles.iconBtn} testID="vinvoice-close">
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <View style={{ flex: 1 }}>
              <Text style={styles.previewTitle}>{preview?.invoice_no}</Text>
              <Text style={styles.previewSub}>Tap 🖨 to print or share</Text>
            </View>
            <TouchableOpacity onPress={() => preview && shareInvoice(preview)} style={styles.iconBtn} testID="vinvoice-share">
              <Feather name={Platform.OS === "ios" ? "share" : "share-2"} size={18} color={colors.textMain} />
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => preview && printInvoice(preview)}
              disabled={printing || !preview}
              style={[styles.iconBtn, printing && { opacity: 0.5 }]}
              testID="vinvoice-print"
            >
              {printing ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="printer" size={18} color={colors.primary} />}
            </TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
            {preview ? (
              <>
                {/* Brand header — big shop name + address + GSTIN */}
                <View style={styles.brandHead}>
                  <Text style={styles.brandName}>{(settings?.business_name || "Slangcart").toUpperCase()}</Text>
                  {settings?.business_address ? <Text style={styles.brandLine}>{settings.business_address}</Text> : null}
                  <Text style={styles.brandLine}>
                    {settings?.business_phone || ""}
                    {settings?.business_gstin ? `  ·  GSTIN ${settings.business_gstin}` : ""}
                  </Text>
                </View>

                {/* Meta */}
                <View style={styles.metaCard}>
                  <View style={styles.metaCell}>
                    <Text style={styles.metaLabel}>INVOICE</Text>
                    <Text style={styles.metaValue}>{preview.invoice_no}</Text>
                  </View>
                  <View style={styles.metaCell}>
                    <Text style={styles.metaLabel}>DATE</Text>
                    <Text style={styles.metaValue}>{new Date(preview.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</Text>
                  </View>
                  <View style={styles.metaCell}>
                    <Text style={styles.metaLabel}>BILL TO</Text>
                    <Text style={styles.metaValue}>{preview.customer?.name || "Walk-in"}</Text>
                    {preview.customer?.phone ? <Text style={styles.metaSub}>{preview.customer.phone}</Text> : null}
                  </View>
                  <View style={styles.metaCell}>
                    <Text style={styles.metaLabel}>GSTIN</Text>
                    <Text style={styles.metaValue}>{preview.customer?.gstin || "—"}</Text>
                  </View>
                </View>

                {/* Items table */}
                <Text style={styles.sectionTitle}>ITEMS</Text>
                <View style={styles.tableWrap}>
                  <View style={styles.tableHeader}>
                    <Text style={[styles.headCell, { flex: 0.4 }]}>#</Text>
                    <Text style={[styles.headCell, { flex: 3 }]}>Item</Text>
                    <Text style={[styles.headCell, { flex: 0.7, textAlign: "right" }]}>Qty</Text>
                    <Text style={[styles.headCell, { flex: 1.1, textAlign: "right" }]}>Price</Text>
                    <Text style={[styles.headCell, { flex: 1.2, textAlign: "right" }]}>Total</Text>
                  </View>
                  {preview.items.map((it, i) => (
                    <View key={i} style={styles.tableRow}>
                      <Text style={[styles.bodyCell, { flex: 0.4 }]}>{i + 1}</Text>
                      <Text style={[styles.bodyCell, { flex: 3 }]} numberOfLines={2}>{it.name}</Text>
                      <Text style={[styles.bodyCell, { flex: 0.7, textAlign: "right" }]}>{it.qty}</Text>
                      <Text style={[styles.bodyCell, { flex: 1.1, textAlign: "right" }]}>{formatINR(it.price)}</Text>
                      <Text style={[styles.bodyCell, { flex: 1.2, textAlign: "right", fontWeight: "800" }]}>{formatINR(it.line_total || 0)}</Text>
                    </View>
                  ))}
                </View>

                {/* Totals ladder */}
                <View style={styles.totalsCard}>
                  <TotalRow label="Subtotal" value={formatINR(preview.totals.subtotal)} />
                  <TotalRow label="GST" value={formatINR(preview.totals.gst_total)} />
                  {preview.totals.discount_total > 0 ? <TotalRow label="Item disc." value={`- ${formatINR(preview.totals.discount_total)}`} /> : null}
                  {preview.totals.bill_discount > 0 ? <TotalRow label="Bill disc." value={`- ${formatINR(preview.totals.bill_discount)}`} /> : null}
                  {preview.totals.round_off !== 0 ? <TotalRow label="Round-off" value={formatINR(preview.totals.round_off)} /> : null}
                  <View style={styles.grandDivider} />
                  <View style={styles.grandRow}>
                    <Text style={styles.grandLabel}>Grand Total</Text>
                    <Text style={styles.grandValue}>{formatINR(preview.totals.grand_total)}</Text>
                  </View>
                </View>

                {(preview.payments || []).length > 0 ? (
                  <>
                    <Text style={styles.sectionTitle}>PAYMENTS</Text>
                    {(preview.payments || []).map((p, i) => (
                      <View key={i} style={styles.payRow}>
                        <Feather name="credit-card" size={13} color={colors.primary} />
                        <Text style={styles.payText}>{p.mode.toUpperCase()} · {formatINR(p.amount)}{p.reference ? `  ·  ${p.reference}` : ""}</Text>
                      </View>
                    ))}
                  </>
                ) : null}

                {preview.notes ? (
                  <>
                    <Text style={styles.sectionTitle}>NOTES</Text>
                    <Text style={styles.notes}>{preview.notes}</Text>
                  </>
                ) : null}

                <Text style={styles.footerNote}>Thank you for your business!</Text>

                {/* Bottom action row */}
                <View style={styles.actionRow}>
                  <TouchableOpacity onPress={() => preview && shareInvoice(preview)} style={styles.actionGhost}>
                    <Feather name={Platform.OS === "ios" ? "share" : "share-2"} size={14} color={colors.primary} />
                    <Text style={styles.actionGhostText}>Share text</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => preview && printInvoice(preview)}
                    disabled={printing}
                    style={[styles.actionPrimary, printing && { opacity: 0.5 }]}
                    testID="vinvoice-print-cta"
                  >
                    {printing
                      ? <ActivityIndicator color="#fff" size="small" />
                      : <><Feather name="printer" size={14} color="#fff" /><Text style={styles.actionPrimaryText}>Print / PDF</Text></>}
                  </TouchableOpacity>
                </View>
              </>
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function TotalRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.totalRow}>
      <Text style={styles.totalLabel}>{label}</Text>
      <Text style={styles.totalValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  previewHeader: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface, gap: 6 },
  iconBtn: { padding: 8, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  previewTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  previewSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  card: { flexDirection: "row", alignItems: "center", padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 8 },
  inv: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  amount: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  // Invoice body
  brandHead: { alignItems: "center", paddingVertical: 16, borderBottomWidth: 2, borderBottomColor: colors.primary, marginBottom: 16 },
  brandName: { fontSize: 26, fontWeight: "900", color: colors.primary, letterSpacing: 2 },
  brandLine: { fontSize: 12, color: colors.textMuted, marginTop: 4, textAlign: "center" },
  metaCard: { flexDirection: "row", flexWrap: "wrap", backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 12, marginBottom: 16 },
  metaCell: { width: "50%", paddingVertical: 6 },
  metaLabel: { fontSize: 9, color: colors.textMuted, fontWeight: "800", letterSpacing: 1 },
  metaValue: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 3 },
  metaSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  sectionTitle: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, marginTop: 12, marginBottom: 8 },
  tableWrap: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, overflow: "hidden" },
  tableHeader: { flexDirection: "row", backgroundColor: colors.surfaceMuted, paddingVertical: 8, paddingHorizontal: 10 },
  headCell: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 1 },
  tableRow: { flexDirection: "row", paddingVertical: 10, paddingHorizontal: 10, borderTopWidth: 1, borderTopColor: colors.border, alignItems: "center" },
  bodyCell: { fontSize: 12, color: colors.textMain },
  totalsCard: { marginTop: 12, padding: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card },
  totalRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  totalLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  totalValue: { fontSize: 13, color: colors.textMain, fontWeight: "700" },
  grandDivider: { height: 2, backgroundColor: colors.textMain, marginVertical: 8 },
  grandRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  grandLabel: { fontSize: 14, fontWeight: "900", color: colors.textMain, letterSpacing: 0.5 },
  grandValue: { fontSize: 22, fontWeight: "900", color: colors.primary, letterSpacing: -0.5 },
  payRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 },
  payText: { fontSize: 12, color: colors.textMain, fontWeight: "600" },
  notes: { fontSize: 12, color: colors.textMain, lineHeight: 18, padding: 10, backgroundColor: colors.surface, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  footerNote: { textAlign: "center", fontSize: 12, color: colors.textMuted, marginTop: 20, fontStyle: "italic" },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 20 },
  actionGhost: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: radii.button, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface },
  actionGhostText: { fontSize: 13, fontWeight: "800", color: colors.primary },
  actionPrimary: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 12, borderRadius: radii.button, backgroundColor: colors.primary },
  actionPrimaryText: { fontSize: 13, fontWeight: "800", color: "#fff" },
});
