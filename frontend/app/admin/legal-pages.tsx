// Admin screen — edit all 5 legal pages (About, Contact Us, Refund, Privacy, T&C)
// stored in `legal_pages` collection. Plain-text editor (use `## ` for headings).
import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { router } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, spacing } from "../../src/theme";

type Kind = "contact_us" | "refund" | "privacy" | "terms" | "about";
type Page = {
  kind: Kind;
  content_text: string;
  is_default: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
};

const TABS: { kind: Kind; label: string; icon: any }[] = [
  { kind: "about",      label: "About us",     icon: "info" },
  { kind: "contact_us", label: "Contact",      icon: "phone" },
  { kind: "refund",     label: "Refunds",      icon: "rotate-ccw" },
  { kind: "privacy",    label: "Privacy",      icon: "shield" },
  { kind: "terms",      label: "T&C",          icon: "file-text" },
];

export default function AdminLegalEditor() {
  const [pages, setPages] = useState<Record<Kind, Page>>({} as any);
  const [loading, setLoading] = useState(true);
  const [activeKind, setActiveKind] = useState<Kind>("contact_us");
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  // Inline feedback that works on web AND native — Alert.alert() is a no-op
  // in the web preview, which made failed saves look successful there.
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const load = async () => {
    try {
      const { data } = await api.get("/admin/legal");
      const mp: any = {};
      for (const p of data.items || []) mp[p.kind] = p;
      setPages(mp);
      const first = mp[activeKind] || mp.contact_us;
      setDraft((first || {}).content_text || "");
      setDirty(false);
    } catch (e) {
      setNotice({ ok: false, text: formatApiError(e) });
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);

  const switchTab = (k: Kind) => {
    if (dirty) {
      Alert.alert(
        "Discard changes?",
        "You have unsaved edits. Switch tabs and discard them?",
        [
          { text: "Stay", style: "cancel" },
          {
            text: "Discard",
            style: "destructive",
            onPress: () => {
              setActiveKind(k);
              setDraft((pages[k] || {}).content_text || "");
              setDirty(false);
            },
          },
        ],
      );
      return;
    }
    setActiveKind(k);
    setDraft((pages[k] || {}).content_text || "");
  };

  const save = async () => {
    if (draft.trim().length < 10) {
      setNotice({ ok: false, text: "Content must be at least 10 characters." });
      return;
    }
    setSaving(true);
    setNotice(null);
    try {
      await api.put(`/admin/legal/${activeKind}`, { content_text: draft });
      // Update the local copy immediately — the editor must show the saved
      // state at once, not wait for (or be rolled back by) a slow reload.
      const savedText = draft.trim();
      setPages((prev: any) => ({
        ...prev,
        [activeKind]: {
          ...(prev[activeKind] || { kind: activeKind }),
          content_text: savedText,
          is_default: false,
          updated_at: new Date().toISOString(),
        },
      }));
      setDirty(false);
      const label = TABS.find((t) => t.kind === activeKind)?.label;
      setNotice({ ok: true, text: `${label} saved — customers see it immediately.` });
      load(); // reconcile with the server in the background
    } catch (e) {
      setNotice({ ok: false, text: `Save failed: ${formatApiError(e)}` });
    } finally {
      setSaving(false);
    }
  };

  const resetToDefault = async () => {
    Alert.alert(
      "Reset to default?",
      "This removes your custom content and restores the system default for this page.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reset",
          style: "destructive",
          onPress: async () => {
            setNotice(null);
            try {
              // The DELETE endpoint truly removes the custom copy, so the
              // page falls back to the built-in default everywhere.
              await api.delete(`/admin/legal/${activeKind}`);
              setNotice({ ok: true, text: "Default content restored." });
              await load();
            } catch (e) { setNotice({ ok: false, text: formatApiError(e) }); }
          },
        },
      ],
    );
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }
  const activePage = pages[activeKind];

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={22} color={colors.textMain} /></TouchableOpacity>
          <Text style={styles.title}>Legal pages</Text>
          <View style={{ width: 40 }} />
        </View>

        {/* Page picker — a fixed two-row grid (3 + 2) of equal-width buttons
            so the top controls line up cleanly on every screen width. The old
            horizontally-scrolling strip cropped tabs and looked misaligned. */}
        <View style={styles.tabGrid}>
          {TABS.map((t) => {
            const active = t.kind === activeKind;
            const customized = pages[t.kind] && !pages[t.kind].is_default;
            return (
              <TouchableOpacity
                key={t.kind}
                onPress={() => switchTab(t.kind)}
                style={[styles.tab, active && styles.tabActive]}
                testID={`legal-tab-${t.kind}`}
              >
                <Feather name={t.icon} size={14} color={active ? "#fff" : colors.textMain} />
                <Text style={[styles.tabLabel, active && { color: "#fff" }]} numberOfLines={1}>{t.label}</Text>
                {customized && !active ? <View style={styles.tabDot} /> : null}
              </TouchableOpacity>
            );
          })}
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 140 }}>
          {notice ? (
            <View style={[styles.notice, notice.ok ? styles.noticeOk : styles.noticeErr]} testID="legal-notice">
              <Feather name={notice.ok ? "check-circle" : "alert-triangle"} size={14} color={notice.ok ? colors.primary : "#B3261E"} />
              <Text style={[styles.noticeText, { color: notice.ok ? colors.primary : "#B3261E" }]}>{notice.text}</Text>
            </View>
          ) : null}

          {activePage?.is_default ? (
            <View style={styles.defaultBanner}>
              <Feather name="info" size={13} color="#0B66C2" />
              <Text style={styles.defaultBannerText}>Using system default. Edit & save to customize.</Text>
            </View>
          ) : (
            <Text style={styles.metaLine}>
              Last updated {activePage?.updated_at ? new Date(activePage.updated_at).toLocaleString() : "—"}
              {activePage?.updated_by ? ` · by ${activePage.updated_by}` : ""}
            </Text>
          )}

          <Text style={styles.hint}>
            Use plain text. Lines starting with <Text style={{ fontWeight: "900" }}>## </Text> become headings. Press Enter twice for new paragraphs.
          </Text>

          <TextInput
            value={draft}
            onChangeText={(t) => { setDraft(t); setDirty(true); }}
            multiline
            placeholder="Enter content…"
            placeholderTextColor={colors.textMuted}
            style={styles.editor}
            testID="legal-editor"
          />

          <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
            <TouchableOpacity
              onPress={save}
              disabled={saving || !dirty}
              style={[styles.saveBtn, (saving || !dirty) && { opacity: 0.5 }]}
              testID="legal-save"
            >
              <Feather name="save" size={16} color="#fff" />
              <Text style={styles.saveBtnText}>{saving ? "Saving…" : dirty ? "Save changes" : "Up to date"}</Text>
            </TouchableOpacity>
            {!activePage?.is_default ? (
              <TouchableOpacity onPress={resetToDefault} style={styles.resetBtn} testID="legal-reset">
                <Feather name="rotate-ccw" size={14} color="#B85F00" />
                <Text style={styles.resetBtnText}>Reset</Text>
              </TouchableOpacity>
            ) : null}
          </View>

          {/* Preview */}
          <Text style={styles.previewLabel}>PREVIEW</Text>
          <View style={styles.previewBox}>
            {draft.split(/\n\n+/).map((para, idx) => {
              if (para.startsWith("## ")) {
                return <Text key={idx} style={styles.previewH2}>{para.replace(/^##\s+/, "")}</Text>;
              }
              return <Text key={idx} style={styles.previewP}>{para}</Text>;
            })}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  tabGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 10 },
  tab: { flexGrow: 1, flexBasis: "29%", flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 10, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, minHeight: 40 },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabLabel: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  tabDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.success },
  notice: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 10, borderWidth: 1, marginBottom: 10 },
  noticeOk: { backgroundColor: "#E8F5EE", borderColor: "#2E7D5233" },
  noticeErr: { backgroundColor: "#FDECEA", borderColor: "#B3261E33" },
  noticeText: { flex: 1, fontSize: 12, fontWeight: "700" },
  defaultBanner: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#E0F2FE", borderWidth: 1, borderColor: "#0B66C244", padding: 10, borderRadius: 10 },
  defaultBannerText: { flex: 1, fontSize: 12, color: "#0B66C2", fontWeight: "700" },
  metaLine: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 8, fontStyle: "italic" },
  editor: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 12, minHeight: 280, textAlignVertical: "top", fontSize: 13, color: colors.textMain, backgroundColor: colors.surface, marginTop: 8, lineHeight: 18 },
  saveBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.primary, paddingVertical: 12, borderRadius: 999 },
  saveBtnText: { color: "#fff", fontWeight: "900", fontSize: 13 },
  resetBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 999, borderWidth: 1, borderColor: "#B85F0044", backgroundColor: "#FFF7E6" },
  resetBtnText: { color: "#B85F00", fontWeight: "800", fontSize: 12 },
  previewLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "900", letterSpacing: 1, marginTop: 24, marginBottom: 8 },
  previewBox: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 14 },
  previewH2: { fontSize: 15, fontWeight: "900", color: colors.textMain, marginTop: 12, marginBottom: 4 },
  previewP: { fontSize: 13, color: colors.textMain, marginBottom: 8, lineHeight: 19 },
});
