import { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, Alert, Modal, TextInput, KeyboardAvoidingView, Platform,
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

  // Reconcile state
  const [reconciling, setReconciling] = useState(false);

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
      const [{ data }, bd, sb] = await Promise.all([
        api.get("/admin/system-wallet"),
        api.get<Breakdown>("/admin/system-wallet/breakdown").catch(() => ({ data: null as any })),
        api.get("/admin/system-wallet/source-breakdown").catch(() => ({ data: null as any })),
      ]);
      setData(data);
      setBreakdown(bd.data || null);
      setSourceBreakdown(sb.data || null);
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

  const runReconcile = useCallback(() => {
    Alert.alert(
      "Reconcile books?",
      "This recomputes each bucket from the transaction ledger (source of truth) and sets the headline total = sum of buckets. Safe to run any time — it never moves real money, just fixes display drift.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reconcile",
          style: "default",
          onPress: async () => {
            setReconciling(true);
            try {
              const { data } = await api.post("/admin/system-wallet/reconcile");
              await load();
              const diff = data?.diff || {};
              const diffLines = Object.entries(diff)
                .filter(([, v]: any) => Math.abs(Number(v) || 0) > 0.005)
                .map(([k, v]: any) => `${k}: ${Number(v) > 0 ? "+" : ""}${formatINR(Number(v))}`)
                .join("\n");
              Alert.alert(
                "Books reconciled",
                diffLines || "No drift detected — books were already in sync.",
              );
            } catch (e) {
              Alert.alert("Reconcile failed", formatApiError(e));
            } finally {
              setReconciling(false);
            }
          },
        },
      ],
    );
  }, [load]);

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
          // Hero KPI: surface the full money-flow identity at the top so the
          // user always sees Inflow = Held + Withdrawn at a glance.
          const inflow      = Number(breakdown?.inflow?.total || 0);
          const adminHeld   = Number(breakdown?.balance?.in_admin_wallet || 0);
          const usersHeld   = Number(breakdown?.balance?.in_user_wallets || 0);
          const heldTotal   = adminHeld + usersHeld;
          const withdrawn   = Number(breakdown?.outflow?.user_withdrawals_settled || 0);
          const bankTally   = Math.max(0, inflow - withdrawn); // == heldTotal when books are balanced
          const tallyOK     = Math.abs(inflow - (heldTotal + withdrawn)) <= 1;
          return (
            <GradientCard variant="emerald" style={{ padding: 22, marginBottom: 12 }}>
              <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>BANK BALANCE TALLY · ON PLATFORM</Text>
              <Text style={{ fontSize: 36, fontWeight: "800", color: "#fff", letterSpacing: -1, marginTop: 6 }}>{formatINR(bankTally)}</Text>
              <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 6 }}>
                Cash currently held on platform (Admin + User wallets).
              </Text>
              {/* 3-up identity grid: Inflow | Held | Withdrawn */}
              <View style={{ flexDirection: "row", gap: 8, marginTop: 16 }}>
                <View style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                  <Text style={{ fontSize: 9, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.5 }}>💰 INFLOW</Text>
                  <Text style={{ fontSize: 14, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>{formatINR(inflow)}</Text>
                </View>
                <View style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                  <Text style={{ fontSize: 9, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.5 }}>🏦 HELD</Text>
                  <Text style={{ fontSize: 14, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>{formatINR(heldTotal)}</Text>
                </View>
                <View style={{ flex: 1, backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 8, borderRadius: 10 }}>
                  <Text style={{ fontSize: 9, color: "rgba(255,255,255,0.85)", fontWeight: "800", letterSpacing: 0.5 }}>🏧 WITHDRAWN</Text>
                  <Text style={{ fontSize: 14, color: "#fff", fontWeight: "800", marginTop: 2, fontVariant: ["tabular-nums"] }}>{formatINR(withdrawn)}</Text>
                </View>
              </View>
              {/* Identity check line */}
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 12, paddingTop: 10, borderTopWidth: 1, borderTopColor: "rgba(255,255,255,0.2)" }}>
                <Feather name={tallyOK ? "check-circle" : "alert-triangle"} size={13} color={tallyOK ? "#A7F3D0" : "#FECACA"} />
                <Text style={{ flex: 1, fontSize: 11, color: "rgba(255,255,255,0.92)", fontWeight: "700", fontVariant: ["tabular-nums"] }}>
                  {tallyOK ? "✓" : "⚠"} Inflow {formatINR(inflow)} = Held {formatINR(heldTotal)} + Withdrawn {formatINR(withdrawn)}
                </Text>
              </View>
            </GradientCard>
          );
        })()}

        {/* ─── Treasury · 3 SUMMED rows + 5 informational rows ─── */}
        {(() => {
          // HONEST IDENTITY: Inflow = Admin Wallet (held) + User Wallets (held) + Withdrawn (left)
          // Other rows are SUB-BUCKETS of Admin Wallet — informational only, NOT summed.
          const adminHeld    = Number(breakdown?.balance?.in_admin_wallet || 0);
          const usersHeld    = Number(breakdown?.balance?.in_user_wallets || 0);
          const withdrawn    = Number(breakdown?.outflow?.user_withdrawals_settled || 0);
          const gstHeld      = Number(breakdown?.outflow?.to_admin_gst_collected || 0);
          const serviceHeld  = Number(breakdown?.outflow?.to_admin_service_margin || 0);
          const shopHeld     = Number(breakdown?.outflow?.to_admin_shop_margin || 0);
          const utrHeld      = Number(breakdown?.outflow?.to_admin_direct_added || 0);
          const referralAdmin= Number(breakdown?.outflow?.to_admin_via_cascade || 0);

          // 3 rows that ADD UP TO INFLOW (Bank Tally identity).
          const tallyRows: { key: TreasuryRowKey; label: string; icon: any; color: string; value: number; sub: string; cta?: string }[] = [
            { key: "admin_wallet",  label: "Admin Wallet · held",   icon: "credit-card", color: "#7C3AED", value: adminHeld, sub: "All admin buckets (signup + cascade + GST + UTR + margins − L1 funding)", cta: "View ledger" },
            { key: "user_wallets",  label: "User Wallets · held",   icon: "users",        color: "#2E7D52", value: usersHeld, sub: "Net referral payouts still sitting in user wallets",                    cta: "View payouts" },
            { key: "withdrawn",     label: "Withdrawn · left platform", icon: "log-out",  color: "#0F766E", value: withdrawn, sub: "Settled withdrawals (UTR) — money physically left to bank",            cta: "View withdrawals" },
          ];
          // 5 informational rows — sub-buckets of Admin Wallet (NOT summed).
          const infoRows: { key: TreasuryInfoKey; label: string; icon: any; color: string; value: number; sub: string; cta?: string }[] = [
            { key: "referral_admin",  label: "↳ Admin Referral (cascade)", icon: "git-branch",       color: "#A855F7", value: referralAdmin, sub: "Admin received L_N when cascade reached root",       cta: "View cascade txns" },
            { key: "gst_info",        label: "↳ GST Collected (18%)",      icon: "percent",          color: "#B3261E", value: gstHeld,       sub: "Regulatory hold — already inside Admin Wallet",        cta: "View GST txns" },
            { key: "service_margin",  label: "↳ Service Margin",           icon: "briefcase",        color: "#E57A44", value: serviceHeld,   sub: "Platform fees from service bookings",                  cta: "View service txns" },
            { key: "shopping_margin", label: "↳ Sales Margin (Shop)",      icon: "shopping-bag",     color: "#1E40AF", value: shopHeld,      sub: "Commission from shop orders",                          cta: "View shop txns" },
            { key: "direct_added",    label: "↳ Direct Added (UTR)",       icon: "arrow-down-circle",color: "#0B66C2", value: utrHeld,       sub: "Manual UTR bank deposits to system wallet",            cta: "View UTR deposits" },
          ];
          const sumAll = tallyRows.reduce((s, r) => s + r.value, 0);
          const inflow = Number(breakdown?.inflow?.total || 0);
          const tallyOK = Math.abs(sumAll - inflow) <= 1;
          return (
            <View style={{ marginBottom: 6 }}>
              <Text style={styles.sectionLabel}>Treasury · Held + Withdrawn = Inflow</Text>
              {tallyRows.map((r) => (
                <TouchableOpacity
                  key={r.key}
                  style={[styles.bucketRow, { borderLeftColor: r.color }]}
                  activeOpacity={0.7}
                  onPress={() => {
                    if (r.key === "admin_wallet") openBucket("admin_wallet");
                    else if (r.key === "user_wallets") openBucket("user_payouts");
                    else if (r.key === "withdrawn") openBucket("user_payouts");
                  }}
                  testID={`treasury-${r.key}`}
                >
                  <View style={[styles.bucketIcon, { backgroundColor: r.color + "22" }]}>
                    <Feather name={r.icon} size={20} color={r.color} />
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.bucketLabel}>{r.label}</Text>
                    <Text style={styles.bucketDesc}>{r.sub}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={styles.bucketAmount}>{formatINR(r.value)}</Text>
                    <View style={styles.bucketCta}>
                      <Text style={styles.bucketCtaText}>{r.cta || "Details"}</Text>
                      <Feather name="chevron-right" size={14} color={colors.primary} />
                    </View>
                  </View>
                </TouchableOpacity>
              ))}
              <View style={[styles.breakdownTotal, { marginTop: 4, backgroundColor: tallyOK ? colors.brand100 : "#FFE4E4" }]}>
                <Text style={[styles.breakdownTotalLabel, { fontSize: 13 }]}>Sum (Held + Withdrawn)</Text>
                <Text style={[styles.breakdownTotalAmount, !tallyOK && { color: "#B3261E" }]}>{formatINR(sumAll)}</Text>
              </View>
              <Text style={styles.helpText}>
                {tallyOK
                  ? `✓ Tally matches inflow (${formatINR(inflow)}). Every rupee accounted for.`
                  : `⚠ Tally ${formatINR(sumAll)} differs from inflow ${formatINR(inflow)} by ${formatINR(Math.abs(sumAll - inflow))}.`}
              </Text>

              {/* ─── INFORMATIONAL · Admin Wallet sub-buckets (NOT summed) ─── */}
              <Text style={[styles.sectionLabel, { marginTop: 18 }]}>Admin Wallet Composition · informational</Text>
              {infoRows.map((r) => (
                <TouchableOpacity
                  key={r.key}
                  style={[styles.bucketRow, { borderLeftColor: r.color, opacity: 0.92 }]}
                  activeOpacity={0.7}
                  onPress={() => {
                    if (r.key === "gst_info") openBucket("gst_collected");
                    else if (r.key === "service_margin") openBucket("service_margin");
                    else if (r.key === "shopping_margin") openBucket("shopping_margin");
                    else if (r.key === "direct_added") openBucket("direct_added");
                    else if (r.key === "referral_admin") openBucket("referral_commission");
                  }}
                  testID={`treasury-info-${r.key}`}
                >
                  <View style={[styles.bucketIcon, { backgroundColor: r.color + "22" }]}>
                    <Feather name={r.icon} size={20} color={r.color} />
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.bucketLabel}>{r.label}</Text>
                    <Text style={styles.bucketDesc}>{r.sub}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={[styles.bucketAmount, { color: colors.textMuted, fontWeight: "700" }]}>{formatINR(r.value)}</Text>
                    <View style={styles.bucketCta}>
                      <Text style={styles.bucketCtaText}>{r.cta || "Details"}</Text>
                      <Feather name="chevron-right" size={14} color={colors.primary} />
                    </View>
                  </View>
                </TouchableOpacity>
              ))}
              <Text style={styles.helpText}>
                ↳ Above rows are sub-buckets of Admin Wallet — they’re already counted in “Admin Wallet · held” above and are NOT added to the tally.
              </Text>
            </View>
          );
        })()}

        {/* ─── Money Flow Breakdown — every rupee accounted for ─── */}
        <TouchableOpacity
          style={styles.breakdownToggle}
          onPress={() => setShowBreakdown((v) => !v)}
          activeOpacity={0.7}
          testID="breakdown-toggle"
        >
          <Feather name="bar-chart-2" size={16} color={colors.primary} />
          <Text style={styles.breakdownToggleText}>Money flow breakdown</Text>
          <Feather name={showBreakdown ? "chevron-up" : "chevron-down"} size={16} color={colors.primary} />
        </TouchableOpacity>
        {showBreakdown && breakdown ? (
          <View style={styles.breakdownPanel}>
            {/* Inflow */}
            <Text style={styles.breakdownHeader}>💰 INFLOW · money coming in</Text>
            <BreakdownRow label="Registration fees (no-ref)" sub={`${breakdown.inflow.no_ref_count} signups × ₹${breakdown.settings.registration_fee.toFixed(0)}`} value={breakdown.inflow.no_ref_signup_revenue} hint="₹100 → direct_signup + ₹18 → GST per signup" />
            <BreakdownRow label="Registration fees (with-ref)" sub={`${breakdown.inflow.with_ref_count} signups × ₹${breakdown.settings.registration_fee.toFixed(0)}`} value={breakdown.inflow.with_ref_signup_revenue} hint="Funds the L1-L10 cascade (paid out to upline)" />
            <BreakdownRow label="UTR direct-added" value={breakdown.inflow.utr_deposits} hint="Manual bank deposits to system wallet" />
            <BreakdownRow label="Service margin" value={breakdown.inflow.service_margin} hint="Platform fees from service bookings" />
            <BreakdownRow label="Shop margin" value={breakdown.inflow.shop_margin} hint="Platform commission from shop orders" />
            <View style={styles.breakdownTotal}>
              <Text style={styles.breakdownTotalLabel}>Total inflow</Text>
              <Text style={styles.breakdownTotalAmount}>{formatINR(breakdown.inflow.total)}</Text>
            </View>

            {/* ─── HELD ON PLATFORM (Admin + Users currently) ─── */}
            {(() => {
              const adminHeld   = Number(breakdown.balance.in_admin_wallet || 0);
              const usersHeld   = Number(breakdown.balance.in_user_wallets || 0);
              const withdrawn   = Number(breakdown.outflow.user_withdrawals_settled || 0);
              const heldTotal   = adminHeld + usersHeld;
              const inflowTotal = Number(breakdown.inflow.total || 0);
              const identityOK  = Math.abs(inflowTotal - (heldTotal + withdrawn)) <= 1;
              return (
                <>
                  <Text style={[styles.breakdownHeader, { marginTop: 16 }]}>🏦 HELD ON PLATFORM · cash currently here</Text>
                  <BreakdownRow label="Admin wallet (all buckets)" value={adminHeld} hint="direct_signup + fee_residual + cascade + GST + UTR + margins − L1 funding" />
                  <BreakdownRow label="User wallets (across all users)" value={usersHeld} hint="Net referral payouts still sitting in user wallets (un-withdrawn)" />
                  <View style={styles.breakdownTotal}>
                    <Text style={styles.breakdownTotalLabel}>Held total (on platform)</Text>
                    <Text style={styles.breakdownTotalAmount}>{formatINR(heldTotal)}</Text>
                  </View>

                  {/* ─── LEFT PLATFORM (Withdrawn to Bank) ─── */}
                  <Text style={[styles.breakdownHeader, { marginTop: 16 }]}>🏧 LEFT PLATFORM · withdrawn to bank</Text>
                  <BreakdownRow label="User withdrawals (settled with UTR)" value={withdrawn} hint="Money that physically left platform via bank transfer / UPI" />
                  <View style={styles.breakdownTotal}>
                    <Text style={styles.breakdownTotalLabel}>Withdrawn total</Text>
                    <Text style={styles.breakdownTotalAmount}>{formatINR(withdrawn)}</Text>
                  </View>

                  {/* ─── IDENTITY CHECK (Inflow = Held + Withdrawn) ─── */}
                  <View style={[styles.identityBox, identityOK ? styles.identityOK : styles.identityBad]}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
                      <Feather name={identityOK ? "check-circle" : "alert-triangle"} size={14} color={identityOK ? "#0F766E" : "#B3261E"} />
                      <Text style={[styles.identityTitle, { color: identityOK ? "#0F766E" : "#B3261E" }]}>
                        {identityOK ? "Books balanced" : "Drift detected"}
                      </Text>
                    </View>
                    <Text style={styles.identityFormula}>
                      Inflow {formatINR(inflowTotal)}  =  Held {formatINR(heldTotal)}  +  Withdrawn {formatINR(withdrawn)}
                    </Text>
                    {!identityOK ? (
                      <Text style={styles.identityDrift}>Drift · {formatINR(Math.abs(inflowTotal - (heldTotal + withdrawn)))} — tap "Reconcile books" below.</Text>
                    ) : null}
                  </View>

                  {/* ─── USER WALLET RECONCILIATION (cumulative-vs-current) ─── */}
                  <Text style={[styles.breakdownHeader, { marginTop: 16 }]}>👥 USER WALLET RECONCILIATION</Text>
                  {(() => {
                    const everCreditedNet = Number(breakdown.outflow.to_user_wallets_referral_net || 0);
                    const otherDelta = everCreditedNet - (usersHeld + withdrawn);
                    const recoCheckOK = Math.abs(otherDelta) <= 1;
                    return (
                      <>
                        <BreakdownRow label="Ever net-credited to user wallets (cumulative)" value={everCreditedNet} hint="L1-L10 referral payouts to non-admin users (lifetime)" />
                        <BreakdownRow label="  ─ Currently held in user wallets" value={usersHeld} hint="Un-withdrawn balance still on platform" />
                        <BreakdownRow label="  ─ Withdrawn by users to bank (UTR)" value={withdrawn} hint="Settled withdrawal requests" />
                        {!recoCheckOK ? (
                          <BreakdownRow
                            label={otherDelta > 0 ? "  ─ Other debits (purchases / adjustments)" : "  ─ Other credits (refunds / bonuses)"}
                            value={Math.abs(otherDelta)}
                            hint={otherDelta > 0 ? "Users spent on shop / services or admin adjustments" : "Refunds / bonuses credited outside referral cascade"}
                          />
                        ) : null}
                        <View style={[styles.identityBox, recoCheckOK ? styles.identityOK : styles.identityBad, { marginTop: 6 }]}>
                          <Text style={[styles.identityTitle, { color: recoCheckOK ? "#0F766E" : "#0B66C2" }]}>
                            {recoCheckOK ? "✓ User wallets reconciled" : "ℹ User wallets reconciled with adjustments"}
                          </Text>
                          <Text style={styles.identityFormula}>
                            {formatINR(everCreditedNet)} credited = {formatINR(usersHeld)} held + {formatINR(withdrawn)} withdrawn{!recoCheckOK ? ` ${otherDelta > 0 ? "+" : "−"} ${formatINR(Math.abs(otherDelta))} adj.` : ""}
                          </Text>
                        </View>
                      </>
                    );
                  })()}

                  {/* ─── ADMIN-WALLET COMPOSITION (full audit trail) ─── */}
                  <Text style={[styles.breakdownHeader, { marginTop: 16 }]}>🏛️ ADMIN WALLET COMPOSITION</Text>
                  <BreakdownRow label="Direct signup (₹100 per no-ref / EARN)" value={breakdown.outflow._legacy_to_admin_direct_signup || 0} />
                  <BreakdownRow label="Fee residual (with-ref leftovers)" value={breakdown.outflow._legacy_to_admin_fee_residual || 0} />
                  <BreakdownRow label="Cascade overflow (chain ended early)" value={breakdown.outflow._legacy_to_admin_cascade_overflow || 0} />
                  <BreakdownRow label="L_N to admin (cascade reached root)" value={breakdown.outflow.to_admin_via_cascade || 0} />
                  <BreakdownRow label="GST collected (18%)" value={breakdown.outflow.to_admin_gst_collected} hint="Regulatory hold — already inside admin wallet" />
                  <BreakdownRow label="L1 funding debit" value={breakdown.outflow._legacy_l1_funding_debit || 0} hint="Negative — funds admin paid out for L1 cycles" />
                  <BreakdownRow label="UTR direct-added" value={breakdown.outflow.to_admin_direct_added || 0} />
                  <BreakdownRow label="Service margin held" value={breakdown.outflow.to_admin_service_margin || 0} />
                  <BreakdownRow label="Shop margin held" value={breakdown.outflow.to_admin_shop_margin || 0} />
                  <View style={styles.breakdownTotal}>
                    <Text style={styles.breakdownTotalLabel}>Admin wallet total (consolidated)</Text>
                    <Text style={styles.breakdownTotalAmount}>{formatINR(adminHeld)}</Text>
                  </View>
                </>
              );
            })()}

            {/* Config */}
            <View style={styles.breakdownNote}>
              <Feather name="info" size={12} color={colors.textMuted} />
              <Text style={styles.breakdownNoteText}>
                Current rules · L1 fires every {breakdown.settings.directs_required} directs · Reg fee ₹{breakdown.settings.registration_fee.toFixed(0)} · L1-L10: ₹{breakdown.settings.level_payouts.map((x) => x.toFixed(0)).join(" / ")}
              </Text>
            </View>
          </View>
        ) : null}

        <TouchableOpacity style={styles.depositBtn} onPress={() => setDepositOpen(true)}>
          <Feather name="plus-circle" size={18} color={colors.primaryFg} />
          <Text style={styles.depositBtnText}>Add Direct-Added Money (UTR)</Text>
        </TouchableOpacity>
        <Text style={styles.helpText}>Only Direct-Added funds can be posted to user wallets.</Text>

        <TouchableOpacity
          style={[styles.reconcileBtn, reconciling && { opacity: 0.6 }]}
          onPress={runReconcile}
          disabled={reconciling}
          testID="reconcile-books"
        >
          {reconciling ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <Feather name="refresh-cw" size={15} color={colors.primary} />
          )}
          <Text style={styles.reconcileBtnText}>{reconciling ? "Reconciling…" : "Reconcile books"}</Text>
        </TouchableOpacity>
        <Text style={styles.helpText}>
          Recomputes each bucket from the transaction ledger and fixes any drift. Run any time to verify books tally.
        </Text>

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
                const icon = s === "razorpay" ? "credit-card" : s === "upi_manual" ? "smartphone" : "dollar-sign";
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

        <Text style={styles.sectionLabel}>Recent UTR Deposits</Text>
        {(data?.deposits || []).length === 0 ? (
          <View style={styles.empty}><Feather name="inbox" size={20} color={colors.textMuted} /><Text style={styles.emptyText}>No deposits yet</Text></View>
        ) : (
          (data?.deposits || []).map((d) => (
            <View key={d.id} style={styles.depositRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.depAmount}>{formatINR(d.amount)} · UTR {d.utr}</Text>
                {d.remarks ? <Text style={styles.depRemarks}>{d.remarks}</Text> : null}
                <Text style={styles.depMeta}>{new Date(d.created_at).toLocaleString()} · {d.deposited_by_email || "system"}</Text>
              </View>
            </View>
          ))
        )}
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
});
