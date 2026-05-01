import { useEffect } from "react";
import { View, ViewStyle, StyleProp } from "react-native";
import Animated, { useSharedValue, useAnimatedStyle, withRepeat, withTiming, Easing } from "react-native-reanimated";
import { colors } from "./theme";

export function Skeleton({ width = "100%", height = 14, radius = 8, style }: { width?: number | `${number}%` | "100%"; height?: number; radius?: number; style?: StyleProp<ViewStyle> }) {
  const opacity = useSharedValue(0.5);
  useEffect(() => {
    opacity.value = withRepeat(withTiming(1, { duration: 900, easing: Easing.inOut(Easing.ease) }), -1, true);
  }, [opacity]);
  const animStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return (
    <Animated.View
      style={[
        { width: width as any, height, borderRadius: radius, backgroundColor: colors.surfaceMuted },
        animStyle,
        style,
      ]}
    />
  );
}

export function SkeletonCard({ height = 120, style }: { height?: number; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ backgroundColor: colors.surface, borderRadius: 16, padding: 16, borderWidth: 1, borderColor: colors.border }, style]}>
      <Skeleton width="40%" height={10} />
      <View style={{ height: 12 }} />
      <Skeleton width="70%" height={28} />
      <View style={{ height: 12 }} />
      <Skeleton width="90%" height={10} />
    </View>
  );
}

export function SkeletonRow({ style }: { style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ flexDirection: "row", alignItems: "center", padding: 12, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, gap: 12 }, style]}>
      <Skeleton width={40} height={40} radius={20} />
      <View style={{ flex: 1 }}>
        <Skeleton width="60%" height={12} />
        <View style={{ height: 8 }} />
        <Skeleton width="40%" height={10} />
      </View>
    </View>
  );
}
