// Reusable "double-tap back to exit" hook (Android pattern).
//
// On Android, hardware-back at the ROOT of a tab stack normally exits the
// app immediately — which is jarring if the user only meant to dismiss a
// keyboard or undo an accidental tap. This hook intercepts the first
// back press, shows a small toast ("Press back again to exit"), and only
// exits if a second back press arrives within the 2-second window.
//
// • On iOS / web → no-op (iOS has no hardware back; web has browser back).
// • Mount once on each TAB ROOT screen (Shop, Dashboard, Admin Home, etc.)
//   — NOT on pushed sub-screens, where the default pop-stack behaviour is
//   already what users expect.
// • The hook uses native BackHandler + ToastAndroid; no extra deps.
//
// Usage:
//   import { useDoubleTapExit } from "../../src/use-double-tap-exit";
//   export default function ShopScreen() {
//     useDoubleTapExit();
//     return ( ... );
//   }

import { useEffect, useRef } from "react";
import { BackHandler, Platform, ToastAndroid } from "react-native";

const EXIT_WINDOW_MS = 2000;

export function useDoubleTapExit(enabled: boolean = true) {
  const lastBackAt = useRef<number>(0);
  useEffect(() => {
    if (!enabled) return;
    if (Platform.OS !== "android") return;

    const onBack = () => {
      const now = Date.now();
      if (now - lastBackAt.current < EXIT_WINDOW_MS) {
        // Second tap within 2 s → really exit.
        BackHandler.exitApp();
        return true;
      }
      lastBackAt.current = now;
      try {
        ToastAndroid.show("Press back again to exit", ToastAndroid.SHORT);
      } catch {
        // Toast can fail in rare contexts (e.g. first paint) — ignore.
      }
      return true; // consumed; don't bubble up
    };

    const sub = BackHandler.addEventListener("hardwareBackPress", onBack);
    return () => sub.remove();
  }, [enabled]);
}
