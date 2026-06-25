/**
 * WhatsApp click-to-chat helpers.
 *
 * Uses WhatsApp's free wa.me URL scheme — no API key, no Meta approval
 * needed. Works on iOS, Android, and the mobile web.
 *
 *   https://wa.me/<phone>?text=<encoded>
 *
 * Falls back to a sensible alert when WhatsApp isn't installed.
 */

import { Alert, Linking, Platform } from "react-native";

/**
 * Admin's support WhatsApp number (E.164 without "+" — wa.me expects this).
 * 2026-06-10: Hard-coded to the number the admin shared. To make this
 * editable, expose it via `/api/branding.support_whatsapp` and read from
 * `useBranding()` — the WhatsAppButton component below already does that.
 */
export const DEFAULT_SUPPORT_WHATSAPP = "919154735888";

/**
 * Build a wa.me URL with an optional pre-filled message.
 *
 * `phone` may be passed with country code prefixes ("+91 91547 35888",
 * "91-91547 35888", etc.) — we strip everything but digits.
 */
export function buildWhatsAppURL(message: string, phone?: string | null): string {
  const digits = String(phone || DEFAULT_SUPPORT_WHATSAPP).replace(/\D+/g, "");
  // If somebody passes a 10-digit Indian number assume +91, since the
  // user explicitly enrolled the admin's IN number in our setup.
  const e164 = digits.length === 10 ? `91${digits}` : digits;
  const encoded = encodeURIComponent(message || "");
  return `https://wa.me/${e164}${encoded ? `?text=${encoded}` : ""}`;
}

/**
 * Open WhatsApp (or browser → wa.me) with the given prefilled message.
 * Returns true on success, false if WhatsApp can't open.
 */
export async function openWhatsApp(message: string, phone?: string | null): Promise<boolean> {
  const url = buildWhatsAppURL(message, phone);
  try {
    const supported = await Linking.canOpenURL(url);
    if (!supported && Platform.OS !== "web") {
      // Web canOpenURL is unreliable, but on native it accurately reflects
      // whether WhatsApp can handle the link.
      Alert.alert(
        "WhatsApp not installed",
        "Please install WhatsApp from the Play Store / App Store and try again.",
      );
      return false;
    }
    await Linking.openURL(url);
    return true;
  } catch (e) {
    Alert.alert("Couldn't open WhatsApp", "Please try again, or message us directly at +91 9154735888.");
    return false;
  }
}

/**
 * Build the standard "Hi Slangcart" welcome message using the user's
 * profile fields. Falls back to safe placeholders so we never produce
 * "Hi Slangcart, I just registered as undefined."
 */
export function buildWelcomeMessage(opts: {
  name?: string | null;
  referral_code?: string | null;
  app_name?: string | null;
}): string {
  const name = (opts.name || "a new user").trim();
  const code = (opts.referral_code || "—").trim();
  const app  = (opts.app_name || "Slangcart").trim();
  return `Hi ${app}, I just registered as ${name}. Looking forward to getting started! My referral code: ${code}`;
}
