import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
// (Platform / StyleSheet no longer needed — system font only.)
// Preload @expo/vector-icons fonts at boot — Expo SDK 54 + new-arch can race
// the runtime font loader and surface "Font file for feather is empty"
// when an icon renders before the font registers. Importing each icon set
// here exposes its `.font` map (e.g. `{ feather: require(...) }`) which we
// pass to `useFonts`.
import Feather from "@expo/vector-icons/Feather";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import Ionicons from "@expo/vector-icons/Ionicons";
// Sep 2026 — the three Google font families (Inter / Poppins / Plus Jakarta)
// were dropped. The app has always shipped with `font: "system"`, yet all
// nine .ttf weights were bundled AND loaded at boot: ~16 MB of package
// weight, nine font assets in the build and a font-loading step in front of
// the first frame. Only the icon fonts are preloaded now.
import { useFonts } from "expo-font";
import { api } from "./api";
import { colors as defaultColors, persistPalette } from "./theme";

export type BrandingTab = { key: string; label: string; icon: string; visible: boolean };

export type Branding = {
  app_name: string;
  tagline: string;
  login_subtitle: string;
  payment_hero: string;
  pending_hero: string;
  colors: typeof defaultColors;
  /** Kept for API compatibility — the app renders in the system font. */
  font: "system";
  tabs: BrandingTab[];
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
  /** Admin-editable WhatsApp support number (digits, country code, no "+"). */
  support_whatsapp?: string;
  // ─── Premium theme extensions (June 2026) ───
  gradient?: {
    start?: string;
    middle?: string;
    end?: string;
    glow?: string;
  };
  button_style?: "rounded" | "pill" | "square";
  home_banner_b64?: string | null;
  // ─── Festival themes (Oct-2026) ───
  /** Null / absent = the normal Slangcart theme. */
  festival?: {
    id: string;
    name: string;
    subtitle?: string;
    icon?: string;
    decor?: {
      pattern?: string;
      sparkles?: boolean;
      rangoli?: boolean;
      glow_color?: string;
      decor_tint?: string;
      banner_title?: string;
      banner_subtitle?: string;
    };
    artwork?: { banner?: string };
  } | null;
  /** Bumped by the backend on every theme change — open apps poll it. */
  theme_version?: number;
};

const DEFAULT_BRANDING: Branding = {
  app_name: "Slangcart",
  tagline: "Track your referrals, earnings and grow your team.",
  login_subtitle: "Sign in to your network",
  payment_hero: "Complete your registration",
  pending_hero: "Awaiting finance approval",
  colors: { ...defaultColors },
  font: "system",
  tabs: [
    { key: "wallet", label: "Wallet", icon: "credit-card", visible: false },
    { key: "dashboard", label: "Dashboard", icon: "home", visible: true },
    { key: "shop", label: "Shop", icon: "shopping-bag", visible: true },
    { key: "services", label: "Services", icon: "briefcase", visible: true },
    { key: "profile", label: "Profile", icon: "user", visible: true },
  ],
  business_name: "Slangcart",
  business_address: "Near Police Station, Beside Ram Mandiram, Valluru",
  business_city: "Cuddapah",
  business_state: "Andhra Pradesh",
  business_pincode: "516293",
  business_gst: "",
  support_email: "support@slangcart.com",
  support_phone: "+91 91547 35888",
  support_whatsapp: "919154735888",
};

// System font everywhere — no custom family to resolve.
const FONT_FAMILY_MAP: Record<string, string | undefined> = { system: undefined };

type Ctx = {
  branding: Branding;
  setBranding: (b: Branding) => void;
  refresh: () => Promise<void>;
  loading: boolean;
  /** Increments whenever the live theme changes; used as a remount key. */
  themeEpoch: number;
};

import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState, View } from "react-native";

// Persisted last-good branding response. Hydrated synchronously-ish on
// BrandingProvider mount so the very first paint already shows the LIVE
// app_name / tagline / colors / logo — instead of flashing the hardcoded
// DEFAULT_BRANDING (e.g. "Slangcart" → "Slangcart").
const BRANDING_CACHE_KEY = "@app/brandingV1";

const BrandingContext = createContext<Ctx | undefined>(undefined);

export function BrandingProvider({ children }: { children: React.ReactNode }) {
  const [branding, setBrandingState] = useState<Branding>(DEFAULT_BRANDING);
  const [loading, setLoading] = useState(true);
  // Oct-2026 festival themes — bumped when the live theme_version moves so the
  // tree below can remount and repaint with the new palette.
  const [themeEpoch, setThemeEpoch] = useState(0);
  // Gates the first render until the cached palette has been applied.
  const [hydrated, setHydrated] = useState(false);
  const seenVersion = useRef<number>(0);

  // Load the trimmed weights so they're ready when the user picks a font.
  useFonts({
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
    // ...and mirror it into synchronous storage so the NEXT launch builds every
    // StyleSheet from this palette instead of the factory one.
    persistPalette(next);
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
      // Festival/theme change detection — a moved theme_version means an admin
      // applied or cleared a theme, so repaint the tree below.
      const v = Number(merged.theme_version || 0);
      if (seenVersion.current && v > seenVersion.current) setThemeEpoch((n) => n + 1);
      seenVersion.current = v;
      // Persist for next launch so first paint already shows LIVE branding.
      try { await AsyncStorage.setItem(BRANDING_CACHE_KEY, JSON.stringify(merged)); } catch { /* quota */ }
    } catch {
      // keep defaults (or cached if we already hydrated)
    } finally {
      setLoading(false);
    }
  }, [setBranding]);

  useEffect(() => {
    // Hydrate from cache BEFORE rendering any screen. Screen modules build
    // their StyleSheets from `colors` the first time they are required, and
    // a StyleSheet snapshots the colour values it reads — so anything that
    // mounts before the live palette is applied keeps the factory green for
    // the rest of the session (visible as stray green buttons under a
    // festival theme). Gating the first render on this read is a few ms and
    // the splash overlay already covers the launch frames.
    (async () => {
      let hadCache = false;
      try {
        const cached = await AsyncStorage.getItem(BRANDING_CACHE_KEY);
        if (cached) {
          const parsed = JSON.parse(cached) as Branding;
          if (parsed && parsed.app_name) { setBranding(parsed); hadCache = true; }
        }
      } catch { /* cache miss / parse error – fall back to DEFAULT_BRANDING */ }

      if (hadCache) {
        // Palette already applied — paint now, reconcile in the background.
        setHydrated(true);
        refresh();
      } else {
        // First-ever launch: there is no cached palette, so wait briefly for
        // the live one. Without this the screens mount on the factory colours
        // and keep them for the session. Capped so an offline first launch
        // still reaches the app.
        await Promise.race([
          refresh(),
          new Promise((res) => setTimeout(res, 2500)),
        ]);
        setHydrated(true);
      }
    })();
  }, [refresh, setBranding]);

  // ── Live theme propagation (Oct-2026) ──────────────────────────────────
  // Poll the tiny /festival-theme/active payload so an applied festival theme
  // reaches already-open apps, and re-check whenever the app comes back to
  // the foreground. Only a changed version triggers the full /branding fetch.
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get<{ theme_version?: number }>("/festival-theme/active");
        const v = Number(data?.theme_version || 0);
        if (alive && v && v !== seenVersion.current) refresh();
      } catch { /* offline — try again on the next tick */ }
    };
    const timer = setInterval(check, 45000);
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") check(); });
    return () => { alive = false; clearInterval(timer); sub.remove(); };
  }, [refresh]);

  const value = useMemo<Ctx>(
    () => ({ branding, setBranding, refresh, loading, themeEpoch }),
    [branding, setBranding, refresh, loading, themeEpoch],
  );
  return (
    <BrandingContext.Provider value={value}>
      {hydrated ? children : <View style={{ flex: 1, backgroundColor: branding.colors.background }} />}
    </BrandingContext.Provider>
  );
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

/** Remount key — changes whenever the live theme changes. */
export function useThemeEpoch(): number {
  return useContext(BrandingContext)?.themeEpoch ?? 0;
}

/** The active festival theme, or null for the normal Slangcart look. */
export function useFestival(): NonNullable<Branding["festival"]> | null {
  const { festival } = useBranding();
  return festival && festival.id ? festival : null;
}

/** Returns the active font-family string (or undefined for system default). */
export function useFontFamily(): string | undefined {
  const { font } = useBranding();
  return FONT_FAMILY_MAP[font];
}

/** Helper to get a typed StyleSheet that automatically applies the active font.
 *  Usage: const styles = useThemedStyles(() => StyleSheet.create({ ... })) */
