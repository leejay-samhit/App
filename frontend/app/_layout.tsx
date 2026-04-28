import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { Text, TextInput } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { AuthProvider } from "../src/auth";
import { BrandingProvider, useFontFamily } from "../src/branding";
import { colors } from "../src/theme";

// Apply the active font to every Text/TextInput by extending defaultProps.
function GlobalFont({ children }: { children: React.ReactNode }) {
  const family = useFontFamily();
  // Set defaultProps once we know the family. Subsequent re-renders will pick it up.
  // @ts-ignore react-native runtime allows this
  (Text as any).defaultProps = (Text as any).defaultProps || {};
  // @ts-ignore
  (Text as any).defaultProps.style = family ? { fontFamily: family } : undefined;
  // @ts-ignore
  (TextInput as any).defaultProps = (TextInput as any).defaultProps || {};
  // @ts-ignore
  (TextInput as any).defaultProps.style = family ? { fontFamily: family } : undefined;
  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.background }}>
      <SafeAreaProvider>
        <BrandingProvider>
          <AuthProvider>
            <GlobalFont>
              <StatusBar style="dark" />
              <Stack
                screenOptions={{
                  headerShown: false,
                  contentStyle: { backgroundColor: colors.background },
                  animation: "fade",
                }}
              />
            </GlobalFont>
          </AuthProvider>
        </BrandingProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
