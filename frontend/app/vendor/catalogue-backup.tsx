/**
 * Vendor → Catalogue backup & restore (Phase 4A).
 *
 * Download every product this shop sells into ONE .json file, then upload
 * that file from another vendor login to recreate the whole catalogue there
 * (photos, variants, specs, stock, price) — after which everything is
 * editable / deletable like any other product.
 *
 * Both directions are CHUNKED: product docs carry base64 photos, so a single
 * request with 200 SKUs is tens of MB and the edge proxy drops it. We page
 * through 10 at a time and show real progress.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import { Platform } from "react-native";

import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { downloadText } from "../../src/download";

const EXPORT_FORMAT = "slangcart.vendor-catalogue";
const EXPORT_PAGE = 10;   // products per export request
const IMPORT_PAGE = 5;    // products per import request

type Parsed = { products: any[]; vendorEmail?: string; exportedAt?: string };

export default function VendorCatalogueBackup() {
  const router = useRouter();
  const [busy, setBusy] = useState<"" | "export" | "import">("");
  const [progress, setProgress] = useState("");
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [result, setResult] = useState<string>("");

  // ── Download ────────────────────────────────────────────────────────────
  const onExport = useCallback(async () => {
    setBusy("export"); setResult(""); setProgress("Starting…");
    try {
      const all: any[] = [];
      let offset = 0;
      let meta: any = null;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const r = await api.get<any>("/vendor/me/catalogue/export", { params: { offset, limit: EXPORT_PAGE } });
        const d = r.data || {};
        meta = meta || d;
        all.push(...(d.products || []));
        setProgress(`Packing ${all.length} of ${d.total || all.length} products…`);
        if (!d.has_more) break;
        offset += EXPORT_PAGE;
      }
      if (all.length === 0) {
        Alert.alert("Nothing to back up", "You don't have any products yet.");
        return;
      }
      const file = {
        format: EXPORT_FORMAT,
        version: 1,
        exported_at: meta?.exported_at || new Date().toISOString(),
        vendor: meta?.vendor || null,
        count: all.length,
        products: all,
      };
      const stamp = new Date().toISOString().slice(0, 10);
      const res = await downloadText({
        filename: `slangcart-catalogue-${stamp}.json`,
        content: JSON.stringify(file),
        mimeType: "application/json",
      });
      if (res.ok) setResult(`✅ Backed up ${all.length} product${all.length === 1 ? "" : "s"}.`);
    } catch (e) {
      Alert.alert("Backup failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); }
  }, []);

  // ── Pick a file ─────────────────────────────────────────────────────────
  const onPickFile = useCallback(async () => {
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
        // On web the picker hands back a real File object (and a blob: uri).
        const f: any = (asset as any).file;
        text = f?.text ? await f.text() : await (await fetch(asset.uri)).text();
      } else {
        text = await FileSystem.readAsStringAsync(asset.uri);
      }
      const json = JSON.parse(text);
      const products = Array.isArray(json?.products) ? json.products : Array.isArray(json) ? json : null;
      if (!products) throw new Error("This file doesn't look like a Slangcart catalogue backup.");
      if (json?.format && json.format !== EXPORT_FORMAT) {
        throw new Error(`Unexpected file type: ${json.format}`);
      }
      setParsed({
        products,
        vendorEmail: json?.vendor?.email,
        exportedAt: json?.exported_at,
      });
    } catch (e: any) {
      Alert.alert("Couldn't read the file", e?.message || "Please pick a .json backup file.");
    }
  }, []);

  // ── Restore ─────────────────────────────────────────────────────────────
  const runImport = useCallback(async (mode: "merge" | "replace") => {
    if (!parsed) return;
    setBusy("import"); setResult(""); setProgress("Starting…");
    let created = 0; let wiped = 0; const skipped: string[] = [];
    try {
      for (let i = 0; i < parsed.products.length; i += IMPORT_PAGE) {
        const chunk = parsed.products.slice(i, i + IMPORT_PAGE);
        const r = await api.post<any>("/vendor/me/catalogue/import", {
          products: chunk,
          mode,
          first_chunk: i === 0,
        });
        created += Number(r.data?.created || 0);
        wiped += Number(r.data?.wiped || 0);
        skipped.push(...(r.data?.skipped || []));
        setProgress(`Restoring ${Math.min(i + IMPORT_PAGE, parsed.products.length)} of ${parsed.products.length}…`);
      }
      const lines = [
        `✅ Restored ${created} product${created === 1 ? "" : "s"} as hidden drafts.`,
        wiped ? `🗑 Removed ${wiped} existing product${wiped === 1 ? "" : "s"}.` : "",
        skipped.length ? `⚠️ Skipped ${skipped.length}: ${skipped.slice(0, 3).join(", ")}${skipped.length > 3 ? "…" : ""}` : "",
        "Open Products to edit price / stock. An admin publishes them to the shop.",
      ].filter(Boolean);
      setResult(lines.join("\n"));
      setParsed(null);
    } catch (e) {
      Alert.alert("Restore failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); }
  }, [parsed]);

  const confirmImport = useCallback((mode: "merge" | "replace") => {
    if (!parsed) return;
    if (mode === "merge") { runImport("merge"); return; }
    Alert.alert(
      "Replace my catalogue?",
      "Every product currently in this shop will be deleted first, then the backup is restored. This can't be undone.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete & restore", style: "destructive", onPress: () => runImport("replace") },
      ],
    );
  }, [parsed, runImport]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="backup-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Catalogue backup</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
        {/* Download */}
        <View style={styles.card}>
          <View style={styles.cardHead}>
            <Feather name="download-cloud" size={18} color={colors.primary} />
            <Text style={styles.cardTitle}>Download my catalogue</Text>
          </View>
          <Text style={styles.cardBody}>
            Saves every product — photos, sizes, specs, price and stock — into one
            .json file you can keep or move to another shop login.
          </Text>
          <TouchableOpacity
            onPress={onExport}
            disabled={!!busy}
            style={[styles.primaryBtn, !!busy && { opacity: 0.5 }]}
            testID="catalogue-export"
          >
            {busy === "export"
              ? <ActivityIndicator color={colors.primaryFg} size="small" />
              : <Feather name="download" size={16} color={colors.primaryFg} />}
            <Text style={styles.primaryBtnText}>{busy === "export" ? "Packing…" : "Download backup"}</Text>
          </TouchableOpacity>
        </View>

        {/* Restore */}
        <View style={styles.card}>
          <View style={styles.cardHead}>
            <Feather name="upload-cloud" size={18} color={colors.primary} />
            <Text style={styles.cardTitle}>Restore into this shop</Text>
          </View>
          <Text style={styles.cardBody}>
            Pick a backup file to recreate those products here. They arrive as
            hidden drafts so you can fix price and quantity first; an admin
            publishes them to the shop.
          </Text>
          <TouchableOpacity
            onPress={onPickFile}
            disabled={!!busy}
            style={[styles.secondaryBtn, !!busy && { opacity: 0.5 }]}
            testID="catalogue-pick"
          >
            <Feather name="file-plus" size={16} color={colors.primary} />
            <Text style={styles.secondaryBtnText}>{parsed ? "Choose a different file" : "Choose backup file"}</Text>
          </TouchableOpacity>

          {parsed ? (
            <View style={styles.pickedBox} testID="catalogue-picked">
              <Text style={styles.pickedTitle}>{parsed.products.length} products in this file</Text>
              {parsed.vendorEmail ? <Text style={styles.pickedMeta}>From: {parsed.vendorEmail}</Text> : null}
              {parsed.exportedAt ? <Text style={styles.pickedMeta}>Taken: {new Date(parsed.exportedAt).toLocaleString()}</Text> : null}
              <View style={styles.modeRow}>
                <TouchableOpacity
                  onPress={() => confirmImport("merge")}
                  disabled={!!busy}
                  style={[styles.modeBtn, !!busy && { opacity: 0.5 }]}
                  testID="catalogue-merge"
                >
                  <Feather name="plus-circle" size={15} color={colors.primary} />
                  <Text style={styles.modeBtnTitle}>Merge</Text>
                  <Text style={styles.modeBtnHint}>Add to what I already have</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => confirmImport("replace")}
                  disabled={!!busy}
                  style={[styles.modeBtn, styles.modeBtnDanger, !!busy && { opacity: 0.5 }]}
                  testID="catalogue-replace"
                >
                  <Feather name="refresh-cw" size={15} color="#B3261E" />
                  <Text style={[styles.modeBtnTitle, { color: "#B3261E" }]}>Replace</Text>
                  <Text style={styles.modeBtnHint}>Wipe my products, then restore</Text>
                </TouchableOpacity>
              </View>
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
          <View style={styles.resultBox} testID="catalogue-result">
            <Text style={styles.resultText}>{result}</Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  iconBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  card: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 14,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  cardTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  cardBody: { fontSize: 12.5, color: colors.textMuted, lineHeight: 18, marginBottom: 12 },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, borderRadius: radii.button, minHeight: 46,
  },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
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
  pickedMeta: { fontSize: 11.5, color: colors.textMuted, marginTop: 2 },
  modeRow: { flexDirection: "row", gap: 10, marginTop: 12 },
  modeBtn: {
    flex: 1, alignItems: "center", gap: 2, paddingVertical: 12, paddingHorizontal: 8,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, minHeight: 48,
  },
  modeBtnDanger: { borderColor: "#F3C9C5" },
  modeBtnTitle: { fontSize: 13, fontWeight: "800", color: colors.primary },
  modeBtnHint: { fontSize: 10.5, color: colors.textMuted, textAlign: "center" },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8 },
  progressText: { fontSize: 12.5, color: colors.textMuted },
  resultBox: {
    padding: 12, borderRadius: radii.card, backgroundColor: colors.brand100,
    borderWidth: 1, borderColor: colors.border,
  },
  resultText: { fontSize: 12.5, color: colors.textMain, lineHeight: 19 },
});
