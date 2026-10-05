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
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { WebView } from "react-native-webview";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { downloadInvoicePdf, fetchInvoiceHtml } from "../../src/invoices";
import { useBackToInitialTab } from "../../src/use-double-tap-exit";

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
  useBackToInitialTab();
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
  // Oct-2026 — "cashback" is a first-class filter so the Dashboard's
  // "Cashback earned" tile can deep-link straight to a list that contains
  // ONLY cashback actually received (no orders, no refunds, no withdrawals).
  const txParams = useLocalSearchParams<{ filter?: string }>();
  const [txFilter, setTxFilter] = useState<"all" | "credits" | "debits" | "cashback">(
    txParams?.filter === "cashback" ? "cashback" : "all",
  );
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
  // Same rule as the row renderer: the ledger's credit/debit fields decide
  // direction, with the type list only as a legacy fallback.
  const isDebit = (t: Txn) => {
    const a = t as any;
    if (Number(a.debit) > 0) return true;
    if (Number(a.credit) > 0) return false;
    if ((t.amount || 0) < 0) return true;
    return [
      "withdrawal", "transfer_out", "order", "registration_fee", "admin_debit",
      "withdrawal_hold", "delivery_charge_paid", "return_refund_debit",
      "cashback_funding", "cashback_reversal", "vendor_sale_reversal",
      "phone_reveal_fee", "dp_cash_remitted",
    ].includes(t.type);
  };
  // Cashback RECEIVED only — the credit side of the cashback engine.
  // Pending, reversed and seller-funding rows are deliberately excluded.
  const isCashbackReceived = (t: Txn) =>
    ["cashback_credit", "cashback", "purchase_cashback"].includes(t.type) && !isDebit(t);
  const filteredTxns = txns.filter((t) => {
    if (txFilter === "all") return true;
    if (txFilter === "cashback") return isCashbackReceived(t);
    if (txFilter === "credits") return !isDebit(t);
    return isDebit(t);
  });
  const [summary, setSummary] = useState<{ cashback_earned: number; pending_cashback: number }>({
    cashback_earned: 0,
    pending_cashback: 0,
  });
  // Sep-2026 — a seller's SHOP wallet lives in `vendor_earnings` on the
  // server, not `wallet_balance`. This screen used to read the personal
  // wallet, so sales money looked like it had vanished and withdrawals
  // were refused as "insufficient balance". One endpoint now feeds the
  // hero, the withdraw gate and the dashboard tile alike.
  const [shopWallet, setShopWallet] = useState<{
    available: number; personal_wallet: number; pending_withdrawals: number;
    cod_to_collect: number; min_withdrawal: number; can_withdraw: boolean;
    withdraw_blocked_reason: string; payout_promise: string; in_sync: boolean;
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const isVendor = !!(user as any)?.is_vendor && !!(user as any)?.is_vendor_approved;
      const [w, t, d, sw] = await Promise.all([
        api.get<Withdrawal[]>("/withdrawals/me"),
        api.get<Txn[]>("/transactions/me"),
        api.get("/users/me/dashboard"),
        isVendor ? api.get("/vendor/me/wallet").catch(() => null) : Promise.resolve(null),
      ]);
      setWithdrawals(w.data);
      setTxns(t.data);
      setSummary({
        cashback_earned: Number(d.data?.cashback_earned || 0),
        pending_cashback: Number(d.data?.pending_cashback || 0),
      });
      setShopWallet(sw ? (sw as any).data : null);
      await refresh();
    } catch {}
    finally { setLoading(false); setRefreshing(false); }
  }, [refresh, user]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const isSeller = !!(user as any)?.is_vendor && !!(user as any)?.is_vendor_approved;

  const onSubmit = async () => {
    setError("");
    const amt = parseFloat(amount);
    const pot = isSeller ? (shopWallet?.available ?? 0) : (user?.wallet_balance || 0);
    const floor = isSeller ? (shopWallet?.min_withdrawal ?? 5000) : 100;
    if (!amt || amt <= 0) { setError("Enter valid amount"); return; }
    if (amt < floor) { setError(`Minimum withdrawal amount is ${formatINR(floor)}`); return; }
    if (amt > pot) { setError(`Insufficient balance — you have ${formatINR(pot)} available`); return; }
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


  // Bank withdrawals are a SELLER settlement feature. A shopper's Slangcart
  // wallet is spent inside the app on purchases (requirement: the wallet is
  // not a general-purpose money service).
  const isAdminUser = user?.role === "admin";
  // Jun 2026 — bank settlement is a SELLER feature only (owner's rule).
  // Customers, service providers and admins use the wallet inside the app;
  // company money is settled from Admin → System wallet.
  const canWithdraw = isSeller;

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
        <Text style={styles.h1Compact}>Your Slangcart wallet</Text>

        <GradientCard variant="emerald" style={styles.balanceCardCompact}>
          {/* Top row — balance + chips on right */}
          <View style={styles.balanceTopRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.balanceLabel}>
                {isSeller ? "SHOP EARNINGS · WITHDRAWABLE" : "AVAILABLE BALANCE"}
              </Text>
              <Text
                style={styles.balanceAmountCompact}
                testID="wallet-balance"
                numberOfLines={1}
                adjustsFontSizeToFit
              >
                {(() => {
                  // Admin sees only their own personal bucket here; the
                  // platform treasury lives in Admin → System Wallet.
                  // A SELLER sees their shop wallet — the pot that sales
                  // credit and that a settlement actually withdraws from.
                  const buckets = (user as any)?.wallet_buckets || {};
                  const value = isAdminUser
                    ? Number(buckets.referral_commission || 0)
                    : isSeller
                    ? Number(shopWallet?.available ?? 0)
                    : Number(user?.wallet_balance || 0);
                  return formatINR(value);
                })()}
              </Text>
              {isAdminUser ? (
                <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "700", marginTop: 2, letterSpacing: 0.3 }}>
                  Personal bucket only · See System Wallet for treasury
                </Text>
              ) : isSeller ? (
                <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "700", marginTop: 2, letterSpacing: 0.3 }}>
                  {`Shopping wallet ${formatINR(shopWallet?.personal_wallet ?? user?.wallet_balance ?? 0)}`}
                  {(shopWallet?.cod_to_collect ?? 0) > 0
                    ? ` · ${formatINR(shopWallet?.cod_to_collect ?? 0)} cash to collect`
                    : ""}
                </Text>
              ) : (
                <Text style={{ fontSize: 10, color: "rgba(255,255,255,0.85)", fontWeight: "700", marginTop: 2, letterSpacing: 0.3 }}>
                  Spend on Slangcart orders · cashback · refunds
                </Text>
              )}
            </View>
            <View style={styles.miniStatsCol}>
              <View style={styles.miniStat}>
                <Text style={styles.miniStatLabel}>CASHBACK</Text>
                <Text style={styles.miniStatValue} testID="wallet-cashback-earned">
                  {formatINR(summary.cashback_earned)}
                </Text>
              </View>
              <View style={styles.miniStatDivider} />
              <View style={styles.miniStat}>
                <Text style={styles.miniStatLabel}>PENDING</Text>
                <Text style={styles.miniStatValue} testID="wallet-cashback-pending">
                  {formatINR(summary.pending_cashback)}
                </Text>
              </View>
            </View>
          </View>

          {summary.pending_cashback > 0 ? (
            <View style={styles.pendingStrip}>
              <Feather name="clock" size={11} color="#fff" />
              <Text style={styles.pendingStripText} testID="wallet-pending-strip">
                {formatINR(summary.pending_cashback)} cashback arriving soon from your sellers
              </Text>
            </View>
          ) : null}

          {/* Bottom row — Add money (everyone) + Withdraw (sellers only) */}
          <View style={styles.actionsRowCompact}>
            <TouchableOpacity
              style={styles.withdrawBtnCompact}
              onPress={() => router.push("/wallet-topup" as any)}
              testID="wallet-add-money"
            >
              <Feather name="plus" size={14} color={colors.accentFg} />
              <Text style={styles.withdrawBtnTextCompact} numberOfLines={1}>Add money</Text>
            </TouchableOpacity>
            {canWithdraw ? (
              <TouchableOpacity
                style={styles.transferBtnCompact}
                onPress={() => {
                  if (!hasPayoutMethod) {
                    Alert.alert(
                      "Add UPI / Bank details",
                      "To settle your sales to a bank account, please add a UPI ID or bank account first.",
                      [
                        { text: "Cancel", style: "cancel" },
                        { text: "Add now", onPress: () => router.push("/payout-details" as any) },
                      ],
                    );
                    return;
                  }
                  if (shopWallet && !shopWallet.can_withdraw) {
                    Alert.alert("Settlement not available yet", shopWallet.withdraw_blocked_reason);
                    return;
                  }
                  setShowModal(true);
                }}
                testID="wallet-request-withdraw"
              >
                <Feather name="arrow-up-right" size={14} color={colors.primary} />
                <Text style={styles.transferBtnTextCompact} numberOfLines={1}>
                  {hasPayoutMethod ? "Withdraw" : "Add details"}
                </Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </GradientCard>

        {canWithdraw ? (
          <>
            <Text style={styles.sectionLabel}>SETTLEMENT HISTORY</Text>
            {withdrawals.length === 0 ? (
              <Text style={styles.empty}>No settlements yet.</Text>
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
          </>
        ) : null}

        <View style={styles.txHeader}>
          <Text style={styles.sectionLabel}>TRANSACTIONS</Text>
          <View style={styles.txFilters}>
            {(["all", "cashback", "credits", "debits"] as const).map((f) => (
              <TouchableOpacity
                key={f}
                onPress={() => setTxFilter(f)}
                style={[styles.txFilterChip, txFilter === f && styles.txFilterChipActive]}
                testID={`wallet-filter-${f}`}
              >
                <Text style={[styles.txFilterText, txFilter === f && { color: colors.primaryFg }]}>{f === "all" ? "All" : f === "cashback" ? "Cashback" : f === "credits" ? "Credits" : "Debits"}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
        {filteredTxns.length === 0 ? (
          <Text style={styles.empty}>{txFilter === "all" ? "No transactions yet." : txFilter === "cashback" ? "No cashback received yet." : `No ${txFilter} yet.`}</Text>
        ) : (
          filteredTxns.map((t) => {
            // Decide if this row is a DEBIT (money leaving the wallet) or a
            // CREDIT. Most txns have a signed `amount` but some legacy rows
            // store positive amounts on debit-typed records — so we treat
            // a row as debit if EITHER the amount is < 0 OR the type is
            // one of the known outgoing types. Per user request: debits
            // must always render in red, credits in green.
            // Sep-2026 — the ledger already records direction in `credit` /
            // `debit`, so trust that first. The type list is only a fallback
            // for legacy rows written before those fields existed (which is
            // why "Delivery charge paid" used to render as a green credit).
            const DEBIT_TYPES = new Set([
              "withdrawal", "transfer_out", "admin_debit", "order",
              "vendor_payout_debit", "purchase", "withdrawal_hold",
              "delivery_charge_paid", "return_refund_debit", "cashback_funding",
              "cashback_reversal", "vendor_sale_reversal", "registration_fee",
              "phone_reveal_fee", "dp_cash_remitted",
            ]);
            const anyT = t as any;
            const isDebit = (Number(anyT.debit) > 0)
              ? true
              : (Number(anyT.credit) > 0)
                ? false
                : (Number(t.amount) < 0) || DEBIT_TYPES.has(t.type);
            const icon = t.type === "cashback_credit" ? "gift"
              : t.type === "cashback_pending" ? "clock"
              : t.type === "cashback_reversal" ? "rotate-ccw"
              : t.type === "withdrawal" ? "arrow-up-right"
              : t.type === "transfer_out" ? "send"
              : t.type === "transfer_in" ? "download"
              : t.type === "admin_adjust" && t.amount > 0 ? "gift"
              : t.type === "admin_adjust" ? "edit-3"
              : t.type === "admin_debit" ? "minus-circle"
              : t.type === "admin_credit" ? "plus-circle"
              : t.type === "vendor_sale" ? "shopping-bag"
              : t.type === "registration_fee" ? "user-plus"
              : t.type === "order" ? "shopping-cart"
              : "credit-card";
            const statusColor = t.status === "processing" ? colors.brand500
              : t.status === "success" ? colors.success
              : t.status === "rejected" ? "#B3261E"
              : null;
            // Color rule: debits ALWAYS red, credits ALWAYS green (success).
            // Failure/rejected statuses fall back to red regardless of sign.
            const amountColor = isDebit ? "#B3261E"
              : t.status === "rejected" || t.status === "failed" ? "#B3261E"
              : colors.success;
            const displaySign = isDebit ? "−" : "+";
            const displayAmt = Math.abs(Number(t.amount) || 0);
            return (
              <TouchableOpacity key={t.id} style={styles.row} onPress={() => openTxDetail(t.id)} testID={`tx-row-${t.id}`}>
                <View style={styles.rowLeft}>
                  <Feather name={icon as any} size={18} color={isDebit ? "#B3261E" : colors.success} style={{ marginRight: 12 }} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle} numberOfLines={2}>{t.description || t.type}</Text>
                    <Text style={styles.rowSub}>
                      {new Date(t.created_at).toLocaleDateString()}
                      {statusColor ? ` · ${t.status}` : ""}
                    </Text>
                  </View>
                </View>
                <Text style={[styles.amountText, { color: amountColor }]}>
                  {displaySign}{formatINR(displayAmt)}
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
            <Text style={styles.modalSub}>
              {`Available: ${formatINR(isSeller ? (shopWallet?.available ?? 0) : (user?.wallet_balance || 0))}`}
              {"\n"}
              {isSeller
                ? `Minimum ${formatINR(shopWallet?.min_withdrawal ?? 5000)}. ${shopWallet?.payout_promise || "Approved settlements reach your bank within 24 hours on banking days."}`
                : "Minimum ₹100. Funds reach your bank within 48 hours after admin approval."}
            </Text>
            <TextInput
              testID="withdraw-amount-input"
              value={amount}
              onChangeText={setAmount}
              placeholder={`Enter amount in ₹ (min ${formatINR(isSeller ? (shopWallet?.min_withdrawal ?? 5000) : 100)})`}
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
                  ...(txDetail.transaction.gross_amount != null && txDetail.transaction.gst_amount != null ? [
                    ["Gross Payout", formatINR(txDetail.transaction.gross_amount)],
                    [`GST Withheld (${txDetail.transaction.gst_pct ?? 18}%)`, `− ${formatINR(txDetail.transaction.gst_amount)}`],
                    ["Net Credited", formatINR(txDetail.transaction.amount)],
                  ] : []),
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
  h1Compact: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.6, marginBottom: 14 },
  balanceCard: { padding: 22, marginBottom: 24 },
  balanceCardCompact: { padding: 16, marginBottom: 20, borderRadius: 18 },
  balanceTopRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  balanceLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 1.6, fontWeight: "800" },
  balanceAmount: { color: colors.primaryFg, fontSize: 44, fontWeight: "800", marginTop: 6, letterSpacing: -1.5 },
  balanceAmountCompact: { color: colors.primaryFg, fontSize: 26, fontWeight: "900", marginTop: 2, letterSpacing: -0.8 },
  miniStatsCol: { backgroundColor: "rgba(255,255,255,0.24)", borderRadius: 12, paddingVertical: 8, paddingHorizontal: 12, alignItems: "center", minWidth: 110 },
  miniStat: { alignItems: "center" },
  // Contrast fix (Jun-2026): 0.75 white on the dark hero read as washed-out.
  // Sep-2026: solid white labels + stronger chip fill for AA contrast on the emerald gradient.
  miniStatLabel: { color: "#fff", fontSize: 10, fontWeight: "900", letterSpacing: 1.2 },
  miniStatValue: { color: "#fff", fontSize: 13, fontWeight: "800", marginTop: 1, letterSpacing: -0.2 },
  miniStatDivider: { width: 28, height: 1, backgroundColor: "rgba(255,255,255,0.5)", marginVertical: 5 },
  statsRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginTop: 18, paddingTop: 16, borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.18)" },
  statCol: { flex: 1, alignItems: "flex-start" },
  statColRight: { flex: 1, alignItems: "flex-end" },
  statRowLabel: { color: "rgba(255,255,255,0.65)", fontSize: 11, letterSpacing: 0.5, fontWeight: "600", textTransform: "uppercase" },
  statRowValue: { color: colors.primaryFg, fontSize: 18, fontWeight: "800", marginTop: 4, letterSpacing: -0.3 },
  withdrawBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.accent, paddingVertical: 12, paddingHorizontal: 10, borderRadius: radii.button, gap: 6, minHeight: 44 },
  withdrawBtnText: { color: colors.accentFg, fontWeight: "700", fontSize: 14 },
  actionsRow: { flexDirection: "row", gap: 10, marginTop: 18 },
  // Compact action row: smaller padding, compact buttons
  actionsRowCompact: { flexDirection: "row", gap: 8, marginTop: 14 },
  withdrawBtnCompact: {
    flex: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: colors.accent,
    paddingVertical: 9, paddingHorizontal: 10,
    borderRadius: 999,
    gap: 5,
    minHeight: 36,
  },
  withdrawBtnTextCompact: { color: colors.accentFg, fontWeight: "800", fontSize: 12, letterSpacing: 0.2 },
  pendingStrip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 10, paddingTop: 9,
    borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.18)",
  },
  pendingStripText: { color: "#fff", fontSize: 11, fontWeight: "700", flex: 1 },
  transferBtnCompact: {    flex: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.95)",
    paddingVertical: 9, paddingHorizontal: 10,
    borderRadius: 999,
    gap: 5,
    minHeight: 36,
  },
  transferBtnTextCompact: { color: colors.primary, fontWeight: "800", fontSize: 12, letterSpacing: 0.2 },
  transferBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: "#fff", paddingVertical: 12, paddingHorizontal: 10, borderRadius: radii.button, gap: 6, minHeight: 44 },
  transferBtnText: { color: colors.primary, fontWeight: "700", fontSize: 14 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12, marginTop: spacing.sectionGap },
  txHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.sectionGap, marginBottom: 12 },
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
