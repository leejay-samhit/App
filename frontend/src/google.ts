// Google Sign-In via Emergent-managed Google Auth.
// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
import * as WebBrowser from "expo-web-browser";
import { Platform } from "react-native";
import { api } from "./api";

WebBrowser.maybeCompleteAuthSession();

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL as string;

export type GoogleResult = {
  ok: boolean;
  cancelled?: boolean;
  token?: string;
  user?: any;
  is_new?: boolean;
  error?: string;
};

export async function signInWithGoogle(referralCode?: string): Promise<GoogleResult> {
  // Redirect must be reachable; we use our backend's callback page which Emergent appends #session_id=... to.
  // On web: use window.location.origin so it works across preview/prod/custom domains.
  // On native: use BACKEND env var (deep-linking back into the deployed backend).
  let origin: string;
  if (Platform.OS === "web") {
    origin = typeof window !== "undefined" ? window.location.origin : "";
  } else {
    origin = BACKEND;
  }
  const redirectUrl = `${origin}/api/auth/google/callback`;
  const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;

  let resultUrl: string | undefined;

  if (Platform.OS === "web") {
    // Web preview: open in same window so we can read the URL fragment
    const win = window.open(authUrl, "_blank", "width=520,height=640");
    if (!win) return { ok: false, error: "Popup blocked. Allow popups and retry." };
    resultUrl = await new Promise<string | undefined>((resolve) => {
      const interval = setInterval(() => {
        try {
          if (!win || win.closed) {
            clearInterval(interval);
            resolve(undefined);
            return;
          }
          // Same-origin or our backend origin only — try reading
          const url = win.location.href;
          if (url && url.includes("session_id=")) {
            clearInterval(interval);
            try { win.close(); } catch {}
            resolve(url);
          }
        } catch {
          // cross-origin while still on auth.emergentagent.com — ignore
        }
      }, 350);
      // Safety timeout
      setTimeout(() => { clearInterval(interval); try { win.close(); } catch {} resolve(undefined); }, 180000);
    });
  } else {
    const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
    if (result.type === "cancel" || result.type === "dismiss") return { ok: false, cancelled: true };
    if (result.type === "success" && result.url) resultUrl = result.url;
  }

  if (!resultUrl) return { ok: false, cancelled: true };
  const m = resultUrl.match(/session_id=([^&#]+)/);
  if (!m) return { ok: false, error: "No session_id in callback URL" };
  const sessionId = decodeURIComponent(m[1]);

  try {
    const { data } = await api.post("/auth/google/exchange", {
      session_id: sessionId,
      referral_code: referralCode || undefined,
    });
    return { ok: true, token: data.token, user: data.user, is_new: data.is_new };
  } catch (e: any) {
    return { ok: false, error: e?.response?.data?.detail || e?.message || "Google sign-in failed" };
  }
}
