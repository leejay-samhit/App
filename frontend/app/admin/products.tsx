import { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl, Alert, Modal, TextInput, ScrollView, Switch, Image, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Product = {
  id: string;
  name: string;
  price: number;
  image_url: string;
  description?: string;
  stock?: number;
  category?: string;
  is_published?: boolean;
};

export default function AdminProducts() {
  const router = useRouter();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Product[]>("/admin/products");
      setItems(data);
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
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Products</Text>
        <TouchableOpacity onPress={() => setCreateOpen(true)} style={styles.iconBtn} testID="product-new">
          <Feather name="plus" size={20} color={colors.textMain} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 8 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.card}>
              {item.image_url ? <Image source={{ uri: item.image_url }} style={styles.thumb} /> : <View style={[styles.thumb, { backgroundColor: colors.surfaceMuted }]} />}
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={styles.cardName} numberOfLines={1}>{item.name}</Text>
                  {item.is_published === false && (
                    <View style={styles.draftPill}><Text style={styles.draftPillText}>DRAFT</Text></View>
                  )}
                </View>
                <Text style={styles.cardPrice}>{formatINR(item.price)}</Text>
                <View style={styles.metaRow}>
                  {item.category ? <Meta icon="tag" text={item.category} /> : null}
                  <Meta icon="package" text={`${item.stock ?? 0} in stock`} />
                </View>
              </View>
              <View style={{ flexDirection: "column", gap: 6 }}>
                <TouchableOpacity onPress={() => setEditing(item)} style={styles.editBtn} testID={`product-${item.id}-edit`}>
                  <Feather name="edit-2" size={14} color={colors.textMain} />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => onDelete(item)} style={styles.deleteBtn} testID={`product-${item.id}-delete`}>
                  <Feather name="trash-2" size={14} color="#B3261E" />
                </TouchableOpacity>
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No products yet — tap the + to add one.</Text>}
        />
      )}

      <ProductModal
        visible={createOpen || !!editing}
        existing={editing}
        onClose={() => { setEditing(null); setCreateOpen(false); }}
        onSaved={async () => { setEditing(null); setCreateOpen(false); await load(); }}
      />
    </SafeAreaView>
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
  iconBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, marginBottom: 10 },
  thumb: { width: 64, height: 64, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  cardName: { fontSize: 14, fontWeight: "700", color: colors.textMain, flex: 1 },
  cardPrice: { fontSize: 14, fontWeight: "800", color: colors.primary, marginTop: 2 },
  metaRow: { flexDirection: "row", gap: 10, marginTop: 6 },
  draftPill: { backgroundColor: "#FFF4E5", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  draftPillText: { color: "#7A4A0E", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
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
});
