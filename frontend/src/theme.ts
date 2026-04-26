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
