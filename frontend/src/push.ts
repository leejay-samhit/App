/**
 * Push notification registration helper.
 *
 * Wire-up flow (per the Emergent push integration playbook):
 *   1. Request notification permission (iOS prompt / Android 13+ dialog).
 *   2. Fetch the **native** FCM/APNs device token (NOT the Expo token).
 *   3. POST it to /api/register-push so the backend's relay can target it.
 *
 * Called from `src/auth.tsx` on every successful login and from
 * `PushReRegister` on every app open (tokens rotate). Wrapped in try/catch —
 * push setup must never block sign-in.
 *
 * Sep 2026 — two gaps that silently killed tray delivery are closed here:
 *   • **Token rotation while the app is running.** FCM rotates tokens (app
 *     upgrade, data clear, restore). Previously nothing re-registered until
 *     the next cold start with a *different* user, so the relay kept pushing
 *     to a dead token. `addPushTokenListener` now re-registers immediately.
 *   • **No evidence.** The token itself is never stored (SuprSend owns it),
 *     but the registration now carries device diagnostics — build ownership
 *     (Expo Go cannot receive push at all), real-device flag, OS version and
 *     the live permission status — so "this phone never had a usable token"
 *     is distinguishable from "the server never sent".
 *
 * Web platforms are skipped entirely; expo-notifications native modules are
 * not available in the browser bundle.
 */
import { Platform } from "react-native";
import { api } from "./api";

let lastRegisteredUserId: string | null = null;
let lastRegisteredToken: string | null = null;
let tokenListenerAttached = false;

async function postToken(userId: string, token: string, permissionStatus: string) {
  const Constants = await import("expo-constants");
  const Device = await import("expo-device");
  const { data } = await api.post<{ status?: string; reason?: string }>("/register-push", {
    user_id: userId,
    platform: Platform.OS,
    device_token: token,
    // Diagnostics — stripped by the backend before the relay call.
    app_ownership: Constants.default?.appOwnership || (Constants.default?.executionEnvironment ?? null),
    is_device: Device.isDevice,
    os_version: String(Device.osVersion || ""),
    device_name: String(Device.modelName || ""),
    app_version: String(Constants.default?.expoConfig?.version || ""),
    permission_status: permissionStatus,
  });
  return data;
}

export async function registerForPush(userId: string): Promise<void> {
  if (!userId) return;
  if (Platform.OS === "web") return;

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

    // Re-register whenever the user OR the token changes. (The old guard
    // returned early on the same user id, so a rotated token was never sent.)
    const tokenResp = await Notifications.getDevicePushTokenAsync();
    const device_token = (tokenResp && (tokenResp.data as string)) || "";
    if (!device_token) return;

    if (lastRegisteredUserId === userId && lastRegisteredToken === device_token) {
      // Nothing changed — but make sure the rotation listener is live.
      attachTokenListener(userId);
      return;
    }

    const data = await postToken(userId, device_token, status);
    // Only remember it when the relay actually took the token. A "deferred"
    // answer (relay key not injected yet, upstream hiccup) must be retried
    // on the next app open, otherwise the phone stays unreachable for the
    // whole install.
    if (data?.status === "registered") {
      lastRegisteredUserId = userId;
      lastRegisteredToken = device_token;
    } else if (__DEV__) {
      console.warn("[push] registration deferred:", data?.reason);
    }
    attachTokenListener(userId);
  } catch (e) {
    // Best-effort. Don't surface to the user — push is non-critical for
    // sign-in. Backend already returns 201/deferred semantics.
    if (__DEV__) console.warn("[push] registerForPush failed:", e);
  }
}

/** Re-register the moment FCM/APNs hands us a new token. */
function attachTokenListener(userId: string) {
  if (tokenListenerAttached || Platform.OS === "web") return;
  tokenListenerAttached = true;
  import("expo-notifications")
    .then((Notifications) => {
      Notifications.addPushTokenListener(async (token) => {
        try {
          const next = (token?.data as string) || "";
          if (!next || next === lastRegisteredToken) return;
          const { status } = await Notifications.getPermissionsAsync();
          const data = await postToken(userId, next, status);
          if (data?.status === "registered") {
            lastRegisteredUserId = userId;
            lastRegisteredToken = next;
          }
          if (__DEV__) console.log("[push] token rotated, re-registered:", data?.status);
        } catch (e) {
          if (__DEV__) console.warn("[push] token rotation re-register failed:", e);
        }
      });
    })
    .catch(() => {
      tokenListenerAttached = false;
    });
}

/** Call on logout so the next login re-registers (token may have rotated). */
export function clearPushRegistrationCache() {
  lastRegisteredUserId = null;
  lastRegisteredToken = null;
}
