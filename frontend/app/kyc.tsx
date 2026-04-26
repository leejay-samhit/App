import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing } from "../src/theme";

type KYC = {
  status: "none" | "pending" | "approved" | "rejected";
  full_name?: string | null;
  aadhaar?: string | null;
  pan?: string | null;
  reject_reason?: string | null;
  submitted_at?: string | null;
};

const STATUS_COLORS: Record<string, string> = {
  none: "#94A3B8",
  pending: colors.warning,
  approved: colors.success,
  rejected: "#B3261E",
};

export default function UserKYC() {
  const router = useRouter();
  const [data, setData] = useState<KYC | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [fullName, setFullName] = useState("");
  const [aadhaar, setAadhaar] = useState("");
  const [pan, setPan] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<KYC>("/users/me/kyc");
      setData(data);
      setFullName(data.full_name || "");
      setAadhaar(data.aadhaar || "");
      setPan(data.pan || "");
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onSubmit = async () => {
    setMsg("");
    setSubmitting(true);
    try {
      await api.post("/users/me/kyc", { full_name: fullName.trim(), aadhaar: aadhaar.trim(), pan: pan.trim() });
      await load();
      setMsg("KYC submitted for review");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally { setSubmitting(false); }
  };

  if (loading || !data) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  const editable = data.status !== "approved" && data.status !== "pending";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="kyc-back">
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>KYC Verification</Text>
            <View style={{ width: 40 }} />
          </View>

          <View style={[styles.statusCard, { borderColor: STATUS_COLORS[data.status] }]}>
            <View style={[styles.statusIcon, { backgroundColor: STATUS_COLORS[data.status] }]}>
              <Feather
                name={data.status === "approved" ? "check" : data.status === "rejected" ? "x" : data.status === "pending" ? "clock" : "alert-circle"}
                size={20}
                color="#fff"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.statusTitle}>
                {data.status === "approved" ? "Verified" : data.status === "pending" ? "Under review" : data.status === "rejected" ? "Rejected" : "Not submitted"}
              </Text>
              <Text style={styles.statusBody}>
                {data.status === "approved" && "Your identity has been verified. You can use all features."}
                {data.status === "pending" && "We're reviewing your KYC details. This usually takes 24 hours."}
                {data.status === "rejected" && (data.reject_reason || "Please review and resubmit.")}
                {data.status === "none" && "Submit your details to verify your account for safer payouts."}
              </Text>
            </View>
          </View>

          <Text style={styles.sectionLabel}>YOUR DETAILS</Text>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>Full name (as per ID)</Text>
            <TextInput
              testID="kyc-fullname"
              value={fullName}
              onChangeText={setFullName}
              editable={editable}
              style={[styles.input, !editable && styles.inputDisabled]}
              placeholder="Enter full legal name"
              placeholderTextColor={colors.textMuted}
            />
          </View>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>Aadhaar number (12 digits)</Text>
            <TextInput
              testID="kyc-aadhaar"
              value={aadhaar}
              onChangeText={(t) => setAadhaar(t.replace(/\D/g, "").slice(0, 12))}
              editable={editable}
              keyboardType="numeric"
              style={[styles.input, !editable && styles.inputDisabled]}
              placeholder="XXXX XXXX XXXX"
              placeholderTextColor={colors.textMuted}
            />
          </View>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>PAN (10 characters)</Text>
            <TextInput
              testID="kyc-pan"
              value={pan}
              onChangeText={(t) => setPan(t.toUpperCase().slice(0, 10))}
              editable={editable}
              autoCapitalize="characters"
              style={[styles.input, !editable && styles.inputDisabled]}
              placeholder="ABCDE1234F"
              placeholderTextColor={colors.textMuted}
            />
          </View>

          {msg ? <Text style={[styles.msg, { color: msg.includes("submit") ? colors.success : "#B3261E" }]} testID="kyc-msg">{msg}</Text> : null}

          {editable && (
            <TouchableOpacity onPress={onSubmit} disabled={submitting || !fullName || aadhaar.length !== 12 || pan.length !== 10} style={[styles.submitBtn, (submitting || !fullName || aadhaar.length !== 12 || pan.length !== 10) && { opacity: 0.5 }]} testID="kyc-submit">
              {submitting ? <ActivityIndicator color={colors.primaryFg} /> : (
                <>
                  <Feather name="shield" size={16} color={colors.primaryFg} />
                  <Text style={styles.submitBtnText}>Submit for review</Text>
                </>
              )}
            </TouchableOpacity>
          )}

          <Text style={styles.note}>
            Your information is encrypted and used only for verification compliance. We do not share details with third parties.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  statusCard: { flexDirection: "row", alignItems: "center", gap: 14, padding: 16, borderRadius: radii.card, borderWidth: 2, backgroundColor: colors.surface, marginBottom: 24 },
  statusIcon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  statusTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  statusBody: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  field: { marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 14, fontSize: 15, color: colors.textMain },
  inputDisabled: { backgroundColor: colors.surfaceMuted, color: colors.textMuted },
  msg: { fontSize: 13, marginTop: 4, marginBottom: 8, textAlign: "center" },
  submitBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 8 },
  submitBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
  note: { fontSize: 11, color: colors.textMuted, marginTop: 16, textAlign: "center", lineHeight: 16 },
});
