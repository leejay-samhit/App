/**
 * Biometric (Fingerprint / Face ID) login helper.
 *
 * Strategy
 * ────────
 * 1. After a successful password login, we ask the user "Enable Fingerprint
 *    login for faster access?". If yes, we securely cache the freshest auth
 *    token (and refresh token, if any) inside `expo-secure-store` — which is
 *    hardware-backed on real devices (Android Keystore / iOS Keychain).
 * 2. On subsequent app launches the login screen offers a "Login with
 *    fingerprint" button. Tapping it triggers the OS-level biometric prompt;
 *    on success we hydrate the auth context from the encrypted store and the
 *    user lands straight on the dashboard.
 * 3. On failure / lockout / disable, the regular email+password path is
 *    always available — biometrics never lock anyone out.
 *
 * Notes
 * ─────
 * • `expo-local-authentication` falls back gracefully on web (where it always
 *   reports unsupported), so the helper is safe to call from shared code.
 * • SecureStore values are tied to THIS phone, so if a user reinstalls or
 *   resets the device they will have to log in with password once more —
 *   that's intentional and matches user expectations.
 */

import { Platform } from "react-native";
import * as LocalAuth from "expo-local-authentication";
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";

// Keys ─────────────────────────────────────────────────────────────────────
const SS_TOKEN_KEY        = "bio_auth_token_v1";
const SS_REFRESH_KEY      = "bio_refresh_token_v1";
const AS_ENABLED_KEY      = "biometric_enabled_v1";  // "1" or "0"
const AS_EMAIL_HINT       = "biometric_email_hint";  // masked email for UI

export type BiometricCapability = {
  /** Whether the OS reports any biometric hardware exists. */
  hasHardware: boolean;
  /** Whether the user has at least one biometric enrolled (registered). */
  isEnrolled: boolean;
  /** What types are supported: Fingerprint, Facial, Iris … */
  supportedTypes: LocalAuth.AuthenticationType[];
  /** True when both hardware + enrollment are usable. */
  available: boolean;
};

/**
 * Probe the device for biometric capability. Always safe to call — returns
 * `available: false` on web / simulators without enrollment.
 */
export async function getBiometricCapability(): Promise<BiometricCapability> {
  // expo-local-authentication has no-op shims on web but checking Platform
  // explicitly avoids spurious console warnings during a web preview build.
  if (Platform.OS === "web") {
    return { hasHardware: false, isEnrolled: false, supportedTypes: [], available: false };
  }
  try {
    const [hasHardware, isEnrolled, supportedTypes] = await Promise.all([
      LocalAuth.hasHardwareAsync(),
      LocalAuth.isEnrolledAsync(),
      LocalAuth.supportedAuthenticationTypesAsync(),
    ]);
    return {
      hasHardware,
      isEnrolled,
      supportedTypes,
      available: hasHardware && isEnrolled,
    };
  } catch {
    return { hasHardware: false, isEnrolled: false, supportedTypes: [], available: false };
  }
}

/**
 * Has the user opted-in to biometric login on this device AND do we have a
 * cached token? UI uses this to decide whether to show the "Login with
 * fingerprint" button on the login screen.
 */
export async function isBiometricLoginReady(): Promise<{ ready: boolean; emailHint: string | null }>
{
  try {
    const enabled = (await AsyncStorage.getItem(AS_ENABLED_KEY)) === "1";
    if (!enabled) return { ready: false, emailHint: null };
    const tok = await SecureStore.getItemAsync(SS_TOKEN_KEY);
    const cap = await getBiometricCapability();
    if (!tok || !cap.available) return { ready: false, emailHint: null };
    const emailHint = await AsyncStorage.getItem(AS_EMAIL_HINT);
    return { ready: true, emailHint };
  } catch {
    return { ready: false, emailHint: null };
  }
}

/**
 * Enroll biometric login: stash the freshest auth tokens in the secure
 * keystore + flip the enabled flag. Caller must have already verified the
 * user via password. `emailHint` is shown on the next login screen so the
 * user knows whose fingerprint will unlock what (masked to "ra***@gmail.com").
 */
export async function enableBiometricLogin(opts: {
  token: string;
  refreshToken?: string | null;
  email: string;
}): Promise<void> {
  await SecureStore.setItemAsync(SS_TOKEN_KEY, opts.token, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
  if (opts.refreshToken) {
    await SecureStore.setItemAsync(SS_REFRESH_KEY, opts.refreshToken, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  } else {
    // Old token in store? clear it so we don't accidentally re-use stale value.
    await SecureStore.deleteItemAsync(SS_REFRESH_KEY).catch(() => {});
  }
  await AsyncStorage.setItem(AS_ENABLED_KEY, "1");
  await AsyncStorage.setItem(AS_EMAIL_HINT, maskEmail(opts.email));
}

/** Disable biometric login completely (called from Profile screen toggle). */
export async function disableBiometricLogin(): Promise<void> {
  await Promise.allSettled([
    SecureStore.deleteItemAsync(SS_TOKEN_KEY),
    SecureStore.deleteItemAsync(SS_REFRESH_KEY),
    AsyncStorage.removeItem(AS_ENABLED_KEY),
    AsyncStorage.removeItem(AS_EMAIL_HINT),
  ]);
}

/**
 * Whenever the user gets a fresh token via refresh / re-login, we update the
 * cached biometric token so it doesn't expire. Silently no-ops if biometric
 * isn't enabled. Called from the api token-refresh hook.
 *
 * If `email` is passed (e.g. on a successful login), we also refresh the
 * cached email hint. This keeps the "Welcome back, ra***@gmail.com" label
 * pointing at the user whose tokens are actually stored — important when a
 * different user logs into the same phone with password after the first
 * user enabled fingerprint.
 */
export async function syncBiometricTokens(
  token: string | null,
  refreshToken: string | null,
  email?: string | null,
): Promise<void> {
  try {
    const enabled = (await AsyncStorage.getItem(AS_ENABLED_KEY)) === "1";
    if (!enabled) return;
    if (token) {
      await SecureStore.setItemAsync(SS_TOKEN_KEY, token, {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
    }
    if (refreshToken) {
      await SecureStore.setItemAsync(SS_REFRESH_KEY, refreshToken, {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
    }
    if (email) {
      await AsyncStorage.setItem(AS_EMAIL_HINT, maskEmail(email));
    }
  } catch {
    // Sync failures are not fatal — worst case the user does one more
    // password login on the next refresh-token expiry.
  }
}

/**
 * Run the native biometric prompt and, on success, return the cached tokens
 * so the auth context can hydrate the session.
 */
export async function authenticateAndGetTokens(): Promise<
  { ok: true; token: string; refreshToken: string | null }
  | { ok: false; reason: string }
> {
  const cap = await getBiometricCapability();
  if (!cap.available) {
    return { ok: false, reason: !cap.hasHardware
      ? "Your device doesn't support biometrics."
      : "Please enrol a fingerprint or face in your phone's settings first." };
  }
  const result = await LocalAuth.authenticateAsync({
    promptMessage: "Unlock Slangcart",
    cancelLabel: "Use password instead",
    fallbackLabel: "",
    disableDeviceFallback: true, // we want biometric ONLY — not the OS PIN
  });
  if (!result.success) {
    const reasonMap: Record<string, string> = {
      user_cancel:    "Cancelled. You can try again or login with password.",
      app_cancel:     "Cancelled.",
      lockout:        "Too many failed attempts. Please use password to login.",
      not_enrolled:   "No fingerprint enrolled. Add one in your phone settings.",
      passcode_not_set:"Set a lock screen passcode in your phone settings first.",
      not_available:  "Biometric hardware not available right now.",
      unknown:        "Couldn't read fingerprint — please try again or use password.",
    };
    const code = (result as any).error || "unknown";
    return { ok: false, reason: reasonMap[code] || reasonMap.unknown };
  }
  const token = await SecureStore.getItemAsync(SS_TOKEN_KEY);
  if (!token) {
    return { ok: false, reason: "No saved session — please login with password once." };
  }
  const refreshToken = await SecureStore.getItemAsync(SS_REFRESH_KEY);
  return { ok: true, token, refreshToken };
}

/** Mask an email for the "Welcome back, **ra***@gmail.com**" label. */
function maskEmail(email: string): string {
  if (!email || !email.includes("@")) return email || "";
  const [local, domain] = email.split("@");
  if (local.length <= 2) return `${local[0]}*@${domain}`;
  return `${local.slice(0, 2)}${"*".repeat(Math.max(1, local.length - 2))}@${domain}`;
}

/** Human-readable label for the available biometric kind. */
export function describeBiometric(cap: BiometricCapability): string {
  if (!cap.available) return "Fingerprint";
  const types = cap.supportedTypes || [];
  if (types.includes(LocalAuth.AuthenticationType.FACIAL_RECOGNITION)) return "Face ID";
  if (types.includes(LocalAuth.AuthenticationType.IRIS)) return "Iris";
  return "Fingerprint";
}
