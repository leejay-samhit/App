// Phase 3 Session A — Tamper-detection facade.
//
// Orchestrates a battery of client-side device-integrity checks and POSTs
// the verdict to /api/security/integrity-report. The backend decides the
// block level which is enforced on financial endpoints + surfaced in UI.
//
// IMPORTANT: This file is SAFE FOR EXPO GO.
//   • No native modules are imported at the top level.
//   • Each check loads its native module lazily inside try/catch.
//   • If the native module is missing (Expo Go, web preview), the check is
//     marked `available: false` — the backend treats unavailable checks as
//     "unknown" and applies the SOFTEST policy (warn) for them.
// This means the app keeps working in Expo Go AND on the not-yet-shipped
// EAS Dev Client + production builds.
//
// When EAS unblocks (Session B), we'll do:
//   1. `expo install jail-monkey react-native-ssl-pinning` etc.
//   2. Replace the `available: false` stubs in this file with real native
//      calls.
//   3. Add the SHA-256 cert pins.
// All FE integration code below stays unchanged — Session B is purely
// swapping out the stubs.

import { Platform } from "react-native";
import Constants from "expo-constants";
import { api } from "./api";

// ─────────────────── Types ───────────────────
export type IntegrityCheck = {
  name:
    | "root_jailbreak"
    | "emulator"
    | "developer_mode"
    | "ssl_pin"
    | "play_integrity"
    | "apk_signature";
  passed: boolean;
  available: boolean;
  detail?: string;
};

export type IntegrityVerdict = {
  block_level: "none" | "warn" | "read_only" | "hard_block";
  reasons: string[];
};

// ─────────────────── Individual checks ───────────────────

/**
 * Detect rooted (Android) / jailbroken (iOS) device using jail-monkey.
 * Stub for now — Session B will replace with real native call:
 *   const JailMonkey = require("jail-monkey").default;
 *   const passed = !JailMonkey.isJailBroken();
 */
async function checkRootJailbreak(): Promise<IntegrityCheck> {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  try {
    // Defer native require so Expo Go bundling doesn't choke.
    // const JailMonkey = require("jail-monkey").default; // <-- enable in Session B
    return {
      name: "root_jailbreak",
      passed: true,
      available: false,
      detail: "jail-monkey not installed (Expo Go / pre-EAS build)",
    };
  } catch (e: any) {
    return { name: "root_jailbreak", passed: true, available: false, detail: e?.message };
  }
}

/**
 * Detect emulator / simulator. We use Constants.isDevice which works in
 * Expo Go and is augmented by jail-monkey in production builds (Session B).
 * Note: For now, web previews always have isDevice=false → would always
 * fail the emulator check. We special-case Platform.OS === "web" → skip.
 */
async function checkEmulator(): Promise<IntegrityCheck> {
  if (Platform.OS === "web") {
    return { name: "emulator", passed: true, available: false, detail: "web preview" };
  }
  try {
    const isDevice = (Constants as any).isDevice ?? true;
    if (isDevice === false) {
      return { name: "emulator", passed: false, available: true, detail: "Constants.isDevice=false" };
    }
    // Real device. In Session B we'll AND this with JailMonkey.isOnExternalStorage()
    // and JailMonkey.isDebuggedMode() for stronger signals.
    return { name: "emulator", passed: true, available: true };
  } catch (e: any) {
    return { name: "emulator", passed: true, available: false, detail: e?.message };
  }
}

/**
 * Detect Android developer mode (USB debugging, mock locations).
 * Stub — Session B uses jail-monkey's isDebuggedMode() + isOnExternalStorage().
 */
async function checkDeveloperMode(): Promise<IntegrityCheck> {
  if (__DEV__) {
    // Expo dev mode is the developer's own machine — never flag.
    return { name: "developer_mode", passed: true, available: false, detail: "__DEV__ build" };
  }
  return { name: "developer_mode", passed: true, available: false, detail: "stub — Session B" };
}

/**
 * SSL pinning check. We can't actually pin from JS — react-native-ssl-pinning
 * patches the native networking layer. This stub records intent.
 */
async function checkSslPin(): Promise<IntegrityCheck> {
  return { name: "ssl_pin", passed: true, available: false, detail: "ssl pinning configured at native layer (Session B)" };
}

/**
 * Google Play Integrity attestation token request. Session B will:
 *   const PlayIntegrity = require("react-native-google-play-integrity").default;
 *   const token = await PlayIntegrity.requestIntegrityToken(nonce);
 * Then we ship the token to the backend so it can validate server-side.
 */
async function checkPlayIntegrity(): Promise<IntegrityCheck & { token?: string }> {
  if (Platform.OS !== "android") {
    return { name: "play_integrity", passed: true, available: false, detail: "non-Android" };
  }
  return { name: "play_integrity", passed: true, available: false, detail: "stub — Session B" };
}

/**
 * APK signature verification — confirms the running APK was signed with our
 * own keystore (catches re-packaged apps from third-party app stores).
 * Native check, Session B.
 */
async function checkApkSignature(): Promise<IntegrityCheck> {
  if (Platform.OS !== "android") {
    return { name: "apk_signature", passed: true, available: false, detail: "non-Android" };
  }
  return { name: "apk_signature", passed: true, available: false, detail: "stub — Session B" };
}

// ─────────────────── Orchestrator ───────────────────

/** Build-type heuristic — used by the backend to discount Expo-Go reports. */
const detectBuildType = (): "expo-go" | "dev-client" | "production" | "web" => {
  if (Platform.OS === "web") return "web";
  // Constants.appOwnership === "expo" when running inside Expo Go.
  // It's "standalone" for EAS-built apps and undefined in dev-client.
  const ownership = (Constants as any).appOwnership;
  if (ownership === "expo") return "expo-go";
  if (__DEV__) return "dev-client";
  return "production";
};

/**
 * Run every integrity check and POST the verdict to the backend. Returns
 * the server-side decision so the caller can act on it (route to a blocked
 * screen, disable a button, etc.). Failures are swallowed — anti-tampering
 * must never break the app for legitimate users on a flaky network.
 */
export async function reportIntegrity(): Promise<IntegrityVerdict | null> {
  try {
    const [root, emu, dev, ssl, play, apk] = await Promise.all([
      checkRootJailbreak(),
      checkEmulator(),
      checkDeveloperMode(),
      checkSslPin(),
      checkPlayIntegrity(),
      checkApkSignature(),
    ]);
    const playToken = (play as any).token as string | undefined;
    const checks: IntegrityCheck[] = [root, emu, dev, ssl, play, apk];

    const { data } = await api.post<IntegrityVerdict>("/security/integrity-report", {
      checks,
      play_integrity_token: playToken,
      build_type: detectBuildType(),
      app_version: (Constants as any).expoConfig?.version || (Constants as any).manifest?.version || "dev",
      os: Platform.OS,
    });
    return data;
  } catch (e: any) {
    if (__DEV__) console.warn("[tamper-detection] integrity report failed", e?.message);
    return null;
  }
}

// ─────────────────── Local cache for UI guards ───────────────────
// In-memory only — refreshed on every reportIntegrity() call. Components
// (Withdraw button, Pay button) can call getLastVerdict() to decide
// instantly whether to render a disabled state, without re-hitting the
// backend or re-running the checks.
let _lastVerdict: IntegrityVerdict | null = null;
export const getLastVerdict = (): IntegrityVerdict | null => _lastVerdict;

export async function runAndCacheIntegrity(): Promise<IntegrityVerdict | null> {
  const v = await reportIntegrity();
  if (v) _lastVerdict = v;
  return v;
}

export const isFinancialBlocked = (): boolean => {
  const v = _lastVerdict;
  return !!v && (v.block_level === "read_only" || v.block_level === "hard_block");
};

export const isHardBlocked = (): boolean => {
  const v = _lastVerdict;
  return !!v && v.block_level === "hard_block";
};
