/**
 * Push notification registration helper.
 *
 * Wire-up flow (per the Emergent push integration playbook):
 *   1. Request notification permission (iOS prompt / Android auto-grant<33).
 *   2. Fetch the **native** FCM/APNs device token (NOT the Expo token).
 *   3. POST it to /api/register-push so the backend's relay can target it.
 *
 * Called from `src/auth.tsx` on every successful login + on every app open
 * (tokens rotate). Wrapped in try/catch — push setup must never block sign-in.
 *
 * Web platforms are skipped entirely; expo-notifications native modules are
 * not available in the browser bundle.
 */
import { Platform } from "react-native";
import { api } from "./api";

let lastRegisteredUserId: string | null = null;

export async function registerForPush(userId: string): Promise<void> {
  if (!userId) return;
  if (Platform.OS === "web") return;
  // De-dupe — only re-register when the active user changes mid-session.
  if (lastRegisteredUserId === userId) return;

  try {
    const Notifications = await import("expo-notifications");
    const Device = await import("expo-device");

    // expo-notifications still ships push registration even on emulators,
    // but device tokens are only meaningful on real hardware. Skip on
    // simulators to avoid noisy backend warnings.
    if (!Device.isDevice) return;

    const perms = await Notifications.getPermissionsAsync();
    let status = perms.status;
    if (status !== "granted") {
      const req = await Notifications.requestPermissionsAsync();
      status = req.status;
    }
    if (status !== "granted") return;

    const tokenResp = await Notifications.getDevicePushTokenAsync();
    const device_token = (tokenResp && (tokenResp.data as string)) || "";
    if (!device_token) return;

    const { data } = await api.post<{ status?: string; reason?: string }>("/register-push", {
      user_id: userId,
      platform: Platform.OS,
      device_token,
    });
    // Only remember it when the relay actually took the token. A "deferred"
    // answer (relay key not injected yet, upstream hiccup) must be retried
    // on the next app open, otherwise the phone stays unreachable for the
    // whole install.
    if (data?.status === "registered") lastRegisteredUserId = userId;
    else if (__DEV__) console.warn("[push] registration deferred:", data?.reason);
  } catch (e) {
    // Best-effort. Don't surface to the user — push is non-critical for
    // sign-in. Backend already returns 201/deferred semantics.
    if (__DEV__) console.warn("[push] registerForPush failed:", e);
  }
}

/** Call on logout so the next login re-registers (token may have rotated). */
export function clearPushRegistrationCache() {
  lastRegisteredUserId = null;
}
