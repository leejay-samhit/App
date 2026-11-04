/**
 * Admin → Reset centre (Sep 2026, owner-specified rework).
 *
 * Replaces the three blind red buttons that used to sit in Admin → More:
 *   • "Wipe all users"        → now RESET ONE ACCOUNT (pick the customer)
 *   • "Reset shop products"   → now RESET ONE VENDOR'S SHOP (pick the vendor)
 *   • "Reset app to zero"     → now a true full-scan wipe of every collection
 *
 * Non-negotiable rule the owner set: nothing is destroyed until the backup
 * FILE has been downloaded to the device. There is no in-app snapshot for
 * these actions and no one-click restore — you restore by uploading the file
 * in Admin → Data backups → File backup. The Reset button literally stays
 * disabled until the download finishes.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { downloadPackedBackup } from "../../src/download";
import { BackupRestoreCard } from "../../src/backup-restore-card";
import { notify } from "../../src/notify";

type Mode = "account" | "vendor" | "app";
type Person = { id: string; name?: string; email?: string; is_vendor?: boolean; shop_name?: string; role?: string };
type Manifest = { collections: { name: string; count: number }[]; total_documents: number; account?: any };


export default function AdminResetCenter() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("account");

  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [searching, setSearching] = useState(false);
  const [picked, setPicked] = useState<Person | null>(null);

  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [busy, setBusy] = useState<"" | "download" | "reset">("");
  const [progress, setProgress] = useState("");
  const [pin, setPin] = useState("");
  const [phrase, setPhrase] = useState("");
  const [result, setResult] = useState("");

  /** Any change of target invalidates the "backup downloaded" gate. */
  const resetGate = () => { setDownloaded(false); setResult(""); setManifest(null); };

  const search = useCallback(async () => {
    setSearching(true);
    try {
      const { data } = await api.get<any>("/admin/users", { params: { q: query.trim(), limit: 25 } });
      const rows: Person[] = Array.isArray(data) ? data : (data?.users || data?.items || []);
      setPeople(mode === "vendor" ? rows.filter((r) => r.is_vendor) : rows);
    } catch (e) {
      notify("Search failed", formatApiError(e));
    } finally { setSearching(false); }
  }, [query, mode]);

  useEffect(() => { if (mode !== "app") search(); }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadManifest = useCallback(async () => {
    setLoadingManifest(true);
    try {
      const url = mode === "app"
        ? "/admin/backup/manifest"
        : `/admin/backup/account/${picked?.id}/manifest`;
      const { data } = await api.get<Manifest>(url);
      setManifest(data);
    } catch (e) {
      notify("Couldn't read the data", formatApiError(e));
    } finally { setLoadingManifest(false); }
  }, [mode, picked]);

  useEffect(() => {
    if (mode === "app" || picked) loadManifest();
  }, [mode, picked, loadManifest]);

  // ── Mandatory backup download ───────────────────────────────────────────
  // Nov 2026 — the file is now PACKED ON THE SERVER as a background job
  // (POST /admin/backup/file/prepare), so a big catalogue no longer means
  // holding the screen open: the pack keeps running even if you leave the
  // app, the progress text shows real collections + MB, and the finished
  // file then downloads in seconds.
  const onDownload = useCallback(async () => {
    if (!manifest) return;
    setBusy("download"); setResult("");
    try {
      const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
      const label = mode === "app"
        ? "app"
        : (picked?.email || picked?.id || "account").replace(/[^a-zA-Z0-9]/g, "-");
      const filename = `slangcart-${mode === "app" ? "full" : "account"}-backup-${label}-${stamp}.json`;

      setProgress("Starting the server-side pack…");
      const res = await downloadPackedBackup({
        scope: mode === "app" ? "app" : "account",
        userId: mode === "app" ? undefined : picked?.id,
        filename,
        onProgress: (m) => setProgress(`${m}\n(you can leave the app — it keeps running)`),
      });
      if (res.ok) {
        setDownloaded(true);
        const mb = res.bytes ? ` (${(res.bytes / 1024 / 1024).toFixed(1)} MB)` : "";
        setResult(
          `✅ Backup saved — ${manifest.total_documents.toLocaleString("en-IN")} records${mb}. ` +
          `Restore it any time from the Restore card below.`,
        );
      }
    } catch (e) {
      notify("Backup failed", formatApiError(e));
    } finally { setBusy(""); setProgress(""); }
  }, [manifest, mode, picked]);

  // ── Destructive actions ─────────────────────────────────────────────────
  const runReset = useCallback(async (accountMode?: "clear" | "delete") => {
    setBusy("reset"); setResult("");
    try {
      let data: any;
      if (mode === "app") {
        ({ data } = await api.post("/admin/system/wipe-all", {
          danger_pin: pin, confirm_phrase: phrase.trim().toUpperCase(), backup_downloaded: true,
        }));
      } else if (mode === "vendor") {
        ({ data } = await api.post("/admin/system/reset-shop-products", {
          danger_pin: pin, vendor_id: picked?.id, backup_downloaded: true,
        }));
      } else {
        ({ data } = await api.post("/admin/system/account-reset", {
          danger_pin: pin, user_id: picked?.id, mode: accountMode || "clear", backup_downloaded: true,
        }));
      }
      const s = data?.summary || {};
      const total = Object.values(s).reduce((a: number, b: any) => a + (Number(b) || 0), 0);
      setResult(`✅ Done — ${total.toLocaleString("en-IN")} records cleared.\n${Object.entries(s).slice(0, 8).map(([k, v]) => `• ${k.replace(/_/g, " ")}: ${v}`).join("\n")}`);
      setPin(""); setPhrase(""); setDownloaded(false);
      loadManifest();
    } catch (e) {
      notify("Reset failed", formatApiError(e));
    } finally { setBusy(""); }
  }, [mode, pin, phrase, picked, loadManifest]);

  const confirmReset = useCallback((accountMode?: "clear" | "delete") => {
    if (!/^[0-9]{6}$/.test(pin)) { notify("Danger PIN required", "Enter your 6-digit Danger PIN."); return; }
    if (!downloaded) { notify("Download the backup first", "The reset stays locked until the backup file is on your device."); return; }
    if (mode === "app" && phrase.trim().toUpperCase() !== "RESET") {
      notify("Type RESET", 'Please type RESET (capitals) to confirm a full wipe.');
      return;
    }
    const who = mode === "app" ? "the entire app" : (picked?.name || picked?.email || "this account");
    notify(
      mode === "app" ? "Reset app to zero?" : accountMode === "delete" ? "Delete this account?" : mode === "vendor" ? "Clear this shop?" : "Clear this account's data?",
      mode === "app"
        ? "Every record in every table is deleted. Only your settings, branding and this super-admin login survive. This cannot be undone."
        : `All data linked to ${who} is deleted${accountMode === "delete" ? ", and the login is removed" : ""}. This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Yes, reset", style: "destructive", onPress: () => runReset(accountMode) },
      ],
    );
  }, [pin, phrase, downloaded, mode, picked, runReset]);

  const targetReady = mode === "app" || !!picked;
  const chips = useMemo(() => (manifest?.collections || []).filter((c) => c.count > 0), [manifest]);

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} style={s.iconBtn} testID="reset-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={s.title}>Reset centre</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
        <View style={s.tabs}>
          {([
            { k: "account", l: "One account", i: "user" as const },
            { k: "vendor", l: "One shop", i: "shopping-bag" as const },
            { k: "app", l: "Whole app", i: "alert-octagon" as const },
          ]).map((t) => (
            <TouchableOpacity
              key={t.k}
              onPress={() => { setMode(t.k as Mode); setPicked(null); resetGate(); setPin(""); setPhrase(""); }}
              style={[s.tab, mode === t.k && (t.k === "app" ? s.tabDanger : s.tabActive)]}
              testID={`reset-tab-${t.k}`}
            >
              <Feather name={t.i} size={14} color={mode === t.k ? (t.k === "app" ? "#B3261E" : colors.primary) : colors.textMuted} />
              <Text style={[s.tabText, mode === t.k && { color: t.k === "app" ? "#B3261E" : colors.primary }]}>{t.l}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* 1 — pick the target */}
        {mode !== "app" ? (
          <View style={s.card}>
            <Text style={s.step}>STEP 1 · CHOOSE {mode === "vendor" ? "A SHOP" : "AN ACCOUNT"}</Text>
            <View style={s.searchRow}>
              <TextInput
                value={query}
                onChangeText={setQuery}
                onSubmitEditing={search}
                placeholder="Search name, email or phone"
                placeholderTextColor={colors.textMuted}
                style={s.input}
                testID="reset-search"
              />
              <TouchableOpacity onPress={search} style={s.searchBtn} testID="reset-search-btn">
                {searching ? <ActivityIndicator color="#fff" size="small" /> : <Feather name="search" size={16} color="#fff" />}
              </TouchableOpacity>
            </View>
            {picked ? (
              <View style={s.pickedRow} testID="reset-picked">
                <Feather name="check-circle" size={16} color={colors.primary} />
                <View style={{ flex: 1 }}>
                  <Text style={s.personName}>{picked.name || "Unnamed"}{picked.is_vendor ? "  ·  vendor" : ""}</Text>
                  <Text style={s.personMeta}>{picked.email}</Text>
                </View>
                <TouchableOpacity onPress={() => { setPicked(null); resetGate(); }} style={s.changeBtn}>
                  <Text style={s.changeBtnText}>Change</Text>
                </TouchableOpacity>
              </View>
            ) : (
              people.slice(0, 12).map((p) => (
                <TouchableOpacity key={p.id} onPress={() => { setPicked(p); resetGate(); }} style={s.personRow} testID={`reset-person-${p.id}`}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.personName}>{p.name || "Unnamed"}{p.is_vendor ? "  ·  vendor" : ""}</Text>
                    <Text style={s.personMeta}>{p.email}</Text>
                  </View>
                  <Feather name="chevron-right" size={16} color={colors.textMuted} />
                </TouchableOpacity>
              ))
            )}
            {!picked && !people.length && !searching ? <Text style={s.personMeta}>No matches yet — search above.</Text> : null}
          </View>
        ) : (
          <View style={[s.card, s.cardDanger]}>
            <Text style={[s.step, { color: "#B3261E" }]}>DANGER · WHOLE APP</Text>
            <Text style={s.body}>
              Clears every table in the database — users, products, orders, invoices,
              chat, services, wallets and ledgers. Your settings, branding and this
              super-admin login are kept so you can log back in.
            </Text>
          </View>
        )}

        {/* 2 — mandatory backup */}
        {targetReady ? (
          <View style={s.card}>
            <Text style={s.step}>STEP 2 · DOWNLOAD THE BACKUP {downloaded ? "✅" : "(REQUIRED)"}</Text>
            {loadingManifest ? <ActivityIndicator color={colors.primary} /> : manifest ? (
              <>
                <Text style={s.body}>
                  {manifest.total_documents.toLocaleString("en-IN")} records will be saved to a
                  .json file on this device. Restore it from the Restore card at the bottom of this screen.
                </Text>
                <View style={s.chipsWrap}>
                  {chips.map((c) => (
                    <View key={c.name} style={s.chip}>
                      <Text style={s.chipName}>{c.name}</Text>
                      <Text style={s.chipCount}>{c.count}</Text>
                    </View>
                  ))}
                  {!chips.length ? <Text style={s.personMeta}>Nothing stored for this target.</Text> : null}
                </View>
                <TouchableOpacity
                  onPress={onDownload}
                  disabled={!!busy || !chips.length}
                  style={[s.primaryBtn, (!!busy || !chips.length) && { opacity: 0.5 }]}
                  testID="reset-download"
                >
                  {busy === "download" ? <ActivityIndicator color="#fff" size="small" /> : <Feather name="download" size={16} color="#fff" />}
                  <Text style={s.primaryBtnText}>{downloaded ? "Download again" : "Download backup"}</Text>
                </TouchableOpacity>
              </>
            ) : null}
          </View>
        ) : null}

        {/* 3 — confirm + wipe */}
        {targetReady && downloaded ? (
          <View style={[s.card, s.cardDanger]}>
            <Text style={[s.step, { color: "#B3261E" }]}>STEP 3 · CONFIRM</Text>
            <Text style={s.label}>6-DIGIT DANGER PIN</Text>
            <TextInput
              value={pin}
              onChangeText={(v) => setPin(v.replace(/[^0-9]/g, "").slice(0, 6))}
              secureTextEntry
              keyboardType="number-pad"
              maxLength={6}
              placeholder="••••••"
              placeholderTextColor={colors.textMuted}
              style={s.pinInput}
              testID="reset-pin"
            />
            {mode === "app" ? (
              <>
                <Text style={s.label}>TYPE “RESET” TO CONFIRM</Text>
                <TextInput
                  value={phrase}
                  onChangeText={setPhrase}
                  autoCapitalize="characters"
                  placeholder="RESET"
                  placeholderTextColor={colors.textMuted}
                  style={s.input}
                  testID="reset-phrase"
                />
              </>
            ) : null}

            {mode === "account" ? (
              <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
                <TouchableOpacity onPress={() => confirmReset("clear")} disabled={!!busy} style={[s.dangerBtn, !!busy && { opacity: 0.5 }]} testID="reset-clear-data">
                  <Feather name="rotate-ccw" size={15} color="#fff" />
                  <Text style={s.dangerBtnText}>Clear data</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => confirmReset("delete")} disabled={!!busy} style={[s.dangerBtn, { backgroundColor: "#7F1D1D" }, !!busy && { opacity: 0.5 }]} testID="reset-delete-user">
                  <Feather name="trash-2" size={15} color="#fff" />
                  <Text style={s.dangerBtnText}>Delete user</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <TouchableOpacity onPress={() => confirmReset()} disabled={!!busy} style={[s.dangerBtn, { marginTop: 12 }, !!busy && { opacity: 0.5 }]} testID="reset-confirm">
                {busy === "reset" ? <ActivityIndicator color="#fff" size="small" /> : <Feather name="alert-triangle" size={15} color="#fff" />}
                <Text style={s.dangerBtnText}>{mode === "app" ? "Reset app to zero" : "Clear this shop"}</Text>
              </TouchableOpacity>
            )}
          </View>
        ) : null}

        {busy ? (
          <View style={s.progressRow}>
            <ActivityIndicator color={colors.primary} size="small" />
            <Text style={s.body}>{progress || "Working…"}</Text>
          </View>
        ) : null}

        {/* Restore — same card as Data backups → File backup, so a
            one-account / one-shop backup can be merged back right here. */}
        <Text style={[s.step, { marginTop: 8 }]}>RESTORE A BACKUP</Text>
        <BackupRestoreCard onDone={loadManifest} />

        {result ? (
          <View style={s.resultBox} testID="reset-result">
            <Text style={s.body}>{result}</Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.screen, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "800", color: colors.textMain },
  tabs: { flexDirection: "row", gap: 8, marginBottom: 14 },
  tab: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 44, borderRadius: radii.button, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface, paddingHorizontal: 6,
  },
  tabActive: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  tabDanger: { borderColor: "#B3261E", backgroundColor: "#FCE9E5" },
  tabText: { fontSize: 12, fontWeight: "800", color: colors.textMuted },
  card: {
    backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1,
    borderColor: colors.border, padding: 16, marginBottom: 14, gap: 8,
  },
  cardDanger: { borderColor: "#F3C9C5", backgroundColor: "#FFF8F7" },
  step: { fontSize: 10, fontWeight: "900", letterSpacing: 1.1, color: colors.textMuted },
  body: { fontSize: 12.5, color: colors.textMain, lineHeight: 19 },
  label: { fontSize: 10, fontWeight: "900", letterSpacing: 1, color: colors.textMuted, marginTop: 8 },
  searchRow: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: {
    flex: 1, minHeight: 46, borderRadius: radii.input, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceMuted, paddingHorizontal: 12, fontSize: 14, color: colors.textMain,
  },
  searchBtn: {
    width: 48, minHeight: 46, borderRadius: radii.button, backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  personRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 11,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  pickedRow: {
    flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: 12,
    backgroundColor: colors.brand100, borderWidth: 1, borderColor: colors.primary,
  },
  personName: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  personMeta: { fontSize: 11.5, color: colors.textMuted, marginTop: 1 },
  changeBtn: { paddingHorizontal: 12, minHeight: 36, justifyContent: "center" },
  changeBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginVertical: 4 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.surfaceMuted,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6,
  },
  chipName: { fontSize: 10, color: colors.textMuted },
  chipCount: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button, backgroundColor: colors.primary, marginTop: 4,
  },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  pinInput: {
    minHeight: 48, borderRadius: radii.input, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface, textAlign: "center", letterSpacing: 8,
    fontSize: 20, fontWeight: "800", color: colors.textMain,
  },
  dangerBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 48, borderRadius: radii.button, backgroundColor: "#B3261E",
  },
  dangerBtnText: { color: "#fff", fontWeight: "900", fontSize: 13.5 },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6 },
  resultBox: {
    padding: 12, borderRadius: 14, backgroundColor: colors.brand100,
    borderWidth: 1, borderColor: colors.border,
  },
});
