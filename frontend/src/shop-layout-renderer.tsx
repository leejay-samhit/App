// ShopLayoutRenderer — renders admin-managed content blocks on the customer
// Shop tab. Content boxes now auto-render the LINKED product (image, name,
// price, Buy CTA) — admin just picks a product, no manual title/image entry.
import React, { useEffect, useState } from "react";
import { View, Text, Image, TouchableOpacity, StyleSheet } from "react-native";
import { Feather } from "@expo/vector-icons";
import { api } from "./api";
import { colors, radii, formatINR } from "./theme";

export type LayoutBlock = {
  id: string;
  block_type: "background" | "section_header" | "text" | "content_box";
  title: string;
  subtitle: string;
  body: string;
  image_data_url: string;
  product_id: string | null;
  cta_label: string;
  sort_order: number;
  active: boolean;
  size?: "small" | "medium" | "large";
};

type Product = {
  id: string;
  name: string;
  price: number;
  description?: string;
  image_data_url?: string;
  images?: string[];
  stock?: number;
};

type Props = { onProductPress?: (productId: string) => void };

const SIZE_HEIGHT: Record<"small" | "medium" | "large", number> = {
  small: 150, medium: 210, large: 280,
};

export function ShopLayoutRenderer({ onProductPress }: Props) {
  const [blocks, setBlocks] = useState<LayoutBlock[]>([]);
  const [products, setProducts] = useState<Record<string, Product>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [bRes, pRes] = await Promise.all([
          api.get<{ items: LayoutBlock[] }>("/shop-layout"),
          api.get<any>("/products"),
        ]);
        if (cancelled) return;
        const blocks: LayoutBlock[] = bRes.data?.items || [];
        setBlocks(blocks);
        const pData = pRes.data;
        const pList: Product[] = Array.isArray(pData) ? pData : (pData?.items || pData?.products || []);
        const map: Record<string, Product> = {};
        pList.forEach((p) => { map[p.id] = p; });
        setProducts(map);
      } catch { /* silent — admin-driven */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const visible = blocks
    .filter((b) => b.active)
    .sort((a, b) => a.sort_order - b.sort_order);
  if (visible.length === 0) return null;

  return (
    <View style={{ marginBottom: 16 }}>
      {visible.map((b) => {
        if (b.block_type === "section_header") {
          return (
            <View key={b.id} style={styles.sectionHeaderWrap}>
              <Text style={styles.sectionHeaderText}>{b.title}</Text>
              {b.subtitle ? <Text style={styles.sectionHeaderSub}>{b.subtitle}</Text> : null}
            </View>
          );
        }
        if (b.block_type === "text") {
          return (
            <View key={b.id} style={styles.textBlock}>
              {b.title ? <Text style={styles.textBlockTitle}>{b.title}</Text> : null}
              {b.body ? <Text style={styles.textBlockBody}>{b.body}</Text> : null}
            </View>
          );
        }
        // content_box → render the LINKED product as a beautiful card
        // (falls back to the manually-entered fields if no product is linked)
        if (b.block_type === "content_box") {
          const p = b.product_id ? products[b.product_id] : null;
          const size = (b.size as "small" | "medium" | "large") || "medium";
          const height = SIZE_HEIGHT[size];
          if (p) {
            return (
              <TouchableOpacity
                key={b.id}
                style={[styles.productCard, { minHeight: height }]}
                onPress={() => onProductPress?.(p.id)}
                activeOpacity={0.85}
                testID={`shop-product-${p.id}`}
              >
                <View style={[styles.productImageWrap, { height: Math.max(120, height - 110) }]}>
                  {p.image_data_url || p.images?.[0] ? (
                    <Image source={{ uri: p.image_data_url || p.images?.[0] }} style={styles.productImage} resizeMode="cover" />
                  ) : (
                    <View style={styles.productImageEmpty}>
                      <Feather name="image" size={28} color={colors.textMuted} />
                    </View>
                  )}
                  {(p.stock ?? 1) <= 0 && (
                    <View style={styles.oosBadge}><Text style={styles.oosBadgeText}>SOLD OUT</Text></View>
                  )}
                </View>
                <View style={styles.productInfo}>
                  <Text style={styles.productName} numberOfLines={1}>{p.name}</Text>
                  {p.description ? <Text style={styles.productDesc} numberOfLines={2}>{p.description}</Text> : null}
                  <View style={styles.productFooter}>
                    <Text style={styles.productPrice}>{formatINR(p.price)}</Text>
                    <View style={styles.viewBtn}>
                      <Text style={styles.viewBtnText}>{b.cta_label || "View"}</Text>
                      <Feather name="arrow-right" size={12} color={colors.primaryFg} />
                    </View>
                  </View>
                </View>
              </TouchableOpacity>
            );
          }
          // Fallback: manual content_box without product link
          return (
            <View key={b.id} style={[styles.contentBox, { minHeight: height }]}>
              {b.image_data_url ? (
                <Image source={{ uri: b.image_data_url }} style={[styles.contentImage, { height: height - 30 }]} resizeMode="cover" />
              ) : null}
              <View style={{ padding: 14 }}>
                {b.title ? <Text style={styles.contentTitle}>{b.title}</Text> : null}
                {b.subtitle ? <Text style={styles.contentSub}>{b.subtitle}</Text> : null}
                {b.body ? <Text style={styles.contentBody}>{b.body}</Text> : null}
              </View>
            </View>
          );
        }
        // background (now "new banner") — full-width image card
        const size = (b.size as "small" | "medium" | "large") || "medium";
        const height = SIZE_HEIGHT[size];
        return (
          <View key={b.id} style={[styles.bannerBox, { height }]}>
            {b.image_data_url ? (
              <Image source={{ uri: b.image_data_url }} style={StyleSheet.absoluteFill as any} resizeMode="cover" />
            ) : null}
            {(b.title || b.subtitle) ? (
              <View style={styles.bannerOverlay}>
                {b.subtitle ? <Text style={styles.bannerEyebrow}>{b.subtitle}</Text> : null}
                {b.title ? <Text style={styles.bannerTitle}>{b.title}</Text> : null}
              </View>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  // Section header
  sectionHeaderWrap: { marginTop: 6, marginBottom: 10 },
  sectionHeaderText: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: 0.6, textTransform: "uppercase" },
  sectionHeaderSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  // Text block
  textBlock: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 12 },
  textBlockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 4 },
  textBlockBody: { fontSize: 13, color: colors.textMuted, lineHeight: 20 },
  // Product spotlight card (content_box w/ linked product)
  productCard: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden", marginBottom: 12 },
  productImageWrap: { width: "100%", backgroundColor: colors.surfaceMuted, position: "relative" },
  productImage: { width: "100%", height: "100%" },
  productImageEmpty: { flex: 1, alignItems: "center", justifyContent: "center" },
  oosBadge: { position: "absolute", top: 10, left: 10, backgroundColor: "#B91C1C", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  oosBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff", letterSpacing: 0.6 },
  productInfo: { padding: 12 },
  productName: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  productDesc: { fontSize: 12, color: colors.textMuted, marginTop: 3, lineHeight: 18 },
  productFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10 },
  productPrice: { fontSize: 17, fontWeight: "900", color: colors.primary, letterSpacing: -0.4 },
  viewBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.primary, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999 },
  viewBtnText: { fontSize: 11, fontWeight: "800", color: colors.primaryFg },
  // Fallback manual content_box
  contentBox: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden", marginBottom: 12 },
  contentImage: { width: "100%" },
  contentTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  contentSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  contentBody: { fontSize: 13, color: colors.textMain, lineHeight: 20, marginTop: 6 },
  // "New banner" block (was: background)
  bannerBox: { borderRadius: radii.card, overflow: "hidden", marginBottom: 12, backgroundColor: colors.brand100, position: "relative" },
  bannerOverlay: { position: "absolute", left: 16, bottom: 16, right: 16, backgroundColor: "rgba(0,0,0,0.35)", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 12 },
  bannerEyebrow: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.4, opacity: 0.9 },
  bannerTitle: { fontSize: 18, fontWeight: "900", color: "#fff", letterSpacing: -0.4, marginTop: 2 },
});
