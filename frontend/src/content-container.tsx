/**
 * ContentContainer — the single source of truth for horizontal page padding
 * across the Shop home, dynamic admin layout blocks, banner slider, category
 * grid, product grids, recommendations, and the footer.
 *
 * Spec (June 2026 redesign):
 *   • Left padding  : 16 dp
 *   • Right padding : 16 dp
 *   • No section ever touches the screen edge.
 *   • Every section/block (admin-created or hardcoded) MUST be wrapped in
 *     this component so they align on the same vertical rail — matching the
 *     Amazon / Flipkart / Meesho / Myntra polish.
 *
 * Usage:
 *   <ContentContainer>
 *     <Banner />
 *   </ContentContainer>
 *   <ContentContainer noTopGap>
 *     <Categories />
 *   </ContentContainer>
 *
 * Props:
 *   - noTopGap: drop the default 16 dp top margin (useful for the first
 *               section right under the sticky header).
 *   - gap:      override the bottom gap. Default = 16 dp (the spec value).
 */
import React from "react";
import { View, StyleSheet, ViewStyle, StyleProp } from "react-native";

export const SHOP_HORIZONTAL_PADDING = 16;     // 16 dp on both sides
export const SHOP_SECTION_GAP        = 16;     // 16 dp between sections
export const SHOP_CARD_RADIUS        = 12;     // 12 px product cards
export const SHOP_BANNER_RADIUS      = 16;     // 16 px banners

// ── Typography presets (used by shop home + dynamic blocks) ──────────────
// Numbers chosen exactly per spec so the entire shop feels coherent.
export const SHOP_TYPO = {
  heading:      { fontSize: 22, fontWeight: "800" as const,  letterSpacing: -0.3 },
  sectionTitle: { fontSize: 18, fontWeight: "800" as const,  letterSpacing: -0.2 },
  productName:  { fontSize: 15, fontWeight: "500" as const,  letterSpacing: -0.1 },
  price:        { fontSize: 16, fontWeight: "800" as const },
} as const;

type Props = {
  children: React.ReactNode;
  noTopGap?: boolean;
  gap?: number;
  style?: StyleProp<ViewStyle>;
};

export function ContentContainer({ children, noTopGap = false, gap, style }: Props) {
  return (
    <View
      style={[
        styles.container,
        noTopGap ? null : { marginTop: 0 },
        { marginBottom: gap ?? SHOP_SECTION_GAP },
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: SHOP_HORIZONTAL_PADDING,
  },
});
