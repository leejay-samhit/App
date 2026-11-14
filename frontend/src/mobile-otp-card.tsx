/**
 * MobileOtpCard — verify a mobile number with a WhatsApp code (OTPly).
 *
 * Nov-2026. Replaces the Truecaller one-tap card and the invite-code field.
 * Two jobs, chosen by `mode`:
 *   • "gate"  — attach + verify a number on an account that signed in with
 *               Google or email (POST /auth/signup-gate/send-otp + /confirm)
 *   • "login" — sign in with the number itself (POST /auth/otp/send + /verify)
 *
 * The backend is the only thing that can call a number verified: this screen
 * just collects the number and the six digits.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError } from "./api";
import { colors, radii, spacing } from "./theme";

type Props = {
  mode: "gate" | "login";
  /** gate: called after the number is verified. login: receives the session. */
  onVerified: (payload: any) => void;
  /** Optional name field, shown on the login flow for brand-new numbers. */
  busyLabel?: string;
};

const RESEND_SECONDS = 60;

export function MobileOtpCard({ mode, onVerified }: Props) {
  const [step, setStep] = useState<"number" | "code">("number");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const startCooldown = useCallback((seconds: number) => {
    setCooldown(seconds);
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(() => {
      setCooldown((n) => {
        if (n <= 1 && timer.current) { clearInterval(timer.current); timer.current = null; }
        return Math.max(0, n - 1);
      });
    }, 1000);
  }, []);

  const digits = phone.replace(/\D+/g, "").slice(-10);
  const phoneValid = digits.length === 10 && /^[6-9]/.test(digits);

  const sendCode = useCallback(async () => {
    if (!phoneValid || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const path = mode === "gate" ? "/auth/signup-gate/send-otp" : "/auth/otp/send";
      const body = mode === "gate" ? { phone: digits } : { mobile: digits };
      const { data } = await api.post<any>(path, body);
      setStep("code");
      setNotice(`Code sent on WhatsApp to +91 ${digits}.`);
      startCooldown(Number(data?.resend_in || RESEND_SECONDS));
    } catch (e) {
      setError(formatApiError(e));
    } finally { setBusy(false); }
  }, [phoneValid, busy, mode, digits, startCooldown]);

  const verify = useCallback(async () => {
    if (code.replace(/\D+/g, "").length !== 6 || busy) return;
    setBusy(true); setError("");
    try {
      const path = mode === "gate" ? "/auth/signup-gate/confirm" : "/auth/otp/verify";
      const body = mode === "gate"
        ? { phone: digits, otp: code.replace(/\D+/g, "") }
        : { mobile: digits, otp: code.replace(/\D+/g, "") };
      const { data } = await api.post<any>(path, body);
      onVerified(data);
    } catch (e) {
      setError(formatApiError(e));
    } finally { setBusy(false); }
  }, [code, busy, mode, digits, onVerified]);

  return (
    <View style={styles.card} testID="mobile-otp-card">
      {step === "number" ? (
        <>
          <Text style={styles.title}>
            {mode === "gate" ? "Verify your mobile number" : "Sign in with your mobile"}
          </Text>
          <Text style={styles.sub}>
            We&apos;ll send a 6-digit code to your WhatsApp. No charges, no membership.
          </Text>
          <View style={styles.inputRow}>
            <Text style={styles.prefix}>+91</Text>
            <TextInput
              value={phone}
              onChangeText={(t) => { setPhone(t); setError(""); }}
              placeholder="10-digit mobile number"
              placeholderTextColor={colors.textMuted}
              keyboardType="number-pad"
              maxLength={14}
              style={styles.input}
              testID="otp-phone-input"
              returnKeyType="send"
              onSubmitEditing={sendCode}
            />
          </View>
          <TouchableOpacity
            onPress={sendCode}
            disabled={!phoneValid || busy}
            style={[styles.primaryBtn, (!phoneValid || busy) && styles.btnDisabled]}
            testID="otp-send-btn"
            activeOpacity={0.85}
          >
            {busy ? <ActivityIndicator size="small" color={colors.primaryFg} />
              : <Feather name="message-circle" size={17} color={colors.primaryFg} />}
            <Text style={styles.primaryBtnText}>{busy ? "Sending…" : "Send code on WhatsApp"}</Text>
          </TouchableOpacity>
        </>
      ) : (
        <>
          <Text style={styles.title}>Enter the code</Text>
          <Text style={styles.sub}>Sent on WhatsApp to +91 {digits}</Text>
          <TextInput
            value={code}
            onChangeText={(t) => { setCode(t.replace(/\D+/g, "").slice(0, 6)); setError(""); }}
            placeholder="● ● ● ● ● ●"
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
            maxLength={6}
            style={styles.codeInput}
            testID="otp-code-input"
            autoFocus
            returnKeyType="done"
            onSubmitEditing={verify}
          />
          <TouchableOpacity
            onPress={verify}
            disabled={code.length !== 6 || busy}
            style={[styles.primaryBtn, (code.length !== 6 || busy) && styles.btnDisabled]}
            testID="otp-verify-btn"
            activeOpacity={0.85}
          >
            {busy ? <ActivityIndicator size="small" color={colors.primaryFg} />
              : <Feather name="check" size={17} color={colors.primaryFg} />}
            <Text style={styles.primaryBtnText}>{busy ? "Verifying…" : "Verify & continue"}</Text>
          </TouchableOpacity>
          <View style={styles.footRow}>
            <TouchableOpacity
              onPress={() => { setStep("number"); setCode(""); setError(""); setNotice(""); }}
              style={styles.linkBtn}
              testID="otp-change-number"
            >
              <Text style={styles.linkText}>Change number</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={sendCode}
              disabled={cooldown > 0 || busy}
              style={styles.linkBtn}
              testID="otp-resend"
            >
              <Text style={[styles.linkText, cooldown > 0 && { color: colors.textMuted }]}>
                {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
              </Text>
            </TouchableOpacity>
          </View>
        </>
      )}

      {error ? (
        <View style={styles.errorBox} testID="otp-error">
          <Feather name="alert-circle" size={14} color={colors.error} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : notice ? (
        <Text style={styles.notice} testID="otp-notice">{notice}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radii.card, padding: spacing.screen,
    borderWidth: 1, borderColor: colors.border, gap: 12,
  },
  title: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  sub: { fontSize: 12.5, color: colors.textMuted, lineHeight: 18 },
  inputRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 12, minHeight: 50,
  },
  prefix: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  input: { flex: 1, fontSize: 15, color: colors.textMain, paddingVertical: 12 },
  codeInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 16, minHeight: 56,
    fontSize: 24, letterSpacing: 8, textAlign: "center",
    color: colors.textMain, fontWeight: "800",
  },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, borderRadius: radii.button, minHeight: 50,
  },
  btnDisabled: { opacity: 0.5 },
  primaryBtnText: { color: colors.primaryFg, fontSize: 14.5, fontWeight: "900" },
  footRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  linkBtn: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4 },
  linkText: { fontSize: 13, fontWeight: "800", color: colors.primary },
  errorBox: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: radii.button, padding: 10,
  },
  errorText: { flex: 1, fontSize: 12.5, color: colors.error, fontWeight: "700", lineHeight: 18 },
  notice: { fontSize: 12, color: colors.textMuted },
});
