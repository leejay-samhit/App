/**
 * Admin → Full app backup to a FILE (Phase 4B).
 *
 * Rendered as the "File backup" tab of Admin → Data backups, next to the
 * in-database snapshots, so there is ONE backup screen in the app instead of
 * two competing ones.
 *
 * The existing "Data backups" screen keeps snapshots INSIDE the database,
 * which is useless when the whole environment is replaced (fork → live) or
 * when the owner wants a copy on their own drive. This screen produces one
 * portable .json with every collection — users, products, orders, invoices /
 * POS sales, chat, services, wallet + transactions, layouts, settings — and
 * restores it back with a choice of Wipe & Replace or Merge.
 *
 * Everything is chunked per collection (products carry base64 photos), and a
 * restore is gated behind the same 6-digit Danger PIN as the Danger Zone.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Alert, TextInput, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";

import { api, formatApiError } from "./api";
import { colors, radii, spacing } from "./theme";
import { downloadText } from "./download";

const APP_FORMAT = "slangcart.app-backup";
/** Image-heavy collections move in small pages so no request is huge. */
const HEAVY = new Set(["products", "products_master_cache", "chat_messages", "offline_sales"]);
const pageFor = (name: string) => (HEAVY.has(name) ? 25 : 200);

type Manifest = {
  collections: { name: string; count: number }[];
  total_documents: number;
  skipped: string[];
  generated_at: string;
};

export function AppBackupPanel() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "download" | "restore">("");
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState("");
  const [file, setFile] = useState<{ counts: { name: string; count: number }[]; data: Record<string, any[]>; takenAt?: string } | null>(null);
  const [mode, setMode] = useState<"merge" | "wipe">("merge");
  const [pin, setPin] = useState("");

  const loadManifest = useCallback(async () => {
    try {
      const r = await api.get<Manifest>("/admin/backup/manifest");
      setManifest(r.data);
    } catch (e) {
      Alert.alert("Couldn't read the database", formatApiError(e));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadManifest(); }, [loadManifest]);

  // ── Download the whole app ──────────────────────────────────────────────
  const onDownload = useCallback(async () => {
    if (!manifest) return;
    setBusy("download"); setResult(""); setProgress("Starting…");
    try {
      const out: Record<string, any[]> = {};
      const counts: Record<string, number> = {};
      for (const c of manifest.collections) {
        if (c.count === 0) { out[c.name] = []; counts[c.name] = 0; continue; }
        const limit = pageFor(c.name);
        let offset = 0;
        const rows: any[] = [];
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const r = await api.get<any>("/admin/backup/dump", { params: { collection: c.name, offset, limit } });
          rows.push(...(r.data?.docs || []));
          setProgress(`${c.name}: ${rows.length} / ${c.count}`);
          if (!r.data?.has_more) break;
          offset += limit;
        }
        out[c.name] = rows;
        counts[c.name] = rows.length;
      }
      const payload = {
        format: APP_FORMAT,
        version: 1,
        exported_at: new Date().toISOString(),
        counts,
        collections: out,
      };
      const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
      const res = await downloadText({
        filename: `slangcart-app-backup-${stamp}.json`,
        content: JSON.stringify(payload),
        mimeType: "application/json",
      });
      if (res.ok) {
        const total = Object.values(counts).reduce((a, b) => a + b, 0);
        setResult(`✅ Saved ${total.toLocaleString("en-IN")} records across ${manifest.collections.length} collections.`);
      }
    } catch (e) {
      Alert.alert("Backup failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); }
  }, [manifest]);

  // ── Pick a backup file ──────────────────────────────────────────────────
  const onPick = useCallback(async () => {
    setResult("");
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["application/json", "text/plain", "*/*"],
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (res.canceled) return;
      const asset = res.assets?.[0];
      if (!asset) return;
      let text = "";
      if (Platform.OS === "web") {
        const f: any = (asset as any).file;
        text = f?.text ? await f.text() : await (await fetch(asset.uri)).text();
      } else {
        text = await FileSystem.readAsStringAsync(asset.uri);
      }
      const json = JSON.parse(text);
      if (json?.format !== APP_FORMAT) throw new Error("This isn't a Slangcart full-app backup file.");
      const data: Record<string, any[]> = json.collections || {};
      const counts = Object.keys(data).sort().map((name) => ({ name, count: (data[name] || []).length }));
      setFile({ counts, data, takenAt: json.exported_at });
    } catch (e: any) {
      Alert.alert("Couldn't read the file", e?.message || "Pick a .json backup file.");
    }
  }, []);

  // ── Restore ─────────────────────────────────────────────────────────────
  const doRestore = useCallback(async () => {
    if (!file) return;
    setBusy("restore"); setResult(""); setProgress("Starting…");
    const summary: string[] = [];
    try {
      for (const { name, count } of file.counts) {
        const rows = file.data[name] || [];
        const limit = pageFor(name);
        if (rows.length === 0) {
          // A wipe restore must still clear collections the file has empty.
          if (mode === "wipe") {
            await api.post("/admin/backup/restore", { collection: name, docs: [], mode, first_chunk: true, danger_pin: pin });
          }
          continue;
        }
        let done = 0;
        for (let i = 0; i < rows.length; i += limit) {
          const r = await api.post<any>("/admin/backup/restore", {
            collection: name,
            docs: rows.slice(i, i + limit),
            mode,
            first_chunk: i === 0,
            danger_pin: pin,
          });
          done += (r.data?.inserted || 0) + (r.data?.upserted || 0);
          setProgress(`${name}: ${Math.min(i + limit, rows.length)} / ${rows.length}`);
        }
        summary.push(`${name}: ${done}/${count}`);
      }
      setResult(`✅ Restore complete (${mode === "wipe" ? "wiped & replaced" : "merged"}).\n${summary.join("\n")}`);
      setFile(null); setPin("");
      loadManifest();
    } catch (e) {
      Alert.alert("Restore failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); }
  }, [file, mode, pin, loadManifest]);

  const confirmRestore = useCallback(() => {
    if (!file) return;
    if (!/^[0-9]{6}$/.test(pin)) {
      Alert.alert("Danger PIN required", "Enter your 6-digit Danger PIN to confirm.");
      return;
    }
    const total = file.counts.reduce((a, c) => a + c.count, 0);
    Alert.alert(
      mode === "wipe" ? "Wipe and replace everything?" : "Merge this backup in?",
      mode === "wipe"
        ? `Every record in the collections listed in this file is deleted first, then ${total.toLocaleString("en-IN")} records are restored. This cannot be undone.`
        : `${total.toLocaleString("en-IN")} records are added or updated by id. Existing records not in the file are left alone.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: mode === "wipe" ? "Wipe & restore" : "Merge", style: mode === "wipe" ? "destructive" : "default", onPress: doRestore },
      ],
    );
  }, [file, mode, pin, doRestore]);

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
        {/* Download */}
        <View style={styles.card}>
          <View style={styles.cardHead}>
            <Feather name="download-cloud" size={18} color={colors.primary} />
            <Text style={styles.cardTitle}>Download everything</Text>
          </View>
          {loading ? (
            <ActivityIndicator color={colors.primary} />
          ) : manifest ? (
            <>
              <Text style={styles.cardBody}>
                {manifest.total_documents.toLocaleString("en-IN")} records across{" "}
                {manifest.collections.length} collections — users, products, orders,
                invoices, chat, services, wallet and settings — in one file you can
                restore into a fork or back into live.
              </Text>
              <View style={styles.chipsWrap}>
                {manifest.collections.filter((c) => c.count > 0).map((c) => (
                  <View key={c.name} style={styles.chip}>
                    <Text style={styles.chipName}>{c.name}</Text>
                    <Text style={styles.chipCount}>{c.count.toLocaleString("en-IN")}</Text>
                  </View>
                ))}
              </View>
              <TouchableOpacity
                onPress={onDownload}
                disabled={!!busy}
                style={[styles.primaryBtn, !!busy && { opacity: 0.5 }]}
                testID="appbackup-download"
              >
                {busy === "download"
                  ? <ActivityIndicator color={colors.primaryFg} size="small" />
                  : <Feather name="download" size={16} color={colors.primaryFg} />}
                <Text style={styles.primaryBtnText}>{busy === "download" ? "Packing…" : "Download backup file"}</Text>
              </TouchableOpacity>
            </>
          ) : null}
        </View>

        {/* Restore */}
        <View style={styles.card}>
          <View style={styles.cardHead}>
            <Feather name="upload-cloud" size={18} color={colors.primary} />
            <Text style={styles.cardTitle}>Restore from a file</Text>
          </View>
          <Text style={styles.cardBody}>
            Wallet balances and history are restored exactly as they appear in the
            file — nothing is recalculated and no payouts are re-triggered.
          </Text>
          <TouchableOpacity onPress={onPick} disabled={!!busy} style={[styles.secondaryBtn, !!busy && { opacity: 0.5 }]} testID="appbackup-pick">
            <Feather name="file-plus" size={16} color={colors.primary} />
            <Text style={styles.secondaryBtnText}>{file ? "Choose a different file" : "Choose backup file"}</Text>
          </TouchableOpacity>

          {file ? (
            <View style={styles.pickedBox} testID="appbackup-picked">
              <Text style={styles.pickedTitle}>
                {file.counts.reduce((a, c) => a + c.count, 0).toLocaleString("en-IN")} records in this file
              </Text>
              {file.takenAt ? <Text style={styles.pickedMeta}>Taken: {new Date(file.takenAt).toLocaleString()}</Text> : null}
              <View style={styles.chipsWrap}>
                {file.counts.filter((c) => c.count > 0).map((c) => (
                  <View key={c.name} style={styles.chip}>
                    <Text style={styles.chipName}>{c.name}</Text>
                    <Text style={styles.chipCount}>{c.count.toLocaleString("en-IN")}</Text>
                  </View>
                ))}
              </View>

              <Text style={styles.fieldLabel}>HOW SHOULD IT APPLY?</Text>
              <View style={styles.modeRow}>
                <TouchableOpacity
                  onPress={() => setMode("merge")}
                  style={[styles.modeBtn, mode === "merge" && styles.modeBtnActive]}
                  testID="appbackup-mode-merge"
                >
                  <Feather name="plus-circle" size={15} color={mode === "merge" ? colors.primary : colors.textMuted} />
                  <Text style={[styles.modeBtnTitle, mode !== "merge" && { color: colors.textMuted }]}>Merge</Text>
                  <Text style={styles.modeBtnHint}>Add / update by id, keep the rest</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => setMode("wipe")}
                  style={[styles.modeBtn, mode === "wipe" && styles.modeBtnDanger]}
                  testID="appbackup-mode-wipe"
                >
                  <Feather name="refresh-cw" size={15} color={mode === "wipe" ? "#B3261E" : colors.textMuted} />
                  <Text style={[styles.modeBtnTitle, { color: mode === "wipe" ? "#B3261E" : colors.textMuted }]}>Wipe & replace</Text>
                  <Text style={styles.modeBtnHint}>Delete current data, then restore</Text>
                </TouchableOpacity>
              </View>

              <Text style={styles.fieldLabel}>6-DIGIT DANGER PIN</Text>
              <TextInput
                value={pin}
                onChangeText={(v) => setPin(v.replace(/[^0-9]/g, "").slice(0, 6))}
                secureTextEntry
                keyboardType="number-pad"
                maxLength={6}
                placeholder="••••••"
                placeholderTextColor={colors.textMuted}
                style={styles.pinInput}
                testID="appbackup-pin"
              />
              <TouchableOpacity
                onPress={confirmRestore}
                disabled={!!busy}
                style={[styles.primaryBtn, mode === "wipe" && { backgroundColor: "#B3261E" }, !!busy && { opacity: 0.5 }]}
                testID="appbackup-restore"
              >
                {busy === "restore"
                  ? <ActivityIndicator color="#fff" size="small" />
                  : <Feather name="rotate-ccw" size={16} color="#fff" />}
                <Text style={styles.primaryBtnText}>{mode === "wipe" ? "Wipe & restore" : "Merge into app"}</Text>
              </TouchableOpacity>
            </View>
          ) : null}
        </View>

        {busy ? (
          <View style={styles.progressRow}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={styles.progressText}>{progress}</Text>
          </View>
        ) : null}

        {result ? (
          <View style={styles.resultBox} testID="appbackup-result">
            <Text style={styles.resultText}>{result}</Text>
          </View>
        ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 14,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  cardTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  cardBody: { fontSize: 12.5, color: colors.textMuted, lineHeight: 18, marginBottom: 12 },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 12 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6,
  },
  chipName: { fontSize: 10, color: colors.textMuted },
  chipCount: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, borderRadius: radii.button, minHeight: 46,
  },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  secondaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: radii.button, minHeight: 46,
    borderWidth: 1, borderColor: colors.border,
  },
  secondaryBtnText: { color: colors.primary, fontWeight: "800", fontSize: 14 },
  pickedBox: {
    marginTop: 12, padding: 12, borderRadius: radii.card,
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  pickedTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  pickedMeta: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, marginBottom: 8 },
  fieldLabel: { fontSize: 10.5, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginTop: 6, marginBottom: 6 },
  modeRow: { flexDirection: "row", gap: 10, marginBottom: 4 },
  modeBtn: {
    flex: 1, alignItems: "center", gap: 2, paddingVertical: 12, paddingHorizontal: 8,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, minHeight: 48,
  },
  modeBtnActive: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  modeBtnDanger: { borderColor: "#B3261E", backgroundColor: "#FCE9E5" },
  modeBtnTitle: { fontSize: 12.5, fontWeight: "800", color: colors.primary, textAlign: "center" },
  modeBtnHint: { fontSize: 10, color: colors.textMuted, textAlign: "center" },
  pinInput: {
    backgroundColor: colors.surface, borderRadius: radii.input, borderWidth: 1, borderColor: colors.border,
    paddingVertical: 14, textAlign: "center", letterSpacing: 8, fontWeight: "800",
    fontSize: 20, color: colors.textMain, marginBottom: 12,
  },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8 },
  progressText: { fontSize: 12.5, color: colors.textMuted },
  resultBox: {
    padding: 12, borderRadius: radii.card, backgroundColor: colors.brand100,
    borderWidth: 1, borderColor: colors.border,
  },
  resultText: { fontSize: 12.5, color: colors.textMain, lineHeight: 19 },
});
