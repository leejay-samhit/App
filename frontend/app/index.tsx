import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "../src/auth";
import { adminLanding } from "../src/admin-roles";
import { colors } from "../src/theme";

export default function Index() {
  const { user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (user === undefined) return;
    if (user === null) {
      router.replace("/login");
    } else if (user.role === "admin") {
      // Scoped managers (products / layout / order / vendor+service) only
      // have their own section — the full admin tabs are hidden and the API
      // 403s them, so send them straight to it.
      router.replace(adminLanding(user));
    } else if (!user.registration_paid && !(user as any).subscription_skipped) {
      // Subscription upsell first (Aug-2026). Once the user chooses
      // "Continue without subscription" we never wall them again — they
      // land on Shop like everyone else, with the upgrade banner shown.
      router.replace("/payment");
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
