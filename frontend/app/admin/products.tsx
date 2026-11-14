import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, ScrollView, FlatList, Platform, AppState } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { FadeSlideIn, ProductCardSkeleton } from "../../src/anim";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { HelpGuide, HelpButton, useFirstVisitGuide, GuideStep } from "../../src/help-guide";
import { RichProductEditor } from "../../src/rich-product-editor";
import { ProductImage } from "../../src/product-image";
import { notify } from "../../src/notify";

/** Products fetched per page by the admin catalogue list. */
const PAGE_SIZE = 250;

// Walkthrough steps shown on first visit (and via the "?" button) of
// /admin/products. Keep these in plain language; admins are not engineers.
const PRODUCT_GUIDE_STEPS: GuideStep[] = [
  {
    icon: "package",
    title: "Welcome! Let's create your first product.",
    body: "Products are what customers see and buy on the Shop tab. This 6-step guide takes ~1 minute.",
    tip: "You can re-open this guide any time by tapping the ? icon above.",
  },
  {
    icon: "plus-circle",
    title: "1. Tap the + button",
    body: "Tap the green + button at the top-right of this screen to open the New Product sheet.",
    highlight: "Top-right · the green + (plus) icon",
  },
  {
    icon: "image",
    title: "2. Upload a product photo",
    body: "Tap the dashed photo box and pick an image from your gallery. We'll auto-compress it to a fast-loading size.",
    tip: "Square photos look best in the catalog grid (1:1 ratio).",
  },
  {
    icon: "edit-3",
    title: "3. Name + Price + Description",
    body: "• Name: what customers will see (e.g. 'Wireless Earbuds Pro')\n• Price: number only — no ₹ or commas\n• Description: a short paragraph about features",
  },
  {
    icon: "tag",
    title: "4. Category + Stock",
    body: "• Category groups products on the Shop (e.g. Electronics, Fashion)\n• Stock is how many units you have — when it hits 0, customers see SOLD OUT",
    tip: "The category you type becomes filterable on the customer Shop and can have its own custom layout.",
  },
  {
    icon: "eye",
    title: "5. Turn ON Published",
    body: "Flip the Published toggle ON. Only published products appear in the customer Shop. Draft products stay hidden until you publish.",
    highlight: "The Published switch at the bottom of the form",
  },
  {
    icon: "check-circle",
    title: "6. Save and you're live!",
    body: "Tap the green ✓ check at the top-right of the form to save. Your product instantly shows in the catalog grid below — and on the customer Shop tab.",
    tip: "Want to feature it? Go to More → Shop layout to add it to Banner sliders, Flash sales, Trending sections, and more.",
  },
];

type Product = {
  id: string;
  name: string;
  price: number;
  image_url: string;
  description?: string;
  stock?: number;
  category?: string;
  is_published?: boolean;
  review_status?: string;
  review_fields?: string[];
  review_requested_at?: string;
  vendor_id?: string;
  vendor_name?: string;
  vendor_email?: string;
  interested_count?: number;
};

type VendorLite = { id: string; name: string; email?: string; store_pincode?: string; is_approved?: boolean; status?: string };

type InterestedUser = { id: string; name: string; email: string; phone?: string };

export default function AdminProducts() {
  const router = useRouter();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  // Auto-opens on the admin's first visit to /admin/products
  const { visible: helpVisible, close: helpClose } = useFirstVisitGuide("products-v1");
  const [search, setSearch] = useState("");
  const [reviewOnly, setReviewOnly] = useState(false);
  // Jul 2026 — Vendor filter: admin can narrow products by vendor.
  const [vendorFilter, setVendorFilter] = useState<VendorLite | null>(null);
  const [vendorPickerOpen, setVendorPickerOpen] = useState(false);
  const [interestedFor, setInterestedFor] = useState<Product | null>(null);
  // Jun 2026 — Bulk publish / unpublish (whole catalog or one vendor).
  const [bulkConfirm, setBulkConfirm] = useState<null | "publish" | "unpublish">(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  // Jun 2026 — Real pagination.  The old screen asked for `limit: 200` and
  // showed whatever came back, so a restored 1,509-product catalogue looked
  // like it had lost 1,300 items.  We now page through the catalogue and
  // search on the SERVER, so every product is reachable.
  const [total, setTotal] = useState(0);
  // Nov 2026 — numbered pages replaced the old "Load more" accumulator.
  // The accumulator reset to 60 whenever the screen regained focus (or the
  // app returned from background), so after scrolling to 180 products the
  // list silently snapped back to 60. Pages hold their position and scale to
  // any catalogue size.
  const [page, setPage] = useState(0);
  const loadSeq = useRef(0);
  // Current page, in a ref too, so `load` keeps a stable identity (the focus
  // effect used to re-run — and re-fetch — on every page tap).
  const pageRef = useRef(0);
  // Bulk sub-category mapping: ids ticked in the grid.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [mapOpen, setMapOpen] = useState(false);
  const [mapBusy, setMapBusy] = useState(false);
  const [catTree, setCatTree] = useState<{ id?: string; name: string; parent_id?: string | null }[]>([]);
  // Jun 2026 — Image repair (see backend routes/product_images_repair.py).
  const [imgHealth, setImgHealth] = useState<{ needs_repair: number; failed: number; permanent: number } | null>(null);
  const [repairBusy, setRepairBusy] = useState(false);
  const [repairNote, setRepairNote] = useState("");
  // Debounced copy of `search` — what we actually send to the server.
  const [appliedSearch, setAppliedSearch] = useState("");

  const loadPage = useCallback(async (offset: number): Promise<{ items: Product[]; total: number; hasMore: boolean }> => {
    const params: Record<string, string> = { limit: String(PAGE_SIZE), offset: String(offset) };
    if (vendorFilter?.id) params.vendor_id = vendorFilter.id;
    if (appliedSearch.trim()) params.q = appliedSearch.trim();
    const r = await api.get<any>("/admin/products", { params });
    const data = r.data || {};
    const list: Product[] = Array.isArray(data) ? data : (data.items || []);
    return {
      items: list,
      total: Number(data.total ?? list.length),
      hasMore: Boolean(data.has_more ?? false),
    };
  }, [vendorFilter, appliedSearch]);

  const load = useCallback(async (toPage?: number) => {
    const target = typeof toPage === "number" ? toPage : pageRef.current;
    // Guard against an older response landing after a newer one (fast typing
    // in the search box fires overlapping requests).
    const reqId = ++loadSeq.current;
    try {
      const res = await loadPage(target * PAGE_SIZE);
      if (reqId !== loadSeq.current) return;
      // `interested_count` lives on the public list. Nov 2026 — ask for THIS
      // page's ids instead of the public first page, so the badge is right
      // beyond product 60 and the call stays tiny.
      let countMap = new Map<string, number>();
      try {
        if (res.items.length) {
          const pub = await api.get<any>("/products", {
            params: { ids: res.items.map((p) => p.id).join(",") },
          });
          const pubList: any[] = Array.isArray(pub.data) ? pub.data : (pub.data?.items || []);
          countMap = new Map(pubList.map((p: any) => [p.id, p.interested_count || 0]));
        }
      } catch { /* badge is cosmetic */ }
      setItems(res.items.map((p) => ({ ...p, interested_count: countMap.get(p.id) || 0 })));
      setTotal(res.total);
      pageRef.current = target;
      setPage(target);
    } catch (e) {
      if (reqId === loadSeq.current) notify("Error", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [loadPage]);


  const togglePick = useCallback((id: string) => {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Nov 2026 — one product card. Extracted so the list can virtualise rows.
  const renderCard = useCallback((item: Product) => {
        const oos = (item.stock || 0) === 0;
        const lowStock = (item.stock || 0) > 0 && (item.stock || 0) <= 5;
        const isPicked = picked.has(item.id);
        return (
          <TouchableOpacity
            key={item.id}
            activeOpacity={0.85}
            onPress={() => (picked.size > 0 ? togglePick(item.id) : setEditing(item))}
            onLongPress={() => togglePick(item.id)}
            delayLongPress={220}
            style={[styles.gridCard, isPicked && { borderColor: colors.primary, borderWidth: 2 }]}
            testID={`product-${item.id}`}
          >
            {/* Tick target — long-press any card to start selecting */}
            <TouchableOpacity
              onPress={() => togglePick(item.id)}
              style={styles.pickDot}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              testID={`product-pick-${item.id}`}
            >
              <Feather
                name={isPicked ? "check-circle" : "circle"}
                size={20}
                color={isPicked ? colors.primary : "rgba(255,255,255,0.9)"}
              />
            </TouchableOpacity>
            <View style={styles.gridImgWrap}>
              <ProductImage
                uri={item.image_url}
                name={item.name}
                style={styles.gridImg}
                containerStyle={{ width: "100%", height: "100%" }}
                resizeMode="cover"
                testID={`product-${item.id}-img`}
              />
              {item.is_published === false && (
                <View style={[styles.draftPillTop, item.review_status === "pending" && { backgroundColor: colors.warning }]}>
                  <Text style={styles.draftPillText}>
                    {item.review_status === "pending" ? "NEEDS APPROVAL" : "DRAFT"}
                  </Text>
                </View>
              )}
              {oos && (
                <View style={styles.oosOverlay} pointerEvents="none">
                  <Text style={styles.oosOverlayText}>SOLD OUT</Text>
                </View>
              )}
              {lowStock && !oos && (
                <View style={styles.lowStockPill}><Text style={styles.lowStockText}>Only {item.stock}</Text></View>
              )}
              {(item.interested_count || 0) > 0 && (
                <TouchableOpacity
                  style={styles.interestBadge}
                  onPress={() => setInterestedFor(item)}
                  testID={`product-${item.id}-interested`}
                >
                  <Feather name="users" size={10} color="#fff" />
                  <Text style={styles.interestBadgeText}>{item.interested_count}</Text>
                </TouchableOpacity>
              )}
            </View>
            <View style={styles.gridBody}>
              {item.category ? <Text style={styles.gridCat} numberOfLines={1}>{item.category}</Text> : null}
              <Text style={styles.gridName} numberOfLines={2}>{item.name}</Text>
              {/* Jul 2026 — Show which vendor owns this product so admins can spot ownership at-a-glance. */}
              {item.vendor_name ? (
                <View style={styles.vendorRow}>
                  <Feather name="briefcase" size={9} color={item.vendor_id ? colors.primary : colors.textMuted} />
                  <Text
                    style={[styles.vendorRowText, !item.vendor_id && { color: colors.textMuted, fontStyle: "italic" }]}
                    numberOfLines={1}
                  >
                    {item.vendor_name}
                  </Text>
                </View>
              ) : null}
              <View style={styles.gridFooter}>
                <Text style={styles.gridPrice}>{formatINR(item.price)}</Text>
                <Text style={styles.gridStock}>{item.stock ?? 0} in stock</Text>
              </View>
              <View style={styles.gridActions}>
                <TouchableOpacity onPress={() => setEditing(item)} style={styles.actionBtn} testID={`product-${item.id}-edit`}>
                  <Feather name="edit-2" size={13} color={colors.primary} />
                  <Text style={styles.actionBtnText}>Edit</Text>
                </TouchableOpacity>
                {/* Aug 2026 — Delete button removed on purpose.
                    Deleting a live product wiped it from vendor
                    stock too, causing downstream cart/order
                    damage.  Admins retain full EDIT rights and
                    can also toggle "Published" off to hide the
                    product without destroying vendor data. */}
              </View>
            </View>
          </TouchableOpacity>
        );
  }, [picked, togglePick, setEditing, setInterestedFor]);

  // Cards are laid out two per row (styles.gridCard is ~48% wide); the list
  // virtualises ROWS so the responsive layout is untouched.
  const cardRows = useMemo(() => {
    // Search happens on the SERVER (see `appliedSearch`), so the only
    // client-side narrowing left is the approval-queue toggle.
    const filtered = reviewOnly ? items.filter((p) => p.review_status === "pending") : items;
    const out: Product[][] = [];
    for (let i = 0; i < filtered.length; i += 2) out.push(filtered.slice(i, i + 2));
    return out;
  }, [items, reviewOnly]);

  const goToPage = useCallback((n: number) => {
    setLoading(true);
    setPicked(new Set());   // selections are per-page
    pageRef.current = n;
    load(n);
  }, [load]);

  // Bulk sub-category mapping (Nov 2026) — same one-tap ergonomics as
  // "Publish all", but for shelving many products at once.

  const openMapper = useCallback(async () => {
    setMapOpen(true);
    if (catTree.length) return;
    try {
      // Nov 2026 — shelving targets only. The Recharge tree is served by the
      // recharge flow, not the product catalogue, so a physical product must
      // never be shelved there.
      const { data } = await api.get<any>("/admin/shop-categories", {
        params: { exclude_recharge_root: "true" },
      });
      setCatTree(data?.items || []);
    } catch (e) {
      notify("Couldn't load categories", formatApiError(e));
    }
  }, [catTree.length]);

  const applyMapping = useCallback(async (category: string, subcategory: string) => {
    setMapBusy(true);
    try {
      const { data } = await api.post<any>("/admin/products/bulk-category", {
        product_ids: Array.from(picked),
        category,
        subcategory,
      });
      setMapOpen(false);
      setPicked(new Set());
      await load(pageRef.current);
      notify(
        "Products shelved",
        `${data.updated} product${data.updated === 1 ? "" : "s"} moved to ` +
        `${category}${subcategory ? ` → ${subcategory}` : ""}.`,
      );
    } catch (e) {
      notify("Mapping failed", formatApiError(e));
    } finally { setMapBusy(false); }
  }, [picked, load]);

  // Debounce the search box, then reload page 1 from the server.
  useEffect(() => {
    const t = setTimeout(() => setAppliedSearch(search), 350);
    return () => clearTimeout(t);
  }, [search]);
  // A new search / vendor filter changes the whole result set, so jump back to
  // page 1 and drop the ticks (they could point at rows no longer shown).
  useEffect(() => {
    setLoading(true);
    setPicked(new Set());
    pageRef.current = 0;
    load(0);
  }, [appliedSearch, vendorFilter]);  // eslint-disable-line react-hooks/exhaustive-deps

  const refreshImageHealth = useCallback(async () => {
    try {
      const r = await api.get<any>("/admin/products/image-health");
      setImgHealth({
        needs_repair: Number(r.data?.needs_repair || 0),
        failed: Number(r.data?.failed || 0),
        permanent: Number(r.data?.permanent || 0),
      });
    } catch { /* non-fatal */ }
  }, []);

  const runImageRepair = useCallback(async (retryFailed: boolean) => {
    setRepairBusy(true);
    setRepairNote("Downloading product photos into permanent storage…");
    try {
      const r = await api.post<any>("/admin/products/repair-images", { limit: 50, retry_failed: retryFailed });
      const d = r.data || {};
      const lines = [
        `✅ ${d.repaired || 0} product${(d.repaired || 0) === 1 ? "" : "s"} fixed`,
        d.partial ? `· ${d.partial} partly fixed` : "",
        d.failed ? `· ${d.failed} could not be fetched` : "",
        `· ${d.imported || 0} photo${(d.imported || 0) === 1 ? "" : "s"} stored`,
        d.images_failed ? `· ${d.images_failed} photo${d.images_failed === 1 ? "" : "s"} unavailable` : "",
        d.remaining ? `\n${d.remaining} product${d.remaining === 1 ? "" : "s"} still to go — tap again to continue.` : "\nNothing left to fix.",
      ].filter(Boolean);
      setRepairNote(lines.join(" "));
      await refreshImageHealth();
      await load();
    } catch (e) {
      setRepairNote("");
      Alert.alert("Image repair failed", formatApiError(e));
    } finally {
      setRepairBusy(false);
    }
  }, [refreshImageHealth, load]);

  // Dec 2026 — Silent auto-refresh so new vendor products & publish-toggle
  // changes appear without a manual pull-to-refresh.
  // Nov 2026 — `load` is re-created whenever the search or vendor filter
  // changes, which used to re-run this effect and fire a second, identical
  // fetch. Keeping it in a ref makes the effect depend on nothing.
  const loadRef = useRef(load);
  loadRef.current = load;
  const firstFocus = useRef(true);
  useFocusEffect(useCallback(() => {
    if (firstFocus.current) {
      // The mount effect already fetched page 1.
      firstFocus.current = false;
      refreshImageHealth();
    } else {
      loadRef.current();
      refreshImageHealth();
    }
    const iv = setInterval(() => {
      if (AppState.currentState !== "active") return;   // don't poll from the pocket
      loadRef.current();
    }, 15000);
    return () => clearInterval(iv);
  }, [refreshImageHealth]));

  const runBulkPublish = async () => {
    if (!bulkConfirm) return;
    const publish = bulkConfirm === "publish";
    setBulkBusy(true);
    try {
      const r = await api.post<any>("/admin/products/publish-all", {
        vendor_id: vendorFilter?.id || null,
        publish,
      });
      setBulkConfirm(null);
      await load();
      Alert.alert(
        publish ? "Published" : "Unpublished",
        `${r.data?.updated ?? 0} product${(r.data?.updated ?? 0) === 1 ? "" : "s"} updated.`,
      );
    } catch (e) {
      Alert.alert("Bulk action failed", formatApiError(e));
    } finally { setBulkBusy(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Products</Text>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <HelpButton onPress={() => setHelpOpen(true)} testID="products-help" />
          <TouchableOpacity onPress={() => setCreateOpen(true)} style={[styles.iconBtn, styles.iconBtnPrimary]} testID="product-new">
            <Feather name="plus" size={20} color={colors.primaryFg} />
          </TouchableOpacity>
        </View>
      </View>

      {/* In-app walkthrough — auto-opens on first visit, re-openable via ?
          button. Nov 2026 — "create your first product" is noise on a shop
          that already has a catalogue, so it only auto-opens once the first
          load has finished and the catalogue really is empty (an unfiltered
          one — a search with no hits isn't an empty shop). */}
      <HelpGuide
        id="products-v1"
        visible={(helpVisible && !loading && total === 0 && !appliedSearch.trim() && !vendorFilter) || helpOpen}
        title="How to create a product"
        subtitle="A quick 6-step tour. Tap anywhere outside to dismiss."
        steps={PRODUCT_GUIDE_STEPS}
        onClose={() => { helpClose(); setHelpOpen(false); }}
      />

      {loading ? (
        <View style={{ paddingHorizontal: spacing.screen, paddingTop: 6 }}>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
            {[...Array(6)].map((_, i) => <ProductCardSkeleton key={i} />)}
          </View>
        </View>
      ) : (
        <FlatList
          // Nov 2026 — VIRTUALISED: 250 image cards used to mount at once,
          // which stuttered (and could force-close) on low-end phones. Rows
          // are recycled now; the pager still decides which 250 are in play.
          data={cardRows}
          keyExtractor={(row: Product[]) => `row-${row[0]?.id}`}
          renderItem={({ item: row }: { item: Product[] }) => (
            <View style={styles.grid}>{row.map(renderCard)}</View>
          )}
          initialNumToRender={6}
          maxToRenderPerBatch={6}
          windowSize={7}
          removeClippedSubviews={Platform.OS !== "web"}
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          ListHeaderComponent={
            <>
          <FadeSlideIn triggerKey={`admprod-${refreshing ? "r" : "d"}`}>
          {/* Hero summary card */}
          <GradientCard variant="primary" style={{ marginBottom: 14, padding: 18 }}>
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>CATALOG</Text>
            <Text style={{ fontSize: 22, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.6 }}>
              {appliedSearch.trim()
                ? `${total.toLocaleString("en-IN")} match${total === 1 ? "" : "es"}`
                : `${total.toLocaleString("en-IN")} product${total === 1 ? "" : "s"} in catalogue`}
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              {appliedSearch.trim() ? `for “${appliedSearch.trim()}” · ` : ""}
              Page {page + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))} · showing {items.length.toLocaleString("en-IN")}
            </Text>
          </GradientCard>

          {/* Search */}
          <View style={styles.search}>
            <Feather name="search" size={16} color={colors.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              testID="products-search-input"
              placeholder="Search products, vendor, or category"
              placeholderTextColor={colors.textMuted}
              style={styles.searchInput}
            />
            {search ? (
              <TouchableOpacity onPress={() => setSearch("")}><Feather name="x-circle" size={16} color={colors.textMuted} /></TouchableOpacity>
            ) : null}
          </View>

          {/* Jul 2026 — Vendor filter chip.  Tap to open the vendor picker
              modal; the current filter shows as a coloured pill with an
              inline clear button. */}
          <TouchableOpacity
            style={[styles.vendorFilterChip, vendorFilter && styles.vendorFilterChipOn]}
            onPress={() => setVendorPickerOpen(true)}
            testID="products-vendor-filter-chip"
            activeOpacity={0.8}
          >
            <Feather name="briefcase" size={13} color={vendorFilter ? colors.primaryFg : colors.textMain} />
            <Text
              style={[styles.vendorFilterText, vendorFilter && { color: colors.primaryFg }]}
              numberOfLines={1}
            >
              {vendorFilter ? `Vendor: ${vendorFilter.name}` : "Filter by vendor"}
            </Text>
            {vendorFilter ? (
              <TouchableOpacity
                onPress={() => setVendorFilter(null)}
                hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                testID="products-vendor-filter-clear"
              >
                <Feather name="x-circle" size={14} color={colors.primaryFg} />
              </TouchableOpacity>
            ) : (
              <Feather name="chevron-down" size={13} color={colors.textMain} />
            )}
          </TouchableOpacity>

          {/* Jun 2026 — Bulk publish. Vendors upload 50-200 SKUs at a time;
              flipping each one by hand was the biggest admin time-sink.
              Scoped to the selected vendor when a filter is active. */}
          <View style={styles.bulkRow}>
            <TouchableOpacity
              style={[styles.bulkBtn, styles.bulkBtnPrimary]}
              onPress={() => setBulkConfirm("publish")}
              testID="products-publish-all"
              activeOpacity={0.85}
            >
              <Feather name="check-circle" size={13} color={colors.primaryFg} />
              <Text style={[styles.bulkBtnText, { color: colors.primaryFg }]} numberOfLines={1}>
                Publish all{vendorFilter ? " (vendor)" : ""}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.bulkBtn}
              onPress={() => setBulkConfirm("unpublish")}
              testID="products-unpublish-all"
              activeOpacity={0.85}
            >
              <Feather name="eye-off" size={13} color={colors.textMain} />
              <Text style={styles.bulkBtnText} numberOfLines={1}>Unpublish all</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.statsStrip}>
            <Stat label="Total" value={total.toLocaleString("en-IN")} />
            <Stat label="Loaded" value={String(items.length)} accent />
            {/* These three can only count what has been loaded, so they say
                "so far" until the last page is in — otherwise a 5,000-SKU
                catalogue looks like it has only 3 out-of-stock items. */}
            <Stat label="No stock (page)" value={String(items.filter(p => (p.stock || 0) === 0).length)} warn />
            <Stat label="Interest (page)" value={String(items.filter(p => (p.interested_count || 0) > 0).length)} />
            <Stat
              label="Approvals (page)"
              value={String(items.filter(p => p.review_status === "pending").length)}
              warn
            />
          </View>

          {/* Jun 2026 — Product photo health + repair.
              Catalogues imported before permanent image storage existed
              still point at third-party CDNs that have started refusing
              us, which is what makes cards go blank days after an import.
              This downloads a permanent copy of each one. */}
          {imgHealth && (imgHealth.needs_repair > 0 || imgHealth.failed > 0) ? (
            <View style={styles.repairCard} testID="image-repair-card">
              <View style={styles.repairHead}>
                <Feather name="image" size={15} color={colors.warning} />
                <Text style={styles.repairTitle}>
                  {imgHealth.needs_repair > 0
                    ? `${imgHealth.needs_repair.toLocaleString("en-IN")} product${imgHealth.needs_repair === 1 ? "" : "s"} still use outside photo links`
                    : `${imgHealth.failed.toLocaleString("en-IN")} product${imgHealth.failed === 1 ? "" : "s"} are missing their photo`}
                </Text>
              </View>
              <Text style={styles.repairBody}>
                {imgHealth.needs_repair > 0
                  ? "Those links can stop working without warning, which leaves blank squares in the shop. Storing our own copy fixes them permanently."
                  : "The source website refused or no longer has these images, so the shop shows a placeholder instead. Retry if the source is back, or add a photo to the product."}
                {imgHealth.needs_repair > 0 && imgHealth.failed
                  ? ` ${imgHealth.failed} could not be fetched last time.`
                  : ""}
              </Text>
              {repairNote ? <Text style={styles.repairNote}>{repairNote}</Text> : null}
              <View style={styles.repairBtnRow}>
                {imgHealth.needs_repair > 0 ? (
                  <TouchableOpacity
                    onPress={() => runImageRepair(false)}
                    disabled={repairBusy}
                    style={[styles.bulkBtn, styles.bulkBtnPrimary, repairBusy && { opacity: 0.6 }]}
                    testID="image-repair-run"
                  >
                    {repairBusy
                      ? <ActivityIndicator size="small" color={colors.primaryFg} />
                      : <Feather name="download-cloud" size={13} color={colors.primaryFg} />}
                    <Text style={[styles.bulkBtnText, { color: colors.primaryFg }]} numberOfLines={1}>
                      Fix product photos
                    </Text>
                  </TouchableOpacity>
                ) : null}
                {imgHealth.failed ? (
                  <TouchableOpacity
                    onPress={() => runImageRepair(true)}
                    disabled={repairBusy}
                    style={[
                      styles.bulkBtn,
                      imgHealth.needs_repair === 0 && styles.bulkBtnPrimary,
                      repairBusy && { opacity: 0.6 },
                    ]}
                    testID="image-repair-retry"
                  >
                    {repairBusy && imgHealth.needs_repair === 0
                      ? <ActivityIndicator size="small" color={colors.primaryFg} />
                      : <Feather name="refresh-cw" size={13} color={imgHealth.needs_repair === 0 ? colors.primaryFg : colors.textMain} />}
                    <Text
                      style={[styles.bulkBtnText, imgHealth.needs_repair === 0 && { color: colors.primaryFg }]}
                      numberOfLines={1}
                    >
                      Retry failed photos
                    </Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            </View>
          ) : null}

          {/* Jun-2026 — a seller's edit pulls a live product out of the shop
              until it is approved again. Surface that queue at the top. */}
          {items.filter(p => p.review_status === "pending").length > 0 ? (
            <TouchableOpacity
              onPress={() => setReviewOnly(v => !v)}
              style={styles.reviewBar}
              testID="products-review-filter"
            >
              <Feather name={reviewOnly ? "check-square" : "square"} size={16} color={colors.warning} />
              <Text style={styles.reviewBarText}>
                {items.filter(p => p.review_status === "pending").length} edited by sellers — hidden from the shop until you approve
              </Text>
            </TouchableOpacity>
          ) : null}

          {/* Nov 2026 — bulk sub-category mapping. Tick products below, then
              shelve them all in one tap (mirrors "Publish all"). */}
          {picked.size > 0 && !reviewOnly ? (
            <View style={styles.mapBar} testID="products-map-bar">
              <Feather name="layers" size={18} color={colors.primaryFg} />
              <Text style={styles.mapBarText}>
                {picked.size} selected on this page
              </Text>
              <TouchableOpacity onPress={() => setPicked(new Set())} style={{ padding: 8 }} testID="products-map-clear">
                <Feather name="x" size={18} color={colors.primaryFg} />
              </TouchableOpacity>
              <TouchableOpacity onPress={openMapper} style={styles.mapBarBtn} testID="products-map-open">
                <Text style={styles.mapBarBtnText}>Map to shelf</Text>
              </TouchableOpacity>
            </View>
          ) : null}

          {/* The product cards themselves are rendered by the
              virtualised list (see `renderItem` above). */}
          {cardRows.length === 0 ? (
            <Text style={styles.empty}>
              {search ? "No matches" : (vendorFilter ? `No products from ${vendorFilter.name} yet.` : "No products yet — tap the + to add one.")}
            </Text>
          ) : null}
          </FadeSlideIn>
            </>
          }
          ListFooterComponent={
            <>
          {/* Nov 2026 — numbered pages (250 per page). Replaces "Load more",
              which reset to the first page whenever the screen refocused. */}
          {!reviewOnly && total > PAGE_SIZE ? (
            <View style={styles.pager} testID="products-pager">
              <TouchableOpacity
                onPress={() => goToPage(page - 1)}
                disabled={page <= 0}
                style={[styles.pagerBtn, page <= 0 && { opacity: 0.35 }]}
                testID="products-page-prev"
              >
                <Feather name="chevron-left" size={18} color={colors.primary} />
              </TouchableOpacity>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: 6, paddingHorizontal: 6 }}
                style={{ flex: 1 }}
              >
                {Array.from({ length: Math.ceil(total / PAGE_SIZE) }).map((_, i) => (
                  <TouchableOpacity
                    key={i}
                    onPress={() => goToPage(i)}
                    style={[styles.pageChip, i === page && styles.pageChipActive]}
                    testID={`products-page-${i + 1}`}
                  >
                    <Text style={[styles.pageChipText, i === page && styles.pageChipTextActive]}>
                      {i + 1}
                    </Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <TouchableOpacity
                onPress={() => goToPage(page + 1)}
                disabled={(page + 1) * PAGE_SIZE >= total}
                style={[styles.pagerBtn, (page + 1) * PAGE_SIZE >= total && { opacity: 0.35 }]}
                testID="products-page-next"
              >
                <Feather name="chevron-right" size={18} color={colors.primary} />
              </TouchableOpacity>
            </View>
          ) : null}
          {items.length > 0 && !reviewOnly ? (
            <Text style={styles.endOfList} testID="products-end">
              Page {page + 1} of {Math.max(1, Math.ceil(total / PAGE_SIZE))} · showing{" "}
              {items.length.toLocaleString("en-IN")} of {total.toLocaleString("en-IN")} products
            </Text>
          ) : null}
            </>
          }
        />
      )}

      {/* Nov 2026 — shelf picker: every category with its sub-shelves nested,
          one tap to map every selected product. */}
      <Modal visible={mapOpen} transparent animationType="slide" onRequestClose={() => setMapOpen(false)}>
        <TouchableOpacity
          style={styles.bulkOverlay}
          activeOpacity={1}
          onPress={() => !mapBusy && setMapOpen(false)}
        >
          <TouchableOpacity activeOpacity={1} style={styles.mapSheet} onPress={() => {}}>
            <View style={styles.mapGrab} />
            <View style={{ paddingHorizontal: 16, paddingBottom: 10 }}>
              <Text style={{ fontSize: 17, fontWeight: "900", color: colors.textMain }}>
                Move {picked.size} product{picked.size === 1 ? "" : "s"} to…
              </Text>
              <Text style={{ fontSize: 12, color: colors.textMuted, marginTop: 3 }}>
                Tap a shelf. Sub-shelves are listed under their category.
              </Text>
            </View>
            {mapBusy ? (
              <View style={{ paddingVertical: 36, alignItems: "center" }}>
                <ActivityIndicator color={colors.primary} />
                <Text style={{ marginTop: 10, color: colors.textMuted, fontSize: 12.5 }}>Shelving…</Text>
              </View>
            ) : (
              <ScrollView style={{ maxHeight: 460 }} contentContainerStyle={{ paddingBottom: 28 }}>
                {catTree.filter((c) => !c.parent_id).map((root) => {
                  const subs = catTree.filter((c) => c.parent_id && c.parent_id === root.id);
                  return (
                    <View key={root.id || root.name}>
                      <TouchableOpacity
                        style={styles.mapRoot}
                        onPress={() => applyMapping(root.name, "")}
                        testID={`map-cat-${root.name}`}
                      >
                        <Feather name="folder" size={17} color={colors.primary} />
                        <Text style={styles.mapRootText}>{root.name}</Text>
                        <Feather name="chevron-right" size={16} color={colors.textMuted} />
                      </TouchableOpacity>
                      {subs.map((sub) => (
                        <TouchableOpacity
                          key={sub.id || sub.name}
                          style={styles.mapSub}
                          onPress={() => applyMapping(root.name, sub.name)}
                          testID={`map-sub-${sub.name}`}
                        >
                          <Feather name="corner-down-right" size={14} color={colors.textMuted} />
                          <Text style={styles.mapSubText}>{sub.name}</Text>
                          <Feather name="chevron-right" size={15} color={colors.border} />
                        </TouchableOpacity>
                      ))}
                    </View>
                  );
                })}
              </ScrollView>
            )}
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>

      <RichProductEditor
        visible={createOpen || !!editing}
        existing={editing as any}
        onClose={() => { setEditing(null); setCreateOpen(false); }}
        onSaved={async () => { setEditing(null); setCreateOpen(false); await load(); }}
        endpoints={{
          create: "/admin/products",
          update: (id: string) => `/admin/products/${id}`,
          detail: (id: string) => `/admin/products/${id}`,
        }}
      />

      <InterestedModal product={interestedFor} onClose={() => setInterestedFor(null)} />

      {/* Jul 2026 — Vendor picker modal for the products filter */}
      <VendorPickerModal
        visible={vendorPickerOpen}
        onClose={() => setVendorPickerOpen(false)}
        onPick={(v) => { setVendorFilter(v); setVendorPickerOpen(false); }}
        selectedId={vendorFilter?.id}
      />

      {/* Bulk publish confirm — a Modal (not Alert.alert, whose buttons are
          a no-op on RN-Web where the admin panel is used most). */}
      <Modal visible={!!bulkConfirm} transparent animationType="fade" onRequestClose={() => setBulkConfirm(null)}>
        <View style={styles.bulkOverlay}>
          <View style={styles.bulkCard}>
            <Text style={styles.bulkTitle}>
              {bulkConfirm === "publish" ? "Publish all products?" : "Unpublish all products?"}
            </Text>
            <Text style={styles.bulkBody}>
              {vendorFilter
                ? `This applies to every product from ${vendorFilter.name}.`
                : "This applies to EVERY product in the catalog, from all vendors."}
              {bulkConfirm === "publish"
                ? " They become visible to customers immediately."
                : " They are hidden from the shop immediately."}
            </Text>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 18 }}>
              <TouchableOpacity
                onPress={() => setBulkConfirm(null)}
                style={[styles.bulkModalBtn, { backgroundColor: colors.surfaceMuted }]}
                testID="bulk-publish-cancel"
              >
                <Text style={{ fontWeight: "700", color: colors.textMain }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={runBulkPublish}
                disabled={bulkBusy}
                style={[
                  styles.bulkModalBtn,
                  { backgroundColor: bulkConfirm === "publish" ? colors.primary : "#B91C1C", opacity: bulkBusy ? 0.6 : 1 },
                ]}
                testID="bulk-publish-confirm"
              >
                {bulkBusy
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={{ fontWeight: "800", color: "#fff" }}>{bulkConfirm === "publish" ? "Publish all" : "Unpublish all"}</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function VendorPickerModal({
  visible,
  onClose,
  onPick,
  selectedId,
}: {
  visible: boolean;
  onClose: () => void;
  onPick: (v: VendorLite | null) => void;
  selectedId?: string;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<VendorLite[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const params: Record<string, string> = {};
        if (q.trim()) params.q = q.trim();
        const r = await api.get<{ items: VendorLite[] }>("/admin/vendors", { params });
        if (!cancelled) setItems(r.data.items || []);
      } catch { /* ignore */ }
      finally { if (!cancelled) setLoading(false); }
    }, q ? 300 : 0);
    return () => { cancelled = true; clearTimeout(t); };
  }, [visible, q]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <TouchableOpacity style={vpStyles.overlay} activeOpacity={1} onPress={onClose}>
        <TouchableOpacity activeOpacity={1} style={vpStyles.sheet} onPress={() => {}}>
          <View style={vpStyles.handle} />
          <Text style={vpStyles.title}>Filter by vendor</Text>
          <Text style={vpStyles.subtitle}>All vendors listed below. Search by name, email, phone or pincode.</Text>

          <View style={vpStyles.search}>
            <Feather name="search" size={15} color={colors.textMuted} />
            <TextInput
              value={q}
              onChangeText={setQ}
              placeholder="Search vendor by name, email, phone, or pincode"
              placeholderTextColor={colors.textMuted}
              style={vpStyles.searchInput}
              autoFocus
              testID="vendor-picker-search"
            />
          </View>

          <TouchableOpacity
            onPress={() => onPick(null)}
            style={[vpStyles.row, !selectedId && vpStyles.rowOn]}
            testID="vendor-picker-all"
          >
            <View style={[vpStyles.avatar, { backgroundColor: colors.brand100 }]}>
              <Feather name="grid" size={16} color={colors.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={vpStyles.rowName}>All vendors</Text>
              <Text style={vpStyles.rowSub}>Clear the filter</Text>
            </View>
            {!selectedId ? <Feather name="check" size={18} color={colors.primary} /> : null}
          </TouchableOpacity>

          <ScrollView
            style={{ maxHeight: 360 }}
            contentContainerStyle={{ paddingBottom: 12 }}
            keyboardShouldPersistTaps="handled"
          >
            {loading ? (
              <View style={{ padding: 24, alignItems: "center" }}>
                <ActivityIndicator color={colors.primary} />
              </View>
            ) : items.length === 0 ? (
              <Text style={vpStyles.empty}>No vendors match.</Text>
            ) : (
              items.map((v) => {
                const on = selectedId === v.id;
                const status = (v.status || (v.is_approved ? "approved" : "pending")).toLowerCase();
                const statusColor = status === "approved" ? "#16A34A" : status === "rejected" ? "#DC2626" : "#F59E0B";
                return (
                  <TouchableOpacity
                    key={v.id}
                    onPress={() => onPick(v)}
                    style={[vpStyles.row, on && vpStyles.rowOn]}
                    testID={`vendor-picker-${v.id}`}
                  >
                    <View style={[vpStyles.avatar, { backgroundColor: colors.brand100 }]}>
                      <Text style={{ color: colors.primary, fontWeight: "900", fontSize: 14 }}>
                        {(v.name || "?")[0].toUpperCase()}
                      </Text>
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                        <Text style={vpStyles.rowName} numberOfLines={1}>{v.name}</Text>
                        <View style={{ paddingHorizontal: 6, paddingVertical: 1, borderRadius: 999, backgroundColor: statusColor + "22" }}>
                          <Text style={{ fontSize: 9, fontWeight: "900", color: statusColor, letterSpacing: 0.5 }}>{status.toUpperCase()}</Text>
                        </View>
                      </View>
                      <Text style={vpStyles.rowSub} numberOfLines={1}>
                        {v.email}{v.store_pincode ? ` · PIN ${v.store_pincode}` : ""}
                      </Text>
                    </View>
                    {on ? <Feather name="check" size={18} color={colors.primary} /> : null}
                  </TouchableOpacity>
                );
              })
            )}
          </ScrollView>

          <TouchableOpacity onPress={onClose} style={vpStyles.close}>
            <Text style={vpStyles.closeText}>Close</Text>
          </TouchableOpacity>
        </TouchableOpacity>
      </TouchableOpacity>
    </Modal>
  );
}

const vpStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 22, paddingBottom: 34 },
  handle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  title: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  subtitle: { fontSize: 12, color: colors.textMuted, marginTop: 2, marginBottom: 14 },
  search: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: 12,
    paddingHorizontal: 12, height: 42, marginBottom: 12,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.textMain, paddingVertical: 0 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: 12, paddingVertical: 12,
    borderRadius: 12, marginBottom: 6,
    borderWidth: 1, borderColor: "transparent",
  },
  rowOn: { backgroundColor: colors.brand100, borderColor: colors.primary },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  rowName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  rowSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  empty: { padding: 24, textAlign: "center", color: colors.textMuted, fontSize: 12 },
  close: {
    marginTop: 8, paddingVertical: 12,
    borderRadius: 12, alignItems: "center",
    backgroundColor: colors.surfaceMuted,
  },
  closeText: { color: colors.textMain, fontWeight: "800", fontSize: 14 },
});

function Stat({ label, value, accent, warn }: { label: string; value: string; accent?: boolean; warn?: boolean }) {
  return (
    <View style={styles.statCell}>
      <Text style={[styles.statValue, accent && { color: colors.primary }, warn && { color: "#B3261E" }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function InterestedModal({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const [users, setUsers] = useState<InterestedUser[]>([]);
  const [loading, setLoading] = useState(false);

  useState(() => {});

  useFocusEffect(useCallback(() => {
    if (!product) return;
    setLoading(true);
    api.get<{ users: InterestedUser[]; interested_count: number }>(`/products/${product.id}/interested`)
      .then((r) => setUsers(r.data.users || []))
      .catch((e) => Alert.alert("Couldn't load", formatApiError(e)))
      .finally(() => setLoading(false));
  }, [product]));

  return (
    <Modal visible={!!product} transparent animationType="slide" onRequestClose={onClose}>
      <View style={modalStyles.overlay}>
        <View style={modalStyles.sheet}>
          <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <Text style={modalStyles.title}>Interested customers</Text>
            <TouchableOpacity onPress={onClose}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
          </View>
          <Text style={{ fontSize: 12, color: colors.textMuted, marginBottom: 12 }}>
            {product?.name} · {users.length} customer{users.length === 1 ? "" : "s"} waiting
          </Text>
          {loading ? (
            <ActivityIndicator color={colors.primary} style={{ marginVertical: 24 }} />
          ) : users.length === 0 ? (
            <Text style={{ textAlign: "center", color: colors.textMuted, paddingVertical: 24 }}>
              No customers have flagged interest yet.
            </Text>
          ) : (
            <ScrollView style={{ maxHeight: 420 }}>
              {users.map((u) => (
                <View key={u.id} style={modalStyles.userRow}>
                  <View style={modalStyles.userAvatar}>
                    <Text style={modalStyles.userAvatarText}>{(u.name || "?").charAt(0).toUpperCase()}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={modalStyles.userName}>{u.name || "Customer"}</Text>
                    <Text style={modalStyles.userMeta}>{u.email}{u.phone ? ` · ${u.phone}` : ""}</Text>
                  </View>
                </View>
              ))}
            </ScrollView>
          )}
          <TouchableOpacity onPress={onClose} style={[modalStyles.btn, { backgroundColor: colors.primary, marginTop: 12 }]}>
            <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Close</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}


const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  iconBtnPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },

  // Search
  search: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, paddingHorizontal: 14, height: 44, marginBottom: 12 },
  searchInput: { flex: 1, fontSize: 14, color: colors.textMain, paddingVertical: 0 },

  // Stats strip
  statsStrip: { flexDirection: "row", backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 12, marginBottom: 14, gap: 8 },
  statCell: { flex: 1, alignItems: "center" },
  statValue: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  statLabel: { fontSize: 9, fontWeight: "700", color: colors.textMuted, marginTop: 2, textTransform: "uppercase", letterSpacing: 0.5 },

  // Grid
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  gridCard: {
    flexBasis: "48%", flexGrow: 1,
    backgroundColor: colors.surface, borderRadius: 18, overflow: "hidden",
    borderWidth: 1, borderColor: colors.border,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 2 },
      default: {},
    }),
  },
  gridImgWrap: { position: "relative", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  gridImg: { width: "100%", height: "100%" },
  gridBody: { padding: 12, gap: 4 },
  gridCat: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.6, textTransform: "uppercase" },
  gridName: { fontSize: 13, fontWeight: "700", color: colors.textMain, lineHeight: 17, minHeight: 34 },
  gridFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  gridPrice: { fontSize: 15, fontWeight: "800", color: colors.primary, letterSpacing: -0.3 },
  gridStock: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  gridActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  actionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingVertical: 8, borderRadius: 10, borderWidth: 1, borderColor: colors.primary },
  actionBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  actionBtnDanger: { flex: 0, width: 36, paddingVertical: 8, backgroundColor: "#FCE9E5", borderColor: "#FCE9E5" },

  // Pills + overlays
  draftPill: { backgroundColor: "#FFF4E5", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  draftPillTop: { position: "absolute", top: 8, left: 8, backgroundColor: "#FFF4E5", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  draftPillText: { color: "#7A4A0E", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  oosOverlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.5)" },
  oosOverlayText: { fontSize: 13, fontWeight: "900", color: colors.textMain, letterSpacing: 2, backgroundColor: "rgba(255,255,255,0.85)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4, overflow: "hidden" },
  lowStockPill: { position: "absolute", top: 8, left: 8, paddingVertical: 4, paddingHorizontal: 8, backgroundColor: "#F59E0B", borderRadius: 999 },
  lowStockText: { fontSize: 9, fontWeight: "800", color: "#fff", letterSpacing: 0.4 },
  interestBadge: { position: "absolute", top: 8, right: 8, flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 3, paddingHorizontal: 8, backgroundColor: colors.primary, borderRadius: 999 },
  interestBadgeText: { fontSize: 10, fontWeight: "800", color: "#fff" },

  // Legacy (kept for backward compatibility, not used in new gallery)
  card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, marginBottom: 10 },
  thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  cardName: { fontSize: 14, fontWeight: "700", color: colors.textMain, flex: 1 },
  cardPrice: { fontSize: 14, fontWeight: "800", color: colors.primary, marginTop: 2 },
  metaRow: { flexDirection: "row", gap: 10, marginTop: 6 },
  editBtn: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },
  deleteBtn: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", backgroundColor: "#FCE9E5" },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },

  reviewBar: {
    flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12,
    paddingHorizontal: 14, paddingVertical: 12, borderRadius: radii.card,
    backgroundColor: "#FFF7E6", borderWidth: 1, borderColor: colors.warning,
  },
  reviewBarText: { flex: 1, fontSize: 12, fontWeight: "800", color: "#8A5A00", lineHeight: 17 },

  // Jul 2026 — Vendor filter chip + row
  vendorFilterChip: {    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 14, paddingVertical: 10,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: 12,
  },
  vendorFilterChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  vendorFilterText: { fontSize: 13, fontWeight: "700", color: colors.textMain, flex: 1 },
  vendorRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  vendorRowText: { fontSize: 10, fontWeight: "700", color: colors.primary, flexShrink: 1 },

  // Jun 2026 — Bulk publish controls
  bulkRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  bulkBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 11, paddingHorizontal: 10, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    minHeight: 44,
  },
  bulkBtnPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  bulkBtnText: { fontSize: 12, fontWeight: "800", color: colors.textMain },

  // Jun 2026 — Photo health / repair card + pagination footer
  repairCard: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.warning, padding: 14, marginBottom: 12,
  },
  repairHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  repairTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain, flexShrink: 1 },
  repairBody: { fontSize: 12, color: colors.textMuted, lineHeight: 18, marginBottom: 10 },
  repairNote: { fontSize: 12, color: colors.textMain, lineHeight: 18, marginBottom: 10, fontWeight: "600" },
  repairBtnRow: { flexDirection: "row", gap: 8 },
  loadMoreBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 4, marginBottom: 12, paddingVertical: 14, borderRadius: radii.button,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, minHeight: 48,
  },
  loadMoreText: { fontSize: 13, fontWeight: "800", color: colors.primary },
  // Numbered pager (Nov 2026)
  pager: {
    flexDirection: "row", alignItems: "center", marginTop: 4, marginBottom: 6,
    backgroundColor: colors.surface, borderRadius: radii.button,
    borderWidth: 1, borderColor: colors.border, paddingVertical: 6, paddingHorizontal: 4,
  },
  pagerBtn: {
    width: 44, height: 44, borderRadius: radii.button,
    alignItems: "center", justifyContent: "center",
  },
  pageChip: {
    minWidth: 44, height: 44, paddingHorizontal: 12, borderRadius: radii.button,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  pageChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pageChipText: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  pageChipTextActive: { color: colors.primaryFg },
  // Bulk sub-category mapping bar + sheet
  mapBar: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.primary, borderRadius: radii.card,
    paddingVertical: 12, paddingHorizontal: 14, marginBottom: 10, minHeight: 48,
  },
  mapBarText: { flex: 1, color: colors.primaryFg, fontSize: 13, fontWeight: "800" },
  mapBarBtn: {
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: radii.button,
    backgroundColor: colors.primaryFg, minHeight: 40, justifyContent: "center",
  },
  mapBarBtnText: { color: colors.primary, fontSize: 12.5, fontWeight: "900" },
  mapSheet: {
    position: "absolute", left: 0, right: 0, bottom: 0, maxHeight: "82%",
    backgroundColor: colors.background,
    borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingTop: 10,
  },
  mapGrab: {
    alignSelf: "center", width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginBottom: 10,
  },
  mapRoot: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 14, paddingHorizontal: 16,
    borderBottomWidth: 1, borderBottomColor: colors.border, minHeight: 52,
  },
  mapRootText: { flex: 1, fontSize: 14.5, fontWeight: "800", color: colors.textMain },
  mapSub: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 12, paddingLeft: 36, paddingRight: 16,
    borderBottomWidth: 1, borderBottomColor: colors.surfaceMuted, minHeight: 48,
  },
  mapSubText: { flex: 1, fontSize: 13.5, fontWeight: "600", color: colors.textMuted },
  tickCell: { width: 30, alignItems: "center", justifyContent: "center" },
  pickDot: {
    position: "absolute", top: 6, left: 6, zIndex: 5,
    width: 30, height: 30, borderRadius: 15,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  endOfList: { textAlign: "center", fontSize: 11.5, color: colors.textMuted, paddingVertical: 14 },
  bulkOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "center", padding: 24 },
  bulkCard: { backgroundColor: colors.surface, borderRadius: 18, padding: 20 },
  bulkTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  bulkBody: { fontSize: 13, color: colors.textMuted, marginTop: 8, lineHeight: 19 },
  bulkModalBtn: { flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: "center", justifyContent: "center", minHeight: 46 },
});

const modalStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 12, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain },
  imagePick: { height: 160, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted, overflow: "hidden", alignItems: "center", justifyContent: "center" },
  imagePickImg: { width: "100%", height: "100%" },
  imagePickPlaceholder: { alignItems: "center", justifyContent: "center" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 16, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  switchTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  switchSub: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  btn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },

  // Interested users list
  userRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  userAvatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  userAvatarText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  userName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  userMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
});
