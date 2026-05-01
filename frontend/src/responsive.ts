import { Dimensions, PixelRatio, Platform } from "react-native";

// Reference design size — iPhone 12 / Pixel 5 width.
const REFERENCE_WIDTH = 390;

const { width: WIN_W, height: WIN_H } = Dimensions.get("window");

/**
 * Scale a numeric size proportionally to the device width.
 * Use this for padding, margin, fontSize, iconSize, etc. so the layout
 * adapts to phones from 320 px (iPhone SE / very small Androids) up to
 * tablets — the TabletContainer in _layout caps tablets to a readable
 * column so we don't blow text up on iPads.
 *
 * The result is rounded to the nearest pixel via PixelRatio for crisp
 * rendering. Optional `factor` (0..1) softens the scaling for fonts —
 * e.g. fs(16, 0.4) only scales 40% as much as `fs(16)`.
 */
export function rs(size: number, factor: number = 0.5): number {
  const w = Math.min(WIN_W, 600); // cap at tablet column
  const scale = w / REFERENCE_WIDTH;
  const newSize = size + (size * scale - size) * factor;
  return Math.round(PixelRatio.roundToNearestPixel(newSize));
}

/** Width-percentage helper (0..100). */
export function wp(percent: number): number {
  return Math.round((WIN_W * percent) / 100);
}

/** Height-percentage helper (0..100). */
export function hp(percent: number): number {
  return Math.round((WIN_H * percent) / 100);
}

/**
 * Live versions for components that need to react to orientation /
 * window resize. Prefer calling `useWindowDimensions()` directly and
 * passing into these helpers when needed.
 */
export function rsWith(width: number, size: number, factor: number = 0.5): number {
  const w = Math.min(width, 600);
  const scale = w / REFERENCE_WIDTH;
  return Math.round(PixelRatio.roundToNearestPixel(size + (size * scale - size) * factor));
}

/** Common breakpoint helpers. */
export const isTinyDevice = WIN_W < 360;     // older / budget Androids
export const isSmallDevice = WIN_W < 380;
export const isLargeDevice = WIN_W >= 414;   // iPhone Pro Max etc.
export const isTablet = WIN_W >= 768;
export const isAndroid = Platform.OS === "android";
export const isIOS = Platform.OS === "ios";
