import { Stack, router as expoRouter } from "expo-router";
import { useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import { Text, TextInput, Platform, View, useWindowDimensions } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { enableFreeze } from "react-native-screens";
import * as SplashScreen from "expo-splash-screen";
import * as Notifications from "expo-notifications";
import * as Linking from "expo-linking";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { notify } from "../src/notify";
import { AuthProvider, useAuth } from "../src/auth";
import { BrandingProvider, useFontFamily } from "../src/branding";
import { ChatSettingsProvider } from "../src/chat-settings";
import { LocationGate } from "../src/location-gate";
import TamperBlockedScreen from "../src/tamper-blocked-screen";
import { registerForPush } from "../src/push";
import { ContentWidthProvider, TABLET_MAX_WIDTH } from "../src/content-width";
import { colors } from "../src/theme";

// ── Push notifications: module-scope wiring (required by playbook) ──
// Foreground display behaviour — show the banner + play sound even while
// the user is inside the app, otherwise chat pings would be silently
// swallowed when the destination thread isn't open.
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}

// Android: a high-importance default channel must exist BEFORE any push
// lands, so create it at module scope.
if (Platform.OS === "android") {
  Notifications.setNotificationChannelAsync("default", {
    name: "Default",
    importance: Notifications.AndroidImportance.MAX,
    sound: "default",
  }).catch(() => {});
}

// ── Denied-permission nudge ─────────────────────────────────────────────
// Once a user says "no" twice (iOS) or picks "Don't ask again" (Android),
// requestPermissionsAsync() can never prompt again — canAskAgain is false.
// The only route back is the OS settings screen, so we ask (politely, at
// most once a week) and deep-link them there.
const PUSH_NUDGE_KEY = "pushNudgeAt";
const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

async function maybeNudgeForPushPermission() {
  if (Platform.OS === "web") return;
  const { status, canAskAgain } = await Notifications.getPermissionsAsync();
  if (status !== "denied" || canAskAgain) return;

  const last = await AsyncStorage.getItem(PUSH_NUDGE_KEY);
  if (last && Date.now() - Number(last) <= ONE_WEEK_MS) return;

  const stamp = () => AsyncStorage.setItem(PUSH_NUDGE_KEY, String(Date.now())).catch(() => {});
  notify(
    "Turn on notifications?",
    "You're missing order updates and replies from sellers. Notifications are " +
    "switched off for Slangcart — you can turn them back on in settings.",
    [
      { text: "Later", style: "cancel", onPress: stamp },
      {
        text: "Open Settings",
        onPress: () => { stamp(); Linking.openSettings().catch(() => {}); },
      },
    ],
  );
}

// Sep 2026 — SPLASHES REMOVED. There is no JS splash overlay any more (it
// used to hold the app hostage for the admin-configured duration, 5s by
// default). The OS launch screen is kept up only until React's first commit
// so the handoff has no white flash, then hidden immediately.
//
// Freeze inactive screens: a blurred tab / pushed-away screen stops
// re-rendering entirely, which is the single biggest win for back-navigation
// and swipe smoothness on mid-range Androids.
enableFreeze(true);

SplashScreen.preventAutoHideAsync().catch(() => {
  /* Safe to ignore — fails on web / when called twice. */
});

// Apply the active font to every Text/TextInput by extending defaultProps.
// Also caps font scaling at 1.2× so users with very large system fonts don't
// break the layout (otherwise titles wrap awkwardly on small phones).
function GlobalFont({ children }: { children: React.ReactNode }) {
  const family = useFontFamily();
  // @ts-ignore react-native runtime allows this
  (Text as any).defaultProps = (Text as any).defaultProps || {};
  // @ts-ignore
  (Text as any).defaultProps.style = family ? { fontFamily: family } : undefined;
  // @ts-ignore
  (Text as any).defaultProps.maxFontSizeMultiplier = 1.2;
  // @ts-ignore
  (TextInput as any).defaultProps = (TextInput as any).defaultProps || {};
  // @ts-ignore
  (TextInput as any).defaultProps.style = family ? { fontFamily: family } : undefined;
  // @ts-ignore
  (TextInput as any).defaultProps.maxFontSizeMultiplier = 1.2;
  return <>{children}</>;
}

// Constrains content to a centered, readable column (~600 px) on tablets / large
// foldables / desktops. On phones the wrapper is a no-op. On desktop, renders
// the mobile app inside a polished phone frame with shadow and rounded corners
// so the preview looks like an actual Android device.
// Jun 2026 tablet fix — the app used to be wrapped in a fake "Android phone
// frame" (a ~504 px centred column on a dark backdrop) for every viewport
// ≥ 900 px.  On a real 12-inch tablet that meant the whole shop rendered in a
// narrow strip in the middle of the screen, with product images and hero /
// banner cards squeezed and misaligned — exactly the bug the user reported.
//
// The frame is gone.  Screens now use the FULL width and the responsive
// components (product grid columns, banner height, layout blocks) adapt via
// useWindowDimensions().  On wide web viewports DesktopShell still supplies
// the sidebar + top bar chrome.
// Jun 2026 tablet fix (v2) — the app used to be wrapped in a fake "Android
// phone frame" (a ~504 px centred column on a dark backdrop) for every
// viewport ≥ 900 px. That was removed, but letting every screen use the FULL
// width of a 12-inch tablet made banners 1000+ dp wide and product images
// 500 dp tall — the layout "disaster" the owner reported.
//
// Per the owner's choice ("keep 2–3 columns, centre the content with a
// max-width") the app now paints into a centred column capped at
// TABLET_MAX_WIDTH on tablets, and every width-aware component reads that
// column width via useContentWidth() instead of the window width, so the
// shop-layout blocks lay out exactly as they were designed.
//
// Phones are untouched (no wrapper, no provider) and desktop web ≥ 1024 px
// still gets the full-width DesktopShell chrome.
function TabletContainer({ children }: { children: React.ReactNode }) {
  const { width } = useWindowDimensions();
  const isDesktopWeb = Platform.OS === "web" && width >= 1024;
  if (isDesktopWeb || width <= TABLET_MAX_WIDTH) return <>{children}</>;
  return (
    <ContentWidthProvider width={TABLET_MAX_WIDTH}>
      <View style={{ flex: 1, backgroundColor: colors.surfaceMuted, alignItems: "center" }}>
        <View style={{ flex: 1, width: TABLET_MAX_WIDTH, backgroundColor: colors.background }}>
          {children}
        </View>
      </View>
    </ContentWidthProvider>
  );
}

// Phase 3 Session A — Full-screen gate that swaps the entire app for a
// tamper-blocked screen when the most-recent integrity verdict from the
// backend is "hard_block". Other verdicts (none / warn / read_only) let
// the children render normally — the per-action 403 guard on the backend
// handles those at the financial endpoint.
function TamperGate({ children }: { children: React.ReactNode }) {
  const { integrity, recheckIntegrity } = useAuth();
  if (integrity && integrity.block_level === "hard_block") {
    return <TamperBlockedScreen verdict={integrity} onRetry={() => { recheckIntegrity().catch(() => {}); }} />;
  }
  return <>{children}</>;
}

// Re-register the push token on every successful sign-in. Tokens can rotate
// (Android updates after app upgrades / data clears), so doing this on every
// auth transition keeps the SuprSend mapping current.
function PushReRegister() {
  const { user } = useAuth();
  useEffect(() => {
    if (user?.id) {
      registerForPush(user.id).catch(() => {});
      // Jun 2026 — if the user has permanently denied notifications we can't
      // re-prompt (canAskAgain === false), so nudge them to system settings
      // at most once a week. Tapping a notification is the only way they
      // hear about orders and chat replies while the app is closed.
      maybeNudgeForPushPermission().catch(() => {});
    }
  }, [user?.id]);

  // NOTE: notification-tap routing lives in RootLayoutInner — exactly ONE
  // response listener must exist, otherwise every tap navigates twice.
  return null;
}

export default function RootLayout() {
  // First commit is done → drop the OS launch screen straight away.
  useEffect(() => {
    SplashScreen.hideAsync().catch(() => {});
  }, []);

  // ── Notification tap routing — warm + cold-start. Pushes carry an
  // `action_url` (e.g. `/chat/{thread_id}`) and we navigate to it via
  // expo-router. http(s) deep links are handed to Linking instead.
  return <RootLayoutInner />;
}

function RootLayoutInner() {
  useEffect(() => {
    if (Platform.OS === "web") return;

    const handleData = (data: any) => {
      try {
        const url: string | undefined = data?.action_url || data?.deeplink || data?.url;
        if (!url) return;
        if (url.startsWith("http")) {
          Linking.openURL(url).catch(() => {});
        } else {
          expoRouter.push(url as any);
        }
      } catch {
        /* ignore — bad payload, never crash the app on a push tap */
      }
    };

    // Warm tap — user taps a banner while the app is open.
    const tapSub = Notifications.addNotificationResponseReceivedListener((response) => {
      handleData(response.notification?.request?.content?.data || {});
    });

    // Cold start — if a push *launched* the app, the response is queued.
    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (response) handleData(response.notification?.request?.content?.data || {});
    }).catch(() => {});

    return () => {
      tapSub.remove();
    };
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#143D2E" }}>
      <SafeAreaProvider>
        <BrandingProvider>
          <AuthProvider>
            <ChatSettingsProvider>
            <PushReRegister />
            <GlobalFont>
              {/* Standard status bar — Android reserves space for it automatically
                  now that edge-to-edge is off, matching how Chrome browser
                  renders pages on the user's phone. */}
              <StatusBar style="dark" />
              <TabletContainer>
                {/* LocationGate: blocks all non-admin authenticated users
                    until location permission is granted. Once granted it
                    silently pings the backend with coords every 5s while
                    online and caches the last position before disconnect.
                    Admin users and the unauthenticated /login screen pass
                    through the gate untouched. */}
                <LocationGate>
                  <TamperGate>
                    <Stack
                      screenOptions={{
                        headerShown: false,
                        // Jun 2026 — this used to be the dark splash green
                        // (#143D2E) so the splash→login handoff blended. But
                        // the navigator background shows THROUGH every screen
                        // transition, so each tab swipe / product open
                        // flashed green. SplashOverlay already covers the
                        // launch frames, so the navigator now uses the app
                        // background and transitions are flash-free.
                        contentStyle: { backgroundColor: colors.background },
                        // Native slide is GPU-driven and reads as "instant"
                        // next to the old cross-fade, and the iOS back-swipe
                        // gesture comes for free with it.
                        animation: "slide_from_right",
                        animationDuration: 180,
                        gestureEnabled: true,
                        freezeOnBlur: true,
                      }}
                    />
                  </TamperGate>
                </LocationGate>
              </TabletContainer>
            </GlobalFont>
            </ChatSettingsProvider>
          </AuthProvider>
        </BrandingProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
