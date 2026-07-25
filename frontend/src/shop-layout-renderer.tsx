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
  Dimensions, FlatList, Platform, AppState,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api } from "./api";
import { cachedGet } from "./cachedGet";
import { colors, radii, formatINR } from "./theme";
import { ContentContainer, SHOP_CARD_RADIUS, SHOP_BANNER_RADIUS, SHOP_SECTION_GAP, SHOP_TYPO } from "./content-container";
import { useAuth } from "./auth";

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
  // Aug 2026 — "cover" (default, may crop) or "contain" (show full image, no crop)
  image_fit?: "cover" | "contain";
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
  // Aug 2026 — controls resizeMode for the block's hero image
  image_fit?: "cover" | "contain";
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
  // Grid extras
  products_per_row?: number;       // 1..4
  show_view_all?: boolean;
  view_all_link?: string;          // category name (empty = /shop)
  // Sept 2026 — For `category_circles` only.  Explicit shop_category ids
  // to render.  Empty ⇒ "auto-mode" (fill with every category NOT already
  // rendered by an earlier category_circles block on the same scope).
  category_ids?: string[];
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
  vendor_id?: string | null;
};

type RendererProps = {
  scope?: "home" | "category";
  category?: string;
  onProductPress?: (productId: string) => void;
  onCategoryPress?: (category: string) => void;
  onAddToCart?: (productId: string) => void;
  // Aug 2026 — parent bumps this counter to force a live re-fetch of admin
  // blocks (e.g. on pull-to-refresh or after an admin publish). Included in
  // the useEffect deps so the renderer re-runs its data load.
  refreshTick?: number;
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
  // June 2026 Shop redesign — banner height clamped to spec range 180–220 dp.
  // Use the block's configured size when set; default to 200 dp.
  const heightRaw = resolveBlockHeight(block);
  const height = Math.max(180, Math.min(220, heightRaw || 200));
  // Slide width = inner width of the ContentContainer (16 dp padding each
  // side). Banner must never overflow the container per spec.
  const slideWidth = screenWidth - 32;
  // Auto-advance every 4s
  useEffect(() => {
    if (items.length <= 1) return;
    const t = setInterval(() => setIdx((i) => (i + 1) % items.length), 4000);
    return () => clearInterval(t);
  }, [items.length]);
  if (items.length === 0) return null;
  return (
    <View>
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
                <Image
                  source={{ uri: item.image_data_url }}
                  style={StyleSheet.absoluteFill as any}
                  resizeMode={
                    (item.image_fit || block.image_fit) === "contain" ? "contain" : "cover"
                  }
                />
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

// Shape returned by /api/shop-categories
type ApiCategory = {
  id: string;
  name: string;
  slug: string;
  icon_pack: "feather" | "mci" | "mat";
  icon_name: string;
  image_url: string | null;
  color: string;
  sort_order: number;
  active: boolean;
};

function CategoryCirclesBlock({
  block, onCategoryPress, excludeCategoryIds,
}: {
  block: LayoutBlock;
  onCategoryPress?: (c: string) => void;
  // IDs that should NOT appear in this block because they've been pinned
  // to an earlier category_circles block on the same scope (auto-dedupe).
  excludeCategoryIds?: Set<string>;
}) {
  // INTERLINKED: Always source categories from the admin-managed
  // /api/shop-categories DB so a single edit in /admin/shop-categories
  // (icon, image, color, name) reflects on every category_circles block
  // across all scopes (home, category, admin shop preview).
  // Falls back to block.items only if the API returns nothing AND the
  // block has items (legacy support).
  const [apiCats, setApiCats] = useState<ApiCategory[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    const apply = (data: { items?: ApiCategory[] } | null) => {
      if (cancelled) return;
      const items = (data?.items || []).filter((c) => c.active !== false);
      items.sort((a, b) => (a.sort_order - b.sort_order) || a.name.localeCompare(b.name));
      setApiCats(items);
    };
    (async () => {
      try {
        // Sept 2026 — cachedGet paints instantly from a prior mount + AsyncStorage.
        const cached = await cachedGet<{ items: ApiCategory[] }>("/shop-categories", {
          ttlMs: 120_000,
          onFresh: (fresh) => apply(fresh),
        });
        if (cached) apply(cached);
        else apply(null);  // first-ever mount — background fetch will fire onFresh
      } catch {
        if (!cancelled) setApiCats([]);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Sept 2026 — Two selection modes:
  //   1. Explicit — block.category_ids has entries ⇒ show exactly those.
  //   2. Auto — empty list ⇒ show every category NOT already used in an
  //      earlier category_circles block on this scope (excludeCategoryIds).
  //      This is the "auto-dedupe" behaviour so an admin can have one
  //      block for "featured" categories and another block that fills
  //      with "everything else" without repeating.
  const explicit = Array.isArray(block.category_ids) && block.category_ids.length > 0;
  const filteredCats = (apiCats || []).filter((c) => {
    if (explicit) return (block.category_ids as string[]).includes(c.id);
    if (excludeCategoryIds && excludeCategoryIds.has(c.id)) return false;
    return true;
  });

  // Build a unified items list: prefer API categories.
  const apiItems = filteredCats.map<LayoutItem & { _pack?: string; _icon?: string }>((c) => ({
    label: c.name,
    image_data_url: c.image_url || "",
    color: c.color,
    link_type: "category" as const,
    link_value: c.name,
    _pack: c.icon_pack,
    _icon: c.icon_name,
  }));
  const fallbackItems = block.items || [];
  const items = apiItems.length > 0 ? apiItems : (explicit ? [] : fallbackItems);

  if (apiCats === null) return <SkeletonBlock height={100} />;
  if (items.length === 0) return null;
  return (
    <View>
      {block.title ? <SectionTitle block={block} /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 4 }}>
        {items.map((it: any, i) => (
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
    <View>
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
    <View>
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
  block, products, onProductPress, onAddToCart, onViewAll,
}: { block: LayoutBlock; products: Product[]; onProductPress?: (id: string) => void; onAddToCart?: (id: string) => void; onViewAll?: (target: string) => void }) {
  if (products.length === 0) return <SkeletonBlock height={160} />;
  const perRow = Math.max(1, Math.min(4, block.products_per_row || 2));
  // ── Nov 2026 — Responsive card sizing that respects the 4-column
  // request from the admin without wrapping into a single column.
  //
  // Previous version used `flexBasis: 47.5%` (from gridCard) combined
  // with a percent basisPct override AND a 16dp gap, which pushed the
  // total row width over 100% at perRow ≥ 3 and forced each card onto
  // its own row (the "going down by down" bug the user reported).
  //
  // We now compute the exact card width in points against the visible
  // ContentContainer inner width and use a tighter gap (10dp) for
  // dense layouts so the cards align edge-to-edge cleanly. This also
  // means the image aspect ratio and price look identical across
  // all four column configurations.
  const PADDING = 16; // ContentContainer horizontal padding (each side)
  const gap = perRow >= 3 ? 10 : perRow === 2 ? 12 : 0;
  const availableWidth = screenWidth - PADDING * 2;
  const cardWidth = Math.floor((availableWidth - gap * (perRow - 1)) / perRow);
  const size = block.size || "medium";
  // Aspect ratio of the image varies with card size — smaller cards get
  // a slightly taller-than-square image, larger cards get square.
  const aspect = size === "small" ? 1 : size === "large" ? 0.95 : 1.05;
  const nameLines = perRow >= 3 ? 1 : 2;
  const fontMul = perRow >= 4 ? 0.82 : perRow >= 3 ? 0.9 : 1;
  const cardPadding = perRow >= 4 ? 5 : perRow >= 3 ? 6 : 8;
  const innerPadding = perRow >= 3 ? 6 : 10;
  return (
    <View>
      {(block.title || block.show_view_all) ? (
        <View style={styles.gridHeader}>
          <View style={{ flex: 1, minWidth: 0 }}>
            {block.title ? <SectionTitle block={block} /> : null}
          </View>
          {block.show_view_all ? (
            <TouchableOpacity
              onPress={() => onViewAll?.(block.view_all_link || block.category_filter || "")}
              style={styles.gridViewAllBtn}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              testID={`grid-view-all-${block.id}`}
            >
              <Text style={styles.gridViewAllText}>View More</Text>
              <Feather name="chevron-right" size={13} color={colors.primary} />
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}
      <View style={[styles.gridWrap, { gap }]}>
        {products.slice(0, block.product_count || 12).map((p) => {
          const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
          return (
            <TouchableOpacity
              key={p.id}
              style={[
                styles.gridCard,
                { width: cardWidth, padding: cardPadding, flexBasis: undefined as any },
                !inStock && { opacity: 0.55 },
              ]}
              activeOpacity={0.85}
              onPress={() => onProductPress?.(p.id)}
            >
              <View style={[styles.gridImgWrap, { aspectRatio: aspect }]}>
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
              <View style={{ paddingHorizontal: innerPadding - cardPadding, paddingTop: innerPadding - cardPadding + 6, paddingBottom: 2 }}>
                <Text
                  style={[styles.gridName, {
                    fontSize: 12.5 * fontMul,
                    minHeight: nameLines === 1 ? 16 : 32,
                    marginTop: 0,
                    lineHeight: 16 * (perRow >= 3 ? 0.9 : 1),
                  }]}
                  numberOfLines={nameLines}
                >{p.name}</Text>
                <View style={[styles.gridFooter, { marginTop: perRow >= 3 ? 3 : 6 }]}>
                  <Text
                    style={[styles.gridPrice, { fontSize: 14 * fontMul }]}
                    numberOfLines={1}
                  >{formatINR(p.price)}</Text>
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
    <View>
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
    <View>
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
        <Image
          source={{ uri: block.image_data_url }}
          style={StyleSheet.absoluteFill as any}
          resizeMode={block.image_fit === "contain" ? "contain" : "cover"}
        />
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
  scope = "home", category, onProductPress, onCategoryPress, onAddToCart, refreshTick,
}: RendererProps) {
  const [blocks, setBlocks] = useState<LayoutBlock[] | null>(null);
  const [productsById, setProductsById] = useState<Record<string, Product>>({});
  const [sourceCache, setSourceCache] = useState<Record<string, Product[]>>({});
  // Aug 2026 — Auto-poll counter for live admin updates (30 s interval).
  const [pollTick, setPollTick] = useState(0);
  // UPDATE 1 — Hide the current vendor's own products from all admin-managed
  // layout blocks so a vendor can't accidentally buy their own inventory.
  const { user } = useAuth();
  const currentUserId = user?.id || null;
  const excludeOwn = <T extends { vendor_id?: string | null }>(arr: T[]): T[] =>
    (currentUserId ? arr.filter((p) => !p.vendor_id || p.vendor_id !== currentUserId) : arr);

  useEffect(() => {
    let cancelled = false;
    setBlocks(null);
    (async () => {
      try {
        const params: any = { scope };
        if (category) params.category = category;
        // Sept 2026 — layout is admin-config and rarely changes → 2 min
        // cache TTL. Paints instantly on repeat visits.
        const applyLayout = (bData: { items?: LayoutBlock[] } | null) => {
          if (cancelled) return null;
          return bData?.items || [];
        };
        const [bRes, pRes] = await Promise.all([
          cachedGet<{ items: LayoutBlock[] }>("/shop-layout", {
            ttlMs: 120_000,
            params,
            onFresh: (fresh) => {
              const items = applyLayout(fresh);
              if (items) setBlocks(items);
            },
          }),
          // Nov 2026 — pass cascading category filter so /products
          // returns Electronics + Mobiles + Chargers when the customer
          // taps "Electronics".  Falls back to the whole catalog on the
          // home scope.
          api.get<any>("/products", {
            params: category ? { category, limit: 120 } : {},
          }),
        ]);
        if (cancelled) return;
        const blocks: LayoutBlock[] = bRes?.items || [];
        const pData = pRes.data;
        const pListRaw: Product[] = Array.isArray(pData) ? pData : (pData?.items || pData?.products || []);
        // UPDATE 1 — Drop the current vendor's own products before caching.
        const pList: Product[] = excludeOwn(pListRaw);
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
                cacheUpdates[b.id] = excludeOwn(arr);
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
  }, [scope, category, currentUserId, refreshTick, pollTick]);

  // Aug 2026 — Silent auto-poll every 30s while the app is foregrounded so
  // admin publishes appear live without a manual pull-to-refresh.  Bumps
  // `pollTick` which is in the deps array above, so the fetch re-runs.
  useEffect(() => {
    const interval = setInterval(() => {
      if (AppState.currentState === "active") {
        setPollTick((n) => n + 1);
      }
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  const visible = useMemo(
    () => (blocks || []).filter((b) => b.active).sort((a, b) => a.sort_order - b.sort_order),
    [blocks],
  );

  // Nov 2026 — Auto-inject Product Grid blocks between banners so
  // customers never see an "empty" shop layout when the admin drops a
  // banner without a manual product_grid below it.  Rule set:
  //   • A "banner" is any purely-visual block: banner_slider, background,
  //     offer_cards, brand_slider, announcement_strip, section_header,
  //     text, category_circles, content_box.
  //   • After each banner we walk forward — if we do NOT hit a product-
  //     bearing block (product_grid / horizontal_slider / flash_sale)
  //     before the next banner, we insert a synthetic product_grid.
  //   • The synthetic grid's data source cascades the current customer
  //     context: `category` when we're inside a category screen (scope
  //     === "category"), otherwise "new" (latest arrivals).
  //   • Injected grids are keyed with a stable `__auto:{parentId}` id so
  //     React remounts don't thrash.
  const augmented = useMemo<LayoutBlock[]>(() => {
    if (visible.length === 0) return visible;
    const PRODUCT_TYPES = new Set(["product_grid", "horizontal_slider", "flash_sale"]);
    const BANNER_TYPES = new Set([
      "banner_slider", "background", "offer_cards", "brand_slider",
      "announcement_strip", "section_header", "text",
      "category_circles", "content_box",
    ]);
    const out: LayoutBlock[] = [];
    for (let i = 0; i < visible.length; i++) {
      const b = visible[i];
      out.push(b);
      if (!BANNER_TYPES.has(b.block_type)) continue;
      // Peek forward — do we already have a product block right after?
      const next = visible[i + 1];
      if (next && PRODUCT_TYPES.has(next.block_type)) continue;
      // Skip auto-inject if the very next block is another banner-of-
      // same-type (e.g. two announcement strips) to keep the layout tidy.
      const autoId = `__auto:${b.id}`;
      out.push({
        id: autoId,
        block_type: "product_grid",
        scope: b.scope,
        scope_category: b.scope_category,
        active: true,
        sort_order: (b.sort_order ?? 0) + 0.5,
        title: "",           // no heading — visual continuity
        data_source: (category ? "category" : "new") as any,
        category_filter: category || "",
        product_count: 8,
        layout_style: "grid" as any,
        product_ids: [] as string[],
      } as LayoutBlock);
    }
    return out;
  }, [visible, category]);

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
    if (augmented.length === 0) return;
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

  // Nov 2026 — When the app auto-injects a synthetic product_grid, we
  // need a product list for it too.  Rather than firing another N
  // /products/by-source requests, we reuse the top-of-catalogue list
  // (`productsById` — already fetched) filtered by the current
  // `category` prop (if any).  This is completely client-side so it
  // renders instantly and doesn't extend the loading state.
  const autoBlockProducts = useMemo<Product[]>(() => {
    const all = Object.values(productsById);
    if (!category) return all.slice(0, 20);
    const lc = category.toLowerCase();
    const filtered = all.filter((p: any) => {
      const c = String(p?.category || "").toLowerCase();
      const s = String(p?.subcategory || "").toLowerCase();
      return c === lc || s === lc;
    });
    // Fallback — if nothing matches (vendor tagged with a different
    // free-form label), show newest anything so the block never blanks.
    return (filtered.length > 0 ? filtered : all).slice(0, 20);
  }, [productsById, category]);

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
  if (augmented.length === 0) return null;

  // Sept 2026 — Compute an accumulated "already-used category ids" map so
  // each CategoryCirclesBlock in auto-mode (empty category_ids) can skip
  // categories that appeared in an earlier circle block on this scope.
  // Explicit-mode blocks (non-empty category_ids) ALSO contribute their
  // IDs to the "consumed" set so subsequent auto blocks fill the gap.
  const consumedByEarlierCircles: Map<string, Set<string>> = new Map();
  {
    const running = new Set<string>();
    for (const b of visible) {
      // Snapshot BEFORE mutating so this block sees what earlier blocks used.
      consumedByEarlierCircles.set(b.id, new Set(running));
      if (b.block_type === "category_circles" && Array.isArray(b.category_ids)) {
        for (const cid of b.category_ids) running.add(cid);
      }
    }
  }

  return (
    <View>
      {augmented.map((b) => {
        // Resolve products for product-driven blocks
        let prods: Product[] = [];
        if (["product_grid", "horizontal_slider", "flash_sale"].includes(b.block_type)) {
          // Auto-injected synthetic blocks have ids prefixed with __auto:
          // and their product list comes from the client-side filter
          // (no extra network round-trip).
          prods = b.id.startsWith("__auto:")
            ? autoBlockProducts
            : (sourceCache[b.id] || []);
        }
        // June 2026 Shop redesign — every block (admin-created or hardcoded)
        // is wrapped in <ContentContainer> so they all align on the same
        // vertical rail (16 dp left/right) with a consistent 16 dp inter-
        // section gap. The block components themselves no longer add their
        // own marginBottom — that's now ContentContainer's job. This
        // guarantees a new block-type added in the future inherits the
        // page layout automatically without touching ShopHome.
        let node: React.ReactNode = null;
        switch (b.block_type) {
          case "banner_slider":
            node = <BannerSliderBlock block={b} onProductPress={wrapProductPress(b.id)} onCategoryPress={wrapCategoryPress(b.id)} />; break;
          case "category_circles":
            node = <CategoryCirclesBlock block={b} onCategoryPress={wrapCategoryPress(b.id)} excludeCategoryIds={consumedByEarlierCircles.get(b.id)} />; break;
          case "brand_slider":
            node = <BrandSliderBlock block={b} />; break;
          case "offer_cards":
            node = <OfferCardsBlock block={b} onProductPress={wrapProductPress(b.id)} onCategoryPress={wrapCategoryPress(b.id)} />; break;
          case "announcement_strip":
            node = <AnnouncementStripBlock block={b} />; break;
          case "flash_sale":
            node = <FlashSaleBlock block={b} products={prods} onProductPress={wrapProductPress(b.id)} onAddToCart={wrapAddToCart(b.id)} />; break;
          case "product_grid":
            node = <ProductGridBlock block={b} products={prods} onProductPress={wrapProductPress(b.id)} onAddToCart={wrapAddToCart(b.id)} onViewAll={(target) => { trackClick(b.id); onCategoryPress?.(target || ""); }} />; break;
          case "horizontal_slider":
            node = <HorizontalSliderBlock block={b} products={prods} onProductPress={wrapProductPress(b.id)} onAddToCart={wrapAddToCart(b.id)} />; break;
          case "section_header":
            node = <SectionHeaderBlock block={b} />; break;
          case "text":
            node = <TextBlock block={b} />; break;
          case "background":
            node = <BackgroundBlock block={b} onProductPress={wrapProductPress(b.id)} />; break;
          case "content_box":
            node = <ContentBoxBlock block={b} products={productsById} onProductPress={wrapProductPress(b.id)} />; break;
          default:
            return null;
        }
        return (
          <ContentContainer key={b.id}>
            {node}
          </ContentContainer>
        );
      })}
      {/* Footer space — final 16 dp breather so the last block doesn't sit
          flush against the bottom tab bar. */}
      <View style={{ height: 16 }} />
    </View>
  );
}

/* ─────────────────────────── Styles ─────────────────────────── */

const styles = StyleSheet.create({
  skeleton: { backgroundColor: colors.surfaceMuted, borderRadius: SHOP_CARD_RADIUS, opacity: 0.6 },
  // Banner slider — 16 px radius per spec.
  slide: { borderRadius: SHOP_BANNER_RADIUS, overflow: "hidden", position: "relative" },
  slideOverlay: { position: "absolute", left: 16, right: 16, bottom: 16, backgroundColor: "rgba(0,0,0,0.32)", padding: 12, borderRadius: 12 },
  slideSub: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.4, opacity: 0.9 },
  slideTitle: { fontSize: 20, fontWeight: "900", color: "#fff", letterSpacing: -0.4, marginTop: 2 },
  slideCta: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, marginTop: 8, alignSelf: "flex-start" },
  slideCtaText: { fontSize: 11, fontWeight: "800" },
  dotsRow: { flexDirection: "row", justifyContent: "center", gap: 5, marginTop: 8 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.border },
  dotActive: { backgroundColor: colors.primary, width: 18 },
  // Category circles — equal width / icon size / spacing per spec.
  circleTile: { alignItems: "center", width: 70 },
  circleAvatar: { width: 60, height: 60, borderRadius: 30, overflow: "hidden", alignItems: "center", justifyContent: "center" },
  circleImg: { width: "100%", height: "100%" },
  circleLabel: { fontSize: 11, fontWeight: "700", color: colors.textMain, marginTop: 6, textAlign: "center" },
  // Brand slider
  brandTile: { width: 90, height: 50, borderRadius: 10, overflow: "hidden", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, padding: 6 },
  brandImg: { width: "100%", height: "100%" },
  brandText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  // Offer cards
  offerCard: { flexBasis: "48%", flexGrow: 1, borderRadius: SHOP_CARD_RADIUS, overflow: "hidden", minHeight: 90, position: "relative" },
  offerImg: { width: "100%", height: "100%", position: "absolute" },
  offerContent: { padding: 14, backgroundColor: "rgba(255,255,255,0.65)", minHeight: 90 },
  offerSub: { fontSize: 9, fontWeight: "900", letterSpacing: 1.2, color: colors.primary },
  offerTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginTop: 2, letterSpacing: -0.3 },
  // Announcement / Offer strip
  announceStrip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 9, borderRadius: 10 },
  announceText: { fontSize: 12, fontWeight: "700" },
  // Flash sale / Deal of the Day
  flashWrap: { padding: 12, borderRadius: SHOP_BANNER_RADIUS },
  flashHeader: { flexDirection: "row", alignItems: "center", marginBottom: 10, gap: 8 },
  flashTitle: { ...SHOP_TYPO.sectionTitle, color: "#991B1B" },
  flashSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  flashTimer: { flexDirection: "row", alignItems: "center", gap: 3 },
  flashTimerBox: { backgroundColor: "#111827", paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6, minWidth: 28, alignItems: "center" },
  flashTimerText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 0.4 },
  flashTimerSep: { color: "#111827", fontWeight: "900" },
  flashEnded: { fontSize: 11, fontWeight: "800", color: colors.textMuted, fontStyle: "italic" },
  flashCard: { width: 110, backgroundColor: "#fff", borderRadius: SHOP_CARD_RADIUS, overflow: "hidden" },
  flashCardImageWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  flashCardImg: { width: "100%", height: "100%" },
  flashCardName: { ...SHOP_TYPO.productName, fontSize: 12, padding: 6, paddingBottom: 0 },
  flashCardPrice: { fontSize: 13, fontWeight: "900", color: "#DC2626", paddingHorizontal: 6, paddingBottom: 6 },
  // Product grid — 2 columns, equal width/height per spec.
  gridHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8, gap: 8 },
  gridViewAllBtn: { flexDirection: "row", alignItems: "center", gap: 2, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.brand100 },
  gridViewAllText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
  // gap:16 → matches the global 16 dp inter-card gap requested in the spec.
  gridWrap: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  gridCard: {
    // Width is set inline by ProductGridBlock (based on perRow + gap +
    // screen width) so removing flexBasis here prevents the double-
    // definition that pushed 3/4-column grids into single-column mode.
    backgroundColor: "#FFFFFF",
    borderRadius: SHOP_CARD_RADIUS,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
    padding: 8,
    // Soft shadow (iOS) + elevation (Android) per spec.
    ...Platform.select({
      ios: {
        shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 2 },
      },
      android: { elevation: 2 },
    }),
  },
  gridImgWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, position: "relative", borderRadius: 8, overflow: "hidden" },
  gridImg: { width: "100%", height: "100%" },
  gridOOSBadge: { position: "absolute", top: 8, left: 8, backgroundColor: "#B91C1C", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  gridOOSText: { fontSize: 8, color: "#fff", fontWeight: "900", letterSpacing: 0.6 },
  gridName: { ...SHOP_TYPO.productName, color: colors.textMain, minHeight: 36, lineHeight: 18, marginTop: 8 },
  gridFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 },
  gridPrice: { ...SHOP_TYPO.price, color: colors.primary, letterSpacing: -0.3 },
  gridAdd: { width: 32, height: 32, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  // Horizontal product slider (Best Sellers / Featured / Recently Added)
  hCard: { width: 140, backgroundColor: colors.surface, borderRadius: SHOP_CARD_RADIUS, borderWidth: 1, borderColor: colors.border, overflow: "hidden", padding: 8 },
  hImgWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, borderRadius: 8, overflow: "hidden" },
  hImg: { width: "100%", height: "100%" },
  hName: { ...SHOP_TYPO.productName, fontSize: 13, marginTop: 8, minHeight: 32 },
  hPrice: { ...SHOP_TYPO.price, color: colors.primary, marginTop: 4 },
  // Section header — Bold 18 per spec.
  sectionHeaderWrap: { marginTop: 0, marginBottom: 8 },
  sectionTitleText: { ...SHOP_TYPO.sectionTitle, color: colors.textMain },
  sectionTitleSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  // Text block
  textBlock: { backgroundColor: colors.surface, borderRadius: SHOP_CARD_RADIUS, borderWidth: 1, borderColor: colors.border, padding: 14 },
  textBlockTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginBottom: 4 },
  textBlockBody: { fontSize: 13, color: colors.textMuted, lineHeight: 20 },
  // Product card (content_box)
  productCard: { backgroundColor: colors.surface, borderRadius: SHOP_CARD_RADIUS, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  productImageWrap: { width: "100%", backgroundColor: colors.surfaceMuted, position: "relative" },
  productImage: { width: "100%", height: "100%" },
  productImageEmpty: { flex: 1, alignItems: "center", justifyContent: "center" },
  oosBadge: { position: "absolute", top: 10, left: 10, backgroundColor: "#B91C1C", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  oosBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff", letterSpacing: 0.6 },
  productInfo: { padding: 12 },
  productName: { ...SHOP_TYPO.sectionTitle, fontSize: 16, color: colors.textMain },
  productDesc: { fontSize: 12, color: colors.textMuted, marginTop: 3, lineHeight: 18 },
  productFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 10 },
  productPrice: { ...SHOP_TYPO.price, fontSize: 17, color: colors.primary, letterSpacing: -0.4 },
  viewBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.primary, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999 },
  viewBtnText: { fontSize: 11, fontWeight: "800", color: colors.primaryFg },
  // Manual content box fallback
  contentBox: { backgroundColor: colors.surface, borderRadius: SHOP_CARD_RADIUS, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  contentImage: { width: "100%" },
  contentTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  contentSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  contentBody: { fontSize: 13, color: colors.textMain, lineHeight: 20, marginTop: 6 },
  // Background banner (single image) — 16 px radius matching slider.
  bannerBox: { borderRadius: SHOP_BANNER_RADIUS, overflow: "hidden", backgroundColor: colors.brand100, position: "relative" },
  bannerOverlay: { position: "absolute", left: 16, bottom: 16, right: 16, backgroundColor: "rgba(0,0,0,0.35)", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 12 },
  bannerEyebrow: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1.4, opacity: 0.9 },
  bannerTitle: { ...SHOP_TYPO.sectionTitle, color: "#fff", marginTop: 2 },
  bannerCta: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, marginTop: 8, alignSelf: "flex-start" },
  bannerCtaText: { fontSize: 11, fontWeight: "800" },
});
