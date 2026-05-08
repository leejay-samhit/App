import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity,
  Modal, ScrollView, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { WebView } from "react-native-webview";
import { api } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { downloadInvoicePdf, fetchInvoiceHtml } from "../../src/invoices";

type Txn = {
  id: string;
  user_id: string;
  user_name?: string;
  user_email?: string;
  user_referral_code?: string;
  type: string;
  amount: number;
  status: string;
  description?: string;
  reference_number?: string;
  created_at: string;
};

type TxDetail = {
  transaction: Txn & Record<string, any>;
  owner: { id: string; name: string; email: string; phone?: string; referral_code?: string } | null;
  counter_party?: { id?: string; name?: string; email?: string; phone?: string; referral_code?: string } | null;
  counter_role?: string;
  auto_remarks?: string;
  utr?: string;
  invoice_number?: string;
  invoiceable?: boolean;
};

export default function AdminTxns() {
  const [items, setItems] = useState<Txn[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [includePending, setIncludePending] = useState(false);

  // detail modal
  const [detail, setDetail] = useState<TxDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // invoice preview / download
  const [invoiceHtml, setInvoiceHtml] = useState<string | null>(null);
  const [invoiceBusy, setInvoiceBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Txn[]>(`/admin/transactions${includePending ? "?include_pending=true" : ""}`);
      setItems(data);
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [includePending]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openDetail = async (txnId: string) => {
    setDetailLoading(true);
    setDetail(null);
    try {
      const { data } = await api.get<TxDetail>(`/transactions/${txnId}`);
      setDetail(data);
    } catch (e: any) {
      Alert.alert("Failed to load detail", e?.response?.data?.detail || e?.message || "Try again");
    } finally {
      setDetailLoading(false);
    }
  };

  const onPreviewInvoice = async () => {
    if (!detail?.transaction?.id) return;
    setInvoiceBusy(true);
    try {
      const html = await fetchInvoiceHtml(detail.transaction.id);
      setInvoiceHtml(html);
    } catch (e: any) {
      Alert.alert("Could not load invoice", e?.message || "Try again");
    } finally {
      setInvoiceBusy(false);
    }
  };
  const onDownloadInvoice = async () => {
    if (!detail?.transaction?.id) return;
    setInvoiceBusy(true);
    try { await downloadInvoicePdf(detail.transaction.id, detail.invoice_number); }
    finally { setInvoiceBusy(false); }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  const tx = detail?.transaction;
  const sign = (tx?.amount ?? 0) >= 0 ? "+" : "";
  const amtColor = (tx?.amount ?? 0) >= 0 ? colors.success : "#B3261E";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <FlatList
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        ListHeaderComponent={
          <View>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.h1}>Transactions</Text>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4, marginBottom: 20 }}>
              <Text style={styles.sub}>{items.length} total</Text>
              <TouchableOpacity onPress={() => setIncludePending((v) => !v)} style={styles.toggle} testID="toggle-pending">
                <Feather name={includePending ? "eye" : "eye-off"} size={13} color={colors.primary} />
                <Text style={styles.toggleText}>{includePending ? "Showing pending/failed" : "Hide pending/failed"}</Text>
              </TouchableOpacity>
            </View>
          </View>
        }
        data={items}
        keyExtractor={(i) => i.id}
        renderItem={({ item }) => (
          <TouchableOpacity onPress={() => openDetail(item.id)} style={styles.row} testID={`txn-${item.id}`}>
            <View style={styles.iconBox}>
              <Feather
                name={item.type === "referral_payout" ? "trending-up" : item.type === "withdrawal" ? "arrow-up-right" : item.type === "gst_collected" ? "percent" : "credit-card"}
                size={16}
                color={colors.primary}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.title} numberOfLines={1}>
                {item.user_name || "—"} · <Text style={{ color: colors.textMuted, fontWeight: "500" }}>{(item.type || "").replace(/_/g, " ")}</Text>
              </Text>
              <Text style={styles.desc} numberOfLines={1}>{item.description || ""}</Text>
              <Text style={styles.meta} numberOfLines={1}>
                {new Date(item.created_at).toLocaleString()}
                {item.reference_number ? ` · Ref ${item.reference_number}` : ""}
              </Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={[styles.amount, { color: item.amount >= 0 ? colors.success : "#B3261E" }]}>
                {item.amount >= 0 ? "+" : ""}{formatINR(item.amount)}
              </Text>
              <Feather name="chevron-right" size={14} color={colors.textMuted} style={{ marginTop: 2 }} />
            </View>
          </TouchableOpacity>
        )}
        ListEmptyComponent={<Text style={styles.empty}>No transactions yet</Text>}
      />

      {/* Detail loading spinner overlay */}
      {detailLoading && (
        <View style={styles.spinnerOverlay} pointerEvents="none">
          <ActivityIndicator color={colors.primary} size="large" />
        </View>
      )}

      {/* Detail modal */}
      <Modal visible={!!detail} animationType="slide" transparent statusBarTranslucent onRequestClose={() => setDetail(null)}>
        <View style={styles.modalBackdrop}>
          <TouchableOpacity activeOpacity={1} style={StyleSheet.absoluteFillObject} onPress={() => setDetail(null)} />
          <View style={styles.sheet}>
            <View style={styles.sheetHandle} />
            <ScrollView showsVerticalScrollIndicator={false}>
              {/* Amount & meta */}
              <Text style={styles.detailType}>{(tx?.type || "").toUpperCase().replace(/_/g, " ")}</Text>
              <Text style={[styles.detailAmount, { color: amtColor }]}>
                {sign}{formatINR(tx?.amount || 0)}
              </Text>
              <Text style={styles.detailDate}>{tx?.created_at ? new Date(tx.created_at).toLocaleString() : ""}</Text>

              {/* Status pill */}
              <View style={styles.statusRow}>
                <View style={[styles.pill, { backgroundColor: tx?.status === "paid" || tx?.status === "success" ? colors.success + "20" : "#F3F1EC" }]}>
                  <Text style={[styles.pillText, { color: tx?.status === "paid" || tx?.status === "success" ? colors.success : colors.textMuted }]}>
                    {(tx?.status || "").toUpperCase()}
                  </Text>
                </View>
              </View>

              {/* Auto remarks summary */}
              {detail?.auto_remarks ? (
                <View style={styles.remarkBox}>
                  <Feather name="info" size={14} color={colors.primary} />
                  <Text style={styles.remarkText}>{detail.auto_remarks}</Text>
                </View>
              ) : null}

              {/* Transaction core fields */}
              <Text style={styles.section}>TRANSACTION</Text>
              <Row k="Txn ID" v={(tx?.id || "").toUpperCase()} mono />
              <Row k="Type" v={(tx?.type || "").replace(/_/g, " ")} />
              <Row k="Status" v={(tx?.status || "").toUpperCase()} />
              {!!detail?.utr && <Row k="UTR" v={detail.utr} mono />}
              {!!tx?.razorpay_payment_id && <Row k="Razorpay ID" v={tx.razorpay_payment_id} mono />}
              {!!tx?.razorpay_order_id && <Row k="Razorpay Order" v={tx.razorpay_order_id} mono />}
              {!!tx?.description && <Row k="Description" v={tx.description} />}
              {!!tx?.remarks && tx.remarks !== tx.description && <Row k="Remarks" v={tx.remarks} />}

              {/* Owner / user info */}
              {detail?.owner && (
                <>
                  <Text style={styles.section}>USER</Text>
                  <Row k="Name" v={detail.owner.name || "—"} />
                  <Row k="Email" v={detail.owner.email || "—"} />
                  {!!detail.owner.phone && <Row k="Phone" v={detail.owner.phone} />}
                  {!!detail.owner.referral_code && <Row k="Member ID" v={detail.owner.referral_code} mono />}
                </>
              )}

              {/* Counter-party */}
              {detail?.counter_party && (detail.counter_party.name || detail.counter_party.email) && (
                <>
                  <Text style={styles.section}>{detail.counter_role === "admin" ? "FROM ADMIN" : (detail.counter_role || "COUNTER-PARTY").toUpperCase()}</Text>
                  <Row k="Name" v={detail.counter_party.name || "—"} />
                  {!!detail.counter_party.email && <Row k="Email" v={detail.counter_party.email} />}
                  {!!detail.counter_party.phone && <Row k="Phone" v={detail.counter_party.phone} />}
                </>
              )}

              {/* Invoice */}
              {detail?.invoiceable && detail?.invoice_number ? (
                <View style={styles.invoiceBox}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <Feather name="file-text" size={16} color={colors.primary} />
                    <Text style={styles.invoiceTitle}>GST INVOICE</Text>
                  </View>
                  <Text style={styles.invoiceNo}>{detail.invoice_number}</Text>
                  <Text style={styles.invoiceSub}>18% GST applied per Indian GST law (CGST 9% + SGST 9%).</Text>
                  <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                    <TouchableOpacity onPress={onPreviewInvoice} disabled={invoiceBusy} style={styles.invoiceBtnSecondary}>
                      {invoiceBusy ? <ActivityIndicator color={colors.primary} /> : (
                        <><Feather name="eye" size={14} color={colors.primary} /><Text style={styles.invoiceBtnSecondaryText}>Preview</Text></>
                      )}
                    </TouchableOpacity>
                    <TouchableOpacity onPress={onDownloadInvoice} disabled={invoiceBusy} style={styles.invoiceBtnPrimary}>
                      {invoiceBusy ? <ActivityIndicator color={colors.primaryFg} /> : (
                        <><Feather name="download" size={14} color={colors.primaryFg} /><Text style={styles.invoiceBtnPrimaryText}>Download PDF</Text></>
                      )}
                    </TouchableOpacity>
                  </View>
                </View>
              ) : null}

              <TouchableOpacity onPress={() => setDetail(null)} style={[styles.closeBtn, { marginTop: 18 }]}>
                <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Close</Text>
              </TouchableOpacity>
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Invoice HTML preview */}
      <Modal visible={!!invoiceHtml} animationType="slide" onRequestClose={() => setInvoiceHtml(null)}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.invoiceHeader}>
            <TouchableOpacity onPress={() => setInvoiceHtml(null)} style={styles.invoiceCloseBtn}>
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.invoiceHeaderTitle}>GST Invoice</Text>
            <TouchableOpacity onPress={onDownloadInvoice} style={styles.invoiceCloseBtn} disabled={invoiceBusy}>
              {invoiceBusy ? <ActivityIndicator color={colors.primary} size="small" /> : <Feather name="download" size={20} color={colors.primary} />}
            </TouchableOpacity>
          </View>
          {invoiceHtml ? (
            Platform.OS === "web" ? (
              // @ts-ignore web iframe via dom element on RNW
              <iframe srcDoc={invoiceHtml} style={{ flex: 1, border: 0, width: "100%", height: "100%" } as any} title="invoice-preview" />
            ) : (
              <WebView originWhitelist={["*"]} source={{ html: invoiceHtml }} style={{ flex: 1, backgroundColor: "#fff" }} />
            )
          ) : null}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <View style={styles.dRow}>
      <Text style={styles.dKey}>{k}</Text>
      <Text style={[styles.dVal, mono ? { fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", fontSize: 12 } : null]} numberOfLines={3}>{v}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 6 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  sub: { fontSize: 13, color: colors.textMuted },
  toggle: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.brand100 },
  toggleText: { fontSize: 11, fontWeight: "700", color: colors.primary, letterSpacing: 0.5 },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8 },
  iconBox: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginRight: 12 },
  title: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  desc: { fontSize: 12, color: colors.textMain, marginTop: 2 },
  meta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  amount: { fontSize: 14, fontWeight: "800" },
  empty: { padding: 24, textAlign: "center", color: colors.textMuted },

  // Detail modal
  spinnerOverlay: { position: "absolute", inset: 0 as any, top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.2)", alignItems: "center", justifyContent: "center" },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 22, paddingBottom: 36, maxHeight: "92%" },
  sheetHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  detailType: { fontSize: 11, fontWeight: "800", color: colors.textMuted, textAlign: "center", letterSpacing: 1.5 },
  detailAmount: { fontSize: 32, fontWeight: "800", textAlign: "center", marginTop: 4 },
  detailDate: { fontSize: 12, color: colors.textMuted, textAlign: "center", marginTop: 4, marginBottom: 12 },
  statusRow: { flexDirection: "row", justifyContent: "center", marginBottom: 14 },
  pill: { paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999 },
  pillText: { fontSize: 11, fontWeight: "800", letterSpacing: 0.8 },
  remarkBox: { flexDirection: "row", alignItems: "flex-start", gap: 10, backgroundColor: colors.brand100, borderRadius: 12, padding: 12, marginBottom: 4 },
  remarkText: { flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 17 },
  section: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1.5, marginTop: 18, marginBottom: 4 },
  dRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 12 },
  dKey: { fontSize: 11, color: colors.textMuted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5, flexShrink: 0, width: 110 },
  dVal: { fontSize: 13, color: colors.textMain, fontWeight: "600", textAlign: "right", flex: 1 },
  closeBtn: { paddingVertical: 14, borderRadius: radii.button, alignItems: "center", backgroundColor: colors.primary },

  // Invoice
  invoiceBox: { marginTop: 18, padding: 14, backgroundColor: colors.surfaceMuted, borderRadius: 14, borderWidth: 1, borderColor: colors.border },
  invoiceTitle: { fontSize: 11, fontWeight: "800", color: colors.textMain, letterSpacing: 1, textTransform: "uppercase" },
  invoiceNo: { fontSize: 14, fontWeight: "700", color: colors.primary, marginTop: 4 },
  invoiceSub: { fontSize: 11, color: colors.textMuted, marginTop: 4, lineHeight: 15 },
  invoiceBtnPrimary: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 12, borderRadius: radii.button, minHeight: 44 },
  invoiceBtnPrimaryText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },
  invoiceBtnSecondary: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "transparent", borderWidth: 1.5, borderColor: colors.primary, paddingVertical: 12, borderRadius: radii.button, minHeight: 44 },
  invoiceBtnSecondaryText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  invoiceHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  invoiceCloseBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  invoiceHeaderTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
});
