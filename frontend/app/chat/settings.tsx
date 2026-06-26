/**
 * Chat → Settings
 *
 * Single screen the user reaches from the Chat tab header gear icon.
 * Surfaces:
 *   1. Wallpaper preset picker (defaults applied to every thread without
 *      its own override). Custom-image upload is exposed inside an
 *      individual thread, not here.
 *   2. Chat lock — setup PIN, change PIN, disable, toggle "lock chat tab",
 *      toggle biometric unlock.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert, ActivityIndicator,
  TextInput, Modal, Pressable, Switch, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as LocalAuth from "expo-local-authentication";
import { api, formatApiError } from "../../src/api";
import { useChatSettings, wallpaperStyle, Wallpaper } from "../../src/chat-settings";
import { colors, radii, spacing } from "../../src/theme";

export default function ChatSettingsScreen() {
  const router = useRouter();
  const { settings, loading, reload, setDefaultWallpaper } = useChatSettings();
  const [pinModal, setPinModal] = useState<null | "setup" | "change" | "disable" | "tab-on" | "tab-off">(null);

  if (loading || !settings) {
    return (
      <SafeAreaView style={[styles.safe, styles.center]}>
        <ActivityIndicator color={colors.primary} />
      </SafeAreaView>
    );
  }

  const presetEntries = Object.entries(settings.presets || {});

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="chat-settings-back">
          <Feather name="arrow-left" size={22} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.h1}>Chat Settings</Text>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* ── Wallpaper ───────────────────────────────────────────── */}
        <Text style={styles.sectionLabel}>WALLPAPER</Text>
        <Text style={styles.sectionHint}>Default background for every chat. Open a chat to override per-thread.</Text>

        <View style={styles.presetGrid}>
          {presetEntries.map(([key]) => {
            const wp: Wallpaper = { kind: "preset", value: key };
            const selected = settings.default_wallpaper?.kind === "preset" && settings.default_wallpaper.value === key;
            return (
              <TouchableOpacity
                key={key}
                style={[styles.preset, wallpaperStyle(wp, settings.presets), selected && styles.presetSelected]}
                onPress={async () => {
                  try { await setDefaultWallpaper(wp); } catch (e) { Alert.alert("Couldn't save", formatApiError(e)); }
                }}
                testID={`chat-wp-${key}`}
              >
                {selected ? (
                  <View style={styles.presetCheck}>
                    <Feather name="check" size={14} color="#fff" />
                  </View>
                ) : null}
                <Text style={[styles.presetLabel, /(slate|midnight)/.test(key) && { color: "#fff" }]} numberOfLines={1}>{key}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {settings.default_wallpaper ? (
          <TouchableOpacity
            style={styles.clearBtn}
            onPress={async () => { try { await setDefaultWallpaper(null); } catch (e) { Alert.alert("Couldn't clear", formatApiError(e)); } }}
            testID="chat-wp-clear"
          >
            <Feather name="x-circle" size={14} color={colors.textMuted} />
            <Text style={styles.clearBtnLabel}>Reset to default</Text>
          </TouchableOpacity>
        ) : null}

        {/* ── Chat Lock ───────────────────────────────────────────── */}
        <View style={styles.divider} />
        <Text style={styles.sectionLabel}>CHAT LOCK</Text>
        <Text style={styles.sectionHint}>
          {settings.has_pin
            ? "PIN configured. Use the row below to gate the entire chat tab."
            : "Add a 4–6 digit PIN to keep your chats private. You can also lock individual threads from each chat."}
        </Text>

        {!settings.has_pin ? (
          <TouchableOpacity style={styles.actionRow} onPress={() => setPinModal("setup")} testID="chat-lock-setup">
            <View style={styles.actionIcon}><Feather name="lock" size={18} color={colors.primary} /></View>
            <Text style={styles.actionLabel}>Set up chat PIN</Text>
            <Feather name="chevron-right" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ) : (
          <>
            <View style={styles.toggleRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.toggleLabel}>Lock the entire chat tab</Text>
                <Text style={styles.toggleHint}>Require PIN every time chats are opened.</Text>
              </View>
              <Switch
                value={settings.lock_chat_tab}
                onValueChange={() => setPinModal(settings.lock_chat_tab ? "tab-off" : "tab-on")}
                trackColor={{ true: colors.primary, false: colors.border }}
                testID="chat-lock-tab-toggle"
              />
            </View>

            <BiometricRow />

            <TouchableOpacity style={styles.actionRow} onPress={() => setPinModal("change")} testID="chat-lock-change">
              <View style={styles.actionIcon}><Feather name="edit-2" size={18} color={colors.primary} /></View>
              <Text style={styles.actionLabel}>Change PIN</Text>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>

            <TouchableOpacity style={[styles.actionRow, { borderColor: "#B3261E" }]} onPress={() => setPinModal("disable")} testID="chat-lock-disable">
              <View style={[styles.actionIcon, { backgroundColor: "#FFE6E6" }]}><Feather name="unlock" size={18} color="#B3261E" /></View>
              <Text style={[styles.actionLabel, { color: "#B3261E" }]}>Disable chat lock</Text>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          </>
        )}

        <View style={{ height: 32 }} />
      </ScrollView>

      <PinModal mode={pinModal} onClose={() => setPinModal(null)} onDone={async () => { setPinModal(null); await reload(); }} />
    </SafeAreaView>
  );
}

// Biometric toggle — flips `use_biometric` via /chat/lock/change with current PIN.
// Uses an inline PIN modal so this works on iOS, Android AND web (the old
// implementation relied on `Alert.prompt` which is iOS-only).
function BiometricRow() {
  const { settings, reload } = useChatSettings();
  const [busy, setBusy] = useState(false);
  const [pinSheetOpen, setPinSheetOpen] = useState(false);
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!settings) return null;

  const open = async () => {
    setErr(null);
    if (Platform.OS !== "web") {
      try {
        const hw = await LocalAuth.hasHardwareAsync();
        const enrolled = await LocalAuth.isEnrolledAsync();
        if (!hw || !enrolled) {
          Alert.alert("Biometric unavailable", "Enrol a fingerprint or face in your phone settings first.");
          return;
        }
      } catch { /* fall through */ }
    }
    setPin("");
    setPinSheetOpen(true);
  };

  const submit = async () => {
    if (!pin || pin.length < 4) { setErr("Enter your 4–6 digit PIN."); return; }
    setBusy(true); setErr(null);
    try {
      await api.post("/chat/lock/change", {
        old_pin: pin,
        new_pin: pin,
        use_biometric: !settings.use_biometric,
      });
      await reload();
      setPinSheetOpen(false);
      setPin("");
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <View style={styles.toggleRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.toggleLabel}>Use fingerprint / face</Text>
          <Text style={styles.toggleHint}>
            {Platform.OS === "web"
              ? "Saves the preference — works on your phone, not on this browser."
              : "Unlock chats with your device biometric instead of typing the PIN."}
          </Text>
        </View>
        <Switch
          value={settings.use_biometric}
          onValueChange={open}
          trackColor={{ true: colors.primary, false: colors.border }}
          disabled={busy}
          testID="chat-lock-bio-toggle"
        />
      </View>

      <Modal visible={pinSheetOpen} transparent animationType="fade" onRequestClose={() => setPinSheetOpen(false)}>
        <Pressable style={styles.modalBackdrop} onPress={() => setPinSheetOpen(false)}>
          <Pressable style={[styles.modalCard, { borderTopLeftRadius: 18, borderTopRightRadius: 18, marginHorizontal: 24, borderRadius: 18 }]} onPress={() => {}}>
            <Text style={styles.modalTitle}>
              {settings.use_biometric ? "Disable biometric unlock" : "Enable biometric unlock"}
            </Text>
            <Text style={[styles.toggleHint, { marginTop: 6 }]}>
              Enter your chat PIN to confirm.
            </Text>
            <PinInput value={pin} onChangeText={setPin} placeholder="Chat PIN" testID="bio-pin" />
            {err ? <Text style={styles.modalErr}>{err}</Text> : null}
            <View style={styles.modalBtns}>
              <TouchableOpacity onPress={() => { setPinSheetOpen(false); setPin(""); setErr(null); }} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
                <Text style={styles.modalBtnLabel}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={submit} disabled={busy} style={[styles.modalBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]} testID="bio-pin-submit">
                {busy ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnLabel, { color: "#fff" }]}>Confirm</Text>}
              </TouchableOpacity>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

// Inline PIN modal used by setup / change / disable / tab-toggle.
function PinModal({
  mode, onClose, onDone,
}: { mode: null | "setup" | "change" | "disable" | "tab-on" | "tab-off"; onClose: () => void; onDone: () => void | Promise<void>; }) {
  const [pin, setPin] = useState("");
  const [pin2, setPin2] = useState("");
  const [oldPin, setOldPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const visible = mode !== null;

  const reset = () => { setPin(""); setPin2(""); setOldPin(""); setBusy(false); setErr(null); };
  const close = () => { reset(); onClose(); };

  const submit = async () => {
    setErr(null);
    if (mode === "setup") {
      if (pin.length < 4 || pin !== pin2) { setErr("PINs must match and be 4–6 digits."); return; }
      setBusy(true);
      try { await api.post("/chat/lock/setup", { pin }); await onDone(); reset(); }
      catch (e) { setErr(formatApiError(e)); }
      finally { setBusy(false); }
    } else if (mode === "change") {
      if (!oldPin || pin.length < 4 || pin !== pin2) { setErr("Enter old PIN and a matching new PIN."); return; }
      setBusy(true);
      try { await api.post("/chat/lock/change", { old_pin: oldPin, new_pin: pin }); await onDone(); reset(); }
      catch (e) { setErr(formatApiError(e)); }
      finally { setBusy(false); }
    } else if (mode === "disable") {
      if (oldPin.length < 4) { setErr("Enter your current PIN."); return; }
      setBusy(true);
      try { await api.post("/chat/lock/disable", { pin: oldPin }); await onDone(); reset(); }
      catch (e) { setErr(formatApiError(e)); }
      finally { setBusy(false); }
    } else if (mode === "tab-on" || mode === "tab-off") {
      if (oldPin.length < 4) { setErr("Enter your chat PIN to confirm."); return; }
      setBusy(true);
      try {
        await api.patch("/chat/lock/tab", { pin: oldPin, lock_chat_tab: mode === "tab-on" });
        await onDone(); reset();
      }
      catch (e) { setErr(formatApiError(e)); }
      finally { setBusy(false); }
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={close}>
      <Pressable style={styles.modalBackdrop} onPress={close}>
        <Pressable style={styles.modalCard} onPress={() => {}}>
          <Text style={styles.modalTitle}>
            {mode === "setup" ? "Set chat PIN"
            : mode === "change" ? "Change PIN"
            : mode === "disable" ? "Disable chat lock"
            : mode === "tab-on" ? "Lock chat tab"
            : mode === "tab-off" ? "Unlock chat tab"
            : ""}
          </Text>

          {mode === "change" || mode === "disable" || mode === "tab-on" || mode === "tab-off" ? (
            <PinInput value={oldPin} onChangeText={setOldPin} placeholder={mode === "change" ? "Current PIN" : "Chat PIN"} testID="pin-old" />
          ) : null}

          {mode === "setup" || mode === "change" ? (
            <>
              <PinInput value={pin} onChangeText={setPin} placeholder={mode === "setup" ? "New PIN (4–6 digits)" : "New PIN"} testID="pin-new" />
              <PinInput value={pin2} onChangeText={setPin2} placeholder="Confirm PIN" testID="pin-confirm" />
            </>
          ) : null}

          {err ? <Text style={styles.modalErr}>{err}</Text> : null}

          <View style={styles.modalBtns}>
            <TouchableOpacity onPress={close} style={[styles.modalBtn, { backgroundColor: colors.surfaceMuted }]}>
              <Text style={styles.modalBtnLabel}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={submit} disabled={busy} style={[styles.modalBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]} testID="pin-submit">
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={[styles.modalBtnLabel, { color: "#fff" }]}>Confirm</Text>}
            </TouchableOpacity>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function PinInput({ value, onChangeText, placeholder, testID }: { value: string; onChangeText: (v: string) => void; placeholder: string; testID?: string }) {
  return (
    <TextInput
      style={styles.modalInput}
      value={value}
      onChangeText={(v) => onChangeText(v.replace(/[^0-9]/g, "").slice(0, 6))}
      placeholder={placeholder}
      placeholderTextColor={colors.textMuted}
      secureTextEntry
      keyboardType="number-pad"
      maxLength={6}
      testID={testID}
    />
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { alignItems: "center", justifyContent: "center" },
  headerBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 20 },
  h1: { fontSize: 20, fontWeight: "700", color: colors.text },
  scroll: { padding: spacing.screen, paddingBottom: 48 },
  sectionLabel: { fontSize: 11, color: colors.textMuted, letterSpacing: 1, fontWeight: "700", marginTop: 4 },
  sectionHint: { fontSize: 12, color: colors.textMuted, marginTop: 4, marginBottom: 12 },
  presetGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  preset: {
    width: 92, height: 92,
    borderRadius: 14, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "flex-end",
    padding: 8,
  },
  presetSelected: { borderWidth: 2, borderColor: colors.primary },
  presetCheck: {
    position: "absolute", top: 8, right: 8,
    width: 20, height: 20, borderRadius: 10,
    backgroundColor: colors.primary, alignItems: "center", justifyContent: "center",
  },
  presetLabel: { fontSize: 11, color: colors.text, fontWeight: "600", textTransform: "capitalize" },
  clearBtn: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 14 },
  clearBtnLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "500" },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 24 },
  actionRow: {
    marginTop: 12,
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: 14, paddingVertical: 14,
    borderRadius: radii.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  actionIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  actionLabel: { flex: 1, fontSize: 14, color: colors.text, fontWeight: "600" },
  toggleRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginTop: 12, paddingHorizontal: 14, paddingVertical: 12,
    borderRadius: radii.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  toggleLabel: { fontSize: 14, color: colors.text, fontWeight: "600" },
  toggleHint: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  modalCard: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: 20, paddingBottom: 32,
  },
  modalTitle: { fontSize: 18, fontWeight: "700", color: colors.text },
  modalInput: {
    marginTop: 14,
    borderRadius: radii.md, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 18, letterSpacing: 4, textAlign: "center", color: colors.text,
    backgroundColor: colors.background,
  },
  modalErr: { color: "#B3261E", fontSize: 13, marginTop: 8 },
  modalBtns: { flexDirection: "row", gap: 10, marginTop: 18 },
  modalBtn: { flex: 1, paddingVertical: 14, borderRadius: radii.md, alignItems: "center", justifyContent: "center" },
  modalBtnLabel: { fontSize: 14, fontWeight: "700", color: colors.text },
});
