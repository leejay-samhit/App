import { Stack } from "expo-router";
import { useEffect } from "react";
import { StatusBar } from "expo-status-bar";
import { Text, TextInput, View, useWindowDimensions, StyleSheet, Platform } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import * as SplashScreen from "expo-splash-screen";
import { AuthProvider, useAuth } from "../src/auth";
import { BrandingProvider, useFontFamily } from "../src/branding";
import { LocationGate } from "../src/location-gate";
import { SplashOverlay } from "../src/splash-overlay";
import TamperBlockedScreen from "../src/tamper-blocked-screen";
import { colors } from "../src/theme";
import { TABLET_MIN_WIDTH, READABLE_MAX_WIDTH } from "../src/theme";

// Keep the native (Expo) splash screen visible until React Native has had a
// chance to mount our own JS splash overlay. Without this, there's a brief
// FAF9F6 (off-white) flash between the moment the native splash auto-hides
// and the moment our `<SplashOverlay/>` renders the dark-green brand splash.
// Calling preventAutoHideAsync() at module-load (outside any component)
// guarantees we win the race against the auto-hide.
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
function TabletContainer({ children }: { children: React.ReactNode }) {
  const { width } = useWindowDimensions();
  const isTablet = width >= TABLET_MIN_WIDTH;
  if (!isTablet) return <>{children}</>;
  return (
    <View style={styles.tabletOuter}>
      <View style={styles.phoneFrame}>
        <View style={styles.phoneNotch} />
        <View style={styles.tabletInner}>{children}</View>
      </View>
    </View>
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

export default function RootLayout() {
  // Once React has mounted and our SplashOverlay is in the tree, hide the
  // native Expo splash. The handoff to the JS-rendered splash is now
  // seamless — no off-white flash between them.
  useEffect(() => {
    SplashScreen.hideAsync().catch(() => {});
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#143D2E" }}>
      <SafeAreaProvider>
        <BrandingProvider>
          <AuthProvider>
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
                        // Use the splash brand color as the screen background
                        // so the brief frame between splash unmount and the
                        // login screen mount blends into the splash colour
                        // instead of flashing off-white (FAF9F6).
                        contentStyle: { backgroundColor: "#143D2E" },
                        animation: "fade",
                      }}
                    />
                  </TamperGate>
                </LocationGate>
                {/* App-launch splash overlay (admin-uploaded image + duration).
                    Renders over EVERYTHING for the first N seconds (default 5s)
                    and then unmounts itself. Reads from branding context so it
                    follows admin changes without a rebuild. */}
                <SplashOverlay />
              </TabletContainer>
            </GlobalFont>
          </AuthProvider>
        </BrandingProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  tabletOuter: {
    flex: 1,
    // Subtle gradient-ish dark background so the phone "floats"
    backgroundColor: "#1F2A24",
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 24,
  },
  // Polished Android phone frame around the readable column
  phoneFrame: {
    flex: 1,
    width: "100%",
    maxWidth: READABLE_MAX_WIDTH + 24,
    backgroundColor: "#0B1411",
    borderRadius: 38,
    padding: 12,
    paddingTop: 18,
    overflow: "hidden",
    // Cross-platform shadow: iOS shadow* / Android elevation / Web boxShadow
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.45, shadowRadius: 30, shadowOffset: { width: 0, height: 18 } },
      android: { elevation: 16 },
      default: { boxShadow: "0 18px 50px rgba(0,0,0,0.45)" } as any,
    }),
  },
  // Subtle status-pill at the top of the frame to mimic Android camera notch
  phoneNotch: {
    width: 80,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#2A3A33",
    alignSelf: "center",
    marginBottom: 10,
  },
  tabletInner: {
    flex: 1,
    width: "100%",
    backgroundColor: colors.background,
    borderRadius: 28,
    overflow: "hidden",
  },
});
