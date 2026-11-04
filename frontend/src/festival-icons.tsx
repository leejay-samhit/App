/**
 * Festival icons — a small registry of react-native-svg decorations.
 *
 * Each festival names an `icon` in `core/festival_themes.py`; this file maps
 * that name to a drawn icon so the strip, the banner and the corner mark
 * don't repeat the same diya for every festival. Drawn, not downloaded:
 * zero network, zero storage, and they repaint the instant the theme changes.
 */
import React from "react";
import Svg, { Circle, Ellipse, G, Line, Path, Rect } from "react-native-svg";
import { withAlpha } from "./theme";

export type IconProps = { size: number; tint: string; glow: string };

/** A single lit clay diya, drawn to scale. */
function DiyaIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      {/* flame glow */}
      <Ellipse cx="32" cy="22" rx="11" ry="14" fill={glow} opacity={0.22} />
      {/* flame */}
      <Path d="M32 10c5 7 7 10 7 15a7 7 0 0 1-14 0c0-5 2-8 7-15z" fill={glow} />
      <Path d="M32 18c2.4 3.4 3.4 5 3.4 7.3a3.4 3.4 0 0 1-6.8 0c0-2.3 1-3.9 3.4-7.3z" fill="#FFF7E0" opacity={0.9} />
      {/* clay bowl */}
      <Path d="M12 42h40c0 8-9 13-20 13S12 50 12 42z" fill={tint} />
      <Path d="M12 42h40a3 3 0 0 1-3 3H15a3 3 0 0 1-3-3z" fill="#FFFFFF" opacity={0.25} />
    </Svg>
  );
}

/** Ugadi — a fresh mango leaf over a pot. */
function UgadiIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      {/* soft glow behind */}
      <Circle cx="32" cy="34" r="24" fill={glow} opacity={0.18} />
      {/* mango leaf */}
      <Path d="M32 8c10 6 15 14 15 24a15 15 0 0 1-30 0c0-10 5-18 15-24z" fill={tint} />
      {/* leaf veins */}
      <Path d="M32 12v30M24 22l8 7 8-7" stroke={glow} strokeWidth={2} fill="none" opacity={0.7} strokeLinecap="round" />
      {/* kalasha pot */}
      <Path d="M20 46h24c2 0 3 1 3 3 0 7-7 11-15 11s-15-4-15-11c0-2 1-3 3-3z" fill={glow} />
      <Rect x="18" y="44" width="28" height="3" rx="1.5" fill={tint} />
    </Svg>
  );
}

/** Independence Day — the Tiranga as a shield, Ashoka Chakra at its centre. */
function TirangaIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="32" r="22" fill={withAlpha(glow, 0.16)} />
      {/* shield */}
      <Path d="M32 12l16 6v12c0 11-7 19-16 22-9-3-16-11-16-22V18z" fill="#FFFFFF" stroke={withAlpha(tint, 0.55)} strokeWidth={2} />
      {/* saffron band */}
      <Path d="M32 12l16 6v7H16v-7z" fill="#FF9933" />
      {/* green band */}
      <Path d="M16 32v-2h32v2c0 9-5 17-16 20-11-3-16-11-16-20z" fill="#138808" />
      {/* chakra */}
      <Circle cx="32" cy="28.5" r="6" stroke="#0A3D91" strokeWidth={2} fill="#FFFFFF" />
      {Array.from({ length: 8 }).map((_, i) => {
        const a = (Math.PI * 2 * i) / 8;
        return (
          <Line
            key={i}
            x1={32} y1={28.5}
            x2={32 + Math.cos(a) * 5} y2={28.5 + Math.sin(a) * 5}
            stroke="#0A3D91" strokeWidth={1.2}
          />
        );
      })}
    </Svg>
  );
}

/** Ganesh Chaturthi — a golden modak. */
function ModakIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="36" r="22" fill={withAlpha(glow, 0.16)} />
      {/* pleats */}
      <Path d="M32 10c4 6 4 12 2 16M32 10c-4 6-4 12-2 16M32 10c9 7 12 12 11 18M32 10c-9 7-12 12-11 18"
        stroke={tint} strokeWidth={2.6} fill="none" strokeLinecap="round" />
      {/* body */}
      <Path d="M20 26h24c3 0 5 2 5 5a17 17 0 0 1-34 0c0-3 2-5 5-5z" fill={glow} />
      {/* tip */}
      <Path d="M32 10c2.6 0 4 2 4 4s-8 0-8 0 1.4-4 4-4z" fill={glow} />
      {/* centre pleat */}
      <Path d="M32 26v20" stroke={withAlpha(tint, 0.5)} strokeWidth={2} strokeLinecap="round" />
    </Svg>
  );
}

/** Dussehra — crossed arrows of victory. */
function ArrowsIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="32" r="22" fill={withAlpha(glow, 0.16)} />
      <G stroke={tint} strokeWidth={3.4} strokeLinecap="round">
        {/* rising arrow, left to right */}
        <Line x1="18" y1="48" x2="46" y2="16" />
        <Line x1="36" y1="16" x2="46" y2="16" />
        <Line x1="46" y1="16" x2="46" y2="26" />
        {/* fletching */}
        <Line x1="18" y1="48" x2="24" y2="46" />
        <Line x1="18" y1="48" x2="16" y2="40" />
      </G>
      {/* bow arc */}
      <Path d="M48 34c5 7 3 15-3 20" stroke={glow} strokeWidth={3} fill="none" strokeLinecap="round" />
      {/* second arrow tip, bottom-left */}
      <G stroke={glow} strokeWidth={2.6} strokeLinecap="round" opacity={0.85}>
        <Line x1="30" y1="52" x2="42" y2="38" />
      </G>
    </Svg>
  );
}

/** Maha Shivaratri — the trishul. */
function TrishulIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="32" r="22" fill={withAlpha(glow, 0.18)} />
      <G stroke={tint} strokeWidth={3.2} strokeLinecap="round" fill="none">
        {/* centre prong */}
        <Path d="M32 6v14" />
        {/* outer prongs */}
        <Path d="M16 12c0 10 4 14 16 14s16-4 16-14" />
        {/* shaft */}
        <Path d="M32 26v30" />
      </G>
      {/* damaru knot */}
      <Circle cx="32" cy="40" r="3.4" fill={glow} />
      {/* centre arrowhead */}
      <Path d="M32 6l-4 6h8z" fill={tint} />
    </Svg>
  );
}

/** Ramzan — crescent and a star. */
function CrescentIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="32" r="23" fill={withAlpha(glow, 0.14)} />
      {/* crescent */}
      <Path
        d="M40 12a20 20 0 1 0 0 40 24 24 0 0 1 0-40z"
        fill={glow}
      />
      {/* star */}
      <Path d="M45 20l2.2 5 5.4.5-4.1 3.6 1.2 5.3-4.7-2.9-4.7 2.9 1.2-5.3-4.1-3.6 5.4-.5z"
        fill={tint} />
    </Svg>
  );
}

/** Christmas — a pine tree with a star. */
function TreeIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="34" r="22" fill={withAlpha(glow, 0.12)} />
      {/* star topper */}
      <Path d="M32 6l2 4.6 5 .4-3.8 3.3 1.2 4.9-4.4-2.7-4.4 2.7 1.2-4.9-3.8-3.3 5-.4z" fill={glow} />
      {/* tree, three tiers */}
      <Path d="M32 14l10 12h-6l8 10H20l8-10h-6z" fill={tint} />
      <Rect x="28" y="46" width="8" height="8" rx="1.5" fill={tint} />
      {/* ornaments */}
      <Circle cx="26" cy="32" r="2.2" fill={glow} />
      <Circle cx="38" cy="30" r="2.2" fill={glow} />
      <Circle cx="32" cy="40" r="2.2" fill={glow} />
    </Svg>
  );
}

/** New Year — a burst of fireworks. */
function FireworksIcon({ size, tint, glow }: IconProps) {
  const rays = Array.from({ length: 8 });
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="32" r="22" fill={withAlpha(glow, 0.14)} />
      {/* central burst */}
      {rays.map((_, i) => {
        const a = (Math.PI * 2 * i) / rays.length - Math.PI / 2;
        const x1 = 32 + Math.cos(a) * 8, y1 = 32 + Math.sin(a) * 8;
        const x2 = 32 + Math.cos(a) * 16, y2 = 32 + Math.sin(a) * 16;
        return <Line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={tint} strokeWidth={2.6} strokeLinecap="round" />;
      })}
      {rays.map((_, i) => {
        const a = (Math.PI * 2 * (i + 0.5)) / rays.length - Math.PI / 2;
        return (
          <Circle key={`d${i}`} cx={32 + Math.cos(a) * 20} cy={32 + Math.sin(a) * 20}
            r={2} fill={glow} />
        );
      })}
      <Circle cx="32" cy="32" r="4.5" fill={glow} />
    </Svg>
  );
}

/** Sankranti — a kite in the harvest sky. */
function KiteIcon({ size, tint, glow }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Circle cx="32" cy="30" r="22" fill={withAlpha(glow, 0.14)} />
      {/* kite */}
      <Path d="M32 10l14 14-14 16-14-16z" fill={tint} />
      {/* kite creases */}
      <Path d="M32 10v30M18 24h28" stroke={glow} strokeWidth={2} fill="none" opacity={0.8} />
      {/* string */}
      <Path d="M32 40c0 6-4 8-4 12s4 5 4 8" stroke={glow} strokeWidth={2.2} fill="none" strokeLinecap="round" />
      {/* string bows */}
      <Path d="M27 46l6 2M27 53l6 2" stroke={tint} strokeWidth={2} strokeLinecap="round" />
    </Svg>
  );
}

const REGISTRY: Record<string, (p: IconProps) => JSX.Element> = {
  diya: DiyaIcon,
  leaf: UgadiIcon,
  tiranga: TirangaIcon,
  modak: ModakIcon,
  arrows: ArrowsIcon,
  trishul: TrishulIcon,
  crescent: CrescentIcon,
  tree: TreeIcon,
  fireworks: FireworksIcon,
  kite: KiteIcon,
};

/** The drawn icon for the active festival — falls back to the diya. */
export function FestivalIcon({ pattern, size, tint, glow }: IconProps & { pattern?: string }) {
  const C = REGISTRY[(pattern || "").toLowerCase()] || DiyaIcon;
  return <C size={size} tint={tint} glow={glow} />;
}
