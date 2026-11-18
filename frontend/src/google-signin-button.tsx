/**
 * "Continue with Google" button — Emergent-managed Google sign-in.
 *
 * Drop it on the login / register screens. Everything platform-specific
 * lives in src/google-auth.ts; the exchange itself lives on our backend.
 *
 * On web the tap navigates away, so the session id is picked up on the next
 * mount by GoogleRedirectHandler. On native we get the id back here and
 * finish the sign-in immediately.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Platform } from "react-native";
import Svg, { Path } from "react-native-svg";
import { useAuth } from "./auth";
import { formatApiError } from "./api";
import { colors, radii } from "./theme";
import {
  isConsumed, markConsumed, setPendingReferral, startGoogleSignIn,
} from "./google-auth";
import { routeAfterAuth } from "./post-auth-route";

/** Google's official four-colour "G". Brand marks must not be themed. */
function GoogleG({ size = 18 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48">
      <Path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <Path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <Path fill="#FBBC05" d="M10.53 28.59A14.5 14.5 0 0 1 9.77 24c0-1.6.27-3.15.76-4.59l-7.98-6.19A23.94 23.94 0 0 0 0 24c0 3.88.93 7.54 2.56 10.78l7.97-6.19z" />
      <Path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.46-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </Svg>
  );
}

type Props = {
  /** Invite code to attribute a brand-new Google signup to. */
  referralCode?: string;
  /** Surface the error inline instead of relying on the caller. */
  onError?: (message: string) => void;
  label?: string;
  /** Show the "OR" rule above the button (legacy single-option layouts). */
  showDivider?: boolean;
};

export function GoogleSignInButton({ referralCode, onError, label, showDivider = false }: Props) {
  const { loginWithGoogle } = useAuth();
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState("");

  const fail = (message: string) => {
    if (onError) onError(message);
    else setLocalError(message);
  };

  const onPress = async () => {
    setLocalError("");
    setBusy(true);
    try {
      // Survives the full-page redirect on web, where state is lost.
      await setPendingReferral(referralCode);
      const sessionId = await startGoogleSignIn();
      if (!sessionId) {
        // Web: we have navigated away. Native: the user really cancelled.
        if (Platform.OS !== "web") setBusy(false);
        return;
      }
      if (isConsumed(sessionId)) { setBusy(false); return; }
      markConsumed(sessionId);
      const u = await loginWithGoogle(sessionId, referralCode?.trim() || undefined);
      routeAfterAuth(u);
    } catch (e) {
      fail(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View>
      {showDivider ? (
        <View style={styles.dividerRow}>
          <View style={styles.dividerLine} />
          <Text style={styles.dividerText}>OR</Text>
          <View style={styles.dividerLine} />
        </View>
      ) : null}
      <TouchableOpacity
        onPress={onPress}
        disabled={busy}
        activeOpacity={0.85}
        style={[styles.btn, busy && { opacity: 0.6 }]}
        testID="google-signin-button"
        accessibilityRole="button"
        accessibilityLabel="Continue with Google"
      >
        {busy ? (
          <ActivityIndicator size="small" color={colors.textMain} />
        ) : (
          <>
            <GoogleG />
            <Text style={styles.btnText}>{label || "Continue with Google"}</Text>
          </>
        )}
      </TouchableOpacity>
      {localError ? <Text style={styles.error}>{localError}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  dividerRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 18, marginBottom: 14 },
  dividerLine: { flex: 1, height: 1, backgroundColor: colors.border },
  dividerText: { fontSize: 11, fontWeight: "800", letterSpacing: 1.2, color: colors.textMuted },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    minHeight: 54, paddingVertical: 14, paddingHorizontal: 16,
    borderRadius: radii.button ?? 12,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  btnText: { fontSize: 15, fontWeight: "700", color: colors.textMain, letterSpacing: -0.2 },
  error: { marginTop: 8, fontSize: 12, color: "#B3261E", textAlign: "center" },
});
