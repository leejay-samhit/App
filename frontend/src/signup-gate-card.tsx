/**
 * SignupGateCard — mandatory mobile number + optional invite code.
 *
 * Oct-2026 owner rule: BOTH payment options ("Pay ₹118" and "Continue
 * without subscription") stay locked until this passes, so no account can
 * exist without a verified mobile number and a sponsor.
 *
 * Invite code is optional — blank or unknown silently falls back to the
 * official Slangcart code (EARN), which the backend resolves.
 *
 * If the mobile already belongs to someone else we never merge or
 * overwrite: we show that account's name + masked email and tell the user to
 * sign in with that same email, use a different mobile AND email, or raise a
 * support ticket. A phone number is the one field two real people collide on
 * most often, so guessing would hand one person another's account.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError } from "./api";
import {
  isTruecallerModuleAvailable,
  isTruecallerUsable,
  requestTruecallerCode,
} from "../modules/truecaller";
import { useAuth } from "./auth";
import { colors, radii } from "./theme";

type Conflict = {
  reason: string;
  name: string;
  email: string;
  email_masked: string;
  message: string;
};

type Props = {
  /** Called once the gate passes so the host screen can unlock its buttons. */
  onPassed: () => void;
};

export function SignupGateCard({ onPassed }: Props) {
  const { user, refresh } = useAuth();
  const router = useRouter();

  const [required, setRequired] = useState<boolean | null>(null);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState<Conflict | null>(null);
  // Truecaller one-tap — only offered when the module is in this build AND
  // the backend says a client ID is configured AND the SDK reports itself
  // usable on this handset. Any "no" simply shows the manual form instead.
  const [tcAvailable, setTcAvailable] = useState(false);
  const [tcBusy, setTcBusy] = useState(false);
  const [method, setMethod] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/signup-gate/status");
      setRequired(!!data.required);
      if (data.phone) setPhone(String(data.phone));
      if (data.referral_code_used) setCode(String(data.referral_code_used));
      setMethod(data.phone_verified ? String(data.phone_verified_method || "") : "");
      if (!data.required) onPassed();
    } catch {
      // A failed status read must NOT unlock the screen: the confirm call is
      // the real gate, and leaving it open would let both options through on
      // a flaky connection.
      setRequired(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  // Decide once whether the Truecaller button can be shown at all.
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!isTruecallerModuleAvailable()) return;
      try {
        const { data } = await api.get("/auth/truecaller/availability");
        if (!data?.configured) return;
        const usable = await isTruecallerUsable();
        if (alive) setTcAvailable(usable);
      } catch {
        /* leave the manual form as the only option */
      }
    })();
    return () => { alive = false; };
  }, []);

  const onTruecaller = async () => {
    setError("");
    setNotice("");
    setConflict(null);
    setTcBusy(true);
    try {
      // The SERVER mints the state + PKCE challenge and keeps the verifier,
      // so a tapped button alone can never produce a verified number.
      const { data: started } = await api.post("/auth/truecaller/start", { purpose: "registration" });
      const res = await requestTruecallerCode(started.state, started.code_challenge);
      const { data } = await api.post("/auth/truecaller/verify", {
        state: started.state,
        authorization_code: res.authorizationCode,
        referral_code: code.trim() || undefined,
      });
      setPhone(String(data.phone || ""));
      setCode(data.invite_code || code);
      setMethod("truecaller");
      setNotice("Mobile number verified with Truecaller.");
      await refresh();
      setRequired(false);
      onPassed();
    } catch (e: any) {
      const reason = String(e?.message || "");
      if (reason === "unavailable" || reason === "oauth_unavailable") {
        setTcAvailable(false);
        setError("Truecaller isn't available on this phone. Please enter your number below.");
      } else if (reason === "verification_required" || reason === "state_mismatch") {
        setError("That didn't complete. Please enter your number below instead.");
      } else if (reason === "timeout" || reason === "already_in_progress") {
        setError("Verification timed out. Tap the button again, or enter your number below.");
      } else if (e?.response) {
        // A real server answer (duplicate number, expired attempt, etc.)
        setError(formatApiError(e));
      } else {
        setError("Truecaller was cancelled or unavailable. You can enter your number below.");
      }
    } finally {
      setTcBusy(false);
    }
  };

  const onConfirm = async () => {
    setError("");
    setNotice("");
    setConflict(null);
    const digits = phone.replace(/\D+/g, "").slice(-10);
    if (digits.length !== 10) {
      setError("Please enter your 10-digit mobile number.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/auth/signup-gate/check", {
        phone: digits,
        referral_code: code.trim() || undefined,
      });
      if (!data.ok) {
        setConflict(data.conflict);
        return;
      }
      const confirmed = await api.post("/auth/signup-gate/confirm", {
        phone: digits,
        referral_code: code.trim() || undefined,
      });
      setNotice(data.notice || "");
      setCode(confirmed.data.invite_code || code);
      await refresh();
      setRequired(false);
      onPassed();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  if (required === null) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  // Already confirmed — show a compact "all set" strip, not the whole form.
  if (!required) {
    return (
      <View style={styles.doneCard} testID="signup-gate-done">
        <View style={styles.doneIcon}>
          <Feather name="check" size={14} color={colors.primaryFg} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.doneTitle}>
            {method === "truecaller" ? "Mobile verified" : "Mobile number saved"}
          </Text>
          <Text style={styles.doneSub}>
            {phone ? `+91 ${phone}` : "Saved"}
            {method === "truecaller" ? " · verified with Truecaller" : ""}
            {code ? ` · invited by ${code}` : ""}
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.card} testID="signup-gate-card">
      <View style={styles.badge}>
        <Feather name="lock" size={11} color={colors.accentFg} />
        <Text style={styles.badgeText}>STEP 1 · VERIFY YOUR MOBILE NUMBER</Text>
      </View>

      <Text style={styles.title}>Verify your mobile number</Text>
      <Text style={styles.sub}>
        {tcAvailable
          ? "One tap with Truecaller confirms the number is really yours — no SMS code to wait for. "
          : "We need a mobile number on your account before you choose how to continue. "}
        Your invite code is optional: leave it blank and you&apos;ll join under the official
        Slangcart code.
      </Text>

      {tcAvailable && (
        <>
          <TouchableOpacity
            onPress={onTruecaller}
            disabled={tcBusy || busy}
            style={[styles.tcBtn, (tcBusy || busy) && { opacity: 0.6 }]}
            testID="gate-truecaller-button"
          >
            {tcBusy ? (
              <ActivityIndicator color={colors.primaryFg} size="small" />
            ) : (
              <>
                <Feather name="shield" size={16} color={colors.primaryFg} />
                <Text style={styles.tcBtnText}>Verify with Truecaller</Text>
              </>
            )}
          </TouchableOpacity>
          <Text style={styles.tcHint}>
            Needs the Truecaller app on this phone. You&apos;ll see Truecaller&apos;s own consent
            screen — we never see your Truecaller password.
          </Text>
          <View style={styles.orRow}>
            <View style={styles.orLine} />
            <Text style={styles.orText}>OR ENTER IT MANUALLY</Text>
            <View style={styles.orLine} />
          </View>
        </>
      )}

      <Text style={styles.label}>
        MOBILE NUMBER <Text style={styles.req}>· required</Text>
      </Text>
      <View style={styles.phoneRow}>
        <View style={styles.cc}><Text style={styles.ccText}>+91</Text></View>
        <TextInput
          value={phone}
          onChangeText={(v) => { setPhone(v.replace(/\D+/g, "").slice(0, 10)); setConflict(null); }}
          placeholder="9876543210"
          placeholderTextColor={colors.textMuted}
          keyboardType="number-pad"
          maxLength={10}
          returnKeyType="next"
          style={styles.phoneInput}
          testID="gate-phone-input"
        />
        {phone.replace(/\D+/g, "").length === 10 ? (
          <Feather name="check-circle" size={18} color={colors.success} />
        ) : null}
      </View>

      <Text style={styles.label}>
        INVITE CODE <Text style={styles.opt}>· optional</Text>
      </Text>
      <TextInput
        value={code}
        onChangeText={(v) => setCode(v.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 16))}
        placeholder="Leave blank if you don't have one"
        placeholderTextColor={colors.textMuted}
        autoCapitalize="characters"
        style={styles.input}
        testID="gate-code-input"
      />

      {conflict ? (
        <View style={styles.conflictBox} testID="gate-conflict">
          <View style={styles.conflictHead}>
            <Feather name="alert-triangle" size={15} color={colors.warning} />
            <Text style={styles.conflictTitle}>This mobile is already registered</Text>
          </View>
          <View style={styles.conflictWho}>
            <Text style={styles.conflictName}>{conflict.name}</Text>
            <Text style={styles.conflictEmail}>{conflict.email_masked}</Text>
          </View>
          <Text style={styles.conflictBody}>
            Please sign in by tapping <Text style={styles.strong}>Continue</Text> with
            that same email id — or use a different mobile number and a different
            email id.
          </Text>
          <View style={styles.conflictActions}>
            <TouchableOpacity
              onPress={() => router.replace("/login")}
              style={styles.conflictPrimary}
              testID="gate-conflict-signin"
            >
              <Feather name="log-in" size={14} color={colors.primaryFg} />
              <Text style={styles.conflictPrimaryText}>Sign in with that email</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => router.push("/ticket-new" as any)}
              style={styles.conflictGhost}
              testID="gate-conflict-contact"
            >
              <Feather name="life-buoy" size={14} color={colors.primary} />
              <Text style={styles.conflictGhostText}>Contact</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      <TouchableOpacity
        onPress={onConfirm}
        disabled={busy}
        style={[styles.cta, busy && { opacity: 0.6 }]}
        testID="gate-confirm"
      >
        {busy ? (
          <ActivityIndicator color={colors.primaryFg} />
        ) : (
          <>
            <Feather name="unlock" size={16} color={colors.primaryFg} />
            <Text style={styles.ctaText}>Confirm &amp; continue</Text>
          </>
        )}
      </TouchableOpacity>

      <Text style={styles.foot}>
        {user?.email ? `Signed in as ${user.email}` : ""}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  loading: { paddingVertical: 28, alignItems: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.primary,
    padding: 18, marginBottom: 16,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 10, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 2 },
      default: {},
    }),
  },
  badge: {
    alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.accent, paddingHorizontal: 9, paddingVertical: 4,
    borderRadius: 999, marginBottom: 10,
  },
  badgeText: { fontSize: 9, fontWeight: "900", letterSpacing: 1.1, color: colors.accentFg },
  title: { fontSize: 19, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4, marginBottom: 6 },
  sub: { fontSize: 12.5, lineHeight: 19, color: colors.textMuted, marginBottom: 16 },
  label: { fontSize: 10, fontWeight: "900", letterSpacing: 1, color: colors.textMuted, marginBottom: 7 },
  req: { color: colors.error, letterSpacing: 0 },
  opt: { color: colors.textMuted, fontWeight: "700", letterSpacing: 0 },
  phoneRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 12,
    minHeight: 50, marginBottom: 16,
  },
  cc: { paddingRight: 10, borderRightWidth: 1, borderRightColor: colors.border },
  ccText: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  phoneInput: {
    flex: 1, fontSize: 16, fontWeight: "700", color: colors.textMain,
    paddingVertical: 12, letterSpacing: 1,
    ...Platform.select({ web: { outlineStyle: "none" } as any, default: {} }),
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 14,
    minHeight: 50, fontSize: 15, fontWeight: "700", color: colors.textMain,
    letterSpacing: 1, marginBottom: 14,
    ...Platform.select({ web: { outlineStyle: "none" } as any, default: {} }),
  },
  conflictBox: {
    backgroundColor: colors.surfaceMuted, borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.warning,
    padding: 14, marginBottom: 14,
  },
  conflictHead: { flexDirection: "row", alignItems: "center", gap: 7, marginBottom: 10 },
  conflictTitle: { flex: 1, fontSize: 13, fontWeight: "900", color: colors.textMain },
  conflictWho: {
    backgroundColor: colors.surface, borderRadius: 10, padding: 11, marginBottom: 10,
    borderWidth: 1, borderColor: colors.border,
  },
  conflictName: { fontSize: 14, fontWeight: "900", color: colors.textMain },
  conflictEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  conflictBody: { fontSize: 12, lineHeight: 18, color: colors.textMuted, marginBottom: 12 },
  strong: { fontWeight: "900", color: colors.textMain },
  conflictActions: { flexDirection: "row", gap: 8 },
  conflictPrimary: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, backgroundColor: colors.primary, minHeight: 44, borderRadius: 11,
  },
  conflictPrimaryText: { color: colors.primaryFg, fontWeight: "900", fontSize: 12.5 },
  conflictGhost: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingHorizontal: 16, minHeight: 44, borderRadius: 11,
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.surface,
  },
  conflictGhostText: { color: colors.primary, fontWeight: "900", fontSize: 12.5 },
  error: { fontSize: 12.5, color: colors.error, marginBottom: 10, fontWeight: "700" },
  notice: { fontSize: 12, color: colors.primary, marginBottom: 10, fontWeight: "700" },
  cta: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, minHeight: 52, borderRadius: 14,
  },
  ctaText: { color: colors.primaryFg, fontWeight: "900", fontSize: 15 },
  foot: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 10 },
  doneCard: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.brand100, borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.primary,
    padding: 12, marginBottom: 14,
  },
  doneIcon: {
    width: 24, height: 24, borderRadius: 12, backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  doneTitle: { fontSize: 13, fontWeight: "900", color: colors.textMain },
  doneSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 1 },
  tcBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    minHeight: 48,
    borderRadius: radii.button,
    backgroundColor: colors.primary,
    marginTop: 4,
  },
  tcBtnText: { color: colors.primaryFg, fontSize: 15, fontWeight: "800" },
  tcHint: { fontSize: 11.5, color: colors.textMuted, lineHeight: 17, marginTop: 6 },
  orRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 14, marginBottom: 4 },
  orLine: { flex: 1, height: 1, backgroundColor: colors.border },
  orText: { fontSize: 10, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.6 },
});
