/**
 * ProductRail — horizontally swiping rail of fixed-size product cards.
 *
 * Oct-2026. The owner's constraints, verbatim, drove every decision here:
 *   • "Select items is to be always The same Size"  → CARD_W/CARD_H are
 *     constants and the image box is a fixed square, so a 4-word name and a
 *     14-word name produce IDENTICAL cards. Nothing reflows.
 *   • "around 10 or 5 items"                        → the caller passes 5-10.
 *   • "Don't make it messy just two types"          → this component is dumb;
 *     the product screen mounts exactly two of them.
 *   • "add to Cart option"                          → every card has a real
 *     add-to-cart that doesn't navigate away.
 *
 * `snapToInterval` makes the swipe land cleanly on a card instead of
 * stopping halfway through one.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError, resolveImageUrl } from "./api";
import { notify } from "./notify";
import { colors, radii, formatINR } from "./theme";

export const CARD_W = 148;
const IMG_H = 130;
const GAP = 10;

export type RailItem = {
  id: string;
  name: string;
  price: number;
  mrp?: number;
  discount_pct?: number;
  image_url?: string;
  brand?: string;
  subcategory?: string;
  in_stock?: boolean;
  free_delivery?: boolean;
  cod_available?: boolean;
  shop_name?: string;
  rating?: number;
};

export type Rail = {
  key: string;
  title: string;
  subtitle?: string;
  personalised?: boolean;
  items: RailItem[];
};

function RailCard({ item, onAdded }: { item: RailItem; onAdded: () => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const img = item.image_url ? resolveImageUrl(item.image_url) : "";
  const out = item.in_stock === false;

  const add = async () => {
    if (out || busy) return;
    setBusy(true);
    try {
      await api.post("/cart/add", { product_id: item.id, qty: 1 });
      notify("Added to bag", item.name);
      onAdded();
    } catch (e) {
      notify("Couldn't add", formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} testID={`rail-card-${item.id}`}>
      <TouchableOpacity
        onPress={() => router.push(`/product/${item.id}` as any)}
        activeOpacity={0.85}
      >
        <View style={styles.imgBox}>
          {img ? (
            <Image source={{ uri: img }} style={styles.img} resizeMode="cover" />
          ) : (
            <View style={styles.imgFallback}>
              <Feather name="image" size={22} color={colors.textMuted} />
            </View>
          )}
          {item.discount_pct ? (
            <View style={styles.offBadge}>
              <Text style={styles.offText}>{item.discount_pct}% OFF</Text>
            </View>
          ) : null}
          {out ? (
            <View style={styles.outOverlay}>
              <Text style={styles.outText}>OUT OF STOCK</Text>
            </View>
          ) : null}
        </View>

        {/* Fixed two-line name box — the single biggest cause of ragged
            rails is letting the title decide the card height. */}
        <View style={styles.nameBox}>
          <Text style={styles.name} numberOfLines={2}>{item.name}</Text>
        </View>

        <View style={styles.priceRow}>
          <Text style={styles.price}>{formatINR(item.price)}</Text>
          {item.mrp ? <Text style={styles.mrp}>{formatINR(item.mrp)}</Text> : null}
        </View>

        {/* Fixed-height meta strip keeps every card the same height whether
            or not the item has a badge to show. */}
        <View style={styles.metaBox}>
          {item.free_delivery ? (
            <Text style={styles.metaFree}>Free delivery</Text>
          ) : item.cod_available === false ? (
            <Text style={styles.metaPrepaid}>Prepaid only</Text>
          ) : item.rating ? (
            <Text style={styles.metaRating}>★ {item.rating.toFixed(1)}</Text>
          ) : (
            <Text style={styles.metaShop} numberOfLines={1}>{item.shop_name || " "}</Text>
          )}
        </View>
      </TouchableOpacity>

      <TouchableOpacity
        onPress={add}
        disabled={out || busy}
        style={[styles.addBtn, (out || busy) && styles.addBtnOff]}
        testID={`rail-add-${item.id}`}
        activeOpacity={0.85}
      >
        {busy ? (
          <ActivityIndicator size="small" color={colors.primaryFg} />
        ) : (
          <>
            <Feather
              name={out ? "slash" : "shopping-bag"}
              size={12}
              color={out ? colors.textMuted : colors.primaryFg}
            />
            <Text style={[styles.addText, out && { color: colors.textMuted }]}>
              {out ? "Sold out" : "Add"}
            </Text>
          </>
        )}
      </TouchableOpacity>
    </View>
  );
}

export function ProductRail({ rail, onAdded }: { rail: Rail; onAdded?: () => void }) {
  if (!rail?.items?.length) return null;
  return (
    <View style={styles.wrap} testID={`rail-${rail.key}`}>
      <View style={styles.head}>
        <View style={{ flex: 1 }}>
          <Text style={styles.title} numberOfLines={1}>{rail.title}</Text>
          {rail.subtitle ? (
            <Text style={styles.subtitle} numberOfLines={1}>{rail.subtitle}</Text>
          ) : null}
        </View>
        {rail.personalised ? (
          <View style={styles.youBadge}>
            <Feather name="user-check" size={9} color={colors.primaryFg} />
            <Text style={styles.youBadgeText}>FOR YOU</Text>
          </View>
        ) : null}
      </View>

      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.row}
        decelerationRate="fast"
        snapToInterval={CARD_W + GAP}
        snapToAlignment="start"
      >
        {rail.items.map((it) => (
          <RailCard key={it.id} item={it} onAdded={() => onAdded?.()} />
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 22 },
  head: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 16, marginBottom: 11,
  },
  title: { fontSize: 15.5, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  subtitle: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, fontWeight: "600" },
  youBadge: {
    flexDirection: "row", alignItems: "center", gap: 3,
    backgroundColor: colors.primary,
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: 999,
  },
  youBadgeText: { fontSize: 8, fontWeight: "900", letterSpacing: 0.7, color: colors.primaryFg },
  row: { paddingHorizontal: 16, gap: GAP, paddingBottom: 4 },

  // Every value below is FIXED on purpose — identical cards, no reflow.
  card: {
    width: CARD_W,
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
    padding: 8, overflow: "hidden",
  },
  imgBox: {
    width: CARD_W - 18, height: IMG_H,
    borderRadius: 10, overflow: "hidden",
    backgroundColor: colors.surfaceMuted,
  },
  img: { width: "100%", height: "100%" },
  imgFallback: { flex: 1, alignItems: "center", justifyContent: "center" },
  offBadge: {
    position: "absolute", top: 6, left: 6,
    backgroundColor: colors.accent,
    paddingHorizontal: 5, paddingVertical: 2, borderRadius: 5,
  },
  offText: { fontSize: 8.5, fontWeight: "900", color: colors.accentFg },
  outOverlay: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(0,0,0,0.6)", paddingVertical: 4, alignItems: "center",
  },
  outText: { fontSize: 8.5, fontWeight: "900", color: "#FFFFFF", letterSpacing: 0.6 },

  nameBox: { height: 34, marginTop: 7, justifyContent: "flex-start" },
  name: { fontSize: 11.5, lineHeight: 15, fontWeight: "700", color: colors.textMain },
  priceRow: { flexDirection: "row", alignItems: "baseline", gap: 5, marginTop: 4 },
  price: { fontSize: 14, fontWeight: "900", color: colors.textMain },
  mrp: { fontSize: 10.5, color: colors.textMuted, textDecorationLine: "line-through" },
  metaBox: { height: 15, justifyContent: "center", marginTop: 2 },
  metaFree: { fontSize: 9.5, fontWeight: "900", color: colors.success },
  metaPrepaid: { fontSize: 9.5, fontWeight: "900", color: colors.accent },
  metaRating: { fontSize: 9.5, fontWeight: "900", color: colors.textMuted },
  metaShop: { fontSize: 9.5, fontWeight: "700", color: colors.textMuted },

  addBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5,
    backgroundColor: colors.primary,
    height: 32, borderRadius: 8, marginTop: 7,
  },
  addBtnOff: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  addText: { fontSize: 11.5, fontWeight: "900", color: colors.primaryFg },
});
