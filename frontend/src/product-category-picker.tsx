/**
 * ProductCategoryPicker
 *
 * Compact dropdown for selecting a product category in the admin/vendor
 * product form. Fetches from the admin-managed `/api/shop-categories`
 * endpoint so vendors pick from the same canonical list customers see
 * in the Shop's category strip.
 *
 * Behaviour:
 *  • If the API succeeds → shows ALL active categories as a tap-to-pick
 *    scrollable chip list + a fallback "Custom…" text field.
 *  • If the API fails    → falls back to a plain text input (safe).
 *
 * Why? Currently admin enters category as free text — typos cause
 * inconsistent filters. With this picker, vendor + admin both pick from
 * the same canonical taxonomy, which keeps the shop home filter strip
 * accurate.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, ActivityIndicator,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError } from "./api";
import { colors } from "./theme";

type Cat = {
  id: string;
  name: string;
  slug: string;
  icon_pack?: string;
  icon_name?: string;
  color?: string;
};

type Props = {
  value: string;
  onChange: (next: string) => void;
  testID?: string;
};

export function ProductCategoryPicker({ value, onChange, testID }: Props) {
  const [cats, setCats] = useState<Cat[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [customMode, setCustomMode] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{ items: Cat[] }>("/shop-categories");
      const items = (data?.items || []).slice().sort((a, b) =>
        a.name.localeCompare(b.name),
      );
      setCats(items);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("ProductCategoryPicker /shop-categories failed:", formatApiError(e));
      setCats(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // If the current value isn't in the API list, surface a "Custom" tag so
  // admin doesn't lose their data when editing legacy products.
  const valueInList = useMemo(() => {
    if (!cats) return false;
    return cats.some((c) => c.name.toLowerCase() === (value || "").toLowerCase());
  }, [cats, value]);

  if (loading) {
    return (
      <View style={[styles.box, styles.center]} testID={testID}>
        <ActivityIndicator size="small" color={colors.primary} />
      </View>
    );
  }

  // Hard fallback: plain text input if the API failed entirely.
  if (cats === null) {
    return (
      <TextInput
        value={value}
        onChangeText={onChange}
        placeholder="e.g. Electronics, Fashion"
        placeholderTextColor={colors.textMuted}
        style={styles.input}
        testID={testID}
      />
    );
  }

  if (cats.length === 0) {
    return (
      <View style={styles.box} testID={testID}>
        <Text style={styles.helper}>
          No shop categories yet. Ask an admin to add them in Admin → Shop categories,
          or enter one manually below.
        </Text>
        <TextInput
          value={value}
          onChangeText={onChange}
          placeholder="Category name"
          placeholderTextColor={colors.textMuted}
          style={styles.input}
        />
      </View>
    );
  }

  return (
    <View testID={testID}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.chipRow}
      >
        {cats.map((c) => {
          const active = !customMode && (value || "").toLowerCase() === c.name.toLowerCase();
          return (
            <TouchableOpacity
              key={c.id}
              style={[styles.chip, active && styles.chipActive]}
              onPress={() => {
                setCustomMode(false);
                onChange(c.name);
              }}
              testID={`category-chip-${c.slug}`}
            >
              {active ? <Feather name="check" size={11} color={colors.primaryFg} /> : null}
              <Text style={[styles.chipText, active && styles.chipTextActive]} numberOfLines={1}>{c.name}</Text>
            </TouchableOpacity>
          );
        })}
        <TouchableOpacity
          style={[styles.chip, (customMode || (value && !valueInList)) && styles.chipCustom]}
          onPress={() => setCustomMode(true)}
        >
          <Feather name="edit-3" size={11} color={colors.primary} />
          <Text style={[styles.chipText, { color: colors.primary }]}>Custom…</Text>
        </TouchableOpacity>
      </ScrollView>

      {(customMode || (value && !valueInList)) ? (
        <TextInput
          value={value}
          onChangeText={onChange}
          placeholder="Custom category name"
          placeholderTextColor={colors.textMuted}
          style={[styles.input, { marginTop: 8 }]}
        />
      ) : null}

      <Text style={styles.hint}>
        Tip: Admin → Shop categories controls this list.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 14 },
  helper: { fontSize: 11.5, color: colors.textMuted, lineHeight: 16 },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 14, paddingVertical: 10,
    fontSize: 14, color: colors.textMain, fontWeight: "600",
    minHeight: 44,
  },
  chipRow: { paddingVertical: 4, gap: 6, flexDirection: "row" },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1, borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipCustom: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  chipTextActive: { color: colors.primaryFg },
  hint: { fontSize: 10.5, color: colors.textMuted, marginTop: 6, fontStyle: "italic" },
});
