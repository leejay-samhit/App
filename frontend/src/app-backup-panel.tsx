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
import { downloadPackedBackup, cancelPackedBackup } from "./download";
import { notify } from "./notify";
import { BackupRestoreCard } from "./backup-restore-card";

type Manifest = {
  collections: { name: string; count: number; bytes?: number }[];
  total_documents: number;
  total_bytes?: number;
  skipped: string[];
  generated_at: string;
};

const fmtSize = (b: number) =>
  b >= 1024 * 1024 * 1024 ? `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
    : b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB`
      : `${Math.max(1, Math.round(b / 1024))} KB`;

export function AppBackupPanel() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "download">("");
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState("");
  const [jobId, setJobId] = useState("");

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
  // Nov 2026 — packed on the SERVER in the background (see
  // downloadPackedBackup): no more holding the screen open while a big
  // catalogue streams, and no OutOfMemoryError from stitching ~120 MB in JS.
  const onDownload = useCallback(async () => {
    if (!manifest) return;
    setBusy("download"); setResult(""); setProgress("Packing on the server…");
    try {
      const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
      const res = await downloadPackedBackup({
        scope: "app",
        filename: `slangcart-app-backup-${stamp}.json`,
        onProgress: setProgress,
        onJobStarted: setJobId,
      });
      if (res.ok) {
        const size = res.bytes ? ` (${fmtSize(res.bytes)})` : "";
        const warn = res.warnings?.length
          ? `\n⚠️ ${res.warnings.length} table(s) stopped early: ${res.warnings.join("; ")}`
          : "";
        setResult(
          `✅ Saved ${manifest.total_documents.toLocaleString("en-IN")} records across ` +
          `${manifest.collections.length} collections${size}.${warn}`,
        );
      }
    } catch (e) {
      notify("Backup failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); setJobId(""); }
  }, [manifest]);

  // Prepared files are a download cache, not history — this frees the space
  // they occupy in the database. Production had gigabytes of them.
  const onPurge = useCallback(async () => {
    try {
      const { data } = await api.delete<any>("/admin/backup/file/cache");
      setResult(
        `🧹 Cleared ${data.jobs_removed} prepared file(s) and ${data.chunks_removed} stored pieces from the server.`,
      );
      loadManifest();
    } catch (e) {
      notify("Could not clear", formatApiError(e));
    }
  }, [loadManifest]);

  const onCancel = useCallback(async () => {
    if (!jobId) return;
    try { await cancelPackedBackup(jobId); } catch { /* the poll will report it */ }
    setProgress("Cancelling…");
  }, [jobId]);

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
              {(manifest.total_bytes || 0) > 700 * 1024 * 1024 ? (
                <View style={styles.warnBox} testID="appbackup-size-warning">
                  <Feather name="alert-triangle" size={14} color={colors.warning} />
                  <Text style={styles.warnText}>
                    This database holds about {fmtSize(manifest.total_bytes || 0)} of data, mostly
                    product photos. The packed file will be larger still, so save it somewhere with
                    plenty of free space and keep this screen open on Wi-Fi.
                  </Text>
                </View>
              ) : null}
              <View style={styles.chipsWrap}>
                {manifest.collections.filter((c) => c.count > 0).map((c) => (
                  <View key={c.name} style={styles.chip}>
                    <Text style={styles.chipName}>{c.name}</Text>
                    <Text style={styles.chipCount}>{c.count.toLocaleString("en-IN")}</Text>
                    {c.bytes && c.bytes > 5 * 1024 * 1024
                      ? <Text style={styles.chipSize}>{fmtSize(c.bytes)}</Text>
                      : null}
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
              <TouchableOpacity
                onPress={onPurge}
                disabled={!!busy}
                style={styles.linkBtn}
                testID="appbackup-purge"
              >
                <Feather name="trash-2" size={13} color={colors.textMuted} />
                <Text style={styles.linkText}>Clear prepared backup files from the server</Text>
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
            {jobId ? (
              <TouchableOpacity onPress={onCancel} style={styles.cancelBtn} testID="appbackup-cancel">
                <Text style={styles.cancelText}>Cancel</Text>
              </TouchableOpacity>
            ) : null}
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
  chipSize: { fontSize: 9.5, fontWeight: "700", color: colors.warning },
  warnBox: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: colors.surfaceMuted, borderRadius: radii.card,
    padding: 10, marginBottom: 12,
  },
  warnText: { flex: 1, fontSize: 11.5, color: colors.textMain, lineHeight: 16 },
  cancelBtn: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.button,
    borderWidth: 1, borderColor: colors.border, minHeight: 36, justifyContent: "center",
  },
  cancelText: { fontSize: 12, fontWeight: "800", color: colors.error },
  linkBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 44, marginTop: 4,
  },
  linkText: { fontSize: 11.5, fontWeight: "700", color: colors.textMuted },
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
