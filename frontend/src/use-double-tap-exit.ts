// Android hardware-back navigation hooks.
//
// Two variants:
//   • useDoubleTapExit() — INITIAL tab (Shop). First back = toast,
//     second back within 2s = exit.
//   • useBackToInitialTab() — non-initial tab roots (Dashboard, Chat,
//     Services, Profile, Wallet, Network, etc). Back navigates to /shop
//     instead of exiting the app. If already on /shop, delegate to
//     useDoubleTapExit behaviour so the user can still leave.
//
// Both hooks:
//   • Are safe no-ops on iOS/web.
//   • Only fire when the containing screen is FOCUSED (via
//     useFocusEffect) so the top-most focused screen wins.
//   • Return `true` from the handler to consume the event so expo-router
//     Stack pop or the app-exit don't run behind our back.
//
// Usage on a tab root:
//   export default function ProfileScreen() {
//     useBackToInitialTab();
//     ...
//   }

import { useCallback, useRef } from "react";
import { BackHandler, Platform, ToastAndroid } from "react-native";
import { useFocusEffect, router } from "expo-router";

const EXIT_WINDOW_MS = 2000;

/** Android tab-root: press back → "Press again to exit" then exit. */
export function useDoubleTapExit(enabled: boolean = true) {
  const lastBackAt = useRef<number>(0);
  useFocusEffect(
    useCallback(() => {
      if (!enabled) return;
      if (Platform.OS !== "android") return;

      const onBack = () => {
        const now = Date.now();
        if (now - lastBackAt.current < EXIT_WINDOW_MS) {
          BackHandler.exitApp();
          return true;
        }
        lastBackAt.current = now;
        try { ToastAndroid.show("Press back again to exit", ToastAndroid.SHORT); } catch { /* ignore */ }
        return true;
      };
      const sub = BackHandler.addEventListener("hardwareBackPress", onBack);
      return () => sub.remove();
    }, [enabled]),
  );
}

/**
 * Android non-initial tab root: press back → navigate to /shop instead
 * of exiting the app. Keeps the user "inside" the app instead of dumping
 * them to the OS launcher.
 */
export function useBackToInitialTab(target: string = "/shop") {
  useFocusEffect(
    useCallback(() => {
      if (Platform.OS !== "android") return;
      const onBack = () => {
        try {
          router.replace(target as any);
        } catch {
          // Router unavailable — silently fall through to default.
          return false;
        }
        return true;
      };
      const sub = BackHandler.addEventListener("hardwareBackPress", onBack);
      return () => sub.remove();
    }, [target]),
  );
}
