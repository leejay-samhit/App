/**
 * Chat lock gate — PIN + optional biometric unlock screen.
 *
 * Used from two places:
 *   - The Chat tab (when `lock_chat_tab=true`) — the entire chat list is
 *     replaced with this gate until the user authenticates.
 *   - The thread screen (when the open thread is in `locked_thread_ids`).
 *
 * The unlock state is held in-memory inside the ChatSettings context so it
 * survives navigation within a session but resets on cold app launch.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, Platform } from "react-native";
import { Feather } from "@expo/vector-icons";
import * as LocalAuth from "expo-local-authentication";
import { api, formatApiError } from "./api";
import { useChatSettings } from "./chat-settings";
import { colors, radii, spacing } from "./theme";

type Props = {
  /** "tab" or a thread_id — used as the cache key in the unlocked set. */
  unlockKey: "tab" | string;
  title?: string;
  subtitle?: string;
  /** Called once the user is authenticated. The parent shows real content. */
  onUnlocked: () => void;
};

export function ChatLockGate({ unlockKey, title, subtitle, onUnlocked }: Props) {
  const { settings, markUnlocked } = useChatSettings();
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bioTried, setBioTried] = useState(false);

  const useBio = !!settings?.use_biometric;

  const onSuccess = useCallback(() => {
    markUnlocked(unlockKey);
    onUnlocked();
  }, [markUnlocked, onUnlocked, unlockKey]);

  const verifyPin = useCallback(async (value: string) => {
    if (value.length < 4) return;
    setBusy(true); setError(null);
    try {
      await api.post("/chat/lock/verify", { pin: value });
      setPin("");
      onSuccess();
    } catch (e: any) {
      setError(formatApiError(e) || "Wrong PIN. Try again.");
      setPin("");
    } finally {
      setBusy(false);
    }
  }, [onSuccess]);

  // Auto-prompt biometric once on mount (if enabled). User can fall back to PIN.
  useEffect(() => {
    if (!useBio || bioTried) return;
    setBioTried(true);
    if (Platform.OS === "web") return;
    (async () => {
      try {
        const hw = await LocalAuth.hasHardwareAsync();
        const enrolled = await LocalAuth.isEnrolledAsync();
        if (!hw || !enrolled) return;
        const res = await LocalAuth.authenticateAsync({
          promptMessage: "Unlock chats",
          cancelLabel: "Use PIN",
          fallbackLabel: "Use PIN",
          disableDeviceFallback: true,
        });
        if (res.success) onSuccess();
      } catch { /* ignore — user can still use the PIN */ }
    })();
  }, [useBio, bioTried, onSuccess]);

  return (
    <View style={styles.wrap}>
      <View style={styles.iconRing}>
        <Feather name="lock" size={32} color={colors.primary} />
      </View>
      <Text style={styles.title}>{title || "Chats locked"}</Text>
      <Text style={styles.subtitle}>{subtitle || "Enter your chat PIN to continue."}</Text>

      <TextInput
        style={styles.pinInput}
        value={pin}
        onChangeText={(v) => {
          const cleaned = v.replace(/[^0-9]/g, "").slice(0, 6);
          setPin(cleaned);
          if (cleaned.length >= 4) verifyPin(cleaned);
        }}
        keyboardType="number-pad"
        secureTextEntry
        placeholder="••••••"
        placeholderTextColor={colors.textMuted}
        maxLength={6}
        autoFocus
        testID="chat-lock-pin"
      />

      {busy ? <ActivityIndicator color={colors.primary} style={{ marginTop: 12 }} /> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}

      {useBio && Platform.OS !== "web" ? (
        <TouchableOpacity
          onPress={async () => {
            try {
              const r = await LocalAuth.authenticateAsync({
                promptMessage: "Unlock chats",
                cancelLabel: "Use PIN",
                fallbackLabel: "Use PIN",
                disableDeviceFallback: true,
              });
              if (r.success) onSuccess();
            } catch {}
          }}
          style={styles.bioBtn}
          testID="chat-lock-bio"
        >
          <Feather name="shield" size={16} color={colors.primary} />
          <Text style={styles.bioBtnLabel}>Use fingerprint / face</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1, alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.screen, backgroundColor: colors.background,
  },
  iconRing: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
    marginBottom: 16,
  },
  title: { fontSize: 20, fontWeight: "700", color: colors.text },
  subtitle: { fontSize: 13, color: colors.textMuted, marginTop: 6, textAlign: "center" },
  pinInput: {
    marginTop: 24,
    width: 220, height: 56,
    borderRadius: radii.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
    textAlign: "center",
    fontSize: 24, letterSpacing: 8,
    color: colors.text,
  },
  error: { marginTop: 12, color: "#B3261E", fontSize: 13, fontWeight: "500" },
  bioBtn: {
    marginTop: 24,
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: 24, backgroundColor: colors.brand100,
  },
  bioBtnLabel: { color: colors.primary, fontWeight: "600", fontSize: 13 },
});
