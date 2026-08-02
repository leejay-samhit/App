/**
 * Unified screen-level entrance animation used across the whole app.
 *
 * Every screen / section in Slangcart wraps its content in a
 * <FadeSlideIn> so:
 *   • the fade duration and easing curve are IDENTICAL everywhere
 *   • the vertical slide amount matches (12 px upward)
 *   • no more mismatched "one screen fades, another slides from below"
 *
 * Powered by react-native-reanimated 4 — no extra dependencies.
 *
 * USAGE:
 *   <FadeSlideIn>
 *     <YourScreenBody />
 *   </FadeSlideIn>
 *
 *   // Staggered lists — apply an increasing `delay` so items cascade.
 *   {items.map((it, i) => (
 *     <FadeSlideIn key={it.id} delay={i * 40}><Card ... /></FadeSlideIn>
 *   ))}
 *
 *   // Skip animation on subsequent renders (already visible content).
 *   <FadeSlideIn once>...</FadeSlideIn>
 */
import React, { useEffect } from "react";
import { StyleProp, ViewStyle } from "react-native";
import Animated, {
  useSharedValue, useAnimatedStyle, withTiming, withDelay, Easing,
} from "react-native-reanimated";

/** Slangcart's canonical entrance timing constants. */
export const ANIM = {
  duration: 320,           // primary fade+slide duration (ms)
  fastDuration: 220,       // secondary refreshes / re-fetches
  slideDistance: 12,       // px the content travels upward
  easing: Easing.out(Easing.cubic),
  stagger: 42,             // ms between staggered list items
} as const;

type Props = {
  children: React.ReactNode;
  /** Optional delay (ms) — pass i * ANIM.stagger for cascading lists. */
  delay?: number;
  /** When true, uses ANIM.fastDuration instead of ANIM.duration. */
  fast?: boolean;
  /** Reset & re-run the animation when this value changes. Useful for
   *  pull-to-refresh — pass your `refreshTick` counter here so the
   *  re-fetched content fades in again instead of appearing instantly. */
  triggerKey?: number | string;
  /** Additional style forwarded to the animated container. */
  style?: StyleProp<ViewStyle>;
};

export function FadeSlideIn({ children, delay = 0, fast, triggerKey, style }: Props) {
  const opacity = useSharedValue(0);
  const translateY = useSharedValue(ANIM.slideDistance);

  useEffect(() => {
    // Reset then run.  On the very first mount the initial values are
    // already 0 / +12 so the animation kicks off from the correct
    // starting position; `triggerKey` re-runs it on demand.
    opacity.value = 0;
    translateY.value = ANIM.slideDistance;
    const duration = fast ? ANIM.fastDuration : ANIM.duration;
    opacity.value = withDelay(delay, withTiming(1, { duration, easing: ANIM.easing }));
    translateY.value = withDelay(delay, withTiming(0, { duration, easing: ANIM.easing }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerKey]);

  const styleAnim = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ translateY: translateY.value }],
  }));

  return <Animated.View style={[styleAnim, style]}>{children}</Animated.View>;
}

/** Convenience: apply the same animation to a plain View — good for
 *  sections that are conditionally mounted (empty states, hero cards). */
export function FadeIn({ children, delay = 0, fast, style }: Omit<Props, "triggerKey">) {
  return <FadeSlideIn delay={delay} fast={fast} style={style}>{children}</FadeSlideIn>;
}
