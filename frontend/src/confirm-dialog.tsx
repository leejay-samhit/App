/**
 * Compact confirmation dialog (Nov-2026).
 *
 * Replaces the stock OS alert for moments that deserve a bit of care — the
 * fingerprint-login confirmation in particular. Icon, title, body and up to
 * two actions, sized to sit comfortably on a phone.
 */
import { ReactNode } from "react";
import {
  Modal,
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Pressable,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii } from "./theme";

type Props = {
  visible: boolean;
  icon?: keyof typeof Feather.glyphMap;
  iconTint?: string;
  title: string;
  body?: string;
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  testID?: string;
};

export function ConfirmDialog({
  visible,
  icon = "help-circle",
  iconTint,
  title,
  body,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Not now",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
  testID,
}: Props) {
  const tint = iconTint || (destructive ? colors.error : colors.primary);
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.backdrop} onPress={busy ? undefined : onCancel}>
        <Pressable style={styles.card} onPress={(e) => e.stopPropagation()} testID={testID}>
          <View style={[styles.iconWrap, { backgroundColor: colors.surfaceMuted }]}>
            <Feather name={icon} size={26} color={tint} />
          </View>
          <Text style={styles.title}>{title}</Text>
          {body ? <Text style={styles.body}>{body}</Text> : null}
          {children}
          <View style={styles.actions}>
            <TouchableOpacity
              onPress={onCancel}
              disabled={busy}
              style={styles.cancelBtn}
              testID={testID ? `${testID}-cancel` : undefined}
            >
              <Text style={styles.cancelText}>{cancelLabel}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={onConfirm}
              disabled={busy}
              style={[styles.confirmBtn, { backgroundColor: destructive ? colors.error : colors.primary }, busy && { opacity: 0.7 }]}
              testID={testID ? `${testID}-confirm` : undefined}
            >
              {busy ? (
                <ActivityIndicator color="#FFFFFF" size="small" />
              ) : (
                <Text style={styles.confirmText}>{confirmLabel}</Text>
              )}
            </TouchableOpacity>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(17, 17, 17, 0.45)",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  card: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: 22,
    alignItems: "center",
    gap: 10,
  },
  iconWrap: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 2,
  },
  title: {
    fontSize: 17,
    fontWeight: "800",
    color: colors.textMain,
    textAlign: "center",
  },
  body: {
    fontSize: 13.5,
    lineHeight: 20,
    color: colors.textMuted,
    textAlign: "center",
  },
  actions: { flexDirection: "row", gap: 10, marginTop: 14, alignSelf: "stretch" },
  cancelBtn: {
    flex: 1,
    minHeight: 46,
    borderRadius: radii.button,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  confirmBtn: {
    flex: 1,
    minHeight: 46,
    borderRadius: radii.button,
    alignItems: "center",
    justifyContent: "center",
  },
  confirmText: { fontSize: 14, fontWeight: "800", color: "#FFFFFF" },
});
