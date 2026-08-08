import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, ScrollView, Switch, Image, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError, resolveImageUrl } from "../../src/api";
import { FadeSlideIn, ListRowSkeleton, ProductCardSkeleton } from "../../src/anim";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { HelpGuide, HelpButton, useFirstVisitGuide, GuideStep } from "../../src/help-guide";
import { RichProductEditor } from "../../src/rich-product-editor";
import { ProductCategoryPicker } from "../../src/product-category-picker";

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

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = {};
      if (vendorFilter?.id) params.vendor_id = vendorFilter.id;
      // /admin/products doesn't include interested_count yet; fetch from public
      // /products too and merge for the count display. Admin keeps full access
      // (incl. unpublished items via /admin/products).
      const [admin, pub] = await Promise.all([
        api.get<Product[]>("/admin/products", { params }),
        api.get<any>("/products").catch(() => ({ data: [] })),
      ]);
      const pubList: any[] = Array.isArray(pub.data) ? pub.data : (pub.data?.items || []);
      const countMap = new Map<string, number>();
      pubList.forEach((p: any) => countMap.set(p.id, p.interested_count || 0));
      setItems(admin.data.map((p) => ({ ...p, interested_count: countMap.get(p.id) || 0 })));
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [vendorFilter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

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

          {/* Stats strip */}
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

function Meta({ icon, text }: { icon: any; text: string }) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <Feather name={icon} size={11} color={colors.textMuted} />
      <Text style={{ fontSize: 11, color: colors.textMuted }}>{text}</Text>
    </View>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   ProductModal — rich Amazon/Flipkart-style product editor.
   Collapsible sections:
     1. Basics              (name, price, stock, category, description, publish)
     2. Brand & Sub-features
     3. Gallery             (cover + up to 10 additional images)
     4. Styled Summaries    (price / protection / warranty / delivery)
     5. Key Attributes      (brand, OS, RAM, CPU, storage + extras)
     6. Specification Tabs  (named tabs with label/value rows)
     7. What's in the Box   (named items with thumbnails)
   ──────────────────────────────────────────────────────────────────────────── */

type StyledText = { text?: string; bold?: boolean; font_size?: number | null; align?: "left" | "center" | "right" };
type SpecRow = { label: string; value: string };
type SpecTab = { name: string; rows: SpecRow[] };
type BoxItem = { name: string; image_data_url: string };

const emptyStyled = (): StyledText => ({ text: "", bold: false, font_size: null, align: "left" });

async function pickAndCompressImage(opts?: { aspect?: [number, number]; width?: number }) {
  // Smart-fitter delegate — product images centre-crop to the 1:1 spec
  // (800×800). See /src/image-fitter.ts for the catalogue of per-target
  // aspect ratios used across the app.
  const { pickAndFitImage } = await import("../../src/image-fitter");
  void opts;
  return await pickAndFitImage("product_image");
}

function Section({ title, icon, summary, defaultOpen, children, testID }: {
  title: string; icon: any; summary?: string; defaultOpen?: boolean; children: React.ReactNode; testID?: string;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <View style={sectionStyles.wrap}>
      <TouchableOpacity onPress={() => setOpen(!open)} style={sectionStyles.head} activeOpacity={0.7} testID={testID}>
        <View style={sectionStyles.headIcon}><Feather name={icon} size={16} color={colors.primary} /></View>
        <View style={{ flex: 1 }}>
          <Text style={sectionStyles.headTitle}>{title}</Text>
          {summary ? <Text style={sectionStyles.headSummary} numberOfLines={1}>{summary}</Text> : null}
        </View>
        <Feather name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
      </TouchableOpacity>
      {open ? <View style={sectionStyles.body}>{children}</View> : null}
    </View>
  );
}

function StyledTextEditor({ value, onChange, placeholder, testID }: {
  value: StyledText; onChange: (next: StyledText) => void; placeholder?: string; testID?: string;
}) {
  return (
    <View>
      <TextInput
        value={value.text || ""}
        onChangeText={(t) => onChange({ ...value, text: t })}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        multiline
        style={[modalStyles.input, { minHeight: 60, paddingTop: 12 }]}
        testID={testID}
      />
      <View style={sectionStyles.toolRow}>
        <TouchableOpacity
          onPress={() => onChange({ ...value, bold: !value.bold })}
          style={[sectionStyles.toolBtn, value.bold && sectionStyles.toolBtnActive]}
        >
          <Feather name="bold" size={13} color={value.bold ? colors.primaryFg : colors.textMain} />
        </TouchableOpacity>
        {(["left", "center", "right"] as const).map((al) => (
          <TouchableOpacity
            key={al}
            onPress={() => onChange({ ...value, align: al })}
            style={[sectionStyles.toolBtn, value.align === al && sectionStyles.toolBtnActive]}
          >
            <Feather name={al === "left" ? "align-left" : al === "center" ? "align-center" : "align-right"} size={13} color={value.align === al ? colors.primaryFg : colors.textMain} />
          </TouchableOpacity>
        ))}
        {[12, 14, 16, 18, 22].map((sz) => (
          <TouchableOpacity
            key={sz}
            onPress={() => onChange({ ...value, font_size: value.font_size === sz ? null : sz })}
            style={[sectionStyles.toolBtn, value.font_size === sz && sectionStyles.toolBtnActive, { paddingHorizontal: 8 }]}
          >
            <Text style={{ fontSize: 10, fontWeight: "700", color: value.font_size === sz ? colors.primaryFg : colors.textMain }}>{sz}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

function ProductModal({ visible, existing, onClose, onSaved }: { visible: boolean; existing: Product | null; onClose: () => void; onSaved: () => void }) {
  // ── Basics ──
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("100");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [published, setPublished] = useState(true);
  // ── Brand + sub-features ──
  const [brand, setBrand] = useState("");
  const [subFeatures, setSubFeatures] = useState<string[]>([]);
  const [newSubFeature, setNewSubFeature] = useState("");
  // ── Gallery ──
  const [galleryImages, setGalleryImages] = useState<string[]>([]);
  // ── Styled summaries ──
  const [priceSummary, setPriceSummary] = useState<StyledText>(emptyStyled());
  const [protectionSummary, setProtectionSummary] = useState<StyledText>(emptyStyled());
  const [warrantySummary, setWarrantySummary] = useState<StyledText>(emptyStyled());
  const [deliverySummary, setDeliverySummary] = useState<StyledText>(emptyStyled());
  // ── Attributes ──
  const [attrsBrand, setAttrsBrand] = useState("");
  const [attrsOs, setAttrsOs] = useState("");
  const [attrsRam, setAttrsRam] = useState("");
  const [attrsCpuModel, setAttrsCpuModel] = useState("");
  const [attrsCpuSpeed, setAttrsCpuSpeed] = useState("");
  const [attrsStorage, setAttrsStorage] = useState("");
  const [extraAttrs, setExtraAttrs] = useState<{ key: string; value: string }[]>([]);
  // ── Spec Tabs ──
  const [specTabs, setSpecTabs] = useState<SpecTab[]>([]);
  // ── What's in the box ──
  const [whatsInBox, setWhatsInBox] = useState<BoxItem[]>([]);

  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);

  // Hydrate when modal opens with a different product (or for create)
  useEffect(() => {
    if (!visible) return;
    setName(existing?.name || "");
    setPrice(existing?.price ? String(existing.price) : "");
    setStock(existing?.stock != null ? String(existing.stock) : "100");
    setDescription(existing?.description || "");
    setCategory(existing?.category || "");
    setImageUrl(existing?.image_url || "");
    setPublished(existing?.is_published !== false);
    const e = (existing || {}) as any;
    setBrand(e.brand || "");
    setSubFeatures(Array.isArray(e.sub_features) ? e.sub_features : []);
    setGalleryImages(Array.isArray(e.images) ? e.images : []);
    setPriceSummary(e.price_summary || emptyStyled());
    setProtectionSummary(e.protection_summary || emptyStyled());
    setWarrantySummary(e.warranty_summary || emptyStyled());
    setDeliverySummary(e.delivery_summary || emptyStyled());
    setAttrsBrand(e.attrs_brand || "");
    setAttrsOs(e.attrs_os || "");
    setAttrsRam(e.attrs_ram || "");
    setAttrsCpuModel(e.attrs_cpu_model || "");
    setAttrsCpuSpeed(e.attrs_cpu_speed || "");
    setAttrsStorage(e.attrs_storage || "");
    setExtraAttrs(Object.entries(e.extra_attrs || {}).map(([k, v]) => ({ key: k, value: String(v) })));
    setSpecTabs(Array.isArray(e.spec_tabs) ? e.spec_tabs.map((t: any) => ({ name: t.name || "", rows: Array.isArray(t.rows) ? t.rows : [] })) : []);
    setWhatsInBox(Array.isArray(e.whats_in_box) ? e.whats_in_box : []);
    setNewSubFeature("");
  }, [visible, existing?.id]);

  const onPickCover = async () => {
    setPicking(true);
    try {
      const data = await pickAndCompressImage({ aspect: [4, 3], width: 900 });
      if (data) setImageUrl(data);
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    } finally { setPicking(false); }
  };

  const onAddGalleryImage = async () => {
    if (galleryImages.length >= 10) {
      Alert.alert("Limit reached", "You can upload up to 10 gallery images.");
      return;
    }
    try {
      const data = await pickAndCompressImage({ aspect: [1, 1], width: 1000 });
      if (data) setGalleryImages([...galleryImages, data]);
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    }
  };

  const onAddSubFeature = () => {
    const t = newSubFeature.trim();
    if (!t) return;
    setSubFeatures([...subFeatures, t]);
    setNewSubFeature("");
  };

  const onAddExtraAttr = () => setExtraAttrs([...extraAttrs, { key: "", value: "" }]);

  const onAddSpecTab = () => setSpecTabs([...specTabs, { name: `Tab ${specTabs.length + 1}`, rows: [] }]);
  const onAddSpecRow = (idx: number) => {
    const next = [...specTabs];
    next[idx] = { ...next[idx], rows: [...next[idx].rows, { label: "", value: "" }] };
    setSpecTabs(next);
  };

  const onAddBoxItem = async () => {
    try {
      const data = await pickAndCompressImage({ aspect: [1, 1], width: 400 });
      setWhatsInBox([...whatsInBox, { name: "", image_data_url: data || "" }]);
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    }
  };

  const onSubmit = async () => {
    const priceN = Number(price);
    const stockN = Number(stock);
    if (!name.trim() || isNaN(priceN) || priceN < 0) {
      Alert.alert("Missing fields", "Name and a valid price are required.");
      return;
    }
    if (!imageUrl) {
      Alert.alert("Cover image required", "Please add a product cover image.");
      return;
    }
    setSaving(true);
    try {
      const extras: Record<string, string> = {};
      extraAttrs.forEach((e) => { if (e.key.trim()) extras[e.key.trim()] = e.value; });

      const payload: any = {
        name: name.trim(),
        price: priceN,
        image_url: imageUrl,
        description: description.trim(),
        stock: isNaN(stockN) ? 0 : stockN,
        category: category.trim() || undefined,
        is_published: published,
        brand: brand.trim(),
        sub_features: subFeatures.filter((s) => s.trim()),
        images: galleryImages,
        price_summary: priceSummary,
        protection_summary: protectionSummary,
        warranty_summary: warrantySummary,
        delivery_summary: deliverySummary,
        attrs_brand: attrsBrand.trim(),
        attrs_os: attrsOs.trim(),
        attrs_ram: attrsRam.trim(),
        attrs_cpu_model: attrsCpuModel.trim(),
        attrs_cpu_speed: attrsCpuSpeed.trim(),
        attrs_storage: attrsStorage.trim(),
        extra_attrs: extras,
        spec_tabs: specTabs
          .map((t) => ({ name: t.name.trim(), rows: t.rows.filter((r) => r.label.trim() || r.value.trim()) }))
          .filter((t) => t.name || t.rows.length),
        whats_in_box: whatsInBox.filter((b) => b.name.trim() || b.image_data_url),
      };
      if (existing) {
        await api.patch(`/admin/products/${existing.id}`, payload);
      } else {
        await api.post("/admin/products", payload);
      }
      onSaved();
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={modalStyles.overlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={[modalStyles.sheet, { maxHeight: "94%" }]}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <Text style={modalStyles.title}>{existing ? "Edit product" : "New product"}</Text>
            <TouchableOpacity onPress={onClose} style={{ padding: 6 }}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
          </View>

          <ScrollView keyboardShouldPersistTaps="handled" style={{ marginBottom: 12 }} contentContainerStyle={{ paddingBottom: 12 }}>

            {/* ── Section 1: Basics ── */}
            <Section
              title="Basics"
              icon="info"
              defaultOpen
              summary={name ? `${name} · ${price ? `₹${price}` : "no price"}` : "Name, price, stock, category"}
              testID="section-basics"
            >
              <TouchableOpacity onPress={onPickCover} style={modalStyles.imagePick} testID="product-image-pick">
                {imageUrl ? <Image source={{ uri: imageUrl }} style={modalStyles.imagePickImg} /> : (
                  <View style={modalStyles.imagePickPlaceholder}>
                    {picking ? <ActivityIndicator color={colors.primary} /> : (
                      <>
                        <Feather name="image" size={24} color={colors.textMuted} />
                        <Text style={{ color: colors.textMuted, marginTop: 6, fontSize: 12 }}>Tap to pick cover image</Text>
                      </>
                    )}
                  </View>
                )}
              </TouchableOpacity>
              <Text style={modalStyles.fieldLabel}>Name</Text>
              <TextInput value={name} onChangeText={setName} style={modalStyles.input} testID="product-name" />
              <Text style={modalStyles.fieldLabel}>Price (₹)</Text>
              <TextInput value={price} onChangeText={setPrice} keyboardType="decimal-pad" style={modalStyles.input} testID="product-price" />
              <Text style={modalStyles.fieldLabel}>Stock</Text>
              <TextInput value={stock} onChangeText={setStock} keyboardType="number-pad" style={modalStyles.input} testID="product-stock" />
              <Text style={modalStyles.fieldLabel}>Category</Text>
              <ProductCategoryPicker value={category} onChange={setCategory} testID="product-category" />
              <Text style={modalStyles.fieldLabel}>Description</Text>
              <TextInput value={description} onChangeText={setDescription} multiline style={[modalStyles.input, { minHeight: 70, paddingTop: 12 }]} testID="product-description" />
              <View style={modalStyles.switchRow}>
                <View style={{ flex: 1 }}>
                  <Text style={modalStyles.switchTitle}>Published</Text>
                  <Text style={modalStyles.switchSub}>Hidden products are not shown to users in the shop.</Text>
                </View>
                <Switch value={published} onValueChange={setPublished} testID="product-published" />
              </View>
            </Section>

            {/* ── Section 2: Brand & Sub-features ── */}
            <Section
              title="Brand & Sub-features"
              icon="tag"
              summary={brand ? `${brand} · ${subFeatures.length} feature${subFeatures.length === 1 ? "" : "s"}` : "Bullet list under product name"}
              testID="section-brand"
            >
              <Text style={modalStyles.fieldLabel}>Brand name</Text>
              <TextInput value={brand} onChangeText={setBrand} placeholder="e.g. Apple, Samsung" placeholderTextColor={colors.textMuted} style={modalStyles.input} testID="product-brand" />
              <Text style={modalStyles.fieldLabel}>Sub-features (bullet points)</Text>
              {subFeatures.map((f, i) => (
                <View key={i} style={sectionStyles.row}>
                  <Feather name="check-circle" size={14} color={colors.primary} />
                  <Text style={sectionStyles.rowText} numberOfLines={2}>{f}</Text>
                  <TouchableOpacity onPress={() => setSubFeatures(subFeatures.filter((_, j) => j !== i))}>
                    <Feather name="x" size={16} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              ))}
              <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                <TextInput
                  value={newSubFeature}
                  onChangeText={setNewSubFeature}
                  placeholder="Type a feature and tap +"
                  placeholderTextColor={colors.textMuted}
                  style={[modalStyles.input, { flex: 1 }]}
                  onSubmitEditing={onAddSubFeature}
                  testID="product-sub-feature-input"
                />
                <TouchableOpacity onPress={onAddSubFeature} style={sectionStyles.addBtn} testID="product-sub-feature-add">
                  <Feather name="plus" size={18} color={colors.primaryFg} />
                </TouchableOpacity>
              </View>
            </Section>

            {/* ── Section 3: Gallery ── */}
            <Section
              title="Gallery (up to 10)"
              icon="image"
              summary={`${galleryImages.length}/10 image${galleryImages.length === 1 ? "" : "s"}`}
              testID="section-gallery"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                The cover image (above) is shown first. Add up to 10 additional images for the product gallery.
              </Text>
              <View style={sectionStyles.galleryGrid}>
                {galleryImages.map((img, i) => (
                  <View key={i} style={sectionStyles.galleryItem}>
                    <Image source={{ uri: img }} style={sectionStyles.galleryImg} />
                    <TouchableOpacity
                      onPress={() => setGalleryImages(galleryImages.filter((_, j) => j !== i))}
                      style={sectionStyles.galleryRemove}
                    >
                      <Feather name="x" size={12} color="#fff" />
                    </TouchableOpacity>
                  </View>
                ))}
                {galleryImages.length < 10 && (
                  <TouchableOpacity onPress={onAddGalleryImage} style={sectionStyles.galleryAdd} testID="product-gallery-add">
                    <Feather name="plus" size={20} color={colors.primary} />
                    <Text style={{ fontSize: 10, color: colors.primary, fontWeight: "700", marginTop: 2 }}>Add</Text>
                  </TouchableOpacity>
                )}
              </View>
            </Section>

            {/* ── Section 4: Styled Summaries ── */}
            <Section
              title="Styled Summaries"
              icon="layout"
              summary="Price · Protection · Warranty · Delivery"
              testID="section-summaries"
            >
              <Text style={modalStyles.fieldLabel}>Price summary</Text>
              <StyledTextEditor value={priceSummary} onChange={setPriceSummary} placeholder="e.g. ₹1,499 inclusive of all taxes (Free shipping)" testID="product-price-summary" />
              <Text style={modalStyles.fieldLabel}>Protection summary</Text>
              <StyledTextEditor value={protectionSummary} onChange={setProtectionSummary} placeholder="e.g. 1-year manufacturer warranty + 2-year extended at checkout" testID="product-protection-summary" />
              <Text style={modalStyles.fieldLabel}>Warranty summary</Text>
              <StyledTextEditor value={warrantySummary} onChange={setWarrantySummary} placeholder="e.g. Free replacement within 7 days of delivery" testID="product-warranty-summary" />
              <Text style={modalStyles.fieldLabel}>Delivery summary</Text>
              <StyledTextEditor value={deliverySummary} onChange={setDeliverySummary} placeholder="e.g. Free delivery in 2-4 business days" testID="product-delivery-summary" />
            </Section>

            {/* ── Section 5: Key Attributes ── */}
            <Section
              title="Key Attributes"
              icon="sliders"
              summary="Brand · OS · RAM · CPU · Storage + extras"
              testID="section-attrs"
            >
              <Text style={modalStyles.fieldLabel}>Brand</Text>
              <TextInput value={attrsBrand} onChangeText={setAttrsBrand} placeholder="e.g. Samsung" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>OS</Text>
              <TextInput value={attrsOs} onChangeText={setAttrsOs} placeholder="e.g. Android 14" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>RAM</Text>
              <TextInput value={attrsRam} onChangeText={setAttrsRam} placeholder="e.g. 8 GB" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>CPU model</Text>
              <TextInput value={attrsCpuModel} onChangeText={setAttrsCpuModel} placeholder="e.g. Snapdragon 8 Gen 3" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>CPU speed</Text>
              <TextInput value={attrsCpuSpeed} onChangeText={setAttrsCpuSpeed} placeholder="e.g. 3.3 GHz" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>Storage</Text>
              <TextInput value={attrsStorage} onChangeText={setAttrsStorage} placeholder="e.g. 256 GB" placeholderTextColor={colors.textMuted} style={modalStyles.input} />

              <Text style={[modalStyles.fieldLabel, { marginTop: 16 }]}>Extra attributes</Text>
              {extraAttrs.map((kv, i) => (
                <View key={i} style={{ flexDirection: "row", gap: 6, marginBottom: 6 }}>
                  <TextInput
                    value={kv.key}
                    onChangeText={(t) => { const n = [...extraAttrs]; n[i] = { ...n[i], key: t }; setExtraAttrs(n); }}
                    placeholder="Label"
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, { flex: 1 }]}
                  />
                  <TextInput
                    value={kv.value}
                    onChangeText={(t) => { const n = [...extraAttrs]; n[i] = { ...n[i], value: t }; setExtraAttrs(n); }}
                    placeholder="Value"
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, { flex: 1.4 }]}
                  />
                  <TouchableOpacity onPress={() => setExtraAttrs(extraAttrs.filter((_, j) => j !== i))} style={sectionStyles.smallDangerBtn}>
                    <Feather name="trash-2" size={14} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              ))}
              <TouchableOpacity onPress={onAddExtraAttr} style={sectionStyles.outlineBtn} testID="product-extra-attr-add">
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={sectionStyles.outlineBtnText}>Add custom attribute</Text>
              </TouchableOpacity>
            </Section>

            {/* ── Section 6: Specification Tabs ── */}
            <Section
              title="Specification Tabs"
              icon="grid"
              summary={`${specTabs.length} tab${specTabs.length === 1 ? "" : "s"}`}
              testID="section-specs"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                Group specs into tabs (General, Display, Battery, etc). Each tab holds label/value rows.
              </Text>
              {specTabs.map((tab, ti) => (
                <View key={ti} style={sectionStyles.specTabCard}>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                    <TextInput
                      value={tab.name}
                      onChangeText={(t) => { const n = [...specTabs]; n[ti] = { ...n[ti], name: t }; setSpecTabs(n); }}
                      placeholder="Tab name (e.g. Display)"
                      placeholderTextColor={colors.textMuted}
                      style={[modalStyles.input, { flex: 1 }]}
                    />
                    <TouchableOpacity onPress={() => setSpecTabs(specTabs.filter((_, j) => j !== ti))} style={sectionStyles.smallDangerBtn}>
                      <Feather name="trash-2" size={14} color="#B3261E" />
                    </TouchableOpacity>
                  </View>
                  {tab.rows.map((row, ri) => (
                    <View key={ri} style={{ flexDirection: "row", gap: 6, marginTop: 8 }}>
                      <TextInput
                        value={row.label}
                        onChangeText={(t) => { const n = [...specTabs]; n[ti].rows[ri] = { ...row, label: t }; setSpecTabs(n); }}
                        placeholder="Label"
                        placeholderTextColor={colors.textMuted}
                        style={[modalStyles.input, { flex: 1 }]}
                      />
                      <TextInput
                        value={row.value}
                        onChangeText={(t) => { const n = [...specTabs]; n[ti].rows[ri] = { ...row, value: t }; setSpecTabs(n); }}
                        placeholder="Value"
                        placeholderTextColor={colors.textMuted}
                        style={[modalStyles.input, { flex: 1.4 }]}
                      />
                      <TouchableOpacity
                        onPress={() => { const n = [...specTabs]; n[ti] = { ...n[ti], rows: n[ti].rows.filter((_, k) => k !== ri) }; setSpecTabs(n); }}
                        style={sectionStyles.smallDangerBtn}
                      >
                        <Feather name="x" size={14} color="#B3261E" />
                      </TouchableOpacity>
                    </View>
                  ))}
                  <TouchableOpacity onPress={() => onAddSpecRow(ti)} style={[sectionStyles.outlineBtn, { marginTop: 8 }]}>
                    <Feather name="plus" size={14} color={colors.primary} />
                    <Text style={sectionStyles.outlineBtnText}>Add row</Text>
                  </TouchableOpacity>
                </View>
              ))}
              <TouchableOpacity onPress={onAddSpecTab} style={[sectionStyles.outlineBtn, { marginTop: 8 }]} testID="product-spec-tab-add">
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={sectionStyles.outlineBtnText}>Add spec tab</Text>
              </TouchableOpacity>
            </Section>

            {/* ── Section 7: What's in the Box ── */}
            <Section
              title="What's in the Box"
              icon="package"
              summary={`${whatsInBox.length} item${whatsInBox.length === 1 ? "" : "s"}`}
              testID="section-box"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                Items included in the package, with an optional thumbnail each.
              </Text>
              {whatsInBox.map((b, i) => (
                <View key={i} style={sectionStyles.boxItemRow}>
                  {b.image_data_url ? (
                    <Image source={{ uri: b.image_data_url }} style={sectionStyles.boxThumb} />
                  ) : (
                    <View style={[sectionStyles.boxThumb, { alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted }]}>
                      <Feather name="image" size={14} color={colors.textMuted} />
                    </View>
                  )}
                  <TextInput
                    value={b.name}
                    onChangeText={(t) => { const n = [...whatsInBox]; n[i] = { ...n[i], name: t }; setWhatsInBox(n); }}
                    placeholder="Item name (e.g. Charging cable)"
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, { flex: 1 }]}
                  />
                  <TouchableOpacity onPress={() => setWhatsInBox(whatsInBox.filter((_, j) => j !== i))} style={sectionStyles.smallDangerBtn}>
                    <Feather name="trash-2" size={14} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              ))}
              <TouchableOpacity onPress={onAddBoxItem} style={[sectionStyles.outlineBtn, { marginTop: 8 }]} testID="product-box-add">
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={sectionStyles.outlineBtnText}>Add item</Text>
              </TouchableOpacity>
            </Section>
          </ScrollView>

          <View style={{ flexDirection: "row", gap: 10 }}>
            <TouchableOpacity onPress={onClose} style={[modalStyles.btn, { backgroundColor: colors.surfaceMuted }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onSubmit} disabled={saving} style={[modalStyles.btn, { backgroundColor: colors.primary }, saving && { opacity: 0.6 }]} testID="product-save">
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : (
                <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>{existing ? "Save changes" : "Create product"}</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
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
  vendorFilterChip: {
    flexDirection: "row", alignItems: "center", gap: 8,
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
