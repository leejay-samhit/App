/**
 * Searchable category dropdown (Nov-2026, req 18).
 *
 * Replaces the long chip walls: one compact field that opens a searchable
 * sheet. Used for the main category and, with a different option list, for the
 * subcategory that belongs to it. Values are plain strings, so nothing about
 * the stored category ids or product links changes.
 */
import { useMemo, useState } from "react";
import {
  Modal,
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  Pressable,
  FlatList,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii } from "./theme";

type Props = {
  label?: string;
  value: string;
  options: string[];
  placeholder?: string;
  /** Shown when there is nothing to choose from yet. */
  emptyHint?: string;
  disabled?: boolean;
  /** Lets the user clear the selection from inside the sheet. */
  allowClear?: boolean;
  onChange: (value: string) => void;
  testID?: string;
};

export function CategoryPicker({
  label,
  value,
  options,
  placeholder = "Select",
  emptyHint,
  disabled,
  allowClear = true,
  onChange,
  testID,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.toLowerCase().includes(q));
  }, [options, query]);

  const pick = (opt: string) => {
    onChange(opt);
    setQuery("");
    setOpen(false);
  };

  return (
    <View>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <TouchableOpacity
        onPress={() => !disabled && setOpen(true)}
        style={[styles.field, disabled && styles.fieldDisabled]}
        activeOpacity={0.8}
        testID={testID}
      >
        <Text style={[styles.fieldText, !value && styles.fieldPlaceholder]} numberOfLines={1}>
          {value || (disabled && emptyHint ? emptyHint : placeholder)}
        </Text>
        <Feather name="chevron-down" size={18} color={colors.textMuted} />
      </TouchableOpacity>

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={styles.sheetHandle} />
            <Text style={styles.sheetTitle}>{label || "Select"}</Text>

            <View style={styles.searchRow}>
              <Feather name="search" size={16} color={colors.textMuted} />
              <TextInput
                value={query}
                onChangeText={setQuery}
                placeholder="Search"
                placeholderTextColor={colors.textMuted}
                style={styles.searchInput}
                autoCorrect={false}
                testID={testID ? `${testID}-search` : undefined}
              />
              {query ? (
                <TouchableOpacity onPress={() => setQuery("")} hitSlop={8}>
                  <Feather name="x" size={16} color={colors.textMuted} />
                </TouchableOpacity>
              ) : null}
            </View>

            <FlatList
              data={filtered}
              keyExtractor={(item) => item}
              keyboardShouldPersistTaps="handled"
              style={styles.list}
              ListEmptyComponent={
                <Text style={styles.empty}>
                  {options.length === 0 ? (emptyHint || "Nothing to choose yet") : "No match"}
                </Text>
              }
              renderItem={({ item }) => {
                const active = item.trim().toLowerCase() === value.trim().toLowerCase();
                return (
                  <TouchableOpacity
                    onPress={() => pick(item)}
                    style={styles.row}
                    testID={testID ? `${testID}-option-${item.toLowerCase()}` : undefined}
                  >
                    <Text style={[styles.rowText, active && styles.rowTextActive]} numberOfLines={1}>
                      {item}
                    </Text>
                    {active ? <Feather name="check" size={16} color={colors.primary} /> : null}
                  </TouchableOpacity>
                );
              }}
            />

            {allowClear && value ? (
              <TouchableOpacity
                onPress={() => pick("")}
                style={styles.clearBtn}
                testID={testID ? `${testID}-clear` : undefined}
              >
                <Text style={styles.clearText}>Clear selection</Text>
              </TouchableOpacity>
            ) : null}
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 11, fontWeight: "800", letterSpacing: 0.8, color: colors.textMuted, marginBottom: 6 },
  field: {
    flexDirection: "row", alignItems: "center", gap: 8,
    minHeight: 48, paddingHorizontal: 14, borderRadius: radii.input,
    backgroundColor: colors.surface, borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  fieldDisabled: { opacity: 0.55 },
  fieldText: { flex: 1, fontSize: 14, color: colors.textMain, fontWeight: "600" },
  fieldPlaceholder: { color: colors.textMuted, fontWeight: "500" },
  backdrop: { flex: 1, backgroundColor: "rgba(17,17,17,0.4)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingHorizontal: 16, paddingTop: 10, paddingBottom: 22,
    maxHeight: "78%",
  },
  sheetHandle: {
    alignSelf: "center", width: 40, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginBottom: 10,
  },
  sheetTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginBottom: 10 },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: radii.input,
    paddingHorizontal: 12, minHeight: 44,
  },
  searchInput: { flex: 1, fontSize: 14, color: colors.textMain, paddingVertical: 10 },
  list: { marginTop: 8 },
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  rowText: { flex: 1, fontSize: 14, color: colors.textMain },
  rowTextActive: { fontWeight: "800", color: colors.primary },
  empty: { textAlign: "center", color: colors.textMuted, paddingVertical: 24, fontSize: 13 },
  clearBtn: { alignItems: "center", paddingVertical: 12, marginTop: 4 },
  clearText: { color: colors.error, fontWeight: "700", fontSize: 13 },
});
