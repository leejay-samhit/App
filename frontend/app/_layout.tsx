import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { Text, TextInput, View, useWindowDimensions, StyleSheet } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { AuthProvider } from "../src/auth";
import { BrandingProvider, useFontFamily } from "../src/branding";
import { colors } from "../src/theme";
import { TABLET_MIN_WIDTH, READABLE_MAX_WIDTH } from "../src/theme";

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
// foldables / desktops. On phones the wrapper is a no-op.
function TabletContainer({ children }: { children: React.ReactNode }) {
  const { width } = useWindowDimensions();
  const isTablet = width >= TABLET_MIN_WIDTH;
  if (!isTablet) return <>{children}</>;
  return (
    <View style={styles.tabletOuter}>
      <View style={styles.tabletInner}>{children}</View>
    </View>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.background }}>
      <SafeAreaProvider>
        <BrandingProvider>
          <AuthProvider>
            <GlobalFont>
              <StatusBar style="dark" />
              <TabletContainer>
                <Stack
                  screenOptions={{
                    headerShown: false,
                    contentStyle: { backgroundColor: colors.background },
                    animation: "fade",
                  }}
                />
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
    backgroundColor: colors.surfaceMuted, // soft side-rails behind the readable column
    alignItems: "center",
  },
  tabletInner: {
    flex: 1,
    width: "100%",
    maxWidth: READABLE_MAX_WIDTH,
    backgroundColor: colors.background,
  },
});
