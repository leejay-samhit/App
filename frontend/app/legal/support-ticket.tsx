// Public (unauthenticated) support ticket submission.
// Linked from /legal/contact (pre-login Contact page). Anyone with a valid
// email address can raise a ticket without signing up. Backed by
// POST /api/tickets/public — stored in the same `tickets` collection with
// is_guest=true so admin sees them alongside authenticated users' tickets.

import { useState, useMemo } from "react";
import {
  View, Text, ScrollView, StyleSheet, TextInput, TouchableOpacity,
  KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

const CATEGORIES: { key: string; label: string; icon: any }[] = [
  { key: "payment",    label: "Payment / UTR Issue",   icon: "credit-card" },
  { key: "withdrawal", label: "Withdrawal Issue",      icon: "arrow-up-circle" },
  { key: "kyc",        label: "KYC Issue",             icon: "shield" },
  { key: "account",    label: "Account / Login Issue", icon: "user" },
  { key: "product",    label: "Referral / Network",    icon: "git-branch" },
  { key: "other",      label: "Other",                 icon: "help-circle" },
];

const BODY_TEMPLATE =
  "Hi Team,\n\n" +
  "I'm facing the following issue:\n\n" +
  "[Describe what happened]\n\n" +
  "Steps I tried so far:\n" +
  "- \n" +
  "- \n\n" +
  "Note: For your privacy, please DO NOT include your phone, referral code, " +
  "UTR or UPI ID here. We can reach you via the email above.";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function PublicSupportTicket() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("ISSUE");
  const [category, setCategory] = useState<string>("other");
  const [customCategory, setCustomCategory] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState<{ id: string } | null>(null);

  const emailOk = useMemo(() => EMAIL_RE.test(email.trim()), [email]);
  const isOther = category === "other";
  const canSubmit =
    emailOk &&
    subject.trim().length >= 2 &&
    message.trim().length >= 10 &&
    (!isOther || customCategory.trim().length >= 2);

  const onSubmit = async () => {
    if (!canSubmit || submitting) return;
    setSubmitting(true);
    try {
      const { data } = await api.post<{ ok: boolean; ticket_id: string }>(
        "/tickets/public",
        {
          email: email.trim(),
          name: name.trim() || null,
          subject: subject.trim() || "ISSUE",
          category,
          custom_category: isOther ? customCategory.trim() : null,
          message: message.trim(),
        },
      );
      setSent({ id: data.ticket_id });
    } catch (e) {
      Alert.alert("Couldn't submit ticket", formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>Ticket submitted</Text>
          <View style={{ width: 40 }} />
        </View>
        <View style={styles.doneWrap}>
          <View style={styles.doneCircle}>
            <Feather name="check" size={40} color={colors.primaryFg} />
          </View>
          <Text style={styles.doneTitle}>We've received your ticket</Text>
          <Text style={styles.doneSub}>
            Ticket ID: {sent.id.slice(0, 8).toUpperCase()}
            {"\n"}We'll reply to{" "}
            <Text style={{ fontWeight: "800", color: colors.textMain }}>{email.trim()}</Text>{" "}
            within 48 hours.
          </Text>
          <TouchableOpacity style={styles.doneBtn} onPress={() => router.back()}>
            <Text style={styles.doneBtnText}>Done</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="pub-ticket-back">
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>Open a support ticket</Text>
          <View style={{ width: 40 }} />
        </View>

        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 120 }}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hintBox}>
            <Feather name="info" size={14} color={colors.primary} />
            <Text style={styles.hintText}>
              You don't need an account. Just share your email below — we'll get back
              to you within 48 hours.
            </Text>
          </View>

          <Text style={styles.sectionLabel}>FROM (YOUR EMAIL) *</Text>
          <TextInput
            style={[styles.input, !emailOk && email.length > 0 && styles.inputError]}
            placeholder="your.email@example.com"
            placeholderTextColor={colors.textMuted}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            testID="pub-ticket-email"
          />
          {!emailOk && email.length > 0 ? (
            <Text style={styles.errText}>Enter a valid email address.</Text>
          ) : null}

          <Text style={styles.sectionLabel}>YOUR NAME (OPTIONAL)</Text>
          <TextInput
            style={styles.input}
            placeholder="Full name"
            placeholderTextColor={colors.textMuted}
            value={name}
            onChangeText={setName}
            maxLength={80}
            testID="pub-ticket-name"
          />

          <Text style={styles.sectionLabel}>CATEGORY *</Text>
          <View style={styles.catGrid}>
            {CATEGORIES.map((c) => {
              const active = category === c.key;
              return (
                <TouchableOpacity
                  key={c.key}
                  onPress={() => setCategory(c.key)}
                  style={[styles.catChip, active && styles.catChipActive]}
                  testID={`pub-ticket-cat-${c.key}`}
                >
                  <Feather
                    name={c.icon}
                    size={14}
                    color={active ? colors.primaryFg : colors.textMain}
                  />
                  <Text style={[styles.catChipText, active && { color: colors.primaryFg }]}>
                    {"  "}
                    {c.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {isOther ? (
            <>
              <Text style={styles.sectionLabel}>CUSTOM CATEGORY *</Text>
              <TextInput
                style={styles.input}
                placeholder='Type your issue category (e.g. "App crash")'
                placeholderTextColor={colors.textMuted}
                value={customCategory}
                onChangeText={setCustomCategory}
                maxLength={60}
                testID="pub-ticket-custom-cat"
              />
            </>
          ) : null}

          <Text style={styles.sectionLabel}>SUBJECT *</Text>
          <TextInput
            style={styles.input}
            placeholder="ISSUE"
            placeholderTextColor={colors.textMuted}
            value={subject}
            onChangeText={setSubject}
            maxLength={120}
            testID="pub-ticket-subject"
          />

          <View style={styles.bodyHeaderRow}>
            <Text style={styles.sectionLabel}>BODY MESSAGE *</Text>
            <TouchableOpacity
              onPress={() => setMessage(BODY_TEMPLATE)}
              style={styles.templateBtn}
              testID="pub-ticket-use-template"
            >
              <Feather name="file-text" size={12} color={colors.primary} />
              <Text style={styles.templateBtnText}>{"  "}Use example template</Text>
            </TouchableOpacity>
          </View>
          <TextInput
            style={[styles.input, styles.textarea]}
            placeholder={BODY_TEMPLATE}
            placeholderTextColor={colors.textMuted}
            value={message}
            onChangeText={setMessage}
            multiline
            textAlignVertical="top"
            testID="pub-ticket-message"
          />
          <Text style={styles.helper}>
            Tap "Use example template" to pre-fill the message and then update the
            placeholders with your details.
          </Text>
        </ScrollView>

        <View style={styles.footer}>
          <TouchableOpacity
            onPress={onSubmit}
            disabled={!canSubmit || submitting}
            style={[styles.submitBtn, (!canSubmit || submitting) && { opacity: 0.5 }]}
            testID="pub-ticket-submit"
          >
            {submitting ? (
              <ActivityIndicator color={colors.primaryFg} />
            ) : (
              <>
                <Feather name="send" size={16} color={colors.primaryFg} />
                <Text style={styles.submitBtnText}>{"  "}Submit ticket</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.screen,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: {
    width: 40, height: 40, borderRadius: 20,
    alignItems: "center", justifyContent: "center",
  },
  hintBox: {
    flexDirection: "row",
    gap: 8,
    alignItems: "flex-start",
    backgroundColor: colors.brand100,
    borderRadius: radii.card,
    padding: 12,
    marginBottom: 4,
  },
  hintText: { flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 18 },
  sectionLabel: {
    fontSize: 10,
    letterSpacing: 1.5,
    color: colors.textMuted,
    fontWeight: "800",
    marginTop: 18,
    marginBottom: 8,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.input,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 14,
    color: colors.textMain,
  },
  inputError: { borderColor: "#D93025" },
  errText: { color: "#D93025", fontSize: 11, marginTop: 4, fontWeight: "600" },
  textarea: { minHeight: 180, paddingTop: 14 },
  helper: { fontSize: 11, color: colors.textMuted, marginTop: 6, lineHeight: 16 },
  catGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  catChip: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  catChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  catChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  bodyHeaderRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  templateBtn: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 14,
    backgroundColor: colors.brand100,
  },
  templateBtnText: { fontSize: 11, fontWeight: "700", color: colors.primary },
  footer: {
    padding: spacing.screen,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.background,
  },
  submitBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.primary,
    borderRadius: radii.button,
    paddingVertical: 15,
  },
  submitBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  // Success state
  doneWrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.screen,
  },
  doneCircle: {
    width: 96, height: 96, borderRadius: 48,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
    marginBottom: 24,
  },
  doneTitle: { fontSize: 22, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  doneSub: {
    fontSize: 13,
    color: colors.textMuted,
    textAlign: "center",
    marginTop: 12,
    lineHeight: 20,
  },
  doneBtn: {
    marginTop: 36,
    paddingHorizontal: 36,
    paddingVertical: 13,
    borderRadius: radii.button,
    backgroundColor: colors.primary,
  },
  doneBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
});
