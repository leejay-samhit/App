/**
 * content-width — the width every layout calculation should use.
 *
 * Jun 2026 tablet fix. Shop-layout blocks (banner, spotlight, product grid,
 * brand slider) sized themselves off `useWindowDimensions().width`. On a
 * 12-inch tablet that meant 1000+ dp wide banners and 500 dp tall product
 * images — the "rendering disaster" the owner reported.
 *
 * The app is now rendered inside a centred, phone-like column on tablets
 * (see TabletContainer in app/_layout.tsx) and every width-aware component
 * reads THIS hook instead of the raw window width, so the maths matches the
 * column it actually paints into.
 *
 * On phones (< TABLET_MAX_WIDTH) and on desktop web (where DesktopShell
 * supplies its own chrome) no provider is mounted and the hook simply
 * returns the live window width — zero behaviour change.
 */
import React, { createContext, useContext } from "react";
import { useWindowDimensions } from "react-native";

/** Widest the app content column ever gets. Tuned to feel like a large phone. */
export const TABLET_MAX_WIDTH = 760;

const ContentWidthCtx = createContext<number | null>(null);

export function ContentWidthProvider({ width, children }: { width: number; children: React.ReactNode }) {
  return <ContentWidthCtx.Provider value={width}>{children}</ContentWidthCtx.Provider>;
}

/** Live width of the column the current screen is painted into. */
export function useContentWidth(): number {
  const provided = useContext(ContentWidthCtx);
  const { width } = useWindowDimensions();
  return provided ?? width;
}
