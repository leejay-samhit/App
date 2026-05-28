// Admin: Subcategory manager.
// Lists subcategories belonging to a single parent category and supports
// CRUD + bulk reorder via simple up/down arrows (drag-drop on RN-web is
// expensive; arrows give the same outcome with cleaner accessibility).
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView,
  ActivityIndicator, Alert, Modal, KeyboardAvoidingView, Platform, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../../src/api";
import { colors, radii, spacing } from "../../../src/theme";

type Sub = {
  id: string;
  parent_id: string;
  name: string;
  description?: string;
  icon?: string;
  image_b64?: string | null;
  sort_order: number;
  active: boolean;
};

const ICONS = [
  "tool", "droplet", "zap", "settings", "wind", "truck", "package",
  "home", "smartphone", "camera", "shield", "refresh-ccw", "users",
  "feather", "trash-2", "edit-3", "wifi", "clipboard",
];

export default function AdminSubcategories() {
  const router = useRouter();
  const { parentId, parentName } = useLocalSearchParams<{ parentId: string; parentName?: string }>();
  const [items, setItems] = useState<Sub[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Sub | null>(null);
  // Form state
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("tool");
  const [active, setActive] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!parentId) return;
    setLoading(true);
    try {
      const { data } = await api.get<{ items: Sub[] }>(`/admin/service-subcategories?parent_id=${parentId}`);
      setItems(data.items || []);
    } catch (e) {
      Alert.alert("Failed to load", formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [parentId]);

  useEffect(() => { load(); }, [load]);

  const openNew = () => {
    setEditing(null);
    setName(""); setDescription(""); setIcon("tool"); setActive(true);
    setOpen(true);
  };
  const openEdit = (s: Sub) => {
    setEditing(s);
    setName(s.name);
    setDescription(s.description || "");
    setIcon(s.icon || "tool");
    setActive(s.active);
    setOpen(true);
  };

  const save = async () => {
    if (!name.trim()) return Alert.alert("Name required");
    setBusy(true);
    try {
      if (editing) {
        await api.patch(`/admin/service-subcategories/${editing.id}`, {
          name: name.trim(), description: description.trim(), icon, active,
        });
      } else {
        await api.post("/admin/service-subcategories", {
          parent_id: parentId, name: name.trim(), description: description.trim(), icon, active,
        });
      }
      setOpen(false);
      await load();
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = (s: Sub) => {
    Alert.alert("Delete subcategory?", `\"${s.name}\" will be removed.`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          try {
            await api.delete(`/admin/service-subcategories/${s.id}`);
            await load();
          } catch (e) {
            Alert.alert("Delete failed", formatApiError(e));
          }
        },
      },
    ]);
  };

  const move = async (s: Sub, dir: -1 | 1) => {
    const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order);
    const idx = sorted.findIndex((x) => x.id === s.id);
    const nxt = idx + dir;
    if (idx < 0 || nxt < 0 || nxt >= sorted.length) return;
    const a = sorted[idx], b = sorted[nxt];
    const reordered = [
      { id: a.id, sort_order: b.sort_order },
      { id: b.id, sort_order: a.sort_order },
    ];
    setItems((prev) => prev.map((x) => {
      if (x.id === a.id) return { ...x, sort_order: b.sort_order };
      if (x.id === b.id) return { ...x, sort_order: a.sort_order };
      return x;
    }));
    try {
      await api.post("/admin/service-subcategories/reorder", { items: reordered });
    } catch {
      load(); // rollback
    }
  };

  const sorted = [...items].sort((a, b) => a.sort_order - b.sort_order);

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <TouchableOpacity onPress={() => router.back()} style={st.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={st.title} numberOfLines={1}>Subcategories</Text>
          <Text style={st.subtitle} numberOfLines={1}>{parentName || "Category"}</Text>
        </View>
        <TouchableOpacity onPress={openNew} style={st.iconBtn} testID="add-sub">
          <Feather name="plus" size={22} color={colors.primary} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={st.center}><ActivityIndicator color={colors.primary} /></View>
      ) : sorted.length === 0 ? (
        <View style={st.center}>
          <Feather name="layers" size={32} color={colors.textMuted} />
          <Text style={st.empty}>No subcategories yet</Text>
          <TouchableOpacity onPress={openNew} style={st.emptyBtn}>
            <Feather name="plus" size={14} color="#fff" />
            <Text style={st.emptyBtnText}>{" "}Add first subcategory</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
          {sorted.map((s, idx) => (
            <View key={s.id} style={[st.card, !s.active && { opacity: 0.55 }]}>
              <View style={[st.iconBg, { backgroundColor: colors.brand100 }]}>
                <Feather name={(s.icon || "tool") as any} size={18} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={st.cName}>{s.name}{!s.active ? " · DISABLED" : ""}</Text>
                {s.description ? <Text style={st.cDesc} numberOfLines={2}>{s.description}</Text> : null}
              </View>
              <View style={{ alignItems: "center", gap: 2 }}>
                <TouchableOpacity onPress={() => move(s, -1)} disabled={idx === 0} style={[st.arr, idx === 0 && { opacity: 0.3 }]}>
                  <Feather name="chevron-up" size={18} color={colors.textMain} />
                </TouchableOpacity>
                <TouchableOpacity onPress={() => move(s, 1)} disabled={idx === sorted.length - 1} style={[st.arr, idx === sorted.length - 1 && { opacity: 0.3 }]}>
                  <Feather name="chevron-down" size={18} color={colors.textMain} />
                </TouchableOpacity>
              </View>
              <TouchableOpacity onPress={() => openEdit(s)} style={st.cBtn}>
                <Feather name="edit-2" size={16} color={colors.primary} />
              </TouchableOpacity>
              <TouchableOpacity onPress={() => remove(s)} style={st.cBtn}>
                <Feather name="trash-2" size={16} color="#B3261E" />
              </TouchableOpacity>
            </View>
          ))}
        </ScrollView>
      )}

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={st.modalBg}>
          <View style={st.modalSheet}>
            <Text style={st.modalTitle}>{editing ? "Edit subcategory" : "Add subcategory"}</Text>
            <Text style={st.label}>Name</Text>
            <TextInput style={st.input} value={name} onChangeText={setName} placeholder="e.g. AC Repair" placeholderTextColor={colors.textMuted} />
            <Text style={st.label}>Description (optional)</Text>
            <TextInput style={[st.input, { minHeight: 70, textAlignVertical: "top" }]} value={description} onChangeText={setDescription} placeholder="Short description" placeholderTextColor={colors.textMuted} multiline />
            <Text style={st.label}>Icon</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {ICONS.map((ic) => (
                <TouchableOpacity key={ic} onPress={() => setIcon(ic)} style={[st.iconChip, icon === ic && { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                  <Feather name={ic as any} size={16} color={icon === ic ? "#fff" : colors.textMain} />
                </TouchableOpacity>
              ))}
            </View>
            <View style={{ flexDirection: "row", alignItems: "center", marginTop: 14, gap: 10 }}>
              <Switch value={active} onValueChange={setActive} />
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>{active ? "Enabled" : "Disabled"}</Text>
            </View>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 18 }}>
              <TouchableOpacity style={[st.modalBtn, { backgroundColor: colors.surfaceMuted }]} onPress={() => setOpen(false)}>
                <Text style={{ fontWeight: "700", color: colors.textMain }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[st.modalBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]} onPress={save} disabled={busy}>
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ fontWeight: "800", color: "#fff" }}>{editing ? "Save" : "Add"}</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 12, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    gap: 8,
  },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  subtitle: { fontSize: 11, color: colors.textMuted, fontWeight: "700", marginTop: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12, padding: 20 },
  empty: { fontSize: 13, color: colors.textMuted, marginTop: 4 },
  emptyBtn: { flexDirection: "row", paddingHorizontal: 18, paddingVertical: 11, backgroundColor: colors.primary, borderRadius: radii.button, alignItems: "center" },
  emptyBtnText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  card: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, marginBottom: 8, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border },
  iconBg: { width: 40, height: 40, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  cName: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  cDesc: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  cBtn: { width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted },
  arr: { width: 26, height: 22, alignItems: "center", justifyContent: "center" },
  modalBg: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.4)" },
  modalSheet: { backgroundColor: colors.background, padding: 20, borderTopLeftRadius: 24, borderTopRightRadius: 24, maxHeight: "90%" },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginBottom: 12 },
  label: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 14, marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
  iconChip: { width: 40, height: 40, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  modalBtn: { flex: 1, paddingVertical: 13, alignItems: "center", borderRadius: radii.button },
});
