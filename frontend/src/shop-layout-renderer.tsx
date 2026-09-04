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
  FlatList, Platform, useWindowDimensions,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api, resolveImageUrl } from "./api";
import { cachedGet } from "./cachedGet";
import { colors, formatINR } from "./theme";
import { ContentContainer, SHOP_CARD_RADIUS, SHOP_BANNER_RADIUS, SHOP_SECTION_GAP, SHOP_TYPO } from "./content-container";
import { useAuth } from "./auth";

/* ─────────────────────────── Types ─────────────────────────── */

export type BlockType =
  | "banner_slider" | "product_grid" | "horizontal_slider"
  | "category_circles" | "flash_sale" | "offer_cards"
  | "brand_slider" | "announcement_strip"
  | "background" | "section_header" | "text" | "content_box"
  // Jun 2026 — full-width immersive showcase (~1/3 of a phone screen)
  | "spotlight";

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
  // Jul 2026 — Delivery location from the parent (customer's chosen area).
  // Forwarded to /products and /shop-layout so only products from vendors
  // that actually deliver to the customer render.
  pincode?: string;
  lat?: number;
  lng?: number;
  onProductPress?: (productId: string) => void;
  onCategoryPress?: (category: string) => void;
  onAddToCart?: (productId: string) => void;
  /** Called with the number of renderable blocks once the layout resolves. */
  onBlocksResolved?: (count: number) => void;
  // Aug 2026 — parent bumps this counter to force a live re-fetch of admin
  // blocks (e.g. on pull-to-refresh or after an admin publish). Included in
  // the useEffect deps so the renderer re-runs its data load.
  refreshTick?: number;
};

/** Block types that render a list of products (need a product fetch). */
const PRODUCT_BLOCK_TYPES: string[] = ["product_grid", "horizontal_slider", "flash_sale", "spotlight"];

const SIZE_HEIGHT: Record<"small" | "medium" | "large", number> = {
  small: 130, medium: 180, large: 240,
};

/* Jun 2026 — module-level width removed: every block now reads the live
   window width via useWindowDimensions() so tablets / rotation / web
   resize all lay out correctly. */

/* ─────────────────────────── Skeleton loaders ─────────────────────────── */

function SkeletonBlock({ height = 140 }: { height?: number }) {
  return <View style={[styles.skeleton, { height }]} />;
}

/* ─────────────────────────── Helpers ─────────────────────────── */

function pickImage(p?: Product): string | undefined {
  if (!p) return undefined;
  const raw = (p as any).image_data_url || p.image_url || p.images?.[0];
  return resolveImageUrl(raw) || undefined;
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
  //
  // Jun 2026 tablet fix — `screenWidth` was read ONCE at module load, so
  // rotating a tablet (or resizing the web window) left the banner at the
  // old width.  It also kept the phone height cap of 220 dp on a ~1000 dp
  // wide tablet, squashing the 1080×600 artwork into a 4.5:1 letterbox
  // strip.  We now track the live window width and grow the banner height
  // proportionally on wide screens.
  const { width: winW } = useWindowDimensions();
  const heightRaw = resolveBlockHeight(block);
  const slideWidth = winW - 32;
  const height = winW >= 700
    ? Math.min(380, Math.max(220, Math.round(slideWidth / 2.2)))
    : Math.max(180, Math.min(220, heightRaw || 200));
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
  /** Hierarchy — main categories have depth 0 / no parent. */
  depth?: number;
  parent_id?: string | null;
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
    // Jun 2026 — MAIN categories only. Sub-categories used to appear as
    // circles too, so the navigator was a long list of leaf labels the
    // customer had no context for. They're still reachable from inside
    // their parent category screen.
    const depth = Number((c as any).depth || 0);
    const isMain = depth === 0 && !(c as any).parent_id;
    if (!isMain) return false;
    if (explicit) return (block.category_ids as string[]).includes(c.id);
    if (excludeCategoryIds && excludeCategoryIds.has(c.id)) return false;
    return true;
  });

  // Jun 2026 — PER-BLOCK image override.
  // The admin can give a category a different picture inside THIS block
  // without touching the master image in /admin/shop-categories (so the
  // same category can be merchandised differently on Home vs a campaign
  // block). Overrides live in `block.items` keyed by category name.
  const overrideByName = new Map<string, string>();
  (block.items || []).forEach((it) => {
    const k = (it.label || "").trim().toLowerCase();
    if (k && it.image_data_url) overrideByName.set(k, it.image_data_url);
  });

  // Build a unified items list: prefer API categories.
  const apiItems = filteredCats.map<LayoutItem & { _pack?: string; _icon?: string }>((c) => ({
    label: c.name,
    image_data_url: overrideByName.get(c.name.trim().toLowerCase()) || c.image_url || "",
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

/* ─────────────────────────── Block: Brand Slider ───────────────────────────
 *
 * Jun 2026 rework, per owner feedback:
 *   • Tapping a tile did NOTHING — `link_type` / `link_value` were never
 *     wired, so the product / category the admin picked was unreachable.
 *   • Tiles were 90×50 dp — too small to read the logo or the label.
 *   • The admin's title never rendered; now it shows UNDER the image with
 *     a guaranteed 2-line clamp so long brand names stay legible.
 */

function BrandSliderBlock({
  block, onProductPress, onCategoryPress,
}: { block: LayoutBlock; onProductPress?: (id: string) => void; onCategoryPress?: (c: string) => void }) {
  const items = block.items || [];
  if (items.length === 0) return null;
  return (
    <View>
      {block.title ? <SectionTitle block={block} /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12, paddingVertical: 6, paddingRight: 4 }}>
        {items.map((it, i) => {
          const tappable = Boolean(it.link_type && it.link_value);
          return (
            <TouchableOpacity
              key={`brand-${i}`}
              style={styles.brandTile}
              activeOpacity={tappable ? 0.8 : 1}
              disabled={!tappable}
              testID={`brand-item-${i}`}
              onPress={() => {
                if (it.link_type === "product" && it.link_value) onProductPress?.(it.link_value);
                else if (it.link_type === "category" && it.link_value) onCategoryPress?.(it.link_value);
              }}
            >
              <View style={styles.brandImgWrap}>
                {it.image_data_url ? (
                  <Image
                    source={{ uri: it.image_data_url }}
                    style={styles.brandImg}
                    resizeMode={it.image_fit === "cover" ? "cover" : "contain"}
                  />
                ) : (
                  <View style={[styles.brandImg, { alignItems: "center", justifyContent: "center" }]}>
                    <Feather name="award" size={22} color={colors.textMuted} />
                  </View>
                )}
              </View>
              {it.label ? (
                <Text style={styles.brandLabel} numberOfLines={2}>{it.label}</Text>
              ) : null}
            </TouchableOpacity>
          );
        })}
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
      {/* Jun 2026 — the leading ⚡ glyph was removed per owner request; the
          strip is now message-only so admin copy controls the whole width. */}
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
  // Jun 2026 — a finished flash sale used to sit on the shop home showing
  // "Sale ended", which is dead space that hurts conversion. Once the timer
  // runs out the whole block disappears from the customer's shop (the block
  // is NOT deleted server-side, so the admin can simply set a new end time
  // and it comes straight back).
  if (countdown?.expired) return null;
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
          {/* Jun 2026 — subtitle removed from flash sale headers. */}
        </View>
        {countdown && !countdown.expired ? (
          <View style={styles.flashTimer}>
            <View style={styles.flashTimerBox}><Text style={styles.flashTimerText}>{String(countdown.h).padStart(2, "0")}</Text></View>
            <Text style={styles.flashTimerSep}>:</Text>
            <View style={styles.flashTimerBox}><Text style={styles.flashTimerText}>{String(countdown.m).padStart(2, "0")}</Text></View>
            <Text style={styles.flashTimerSep}>:</Text>
            <View style={styles.flashTimerBox}><Text style={styles.flashTimerText}>{String(countdown.s).padStart(2, "0")}</Text></View>
          </View>
        ) : null}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 10, paddingVertical: 4 }}>
        {products.slice(0, (block.data_source || "manual") === "manual" ? products.length : (block.product_count || 10)).map((p) => (
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
  // Jun 2026 tablet fix — hook MUST run before the early return.
  const { width: winW } = useWindowDimensions();
  if (products.length === 0) return <SkeletonBlock height={160} />;
  const basePerRow = Math.max(1, Math.min(4, block.products_per_row || 2));
  // On a 12-inch tablet the admin's "2 per row" produced ~480 dp wide cards
  // with 500 dp tall images.  On wide screens we keep the same card size the
  // design was drawn for (~210 dp) and fit as many columns as the width
  // allows instead of stretching two giant cards across the row.
  const perRow = winW >= 700
    ? Math.min(6, Math.max(basePerRow, Math.floor((winW - 32) / 210)))
    : basePerRow;

  // ── Jun 2026 — PERCENTAGE grid (was pixel math) ─────────────────────────
  // The previous version measured `winW - 32` and divided by perRow to get a
  // pixel card width. That assumed the block was always 16 dp from each
  // screen edge; inside a category screen (extra padding) the row overflowed
  // and the LAST card wrapped away — the owner's "selected 4, only 3 show"
  // report. Each cell is now an exact `100 / perRow` % with its own padding,
  // so the row can never overflow regardless of the parent's padding.
  const cellPct = `${100 / perRow}%`;
  const gutter = perRow >= 3 ? 8 : 10;

  // Manual blocks show EVERY product the admin picked. `product_count` only
  // caps auto-sourced (trending / new / best / category) lists — previously a
  // stale count of 3 silently hid the 4th manual product.
  const isManual = (block.data_source || "manual") === "manual";
  const limit = isManual ? products.length : (block.product_count || 12);

  const nameLines = perRow >= 3 ? 1 : 2;
  const fontMul = perRow >= 4 ? 0.82 : perRow >= 3 ? 0.9 : 1;
  return (
    <View>
      {(block.title || block.show_view_all) ? (
        <View style={styles.gridHeader}>
          <View style={{ flex: 1, minWidth: 0 }}>
            {block.title ? <SectionTitle block={block} hideSubtitle /> : null}
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
      <View style={[styles.gridWrap, { marginHorizontal: -gutter / 2 }]}>
        {products.slice(0, limit).map((p) => {
          const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
          const stockQty = Number(p.stock || 0);
          const lowStock = inStock && stockQty > 0 && stockQty <= 5;
          return (
            <View
              key={p.id}
              style={{ width: cellPct as any, maxWidth: cellPct as any, paddingHorizontal: gutter / 2, paddingBottom: gutter }}
            >
              <TouchableOpacity
                style={[styles.gridCard, { width: "100%", padding: 0, flexBasis: undefined as any }, !inStock && { opacity: 0.7 }]}
                activeOpacity={0.85}
                onPress={() => onProductPress?.(p.id)}
                testID={`grid-card-${p.id}`}
              >
                {/* Square image — matches the shop-wide product tile so every
                    surface of the app reads as one catalogue. */}
                <View style={[styles.gridImgWrap, { aspectRatio: 1 }]}>
                  {pickImage(p) ? (
                    <Image source={{ uri: pickImage(p) }} style={styles.gridImg} resizeMode="cover" />
                  ) : (
                    <View style={[styles.gridImg, { alignItems: "center", justifyContent: "center" }]}>
                      <Feather name="image" size={22} color={colors.textMuted} />
                    </View>
                  )}
                  {!inStock ? (
                    <View style={styles.gridOOSBadge}><Text style={styles.gridOOSText}>SOLD OUT</Text></View>
                  ) : lowStock ? (
                    <View style={[styles.gridOOSBadge, { backgroundColor: "#F59E0B" }]}>
                      <Text style={styles.gridOOSText}>ONLY {stockQty}</Text>
                    </View>
                  ) : null}
                  {/* Jun 2026 — wishlist heart removed: it was decorative
                      (no handler) and competed with the Add button for the
                      customer's tap. One card, one goal: add to cart. */}
                </View>

                {/* Info block */}
                <View style={{ paddingHorizontal: 9, paddingTop: 8, paddingBottom: 9 }}>
                  <Text
                    style={[styles.gridName, {
                      fontSize: 13 * fontMul,
                      lineHeight: 17 * (perRow >= 3 ? 0.9 : 1),
                      marginTop: 0,
                      minHeight: nameLines === 1 ? 17 : 34,
                    }]}
                    numberOfLines={nameLines}
                  >{p.name}</Text>

                  <Text
                    style={{
                      fontSize: 10.5 * fontMul,
                      color: !inStock ? "#DC2626" : lowStock ? "#B45309" : "#0F7A3C",
                      fontWeight: "700",
                      marginTop: 3,
                      letterSpacing: 0.2,
                    }}
                    numberOfLines={1}
                  >
                    {!inStock ? "Out of stock" : lowStock ? `Only ${stockQty} left` : "In stock"}
                  </Text>

                  <View style={[styles.gridFooter, { marginTop: 6, gap: 6 }]}>
                    <Text
                      style={[styles.gridPrice, { fontSize: 15 * fontMul, flex: 1 }]}
                      numberOfLines={1}
                    >{formatINR(p.price)}</Text>
                    {/* Jun 2026 — products with sizes open the picker
                        instead of blind-adding (the API rejects a sizeless
                        add, which used to look like a dead button). */}
                    {(p as any).has_variants ? (
                      <TouchableOpacity
                        onPress={(e: any) => { e.stopPropagation?.(); onProductPress?.(p.id); }}
                        disabled={!inStock}
                        style={[styles.addCartBtn, { paddingHorizontal: 9, width: undefined }, !inStock && { opacity: 0.5 }]}
                        testID={`grid-select-${p.id}`}
                        hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                      >
                        <Text style={{ color: "#fff", fontSize: 10, fontWeight: "900" }}>SELECT</Text>
                      </TouchableOpacity>
                    ) : (
                      <TouchableOpacity
                        onPress={(e: any) => { e.stopPropagation?.(); onAddToCart?.(p.id); }}
                        disabled={!inStock}
                        style={[styles.addCartBtn, !inStock && { opacity: 0.5 }]}
                        testID={`grid-add-${p.id}`}
                        hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                      >
                        <Feather name="plus" size={14} color="#fff" />
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
              </TouchableOpacity>
            </View>
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
  // Manual blocks show every product the admin picked (see ProductGridBlock).
  const isManual = (block.data_source || "manual") === "manual";
  const limit = isManual ? products.length : (block.product_count || 10);
  return (
    <View>
      {block.title ? <SectionTitle block={block} hideSubtitle /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 12, paddingVertical: 6, paddingRight: 4 }}>
        {products.slice(0, limit).map((p) => {
          const inStock = (p.is_in_stock ?? (p.stock || 0) > 0);
          return (
            <TouchableOpacity
              key={p.id}
              style={[styles.hCard, !inStock && { opacity: 0.6 }]}
              activeOpacity={0.85}
              onPress={() => onProductPress?.(p.id)}
              testID={`hslide-card-${p.id}`}
            >
              <View style={styles.hImgWrap}>
                {pickImage(p) ? (
                  <Image source={{ uri: pickImage(p) }} style={styles.hImg} resizeMode="cover" />
                ) : (
                  <View style={[styles.hImg, { alignItems: "center", justifyContent: "center" }]}>
                    <Feather name="image" size={20} color={colors.textMuted} />
                  </View>
                )}
                {!inStock ? (
                  <View style={styles.gridOOSBadge}><Text style={styles.gridOOSText}>SOLD OUT</Text></View>
                ) : null}
              </View>
              <Text style={styles.hName} numberOfLines={2}>{p.name}</Text>
              {/* Jun 2026 — price + Add on one aligned row so every card in
                  the strip has the same height and a 1-tap buy action. */}
              <View style={styles.hFooter}>
                <Text style={styles.hPrice} numberOfLines={1}>{formatINR(p.price)}</Text>
                {(p as any).has_variants ? (
                  <TouchableOpacity
                    onPress={(e: any) => { e.stopPropagation?.(); onProductPress?.(p.id); }}
                    disabled={!inStock}
                    style={[styles.addCartBtn, { paddingHorizontal: 9, width: undefined }, !inStock && { opacity: 0.5 }]}
                    testID={`hslide-select-${p.id}`}
                    hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                  >
                    <Text style={{ color: "#fff", fontSize: 10, fontWeight: "900" }}>SELECT</Text>
                  </TouchableOpacity>
                ) : (
                  <TouchableOpacity
                    onPress={(e: any) => { e.stopPropagation?.(); onAddToCart?.(p.id); }}
                    disabled={!inStock}
                    style={[styles.addCartBtn, !inStock && { opacity: 0.5 }]}
                    testID={`hslide-add-${p.id}`}
                    hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                  >
                    <Feather name="plus" size={14} color="#fff" />
                  </TouchableOpacity>
                )}
              </View>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </View>
  );
}

/* ─────────────────────────── Block: Section Header ─────────────────────────── */

function SectionTitle({ block, hideSubtitle = false }: { block: LayoutBlock; hideSubtitle?: boolean }) {
  return (
    <View>
      <Text style={[
        styles.sectionTitleText,
        block.text_color ? { color: block.text_color } : null,
        block.font_size ? { fontSize: block.font_size } : null,
        block.text_align ? { textAlign: alignToTextAlign(block.text_align) } : null,
      ]}>{block.title}</Text>
      {/* Jun 2026 — product sections (grid / slider / flash sale) no longer
          show a subtitle: it stole vertical space and pushed the last row of
          products out of view. */}
      {block.subtitle && !hideSubtitle ? <Text style={styles.sectionTitleSub}>{block.subtitle}</Text> : null}
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
    // Jun 2026 — the image used to get `height - 100`, which on a "small"
    // block left a ~60 dp letterbox strip: the hero product was unreadable.
    // The photo is now the star (square-ish, 72% of the card) and the
    // name / price / CTA sit in a compact footer underneath.
    const imgHeight = Math.max(180, Math.round(height * 0.72));
    return (
      <TouchableOpacity
        style={[styles.productCard, { minHeight: imgHeight + 96 }]}
        onPress={() => onProductPress?.(p.id)}
        activeOpacity={0.85}
        testID={`content-box-${p.id}`}
      >
        <View style={[styles.productImageWrap, { height: imgHeight }]}>
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

/* ─────────────────────────── Block: Spotlight ───────────────────────────
 *
 * Jun 2026 — NEW block type requested by the owner.
 *
 * Brief: "a block that covers the mobile view — roughly 1/3 of the shop
 * home screen — like a horizontal slider but rectangular and immersive, to
 * pull the customer INSIDE the products / a category, with View more."
 *
 * Design:
 *   • Full-width rectangular hero, height = 34 % of the window height,
 *     clamped to 240–340 dp so a 6-inch phone gets ~1/3 of the screen and
 *     a tablet doesn't get a billboard.
 *   • Optional background artwork (block image, or the first product photo)
 *     with a dark scrim so the copy always reads.
 *   • Bottom row = a horizontally-swipeable strip of product chips (photo +
 *     price). Tapping a chip opens that product.
 *   • Tapping the hero body → the block's "View more" target (a category, or
 *     the whole shop). Same for the CTA pill.
 */

function SpotlightBlock({
  block, products, onProductPress, onViewAll,
}: {
  block: LayoutBlock; products: Product[];
  onProductPress?: (id: string) => void;
  onViewAll?: (target: string) => void;
}) {
  const { height: winH } = useWindowDimensions();
  // ~1/3 of the phone screen, clamped so the header + product strip always
  // fit exactly (no dead band between the CTA and the chips).
  const heroHeight = block.height || Math.max(288, Math.min(348, Math.round(winH * 0.34)));
  const cover = block.image_data_url || pickImage(products[0]);
  const strip = products.slice(0, 12);
  const target = block.view_all_link || block.category_filter || "";

  return (
    <View style={[styles.spotWrap, { height: heroHeight, backgroundColor: block.bg_color || colors.primary }]}>
      {cover ? (
        <Image
          source={{ uri: cover }}
          style={StyleSheet.absoluteFill as any}
          resizeMode={block.image_fit === "contain" ? "contain" : "cover"}
        />
      ) : null}
      <View style={styles.spotScrim} />

      <TouchableOpacity
        style={styles.spotHeader}
        activeOpacity={target ? 0.85 : 1}
        disabled={!target}
        onPress={() => onViewAll?.(target)}
        testID={`spotlight-open-${block.id}`}
      >
        {block.subtitle ? (
          <Text style={[styles.spotEyebrow, block.text_color ? { color: block.text_color } : null]} numberOfLines={1}>
            {block.subtitle.toUpperCase()}
          </Text>
        ) : null}
        <Text
          style={[
            styles.spotTitle,
            block.text_color ? { color: block.text_color } : null,
            block.font_size ? { fontSize: block.font_size } : null,
          ]}
          numberOfLines={2}
        >
          {block.title || "Featured"}
        </Text>
        {/* The CTA only appears when the admin actually set a "View more"
            target — otherwise it looked broken (tap did nothing because the
            customer is already on the shop home). */}
        {target ? (
          <View style={[styles.spotCta, { backgroundColor: block.button_color || "#fff" }]}>
            <Text style={[styles.spotCtaText, { color: block.button_text_color || colors.primary }]}>
              {block.cta_label || "View more"}
            </Text>
            <Feather name="arrow-right" size={13} color={block.button_text_color || colors.primary} />
          </View>
        ) : null}
      </TouchableOpacity>

      {strip.length > 0 ? (
        // Fixed strip height so the chips never get vertically squashed by
        // the parent's fixed hero height.
        <View style={{ height: 174 }}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.spotStrip}
          >
            {strip.map((p) => (
              <TouchableOpacity
                key={`spot-${p.id}`}
                style={styles.spotChip}
                activeOpacity={0.85}
                onPress={() => onProductPress?.(p.id)}
                testID={`spotlight-product-${p.id}`}
              >
                <View style={styles.spotChipImgWrap}>
                  {pickImage(p) ? (
                    <Image source={{ uri: pickImage(p) }} style={styles.spotChipImg} resizeMode="cover" />
                  ) : (
                    <View style={[styles.spotChipImg, { alignItems: "center", justifyContent: "center" }]}>
                      <Feather name="image" size={16} color={colors.textMuted} />
                    </View>
                  )}
                </View>
                <Text style={styles.spotChipName} numberOfLines={1}>{p.name}</Text>
                <Text style={styles.spotChipPrice} numberOfLines={1}>{formatINR(p.price)}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

/* ─────────────────────────── Main Renderer ─────────────────────────── */

export function ShopLayoutRenderer({
  scope = "home", category, pincode, lat, lng, onProductPress, onCategoryPress, onAddToCart, refreshTick, onBlocksResolved,
}: RendererProps) {
  const [blocks, setBlocks] = useState<LayoutBlock[] | null>(null);
  const [productsById, setProductsById] = useState<Record<string, Product>>({});
  const [sourceCache, setSourceCache] = useState<Record<string, Product[]>>({});
  // Aug 2026 — Auto-poll counter for live admin updates (30 s interval).
  // pollTick retained (referenced in deps) but auto-poll effect removed.
  const [pollTick] = useState(0);
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
        // Nov 2026 — forward the customer's delivery pincode so the
        // backend can filter to pincode-scoped layout blocks + global
        // blocks that apply to any pincode.
        if (pincode) params.pincode = pincode;
        // Jun 2026 BUGFIX — cold-cache layout wipe.
        //
        // `cachedGet` returns the STALE copy immediately (null on a cold
        // start) and calls `onFresh` when the network copy lands. The code
        // below then did `setBlocks(bRes?.items || [])` — so on a first-ever
        // open the freshly-fetched blocks were overwritten with `[]` and the
        // customer saw a shop with NO admin layout at all until the next
        // app open. We now remember the fresh payload and prefer it.
        let freshBlocks: LayoutBlock[] | null = null;
        const applyLayout = (bData: { items?: LayoutBlock[] } | null) => {
          if (cancelled) return null;
          return bData?.items || [];
        };
        const [bRes, pRes] = await Promise.all([
          cachedGet<{ items: LayoutBlock[] }>("/shop-layout", {
            ttlMs: 600_000,   // Nov 2026 — 10 min TTL (was 2 min) to
                              // eliminate the constant network churn.
            params,
            onFresh: (fresh) => {
              const items = applyLayout(fresh);
              if (items) { freshBlocks = items; setBlocks(items); }
            },
          }),
          // Jul 2026 — pass lat/lng + strict_location so the layout
          // renderer's products fetch matches the customer's actual
          // delivery zone (previously only pincode was forwarded, and
          // when pincode reverse-geocode failed the shop leaked all
          // products regardless of location).
          api.get<any>("/products", {
            params: {
              ...(category ? { category, limit: 240 } : { limit: 240 }),
              ...(pincode ? { pincode } : {}),
              ...(lat !== undefined && lng !== undefined ? { lat, lng } : {}),
              strict_location: "true",
            },
          }),
        ]);
        if (cancelled) return;
        const blocks: LayoutBlock[] = freshBlocks || bRes?.items || [];
        const pData = pRes.data;
        const pListRaw: Product[] = Array.isArray(pData) ? pData : (pData?.items || pData?.products || []);
        // UPDATE 1 — Drop the current vendor's own products before caching.
        const pList: Product[] = excludeOwn(pListRaw);
        const map: Record<string, Product> = {};
        pList.forEach((p) => { map[p.id] = p; });
        setProductsById(map);
        // Jun 2026 — manual blocks no longer need a pre-computed cache: the
        // renderer maps `product_ids` → `productsById` at render time. That
        // removes an ordering bug where the cache was built from an EMPTY
        // block list (the layout arrived a beat later via `onFresh`), leaving
        // every manual grid / spotlight showing zero products.
        // Auto-sourced blocks are fetched by a dedicated effect below, once
        // we actually know which blocks exist.
        setBlocks(blocks);
      } catch {
        if (!cancelled) setBlocks([]);
      }
    })();
    return () => { cancelled = true; };
  }, [scope, category, pincode, lat, lng, currentUserId, refreshTick, pollTick]);

  // Nov 2026 — Auto-poll REMOVED per user directive.
  // The prior 30s setInterval caused visible splash flicker and made the
  // shop feel constantly "loading".  Refreshes are now:
  //   • Explicit — parent bumps `refreshTick` (e.g. pull-to-refresh).
  //   • Focus-driven — the Shop tab re-fetches on focus via useFocusEffect
  //     in shop-home.tsx (which the customer sees as instant).
  //   • Cache-driven — `cachedGet` serves fresh data if <10 min stale.
  // Nothing to schedule here.

  const visible = useMemo(
    () => (blocks || [])
      .filter((b) => b.active)
      // Jun 2026 — belt-and-braces scope guard. The owner reported a block
      // created for "Essentials" also appearing on the Vegetables & Meat
      // category screens. A stale cache entry or a legacy block with the
      // wrong `scope_category` can do that, so we now re-assert the match
      // on the client: on a category screen only blocks scoped to THAT
      // exact category render; on Home only home-scoped blocks render.
      .filter((b) => {
        const bScope = (b as any).scope || "home";
        if (scope === "category") {
          return bScope === "category" && ((b as any).scope_category || "") === (category || "");
        }
        return bScope === "home";
      })
      .sort((a, b) => a.sort_order - b.sort_order),
    [blocks, scope, category],
  );

  // Jun 2026 — Auto-sourced product fetch.
  // Runs AFTER `visible` is known (previously it ran inside the layout
  // effect, before the blocks had landed). Only fires for blocks whose
  // data_source is trending / new / best / category.
  useEffect(() => {
    const autoBlocks = visible.filter(
      (b) => PRODUCT_BLOCK_TYPES.includes(b.block_type) && (b.data_source || "manual") !== "manual",
    );
    if (autoBlocks.length === 0) return;
    let cancelled = false;
    (async () => {
      const updates: Record<string, Product[]> = {};
      await Promise.all(autoBlocks.map(async (b) => {
        try {
          const r = await api.get<any>("/products/by-source", {
            params: {
              source: b.data_source,
              limit: b.product_count || 10,
              ...(b.category_filter ? { category: b.category_filter } : (category ? { category } : {})),
              // Jul 2026 — enforce delivery zone on layout-block products too.
              ...(pincode ? { pincode } : {}),
              ...(lat !== undefined && lng !== undefined ? { lat, lng } : {}),
              strict_location: "true",
            },
          });
          const data = r.data;
          const arr: Product[] = Array.isArray(data) ? data : (data?.items || []);
          updates[b.id] = excludeOwn(arr);
        } catch {
          updates[b.id] = [];
        }
      }));
      if (!cancelled) setSourceCache((prev) => ({ ...prev, ...updates }));
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, category, pincode, lat, lng, currentUserId]);

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
    // Dec 2026 v2 — Auto-inject REMOVED per user directive.
    //
    // Previously we injected a synthetic product_grid below every
    // banner/announcement block that had no product block after it.
    // This gave two bad outcomes:
    //   1. Home banners visually "leaked" — huge white gap + shadow
    //      of the auto-grid below what should be a lone banner.
    //   2. Category screens double-rendered products (once inside the
    //      auto-injected block, once in the fallback grid below the
    //      renderer), or hid the fallback altogether.
    //
    // The Shop-category screen (see shop-category/[name].tsx) now ALWAYS
    // renders a product grid BELOW <ShopLayoutRenderer>, so admin can
    // freely drop banners/announcements without polluting the grid.
    // ShopLayoutRenderer only renders exactly what admin configured.
    return visible;
  }, [visible]);

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

  // (Removed Jun 2026) `autoBlockProducts` — the auto-inject feature it
  // fed was deleted earlier; manual blocks now resolve from `productsById`
  // directly at render time.

  // Jun 2026 — Tell the parent how many blocks actually resolved so it can
  // fall back to a plain "All products near you" grid when an admin hasn't
  // built a layout for this pincode yet (customers were seeing a shop home
  // with no products at all).
  useEffect(() => {
    if (blocks !== null) onBlocksResolved?.(augmented.length);
  }, [blocks, augmented.length, onBlocksResolved]);

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
        if (PRODUCT_BLOCK_TYPES.includes(b.block_type)) {
          // Manual blocks resolve from the already-loaded product map at
          // render time (see the layout effect); auto-sourced blocks come
          // from the by-source cache.
          prods = (b.data_source || "manual") === "manual"
            ? ((b.product_ids || []).map((id) => productsById[id]).filter(Boolean) as Product[])
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
            node = <BrandSliderBlock block={b} onProductPress={wrapProductPress(b.id)} onCategoryPress={wrapCategoryPress(b.id)} />; break;
          case "spotlight":
            node = (
              <SpotlightBlock
                block={b}
                products={prods}
                onProductPress={wrapProductPress(b.id)}
                onViewAll={(target) => { trackClick(b.id); onCategoryPress?.(target || ""); }}
              />
            ); break;
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
  // Brand slider — Jun 2026: bigger, readable tile with the label UNDER
  // the logo (was a cramped 90×50 image-only chip).
  brandTile: { width: 118, alignItems: "center" },
  brandImgWrap: {
    width: 118, height: 82, borderRadius: 14, overflow: "hidden",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    padding: 8, alignItems: "center", justifyContent: "center",
  },
  brandImg: { width: "100%", height: "100%" },
  brandLabel: {
    fontSize: 11.5, fontWeight: "800", color: colors.textMain,
    marginTop: 6, textAlign: "center", lineHeight: 14.5,
  },
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
  // Flash sale card — Jun 2026: 132 dp (was 110) so the photo actually
  // sells the discount on a 6-inch phone.
  flashCard: { width: 132, backgroundColor: "#fff", borderRadius: SHOP_CARD_RADIUS, overflow: "hidden" },
  flashCardImageWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  flashCardImg: { width: "100%", height: "100%" },
  flashCardName: { ...SHOP_TYPO.productName, fontSize: 12.5, padding: 8, paddingBottom: 0, minHeight: 32, lineHeight: 16 },
  flashCardPrice: { fontSize: 14, fontWeight: "900", color: "#DC2626", paddingHorizontal: 8, paddingBottom: 8 },
  // Product grid — 2 columns, equal width/height per spec.
  gridHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8, gap: 8 },
  gridViewAllBtn: { flexDirection: "row", alignItems: "center", gap: 2, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.brand100 },
  gridViewAllText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
  // gap:16 → matches the global 16 dp inter-card gap requested in the spec.
  // Jun 2026 — no `gap`: each cell owns its padding so percentage
  // widths always add up to exactly 100%.
  gridWrap: { flexDirection: "row", flexWrap: "wrap" },
  gridCard: {
    // Width is set inline by ProductGridBlock (based on perRow + gap +
    // screen width) so removing flexBasis here prevents the double-
    // definition that pushed 3/4-column grids into single-column mode.
    backgroundColor: "#FFFFFF",
    borderRadius: SHOP_CARD_RADIUS,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
    // Nov 2026 — padding moved into the inner Info block; card is edge-
    // to-edge so the image reaches the card border for a hero look.
    padding: 0,
    // Soft shadow (iOS) + elevation (Android) per spec.
    ...Platform.select({
      ios: {
        shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 2 },
      },
      android: { elevation: 2 },
    }),
  },
  // Nov 2026 — Wishlist heart overlay pill
  // ── Spotlight (Jun 2026) — immersive full-width showcase, ~1/3 screen ──
  spotWrap: {
    borderRadius: SHOP_BANNER_RADIUS, overflow: "hidden",
    position: "relative", justifyContent: "space-between",
  },
  spotScrim: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(8,20,14,0.46)" },
  spotHeader: { paddingHorizontal: 16, paddingTop: 16 },
  spotEyebrow: { fontSize: 10, fontWeight: "900", color: "rgba(255,255,255,0.9)", letterSpacing: 1.6 },
  spotTitle: { fontSize: 21, fontWeight: "900", color: "#fff", letterSpacing: -0.5, marginTop: 3, lineHeight: 26 },
  spotCta: {
    flexDirection: "row", alignItems: "center", gap: 5,
    alignSelf: "flex-start", paddingHorizontal: 13, paddingVertical: 8,
    borderRadius: 999, marginTop: 12, minHeight: 34,
  },
  spotCtaText: { fontSize: 12, fontWeight: "900" },
  spotStrip: { gap: 10, paddingHorizontal: 16, paddingBottom: 16, paddingTop: 6, alignItems: "flex-start" },
  // Explicit pixel sizes (not aspectRatio) — the chip lives inside a
  // fixed-height hero, and a ratio-driven box got vertically squeezed there.
  spotChip: {
    width: 106, height: 152, backgroundColor: "rgba(255,255,255,0.96)",
    borderRadius: 12, overflow: "hidden", padding: 6,
  },
  spotChipImgWrap: { width: 94, height: 94, borderRadius: 8, overflow: "hidden", backgroundColor: colors.surfaceMuted },
  spotChipImg: { width: "100%", height: "100%" },
  spotChipName: { fontSize: 11, fontWeight: "700", color: colors.textMain, marginTop: 5, lineHeight: 14 },
  spotChipPrice: { fontSize: 12.5, fontWeight: "900", color: colors.primary, marginTop: 2 },

  wishBtn: {
    position: "absolute", top: 6, right: 6,
    width: 26, height: 26, borderRadius: 13,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(255,255,255,0.92)",
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.08, shadowRadius: 3, shadowOffset: { width: 0, height: 1 } },
      android: { elevation: 1 },
    }),
  },
  // Nov 2026 — Add-to-Cart quick pill inside the card footer
  addCartBtn: {
    width: 28, height: 28, borderRadius: 14,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
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
  // Horizontal slider — Jun 2026: 156 dp wide (was 140) with a price+Add
  // footer row so cards align and are buyable in one tap.
  hCard: { width: 156, backgroundColor: colors.surface, borderRadius: SHOP_CARD_RADIUS, borderWidth: 1, borderColor: colors.border, overflow: "hidden", padding: 8 },
  hImgWrap: { width: "100%", aspectRatio: 1, backgroundColor: colors.surfaceMuted, borderRadius: 10, overflow: "hidden", position: "relative" },
  hImg: { width: "100%", height: "100%" },
  hName: { ...SHOP_TYPO.productName, fontSize: 13, marginTop: 8, minHeight: 34, lineHeight: 17 },
  hFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6, gap: 6 },
  hPrice: { ...SHOP_TYPO.price, color: colors.primary, flex: 1 },
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
