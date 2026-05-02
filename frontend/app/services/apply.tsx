import { useEffect, useState } from "react";
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, ActivityIndicator, Alert, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

export default function ServiceApply() {
  const router = useRouter();
  const [serviceName, setServiceName] = useState("");
  const [category, setCategory] = useState("");
  const [pincode, setPincode] = useState("");
  const [charge, setCharge] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [existing, setExisting] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/service/me");
        setExisting(data);
        if (data?.application) {
          setServiceName(data.application.service_name || "");
          setCategory(data.application.service_category || "");
          setPincode(data.application.pincode || "");
          setCharge(String(data.application.charge || ""));
          setDescription(data.application.description || "");
        }
      } finally { setLoading(false); }
    })();
  }, []);

  const submit = async () => {
    if (!serviceName.trim() || serviceName.trim().length < 2) return Alert.alert("Service name required");
    if (!category.trim() || category.trim().length < 2) return Alert.alert("Category required");
    if (!/^\d{6}$/.test(pincode)) return Alert.alert("Pincode must be 6 digits");
    const c = Number(charge);
    if (!c || c < 0) return Alert.alert("Charge must be a positive number");
    setSubmitting(true);
    try {
      await api.post("/service/apply", {
        service_name: serviceName.trim(),
        service_category: category.trim(),
        pincode,
        charge: c,
        description: description.trim() || null,
      });
      Alert.alert("Submitted", "Your service application is under review.", [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e) {
      Alert.alert("Could not submit", formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  const status = existing?.service_status as string | null;
  const isApproved = status === "approved";
  const isPending = status === "pending";
  const banner = isApproved ? { color: colors.success, label: "You're a verified service provider" } : isPending ? { color: colors.accent, label: "Application under review" } : status === "rejected" ? { color: colors.error, label: existing?.application?.reject_reason || "Last application rejected — try again" } : null;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
            <Text style={styles.title}>List your service</Text>
          </View>

          {banner && (
            <View style={[styles.banner, { backgroundColor: banner.color + "22", borderColor: banner.color }] }>
              <Feather name={isApproved ? "check-circle" : isPending ? "clock" : "alert-circle"} size={16} color={banner.color} />
              <Text style={[styles.bannerText, { color: banner.color }]}>{banner.label}</Text>
            </View>
          )}

          <Text style={styles.label}>Service name</Text>
          <TextInput style={styles.input} value={serviceName} onChangeText={setServiceName} placeholder="e.g. AC Installation & Repair" placeholderTextColor={colors.textMuted} editable={!isApproved && !isPending} />

          <Text style={styles.label}>Category</Text>
          <TextInput style={styles.input} value={category} onChangeText={setCategory} placeholder="e.g. Electrician, Tutor, Plumber" placeholderTextColor={colors.textMuted} editable={!isApproved && !isPending} />

          <View style={{ flexDirection: "row", gap: 12 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Pincode</Text>
              <TextInput style={styles.input} value={pincode} onChangeText={setPincode} placeholder="6 digits" placeholderTextColor={colors.textMuted} keyboardType="numeric" maxLength={6} editable={!isApproved && !isPending} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Charge (₹)</Text>
              <TextInput style={styles.input} value={charge} onChangeText={setCharge} placeholder="500" placeholderTextColor={colors.textMuted} keyboardType="numeric" editable={!isApproved && !isPending} />
            </View>
          </View>

          <Text style={styles.label}>Description (optional)</Text>
          <TextInput style={[styles.input, { minHeight: 90, textAlignVertical: "top" }]} value={description} onChangeText={setDescription} placeholder="What you offer, experience, area covered..." placeholderTextColor={colors.textMuted} multiline maxLength={500} editable={!isApproved && !isPending} />

          {!isApproved && !isPending && (
            <TouchableOpacity style={[styles.submitBtn, submitting && { opacity: 0.6 }]} onPress={submit} disabled={submitting}>
              {submitting ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={styles.submitText}>Submit application</Text>}
            </TouchableOpacity>
          )}

          <Text style={styles.help}>Once approved by admin, you’ll appear in the Services directory in the user’s pincode area. Earnings credit to your wallet (minus a small platform fee).</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 20 },
  backBtn: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  banner: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 10, borderWidth: 1, marginBottom: 14 },
  bannerText: { fontSize: 12, fontWeight: "700", flex: 1 },
  label: { fontSize: 12, fontWeight: "700", color: colors.textMuted, marginTop: 14, marginBottom: 6, letterSpacing: 0.6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  submitBtn: { marginTop: 22, backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14, alignItems: "center" },
  submitText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  help: { fontSize: 11, color: colors.textMuted, marginTop: 16, lineHeight: 16 },
});
