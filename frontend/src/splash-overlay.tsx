// SplashOverlay — shows an admin-uploaded image full-screen for N ms after
// the app boots (immediately after the native Expo splash dismisses).
// Reads `splash_image`, `splash_duration_ms`, `splash_bg` from /api/branding.
//
// 2026-06-10 — Killed the multi-stage flash. Previously the user saw:
//   1. Native splash with white-lined PNG (now replaced by solid #143D2E PNG)
//   2. Full-green screen with 3 white "loading dots" while /api/branding fetched
//   3. Full-green screen with app name + tagline (the desired state)
// We now render stage 3 from the very first frame. The branding hook returns
// DEFAULT_BRANDING immediately while the async refresh runs in the background;
// because the cached/last branding lives in branding.tsx state and persists
// across the JS module's lifetime, the user never sees "loading" — they see
// brand name + tagline instantly, animated in via a tiny fade for polish.
import { useEffect, useRef, useState } from "react";
import { Animated, View, Image, StyleSheet, Text } from "react-native";
import { useBranding } from "./branding";

export function SplashOverlay() {
  const b = useBranding();
  const [visible, setVisible] = useState(true);

  // Fade-in for a touch of polish. Starts at opacity 1 immediately so we
  // never see a black/empty frame — the fade is from the splash overlay
  // mounting on top of the native splash, both of which are #143D2E.
  const fade = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    // Default duration 1.5s — short enough to feel snappy, long enough for
    // /api/branding to refresh app_name & tagline if they differ from the
    // hard-coded defaults. The native splash now stays up until we mount
    // (see _layout.tsx), and the native PNG is solid #143D2E — so the
    // handoff is invisible.
    const dur = Math.max(800, Math.min(10000, Number(b.splash_duration_ms || 1500)));
    const t = setTimeout(() => {
      Animated.timing(fade, {
        toValue: 0,
        duration: 220,
        useNativeDriver: true,
      }).start(({ finished }) => {
        if (finished) setVisible(false);
      });
    }, dur);
    return () => clearTimeout(t);
  }, [b.splash_duration_ms, fade]);

  if (!visible) return null;
  const img = b.splash_image;
  const bg  = b.splash_bg || b.colors?.primary || "#143D2E";

  return (
    <Animated.View
      style={[styles.overlay, { backgroundColor: bg, opacity: fade }]}
      pointerEvents="auto"
    >
      {img ? (
        <Image
          source={{ uri: img }}
          style={styles.image}
          resizeMode="cover"
          onError={() => setVisible(false)}
        />
      ) : (
        <View style={styles.fallback}>
          {/* Render brand name + tagline IMMEDIATELY from DEFAULT_BRANDING.
             Once /api/branding refreshes (typically <300ms) the live values
             slot in seamlessly. No dots, no loading flash. */}
          <Text style={styles.fallbackTitle}>{b.app_name || "Welcome"}</Text>
          {b.tagline ? <Text style={styles.fallbackSub}>{b.tagline}</Text> : null}
        </View>
      )}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    alignItems: "center", justifyContent: "center",
    zIndex: 9999,
  },
  // Full-screen splash: image fills the entire viewport (cover crop). The
  // admin-uploaded image should be designed at portrait aspect for best result.
  image:       { width: "100%", height: "100%" },
  fallback:    { alignItems: "center", justifyContent: "center", paddingHorizontal: 32 },
  fallbackTitle: { fontSize: 36, fontWeight: "900", color: "#fff", letterSpacing: -0.5, textAlign: "center" },
  fallbackSub:   { fontSize: 14, fontWeight: "600", color: "rgba(255,255,255,0.85)", marginTop: 10, textAlign: "center" },
});
