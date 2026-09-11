/**
 * "Restore from a file" — shared by Admin → Data backups → File backup and
 * Admin → Danger zone → Reset centre, so a one-account / one-shop backup can
 * be merged back right where it was taken.
 *
 * Accepts the `slangcart.app-backup` envelope (full-app OR per-account scope)
 * and replays it collection by collection, chunked, behind the Danger PIN.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator,
  TextInput, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";

import { api, formatApiError } from "./api";
import { colors, radii } from "./theme";
import { notify } from "./notify";

const APP_FORMAT = "slangcart.app-backup";
/** Image-heavy collections move in small pages so no request is huge. */
const HEAVY = new Set(["products", "products_master_cache", "chat_messages", "offline_sales"]);
const pageFor = (name: string) => (HEAVY.has(name) ? 25 : 200);
/** A phone can't hold a multi-hundred-MB JSON string in memory. */
const NATIVE_MAX_BYTES = 40 * 1024 * 1024;

type Picked = {
  counts: { name: string; count: number }[];
  data: Record<string, any[]>;
  takenAt?: string;
  scope?: string;
  account?: { id?: string; email?: string; name?: string } | null;
};

export function BackupRestoreCard({ onDone }: { onDone?: () => void }) {
  const [file, setFile] = useState<Picked | null>(null);
  const [mode, setMode] = useState<"merge" | "wipe">("merge");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState("");

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
        const info: any = await FileSystem.getInfoAsync(asset.uri, { size: true } as any);
        if (info?.size && info.size > NATIVE_MAX_BYTES) {
          notify(
            "File too large for a phone",
            `This backup is ${(info.size / 1024 / 1024).toFixed(0)} MB. Phones run out of ` +
            `memory reading a file that size — open the admin panel in a browser on a ` +
            `computer and restore it from there. One-account and one-shop backups are ` +
            `small enough to restore here.`,
          );
          return;
        }
        text = await FileSystem.readAsStringAsync(asset.uri);
      }
      const json = JSON.parse(text);
      if (json?.format !== APP_FORMAT) throw new Error("This isn't a Slangcart backup file.");
      const data: Record<string, any[]> = json.collections || {};
      const counts = Object.keys(data).sort().map((name) => ({ name, count: (data[name] || []).length }));
      setFile({ counts, data, takenAt: json.exported_at, scope: json.scope, account: json.account });
    } catch (e: any) {
      notify("Couldn't read the file", e?.message || "Pick a .json backup file.");
    }
  }, []);

  const doRestore = useCallback(async () => {
    if (!file) return;
    setBusy(true); setResult(""); setProgress("Starting…");
    const summary: string[] = [];
    try {
      for (const { name, count } of file.counts) {
        const rows = file.data[name] || [];
        const limit = pageFor(name);
        if (rows.length === 0) {
          // A wipe restore must still clear collections the file has empty —
          // but ONLY for a full-app file. Wiping a whole collection from a
          // single-account backup would delete everyone else's data.
          if (mode === "wipe" && file.scope !== "account") {
            await api.post("/admin/backup/restore", { collection: name, docs: [], mode, first_chunk: true, danger_pin: pin });
          }
          continue;
        }
        let done = 0;
        for (let i = 0; i < rows.length; i += limit) {
          const r = await api.post<any>("/admin/backup/restore", {
            collection: name,
            docs: rows.slice(i, i + limit),
            // An account-scoped file is always merged — see above.
            mode: file.scope === "account" ? "merge" : mode,
            first_chunk: i === 0,
            danger_pin: pin,
          });
          done += (r.data?.inserted || 0) + (r.data?.upserted || 0);
          setProgress(`${name}: ${Math.min(i + limit, rows.length)} / ${rows.length}`);
        }
        summary.push(`${name}: ${done}/${count}`);
      }
      const applied = file.scope === "account" ? "merged back" : (mode === "wipe" ? "wiped & replaced" : "merged");
      setResult(`✅ Restore complete (${applied}).\n${summary.join("\n")}`);
      setFile(null); setPin("");
      onDone?.();
    } catch (e) {
      notify("Restore failed", formatApiError(e));
    } finally { setBusy(false); setProgress(""); }
  }, [file, mode, pin, onDone]);

  const confirmRestore = useCallback(() => {
    if (!file) return;
    if (!/^[0-9]{6}$/.test(pin)) {
      notify("Danger PIN required", "Enter your 6-digit Danger PIN to confirm.");
      return;
    }
    const total = file.counts.reduce((a, c) => a + c.count, 0);
    const accountScoped = file.scope === "account";
    notify(
      accountScoped
        ? "Restore this account?"
        : mode === "wipe" ? "Wipe and replace everything?" : "Merge this backup in?",
      accountScoped
        ? `${total.toLocaleString("en-IN")} records belonging to ${file.account?.email || file.account?.name || "this account"} are added back or updated. Nobody else's data is touched.`
        : mode === "wipe"
          ? `Every record in the collections listed in this file is deleted first, then ${total.toLocaleString("en-IN")} records are restored. This cannot be undone.`
          : `${total.toLocaleString("en-IN")} records are added or updated by id. Existing records not in the file are left alone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: accountScoped ? "Restore account" : mode === "wipe" ? "Wipe & restore" : "Merge",
          style: !accountScoped && mode === "wipe" ? "destructive" : "default",
          onPress: doRestore,
        },
      ],
    );
  }, [file, mode, pin, doRestore]);

  const accountScoped = file?.scope === "account";

  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Feather name="upload-cloud" size={18} color={colors.primary} />
        <Text style={styles.cardTitle}>Restore from a file</Text>
      </View>
      <Text style={styles.cardBody}>
        Works with a full-app backup or a single account / shop backup. Wallet
        balances and history are restored exactly as they appear in the file —
        nothing is recalculated and no payouts are re-triggered.
      </Text>
      <TouchableOpacity onPress={onPick} disabled={busy} style={[styles.secondaryBtn, busy && { opacity: 0.5 }]} testID="appbackup-pick">
        <Feather name="file-plus" size={16} color={colors.primary} />
        <Text style={styles.secondaryBtnText}>{file ? "Choose a different file" : "Choose backup file"}</Text>
      </TouchableOpacity>

      {file ? (
        <View style={styles.pickedBox} testID="appbackup-picked">
          <Text style={styles.pickedTitle}>
            {file.counts.reduce((a, c) => a + c.count, 0).toLocaleString("en-IN")} records in this file
          </Text>
          <Text style={styles.pickedMeta}>
            {accountScoped
              ? `One account / shop · ${file.account?.email || file.account?.name || "unknown"}`
              : "Full app backup"}
            {file.takenAt ? ` · taken ${new Date(file.takenAt).toLocaleString()}` : ""}
          </Text>
          <View style={styles.chipsWrap}>
            {file.counts.filter((c) => c.count > 0).map((c) => (
              <View key={c.name} style={styles.chip}>
                <Text style={styles.chipName}>{c.name}</Text>
                <Text style={styles.chipCount}>{c.count.toLocaleString("en-IN")}</Text>
              </View>
            ))}
          </View>

          {accountScoped ? (
            <Text style={styles.scopeNote}>
              Account backups always MERGE with what&apos;s live now, so restoring one
              customer or one shop can never wipe anybody else.
            </Text>
          ) : (
            <>
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
            </>
          )}

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
            disabled={busy}
            style={[styles.primaryBtn, !accountScoped && mode === "wipe" && { backgroundColor: "#B3261E" }, busy && { opacity: 0.5 }]}
            testID="appbackup-restore"
          >
            {busy
              ? <ActivityIndicator color="#fff" size="small" />
              : <Feather name="rotate-ccw" size={16} color="#fff" />}
            <Text style={styles.primaryBtnText}>
              {accountScoped ? "Restore this account" : mode === "wipe" ? "Wipe & restore" : "Merge into app"}
            </Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {busy ? (
        <View style={styles.progressRow}>
          <ActivityIndicator color={colors.primary} size="small" />
          <Text style={styles.progressText}>{progress}</Text>
        </View>
      ) : null}
      {result ? (
        <View style={styles.resultBox} testID="appbackup-restore-result">
          <Text style={styles.resultText}>{result}</Text>
        </View>
      ) : null}
    </View>
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
    backgroundColor: colors.surface, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6,
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
  scopeNote: { fontSize: 11.5, color: colors.textMuted, lineHeight: 17, marginBottom: 4 },
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
    marginTop: 10, padding: 12, borderRadius: radii.card, backgroundColor: colors.brand100,
    borderWidth: 1, borderColor: colors.border,
  },
  resultText: { fontSize: 12.5, color: colors.textMain, lineHeight: 19 },
});
