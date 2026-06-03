import { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, Alert, Modal, TextInput, KeyboardAvoidingView, Platform, Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { downloadInvoicePdf, fetchInvoiceHtml } from "../../src/invoices";
import { WebView } from "react-native-webview";

/** Buckets shown in the UI — keep order aligned with business priority. */
type BucketKey =
  | "direct_signup"
  | "fee_residual"
  | "referral_commission"
  | "gst_collected"
  | "direct_added"
  | "service_margin"
  | "shopping_margin"
  | "user_payouts"
  | "admin_wallet";

/** Top-level treasury rows shown on the System Wallet home — clean tally:
 *  Admin Wallet (held) + User Wallets (held) + Withdrawn (left platform) = Inflow.
 *  All other rows (GST/Service/Shop/UTR/Referral) are INFORMATIONAL sub-buckets
 *  of Admin Wallet and are NOT added to the tally. */
type TreasuryRowKey = "admin_wallet" | "user_wallets" | "withdrawn";
type TreasuryInfoKey = "gst_info" | "service_margin" | "shopping_margin" | "direct_added" | "referral_admin";

const BUCKETS: { key: BucketKey; label: string; icon: any; color: string; desc: string; cta?: string }[] = [
  { key: "direct_signup",       label: "Direct Joins & Realignments", icon: "user-plus",         color: "#2E7D52", desc: "No-referral + EARN signups (₹100 each)", cta: "View transactions" },
  { key: "fee_residual",        label: "Fee Residual",                 icon: "shuffle",          color: "#0EA5A4", desc: "Leftover when with-ref cascade < fee",     cta: "View transactions" },
  { key: "referral_commission", label: "Admin Wallet (cascade + GST)", icon: "credit-card",      color: "#7C3AED", desc: "Direct joins + Residual + Referral + GST",  cta: "View ledger" },
  { key: "gst_collected",       label: "GST Collected (info)",         icon: "percent",          color: "#B3261E", desc: "Already part of Admin Wallet (compliance)", cta: "View GST txns" },
  { key: "direct_added",        label: "Direct-Added (UTR)",           icon: "arrow-down-circle", color: "#0B66C2", desc: "Manual UTR-verified bank deposits",         cta: "View UTR deposits" },
  { key: "service_margin",      label: "Service Margin",               icon: "briefcase",        color: "#E57A44", desc: "Platform fee from service bookings",        cta: "View service txns" },
  { key: "shopping_margin",     label: "Sales Margin (Shop)",          icon: "shopping-bag",     color: "#1E40AF", desc: "Commission from shop orders",               cta: "View shop txns" },
  { key: "user_payouts",        label: "Total Paid to Users",          icon: "users",            color: "#2E7D52", desc: "Referral payouts + settled withdrawals (with UTR)", cta: "View payouts & withdrawals" },
  { key: "admin_wallet",        label: "Admin Wallet · full ledger",   icon: "credit-card",      color: "#7C3AED", desc: "Direct joins + Residual + Referral + GST + L1 fundings", cta: "View ledger" },
];

type Deposit = { id: string; amount: number; utr: string; bank_ref?: string; remarks?: string; deposited_by_email?: string; created_at: string };
type Txn = {
  id: string; type: string; level?: number; amount: number;
  gross_amount?: number; gst_amount?: number; gst_pct?: number;
  description?: string;
  source_user_name?: string; source_user_email?: string;
  placement_sponsor_name?: string; placement_sponsor_email?: string;
  reference_number?: string; created_at: string;
  // Server may include these flags from /transactions; on /system-wallet
  // they're absent — treat absence as "try and let backend reject 400".
  invoiceable?: boolean;
  invoice_number?: string;
};
type Breakdown = {
  inflow: {
    registration_fee_total: number;
    no_ref_signup_revenue: number;
    with_ref_signup_revenue: number;
    no_ref_count: number;
    with_ref_count: number;
    utr_deposits: number;
    service_margin: number;
    shop_margin: number;
    total: number;
  };
  outflow: {
    // Internal redistribution (cash still on platform)
    to_user_wallets_referral_net: number;        // paid to NON-admin users only
    to_admin_retained: number;                    // consolidated admin pool (incl. GST & L1 funding netted)
    to_admin_gst_collected: number;               // informational only — already inside admin_retained
    to_admin_direct_added: number;
    to_admin_shop_margin: number;
    to_admin_service_margin: number;
    to_admin_via_cascade: number;                 // already inside admin_retained
    // Left platform
    user_withdrawals_settled: number;
    // Legacy / backwards-compat
    to_user_wallets_referral: number;             // = referral_net + via_cascade (gross to all)
    _legacy_to_admin_direct_signup: number;
    _legacy_to_admin_fee_residual: number;
    _legacy_to_admin_cascade_overflow: number;
    _legacy_l1_funding_debit: number;
    redistributed_total: number;                  // cash still on platform = inflow − withdrawn
    total: number;                                // = redistributed + withdrawn = inflow
  };
  balance: { in_admin_wallet: number; in_user_wallets: number; held_total: number };
  settings: { registration_fee: number; directs_required: number; level_payouts: number[] };
};

/** 7-Group Net Worth (from /admin/finance/net-worth) — merged from the old
 *  standalone Finance Dashboard so the Wallet screen surfaces every rupee. */
type NetWorth = {
  group_1_revenue: {
    registration: number; service: number; platform_fee: number; shop: number; gross: number;
    by_source?: {
      razorpay:     { amount: number; count: number };
      upi_manual:   { amount: number; count: number };
      offline_cash: { amount: number; count: number };
    };
    reversed?: number;
  };
  group_2_liability: { total_reward_credits: number; total_withdrawals_settled: number; available_user_balance: number };
  group_3_gst: { collected: number; paid: number; payable: number };
  group_4_platform_fee: { collected: number };
  group_5_expenses: { total: number };
  group_6_pending_withdrawals: { pending_amount: number };
  group_7_bank: { credits: number; debits: number; balance: number };
  bank_tally?: {
    inflow: number; outflow: number; net: number;
    utr_deposits: number;
    reversals_count: number; reversals_amount: number;
    adjustments_count: number; adjustments_amount: number;
    formula: string;
  };
  master: {
    pending_collections: number; net_worth: number; formula: string;
    components?: {
      bank_tally_net: number;
      pending_collections: number;
      user_wallet_balance: number;
      pending_withdrawals: number;
      gst_payable: number;
    };
  };
};

export default function AdminSystemWallet() {
  const router = useRouter();
  const [data, setData] = useState<{ buckets: Record<string, number>; total: number; deposits: Deposit[] } | null>(null);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [showBreakdown, setShowBreakdown] = useState(false);
  // Phase: User-source unification (2026-05-27). 3-way accountability card
  // — Razorpay / UPI Manual / Offline Cash inflow + downstream payout fan-out.
  const [sourceBreakdown, setSourceBreakdown] = useState<{
    rows: { source: string; count: number; amount: number }[];
    totals: { count: number; amount: number };
    fan_out: Record<string, { payouts_count: number; payouts_amount: number }>;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // ─── 7-Group Net-Worth (merged from old Finance Dashboard) ───
  // Lives at the top of this screen so admins see "every rupee" in one place.
  const [netWorth, setNetWorth] = useState<NetWorth | null>(null);
  const [bankOpen, setBankOpen] = useState(false);  // Group 7 bank entry modal
  const [expOpen, setExpOpen] = useState(false);    // Group 5 expense modal
  const [adjOpen, setAdjOpen] = useState(false);    // Manual adjustment modal

  // Reset confirmation drawer — type-to-confirm gate for the destructive
  // Reset Bank Ledger / Reset Expenses Ledger actions.
  const [resetTarget, setResetTarget] = useState<"bank" | "expenses" | "payments" | null>(null);
  const [resetConfirmText, setResetConfirmText] = useState("");
  const [resetBusy, setResetBusy] = useState(false);
  const closeReset = () => { setResetTarget(null); setResetConfirmText(""); setResetBusy(false); };
  const doReset = useCallback(async () => {
    if (!resetTarget) return;
    if (resetConfirmText.trim().toUpperCase() !== "RESET") {
      Alert.alert("Type RESET", "Please type RESET in capital letters to confirm.");
      return;
    }
    setResetBusy(true);
    try {
      const path =
        resetTarget === "bank"     ? "/admin/bank-ledger/reset"
      : resetTarget === "expenses" ? "/admin/expenses/reset"
      :                              "/admin/payment-history/reset";
      const { data } = await api.post(path);
      let msg = "";
      if (resetTarget === "payments") {
        const mp = data?.manual_payments || {};
        const sd = data?.system_wallet_deposits || {};
        msg = `Payment History cleared.\n• Manual payments archived: ${mp.archived ?? 0}, removed: ${mp.deleted ?? 0}\n• UTR deposits archived: ${sd.archived ?? 0}, removed: ${sd.deleted ?? 0}\n\nArchived in *_archived collections for recovery.`;
      } else {
        msg = `Archived ${data?.archived ?? 0} entries · Removed ${data?.deleted ?? 0} from live ledger.\n\nArchived rows live in ${resetTarget === "bank" ? "bank_ledger_archived" : "expenses_archived"} and can be restored by support.`;
      }
      Alert.alert("Ledger reset", msg);
      closeReset();
      await load();
    } catch (e) {
      Alert.alert("Reset failed", formatApiError(e));
      setResetBusy(false);
    }
  }, [resetTarget, resetConfirmText, load]);

  // ─── Group drilldown drawer (taps on any of the 7 Group cards) ───
  type GroupTxn = {
    id: string; display_id?: string; type: string; amount: number;
    status?: string; level?: number; description?: string; source?: string;
    user_id?: string; reversed_by?: string; reverses?: string; created_at?: string;
    bank?: string; utr?: string; vendor?: string; category?: string;
  };
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [groupTitle, setGroupTitle] = useState<string>("");
  const [groupTxns, setGroupTxns] = useState<GroupTxn[] | null>(null);
  const [groupSubtotal, setGroupSubtotal] = useState<number>(0);
  const [groupLoading, setGroupLoading] = useState(false);

  const openGroup = useCallback(async (gid: string) => {
    setActiveGroup(gid);
    setGroupTxns(null);
    setGroupSubtotal(0);
    setGroupLoading(true);
    setGroupTitle("");
    try {
      const { data } = await api.get(`/admin/finance/groups/${gid}/transactions`, { params: { limit: 200 } });
      setGroupTxns(data?.items || []);
      setGroupSubtotal(Number(data?.subtotal || 0));
      setGroupTitle(String(data?.title || gid));
    } catch (e) {
      Alert.alert("Could not load group transactions", formatApiError(e));
      setGroupTxns([]);
    } finally {
      setGroupLoading(false);
    }
  }, []);

  // Export CSV files via authenticated URL — opens in a new tab/window.
  const exportFile = useCallback((kind: "transactions" | "expenses" | "bank") => {
    const base = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
    const url = `${base}/api/admin/finance/export/${kind}`;
    Linking.openURL(url).catch(() => Alert.alert("Could not open", url));
  }, []);

  // Bucket-detail drawer state
  const [activeBucket, setActiveBucket] = useState<BucketKey | null>(null);
  const [bucketTxns, setBucketTxns] = useState<Txn[] | null>(null);
  const [bucketSubtotal, setBucketSubtotal] = useState<number>(0);
  const [bucketLoading, setBucketLoading] = useState(false);

  // Deposit modal state (Direct-Added bucket)
  const [depositOpen, setDepositOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [utr, setUtr] = useState("");
  const [bankRef, setBankRef] = useState("");
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Account-tally withdraw modal — debits the System Wallet when admin uses
  // platform money for personal/business reasons. Properly audit-logged.
  const [tallyOpen, setTallyOpen] = useState(false);
  const [tallyAmount, setTallyAmount] = useState("");
  const [tallyNote, setTallyNote] = useState("");
  const [tallyBucket, setTallyBucket] = useState<string>("direct_added");
  const [tallyBusy, setTallyBusy] = useState(false);

  const submitTally = async () => {
    const amt = Number(tallyAmount);
    if (!amt || amt <= 0) return Alert.alert("Amount required");
    if (tallyNote.trim().length < 3) return Alert.alert("Please add a short note (min 3 chars).");
    setTallyBusy(true);
    try {
      await api.post("/admin/system-wallet/tally-withdraw", {
        amount: amt,
        note: tallyNote.trim(),
        bucket: tallyBucket,
      });
      setTallyOpen(false);
      setTallyAmount(""); setTallyNote(""); setTallyBucket("direct_added");
      await load();
      Alert.alert("Recorded", `Withdrew ${formatINR(amt)} from System Wallet for account tally.`);
    } catch (e) {
      Alert.alert("Could not record", formatApiError(e));
    } finally {
      setTallyBusy(false);
    }
  };

  // Reconcile state — REMOVED on 2026-06-01 per admin request (button cleared
  // from Treasury Tools to reduce clutter). Keeping state stub commented out
  // in case we want to bring it back behind an "advanced" toggle later.
  // const [reconciling, setReconciling] = useState(false);

  // ─── Invoice preview modal state ─────────────────────────────────
  // When admin taps "View invoice/statement" on a txn row, we fetch the
  // HTML via authenticated `api` (because Linking.openURL opens an
  // external browser that has NO auth token — the request would 401).
  const [invoiceHtml,     setInvoiceHtml]     = useState<string | null>(null);
  const [invoiceTxnId,    setInvoiceTxnId]    = useState<string | null>(null);
  const [invoiceNumber,   setInvoiceNumber]   = useState<string | undefined>(undefined);
  const [invoiceBusy,     setInvoiceBusy]     = useState(false);
  const onPreviewInvoice = useCallback(async (txn: Txn) => {
    setInvoiceBusy(true);
    setInvoiceTxnId(txn.id);
    setInvoiceNumber(txn.invoice_number);
    try {
      const html = await fetchInvoiceHtml(txn.id);
      setInvoiceHtml(html);
    } catch (e: any) {
      const status = e?.response?.status;
      const msg = status === 400
        ? "This transaction type does not have a GST invoice (it's an internal ledger movement)."
        : status === 401 || status === 403
        ? "You're not authorized to view this invoice."
        : e?.response?.data?.detail || e?.message || "Could not load invoice. Please try again.";
      Alert.alert("Invoice unavailable", msg);
      setInvoiceTxnId(null);
    } finally {
      setInvoiceBusy(false);
    }
  }, []);
  const onDownloadInvoice = useCallback(async () => {
    if (!invoiceTxnId) return;
    setInvoiceBusy(true);
    try { await downloadInvoicePdf(invoiceTxnId, invoiceNumber); }
    finally { setInvoiceBusy(false); }
  }, [invoiceTxnId, invoiceNumber]);

  const load = useCallback(async () => {
    try {
      const [{ data }, bd, sb, nw] = await Promise.all([
        api.get("/admin/system-wallet"),
        api.get<Breakdown>("/admin/system-wallet/breakdown").catch(() => ({ data: null as any })),
        api.get("/admin/system-wallet/source-breakdown").catch(() => ({ data: null as any })),
        api.get<NetWorth>("/admin/finance/net-worth").catch(() => ({ data: null as any })),
      ]);
      setData(data);
      setBreakdown(bd.data || null);
      setSourceBreakdown(sb.data || null);
      setNetWorth(nw.data || null);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openBucket = useCallback(async (b: BucketKey) => {
    setActiveBucket(b);
    setBucketTxns(null);
    setBucketSubtotal(0);
    setBucketLoading(true);
    try {
      const { data } = await api.get("/admin/system-wallet/transactions", { params: { bucket: b, limit: 200 } });
      setBucketTxns(data?.items || []);
      setBucketSubtotal(Number(data?.subtotal || 0));
    } catch (e) {
      Alert.alert("Failed", formatApiError(e));
      setBucketTxns([]);
    } finally {
      setBucketLoading(false);
    }
  }, []);

  const runReconcile = useCallback(() => { /* deprecated 2026-06-01 */ }, []);

  const submitDeposit = async () => {    const amt = Number(amount);
    if (!amt || amt <= 0) return Alert.alert("Amount required");
    if (!utr.trim() || utr.trim().length < 4) return Alert.alert("UTR / reference number required");
    setSubmitting(true);
    try {
      await api.post("/admin/system-wallet/deposit", {
        amount: amt,
        utr: utr.trim(),
        bank_ref: bankRef.trim() || null,
        remarks: remarks.trim() || null,
      });
      setDepositOpen(false);
      setAmount(""); setUtr(""); setBankRef(""); setRemarks("");
      await load();
      Alert.alert("Deposited", `₹${amt} added to Direct-Added bucket.`);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
    finally { setSubmitting(false); }
  };

  const activeBucketMeta = useMemo(
    () => BUCKETS.find((x) => x.key === activeBucket) || null,
    [activeBucket],
  );

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN · FINANCE</Text>
            <Text style={styles.title}>System Wallet</Text>
          </View>
        </View>

        {(() => {
          // Hero KPI · BANK BALANCE TALLY — Powered by /admin/finance/net-worth
          // bank_tally block, so the number is reconciliation-aware:
          //   Inflow  = Revenue (regs incl. UPI manual + Offline + Razorpay,
          //             service, platform fee, shop) + UTR deposits + bank
          //             credits + positive adjustments
          //   Outflow = Settled withdrawals + bank debits + reversals + neg. adjustments
          //   Tally   = Inflow − Outflow
          const t = netWorth?.bank_tally;
          const inflow    = Number(t?.inflow  ?? breakdown?.inflow?.total ?? 0);
          const outflow   = Number(t?.outflow ?? breakdown?.outflow?.user_withdrawals_settled ?? 0);
          const tally     = Number(t?.net ?? Math.max(0, inflow - outflow));
          const revAmt    = Number(t?.reversals_amount  || 0);
          const revCnt    = Number(t?.reversals_count   || 0);
          const adjAmt    = Number(t?.adjustments_amount || 0);
          const adjCnt    = Number(t?.adjustments_count  || 0);
          // For visual confidence: held = inflow − outflow should equal what
          // we display; if breakdown is unavailable assume OK.
          const tallyOK = !breakdown ? true : Math.abs(tally - (Number(breakdown?.balance?.in_admin_wallet || 0) + Number(breakdown?.balance?.in_user_wallets || 0))) <= 5;
          return (
            <GradientCard variant="emerald" style={{ padding: 22, marginBottom: 12 }}>
              <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>BANK BALANCE TALLY · ON PLATFORM</Text>
              <Text style={{ fontSize: 36, fontWeight: "800", color: "#fff", letterSpacing: -1, marginTop: 6 }}>{formatINR(tally)}</Text>
              <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 6 }}>
                Net cash position · reversals & adjustments included.
              </Text>
              {/* 2-up identity grid: Inflow | Outflow */}
              <View style={{ flexDirection: "row", gap: 8, marginTop: 16 }}>
                <View style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                  <Text style={{ fontSize: 9, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.5 }}>💰 INFLOW</Text>
                  <Text style={{ fontSize: 14, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>{formatINR(inflow)}</Text>
                </View>
                <View style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                  <Text style={{ fontSize: 9, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.5 }}>🏧 OUTFLOW</Text>
                  <Text style={{ fontSize: 14, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>{formatINR(outflow)}</Text>
                </View>
              </View>
              {/* Reversals + Adjustments row (only shown if non-zero) */}
              {(revCnt > 0 || adjCnt > 0) ? (
                <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                  {revCnt > 0 ? (
                    <View style={{ flex: 1, backgroundColor: "rgba(254, 202, 202, 0.22)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                      <Text style={{ fontSize: 9, color: "#FECACA", fontWeight: "800", letterSpacing: 0.5 }}>↩ REVERSALS · {revCnt}</Text>
                      <Text style={{ fontSize: 13, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>−{formatINR(revAmt)}</Text>
                    </View>
                  ) : null}
                  {adjCnt > 0 ? (
                    <View style={{ flex: 1, backgroundColor: "rgba(254, 240, 138, 0.22)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                      <Text style={{ fontSize: 9, color: "#FEF08A", fontWeight: "800", letterSpacing: 0.5 }}>⚖ ADJUSTMENTS · {adjCnt}</Text>
                      <Text style={{ fontSize: 13, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>
                        {adjAmt >= 0 ? "+" : ""}{formatINR(adjAmt)}
                      </Text>
                    </View>
                  ) : null}
                </View>
              ) : null}
              {/* Identity / formula line */}
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.2)" }}>
                <Feather name={tallyOK ? "check-circle" : "alert-triangle"} size={13} color={tallyOK ? "#A7F3D0" : "#FECACA"} />
                <Text style={{ flex: 1, fontSize: 11, color: "rgba(255,255,255,0.92)", fontWeight: "700", fontVariant: ["tabular-nums"] }}>
                  {tallyOK ? "✓" : "⚠"} {t?.formula || "Inflow − Outflow = Tally"}
                </Text>
              </View>
            </GradientCard>
          );
        })()}

        {/* ────────────────────────────────────────────────────────────────
            🏛 7-GROUP NET-WORTH (formerly the standalone Finance Dashboard).
            Merged in here so the System Wallet is the single source of truth
            for every rupee on the platform. Driven by /admin/finance/net-worth.
            ──────────────────────────────────────────────────────────────── */}
        {netWorth ? (
          <View style={{ marginBottom: 8 }}>
            <Text style={styles.sectionLabel}>Company Net Worth · 7-Group Ledger</Text>
            <View style={styles.nwHero}>
              <Text style={styles.nwHeroLabel}>COMPANY NET WORTH</Text>
              <Text style={styles.nwHeroValue}>{formatINR(netWorth.master.net_worth)}</Text>
              {netWorth.master.components ? (
                <View style={styles.nwComponentsGrid}>
                  <View style={styles.nwCompCol}>
                    <Text style={styles.nwCompLabel}>＋ Cash on hand</Text>
                    <Text style={styles.nwCompValue}>{formatINR(netWorth.master.components.bank_tally_net)}</Text>
                  </View>
                  <View style={styles.nwCompCol}>
                    <Text style={styles.nwCompLabel}>＋ Receivables</Text>
                    <Text style={styles.nwCompValue}>{formatINR(netWorth.master.components.pending_collections)}</Text>
                  </View>
                  <View style={styles.nwCompCol}>
                    <Text style={[styles.nwCompLabel, { color: "#FECACA" }]}>− User wallets</Text>
                    <Text style={styles.nwCompValue}>{formatINR(netWorth.master.components.user_wallet_balance)}</Text>
                  </View>
                  <View style={styles.nwCompCol}>
                    <Text style={[styles.nwCompLabel, { color: "#FECACA" }]}>− Pending withdrawals</Text>
                    <Text style={styles.nwCompValue}>{formatINR(netWorth.master.components.pending_withdrawals)}</Text>
                  </View>
                  <View style={styles.nwCompCol}>
                    <Text style={[styles.nwCompLabel, { color: "#FECACA" }]}>− GST payable</Text>
                    <Text style={styles.nwCompValue}>{formatINR(netWorth.master.components.gst_payable)}</Text>
                  </View>
                </View>
              ) : null}
              <Text style={styles.nwHeroFormula}>{netWorth.master.formula}</Text>
            </View>

            <NwGroup icon="trending-up" title="Group 1 · Revenue Ledger" color="#10B981" onPress={() => openGroup("group_1_revenue")}>
              <NwRow label="Registration revenue"   value={netWorth.group_1_revenue.registration} />
              {/* Joining inflow by source — counts Razorpay, UPI Manual & Offline. */}
              {netWorth.group_1_revenue.by_source ? (
                <View style={styles.sourceMini}>
                  <Text style={styles.sourceMiniHead}>↳ Joinings by source</Text>
                  <NwSourceRow
                    icon="credit-card" label="Razorpay Gateway"
                    amount={netWorth.group_1_revenue.by_source.razorpay.amount}
                    count={netWorth.group_1_revenue.by_source.razorpay.count}
                  />
                  <NwSourceRow
                    icon="smartphone" label="UPI Manual (UTR)"
                    amount={netWorth.group_1_revenue.by_source.upi_manual.amount}
                    count={netWorth.group_1_revenue.by_source.upi_manual.count}
                  />
                  <NwSourceRow
                    icon="tag" label="Offline / Cash"
                    amount={netWorth.group_1_revenue.by_source.offline_cash.amount}
                    count={netWorth.group_1_revenue.by_source.offline_cash.count}
                  />
                </View>
              ) : null}
              {(netWorth.group_1_revenue.reversed || 0) > 0 ? (
                <NwRow label="↳ Reversed (subtracted)" value={-(netWorth.group_1_revenue.reversed || 0)} />
              ) : null}
              <NwRow label="Service revenue"        value={netWorth.group_1_revenue.service} />
              <NwRow label="Platform fee revenue"   value={netWorth.group_1_revenue.platform_fee} />
              <NwRow label="Shop revenue"           value={netWorth.group_1_revenue.shop} />
              <NwRow label="Gross revenue"          value={netWorth.group_1_revenue.gross} bold />
            </NwGroup>

            <NwGroup icon="users" title="Group 2 · User Liability Wallet" color="#F59E0B" onPress={() => openGroup("group_2_liability")}>
              <NwRow label="Total reward credits issued"   value={netWorth.group_2_liability.total_reward_credits} />
              <NwRow label="Total withdrawals settled"     value={netWorth.group_2_liability.total_withdrawals_settled} />
              <NwRow label="Available user balance (LIABILITY)" value={netWorth.group_2_liability.available_user_balance} bold />
            </NwGroup>

            <NwGroup icon="percent" title="Group 3 · GST Ledger" color="#EF4444" onPress={() => openGroup("group_3_gst")}>
              <NwRow label="GST collected"          value={netWorth.group_3_gst.collected} />
              <NwRow label="GST paid (expenses)"    value={netWorth.group_3_gst.paid} />
              <NwRow label="GST payable to govt"    value={netWorth.group_3_gst.payable} bold />
            </NwGroup>

            <NwGroup icon="briefcase" title="Group 4 · Platform Fee Ledger" color="#8B5CF6" onPress={() => openGroup("group_4_platform_fee")}>
              <NwRow label="18% on L1–L10 payouts (company revenue)" value={netWorth.group_4_platform_fee.collected} bold />
            </NwGroup>

            <NwGroup
              icon="dollar-sign" title="Group 5 · Expense Ledger" color="#6366F1"
              rightChip={{ label: "+ Add", onPress: () => setExpOpen(true) }}
              onPress={() => openGroup("group_5_expenses")}
            >
              <NwRow label="Total expenses (approved)" value={netWorth.group_5_expenses.total} bold />
            </NwGroup>

            <NwGroup icon="clock" title="Group 6 · Pending Withdrawals" color="#0EA5E9" onPress={() => openGroup("group_6_pending_withdrawals")}>
              <NwRow label="Awaiting approval" value={netWorth.group_6_pending_withdrawals.pending_amount} bold />
            </NwGroup>

            <NwGroup
              icon="credit-card" title="Group 7 · Bank Ledger" color="#14B8A6"
              rightChip={{ label: "+ Entry", onPress: () => setBankOpen(true) }}
              onPress={() => openGroup("group_7_bank")}
            >
              <NwRow label="Total credits"          value={netWorth.group_7_bank.credits} />
              <NwRow label="Total debits"           value={netWorth.group_7_bank.debits} />
              <NwRow label="Current bank balance"   value={netWorth.group_7_bank.balance} bold />
            </NwGroup>

            <Text style={styles.helpText}>
              Every entry is permanent — reverse or adjust instead of deleting.
            </Text>
          </View>
        ) : null}


        <TouchableOpacity style={styles.depositBtn} onPress={() => setDepositOpen(true)}>
          <Feather name="plus-circle" size={18} color={colors.primaryFg} />
          <Text style={styles.depositBtnText}>Add Direct-Added Money (UTR)</Text>
        </TouchableOpacity>
        <Text style={styles.helpText}>Only Direct-Added funds can be posted to user wallets.</Text>

        <TouchableOpacity
          style={[styles.depositBtn, { backgroundColor: "#B45309", marginTop: 12 }]}
          onPress={() => setTallyOpen(true)}
          testID="open-tally-withdraw"
        >
          <Feather name="minus-circle" size={18} color="#fff" />
          <Text style={styles.depositBtnText}>Withdraw for Account Tally</Text>
        </TouchableOpacity>
        <Text style={styles.helpText}>
          Use this when the System Wallet's money has been spent off-platform (e.g.
          for personal or business use). Properly audit-logged.
        </Text>

        {/* ─── CSV Exports + Manual Adjustment (merged from old Finance Dashboard) ─── */}
        <Text style={[styles.sectionLabel, { marginTop: 18 }]}>Treasury Tools · Exports & Adjustments</Text>
        <NwActionRow
          icon="rotate-ccw" color="#EAB308"
          label="Manual Adjustment Entry"
          description="Add a debit/credit correction to any user wallet — audit-logged."
          onPress={() => setAdjOpen(true)}
        />
        <NwActionRow
          icon="download" color="#0EA5E9"
          label="Export Transactions (CSV)"
          description="Last 90 days of every txn with full audit fields."
          onPress={() => exportFile("transactions")}
        />
        <NwActionRow
          icon="download" color="#6366F1"
          label="Export Expenses (CSV)"
          description="Group 5 entries — full lifetime export."
          onPress={() => exportFile("expenses")}
        />
        <NwActionRow
          icon="download" color="#14B8A6"
          label="Export Bank Ledger (CSV)"
          description="Group 7 entries — full lifetime export."
          onPress={() => exportFile("bank")}
        />

        {/* Destructive reset buttons — type-to-confirm gated.
           Bank Ledger reset and Expense Ledger reset live here so they're
           one tap away from the exports (admins typically export → reset). */}
        <NwActionRow
          icon="rotate-ccw" color="#B3261E"
          label="Reset Bank Ledger"
          description="Clear all Group 7 entries · archived for recovery."
          onPress={() => setResetTarget("bank")}
        />
        <NwActionRow
          icon="rotate-ccw" color="#B3261E"
          label="Reset Expenses Ledger"
          description="Clear all Group 5 expenses · archived for recovery."
          onPress={() => setResetTarget("expenses")}
        />
        <NwActionRow
          icon="rotate-ccw" color="#B3261E"
          label="Reset Payment History"
          description="Clear UPI manual approval log + UTR deposit log · archived for recovery."
          onPress={() => setResetTarget("payments")}
        />

        {/* Phase: User-source unification — 3-way accountability breakdown.
            Shows registration revenue and downstream payout fan-out grouped
            by HOW the user joined (Razorpay / UPI manual / Offline cash).
            Always rendered, even when totals are zero, so admins know the
            tracking is active. Empty rows are styled muted. */}
        {sourceBreakdown ? (
          <View style={{ marginTop: 8 }}>
            <Text style={styles.sectionLabel}>USER SOURCE ACCOUNTABILITY</Text>
            <View style={[styles.identityCard, { padding: 12 }]} testID="src-breakdown-card">
              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <Text style={{ fontSize: 12.5, color: colors.textMuted }}>Registration revenue by source</Text>
                <Text style={{ fontSize: 13, fontWeight: "900", color: colors.textMain }}>
                  {formatINR(sourceBreakdown.totals.amount)} · {sourceBreakdown.totals.count} user{sourceBreakdown.totals.count === 1 ? "" : "s"}
                </Text>
              </View>
              {(["razorpay", "upi_manual", "offline_cash"] as const).map((s) => {
                const row = sourceBreakdown.rows.find((r) => r.source === s);
                const fan = sourceBreakdown.fan_out?.[s];
                const amt = row?.amount || 0;
                const cnt = row?.count || 0;
                const icon = s === "razorpay" ? "credit-card" : s === "upi_manual" ? "smartphone" : "tag";
                const label = s === "razorpay" ? "Razorpay Gateway" : s === "upi_manual" ? "UPI Manual" : "Offline / Cash";
                return (
                  <View key={s} style={localStyles.srcRow} testID={`src-row-${s}`}>
                    <View style={localStyles.srcIcon}>
                      <Feather name={icon as any} size={14} color={colors.primary} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={localStyles.srcLabel}>{label}</Text>
                      <Text style={localStyles.srcSub}>
                        {cnt} signup{cnt === 1 ? "" : "s"}
                        {fan && fan.payouts_count > 0 ? ` · ${fan.payouts_count} payout${fan.payouts_count === 1 ? "" : "s"} (${formatINR(fan.payouts_amount)})` : ""}
                      </Text>
                    </View>
                    <Text style={[localStyles.srcAmt, cnt === 0 && { color: colors.textMuted }]}>
                      {formatINR(amt)}
                    </Text>
                  </View>
                );
              })}
              <Text style={styles.helpText}>
                Inflow on the LEFT vs upline payouts on the RIGHT — must reconcile to the bucket balances above.
              </Text>
            </View>
          </View>
        ) : null}

        {/* Recent UTR Deposits — removed 2026-06-01 per admin request:
            the section was causing excessive scroll and is already
            accessible via Group 7 Bank Ledger drill-down. */}
      </ScrollView>

      {/* ───────── Bucket detail drawer ───────── */}
      <Modal visible={!!activeBucket} animationType="slide" transparent onRequestClose={() => setActiveBucket(null)}>
        <View style={styles.drawerBg}>
          <View style={styles.drawerSheet}>
            <View style={styles.modalHandle} />
            <View style={styles.drawerHeader}>
              <View style={[styles.bucketIcon, { backgroundColor: (activeBucketMeta?.color || colors.primary) + "22" }]}>
                <Feather name={activeBucketMeta?.icon || "list"} size={18} color={activeBucketMeta?.color || colors.primary} />
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.drawerTitle}>{activeBucketMeta?.label || "Transactions"}</Text>
                <Text style={styles.drawerSub}>
                  Bucket total · {formatINR(data?.buckets[activeBucket || ""] || 0)}
                  {bucketTxns ? `   ·   showing ${bucketTxns.length}` : ""}
                </Text>
              </View>
              <TouchableOpacity onPress={() => setActiveBucket(null)} style={styles.closeBtn}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>

            {bucketLoading ? (
              <View style={[styles.center, { paddingVertical: 40 }]}><ActivityIndicator color={colors.primary} /></View>
            ) : (bucketTxns || []).length === 0 ? (
              <View style={styles.empty}><Feather name="inbox" size={22} color={colors.textMuted} /><Text style={styles.emptyText}>No transactions yet</Text></View>
            ) : (
              <ScrollView style={{ flexGrow: 1 }} contentContainerStyle={{ paddingBottom: 28 }}>
                {(bucketTxns || []).map((t) => (
                  <TxnRow key={t.id} txn={t} onPreviewInvoice={onPreviewInvoice} />
                ))}
                <View style={{ height: 16 }} />
                <Text style={styles.subtotalText}>Shown subtotal · {formatINR(bucketSubtotal)}</Text>
                <Text style={styles.subtotalHint}>(latest 200 transactions; pull the wallet screen to refresh totals)</Text>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

      {/* ───────── UTR Deposit modal ───────── */}
      <Modal visible={depositOpen} transparent animationType="slide" onRequestClose={() => setDepositOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.modalBg}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Add Direct-Added Money</Text>
            <Text style={styles.modalSub}>UTR-verified bank deposit. Goes to Direct-Added bucket; from there you can credit user wallets.</Text>
            <Text style={styles.label}>Amount (₹)</Text>
            <TextInput style={styles.input} value={amount} onChangeText={setAmount} placeholder="10000" placeholderTextColor={colors.textMuted} keyboardType="numeric" />
            <Text style={styles.label}>UTR / Bank reference</Text>
            <TextInput style={styles.input} value={utr} onChangeText={setUtr} placeholder="e.g. UTR123456789012" placeholderTextColor={colors.textMuted} autoCapitalize="characters" />
            <Text style={styles.label}>Bank ref (optional)</Text>
            <TextInput style={styles.input} value={bankRef} onChangeText={setBankRef} placeholder="HDFC IMPS" placeholderTextColor={colors.textMuted} />
            <Text style={styles.label}>Remarks (optional)</Text>
            <TextInput style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]} value={remarks} onChangeText={setRemarks} placeholder="Source / purpose" placeholderTextColor={colors.textMuted} multiline />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
              <TouchableOpacity style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]} onPress={() => setDepositOpen(false)}><Text style={{ fontWeight: "700", color: colors.textMain }}>Cancel</Text></TouchableOpacity>
              <TouchableOpacity style={[styles.modalBtn, { backgroundColor: colors.primary }, submitting && { opacity: 0.6 }]} onPress={submitDeposit} disabled={submitting}>{submitting ? <ActivityIndicator color="#fff" /> : <Text style={{ fontWeight: "800", color: "#fff" }}>Deposit</Text>}</TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ───────── Account-Tally Withdraw modal ───────── */}
      <Modal visible={tallyOpen} transparent animationType="slide" onRequestClose={() => setTallyOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.modalBg}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Withdraw for Account Tally</Text>
            <Text style={styles.modalSub}>
              Record a withdrawal from the System Wallet for off-platform usage. Audit-logged.
            </Text>
            <Text style={styles.label}>Amount (₹)</Text>
            <TextInput
              style={styles.input}
              value={tallyAmount}
              onChangeText={setTallyAmount}
              placeholder="1000"
              placeholderTextColor={colors.textMuted}
              keyboardType="numeric"
              testID="tally-amount"
            />
            <Text style={styles.label}>From bucket</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {[
                { k: "direct_added", l: "Direct-Added (UTR)" },
                { k: "service_margin", l: "Service Margin" },
                { k: "shopping_margin", l: "Sales Margin" },
                { k: "referral_commission", l: "Admin Wallet" },
              ].map((b) => (
                <TouchableOpacity
                  key={b.k}
                  onPress={() => setTallyBucket(b.k)}
                  style={[
                    {
                      paddingHorizontal: 12,
                      paddingVertical: 7,
                      borderRadius: 999,
                      borderWidth: 1,
                      borderColor: tallyBucket === b.k ? colors.primary : colors.border,
                      backgroundColor: tallyBucket === b.k ? colors.primary : colors.surface,
                    },
                  ]}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      fontWeight: "700",
                      color: tallyBucket === b.k ? "#fff" : colors.textMain,
                    }}
                  >
                    {b.l}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.label}>Note (audit log)</Text>
            <TextInput
              style={[styles.input, { minHeight: 70, textAlignVertical: "top" }]}
              value={tallyNote}
              onChangeText={setTallyNote}
              placeholder="What was this used for?"
              placeholderTextColor={colors.textMuted}
              multiline
              maxLength={500}
              testID="tally-note"
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
              <TouchableOpacity
                style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}
                onPress={() => setTallyOpen(false)}
              >
                <Text style={{ fontWeight: "700", color: colors.textMain }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.modalBtn,
                  { backgroundColor: "#B45309" },
                  tallyBusy && { opacity: 0.6 },
                ]}
                onPress={submitTally}
                disabled={tallyBusy}
                testID="tally-confirm"
              >
                {tallyBusy ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={{ fontWeight: "800", color: "#fff" }}>Record withdrawal</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ─── Invoice HTML preview modal (in-app, authenticated) ─── */}
      <Modal visible={!!invoiceHtml} animationType="slide" onRequestClose={() => setInvoiceHtml(null)}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.invoiceHeader}>
            <TouchableOpacity onPress={() => { setInvoiceHtml(null); setInvoiceTxnId(null); }} style={styles.invoiceCloseBtn} testID="invoice-close">
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.invoiceHeaderTitle}>GST Invoice / Statement</Text>
            <TouchableOpacity onPress={onDownloadInvoice} style={styles.invoiceCloseBtn} disabled={invoiceBusy} testID="invoice-download">
              {invoiceBusy ? <ActivityIndicator color={colors.primary} size="small" /> : <Feather name="download" size={20} color={colors.primary} />}
            </TouchableOpacity>
          </View>
          {invoiceHtml ? (
            Platform.OS === "web" ? (
              // @ts-ignore — web iframe via dom element on RNW
              <iframe srcDoc={invoiceHtml} style={{ flex: 1, border: 0, width: "100%", height: "100%" } as any} title="invoice-preview" />
            ) : (
              <WebView originWhitelist={["*"]} source={{ html: invoiceHtml }} style={{ flex: 1, backgroundColor: "#fff" }} />
            )
          ) : null}
        </SafeAreaView>
      </Modal>

      {/* ───────── Bank Entry modal (Group 7) ───────── */}
      <NwBankModal open={bankOpen} onClose={() => setBankOpen(false)} onSaved={load} />
      {/* ───────── Expense modal (Group 5) ───────── */}
      <NwExpenseModal open={expOpen} onClose={() => setExpOpen(false)} onSaved={load} />
      {/* ───────── Manual Adjustment modal ───────── */}
      <NwAdjustModal open={adjOpen} onClose={() => setAdjOpen(false)} onSaved={load} />

      {/* ───────── Reset confirmation modal (Bank / Expenses) ───────── */}
      <Modal visible={!!resetTarget} animationType="fade" transparent onRequestClose={closeReset}>
        <KeyboardAvoidingView style={{ flex: 1, justifyContent: "center", padding: 24, backgroundColor: "rgba(0,0,0,0.55)" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={{ backgroundColor: colors.surface, borderRadius: 18, padding: 22 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={{ width: 38, height: 38, borderRadius: 19, backgroundColor: "#FECACA", alignItems: "center", justifyContent: "center" }}>
                <Feather name="alert-triangle" size={18} color="#B3261E" />
              </View>
              <Text style={{ flex: 1, fontSize: 17, fontWeight: "800", color: colors.textMain }}>
                Reset {resetTarget === "bank" ? "Bank Ledger" : "Expenses Ledger"}?
              </Text>
            </View>
            <Text style={{ marginTop: 12, fontSize: 13, color: colors.textMuted, lineHeight: 19 }}>
              This will move ALL entries in the {resetTarget === "bank" ? "Group 7 Bank Ledger" : "Group 5 Expense Ledger"} to an archive collection and remove them from your live books. Net Worth and Bank Tally numbers will recompute immediately.
            </Text>
            <Text style={{ marginTop: 10, fontSize: 12, color: "#B3261E", fontWeight: "700" }}>
              Type RESET below to confirm.
            </Text>
            <TextInput
              value={resetConfirmText}
              onChangeText={setResetConfirmText}
              placeholder="RESET"
              placeholderTextColor={colors.textMuted}
              autoCapitalize="characters"
              style={{ borderWidth: 1.5, borderColor: "#B3261E", backgroundColor: colors.background, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, marginTop: 10, color: colors.textMain, letterSpacing: 4, fontWeight: "800", textAlign: "center", fontSize: 16 }}
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 16 }}>
              <TouchableOpacity onPress={closeReset} style={{ flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: "center", backgroundColor: colors.surfaceMuted }}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={doReset}
                disabled={resetBusy || resetConfirmText.trim().toUpperCase() !== "RESET"}
                style={{ flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: "center", backgroundColor: "#B3261E", opacity: resetBusy || resetConfirmText.trim().toUpperCase() !== "RESET" ? 0.5 : 1 }}
              >
                {resetBusy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Reset Ledger</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ───────── Group transactions drawer ───────── */}
      <Modal visible={!!activeGroup} animationType="slide" transparent onRequestClose={() => setActiveGroup(null)}>
        <View style={styles.drawerBg}>
          <View style={styles.drawerSheet}>
            <View style={styles.modalHandle} />
            <View style={styles.drawerHeader}>
              <View style={[styles.bucketIcon, { backgroundColor: colors.primary + "22" }]}>
                <Feather name="list" size={18} color={colors.primary} />
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.drawerTitle}>{groupTitle || "Group transactions"}</Text>
                <Text style={styles.drawerSub}>
                  Subtotal · {formatINR(groupSubtotal)}
                  {groupTxns ? `   ·   showing ${groupTxns.length}` : ""}
                </Text>
              </View>
              <TouchableOpacity onPress={() => setActiveGroup(null)} style={styles.closeBtn}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>

            {groupLoading ? (
              <View style={[styles.center, { paddingVertical: 40 }]}><ActivityIndicator color={colors.primary} /></View>
            ) : (groupTxns || []).length === 0 ? (
              <View style={styles.empty}><Feather name="inbox" size={22} color={colors.textMuted} /><Text style={styles.emptyText}>No transactions yet</Text></View>
            ) : (
              <ScrollView style={{ flexGrow: 1 }} contentContainerStyle={{ paddingBottom: 28 }}>
                {(groupTxns || []).map((t) => (
                  <View key={t.id} style={styles.groupTxnRow}>
                    <View style={[styles.txnDot, { backgroundColor: t.amount < 0 ? "#B3261E" : colors.primary }]} />
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        {t.display_id ? (
                          <View style={styles.idChip}><Text style={styles.idChipText}>{t.display_id}</Text></View>
                        ) : null}
                        <Text style={styles.gTxnType}>{t.type}</Text>
                        {t.level != null ? (
                          <View style={[styles.idChip, { backgroundColor: "#7C3AED" + "22" }]}><Text style={[styles.idChipText, { color: "#7C3AED" }]}>L{t.level}</Text></View>
                        ) : null}
                        {t.reversed_by ? (
                          <View style={[styles.idChip, { backgroundColor: "#FECACA" }]}><Text style={[styles.idChipText, { color: "#B3261E" }]}>reversed</Text></View>
                        ) : null}
                      </View>
                      {t.description ? <Text style={styles.gTxnDesc} numberOfLines={3}>{t.description}</Text> : null}
                      {(t.bank || t.utr || t.vendor || t.category) ? (
                        <Text style={styles.gTxnMeta}>
                          {t.bank ? `${t.bank}` : ""}{t.bank && t.utr ? " · " : ""}{t.utr ? `UTR ${t.utr}` : ""}
                          {t.vendor ? `vendor: ${t.vendor}` : ""}{t.vendor && t.category ? " · " : ""}{t.category ? `cat: ${t.category}` : ""}
                        </Text>
                      ) : null}
                      <Text style={styles.gTxnMeta}>{t.created_at ? new Date(t.created_at).toLocaleString() : "—"}</Text>
                    </View>
                    <Text style={[styles.txnAmount, { color: t.amount < 0 ? "#B3261E" : colors.primary }]}>
                      {t.amount < 0 ? "" : "+"}{formatINR(t.amount)}
                    </Text>
                  </View>
                ))}
                <View style={{ height: 12 }} />
                <Text style={styles.subtotalText}>Subtotal · {formatINR(groupSubtotal)}</Text>
                <Text style={styles.subtotalHint}>(latest 200 entries; pull the wallet screen to refresh totals)</Text>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

/* ────────────────────────── Breakdown row ────────────────────────── */

function BreakdownRow({ label, sub, value, hint }: { label: string; sub?: string; value: number; hint?: string }) {
  return (
    <View style={styles.bRow}>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={styles.bRowLabel}>{label}</Text>
        {sub ? <Text style={styles.bRowSub}>{sub}</Text> : null}
        {hint ? <Text style={styles.bRowHint}>{hint}</Text> : null}
      </View>
      <Text style={styles.bRowAmount}>{formatINR(value)}</Text>
    </View>
  );
}

/* ────────────────────────── Transaction row ────────────────────────── */

function TxnRow({ txn, onPreviewInvoice }: { txn: Txn; onPreviewInvoice?: (t: Txn) => void }) {
  const dt = new Date(txn.created_at);
  const isCascade = txn.type === "cascade_overflow";
  const isDirect = txn.type === "direct_signup_credit";
  const isFeeResidual = txn.type === "fee_residual";
  const isGst = txn.type === "gst_collected";
  const isL1Funding = txn.type === "l1_funding";
  const isSystemDeposit = txn.type === "system_deposit";
  const isWithdrawal = txn.type === "withdrawal";
  const isShop = txn.type === "shop_commission" || txn.type === "shopping_margin" || txn.type === "shop_commission_reversal";
  const isService = txn.type === "service_commission" || txn.type === "service_margin" || txn.type === "service_commission_reversal";
  const isReversal = txn.type === "shop_commission_reversal" || txn.type === "service_commission_reversal";

  // Color + chip label — covers every txn type appearing in any drilldown.
  const meta = isCascade
    ? { color: "#A855F7", label: `L${txn.level} overflow` }
    : isDirect
    ? { color: "#2E7D52", label: "Direct join (₹100)" }
    : isFeeResidual
    ? { color: "#0EA5A4", label: "Fee residual" }
    : isGst
    ? { color: "#B3261E", label: "GST 18%" }
    : isL1Funding
    ? { color: "#7C3AED", label: "L1 funding (debit)" }
    : isSystemDeposit
    ? { color: "#0B66C2", label: "UTR top-up" }
    : isWithdrawal
    ? { color: "#0F766E", label: "Withdrawal" }
    : isReversal
    ? { color: "#9CA3AF", label: txn.type.includes("shop") ? "Shop reversal" : "Service reversal" }
    : isShop
    ? { color: "#1E40AF", label: "Sales margin" }
    : isService
    ? { color: "#E57A44", label: "Service margin" }
    : txn.type === "referral_payout"
    ? { color: "#7C3AED", label: `Level ${txn.level || "?"} payout` }
    : { color: colors.primary, label: txn.type };

  // The HTML invoice endpoint requires an auth token (Bearer JWT) so we
  // CAN'T just Linking.openURL the URL — the external browser has no auth.
  // Instead, the parent component fetches the HTML via authenticated API
  // and renders it in an in-app WebView/iframe modal.
  const isDebit = Number(txn.amount) < 0;

  return (
    <View style={styles.txnRow}>
      <View style={[styles.txnDot, { backgroundColor: meta.color }]} />
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <View style={[styles.chip, { backgroundColor: meta.color + "1A", borderColor: meta.color + "55" }]}>
            <Text style={[styles.chipText, { color: meta.color }]}>{meta.label}</Text>
          </View>
          {txn.source_user_name ? (
            <Text style={styles.txnSource} numberOfLines={1}>· {txn.source_user_name}</Text>
          ) : null}
          {(txn as any).recipient_email ? (
            <Text style={styles.txnSource} numberOfLines={1}>→ {(txn as any).recipient_email}</Text>
          ) : null}
        </View>
        <Text style={styles.txnDesc} numberOfLines={4}>{txn.description || "—"}</Text>
        {(txn.gross_amount || txn.gst_amount) ? (
          <Text style={styles.txnSplit}>
            Gross {formatINR(txn.gross_amount || 0)} − GST {formatINR(txn.gst_amount || 0)} = Net {formatINR(Math.abs(Number(txn.amount)))}
          </Text>
        ) : null}
        {txn.placement_sponsor_name ? (
          <Text style={styles.txnPlacement}>Placed under: {txn.placement_sponsor_name}{txn.placement_sponsor_email ? ` (${txn.placement_sponsor_email})` : ""}</Text>
        ) : null}
        <Text style={styles.txnMeta}>{dt.toLocaleString()} · ref {txn.reference_number || "—"}</Text>
        {onPreviewInvoice ? (
          <TouchableOpacity
            onPress={() => onPreviewInvoice(txn)}
            style={styles.invoiceLink}
            testID={`invoice-${txn.id}`}
          >
            <Feather name="file-text" size={11} color={colors.primary} />
            <Text style={styles.invoiceLinkText}>View invoice / statement</Text>
          </TouchableOpacity>
        ) : null}
      </View>
      <View style={{ alignItems: "flex-end" }}>
        <Text style={[styles.txnAmount, { color: isDebit ? "#B3261E" : meta.color }]}>
          {isDebit ? "" : "+"}{formatINR(txn.amount)}
        </Text>
      </View>
    </View>
  );
}

/* ────────────────────── Net-Worth helpers (merged from Finance Dashboard) ────────────────────── */

function NwGroup({ icon, title, color, children, rightChip, onPress }: any) {
  const Wrapper: any = onPress ? TouchableOpacity : View;
  return (
    <Wrapper style={nwStyles.card} onPress={onPress} activeOpacity={0.7}>
      <View style={nwStyles.cardHead}>
        <View style={[nwStyles.iconWrap, { backgroundColor: color + "22" }]}>
          <Feather name={icon} size={14} color={color} />
        </View>
        <Text style={nwStyles.cardTitle}>{title}</Text>
        {rightChip ? (
          <TouchableOpacity onPress={rightChip.onPress} style={[nwStyles.chipBtn, { backgroundColor: color }]}>
            <Text style={nwStyles.chipBtnText}>{rightChip.label}</Text>
          </TouchableOpacity>
        ) : null}
        {onPress ? <Feather name="chevron-right" size={16} color={colors.textMuted} style={{ marginLeft: 6 }} /> : null}
      </View>
      <View style={{ marginTop: 8 }}>{children}</View>
      {onPress ? (
        <View style={nwStyles.viewAll}>
          <Feather name="list" size={11} color={colors.primary} />
          <Text style={nwStyles.viewAllText}>Tap to view transactions</Text>
        </View>
      ) : null}
    </Wrapper>
  );
}

function NwRow({ label, value, bold }: { label: string; value: number; bold?: boolean }) {
  return (
    <View style={nwStyles.row}>
      <Text style={[nwStyles.rowLabel, bold && { fontWeight: "800", color: colors.textMain }]}>{label}</Text>
      <Text style={[nwStyles.rowValue, bold && { fontSize: 16, color: colors.primary }]}>{formatINR(value)}</Text>
    </View>
  );
}

function NwSourceRow({ icon, label, amount, count }: { icon: any; label: string; amount: number; count: number }) {
  const empty = count === 0 && amount === 0;
  return (
    <View style={nwStyles.srcRow}>
      <View style={[nwStyles.srcIco, empty && { opacity: 0.4 }]}>
        <Feather name={icon} size={12} color={colors.primary} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[nwStyles.srcLbl, empty && { color: colors.textMuted }]}>{label}</Text>
        <Text style={nwStyles.srcSub}>{count} signup{count === 1 ? "" : "s"}</Text>
      </View>
      <Text style={[nwStyles.srcAmt, empty && { color: colors.textMuted }]}>{formatINR(amount)}</Text>
    </View>
  );
}

function NwActionRow({ icon, label, description, onPress, color }: any) {
  return (
    <TouchableOpacity onPress={onPress} style={[nwStyles.card, { flexDirection: "row", alignItems: "center", paddingVertical: 12 }]}>
      <View style={[nwStyles.iconWrap, { backgroundColor: color + "22", marginRight: 10 }]}>
        <Feather name={icon} size={14} color={color} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ fontWeight: "800", color: colors.textMain }}>{label}</Text>
        <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 2 }}>{description}</Text>
      </View>
      <Feather name="chevron-right" size={18} color={colors.textMuted} />
    </TouchableOpacity>
  );
}

function NwField(props: any) {
  return (
    <TextInput
      placeholderTextColor={colors.textMuted}
      style={[nwStyles.field, props.multiline && { minHeight: 70, textAlignVertical: "top" }]}
      {...props}
    />
  );
}

function NwBankModal({ open, onClose, onSaved }: any) {
  const [kind, setKind] = useState<"credit" | "debit">("credit");
  const [amount, setAmount] = useState("");
  const [bank, setBank] = useState("");
  const [utr, setUtr] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!amount || !description) return Alert.alert("Required", "Amount and description required");
    setBusy(true);
    try {
      await api.post("/admin/bank-ledger", { kind, amount: Number(amount), bank, utr, description });
      setAmount(""); setBank(""); setUtr(""); setDescription("");
      onSaved(); onClose();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={open} animationType="slide" onRequestClose={onClose} transparent>
      <KeyboardAvoidingView style={{ flex: 1, justifyContent: "flex-end" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={nwStyles.sheetBackdrop} />
        <View style={nwStyles.sheet}>
          <Text style={nwStyles.sheetTitle}>Add Bank Entry · Group 7</Text>
          <View style={{ flexDirection: "row", gap: 8, marginVertical: 10 }}>
            {(["credit", "debit"] as const).map((k) => (
              <TouchableOpacity key={k} onPress={() => setKind(k)} style={[nwStyles.toggle, kind === k && { backgroundColor: k === "credit" ? "#10B981" : "#EF4444" }]}>
                <Text style={[nwStyles.toggleText, kind === k && { color: "#fff" }]}>{k.toUpperCase()}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <NwField placeholder="Amount (₹)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" />
          <NwField placeholder="Bank name (optional)" value={bank} onChangeText={setBank} />
          <NwField placeholder="UTR / Reference (optional)" value={utr} onChangeText={setUtr} />
          <NwField placeholder="Description" value={description} onChangeText={setDescription} multiline />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TouchableOpacity onPress={onClose} style={[nwStyles.btn, { backgroundColor: colors.surfaceMuted, flex: 1 }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[nwStyles.btn, { backgroundColor: colors.primary, flex: 1 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function NwExpenseModal({ open, onClose, onSaved }: any) {
  const [category, setCategory] = useState("server_hosting");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [vendor, setVendor] = useState("");
  const [busy, setBusy] = useState(false);

  const cats = ["server_hosting", "sms_charges", "whatsapp_api", "staff_salary", "marketing", "legal_fees", "office_expenses", "payment_gateway", "refunds", "gst_paid", "other"];

  const submit = async () => {
    if (!amount || !description) return Alert.alert("Required", "Amount and description required");
    setBusy(true);
    try {
      await api.post("/admin/expenses", { category, amount: Number(amount), description, vendor });
      setAmount(""); setDescription(""); setVendor("");
      onSaved(); onClose();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={open} animationType="slide" onRequestClose={onClose} transparent>
      <KeyboardAvoidingView style={{ flex: 1, justifyContent: "flex-end" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={nwStyles.sheetBackdrop} />
        <View style={nwStyles.sheet}>
          <Text style={nwStyles.sheetTitle}>Add Expense · Group 5</Text>
          <Text style={nwStyles.fieldLabel}>Category</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 4 }}>
            {cats.map((c) => (
              <TouchableOpacity key={c} onPress={() => setCategory(c)} style={[nwStyles.chipChoice, category === c && { backgroundColor: colors.primary }]}>
                <Text style={[nwStyles.chipChoiceText, category === c && { color: "#fff" }]}>{c.replace(/_/g, " ")}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <NwField placeholder="Amount (₹)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" />
          <NwField placeholder="Vendor (optional)" value={vendor} onChangeText={setVendor} />
          <NwField placeholder="Description" value={description} onChangeText={setDescription} multiline />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TouchableOpacity onPress={onClose} style={[nwStyles.btn, { backgroundColor: colors.surfaceMuted, flex: 1 }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[nwStyles.btn, { backgroundColor: colors.primary, flex: 1 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function NwAdjustModal({ open, onClose, onSaved }: any) {
  const [userId, setUserId] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("correction");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!userId || !amount || !description) return Alert.alert("Required", "User ID, amount and description required");
    setBusy(true);
    try {
      await api.post("/admin/transactions/adjust", { user_id: userId, amount: Number(amount), description, category });
      setUserId(""); setAmount(""); setDescription("");
      onSaved(); onClose();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={open} animationType="slide" onRequestClose={onClose} transparent>
      <KeyboardAvoidingView style={{ flex: 1, justifyContent: "flex-end" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={nwStyles.sheetBackdrop} />
        <View style={nwStyles.sheet}>
          <Text style={nwStyles.sheetTitle}>Manual Adjustment</Text>
          <NwField placeholder="User ID (target wallet)" value={userId} onChangeText={setUserId} />
          <NwField placeholder="Amount (+ credit / − debit)" value={amount} onChangeText={setAmount} />
          <NwField placeholder="Category (correction / writeoff / topup)" value={category} onChangeText={setCategory} />
          <NwField placeholder="Reason / description" value={description} onChangeText={setDescription} multiline />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TouchableOpacity onPress={onClose} style={[nwStyles.btn, { backgroundColor: colors.surfaceMuted, flex: 1 }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[nwStyles.btn, { backgroundColor: "#EAB308", flex: 1 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const nwStyles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: colors.border },
  cardHead: { flexDirection: "row", alignItems: "center" },
  iconWrap: { width: 28, height: 28, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginLeft: 8, flex: 1, letterSpacing: 0.3 },
  chipBtn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  chipBtnText: { color: "#fff", fontSize: 11, fontWeight: "800" },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 5 },
  rowLabel: { fontSize: 12, color: colors.textMuted, flex: 1 },
  rowValue: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.45)" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 18, paddingBottom: 30 },
  sheetTitle: { fontSize: 17, fontWeight: "800", color: colors.textMain, marginBottom: 4 },
  fieldLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, marginTop: 8, letterSpacing: 0.6 },
  field: { borderWidth: 1, borderColor: colors.border, backgroundColor: colors.background, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, marginTop: 8, color: colors.textMain },
  toggle: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border, flex: 1, alignItems: "center" },
  toggleText: { fontWeight: "800", color: colors.textMain },
  chipChoice: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  chipChoiceText: { fontSize: 11, fontWeight: "700", color: colors.textMain, textTransform: "capitalize" },
  btn: { paddingVertical: 12, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  // Joinings-by-source mini list inside Group 1
  srcRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  srcIco: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.primary + "15" },
  srcLbl: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  srcSub: { fontSize: 10, color: colors.textMuted, marginTop: 1 },
  srcAmt: { fontSize: 12.5, fontWeight: "800", color: colors.textMain, fontVariant: ["tabular-nums"] },
});



// Phase: User-source unification — styles for the 3-way breakdown card.
const localStyles = StyleSheet.create({
  srcRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: colors.divider,
  },
  srcIcon: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary + "12",
  },
  srcLabel: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  srcSub:   { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  srcAmt:   { fontSize: 14, fontWeight: "900", color: colors.textMain },
});


const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  backBtn: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  overline: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  sectionLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, marginTop: 6, marginBottom: 8, letterSpacing: 1, textTransform: "uppercase" },

  // Money-flow breakdown panel
  breakdownToggle: { flexDirection: "row", alignItems: "center", gap: 8, justifyContent: "center", paddingVertical: 12, marginBottom: 14, backgroundColor: colors.brand100, borderRadius: 14, borderWidth: 1, borderColor: colors.primary + "55" },
  breakdownToggleText: { flex: 1, fontSize: 13, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  breakdownPanel: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 18 },
  breakdownHeader: { fontSize: 11, fontWeight: "900", color: colors.textMain, letterSpacing: 1, marginBottom: 8, textTransform: "uppercase" },
  bRow: { flexDirection: "row", alignItems: "flex-start", paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, gap: 10 },
  bRowLabel: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  bRowSub: { fontSize: 10, color: colors.textMuted, marginTop: 1, fontWeight: "700" },
  bRowHint: { fontSize: 10, color: colors.textMuted, marginTop: 2, fontStyle: "italic" },
  bRowAmount: { fontSize: 13, fontWeight: "900", color: colors.textMain, fontVariant: ["tabular-nums"], letterSpacing: -0.3 },
  breakdownTotal: { flexDirection: "row", justifyContent: "space-between", paddingTop: 10, marginTop: 4, borderTopWidth: 1, borderTopColor: colors.primary + "55" },
  breakdownTotalLabel: { fontSize: 12, fontWeight: "900", color: colors.primary, letterSpacing: 0.3 },
  breakdownTotalAmount: { fontSize: 15, fontWeight: "900", color: colors.primary, fontVariant: ["tabular-nums"], letterSpacing: -0.3 },
  breakdownNote: { flexDirection: "row", alignItems: "flex-start", gap: 6, marginTop: 14, paddingTop: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  breakdownNoteText: { flex: 1, fontSize: 10, color: colors.textMuted, fontStyle: "italic", lineHeight: 14 },

  // Identity-check box (Inflow = Held + Withdrawn)
  identityBox: { padding: 10, borderRadius: 10, marginTop: 8, borderWidth: 1 },
  identityOK:  { backgroundColor: "#E6F8F1", borderColor: "#0F766E55" },
  identityBad: { backgroundColor: "#FFE4E4", borderColor: "#B3261E55" },
  identityTitle:   { fontSize: 12, fontWeight: "900", letterSpacing: 0.3 },
  identityFormula: { fontSize: 12, fontWeight: "700", color: colors.textMain, fontVariant: ["tabular-nums"], lineHeight: 18 },
  identityDrift:   { fontSize: 11, fontWeight: "700", color: "#B3261E", marginTop: 4 },

  bucketRow: { flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderLeftWidth: 4, borderRadius: 14, padding: 14, marginBottom: 8 },
  bucketIcon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  bucketLabel: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  bucketDesc: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  bucketAmount: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  bucketCta: { flexDirection: "row", alignItems: "center", gap: 2, marginTop: 4 },
  bucketCtaText: { fontSize: 11, fontWeight: "800", color: colors.primary },

  depositBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, backgroundColor: colors.primary, borderRadius: radii.button, marginTop: 14 },
  depositBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },
  reconcileBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, backgroundColor: colors.surface, borderRadius: radii.button, borderWidth: 1, borderColor: colors.primary + "55", marginTop: 12 },
  reconcileBtnText: { fontSize: 13, fontWeight: "800", color: colors.primary, letterSpacing: 0.3 },
  helpText: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 8, marginBottom: 4 },
  invoiceLink: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6, alignSelf: "flex-start", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: colors.brand100, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.primary + "55" },
  invoiceLinkText: { fontSize: 10, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
  // Invoice preview modal
  invoiceHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, backgroundColor: colors.surface },
  invoiceHeaderTitle: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  invoiceCloseBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },

  empty: { padding: 30, alignItems: "center", gap: 6 },
  emptyText: { fontSize: 12, color: colors.textMuted },
  depositRow: { padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 8 },
  depAmount: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  depRemarks: { fontSize: 12, color: colors.textMain, marginTop: 2 },
  depMeta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },

  // Drawer
  drawerBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  drawerSheet: { backgroundColor: colors.background, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 16, paddingTop: 6, paddingBottom: Platform.OS === "ios" ? 24 : 14, height: "82%" },
  drawerHeader: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border, marginBottom: 8 },
  drawerTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  drawerSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  closeBtn: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },

  // Txn row
  txnRow: { flexDirection: "row", gap: 10, alignItems: "flex-start", paddingVertical: 12, paddingHorizontal: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  txnDot: { width: 8, height: 8, borderRadius: 4, marginTop: 6 },
  chip: { paddingHorizontal: 7, paddingVertical: 2, borderRadius: 999, borderWidth: 1 },
  chipText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.4, textTransform: "uppercase" },
  txnSource: { fontSize: 12, fontWeight: "700", color: colors.textMain, flexShrink: 1 },
  txnDesc: { fontSize: 12, color: colors.textMain, marginTop: 4, lineHeight: 17 },
  txnSplit: { fontSize: 11, color: colors.textMuted, marginTop: 4, fontVariant: ["tabular-nums"] },
  txnPlacement: { fontSize: 11, color: colors.primary, marginTop: 2, fontStyle: "italic" },
  txnMeta: { fontSize: 10, color: colors.textMuted, marginTop: 4 },
  txnAmount: { fontSize: 14, fontWeight: "900", letterSpacing: -0.3 },

  subtotalText: { fontSize: 12, fontWeight: "800", color: colors.textMain, textAlign: "right", paddingHorizontal: 4, marginTop: 8 },
  subtotalHint: { fontSize: 10, color: colors.textMuted, textAlign: "right", paddingHorizontal: 4, marginTop: 2, fontStyle: "italic" },

  // UTR modal (unchanged from before)
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, paddingBottom: Platform.OS === "ios" ? 36 : 22 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  modalSub: { fontSize: 12, color: colors.textMuted, marginTop: 4, marginBottom: 8 },
  label: { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginTop: 12, marginBottom: 4, letterSpacing: 0.5, textTransform: "uppercase" },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: colors.textMain, borderWidth: 1, borderColor: colors.border },
  modalBtn: { flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: "center", justifyContent: "center" },

  // 7-Group net-worth hero (merged from old Finance Dashboard)
  nwHero: {
    backgroundColor: colors.primary,
    borderRadius: 18,
    padding: 22,
    marginBottom: 12,
  },
  nwHeroLabel: { fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "800" },
  nwHeroValue: { fontSize: 32, fontWeight: "800", color: colors.primaryFg, marginTop: 6, letterSpacing: -0.5 },
  nwHeroFormula: { fontSize: 11, color: "rgba(255,255,255,0.78)", marginTop: 6, lineHeight: 16 },
  // Components grid showing how Net Worth is computed
  nwComponentsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 14 },
  nwCompCol:    { flexBasis: "31%", flexGrow: 1, backgroundColor: "rgba(255,255,255,0.13)", borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6 },
  nwCompLabel:  { fontSize: 9.5, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.4 },
  nwCompValue:  { fontSize: 13, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] },
  // Joinings-by-source mini block inside Group 1
  sourceMini: { marginTop: 6, marginBottom: 4, paddingLeft: 8, borderLeftWidth: 2, borderLeftColor: colors.primary + "55" },
  sourceMiniHead: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.6, textTransform: "uppercase", marginBottom: 4 },

  // Group drilldown drawer
  drawerBg:    { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  drawerSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8, maxHeight: "88%" },
  drawerHeader:{ flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12, paddingBottom: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  drawerTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  drawerSub:   { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginTop: 2 },
  closeBtn:    { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },

  // ID chips (txn display_id, level, reversed badge)
  idChip:      { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: colors.primary + "18" },
  idChipText:  { fontSize: 10, fontWeight: "800", color: colors.primary, letterSpacing: 0.3 },

  // Transaction row inside the drawer
  groupTxnRow: { flexDirection: "row", alignItems: "flex-start", gap: 10, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  gTxnType:    { fontSize: 12, fontWeight: "800", color: colors.textMain, textTransform: "capitalize" },
  gTxnDesc:    { fontSize: 11.5, color: colors.textMuted, marginTop: 3, lineHeight: 16 },
  gTxnMeta:    { fontSize: 10, color: colors.textMuted, marginTop: 2 },
  subtotalText:{ textAlign: "center", marginTop: 12, fontSize: 14, fontWeight: "800", color: colors.primary },
  subtotalHint:{ textAlign: "center", marginTop: 2, fontSize: 10, color: colors.textMuted },

  // "Tap to view transactions" affordance inside each Group card
  viewAll:     { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border, justifyContent: "center" },
  viewAllText: { fontSize: 10.5, fontWeight: "700", color: colors.primary, letterSpacing: 0.4 },
});
