import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

const BUCKETS: { key: "referral_commission" | "direct_added" | "service_margin" | "shopping_margin" | "gst_collected"; label: string; icon: any; color: string; desc: string }[] = [
  { key: "referral_commission", label: "Referral Commission", icon: "git-branch", color: "#7C3AED", desc: "From the 1+10 cascade" },
  { key: "direct_added", label: "Direct Added Money", icon: "arrow-down-circle", color: "#2E7D52", desc: "UTR-verified deposits" },
  { key: "service_margin", label: "Service Margin", icon: "briefcase", color: "#E57A44", desc: "Platform fee from bookings" },
  { key: "shopping_margin", label: "Shopping Margin", icon: "shopping-bag", color: "#1E40AF", desc: "Commission from shop orders" },
  { key: "gst_collected", label: "GST Collected", icon: "percent", color: "#B3261E", desc: "18% withheld from referral payouts" },
];

type Deposit = { id: string; amount: number; utr: string; bank_ref?: string; remarks?: string; deposited_by_email?: string; created_at: string };

export default function AdminSystemWallet() {
  const router = useRouter();
  const [data, setData] = useState<{ buckets: Record<string, number>; total: number; deposits: Deposit[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [depositOpen, setDepositOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [utr, setUtr] = useState("");
  const [bankRef, setBankRef] = useState("");
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/system-wallet");
      setData(data);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const submitDeposit = async () => {
    const amt = Number(amount);
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

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN · FINANCE</Text>
            <Text style={styles.title}>System Wallet</Text>
          </View>
        </View>

        <GradientCard variant="emerald" style={{ padding: 22, marginBottom: 18 }}>
          <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>TOTAL FUNDS</Text>
          <Text style={{ fontSize: 36, fontWeight: "800", color: "#fff", letterSpacing: -1, marginTop: 6 }}>{formatINR(data?.total || 0)}</Text>
          <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 6 }}>Sum of all 5 categorised buckets below</Text>
        </GradientCard>

        <View style={styles.bucketGrid}>
          {BUCKETS.map((b) => (
            <View key={b.key} style={[styles.bucketCard, { borderLeftColor: b.color }]}>
              <View style={[styles.bucketIcon, { backgroundColor: b.color + "22" }]}><Feather name={b.icon} size={18} color={b.color} /></View>
              <Text style={styles.bucketLabel}>{b.label}</Text>
              <Text style={styles.bucketAmount}>{formatINR(data?.buckets[b.key] || 0)}</Text>
              <Text style={styles.bucketDesc}>{b.desc}</Text>
            </View>
          ))}
        </View>

        <TouchableOpacity style={styles.depositBtn} onPress={() => setDepositOpen(true)}>
          <Feather name="plus-circle" size={18} color={colors.primaryFg} />
          <Text style={styles.depositBtnText}>Add Direct-Added Money (UTR)</Text>
        </TouchableOpacity>
        <Text style={styles.helpText}>Only Direct-Added funds can be posted to user wallets.</Text>

        <Text style={styles.sectionTitle}>Recent Deposits</Text>
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
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 14 },
  backBtn: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  overline: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "700" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain, marginTop: 2 },
  bucketGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 16 },
  bucketCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderLeftWidth: 3, borderRadius: 14, padding: 14 },
  bucketIcon: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  bucketLabel: { fontSize: 11, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.5, textTransform: "uppercase" },
  bucketAmount: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 4 },
  bucketDesc: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  depositBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 14, backgroundColor: colors.primary, borderRadius: radii.button },
  depositBtnText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },
  helpText: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 8, marginBottom: 16 },
  sectionTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginBottom: 8, marginTop: 8, letterSpacing: 0.3 },
  empty: { padding: 30, alignItems: "center", gap: 6 },
  emptyText: { fontSize: 12, color: colors.textMuted },
  depositRow: { padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, marginBottom: 8 },
  depAmount: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  depRemarks: { fontSize: 12, color: colors.textMain, marginTop: 2 },
  depMeta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, paddingBottom: Platform.OS === "ios" ? 36 : 22 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  modalSub: { fontSize: 12, color: colors.textMuted, marginTop: 4, marginBottom: 8 },
  label: { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginTop: 12, marginBottom: 4, letterSpacing: 0.5, textTransform: "uppercase" },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: colors.textMain, borderWidth: 1, borderColor: colors.border },
  modalBtn: { flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: "center", justifyContent: "center" },
});
