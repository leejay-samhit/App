/**
 * JS surface of the local `truecaller` Android module.
 *
 * Absent on web, on iOS and in Expo Go — every call then reports
 * `unavailable` instead of throwing, so the screen can fall straight back to
 * manual number entry.
 */
import { requireOptionalNativeModule, EventSubscription } from "expo-modules-core";
import { Platform } from "react-native";

export type TruecallerSuccess = {
  authorizationCode: string;
  state: string;
  scopesGranted: string[];
};

export type TruecallerFailure = { code: number; message: string };

type NativeTruecaller = {
  isUsable: () => Promise<boolean>;
  requestVerification: (state: string, codeChallenge: string) => Promise<boolean>;
  addListener: (
    event: "onSdkReady" | "onSuccess" | "onFailure" | "onVerificationRequired",
    cb: (e: any) => void,
  ) => EventSubscription;
};

const native = requireOptionalNativeModule<NativeTruecaller>("Truecaller");

export const isTruecallerModuleAvailable = (): boolean => Platform.OS === "android" && !!native;

export async function isTruecallerUsable(): Promise<boolean> {
  if (!isTruecallerModuleAvailable()) return false;
  try {
    return await native!.isUsable();
  } catch {
    return false;
  }
}

/**
 * Shows Truecaller's consent sheet and resolves with the one-time
 * authorization code, or rejects with a short reason the UI can explain.
 */
export function requestTruecallerCode(
  state: string,
  codeChallenge: string,
  timeoutMs = 120000,
): Promise<TruecallerSuccess> {
  if (!isTruecallerModuleAvailable()) {
    return Promise.reject(new Error("unavailable"));
  }
  return new Promise<TruecallerSuccess>((resolve, reject) => {
    const subs: EventSubscription[] = [];
    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      subs.forEach((s) => {
        try {
          s.remove();
        } catch {
          /* already removed */
        }
      });
      clearTimeout(timer);
      fn();
    };
    const timer = setTimeout(() => finish(() => reject(new Error("timeout"))), timeoutMs);

    subs.push(
      native!.addListener("onSuccess", (e: TruecallerSuccess) => {
        // The state must be the one the server issued for this attempt.
        if (!e?.authorizationCode || e.state !== state) {
          finish(() => reject(new Error("state_mismatch")));
          return;
        }
        finish(() => resolve(e));
      }),
    );
    subs.push(
      native!.addListener("onFailure", (e: TruecallerFailure) => {
        finish(() => reject(new Error(String(e?.code ?? "failed"))));
      }),
    );
    subs.push(
      native!.addListener("onVerificationRequired", () => {
        finish(() => reject(new Error("verification_required")));
      }),
    );

    native!.requestVerification(state, codeChallenge).catch((err: any) => {
      finish(() => reject(new Error(String(err?.message || err || "failed"))));
    });
  });
}
