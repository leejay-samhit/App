// Admin Shop Layout — admin can add/edit/delete content blocks rendered on
// the customer Shop tab between the promo carousel and the products grid.
// Block types: background, section_header, text, content_box.
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

type Block = {
  id: string;
  block_type: "background" | "section_header" | "text" | "content_box";
  title: string;
  subtitle: string;
  body: string;
  image_data_url: string;
  product_id: string | null;
  cta_label: string;
  sort_order: number;
  active: boolean;
};

type Product = { id: string; name: string };

const TYPE_META: Record<Block["block_type"], { label: string; icon: any; hint: string }> = {
  background:     { label: "Background image",      icon: "image",        hint: "Full-bleed backdrop for the Shop screen" },
  section_header: { label: "Section header / Sub-category", icon: "type",  hint: "Bold sub-category title (e.g. ELECTRONICS)" },
  text:           { label: "Free text",              icon: "align-left",   hint: "A paragraph of supporting text" },
  content_box:    { label: "Content box",            icon: "square",       hint: "Card with title, image, optional product link" },
};

export default function AdminShopLayoutScreen() {
  const router = useRouter();
  const [items, setItems] = useState<Block[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Block | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    try {
      const [bRes, pRes] = await Promise.all([
        api.get<{ items: Block[] }>("/admin/shop-layout"),
        api.get<{ items?: Product[]; products?: Product[] }>("/admin/products"),
      ]);
      setItems(bRes.data?.items || []);
      setProducts(pRes.data?.items || pRes.data?.products || []);
    } catch (e) { Alert.alert("Failed to load", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onDelete = (b: Block) => {
    Alert.alert("Delete block?", `"${b.title || TYPE_META[b.block_type].label}" will be removed.`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive",
        onPress: async () => {
          try {
            await api.delete(`/admin/shop-layout/${b.id}`);
            setItems((prev) => prev.filter((x) => x.id !== b.id));
          } catch (e) { Alert.alert("Delete failed", formatApiError(e)); }
        },
      },
    ]);
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

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Shop Layout</Text>
        <TouchableOpacity onPress={() => { setEditing(null); setShowForm(true); }} style={[styles.iconBtn, styles.iconBtnPrimary]} testID="block-new">
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
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>SHOP LAYOUT</Text>
            <Text style={{ fontSize: 20, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.4 }}>
              {items.length} block{items.length === 1 ? "" : "s"}
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              Background, sub-category labels, content boxes & free text. Sorted by order on the customer Shop screen.
            </Text>
          </GradientCard>

          {items.length === 0 ? (
            <View style={styles.emptyCard}>
              <Feather name="layout" size={28} color={colors.textMuted} />
              <Text style={styles.emptyText}>No blocks yet</Text>
              <Text style={styles.emptySub}>Tap + to add a sub-category header, content box, free text, or background image.</Text>
            </View>
          ) : (
            items.map((b) => {
              const meta = TYPE_META[b.block_type] || TYPE_META.text;
              return (
                <View key={b.id} style={styles.card} testID={`block-${b.id}`}>
                  <View style={styles.cardLeft}>
                    {b.image_data_url ? (
                      <Image source={{ uri: b.image_data_url }} style={styles.thumb} resizeMode="cover" />
                    ) : (
                      <View style={[styles.thumb, { alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted }]}>
                        <Feather name={meta.icon} size={20} color={colors.textMuted} />
                      </View>
                    )}
                  </View>
                  <View style={{ flex: 1, marginLeft: 12 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <View style={styles.typePill}><Text style={styles.typePillText}>{meta.label.toUpperCase()}</Text></View>
                      <View style={[styles.statusPill, { backgroundColor: b.active ? "#DCFCE7" : "#F3F4F6" }]}>
                        <Text style={[styles.statusText, { color: b.active ? "#065F46" : "#475569" }]}>{b.active ? "ACTIVE" : "DRAFT"}</Text>
                      </View>
                    </View>
                    <Text style={styles.cardTitle} numberOfLines={1}>{b.title || "—"}</Text>
                    {b.subtitle ? <Text style={styles.cardSub} numberOfLines={1}>{b.subtitle}</Text> : null}
                    <Text style={styles.cardMeta}>Order #{b.sort_order}{b.product_id ? ` · → ${(products.find(p => p.id === b.product_id)?.name || "Linked product")}` : ""}</Text>
                    <View style={{ flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                      <TouchableOpacity onPress={() => onMove(b, -1)} style={styles.actionMicro}><Feather name="chevron-up" size={12} color={colors.textMain} /></TouchableOpacity>
                      <TouchableOpacity onPress={() => onMove(b, 1)} style={styles.actionMicro}><Feather name="chevron-down" size={12} color={colors.textMain} /></TouchableOpacity>
                      <TouchableOpacity onPress={() => { setEditing(b); setShowForm(true); }} style={styles.actionBtn}>
                        <Feather name="edit-2" size={12} color={colors.primary} />
                        <Text style={styles.actionText}>Edit</Text>
                      </TouchableOpacity>
                      <TouchableOpacity onPress={() => onToggleActive(b)} style={styles.actionBtn}>
                        <Feather name={b.active ? "eye-off" : "eye"} size={12} color={colors.textMain} />
                        <Text style={styles.actionText}>{b.active ? "Hide" : "Publish"}</Text>
                      </TouchableOpacity>
                      <TouchableOpacity onPress={() => onDelete(b)} style={[styles.actionBtn, { borderColor: "#FCA5A5" }]}>
                        <Feather name="trash-2" size={12} color="#B91C1C" />
                        <Text style={[styles.actionText, { color: "#B91C1C" }]}>Delete</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                </View>
              );
            })
          )}
        </ScrollView>
      )}

      <BlockFormModal
        visible={showForm}
        block={editing}
        products={products}
        onClose={() => setShowForm(false)}
        onSaved={() => { setShowForm(false); load(); }}
      />
    </SafeAreaView>
  );
}

// ---------- Form Modal ----------
function BlockFormModal({ visible, block, products, onClose, onSaved }: {
  visible: boolean; block: Block | null; products: Product[];
  onClose: () => void; onSaved: () => void;
}) {
  const [type, setType] = useState<Block["block_type"]>("section_header");
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [body, setBody] = useState("");
  const [ctaLabel, setCtaLabel] = useState("");
  const [imageDataUrl, setImageDataUrl] = useState("");
  const [productId, setProductId] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState("0");
  const [active, setActive] = useState(true);
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [showProductPicker, setShowProductPicker] = useState(false);

  useEffect(() => {
    if (visible) {
      setType(block?.block_type || "section_header");
      setTitle(block?.title || "");
      setSubtitle(block?.subtitle || "");
      setBody(block?.body || "");
      setCtaLabel(block?.cta_label || "");
      setImageDataUrl(block?.image_data_url || "");
      setProductId(block?.product_id || null);
      setSortOrder(String(block?.sort_order ?? 0));
      setActive(block?.active ?? true);
    }
  }, [visible, block]);

  const pickImage = async () => {
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
        if (m.base64) setImageDataUrl(`data:image/jpeg;base64,${m.base64}`);
      }
    } catch (e) { Alert.alert("Image pick failed", formatApiError(e)); }
    finally { setPicking(false); }
  };

  const onSave = async () => {
    if (type === "background" && !imageDataUrl) { Alert.alert("Image required", "Background blocks need an image."); return; }
    if (type !== "background" && !title.trim() && !body.trim()) { Alert.alert("Empty block", "Please add a title or body."); return; }
    setSaving(true);
    try {
      const payload = {
        block_type: type,
        title: title.trim(),
        subtitle: subtitle.trim(),
        body: body.trim(),
        cta_label: ctaLabel.trim(),
        image_data_url: imageDataUrl,
        product_id: productId,
        sort_order: parseInt(sortOrder, 10) || 0,
        active,
      };
      if (block) await api.patch(`/admin/shop-layout/${block.id}`, payload);
      else await api.post("/admin/shop-layout", payload);
      onSaved();
    } catch (e) { Alert.alert("Save failed", formatApiError(e)); }
    finally { setSaving(false); }
  };

  const linkedProduct = productId ? products.find(p => p.id === productId) : null;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent>
      <View style={styles.modalOverlay}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={onClose} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
            <Text style={styles.modalTitle}>{block ? "Edit block" : "New block"}</Text>
            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.iconBtn, styles.iconBtnPrimary, saving && { opacity: 0.5 }]}>
              {saving ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <Feather name="check" size={20} color={colors.primaryFg} />}
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={{ padding: 20, paddingBottom: 80 }} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>Block type</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              {(Object.keys(TYPE_META) as Block["block_type"][]).map((t) => {
                const meta = TYPE_META[t];
                const active = type === t;
                return (
                  <TouchableOpacity key={t} style={[styles.typeChoice, active && styles.typeChoiceActive]} onPress={() => setType(t)}>
                    <Feather name={meta.icon} size={14} color={active ? colors.primaryFg : colors.primary} />
                    <Text style={[styles.typeChoiceText, active && { color: colors.primaryFg }]}>{meta.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>
            <Text style={styles.hint}>{TYPE_META[type].hint}</Text>

            {/* Image (for background, content_box) */}
            {(type === "background" || type === "content_box") && (
              <>
                <Text style={styles.label}>Image{type === "background" ? " (required)" : ""}</Text>
                <TouchableOpacity onPress={pickImage} style={styles.imagePicker}>
                  {imageDataUrl ? (
                    <Image source={{ uri: imageDataUrl }} style={styles.imagePreview} resizeMode="cover" />
                  ) : (
                    <View style={styles.imagePickerEmpty}>
                      {picking ? <ActivityIndicator color={colors.primary} /> : (<>
                        <Feather name="image" size={28} color={colors.textMuted} />
                        <Text style={styles.imagePickerHint}>Tap to upload</Text>
                      </>)}
                    </View>
                  )}
                </TouchableOpacity>
              </>
            )}

            {/* Title (for everything except background) */}
            {type !== "background" && (
              <>
                <Text style={styles.label}>Title{type === "section_header" ? " (sub-category label)" : ""}</Text>
                <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder={type === "section_header" ? "FEATURED ELECTRONICS" : "Block title"} placeholderTextColor={colors.textMuted} maxLength={80} />
              </>
            )}

            {(type === "content_box") && (
              <>
                <Text style={styles.label}>Subtitle</Text>
                <TextInput style={styles.input} value={subtitle} onChangeText={setSubtitle} placeholder="Optional supporting line" placeholderTextColor={colors.textMuted} maxLength={120} />
              </>
            )}

            {(type === "text" || type === "content_box") && (
              <>
                <Text style={styles.label}>Body text</Text>
                <TextInput style={[styles.input, { minHeight: 80, textAlignVertical: "top" }]} value={body} onChangeText={setBody} placeholder="Free-text paragraph" placeholderTextColor={colors.textMuted} multiline maxLength={500} />
              </>
            )}

            {type === "content_box" && (
              <>
                <Text style={styles.label}>Linked product (optional)</Text>
                <TouchableOpacity style={styles.input} onPress={() => setShowProductPicker(true)}>
                  <Text style={{ color: linkedProduct ? colors.textMain : colors.textMuted }}>
                    {linkedProduct ? linkedProduct.name : "Tap to pick a product"}
                  </Text>
                </TouchableOpacity>
                {productId ? (
                  <TouchableOpacity onPress={() => setProductId(null)} style={{ alignSelf: "flex-start", marginTop: 4 }}>
                    <Text style={{ color: "#B91C1C", fontSize: 12, fontWeight: "700" }}>Clear link</Text>
                  </TouchableOpacity>
                ) : null}

                <Text style={styles.label}>CTA button label</Text>
                <TextInput style={styles.input} value={ctaLabel} onChangeText={setCtaLabel} placeholder="View" placeholderTextColor={colors.textMuted} maxLength={24} />
              </>
            )}

            <View style={{ flexDirection: "row", gap: 12, marginTop: 4 }}>
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

      <Modal visible={showProductPicker} transparent animationType="slide" onRequestClose={() => setShowProductPicker(false)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalSheet, { maxHeight: "70%" }]}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setShowProductPicker(false)} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
              <Text style={styles.modalTitle}>Pick a product</Text>
              <View style={{ width: 40 }} />
            </View>
            <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
              {products.length === 0 ? (
                <Text style={{ color: colors.textMuted, textAlign: "center", padding: 20 }}>No products yet</Text>
              ) : products.map((p) => (
                <TouchableOpacity key={p.id} style={[styles.productRow, productId === p.id && { borderColor: colors.primary, backgroundColor: colors.brand100 }]} onPress={() => { setProductId(p.id); setShowProductPicker(false); }}>
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
  cardLeft: {},
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
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 6, fontStyle: "italic" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  imagePicker: { width: "100%", aspectRatio: 16/9, borderRadius: 14, borderWidth: 1.5, borderColor: colors.border, borderStyle: "dashed", overflow: "hidden", backgroundColor: colors.surfaceMuted },
  imagePickerEmpty: { flex: 1, alignItems: "center", justifyContent: "center", gap: 4 },
  imagePickerHint: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 4 },
  imagePreview: { width: "100%", height: "100%" },
  typeChoice: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  typeChoiceActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  typeChoiceText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  productRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8, backgroundColor: colors.surface },
  productRowText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
});
