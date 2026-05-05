import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  TextInput,
  Modal,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { WebView } from "react-native-webview";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { downloadInvoicePdf, fetchInvoiceHtml } from "../../src/invoices";

type Withdrawal = {
  id: string;
  amount: number;
  status: "pending" | "approved" | "processing" | "success" | "rejected";
  created_at: string;
  processed_at?: string | null;
  estimated_completion_at?: string | null;
  completed_at?: string | null;
};

type Txn = {
  id: string;
  type: string;
  amount: number;
  status: string;
  description?: string;
  created_at: string;
};

export default function WalletScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // Wallet-to-wallet transfer state
  const [showTransfer, setShowTransfer] = useState(false);
  const [txFilter, setTxFilter] = useState<"all" | "credits" | "debits">("all");
  // Transaction detail modal
  const [txDetail, setTxDetail] = useState<any | null>(null);
  const [txDetailLoading, setTxDetailLoading] = useState(false);
  // Invoice preview state
  const [invoiceHtml, setInvoiceHtml] = useState<string | null>(null);
  const [invoiceBusy, setInvoiceBusy] = useState(false);
  const onPreviewInvoice = async () => {
    if (!txDetail?.transaction?.id) return;
    setInvoiceBusy(true);
    try {
      const html = await fetchInvoiceHtml(txDetail.transaction.id);
      setInvoiceHtml(html);
    } catch (e: any) {
      Alert.alert("Could not load invoice", e?.message || "Try again");
    } finally {
      setInvoiceBusy(false);
    }
  };
  const onDownloadInvoice = async () => {
    if (!txDetail?.transaction?.id) return;
    setInvoiceBusy(true);
    try {
      await downloadInvoicePdf(txDetail.transaction.id, txDetail.invoice_number);
    } finally {
      setInvoiceBusy(false);
    }
  };
  const openTxDetail = async (txnId: string) => {
    setTxDetailLoading(true);
    setTxDetail({ loading: true });
    try {
      const { data } = await api.get(`/transactions/${txnId}`);
      setTxDetail(data);
    } catch (e) {
      setTxDetail(null);
    } finally {
      setTxDetailLoading(false);
    }
  };
  // Type-aware classification (some legacy txns store positive amount for debits like registration_fee/order).
  const isDebit = (t: Txn) => {
    if ((t.amount || 0) < 0) return true;
    return ["withdrawal", "transfer_out", "order", "registration_fee"].includes(t.type);
  };
  const filteredTxns = txns.filter((t) => {
    if (txFilter === "all") return true;
    if (txFilter === "credits") return !isDebit(t);
    return isDebit(t);
  });
  const [recipient, setRecipient] = useState("");
  const [transferAmt, setTransferAmt] = useState("");
  const [transferNote, setTransferNote] = useState("");
  const [transferring, setTransferring] = useState(false);
  const [transferError, setTransferError] = useState("");

  const load = useCallback(async () => {
    try {
      const [w, t] = await Promise.all([
        api.get<Withdrawal[]>("/withdrawals/me"),
        api.get<Txn[]>("/transactions/me"),
      ]);
      setWithdrawals(w.data);
      setTxns(t.data);
      await refresh();
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [refresh]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onSubmit = async () => {
    setError("");
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) { setError("Enter valid amount"); return; }
    if (amt > (user?.wallet_balance || 0)) { setError("Insufficient balance"); return; }
    setSubmitting(true);
    try {
      await api.post("/withdrawals", { amount: amt });
      setShowModal(false);
      setAmount("");
      await load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  const onTransfer = async () => {
    setTransferError("");
    const amt = parseFloat(transferAmt);
    if (!recipient.trim()) { setTransferError("Enter recipient email or referral code"); return; }
    if (!amt || amt <= 0) { setTransferError("Enter valid amount"); return; }
    if (amt > (user?.wallet_balance || 0)) { setTransferError("Insufficient balance"); return; }
    setTransferring(true);
    try {
      await api.post("/wallet/transfer", {
        recipient: recipient.trim(),
        amount: amt,
        note: transferNote.trim() || undefined,
      });
      setShowTransfer(false);
      setRecipient("");
      setTransferAmt("");
      setTransferNote("");
      await load();
      Alert.alert("Sent", `₹${amt} transferred successfully.`);
    } catch (e) {
      setTransferError(formatApiError(e));
    } finally {
      setTransferring(false);
    }
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  const hasPayoutMethod = !!(user?.upi_id || user?.bank_account);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <Text style={styles.overline}>WALLET</Text>
        <Text style={styles.h1}>Your earnings</Text>

        <GradientCard variant="emerald" style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>AVAILABLE BALANCE</Text>
          <Text style={styles.balanceAmount} testID="wallet-balance">{formatINR(user?.wallet_balance || 0)}</Text>
          <View style={styles.statsRow}>
            <View>
              <Text style={styles.statRowLabel}>Total earned</Text>
              <Text style={styles.statRowValue}>{formatINR(user?.total_earned || 0)}</Text>
            </View>
            <View>
              <Text style={styles.statRowLabel}>Payouts</Text>
              <Text style={styles.statRowValue}>{user?.payouts_received || 0}</Text>
            </View>
          </View>
          <View style={styles.actionsRow}>
            <TouchableOpacity
              style={[styles.withdrawBtn, { flex: 1 }]}
              onPress={() => {
                if (!hasPayoutMethod) {
                  Alert.alert(
                    "Add UPI / Bank details",
                    "To withdraw, please add a UPI ID or bank account first.",
                    [
                      { text: "Cancel", style: "cancel" },
                      { text: "Add now", onPress: () => router.push("/payout-details" as any) },
                    ],
                  );
                  return;
                }
                setShowModal(true);
              }}
              testID="wallet-request-withdraw"
            >
              <Feather name="arrow-up-right" size={18} color={colors.accentFg} />
              <Text style={styles.withdrawBtnText}>{hasPayoutMethod ? "Schedule withdrawal" : "Add details to withdraw"}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.transferBtn, { flex: 1 }]}
              onPress={() => setShowTransfer(true)}
              testID="wallet-transfer"
            >
              <Feather name="send" size={18} color={colors.primary} />
              <Text style={styles.transferBtnText}>Send to user</Text>
            </TouchableOpacity>
          </View>
        </GradientCard>

        <Text style={styles.sectionLabel}>WITHDRAWAL HISTORY</Text>
        {withdrawals.length === 0 ? (
          <Text style={styles.empty}>No withdrawals yet.</Text>
        ) : (
          withdrawals.map((w) => {
            const color = w.status === "success" || w.status === "approved" ? colors.success
              : w.status === "rejected" ? "#B3261E"
              : w.status === "processing" ? colors.brand500
              : colors.warning;
            return (
              <View key={w.id} style={styles.row} testID={`withdrawal-${w.id}`}>
                <View style={styles.rowLeft}>
                  <View style={[styles.rowDot, { backgroundColor: color }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle}>{formatINR(w.amount)}</Text>
                    <Text style={styles.rowSub}>
                      {new Date(w.created_at).toLocaleDateString()}
                      {w.status === "processing" && w.estimated_completion_at
                        ? ` · ETA ${new Date(w.estimated_completion_at).toLocaleDateString()}`
                        : ""}
                      {w.status === "success" && w.completed_at
                        ? ` · paid ${new Date(w.completed_at).toLocaleDateString()}`
                        : ""}
                    </Text>
                  </View>
                </View>
                <Text style={[styles.statusPill, { color }]}>{w.status.toUpperCase()}</Text>
              </View>
            );
          })
        )}

        <View style={styles.txHeader}>
          <Text style={styles.sectionLabel}>TRANSACTIONS</Text>
          <View style={styles.txFilters}>
            {(["all", "credits", "debits"] as const).map((f) => (
              <TouchableOpacity
                key={f}
                onPress={() => setTxFilter(f)}
                style={[styles.txFilterChip, txFilter === f && styles.txFilterChipActive]}
                testID={`wallet-filter-${f}`}
              >
                <Text style={[styles.txFilterText, txFilter === f && { color: colors.primaryFg }]}>{f === "all" ? "All" : f === "credits" ? "Credits" : "Debits"}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
        {filteredTxns.length === 0 ? (
          <Text style={styles.empty}>{txFilter === "all" ? "No transactions yet." : `No ${txFilter} yet.`}</Text>
        ) : (
          filteredTxns.map((t) => {
            const icon = t.type === "referral_payout" || t.type === "level_payout" ? "trending-up"
              : t.type === "withdrawal" ? "arrow-up-right"
              : t.type === "transfer_out" ? "send"
              : t.type === "transfer_in" ? "download"
              : t.type === "admin_adjust" && t.amount > 0 ? "gift"
              : t.type === "admin_adjust" ? "edit-3"
              : t.type === "vendor_sale" ? "shopping-bag"
              : t.type === "registration_fee" ? "user-plus"
              : t.type === "order" ? "shopping-cart"
              : "credit-card";
            const statusColor = t.status === "processing" ? colors.brand500
              : t.status === "success" ? colors.success
              : t.status === "rejected" ? "#B3261E"
              : null;
            return (
              <TouchableOpacity key={t.id} style={styles.row} onPress={() => openTxDetail(t.id)} testID={`tx-row-${t.id}`}>
                <View style={styles.rowLeft}>
                  <Feather name={icon as any} size={18} color={t.amount > 0 ? colors.success : colors.textMain} style={{ marginRight: 12 }} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle} numberOfLines={2}>{t.description || t.type}</Text>
                    <Text style={styles.rowSub}>
                      {new Date(t.created_at).toLocaleDateString()}
                      {statusColor ? ` · ${t.status}` : ""}
                    </Text>
                  </View>
                </View>
                <Text style={[styles.amountText, { color: t.amount >= 0 ? colors.success : statusColor || "#B3261E" }]}>
                  {t.amount >= 0 ? "+" : ""}{formatINR(t.amount)}
                </Text>
              </TouchableOpacity>
            );
          })
        )}
      </ScrollView>

      <Modal visible={showModal} transparent animationType="slide" onRequestClose={() => setShowModal(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Schedule withdrawal</Text>
            <Text style={styles.modalSub}>Available: {formatINR(user?.wallet_balance || 0)}{"\n"}Funds reach your bank within 48 hours after admin approval.</Text>
            <TextInput
              testID="withdraw-amount-input"
              value={amount}
              onChangeText={setAmount}
              placeholder="Enter amount in ₹"
              placeholderTextColor={colors.textMuted}
              keyboardType="numeric"
              style={styles.modalInput}
            />
            {error ? <Text style={styles.errorText}>{error}</Text> : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => setShowModal(false)} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onSubmit} disabled={submitting} style={[styles.modalBtn, { backgroundColor: colors.primary }]} testID="withdraw-submit">
                {submitting ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Submit</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      <Modal visible={showTransfer} transparent animationType="slide" onRequestClose={() => setShowTransfer(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Send to another user</Text>
            <Text style={styles.modalSub}>Wallet-to-wallet transfer · Available: {formatINR(user?.wallet_balance || 0)}</Text>
            <TextInput
              testID="transfer-recipient"
              value={recipient}
              onChangeText={setRecipient}
              autoCapitalize="none"
              placeholder="Recipient email or referral code"
              placeholderTextColor={colors.textMuted}
              style={styles.modalInput}
            />
            <TextInput
              testID="transfer-amount"
              value={transferAmt}
              onChangeText={setTransferAmt}
              placeholder="Amount in ₹"
              placeholderTextColor={colors.textMuted}
              keyboardType="numeric"
              style={[styles.modalInput, { marginTop: 10 }]}
            />
            <TextInput
              testID="transfer-note"
              value={transferNote}
              onChangeText={setTransferNote}
              placeholder="Note (optional)"
              placeholderTextColor={colors.textMuted}
              style={[styles.modalInput, { marginTop: 10 }]}
            />
            {transferError ? <Text style={styles.errorText}>{transferError}</Text> : null}
            <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
              <TouchableOpacity onPress={() => { setShowTransfer(false); setTransferError(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onTransfer} disabled={transferring} style={[styles.modalBtn, { backgroundColor: colors.primary }]} testID="transfer-submit">
                {transferring ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "700" }}>Send</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Transaction detail modal */}
      <Modal visible={!!txDetail} transparent animationType="slide" onRequestClose={() => setTxDetail(null)}>
        <TouchableOpacity activeOpacity={1} style={styles.modalOverlay} onPress={() => setTxDetail(null)}>
          <TouchableOpacity activeOpacity={1} style={styles.modalSheet} onPress={() => {}}>
            <View style={styles.modalHandle} />
            {txDetailLoading || txDetail?.loading ? (
              <View style={{ paddingVertical: 30, alignItems: "center" }}><ActivityIndicator color={colors.primary} /></View>
            ) : txDetail?.transaction ? (
              <>
                <Text style={styles.modalTitle}>Transaction details</Text>
                <Text style={[styles.modalSub, { marginBottom: 14 }]}>{txDetail.auto_remarks}</Text>

                <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 14 }}>
                  <Text style={{ fontSize: 28, fontWeight: "800", color: txDetail.transaction.amount >= 0 ? colors.success : "#B3261E" }}>
                    {txDetail.transaction.amount >= 0 ? "+" : ""}{formatINR(txDetail.transaction.amount)}
                  </Text>
                  <Text style={{ fontSize: 12, color: colors.textMuted, textTransform: "uppercase", letterSpacing: 1 }}>{txDetail.transaction.status}</Text>
                </View>

                {[
                  ["Type", (txDetail.transaction.type || "").replace(/_/g, " ")],
                  ["Date", new Date(txDetail.transaction.created_at).toLocaleString()],
                  ["Reference / UTR", txDetail.utr || "—"],
                  ["Transaction ID", (txDetail.transaction.id || "").slice(0, 16) + "…"],
                  ["Description", txDetail.transaction.description || "—"],
                  ["Remarks", txDetail.transaction.remarks || "—"],
                ].map(([k, v], i) => (
                  <View key={i} style={styles.detailRow}>
                    <Text style={styles.detailKey}>{k}</Text>
                    <Text style={styles.detailVal}>{String(v)}</Text>
                  </View>
                ))}

                {txDetail.counter_party && (
                  <>
                    <Text style={[styles.modalSub, { marginTop: 14, marginBottom: 6, fontWeight: "800", color: colors.textMain, fontSize: 13, letterSpacing: 0.5 }]}>
                      {txDetail.counter_role === "admin" ? "FROM ADMIN" : `${txDetail.counter_role.toUpperCase()} INFO`}
                    </Text>
                    <View style={styles.detailRow}><Text style={styles.detailKey}>Name</Text><Text style={styles.detailVal}>{txDetail.counter_party.name || "—"}</Text></View>
                    <View style={styles.detailRow}><Text style={styles.detailKey}>Email</Text><Text style={styles.detailVal}>{txDetail.counter_party.email || "—"}</Text></View>
                    {txDetail.counter_party.phone ? <View style={styles.detailRow}><Text style={styles.detailKey}>Phone</Text><Text style={styles.detailVal}>{txDetail.counter_party.phone}</Text></View> : null}
                    {txDetail.counter_party.referral_code ? <View style={styles.detailRow}><Text style={styles.detailKey}>Referral</Text><Text style={styles.detailVal}>{txDetail.counter_party.referral_code}</Text></View> : null}
                  </>
                )}

                {txDetail.invoiceable && txDetail.invoice_number ? (
                  <View style={styles.invoiceBox}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Feather name="file-text" size={16} color={colors.primary} />
                      <Text style={styles.invoiceTitle}>GST Invoice</Text>
                    </View>
                    <Text style={styles.invoiceNo}>{txDetail.invoice_number}</Text>
                    <Text style={styles.invoiceSub}>18% GST applied as per Indian GST law (CGST 9% + SGST 9%).</Text>
                    <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                      <TouchableOpacity onPress={onPreviewInvoice} disabled={invoiceBusy} style={[styles.invoiceBtnSecondary, { flex: 1 }]} testID="invoice-preview">
                        {invoiceBusy ? <ActivityIndicator color={colors.primary} /> : (
                          <>
                            <Feather name="eye" size={16} color={colors.primary} />
                            <Text style={styles.invoiceBtnSecondaryText}>Preview</Text>
                          </>
                        )}
                      </TouchableOpacity>
                      <TouchableOpacity onPress={onDownloadInvoice} disabled={invoiceBusy} style={[styles.invoiceBtnPrimary, { flex: 1 }]} testID="invoice-download">
                        {invoiceBusy ? <ActivityIndicator color={colors.primaryFg} /> : (
                          <>
                            <Feather name="download" size={16} color={colors.primaryFg} />
                            <Text style={styles.invoiceBtnPrimaryText}>Download PDF</Text>
                          </>
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                ) : null}

                <TouchableOpacity onPress={() => setTxDetail(null)} style={[styles.modalBtn, { backgroundColor: colors.primary, marginTop: 18 }]}>
                  <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Close</Text>
                </TouchableOpacity>
              </>
            ) : (
              <View style={{ paddingVertical: 30, alignItems: "center" }}>
                <Feather name="alert-circle" size={28} color={colors.textMuted} />
                <Text style={{ color: colors.textMuted, marginTop: 8 }}>Could not load transaction</Text>
              </View>
            )}
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
      {/* Invoice HTML Preview modal */}
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
              <View style={{ flex: 1, backgroundColor: "#fff" }}>
                {/* Inline HTML on web via iframe */}
                {/* @ts-ignore react-native-web allows raw DOM elements via createElement */}
                <iframe
                  srcDoc={invoiceHtml}
                  style={{ flex: 1, border: 0, width: "100%", height: "100%" } as any}
                  title="invoice-preview"
                />
              </View>
            ) : (
              <WebView
                originWhitelist={["*"]}
                source={{ html: invoiceHtml }}
                style={{ flex: 1, backgroundColor: "#fff" }}
              />
            )
          ) : null}
        </SafeAreaView>
      </Modal>

    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 20 },
  balanceCard: { padding: 24, marginBottom: 24 },
  balanceLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  balanceAmount: { color: colors.primaryFg, fontSize: 44, fontWeight: "800", marginTop: 6, letterSpacing: -1.5 },
  statsRow: { flexDirection: "row", gap: 32, marginTop: 16 },
  statRowLabel: { color: "rgba(255,255,255,0.6)", fontSize: 12 },
  statRowValue: { color: colors.primaryFg, fontSize: 16, fontWeight: "700", marginTop: 2 },
  withdrawBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.accent, paddingVertical: 14, borderRadius: radii.button, gap: 8 },
  withdrawBtnText: { color: colors.accentFg, fontWeight: "700", fontSize: 14 },
  actionsRow: { flexDirection: "row", gap: 10, marginTop: 18 },
  transferBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: "#fff", paddingVertical: 14, borderRadius: radii.button, gap: 8 },
  transferBtnText: { color: colors.primary, fontWeight: "700", fontSize: 14 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12, marginTop: 8 },
  txHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 8, marginBottom: 12 },
  txFilters: { flexDirection: "row", gap: 6 },
  txFilterChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  txFilterChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  txFilterText: { fontSize: 11, fontWeight: "700", color: colors.textMain },
  empty: { color: colors.textMuted, fontSize: 13, padding: 16, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 16 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 8 },
  rowLeft: { flexDirection: "row", alignItems: "center", flex: 1 },
  rowDot: { width: 10, height: 10, borderRadius: 5, marginRight: 12 },
  rowTitle: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rowSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  statusPill: { fontSize: 11, fontWeight: "800", letterSpacing: 1 },
  amountText: { fontSize: 14, fontWeight: "800" },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 16 },
  modalTitle: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  modalSub: { fontSize: 13, color: colors.textMuted, marginTop: 4, marginBottom: 16 },
  modalInput: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 16, fontSize: 18, color: colors.textMain, fontWeight: "700" },
  errorText: { color: "#B3261E", fontSize: 13, marginTop: 8 },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
  detailRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 12 },
  detailKey: { fontSize: 12, color: colors.textMuted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5, flexShrink: 0, width: 120 },
  detailVal: { fontSize: 13, color: colors.textMain, fontWeight: "600", textAlign: "right", flex: 1 },
  invoiceBox: { marginTop: 18, padding: 14, backgroundColor: colors.surfaceMuted, borderRadius: 14, borderWidth: 1, borderColor: colors.border },
  invoiceTitle: { fontSize: 12, fontWeight: "800", color: colors.textMain, letterSpacing: 1, textTransform: "uppercase" },
  invoiceNo: { fontSize: 14, fontWeight: "700", color: colors.primary, marginTop: 4 },
  invoiceSub: { fontSize: 11, color: colors.textMuted, marginTop: 4, lineHeight: 15 },
  invoiceBtnPrimary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 12, borderRadius: radii.button, minHeight: 44 },
  invoiceBtnPrimaryText: { color: colors.primaryFg, fontWeight: "800", fontSize: 13 },
  invoiceBtnSecondary: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "transparent", borderWidth: 1.5, borderColor: colors.primary, paddingVertical: 12, borderRadius: radii.button, minHeight: 44 },
  invoiceBtnSecondaryText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  invoiceHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  invoiceCloseBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  invoiceHeaderTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
});
