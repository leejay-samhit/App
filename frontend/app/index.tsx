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
      router.replace("/admin/home");
    } else if (!user.registration_paid) {
      router.replace("/payment");
    } else if (((user as any).approval_status || "approved") !== "approved") {
      router.replace("/pending-approval" as any);
    } else {
      router.replace("/(tabs)/dashboard");
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
