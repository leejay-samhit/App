// /app/frontend/src/zoomable-image.tsx
// ─────────────────────────────────────────────────────────────────────────────
// ZoomableImage — phone-gallery-style pinch-to-zoom + pan for a single image.
//
// Implementation notes
// • Uses react-native-gesture-handler's GestureDetector (Gesture API) + a
//   composed Pinch + Pan gesture so users can zoom IN/OUT with two fingers
//   and drag the image around when zoomed.
// • Reanimated v3 shared values keep the transform on the UI thread so the
//   gesture feels native (60fps) on iOS + Android.
// • Double-tap toggles between 1× and 2× (familiar phone-gallery affordance).
// • On web, GH still wires up wheel + touch gestures; pinch on trackpads
//   works out of the box.
// ─────────────────────────────────────────────────────────────────────────────
import React from "react";
import { Image, StyleSheet, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";

const AnimatedImage = Animated.createAnimatedComponent(Image);

type Props = {
  uri: string;
  /** Optional callback fired when the user double-taps while at the
   *  minimum scale (1×) — handy for caller to dismiss the viewer. */
  onDoubleTapAtBase?: () => void;
};

export default function ZoomableImage({ uri, onDoubleTapAtBase }: Props) {
  // Shared values driving the transform — all live on the UI thread.
  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const savedTranslateX = useSharedValue(0);
  const savedTranslateY = useSharedValue(0);

  const MIN = 1;
  const MAX = 5;

  // Pinch — multiply current scale by gesture scale, clamped to [MIN, MAX].
  const pinch = Gesture.Pinch()
    .onUpdate((e) => {
      const next = savedScale.value * e.scale;
      scale.value = Math.max(MIN, Math.min(MAX, next));
    })
    .onEnd(() => {
      savedScale.value = scale.value;
      // Snap back to base if released below 1.05× — feels natural.
      if (scale.value < 1.05) {
        scale.value = withTiming(1);
        translateX.value = withTiming(0);
        translateY.value = withTiming(0);
        savedScale.value = 1;
        savedTranslateX.value = 0;
        savedTranslateY.value = 0;
      }
    });

  // Pan — only meaningful when zoomed in. We let translation grow with the
  // gesture and don't clamp it (browser/native image will look clipped at
  // extreme edges; users naturally pinch out to return to base).
  const pan = Gesture.Pan()
    .averageTouches(true)
    .onUpdate((e) => {
      if (scale.value <= 1.02) return; // ignore pans at base scale
      translateX.value = savedTranslateX.value + e.translationX;
      translateY.value = savedTranslateY.value + e.translationY;
    })
    .onEnd(() => {
      savedTranslateX.value = translateX.value;
      savedTranslateY.value = translateY.value;
    });

  // Double-tap — toggle between 1× and 2×. At base scale, also invokes
  // the optional caller callback (e.g. dismiss the viewer).
  const doubleTap = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      if (scale.value > 1.01) {
        scale.value = withTiming(1);
        translateX.value = withTiming(0);
        translateY.value = withTiming(0);
        savedScale.value = 1;
        savedTranslateX.value = 0;
        savedTranslateY.value = 0;
      } else {
        scale.value = withTiming(2);
        savedScale.value = 2;
        if (onDoubleTapAtBase) runOnJS(onDoubleTapAtBase)();
      }
    });

  // Compose: simultaneous pinch + pan, double-tap exclusive.
  const composed = Gesture.Race(
    doubleTap,
    Gesture.Simultaneous(pinch, pan),
  );

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }));

  return (
    <GestureDetector gesture={composed}>
      <View style={styles.wrap} collapsable={false}>
        <AnimatedImage
          source={{ uri }}
          style={[styles.img, animatedStyle]}
          resizeMode="contain"
        />
      </View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, width: "100%", alignItems: "center", justifyContent: "center" },
  img: { width: "100%", height: "100%" },
});
