/**
 * Where a freshly signed-in user lands. Shared by the Google sign-in button,
 * the Google redirect handler, the mobile-OTP sign-in and app/index.tsx.
 *
 * Nov-2026 — the ₹118 registration gate is gone. Nobody is sent to a payment
 * screen after signing in. A Google account with no mobile number yet is sent
 * once to /verify-mobile, which confirms the number over WhatsApp.
 */
import { router } from "expo-router";
import { adminLanding } from "./admin-roles";

export function routeAfterAuth(u: any): void {
  if (!u) return;
  if (u.role === "admin") {
    router.replace(adminLanding(u));
  } else if (u.is_delivery_partner_approved) {
    // Approved riders get their own workspace — no Shop, no Services.
    router.replace("/delivery/dashboard" as any);
  } else if (u.is_vendor && u.is_vendor_approved) {
    // Oct-2026 — Shop and Services are hidden for sellers, so landing them
    // on /shop dropped them on a tab that isn't in their bar. Their home is
    // the Vendor panel.
    router.replace("/vendor/dashboard" as any);
  } else if (!u.phone) {
    router.replace("/verify-mobile" as any);
  } else {
    router.replace("/(tabs)/shop");
  }
}
