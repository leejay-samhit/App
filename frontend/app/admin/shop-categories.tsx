/**
 * Admin · Shop Categories
 *
 * CRUD UI for the customer-facing Shop home category strip + the "All
 * Categories" modal grid + the product-form category dropdown.
 *
 * Admin can:
 *   • Rename a category
 *   • Pick a different MaterialCommunityIcons / Feather / MaterialIcons icon
 *   • Upload a base64 image (takes precedence over the icon)
 *   • Change the soft pastel background colour
 *   • Re-order (sort_order)
 *   • Toggle Active / Delete
 *
 * Backend: /api/admin/shop-categories (CRUD)
 */
import { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, FlatList, TouchableOpacity,
  Modal, TextInput, ActivityIndicator, Alert, Image, Platform,
  KeyboardAvoidingView, Switch, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons, MaterialIcons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type Pack = "feather" | "mci" | "mat";
type Cat = {
  id: string;
  name: string;
  slug: string;
  parent_id?: string | null;
  depth?: number;
  icon_pack: Pack;
  icon_name: string;
  image_url: string | null;
  color: string;
  sort_order: number;
  active: boolean;
};

// ── Icon library available in picker ──────────────────────────────────
// Trimmed to popular shop-related icons. Admin can swap to anything here.
const ICON_LIBRARY: { pack: Pack; name: string; label: string }[] = [
  { pack: "mci", name: "hanger",                  label: "Hanger" },
  { pack: "mci", name: "tshirt-crew",             label: "T-shirt" },
  { pack: "mci", name: "shoe-sneaker",            label: "Sneaker" },
  { pack: "mci", name: "human-male",              label: "Man" },
  { pack: "mci", name: "human-female",            label: "Woman" },
  { pack: "mci", name: "baby-face",               label: "Kids" },
  { pack: "mci", name: "sunglasses",              label: "Accessories" },
  { pack: "mci", name: "watch",                   label: "Watch" },
  { pack: "mci", name: "bag-personal",            label: "Handbag" },
  { pack: "mci", name: "lipstick",                label: "Beauty" },
  { pack: "mci", name: "tv",                      label: "Electronics" },
  { pack: "mci", name: "cellphone",               label: "Mobiles" },
  { pack: "mci", name: "laptop",                  label: "Laptop" },
  { pack: "mci", name: "headphones",              label: "Audio" },
  { pack: "mci", name: "camera",                  label: "Camera" },
  { pack: "mci", name: "sofa",                    label: "Furniture" },
  { pack: "mci", name: "home",                    label: "Home" },
  { pack: "mci", name: "cart",                    label: "Grocery" },
  { pack: "mci", name: "fruit-watermelon",        label: "Fruits" },
  { pack: "mci", name: "robot-happy",             label: "Toys" },
  { pack: "mci", name: "book-open-page-variant",  label: "Books" },
  { pack: "mci", name: "soccer",                  label: "Sports" },
  { pack: "mci", name: "dumbbell",                label: "Fitness" },
  { pack: "mci", name: "heart-pulse",             label: "Health" },
  { pack: "mci", name: "pill",                    label: "Pharmacy" },
  { pack: "mci", name: "dog",                     label: "Pet Care" },
  { pack: "mci", name: "car",                     label: "Auto" },
  { pack: "mci", name: "tools",                   label: "Tools" },
  { pack: "mci", name: "flower",                  label: "Garden" },
  { pack: "mci", name: "food",                    label: "Food" },
  { pack: "mci", name: "coffee",                  label: "Beverages" },
  { pack: "mci", name: "gift",                    label: "Gifts" },
  { pack: "mat", name: "grid-view",               label: "All / Grid" },
  { pack: "feather", name: "shopping-bag",        label: "Bag" },
  { pack: "feather", name: "star",                label: "Star" },
];

// Pastel colour swatches admin can pick from.
const COLOR_SWATCHES = [
  "#FCE7F3", "#DBEAFE", "#FDE68A", "#FEE2E2", "#E0E7FF", "#FFEDD5",
  "#DCFCE7", "#FAE8FF", "#FEF3C7", "#D1FAE5", "#FFE4E6", "#E5E7EB",
  "#E5F2EC", "#F3F4F6",
];

function CatIcon({ pack, name, size, color }: { pack: Pack; name: string; size: number; color: string }) {
  if (pack === "mci") return <MaterialCommunityIcons name={name as any} size={size} color={color} />;
  if (pack === "mat") return <MaterialIcons name={name as any} size={size} color={color} />;
  return <Feather name={name as any} size={size} color={color} />;
}

export default function AdminShopCategories() {
  const router = useRouter();
  const [items, setItems] = useState<Cat[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Cat | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);

  // form fields
  const [fName, setFName] = useState("");
  const [fIconPack, setFIconPack] = useState<Pack>("mci");
  const [fIconName, setFIconName] = useState("shopping-bag");
  const [fImage, setFImage] = useState<string | null>(null);
  const [fColor, setFColor] = useState("#E5F2EC");
  const [fSortOrder, setFSortOrder] = useState<string>("999");
  const [fActive, setFActive] = useState(true);
  // Nov 2026 — parent picker for nested subcategory support.
  const [fParentId, setFParentId] = useState<string | null>(null);
  const [parentPickerOpen, setParentPickerOpen] = useState(false);

  // icon picker modal
  const [iconPickerOpen, setIconPickerOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{ items: Cat[] }>("/admin/shop-categories");
      setItems(data.items || []);
    } catch (e) {
      Alert.alert("Failed to load", formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openCreate = (parentId?: string | null) => {
    setEditing(null);
    setCreating(true);
    setFName("");
    setFIconPack("mci");
    setFIconName("shopping-bag");
    setFImage(null);
    setFColor("#E5F2EC");
    setFSortOrder(String(items.length));
    setFActive(true);
    setFParentId(parentId || null);
  };

  const openEdit = (c: Cat) => {
    setEditing(c);
    setCreating(false);
    setFName(c.name);
    setFIconPack((c.icon_pack as Pack) || "feather");
    setFIconName(c.icon_name || "shopping-bag");
    setFImage(c.image_url || null);
    setFColor(c.color || "#E5F2EC");
    setFSortOrder(String(c.sort_order));
    setFActive(c.active);
    setFParentId(c.parent_id || null);
  };

  const closeForm = () => {
    setEditing(null);
    setCreating(false);
  };

  const pickImage = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("Permission needed", "We need photo library access to upload an icon image.");
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.8,
        allowsEditing: true,
        aspect: [1, 1],
      });
      if (res.canceled || !res.assets || !res.assets[0]) return;
      const asset = res.assets[0];
      // Compress to ~256x256 max — these are tiny circle icons.
      const compressed = await ImageManipulator.manipulateAsync(
        asset.uri,
        [{ resize: { width: 256, height: 256 } }],
        { compress: 0.75, format: ImageManipulator.SaveFormat.JPEG, base64: true },
      );
      const data = `data:image/jpeg;base64,${compressed.base64}`;
      setFImage(data);
    } catch (e) {
      Alert.alert("Couldn't pick image", String(e));
    }
  };

  const onSave = async () => {
    const name = fName.trim();
    if (!name) {
      Alert.alert("Name required", "Please enter a category name.");
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, any> = {
        name,
        icon_pack: fIconPack,
        icon_name: fIconName,
        image_url: fImage,
        color: fColor,
        sort_order: parseInt(fSortOrder || "0", 10) || 0,
        active: fActive,
      };
      // Only include parent_id when explicitly set — the backend
      // treats "field missing" as "keep current parent", and empty
      // string as "move to root".
      body.parent_id = fParentId || "";
      if (editing) {
        await api.put(`/admin/shop-categories/${editing.id}`, body);
      } else {
        await api.post("/admin/shop-categories", body);
      }
      closeForm();
      await load();
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (c: Cat) => {
    Alert.alert(
      `Delete "${c.name}"?`,
      "This will remove the category from the customer Shop and the product form.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await api.delete(`/admin/shop-categories/${c.id}`);
              await load();
            } catch (e) {
              Alert.alert("Delete failed", formatApiError(e));
            }
          },
        },
      ],
    );
  };

  const formOpen = creating || !!editing;

  // ── Nov 2026 — Build a flat, depth-annotated list from the parent
  // graph so children render indented under their parents.  We keep the
  // FlatList (fast + native scroll) rather than a nested SectionList.
  const treeList = useMemo<Cat[]>(() => {
    const byParent = new Map<string, Cat[]>();
    for (const c of items) {
      const key = c.parent_id || "__root__";
      const arr = byParent.get(key) || [];
      arr.push(c);
      byParent.set(key, arr);
    }
    const walk = (parentKey: string, depth: number, out: Cat[]) => {
      const kids = (byParent.get(parentKey) || [])
        .slice()
        .sort((a, b) => (a.sort_order - b.sort_order) || a.name.localeCompare(b.name));
      for (const k of kids) {
        out.push({ ...k, depth });
        walk(k.id, depth + 1, out);
      }
    };
    const out: Cat[] = [];
    walk("__root__", 0, out);
    return out;
  }, [items]);

  // Root categories only — used to populate the parent picker.
  // (Parent picker walks treeList directly; kept as inline eslint stub.)

  const parentName = fParentId
    ? (items.find((c) => c.id === fParentId)?.name || "Unknown")
    : "None (top level)";

  // ── Render ──────────────────────────────────────────────────────────
  if (loading && items.length === 0) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.overline}>ADMIN</Text>
          <Text style={styles.h1}>Shop categories</Text>
        </View>
        <TouchableOpacity onPress={() => openCreate(null)} style={styles.addBtn} testID="add-cat-btn">
          <Feather name="plus" size={20} color={colors.primaryFg} />
        </TouchableOpacity>
      </View>

      <Text style={styles.helper}>
        Categories shown in the customer Shop &ldquo;More&rdquo; grid and used in the product form. Admin
        can rename, change icons or upload an image, reorder, hide or delete them. Tap the
        {" + "}button next to a category to add a subcategory under it.
      </Text>

      <FlatList
        data={treeList}
        keyExtractor={(c) => c.id}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }}
            colors={[colors.primary]}
            tintColor={colors.primary}
          />
        }
        renderItem={({ item: c }) => {
          const depth = c.depth || 0;
          // Nov 2026 — indent children to visually communicate nesting.
          const indentPx = Math.min(depth, 4) * 20;
          return (
            <View style={[styles.row, { marginLeft: indentPx }]}>
              {depth > 0 ? (
                <View style={styles.threadLine} />
              ) : null}
              <View style={[styles.iconCircle, { backgroundColor: c.color }, depth > 0 && { width: 36, height: 36, borderRadius: 18 }]}>
                {c.image_url ? (
                  <Image source={{ uri: c.image_url }} style={styles.iconImg} />
                ) : (
                  <CatIcon pack={c.icon_pack as Pack} name={c.icon_name} size={depth > 0 ? 20 : 26} color={colors.textMain} />
                )}
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>{c.name}</Text>
                  {!c.active && (
                    <View style={styles.hiddenPill}><Text style={styles.hiddenPillText}>HIDDEN</Text></View>
                  )}
                  {depth === 0 ? null : (
                    <View style={styles.subPill}><Text style={styles.subPillText}>SUB · L{depth}</Text></View>
                  )}
                </View>
                <Text style={styles.rowSub} numberOfLines={1}>
                  {c.image_url ? "Custom image" : `${c.icon_pack}:${c.icon_name}`} · order {c.sort_order}
                </Text>
              </View>
              {/* + Add subcategory — quick action to nest under this row */}
              <TouchableOpacity
                onPress={() => openCreate(c.id)}
                style={styles.rowAction}
                testID={`add-sub-${c.slug}`}
                accessibilityLabel="Add subcategory"
              >
                <Feather name="plus" size={16} color={colors.primary} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => openEdit(c)} style={styles.rowAction} testID={`edit-${c.slug}`}>
                <Feather name="edit-2" size={16} color={colors.primary} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => onDelete(c)} style={styles.rowAction} testID={`delete-${c.slug}`}>
                <Feather name="trash-2" size={16} color="#EF4444" />
              </TouchableOpacity>
            </View>
          );
        }}
        ListEmptyComponent={(
          <View style={styles.emptyWrap}>
            <Feather name="grid" size={40} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>No categories yet</Text>
            <Text style={styles.emptySub}>Tap + to add your first category.</Text>
          </View>
        )}
      />

      {/* ── Create / Edit modal ───────────────────────────────────────── */}
      <Modal visible={formOpen} animationType="slide" transparent onRequestClose={closeForm}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalScrim}
        >
          <View style={styles.modalSheet}>
            <View style={styles.modalGrabber} />
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>{editing ? "Edit category" : "New category"}</Text>
              <TouchableOpacity onPress={closeForm} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>

            <ScrollView
              showsVerticalScrollIndicator={false}
              contentContainerStyle={{ paddingBottom: 8 }}
              keyboardShouldPersistTaps="handled"
            >
              {/* Preview */}
              <View style={styles.previewWrap}>
                <View style={[styles.previewCircle, { backgroundColor: fColor }]}>
                  {fImage ? (
                    <Image source={{ uri: fImage }} style={styles.previewImg} />
                  ) : (
                    <CatIcon pack={fIconPack} name={fIconName} size={32} color={colors.textMain} />
                  )}
                </View>
                <Text style={styles.previewLabel} numberOfLines={1}>{fName || "Name…"}</Text>
              </View>

              {/* Name */}
              <Text style={styles.label}>Name</Text>
              <TextInput
                value={fName}
                onChangeText={setFName}
                placeholder="e.g. Sarees"
                placeholderTextColor={colors.textMuted}
                style={styles.input}
                testID="cat-name"
              />

              {/* Nov 2026 — Parent picker for nested subcategories */}
              <Text style={styles.label}>Parent category</Text>
              <TouchableOpacity
                onPress={() => setParentPickerOpen(true)}
                style={styles.parentPicker}
                testID="cat-parent-picker"
              >
                <Feather name={fParentId ? "corner-down-right" : "grid"} size={16} color={colors.textMain} />
                <Text style={styles.parentPickerText} numberOfLines={1}>{parentName}</Text>
                <Feather name="chevron-down" size={16} color={colors.textMuted} />
              </TouchableOpacity>

              {/* Icon source toggle */}
              <Text style={styles.label}>Icon</Text>
              <View style={styles.tabRow}>
                <TouchableOpacity
                  style={[styles.tabBtn, !fImage && styles.tabBtnActive]}
                  onPress={() => setFImage(null)}
                >
                  <Feather name="star" size={13} color={!fImage ? colors.primaryFg : colors.textMain} />
                  <Text style={[styles.tabBtnText, !fImage && styles.tabBtnTextActive]}>Pick icon</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.tabBtn, fImage && styles.tabBtnActive]}
                  onPress={pickImage}
                >
                  <Feather name="image" size={13} color={fImage ? colors.primaryFg : colors.textMain} />
                  <Text style={[styles.tabBtnText, fImage && styles.tabBtnTextActive]}>Upload image</Text>
                </TouchableOpacity>
              </View>

              {!fImage ? (
                <TouchableOpacity
                  style={styles.iconPickerBtn}
                  onPress={() => setIconPickerOpen(true)}
                  testID="open-icon-picker"
                >
                  <View style={styles.iconPickerPreview}>
                    <CatIcon pack={fIconPack} name={fIconName} size={22} color={colors.textMain} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.iconPickerTitle}>{fIconPack}:{fIconName}</Text>
                    <Text style={styles.iconPickerSub}>Tap to change icon</Text>
                  </View>
                  <Feather name="chevron-right" size={18} color={colors.textMuted} />
                </TouchableOpacity>
              ) : (
                <View style={styles.imagePreviewRow}>
                  <Image source={{ uri: fImage }} style={styles.imagePreviewSquare} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.iconPickerTitle}>Custom image uploaded</Text>
                    <Text style={styles.iconPickerSub}>Will be shown instead of an icon.</Text>
                  </View>
                  <TouchableOpacity onPress={() => setFImage(null)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                    <Feather name="x-circle" size={20} color="#EF4444" />
                  </TouchableOpacity>
                </View>
              )}

              {/* Background colour */}
              <Text style={styles.label}>Background colour</Text>
              <View style={styles.swatchRow}>
                {COLOR_SWATCHES.map((c) => (
                  <TouchableOpacity
                    key={c}
                    onPress={() => setFColor(c)}
                    style={[
                      styles.swatch,
                      { backgroundColor: c },
                      fColor === c && styles.swatchActive,
                    ]}
                    testID={`swatch-${c}`}
                  >
                    {fColor === c ? <Feather name="check" size={14} color={colors.textMain} /> : null}
                  </TouchableOpacity>
                ))}
              </View>

              {/* Sort order + Active */}
              <View style={{ flexDirection: "row", gap: 12, marginTop: 4 }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.label}>Sort order</Text>
                  <TextInput
                    value={fSortOrder}
                    onChangeText={setFSortOrder}
                    keyboardType="number-pad"
                    style={styles.input}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.label}>Active</Text>
                  <View style={[styles.input, { flexDirection: "row", alignItems: "center", paddingHorizontal: 12 }]}>
                    <Switch value={fActive} onValueChange={setFActive} />
                    <Text style={{ marginLeft: 8, fontWeight: "700", color: fActive ? colors.success : colors.textMuted }}>
                      {fActive ? "Visible" : "Hidden"}
                    </Text>
                  </View>
                </View>
              </View>
            </ScrollView>

            {/* Footer actions */}
            <View style={styles.modalFooter}>
              <TouchableOpacity style={styles.cancelBtn} onPress={closeForm}>
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveBtn, busy && { opacity: 0.7 }]}
                onPress={onSave}
                disabled={busy}
                testID="save-cat-btn"
              >
                {busy ? (
                  <ActivityIndicator color={colors.primaryFg} />
                ) : (
                  <>
                    <Feather name="check" size={16} color={colors.primaryFg} />
                    <Text style={styles.saveBtnText}>{editing ? "Save" : "Create"}</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ── Icon library picker ────────────────────────────────────── */}
      <Modal
        visible={iconPickerOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setIconPickerOpen(false)}
      >
        <View style={styles.modalScrim}>
          <View style={[styles.modalSheet, { maxHeight: "80%" }]}>
            <View style={styles.modalGrabber} />
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Pick an icon</Text>
              <TouchableOpacity onPress={() => setIconPickerOpen(false)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>

            <ScrollView
              contentContainerStyle={styles.iconGrid}
              showsVerticalScrollIndicator={false}
            >
              {ICON_LIBRARY.map((ic) => {
                const active = fIconPack === ic.pack && fIconName === ic.name;
                return (
                  <TouchableOpacity
                    key={`${ic.pack}-${ic.name}`}
                    style={[styles.iconCell, active && styles.iconCellActive]}
                    onPress={() => {
                      setFIconPack(ic.pack);
                      setFIconName(ic.name);
                      setIconPickerOpen(false);
                    }}
                    testID={`icon-${ic.name}`}
                  >
                    <View style={[styles.iconCellCircle, { backgroundColor: fColor }]}>
                      <CatIcon pack={ic.pack} name={ic.name} size={22} color={colors.textMain} />
                    </View>
                    <Text style={styles.iconCellLabel} numberOfLines={1}>{ic.label}</Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
          </View>
        </View>
      </Modal>
      {/* ── Nov 2026 — Parent category picker ─────────────────────── */}
      <Modal
        visible={parentPickerOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setParentPickerOpen(false)}
      >
        <View style={styles.modalScrim}>
          <View style={[styles.modalSheet, { maxHeight: "72%" }]}>
            <View style={styles.modalGrabber} />
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Pick a parent</Text>
              <TouchableOpacity onPress={() => setParentPickerOpen(false)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                <Feather name="x" size={20} color={colors.textMain} />
              </TouchableOpacity>
            </View>
            <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: 16 }}>
              <TouchableOpacity
                onPress={() => { setFParentId(null); setParentPickerOpen(false); }}
                style={[styles.parentOption, !fParentId && styles.parentOptionActive]}
              >
                <Feather name="grid" size={16} color={colors.primary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.parentOptionText}>None — top-level category</Text>
                  <Text style={styles.parentOptionSub}>Shows in the customer Shop main strip</Text>
                </View>
                {!fParentId ? <Feather name="check" size={16} color={colors.primary} /> : null}
              </TouchableOpacity>
              {treeList
                .filter((c) => c.id !== editing?.id) // can't be your own parent
                .map((c) => {
                  const depth = c.depth || 0;
                  const active = fParentId === c.id;
                  return (
                    <TouchableOpacity
                      key={c.id}
                      onPress={() => { setFParentId(c.id); setParentPickerOpen(false); }}
                      style={[styles.parentOption, active && styles.parentOptionActive, { marginLeft: Math.min(depth, 4) * 16 }]}
                    >
                      <View style={[styles.parentDot, { backgroundColor: c.color }]}>
                        <CatIcon pack={c.icon_pack as Pack} name={c.icon_name} size={14} color={colors.textMain} />
                      </View>
                      <Text style={styles.parentOptionText} numberOfLines={1}>{c.name}</Text>
                      {active ? <Feather name="check" size={16} color={colors.primary} /> : null}
                    </TouchableOpacity>
                  );
                })}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingTop: 6, paddingBottom: 8,
  },
  iconBtn: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  overline: { fontSize: 10, letterSpacing: 1.6, color: colors.textMuted, fontWeight: "800" },
  h1: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.5, marginTop: 2 },
  addBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  helper: {
    fontSize: 12, color: colors.textMuted,
    paddingHorizontal: 16, marginBottom: 12, lineHeight: 17,
  },

  // Rows
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 14, padding: 10,
    marginBottom: 8,
  },
  iconCircle: {
    width: 52, height: 52, borderRadius: 26,
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
  },
  iconImg: { width: 52, height: 52, borderRadius: 26 },
  rowTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  rowSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  hiddenPill: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    backgroundColor: "#FEF3C7",
  },
  hiddenPillText: { fontSize: 9, fontWeight: "900", color: "#92400E", letterSpacing: 0.5 },
  rowAction: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  emptyWrap: { alignItems: "center", paddingVertical: 80, gap: 8 },
  emptyTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain, marginTop: 8 },
  emptySub: { fontSize: 12, color: colors.textMuted },

  // Modal sheet
  modalScrim: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "flex-end",
  },
  modalSheet: {
    backgroundColor: colors.background,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: 18, paddingTop: 10, paddingBottom: 16,
    maxHeight: "92%",
  },
  modalGrabber: {
    alignSelf: "center", width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginBottom: 8,
  },
  modalHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 12,
  },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },

  // Preview
  previewWrap: {
    alignItems: "center", paddingVertical: 6, gap: 8, marginBottom: 4,
  },
  previewCircle: {
    width: 80, height: 80, borderRadius: 40,
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
  },
  previewImg: { width: 80, height: 80, borderRadius: 40 },
  previewLabel: { fontSize: 14, fontWeight: "800", color: colors.textMain },

  // Form fields
  label: { fontSize: 11, fontWeight: "800", color: colors.textMuted, marginTop: 12, marginBottom: 6, letterSpacing: 0.4 },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 14, color: colors.textMain, fontWeight: "600",
    minHeight: 46,
  },
  tabRow: { flexDirection: "row", gap: 8 },
  tabBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 12,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  tabBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabBtnText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  tabBtnTextActive: { color: colors.primaryFg },

  iconPickerBtn: {
    marginTop: 8,
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 12,
  },
  iconPickerPreview: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  iconPickerTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  iconPickerSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },

  imagePreviewRow: {
    marginTop: 8,
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 8,
    borderRadius: 12,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  imagePreviewSquare: { width: 50, height: 50, borderRadius: 10, backgroundColor: colors.surfaceMuted },

  // Colour swatches
  swatchRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  swatch: {
    width: 36, height: 36, borderRadius: 18,
    borderWidth: 2, borderColor: "transparent",
    alignItems: "center", justifyContent: "center",
  },
  swatchActive: { borderColor: colors.primary },

  // Modal footer
  modalFooter: { flexDirection: "row", gap: 10, paddingTop: 12, borderTopWidth: 1, borderTopColor: colors.border, marginTop: 8 },
  cancelBtn: {
    flex: 1, paddingVertical: 13, borderRadius: 12,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  cancelBtnText: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  saveBtn: {
    flex: 2, paddingVertical: 13, borderRadius: 12,
    backgroundColor: colors.primary,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
  },
  saveBtnText: { fontSize: 13.5, fontWeight: "900", color: colors.primaryFg },

  // Icon picker grid (modal)
  iconGrid: {
    flexDirection: "row", flexWrap: "wrap",
    justifyContent: "space-between",
    rowGap: 10, paddingVertical: 6,
  },
  iconCell: {
    flexBasis: "23%",
    alignItems: "center", gap: 4,
    padding: 6,
    borderRadius: 10,
    borderWidth: 1, borderColor: "transparent",
  },
  iconCellActive: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  iconCellCircle: {
    width: 46, height: 46, borderRadius: 23,
    alignItems: "center", justifyContent: "center",
  },
  iconCellLabel: { fontSize: 10, fontWeight: "700", color: colors.textMain, textAlign: "center" },
  // ── Nov 2026 — parent picker + tree-indent styles ─────────────
  parentPicker: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 12, paddingVertical: 12,
    borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    backgroundColor: colors.surface,
  },
  parentPickerText: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.textMain },
  parentOption: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 12, paddingVertical: 10,
    borderRadius: 10,
    marginBottom: 4,
  },
  parentOptionActive: { backgroundColor: colors.brand100 },
  parentOptionText: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.textMain },
  parentOptionSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  parentDot: {
    width: 28, height: 28, borderRadius: 14,
    alignItems: "center", justifyContent: "center",
  },
  threadLine: {
    position: "absolute", left: -12, top: 0, bottom: 0, width: 2,
    backgroundColor: colors.border,
  },
  subPill: {
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4, backgroundColor: colors.brand100,
  },
  subPillText: { fontSize: 9, fontWeight: "900", color: colors.primary, letterSpacing: 0.5 },
});
