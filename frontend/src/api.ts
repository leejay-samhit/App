import axios, { AxiosError, AxiosRequestConfig } from "axios";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

import { getDeviceFingerprint, getDeviceName } from "./device";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL;

/** Dec 2026 — Resolve a possibly-relative product image URL against the
 *  backend base.  List endpoints now return `/api/products/{id}/image`
 *  paths (see backend `_slim_list_item`) so the mobile client can lazy-
 *  load each thumbnail as a card scrolls into view.  Absolute URLs and
 *  base64 data URIs pass through untouched.
 *
 *  Jun 2026 — Hardened against non-string input.  Shopify-converted
 *  catalogue imports store gallery entries as OBJECTS (`{src, position}`);
 *  calling `.startsWith` on one threw a TypeError mid-render and closed
 *  the Android release build as soon as a shopper tapped a product card.
 *  Objects are now unwrapped, and anything else resolves to "". */
export function resolveImageUrl(url?: unknown): string {
  if (!url) return "";
  if (typeof url !== "string") {
    if (typeof url === "object") {
      const o = url as Record<string, unknown>;
      for (const k of ["src", "url", "image_url", "image", "href", "data_url"]) {
        if (typeof o[k] === "string" && o[k]) return resolveImageUrl(o[k]);
      }
    }
    return "";
  }
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) return url;
  if (url.startsWith("/")) return `${BASE_URL}${url}`;
  return url;
}

const ACCESS_KEY  = "auth_token";
const REFRESH_KEY = "auth_refresh_token";

export const api = axios.create({
  baseURL: `${BASE_URL}/api`,
  // Dec 2026 — Bumped from 20s → 60s so vendor uploads with several
  // MB of base64 images don't spuriously time out on flaky 3G/4G.
  // The response interceptor still auto-retries safe GETs on genuine
  // transient failures, so this only affects request duration bound.
  timeout: 60000,
});

// ────────────────── REQUEST INTERCEPTOR ──────────────────
// Adds the bearer token (if any) and the device fingerprint to every call.
api.interceptors.request.use(async (config) => {
  const token = await AsyncStorage.getItem(ACCESS_KEY);
  if (token) {
    config.headers = config.headers || {};
    (config.headers as any).Authorization = `Bearer ${token}`;
  }
  // Oct 2026 — tells the server whether this call came from the installed app
  // or a browser. The SIM-binding chat gate uses it to decide whether a
  // linked phone is required (a browser has no SIM of its own).
  config.headers = config.headers || {};
  (config.headers as any)["X-Client-Platform"] = Platform.OS;
  try {
    const fp = await getDeviceFingerprint();
    if (fp) {
      config.headers = config.headers || {};
      (config.headers as any)["X-Device-FP"] = fp;
    }
  } catch { /* fingerprint failure must never break the request */ }
  try {
    // Human device label so "Login activity" can name the device
    // ("Samsung SM-G991B · Android") instead of a raw user-agent.
    const name = getDeviceName();
    if (name) {
      config.headers = config.headers || {};
      (config.headers as any)["X-Device-Name"] = name;
    }
  } catch { /* label is cosmetic — never break the request */ }
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
    // Keep the fingerprint-login cache in step with the rotation. Without
    // this the SecureStore copy went stale within 15 minutes and the next
    // fingerprint unlock fell back to "please login with password once"
    // (owner report, Sep 2026).
    try {
      const { syncBiometricTokens } = await import("./biometric");
      await syncBiometricTokens(data.token, data.refresh_token);
    } catch { /* cache sync is best-effort */ }
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
    const original = error.config as AxiosRequestConfig & { _retry?: boolean; _retryCount?: number };

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

    // Dec 2026 v2 — App-wide silent resilience.
    //
    // Goal: the customer / vendor / admin should NEVER see a raw
    // "network error" pop-up.  We retry aggressively, per-method:
    //
    //   • SAFE verbs (GET/HEAD/OPTIONS): retry up to **5** times at
    //     250 ms, 500 ms, 1 s, 2 s, 4 s (~7.75 s max wait).  These
    //     verbs are idempotent by RFC, retrying is always safe.
    //
    //   • UNSAFE verbs (POST/PUT/PATCH/DELETE): retry up to **3**
    //     times at 400 ms, 900 ms, 1.8 s.  We stamp an
    //     `Idempotency-Key` header on the FIRST attempt so the server
    //     can dedupe if a previous request actually succeeded but the
    //     response was lost in transit (see backend middleware
    //     `_idempotency_guard`).  This makes retries safe for writes.
    //
    // Transient error definition — retryable when:
    //   • No response at all (DNS / TCP reset / TLS handshake / mobile
    //     radio blip / airplane-mode flicker).
    //   • 5xx gateway class: 502 Bad Gateway, 503 Unavailable, 504
    //     Timeout, 429 rate-limit (with backoff).
    //   • 408 request-timeout (rare — some CDNs use it).
    const method = (original?.method || "get").toLowerCase();
    const isSafe = method === "get" || method === "head" || method === "options";
    const isTransient = (
      !error.response ||
      status === 408 || status === 429 ||
      status === 502 || status === 503 || status === 504
    );
    const maxRetries = isSafe ? 5 : 3;
    const retryCount = original?._retryCount || 0;
    if (isTransient && retryCount < maxRetries && original) {
      original._retryCount = retryCount + 1;
      // Idempotency key for write verbs — persists across retries so the
      // server can safely reject duplicates.  Reused across attempts of
      // the SAME request; each new original request gets a fresh one.
      if (!isSafe) {
        original.headers = original.headers || {};
        if (!(original.headers as any)["Idempotency-Key"]) {
          const idem = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
          (original.headers as any)["Idempotency-Key"] = idem;
        }
      }
      // Exponential backoff with a small jitter (±15 %) so a stampede
      // of clients recovering from the same outage don't hammer the
      // server in perfect lockstep.
      const base = isSafe
        ? [250, 500, 1000, 2000, 4000][retryCount]
        : [400, 900, 1800][retryCount];
      const jitter = (Math.random() - 0.5) * base * 0.3;
      await new Promise((r) => setTimeout(r, Math.max(100, base + jitter)));
      return api.request(original);
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
  // Dec 2026 — Friendly, informative messages when a request DOES
  // finally fail after all retries.  The interceptor above hides ~99%
  // of transient blips silently; anything reaching here is a real
  // condition the user needs to know about.
  if (e?.code === "ECONNABORTED") {
    return "The request took too long. Please check your connection and try again.";
  }
  if (!e?.response && (e?.message === "Network Error" || e?.code === "ERR_NETWORK")) {
    return "Couldn't reach the server. We'll keep trying — check your internet if this persists.";
  }
  const detail = e?.response?.data?.detail;
  if (!detail) return e?.message || "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  // Structured errors (e.g. the SIM-binding chat gate) carry a plain-language
  // `message` alongside a machine code — show the sentence, not the JSON.
  if (detail && typeof detail === "object" && typeof (detail as any).message === "string") {
    return (detail as any).message;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => (typeof d?.msg === "string" ? d.msg : JSON.stringify(d)))
      .join(" ");
  }
  return JSON.stringify(detail);
};
