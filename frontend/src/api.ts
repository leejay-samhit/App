import axios, { AxiosError, AxiosRequestConfig } from "axios";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { getDeviceFingerprint } from "./device";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

/** Dec 2026 — Resolve a possibly-relative product image URL against the
 *  backend base.  List endpoints now return `/api/products/{id}/image`
 *  paths (see backend `_slim_list_item`) so the mobile client can lazy-
 *  load each thumbnail as a card scrolls into view.  Absolute URLs and
 *  base64 data URIs pass through untouched. */
export function resolveImageUrl(url?: string | null): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) return url;
  if (url.startsWith("/api/")) return `${BASE_URL}${url}`;
  if (url.startsWith("/")) return `${BASE_URL}${url}`;
  return url;
}

const ACCESS_KEY  = "auth_token";
const REFRESH_KEY = "auth_refresh_token";

export const api = axios.create({
  baseURL: `${BASE_URL}/api`,
  timeout: 20000,
});

// ────────────────── REQUEST INTERCEPTOR ──────────────────
// Adds the bearer token (if any) and the device fingerprint to every call.
api.interceptors.request.use(async (config) => {
  const token = await AsyncStorage.getItem(ACCESS_KEY);
  if (token) {
    config.headers = config.headers || {};
    (config.headers as any).Authorization = `Bearer ${token}`;
  }
  try {
    const fp = await getDeviceFingerprint();
    if (fp) {
      config.headers = config.headers || {};
      (config.headers as any)["X-Device-FP"] = fp;
    }
  } catch { /* fingerprint failure must never break the request */ }
  return config;
});

// ────────────────── RESPONSE INTERCEPTOR (Phase 1 Session B) ──────────────────
// Two concerns handled here:
//
//   1. ACCESS TOKEN EXPIRY ("token_expired") — backend access tokens last
//      15 minutes. On a 401 with that exact detail, we try `/auth/refresh`
//      ONCE (using the refresh token in storage) and replay the original
//      request with the new access token. Successful refresh is invisible
//      to the user.
//
//   2. SESSION REVOKED ("session_revoked") — the user signed in on
//      another device, or explicitly logged out elsewhere, or the refresh
//      token they presented was stale. We clear local storage and fire a
//      "session-revoked" event so auth.tsx can surface a "Signed in
//      elsewhere — please log in again" banner and route to /login.
//
// Anything else (incl. plain 401 for bad credentials, 403 for blocked etc.)
// passes through untouched so individual screens can render their own
// error messages.

// Single-flight refresh promise — multiple parallel 401s share one refresh.
let _refreshing: Promise<string | null> | null = null;

// Tiny pub-sub so AuthProvider can react to session-revoked without an
// import cycle. AuthProvider subscribes in its useEffect.
type Listener = (reason: "session_revoked" | "refresh_failed") => void;
const _sessionListeners = new Set<Listener>();
export const onSessionInvalidated = (cb: Listener) => {
  _sessionListeners.add(cb);
  return () => { _sessionListeners.delete(cb); };
};
const _emitSessionInvalidated = (reason: "session_revoked" | "refresh_failed") => {
  for (const cb of _sessionListeners) { try { cb(reason); } catch { /* ignore */ } }
};

async function _refreshAccessToken(): Promise<string | null> {
  const refreshToken = await AsyncStorage.getItem(REFRESH_KEY);
  if (!refreshToken) return null;
  try {
    // Bare axios — DON'T go through `api` (would loop on its own interceptor).
    const resp = await axios.post(`${BASE_URL}/api/auth/refresh`, {
      refresh_token: refreshToken,
    }, { timeout: 15000 });
    const data: any = resp.data || {};
    if (!data.token || !data.refresh_token) return null;
    await AsyncStorage.setItem(ACCESS_KEY, data.token);
    await AsyncStorage.setItem(REFRESH_KEY, data.refresh_token);
    return data.token;
  } catch (e: any) {
    // Distinguish session_revoked (terminal) from transient failures.
    const detail = e?.response?.data?.detail;
    if (detail === "session_revoked" || detail === "refresh_expired" || detail === "refresh_invalid") {
      // Refresh token itself is dead — wipe local state.
      await AsyncStorage.removeItem(ACCESS_KEY);
      await AsyncStorage.removeItem(REFRESH_KEY);
      _emitSessionInvalidated(detail === "session_revoked" ? "session_revoked" : "refresh_failed");
    }
    return null;
  }
}

api.interceptors.response.use(
  (resp) => resp,
  async (error: AxiosError<any>) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    const original = error.config as AxiosRequestConfig & { _retry?: boolean };

    if (status === 401 && detail === "session_revoked") {
      // Definitive kick: clear tokens and notify UI.
      await AsyncStorage.removeItem(ACCESS_KEY);
      await AsyncStorage.removeItem(REFRESH_KEY);
      _emitSessionInvalidated("session_revoked");
      return Promise.reject(error);
    }

    if (status === 401 && detail === "token_expired" && original && !original._retry) {
      original._retry = true;
      // Coalesce concurrent refreshes — only the first call hits the network.
      if (!_refreshing) _refreshing = _refreshAccessToken().finally(() => { _refreshing = null; });
      const newToken = await _refreshing;
      if (newToken) {
        original.headers = original.headers || {};
        (original.headers as any).Authorization = `Bearer ${newToken}`;
        return api.request(original);
      }
      // Refresh failed terminal — _refreshAccessToken already emitted the event.
      return Promise.reject(error);
    }

    return Promise.reject(error);
  },
);

// ────────────────── TOKEN HELPERS ──────────────────
export const setAuthToken = async (token: string | null) => {
  if (token) await AsyncStorage.setItem(ACCESS_KEY, token);
  else await AsyncStorage.removeItem(ACCESS_KEY);
};

export const setRefreshToken = async (token: string | null) => {
  if (token) await AsyncStorage.setItem(REFRESH_KEY, token);
  else await AsyncStorage.removeItem(REFRESH_KEY);
};

export const setSessionTokens = async (
  accessToken: string | null,
  refreshToken: string | null,
) => {
  await setAuthToken(accessToken);
  await setRefreshToken(refreshToken);
};

export const getAuthToken = async () => AsyncStorage.getItem(ACCESS_KEY);
export const getRefreshToken = async () => AsyncStorage.getItem(REFRESH_KEY);

export const formatApiError = (e: any): string => {
  const detail = e?.response?.data?.detail;
  if (!detail) return e?.message || "Something went wrong";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => (typeof d?.msg === "string" ? d.msg : JSON.stringify(d)))
      .join(" ");
  }
  return JSON.stringify(detail);
};
