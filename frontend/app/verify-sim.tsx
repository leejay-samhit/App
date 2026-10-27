// Verify SIM — the user-facing readiness screen (Oct 2026).
//
// Honest by design: it never says "number verified" off the back of a local
// SIM read. The two facts are shown as two separate rows, and the server's
// answer is the one displayed.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Linking, Platform, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { colors, spacing, radii } from "../src/theme";
import { getAuthToken } from "../src/api";
import { useSimVerification } from "../src/sim-verification";
import { useAuth } from "../src/auth";

const STATE_COPY: Record<string, { title: string; body: string; tone: "ok" | "warn" | "bad" }> = {
  SIM_PRESENT: {
    title: "SIM detected",
    body: "A SIM or eSIM is active in this phone.",
    tone: "ok",
  },
  SIM_ABSENT: {
    title: "No SIM in this phone",
    body: "Insert your SIM (or activate your eSIM) and check again. Shopping, payments and recharge keep working as normal.",
    tone: "bad",
  },
  SIM_STATE_UNKNOWN: {
    title: "SIM status unclear",
    body: "Android didn't give a clear answer — often a locked SIM or a profile that isn't activated yet. Try again in a moment.",
    tone: "warn",
  },
  PERMISSION_DENIED: {
    title: "Permission needed",
    body: "Slangcart needs permission to see whether a SIM is present. We never read your SIM number, IMEI or your messages.",
    tone: "warn",
  },
  DEVICE_UNSUPPORTED: {
    title: "This device can't report a SIM",
    body: "Tablets, Wi-Fi-only devices and the website have no SIM to check. Link your verified phone instead to use chat here.",
    tone: "warn",
  },
  REVALIDATION_REQUIRED: {
    title: "Re-check needed",
    body: "Your SIM setup changed, so we need to look again.",
    tone: "warn",
  },
};

export default function VerifySimScreen() {
  const router = useRouter();
  const { status, loading, refresh, runCheck, nativeAvailable } = useSimVerification();
  const { user } = useAuth();
  // Auth hydrates from storage a tick after mount, so `user` is briefly null
  // even for a signed-in user. Knowing whether a token EXISTS stops the
  // screen flashing "Sign in to verify" at someone who is already signed in.
  const [hasToken, setHasToken] = useState<boolean | null>(null);
  useEffect(() => {
    getAuthToken().then((t) => setHasToken(!!t)).catch(() => setHasToken(false));
  }, [user?.id]);
  const [msg, setMsg] = useState<string>("");
  const [needsSettings, setNeedsSettings] = useState(false);
  const [busy, setBusy] = useState(false);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh]),
  );

  const onVerify = async () => {
    setBusy(true);
    setMsg("");
    const res = await runCheck({ askPermission: true });
    setNeedsSettings(!!res.needsSettings);
    if (res.ok) {
      setMsg("");
    } else if (res.error === "permission_denied") {
      setMsg(
        res.needsSettings
          ? "Permission is switched off for good. Turn on “Phone” for Slangcart in Settings, then come back."
          : "Without this permission we can't open chat. Everything else in the app still works.",
      );
    } else if (res.error === "web_unsupported") {
      setMsg("A browser can't check a SIM — link your phone instead.");
    } else if (res.error) {
      setMsg(res.error);
    }
    setBusy(false);
  };

  const state = status?.sim_state || "SIM_STATE_UNKNOWN";
  const onWeb = Platform.OS === "web";
  const copy = hasToken === false
    ? {
        title: "Sign in to verify",
        body: "Sign in to your Slangcart account, then this screen can check your SIM.",
        tone: "warn" as const,
      }
    : !status
      ? {
          title: "Checking…",
          body: "Fetching your current verification status.",
          tone: "warn" as const,
        }
      : onWeb
        ? state === "SIM_PRESENT"
          ? {
              title: "Verified on your phone",
              body:
                "Your Slangcart app reported an active SIM. This browser has none of its own, " +
                "so link it to your phone to chat here.",
              tone: "ok" as const,
            }
          : STATE_COPY.DEVICE_UNSUPPORTED
        : STATE_COPY[state] || STATE_COPY.SIM_STATE_UNKNOWN;
  const toneColor = copy.tone === "ok" ? colors.success : copy.tone === "bad" ? colors.error : colors.warning;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <Stack.Screen options={{ title: "Verify SIM", headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} hitSlop={12} testID="verify-sim-back">
          <Feather name="arrow-left" size={22} color={colors.primaryFg} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Chat verification</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} tintColor={colors.primary} />}
      >
        {/* Fact 1 — SIM presence */}
        <View style={styles.card}>
          <View style={styles.rowTop}>
            <Feather
              name={copy.tone === "ok" ? "check-circle" : copy.tone === "bad" ? "x-circle" : "alert-circle"}
              size={20}
              color={toneColor}
            />
            <Text style={[styles.cardTitle, { color: toneColor }]} testID="verify-sim-state-title">{copy.title}</Text>
          </View>
          <Text style={styles.cardBody}>{copy.body}</Text>
          {state === "SIM_PRESENT" && !onWeb && (
            <Text style={styles.meta}>
              {status?.slot_count || 1} active {status?.slot_count === 1 ? "SIM" : "SIMs"}
              {status?.has_esim ? " · includes eSIM" : ""}
            </Text>
          )}
          {state === "SIM_PRESENT" && onWeb && (
            <Text style={styles.meta}>Reported by your Slangcart app, not by this browser.</Text>
          )}
        </View>

        {/* Fact 2 — number ownership, kept strictly separate */}
        <View style={styles.card}>
          <View style={styles.rowTop}>
            <Feather
              name={status?.number_verified ? "check-circle" : "info"}
              size={20}
              color={status?.number_verified ? colors.success : colors.textMuted}
            />
            <Text style={styles.cardTitle} testID="verify-sim-number-title">
              {status?.number_verified ? "Number confirmed" : "Number not confirmed"}
            </Text>
          </View>
          <Text style={styles.cardBody}>
            {status?.number_verified
              ? `Your mobile number ending ${status?.phone_last4 || "••••"} was confirmed by ${status?.number_proof_method || "the verifier"}.`
              : status?.number_proof_available
                ? "Confirm that this number is yours with one tap — no SMS code needed."
                : "A SIM check alone can't prove the number belongs to you. One-tap number confirmation isn't switched on for this app yet."}
          </Text>
        </View>

        {!!msg && (
          <View style={styles.msgBox}>
            <Text style={styles.msgText}>{msg}</Text>
          </View>
        )}

        {needsSettings && (
          <TouchableOpacity style={styles.secondaryBtn} onPress={() => Linking.openSettings().catch(() => {})} testID="verify-sim-open-settings">
            <Feather name="settings" size={16} color={colors.primary} />
            <Text style={styles.secondaryText}>Open app settings</Text>
          </TouchableOpacity>
        )}

        {nativeAvailable ? (
          <TouchableOpacity style={styles.primaryBtn} onPress={onVerify} disabled={busy} testID="verify-sim-check-button">
            {busy ? (
              <ActivityIndicator color={colors.primaryFg} />
            ) : (
              <Text style={styles.primaryText}>
                {status?.meets_requirement ? "Check again" : "Check my SIM"}
              </Text>
            )}
          </TouchableOpacity>
        ) : (
          <View style={styles.infoBox}>
            <Text style={styles.infoText}>
              {Platform.OS === "web"
                ? "You're on the website, which has no SIM to read."
                : "This build cannot read SIM status — install the Slangcart app from your Android build."}
              {" "}Link a verified phone to carry on chatting here.
            </Text>
          </View>
        )}

        <TouchableOpacity style={styles.secondaryBtn} onPress={() => router.push("/link-device")} testID="verify-sim-link-device-button">
          <Feather name="smartphone" size={16} color={colors.primary} />
          <Text style={styles.secondaryText}>Link a verified phone</Text>
        </TouchableOpacity>

        <Text style={styles.disclaimer} testID="verify-sim-disclaimer">
          {status?.disclaimer ||
            "A local SIM check only shows that a SIM is present in the phone. It is not proof that the number belongs to this account."}
        </Text>
        <Text style={styles.privacy}>
          Slangcart reads only whether a SIM is present, how many are active and your carrier&apos;s public network
          code.
          It never reads your SIM number, IMEI, ICCID or SMS, and never sends an SMS.
        </Text>
        <Text style={styles.privacy}>
          Shopping, cart, checkout, payments, wallet, cashback, recharge and seller tools are never blocked by this
          check — it applies to chat only.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    backgroundColor: colors.primary,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.screen,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  backBtn: { width: 44, height: 44, alignItems: "flex-start", justifyContent: "center" },
  headerTitle: { color: colors.primaryFg, fontSize: 18, fontWeight: "700" },
  body: { padding: spacing.screen, gap: spacing.md, paddingBottom: spacing.xl },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  rowTop: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  cardTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, flexShrink: 1 },
  cardBody: { fontSize: 14, color: colors.textMain, lineHeight: 20 },
  meta: { fontSize: 13, color: colors.textMuted },
  msgBox: {
    backgroundColor: colors.surfaceMuted,
    borderRadius: radii.input,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  msgText: { color: colors.textMain, fontSize: 14, lineHeight: 20 },
  infoBox: { backgroundColor: colors.brand100, borderRadius: radii.input, padding: spacing.md },
  infoText: { color: colors.textMain, fontSize: 14, lineHeight: 20 },
  primaryBtn: {
    backgroundColor: colors.primary,
    borderRadius: radii.button,
    minHeight: 48,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: { color: colors.primaryFg, fontSize: 16, fontWeight: "700" },
  secondaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    minHeight: 48,
    borderRadius: radii.button,
    borderWidth: 1,
    borderColor: colors.primary,
  },
  secondaryText: { color: colors.primary, fontSize: 15, fontWeight: "600" },
  disclaimer: { fontSize: 13, color: colors.textMuted, lineHeight: 19, marginTop: spacing.sm },
  privacy: { fontSize: 12, color: colors.textMuted, lineHeight: 18 },
});
