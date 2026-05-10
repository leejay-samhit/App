// ShopLayoutRenderer — renders admin-managed content blocks on the customer
// Shop tab between the promo carousel and the products grid.
import React, { useEffect, useState } from "react";
import { View, Text, Image, TouchableOpacity, StyleSheet } from "react-native";
import { Feather } from "@expo/vector-icons";
import { api } from "./api";
import { colors, radii } from "./theme";

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
};

type Props = { onProductPress?: (productId: string) => void };

export function ShopLayoutRenderer({ onProductPress }: Props) {
  const [blocks, setBlocks] = useState<LayoutBlock[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ items: LayoutBlock[] }>("/shop-layout");
        if (!cancelled) setBlocks(res.data?.items || []);
      } catch { /* silent — admin-driven, may be empty */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // background blocks render via parent — here we only handle the visible ones
  const visible = blocks.filter((b) => b.block_type !== "background");
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
        // content_box
        return (
          <View key={b.id} style={styles.contentBox}>
            {b.image_data_url ? (
              <Image source={{ uri: b.image_data_url }} style={styles.contentImage} resizeMode="cover" />
            ) : null}
            <View style={{ padding: 14 }}>
              {b.title ? <Text style={styles.contentTitle}>{b.title}</Text> : null}
              {b.subtitle ? <Text style={styles.contentSub}>{b.subtitle}</Text> : null}
              {b.body ? <Text style={styles.contentBody}>{b.body}</Text> : null}
              {b.product_id ? (
                <TouchableOpacity
                  style={styles.contentCta}
                  onPress={() => onProductPress?.(b.product_id!)}
                  testID={`layout-cta-${b.id}`}
                >
                  <Text style={styles.contentCtaText}>{b.cta_label || "View"}</Text>
                  <Feather name="arrow-right" size={13} color={colors.primaryFg} />
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

/** Look up an active background image (first one, lowest sort_order) for the Shop screen. */
export function useShopLayoutBackground(): string | null {
  const [bg, setBg] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ items: LayoutBlock[] }>("/shop-layout");
        if (!cancelled) {
          const found = (res.data?.items || []).find((b) => b.block_type === "background" && b.image_data_url);
          setBg(found?.image_data_url || null);
        }
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, []);
  return bg;
}

const styles = StyleSheet.create({
  sectionHeaderWrap: { marginTop: 6, marginBottom: 10 },
  sectionHeaderText: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: 0.6, textTransform: "uppercase" },
  sectionHeaderSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  textBlock: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 12 },
  textBlockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 4 },
  textBlockBody: { fontSize: 13, color: colors.textMuted, lineHeight: 20 },
  contentBox: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden", marginBottom: 12 },
  contentImage: { width: "100%", height: 140 },
  contentTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  contentSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  contentBody: { fontSize: 13, color: colors.textMain, lineHeight: 20, marginTop: 6 },
  contentCta: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", backgroundColor: colors.primary, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, marginTop: 10 },
  contentCtaText: { color: colors.primaryFg, fontWeight: "800", fontSize: 12 },
});
