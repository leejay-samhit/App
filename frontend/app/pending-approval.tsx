import { useCallback, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, ScrollView, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { useBranding } from "../src/branding";
import { colors, radii, spacing } from "../src/theme";

/**
 * Shown to users whose registration is paid but awaiting finance approval
 * (or whose account was rejected). Gives them clear status + what to do next.
 */
export default function PendingApproval() {
  const router = useRouter();
  const { user, refresh, logout } = useAuth();
  const { pending_hero } = useBranding();
  const [refreshing, setRefreshing] = useState(false);

  const status = (user as any)?.approval_status || "pending";
  const category = (user as any)?.approval_reject_category as string | undefined;
  const reason = (user as any)?.approval_reject_reason as string | undefined;

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
      // If user has been approved in the meantime, index.tsx will route them on next render.
      if ((user as any)?.approval_status === "approved") {
        router.replace("/(tabs)/dashboard");
      }
    } catch (e) {
      // silent
    } finally {
      setRefreshing(false);
    }
  }, [refresh, router, user]);

  useFocusEffect(
    useCallback(() => {
      onRefresh();
    }, [onRefresh]),
  );

  const isRejected = status === "rejected";
  const title = isRejected ? "Registration rejected" : pending_hero;
  const iconName: any = isRejected ? "x-octagon" : "clock";
  const tint = isRejected ? "#B3261E" : colors.warning;
  const tintBg = isRejected ? "#FCE9E5" : "#FFF4E5";

  const categoryLabel = (c?: string) => {
    switch (c) {
      case "payment_unsuccessful": return "Payment unsuccessful";
      case "referral_code_mistake": return "Referral code mistake";
      case "other": return "Other";
      default: return c || "Other";
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        <View style={styles.topRow}>
          <Text style={styles.overline}>STATUS</Text>
          <TouchableOpacity
            onPress={async () => {
              await logout();
              router.replace("/login");
            }}
            style={styles.iconBtn}
            testID="pending-logout"
          >
            <Feather name="log-out" size={16} color={colors.textMain} />
          </TouchableOpacity>
        </View>

        <View style={[styles.hero, { backgroundColor: tintBg }]}>
          <View style={[styles.heroIconWrap, { backgroundColor: "#fff" }]}>
            {refreshing ? (
              <ActivityIndicator color={tint} />
            ) : (
              <Feather name={iconName} size={28} color={tint} />
            )}
          </View>
          <Text style={[styles.h1, { color: isRejected ? "#7A1F18" : colors.textMain }]}>{title}</Text>
          <Text style={styles.subtitle}>
            {isRejected
              ? "Unfortunately, your registration was not approved. Review the details below or contact support."
              : "Your payment has been received. A member of our finance team is reviewing your account. You'll get access as soon as it's approved — usually within a few hours."}
          </Text>
        </View>

        {isRejected ? (
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.rowLabel}>Reason category</Text>
              <Text style={styles.rowValue}>{categoryLabel(category)}</Text>
            </View>
            {reason ? (
              <>
                <View style={styles.divider} />
                <Text style={styles.rowLabel}>Admin note</Text>
                <Text style={styles.rowLong}>{reason}</Text>
              </>
            ) : null}
          </View>
        ) : (
          <View style={styles.card}>
            <View style={styles.stepRow}>
              <View style={[styles.stepCircle, styles.stepDone]}><Feather name="check" size={14} color="#fff" /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.stepTitle}>Payment received</Text>
                <Text style={styles.stepBody}>Your registration fee was successfully paid.</Text>
              </View>
            </View>
            <View style={[styles.stepLine]} />
            <View style={styles.stepRow}>
              <View style={[styles.stepCircle, styles.stepActive]}>
                <ActivityIndicator size="small" color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.stepTitle}>Finance review</Text>
                <Text style={styles.stepBody}>Our finance team is verifying your registration.</Text>
              </View>
            </View>
            <View style={[styles.stepLine, { opacity: 0.4 }]} />
            <View style={styles.stepRow}>
              <View style={[styles.stepCircle, styles.stepPending]}><Feather name="key" size={14} color={colors.textMuted} /></View>
              <View style={{ flex: 1 }}>
                <Text style={[styles.stepTitle, { color: colors.textMuted }]}>Account unlocked</Text>
                <Text style={styles.stepBody}>Log in and start earning referral commissions.</Text>
              </View>
            </View>
          </View>
        )}

        <View style={styles.card}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Account</Text>
            <Text style={styles.rowValue}>{user?.email}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Referral code</Text>
            <Text style={styles.rowValueMono}>{(user as any)?.referral_code}</Text>
          </View>
        </View>

        <TouchableOpacity onPress={onRefresh} style={styles.primaryBtn} testID="pending-refresh">
          {refreshing ? <ActivityIndicator color={colors.primaryFg} /> : (
            <>
              <Feather name="refresh-cw" size={16} color={colors.primaryFg} />
              <Text style={styles.primaryBtnText}> Check status</Text>
            </>
          )}
        </TouchableOpacity>

        <Text style={styles.note}>
          Need help? Contact us at <Text style={{ fontWeight: "700", color: colors.textMain }}>support@networkpay.app</Text>
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 40 },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 20 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700" },
  iconBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  hero: { borderRadius: radii.card, padding: 24, alignItems: "center", marginBottom: 20 },
  heroIconWrap: { width: 72, height: 72, borderRadius: 36, alignItems: "center", justifyContent: "center", marginBottom: 16 },
  h1: { fontSize: 26, fontWeight: "800", letterSpacing: -1, textAlign: "center", marginBottom: 10 },
  subtitle: { fontSize: 14, color: colors.textMuted, lineHeight: 21, textAlign: "center" },
  card: { backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, padding: 16, marginBottom: 12 },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 6 },
  rowLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600" },
  rowValue: { fontSize: 13, color: colors.textMain, fontWeight: "700" },
  rowValueMono: { fontSize: 13, color: colors.textMain, fontWeight: "800", letterSpacing: 1 },
  rowLong: { fontSize: 13, color: colors.textMain, marginTop: 8, lineHeight: 20 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 12 },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  stepCircle: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  stepDone: { backgroundColor: colors.success },
  stepActive: { backgroundColor: colors.warning },
  stepPending: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  stepLine: { height: 16, width: 2, marginLeft: 15, backgroundColor: colors.border, marginVertical: 2 },
  stepTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  stepBody: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14, marginTop: 4 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 15 },
  note: { textAlign: "center", color: colors.textMuted, fontSize: 12, marginTop: 16 },
});
