import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity,
  Modal, TextInput, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { AppBackupPanel } from "../../src/app-backup-panel";
import { colors, radii, spacing } from "../../src/theme";
import { useTabSwipe } from "../../src/use-swipe-pager";

type Backup = {
  id: string;
  kind: "auto" | "manual";
  note?: string | null;
  created_by?: string | null;
  created_at: string;
  counts: Record<string, number>;
};

export default function AdminBackups() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = ((user as any)?.admin_role || "super_admin") === "super_admin";
  // Jun 2026 — ONE backup screen. "File" is the portable .json download /
  // restore (works across forks and environments); "Snapshots" is the
  // in-database auto-history. They used to be two separate screens, which is
  // why taking a backup here looked like it did nothing useful.
  const [tab, setTab] = useState<"file" | "snapshots">("file");
const swipe = useTabSwipe(["file", "snapshots"] as const, tab, setTab);

  const [items, setItems] = useState<Backup[]>([]);
  const [meta, setMeta] = useState<{ interval_seconds: number; retention: number; auto_retention?: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  // Manual snapshot modal
  const [manualOpen, setManualOpen] = useState(false);
  const [note, setNote] = useState("");

  // Restore modal
  const [restoreFor, setRestoreFor] = useState<Backup | null>(null);
  const [restorePin, setRestorePin] = useState("");
  const isPin = (p: string) => /^[0-9]{6}$/.test(p);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ backups: Backup[]; interval_seconds: number; retention: number; auto_retention?: number }>("/admin/backups");
      setItems(data.backups);
      setMeta({ interval_seconds: data.interval_seconds, retention: data.retention, auto_retention: data.auto_retention });
    } catch (e) {
      Alert.alert("Error", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onTakeSnapshot = async () => {
    setBusy("manual");
    try {
      await api.post("/admin/backups", { note: note.trim() || undefined });
      setManualOpen(false);
      setNote("");
      await load();
      Alert.alert("Snapshot taken", "Database state has been captured successfully.");
    } catch (e) {
      Alert.alert("Snapshot failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  // Nov-2026 — production had accumulated 1,160 auto snapshots because every
  // admin user-deletion used to take a full-database copy first. That is gone;
  // this reclaims the space those copies still occupy.
  const onPurgeOld = async () => {
    Alert.alert(
      "Clean up old snapshots?",
      "The 10 newest snapshots are kept. Everything older is removed along with its stored data.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Clean up",
          style: "destructive",
          onPress: async () => {
            setBusy("purge");
            try {
              const { data } = await api.post<{ snapshots_removed: number; chunks_removed: number }>(
                "/admin/backups/purge-old?keep=10", {},
              );
              await load();
              Alert.alert(
                "Clean-up done",
                `Removed ${data.snapshots_removed} old snapshot${data.snapshots_removed === 1 ? "" : "s"}.`,
              );
            } catch (e) {
              Alert.alert("Clean-up failed", formatApiError(e));
            } finally { setBusy(null); }
          },
        },
      ],
    );
  };

  const onRestore = async () => {
    if (!restoreFor) return;
    if (!isPin(restorePin)) {
      Alert.alert("Invalid PIN", "Enter your 6-digit Danger PIN to confirm.");
      return;
    }
    setBusy(restoreFor.id);
    try {
      // Nov 2026 — the restore now runs as a server-side JOB: a full replay
      // can outlive the request timeout (which surfaced as a bare "500"),
      // so we start the job, then poll until it reports done.
      const { data: started } = await api.post(`/admin/backups/${restoreFor.id}/restore`, {
        danger_pin: restorePin,
      });
      let job: any = null;
      for (let tries = 0; tries < 600; tries++) { // up to ~20 min
        await new Promise((r) => setTimeout(r, 2000));
        try {
          const { data } = await api.get(`/admin/backups/restore-jobs/${started.job_id}`);
          job = data;
          if (data.status === "done" || data.status === "failed") break;
        } catch {
          // transient blip — keep polling
        }
      }
      setRestoreFor(null);
      setRestorePin("");
      await load();
      if (!job || job.status !== "done") {
        Alert.alert("Restore failed", job?.error || "The restore did not finish. Please try again.");
        return;
      }
      const restoredLines = Object.entries((job.restored || {}) as Record<string, number>)
        .slice(0, 12).map(([k, v]) => `• ${k}: ${v}`).join("\n");
      const failed = Object.entries((job.failed || {}) as Record<string, string>);
      Alert.alert(
        failed.length ? "Restore finished with warnings" : "Restore complete",
        `Restored ${Object.keys(job.restored || {}).length} tables` +
        (failed.length ? `, ${failed.length} failed:\n${failed.slice(0, 5).map(([k, v]) => `⚠️ ${k}: ${v}`).join("\n")}` : "") +
        `\n\n${restoredLines}\n\nYou may need to refresh other screens.`,
      );
    } catch (e) {
      Alert.alert("Restore failed", formatApiError(e));
    } finally { setBusy(null); }
  };

  const onDelete = (b: Backup) => {
    Alert.alert(
      "Delete snapshot?",
      `Permanently delete this ${b.kind} snapshot from ${new Date(b.created_at).toLocaleString()}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setBusy(b.id);
            try {
              await api.delete(`/admin/backups/${b.id}`);
              await load();
            } catch (e) {
              Alert.alert("Delete failed", formatApiError(e));
            } finally { setBusy(null); }
          },
        },
      ],
    );
  };

  const totalRows = (b: Backup) => Object.values(b.counts || {}).reduce((a, c) => a + c, 0);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]} {...swipe}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="backups-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Data backups</Text>
        <View style={{ width: 40 }} />
      </View>

      <View style={styles.tabsRow}>
        {([
          { k: "file", l: "File backup", icon: "hard-drive" as const },
          { k: "snapshots", l: "Snapshots", icon: "clock" as const },
        ]).map((t) => (
          <TouchableOpacity
            key={t.k}
            onPress={() => setTab(t.k as any)}
            style={[styles.tabBtn, tab === t.k && styles.tabBtnActive]}
            testID={`backups-tab-${t.k}`}
          >
            <Feather name={t.icon} size={14} color={tab === t.k ? colors.primary : colors.textMuted} />
            <Text style={[styles.tabBtnText, tab === t.k && { color: colors.primary }]}>{t.l}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {tab === "file" ? (
        isSuper ? <AppBackupPanel /> : (
          <Text style={styles.empty}>Only a super admin can download or restore a full app backup.</Text>
        )
      ) : (
      <>
      <View style={styles.metaCard}>
        <Feather name="hard-drive" size={20} color={colors.primary} />
        <View style={{ flex: 1 }}>
          <Text style={styles.metaTitle}>Auto-snapshot every {meta ? Math.round(meta.interval_seconds / 60) : 15} min</Text>
          <Text style={styles.metaSub}>Full database each time · keeps the last {meta?.auto_retention ?? 6} automatic and {meta?.retention ?? 24} manual snapshots</Text>
        </View>
      </View>

      {isSuper && (
        <>
          <TouchableOpacity onPress={() => setManualOpen(true)} style={styles.takeBtn} testID="backups-take">
            <Feather name="camera" size={16} color={colors.primaryFg} />
            <Text style={styles.takeBtnText}>Take snapshot now</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onPurgeOld}
            disabled={busy === "purge"}
            style={styles.purgeBtn}
            testID="backups-purge-old"
          >
            {busy === "purge"
              ? <ActivityIndicator size="small" color={colors.textMuted} />
              : <Feather name="trash-2" size={14} color={colors.textMuted} />}
            <Text style={styles.purgeBtnText}>Clean up old snapshots</Text>
          </TouchableOpacity>
        </>
      )}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <FlatList
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 0, paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`backup-${item.id}`}>
              <View style={styles.cardTop}>
                <View style={[styles.kindPill, { backgroundColor: item.kind === "manual" ? colors.brand500 : colors.success }]}>
                  <Feather name={item.kind === "manual" ? "user" : "clock"} size={11} color="#fff" />
                  <Text style={styles.kindPillText}>{item.kind.toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTime}>{new Date(item.created_at).toLocaleString()}</Text>
                  {item.note ? <Text style={styles.cardNote} numberOfLines={2}>{'“'}{item.note}{'”'}</Text> : null}
                </View>
                <Text style={styles.totalRows}>{totalRows(item).toLocaleString("en-IN")} rows</Text>
              </View>
              <View style={styles.countsRow}>
                {Object.entries(item.counts || {}).map(([k, v]) => (
                  <View key={k} style={styles.countChip}>
                    <Text style={styles.countLabel}>{k}</Text>
                    <Text style={styles.countValue}>{v}</Text>
                  </View>
                ))}
              </View>
              {isSuper && (
                <View style={styles.actions}>
                  <TouchableOpacity
                    onPress={() => setRestoreFor(item)}
                    disabled={busy === item.id}
                    style={[styles.miniBtn, { backgroundColor: colors.primary }]}
                    testID={`backup-restore-${item.id}`}
                  >
                    <Feather name="rotate-ccw" size={13} color={colors.primaryFg} />
                    <Text style={[styles.miniBtnText, { color: colors.primaryFg }]}>Restore</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => onDelete(item)}
                    disabled={busy === item.id}
                    style={[styles.miniBtn, { backgroundColor: "#FCE9E5" }]}
                    testID={`backup-delete-${item.id}`}
                  >
                    {busy === item.id ? <ActivityIndicator color="#B3261E" size="small" /> : (
                      <>
                        <Feather name="trash-2" size={13} color="#B3261E" />
                        <Text style={[styles.miniBtnText, { color: "#B3261E" }]}>Delete</Text>
                      </>
                    )}
                  </TouchableOpacity>
                </View>
              )}
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>No snapshots yet — first one will auto-trigger soon.</Text>}
        />
      )}
      </>
      )}

      {/* Manual snapshot modal */}
      <Modal visible={manualOpen} transparent animationType="slide" onRequestClose={() => setManualOpen(false)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Take snapshot</Text>
            <Text style={styles.modalSub}>Captures every collection in the database — users, products, orders, invoices, chat, services, wallet and settings. Stored inside the app; use the File backup tab for a copy you can download.</Text>
            <Text style={styles.fieldLabel}>Note (optional)</Text>
            <TextInput
              value={note}
              onChangeText={setNote}
              placeholder="e.g. Before payout structure change"
              placeholderTextColor={colors.textMuted}
              style={styles.input}
              testID="backup-note"
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity onPress={() => setManualOpen(false)} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={onTakeSnapshot} disabled={busy === "manual"} style={[styles.modalBtn, { backgroundColor: colors.primary }]} testID="backup-take-confirm">
                {busy === "manual" ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Take snapshot</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Restore modal */}
      <Modal visible={!!restoreFor} transparent animationType="slide" onRequestClose={() => setRestoreFor(null)}>
        <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
          <View style={styles.modalSheet}>
            <View style={styles.modalIconWrap}><Feather name="alert-triangle" size={28} color="#B3261E" /></View>
            <Text style={styles.modalTitle}>Restore database?</Text>
            <Text style={styles.modalSub}>
              This replaces ALL current users / transactions / withdrawals / orders / products / settings / audit logs with the data from{"\n\n"}
              <Text style={{ fontWeight: "800", color: colors.textMain }}>
                {restoreFor ? new Date(restoreFor.created_at).toLocaleString() : ""}
              </Text>{"\n\n"}
              Enter your <Text style={{ fontWeight: "800" }}>6-digit Danger PIN</Text> to confirm.
            </Text>
            <TextInput
              value={restorePin}
              onChangeText={(v) => setRestorePin(v.replace(/[^0-9]/g, "").slice(0, 6))}
              secureTextEntry
              keyboardType="number-pad"
              maxLength={6}
              placeholder="••••••"
              placeholderTextColor={colors.textMuted}
              style={[styles.input, { textAlign: "center", letterSpacing: 8, fontWeight: "800", fontSize: 22, paddingVertical: 16 }]}
              testID="backup-restore-pin"
            />
            <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
              <TouchableOpacity onPress={() => { setRestoreFor(null); setRestorePin(""); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={onRestore}
                disabled={!isPin(restorePin) || !!busy}
                style={[styles.modalBtn, { backgroundColor: "#B3261E" }, (!isPin(restorePin) || !!busy) && { opacity: 0.5 }]}
                testID="backup-restore-submit"
              >
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={{ color: "#fff", fontWeight: "800" }}>Restore</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.screen, paddingBottom: 8 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  metaCard: { flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: spacing.screen, padding: 14, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  metaTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  metaSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  takeBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginHorizontal: spacing.screen, padding: 12, backgroundColor: colors.primary, borderRadius: radii.button, marginBottom: 10 },
  purgeBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 8, paddingVertical: 11, borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted, minHeight: 44,
  },
  purgeBtnText: { fontSize: 12.5, fontWeight: "700", color: colors.textMuted },
  takeBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  // Jun 2026 — entry point for the portable file backup (Phase 4B).
  tabsRow: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.screen, marginBottom: 10 },
  tabBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: radii.button, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, minHeight: 44 },
  tabBtnActive: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  tabBtnText: { fontSize: 12.5, fontWeight: "800", color: colors.textMuted },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 10 },
  cardTop: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  kindPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 99 },
  kindPillText: { color: "#fff", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  cardTime: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  cardNote: { fontSize: 11, color: colors.textMuted, fontStyle: "italic", marginTop: 2 },
  totalRows: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  countsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 },
  countChip: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.surfaceMuted, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  countLabel: { fontSize: 10, color: colors.textMuted },
  countValue: { fontSize: 11, fontWeight: "800", color: colors.textMain },
  actions: { flexDirection: "row", gap: 8, marginTop: 12 },
  miniBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 10 },
  miniBtnText: { fontSize: 12, fontWeight: "800" },
  empty: { padding: 40, textAlign: "center", color: colors.textMuted },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  modalIconWrap: { width: 56, height: 56, borderRadius: 28, backgroundColor: "#FCE9E5", alignItems: "center", justifyContent: "center", alignSelf: "center", marginBottom: 12 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain, textAlign: "center" },
  modalSub: { fontSize: 13, color: colors.textMuted, marginTop: 8, marginBottom: 14, lineHeight: 20, textAlign: "center" },
  fieldLabel: { fontSize: 11, color: colors.textMuted, fontWeight: "800", letterSpacing: 1, marginTop: 6, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});
