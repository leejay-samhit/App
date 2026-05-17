import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "../src/auth";
import { colors } from "../src/theme";

export default function Index() {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user === undefined) return;
    if (user === null) {
      router.replace("/login");
    } else if (user.role === "admin") {
      // Admin's default landing tab is Shop (per product spec) — admin
      // sees the store from a customer's perspective on login.
      router.replace("/admin/shop");
    } else if (!user.registration_paid) {
      router.replace("/payment");
    } else if (((user as any).approval_status || "approved") !== "approved") {
      router.replace("/pending-approval" as any);
    } else {
      // Approved users land directly on the Shop tab so they can start
      // browsing immediately. Dashboard is one tap away via bottom nav.
      router.replace("/(tabs)/shop");
    }
  }, [user]);

  return (
    <View style={styles.center} testID="splash-screen">
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background },
});
