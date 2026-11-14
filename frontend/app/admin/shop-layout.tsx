// Admin Shop Layout — JSON-driven layout manager with 12 block types,
// scope routing (Home / per-category), styling overrides, multi-product
// picker, items editor, data-source selector, and live customer preview.
// All saved data is rendered by /src/shop-layout-renderer.tsx in both
// admin preview and on the customer app.
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Alert, RefreshControl, TextInput, Image, Modal, Switch, Pressable, AppState,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError, resolveImageUrl } from "../../src/api";
import { useAdminProductSearch } from "../../src/use-admin-product-search";
import { colors, radii, spacing } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { LayoutBlock, LayoutItem, BlockType } from "../../src/shop-layout-renderer";
import { DraggableLayoutList } from "../../src/draggable-layout-list";
import { HelpGuide, HelpButton, useFirstVisitGuide, GuideStep } from "../../src/help-guide";
import { pickAndFitImage, IMAGE_SPECS, ImageTarget } from "../../src/image-fitter";

// First-visit walkthrough for /admin/shop-layout. The shop-layout editor is
// powerful so the guide is intentionally generous — 7 short steps.
const LAYOUT_GUIDE_STEPS: GuideStep[] = [
  {
    icon: "layout",
    title: "Welcome to Shop Layout!",
    body: "This screen controls EVERYTHING customers see on the Shop tab — banners, product grids, flash sales, category circles. No app update needed.",
    tip: "Re-open this guide any time via the ? icon above.",
  },
  {
    icon: "navigation",
    title: "1. Pick a scope first",
    body: "The chips at the top decide WHERE your blocks appear:\n• HOME = main Shop tab\n• Each CATEGORY tab = a per-category page",
    highlight: "Tap a chip at the top (Home, Electronics, Fashion, etc.)",
  },
  {
    icon: "plus-circle",
    title: "2. Add a block",
    body: "Tap the + at the top-right. Pick from 12 block types: banner slider, product grid, category circles, flash sale, offer cards, and more.",
    highlight: "Top-right · green + button",
  },
  {
    icon: "image",
    title: "3. Choose Manual or Auto products",
    body: "For Product grid / Horizontal slider / Flash sale you can pick:\n• Manual → multi-select your own products\n• Trending / New / Best → auto-fills from data",
    tip: "Auto sections refresh every time a customer opens the Shop — zero maintenance!",
  },
  {
    icon: "droplet",
    title: "4. Style it your way",
    body: "Every block supports color overrides (text, background, button), font size, height, and text alignment — using the palette swatches in the form.",
  },
  {
    icon: "move",
    title: "5. Reorder by drag or buttons",
    body: "On the block list, LONG-PRESS a card and drag to reorder. Or use the up/down chevrons. Order saves automatically.",
    highlight: "Long-press a block card for 0.3s, then drag",
  },
  {
    icon: "smartphone",
    title: "6. Analytics",
    body: "Each saved block shows 7-day impressions, clicks, and CTR%. Use the data to refine your layout. Tap the Shop tab to browse the experience as a customer.",
    tip: "Green CTR badge = ≥5% (great). Amber = below 5% — try a new image or title.",
  },
];

type Block = LayoutBlock;
type Product = { id: string; name: string; price?: number; image_url?: string; category?: string; vendor_id?: string | null; vendor_name?: string; is_published?: boolean };

const TYPE_META: Record<BlockType, { label: string; icon: any; hint: string; group: string }> = {
  // Hero / Banners
  banner_slider:    { label: "Banner slider",   icon: "image",        hint: "Swipeable carousel of hero banners (replaces old promo banners)", group: "Hero" },
  background:       { label: "New banner",      icon: "square",       hint: "Single full-width banner card",                              group: "Hero" },
  announcement_strip:{ label: "Announcement",   icon: "zap",          hint: "Thin strip with a message (sale alert, free shipping, etc.)", group: "Hero" },
  // Navigation
  category_circles: { label: "Category circles",icon: "circle",       hint: "Circular category navigator (Meesho-style)",                  group: "Navigation" },
  brand_slider:     { label: "Brand slider",    icon: "award",        hint: "Horizontal scroll of brand logos",                            group: "Navigation" },
  // Products
  product_grid:     { label: "Product grid",    icon: "grid",         hint: "2-column grid of products (manual or auto-sourced)",          group: "Products" },
  horizontal_slider:{ label: "Horizontal slider",icon: "arrow-right", hint: "Horizontal-scroll list of products (Trending / New / Best)",  group: "Products" },
  content_box:      { label: "Content box",     icon: "package",      hint: "Single featured-product card · big photo · resizable",         group: "Products" },
  spotlight:        { label: "Spotlight",       icon: "star",         hint: "Immersive full-width showcase (~1/3 of the phone screen) with product chips + View more", group: "Products" },
  flash_sale:       { label: "Flash sale",      icon: "clock",        hint: "Countdown sale section with featured products",              group: "Products" },
  // Promo
  offer_cards:      { label: "Offer cards",     icon: "tag",          hint: "Promotional cards (Buy 1 Get 1, Cashback, etc.)",            group: "Promo" },
  // Typography
  section_header:   { label: "Sub-category label",icon: "type",       hint: "Bold sub-category title (e.g. ELECTRONICS)",                  group: "Typography" },
  text:             { label: "Free text",       icon: "align-left",   hint: "A paragraph of supporting text",                              group: "Typography" },
};

const ALL_TYPES: BlockType[] = [
  "banner_slider", "background", "announcement_strip",
  "category_circles", "brand_slider",
  "spotlight", "product_grid", "horizontal_slider", "content_box", "flash_sale",
  "offer_cards", "section_header", "text",
];

const DATA_SOURCES: { value: string; label: string; hint: string }[] = [
  { value: "manual", label: "Manual",     hint: "Pick specific products" },
  { value: "trending", label: "Trending", hint: "Auto: top by interest" },
  { value: "new", label: "New",           hint: "Auto: newest products" },
  { value: "best", label: "Best sellers", hint: "Auto: most sold" },
  { value: "category", label: "Category", hint: "All products in a category" },
];

// Jun 2026 — data sources are now PER BLOCK TYPE, per owner spec:
//   • Product grid  → Manual only (admin curates exactly what sells)
//   • Flash sale    → Manual only (used to clear slow-moving stock)
//   • Horizontal    → Manual + Category
//   • Spotlight     → Manual + Category
// The old "Trending / New / Best" auto chips were removed from those
// blocks because they silently replaced the admin's curated picks.
const SOURCES_FOR_TYPE: Record<string, string[]> = {
  product_grid: ["manual"],
  flash_sale: ["manual"],
  horizontal_slider: ["manual", "category"],
  spotlight: ["manual", "category"],
};

const ALIGN_OPTIONS: { v: "left" | "center" | "right"; icon: any }[] = [
  { v: "left", icon: "align-left" }, { v: "center", icon: "align-center" }, { v: "right", icon: "align-right" },
];

// Quick color palette for the color pickers
const PALETTE = ["", "#FFFFFF", "#000000", "#0F172A", "#DC2626", "#F97316", "#F59E0B", "#10B981", "#0EA5E9", "#6366F1", "#EC4899", "#FEF3C7", "#DCFCE7", "#E0E7FF", "#FCE7F3"];

export default function AdminShopLayoutScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Block[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Block | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [migrating, setMigrating] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const { visible: helpVisible, close: helpClose } = useFirstVisitGuide("shop-layout-v1");
  // Per-block analytics: { [block_id]: { impressions, clicks, ctr } }
  const [analytics, setAnalytics] = useState<Record<string, { impressions: number; clicks: number; ctr: number }>>({});
  // Scope state: which layout we're editing
  const [scope, setScope] = useState<"home" | "category">("home");
  const [scopeCategory, setScopeCategory] = useState<string>("");
  // Admin-managed shop categories — the single source of truth, in sync
  // with /admin/shop-categories. When admin adds / removes / hides a
  // category there, the scope tabs and the in-form category pickers
  // here update on the next focus / refresh automatically.
  const [shopCats, setShopCats] = useState<{ id?: string; name: string; active: boolean; parent_id?: string | null; depth?: number }[]>([]);

  // Categories list — sourced ONLY from active admin-managed
  // shop_categories so it stays perfectly in sync with
  // /admin/shop-categories. Deleting (or hiding) a category there
  // removes it from the scope tabs and pickers here on the next focus.
  // We also include any scope_category currently in use by an existing
  // layout block so admin can still reach and clean up orphaned blocks
  // after a category is deleted.
  // Dec 2026 — Show categories as HIERARCHY breadcrumbs so admin can
  // pick nested subcategories (e.g. "Groceries › Fruits › Citrus")
  // when creating a scoped shop-layout block.  Storage remains
  // `scope_category = leaf name` so it still matches the customer's
  // `/shop-category/{name}` URL exactly.
  // Nov 2026 — every product id already placed in a block, EXCLUDING the one
  // being edited. The picker hides these so the same SKU can't be shelved in
  // two different blocks (the owner's rule: once mapped, it leaves the pool).
  const usedElsewhere = useMemo(() => {
    const s = new Set<string>();
    for (const b of items) {
      if (editing && b.id === editing.id) continue;
      for (const pid of (((b as any).product_ids || []) as string[])) s.add(pid);
    }
    return s;
  }, [items, editing]);


  const categories = useMemo(() => {
    // Build a map: id → cat for parent-path resolution
    const byId = new Map<string, any>();
    shopCats.forEach((c: any) => { if (c?.id) byId.set(c.id, c); });
    const path = (c: any): string => {
      const parts: string[] = [c.name];
      let cur = c;
      const seen = new Set<string>([c.id]);
      while (cur?.parent_id && byId.has(cur.parent_id) && !seen.has(cur.parent_id)) {
        cur = byId.get(cur.parent_id);
        seen.add(cur.id);
        parts.unshift(cur.name);
      }
      return parts.join(" › ");
    };
    const map = new Map<string, { name: string; label: string; depth: number }>();
    // Admin cats (only include active ones)
    shopCats.forEach((c: any) => {
      if (!c?.name || c.active === false) return;
      if (map.has(c.name)) return;
      map.set(c.name, { name: c.name, label: path(c), depth: Number(c.depth || 0) });
    });
    // Also include any legacy scope_category currently in use by blocks
    // but not present in the tree (so admin can still edit / migrate them).
    // Nov-2026 — except recharge: it is sold through its own flow and is no
    // longer offerable as a layout scope.
    const isRecharge = (n: string) => /recharge/i.test(n);
    items.forEach((b: any) => {
      const sc = b?.scope_category;
      if (b?.scope === "category" && typeof sc === "string" && sc && !map.has(sc) && !isRecharge(sc)) {
        map.set(sc, { name: sc, label: sc, depth: 0 });
      }
    });
    for (const key of Array.from(map.keys())) {
      if (isRecharge(map.get(key)!.label)) map.delete(key);
    }
    // Sort: depth first (parents at top), then alphabetical by label
    return Array.from(map.values()).sort((a, b) => a.depth - b.depth || a.label.localeCompare(b.label));
  }, [shopCats, items]);

  const load = useCallback(async () => {
    try {
      const [bRes, aRes, cRes] = await Promise.all([
        api.get<{ items: Block[] }>("/admin/shop-layout"),
        api.get<{ blocks: Record<string, { impressions: number; clicks: number; ctr: number }> }>("/admin/shop-layout/analytics", { params: { days: 7 } }).catch(() => ({ data: { blocks: {} } as any })),
        api.get<{ items: { id?: string; name: string; active: boolean; parent_id?: string | null; depth?: number }[] }>("/admin/shop-categories?exclude_recharge=true").catch(() => ({ data: { items: [] } as any })),
      ]);
      setItems(bRes.data?.items || []);
      // Nov 2026 — the screen used to download the WHOLE catalogue here (23
      // sequential pages at 5.7k SKUs → the app froze and the picker opened
      // empty). It only needs the products its own blocks reference, so we
      // resolve just those by id; the picker itself searches server-side.
      const blocks = bRes.data?.items || [];
      const refIds = Array.from(new Set(
        blocks.flatMap((b: any) => [...(b.product_ids || []), ...(b.product_id ? [b.product_id] : [])])
          .filter(Boolean) as string[],
      ));
      if (refIds.length) {
        const pr = await api.get<any>("/admin/products", { params: { ids: refIds.join(",") } });
        setProducts(pr.data?.items || []);
      } else {
        setProducts([]);
      }
      setAnalytics(aRes.data?.blocks || {});
      setShopCats(cRes.data?.items || []);
    } catch (e) { Alert.alert("Failed to load", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  // Re-fetch on focus so removing / adding a category in
  // /admin/shop-categories reflects here the next time admin pops back.
  useFocusEffect(useCallback(() => {
    load();
    // Dec 2026 — Silent auto-refresh so admin sees new blocks / edits
    // from other admins without a manual pull-to-refresh.
    const iv = setInterval(() => {
      if (AppState.currentState !== "active") return;   // don't poll from the pocket
      load();
    }, 20000);
    return () => clearInterval(iv);
  }, [load]));

  // Dec 2026 — Pincode search filter.  When admin types a pincode, we
  // narrow the visible blocks to those whose `scope_pincode` matches
  // (exact or partial prefix).  Empty pincode = show all blocks
  // (including ones with no scope_pincode set = global blocks).
  const [pincodeSearch, setPincodeSearch] = useState<string>("");

  // Filter items by current scope + pincode search
  const filteredItems = useMemo(() => {
    const pin = pincodeSearch.trim();
    return items.filter((b) => {
      const itemScope = (b as any).scope || "home";
      if (scope === "home") {
        if (!(itemScope === "home" || !itemScope)) return false;
      } else {
        if (!(itemScope === "category" && (b as any).scope_category === scopeCategory)) return false;
      }
      if (pin) {
        // Jun 2026 — Multi-pincode aware. A block matches when ANY of its
        // target pincodes equals or starts with the search (so typing
        // "5176" matches every block scoped to 5176xx).
        const pins: string[] = [
          ...(Array.isArray((b as any).scope_pincodes) ? (b as any).scope_pincodes.map(String) : []),
          String((b as any).scope_pincode || ""),
        ].map((s) => s.trim()).filter(Boolean);
        if (!pins.length) return false;
        return pins.some((sp) => sp === pin || sp.startsWith(pin));
      }
      return true;
    });
  }, [items, scope, scopeCategory, pincodeSearch]);

  // Dec 2026 — Compute the distinct pincodes used across the currently-
  // scoped blocks so admin can see at a glance which pincodes have
  // custom layouts (renders as tappable chips below the search).
  const distinctPincodes = useMemo(() => {
    const set = new Set<string>();
    items.forEach((b: any) => {
      const bScope = b?.scope || "home";
      if (scope === "home" && !(bScope === "home" || !bScope)) return;
      if (scope === "category" && !(bScope === "category" && b?.scope_category === scopeCategory)) return;
      const pins: string[] = [
        ...(Array.isArray(b?.scope_pincodes) ? b.scope_pincodes.map(String) : []),
        String(b?.scope_pincode || ""),
      ].map((s) => s.trim()).filter(Boolean);
      pins.forEach((p) => set.add(p));
    });
    return Array.from(set).sort();
  }, [items, scope, scopeCategory]);

  // Delete with 2-tap confirm
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const confirmTimerRef = useRef<any>(null);

  const onDelete = async (b: Block) => {
    if (confirmDeleteId !== b.id) {
      setConfirmDeleteId(b.id);
      if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
      confirmTimerRef.current = setTimeout(() => setConfirmDeleteId(null), 4000);
      return;
    }
    if (confirmTimerRef.current) clearTimeout(confirmTimerRef.current);
    setConfirmDeleteId(null);
    try {
      await api.delete(`/admin/shop-layout/${b.id}`);
      setItems((prev) => prev.filter((x) => x.id !== b.id));
    } catch (e) { Alert.alert("Delete failed", formatApiError(e)); }
  };

  const onToggleActive = async (b: Block) => {
    try {
      await api.patch(`/admin/shop-layout/${b.id}`, { active: !b.active });
      setItems((prev) => prev.map((x) => x.id === b.id ? { ...x, active: !b.active } : x));
    } catch (e) { Alert.alert("Update failed", formatApiError(e)); }
  };

  const onMove = async (b: Block, dir: -1 | 1) => {
    const newOrder = b.sort_order + dir;
    try {
      await api.patch(`/admin/shop-layout/${b.id}`, { sort_order: newOrder });
      load();
    } catch (e) { Alert.alert("Move failed", formatApiError(e)); }
  };

  const onMigratePromoBanners = async () => {
    if (migrating) return;
    setMigrating(true);
    try {
      const r = await api.post<any>("/admin/shop-layout/migrate-banners");
      Alert.alert("Migration done", `${r.data?.migrated || 0} banners folded into a single banner_slider block.`);
      await load();
    } catch (e) { Alert.alert("Migration failed", formatApiError(e)); }
    finally { setMigrating(false); }
  };

  const onSeedDefaultHome = async () => {
    if (seeding) return;
    if (scope !== "home") {
      Alert.alert("Switch to Home scope", "Tap the 'Home' tab above first — default seed only applies to the Home scope.");
      return;
    }
    setSeeding(true);
    try {
      const r = await api.post<any>("/admin/shop-layout/seed-default-home");
      if (r.data?.skipped) {
        Alert.alert("Home already has blocks", r.data?.message || "Delete existing Home blocks first.");
      } else {
        Alert.alert(
          "Default Home seeded",
          `${r.data?.inserted || 0} starter blocks added: announcement strip, banner slider, category circles, flash sale (24h), trending grid, and offer cards. Customize them now or leave as-is.`,
        );
        await load();
      }
    } catch (e) { Alert.alert("Seed failed", formatApiError(e)); }
    finally { setSeeding(false); }
  };

  // Drag-to-reorder: receives the new ordered list of block IDs (within
  // the current scope) and POSTs to the bulk-reorder endpoint. Re-numbers
  // sort_order = 0..N-1 so blocks always stay tight after operations.
  const onReorder = async (newIds: string[]) => {
    const payload = { items: newIds.map((id, i) => ({ id, sort_order: i })) };
    // Optimistic update
    setItems((prev) => prev.map((b) => {
      const idx = newIds.indexOf(b.id);
      return idx >= 0 ? { ...b, sort_order: idx } : b;
    }));
    try {
      await api.post("/admin/shop-layout/reorder", payload);
    } catch (e) { Alert.alert("Reorder failed", formatApiError(e)); load(); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Shop Layout</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <HelpButton onPress={() => setHelpOpen(true)} testID="layout-help" />
          <TouchableOpacity
            onPress={() => { setEditing(null); setShowForm(true); }}
            style={[styles.iconBtn, styles.iconBtnPrimary]}
            testID="block-new"
          >
            <Feather name="plus" size={20} color={colors.primaryFg} />
          </TouchableOpacity>
        </View>
      </View>

      {/* In-app walkthrough — auto-opens on first visit, re-openable via ? button */}
      <HelpGuide
        id="shop-layout-v1"
        visible={helpVisible || helpOpen}
        title="How to use Shop Layout"
        subtitle="A quick 7-step tour. Tap anywhere outside to dismiss."
        steps={LAYOUT_GUIDE_STEPS}
        onClose={() => { helpClose(); setHelpOpen(false); }}
      />

      {/* Scope tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scopeTabs}
        style={styles.scopeTabsWrap}
      >
        <TouchableOpacity
          onPress={() => { setScope("home"); setScopeCategory(""); }}
          style={[styles.scopeTab, scope === "home" && styles.scopeTabActive]}
        >
          <Feather name="home" size={12} color={scope === "home" ? colors.primaryFg : colors.textMain} />
          <Text style={[styles.scopeTabText, scope === "home" && styles.scopeTabTextActive]}>Home</Text>
        </TouchableOpacity>
        {categories.map((c) => {
          const active = scope === "category" && scopeCategory === c.name;
          return (
            <TouchableOpacity
              key={c.name}
              onPress={() => { setScope("category"); setScopeCategory(c.name); }}
              style={[styles.scopeTab, active && styles.scopeTabActive, c.depth ? { paddingLeft: 10 + Math.min(c.depth, 3) * 6 } : null]}
              testID={`scope-cat-${c.name}`}
            >
              <Feather name={c.depth ? "corner-down-right" : "grid"} size={12} color={active ? colors.primaryFg : colors.textMain} />
              <Text style={[styles.scopeTabText, active && styles.scopeTabTextActive]} numberOfLines={1}>{c.label}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {/* Dec 2026 — Pincode search filter.  Type a pincode (or prefix)
          to narrow the block list to blocks scoped to that pincode.
          Tapping a chip auto-fills the search.  "Clear" resets to show
          every block in the current scope (including global ones with
          no pincode set). */}
      <View style={styles.pinBar}>
        <View style={styles.pinInputWrap}>
          <Feather name="map-pin" size={14} color={colors.textMuted} />
          <TextInput
            value={pincodeSearch}
            onChangeText={(t) => setPincodeSearch(t.replace(/[^0-9]/g, "").slice(0, 6))}
            placeholder="Filter blocks by pincode (e.g. 517644)"
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
            maxLength={6}
            style={styles.pinInput}
            testID="shop-layout-pin-search"
          />
          {pincodeSearch ? (
            <TouchableOpacity onPress={() => setPincodeSearch("")} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} testID="shop-layout-pin-clear">
              <Feather name="x-circle" size={16} color={colors.textMuted} />
            </TouchableOpacity>
          ) : null}
        </View>
        {distinctPincodes.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ gap: 6, paddingHorizontal: 4 }}
            style={{ marginTop: 8 }}
          >
            {distinctPincodes.map((p) => {
              const active = pincodeSearch === p;
              return (
                <TouchableOpacity
                  key={p}
                  onPress={() => setPincodeSearch(active ? "" : p)}
                  style={[styles.pinChip, active && styles.pinChipActive]}
                  testID={`pin-chip-${p}`}
                >
                  <Text style={[styles.pinChipText, active && styles.pinChipTextActive]}>{p}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        ) : null}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          <GradientCard variant="primary" style={{ marginBottom: 14, padding: 18 }}>
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>
              {scope === "home" ? "HOME LAYOUT" : `CATEGORY: ${scopeCategory.toUpperCase()}`}
            </Text>
            <Text style={{ fontSize: 20, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.4 }}>
              {filteredItems.length} block{filteredItems.length === 1 ? "" : "s"}
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              Long-press & drag a block to reorder · Tap S/M/L to resize · Switch the scope tabs above to manage per-category layouts · CTR data updates over 7 days.
            </Text>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
              {scope === "home" && filteredItems.length === 0 ? (
                <TouchableOpacity
                  onPress={onSeedDefaultHome}
                  disabled={seeding}
                  style={[styles.heroBtn, { backgroundColor: "#fff" }, seeding && { opacity: 0.6 }]}
                  testID="seed-default-home"
                >
                  {seeding ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="zap" size={12} color={colors.primary} />}
                  <Text style={styles.heroBtnText}>Seed default Home</Text>
                </TouchableOpacity>
              ) : null}
              <TouchableOpacity onPress={onMigratePromoBanners} disabled={migrating} style={[styles.heroBtn, migrating && { opacity: 0.6 }]} testID="migrate-banners">
                {migrating ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="download" size={12} color={colors.primary} />}
                <Text style={styles.heroBtnText}>Migrate old banners</Text>
              </TouchableOpacity>
            </View>
          </GradientCard>

          {/* Live customer preview was removed per user request — admin can
              still view the rendered experience from /admin/shop tab. */}

          {filteredItems.length === 0 ? (
            <View style={styles.emptyCard}>
              <Feather name="layout" size={28} color={colors.textMuted} />
              <Text style={styles.emptyText}>
                {pincodeSearch
                  ? `No blocks matching pincode ${pincodeSearch}`
                  : `No blocks for ${scope === "home" ? "Home" : scopeCategory}`}
              </Text>
              <Text style={styles.emptySub}>
                {pincodeSearch
                  ? "Clear the pincode filter above or add a new block scoped to this pincode."
                  : "Tap + to add a banner slider, category circles, product grid, flash sale, or any other block."}
              </Text>
              {pincodeSearch ? (
                <TouchableOpacity onPress={() => setPincodeSearch("")} style={{ marginTop: 6 }}>
                  <Text style={{ color: colors.primary, fontWeight: "800", fontSize: 12 }}>Clear pincode filter</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          ) : (
            <DraggableLayoutList
              items={filteredItems}
              onReorder={onReorder}
              renderItem={(b: Block, isDragging: boolean) => (
                <BlockCard
                  block={b}
                  products={products}
                  analytics={analytics[b.id]}
                  confirmDeleteId={confirmDeleteId}
                  isDragging={isDragging}
                  onMove={onMove}
                  onToggle={onToggleActive}
                  onEdit={() => { setEditing(b); setShowForm(true); }}
                  onDelete={() => onDelete(b)}
                  onSetSize={async (size) => {
                    try {
                      await api.patch(`/admin/shop-layout/${b.id}`, { size });
                      setItems((prev) => prev.map((x) => x.id === b.id ? { ...x, size } : x));
                    } catch (e) { Alert.alert("Resize failed", formatApiError(e)); }
                  }}
                />
              )}
            />
          )}
        </ScrollView>
      )}

      <BlockFormModal
        visible={showForm}
        block={editing}
        products={products}
        categories={categories}
        defaultScope={scope}
        defaultScopeCategory={scopeCategory}
        usedElsewhere={usedElsewhere}
        onClose={() => setShowForm(false)}
        onSaved={() => { setShowForm(false); load(); }}
      />
    </SafeAreaView>
  );
}

/* ─────────────────────────── Block card (list row) ─────────────────────────── */

function BlockCard({
  block: b, products, analytics, confirmDeleteId, isDragging, onMove, onToggle, onEdit, onDelete, onSetSize,
}: {
  block: Block; products: Product[];
  analytics?: { impressions: number; clicks: number; ctr: number };
  confirmDeleteId: string | null; isDragging?: boolean;
  onMove: (b: Block, d: -1 | 1) => void; onToggle: (b: Block) => void;
  onEdit: () => void; onDelete: () => void; onSetSize: (s: "small" | "medium" | "large") => void;
}) {
  const meta = TYPE_META[b.block_type] || TYPE_META.text;
  const sizable = (b.block_type === "background" || b.block_type === "content_box" || b.block_type === "banner_slider");
  const linkedProduct = b.product_id ? products.find((p) => p.id === b.product_id) : null;
  const thumbUrl = resolveImageUrl(b.image_data_url || (b.items && b.items[0]?.image_data_url) || "");
  // Jun 2026 — Multi-pincode targets (falls back to the legacy single field).
  const targetPins: string[] = Array.from(new Set([
    ...(Array.isArray((b as any).scope_pincodes) ? (b as any).scope_pincodes.map(String) : []),
    String((b as any).scope_pincode || ""),
  ].map((s) => s.trim()).filter(Boolean)));

  return (
    <View style={[styles.card, isDragging && styles.cardDragging]} testID={`block-${b.id}`}>
      {/* Drag-handle hint stripe — long-press anywhere on the card to drag */}
      <View style={styles.dragHandle}>
        <Feather name="menu" size={14} color={colors.textMuted} />
      </View>
      <View>
        {thumbUrl ? (
          <Image source={{ uri: thumbUrl }} style={styles.thumb} resizeMode="cover" />
        ) : (
          <View style={[styles.thumb, { alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted }]}>
            <Feather name={meta.icon} size={20} color={colors.textMuted} />
          </View>
        )}
      </View>
      <View style={{ flex: 1, marginLeft: 12 }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <View style={styles.typePill}><Text style={styles.typePillText}>{meta.label.toUpperCase()}</Text></View>
          <View style={[styles.statusPill, { backgroundColor: b.active ? "#DCFCE7" : "#F3F4F6" }]}>
            <Text style={[styles.statusText, { color: b.active ? "#065F46" : "#475569" }]}>{b.active ? "ACTIVE" : "DRAFT"}</Text>
          </View>
          {b.data_source && b.data_source !== "manual" ? (
            <View style={[styles.statusPill, { backgroundColor: "#EEF2FF" }]}>
              <Text style={[styles.statusText, { color: "#3730A3" }]}>{(b.data_source || "manual").toUpperCase()}</Text>
            </View>
          ) : null}
          {/* Jun 2026 — Multi-pincode targeting badge. */}
          {targetPins.length ? (
            <View style={[styles.statusPill, { backgroundColor: "#FEF3C7", flexDirection: "row", alignItems: "center", gap: 3 }]}>
              <Feather name="map-pin" size={9} color="#92400E" />
              <Text style={[styles.statusText, { color: "#92400E" }]}>
                {targetPins.length === 1 ? targetPins[0] : `${targetPins.length} PINCODES`}
              </Text>
            </View>
          ) : null}
        </View>
        <Text style={styles.cardTitle} numberOfLines={1}>{b.title || meta.label}</Text>
        {b.subtitle ? <Text style={styles.cardSub} numberOfLines={1}>{b.subtitle}</Text> : null}
        <Text style={styles.cardMeta}>
          Order #{b.sort_order}
          {linkedProduct ? ` · → ${linkedProduct.name}` : ""}
          {b.items && b.items.length ? ` · ${b.items.length} slide${b.items.length === 1 ? "" : "s"}` : ""}
          {b.product_ids && b.product_ids.length ? ` · ${b.product_ids.length} products` : ""}
        </Text>
        {analytics ? (
          <View style={styles.analyticsRow}>
            <View style={styles.analyticsChip}>
              <Feather name="eye" size={10} color="#3730A3" />
              <Text style={styles.analyticsText}>{analytics.impressions}</Text>
            </View>
            <View style={styles.analyticsChip}>
              <Feather name="mouse-pointer" size={10} color="#065F46" />
              <Text style={[styles.analyticsText, { color: "#065F46" }]}>{analytics.clicks}</Text>
            </View>
            <View style={[styles.analyticsChip, { backgroundColor: analytics.ctr >= 5 ? "#DCFCE7" : "#FEF3C7" }]}>
              <Feather name="trending-up" size={10} color={analytics.ctr >= 5 ? "#065F46" : "#92400E"} />
              <Text style={[styles.analyticsText, { color: analytics.ctr >= 5 ? "#065F46" : "#92400E" }]}>{analytics.ctr}% CTR</Text>
            </View>
            <Text style={styles.analyticsHint}>7d</Text>
          </View>
        ) : null}
        <View style={{ flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
          <TouchableOpacity onPress={() => onMove(b, -1)} style={styles.actionMicro}><Feather name="chevron-up" size={12} color={colors.textMain} /></TouchableOpacity>
          <TouchableOpacity onPress={() => onMove(b, 1)} style={styles.actionMicro}><Feather name="chevron-down" size={12} color={colors.textMain} /></TouchableOpacity>
          {sizable ? (
            <View style={styles.sizeChips}>
              {(["small", "medium", "large"] as const).map((s) => (
                <TouchableOpacity
                  key={s} onPress={() => onSetSize(s)}
                  style={[styles.sizeChip, (b.size || "medium") === s && styles.sizeChipActive]}
                  testID={`block-size-${b.id}-${s}`}
                >
                  <Text style={[styles.sizeChipText, (b.size || "medium") === s && styles.sizeChipTextActive]}>{s[0].toUpperCase()}</Text>
                </TouchableOpacity>
              ))}
            </View>
          ) : null}
          <TouchableOpacity onPress={onEdit} style={styles.actionBtn} testID={`block-edit-${b.id}`}>
            <Feather name="edit-2" size={12} color={colors.primary} />
            <Text style={styles.actionText}>Edit</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => onToggle(b)} style={styles.actionBtn}>
            <Feather name={b.active ? "eye-off" : "eye"} size={12} color={colors.textMain} />
            <Text style={styles.actionText}>{b.active ? "Hide" : "Publish"}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onDelete}
            style={[
              styles.actionBtn,
              confirmDeleteId === b.id
                ? { borderColor: "#B91C1C", backgroundColor: "#FEE2E2" }
                : { borderColor: "#FCA5A5" },
            ]}
            testID={`block-delete-${b.id}`}
          >
            <Feather name={confirmDeleteId === b.id ? "alert-triangle" : "trash-2"} size={12} color="#B91C1C" />
            <Text style={[styles.actionText, { color: "#B91C1C" }]}>
              {confirmDeleteId === b.id ? "Tap again to delete" : "Delete"}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

/* ─────────────────────────── Block Form Modal ─────────────────────────── */

function BlockFormModal({
  visible, block, products, categories, defaultScope, defaultScopeCategory, usedElsewhere, onClose, onSaved,
}: {
  visible: boolean; block: Block | null; products: Product[]; categories: { name: string; label: string; depth: number }[];
  defaultScope: "home" | "category"; defaultScopeCategory: string;
  /** Product ids already placed in OTHER blocks — hidden from the picker. */
  usedElsewhere: Set<string>;
  onClose: () => void; onSaved: () => void;
}) {
  const router = useRouter();
  const [type, setType] = useState<BlockType>("banner_slider");
  const [scope, setScope] = useState<"home" | "category">(defaultScope);
  const [scopeCategory, setScopeCategory] = useState(defaultScopeCategory);
  // Jun 2026 — MULTI-pincode targeting. A block can now be aimed at
  // several pincodes at once; empty list = renders everywhere.
  const [scopePincodes, setScopePincodes] = useState<string[]>([]);
  const [pincodeDraft, setPincodeDraft] = useState<string>("");
  const addPincode = useCallback(() => {
    const p = pincodeDraft.trim();
    if (p.length !== 6) return;
    setScopePincodes((prev) => (prev.includes(p) ? prev : [...prev, p]));
    setPincodeDraft("");
  }, [pincodeDraft]);
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [body, setBody] = useState("");
  const [ctaLabel, setCtaLabel] = useState("");
  const [imageDataUrl, setImageDataUrl] = useState("");
  // Aug 2026 — "cover" (crop-to-fill, default) OR "contain" (show full image,
  // no crop, letterbox with bg_color). Toggle exposed in the form for
  // banner-type blocks so admins choose per-banner.
  const [imageFit, setImageFit] = useState<"cover" | "contain">("cover");
  const [productId, setProductId] = useState<string | null>(null);
  const [productIds, setProductIds] = useState<string[]>([]);
  const [sortOrder, setSortOrder] = useState("0");
  const [active, setActive] = useState(true);
  const [size, setSize] = useState<"small" | "medium" | "large">("medium");
  // Styling
  const [textColor, setTextColor] = useState("");
  const [bgColor, setBgColor] = useState("");
  const [fontSize, setFontSize] = useState("");
  const [textAlign, setTextAlign] = useState<"left" | "center" | "right" | "">("");
  const [buttonColor, setButtonColor] = useState("");
  const [buttonTextColor, setButtonTextColor] = useState("");
  const [height, setHeight] = useState("");
  // Data
  const [dataSource, setDataSource] = useState<string>("manual");
  const [productCount, setProductCount] = useState("10");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [items, setItems] = useState<LayoutItem[]>([]);
  const [flashEndsAt, setFlashEndsAt] = useState("");
  const [productsPerRow, setProductsPerRow] = useState<string>("2");
  const [showViewAll, setShowViewAll] = useState<boolean>(false);
  const [viewAllLink, setViewAllLink] = useState<string>("");
  // Sept 2026 — multi-select which categories appear in THIS
  // category_circles block. Empty ⇒ auto-show every category not already
  // pinned to another category_circles block on the same scope.
  const [categoryIds, setCategoryIds] = useState<string[]>([]);
  // API-loaded catalog of shop_categories (name, image, icon) so the
  // multi-select can render pretty labels + previews.
  const [shopCats, setShopCats] = useState<Array<{
    id: string; name: string; image_url?: string | null;
    color: string; icon_pack: string; icon_name: string; active: boolean;
    depth?: number; parent_id?: string | null;
  }>>([]);
  // UI
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [showProductPicker, setShowProductPicker] = useState(false);
  const [showMultiPicker, setShowMultiPicker] = useState(false);
  // Jun 2026 — multi-picker search + vendor filter state
  const [pickSearch, setPickSearch] = useState("");
  const [pickVendor, setPickVendor] = useState("");
  // Nov 2026 — the picker asks the SERVER for products (paged + searched)
  // instead of waiting on a full-catalogue download, so it opens instantly at
  // any catalogue size.
  const pool = useAdminProductSearch({
    enabled: showMultiPicker,
    search: pickSearch,
    vendorId: pickVendor,
  });
  // Nov 2026 — the single picker keeps its OWN search, otherwise a search
  // left in the multi picker made it open showing one product.
  const [singleSearch, setSingleSearch] = useState("");
  const singlePool = useAdminProductSearch({
    enabled: showProductPicker,
    search: singleSearch,
  });
  const pickerVendors = useMemo(() => {
    // Nov 2026 — derived from the rows currently loaded in the picker (the
    // catalogue is no longer downloaded in full). Enough to jump between the
    // vendors you can see; search narrows the rest.
    const m = new Map<string, { id: string; name: string; count: number }>();
    pool.items.forEach((p) => {
      const id = p.vendor_id || "";
      if (!id) return;
      const cur = m.get(id);
      if (cur) cur.count += 1;
      else m.set(id, { id, name: p.vendor_name || "Vendor", count: 1 });
    });
    return Array.from(m.values()).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [pool.items]);
  const pickerFiltered = useMemo(() => {
    // Search + vendor filtering happen on the SERVER (useAdminProductSearch),
    // so only the block-level exclusion is local.
    return pool.items.filter((p) => {
      // Nov 2026 — a product already placed in ANOTHER block is hidden here,
      // so the same SKU can't be shelved twice across the shop. Products in
      // the block being edited stay visible (they're the current selection).
      if (usedElsewhere.has(p.id) && !productIds.includes(p.id)) return false;
      return true;
    });
  }, [pool.items, usedElsewhere, productIds]);
  // Nov 2026 — names for products the admin just picked. The screen only
  // pre-loads the products its blocks reference, so a freshly picked product
  // isn't in `products` yet and used to render as a raw UUID.
  const nameOf = useCallback((id: string) => (
    products.find((p) => p.id === id)?.name || pool.items.find((p) => p.id === id)?.name || ""
  ), [products, pool.items]);
  const [editingItemIdx, setEditingItemIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!visible) return;
    setType((block?.block_type as BlockType) || "banner_slider");
    setScope((block as any)?.scope || defaultScope);
    setScopeCategory((block as any)?.scope_category || defaultScopeCategory);
    setScopePincodes(
      Array.isArray((block as any)?.scope_pincodes) && (block as any).scope_pincodes.length
        ? (block as any).scope_pincodes.map(String)
        : ((block as any)?.scope_pincode ? [String((block as any).scope_pincode)] : []),
    );
    setPincodeDraft("");
    // Nov 2026 — a stale picker search / vendor filter used to carry over into
    // the next block, so "New Block → Products" could open showing
    // "0 shown — No products match this search" and look empty.
    setPickSearch("");
    setPickVendor("");
    setSingleSearch("");
    setTitle(block?.title || "");
    setSubtitle(block?.subtitle || "");
    setBody(block?.body || "");
    setCtaLabel(block?.cta_label || "");
    setImageDataUrl(block?.image_data_url || "");
    setImageFit(((block as any)?.image_fit === "contain" ? "contain" : "cover"));
    setProductId(block?.product_id || null);
    setProductIds(block?.product_ids || []);
    setSortOrder(String(block?.sort_order ?? 0));
    setActive(block?.active ?? true);
    setSize((block?.size as any) || "medium");
    setTextColor((block as any)?.text_color || "");
    setBgColor((block as any)?.bg_color || "");
    setFontSize((block as any)?.font_size ? String((block as any).font_size) : "");
    setTextAlign((block as any)?.text_align || "");
    setButtonColor((block as any)?.button_color || "");
    setButtonTextColor((block as any)?.button_text_color || "");
    setHeight((block as any)?.height ? String((block as any).height) : "");
    setDataSource((block as any)?.data_source || "manual");
    setProductCount(String((block as any)?.product_count || 10));
    setCategoryFilter((block as any)?.category_filter || "");
    setItems(block?.items || []);
    setFlashEndsAt((block as any)?.flash_sale_ends_at || "");
    setProductsPerRow(String((block as any)?.products_per_row || 2));
    setShowViewAll(Boolean((block as any)?.show_view_all));
    setViewAllLink((block as any)?.view_all_link || "");
    setCategoryIds(Array.isArray((block as any)?.category_ids) ? (block as any).category_ids : []);
  }, [visible, block, defaultScope, defaultScopeCategory]);

  // Load the shop_categories catalog once when the form opens — used to
  // render the "which categories in this block" multi-select for
  // category_circles blocks.
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      try {
        // `exclude_recharge=true` offers the Recharge ROOT (so it can be
        // placed in the shop) while hiding every operator sub-shelf —
        // Vi / Jio / Airtel / BSNL / Dish TV / Tata Play / Sun Direct /
        // Airtel Digital TV — which are served by the recharge flow, not
        // by a product grid. Without this flag they leaked into the picker.
        const r = await api.get<{ items: any[] }>("/admin/shop-categories?exclude_recharge=true");
        if (cancelled) return;
        const items = (r.data?.items || []) as any[];
        // Sort by sort_order then name so the picker matches the admin
        // Shop Categories page.
        items.sort((a, b) => (a.sort_order - b.sort_order) || (a.name || "").localeCompare(b.name || ""));
        setShopCats(items);
      } catch { /* silent — falls back to no picker */ }
    })();
    return () => { cancelled = true; };
  }, [visible]);

  // Smart picker — auto-crops + resizes to the destination block's native
  // aspect ratio. Pass the block_type so the right preset (banner 16:9,
  // category 1:1, brand 9:5, etc.) is used; falls back to a square crop
  // for blocks we haven't catalogued yet.
  const pickImage = async (cb: (url: string) => void, target?: ImageTarget, forceFit?: "cover" | "contain") => {
    setPicking(true);
    try {
      const tgt: ImageTarget = target || (type as ImageTarget) || "banner_slider";
      // Aug 2026 — honor per-block `imageFit`. When admin opts into
      // "contain" we skip the centre-crop step in the fitter entirely.
      const mode: "cover" | "contain" = forceFit || imageFit;
      const dataUrl = await pickAndFitImage(IMAGE_SPECS[tgt] ? tgt : "banner_slider", mode);
      if (dataUrl) cb(dataUrl);
    } catch (e) { Alert.alert("Image pick failed", formatApiError(e)); }
    finally { setPicking(false); }
  };

  // Recommended-size hint shown next to each image picker so the admin
  // sees the optimal source resolution at a glance.
  const pickerHintFor = (target?: ImageTarget): string => {
    const tgt: ImageTarget = target || (type as ImageTarget) || "banner_slider";
    const spec = IMAGE_SPECS[tgt];
    return spec ? `Auto-fits to ${spec.label}` : "Auto-fits to block size";
  };

  const usesItems = ["banner_slider", "brand_slider", "offer_cards"].includes(type);
  const usesDynamicCategories = type === "category_circles";
  // Jun 2026 — Category Circles are a MAIN-category navigator only.
  const mainShopCats = useMemo(
    () => shopCats.filter((c) => Number(c.depth || 0) === 0 && !c.parent_id),
    [shopCats],
  );
  // Per-block image override, stored in `items` keyed by category name, so
  // the master image in /admin/shop-categories is never touched.
  const circleOverride = (name: string) =>
    (items.find((it) => (it.label || "").trim().toLowerCase() === name.trim().toLowerCase())?.image_data_url) || "";
  const setCircleOverride = (name: string, url: string) => {
    setItems((prev) => {
      const idx = prev.findIndex((it) => (it.label || "").trim().toLowerCase() === name.trim().toLowerCase());
      if (idx >= 0) {
        const n = [...prev];
        if (url) n[idx] = { ...n[idx], image_data_url: url };
        else n.splice(idx, 1);
        return n;
      }
      if (!url) return prev;
      return [...prev, { label: name, subtitle: "", image_data_url: url, link_type: "category", link_value: name, color: "" }];
    });
  };
  const usesProducts = ["product_grid", "horizontal_slider", "flash_sale", "spotlight"].includes(type);
  const usesSingleProduct = type === "content_box" || type === "background";
  const usesImage = type === "background" || type === "spotlight";
  // Jun 2026 — subtitle is hidden for product sections (it pushed the last
  // row of products off-screen). Spotlight keeps it as a small eyebrow line.
  const usesSubtitle = !["announcement_strip", "product_grid", "horizontal_slider", "flash_sale"].includes(type);
  const allowedSources = SOURCES_FOR_TYPE[type] || DATA_SOURCES.map((d) => d.value);
  const sourceOptions = DATA_SOURCES.filter((d) => allowedSources.includes(d.value));
  // "View more" is supported by product_grid AND the new spotlight block.
  const usesViewMore = type === "product_grid" || type === "spotlight";

  useEffect(() => {
    if (!visible) return;
    // Jun 2026 — keep `dataSource` legal for the current block type. Product
    // grid / flash sale are Manual-only now, so an old "trending" value must
    // snap back to "manual" instead of silently overriding the admin's picks.
    const allowed = SOURCES_FOR_TYPE[type];
    if (allowed && !allowed.includes(dataSource)) setDataSource(allowed[0]);
  }, [visible, type, dataSource]);

  const onSave = async () => {
    if (type === "background" && !imageDataUrl) { Alert.alert("Image required", "Banner blocks need an image."); return; }
    if (type === "content_box" && !productId) { Alert.alert("Product required", "Pick a product for this content box."); return; }
    if (usesItems && items.length === 0) { Alert.alert("Items required", "Add at least one slide/item."); return; }
    setSaving(true);
    try {
      const payload: any = {
        block_type: type,
        scope, scope_category: scope === "category" ? scopeCategory : "",
        scope_pincode: (scopePincodes[0] || "").trim(),
        scope_pincodes: scopePincodes,
        title: title.trim(), subtitle: subtitle.trim(), body: body.trim(),
        cta_label: ctaLabel.trim(),
        image_data_url: imageDataUrl,
        image_fit: imageFit,
        product_id: productId,
        product_ids: usesProducts && dataSource === "manual" ? productIds : [],
        sort_order: parseInt(sortOrder, 10) || 0,
        active, size,
        text_color: textColor, bg_color: bgColor,
        font_size: fontSize ? parseInt(fontSize, 10) : null,
        text_align: textAlign,
        button_color: buttonColor, button_text_color: buttonTextColor,
        height: height ? parseInt(height, 10) : null,
        data_source: usesProducts ? dataSource : "manual",
        product_count: usesProducts ? Math.max(1, Math.min(500, parseInt(productCount, 10) || 10)) : 10,
        category_filter: usesProducts ? categoryFilter : "",
        // category_circles reuses `items` to carry per-block image overrides.
        items: (usesItems || type === "category_circles") ? items : [],
        flash_sale_ends_at: type === "flash_sale" ? flashEndsAt : "",
        products_per_row: type === "product_grid" ? Math.max(1, Math.min(4, parseInt(productsPerRow, 10) || 2)) : 2,
        show_view_all: usesViewMore ? showViewAll : false,
        view_all_link: usesViewMore ? viewAllLink.trim() : "",
        // Sept 2026 — only meaningful for category_circles blocks; other
        // block types persist an empty list so a follow-up type-switch
        // doesn't inherit stale selection.
        category_ids: type === "category_circles" ? categoryIds : [],
      };
      if (block) await api.patch(`/admin/shop-layout/${block.id}`, payload);
      else await api.post("/admin/shop-layout", payload);
      onSaved();
    } catch (e) { Alert.alert("Save failed", formatApiError(e)); }
    finally { setSaving(false); }
  };

  // Items editor handlers
  const addItem = () => setItems((prev) => [...prev, { label: "", subtitle: "", image_data_url: "", link_type: null, link_value: "", color: "" }]);
  const updateItem = (idx: number, patch: Partial<LayoutItem>) => setItems((prev) => prev.map((it, i) => i === idx ? { ...it, ...patch } : it));
  const removeItem = (idx: number) => setItems((prev) => prev.filter((_, i) => i !== idx));
  const moveItem = (idx: number, dir: -1 | 1) => setItems((prev) => {
    const n = [...prev]; const j = idx + dir;
    if (j < 0 || j >= n.length) return n;
    [n[idx], n[j]] = [n[j], n[idx]]; return n;
  });

  const toggleProductId = (id: string) => setProductIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent>
      <View style={styles.modalOverlay}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={onClose} style={styles.iconBtn} testID="block-editor-close">
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.modalTitle}>{block ? "Edit block" : "New block"}</Text>
            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.iconBtn, styles.iconBtnPrimary, saving && { opacity: 0.5 }]} testID="block-editor-save">
              {saving ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <Feather name="check" size={20} color={colors.primaryFg} />}
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} keyboardShouldPersistTaps="handled">
            {/* Scope */}
            <Text style={styles.label}>Where does this block appear?</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TouchableOpacity onPress={() => setScope("home")} style={[styles.scopeChoice, scope === "home" && styles.scopeChoiceActive]}>
                <Feather name="home" size={13} color={scope === "home" ? colors.primaryFg : colors.primary} />
                <Text style={[styles.scopeChoiceText, scope === "home" && { color: colors.primaryFg }]}>Home</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setScope("category")} style={[styles.scopeChoice, scope === "category" && styles.scopeChoiceActive]}>
                <Feather name="grid" size={13} color={scope === "category" ? colors.primaryFg : colors.primary} />
                <Text style={[styles.scopeChoiceText, scope === "category" && { color: colors.primaryFg }]}>Category</Text>
              </TouchableOpacity>
            </View>
            {scope === "category" ? (
              <>
                <Text style={styles.label}>Category</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {categories.length === 0 ? (
                    <Text style={styles.hint}>No categories yet — assign a category to your products first.</Text>
                  ) : categories.map((c) => (
                    <TouchableOpacity
                      key={c.name}
                      onPress={() => setScopeCategory(c.name)}
                      style={[styles.chip, scopeCategory === c.name && styles.chipActive]}
                      testID={`block-cat-${c.name}`}
                    >
                      {c.depth ? <Feather name="corner-down-right" size={11} color={scopeCategory === c.name ? colors.primaryFg : colors.primary} style={{ marginRight: 4 }} /> : null}
                      <Text style={[styles.chipText, scopeCategory === c.name && { color: colors.primaryFg }]}>{c.label}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </>
            ) : null}

            {/* Jun 2026 — MULTI-pincode targeting.  Add as many pincodes as
                the campaign covers; leave the list empty to render the
                block in every area. */}
            <Text style={styles.label}>Target pincodes (optional)</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput
                value={pincodeDraft}
                onChangeText={(v) => setPincodeDraft(v.replace(/\D/g, "").slice(0, 6))}
                onSubmitEditing={addPincode}
                placeholder="Type a 6-digit pincode"
                placeholderTextColor={colors.textMuted}
                style={[styles.input, { flex: 1, marginBottom: 0 }]}
                keyboardType="number-pad"
                maxLength={6}
                testID="block-scope-pincode"
              />
              <TouchableOpacity
                onPress={addPincode}
                disabled={pincodeDraft.length !== 6}
                style={[styles.pinAddBtn, pincodeDraft.length !== 6 && { opacity: 0.4 }]}
                testID="block-add-pincode"
              >
                <Feather name="plus" size={16} color={colors.primaryFg} />
                <Text style={styles.pinAddBtnText}>Add</Text>
              </TouchableOpacity>
            </View>
            {scopePincodes.length ? (
              <View style={styles.pinChipRow}>
                {scopePincodes.map((p) => (
                  <TouchableOpacity
                    key={p}
                    onPress={() => setScopePincodes((prev) => prev.filter((x) => x !== p))}
                    style={styles.pinTargetChip}
                    testID={`block-pin-chip-${p}`}
                  >
                    <Text style={styles.pinTargetChipText}>{p}</Text>
                    <Feather name="x" size={12} color={colors.primary} />
                  </TouchableOpacity>
                ))}
                <TouchableOpacity onPress={() => setScopePincodes([])} style={styles.pinClearBtn} testID="block-clear-pincodes">
                  <Text style={styles.pinClearText}>Clear all</Text>
                </TouchableOpacity>
              </View>
            ) : null}
            <Text style={styles.pinHelp}>
              {scopePincodes.length
                ? `Shows only to customers in ${scopePincodes.length} pincode${scopePincodes.length === 1 ? "" : "s"}.`
                : "No pincodes added — this block shows in every area."}
            </Text>

            {/* Block type */}
            <Text style={styles.label}>Block type</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              {ALL_TYPES.map((t) => {
                const meta = TYPE_META[t];
                const isActive = type === t;
                return (
                  <TouchableOpacity key={t} style={[styles.typeChoice, isActive && styles.typeChoiceActive]} onPress={() => setType(t)} testID={`block-type-${t}`}>
                    <Feather name={meta.icon} size={14} color={isActive ? colors.primaryFg : colors.primary} />
                    <Text style={[styles.typeChoiceText, isActive && { color: colors.primaryFg }]}>{meta.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
            <Text style={styles.hint}>{TYPE_META[type].hint}</Text>

            {/* Category Circles: dynamic from /admin/shop-categories */}
            {usesDynamicCategories ? (
              <View style={styles.dynamicCatInfo}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
                  <Feather name="link" size={14} color={colors.primary} />
                  <Text style={styles.dynamicCatTitle}>Which categories in this circle?</Text>
                </View>
                <Text style={styles.dynamicCatBody}>
                  Tap categories below to include them. Only MAIN categories appear as circles — sub-categories stay inside their parent screen.{"\n"}
                  <Text style={{ fontWeight: "800" }}>Leave empty</Text> to auto-show every category that isn&apos;t already used in another circle block on this scope.
                </Text>

                {/* Multi-select grid of active shop_categories */}
                {mainShopCats.length === 0 ? (
                  <Text style={[styles.hint, { marginTop: 8 }]}>Loading categories…</Text>
                ) : (
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                    {mainShopCats.map((c) => {
                      const isSelected = categoryIds.includes(c.id);
                      const isInactive = !c.active;
                      return (
                        <TouchableOpacity
                          key={c.id}
                          disabled={isInactive}
                          onPress={() => {
                            setCategoryIds((prev) => isSelected
                              ? prev.filter((x) => x !== c.id)
                              : [...prev, c.id]);
                          }}
                          style={[
                            styles.catChip,
                            isSelected && styles.catChipActive,
                            isInactive && { opacity: 0.45 },
                          ]}
                          testID={`circle-cat-${c.id}`}
                        >
                          <View style={[styles.catChipDot, { backgroundColor: c.color || "#E5F2EC" }]}>
                            {c.image_url ? (
                              <Image source={{ uri: c.image_url }} style={{ width: 20, height: 20, borderRadius: 10 }} />
                            ) : (
                              <Feather name={isSelected ? "check" : "grid"} size={11} color={isSelected ? colors.primaryFg : colors.textMain} />
                            )}
                          </View>
                          <Text style={[styles.catChipText, isSelected && styles.catChipTextActive]} numberOfLines={1}>
                            {c.name}{isInactive ? " (off)" : ""}
                          </Text>
                          {isSelected ? (
                            <Feather name="check" size={12} color={colors.primaryFg} />
                          ) : null}
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                )}

                {/* Jun 2026 — Per-block image override for the SELECTED
                    categories. Changing it here only affects THIS block;
                    /admin/shop-categories keeps the master image. */}
                {categoryIds.length > 0 ? (
                  <View style={{ marginTop: 12, gap: 8 }}>
                    <Text style={styles.dynamicCatTitle}>Image for this block only</Text>
                    {mainShopCats.filter((c) => categoryIds.includes(c.id)).map((c) => {
                      const ov = circleOverride(c.name);
                      return (
                        <View key={`ov-${c.id}`} style={styles.ovRow}>
                          <TouchableOpacity
                            onPress={() => pickImage((url) => setCircleOverride(c.name, url), "category_circles", "cover")}
                            style={styles.ovThumb}
                            testID={`circle-img-${c.id}`}
                          >
                            {ov || c.image_url ? (
                              <Image source={{ uri: resolveImageUrl(ov || (c.image_url as string)) }} style={{ width: "100%", height: "100%", borderRadius: 8 }} resizeMode="cover" />
                            ) : (
                              <Feather name="image" size={14} color={colors.textMuted} />
                            )}
                          </TouchableOpacity>
                          <View style={{ flex: 1, minWidth: 0 }}>
                            <Text style={styles.ovName} numberOfLines={1}>{c.name}</Text>
                            <Text style={styles.ovHint} numberOfLines={1}>
                              {ov ? "Custom image for this block" : "Using the main shop image — tap to change"}
                            </Text>
                          </View>
                          {ov ? (
                            <TouchableOpacity onPress={() => setCircleOverride(c.name, "")} style={styles.actionMicro} testID={`circle-img-reset-${c.id}`}>
                              <Feather name="rotate-ccw" size={12} color={colors.textMain} />
                            </TouchableOpacity>
                          ) : null}
                        </View>
                      );
                    })}
                  </View>
                ) : null}

                {/* Summary + shortcuts */}
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                  <Text style={[styles.hint, { flex: 1, minWidth: 120 }]}>
                    {categoryIds.length === 0
                      ? "0 selected · auto mode (fills gaps)"
                      : `${categoryIds.length} selected`}
                  </Text>
                  {categoryIds.length > 0 ? (
                    <TouchableOpacity onPress={() => setCategoryIds([])} style={styles.dynamicCatBtnGhost} testID="circle-clear-all">
                      <Feather name="x" size={12} color={colors.primary} />
                      <Text style={styles.dynamicCatBtnGhostText}>Clear</Text>
                    </TouchableOpacity>
                  ) : null}
                  <TouchableOpacity onPress={() => setCategoryIds(shopCats.filter((c) => c.active).map((c) => c.id))} style={styles.dynamicCatBtnGhost} testID="circle-select-all">
                    <Feather name="check-square" size={12} color={colors.primary} />
                    <Text style={styles.dynamicCatBtnGhostText}>Select all</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => { onClose(); router.push("/admin/shop-categories" as any); }}
                    style={styles.dynamicCatBtn}
                    testID="manage-shop-categories"
                  >
                    <Feather name="grid" size={12} color={colors.primaryFg} />
                    <Text style={styles.dynamicCatBtnText}>Manage</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ) : null}

            {/* Title / Subtitle / Body */}
            {(type !== "content_box" && type !== "background") ? (
              <>
                <Text style={styles.label}>{type === "announcement_strip" ? "Message" : "Title"} (optional)</Text>
                <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder={
                  type === "section_header" ? "FEATURED ELECTRONICS" :
                  type === "flash_sale" ? "Flash Sale" :
                  type === "announcement_strip" ? "Free shipping on orders over ₹999" : "Block title"
                } placeholderTextColor={colors.textMuted} maxLength={80} />
                {usesSubtitle ? (
                  <>
                    <Text style={styles.label}>{type === "spotlight" ? "Eyebrow line (optional)" : "Subtitle (optional)"}</Text>
                    <TextInput style={styles.input} value={subtitle} onChangeText={setSubtitle} placeholder={type === "spotlight" ? "TRENDING NOW" : "Short helper text"} placeholderTextColor={colors.textMuted} maxLength={120} />
                  </>
                ) : null}
                {type === "text" ? (
                  <>
                    <Text style={styles.label}>Body</Text>
                    <TextInput style={[styles.input, { minHeight: 80, textAlignVertical: "top" }]} value={body} onChangeText={setBody} multiline maxLength={500} />
                  </>
                ) : null}
              </>
            ) : null}

            {/* Single image (background / spotlight backdrop) */}
            {usesImage ? (
              <>
                <Text style={styles.label}>{type === "spotlight" ? "Backdrop image (optional)" : "Image (required)"}</Text>
                <Text style={styles.hint}>
                  {type === "spotlight"
                    ? "Fills the whole spotlight card behind the title. Leave empty to use the first product's photo."
                    : pickerHintFor("background")}
                  {imageFit === "cover"
                    ? " — image will fill the block (edges may crop)."
                    : " — full image will be shown (no crop). Set a background color below to fill any gaps."}
                </Text>

                {/* Aug 2026 — Fit-mode toggle. Lets admin choose full-image
                    vs. crop-to-fill BEFORE picking the image so the fitter
                    doesn't centre-crop when they want the whole photo. */}
                <View style={styles.fitRow}>
                  <TouchableOpacity
                    onPress={() => setImageFit("cover")}
                    style={[styles.fitBtn, imageFit === "cover" && styles.fitBtnActive]}
                    testID="banner-fit-cover"
                  >
                    <Feather name="maximize-2" size={12} color={imageFit === "cover" ? "#fff" : colors.primary} />
                    <Text style={[styles.fitBtnText, imageFit === "cover" && styles.fitBtnTextActive]}>Crop to fill</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => setImageFit("contain")}
                    style={[styles.fitBtn, imageFit === "contain" && styles.fitBtnActive]}
                    testID="banner-fit-contain"
                  >
                    <Feather name="image" size={12} color={imageFit === "contain" ? "#fff" : colors.primary} />
                    <Text style={[styles.fitBtnText, imageFit === "contain" && styles.fitBtnTextActive]}>Show full image</Text>
                  </TouchableOpacity>
                </View>

                <TouchableOpacity onPress={() => pickImage(setImageDataUrl, "background")} style={styles.imagePicker}>
                  {imageDataUrl ? (
                    <Image source={{ uri: resolveImageUrl(imageDataUrl) }} style={styles.imagePreview} resizeMode={imageFit === "contain" ? "contain" : "cover"} />
                  ) : (
                    <View style={styles.imagePickerEmpty}>
                      {picking ? <ActivityIndicator color={colors.primary} /> : (
                        <>
                          <Feather name="image" size={28} color={colors.textMuted} />
                          <Text style={styles.imagePickerHint}>Tap to upload</Text>
                        </>
                      )}
                    </View>
                  )}
                </TouchableOpacity>
              </>
            ) : null}

            {/* Single product (content_box, background) */}
            {usesSingleProduct ? (
              <>
                <Text style={styles.label}>{type === "content_box" ? "Linked product (required)" : "Link to product (optional)"}</Text>
                <TouchableOpacity style={styles.input} onPress={() => setShowProductPicker(true)} testID="single-product-picker">
                  <Text style={{ color: productId ? colors.textMain : colors.textMuted }}>
                    {productId ? (nameOf(productId) || productId) : "Tap to pick a product"}
                  </Text>
                </TouchableOpacity>
                {productId ? (
                  <TouchableOpacity onPress={() => setProductId(null)} style={{ alignSelf: "flex-start", marginTop: 4 }}>
                    <Text style={{ color: "#B91C1C", fontSize: 12, fontWeight: "700" }}>Clear link</Text>
                  </TouchableOpacity>
                ) : null}
                <Text style={styles.label}>CTA label (optional)</Text>
                <TextInput style={styles.input} value={ctaLabel} onChangeText={setCtaLabel} placeholder="View" placeholderTextColor={colors.textMuted} maxLength={24} />
              </>
            ) : null}

            {/* Product-grid / Horizontal slider / Flash sale — data source + products */}
            {usesProducts ? (
              <>
                {sourceOptions.length > 1 ? (
                  <>
                    <Text style={styles.label}>Data source</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                      {sourceOptions.map((ds) => (
                        <TouchableOpacity key={ds.value} onPress={() => setDataSource(ds.value)} style={[styles.chip, dataSource === ds.value && styles.chipActive]} testID={`ds-${ds.value}`}>
                          <Text style={[styles.chipText, dataSource === ds.value && { color: colors.primaryFg }]}>{ds.label}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                    <Text style={styles.hint}>{sourceOptions.find((d) => d.value === dataSource)?.hint || ""}</Text>
                  </>
                ) : (
                  <Text style={styles.hint}>
                    {type === "flash_sale"
                      ? "Products are hand-picked — use a flash sale to move slow stock at a discount."
                      : "Products are hand-picked so this section always shows exactly what you choose."}
                  </Text>
                )}

                {dataSource === "manual" ? (
                  <>
                    <Text style={styles.label}>Products ({productIds.length} selected)</Text>
                    <TouchableOpacity style={styles.input} onPress={() => setShowMultiPicker(true)} testID="multi-product-picker">
                      <Text style={{ color: productIds.length ? colors.textMain : colors.textMuted }}>
                        {productIds.length ? `${productIds.length} product${productIds.length === 1 ? "" : "s"} selected — tap to edit` : "Tap to select products"}
                      </Text>
                    </TouchableOpacity>
                    {/* Jun 2026 — manual blocks show EVERY selected product, so
                        there is no "Product count" cap to get out of sync
                        (the old default of 3 hid the 4th pick). */}
                    <Text style={styles.hint}>All {productIds.length || 0} selected product{productIds.length === 1 ? "" : "s"} will be shown.</Text>
                  </>
                ) : (
                  <>
                    <Text style={styles.label}>Filter by category (optional)</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                      <TouchableOpacity onPress={() => setCategoryFilter("")} style={[styles.chip, !categoryFilter && styles.chipActive]}>
                        <Text style={[styles.chipText, !categoryFilter && { color: colors.primaryFg }]}>All</Text>
                      </TouchableOpacity>
                      {categories.map((c) => (
                        <TouchableOpacity key={c.name} onPress={() => setCategoryFilter(c.name)} style={[styles.chip, categoryFilter === c.name && styles.chipActive]}>
                          {c.depth ? <Feather name="corner-down-right" size={11} color={categoryFilter === c.name ? colors.primaryFg : colors.primary} style={{ marginRight: 4 }} /> : null}
                          <Text style={[styles.chipText, categoryFilter === c.name && { color: colors.primaryFg }]}>{c.label}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                    <Text style={styles.label}>Product count (1-500)</Text>
                    <TextInput style={styles.input} value={productCount} onChangeText={(t) => setProductCount(t.replace(/[^0-9]/g, "").slice(0, 3))} keyboardType="numeric" placeholder="10" placeholderTextColor={colors.textMuted} />
                    <Text style={styles.hint}>How many auto-picked products to show. Max 500.</Text>
                  </>
                )}

                {/* Product Grid extras: per-row count, View More link */}
                {type === "product_grid" ? (
                  <>
                    <Text style={styles.label}>Products per row</Text>
                    <View style={{ flexDirection: "row", gap: 8 }}>
                      {([1, 2, 3, 4] as const).map((n) => {
                        const active = String(n) === productsPerRow;
                        return (
                          <TouchableOpacity
                            key={`ppr-${n}`}
                            onPress={() => setProductsPerRow(String(n))}
                            style={[styles.perRowChip, active && styles.perRowChipActive]}
                            testID={`ppr-${n}`}
                          >
                            <Text style={[styles.perRowChipText, active && { color: colors.primaryFg }]}>{n}</Text>
                            <Text style={[styles.perRowChipSub, active && { color: colors.primaryFg, opacity: 0.85 }]}>
                              per row
                            </Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                    <Text style={styles.hint}>
                      Combine with Size (S/M/L) on the block card to fine-tune card height. 1 per row = full-width hero cards, 4 per row = compact thumbnails.
                    </Text>
                  </>
                ) : null}

                {usesViewMore ? (
                  <>
                    <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 12, paddingHorizontal: 4 }}>
                      <View style={{ flex: 1, paddingRight: 10 }}>
                        <Text style={[styles.label, { marginTop: 0 }]}>Show {`"View More"`} link</Text>
                        <Text style={styles.hint}>
                          {type === "spotlight"
                            ? "Adds the CTA pill on the spotlight card. Tapping the card also opens this target."
                            : "Appears at the top-right of the section header."}
                        </Text>
                      </View>
                      <Switch value={showViewAll} onValueChange={setShowViewAll} />
                    </View>

                    {showViewAll ? (
                      <>
                        <Text style={styles.label}>{`"View More"`} target</Text>
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                          <TouchableOpacity onPress={() => setViewAllLink("")} style={[styles.chip, !viewAllLink && styles.chipActive]}>
                            <Text style={[styles.chipText, !viewAllLink && { color: colors.primaryFg }]}>Whole shop</Text>
                          </TouchableOpacity>
                          {categories.map((c) => (
                            <TouchableOpacity key={`val-${c.name}`} onPress={() => setViewAllLink(c.name)} style={[styles.chip, viewAllLink === c.name && styles.chipActive]}>
                              <Text style={[styles.chipText, viewAllLink === c.name && { color: colors.primaryFg }]}>{c.label}</Text>
                            </TouchableOpacity>
                          ))}
                        </View>
                      </>
                    ) : null}
                  </>
                ) : null}

                {type === "spotlight" ? (
                  <>
                    <Text style={styles.label}>CTA label (optional)</Text>
                    <TextInput style={styles.input} value={ctaLabel} onChangeText={setCtaLabel} placeholder="Shop the collection" placeholderTextColor={colors.textMuted} maxLength={28} />
                    <Text style={styles.hint}>
                      The spotlight card is ~1/3 of the phone screen tall. Leave Height blank below for the automatic size.
                    </Text>
                  </>
                ) : null}

                {type === "flash_sale" ? <FlashEndsPicker value={flashEndsAt} onChange={setFlashEndsAt} /> : null}
              </>
            ) : null}

            {/* Items editor (banner_slider / category_circles / brand_slider / offer_cards) */}
            {usesItems ? (
              <>
                <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 14 }}>
                  <Text style={[styles.label, { marginTop: 0 }]}>Items ({items.length})</Text>
                  <TouchableOpacity onPress={addItem} style={[styles.iconBtn, styles.iconBtnPrimary, { width: 32, height: 32, borderRadius: 16 }]} testID="add-item">
                    <Feather name="plus" size={16} color={colors.primaryFg} />
                  </TouchableOpacity>
                </View>
                {items.length === 0 ? (
                  <Text style={styles.hint}>Tap + to add a {type === "banner_slider" ? "slide" : type === "category_circles" ? "category" : type === "brand_slider" ? "brand" : "offer"}. {pickerHintFor(type as ImageTarget)}</Text>
                ) : (
                  <Text style={styles.hint}>
                    {pickerHintFor(type as ImageTarget)} — {imageFit === "cover" ? "images auto-cropped to fit" : "full image shown (no crop)"}.
                  </Text>
                )}
                {items.map((it, idx) => (
                  <View key={`item-${idx}`} style={styles.itemRow}>
                    <TouchableOpacity onPress={() => pickImage((url) => updateItem(idx, { image_data_url: url }), type as ImageTarget)} style={styles.itemThumb}>
                      {it.image_data_url ? (
                        <Image source={{ uri: resolveImageUrl(it.image_data_url) }} style={{ width: "100%", height: "100%", borderRadius: 8 }} resizeMode="cover" />
                      ) : (
                        <Feather name="image" size={16} color={colors.textMuted} />
                      )}
                    </TouchableOpacity>
                    <View style={{ flex: 1, gap: 4 }}>
                      <TextInput style={[styles.input, { paddingVertical: 6, fontSize: 12 }]} value={it.label || ""} onChangeText={(v) => updateItem(idx, { label: v })} placeholder={type === "category_circles" ? "Category name" : "Title"} placeholderTextColor={colors.textMuted} />
                      {type !== "category_circles" && type !== "brand_slider" ? (
                        <TextInput style={[styles.input, { paddingVertical: 6, fontSize: 12 }]} value={it.subtitle || ""} onChangeText={(v) => updateItem(idx, { subtitle: v })} placeholder="Subtitle (optional)" placeholderTextColor={colors.textMuted} />
                      ) : null}
                      {/* Link selector */}
                      <View style={{ flexDirection: "row", gap: 4 }}>
                        {(["product", "category", null] as const).map((lt) => (
                          <TouchableOpacity key={String(lt)} onPress={() => updateItem(idx, { link_type: lt, link_value: "" })} style={[styles.miniChip, (it.link_type || null) === lt && styles.miniChipActive]}>
                            <Text style={[styles.miniChipText, (it.link_type || null) === lt && { color: colors.primaryFg }]}>{lt === null ? "No link" : lt}</Text>
                          </TouchableOpacity>
                        ))}
                      </View>
                      {it.link_type === "category" ? (
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
                          {categories.map((c) => (
                            <TouchableOpacity key={c.name} onPress={() => updateItem(idx, { link_value: c.name })} style={[styles.miniChip, it.link_value === c.name && styles.miniChipActive]}>
                              <Text style={[styles.miniChipText, it.link_value === c.name && { color: colors.primaryFg }]}>{c.label}</Text>
                            </TouchableOpacity>
                          ))}
                        </View>
                      ) : it.link_type === "product" ? (
                        <TouchableOpacity style={[styles.input, { paddingVertical: 6 }]} onPress={() => {
                          setEditingItemIdx(idx); setShowProductPicker(true);
                        }}>
                          <Text style={{ fontSize: 11, color: it.link_value ? colors.textMain : colors.textMuted }}>
                            {it.link_value ? (nameOf(it.link_value) || "—") : "Pick a product"}
                          </Text>
                        </TouchableOpacity>
                      ) : null}
                    </View>
                    <View style={{ gap: 4 }}>
                      <TouchableOpacity onPress={() => moveItem(idx, -1)} style={styles.actionMicro}><Feather name="chevron-up" size={12} color={colors.textMain} /></TouchableOpacity>
                      <TouchableOpacity onPress={() => moveItem(idx, 1)} style={styles.actionMicro}><Feather name="chevron-down" size={12} color={colors.textMain} /></TouchableOpacity>
                      <TouchableOpacity onPress={() => removeItem(idx)} style={[styles.actionMicro, { backgroundColor: "#FEE2E2" }]}>
                        <Feather name="x" size={12} color="#B91C1C" />
                      </TouchableOpacity>
                    </View>
                  </View>
                ))}
              </>
            ) : null}

            {/* Styling overrides */}
            <Text style={[styles.label, { marginTop: 18 }]}>Style overrides (optional)</Text>
            <Text style={styles.hint}>Leave blank to use app defaults.</Text>

            <Text style={styles.miniLabel}>Text color</Text>
            <ColorRow value={textColor} onChange={setTextColor} />
            <Text style={styles.miniLabel}>Background color</Text>
            <ColorRow value={bgColor} onChange={setBgColor} />
            <Text style={styles.miniLabel}>Button color</Text>
            <ColorRow value={buttonColor} onChange={setButtonColor} />
            <Text style={styles.miniLabel}>Button text color</Text>
            <ColorRow value={buttonTextColor} onChange={setButtonTextColor} />

            <View style={{ flexDirection: "row", gap: 10, marginTop: 8 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.miniLabel}>Font size</Text>
                <TextInput style={styles.input} value={fontSize} onChangeText={setFontSize} keyboardType="numeric" placeholder="auto" placeholderTextColor={colors.textMuted} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.miniLabel}>Height (px)</Text>
                <TextInput style={styles.input} value={height} onChangeText={setHeight} keyboardType="numeric" placeholder="auto" placeholderTextColor={colors.textMuted} />
              </View>
            </View>

            <Text style={styles.miniLabel}>Text alignment</Text>
            <View style={{ flexDirection: "row", gap: 6 }}>
              {ALIGN_OPTIONS.map((a) => (
                <TouchableOpacity key={a.v} onPress={() => setTextAlign(textAlign === a.v ? "" : a.v)} style={[styles.alignBtn, textAlign === a.v && styles.alignBtnActive]}>
                  <Feather name={a.icon} size={14} color={textAlign === a.v ? colors.primaryFg : colors.textMain} />
                </TouchableOpacity>
              ))}
            </View>

            {/* Sort order / active */}
            <View style={{ flexDirection: "row", gap: 12, marginTop: 14 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Sort order</Text>
                <TextInput style={styles.input} value={sortOrder} onChangeText={setSortOrder} keyboardType="numeric" placeholder="0" placeholderTextColor={colors.textMuted} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Active</Text>
                <View style={[styles.input, { flexDirection: "row", alignItems: "center", justifyContent: "space-between" }]}>
                  <Text style={{ color: active ? colors.primary : colors.textMuted, fontWeight: "700" }}>{active ? "Visible" : "Hidden"}</Text>
                  <Switch value={active} onValueChange={setActive} />
                </View>
              </View>
            </View>
          </ScrollView>
        </View>
      </View>

      {/* Single product picker (also used for item link selection) */}
      <Modal visible={showProductPicker} transparent animationType="slide" onRequestClose={() => { setShowProductPicker(false); setEditingItemIdx(null); }}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalSheet, { maxHeight: "70%" }]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => { setShowProductPicker(false); setEditingItemIdx(null); }} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
              <Text style={styles.modalTitle}>Pick a product</Text>
              <View style={{ width: 40 }} />
            </View>
            {/* Nov 2026 — search box: at 6k+ SKUs an admin can't scroll to
                find one product. Queries the server as you type. */}
            <View style={{ paddingHorizontal: 16, paddingBottom: 8 }}>
              <View style={styles.pickerSearchWrap}>
                <Feather name="search" size={16} color={colors.textMuted} />
                <TextInput
                  value={singleSearch}
                  onChangeText={setSingleSearch}
                  placeholder="Search products…"
                  placeholderTextColor={colors.textMuted}
                  style={styles.pickerSearchInput}
                  testID="single-picker-search"
                  returnKeyType="search"
                />
                {singleSearch ? (
                  <TouchableOpacity
                    onPress={() => setSingleSearch("")}
                    style={{ width: 44, height: 44, alignItems: "center", justifyContent: "center" }}
                    testID="single-picker-search-clear"
                  >
                    <Feather name="x" size={15} color={colors.textMuted} />
                  </TouchableOpacity>
                ) : null}
              </View>
              <Text style={styles.hint}>
                {singlePool.loading ? "Loading…" : `${singlePool.items.length} shown of ${singlePool.total.toLocaleString("en-IN")}`}
              </Text>
            </View>
            <ScrollView
              contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
              scrollEventThrottle={64}
              onScroll={(e) => {
                const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent;
                if (contentOffset.y + layoutMeasurement.height >= contentSize.height - 200) singlePool.loadMore();
              }}
            >
              {singlePool.loading ? (
                <View style={{ padding: 24, alignItems: "center" }}>
                  <ActivityIndicator size="small" color={colors.primary} />
                </View>
              ) : singlePool.items.length === 0 ? (
                <Text style={{ color: colors.textMuted, textAlign: "center", padding: 20 }} testID="single-picker-empty">
                  {singleSearch ? "No products match this search" : "No products yet"}
                </Text>
              ) : singlePool.items.map((p) => {
                const isSelected = editingItemIdx !== null
                  ? items[editingItemIdx]?.link_value === p.id
                  : productId === p.id;
                return (
                  <TouchableOpacity key={p.id} testID={`single-pick-${p.id}`} style={[styles.productRow, isSelected && { borderColor: colors.primary, backgroundColor: colors.brand100 }]}
                    onPress={() => {
                      if (editingItemIdx !== null) {
                        updateItem(editingItemIdx, { link_value: p.id });
                        setEditingItemIdx(null);
                      } else {
                        setProductId(p.id);
                      }
                      setShowProductPicker(false);
                    }}>
                    <Text style={styles.productRowText}>{p.name}</Text>
                    {isSelected ? <Feather name="check" size={16} color={colors.primary} /> : null}
                  </TouchableOpacity>
                );
              })}
              {singlePool.loadingMore ? (
                <View style={{ padding: 16, alignItems: "center" }}>
                  <ActivityIndicator size="small" color={colors.primary} />
                </View>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Multi-product picker — Jun 2026 rebuild.
          Owner asked for a vendor-wise filter and the full product list (the
          old sheet was an unsearchable flat list capped at the API default,
          which made curating a flash sale across 200 SKUs impossible).
          Adds: search box, vendor chips, thumbnails + price, and
          "Select all shown / Clear". */}
      <Modal visible={showMultiPicker} transparent animationType="slide" onRequestClose={() => setShowMultiPicker(false)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalSheet, { maxHeight: "88%" }]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setShowMultiPicker(false)} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
              <Text style={styles.modalTitle}>Select products ({productIds.length})</Text>
              <TouchableOpacity onPress={() => setShowMultiPicker(false)} style={[styles.iconBtn, styles.iconBtnPrimary]} testID="multi-picker-done">
                <Feather name="check" size={20} color={colors.primaryFg} />
              </TouchableOpacity>
            </View>

            <View style={{ paddingHorizontal: 16, paddingTop: 8 }}>
              <View style={styles.pickSearchWrap}>
                <Feather name="search" size={14} color={colors.textMuted} />
                <TextInput
                  value={pickSearch}
                  onChangeText={setPickSearch}
                  placeholder="Search products"
                  placeholderTextColor={colors.textMuted}
                  style={styles.pickSearchInput}
                  testID="multi-picker-search"
                />
                {pickSearch ? (
                  <TouchableOpacity onPress={() => setPickSearch("")} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                    <Feather name="x-circle" size={15} color={colors.textMuted} />
                  </TouchableOpacity>
                ) : null}
              </View>

              {pickerVendors.length > 1 ? (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 8 }}>
                  <TouchableOpacity onPress={() => setPickVendor("")} style={[styles.chip, !pickVendor && styles.chipActive]} testID="pick-vendor-all">
                    <Text style={[styles.chipText, !pickVendor && { color: colors.primaryFg }]}>All vendors</Text>
                  </TouchableOpacity>
                  {pickerVendors.map((v) => (
                    <TouchableOpacity key={v.id} onPress={() => setPickVendor(v.id)} style={[styles.chip, pickVendor === v.id && styles.chipActive]} testID={`pick-vendor-${v.id}`}>
                      <Text style={[styles.chipText, pickVendor === v.id && { color: colors.primaryFg }]} numberOfLines={1}>{v.name} ({v.count})</Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              ) : null}

              <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingBottom: 6 }}>
                <Text style={styles.hint}>
                  {pool.loading ? "Loading…" : `${pickerFiltered.length} shown of ${pool.total.toLocaleString("en-IN")} · ${productIds.length} selected`}
                </Text>
                <View style={{ flexDirection: "row", gap: 6 }}>
                  <TouchableOpacity
                    onPress={() => setProductIds((prev) => Array.from(new Set([...prev, ...pickerFiltered.map((p) => p.id)])))}
                    style={styles.miniChip}
                    testID="multi-picker-select-all"
                  >
                    <Text style={styles.miniChipText}>Select all shown</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => setProductIds([])} style={styles.miniChip} testID="multi-picker-clear">
                    <Text style={[styles.miniChipText, { color: "#B91C1C" }]}>Clear</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </View>

            <ScrollView
              contentContainerStyle={{ padding: 16, paddingTop: 4, paddingBottom: 32 }}
              scrollEventThrottle={64}
              onScroll={(e) => {
                const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent;
                if (contentOffset.y + layoutMeasurement.height >= contentSize.height - 200) pool.loadMore();
              }}
            >
              {pool.loading ? (
                <View style={{ padding: 28, alignItems: "center" }}>
                  <ActivityIndicator size="small" color={colors.primary} />
                  <Text style={[styles.hint, { marginTop: 8 }]}>Loading products…</Text>
                </View>
              ) : pickerFiltered.length === 0 ? (
                <Text style={{ color: colors.textMuted, textAlign: "center", padding: 20 }}>
                  {pool.total === 0 ? "No products yet" : "No products match this search / vendor"}
                </Text>
              ) : pickerFiltered.map((p) => {
                const selected = productIds.includes(p.id);
                return (
                  <TouchableOpacity
                    key={p.id}
                    style={[styles.pickRow, selected && { borderColor: colors.primary, backgroundColor: colors.brand100 }]}
                    onPress={() => toggleProductId(p.id)}
                    testID={`pick-product-${p.id}`}
                  >
                    {p.image_url ? (
                      <Image source={{ uri: resolveImageUrl(p.image_url) }} style={styles.pickThumb} resizeMode="cover" />
                    ) : (
                      <View style={[styles.pickThumb, { alignItems: "center", justifyContent: "center" }]}>
                        <Feather name="image" size={14} color={colors.textMuted} />
                      </View>
                    )}
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={styles.productRowText} numberOfLines={1}>{p.name}</Text>
                      <Text style={styles.pickMeta} numberOfLines={1}>
                        {p.vendor_name || "Own catalogue"}
                        {typeof p.price === "number" ? ` · ₹${Math.round(p.price)}` : ""}
                        {p.is_published === false ? " · unpublished" : ""}
                      </Text>
                    </View>
                    {selected ? <Feather name="check-square" size={18} color={colors.primary} /> : <Feather name="square" size={18} color={colors.textMuted} />}
                  </TouchableOpacity>
                );
              })}
              {pool.loadingMore ? (
                <View style={{ padding: 16, alignItems: "center" }}>
                  <ActivityIndicator size="small" color={colors.primary} />
                </View>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </Modal>
  );
}

/* ────────────────── Flash-sale "Sale ends" date + time picker ──────────────────
 *
 * Jun 2026 — the field used to be a raw ISO text box which shipped empty
 * (`""`), so the countdown never rendered and admins had no idea what format
 * to type. This gives a date box, a time box, and one-tap presets. We keep
 * storing an ISO-8601 string so the renderer's countdown is unchanged.
 * Deliberately dependency-free (no native date-picker module) so it behaves
 * identically on iOS, Android and the web admin panel.
 */

function pad2(n: number) { return String(n).padStart(2, "0"); }

function FlashEndsPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const parsed = value ? new Date(value) : null;
  const valid = parsed && !isNaN(parsed.getTime());
  const dateStr = valid ? `${parsed!.getFullYear()}-${pad2(parsed!.getMonth() + 1)}-${pad2(parsed!.getDate())}` : "";
  const timeStr = valid ? `${pad2(parsed!.getHours())}:${pad2(parsed!.getMinutes())}` : "";
  const [dateDraft, setDateDraft] = useState(dateStr);
  const [timeDraft, setTimeDraft] = useState(timeStr);

  useEffect(() => { setDateDraft(dateStr); setTimeDraft(timeStr); }, [dateStr, timeStr]);

  const commit = (d: string, t: string) => {
    const dm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d.trim());
    const tm = /^(\d{1,2}):(\d{2})$/.exec(t.trim());
    if (!dm) { onChange(""); return; }
    const hh = tm ? Math.min(23, parseInt(tm[1], 10)) : 23;
    const mm = tm ? Math.min(59, parseInt(tm[2], 10)) : 59;
    const dt = new Date(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3]), hh, mm, 0);
    if (isNaN(dt.getTime())) { onChange(""); return; }
    onChange(dt.toISOString());
  };

  const preset = (hours: number) => {
    const dt = new Date(Date.now() + hours * 3_600_000);
    onChange(dt.toISOString());
  };

  const remaining = (() => {
    if (!valid) return "";
    const diff = parsed!.getTime() - Date.now();
    if (diff <= 0) return "Already ended";
    const h = Math.floor(diff / 3_600_000);
    const d = Math.floor(h / 24);
    return d > 0 ? `Ends in ${d}d ${h % 24}h` : `Ends in ${h}h ${Math.floor((diff % 3_600_000) / 60_000)}m`;
  })();

  return (
    <>
      <Text style={styles.label}>Sale ends</Text>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <View style={{ flex: 1.4 }}>
          <TextInput
            style={styles.input}
            value={dateDraft}
            onChangeText={(t) => { setDateDraft(t); commit(t, timeDraft); }}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            maxLength={10}
            testID="flash-ends-date"
          />
        </View>
        <View style={{ flex: 1 }}>
          <TextInput
            style={styles.input}
            value={timeDraft}
            onChangeText={(t) => { setTimeDraft(t); commit(dateDraft, t); }}
            placeholder="HH:MM"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            maxLength={5}
            testID="flash-ends-time"
          />
        </View>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
        {[["+6 hours", 6], ["+24 hours", 24], ["+3 days", 72], ["+7 days", 168]].map(([label, h]) => (
          <TouchableOpacity key={String(label)} onPress={() => preset(Number(h))} style={styles.chip} testID={`flash-preset-${h}`}>
            <Text style={styles.chipText}>{label as string}</Text>
          </TouchableOpacity>
        ))}
        {value ? (
          <TouchableOpacity onPress={() => onChange("")} style={[styles.chip, { borderColor: "#FCA5A5" }]} testID="flash-clear">
            <Text style={[styles.chipText, { color: "#B91C1C" }]}>Clear</Text>
          </TouchableOpacity>
        ) : null}
      </View>
      <Text style={styles.hint}>
        {valid ? `${remaining} · countdown shown to customers` : "Pick a date/time (or a preset) to show the live countdown on the block."}
      </Text>
    </>
  );
}

/* ─────────────────────────── Color row picker ─────────────────────────── */

function ColorRow({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingVertical: 4 }}>
      {PALETTE.map((c) => {
        const isClear = c === "";
        const isActive = value === c;
        return (
          <Pressable key={`${c}-${isClear}`} onPress={() => onChange(c)} style={[
            styles.colorSwatch,
            { backgroundColor: c || "#fff" },
            isClear && { borderStyle: "dashed", borderColor: colors.border, borderWidth: 1, alignItems: "center", justifyContent: "center" },
            isActive && { borderColor: colors.primary, borderWidth: 2 },
          ]}>
            {isClear ? <Feather name="x" size={12} color={colors.textMuted} /> : null}
          </Pressable>
        );
      })}
      <TextInput style={[styles.input, { paddingVertical: 6, marginLeft: 4, minWidth: 100, fontSize: 11 }]} value={value} onChangeText={onChange} placeholder="#hex" placeholderTextColor={colors.textMuted} autoCapitalize="none" maxLength={9} />
    </ScrollView>
  );
}

/* ─────────────────────────── Styles ─────────────────────────── */

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  iconBtnPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  title: { fontSize: 20, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyCard: { backgroundColor: colors.surface, borderRadius: radii.card, padding: 28, alignItems: "center", borderWidth: 1, borderColor: colors.border, gap: 8 },
  emptyText: { fontSize: 14, fontWeight: "800", color: colors.textMain, marginTop: 6 },
  emptySub: { fontSize: 12, color: colors.textMuted, textAlign: "center" },
  card: { flexDirection: "row", backgroundColor: colors.surface, borderRadius: radii.card, padding: 12, marginBottom: 12, borderWidth: 1, borderColor: colors.border },
  cardDragging: { borderColor: colors.primary, borderWidth: 2, backgroundColor: colors.brand100, shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 8 },
  dragHandle: { width: 18, alignItems: "center", justifyContent: "center", marginRight: 4, opacity: 0.5 },
  analyticsRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6, flexWrap: "wrap" },
  analyticsChip: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, backgroundColor: "#EEF2FF" },
  analyticsText: { fontSize: 10, fontWeight: "800", color: "#3730A3" },
  analyticsHint: { fontSize: 9, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.6, marginLeft: 2 },
  thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  cardTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, marginTop: 4, letterSpacing: -0.2 },
  cardSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  cardMeta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  typePill: { paddingHorizontal: 7, paddingVertical: 2, borderRadius: 6, backgroundColor: colors.brand100 },
  typePillText: { fontSize: 9, fontWeight: "900", color: colors.primary, letterSpacing: 0.6 },
  statusPill: { paddingHorizontal: 7, paddingVertical: 2, borderRadius: 999 },
  statusText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.4 },
  actionMicro: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  actionText: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  modalSheet: { flex: 1, marginTop: 60, backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  label: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1.2, marginTop: 14, marginBottom: 6 },
  miniLabel: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.8, marginTop: 8, marginBottom: 4 },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 6, fontStyle: "italic" },
  pickerSearchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 12, minHeight: 44,
  },
  pickerSearchInput: { flex: 1, fontSize: 13.5, color: colors.textMain, paddingVertical: 10 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  // Jun 2026 — Multi-pincode targeting controls
  pinAddBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 16, borderRadius: 12, backgroundColor: colors.primary, minHeight: 46, justifyContent: "center" },
  pinAddBtnText: { fontSize: 13, fontWeight: "800", color: colors.primaryFg },
  pinChipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  pinTargetChip: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primary },
  pinTargetChipText: { fontSize: 12, fontWeight: "800", color: colors.primary, letterSpacing: 0.3 },
  pinClearBtn: { paddingHorizontal: 10, paddingVertical: 7 },
  pinClearText: { fontSize: 11, fontWeight: "800", color: colors.textMuted },
  pinHelp: { fontSize: 11, color: colors.textMuted, marginTop: 8, fontWeight: "600" },

  imagePicker: { width: "100%", aspectRatio: 16 / 9, borderRadius: 14, borderWidth: 1.5, borderColor: colors.border, borderStyle: "dashed", overflow: "hidden", backgroundColor: colors.surfaceMuted },
  imagePickerEmpty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 4 },
  imagePickerHint: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 4 },
  fitRow: { flexDirection: "row", gap: 8, marginBottom: 10, marginTop: 4 },
  fitBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    borderWidth: 1, borderColor: colors.primary + "50",
    backgroundColor: colors.surface,
  },
  fitBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  fitBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  fitBtnTextActive: { color: "#fff" },
  imagePreview: { width: "100%", height: "100%" },
  typeChoice: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  typeChoiceActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  typeChoiceText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  scopeChoice: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 12, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  scopeChoiceActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  scopeChoiceText: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  chip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 11, fontWeight: "700", color: colors.textMain },
  miniChip: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  miniChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  miniChipText: { fontSize: 10, fontWeight: "700", color: colors.textMain },
  itemRow: { flexDirection: "row", alignItems: "flex-start", gap: 8, padding: 8, marginBottom: 8, backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  itemThumb: { width: 50, height: 50, borderRadius: 8, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  colorSwatch: { width: 28, height: 28, borderRadius: 14, borderWidth: 1, borderColor: colors.border },
  alignBtn: { width: 40, height: 36, borderRadius: 10, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  alignBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  productRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8, backgroundColor: colors.surface },
  // Jun 2026 — multi-product picker chrome
  pickSearchWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: 12,
    paddingHorizontal: 12, minHeight: 44,
    borderWidth: 1, borderColor: colors.border,
  },
  pickSearchInput: { flex: 1, fontSize: 13, color: colors.textMain, paddingVertical: 10 },
  pickRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    padding: 10, marginBottom: 8, backgroundColor: colors.surface,
    minHeight: 56,
  },
  pickThumb: { width: 40, height: 40, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  // Category-circle per-block image override rows
  ovRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, padding: 8, minHeight: 56,
  },
  ovThumb: {
    width: 40, height: 40, borderRadius: 8, backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  ovName: { fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  ovHint: { fontSize: 10.5, color: colors.textMuted, marginTop: 2 },
  pickMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  productRowText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  // Category-circles "interlinked" info banner shown in the form for the
  // category_circles block type. Categories themselves are managed from
  // /admin/shop-categories so the editor here is intentionally read-only.
  dynamicCatInfo: { marginTop: 14, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.brand100, gap: 4 },
  dynamicCatTitle: { fontSize: 13, fontWeight: "900", color: colors.primary },
  dynamicCatBody: { fontSize: 12, color: colors.textMain, lineHeight: 18 },
  dynamicCatBtn: { marginTop: 0, alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: colors.primary },
  dynamicCatBtnText: { fontSize: 12, fontWeight: "900", color: colors.primaryFg, letterSpacing: 0.2 },
  dynamicCatBtnGhost: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  dynamicCatBtnGhostText: { fontSize: 11, fontWeight: "700", color: colors.primary, letterSpacing: 0.2 },
  catChip: { flexDirection: "row", alignItems: "center", gap: 6, paddingLeft: 4, paddingRight: 10, paddingVertical: 4, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, maxWidth: 180 },
  catChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  catChipDot: { width: 26, height: 26, borderRadius: 13, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  catChipText: { fontSize: 11, fontWeight: "700", color: colors.textMain, letterSpacing: 0.2 },
  catChipTextActive: { color: colors.primaryFg },
  // Products per row chip (1..4) — square, large, easy to tap.
  perRowChip: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 12, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, gap: 2 },
  perRowChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  perRowChipText: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  perRowChipSub: { fontSize: 9, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.4 },
  sizeChips: { flexDirection: "row", borderWidth: 1, borderColor: colors.border, borderRadius: 999, overflow: "hidden", backgroundColor: colors.surface },
  sizeChip: { paddingHorizontal: 8, paddingVertical: 4, minWidth: 22, alignItems: "center", justifyContent: "center" },
  sizeChipActive: { backgroundColor: colors.primary },
  sizeChipText: { fontSize: 10, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.4 },
  sizeChipTextActive: { color: colors.primaryFg },
  scopeTabsWrap: { flexGrow: 0, flexShrink: 0, maxHeight: 50, marginTop: 4 },
  scopeTabs: { paddingHorizontal: spacing.screen, gap: 8, paddingBottom: 8, alignItems: "center" },
  scopeTab: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, height: 34 },
  scopeTabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  scopeTabText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  scopeTabTextActive: { color: colors.primaryFg },
  // Dec 2026 — Pincode filter bar (below scope tabs)
  pinBar: { paddingHorizontal: spacing.screen, paddingTop: 2, paddingBottom: 8 },
  pinInputWrap: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 12, paddingHorizontal: 12, height: 40,
  },
  pinInput: { flex: 1, fontSize: 13, color: colors.textMain, paddingVertical: 0, letterSpacing: 0.5 },
  pinChip: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    minHeight: 30, alignItems: "center", justifyContent: "center",
  },
  pinChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pinChipText: { fontSize: 11, fontWeight: "800", color: colors.textMain, letterSpacing: 0.4 },
  pinChipTextActive: { color: colors.primaryFg },
  heroBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: "#fff" },
  heroBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
});
