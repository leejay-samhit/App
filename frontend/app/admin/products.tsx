import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, ScrollView, Switch, Image, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

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
  interested_count?: number;
};

type InterestedUser = { id: string; name: string; email: string; phone?: string };

export default function AdminProducts() {
  const router = useRouter();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [interestedFor, setInterestedFor] = useState<Product | null>(null);

  const load = useCallback(async () => {
    try {
      // /admin/products doesn't include interested_count yet; fetch from public
      // /products too and merge for the count display. Admin keeps full access
      // (incl. unpublished items via /admin/products).
      const [admin, pub] = await Promise.all([
        api.get<Product[]>("/admin/products"),
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
  }, []);

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
        <TouchableOpacity onPress={() => setCreateOpen(true)} style={[styles.iconBtn, styles.iconBtnPrimary]} testID="product-new">
          <Feather name="plus" size={20} color={colors.primaryFg} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
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
              placeholder="Search products"
              placeholderTextColor={colors.textMuted}
              style={styles.searchInput}
            />
            {search ? (
              <TouchableOpacity onPress={() => setSearch("")}><Feather name="x-circle" size={16} color={colors.textMuted} /></TouchableOpacity>
            ) : null}
          </View>

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
            const filtered = q ? items.filter(p => p.name.toLowerCase().includes(q) || (p.category || "").toLowerCase().includes(q)) : items;
            if (filtered.length === 0) {
              return <Text style={styles.empty}>{search ? "No matches" : "No products yet — tap the + to add one."}</Text>;
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
                          ? <Image source={{ uri: item.image_url }} style={styles.gridImg} />
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
                        <View style={styles.gridFooter}>
                          <Text style={styles.gridPrice}>{formatINR(item.price)}</Text>
                          <Text style={styles.gridStock}>{item.stock ?? 0} in stock</Text>
                        </View>
                        <View style={styles.gridActions}>
                          <TouchableOpacity onPress={() => setEditing(item)} style={styles.actionBtn} testID={`product-${item.id}-edit`}>
                            <Feather name="edit-2" size={13} color={colors.primary} />
                            <Text style={styles.actionBtnText}>Edit</Text>
                          </TouchableOpacity>
                          <TouchableOpacity onPress={() => onDelete(item)} style={[styles.actionBtn, styles.actionBtnDanger]} testID={`product-${item.id}-delete`}>
                            <Feather name="trash-2" size={13} color="#B3261E" />
                          </TouchableOpacity>
                        </View>
                      </View>
                    </TouchableOpacity>
                  );
                })}
              </View>
            );
          })()}
        </ScrollView>
      )}

      <ProductModal
        visible={createOpen || !!editing}
        existing={editing}
        onClose={() => { setEditing(null); setCreateOpen(false); }}
        onSaved={async () => { setEditing(null); setCreateOpen(false); await load(); }}
      />

      <InterestedModal product={interestedFor} onClose={() => setInterestedFor(null)} />
    </SafeAreaView>
  );
}

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

function ProductModal({ visible, existing, onClose, onSaved }: { visible: boolean; existing: Product | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(existing?.name || "");
  const [price, setPrice] = useState(existing?.price ? String(existing.price) : "");
  const [stock, setStock] = useState(existing?.stock != null ? String(existing.stock) : "100");
  const [description, setDescription] = useState(existing?.description || "");
  const [category, setCategory] = useState(existing?.category || "");
  const [imageUrl, setImageUrl] = useState(existing?.image_url || "");
  const [published, setPublished] = useState(existing?.is_published !== false);
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);

  // Sync when existing changes (open different items)
  useState(() => {
    setName(existing?.name || "");
    setPrice(existing?.price ? String(existing.price) : "");
    setStock(existing?.stock != null ? String(existing.stock) : "100");
    setDescription(existing?.description || "");
    setCategory(existing?.category || "");
    setImageUrl(existing?.image_url || "");
    setPublished(existing?.is_published !== false);
  });

  const onPickImage = async () => {
    setPicking(true);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Permission needed", "Please allow photo library access to pick a product image.");
        return;
      }
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.8,
        allowsEditing: true,
        aspect: [4, 3],
      });
      if (!r.canceled && r.assets?.[0]?.uri) {
        const m = await ImageManipulator.manipulateAsync(
          r.assets[0].uri,
          [{ resize: { width: 800 } }],
          { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true },
        );
        if (m.base64) setImageUrl(`data:image/jpeg;base64,${m.base64}`);
      }
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    } finally { setPicking(false); }
  };

  const onSubmit = async () => {
    const priceN = Number(price);
    const stockN = Number(stock);
    if (!name.trim() || isNaN(priceN) || priceN < 0) {
      Alert.alert("Missing fields", "Name and a valid price are required.");
      return;
    }
    if (!imageUrl) {
      Alert.alert("Image required", "Please add a product image.");
      return;
    }
    setSaving(true);
    try {
      const payload: any = {
        name: name.trim(),
        price: priceN,
        image_url: imageUrl,
        description: description.trim(),
        stock: isNaN(stockN) ? 0 : stockN,
        category: category.trim() || undefined,
        is_published: published,
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
        <View style={modalStyles.sheet}>
          <Text style={modalStyles.title}>{existing ? "Edit product" : "New product"}</Text>
          <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 520 }}>
            <TouchableOpacity onPress={onPickImage} style={modalStyles.imagePick} testID="product-image-pick">
              {imageUrl ? <Image source={{ uri: imageUrl }} style={modalStyles.imagePickImg} /> : (
                <View style={modalStyles.imagePickPlaceholder}>
                  {picking ? <ActivityIndicator color={colors.primary} /> : (
                    <>
                      <Feather name="image" size={24} color={colors.textMuted} />
                      <Text style={{ color: colors.textMuted, marginTop: 6, fontSize: 12 }}>Tap to pick image</Text>
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
            <Text style={modalStyles.fieldLabel}>Category (optional)</Text>
            <TextInput value={category} onChangeText={setCategory} placeholder="e.g. Apparel" placeholderTextColor={colors.textMuted} style={modalStyles.input} testID="product-category" />
            <Text style={modalStyles.fieldLabel}>Description</Text>
            <TextInput value={description} onChangeText={setDescription} multiline style={[modalStyles.input, { minHeight: 70, paddingTop: 12 }]} testID="product-description" />
            <View style={modalStyles.switchRow}>
              <View style={{ flex: 1 }}>
                <Text style={modalStyles.switchTitle}>Published</Text>
                <Text style={modalStyles.switchSub}>Hidden products are not shown to users in the shop.</Text>
              </View>
              <Switch value={published} onValueChange={setPublished} testID="product-published" />
            </View>
          </ScrollView>
          <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
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
