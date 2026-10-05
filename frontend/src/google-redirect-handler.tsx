/**
 * Completes an Emergent Google sign-in that arrived via a URL rather than a
 * button tap:
 *   • Web   — the full-page redirect lands back on "/" with #session_id=…
 *   • Native cold start — the app was killed and relaunched by the deep link.
 *
 * Mounted inside AuthProvider (see app/_layout.tsx) so it runs before any
 * screen decides what to show. Renders nothing.
 */
import { useEffect, useRef } from "react";
import { useAuth } from "./auth";
import {
  cleanWebUrl, isConsumed, markConsumed, pendingRedirectSessionId, takePendingReferral,
} from "./google-auth";
import { routeAfterAuth } from "./post-auth-route";

export function GoogleRedirectHandler() {
  const { loginWithGoogle } = useAuth();
  const ranRef = useRef(false);

  useEffect(() => {
    if (ranRef.current) return;
    ranRef.current = true;
    (async () => {
      try {
        const sessionId = await pendingRedirectSessionId();
        if (!sessionId || isConsumed(sessionId)) return;
        // Mark synchronously before the network call — a re-mount and a hot
        // deep link can both surface the same one-time id.
        markConsumed(sessionId);
        const referral = await takePendingReferral();
        const u = await loginWithGoogle(sessionId, referral);
        // Only tidy the address bar once the exchange actually succeeded.
        cleanWebUrl();
        routeAfterAuth(u);
      } catch {
        // A failed exchange must not leave the app in a half state — the
        // user simply stays on the login screen and can retry.
        cleanWebUrl();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
