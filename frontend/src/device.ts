// Stable per-install device fingerprint.
//
// Generates and caches a random UUID in AsyncStorage the very first time the
// app boots. From then on every authenticated API call adds it as an
// X-Device-FP header so the backend can audit-log when the fingerprint for
// a given account changes (e.g. user signed in from a phone, then from a
// laptop, or from a different person's phone). Note: this is OBSERVATION
// only — we do NOT block on mismatch. Clearing app data legitimately resets
// the fingerprint, so a hard block would lock people out.
//
// Why not use expo-constants.sessionId / installationId?
//   • installationId is on Expo Go only (deprecated in SDK 50+).
//   • sessionId resets every app launch — useless for our use-case.
// A self-generated UUID stored in AsyncStorage survives app restarts, gives
// us stability across logins, and resets cleanly when the user clears the
// app — which is exactly the behaviour we want.
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

const KEY = "@app/deviceFingerprint";

// Tiny pure-JS UUID v4 (good enough for fingerprinting — not crypto).
const uuidv4 = (): string => {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};

let cached: string | null = null;

export async function getDeviceFingerprint(): Promise<string> {
  if (cached) return cached;
  try {
    const existing = await AsyncStorage.getItem(KEY);
    if (existing) {
      cached = existing;
      return existing;
    }
  } catch { /* AsyncStorage failure — fall through to fresh ID */ }
  // First boot: mint + persist a fresh fingerprint. Prefix with the platform
  // so a quick glance at security events tells admins which OS the device is.
  const fp = `${Platform.OS || "x"}-${uuidv4()}`;
  cached = fp;
  try { await AsyncStorage.setItem(KEY, fp); } catch { /* best effort */ }
  return fp;
}
