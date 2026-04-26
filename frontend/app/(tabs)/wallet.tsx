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
import { useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Withdrawal = {
  id: string;
  amount: number;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  processed_at?: string | null;
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
  const { user, refresh } = useAuth();
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
  const [txns, setTxns] = useState<Txn[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [amount, setAmount] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

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

        <View style={styles.balanceCard}>
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
          <TouchableOpacity
            style={[styles.withdrawBtn, !hasPayoutMethod && { opacity: 0.5 }]}
            onPress={() => {
              if (!hasPayoutMethod) {
                Alert.alert("Add UPI / Bank", "Please add UPI or bank details from your profile first.");
                return;
              }
              setShowModal(true);
            }}
            testID="wallet-request-withdraw"
          >
            <Feather name="arrow-up-right" size={18} color={colors.accentFg} />
            <Text style={styles.withdrawBtnText}>Request withdrawal</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.sectionLabel}>WITHDRAWAL HISTORY</Text>
        {withdrawals.length === 0 ? (
          <Text style={styles.empty}>No withdrawals yet.</Text>
        ) : (
          withdrawals.map((w) => (
            <View key={w.id} style={styles.row} testID={`withdrawal-${w.id}`}>
              <View style={styles.rowLeft}>
                <View style={[styles.rowDot, { backgroundColor: w.status === "approved" ? colors.success : w.status === "rejected" ? "#B3261E" : colors.warning }]} />
                <View>
                  <Text style={styles.rowTitle}>{formatINR(w.amount)}</Text>
                  <Text style={styles.rowSub}>{new Date(w.created_at).toLocaleDateString()}</Text>
                </View>
              </View>
              <Text style={[styles.statusPill, { color: w.status === "approved" ? colors.success : w.status === "rejected" ? "#B3261E" : colors.warning }]}>{w.status.toUpperCase()}</Text>
            </View>
          ))
        )}

        <Text style={styles.sectionLabel}>TRANSACTIONS</Text>
        {txns.length === 0 ? (
          <Text style={styles.empty}>No transactions yet.</Text>
        ) : (
          txns.map((t) => (
            <View key={t.id} style={styles.row}>
              <View style={styles.rowLeft}>
                <Feather
                  name={t.type === "referral_payout" ? "trending-up" : t.type === "withdrawal" ? "arrow-up-right" : "credit-card"}
                  size={18}
                  color={t.amount > 0 ? colors.success : colors.textMain}
                  style={{ marginRight: 12 }}
                />
                <View>
                  <Text style={styles.rowTitle}>{t.description || t.type}</Text>
                  <Text style={styles.rowSub}>{new Date(t.created_at).toLocaleDateString()}</Text>
                </View>
              </View>
              <Text style={[styles.amountText, { color: t.amount >= 0 ? colors.success : "#B3261E" }]}>
                {t.amount >= 0 ? "+" : ""}{formatINR(t.amount)}
              </Text>
            </View>
          ))
        )}
      </ScrollView>

      <Modal visible={showModal} transparent animationType="slide" onRequestClose={() => setShowModal(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Request withdrawal</Text>
            <Text style={styles.modalSub}>Available: {formatINR(user?.wallet_balance || 0)}</Text>
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
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 40 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1, marginBottom: 20 },
  balanceCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 24, marginBottom: 24 },
  balanceLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  balanceAmount: { color: colors.primaryFg, fontSize: 44, fontWeight: "800", marginTop: 6, letterSpacing: -1.5 },
  statsRow: { flexDirection: "row", gap: 32, marginTop: 16 },
  statRowLabel: { color: "rgba(255,255,255,0.6)", fontSize: 12 },
  statRowValue: { color: colors.primaryFg, fontSize: 16, fontWeight: "700", marginTop: 2 },
  withdrawBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.accent, paddingVertical: 14, borderRadius: radii.button, marginTop: 18, gap: 8 },
  withdrawBtnText: { color: colors.accentFg, fontWeight: "700", fontSize: 15 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12, marginTop: 8 },
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
});
