/**
 * Shimmering skeleton primitive — used app-wide as the "content is
 * loading" placeholder so every screen shows the SAME visual language
 * instead of a mix of spinners, dots, and blank white space.
 *
 * Design principles:
 *   • Same base radius / colour as real cards → the transition from
 *     skeleton → real card feels instant to the eye.
 *   • Powered by react-native-reanimated 4 — one 1600 ms loop, no JS
 *     bridge chatter.
 *   • Composable — call <Skeleton /> for a bare block, or use one of
 *     the higher-level helpers (ProductCardSkeleton, ListRowSkeleton).
 */
import React, { useEffect } from "react";
import { View, StyleSheet, ViewStyle, StyleProp } from "react-native";
import Animated, {
  useSharedValue, useAnimatedStyle, withRepeat, withTiming, Easing,
} from "react-native-reanimated";
import { colors, radii } from "../theme";

type Props = {
  width?: number | `${number}%`;
  height?: number;
  radius?: number;
  style?: StyleProp<ViewStyle>;
};

export function Skeleton({ width = "100%", height = 12, radius = 6, style }: Props) {
  const shimmer = useSharedValue(0.55);
  useEffect(() => {
    shimmer.value = withRepeat(
      withTiming(1, { duration: 900, easing: Easing.inOut(Easing.quad) }),
      -1, true,
    );
  }, []);
  const anim = useAnimatedStyle(() => ({ opacity: shimmer.value }));
  return (
    <Animated.View
      style={[
        {
          width: width as any,
          height,
          borderRadius: radius,
          backgroundColor: colors.surfaceMuted,
        },
        anim,
        style,
      ]}
    />
  );
}

/** Product-card placeholder that matches the real Shop grid tile. */
export function ProductCardSkeleton({ width = "48%" }: { width?: number | `${number}%` }) {
  return (
    <View style={[styles.card, { width: width as any }]}>
      <Skeleton height={120} radius={radii.card - 2} style={{ marginBottom: 10 }} />
      <Skeleton width="80%" height={12} style={{ marginBottom: 6 }} />
      <Skeleton width="55%" height={14} />
    </View>
  );
}

/** Row placeholder for lists (invoices, orders, sales, transactions). */
export function ListRowSkeleton() {
  return (
    <View style={styles.row}>
      <Skeleton width={44} height={44} radius={12} />
      <View style={{ flex: 1 }}>
        <Skeleton width="65%" height={13} style={{ marginBottom: 6 }} />
        <Skeleton width="40%" height={11} />
      </View>
      <Skeleton width={64} height={14} />
    </View>
  );
}

/** Stat-card placeholder for the vendor / admin dashboards. */
export function StatCardSkeleton({ width = "47%" }: { width?: number | `${number}%` }) {
  return (
    <View style={[styles.stat, { width: width as any }]}>
      <Skeleton width={30} height={30} radius={15} style={{ marginBottom: 10 }} />
      <Skeleton width="70%" height={10} style={{ marginBottom: 6 }} />
      <Skeleton width="55%" height={18} />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: 12,
    padding: 12, marginBottom: 8,
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
  },
  stat: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: 14,
    borderWidth: 1, borderColor: colors.border,
  },
});
