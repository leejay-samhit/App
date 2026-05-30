import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  RefreshControl, Alert, TextInput, Modal, KeyboardAvoidingView, Platform,
  Linking,
} from "react-native";
import { Stack, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError } from "../../src/api";
import { colors } from "../../src/theme";

type NetWorth = {
  group_1_revenue: { registration: number; service: number; platform_fee: number; shop: number; gross: number };
  group_2_liability: { total_reward_credits: number; total_withdrawals_settled: number; available_user_balance: number };
  group_3_gst: { collected: number; paid: number; payable: number };
  group_4_platform_fee: { collected: number };
  group_5_expenses: { total: number };
  group_6_pending_withdrawals: { pending_amount: number };
  group_7_bank: { credits: number; debits: number; balance: number };
  master: { pending_collections: number; net_worth: number; formula: string };
};

const fmt = (n: number) => `₹${(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function FinanceDashboardScreen() {
  const [data, setData] = useState<NetWorth | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [bankOpen, setBankOpen] = useState(false);
  const [expOpen, setExpOpen] = useState(false);
  const [adjOpen, setAdjOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<NetWorth>("/admin/finance/net-worth");
      setData(r.data);
    } catch (e) {
      Alert.alert("Could not load finance data", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const exportFile = async (kind: "transactions" | "expenses" | "bank") => {
    const base = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
    const url = `${base}/api/admin/finance/export/${kind}`;
    Linking.openURL(url).catch(() => Alert.alert("Could not open", url));
  };

  if (loading) {
    return (
      <View style={[styles.center, { backgroundColor: colors.bg }]}><ActivityIndicator size="large" color={colors.primary} /></View>
    );
  }
  if (!data) return null;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }} edges={["top"]}>
      <Stack.Screen options={{ title: "Finance Dashboard", headerStyle: { backgroundColor: colors.surface } }} />
      <ScrollView
        contentContainerStyle={{ padding: 14, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      >
        {/* Master Net Worth */}
        <View style={[styles.card, { backgroundColor: colors.primary }]}>
          <Text style={[styles.cardTitle, { color: colors.primaryFg, opacity: 0.85 }]}>COMPANY NET WORTH</Text>
          <Text style={[styles.bigNum, { color: colors.primaryFg }]}>{fmt(data.master.net_worth)}</Text>
          <Text style={{ color: colors.primaryFg, opacity: 0.7, fontSize: 11, marginTop: 4 }}>{data.master.formula}</Text>
        </View>

        {/* Group 1 — Revenue */}
        <GroupCard icon="trending-up" title="Group 1 · Revenue Ledger" color="#10B981">
          <Row label="Registration revenue" value={data.group_1_revenue.registration} />
          <Row label="Service revenue" value={data.group_1_revenue.service} />
          <Row label="Platform fee revenue" value={data.group_1_revenue.platform_fee} />
          <Row label="Shop revenue" value={data.group_1_revenue.shop} />
          <Row label="Gross revenue" value={data.group_1_revenue.gross} bold />
        </GroupCard>

        {/* Group 2 — User Liability */}
        <GroupCard icon="users" title="Group 2 · User Liability Wallet" color="#F59E0B">
          <Row label="Total reward credits issued" value={data.group_2_liability.total_reward_credits} />
          <Row label="Total withdrawals settled" value={data.group_2_liability.total_withdrawals_settled} />
          <Row label="Available user balance (LIABILITY)" value={data.group_2_liability.available_user_balance} bold />
        </GroupCard>

        {/* Group 3 — GST */}
        <GroupCard icon="percent" title="Group 3 · GST Ledger" color="#EF4444">
          <Row label="GST collected" value={data.group_3_gst.collected} />
          <Row label="GST paid (expenses)" value={data.group_3_gst.paid} />
          <Row label="GST payable to govt" value={data.group_3_gst.payable} bold />
        </GroupCard>

        {/* Group 4 — Platform Fee */}
        <GroupCard icon="briefcase" title="Group 4 · Platform Fee Ledger" color="#8B5CF6">
          <Row label="18% on L1–L10 payouts (company revenue)" value={data.group_4_platform_fee.collected} bold />
        </GroupCard>

        {/* Group 5 — Expenses */}
        <GroupCard
          icon="dollar-sign" title="Group 5 · Expense Ledger" color="#6366F1"
          rightChip={{ label: "+ Add", onPress: () => setExpOpen(true) }}
        >
          <Row label="Total expenses (approved)" value={data.group_5_expenses.total} bold />
        </GroupCard>

        {/* Group 6 — Pending withdrawals */}
        <GroupCard icon="clock" title="Group 6 · Pending Withdrawals" color="#0EA5E9">
          <Row label="Awaiting approval" value={data.group_6_pending_withdrawals.pending_amount} bold />
        </GroupCard>

        {/* Group 7 — Bank Ledger */}
        <GroupCard
          icon="credit-card" title="Group 7 · Bank Ledger" color="#14B8A6"
          rightChip={{ label: "+ Entry", onPress: () => setBankOpen(true) }}
        >
          <Row label="Total credits" value={data.group_7_bank.credits} />
          <Row label="Total debits" value={data.group_7_bank.debits} />
          <Row label="Current bank balance" value={data.group_7_bank.balance} bold />
        </GroupCard>

        {/* Actions */}
        <View style={{ marginTop: 16, gap: 8 }}>
          <ActionRow
            icon="rotate-ccw"
            label="Manual Adjustment Entry"
            description="Add a debit/credit correction without referencing a prior txn."
            onPress={() => setAdjOpen(true)}
            color="#EAB308"
          />
          <ActionRow
            icon="download"
            label="Export Transactions (CSV)"
            description="Last 90 days of every txn with full audit fields."
            onPress={() => exportFile("transactions")}
            color="#0EA5E9"
          />
          <ActionRow
            icon="download"
            label="Export Expenses (CSV)"
            description="Group 5 entries, all-time."
            onPress={() => exportFile("expenses")}
            color="#6366F1"
          />
          <ActionRow
            icon="download"
            label="Export Bank Ledger (CSV)"
            description="Group 7 entries, all-time."
            onPress={() => exportFile("bank")}
            color="#14B8A6"
          />
        </View>

        <Text style={{ fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 18, lineHeight: 16 }}>
          Generated live from ledger.{"\n"}Every entry is permanent — reverse or adjust instead of deleting.
        </Text>
      </ScrollView>

      <BankEntryModal open={bankOpen} onClose={() => setBankOpen(false)} onSaved={load} />
      <ExpenseModal open={expOpen} onClose={() => setExpOpen(false)} onSaved={load} />
      <AdjustModal open={adjOpen} onClose={() => setAdjOpen(false)} onSaved={load} />
    </SafeAreaView>
  );
}

function GroupCard({ icon, title, color, children, rightChip }: any) {
  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <View style={[styles.iconWrap, { backgroundColor: color + "22" }]}>
          <Feather name={icon} size={14} color={color} />
        </View>
        <Text style={styles.cardTitle}>{title}</Text>
        {rightChip ? (
          <TouchableOpacity onPress={rightChip.onPress} style={[styles.chipBtn, { backgroundColor: color }]}>
            <Text style={styles.chipBtnText}>{rightChip.label}</Text>
          </TouchableOpacity>
        ) : null}
      </View>
      <View style={{ marginTop: 8 }}>{children}</View>
    </View>
  );
}

function Row({ label, value, bold }: { label: string; value: number; bold?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowLabel, bold && { fontWeight: "800", color: colors.textMain }]}>{label}</Text>
      <Text style={[styles.rowValue, bold && { fontSize: 16, color: colors.primary }]}>{fmt(value)}</Text>
    </View>
  );
}

function ActionRow({ icon, label, description, onPress, color }: any) {
  return (
    <TouchableOpacity onPress={onPress} style={[styles.card, { flexDirection: "row", alignItems: "center", paddingVertical: 12 }]}>
      <View style={[styles.iconWrap, { backgroundColor: color + "22", marginRight: 10 }]}>
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

/* ── Modals ──────────────────────────────────────────────────────────── */

function BankEntryModal({ open, onClose, onSaved }: any) {
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
      onSaved();
      onClose();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={open} animationType="slide" onRequestClose={onClose} transparent>
      <KeyboardAvoidingView style={{ flex: 1, justifyContent: "flex-end" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.sheetBackdrop} />
        <View style={styles.sheet}>
          <Text style={styles.sheetTitle}>Add Bank Entry</Text>
          <View style={{ flexDirection: "row", gap: 8, marginVertical: 10 }}>
            {(["credit", "debit"] as const).map((k) => (
              <TouchableOpacity key={k} onPress={() => setKind(k)} style={[styles.toggle, kind === k && { backgroundColor: k === "credit" ? "#10B981" : "#EF4444" }]}>
                <Text style={[styles.toggleText, kind === k && { color: "#fff" }]}>{k.toUpperCase()}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Field placeholder="Amount (₹)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" />
          <Field placeholder="Bank name (optional)" value={bank} onChangeText={setBank} />
          <Field placeholder="UTR / Reference (optional)" value={utr} onChangeText={setUtr} />
          <Field placeholder="Description" value={description} onChangeText={setDescription} multiline />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TouchableOpacity onPress={onClose} style={[styles.btn, { backgroundColor: colors.surfaceMuted, flex: 1 }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[styles.btn, { backgroundColor: colors.primary, flex: 1 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function ExpenseModal({ open, onClose, onSaved }: any) {
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
      onSaved();
      onClose();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={open} animationType="slide" onRequestClose={onClose} transparent>
      <KeyboardAvoidingView style={{ flex: 1, justifyContent: "flex-end" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.sheetBackdrop} />
        <View style={styles.sheet}>
          <Text style={styles.sheetTitle}>Add Expense</Text>
          <Text style={styles.fieldLabel}>Category</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 4 }}>
            {cats.map((c) => (
              <TouchableOpacity key={c} onPress={() => setCategory(c)} style={[styles.chipChoice, category === c && { backgroundColor: colors.primary }]}>
                <Text style={[styles.chipChoiceText, category === c && { color: "#fff" }]}>{c.replace(/_/g, " ")}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
          <Field placeholder="Amount (₹)" value={amount} onChangeText={setAmount} keyboardType="decimal-pad" />
          <Field placeholder="Vendor (optional)" value={vendor} onChangeText={setVendor} />
          <Field placeholder="Description" value={description} onChangeText={setDescription} multiline />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TouchableOpacity onPress={onClose} style={[styles.btn, { backgroundColor: colors.surfaceMuted, flex: 1 }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[styles.btn, { backgroundColor: colors.primary, flex: 1 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function AdjustModal({ open, onClose, onSaved }: any) {
  const [userId, setUserId] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("correction");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!userId || !amount || !description) return Alert.alert("Required", "User ID, amount, description required");
    setBusy(true);
    try {
      await api.post("/admin/transactions/adjust", { user_id: userId, amount: Number(amount), description, category });
      setUserId(""); setAmount(""); setDescription("");
      onSaved();
      onClose();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={open} animationType="slide" onRequestClose={onClose} transparent>
      <KeyboardAvoidingView style={{ flex: 1, justifyContent: "flex-end" }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.sheetBackdrop} />
        <View style={styles.sheet}>
          <Text style={styles.sheetTitle}>Manual Adjustment</Text>
          <Field placeholder="User ID (target wallet)" value={userId} onChangeText={setUserId} />
          <Field placeholder="Amount (+ credit / − debit)" value={amount} onChangeText={setAmount} keyboardType="default" />
          <Field placeholder="Category (correction / writeoff / topup)" value={category} onChangeText={setCategory} />
          <Field placeholder="Reason / description" value={description} onChangeText={setDescription} multiline />
          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <TouchableOpacity onPress={onClose} style={[styles.btn, { backgroundColor: colors.surfaceMuted, flex: 1 }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[styles.btn, { backgroundColor: "#EAB308", flex: 1 }]}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Save</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Field(props: any) {
  return (
    <TextInput
      placeholderTextColor={colors.textMuted}
      style={[styles.field, props.multiline && { minHeight: 70, textAlignVertical: "top" }]}
      {...props}
    />
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  card: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 14,
    marginBottom: 10, borderWidth: 1, borderColor: colors.border,
  },
  bigNum: { fontSize: 32, fontWeight: "800", marginTop: 4 },
  cardHead: { flexDirection: "row", alignItems: "center" },
  iconWrap: { width: 28, height: 28, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginLeft: 8, flex: 1, letterSpacing: 0.3 },
  chipBtn: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  chipBtnText: { color: "#fff", fontSize: 11, fontWeight: "800" },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 5 },
  rowLabel: { fontSize: 12, color: colors.textMuted, flex: 1 },
  rowValue: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  sheetBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.45)" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 18, borderTopRightRadius: 18,
    padding: 18, paddingBottom: 30,
  },
  sheetTitle: { fontSize: 17, fontWeight: "800", color: colors.textMain, marginBottom: 4 },
  fieldLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, marginTop: 8, letterSpacing: 0.6 },
  field: {
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.bg,
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, marginTop: 8, color: colors.textMain,
  },
  toggle: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border, flex: 1, alignItems: "center" },
  toggleText: { fontWeight: "800", color: colors.textMain },
  chipChoice: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  chipChoiceText: { fontSize: 11, fontWeight: "700", color: colors.textMain, textTransform: "capitalize" },
  btn: { paddingVertical: 12, borderRadius: 12, alignItems: "center", justifyContent: "center" },
});
