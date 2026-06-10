import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Platform, StyleSheet } from "react-native";
// Preload @expo/vector-icons fonts at boot — Expo SDK 54 + new-arch can race
// the runtime font loader and surface "Font file for feather is empty"
// when an icon renders before the font registers. Importing each icon set
// here exposes its `.font` map (e.g. `{ feather: require(...) }`) which we
// pass to `useFonts` alongside the Google fonts.
import Feather from "@expo/vector-icons/Feather";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import Ionicons from "@expo/vector-icons/Ionicons";
// Trimmed to 3 weights per font (400/600/800) — drops ~40% of the bundled font assets
// while still covering Body / Heading / ExtraBold use cases throughout the app.
import {
  useFonts as useInter,
  Inter_400Regular,
  Inter_600SemiBold,
  Inter_800ExtraBold,
} from "@expo-google-fonts/inter";
import {
  Poppins_400Regular,
  Poppins_600SemiBold,
  Poppins_800ExtraBold,
} from "@expo-google-fonts/poppins";
import {
  PlusJakartaSans_400Regular,
  PlusJakartaSans_600SemiBold,
  PlusJakartaSans_800ExtraBold,
} from "@expo-google-fonts/plus-jakarta-sans";
import { api } from "./api";
import { colors as defaultColors } from "./theme";

export type BrandingTab = { key: string; label: string; icon: string; visible: boolean };

export type Branding = {
  app_name: string;
  tagline: string;
  login_subtitle: string;
  payment_hero: string;
  pending_hero: string;
  colors: typeof defaultColors;
  font: "system" | "inter" | "poppins" | "jakarta" | "manrope" | "dmsans";
  tabs: BrandingTab[];
  // ─── Splash overlay (Feb-2026) ───
  splash_image?: string | null;
  splash_duration_ms?: number;
  splash_bg?: string;
  // ─── Payment methods config (Feb-2026) ───
  payment_methods?: {
    razorpay_enabled?: boolean;
    upi_manual_enabled?: boolean;
    payee_upi_id?: string;
    payee_name?: string;
  };
  // Legal / business info (shown on Legal pages & used by payment gateway KYC)
  business_name?: string;
  business_address?: string;
  business_city?: string;
  business_state?: string;
  business_pincode?: string;
  business_gst?: string;
  support_email?: string;
  support_phone?: string;
  // ─── Premium theme extensions (June 2026) ───
  gradient?: {
    start?: string;
    middle?: string;
    end?: string;
    glow?: string;
  };
  button_style?: "rounded" | "pill" | "square";
  home_banner_b64?: string | null;
};

const DEFAULT_BRANDING: Branding = {
  app_name: "NetworkPay",
  tagline: "Track your referrals, earnings and grow your team.",
  login_subtitle: "Sign in to your network",
  payment_hero: "Complete your registration",
  pending_hero: "Awaiting finance approval",
  colors: { ...defaultColors },
  font: "system",
  tabs: [
    { key: "network", label: "Network", icon: "git-branch", visible: false },
    { key: "wallet", label: "Wallet", icon: "credit-card", visible: false },
    { key: "dashboard", label: "Dashboard", icon: "home", visible: true },
    { key: "shop", label: "Shop", icon: "shopping-bag", visible: true },
    { key: "services", label: "Services", icon: "briefcase", visible: true },
    { key: "profile", label: "Profile", icon: "user", visible: true },
  ],
  business_name: "Network RuPay Solutions Pvt Ltd",
  business_address: "Near Police Station, Beside Ram Mandiram, Valluru",
  business_city: "Cuddapah",
  business_state: "Andhra Pradesh",
  business_pincode: "516293",
  business_gst: "",
  support_email: "support@networkrupay.com",
  support_phone: "+91 91547 35888",
};

const FONT_FAMILY_MAP: Record<Branding["font"], string | undefined> = {
  system: undefined,
  inter: "Inter_600SemiBold",
  poppins: "Poppins_600SemiBold",
  jakarta: "PlusJakartaSans_600SemiBold",
  manrope: undefined, // can be added later
  dmsans: undefined, // can be added later
};

type Ctx = {
  branding: Branding;
  setBranding: (b: Branding) => void;
  refresh: () => Promise<void>;
  loading: boolean;
};

import AsyncStorage from "@react-native-async-storage/async-storage";

// Persisted last-good branding response. Hydrated synchronously-ish on
// BrandingProvider mount so the very first paint already shows the LIVE
// app_name / tagline / colors / logo — instead of flashing the hardcoded
// DEFAULT_BRANDING (e.g. "NetworkPay" → "NetworkRupay").
const BRANDING_CACHE_KEY = "@app/brandingV1";

const BrandingContext = createContext<Ctx | undefined>(undefined);

export function BrandingProvider({ children }: { children: React.ReactNode }) {
  const [branding, setBrandingState] = useState<Branding>(DEFAULT_BRANDING);
  const [loading, setLoading] = useState(true);

  // Load the trimmed weights so they're ready when the user picks a font.
  const [fontsLoaded] = useInter({
    Inter_400Regular,
    Inter_600SemiBold,
    Inter_800ExtraBold,
    Poppins_400Regular,
    Poppins_600SemiBold,
    Poppins_800ExtraBold,
    PlusJakartaSans_400Regular,
    PlusJakartaSans_600SemiBold,
    PlusJakartaSans_800ExtraBold,
    // Icon fonts — preload to avoid the Expo SDK 54 race condition where the
    // first <Feather/> render happens before the font asset registers.
    ...((Feather as any).font || {}),
    ...((MaterialCommunityIcons as any).font || {}),
    ...((Ionicons as any).font || {}),
  });

  const applyToColors = (next: Branding["colors"]) => {
    // Mutate the singleton colors object so existing screens that import { colors } pick up
    // the new values on their next render.
    Object.assign(defaultColors, next);
  };

  const setBranding = useCallback((b: Branding) => {
    setBrandingState(b);
    applyToColors(b.colors);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<Branding>("/branding");
      const merged: Branding = {
        ...DEFAULT_BRANDING,
        ...data,
        colors: { ...DEFAULT_BRANDING.colors, ...(data?.colors || {}) },
        tabs: Array.isArray(data?.tabs) && data.tabs.length ? data.tabs : DEFAULT_BRANDING.tabs,
      };
      setBranding(merged);
      // Persist for next launch so first paint already shows LIVE branding.
      try { await AsyncStorage.setItem(BRANDING_CACHE_KEY, JSON.stringify(merged)); } catch { /* quota */ }
    } catch {
      // keep defaults (or cached if we already hydrated)
    } finally {
      setLoading(false);
    }
  }, [setBranding]);

  useEffect(() => {
    // Hydrate from cache synchronously-ish so the very first paint already
    // shows the LIVE app_name / tagline / colors. Then refresh from the API
    // in parallel — by the time the request resolves, we silently swap to
    // the freshest values (usually identical, so no visual change).
    (async () => {
      try {
        const cached = await AsyncStorage.getItem(BRANDING_CACHE_KEY);
        if (cached) {
          const parsed = JSON.parse(cached) as Branding;
          if (parsed && parsed.app_name) setBranding(parsed);
        }
      } catch { /* cache miss / parse error – fall back to DEFAULT_BRANDING */ }
      refresh();
    })();
  }, [refresh, setBranding]);

  // Apply the chosen font globally. We override default styles for Text via
  // a one-time monkey-patch on StyleSheet (works for RN out of the box).
  useEffect(() => {
    const fam = FONT_FAMILY_MAP[branding.font];
    // Use setNativeProps via Text default — see below in `useFontFamily()` hook.
    // No-op here; consumers can use useFontFamily() to get the active family.
    return () => undefined;
  }, [branding.font, fontsLoaded]);

  const value = useMemo<Ctx>(() => ({ branding, setBranding, refresh, loading }), [branding, setBranding, refresh, loading]);
  return <BrandingContext.Provider value={value}>{children}</BrandingContext.Provider>;
}

export function useBranding(): Branding {
  const ctx = useContext(BrandingContext);
  return ctx?.branding ?? DEFAULT_BRANDING;
}

export function useBrandingActions() {
  const ctx = useContext(BrandingContext);
  if (!ctx) throw new Error("useBrandingActions must be inside BrandingProvider");
  return { setBranding: ctx.setBranding, refresh: ctx.refresh, loading: ctx.loading };
}

/** Returns the active font-family string (or undefined for system default). */
export function useFontFamily(): string | undefined {
  const { font } = useBranding();
  return FONT_FAMILY_MAP[font];
}

/** Helper to get a typed StyleSheet that automatically applies the active font.
 *  Usage: const styles = useThemedStyles(() => StyleSheet.create({ ... })) */
export const FONT_OPTIONS: { key: Branding["font"]; label: string }[] = [
  { key: "system", label: "System default" },
  { key: "inter", label: "Inter" },
  { key: "poppins", label: "Poppins" },
  { key: "jakarta", label: "Plus Jakarta Sans" },
];
