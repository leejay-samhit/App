// Admin Shop Layout — JSON-driven layout manager with 12 block types,
// scope routing (Home / per-category), styling overrides, multi-product
// picker, items editor, data-source selector, and live customer preview.
// All saved data is rendered by /src/shop-layout-renderer.tsx in both
// admin preview and on the customer app.
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Alert, RefreshControl, TextInput, Image, Modal, Switch, Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { ShopLayoutRenderer, LayoutBlock, LayoutItem, BlockType } from "../../src/shop-layout-renderer";

type Block = LayoutBlock;
type Product = { id: string; name: string; price?: number; image_url?: string; category?: string };

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
  content_box:      { label: "Content box",     icon: "package",      hint: "Single featured-product card · resizable",                    group: "Products" },
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
  "product_grid", "horizontal_slider", "content_box", "flash_sale",
  "offer_cards", "section_header", "text",
];

const DATA_SOURCES: { value: string; label: string; hint: string }[] = [
  { value: "manual", label: "Manual",     hint: "Pick specific products" },
  { value: "trending", label: "Trending", hint: "Auto: top by interest" },
  { value: "new", label: "New",           hint: "Auto: newest products" },
  { value: "best", label: "Best sellers", hint: "Auto: most sold" },
  { value: "category", label: "Category", hint: "All products in a category" },
];

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
  // Scope state: which layout we're editing
  const [scope, setScope] = useState<"home" | "category">("home");
  const [scopeCategory, setScopeCategory] = useState<string>("");

  // Categories list derived from products
  const categories = useMemo(() => {
    const set = new Set<string>();
    products.forEach((p) => { if (p.category) set.add(p.category); });
    return Array.from(set).sort();
  }, [products]);

  const load = useCallback(async () => {
    try {
      const [bRes, pRes] = await Promise.all([
        api.get<{ items: Block[] }>("/admin/shop-layout"),
        api.get<any>("/admin/products"),
      ]);
      setItems(bRes.data?.items || []);
      const pData = pRes.data;
      const list: Product[] = Array.isArray(pData) ? pData : (pData?.items || pData?.products || []);
      setProducts(list);
    } catch (e) { Alert.alert("Failed to load", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Filter items by current scope
  const filteredItems = useMemo(() => {
    return items.filter((b) => {
      const itemScope = (b as any).scope || "home";
      if (scope === "home") return itemScope === "home" || !itemScope;
      return itemScope === "category" && (b as any).scope_category === scopeCategory;
    });
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

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Shop Layout</Text>
        <TouchableOpacity
          onPress={() => { setEditing(null); setShowForm(true); }}
          style={[styles.iconBtn, styles.iconBtnPrimary]}
          testID="block-new"
        >
          <Feather name="plus" size={20} color={colors.primaryFg} />
        </TouchableOpacity>
      </View>

      {/* Scope tabs */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.scopeTabs}>
        <TouchableOpacity
          onPress={() => { setScope("home"); setScopeCategory(""); }}
          style={[styles.scopeTab, scope === "home" && styles.scopeTabActive]}
        >
          <Feather name="home" size={12} color={scope === "home" ? colors.primaryFg : colors.textMain} />
          <Text style={[styles.scopeTabText, scope === "home" && styles.scopeTabTextActive]}>Home</Text>
        </TouchableOpacity>
        {categories.map((c) => {
          const active = scope === "category" && scopeCategory === c;
          return (
            <TouchableOpacity
              key={c}
              onPress={() => { setScope("category"); setScopeCategory(c); }}
              style={[styles.scopeTab, active && styles.scopeTabActive]}
            >
              <Feather name="grid" size={12} color={active ? colors.primaryFg : colors.textMain} />
              <Text style={[styles.scopeTabText, active && styles.scopeTabTextActive]}>{c}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

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
              Tap S/M/L on a block to resize · Use up/down arrows to reorder · Switch the scope tabs above to manage per-category layouts.
            </Text>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <TouchableOpacity onPress={onMigratePromoBanners} disabled={migrating} style={[styles.heroBtn, migrating && { opacity: 0.6 }]} testID="migrate-banners">
                {migrating ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="download" size={12} color={colors.primary} />}
                <Text style={styles.heroBtnText}>Migrate old banners</Text>
              </TouchableOpacity>
            </View>
          </GradientCard>

          {/* === Live customer preview using the SAME renderer as the mobile app === */}
          {filteredItems.filter((b) => b.active).length > 0 ? (
            <View style={styles.previewWrap}>
              <View style={styles.previewHeader}>
                <Feather name="smartphone" size={14} color={colors.primary} />
                <Text style={styles.previewLabel}>LIVE CUSTOMER PREVIEW</Text>
                <Text style={styles.previewHint}>Identical to mobile app</Text>
              </View>
              <View style={styles.previewFrame}>
                <ShopLayoutRenderer
                  scope={scope}
                  category={scope === "category" ? scopeCategory : undefined}
                  onProductPress={() => {}}
                  onCategoryPress={() => {}}
                />
              </View>
            </View>
          ) : null}

          {filteredItems.length === 0 ? (
            <View style={styles.emptyCard}>
              <Feather name="layout" size={28} color={colors.textMuted} />
              <Text style={styles.emptyText}>No blocks for {scope === "home" ? "Home" : scopeCategory}</Text>
              <Text style={styles.emptySub}>Tap + to add a banner slider, category circles, product grid, flash sale, or any other block.</Text>
            </View>
          ) : (
            filteredItems.map((b) => <BlockCard key={b.id} block={b} products={products} confirmDeleteId={confirmDeleteId}
              onMove={onMove} onToggle={onToggleActive} onEdit={() => { setEditing(b); setShowForm(true); }}
              onDelete={() => onDelete(b)} onSetSize={async (size) => {
                try {
                  await api.patch(`/admin/shop-layout/${b.id}`, { size });
                  setItems((prev) => prev.map((x) => x.id === b.id ? { ...x, size } : x));
                } catch (e) { Alert.alert("Resize failed", formatApiError(e)); }
              }}
            />)
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
        onClose={() => setShowForm(false)}
        onSaved={() => { setShowForm(false); load(); }}
      />
    </SafeAreaView>
  );
}

/* ─────────────────────────── Block card (list row) ─────────────────────────── */

function BlockCard({
  block: b, products, confirmDeleteId, onMove, onToggle, onEdit, onDelete, onSetSize,
}: {
  block: Block; products: Product[]; confirmDeleteId: string | null;
  onMove: (b: Block, d: -1 | 1) => void; onToggle: (b: Block) => void;
  onEdit: () => void; onDelete: () => void; onSetSize: (s: "small" | "medium" | "large") => void;
}) {
  const meta = TYPE_META[b.block_type] || TYPE_META.text;
  const sizable = (b.block_type === "background" || b.block_type === "content_box" || b.block_type === "banner_slider");
  const linkedProduct = b.product_id ? products.find((p) => p.id === b.product_id) : null;
  const thumbUrl = b.image_data_url || (b.items && b.items[0]?.image_data_url) || "";

  return (
    <View style={styles.card} testID={`block-${b.id}`}>
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
        </View>
        <Text style={styles.cardTitle} numberOfLines={1}>{b.title || meta.label}</Text>
        {b.subtitle ? <Text style={styles.cardSub} numberOfLines={1}>{b.subtitle}</Text> : null}
        <Text style={styles.cardMeta}>
          Order #{b.sort_order}
          {linkedProduct ? ` · → ${linkedProduct.name}` : ""}
          {b.items && b.items.length ? ` · ${b.items.length} slide${b.items.length === 1 ? "" : "s"}` : ""}
          {b.product_ids && b.product_ids.length ? ` · ${b.product_ids.length} products` : ""}
        </Text>
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
          <TouchableOpacity onPress={onEdit} style={styles.actionBtn}>
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
  visible, block, products, categories, defaultScope, defaultScopeCategory, onClose, onSaved,
}: {
  visible: boolean; block: Block | null; products: Product[]; categories: string[];
  defaultScope: "home" | "category"; defaultScopeCategory: string;
  onClose: () => void; onSaved: () => void;
}) {
  const [type, setType] = useState<BlockType>("banner_slider");
  const [scope, setScope] = useState<"home" | "category">(defaultScope);
  const [scopeCategory, setScopeCategory] = useState(defaultScopeCategory);
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [body, setBody] = useState("");
  const [ctaLabel, setCtaLabel] = useState("");
  const [imageDataUrl, setImageDataUrl] = useState("");
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
  // UI
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [showProductPicker, setShowProductPicker] = useState(false);
  const [showMultiPicker, setShowMultiPicker] = useState(false);
  const [editingItemIdx, setEditingItemIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!visible) return;
    setType((block?.block_type as BlockType) || "banner_slider");
    setScope((block as any)?.scope || defaultScope);
    setScopeCategory((block as any)?.scope_category || defaultScopeCategory);
    setTitle(block?.title || "");
    setSubtitle(block?.subtitle || "");
    setBody(block?.body || "");
    setCtaLabel(block?.cta_label || "");
    setImageDataUrl(block?.image_data_url || "");
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
  }, [visible, block, defaultScope, defaultScopeCategory]);

  const pickImage = async (cb: (url: string) => void) => {
    setPicking(true);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) { Alert.alert("Permission needed", "Please allow photo library access."); return; }
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.8, allowsEditing: true,
      });
      if (!r.canceled && r.assets?.[0]?.uri) {
        const m = await ImageManipulator.manipulateAsync(
          r.assets[0].uri,
          [{ resize: { width: 1200 } }],
          { compress: 0.75, format: ImageManipulator.SaveFormat.JPEG, base64: true },
        );
        if (m.base64) cb(`data:image/jpeg;base64,${m.base64}`);
      }
    } catch (e) { Alert.alert("Image pick failed", formatApiError(e)); }
    finally { setPicking(false); }
  };

  const usesItems = ["banner_slider", "category_circles", "brand_slider", "offer_cards"].includes(type);
  const usesProducts = ["product_grid", "horizontal_slider", "flash_sale"].includes(type);
  const usesSingleProduct = type === "content_box" || type === "background";
  const usesImage = type === "background";

  const onSave = async () => {
    if (usesImage && !imageDataUrl) { Alert.alert("Image required", "Banner blocks need an image."); return; }
    if (type === "content_box" && !productId) { Alert.alert("Product required", "Pick a product for this content box."); return; }
    if (usesItems && items.length === 0) { Alert.alert("Items required", "Add at least one slide/item."); return; }
    setSaving(true);
    try {
      const payload: any = {
        block_type: type,
        scope, scope_category: scope === "category" ? scopeCategory : "",
        title: title.trim(), subtitle: subtitle.trim(), body: body.trim(),
        cta_label: ctaLabel.trim(),
        image_data_url: imageDataUrl,
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
        product_count: usesProducts ? parseInt(productCount, 10) || 10 : 10,
        category_filter: usesProducts ? categoryFilter : "",
        items: usesItems ? items : [],
        flash_sale_ends_at: type === "flash_sale" ? flashEndsAt : "",
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
            <TouchableOpacity onPress={onClose} style={styles.iconBtn}>
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.modalTitle}>{block ? "Edit block" : "New block"}</Text>
            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.iconBtn, styles.iconBtnPrimary, saving && { opacity: 0.5 }]}>
              {saving ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <Feather name="check" size={20} color={colors.primaryFg} />}
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 80 }} keyboardShouldPersistTaps="handled">
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
                    <TouchableOpacity key={c} onPress={() => setScopeCategory(c)} style={[styles.chip, scopeCategory === c && styles.chipActive]}>
                      <Text style={[styles.chipText, scopeCategory === c && { color: colors.primaryFg }]}>{c}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </>
            ) : null}

            {/* Block type */}
            <Text style={styles.label}>Block type</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              {ALL_TYPES.map((t) => {
                const meta = TYPE_META[t];
                const isActive = type === t;
                return (
                  <TouchableOpacity key={t} style={[styles.typeChoice, isActive && styles.typeChoiceActive]} onPress={() => setType(t)}>
                    <Feather name={meta.icon} size={14} color={isActive ? colors.primaryFg : colors.primary} />
                    <Text style={[styles.typeChoiceText, isActive && { color: colors.primaryFg }]}>{meta.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
            <Text style={styles.hint}>{TYPE_META[type].hint}</Text>

            {/* Title / Subtitle / Body */}
            {(type !== "content_box" && type !== "background") ? (
              <>
                <Text style={styles.label}>{type === "announcement_strip" ? "Message" : "Title"} (optional)</Text>
                <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder={
                  type === "section_header" ? "FEATURED ELECTRONICS" :
                  type === "flash_sale" ? "Flash Sale" :
                  type === "announcement_strip" ? "Free shipping on orders over ₹999" : "Block title"
                } placeholderTextColor={colors.textMuted} maxLength={80} />
                {(type !== "announcement_strip") ? (
                  <>
                    <Text style={styles.label}>Subtitle (optional)</Text>
                    <TextInput style={styles.input} value={subtitle} onChangeText={setSubtitle} placeholder="Short helper text" placeholderTextColor={colors.textMuted} maxLength={120} />
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

            {/* Single image (background) */}
            {usesImage ? (
              <>
                <Text style={styles.label}>Image (required)</Text>
                <TouchableOpacity onPress={() => pickImage(setImageDataUrl)} style={styles.imagePicker}>
                  {imageDataUrl ? (
                    <Image source={{ uri: imageDataUrl }} style={styles.imagePreview} resizeMode="cover" />
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
                    {productId ? (products.find((p) => p.id === productId)?.name || productId) : "Tap to pick a product"}
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
                <Text style={styles.label}>Data source</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {DATA_SOURCES.map((ds) => (
                    <TouchableOpacity key={ds.value} onPress={() => setDataSource(ds.value)} style={[styles.chip, dataSource === ds.value && styles.chipActive]}>
                      <Text style={[styles.chipText, dataSource === ds.value && { color: colors.primaryFg }]}>{ds.label}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <Text style={styles.hint}>{DATA_SOURCES.find((d) => d.value === dataSource)?.hint || ""}</Text>

                {dataSource === "manual" ? (
                  <>
                    <Text style={styles.label}>Products ({productIds.length} selected)</Text>
                    <TouchableOpacity style={styles.input} onPress={() => setShowMultiPicker(true)} testID="multi-product-picker">
                      <Text style={{ color: productIds.length ? colors.textMain : colors.textMuted }}>
                        {productIds.length ? `${productIds.length} product${productIds.length === 1 ? "" : "s"} selected — tap to edit` : "Tap to select products"}
                      </Text>
                    </TouchableOpacity>
                  </>
                ) : (
                  <>
                    <Text style={styles.label}>Filter by category (optional)</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                      <TouchableOpacity onPress={() => setCategoryFilter("")} style={[styles.chip, !categoryFilter && styles.chipActive]}>
                        <Text style={[styles.chipText, !categoryFilter && { color: colors.primaryFg }]}>All</Text>
                      </TouchableOpacity>
                      {categories.map((c) => (
                        <TouchableOpacity key={c} onPress={() => setCategoryFilter(c)} style={[styles.chip, categoryFilter === c && styles.chipActive]}>
                          <Text style={[styles.chipText, categoryFilter === c && { color: colors.primaryFg }]}>{c}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                  </>
                )}

                <Text style={styles.label}>Product count (1-50)</Text>
                <TextInput style={styles.input} value={productCount} onChangeText={setProductCount} keyboardType="numeric" placeholder="10" placeholderTextColor={colors.textMuted} />

                {type === "flash_sale" ? (
                  <>
                    <Text style={styles.label}>Sale ends (ISO date)</Text>
                    <TextInput style={styles.input} value={flashEndsAt} onChangeText={setFlashEndsAt} placeholder="2026-12-31T23:59:00Z" placeholderTextColor={colors.textMuted} autoCapitalize="none" />
                  </>
                ) : null}
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
                  <Text style={styles.hint}>Tap + to add a {type === "banner_slider" ? "slide" : type === "category_circles" ? "category" : type === "brand_slider" ? "brand" : "offer"}.</Text>
                ) : null}
                {items.map((it, idx) => (
                  <View key={`item-${idx}`} style={styles.itemRow}>
                    <TouchableOpacity onPress={() => pickImage((url) => updateItem(idx, { image_data_url: url }))} style={styles.itemThumb}>
                      {it.image_data_url ? (
                        <Image source={{ uri: it.image_data_url }} style={{ width: "100%", height: "100%", borderRadius: 8 }} resizeMode="cover" />
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
                            <TouchableOpacity key={c} onPress={() => updateItem(idx, { link_value: c })} style={[styles.miniChip, it.link_value === c && styles.miniChipActive]}>
                              <Text style={[styles.miniChipText, it.link_value === c && { color: colors.primaryFg }]}>{c}</Text>
                            </TouchableOpacity>
                          ))}
                        </View>
                      ) : it.link_type === "product" ? (
                        <TouchableOpacity style={[styles.input, { paddingVertical: 6 }]} onPress={() => {
                          setEditingItemIdx(idx); setShowProductPicker(true);
                        }}>
                          <Text style={{ fontSize: 11, color: it.link_value ? colors.textMain : colors.textMuted }}>
                            {it.link_value ? (products.find((p) => p.id === it.link_value)?.name || "—") : "Pick a product"}
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
            <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
              {products.length === 0 ? (
                <Text style={{ color: colors.textMuted, textAlign: "center", padding: 20 }}>No products yet</Text>
              ) : products.map((p) => {
                const isSelected = editingItemIdx !== null
                  ? items[editingItemIdx]?.link_value === p.id
                  : productId === p.id;
                return (
                  <TouchableOpacity key={p.id} style={[styles.productRow, isSelected && { borderColor: colors.primary, backgroundColor: colors.brand100 }]}
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
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Multi-product picker */}
      <Modal visible={showMultiPicker} transparent animationType="slide" onRequestClose={() => setShowMultiPicker(false)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalSheet, { maxHeight: "75%" }]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setShowMultiPicker(false)} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
              <Text style={styles.modalTitle}>Select products ({productIds.length})</Text>
              <TouchableOpacity onPress={() => setShowMultiPicker(false)} style={[styles.iconBtn, styles.iconBtnPrimary]}>
                <Feather name="check" size={20} color={colors.primaryFg} />
              </TouchableOpacity>
            </View>
            <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
              {products.length === 0 ? (
                <Text style={{ color: colors.textMuted, textAlign: "center", padding: 20 }}>No products yet</Text>
              ) : products.map((p) => {
                const selected = productIds.includes(p.id);
                return (
                  <TouchableOpacity key={p.id} style={[styles.productRow, selected && { borderColor: colors.primary, backgroundColor: colors.brand100 }]} onPress={() => toggleProductId(p.id)}>
                    <Text style={styles.productRowText}>{p.name}</Text>
                    {selected ? <Feather name="check-square" size={16} color={colors.primary} /> : <Feather name="square" size={16} color={colors.textMuted} />}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </Modal>
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
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  imagePicker: { width: "100%", aspectRatio: 16 / 9, borderRadius: 14, borderWidth: 1.5, borderColor: colors.border, borderStyle: "dashed", overflow: "hidden", backgroundColor: colors.surfaceMuted },
  imagePickerEmpty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 4 },
  imagePickerHint: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 4 },
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
  productRowText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  previewWrap: { marginBottom: 16, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted, overflow: "hidden" },
  previewHeader: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: colors.brand100 },
  previewLabel: { fontSize: 10, fontWeight: "900", letterSpacing: 1.4, color: colors.primary, marginLeft: 2 },
  previewHint: { fontSize: 10, color: colors.textMuted, marginLeft: "auto", fontStyle: "italic" },
  previewFrame: { padding: 12, backgroundColor: colors.background },
  sizeChips: { flexDirection: "row", borderWidth: 1, borderColor: colors.border, borderRadius: 999, overflow: "hidden", backgroundColor: colors.surface },
  sizeChip: { paddingHorizontal: 8, paddingVertical: 4, minWidth: 22, alignItems: "center", justifyContent: "center" },
  sizeChipActive: { backgroundColor: colors.primary },
  sizeChipText: { fontSize: 10, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.4 },
  sizeChipTextActive: { color: colors.primaryFg },
  scopeTabs: { paddingHorizontal: spacing.screen, gap: 6, paddingBottom: 8 },
  scopeTab: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  scopeTabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  scopeTabText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  scopeTabTextActive: { color: colors.primaryFg },
  heroBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: "#fff" },
  heroBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
});
