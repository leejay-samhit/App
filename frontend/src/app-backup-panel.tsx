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
} from "react-native";
import { Feather } from "@expo/vector-icons";

import { api, formatApiError } from "./api";
import { colors, radii, spacing } from "./theme";
import { downloadServerFile } from "./download";
import { notify } from "./notify";
import { BackupRestoreCard } from "./backup-restore-card";

type Manifest = {
  collections: { name: string; count: number }[];
  total_documents: number;
  skipped: string[];
  generated_at: string;
};

export function AppBackupPanel() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "download">("");
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState("");

  const loadManifest = useCallback(async () => {
    try {
      const r = await api.get<Manifest>("/admin/backup/manifest");
      setManifest(r.data);
    } catch (e) {
      notify("Couldn't read the database", formatApiError(e));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadManifest(); }, [loadManifest]);

  // ── Download the whole app ──────────────────────────────────────────────
  // The server streams the finished .json straight to disk (see
  // downloadServerFile) — building it page-by-page in JS used to blow up
  // Android with an OutOfMemoryError on a ~120 MB backup.
  const onDownload = useCallback(async () => {
    if (!manifest) return;
    setBusy("download"); setResult(""); setProgress("Packing on the server…");
    try {
      const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
      const res = await downloadServerFile({
        path: "/admin/backup/file",
        filename: `slangcart-app-backup-${stamp}.json`,
      });
      if (res.ok) {
        const mb = res.bytes ? ` (${(res.bytes / 1024 / 1024).toFixed(1)} MB)` : "";
        setResult(
          `✅ Saved ${manifest.total_documents.toLocaleString("en-IN")} records across ` +
          `${manifest.collections.length} collections${mb}.`,
        );
      }
    } catch (e) {
      notify("Backup failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); }
  }, [manifest]);

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

        {/* Restore — shared with Admin → Reset centre */}
        <BackupRestoreCard onDone={loadManifest} />

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
