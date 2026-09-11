// Cross-platform alert.
//
// `Alert.alert` is a NO-OP on react-native-web, which meant every success /
// error message in the cart → checkout → orders flow was invisible in the
// browser preview (and to automated tests).  This shim keeps the native
// dialog on iOS/Android and falls back to window.alert / window.confirm on
// web, preserving a single actionable button.
import { Alert, Platform } from "react-native";

export type NotifyButton = {
  text: string;
  onPress?: () => void;
  style?: "cancel" | "destructive" | "default";
};

export function notify(title: string, message?: string, buttons?: NotifyButton[]) {
  if (Platform.OS !== "web") {
    Alert.alert(title, message, buttons as any);
    return;
  }
  if (typeof window === "undefined") return;
  const body = [title, message].filter(Boolean).join("\n\n");
  const actionable = (buttons || []).filter((b) => b.style !== "cancel" && b.onPress);
  if (actionable.length) {
    const primary = actionable[actionable.length - 1];
    if (window.confirm(`${body}\n\n[OK] ${primary.text}`)) primary.onPress?.();
    else (buttons || []).find((b) => b.style === "cancel")?.onPress?.();
    return;
  }
  window.alert(body);
}
