import { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Alert, RefreshControl, TextInput, Image, Modal, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

type Banner = {
  id: string;
  image_data_url: string;
  title: string;
  subtitle: string;
  cta_label: string;
  product_id: string | null;
  sort_order: number;
  active: boolean;
  created_at?: string;
};

type Product = { id: string; name: string };

export default function AdminPromoBannersScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Banner[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Banner | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    try {
      const [bRes, pRes] = await Promise.all([
        api.get<{ items: Banner[] }>("/admin/promo-banners"),
        api.get<{ items?: Product[]; products?: Product[] }>("/admin/products"),
      ]);
      setItems(bRes.data?.items || []);
      const pData = pRes.data;
      setProducts(pData?.items || pData?.products || []);
    } catch (e) {
      Alert.alert("Failed to load", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onDelete = (b: Banner) => {
    Alert.alert("Delete banner?", `"${b.title || "Untitled"}" will be removed permanently.`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive",
        onPress: async () => {
          try {
            await api.delete(`/admin/promo-banners/${b.id}`);
            setItems((prev) => prev.filter((x) => x.id !== b.id));
          } catch (e) { Alert.alert("Delete failed", formatApiError(e)); }
        },
      },
    ]);
  };

  const onToggleActive = async (b: Banner) => {
    try {
      await api.patch(`/admin/promo-banners/${b.id}`, { active: !b.active });
      setItems((prev) => prev.map((x) => x.id === b.id ? { ...x, active: !b.active } : x));
    } catch (e) { Alert.alert("Update failed", formatApiError(e)); }
  };

  const openCreate = () => { setEditing(null); setShowForm(true); };
  const openEdit = (b: Banner) => { setEditing(b); setShowForm(true); };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Promo Banners</Text>
        <TouchableOpacity onPress={openCreate} style={[styles.iconBtn, styles.iconBtnPrimary]} testID="banner-new">
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
          <GradientCard variant="primary" style={{ marginBottom: 14, padding: 18 }}>
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>HERO BANNERS</Text>
            <Text style={{ fontSize: 22, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.6 }}>
              {items.length} banner{items.length === 1 ? "" : "s"}
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              {items.filter(b => b.active).length} active · swipe to view next on the Shop screen
            </Text>
          </GradientCard>

          {items.length === 0 ? (
            <View style={styles.emptyCard}>
              <Feather name="image" size={28} color={colors.textMuted} />
              <Text style={styles.emptyText}>No banners yet</Text>
              <Text style={styles.emptySub}>Tap + to add your first hero slide. Customers will see them at the top of the Shop tab.</Text>
            </View>
          ) : (
            items.map((b) => (
              <View key={b.id} style={styles.card} testID={`banner-${b.id}`}>
                {b.image_data_url ? (
                  <Image source={{ uri: b.image_data_url }} style={styles.thumb} resizeMode="cover" />
                ) : (
                  <View style={[styles.thumb, { backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" }]}>
                    <Feather name="image" size={20} color={colors.textMuted} />
                  </View>
                )}
                <View style={{ flex: 1, marginLeft: 12 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                    <Text style={styles.cardTitle} numberOfLines={1}>{b.title || "Untitled"}</Text>
                    <View style={[styles.statusPill, { backgroundColor: b.active ? "#DCFCE7" : "#F3F4F6" }]}>
                      <View style={[styles.statusDot, { backgroundColor: b.active ? colors.success : "#94A3B8" }]} />
                      <Text style={[styles.statusText, { color: b.active ? "#065F46" : "#475569" }]}>{b.active ? "ACTIVE" : "DRAFT"}</Text>
                    </View>
                  </View>
                  <Text style={styles.cardSub} numberOfLines={1}>{b.subtitle || "—"}</Text>
                  <Text style={styles.cardMeta} numberOfLines={1}>
                    Order #{b.sort_order} · {b.product_id ? `→ ${(products.find((p) => p.id === b.product_id)?.name) || "Linked product"}` : "No linked product"}
                  </Text>
                  <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                    <TouchableOpacity onPress={() => openEdit(b)} style={styles.actionBtn} testID={`banner-edit-${b.id}`}>
                      <Feather name="edit-2" size={13} color={colors.primary} />
                      <Text style={styles.actionText}>Edit</Text>
                    </TouchableOpacity>
                    <TouchableOpacity onPress={() => onToggleActive(b)} style={styles.actionBtn}>
                      <Feather name={b.active ? "eye-off" : "eye"} size={13} color={colors.textMain} />
                      <Text style={styles.actionText}>{b.active ? "Hide" : "Publish"}</Text>
                    </TouchableOpacity>
                    <TouchableOpacity onPress={() => onDelete(b)} style={[styles.actionBtn, { borderColor: "#FCA5A5" }]} testID={`banner-delete-${b.id}`}>
                      <Feather name="trash-2" size={13} color="#B91C1C" />
                      <Text style={[styles.actionText, { color: "#B91C1C" }]}>Delete</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            ))
          )}
        </ScrollView>
      )}

      {/* Create / Edit modal */}
      <BannerFormModal
        visible={showForm}
        banner={editing}
        products={products}
        onClose={() => setShowForm(false)}
        onSaved={() => { setShowForm(false); load(); }}
      />
    </SafeAreaView>
  );
}

// ---------- Form Modal ----------
function BannerFormModal({ visible, banner, products, onClose, onSaved }: {
  visible: boolean;
  banner: Banner | null;
  products: Product[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [ctaLabel, setCtaLabel] = useState("Shop now");
  const [productId, setProductId] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState("0");
  const [active, setActive] = useState(true);
  const [imageDataUrl, setImageDataUrl] = useState("");
  const [picking, setPicking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showProductPicker, setShowProductPicker] = useState(false);

  useEffect(() => {
    if (visible) {
      setTitle(banner?.title || "");
      setSubtitle(banner?.subtitle || "");
      setCtaLabel(banner?.cta_label || "Shop now");
      setProductId(banner?.product_id || null);
      setSortOrder(String(banner?.sort_order ?? 0));
      setActive(banner?.active ?? true);
      setImageDataUrl(banner?.image_data_url || "");
    }
  }, [visible, banner]);

  const pickImage = async () => {
    setPicking(true);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Permission needed", "Please allow photo library access.");
        return;
      }
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.8,
        allowsEditing: true,
        aspect: [16, 9],
      });
      if (!r.canceled && r.assets?.[0]?.uri) {
        const m = await ImageManipulator.manipulateAsync(
          r.assets[0].uri,
          [{ resize: { width: 1200 } }],
          { compress: 0.75, format: ImageManipulator.SaveFormat.JPEG, base64: true },
        );
        if (m.base64) setImageDataUrl(`data:image/jpeg;base64,${m.base64}`);
      }
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    } finally { setPicking(false); }
  };

  const onSave = async () => {
    if (!imageDataUrl) {
      Alert.alert("Image required", "Please add a banner image.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        image_data_url: imageDataUrl,
        title: title.trim(),
        subtitle: subtitle.trim(),
        cta_label: ctaLabel.trim() || "Shop now",
        product_id: productId,
        sort_order: parseInt(sortOrder, 10) || 0,
        active,
      };
      if (banner) {
        await api.patch(`/admin/promo-banners/${banner.id}`, payload);
      } else {
        await api.post("/admin/promo-banners", payload);
      }
      onSaved();
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally { setSaving(false); }
  };

  const linkedProduct = productId ? products.find((p) => p.id === productId) : null;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent>
      <View style={styles.modalOverlay}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={onClose} style={styles.iconBtn}>
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.modalTitle}>{banner ? "Edit banner" : "New banner"}</Text>
            <TouchableOpacity
              onPress={onSave}
              disabled={saving}
              style={[styles.iconBtn, styles.iconBtnPrimary, saving && { opacity: 0.5 }]}
              testID="banner-save"
            >
              {saving ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <Feather name="check" size={20} color={colors.primaryFg} />}
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
            {/* Image */}
            <Text style={styles.label}>Banner image / GIF</Text>
            <TouchableOpacity onPress={pickImage} style={styles.imagePicker} testID="banner-image-picker">
              {imageDataUrl ? (
                <Image source={{ uri: imageDataUrl }} style={styles.imagePreview} resizeMode="cover" />
              ) : (
                <View style={styles.imagePickerEmpty}>
                  {picking ? <ActivityIndicator color={colors.primary} /> : (
                    <>
                      <Feather name="image" size={28} color={colors.textMuted} />
                      <Text style={styles.imagePickerHint}>Tap to upload</Text>
                      <Text style={styles.imagePickerSub}>16:9 ratio recommended</Text>
                    </>
                  )}
                </View>
              )}
            </TouchableOpacity>

            <Text style={styles.label}>Title</Text>
            <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder="e.g. Save 70%" placeholderTextColor={colors.textMuted} maxLength={60} />

            <Text style={styles.label}>Subtitle</Text>
            <TextInput style={styles.input} value={subtitle} onChangeText={setSubtitle} placeholder="e.g. on premium picks" placeholderTextColor={colors.textMuted} maxLength={80} />

            <Text style={styles.label}>CTA button label</Text>
            <TextInput style={styles.input} value={ctaLabel} onChangeText={setCtaLabel} placeholder="Shop now" placeholderTextColor={colors.textMuted} maxLength={24} />

            <Text style={styles.label}>Linked product (optional)</Text>
            <TouchableOpacity style={styles.input} onPress={() => setShowProductPicker(true)} testID="banner-product-picker">
              <Text style={{ color: linkedProduct ? colors.textMain : colors.textMuted }}>
                {linkedProduct ? linkedProduct.name : "Tap to pick a product"}
              </Text>
            </TouchableOpacity>
            {productId ? (
              <TouchableOpacity onPress={() => setProductId(null)} style={{ alignSelf: "flex-start", marginTop: 4 }}>
                <Text style={{ color: "#B91C1C", fontSize: 12, fontWeight: "700" }}>Clear link</Text>
              </TouchableOpacity>
            ) : null}

            <View style={{ flexDirection: "row", gap: 12, marginTop: 4 }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Sort order</Text>
                <TextInput
                  style={styles.input}
                  value={sortOrder}
                  onChangeText={setSortOrder}
                  keyboardType="numeric"
                  placeholder="0"
                  placeholderTextColor={colors.textMuted}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Active</Text>
                <View style={[styles.input, { flexDirection: "row", alignItems: "center", justifyContent: "space-between" }]}>
                  <Text style={{ color: active ? colors.primary : colors.textMuted, fontWeight: "700" }}>
                    {active ? "Visible" : "Hidden"}
                  </Text>
                  <Switch value={active} onValueChange={setActive} />
                </View>
              </View>
            </View>
          </ScrollView>
        </View>
      </View>

      {/* Product picker modal */}
      <Modal visible={showProductPicker} transparent animationType="slide" onRequestClose={() => setShowProductPicker(false)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalSheet, { maxHeight: "70%" }]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setShowProductPicker(false)} style={styles.iconBtn}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
              <Text style={styles.modalTitle}>Pick a product</Text>
              <View style={{ width: 40 }} />
            </View>
            <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
              {products.length === 0 ? (
                <Text style={{ color: colors.textMuted, textAlign: "center", padding: 20 }}>No products yet</Text>
              ) : products.map((p) => (
                <TouchableOpacity
                  key={p.id}
                  style={[styles.productRow, productId === p.id && { borderColor: colors.primary, backgroundColor: colors.brand100 }]}
                  onPress={() => { setProductId(p.id); setShowProductPicker(false); }}
                >
                  <Text style={styles.productRowText}>{p.name}</Text>
                  {productId === p.id ? <Feather name="check" size={16} color={colors.primary} /> : null}
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </Modal>
  );
}

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
  thumb: { width: 80, height: 80, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  cardTitle: { fontSize: 14, fontWeight: "900", color: colors.textMain, flex: 1, letterSpacing: -0.2 },
  cardSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  cardMeta: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 7, paddingVertical: 2, borderRadius: 999 },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  statusText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.4 },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted },
  actionText: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  modalSheet: { flex: 1, marginTop: 60, backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  label: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1.2, marginTop: 14, marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  imagePicker: { width: "100%", aspectRatio: 16/9, borderRadius: 14, borderWidth: 1.5, borderColor: colors.border, borderStyle: "dashed", overflow: "hidden", backgroundColor: colors.surfaceMuted },
  imagePickerEmpty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 4 },
  imagePickerHint: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 4 },
  imagePickerSub: { fontSize: 11, color: colors.textMuted },
  imagePreview: { width: "100%", height: "100%" },
  productRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8, backgroundColor: colors.surface },
  productRowText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
});
