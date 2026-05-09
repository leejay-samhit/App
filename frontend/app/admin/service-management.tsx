/**
 * Admin · Service Application Management
 *
 * Manage the list of service categories that customers see in the grid and
 * that providers pick when applying. Supports:
 *   - Add new category (with icon name + color)
 *   - Edit existing (name, icon, color, sort order)
 *   - Toggle active/inactive (deactivated categories are hidden from users
 *     but past providers stay linked)
 *   - Delete (only when no providers are using it; otherwise auto-deactivates)
 */
import { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Modal,
  Alert,
  Platform,
  KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type Category = {
  id: string;
  name: string;
  slug: string;
  icon: string;
  color: string;
  sort_order: number;
  active: boolean;
  provider_count: number;
};

const ICON_PRESETS = [
  "tool", "wifi", "droplet", "zap", "edit-3", "settings",
  "camera", "wind", "feather", "trash-2", "shield", "home",
  "smartphone", "briefcase", "truck", "scissors", "key",
  "globe", "star", "heart", "package", "phone-call",
];
const COLOR_PRESETS = [
  "#EA580C", "#2563EB", "#0891B2", "#CA8A04", "#9333EA", "#92400E",
  "#475569", "#0EA5E9", "#10B981", "#06B6D4", "#65A30D", "#DC2626",
  "#DB2777", "#7C3AED", "#F59E0B", "#14B8A6",
];

export default function AdminServiceApplicationManagement() {
  const router = useRouter();
  const [items, setItems] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ categories: Category[] }>("/admin/service-categories");
      setItems(r.data.categories || []);
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onToggleActive = async (cat: Category) => {
    try {
      await api.patch(`/admin/service-categories/${cat.id}`, { active: !cat.active });
      await load();
    } catch (e) {
      Alert.alert("Could not update", formatApiError(e));
    }
  };

  const onDelete = (cat: Category) => {
    Alert.alert(
      `Delete "${cat.name}"?`,
      cat.provider_count > 0
        ? `${cat.provider_count} provider${cat.provider_count === 1 ? "" : "s"} use this category. We'll deactivate it instead of deleting so existing providers stay linked.`
        : "This category will be permanently removed.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: cat.provider_count > 0 ? "Deactivate" : "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              const r = await api.delete(`/admin/service-categories/${cat.id}`);
              await load();
              if (r.data?.deactivated) {
                Alert.alert("Deactivated", `Category hidden from users but kept for ${r.data.providers_using} existing provider(s).`);
              }
            } catch (e) {
              Alert.alert("Could not delete", formatApiError(e));
            }
          },
        },
      ],
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
            <Feather name="chevron-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.overline}>ADMIN</Text>
            <Text style={styles.title}>Service Application Management</Text>
          </View>
        </View>

        <Text style={styles.helper}>
          These are the categories customers browse and providers apply under. Add, edit, reorder
          (via Sort #), or deactivate as your service portfolio evolves.
        </Text>

        <TouchableOpacity style={styles.newBtn} onPress={() => setCreating(true)} testID="cat-new">
          <Feather name="plus" size={16} color={colors.primaryFg} />
          <Text style={styles.newBtnText}>  Add new category</Text>
        </TouchableOpacity>

        <View style={styles.viewBookingsRow}>
          <TouchableOpacity
            style={styles.softLinkBtn}
            onPress={() => router.push("/admin/service-applications" as any)}
          >
            <Feather name="clipboard" size={14} color={colors.primary} />
            <Text style={styles.softLinkText}>  Review pending provider applications →</Text>
          </TouchableOpacity>
        </View>

        <Text style={styles.sectionLabel}>{items.length} CATEGORIES</Text>

        {items.length === 0 ? (
          <View style={styles.empty}>
            <Feather name="grid" size={28} color={colors.textMuted} />
            <Text style={styles.emptyText}>No categories yet — add the first one.</Text>
          </View>
        ) : (
          <View style={styles.list}>
            {items.map((c) => (
              <View key={c.id} style={[styles.row, !c.active && { opacity: 0.55 }]}>
                <View style={[styles.iconWrap, { backgroundColor: c.color + "20" }]}>
                  <Feather name={c.icon as any} size={20} color={c.color} />
                </View>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.rowName}>{c.name}</Text>
                    {!c.active ? (
                      <View style={styles.inactiveBadge}>
                        <Text style={styles.inactiveBadgeText}>INACTIVE</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.rowMeta}>
                    {c.slug} · sort #{c.sort_order} · {c.provider_count} provider{c.provider_count === 1 ? "" : "s"}
                  </Text>
                </View>
                <TouchableOpacity onPress={() => onToggleActive(c)} style={styles.iconBtn} testID={`toggle-${c.slug}`}>
                  <Feather name={c.active ? "eye" : "eye-off"} size={16} color={colors.textMuted} />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => setEditing(c)} style={styles.iconBtn} testID={`edit-${c.slug}`}>
                  <Feather name="edit-2" size={16} color={colors.primary} />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => onDelete(c)} style={styles.iconBtn} testID={`del-${c.slug}`}>
                  <Feather name="trash-2" size={16} color={colors.error} />
                </TouchableOpacity>
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      <CategoryEditor
        visible={creating || editing !== null}
        category={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSaved={() => { setCreating(false); setEditing(null); load(); }}
      />
    </SafeAreaView>
  );
}

// ============================================================================
// Editor modal
// ============================================================================
function CategoryEditor({
  visible,
  category,
  onClose,
  onSaved,
}: {
  visible: boolean;
  category: Category | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!category;
  const [name, setName] = useState(category?.name || "");
  const [icon, setIcon] = useState(category?.icon || "briefcase");
  const [color, setColor] = useState(category?.color || "#2563EB");
  const [sortOrder, setSortOrder] = useState(String(category?.sort_order ?? 999));
  const [saving, setSaving] = useState(false);

  // Re-init when opening for a new category / different category
  useFocusEffect(useCallback(() => {}, []));
  // simple: reset every time visible flips on
  // (using key prop on Modal would also work but this keeps things simple)
  // We re-init via a derived effect:
  if (!visible && (name !== "" || icon !== "briefcase")) {
    // skip — will be reset on next open via the Modal's onShow workaround below
  }

  const save = async () => {
    if (!name.trim() || name.trim().length < 2) return Alert.alert("Name required", "At least 2 characters.");
    setSaving(true);
    try {
      const body = {
        name: name.trim(),
        icon: icon || "briefcase",
        color: color || "#2563EB",
        sort_order: Number(sortOrder) || 0,
      };
      if (isEdit && category) {
        await api.patch(`/admin/service-categories/${category.id}`, body);
      } else {
        await api.post("/admin/service-categories", body);
      }
      onSaved();
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      onShow={() => {
        // re-init form from `category` whenever sheet opens
        setName(category?.name || "");
        setIcon(category?.icon || "briefcase");
        setColor(category?.color || "#2563EB");
        setSortOrder(String(category?.sort_order ?? 999));
      }}
    >
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <TouchableOpacity activeOpacity={1} onPress={onClose} style={styles.modalBackdrop}>
          <TouchableOpacity activeOpacity={1} onPress={() => {}} style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>{isEdit ? "Edit category" : "New category"}</Text>

            <ScrollView contentContainerStyle={{ paddingBottom: 20 }} showsVerticalScrollIndicator={false}>
              {/* Live preview */}
              <View style={styles.preview}>
                <View style={[styles.previewIconWrap, { backgroundColor: color + "20" }]}>
                  <Feather name={icon as any} size={28} color={color} />
                </View>
                <Text style={styles.previewName}>{name || "Category name"}</Text>
              </View>

              <Text style={styles.label}>Name</Text>
              <TextInput
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder="e.g. Plumber"
                placeholderTextColor={colors.textMuted}
                maxLength={40}
              />

              <Text style={styles.label}>Icon</Text>
              <View style={styles.pickerGrid}>
                {ICON_PRESETS.map((i) => {
                  const sel = icon === i;
                  return (
                    <TouchableOpacity
                      key={i}
                      onPress={() => setIcon(i)}
                      style={[styles.pickerTile, sel && { borderColor: color, borderWidth: 2 }]}
                    >
                      <Feather name={i as any} size={18} color={sel ? color : colors.textMain} />
                    </TouchableOpacity>
                  );
                })}
              </View>

              <Text style={styles.label}>Color</Text>
              <View style={styles.pickerGrid}>
                {COLOR_PRESETS.map((cl) => {
                  const sel = color === cl;
                  return (
                    <TouchableOpacity
                      key={cl}
                      onPress={() => setColor(cl)}
                      style={[
                        styles.colorTile,
                        { backgroundColor: cl, borderWidth: sel ? 3 : 1, borderColor: sel ? colors.textMain : colors.border },
                      ]}
                    />
                  );
                })}
              </View>

              <Text style={styles.label}>Sort order (lower = appears first)</Text>
              <TextInput
                style={styles.input}
                value={sortOrder}
                onChangeText={setSortOrder}
                keyboardType="numeric"
                placeholder="999"
                placeholderTextColor={colors.textMuted}
              />

              <View style={{ flexDirection: "row", gap: 10, marginTop: 18 }}>
                <TouchableOpacity onPress={onClose} style={styles.cancelBtn}>
                  <Text style={styles.cancelText}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={save} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.6 }]}>
                  {saving ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={styles.saveText}>{isEdit ? "Save changes" : "Create"}</Text>}
                </TouchableOpacity>
              </View>
            </ScrollView>
          </TouchableOpacity>
        </TouchableOpacity>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.lg, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 6 },
  backBtn: { padding: 6 },
  overline: { fontSize: 11, fontWeight: "700", letterSpacing: 1, color: colors.textMuted },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  helper: { color: colors.textMuted, fontSize: 12, marginTop: 6, marginBottom: 16, lineHeight: 17 },
  newBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary,
    borderRadius: radii.button,
    paddingVertical: 13, marginBottom: 8,
  },
  newBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  viewBookingsRow: { marginBottom: 16 },
  softLinkBtn: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 8,
  },
  softLinkText: { color: colors.primary, fontWeight: "700", fontSize: 12 },
  sectionLabel: {
    fontSize: 11, color: colors.textMuted, fontWeight: "800",
    letterSpacing: 1, marginBottom: 8,
  },
  empty: { alignItems: "center", padding: 40, gap: 8 },
  emptyText: { color: colors.textMuted, fontSize: 13 },
  list: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 12, paddingHorizontal: 12,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  iconWrap: {
    width: 40, height: 40, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
  },
  rowName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  rowMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  inactiveBadge: { backgroundColor: "#FEE2E2", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  inactiveBadgeText: { color: "#B91C1C", fontSize: 9, fontWeight: "800", letterSpacing: 0.3 },
  iconBtn: { padding: 8, borderRadius: 8 },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: {
    backgroundColor: colors.bg,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 18, maxHeight: "88%",
  },
  modalHandle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, alignSelf: "center", marginBottom: 14,
  },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain, marginBottom: 8 },
  preview: {
    backgroundColor: colors.surface, borderRadius: radii.lg,
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center", padding: 18, marginBottom: 14,
  },
  previewIconWrap: { width: 60, height: 60, borderRadius: 16, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  previewName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  label: { fontSize: 12, fontWeight: "700", color: colors.textMuted, marginTop: 12, marginBottom: 8, letterSpacing: 0.6 },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 14, color: colors.textMain,
  },
  pickerGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  pickerTile: {
    width: 44, height: 44, borderRadius: 10,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  colorTile: { width: 36, height: 36, borderRadius: 18 },
  cancelBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingVertical: 12, borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted,
  },
  cancelText: { color: colors.textMain, fontWeight: "700" },
  saveBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingVertical: 12, borderRadius: radii.button,
    backgroundColor: colors.primary,
  },
  saveText: { color: colors.primaryFg, fontWeight: "800" },
});
