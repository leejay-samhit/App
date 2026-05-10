import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, FlatList, Modal, TextInput, TouchableOpacity, ActivityIndicator, Alert, RefreshControl, Image, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

type Stats = { total_sales: number; total_earnings: number; today_earnings: number; today_orders: number; all_orders: number; products_count: number; published_count: number; wallet_balance: number };
type Product = { id: string; name: string; price: number; stock: number; image_url: string; description?: string; category?: string; is_published?: boolean; created_at?: string; interested_count?: number };
type Sale = { id: string; order_id: string; product_id: string; product_name: string; qty: number; line_total: number; vendor_share: number; commission_pct: number; created_at: string };
type InterestedUser = { id: string; name: string; email: string; phone?: string };

export default function VendorDashboard() {
  const router = useRouter();
  const [tab, setTab] = useState<"home" | "products" | "sales">("home");
  const [stats, setStats] = useState<Stats | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [interestedFor, setInterestedFor] = useState<Product | null>(null);
  const [interestedUsers, setInterestedUsers] = useState<InterestedUser[]>([]);
  const [interestedLoading, setInterestedLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, p, sl, pubResp] = await Promise.all([
        api.get<Stats>("/vendor/me/stats"),
        api.get<Product[]>("/vendor/me/products"),
        api.get<{ items: Sale[] }>("/vendor/me/sales"),
        api.get<any>("/products").catch(() => ({ data: [] })),
      ]);
      const pubList: any[] = Array.isArray(pubResp.data) ? pubResp.data : (pubResp.data?.items || []);
      const cMap = new Map<string, number>();
      pubList.forEach((x: any) => cMap.set(x.id, x.interested_count || 0));
      setStats(s.data);
      setProducts(p.data.map((it) => ({ ...it, interested_count: cMap.get(it.id) || 0 })));
      setSales(sl.data.items || []);
    } catch (e) {
      // If 403 (not approved), redirect to apply
      const msg = formatApiError(e);
      if (String(msg).toLowerCase().includes("vendor")) router.replace("/vendor/apply" as any);
      else Alert.alert("Error", msg);
    }
    finally { setLoading(false); setRefreshing(false); }
  }, [router]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onAddProduct = () => { setEditing({ id: "", name: "", price: 0, stock: 100, image_url: "", description: "", category: "", is_published: true }); setEditorOpen(true); };
  const onEditProduct = (p: Product) => { setEditing({ ...p }); setEditorOpen(true); };

  const onDeleteProduct = (p: Product) => {
    Alert.alert("Delete product?", `\"${p.name}\" will be removed permanently.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try { await api.delete(`/vendor/me/products/${p.id}`); await load(); }
        catch (e) { Alert.alert("Couldn't delete", formatApiError(e)); }
      }}
    ]);
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="vendor-back"><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Vendor Panel</Text>
        <TouchableOpacity onPress={onAddProduct} style={styles.iconBtn} testID="vendor-add"><Feather name="plus" size={22} color={colors.primary} /></TouchableOpacity>
      </View>

      <View style={styles.tabsRow}>
        {[{ k: "home", l: "Overview" }, { k: "products", l: "Products" }, { k: "sales", l: "Sales" }].map((t) => (
          <TouchableOpacity key={t.k} onPress={() => setTab(t.k as any)} style={[styles.tab, tab === t.k && styles.tabActive]} testID={`vendor-tab-${t.k}`}>
            <Text style={[styles.tabText, tab === t.k && { color: colors.primary }]}>{t.l}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {tab === "home" && stats && (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>
          <GradientCard variant="emerald" style={{ marginBottom: 14, padding: 18 }}>
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>VENDOR</Text>
            <Text style={{ fontSize: 24, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.6 }}>
              {formatINR(stats.today_earnings)} today
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              {stats.today_orders} order{stats.today_orders === 1 ? "" : "s"} · {stats.published_count} of {stats.products_count} products live
            </Text>
          </GradientCard>
          <View style={styles.statsGrid}>
            <StatCard icon="trending-up" label="TODAY EARNINGS" value={formatINR(stats.today_earnings)} color="#1F6B44" />
            <StatCard icon="package" label="TODAY ORDERS" value={String(stats.today_orders)} color="#1F5E9E" />
            <StatCard icon="dollar-sign" label="LIFETIME EARNINGS" value={formatINR(stats.total_earnings)} color={colors.primary} />
            <StatCard icon="shopping-cart" label="LIFETIME SALES" value={formatINR(stats.total_sales)} color="#7A4A0E" />
            <StatCard icon="box" label="PRODUCTS" value={`${stats.published_count}/${stats.products_count}`} color="#1F5E9E" />
            <StatCard icon="credit-card" label="WALLET" value={formatINR(stats.wallet_balance)} color="#1F6B44" />
          </View>
          <TouchableOpacity onPress={onAddProduct} style={styles.primaryBtn} testID="vendor-add-cta">
            <Feather name="plus-circle" size={18} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Add new product</Text>
          </TouchableOpacity>
        </ScrollView>
      )}

      {tab === "products" && (
        products.length === 0 ? (
          <View style={styles.center}>
            <Feather name="package" size={48} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>No products yet</Text>
            <TouchableOpacity onPress={onAddProduct} style={styles.primaryBtn} testID="vendor-add-empty">
              <Feather name="plus" size={16} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Add product</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <ScrollView
            contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          >
            <View style={styles.vendorGrid}>
              {products.map((item) => {
                const oos = (item.stock || 0) === 0;
                const lowStock = (item.stock || 0) > 0 && (item.stock || 0) <= 5;
                return (
                  <TouchableOpacity
                    key={item.id}
                    activeOpacity={0.85}
                    onPress={() => onEditProduct(item)}
                    style={styles.vendorCard}
                    testID={`vendor-product-${item.id}`}
                  >
                    <View style={styles.vendorImgWrap}>
                      {item.image_url
                        ? <Image source={{ uri: item.image_url }} style={styles.vendorImg} />
                        : <View style={[styles.vendorImg, { backgroundColor: "#F1F3F5" }]} />}
                      {item.is_published === false && (
                        <View style={styles.vendorDraftPill}><Text style={styles.vendorDraftText}>HIDDEN</Text></View>
                      )}
                      {oos && (
                        <View style={styles.vendorOosOverlay} pointerEvents="none">
                          <Text style={styles.vendorOosText}>SOLD OUT</Text>
                        </View>
                      )}
                      {lowStock && !oos && (
                        <View style={styles.vendorLowStock}><Text style={styles.vendorLowStockText}>Only {item.stock}</Text></View>
                      )}
                      {(item.interested_count || 0) > 0 && (
                        <TouchableOpacity
                          style={styles.vendorInterestBadge}
                          onPress={async () => {
                            setInterestedFor(item);
                            setInterestedLoading(true);
                            try {
                              const r = await api.get<{ users: InterestedUser[] }>(`/products/${item.id}/interested`);
                              setInterestedUsers(r.data.users || []);
                            } catch (e) { Alert.alert("Couldn't load", formatApiError(e)); }
                            finally { setInterestedLoading(false); }
                          }}
                          testID={`vendor-interested-${item.id}`}
                        >
                          <Feather name="users" size={10} color="#fff" />
                          <Text style={styles.vendorInterestText}>{item.interested_count}</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                    <View style={styles.vendorBody}>
                      {item.category ? <Text style={styles.vendorCat} numberOfLines={1}>{item.category}</Text> : null}
                      <Text style={styles.vendorName} numberOfLines={2}>{item.name}</Text>
                      <View style={styles.vendorFooterRow}>
                        <Text style={styles.vendorPrice}>{formatINR(item.price)}</Text>
                        <Text style={styles.vendorStockLabel}>Stock {item.stock ?? 0}</Text>
                      </View>
                      <View style={styles.vendorActions}>
                        <TouchableOpacity onPress={() => onEditProduct(item)} style={styles.vendorActionBtn} testID={`vendor-edit-${item.id}`}>
                          <Feather name="edit-2" size={13} color={colors.primary} />
                          <Text style={styles.vendorActionText}>Edit</Text>
                        </TouchableOpacity>
                        <TouchableOpacity onPress={() => onDeleteProduct(item)} style={[styles.vendorActionBtn, styles.vendorActionDanger]} testID={`vendor-del-${item.id}`}>
                          <Feather name="trash-2" size={13} color="#B3261E" />
                        </TouchableOpacity>
                      </View>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </View>
          </ScrollView>
        )
      )}

      {tab === "sales" && (
        sales.length === 0 ? (
          <View style={styles.center}><Feather name="trending-up" size={48} color={colors.textMuted} /><Text style={styles.emptyTitle}>No sales yet</Text></View>
        ) : (
          <FlatList
            data={sales}
            keyExtractor={(it) => it.id}
            renderItem={({ item }) => (
              <View style={styles.saleRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.saleName} numberOfLines={1}>{item.product_name}</Text>
                  <Text style={styles.saleMeta}>Order #{item.order_id.slice(0, 8)} · qty {item.qty} · {new Date(item.created_at).toLocaleDateString()}</Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.saleAmount}>+{formatINR(item.vendor_share)}</Text>
                  <Text style={styles.saleSub}>of {formatINR(item.line_total)}</Text>
                </View>
              </View>
            )}
            contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
            ItemSeparatorComponent={() => <View style={styles.sep} />}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          />
        )
      )}

      <ProductEditor
        visible={editorOpen}
        product={editing}
        onClose={() => setEditorOpen(false)}
        onSaved={async () => { setEditorOpen(false); await load(); }}
      />

      {/* Interested customers modal */}
      <Modal visible={!!interestedFor} transparent animationType="slide" onRequestClose={() => setInterestedFor(null)}>
        <View style={styles.vendorModalOverlay}>
          <View style={styles.vendorModalSheet}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <Text style={styles.vendorModalTitle}>Customers waiting</Text>
              <TouchableOpacity onPress={() => setInterestedFor(null)}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
            </View>
            <Text style={styles.vendorModalSub}>
              {interestedFor?.name} · {interestedUsers.length} interested
            </Text>
            {interestedLoading ? (
              <ActivityIndicator color={colors.primary} style={{ marginVertical: 24 }} />
            ) : interestedUsers.length === 0 ? (
              <Text style={{ textAlign: "center", color: colors.textMuted, paddingVertical: 24 }}>
                No customers yet — when shoppers tap “I'm interested” on the out-of-stock card, they'll show up here.
              </Text>
            ) : (
              <ScrollView style={{ maxHeight: 380 }}>
                {interestedUsers.map((u) => (
                  <View key={u.id} style={styles.vendorUserRow}>
                    <View style={styles.vendorUserAvatar}>
                      <Text style={styles.vendorUserAvatarText}>{(u.name || "?").charAt(0).toUpperCase()}</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.vendorUserName}>{u.name || "Customer"}</Text>
                      <Text style={styles.vendorUserMeta}>{u.email}{u.phone ? ` · ${u.phone}` : ""}</Text>
                    </View>
                  </View>
                ))}
              </ScrollView>
            )}
            <TouchableOpacity onPress={() => setInterestedFor(null)} style={[styles.primaryBtn, { marginTop: 14 }]}>
              <Text style={styles.primaryBtnText}>Got it</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function StatCard({ icon, label, value, color }: { icon: any; label: string; value: string; color: string }) {
  return (
    <View style={[styles.statCard]}>
      <View style={[styles.statIcon, { backgroundColor: color + "20" }]}><Feather name={icon} size={16} color={color} /></View>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
    </View>
  );
}

function ProductEditor({ visible, product, onClose, onSaved }: { visible: boolean; product: Product | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("100");
  const [imageUrl, setImageUrl] = useState("");
  const [desc, setDesc] = useState("");
  const [category, setCategory] = useState("");
  const [published, setPublished] = useState(true);
  const [saving, setSaving] = useState(false);

  useFocusEffect(useCallback(() => {}, []));

  // Sync state when product changes
  useFocusEffect(useCallback(() => {
    if (product) {
      setName(product.name || ""); setPrice(product.price ? String(product.price) : "");
      setStock(product.stock != null ? String(product.stock) : "100");
      setImageUrl(product.image_url || ""); setDesc(product.description || "");
      setCategory(product.category || ""); setPublished(product.is_published !== false);
    }
  }, [product]));

  const pickImage = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== "granted") return;
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.7, base64: true });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    if (a.base64) setImageUrl(`data:image/jpeg;base64,${a.base64}`);
  };

  const onSave = async () => {
    if (!name.trim() || !price.trim() || !imageUrl.trim()) { Alert.alert("Missing fields", "Name, price and image are required."); return; }
    const priceN = Number(price);
    if (!Number.isFinite(priceN) || priceN <= 0) { Alert.alert("Invalid price"); return; }
    setSaving(true);
    try {
      const body = { name: name.trim(), price: priceN, stock: Number(stock) || 0, image_url: imageUrl.trim(), description: desc.trim(), category: category.trim() || null, is_published: published };
      if (product?.id) await api.patch(`/vendor/me/products/${product.id}`, body);
      else await api.post("/vendor/me/products", body);
      onSaved();
    } catch (e) { Alert.alert("Couldn't save", formatApiError(e)); }
    finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
          <View style={styles.header}>
            <TouchableOpacity onPress={onClose} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
            <Text style={styles.title}>{product?.id ? "Edit product" : "New product"}</Text>
            <View style={{ width: 40 }} />
          </View>
          <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>Image</Text>
            {imageUrl ? <Image source={{ uri: imageUrl }} style={styles.imagePreview} /> : null}
            <TouchableOpacity onPress={pickImage} style={styles.attachBtn}><Feather name="image" size={16} color={colors.textMain} /><Text style={styles.attachBtnText}>  Pick from gallery</Text></TouchableOpacity>
            <Text style={styles.label}>Name *</Text>
            <TextInput style={styles.input} value={name} onChangeText={setName} placeholder="Product name" placeholderTextColor={colors.textMuted} />
            <Text style={styles.label}>Price (₹) *</Text>
            <TextInput style={styles.input} value={price} onChangeText={setPrice} placeholder="0" placeholderTextColor={colors.textMuted} keyboardType="numeric" />
            <Text style={styles.label}>Stock</Text>
            <TextInput style={styles.input} value={stock} onChangeText={setStock} placeholder="100" placeholderTextColor={colors.textMuted} keyboardType="numeric" />
            <Text style={styles.label}>Category</Text>
            <TextInput style={styles.input} value={category} onChangeText={setCategory} placeholder="e.g. Electronics, Apparel" placeholderTextColor={colors.textMuted} />
            <Text style={styles.label}>Description</Text>
            <TextInput style={[styles.input, styles.area]} value={desc} onChangeText={setDesc} placeholder="Describe what makes this product great..." placeholderTextColor={colors.textMuted} multiline textAlignVertical="top" />
            <TouchableOpacity onPress={() => setPublished((v) => !v)} style={styles.toggleRow}>
              <View style={[styles.toggleBox, published && styles.toggleBoxOn]}>{published ? <Feather name="check" size={14} color="#fff" /> : null}</View>
              <Text style={styles.toggleLabel}>Publish on shop</Text>
            </TouchableOpacity>
          </ScrollView>
          <View style={styles.modalFooter}>
            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.primaryBtn, saving && { opacity: 0.6 }]}>
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : <><Feather name="save" size={16} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Save</Text></>}
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  tabsRow: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, paddingHorizontal: spacing.screen },
  tab: { paddingVertical: 12, paddingHorizontal: 16, marginRight: 8, borderBottomWidth: 2, borderBottomColor: "transparent" },
  tabActive: { borderBottomColor: colors.primary },
  tabText: { fontSize: 13, fontWeight: "700", color: colors.textMuted },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  statCard: { width: "47%", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14 },
  statIcon: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  statLabel: { fontSize: 9, letterSpacing: 1, color: colors.textMuted, fontWeight: "700" },
  statValue: { fontSize: 17, fontWeight: "800", marginTop: 2 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14, marginTop: 20 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  prodCard: { flexDirection: "row", alignItems: "center", padding: 10, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, gap: 10 },
  prodImg: { width: 48, height: 48, borderRadius: 8 },
  prodName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  prodMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  saleRow: { flexDirection: "row", alignItems: "center", paddingVertical: 12 },
  sep: { height: 1, backgroundColor: colors.border },
  saleName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  saleMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  saleAmount: { fontSize: 14, fontWeight: "800", color: "#1F6B44" },
  saleSub: { fontSize: 10, color: colors.textMuted, marginTop: 2 },
  label: { fontSize: 12, color: colors.textMuted, marginTop: 12, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 14, color: colors.textMain },
  area: { minHeight: 90, paddingTop: 14 },
  imagePreview: { width: "100%", height: 180, borderRadius: radii.card, marginBottom: 8 },
  attachBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", padding: 12, borderRadius: radii.input, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, backgroundColor: colors.surface },
  attachBtnText: { color: colors.textMain, fontSize: 13, fontWeight: "600" },
  toggleRow: { flexDirection: "row", alignItems: "center", marginTop: 16, gap: 10 },
  toggleBox: { width: 22, height: 22, borderRadius: 4, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  toggleBoxOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleLabel: { fontSize: 13, color: colors.textMain, fontWeight: "600" },
  modalFooter: { padding: spacing.screen, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.background },

  // ============================================================
  //  Phase D — Vendor product gallery (matches customer/admin look)
  // ============================================================
  vendorGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  vendorCard: {
    flexBasis: "48%", flexGrow: 1,
    backgroundColor: colors.surface, borderRadius: 18, overflow: "hidden",
    borderWidth: 1, borderColor: colors.border,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 2 },
      default: {},
    }),
  },
  vendorImgWrap: { position: "relative", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  vendorImg: { width: "100%", height: "100%" },
  vendorBody: { padding: 12, gap: 4 },
  vendorCat: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.6, textTransform: "uppercase" },
  vendorName: { fontSize: 13, fontWeight: "700", color: colors.textMain, lineHeight: 17, minHeight: 34 },
  vendorFooterRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  vendorPrice: { fontSize: 15, fontWeight: "800", color: colors.primary, letterSpacing: -0.3 },
  vendorStockLabel: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  vendorActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  vendorActionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingVertical: 8, borderRadius: 10, borderWidth: 1, borderColor: colors.primary },
  vendorActionText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  vendorActionDanger: { flex: 0, width: 36, paddingVertical: 8, backgroundColor: "#FCE9E5", borderColor: "#FCE9E5" },

  vendorDraftPill: { position: "absolute", top: 8, left: 8, backgroundColor: "#FFF4E5", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  vendorDraftText: { color: "#7A4A0E", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  vendorOosOverlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.5)" },
  vendorOosText: { fontSize: 13, fontWeight: "900", color: colors.textMain, letterSpacing: 2, backgroundColor: "rgba(255,255,255,0.85)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4, overflow: "hidden" },
  vendorLowStock: { position: "absolute", top: 8, left: 8, paddingVertical: 4, paddingHorizontal: 8, backgroundColor: "#F59E0B", borderRadius: 999 },
  vendorLowStockText: { fontSize: 9, fontWeight: "800", color: "#fff", letterSpacing: 0.4 },
  vendorInterestBadge: { position: "absolute", top: 8, right: 8, flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 3, paddingHorizontal: 8, backgroundColor: colors.primary, borderRadius: 999 },
  vendorInterestText: { fontSize: 10, fontWeight: "800", color: "#fff" },

  // Interested-customers modal styles
  vendorModalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  vendorModalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 36 },
  vendorModalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  vendorModalSub: { fontSize: 12, color: colors.textMuted, marginBottom: 12 },
  vendorUserRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  vendorUserAvatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  vendorUserAvatarText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  vendorUserName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  vendorUserMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
});
