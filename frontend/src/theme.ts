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
  screen: 24,
};

export const formatINR = (n: number) => {
  if (typeof n !== "number") n = Number(n) || 0;
  return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
};

// ---------- Responsive helpers ----------
// Tablet breakpoint: anything >= 600 px viewport (covers iPad mini portrait & up).
export const TABLET_MIN_WIDTH = 600;
// Above this width, content is centered in a single readable column (~600 px) so it
// doesn't stretch edge-to-edge on iPads, foldables, and large tablets.
export const READABLE_MAX_WIDTH = 600;

import { useWindowDimensions, ViewStyle } from "react-native";

/** Returns true when the viewport is tablet-sized (>= 600 px). */
export function useIsTablet(): boolean {
  const { width } = useWindowDimensions();
  return width >= TABLET_MIN_WIDTH;
}

/** Style spread that constrains content to a centered, readable column on tablets.
 *  Drop this onto a screen's outermost <View>/<ScrollView>'s contentContainerStyle. */
export function useResponsiveContainer(): ViewStyle {
  const { width } = useWindowDimensions();
  if (width >= TABLET_MIN_WIDTH) {
    return {
      maxWidth: READABLE_MAX_WIDTH,
      alignSelf: "center",
      width: "100%",
    };
  }
  return { width: "100%" };
}
