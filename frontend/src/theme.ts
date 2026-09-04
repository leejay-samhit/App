// Centralized theme based on design_guidelines.json (Organic & Earthy)
export const colors = {
  background: "#FAF9F6",
  surface: "#FFFFFF",
  surfaceMuted: "#F3F1EC",
  primary: "#143D2E",
  primaryFg: "#FFFFFF",
  accent: "#E57A44",
  accentFg: "#FFFFFF",
  success: "#2E7D52",
  warning: "#D9A05B",
  error: "#B3261E",
  textMain: "#1C2520",
  textMuted: "#6B7280",
  border: "#E5E4E0",
  brand500: "#2C6B50",
  brand100: "#DDE8E2",
};

export const radii = {
  card: 20,
  button: 999,
  input: 14,
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  // Horizontal padding applied at the edge of every screen.
  // Was 24 (felt too "indented" on 390-414 px phones — only ~342 px of usable
  // content). Tightened to 16 to match iOS HIG / Material 3 mobile standard
  // and recover ~16 px (≈5 %) of horizontal real-estate across the whole app.
  // This is the single source of truth — 143 usages downstream pick it up
  // automatically (Shop cards, wallet, profile, admin pages, etc.).
  screen: 16,
  // Phase: Shop visual polish (2026-05-27).
  // Canonical inter-card gutter inside grids/strips. Keeps category circles,
  // product cards, and section dividers visually rhythmic on the same rail.
  // 12 px is the magic number that lets a 2-col grid breathe without making
  // each card narrower than ~155 px on a 390-px phone (`(390 - 16*2 - 12) / 2`).
  gridGap: 12,
  // Vertical breathing room between sections (header → search → categories →
  // banner → product strips). Sits between md (16) and lg (24) so the page
  // scrolls feel rhythmic, not crowded.
  sectionGap: 20,
  // Phase 2B UX polish (2026-05-27).
  // Canonical inner padding for "card" surfaces (KPI tile, balance card,
  // settings row, list-row, etc.). Picked at 16 to match the iOS HIG
  // "regular" inset and keep cards consistent across Wallet / Dashboard /
  // Profile / Admin. Override per-card only when there's a deliberate
  // visual reason (e.g. hero gradient cards still use 24 for prominence).
  cardPad: 16,
  // Inter-card vertical gap inside a related group (e.g. settings rows
  // belonging to the same logical section). Same value as `sm` (8) — kept
  // separate so future tuning doesn't spill into other 8-px usages.
  rowGap: 8,
};

export const formatINR = (n: number) => {
  if (typeof n !== "number") n = Number(n) || 0;
  // Show exact paise (2 decimals) ONLY when the amount has a fractional part —
  // keeps whole rupees clean (e.g. ₹100) and surfaces sub-rupee values that
  // would otherwise display as ₹0 (e.g. ₹0.50, ₹0.25, ₹0.05).
  const hasFraction = Math.abs(n - Math.trunc(n)) >= 0.005;
  return "₹" + n.toLocaleString("en-IN", {
    minimumFractionDigits: hasFraction ? 2 : 0,
    maximumFractionDigits: hasFraction ? 2 : 0,
  });
};

// ---------- Responsive helpers ----------
// Tablet breakpoint: 900 px viewport and above. This keeps the app in its
// native "mobile" layout even when viewed in landscape on a phone (which can
// be ~800-900 px wide) or in Chrome on a narrow desktop window — prevents the
// tab bar / content from being squeezed into a tiny centered column.
export const TABLET_MIN_WIDTH = 900;
// Above this width, content is centered in a single readable column (~480 px)
// so it doesn't stretch edge-to-edge on iPads, foldables, and large tablets.
export const READABLE_MAX_WIDTH = 480;

import { useWindowDimensions, ViewStyle } from "react-native";

/** Returns true when the viewport is tablet-sized (>= 900 px). */
export function useIsTablet(): boolean {
  const { width } = useWindowDimensions();
  return width >= TABLET_MIN_WIDTH;
}

/**
 * Style spread that constrains a FORM-style screen (login, register,
 * payment) to a centred, readable column on tablets / desktop.
 *
 * Jun 2026 — the app no longer wraps everything in a fake phone frame, so
 * single-column form screens would otherwise stretch edge-to-edge on a
 * 12-inch tablet. Content-heavy screens (shop grid, layout blocks) are
 * deliberately NOT constrained — they adapt their column count instead.
 */
export function useResponsiveContainer(): ViewStyle {
  const { width } = useWindowDimensions();
  if (width >= 768) {
    return {
      maxWidth: 560,
      alignSelf: "center",
      width: "100%",
    };
  }
  return { width: "100%" };
}
