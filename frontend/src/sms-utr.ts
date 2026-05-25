// Platform fallback (web / iOS) — SMS User Consent only ships on Android.
// Metro automatically prefers `sms-utr.android.ts` on Android builds.
export const isSmsConsentAvailable = (): boolean => false;

export function extractUtrFromSms(_sms: string | undefined | null): string | null {
  return null;
}

export type UtrSmsEvent = { utr: string; fullSms: string };

export function useSmsUtrListener(
  _enabled: boolean,
  _onUtr: (event: UtrSmsEvent) => void,
  _onError?: (err: any) => void,
) {
  return { listening: false, supported: false };
}
