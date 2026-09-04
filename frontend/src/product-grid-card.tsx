/**
 * ProductGridCard — THE product card for the whole shop.
 *
 * Jun 2026, per user request: "apply only one type of product display".
 * Search results used to render a different, flashier card (fake -33% badge,
 * invented 4.4★ / 48k reviews, no Add button) while categories used this
 * clean one. Search, the home category grid and the category screen now all
 * render this single component, so:
 *   • one look everywhere,
 *   • add-to-cart works from search (it previously didn't exist there),
 *   • less code to ship and re-render.
 *
 * Layout: 2-up grid tile — square image, 2-line name, price, and either an
 * "Add" pill, an inline −/+ stepper (when already in the cart) or a SOLD OUT
 * chip. Wrap a list of these in a <View style={productGridStyles.wrap}>.
 */
import React from "react";
import { View, Text, Image, TouchableOpacity, StyleSheet, useWindowDimensions } from "react-native";
import { Feather } from "@expo/vector-icons";

import { resolveImageUrl } from "./api";
import { colors, formatINR } from "./theme";
import { FadeSlideIn } from "./anim";

export type GridProduct = {
  id: string;
  name: string;
  price: number;
  image_url?: string;
  stock?: number;
  is_in_stock?: boolean;
  /** Jun 2026 — true when the product has sizes / RAM-ROM options. */
  has_variants?: boolean;
};

type Props = {
  product: GridProduct;
  qty: number;
  onOpen: (p: GridProduct) => void;
  onAdd: (p: GridProduct) => void;
  onDecrement: (p: GridProduct) => void;
  /** Staggered entrance index; pass the map index. */
  index?: number;
};

/**
 * Jun 2026 — Responsive column count.
 *
 * The card was hard-coded to `flexBasis: 48%` (always 2-up). On a 12-inch
 * tablet that made each tile ~500 dp wide with a 500 dp tall square image —
 * two absurdly large cards per row. We now derive the column count from the
 * live window width so phones stay 2-up while tablets/desktop fill the row.
 */
export function gridColumnsFor(width: number): number {
  if (width >= 1280) return 5;
  if (width >= 1024) return 4;
  if (width >= 700) return 3;
  return 2;
}

const GRID_GAP = 12;

export function ProductGridCard({ product: p, qty, onOpen, onAdd, onDecrement, index = 0 }: Props) {
  const { width } = useWindowDimensions();
  const cols = gridColumnsFor(width);
  // ── Gutter strategy (Jun 2026) ────────────────────────────────────────
  // The old card mixed a PERCENT basis (48%) with a PIXEL `gap: 12` on the
  // wrapper.  48% + 48% + 12 px overflows 100% on narrow phones, so flexWrap
  // pushed every second card onto its own row — the "one product per line"
  // bug.  Now the OUTER cell is an exact 100/cols % with symmetric padding,
  // and the visual card lives inside it.  Percentages only → never overflows.
  const cellWidth = `${100 / cols}%`;
  const inStock = p.is_in_stock ?? (p.stock || 0) > 0;
  return (
    <FadeSlideIn
      delay={Math.min(index, 8) * 40}
      style={[styles.cell, { width: cellWidth as any, maxWidth: cellWidth as any }] as any}
    >
      <View style={[styles.card, !inStock && { opacity: 0.55 }]}>
        <TouchableOpacity activeOpacity={0.85} onPress={() => onOpen(p)} testID={`product-open-${p.id}`}>
          <Image source={{ uri: resolveImageUrl(p.image_url || "") }} style={styles.img} resizeMode="cover" />
        </TouchableOpacity>
        <View style={styles.body}>
          <TouchableOpacity activeOpacity={0.85} onPress={() => onOpen(p)}>
            <Text style={styles.name} numberOfLines={2}>{p.name}</Text>
          </TouchableOpacity>
          <View style={styles.footer}>
            <Text style={styles.price} numberOfLines={1}>{formatINR(p.price)}</Text>
            {!inStock ? (
              <View style={[styles.addBtn, { backgroundColor: "#B91C1C" }]}>
                <Text style={styles.addBtnText}>SOLD OUT</Text>
              </View>
            ) : p.has_variants ? (
              /* Jun 2026 — a product with sizes can't be blind-added: the
                 customer has to choose one, so the button opens the product
                 page (where the size picker lives) instead of failing. */
              <TouchableOpacity
                onPress={() => onOpen(p)}
                style={styles.addBtn}
                hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                testID={`pick-size-${p.id}`}
              >
                <Text style={styles.addBtnText}>SELECT</Text>
              </TouchableOpacity>
            ) : qty > 0 ? (
              <View style={styles.stepper} testID={`qty-${p.id}`}>
                <TouchableOpacity
                  onPress={() => onDecrement(p)}
                  style={styles.stepBtn}
                  hitSlop={{ top: 6, bottom: 6, left: 4, right: 4 }}
                  testID={`dec-${p.id}`}
                >
                  <Feather name="minus" size={12} color="#fff" />
                </TouchableOpacity>
                <Text style={styles.stepNum}>{qty}</Text>
                <TouchableOpacity
                  onPress={() => onAdd(p)}
                  style={styles.stepBtn}
                  hitSlop={{ top: 6, bottom: 6, left: 4, right: 4 }}
                  testID={`inc-${p.id}`}
                >
                  <Feather name="plus" size={12} color="#fff" />
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity style={styles.addBtn} onPress={() => onAdd(p)} testID={`add-${p.id}`}>
                <Feather name="plus" size={12} color="#fff" />
                <Text style={styles.addBtnText}>Add</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </View>
    </FadeSlideIn>
  );
}

/** Wrapper style for a responsive grid of ProductGridCards. */
export const productGridStyles = StyleSheet.create({
  // No `gap` here — each cell carries its own padding (see styles.cell), so
  // the row math is 100% percentage-based and can never overflow.
  wrap: { flexDirection: "row", flexWrap: "wrap", marginHorizontal: -GRID_GAP / 2 },
});

const styles = StyleSheet.create({
  cell: { paddingHorizontal: GRID_GAP / 2, paddingBottom: GRID_GAP },
  card: {
    backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1,
    borderColor: colors.border, overflow: "hidden",
  },
  body: { padding: 10 },
  img: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  name: { fontSize: 12.5, fontWeight: "700", color: colors.textMain, minHeight: 32, lineHeight: 16 },
  price: { fontSize: 14, fontWeight: "900", color: colors.primary, flexShrink: 1 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8, gap: 6 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.primary, minHeight: 28, flexShrink: 0 },
  addBtnText: { fontSize: 11, fontWeight: "800", color: "#fff", letterSpacing: 0.3 },
  stepper: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.primary,
    borderRadius: 999, paddingHorizontal: 3, paddingVertical: 2,
    minHeight: 28, gap: 2,
  },
  stepBtn: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.18)",
  },
  stepNum: {
    fontSize: 12, fontWeight: "900", color: "#fff",
    minWidth: 18, textAlign: "center", letterSpacing: 0.3,
  },
});
