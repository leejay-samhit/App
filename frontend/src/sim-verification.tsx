/**
 * SIM-binding client orchestration (Oct 2026).
 *
 * Responsibilities, in order:
 *   1. Ask for READ_PHONE_STATE only when the user actually wants chat, with
 *      a plain-language reason first (never on app start).
 *   2. Read the local SIM status through the native module.
 *   3. Fetch a one-time server challenge and post the reading back with it.
 *   4. Keep the SERVER's answer as the single source of truth — this file
 *      never decides that anything is "verified".
 *   5. Re-check when the subscriptions change (SIM swap, eSIM switch) and
 *      when the app comes back to the foreground.
 *
 * Everything degrades quietly: on web, on iOS, in Expo Go or on a tablet with
 * no telephony the calls still run and the server simply records
 * DEVICE_UNSUPPORTED, which the screens explain.
 */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AppState, PermissionsAndroid, Platform } from "react-native";
import { api } from "./api";
import { notify } from "./notify";
import { useAuth } from "./auth";
import { isNativeAvailable, onSimChanged, readSim, hasSimPermission, SimReading } from "../modules/sim-binding";

export type SimStatus = {
  level: "none" | "sim_presence" | "number_verified" | "linked_device";
  meets_requirement: boolean;
  required_level: string;
  enforce_chat: boolean;
  number_proof_available: boolean;
  sim_state: string;
  slot_count: number;
  has_esim: boolean;
  number_verified: boolean;
  number_proof_method?: string | null;
  phone_last4?: string | null;
  revalidate_required: boolean;
  last_check_at?: string | null;
  verified_at?: string | null;
  linked_from_device?: boolean;
  binding_ttl_hours: number;
  disclaimer: string;
  sim_changed?: boolean;
};

type RunResult = {
  ok: boolean;
  reading?: SimReading;
  status?: SimStatus;
  error?: string;
  /** Permission is blocked for good — the only way back is system settings. */
  needsSettings?: boolean;
};

type Ctx = {
  status: SimStatus | null;
  loading: boolean;
  refresh: () => Promise<SimStatus | null>;
  runCheck: (opts?: { askPermission?: boolean }) => Promise<RunResult>;
  nativeAvailable: boolean;
};

const SimCtx = createContext<Ctx>({
  status: null,
  loading: false,
  refresh: async () => null,
  runCheck: async () => ({ ok: false, error: "not_ready" }),
  nativeAvailable: false,
});

export const useSimVerification = () => useContext(SimCtx);

/**
 * Turn a 403 from the chat gate into a prompt that actually leads somewhere.
 *
 * Uses `notify` (not `Alert.alert`, which is a no-op on web) so the browser
 * shows it too. Returns true when it handled the error, so callers can skip
 * their generic "failed" message.
 */
export function handleChatGateError(e: any, goTo: (path: string) => void): boolean {
  const detail = e?.response?.data?.detail;
  if (!detail || detail.code !== "sim_verification_required") return false;
  const onWeb = Platform.OS === "web";
  notify("Verify to chat", detail.message || "Verify your SIM to start chatting.", [
    { text: "Later", style: "cancel" },
    { text: onWeb ? "Link my phone" : "Verify now", onPress: () => goTo(onWeb ? "/link-device" : "/verify-sim") },
  ]);
  return true;
}

async function requestPhoneStatePermission(): Promise<"granted" | "denied" | "blocked"> {
  if (Platform.OS !== "android") return "denied";
  try {
    const res = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.READ_PHONE_STATE,
      {
        title: "Check your SIM?",
        message:
          "Slangcart checks that a SIM is present before opening chat with sellers. " +
          "We never read your SIM number, IMEI or messages.",
        buttonPositive: "Allow",
        buttonNegative: "Not now",
      },
    );
    if (res === PermissionsAndroid.RESULTS.GRANTED) return "granted";
    if (res === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN) return "blocked";
    return "denied";
  } catch {
    return "denied";
  }
}

export function SimVerificationProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [status, setStatus] = useState<SimStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const running = useRef(false);
  const lastAutoRun = useRef(0);

  const refresh = useCallback(async (): Promise<SimStatus | null> => {
    if (!user?.id) return null;
    try {
      const { data } = await api.get<SimStatus>("/sim-binding/status");
      setStatus(data);
      return data;
    } catch {
      return null;
    }
  }, [user?.id]);

  const runCheck = useCallback(
    async (opts?: { askPermission?: boolean }): Promise<RunResult> => {
      if (!user?.id) return { ok: false, error: "not_signed_in" };
      if (running.current) return { ok: false, error: "already_running" };
      running.current = true;
      setLoading(true);
      try {
        // Permission, only when the user asked for this.
        if (isNativeAvailable() && !hasSimPermission()) {
          if (!opts?.askPermission) {
            return { ok: false, error: "permission_needed" };
          }
          const perm = await requestPhoneStatePermission();
          if (perm !== "granted") {
            const fresh = await refresh();
            return {
              ok: false,
              error: "permission_denied",
              needsSettings: perm === "blocked",
              status: fresh || undefined,
            };
          }
        }

        const reading = await readSim();

        // A browser genuinely cannot do this; don't pretend by posting.
        if (Platform.OS === "web") {
          const fresh = await refresh();
          return { ok: false, error: "web_unsupported", reading, status: fresh || undefined };
        }

        const { data: challenge } = await api.post<{ challenge_id: string; nonce: string }>(
          "/sim-binding/challenge",
          { purpose: "sim_check" },
        );
        const { data } = await api.post<SimStatus>("/sim-binding/verify", {
          challenge_id: challenge.challenge_id,
          nonce: challenge.nonce,
          sim_state: reading.state,
          slot_count: reading.slotCount,
          has_esim: reading.hasEsim,
          mcc: reading.mcc,
          mnc: reading.mnc,
          platform: Platform.OS,
          os_version: String(Platform.Version || ""),
          is_device: true,
        });
        setStatus(data);
        return { ok: data.meets_requirement, reading, status: data };
      } catch (e: any) {
        const fresh = await refresh();
        // The server's structured errors are objects; String()-ing one gives
        // "[object Object]" on screen, so read the sentence out of it.
        const detail = e?.response?.data?.detail;
        const text =
          typeof detail === "string"
            ? detail
            : detail?.message || e?.message || "Please try again.";
        return {
          ok: false,
          error: String(text).slice(0, 160),
          status: fresh || undefined,
        };
      } finally {
        running.current = false;
        setLoading(false);
      }
    },
    [user?.id, refresh],
  );

  // Initial status + silent re-check on resume (cheap: a local read, never an SMS).
  useEffect(() => {
    if (!user?.id) {
      setStatus(null);
      return;
    }
    refresh();
    const maybeAutoRun = () => {
      if (!isNativeAvailable() || !hasSimPermission()) return;
      if (Date.now() - lastAutoRun.current < 60_000) return;
      lastAutoRun.current = Date.now();
      runCheck().catch(() => {});
    };
    maybeAutoRun();
    const appSub = AppState.addEventListener("change", (s) => {
      if (s === "active") maybeAutoRun();
    });
    // SIM inserted / removed / eSIM profile switched → re-verify immediately,
    // which is also what flips the server to "revalidate required".
    const simSub = onSimChanged(() => {
      lastAutoRun.current = 0;
      maybeAutoRun();
    });
    return () => {
      appSub.remove();
      simSub.remove();
    };
  }, [user?.id, refresh, runCheck]);

  return (
    <SimCtx.Provider value={{ status, loading, refresh, runCheck, nativeAvailable: isNativeAvailable() }}>
      {children}
    </SimCtx.Provider>
  );
}
