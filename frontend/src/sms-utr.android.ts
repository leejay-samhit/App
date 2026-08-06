// SMS User Consent helper — auto-detects UTR / UPI reference number from
// incoming bank SMS on Android. Uses Google's SMS User Consent API (no
// READ_SMS permission required). Shows a one-time system dialog asking the
// user to share a single SMS with the app, then we run regex extraction.
//
// • Android only — on iOS / web this is a no-op (returns null).
// • Native module only available in EAS dev/prod builds (not Expo Go).
//   We try/catch so the JS bundle still loads in Expo Go.
// • Listening window: ~5 minutes from `start()`. Call again as needed.

import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";

// ---- safely load the native module ------------------------------------------------
type SmsModule = {
  startSmsHandling: (cb: (e?: { sms?: string }) => void) => () => void;
  addErrorListener?: (cb: (err?: any) => void) => () => void;
};
let SMS: SmsModule | null = null;
try {
  // Dec 2026 — Variable indirection so Metro can't statically resolve
  // the module.  This lets release builds succeed even when the SMS
  // User Consent native module isn't installed (in which case the
  // feature degrades to a no-op).  When the module IS installed (via
  // EAS dev/prod build with autolinking), the runtime require picks it
  // up transparently.
  const _modId = "@eabdullazyanov/react-native-sms-user-consent";
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  SMS = require(_modId);
} catch {
  SMS = null;
}

export const isSmsConsentAvailable = (): boolean =>
  Platform.OS === "android" && !!SMS?.startSmsHandling;

// ---- UTR extraction ---------------------------------------------------------------
// UPI UTR/RRN is typically 12 digits but can be 8–22 alphanumeric.
// We try keyword-based capture first (more accurate), then fall back to
// "longest pure-numeric token between 10 and 22 chars" which catches almost
// every Indian bank SMS for UPI.
const KEYWORD_RE = /(?:UPI[\s:\-#/]*Ref(?:erence)?\s*(?:no\.?|#|num(?:ber)?)?[\s:\-]*|UPI[\s:\-]*|RRN[\s:\-]*|Ref(?:erence)?\s*(?:no\.?|#)?[\s:\-]*|Txn\s*ID[\s:\-]*|Transaction\s*ID[\s:\-]*)([A-Z0-9]{10,22})/i;
const LOOSE_RE   = /\b(\d{10,22})\b/g;

export function extractUtrFromSms(sms: string | undefined | null): string | null {
  if (!sms) return null;
  const text = String(sms);
  const k = text.match(KEYWORD_RE);
  if (k?.[1]) return k[1].toUpperCase();
  // pick longest numeric token (usually the UTR vs amount/date)
  let best: string | null = null;
  const matches = text.match(LOOSE_RE) || [];
  for (const m of matches) {
    if (m.length < 10 || m.length > 22) continue;
    // avoid mobile numbers (10-digit starting with 6-9 commonly are mobiles)
    if (m.length === 10 && /^[6-9]/.test(m)) continue;
    if (!best || m.length > best.length) best = m;
  }
  return best;
}

// ---- React hook -------------------------------------------------------------------
export type UtrSmsEvent = { utr: string; fullSms: string };

/**
 * Starts the SMS User Consent listener while `enabled` is true.
 * Calls `onUtr` when the user shares an SMS that contains a parseable UTR.
 * On unmount or when `enabled` flips false, stops listening.
 */
export function useSmsUtrListener(
  enabled: boolean,
  onUtr: (event: UtrSmsEvent) => void,
  onError?: (err: any) => void,
) {
  const [listening, setListening] = useState(false);
  const onUtrRef = useRef(onUtr);
  const onErrRef = useRef(onError);
  useEffect(() => { onUtrRef.current = onUtr; }, [onUtr]);
  useEffect(() => { onErrRef.current = onError; }, [onError]);

  useEffect(() => {
    if (!enabled || !isSmsConsentAvailable() || !SMS) {
      setListening(false);
      return;
    }
    let stopSms: (() => void) | null = null;
    let stopErr: (() => void) | null = null;
    try {
      stopSms = SMS.startSmsHandling((event) => {
        const sms = event?.sms || "";
        const utr = extractUtrFromSms(sms);
        if (utr) onUtrRef.current?.({ utr, fullSms: sms });
      });
      if (SMS.addErrorListener) {
        stopErr = SMS.addErrorListener((err) => {
          // CONSENT_TIMEOUT and CONSENT_CANCELED are expected and noisy — swallow them.
          const payload = (err && typeof err === "object") ? Object.keys(err)[0] : "";
          if (payload === "CONSENT_TIMEOUT" || payload === "CONSENT_CANCELED") return;
          onErrRef.current?.(err);
        });
      }
      setListening(true);
    } catch (e) {
      onErrRef.current?.(e);
      setListening(false);
    }
    return () => {
      try { stopSms && stopSms(); } catch {}
      try { stopErr && stopErr(); } catch {}
      setListening(false);
    };
  }, [enabled]);

  return { listening, supported: isSmsConsentAvailable() };
}
