import React, { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, setAuthToken, setSessionTokens, onSessionInvalidated, getAuthToken, getRefreshToken } from "./api";
import { runAndCacheIntegrity, IntegrityVerdict } from "./tamper-detection";
import {
  authenticateAndGetTokens,
  disableBiometricLogin,
  enableBiometricLogin,
  getBiometricCapability,
  isBiometricLoginReady,
  syncBiometricTokens,
} from "./biometric";

export type User = {
  id: string;
  name: string;
  email: string;
  role: "user" | "admin";
  referral_code: string;
  referred_by: string | null;
  wallet_balance: number;
  total_earned: number;
  registration_paid: boolean;
  direct_referrals_count: number;
  payouts_received: number;
  upi_id: string | null;
  bank_account: string | null;
  ifsc: string | null;
  account_holder: string | null;
  phone?: string | null;
};

type AuthState = {
  user: User | null | undefined; // undefined = checking, null = not auth
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (data: { name: string; email: string; password: string; phone?: string; referral_code?: string }) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setSession: (token: string, user: User, refreshToken?: string | null) => Promise<void>;
  /**
   * Reason for the most recent involuntary sign-out. Drives the "Signed in
   * elsewhere — please log in again" banner shown on the login screen.
   * Reset by calling clearSessionEnd() after the banner is dismissed or
   * the next successful login.
   */
  sessionEndReason: "session_revoked" | "refresh_failed" | null;
  clearSessionEnd: () => void;
  /** Phase 3 — Latest device-integrity verdict from the backend.
   *  null = haven't checked yet (still loading), or check failed silently
   *  (network blip — we never block the user on transport errors). */
  integrity: IntegrityVerdict | null;
  /** Force a re-run of the integrity checks (e.g. after a fresh login or
   *  on a payment screen entrance). */
  recheckIntegrity: () => Promise<IntegrityVerdict | null>;

  // ── Biometric (fingerprint / Face ID) login ──────────────────────────
  /** Whether the device supports biometrics AND the user has enrolled one. */
  biometricAvailable: boolean;
  /** Whether the user has previously opted-in on this device, has a cached
   *  token, and can therefore tap "Login with fingerprint". */
  biometricReady: boolean;
  /** Masked email associated with the cached biometric token. Shown on the
   *  login screen so the user knows whose session will be unlocked. */
  biometricEmailHint: string | null;
  /** Run the OS biometric prompt and, on success, restore the cached
   *  session. Returns the User on success or throws Error("…") on failure. */
  loginWithBiometric: () => Promise<User>;
  /** Opt in: stash the current token securely + flip the enabled flag. */
  enableBiometric: () => Promise<void>;
  /** Opt out: wipe stored tokens + disable. */
  disableBiometric: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [sessionEndReason, setSessionEndReason] = useState<AuthState["sessionEndReason"]>(null);
  const [integrity, setIntegrity] = useState<IntegrityVerdict | null>(null);
  // ── Biometric state ────────────────────────────────────────────────
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const [biometricReady, setBiometricReady] = useState(false);
  const [biometricEmailHint, setBiometricEmailHint] = useState<string | null>(null);

  // Re-evaluate biometric readiness — called on mount and after enable/disable.
  const refreshBiometricStatus = async () => {
    try {
      const cap = await getBiometricCapability();
      setBiometricAvailable(cap.available);
      const r = await isBiometricLoginReady();
      setBiometricReady(r.ready);
      setBiometricEmailHint(r.emailHint);
    } catch {
      setBiometricAvailable(false);
      setBiometricReady(false);
      setBiometricEmailHint(null);
    }
  };

  useEffect(() => {
    refreshBiometricStatus();
  }, []);

  // Phase 3 — run the integrity battery + POST verdict to the backend.
  // Always backgrounded (never blocks UI) and tolerant of failures —
  // anti-tampering must never lock people out on a flaky network.
  const recheckIntegrity = async () => {
    const v = await runAndCacheIntegrity();
    setIntegrity(v);
    return v;
  };

  const refresh = async () => {
    try {
      const { data } = await api.get<User>("/auth/me");
      setUser(data);
    } catch {
      setUser(null);
      await setSessionTokens(null, null);
    }
  };

  useEffect(() => {
    (async () => {
      const token = await AsyncStorage.getItem("auth_token");
      if (!token) {
        setUser(null);
        return;
      }
      // 2026-06-10 — When biometric is enabled, every cold app launch must
      // gate behind the fingerprint screen instead of silently restoring
      // the previous session. We leave `user = null` so the navigator
      // routes to /login, where the auto-prompt fires the fingerprint
      // sheet. After a successful scan, `loginWithBiometric()` re-hydrates
      // the user from the cached tokens (already in SecureStore).
      //
      // Without this, the user could close + reopen the app and land
      // straight on the dashboard — bypassing the biometric gate the
      // user explicitly asked us to add. We probe AsyncStorage directly
      // here because the biometric state hook hasn't run yet at this
      // point in the boot sequence.
      const bioEnabled = (await AsyncStorage.getItem("biometric_enabled_v1")) === "1";
      if (bioEnabled) {
        setUser(null);
        return;
      }
      await refresh();
      // Phase 3 — restored session → re-run integrity check so the
      // server's stamp on this user reflects the CURRENT device, not the
      // last one they signed in from.
      recheckIntegrity().catch(() => {});
    })();
  }, []);

  // Subscribe to involuntary sign-out events broadcast by the api layer.
  // The interceptor wipes tokens itself; here we just flip state so the UI
  // re-renders to /login and shows the "session ended" banner.
  useEffect(() => {
    const unsubscribe = onSessionInvalidated((reason) => {
      setUser(null);
      setSessionEndReason(reason);
    });
    return unsubscribe;
  }, []);

  const _persistLogin = async (data: any) => {
    // Backend returns { token, refresh_token, user }. Older responses (legacy
    // OAuth flow) may omit refresh_token — still works, that token will fall
    // back to the 401-token_expired path which gracefully logs the user out.
    await setSessionTokens(data.token ?? null, data.refresh_token ?? null);
    setUser(data.user);
    setSessionEndReason(null);
    // Phase 3 — every fresh login triggers an integrity check so the
    // backend stamp on this user is up-to-date before they touch any
    // financial action. Fire-and-forget; we don't block the UI.
    recheckIntegrity().catch(() => {});
    // Refresh biometric cache so the cached token doesn't go stale.
    // Also pass the user's email so the email hint shown on the login
    // screen always reflects whose session is actually cached (important
    // when a different user logs in on a phone where biometric was
    // previously enabled — the hint must follow the cached session).
    syncBiometricTokens(data.token ?? null, data.refresh_token ?? null, data.user?.email ?? null)
      .then(refreshBiometricStatus)
      .catch(() => {});
  };

  // ── Biometric methods ────────────────────────────────────────────
  const loginWithBiometric = async (): Promise<User> => {
    const r = await authenticateAndGetTokens();
    if (!r.ok) throw new Error(r.reason);
    await setSessionTokens(r.token, r.refreshToken);
    try {
      const { data } = await api.get<User>("/auth/me");
      setUser(data);
      setSessionEndReason(null);
      recheckIntegrity().catch(() => {});
      return data;
    } catch (e: any) {
      // Cached token is bad — wipe biometric so user can re-enroll on next
      // password login. Surface a friendly error.
      await disableBiometricLogin();
      await refreshBiometricStatus();
      await setSessionTokens(null, null);
      throw new Error("Your saved session has expired. Please login with password once.");
    }
  };

  const enableBiometric = async (): Promise<void> => {
    // Read CURRENT tokens via the canonical helpers (not by guessing keys).
    // Previously this read `refresh_token` directly which is the wrong key
    // (real key is `auth_refresh_token`), so refresh tokens never got cached
    // and biometric sessions died on the first refresh. Fixed 2026-06-07.
    const token = await getAuthToken();
    const refresh = await getRefreshToken();
    if (!token) throw new Error("Please login with password first.");
    if (!user?.email) throw new Error("Could not read your email — please re-login.");
    // Verify the user can actually pass their device biometric BEFORE we
    // mark it as enabled. This avoids enabling the feature on a device
    // where the user can't actually unlock it (e.g. enrolled fingerprints
    // were removed in OS settings since the device was provisioned). The
    // OS sheet shown here also serves as an explicit consent moment.
    const cap = await getBiometricCapability();
    if (!cap.available) {
      throw new Error(
        !cap.hasHardware
          ? "Your device doesn't support biometrics."
          : "Please enrol a fingerprint or face in your phone's settings first.",
      );
    }
    const LocalAuth = await import("expo-local-authentication");
    const proof = await LocalAuth.authenticateAsync({
      promptMessage: "Confirm fingerprint to enable quick login",
      cancelLabel: "Cancel",
      fallbackLabel: "",
      disableDeviceFallback: true,
    });
    if (!proof.success) {
      throw new Error("Fingerprint not confirmed. Try again.");
    }
    await enableBiometricLogin({ token, refreshToken: refresh, email: user.email });
    await refreshBiometricStatus();
  };

  const disableBiometric = async (): Promise<void> => {
    await disableBiometricLogin();
    await refreshBiometricStatus();
  };

  const login = async (email: string, password: string) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      await _persistLogin(data);
      return data.user as User;
    } finally {
      setLoading(false);
    }
  };

  const register = async (payload: any) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/register", payload);
      await _persistLogin(data);
      return data.user as User;
    } finally {
      setLoading(false);
    }
  };

  const setSession = async (token: string, u: User, refreshToken: string | null = null) => {
    await setSessionTokens(token, refreshToken);
    setUser(u);
    setSessionEndReason(null);
  };

  const logout = async () => {
    // 2026-06-10 — Explicit Logout is the ONLY way (other than the "Use a
    // different account" link on the login screen) to break out of the
    // biometric lock-in and sign in as a different user. So we always:
    //   1. Call the server's /auth/logout to invalidate the access token
    //      and active_session_id.
    //   2. Clear both AsyncStorage tokens.
    //   3. Wipe the encrypted biometric cache so the login screen falls
    //      back to the email + password form.
    //   4. Clear in-memory user.
    //
    // This is different from a cold app launch — closing the app preserves
    // the biometric cache so the fingerprint screen can resume the session
    // (see useEffect in AuthProvider for that flow).
    try { await api.post("/auth/logout"); } catch { /* ignore offline */ }
    await setSessionTokens(null, null);
    await disableBiometricLogin().catch(() => {});
    await refreshBiometricStatus();
    setUser(null);
    setSessionEndReason(null);
  };

  const clearSessionEnd = () => setSessionEndReason(null);

  return (
    <AuthContext.Provider
      value={{
        user, loading,
        login, register, logout, refresh, setSession,
        sessionEndReason, clearSessionEnd,
        integrity, recheckIntegrity,
        biometricAvailable, biometricReady, biometricEmailHint,
        loginWithBiometric, enableBiometric, disableBiometric,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
};

// Avoid unused import warnings on the bundled output.
void Platform; void setAuthToken;
