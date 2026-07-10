/**
 * Onboarding Terms — mobile mirror of the web `frontend/src/lib/onboardingTerms.js`.
 *
 * Design (spec: MOBILE_ONBOARDING_TERMS_SPEC.md v1.0.0):
 *   1. Attempt to fetch admin-editable copy from `GET /api/admin/settings`,
 *      reading `onboarding_terms.{vendor, service_provider}`.
 *   2. If the backend hasn't shipped the field yet (or the payload doesn't
 *      round-trip cleanly), fall back to the DEFAULTS baked in below.
 *   3. Everything is exported as a small helper so the two apply screens
 *      stay lean.
 *
 * The default text is copied 1:1 from what slangcart.com currently renders
 * on the /become-vendor and /become-provider pages (10-12 numbered clauses
 * each + a short "Declaration" block).  Any future CMS edit on the web side
 * will silently override these locally-baked strings for the mobile client.
 */

import { api } from "./api";

export type OnboardingTermsBlock = {
  version: string;
  effective_date: string;   // YYYY-MM-DD
  title: string;
  intro: string;
  clauses: string[];
  declaration_title: string;
  declaration_body: string;
  agree_label: string;
  role: "vendor" | "service_provider";
};

export type AcceptedTerms = {
  role: "vendor" | "service_provider";
  version: string;
  accepted_at: string;      // ISO 8601
  title: string;
};

// ── Baked-in fallback ─────────────────────────────────────────────────
export const VENDOR_TERMS_FALLBACK: OnboardingTermsBlock = {
  role: "vendor",
  version: "1.0.0",
  effective_date: "2026-07-04",
  title: "Vendor Declaration & GST Compliance Agreement",
  intro: `By selecting "I Agree" and registering as a vendor on Slangcart, I declare and agree that:`,
  clauses: [
    "I confirm that all information provided during registration is true, complete, and accurate.",
    "I understand that I am solely responsible for complying with all applicable laws, including GST, income tax, business licensing, and any other statutory requirements.",
    "If I am required to obtain GST registration under applicable law, I agree to obtain and maintain a valid GSTIN and update my Slangcart account without delay.",
    "If I am currently not GST registered, I declare that I am legally eligible to operate without GST registration. I agree to obtain GST registration immediately if I become legally required to do so.",
    "I acknowledge that any incorrect declaration, false information, or failure to comply with tax laws is my sole responsibility.",
    "I agree to indemnify and hold Slangcart harmless from any loss, penalty, tax demand, interest, or legal action arising from false information or my failure to comply with applicable laws.",
    "I authorize Slangcart to suspend payouts, temporarily restrict my account, or terminate my vendor account if false information or non-compliance is identified.",
    "I agree to provide any documents reasonably requested by Slangcart for verification, including PAN, GSTIN (if applicable), bank account details, identity documents, and other business-related documents.",
    "I understand that Slangcart operates as a marketplace platform and that I remain responsible for the products I sell, the invoices I issue (where applicable), taxes, product quality, warranties, and customer obligations under applicable law.",
    "I confirm that I have read, understood, and agree to these Vendor Terms and Conditions and will comply with all applicable laws while using the Slangcart platform.",
  ],
  declaration_title: "Declaration",
  declaration_body:
    "I hereby declare that the information provided by me is true and correct. I understand that providing false information may result in suspension or termination of my account and may attract legal action under applicable laws.",
  agree_label: "I have read, understood and agree to the Vendor Declaration & GST Compliance Agreement.",
};

export const PROVIDER_TERMS_FALLBACK: OnboardingTermsBlock = {
  role: "service_provider",
  version: "1.0.0",
  effective_date: "2026-07-04",
  title: "Service Provider Declaration & Compliance Agreement",
  intro: `By selecting "I Agree" and registering as a Service Provider on Slangcart, I declare and agree that:`,
  clauses: [
    "I confirm that all information provided during registration is true, complete, and accurate.",
    "I am solely responsible for complying with all applicable laws, including GST (where applicable), income tax, professional tax, business licenses, registrations, permits, and any other statutory requirements related to my services.",
    "If I am required by law to obtain GST registration or any other mandatory registration, I agree to obtain and maintain it and update my Slangcart account without delay.",
    "If I am currently not GST registered, I declare that I am legally eligible to provide services without GST registration and will obtain GST registration immediately if it becomes legally mandatory.",
    "I am solely responsible for the quality, safety, pricing, execution, warranty, and completion of the services I offer through Slangcart.",
    "I agree not to upload false, misleading, illegal, prohibited, or fraudulent service listings.",
    "I acknowledge that any incorrect declaration, false information, tax non-compliance, or violation of applicable laws is my sole responsibility.",
    "I agree to indemnify and hold Slangcart harmless from any tax demand, penalty, interest, legal claim, loss, or liability arising from my services, incorrect declarations, or failure to comply with applicable laws.",
    "I authorize Slangcart to verify my information and to request documents such as PAN, GSTIN (if applicable), Aadhaar or other identity documents, bank account details, business registrations, and any other documents reasonably required for verification.",
    "I understand that Slangcart is a marketplace platform that connects customers with independent service providers. Slangcart is not responsible for the services performed by me, and I remain solely responsible for fulfilling my commitments to customers.",
    "I agree that Slangcart may suspend payouts, temporarily restrict my account, or permanently terminate my account if false information, fraud, misuse, or non-compliance with applicable laws is identified.",
    "I confirm that I have read, understood, and agree to these Service Provider Terms and Conditions and will comply with all applicable laws while using the Slangcart platform.",
  ],
  declaration_title: "Declaration",
  declaration_body:
    "I hereby declare that all information and documents submitted by me are true and correct. I understand that providing false information or violating applicable laws may result in suspension or termination of my account, withholding of payouts where legally permitted, and legal action under applicable laws.",
  agree_label: "I have read, understood and agree to the Service Provider Declaration & Compliance Agreement.",
};

// ── Fetch helper ──────────────────────────────────────────────────────
type SettingsPayload = {
  onboarding_terms?: {
    vendor?: Partial<OnboardingTermsBlock>;
    service_provider?: Partial<OnboardingTermsBlock>;
  };
};

/**
 * Merge a partial CMS payload into the local fallback so a half-populated
 * onboarding_terms (e.g. body updated but effective_date left blank) still
 * renders a valid panel.  Missing fields cascade to the fallback value.
 */
function mergeBlock(
  fallback: OnboardingTermsBlock,
  patch?: Partial<OnboardingTermsBlock>,
): OnboardingTermsBlock {
  if (!patch || typeof patch !== "object") return fallback;
  return {
    ...fallback,
    ...patch,
    // Deep-safe merge for lists — never fall back to an accidentally-empty
    // clauses array from the CMS (which would render a blank agreement).
    clauses: Array.isArray(patch.clauses) && patch.clauses.length > 0
      ? patch.clauses.map(String).filter(Boolean)
      : fallback.clauses,
  };
}

/**
 * Fetch the LATEST onboarding terms for both roles.  Silent fallback to
 * the baked-in defaults on any failure so the apply screens NEVER show
 * a spinner blocking the T&C panel.
 */
export async function fetchOnboardingTerms(): Promise<{
  vendor: OnboardingTermsBlock;
  service_provider: OnboardingTermsBlock;
}> {
  try {
    const r = await api.get<SettingsPayload>("/admin/settings");
    const cms = r.data?.onboarding_terms || {};
    return {
      vendor: mergeBlock(VENDOR_TERMS_FALLBACK, cms.vendor),
      service_provider: mergeBlock(PROVIDER_TERMS_FALLBACK, cms.service_provider),
    };
  } catch {
    return {
      vendor: VENDOR_TERMS_FALLBACK,
      service_provider: PROVIDER_TERMS_FALLBACK,
    };
  }
}

/** Build the payload block backend expects when the user accepts. */
export function buildAcceptedTerms(block: OnboardingTermsBlock): AcceptedTerms {
  return {
    role: block.role,
    version: block.version,
    accepted_at: new Date().toISOString(),
    title: block.title,
  };
}
