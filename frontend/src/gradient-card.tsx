import { LinearGradient } from "expo-linear-gradient";
import { View, Text, StyleSheet, ViewStyle, StyleProp } from "react-native";
import { ReactNode } from "react";
import { colors, radii } from "./theme";

export type GradientCardProps = {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  variant?: "primary" | "emerald" | "sunset" | "royal" | "midnight";
  rounded?: number;
  withDecor?: boolean; // adds soft circular blob on top-right
};

// Curated gradient palettes — premium, modern, brandable
const GRADIENTS: Record<NonNullable<GradientCardProps["variant"]>, [string, string, string]> = {
  primary: ["#143D2E", "#1F5E45", "#2C6B50"],         // earthy green (default)
  emerald: ["#0D5C4A", "#177B5C", "#3DB082"],          // bright emerald
  sunset:  ["#E57A44", "#FF9966", "#FFB88C"],          // warm orange peach
  royal:   ["#1E3A8A", "#2563EB", "#3B82F6"],          // royal blue
  midnight:["#0F172A", "#1E293B", "#334155"],          // dark navy
};

export function GradientCard({ children, style, variant = "primary", rounded, withDecor = true }: GradientCardProps) {
  const grads = GRADIENTS[variant];
  return (
    <LinearGradient
      colors={grads as any}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={[styles.card, { borderRadius: rounded ?? radii.card }, style]}
    >
      {withDecor && <View style={styles.decor1} />}
      {withDecor && <View style={styles.decor2} />}
      {children}
    </LinearGradient>
  );
}

export function GradientText({ children, style, colors: gradColors }: { children: ReactNode; style?: any; colors?: [string, string] }) {
  // Fallback: simply render in primary color (true gradient text needs MaskedView; keep it simple)
  return <Text style={[{ color: colors.primary, fontWeight: "800" }, style]}>{children}</Text>;
}

const styles = StyleSheet.create({
  card: { padding: 24, overflow: "hidden", position: "relative" },
  decor1: { position: "absolute", width: 180, height: 180, borderRadius: 90, backgroundColor: "rgba(255,255,255,0.07)", top: -60, right: -40 },
  decor2: { position: "absolute", width: 120, height: 120, borderRadius: 60, backgroundColor: "rgba(255,255,255,0.05)", bottom: -30, left: -20 },
});
