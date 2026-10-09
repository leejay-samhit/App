/**
 * Admin → Recharge options.
 *
 * The owner adds and deletes States and Networks for both Mobile and DTH
 * from here, exactly as asked ("Manual Adding Deleting Option for Both").
 * These lists drive the two dropdowns on the customer Recharge screen, so
 * new circles and operators never need a code change.
 *
 * Deletes are soft: products already tagged with an option keep their tag,
 * so re-adding the same name brings the whole list straight back.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Alert, RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { notify } from "../../src/notify";
import { colors, radii, spacing } from "../../src/theme";

type Option = { id: string; name: string; slug: string; kind: string; group: string };

const KINDS = [
  { key: "mobile", label: "Mobile Recharge" },
  { key: "dth", label: "DTH TV Recharge" },
] as const;

export default function AdminRechargeOptions() {
  const router = useRouter();
  const [kind, setKind] = useState<"mobile" | "dth">("mobile");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [draft, setDraft] = useState<{ state: string; network: string }>({ state: "", network: "" });
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get("/recharge/options");
      setData(d);
    } catch (e) {
      notify("Couldn't load options", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const add = async (group: "state" | "network") => {
    const name = draft[group].trim();
    if (name.length < 2) {
      notify("Name too short", "Enter at least 2 characters.");
      return;
    }
    setBusy(`add-${group}`);
    try {
      await api.post("/admin/recharge/options", { kind, group, name });
      setDraft((d) => ({ ...d, [group]: "" }));
      notify("Added", `“${name}” is now available to customers.`);
      load();
    } catch (e) {
      notify("Couldn't add", formatApiError(e));
    } finally {
      setBusy(null);
    }
  };

  const remove = (o: Option) => {
    Alert.alert(
      `Remove “${o.name}”?`,
      "Customers will stop seeing it immediately, and its Recharge sub-category is hidden from the vendor product form. If any product is still listed under it the removal is blocked.",
      [
        { text: "Keep it", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            setBusy(o.id);
            try {
              await api.delete(`/admin/recharge/options/${o.id}`);
              notify("Removed", `“${o.name}” is no longer shown to customers.`);
              load();
            } catch (e) {
              notify("Couldn't remove", formatApiError(e));
            } finally {
              setBusy(null);
            }
          },
        },
      ],
    );
  };

  const section = (group: "state" | "network", title: string, hint: string) => {
    const rows: Option[] = (data?.[kind]?.[group === "state" ? "states" : "networks"] || []);
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>{title}</Text>
        <Text style={styles.cardHint}>{hint}</Text>

        <View style={styles.addRow}>
          <TextInput
            value={draft[group]}
            onChangeText={(v) => setDraft((d) => ({ ...d, [group]: v }))}
            placeholder={group === "state" ? "e.g. Karnataka" : "e.g. Airtel"}
            placeholderTextColor={colors.textMuted}
            style={styles.addInput}
            testID={`recharge-admin-input-${group}`}
          />
          <TouchableOpacity
            onPress={() => add(group)}
            disabled={busy !== null}
            style={[styles.addBtn, busy === `add-${group}` && { opacity: 0.6 }]}
            testID={`recharge-admin-add-${group}`}
          >
            {busy === `add-${group}`
              ? <ActivityIndicator size="small" color={colors.primaryFg} />
              : <Feather name="plus" size={17} color={colors.primaryFg} />}
          </TouchableOpacity>
        </View>

        {rows.length === 0 ? (
          <Text style={styles.empty}>Nothing added yet.</Text>
        ) : rows.map((o) => (
          <View key={o.id} style={styles.optRow} testID={`recharge-admin-opt-${o.slug}`}>
            <Text style={styles.optName} numberOfLines={1}>{o.name}</Text>
            <TouchableOpacity
              onPress={() => remove(o)}
              disabled={busy !== null}
              style={styles.delBtn}
              hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
              testID={`recharge-admin-del-${o.slug}`}
            >
              {busy === o.id
                ? <ActivityIndicator size="small" color={colors.textMuted} />
                : <Feather name="trash-2" size={15} color="#B3261E" />}
            </TouchableOpacity>
          </View>
        ))}
      </View>
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
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="recharge-admin-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>Recharge options</Text>
          <Text style={styles.headerSub}>States & networks shown to customers</Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />
        }
      >
        <View style={styles.kindRow}>
          {KINDS.map((k) => {
            const on = kind === k.key;
            return (
              <TouchableOpacity
                key={k.key}
                onPress={() => setKind(k.key)}
                style={[styles.kindTab, on && styles.kindTabOn]}
                testID={`recharge-admin-kind-${k.key}`}
              >
                <Text style={[styles.kindText, on && { color: colors.primaryFg }]}>{k.label}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {section("state", "States / circles", "Shown in the first dropdown on the Recharge screen.")}
        {section(
          "network", "Networks / operators",
          "Shown in the second dropdown, and mirrored automatically into Shop Categories → Recharge → " +
          (kind === "mobile" ? "Mobile Recharge" : "DTH TV Recharge") +
          ", so vendors can pick the operator when adding a plan.",
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { paddingVertical: 40, alignItems: "center" },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 11,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  backBtn: { padding: 4 },
  headerTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  headerSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 1 },
  kindRow: { flexDirection: "row", gap: 8, marginBottom: 16 },
  kindTab: {
    flex: 1, alignItems: "center", paddingVertical: 11, borderRadius: 11,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  kindTabOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  kindText: { fontSize: 12.5, fontWeight: "900", color: colors.textMuted },
  card: {
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
    padding: 14, marginBottom: 14,
  },
  cardTitle: { fontSize: 14.5, fontWeight: "900", color: colors.textMain, letterSpacing: -0.2 },
  cardHint: { fontSize: 11.5, lineHeight: 16, color: colors.textMuted, marginTop: 3, marginBottom: 12 },
  addRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  addInput: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 12,
    minHeight: 46, fontSize: 14, fontWeight: "700", color: colors.textMain,
  },
  addBtn: {
    width: 48, minHeight: 46, borderRadius: radii.input,
    backgroundColor: colors.primary, alignItems: "center", justifyContent: "center",
  },
  optRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 11, borderTopWidth: 1, borderTopColor: colors.border,
  },
  optName: { flex: 1, fontSize: 13.5, fontWeight: "700", color: colors.textMain },
  delBtn: { padding: 5 },
  empty: { fontSize: 12.5, color: colors.textMuted, paddingVertical: 14, textAlign: "center" },
});
