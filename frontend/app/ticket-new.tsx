import { useState } from "react";
import { View, Text, StyleSheet, TextInput, TouchableOpacity, KeyboardAvoidingView, Platform, ScrollView, Alert, ActivityIndicator, Image } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing } from "../src/theme";

const CATEGORIES: { key: string; label: string; icon: any }[] = [
  { key: "payment", label: "Payment", icon: "credit-card" },
  { key: "withdrawal", label: "Withdrawal", icon: "arrow-up-circle" },
  { key: "account", label: "Account", icon: "user" },
  { key: "kyc", label: "KYC", icon: "shield" },
  { key: "product", label: "Shop / Product", icon: "shopping-bag" },
  { key: "account_deletion", label: "Account Deletion", icon: "user-x" },
  { key: "other", label: "Other", icon: "help-circle" },
];

export default function TicketNewScreen() {
  const router = useRouter();
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("other");
  const [message, setMessage] = useState("");
  const [attachment, setAttachment] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const pickImage = async () => {
    try {
      const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (status !== "granted") { Alert.alert("Permission denied", "Allow photo access to attach an image."); return; }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.6, base64: true, allowsEditing: false,
      });
      if (res.canceled || !res.assets?.length) return;
      const a = res.assets[0];
      if (a.base64) setAttachment(`data:image/jpeg;base64,${a.base64}`);
    } catch (e) { Alert.alert("Attach failed", formatApiError(e)); }
  };

  const onSubmit = async () => {
    const s = subject.trim();
    const m = message.trim();
    if (s.length < 3) { Alert.alert("Subject is too short"); return; }
    if (m.length < 3) { Alert.alert("Message is too short"); return; }
    setSubmitting(true);
    try {
      const { data } = await api.post<{ ok: boolean; ticket: { id: string } }>("/tickets", {
        subject: s, category, message: m, attachment_b64: attachment,
      });
      router.replace({ pathname: "/ticket" as any, params: { id: data.ticket.id } });
    } catch (e) { Alert.alert("Couldn't create ticket", formatApiError(e)); }
    finally { setSubmitting(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="ticketnew-back">
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>New ticket</Text>
          <View style={{ width: 40 }} />
        </View>
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.sectionLabel}>CATEGORY</Text>
          <View style={styles.catGrid}>
            {CATEGORIES.map((c) => {
              const active = category === c.key;
              return (
                <TouchableOpacity key={c.key} onPress={() => setCategory(c.key)} style={[styles.catChip, active && styles.catChipActive]} testID={`ticketnew-cat-${c.key}`}>
                  <Feather name={c.icon} size={14} color={active ? colors.primaryFg : colors.textMain} />
                  <Text style={[styles.catChipText, active && { color: colors.primaryFg }]}>  {c.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
          <Text style={styles.sectionLabel}>SUBJECT</Text>
          <TextInput
            style={styles.input}
            placeholder="Briefly describe the issue"
            placeholderTextColor={colors.textMuted}
            value={subject}
            onChangeText={setSubject}
            maxLength={120}
            testID="ticketnew-subject"
          />
          <Text style={styles.sectionLabel}>MESSAGE</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            placeholder="Describe what happened, what you expected, and any steps to reproduce..."
            placeholderTextColor={colors.textMuted}
            value={message}
            onChangeText={setMessage}
            multiline
            textAlignVertical="top"
            testID="ticketnew-message"
          />
          <Text style={styles.sectionLabel}>ATTACHMENT (OPTIONAL)</Text>
          {attachment ? (
            <View style={styles.attachPreview}>
              <Image source={{ uri: attachment }} style={styles.attachImg} />
              <TouchableOpacity onPress={() => setAttachment(null)} style={styles.removeAttach} testID="ticketnew-remove-attach">
                <Feather name="x" size={16} color="#fff" />
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity style={styles.attachBtn} onPress={pickImage} testID="ticketnew-attach">
              <Feather name="paperclip" size={16} color={colors.textMain} />
              <Text style={styles.attachBtnText}>  Add screenshot</Text>
            </TouchableOpacity>
          )}
        </ScrollView>
        <View style={styles.footer}>
          <TouchableOpacity onPress={onSubmit} disabled={submitting} style={[styles.submitBtn, submitting && { opacity: 0.7 }]} testID="ticketnew-submit">
            {submitting ? <ActivityIndicator color={colors.primaryFg} /> : <><Feather name="send" size={16} color={colors.primaryFg} /><Text style={styles.submitBtnText}>  Submit ticket</Text></>}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  sectionLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 16, marginBottom: 8 },
  catGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  catChip: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10, borderRadius: 20, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  catChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  catChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 14, color: colors.textMain },
  textarea: { minHeight: 140, paddingTop: 14 },
  attachBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", padding: 14, borderRadius: radii.input, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, backgroundColor: colors.surface },
  attachBtnText: { color: colors.textMain, fontSize: 13, fontWeight: "600" },
  attachPreview: { position: "relative" },
  attachImg: { width: "100%", height: 180, borderRadius: radii.card },
  removeAttach: { position: "absolute", top: 8, right: 8, width: 28, height: 28, borderRadius: 14, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center" },
  footer: { padding: spacing.screen, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.background },
  submitBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 15 },
  submitBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
});
