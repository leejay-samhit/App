/**
 * Festival decoration layer (Oct-2026).
 *
 * The palette half of a festival theme rides on the existing branding colours.
 * THIS file is the artwork half: lightweight, drawn-in-app decorations
 * (react-native-svg + a gradient) plus the optional AI-generated banner.
 *
 * Everything here reads the live branding at RENDER time, so a theme change
 * repaints these without any app restart.
 *
 * Nothing in here changes behaviour — it is purely decorative and renders
 * `null` whenever no festival theme is active.
 */
import React from "react";
import { Image, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Svg, { Circle, G, Path } from "react-native-svg";
import Constants from "expo-constants";
import { useBranding, useFestival } from "./branding";
import { FestivalIcon } from "./festival-icons";
import { colors, radii, spacing } from "./theme";

const API_BASE =
  (process.env.EXPO_PUBLIC_BACKEND_URL as string) ||
  (Constants.expoConfig?.extra as any)?.backendUrl ||
  "";

function artworkUrl(path?: string): string | null {
  if (!path) return null;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return API_BASE ? `${API_BASE.replace(/\/$/, "")}${path}` : null;
}

/** A single drawn decoration for the active festival. */
function Diya({ size = 34, tint, glow, pattern }: { size?: number; tint: string; glow: string; pattern?: string }) {
  return <FestivalIcon pattern={pattern} size={size} tint={tint} glow={glow} />;
}

/** Decorative rangoli arc used behind headers. */
function RangoliArc({ width, color }: { width: number; color: string }) {
  const petals = Array.from({ length: 12 });
  return (
    <Svg width={width} height={70} viewBox="0 0 300 70">
      <G opacity={0.4}>
        {petals.map((_, i) => {
          const x = 150 + Math.cos((Math.PI * i) / 11 + Math.PI) * 140;
          const y = 66 + Math.sin((Math.PI * i) / 11 + Math.PI) * 44;
          return <Circle key={i} cx={x} cy={Math.abs(y)} r={3.2} fill={color} />;
        })}
        <Path d="M10 66 Q150 2 290 66" stroke={color} strokeWidth={2} fill="none" />
      </G>
    </Svg>
  );
}

/**
 * Thin festive strip for screen headers / section tops.
 * Renders nothing when no festival theme is active.
 */
export function FestivalStrip({ compact }: { compact?: boolean }) {
  const festival = useFestival();
  const { width } = useWindowDimensions();
  if (!festival) return null;
  const decor = festival.decor || {};
  const glow = decor.glow_color || colors.warning;
  const tint = decor.decor_tint || colors.accent;
  const count = Math.max(3, Math.min(6, Math.floor(width / 90)));

  return (
    <View style={[stripStyles.wrap, compact && { paddingVertical: 4 }]} pointerEvents="none" testID="festival-strip">
      {decor.rangoli ? (
        <View style={stripStyles.rangoli}>
          <RangoliArc width={width} color={tint} />
        </View>
      ) : null}
      <View style={stripStyles.diyas}>
        {Array.from({ length: count }).map((_, i) => (
          <Diya key={i} size={compact ? 22 : 28} tint={tint} glow={glow} pattern={decor.pattern} />
        ))}
      </View>
    </View>
  );
}

/**
 * Full festival banner for the Shop home / promotional slots.
 * Uses the AI-generated artwork when the admin has produced it, and falls
 * back to the drawn decoration so the theme never shows a broken image.
 */
export function FestivalBanner() {
  const festival = useFestival();
  const { gradient } = useBranding();
  const { width } = useWindowDimensions();
  if (!festival) return null;

  const decor = festival.decor || {};
  const art = artworkUrl(festival.artwork?.banner);
  const glow = decor.glow_color || colors.warning;
  const tint = decor.decor_tint || colors.accent;
  const diyaCount = Math.max(4, Math.min(7, Math.floor(width / 70)));

  // Nov-2026 (req 17) — heading, subtitle and layout are editable from
  // Admin → Branding → Festival Themes. Anything the admin leaves blank falls
  // back to the festival's own wording, and the height is clamped so the
  // banner can never eat the screen again.
  const copy = (festival as any).banner_text || {};
  const align: "left" | "center" | "right" = copy.align || "left";
  const bannerHeight = Math.max(84, Math.min(Number(copy.height) || 112, 200));

  return (
    <View style={bannerStyles.wrap} testID="festival-banner">
      <LinearGradient
        colors={[gradient?.start || "#190A33", gradient?.middle || "#3B1178", gradient?.end || "#7C2D12"]}
        start={{ x: 0, y: 0 }}
        end={{ x: 1, y: 1 }}
        style={[bannerStyles.grad, { height: bannerHeight }]}
      >
        {art ? (
          <Image source={{ uri: art }} style={bannerStyles.art} resizeMode="cover" />
        ) : null}
        <View style={[bannerStyles.inner, { alignItems: align === "center" ? "center" : align === "right" ? "flex-end" : "flex-start" }]}>
          <Text
            style={[
              bannerStyles.title,
              { color: copy.title_color || glow, textAlign: align },
              copy.title_size ? { fontSize: copy.title_size } : null,
            ]}
            numberOfLines={1}
          >
            {copy.title || decor.banner_title || festival.name}
          </Text>
          <Text
            style={[
              bannerStyles.sub,
              { textAlign: align },
              copy.subtitle_color ? { color: copy.subtitle_color } : null,
              copy.subtitle_size ? { fontSize: copy.subtitle_size } : null,
            ]}
            numberOfLines={2}
          >
            {copy.subtitle || decor.banner_subtitle || `Celebrate ${festival.name} with us`}
          </Text>
        </View>
        <View style={bannerStyles.diyaRow} pointerEvents="none">
          {Array.from({ length: diyaCount }).map((_, i) => (
            <Diya key={i} size={30} tint={tint} glow={glow} pattern={decor.pattern} />
          ))}
        </View>
      </LinearGradient>
    </View>
  );
}

/**
 * Small festive corner mark for cards / headers — one diya + a soft glow.
 * Deliberately subtle so product cards stay readable.
 */
export function FestivalMark({ size = 22 }: { size?: number }) {
  const festival = useFestival();
  if (!festival) return null;
  const decor = festival.decor || {};
  return (
    <View pointerEvents="none" testID="festival-mark">
      <Diya size={size} tint={decor.decor_tint || colors.accent} glow={decor.glow_color || colors.warning} pattern={decor.pattern} />
    </View>
  );
}

const stripStyles = StyleSheet.create({
  wrap: { paddingVertical: 6, alignItems: "center", justifyContent: "center" },
  rangoli: { position: "absolute", top: -6, left: 0, right: 0, alignItems: "center" },
  diyas: { flexDirection: "row", alignItems: "flex-end", justifyContent: "center", gap: 18 },
});

const bannerStyles = StyleSheet.create({
  wrap: {
    marginHorizontal: spacing.screen,
    borderRadius: radii.card,
    overflow: "hidden",
  },
  // Nov 2026 — the text block used to be pushed to the bottom with the
  // decorations stacked under it, leaving a big empty band across the top.
  // Now the text is vertically centered and the decoration row is pinned to
  // the bottom edge, so the banner fills evenly at any width.
  grad: { justifyContent: "center" },
  art: { ...StyleSheet.absoluteFillObject, opacity: 0.55 },
  inner: { paddingHorizontal: spacing.cardPad, paddingBottom: 22 },
  title: { fontSize: 19, fontWeight: "900", letterSpacing: 0.3 },
  sub: { color: "#F3E8FF", fontSize: 13, fontWeight: "600", marginTop: 2, lineHeight: 18 },
  diyaRow: {
    position: "absolute", bottom: 6, left: 0, right: 0,
    flexDirection: "row", alignItems: "flex-end", justifyContent: "space-around",
    paddingHorizontal: 8,
  },
});
