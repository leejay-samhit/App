import React, { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, setAuthToken, setSessionTokens, onSessionInvalidated } from "./api";
import { runAndCacheIntegrity, IntegrityVerdict } from "./tamper-detection";

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
};

const AuthContext = createContext<AuthState | null>(null);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [sessionEndReason, setSessionEndReason] = useState<AuthState["sessionEndReason"]>(null);
  const [integrity, setIntegrity] = useState<IntegrityVerdict | null>(null);

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
    // Best-effort: tell the server to wipe active_session_id so the access
    // token dies immediately. Don't block the UI on it — even if this fails
    // (offline), the local wipe below will sign the user out on this device.
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    await setSessionTokens(null, null);
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
