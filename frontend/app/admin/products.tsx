import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, ScrollView, Switch, Image, Platform, AppState } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError, resolveImageUrl } from "../../src/api";
import { FadeSlideIn, ProductCardSkeleton } from "../../src/anim";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { HelpGuide, HelpButton, useFirstVisitGuide, GuideStep } from "../../src/help-guide";
import { RichProductEditor } from "../../src/rich-product-editor";

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
  // Jul 2026 — Vendor filter: admin can narrow products by vendor.
  const [vendorFilter, setVendorFilter] = useState<VendorLite | null>(null);
  const [vendorPickerOpen, setVendorPickerOpen] = useState(false);
  const [interestedFor, setInterestedFor] = useState<Product | null>(null);
  // Jun 2026 — bulk publish / unpublish (whole catalog or one vendor).
  const [bulkConfirm, setBulkConfirm] = useState<null | "publish" | "unpublish">(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = { limit: "200" };
      if (vendorFilter?.id) params.vendor_id = vendorFilter.id;
      // /admin/products doesn't include interested_count yet; fetch from public
      // /products too and merge for the count display. Admin keeps full access
      // (incl. unpublished items via /admin/products).
      const [admin, pub] = await Promise.all([
        api.get<any>("/admin/products", { params }),
        api.get<any>("/products").catch(() => ({ data: [] })),
      ]);
      // Jun 2026 — /admin/products now returns { items, total, ... }.
      // Legacy fallback still handles the old array shape.
      const adminList: Product[] = Array.isArray(admin.data)
        ? admin.data
        : (admin.data?.items || []);
      const pubList: any[] = Array.isArray(pub.data) ? pub.data : (pub.data?.items || []);
      const countMap = new Map<string, number>();
      pubList.forEach((p: any) => countMap.set(p.id, p.interested_count || 0));
      setItems(adminList.map((p) => ({ ...p, interested_count: countMap.get(p.id) || 0 })));
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [vendorFilter]);

  useFocusEffect(useCallback(() => {
    load();
    // Dec 2026 — Silent auto-refresh every 15 s so new vendor products
    // & publish-toggle changes appear without a manual pull-to-refresh.
    // Interval is cleared on blur (useFocusEffect cleanup runs).
    const iv = setInterval(() => {
      if (AppState.currentState !== "active") return;   // don't poll from the pocket
      load();
    }, 15000);
    return () => clearInterval(iv);
  }, [load]));

  const onDelete = (p: Product) => {
    Alert.alert("Delete product?", `"${p.name}" will be removed permanently and from all open carts.`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive", onPress: async () => {
          try {
            await api.delete(`/admin/products/${p.id}`);
            await load();
          } catch (e) {
            Alert.alert("Delete failed", formatApiError(e));
          }
        },
      },
    ]);
  };

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

      {/* In-app walkthrough — auto-opens on first visit, re-openable via ? button */}
      <HelpGuide
        id="products-v1"
        visible={helpVisible || helpOpen}
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
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          <FadeSlideIn triggerKey={`admprod-${refreshing ? "r" : "d"}`}>
          {/* Hero summary card */}
          <GradientCard variant="primary" style={{ marginBottom: 14, padding: 18 }}>
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>CATALOG</Text>
            <Text style={{ fontSize: 22, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.6 }}>
              {items.length} product{items.length === 1 ? "" : "s"} live
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              {items.filter(p => (p.stock || 0) === 0).length} sold-out · {items.filter(p => (p.interested_count || 0) > 0).length} with waitlist
            </Text>
          </GradientCard>

          {/* Search */}
          <View style={styles.search}>
            <Feather name="search" size={16} color={colors.textMuted} />
            <TextInput
              value={search}
              onChangeText={setSearch}
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
            <Stat label="Total" value={String(items.length)} />
            <Stat label="Live" value={String(items.filter(p => p.is_published !== false).length)} accent />
            <Stat label="Out of stock" value={String(items.filter(p => (p.stock || 0) === 0).length)} warn />
            <Stat label="With interest" value={String(items.filter(p => (p.interested_count || 0) > 0).length)} />
          </View>

          {/* Grid */}
          {(() => {
            const q = search.trim().toLowerCase();
            const filtered = q ? items.filter(p =>
              p.name.toLowerCase().includes(q)
              || (p.category || "").toLowerCase().includes(q)
              || (p.vendor_name || "").toLowerCase().includes(q)
              || (p.vendor_email || "").toLowerCase().includes(q)
            ) : items;
            if (filtered.length === 0) {
              return <Text style={styles.empty}>{search ? "No matches" : (vendorFilter ? `No products from ${vendorFilter.name} yet.` : "No products yet — tap the + to add one.")}</Text>;
            }
            return (
              <View style={styles.grid}>
                {filtered.map((item) => {
                  const oos = (item.stock || 0) === 0;
                  const lowStock = (item.stock || 0) > 0 && (item.stock || 0) <= 5;
                  return (
                    <TouchableOpacity
                      key={item.id}
                      activeOpacity={0.85}
                      onPress={() => setEditing(item)}
                      style={styles.gridCard}
                      testID={`product-${item.id}`}
                    >
                      <View style={styles.gridImgWrap}>
                        {item.image_url
                          ? <Image source={{ uri: resolveImageUrl(item.image_url) }} style={styles.gridImg} />
                          : <View style={[styles.gridImg, { backgroundColor: colors.surfaceMuted }]} />}
                        {item.is_published === false && (
                          <View style={styles.draftPillTop}><Text style={styles.draftPillText}>DRAFT</Text></View>
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
                })}
              </View>
            );
          })()}
          </FadeSlideIn>
        </ScrollView>
      )}

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

const sectionStyles = StyleSheet.create({
  wrap: {
    marginBottom: 10,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  head: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14 },
  headIcon: {
    width: 32, height: 32, borderRadius: 10,
    backgroundColor: colors.primary + "12",
    alignItems: "center", justifyContent: "center",
  },
  headTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  headSummary: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  body: { paddingHorizontal: 14, paddingBottom: 14, paddingTop: 4 },

  // Sub-feature rows
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 8, paddingHorizontal: 10,
    backgroundColor: colors.surfaceMuted, borderRadius: 10, marginTop: 6,
  },
  rowText: { flex: 1, fontSize: 13, color: colors.textMain },
  addBtn: {
    width: 44, height: 44, borderRadius: 12,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },

  // Outline / mini buttons
  outlineBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 10,
    borderWidth: 1, borderColor: colors.primary,
    backgroundColor: colors.primary + "08",
  },
  outlineBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  smallDangerBtn: {
    width: 44, height: 44, borderRadius: 10,
    backgroundColor: "#FCE9E5", alignItems: "center", justifyContent: "center",
  },

  // Style toolbar (bold/align/font-size)
  toolRow: { flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" },
  toolBtn: {
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface, minWidth: 36, alignItems: "center", justifyContent: "center",
  },
  toolBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },

  // Gallery
  galleryGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  galleryItem: { width: 72, height: 72, borderRadius: 10, overflow: "hidden", position: "relative" },
  galleryImg: { width: "100%", height: "100%" },
  galleryRemove: {
    position: "absolute", top: 4, right: 4,
    width: 20, height: 20, borderRadius: 10,
    backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center",
  },
  galleryAdd: {
    width: 72, height: 72, borderRadius: 10,
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.primary,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.primary + "08",
  },

  // Spec tabs
  specTabCard: {
    backgroundColor: colors.surfaceMuted, borderRadius: 12,
    padding: 10, marginBottom: 8,
  },

  // What's in the box
  boxItemRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6,
  },
  boxThumb: { width: 44, height: 44, borderRadius: 10, overflow: "hidden" },
});
