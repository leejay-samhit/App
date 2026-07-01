// Invoices — like /vendor/invoices on the web. Same data as sales but
// with a full-screen invoice preview + share/print.
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, ActivityIndicator, Alert, Share, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { colors, spacing, formatINR } from "../../src/theme";
import { listSales, getSale, PosSale, getPosSettings, PosSettings } from "../../src/vendor-pos-client";
import { formatApiError } from "../../src/api";

export default function VendorInvoices() {
  const router = useRouter();
  const { open } = useLocalSearchParams<{ open?: string }>();
  const [items, setItems] = useState<PosSale[]>([]);
  const [settings, setSettings] = useState<PosSettings | null>(null);
  const [preview, setPreview] = useState<PosSale | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [r, s] = await Promise.all([listSales({ limit: 200, status: "completed" }), getPosSettings()]);
      setItems(r.items); setSettings(s);
      if (open) {
        try { const one = await getSale(String(open)); setPreview(one); } catch { /* ignore */ }
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

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Invoices</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}>
        {loading ? <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} /> :
          items.length === 0 ? <Text style={{ color: colors.textMuted, textAlign: "center", marginTop: 40 }}>No invoices yet.</Text> :
            items.map(s => (
              <TouchableOpacity key={s.id} onPress={() => setPreview(s)} style={styles.card} activeOpacity={0.85}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.inv}>{s.invoice_no}</Text>
                  <Text style={styles.meta}>{new Date(s.created_at).toLocaleString("en-IN")} · {s.customer?.name}</Text>
                </View>
                <Text style={styles.amount}>{formatINR(s.totals.grand_total)}</Text>
              </TouchableOpacity>
            ))
        }
      </ScrollView>

      <Modal visible={!!preview} animationType="slide" onRequestClose={() => setPreview(null)}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setPreview(null)} style={styles.iconBtn}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
            <Text style={styles.title}>{preview?.invoice_no}</Text>
            <View style={{ flex: 1 }} />
            <TouchableOpacity onPress={() => preview && shareInvoice(preview)} style={styles.iconBtn}><Feather name={Platform.OS === "ios" ? "share" : "share-2"} size={18} color={colors.textMain} /></TouchableOpacity>
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen }}>
            {preview ? (
              <>
                <Text style={styles.biz}>{settings?.business_name || "Invoice"}</Text>
                <Text style={styles.bizMeta}>{settings?.business_address}</Text>
                <Text style={styles.bizMeta}>{settings?.business_phone} · GSTIN {settings?.business_gstin || "—"}</Text>

                <View style={{ marginTop: 16 }}>
                  <Text style={styles.section}>Bill to</Text>
                  <Text style={styles.name}>{preview.customer?.name || "—"}</Text>
                  {preview.customer?.phone ? <Text style={styles.bizMeta}>{preview.customer.phone}</Text> : null}
                  {preview.customer?.gstin ? <Text style={styles.bizMeta}>GSTIN {preview.customer.gstin}</Text> : null}
                </View>

                <View style={{ marginTop: 16 }}>
                  <View style={styles.hrow}><Text style={styles.hcell}>#</Text><Text style={[styles.hcell, { flex: 3 }]}>Item</Text><Text style={styles.hcell}>Qty</Text><Text style={styles.hcell}>Price</Text><Text style={styles.hcell}>Total</Text></View>
                  {preview.items.map((it, i) => (
                    <View key={i} style={styles.row}>
                      <Text style={styles.cell}>{i + 1}</Text>
                      <Text style={[styles.cell, { flex: 3 }]} numberOfLines={2}>{it.name}</Text>
                      <Text style={styles.cell}>{it.qty}</Text>
                      <Text style={styles.cell}>{formatINR(it.price)}</Text>
                      <Text style={styles.cell}>{formatINR(it.line_total || 0)}</Text>
                    </View>
                  ))}
                </View>

                <View style={{ marginTop: 16, alignSelf: "flex-end", width: 240 }}>
                  <T r="Subtotal" v={formatINR(preview.totals.subtotal)} />
                  <T r="GST" v={formatINR(preview.totals.gst_total)} />
                  {preview.totals.discount_total > 0 ? <T r="Item disc." v={`- ${formatINR(preview.totals.discount_total)}`} /> : null}
                  {preview.totals.bill_discount > 0 ? <T r="Bill disc." v={`- ${formatINR(preview.totals.bill_discount)}`} /> : null}
                  {preview.totals.round_off !== 0 ? <T r="Round-off" v={formatINR(preview.totals.round_off)} /> : null}
                  <View style={{ height: 1, backgroundColor: colors.border, marginVertical: 6 }} />
                  <T r="Grand total" v={formatINR(preview.totals.grand_total)} bold />
                </View>

                <Text style={styles.section}>Payments</Text>
                {(preview.payments || []).map((p, i) => (
                  <Text key={i} style={styles.bizMeta}>{p.mode.toUpperCase()} · {formatINR(p.amount)}{p.reference ? ` · ${p.reference}` : ""}</Text>
                ))}
                {preview.notes ? <><Text style={styles.section}>Notes</Text><Text style={styles.bizMeta}>{preview.notes}</Text></> : null}
              </>
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function T({ r, v, bold }: { r: string; v: string; bold?: boolean }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: 3 }}>
      <Text style={{ color: colors.textMuted, fontWeight: bold ? "800" : "500" }}>{r}</Text>
      <Text style={{ color: colors.textMain, fontWeight: bold ? "900" : "700", fontSize: bold ? 15 : 13 }}>{v}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { padding: 8 },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  card: { flexDirection: "row", alignItems: "center", padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 8 },
  inv: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  amount: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  biz: { fontSize: 20, fontWeight: "900", color: colors.textMain },
  bizMeta: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  section: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, textTransform: "uppercase", marginTop: 10, marginBottom: 4 },
  name: { fontSize: 14, color: colors.textMain, fontWeight: "700" },
  hrow: { flexDirection: "row", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
  hcell: { flex: 1, fontSize: 11, fontWeight: "800", color: colors.textMuted, textTransform: "uppercase" },
  row: { flexDirection: "row", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.surfaceMuted },
  cell: { flex: 1, fontSize: 13, color: colors.textMain },
});
