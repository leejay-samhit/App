/**
 * Emergent-managed Google sign-in.
 *
 * Flow (see the Emergent mobile auth contract):
 *   1. We send the user to `https://auth.emergentagent.com/?redirect=<our url>`.
 *   2. Emergent handles Google, then returns the user to our redirect URL with
 *      a ONE-TIME `session_id` in the URL **hash fragment**.
 *   3. We POST that `session_id` to OUR OWN backend
 *      (`POST /api/auth/google/exchange`), which is the only place allowed to
 *      talk to Emergent. It returns our normal JWT pair + user.
 *
 * The frontend NEVER calls the Emergent session-data API directly.
 *
 * Platform differences that matter:
 *   • redirect URL — `Linking.createURL("")` on native, `window.location.origin + "/"`
 *     on web (must be a route that exists, so we use the root).
 *   • opening      — `WebBrowser.openAuthSessionAsync` on native;
 *                    a plain `window.location.href` navigation on web
 *                    (a popup's return URL is cross-origin and unreadable).
 *   • capture      — on native the URL can arrive from THREE co-equal sources
 *                    (the auth-session result, the `url` listener, or
 *                    `getInitialURL()`); Android Custom Tabs routinely reports
 *                    `dismiss` with no URL even on success.
 */
import { Platform } from "react-native";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import AsyncStorage from "@react-native-async-storage/async-storage";

// Required so a returning auth session is finalised on native.
WebBrowser.maybeCompleteAuthSession();

const AUTH_URL = "https://auth.emergentagent.com/";

/** Invite code the user typed before being sent to Google. Survives the
 *  full-page redirect on web, where component state is lost. */
const PENDING_REFERRAL_KEY = "google_pending_referral";

/** Session ids we have already handed to the backend. The exchange is
 *  single-use, and on native the same deep link surfaces from two sources. */
const consumed = new Set<string>();

export function redirectUrl(): string {
  if (Platform.OS === "web") {
    return `${window.location.origin}/`;
  }
  return Linking.createURL("");
}

/** Emergent returns `#session_id=…`, which `Linking.parse().queryParams`
 *  cannot see — always match the raw URL string. */
export function extractSessionId(url?: string | null): string | null {
  if (!url) return null;
  const m = /[?#&]session_id=([^&#]+)/.exec(url);
  return m ? decodeURIComponent(m[1]) : null;
}

/** True when this session id has already been exchanged in this app run. */
export function isConsumed(sessionId: string): boolean {
  return consumed.has(sessionId);
}

/** Mark synchronously BEFORE the network call so two sources can't race. */
export function markConsumed(sessionId: string): void {
  consumed.add(sessionId);
}

export async function setPendingReferral(code?: string | null): Promise<void> {
  const clean = (code || "").trim().toUpperCase();
  if (clean) await AsyncStorage.setItem(PENDING_REFERRAL_KEY, clean);
  else await AsyncStorage.removeItem(PENDING_REFERRAL_KEY);
}

export async function takePendingReferral(): Promise<string | undefined> {
  try {
    const v = await AsyncStorage.getItem(PENDING_REFERRAL_KEY);
    if (v) await AsyncStorage.removeItem(PENDING_REFERRAL_KEY);
    return v || undefined;
  } catch {
    return undefined;
  }
}

/**
 * Start the Google flow.
 *
 * Web  — navigates away; this function never resolves in a meaningful way.
 *        The session id is picked up on the next mount by
 *        `pendingRedirectSessionId()`.
 * Native — resolves with the session id, or null when the user really did
 *        cancel (i.e. all three URL sources came up empty).
 */
export async function startGoogleSignIn(): Promise<string | null> {
  const redirect = redirectUrl();
  const authUrl = `${AUTH_URL}?redirect=${encodeURIComponent(redirect)}`;

  if (Platform.OS === "web") {
    window.location.href = authUrl;
    return null;
  }

  // Register the deep-link listener BEFORE opening the browser: on Android
  // the OS often delivers the link to the app while Custom Tabs reports a
  // dismissal, so this is the only source that sees it.
  let fromListener: string | null = null;
  const sub = Linking.addEventListener("url", (e) => {
    if (!fromListener && e?.url) fromListener = e.url;
  });
  try {
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirect);
    const fromResult = (result as any)?.url as string | undefined;
    const fromInitial = fromListener ? null : await Linking.getInitialURL();
    return (
      extractSessionId(fromResult)
      ?? extractSessionId(fromListener)
      ?? extractSessionId(fromInitial)
    );
  } finally {
    try { sub.remove(); } catch { /* ignore */ }
  }
}

/**
 * Session id waiting in the current URL — web redirects and native cold
 * starts. Returns null when there is nothing to process.
 */
export async function pendingRedirectSessionId(): Promise<string | null> {
  if (Platform.OS === "web") {
    if (typeof window === "undefined") return null;
    return extractSessionId(window.location.href);
  }
  return extractSessionId(await Linking.getInitialURL());
}

/**
 * Strip ONLY `session_id` from the browser URL, keeping every other param
 * and the history state. Call this after the exchange SUCCEEDS.
 */
export function cleanWebUrl(): void {
  if (Platform.OS !== "web" || typeof window === "undefined") return;
  try {
    const strip = (s: string) => s
      .replace(/([?#&])session_id=[^&]*&?/, "$1")
      .replace(/[?#&]$/, "");
    const url = window.location.pathname + strip(window.location.search) + strip(window.location.hash);
    window.history.replaceState(window.history.state, "", url);
  } catch {
    /* ignore — a cosmetic cleanup must never break sign-in */
  }
}
