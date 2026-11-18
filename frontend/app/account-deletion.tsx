/**
 * Account deletion request (Nov-2026).
 *
 * Reached from Profile → Support & Help. Submitting locks the account at once
 * and opens a support ticket an admin must review before the account is
 * removed. Payment, order and tax records are kept as the law requires.
 */
import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { ConfirmDialog } from "../src/confirm-dialog";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

type DeletionRequest = {
  id: string;
  status: string;
  created_at: string;
};

const CONSEQUENCES = [
  "You are signed out everywhere and cannot sign back in while the request is open.",
  "Your profile, addresses and saved items are removed once an admin approves.",
  "Any wallet balance must be withdrawn first — it is not refunded after deletion.",
  "Order, payment and tax records are kept for the period the law requires.",
  "Vendor, delivery partner and service listings are taken down.",
];

export default function AccountDeletionScreen() {
  const router = useRouter();
  const { user, logout, bootstrapped } = useAuth() as any;
  const [loading, setLoading] = useState(true);
  const [existing, setExisting] = useState<DeletionRequest | null>(null);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ request: DeletionRequest | null }>("/me/account-deletion");
      setExisting(data?.request ?? null);
    } catch {
      // non-fatal — the form still works
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => {
    // Wait for the cold-start session restore before deciding — a hard reload
    // on web starts with user = null even for a signed-in person.
    if (!bootstrapped) return;
    if (!user) { router.replace("/login"); return; }
    load();
  }, [bootstrapped, user, load, router]));

  const submit = async () => {
    if (!confirmed) {
      setError("Please tick the confirmation box first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.post("/me/account-deletion", { reason: reason.trim(), confirm: true });
      // Shown in-app rather than through Alert.alert, which does nothing on web.
      setSubmitted(true);
      setLocked(true);
      load();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={10} testID="deletion-back">
          <Feather name="arrow-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Delete my account</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        {loading ? (
          <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
        ) : locked || (existing && ["open", "in_progress"].includes(existing.status)) ? (
          <View style={styles.pendingCard}>
            <Feather name="clock" size={22} color={colors.warning} />
            <Text style={styles.pendingTitle}>Request under review</Text>
            <Text style={styles.pendingBody}>
              You asked for this account to be deleted{existing?.created_at ? ` on ${new Date(existing.created_at).toLocaleDateString()}` : ""}.
              The account is locked while our team reviews it. To cancel, email
              us from your registered address and quote the reference below.
            </Text>
            {existing?.id ? (
              <Text style={styles.refText} selectable testID="deletion-reference">
                Reference: {existing.id.slice(0, 8).toUpperCase()}
              </Text>
            ) : null}
            <TouchableOpacity
              onPress={async () => { await logout?.(); router.replace("/login"); }}
              style={styles.secondaryBtn}
              testID="deletion-signout"
            >
              <Text style={styles.secondaryBtnText}>Sign out</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <>
            <View style={styles.warnCard}>
              <Feather name="alert-triangle" size={20} color={colors.error} />
              <Text style={styles.warnText}>
                This cannot be undone once an admin approves it.
              </Text>
            </View>

            <Text style={styles.sectionTitle}>What happens next</Text>
            <View style={styles.listCard}>
              {CONSEQUENCES.map((line) => (
                <View key={line} style={styles.listRow}>
                  <Feather name="chevron-right" size={14} color={colors.textMuted} />
                  <Text style={styles.listText}>{line}</Text>
                </View>
              ))}
            </View>

            <Text style={styles.sectionTitle}>Why are you leaving? (optional)</Text>
            <TextInput
              value={reason}
              onChangeText={setReason}
              placeholder="Tell us what went wrong — it helps us improve"
              placeholderTextColor={colors.textMuted}
              multiline
              style={styles.reasonInput}
              testID="deletion-reason"
            />

            <TouchableOpacity
              onPress={() => { setConfirmed((v) => !v); setError(""); }}
              style={styles.confirmRow}
              activeOpacity={0.8}
              testID="deletion-confirm"
            >
              <View style={[styles.checkbox, confirmed && styles.checkboxOn]}>
                {confirmed ? <Feather name="check" size={14} color={colors.primaryFg} /> : null}
              </View>
              <Text style={styles.confirmText}>
                I understand my account will be locked now and deleted after review.
              </Text>
            </TouchableOpacity>

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <TouchableOpacity
              onPress={submit}
              disabled={busy}
              style={[styles.dangerBtn, busy && { opacity: 0.6 }]}
              testID="deletion-submit"
            >
              {busy ? <ActivityIndicator color="#FFFFFF" /> : (
                <Text style={styles.dangerBtnText}>Request account deletion</Text>
              )}
            </TouchableOpacity>

            <TouchableOpacity onPress={() => router.back()} style={styles.linkBtn}>
              <Text style={styles.linkText}>Keep my account</Text>
            </TouchableOpacity>
          </>
        )}
      </ScrollView>

      <ConfirmDialog
        visible={submitted}
        icon="check-circle"
        iconTint={colors.success}
        title="Request submitted"
        body="Your account is now locked and our team will review the request. Sign out when you are ready — you will not be able to sign back in until it is reviewed."
        confirmLabel="Sign out now"
        cancelLabel="Stay here"
        onConfirm={async () => { setSubmitted(false); await logout?.(); router.replace("/login"); }}
        onCancel={() => setSubmitted(false)}
        testID="deletion-submitted"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  container: { padding: spacing.screen, gap: 14, paddingBottom: 40 },
  warnCard: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radii.card, padding: 14,
    borderWidth: 1, borderColor: colors.error,
  },
  warnText: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.textMain },
  sectionTitle: {
    fontSize: 11, letterSpacing: 1.5, fontWeight: "800",
    color: colors.textMuted, marginTop: 6,
  },
  listCard: {
    backgroundColor: colors.surface, borderRadius: radii.card, padding: 14, gap: 10,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
  },
  listRow: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  listText: { flex: 1, fontSize: 13, color: colors.textMain, lineHeight: 19 },
  reasonInput: {
    backgroundColor: colors.surface, borderRadius: radii.input, padding: 14,
    minHeight: 96, textAlignVertical: "top", fontSize: 14, color: colors.textMain,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
  },
  confirmRow: { flexDirection: "row", gap: 10, alignItems: "flex-start", paddingVertical: 6 },
  checkbox: {
    width: 22, height: 22, borderRadius: 6, borderWidth: 1.5,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  checkboxOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  confirmText: { flex: 1, fontSize: 13, color: colors.textMain, lineHeight: 19 },
  error: { fontSize: 12, color: colors.error, fontWeight: "600" },
  dangerBtn: {
    backgroundColor: colors.error, borderRadius: radii.button, paddingVertical: 15,
    alignItems: "center", justifyContent: "center", minHeight: 48,
  },
  dangerBtnText: { color: "#FFFFFF", fontSize: 15, fontWeight: "800" },
  linkBtn: { alignItems: "center", paddingVertical: 12 },
  linkText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  pendingCard: {
    backgroundColor: colors.surface, borderRadius: radii.card, padding: 20, gap: 10,
    borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border, alignItems: "flex-start",
  },
  pendingTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  pendingBody: { fontSize: 13, color: colors.textMuted, lineHeight: 19 },
  secondaryBtn: {
    marginTop: 6, backgroundColor: colors.surfaceMuted, borderRadius: radii.button,
    paddingVertical: 12, paddingHorizontal: 18, minHeight: 44, justifyContent: "center",
  },
  secondaryBtnText: { color: colors.textMain, fontWeight: "700", fontSize: 13 },
  refText: {
    fontSize: 12, fontWeight: "800", color: colors.textMain,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 8, letterSpacing: 0.6,
  },
});
