// ShopLayoutRenderer — JSON-driven dynamic shop layout engine.
// Renders 12 block types defined by the admin via /admin/shop-layout.
// Used by:
//   • (tabs)/shop.tsx           with scope="home"
//   • shop-category/[name].tsx  with scope="category" & category=...
//
// All block types are pure functions over (block, products, callbacks) so
// they're trivial to extend with new ones. Skeleton loaders show while data
// is in-flight; out-of-stock products are dimmed; lazy image loading is
// implicit via RN <Image>.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, Image, TouchableOpacity, StyleSheet, ScrollView,
  Dimensions, FlatList, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api } from "./api";
import { colors, radii, formatINR } from "./theme";

/* ─────────────────────────── Types ─────────────────────────── */

export type BlockType =
  | "banner_slider" | "product_grid" | "horizontal_slider"
  | "category_circles" | "flash_sale" | "offer_cards"
  | "brand_slider" | "announcement_strip"
  | "background" | "section_header" | "text" | "content_box";

export type LayoutItem = {
  label?: string;
  subtitle?: string;
  image_data_url?: string;
  link_type?: "product" | "category" | null;
  link_value?: string;
  color?: string;
};

export type LayoutBlock = {
  id: string;
  block_type: BlockType;
  scope?: "home" | "category";
  scope_category?: string;
  title?: string;
  subtitle?: string;
  body?: string;
  image_data_url?: string;
  product_id?: string | null;
  cta_label?: string;
  sort_order: number;
  active: boolean;
  size?: "small" | "medium" | "large";
  // Styling
  text_color?: string;
  bg_color?: string;
  font_size?: number | null;
  text_align?: "left" | "center" | "right" | "";
  button_color?: string;
  button_text_color?: string;
  height?: number | null;
  // Data binding
  product_ids?: string[];
  data_source?: "manual" | "trending" | "new" | "best" | "category";
  product_count?: number;
  layout_style?: "grid" | "list" | "horizontal";
  category_filter?: string;
  items?: LayoutItem[];
  flash_sale_ends_at?: string;
};

export type Product = {
  id: string;
  name: string;
  price: number;
  description?: string;
  image_url?: string;
  image_data_url?: string;
  images?: string[];
  stock?: number;
  is_in_stock?: boolean;
  category?: string;
};

type RendererProps = {
  scope?: "home" | "category";
  category?: string;
  onProductPress?: (productId: string) => void;
  onCategoryPress?: (category: string) => void;
  onAddToCart?: (productId: string) => void;
};

const SIZE_HEIGHT: Record<"small" | "medium" | "large", number> = {
  small: 130, medium: 180, large: 240,
};

const screenWidth = Dimensions.get("window").width;

/* ─────────────────────────── Skeleton loaders ─────────────────────────── */

function SkeletonBlock({ height = 140 }: { height?: number }) {
  return <View style={[styles.skeleton, { height }]} />;
}

/* ─────────────────────────── Helpers ─────────────────────────── */

function pickImage(p?: Product): string | undefined {
  if (!p) return undefined;
  return p.image_data_url || p.image_url || p.images?.[0];
}

function alignToTextAlign(a?: string): "left" | "center" | "right" {
  return a === "center" || a === "right" || a === "left" ? a : "left";
}

function resolveBlockHeight(b: LayoutBlock): number {
  if (typeof b.height === "number" && b.height > 0) return b.height;
  const sz = (b.size as "small" | "medium" | "large") || "medium";
  return SIZE_HEIGHT[sz];
}

/* ─────────────────────────── Block: Banner Slider ─────────────────────────── */

function BannerSliderBlock({
  block, onProductPress, onCategoryPress,
}: { block: LayoutBlock; onProductPress?: (id: string) => void; onCategoryPress?: (c: string) => void }) {
  const [idx, setIdx] = useState(0);
  const items = block.items || [];
  const height = resolveBlockHeight(block);
  // Slide width must exactly match the visible carousel width. The shop tab
  // uses 12px horizontal padding on each side (24px total), so the carousel
  // takes up `screenWidth - 24`. Mismatched widths cause the next slide to
  // peek from the right edge — the exact bug a customer reported.
  const slideWidth = screenWidth - 24;
  // Auto-advance every 4s
  useEffect(() => {
    if (items.length <= 1) return;
    const t = setInterval(() => setIdx((i) => (i + 1) % items.length), 4000);
    return () => clearInterval(t);
  }, [items.length]);
  if (items.length === 0) return null;
  return (
    <View style={{ marginBottom: 14 }}>
      <FlatList
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        snapToInterval={slideWidth}
        snapToAlignment="start"
        decelerationRate="fast"
        data={items}
        keyExtractor={(_, i) => `slide-${i}`}
        renderItem={({ item }) => {
          return (
            <TouchableOpacity
              activeOpacity={0.9}
              style={[styles.slide, { width: slideWidth, height, backgroundColor: item.color || block.bg_color || colors.brand100 }]}
              onPress={() => {
                if (item.link_type === "product" && item.link_value) onProductPress?.(item.link_value);
                else if (item.link_type === "category" && item.link_value) onCategoryPress?.(item.link_value);
              }}
            >
              {item.image_data_url ? (
                <Image source={{ uri: item.image_data_url }} style={StyleSheet.absoluteFill as any} resizeMode="cover" />
              ) : null}
              {(item.label || item.subtitle) ? (
                <View style={[styles.slideOverlay, { alignItems: alignToTextAlign(block.text_align) === "center" ? "center" : "flex-start" }]}>
                  {item.subtitle ? (
                    <Text style={[styles.slideSub, block.text_color ? { color: block.text_color } : null]}>{item.subtitle}</Text>
                  ) : null}
                  {item.label ? (
                    <Text style={[styles.slideTitle, block.text_color ? { color: block.text_color } : null, block.font_size ? { fontSize: block.font_size } : null]}>{item.label}</Text>
                  ) : null}
                  {block.cta_label ? (
                    <View style={[styles.slideCta, { backgroundColor: block.button_color || "#fff" }]}>
                      <Text style={[styles.slideCtaText, { color: block.button_text_color || colors.primary }]}>{block.cta_label}</Text>
                      <Feather name="arrow-right" size={11} color={block.button_text_color || colors.primary} />
                    </View>
                  ) : null}
                </View>
              ) : null}
            </TouchableOpacity>
          );
        }}
        onMomentumScrollEnd={(e) => {
          const x = e.nativeEvent.contentOffset.x;
          setIdx(Math.round(x / slideWidth));
        }}
        getItemLayout={(_, index) => ({ length: slideWidth, offset: slideWidth * index, index })}
        ItemSeparatorComponent={() => <View style={{ width: 0 }} />}
      />
      {items.length > 1 ? (
        <View style={styles.dotsRow}>
          {items.map((_, i) => (
            <View key={i} style={[styles.dot, i === idx && styles.dotActive]} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/* ─────────────────────────── Block: Category Circles ─────────────────────────── */

function CategoryCirclesBlock({
  block, onCategoryPress,
}: { block: LayoutBlock; onCategoryPress?: (c: string) => void }) {
  const items = block.items || [];
  if (items.length === 0) return null;
  return (
    <View style={{ marginBottom: 14 }}>
      {block.title ? <SectionTitle block={block} /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 4 }}>
        {items.map((it, i) => (
          <TouchableOpacity
            key={`cc-${i}`}
            style={styles.circleTile}
            activeOpacity={0.8}
            onPress={() => {
              if (it.link_type === "category" && it.link_value) onCategoryPress?.(it.link_value);
            }}
          >
            <View style={[styles.circleAvatar, { backgroundColor: it.color || colors.brand100 }]}>
              {it.image_data_url ? (
                <Image source={{ uri: it.image_data_url }} style={styles.circleImg} resizeMode="cover" />
              ) : (
                <Feather name="grid" size={22} color={colors.primary} />
              )}
            </View>
            <Text style={styles.circleLabel} numberOfLines={1}>{it.label || "—"}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </View>
  );
}

/* ─────────────────────────── Block: Brand Slider ─────────────────────────── */

function BrandSliderBlock({ block }: { block: LayoutBlock }) {
  const items = block.items || [];
  if (items.length === 0) return null;
  return (
    <View style={{ marginBottom: 14 }}>
      {block.title ? <SectionTitle block={block} /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 4 }}>
        {items.map((it, i) => (
          <View key={`brand-${i}`} style={styles.brandTile}>
            {it.image_data_url ? (
              <Image source={{ uri: it.image_data_url }} style={styles.brandImg} resizeMode="contain" />
            ) : (
              <View style={[styles.brandImg, { alignItems: "center", justifyContent: "center" }]}>
                <Text style={styles.brandText}>{it.label || "Brand"}</Text>
              </View>
            )}
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

/* ─────────────────────────── Block: Offer Cards ─────────────────────────── */

function OfferCardsBlock({
  block, onProductPress, onCategoryPress,
}: { block: LayoutBlock; onProductPress?: (id: string) => void; onCategoryPress?: (c: string) => void }) {
  const items = block.items || [];
  if (items.length === 0) return null;
  return (
    <View style={{ marginBottom: 14 }}>
      {block.title ? <SectionTitle block={block} /> : null}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
        {items.map((it, i) => (
          <TouchableOpacity
            key={`offer-${i}`}
            style={[styles.offerCard, { backgroundColor: it.color || colors.brand100 }]}
            activeOpacity={0.85}
            onPress={() => {
              if (it.link_type === "product" && it.link_value) onProductPress?.(it.link_value);
              else if (it.link_type === "category" && it.link_value) onCategoryPress?.(it.link_value);
            }}
          >
            {it.image_data_url ? (
              <Image source={{ uri: it.image_data_url }} style={styles.offerImg} resizeMode="cover" />
            ) : null}
            <View style={styles.offerContent}>
              {it.subtitle ? <Text style={styles.offerSub} numberOfLines={1}>{it.subtitle}</Text> : null}
              {it.label ? <Text style={styles.offerTitle} numberOfLines={2}>{it.label}</Text> : null}
            </View>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

/* ─────────────────────────── Block: Announcement Strip ─────────────────────────── */

function AnnouncementStripBlock({ block }: { block: LayoutBlock }) {
  const bg = block.bg_color || "#FEF3C7";
  const fg = block.text_color || "#92400E";
  return (
    <View style={[styles.announceStrip, { backgroundColor: bg }]}>
      <Feather name="zap" size={13} color={fg} />
      <Text style={[styles.announceText, { color: fg, textAlign: alignToTextAlign(block.text_align), flex: 1 }, block.font_size ? { fontSize: block.font_size } : null]}>
        {block.title || block.body || "Announcement"}
      </Text>
    </View>
  );
}

/* ─────────────────────────── Block: Flash Sale ─────────────────────────── */

function useCountdown(endsAt?: string) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (!endsAt) return null;
  const target = new Date(endsAt).getTime();
  const diff = Math.max(0, target - now);
  if (!isFinite(diff)) return null;
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  const s = Math.floor((diff % 60_000) / 1000);
  return { h, m, s, expired: diff === 0 };
}

function FlashSaleBlock({
  block, products, onProductPress, onAddToCart,
}: { block: LayoutBlock; products: Product[]; onProductPress?: (id: string) => void; onAddToCart?: (id: string) => void }) {
  const countdown = useCountdown(block.flash_sale_ends_at);
  const bg = block.bg_color || "#FFF1F2";
  return (
    <View style={[styles.flashWrap, { backgroundColor: bg }]}>
      <View style={styles.flashHeader}>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Feather name="zap" size={16} color="#DC2626" />
            <Text style={[styles.flashTitle, block.text_color ? { color: block.text_color } : null]}>
              {block.title || "Flash Sale"}
            </Text>
          </View>
          {block.subtitle ? <Text style={styles.flashSub}>{block.subtitle}</Text> : null}
        </View>
        {countdown && !countdown.expired ? (
          <View style={styles.flashTimer}>
            <View style={styles.flashTimerBox}><Text style={styles.flashTimerText}>{String(countdown.h).padStart(2, "0")}</Text></View>
            <Text style={styles.flashTimerSep}>:</Text>
            <View style={styles.flashTimerBox}><Text style={styles.flashTimerText}>{String(countdown.m).padStart(2, "0")}</Text></View>
            <Text style={styles.flashTimerSep}>:</Text>
            <View style={styles.flashTimerBox}><Text style={styles.flashTimerText}>{String(countdown.s).padStart(2, "0")}</Text></View>
          </View>
        ) : countdown?.expired ? (
          <Text style={styles.flashEnded}>Sale ended</Text>
        ) : null}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 4 }}>
        {products.slice(0, block.product_count || 10).map((p) => (
          <TouchableOpacity key={p.id} style={styles.flashCard} activeOpacity={0.85} onPress={() => onProductPress?.(p.id)}>
            <View style={styles.flashCardImageWrap}>
              {pickImage(p) ? (
                <Image source={{ uri: pickImage(p) }} style={styles.flashCardImg} resizeMode="cover" />
              ) : (
                <View style={[styles.flashCardImg, { alignItems: "center", justifyContent: "center" }]}>
                  <Feather name="image" size={20} color={colors.textMuted} />
                </View>
              )}
            </View>
            <Text style={styles.flashCardName} numberOfLines={1}>{p.name}</Text>
            <Text style={styles.flashCardPrice}>{formatINR(p.price)}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
    </View>
  );
}

/* ─────────────────────────── Block: Product Grid ─────────────────────────── */

function ProductGridBlock({
  block, products, onProductPress, onAddToCart,
}: { block: LayoutBlock; products: Product[]; onProductPress?: (id: string) => void; onAddToCart?: (id: string) => void }) {
  if (products.length === 0) return <SkeletonBlock height={160} />;
  return (
    <View style={{ marginBottom: 14 }}>
      {block.title ? <SectionTitle block={block} /> : null}
      <View style={styles.gridWrap}>
        {products.slice(0, block.product_count || 10).map((p) => {
          const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
          return (
            <TouchableOpacity
              key={p.id}
              style={[styles.gridCard, !inStock && { opacity: 0.55 }]}
              activeOpacity={0.85}
              onPress={() => onProductPress?.(p.id)}
            >
              <View style={styles.gridImgWrap}>
                {pickImage(p) ? (
                  <Image source={{ uri: pickImage(p) }} style={styles.gridImg} resizeMode="cover" />
                ) : (
                  <View style={[styles.gridImg, { alignItems: "center", justifyContent: "center" }]}>
                    <Feather name="image" size={22} color={colors.textMuted} />
                  </View>
                )}
                {!inStock ? (
                  <View style={styles.gridOOSBadge}><Text style={styles.gridOOSText}>SOLD OUT</Text></View>
                ) : null}
              </View>
              <View style={{ padding: 10 }}>
                <Text style={styles.gridName} numberOfLines={2}>{p.name}</Text>
                <View style={styles.gridFooter}>
                  <Text style={styles.gridPrice}>{formatINR(p.price)}</Text>
                  {/* Add-to-cart pill removed per user feedback (clutters the
                      grid). Tap the card to open product detail and add from
                      there. */}
                </View>
              </View>
            </TouchableOpacity>
          );
        })}
      </View>
    </View>
  );
}

/* ─────────────────────────── Block: Horizontal Slider ─────────────────────────── */

function HorizontalSliderBlock({
  block, products, onProductPress, onAddToCart,
}: { block: LayoutBlock; products: Product[]; onProductPress?: (id: string) => void; onAddToCart?: (id: string) => void }) {
  if (products.length === 0) return <SkeletonBlock height={180} />;
  return (
    <View style={{ marginBottom: 14 }}>
      {block.title ? <SectionTitle block={block} /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 4, paddingRight: 4 }}>
        {products.slice(0, block.product_count || 10).map((p) => {
          const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
          return (
            <TouchableOpacity
              key={p.id}
              style={[styles.hCard, !inStock && { opacity: 0.55 }]}
              activeOpacity={0.85}
              onPress={() => onProductPress?.(p.id)}
            >
              <View style={styles.hImgWrap}>
                {pickImage(p) ? (
                  <Image source={{ uri: pickImage(p) }} style={styles.hImg} resizeMode="cover" />
                ) : (
                  <View style={[styles.hImg, { alignItems: "center", justifyContent: "center" }]}>
                    <Feather name="image" size={20} color={colors.textMuted} />
                  </View>
                )}
              </View>
              <Text style={styles.hName} numberOfLines={2}>{p.name}</Text>
              <Text style={styles.hPrice}>{formatINR(p.price)}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}

/* ─────────────────────────── Block: Section Header ─────────────────────────── */

function SectionTitle({ block }: { block: LayoutBlock }) {
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={[
        styles.sectionTitleText,
        block.text_color ? { color: block.text_color } : null,
        block.font_size ? { fontSize: block.font_size } : null,
        block.text_align ? { textAlign: alignToTextAlign(block.text_align) } : null,
      ]}>{block.title}</Text>
      {block.subtitle ? <Text style={styles.sectionTitleSub}>{block.subtitle}</Text> : null}
    </View>
  );
}

function SectionHeaderBlock({ block }: { block: LayoutBlock }) {
  return (
    <View style={styles.sectionHeaderWrap}>
      <SectionTitle block={block} />
    </View>
  );
}

/* ─────────────────────────── Block: Text ─────────────────────────── */

function TextBlock({ block }: { block: LayoutBlock }) {
  return (
    <View style={[styles.textBlock, block.bg_color ? { backgroundColor: block.bg_color } : null]}>
      {block.title ? (
        <Text style={[
          styles.textBlockTitle,
          block.text_color ? { color: block.text_color } : null,
          block.font_size ? { fontSize: block.font_size } : null,
          block.text_align ? { textAlign: alignToTextAlign(block.text_align) } : null,
        ]}>{block.title}</Text>
      ) : null}
      {block.body ? (
        <Text style={[
          styles.textBlockBody,
          block.text_color ? { color: block.text_color } : null,
          block.text_align ? { textAlign: alignToTextAlign(block.text_align) } : null,
        ]}>{block.body}</Text>
      ) : null}
    </View>
  );
}

/* ─────────────────────────── Block: Background (single banner) ─────────────────────────── */

function BackgroundBlock({
  block, onProductPress,
}: { block: LayoutBlock; onProductPress?: (id: string) => void }) {
  const height = resolveBlockHeight(block);
  const inner = (
    <View style={[styles.bannerBox, { height, backgroundColor: block.bg_color || colors.brand100 }]}>
      {block.image_data_url ? (
        <Image source={{ uri: block.image_data_url }} style={StyleSheet.absoluteFill as any} resizeMode="cover" />
      ) : null}
      {(block.title || block.subtitle) ? (
        <View style={[styles.bannerOverlay, { alignItems: alignToTextAlign(block.text_align) === "center" ? "center" : "flex-start" }]}>
          {block.subtitle ? (
            <Text style={[styles.bannerEyebrow, block.text_color ? { color: block.text_color } : null]}>{block.subtitle}</Text>
          ) : null}
          {block.title ? (
            <Text style={[
              styles.bannerTitle,
              block.text_color ? { color: block.text_color } : null,
              block.font_size ? { fontSize: block.font_size } : null,
            ]}>{block.title}</Text>
          ) : null}
          {block.cta_label ? (
            <View style={[styles.bannerCta, { backgroundColor: block.button_color || "#fff" }]}>
              <Text style={[styles.bannerCtaText, { color: block.button_text_color || colors.primary }]}>{block.cta_label}</Text>
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
  if (block.product_id) {
    return <TouchableOpacity activeOpacity={0.9} onPress={() => onProductPress?.(block.product_id!)}>{inner}</TouchableOpacity>;
  }
  return inner;
}

/* ─────────────────────────── Block: Content Box ─────────────────────────── */

function ContentBoxBlock({
  block, products, onProductPress,
}: { block: LayoutBlock; products: Record<string, Product>; onProductPress?: (id: string) => void }) {
  const p = block.product_id ? products[block.product_id] : null;
  const size = (block.size as "small" | "medium" | "large") || "medium";
  const height = block.height || SIZE_HEIGHT[size];
  if (p) {
    return (
      <TouchableOpacity
        style={[styles.productCard, { minHeight: height }]}
        onPress={() => onProductPress?.(p.id)}
        activeOpacity={0.85}
      >
        <View style={[styles.productImageWrap, { height: Math.max(100, height - 100) }]}>
          {pickImage(p) ? (
            <Image source={{ uri: pickImage(p) }} style={styles.productImage} resizeMode="cover" />
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
            <View style={[styles.viewBtn, block.button_color ? { backgroundColor: block.button_color } : null]}>
              <Text style={[styles.viewBtnText, block.button_text_color ? { color: block.button_text_color } : null]}>{block.cta_label || "View"}</Text>
              <Feather name="arrow-right" size={12} color={block.button_text_color || colors.primaryFg} />
            </View>
          </View>
        </View>
      </TouchableOpacity>
    );
  }
  return (
    <View style={[styles.contentBox, { minHeight: height }]}>
      {block.image_data_url ? (
        <Image source={{ uri: block.image_data_url }} style={[styles.contentImage, { height: Math.max(80, height - 80) }]} resizeMode="cover" />
      ) : null}
      <View style={{ padding: 14 }}>
        {block.title ? <Text style={styles.contentTitle}>{block.title}</Text> : null}
        {block.subtitle ? <Text style={styles.contentSub}>{block.subtitle}</Text> : null}
        {block.body ? <Text style={styles.contentBody}>{block.body}</Text> : null}
      </View>
    </View>
  );
}

/* ─────────────────────────── Main Renderer ─────────────────────────── */

export function ShopLayoutRenderer({
  scope = "home", category, onProductPress, onCategoryPress, onAddToCart,
}: RendererProps) {
  const [blocks, setBlocks] = useState<LayoutBlock[] | null>(null);
  const [productsById, setProductsById] = useState<Record<string, Product>>({});
  const [sourceCache, setSourceCache] = useState<Record<string, Product[]>>({});

  useEffect(() => {
    let cancelled = false;
    setBlocks(null);
    (async () => {
      try {
        const params: any = { scope };
        if (category) params.category = category;
        const [bRes, pRes] = await Promise.all([
          api.get<{ items: LayoutBlock[] }>("/shop-layout", { params }),
          api.get<any>("/products"),
        ]);
        if (cancelled) return;
        const blocks: LayoutBlock[] = bRes.data?.items || [];
        const pData = pRes.data;
        const pList: Product[] = Array.isArray(pData) ? pData : (pData?.items || pData?.products || []);
        const map: Record<string, Product> = {};
        pList.forEach((p) => { map[p.id] = p; });
        setProductsById(map);
        // Pre-fetch products for any block using a non-manual data source
        const dataPromises: Promise<void>[] = [];
        const cacheUpdates: Record<string, Product[]> = {};
        for (const b of blocks) {
          if (!b.active) continue;
          const usesProducts = ["product_grid", "horizontal_slider", "flash_sale"].includes(b.block_type);
          if (!usesProducts) continue;
          const ds = b.data_source || "manual";
          if (ds === "manual") {
            const ids = b.product_ids || [];
            const arr = ids.map((id) => map[id]).filter(Boolean) as Product[];
            cacheUpdates[b.id] = arr;
          } else {
            dataPromises.push((async () => {
              try {
                const r = await api.get<any>("/products/by-source", {
                  params: {
                    source: ds,
                    limit: b.product_count || 10,
                    ...(b.category_filter ? { category: b.category_filter } : (category ? { category } : {})),
                  },
                });
                const data = r.data;
                const arr: Product[] = Array.isArray(data) ? data : (data?.items || []);
                cacheUpdates[b.id] = arr;
              } catch {
                cacheUpdates[b.id] = [];
              }
            })());
          }
        }
        await Promise.all(dataPromises);
        if (cancelled) return;
        // Critical: commit BOTH the layout AND the product cache in the same
        // render tick. This avoids the "empty blocks flash" the user saw —
        // previously blocks rendered first (empty product lists), then the
        // by-source calls filled them in over the next 500-1500ms which
        // looked like the layout was missing or broken.
        setSourceCache(cacheUpdates);
        setBlocks(blocks);
      } catch {
        if (!cancelled) setBlocks([]);
      }
    })();
    return () => { cancelled = true; };
  }, [scope, category]);

  const visible = useMemo(
    () => (blocks || []).filter((b) => b.active).sort((a, b) => a.sort_order - b.sort_order),
    [blocks],
  );

  // Analytics: batch impressions + clicks and flush every 5s / on unmount
  const eventQueueRef = useRef<{ block_id: string; event: "impression" | "click"; scope: string }[]>([]);
  const lastFlushRef = useRef<number>(Date.now());

  const flush = React.useCallback(async () => {
    const queue = eventQueueRef.current;
    if (queue.length === 0) return;
    eventQueueRef.current = [];
    try {
      await api.post("/shop-layout/analytics", { events: queue });
    } catch { /* swallow analytics errors */ }
  }, []);

  useEffect(() => {
    if (visible.length === 0) return;
    // Log impression for each visible block once per renderer mount
    const seen = new Set<string>();
    visible.forEach((b) => {
      if (!seen.has(b.id)) {
        seen.add(b.id);
        eventQueueRef.current.push({ block_id: b.id, event: "impression", scope: scope || "home" });
      }
    });
    const t = setInterval(() => {
      if (Date.now() - lastFlushRef.current > 4500 && eventQueueRef.current.length) {
        flush();
        lastFlushRef.current = Date.now();
      }
    }, 5000);
    return () => { clearInterval(t); flush(); };
  }, [visible, scope, flush]);

  const trackClick = React.useCallback((blockId: string) => {
    eventQueueRef.current.push({ block_id: blockId, event: "click", scope: scope || "home" });
  }, [scope]);

  const wrapProductPress = (blockId: string) => (productId: string) => {
    trackClick(blockId);
    onProductPress?.(productId);
  };
  const wrapCategoryPress = (blockId: string) => (c: string) => {
    trackClick(blockId);
    onCategoryPress?.(c);
  };
  const wrapAddToCart = (blockId: string) => (productId: string) => {
    trackClick(blockId);
    onAddToCart?.(productId);
  };

  if (blocks === null) {
    // Loading skeletons
    return (
      <View style={{ marginBottom: 16 }}>
        <SkeletonBlock height={170} />
        <View style={{ height: 12 }} />
        <SkeletonBlock height={120} />
        <View style={{ height: 12 }} />
        <SkeletonBlock height={200} />
      </View>
    );
  }
  if (visible.length === 0) return null;

  return (
    <View style={{ marginBottom: 16 }}>
      {visible.map((b) => {
        // Resolve products for product-driven blocks
        let prods: Product[] = [];
        if (["product_grid", "horizontal_slider", "flash_sale"].includes(b.block_type)) {
          prods = sourceCache[b.id] || [];
        }
        switch (b.block_type) {
          case "banner_slider":
            return <BannerSliderBlock key={b.id} block={b} onProductPress={wrapProductPress(b.id)} onCategoryPress={wrapCategoryPress(b.id)} />;
          case "category_circles":
            return <CategoryCirclesBlock key={b.id} block={b} onCategoryPress={wrapCategoryPress(b.id)} />;
          case "brand_slider":
            return <BrandSliderBlock key={b.id} block={b} />;
          case "offer_cards":
            return <OfferCardsBlock key={b.id} block={b} onProductPress={wrapProductPress(b.id)} onCategoryPress={wrapCategoryPress(b.id)} />;
          case "announcement_strip":
            return <AnnouncementStripBlock key={b.id} block={b} />;
          case "flash_sale":
            return <FlashSaleBlock key={b.id} block={b} products={prods} onProductPress={wrapProductPress(b.id)} onAddToCart={wrapAddToCart(b.id)} />;
          case "product_grid":
            return <ProductGridBlock key={b.id} block={b} products={prods} onProductPress={wrapProductPress(b.id)} onAddToCart={wrapAddToCart(b.id)} />;
          case "horizontal_slider":
            return <HorizontalSliderBlock key={b.id} block={b} products={prods} onProductPress={wrapProductPress(b.id)} onAddToCart={wrapAddToCart(b.id)} />;
          case "section_header":
            return <SectionHeaderBlock key={b.id} block={b} />;
          case "text":
            return <TextBlock key={b.id} block={b} />;
          case "background":
            return <BackgroundBlock key={b.id} block={b} onProductPress={wrapProductPress(b.id)} />;
          case "content_box":
            return <ContentBoxBlock key={b.id} block={b} products={productsById} onProductPress={wrapProductPress(b.id)} />;
          default:
            return null;
        }
      })}
    </View>
  );
}

/* ─────────────────────────── Styles ─────────────────────────── */

const styles = StyleSheet.create({
  skeleton: { backgroundColor: colors.surfaceMuted, borderRadius: 14, marginBottom: 8, opacity: 0.6 },
  // Banner slider
  slide: { borderRadius: 18, overflow: "hidden", position: "relative" },
  slideOverlay: { position: "absolute", left: 16, right: 16, bottom: 16, backgroundColor: "rgba(0,0,0,0.32)", padding: 12, borderRadius: 12 },
  slideSub: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.4, opacity: 0.9 },
  slideTitle: { fontSize: 20, fontWeight: "900", color: "#fff", letterSpacing: -0.4, marginTop: 2 },
  slideCta: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, marginTop: 8, alignSelf: "flex-start" },
  slideCtaText: { fontSize: 11, fontWeight: "800" },
  dotsRow: { flexDirection: "row", justifyContent: "center", gap: 5, marginTop: 8 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.border },
  dotActive: { backgroundColor: colors.primary, width: 18 },
  // Category circles
  circleTile: { alignItems: "center", width: 70 },
  circleAvatar: { width: 60, height: 60, borderRadius: 30, overflow: "hidden", alignItems: "center", justifyContent: "center" },
  circleImg: { width: "100%", height: "100%" },
  circleLabel: { fontSize: 11, fontWeight: "700", color: colors.textMain, marginTop: 6, textAlign: "center" },
  // Brand slider
  brandTile: { width: 90, height: 50, borderRadius: 10, overflow: "hidden", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, padding: 6 },
  brandImg: { width: "100%", height: "100%" },
  brandText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  // Offer cards
  offerCard: { flexBasis: "48%", flexGrow: 1, borderRadius: 14, overflow: "hidden", minHeight: 90, position: "relative" },
  offerImg: { width: "100%", height: "100%", position: "absolute" },
  offerContent: { padding: 14, backgroundColor: "rgba(255,255,255,0.65)", minHeight: 90 },
  offerSub: { fontSize: 9, fontWeight: "900", letterSpacing: 1.2, color: colors.primary },
  offerTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginTop: 2, letterSpacing: -0.3 },
  // Announcement strip
  announceStrip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 9, borderRadius: 10, marginBottom: 12 },
  announceText: { fontSize: 12, fontWeight: "700" },
  // Flash sale
  flashWrap: { padding: 12, borderRadius: 16, marginBottom: 14 },
  flashHeader: { flexDirection: "row", alignItems: "center", marginBottom: 10, gap: 8 },
  flashTitle: { fontSize: 16, fontWeight: "900", color: "#991B1B", letterSpacing: -0.3 },
  flashSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  flashTimer: { flexDirection: "row", alignItems: "center", gap: 3 },
  flashTimerBox: { backgroundColor: "#111827", paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6, minWidth: 28, alignItems: "center" },
  flashTimerText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 0.4 },
  flashTimerSep: { color: "#111827", fontWeight: "900" },
  flashEnded: { fontSize: 11, fontWeight: "800", color: colors.textMuted, fontStyle: "italic" },
  flashCard: { width: 110, backgroundColor: "#fff", borderRadius: 10, overflow: "hidden" },
  flashCardImageWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  flashCardImg: { width: "100%", height: "100%" },
  flashCardName: { fontSize: 11, fontWeight: "700", color: colors.textMain, padding: 6, paddingBottom: 0 },
  flashCardPrice: { fontSize: 13, fontWeight: "900", color: "#DC2626", paddingHorizontal: 6, paddingBottom: 6 },
  // Product grid
  gridWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  gridCard: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  gridImgWrap: { width: "100%", aspectRatio: 1.1, backgroundColor: colors.surfaceMuted, position: "relative" },
  gridImg: { width: "100%", height: "100%" },
  gridOOSBadge: { position: "absolute", top: 8, left: 8, backgroundColor: "#B91C1C", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  gridOOSText: { fontSize: 8, color: "#fff", fontWeight: "900", letterSpacing: 0.6 },
  gridName: { fontSize: 12, fontWeight: "700", color: colors.textMain, minHeight: 30, lineHeight: 15 },
  gridFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 },
  gridPrice: { fontSize: 14, fontWeight: "900", color: colors.primary, letterSpacing: -0.3 },
  gridAdd: { width: 30, height: 30, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  // Horizontal slider
  hCard: { width: 130, backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, overflow: "hidden", padding: 8 },
  hImgWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, borderRadius: 8, overflow: "hidden" },
  hImg: { width: "100%", height: "100%" },
  hName: { fontSize: 11, fontWeight: "700", color: colors.textMain, marginTop: 6, minHeight: 28 },
  hPrice: { fontSize: 13, fontWeight: "900", color: colors.primary, marginTop: 2 },
  // Section header
  sectionHeaderWrap: { marginTop: 6, marginBottom: 6 },
  sectionTitleText: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3, textTransform: "none" },
  sectionTitleSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  // Text block
  textBlock: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 14, marginBottom: 12 },
  textBlockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 4 },
  textBlockBody: { fontSize: 13, color: colors.textMuted, lineHeight: 20 },
  // Product card (content_box)
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
  // Manual content box fallback
  contentBox: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, overflow: "hidden", marginBottom: 12 },
  contentImage: { width: "100%" },
  contentTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  contentSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  contentBody: { fontSize: 13, color: colors.textMain, lineHeight: 20, marginTop: 6 },
  // Background banner (single image)
  bannerBox: { borderRadius: radii.card, overflow: "hidden", marginBottom: 12, backgroundColor: colors.brand100, position: "relative" },
  bannerOverlay: { position: "absolute", left: 16, bottom: 16, right: 16, backgroundColor: "rgba(0,0,0,0.35)", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 12 },
  bannerEyebrow: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.4, opacity: 0.9 },
  bannerTitle: { fontSize: 18, fontWeight: "900", color: "#fff", letterSpacing: -0.4, marginTop: 2 },
  bannerCta: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, marginTop: 8, alignSelf: "flex-start" },
  bannerCtaText: { fontSize: 11, fontWeight: "800" },
});
