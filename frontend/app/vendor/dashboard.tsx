import { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, FlatList, Modal, TextInput, TouchableOpacity, ActivityIndicator, Alert, RefreshControl, Image, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Stats = { total_sales: number; total_earnings: number; today_earnings: number; today_orders: number; all_orders: number; products_count: number; published_count: number; wallet_balance: number };
type Product = { id: string; name: string; price: number; stock: number; image_url: string; description?: string; category?: string; is_published?: boolean; created_at?: string };
type Sale = { id: string; order_id: string; product_id: string; product_name: string; qty: number; line_total: number; vendor_share: number; commission_pct: number; created_at: string };

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

  const load = useCallback(async () => {
    try {
      const [s, p, sl] = await Promise.all([
        api.get<Stats>("/vendor/me/stats"),
        api.get<Product[]>("/vendor/me/products"),
        api.get<{ items: Sale[] }>("/vendor/me/sales"),
      ]);
      setStats(s.data);
      setProducts(p.data);
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
          <FlatList
            data={products}
            keyExtractor={(it) => it.id}
            renderItem={({ item }) => (
              <View style={styles.prodCard}>
                {item.image_url ? <Image source={{ uri: item.image_url }} style={styles.prodImg} /> : <View style={[styles.prodImg, { backgroundColor: "#F1F3F5" }]} />}
                <View style={{ flex: 1 }}>
                  <Text style={styles.prodName} numberOfLines={1}>{item.name}</Text>
                  <Text style={styles.prodMeta}>{formatINR(item.price)} · stock {item.stock}{item.is_published ? "" : " · unpublished"}</Text>
                </View>
                <TouchableOpacity onPress={() => onEditProduct(item)} style={styles.iconBtn} testID={`vendor-edit-${item.id}`}><Feather name="edit-2" size={16} color={colors.primary} /></TouchableOpacity>
                <TouchableOpacity onPress={() => onDeleteProduct(item)} style={styles.iconBtn} testID={`vendor-del-${item.id}`}><Feather name="trash-2" size={16} color="#B3261E" /></TouchableOpacity>
              </View>
            )}
            contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
            ItemSeparatorComponent={() => <View style={{ height: 8 }} />}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          />
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
});
