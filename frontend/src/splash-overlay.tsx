// SplashOverlay — shows an admin-uploaded image full-screen for N ms after
// the app boots (immediately after the native Expo splash dismisses).
// Reads `splash_image`, `splash_duration_ms`, `splash_bg` from /api/branding.
import { useEffect, useState } from "react";
import { View, Image, StyleSheet, Text } from "react-native";
import { useBranding } from "./branding";

export function SplashOverlay() {
  const b = useBranding();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    // Default duration 5s if branding doesn't specify
    const dur = Math.max(1000, Math.min(10000, Number(b.splash_duration_ms || 5000)));
    const t = setTimeout(() => setVisible(false), dur);
    return () => clearTimeout(t);
  }, [b.splash_duration_ms]);

  if (!visible) return null;
  const img = b.splash_image;
  const bg  = b.splash_bg || b.colors?.primary || "#143D2E";

  return (
    <View style={[styles.overlay, { backgroundColor: bg }]} pointerEvents="auto">
      {img ? (
        <Image
          source={{ uri: img }}
          style={styles.image}
          resizeMode="cover"
          onError={() => setVisible(false)}
        />
      ) : (
        <View style={styles.fallback}>
          <Text style={styles.fallbackTitle}>{b.app_name || "Welcome"}</Text>
          {b.tagline ? <Text style={styles.fallbackSub}>{b.tagline}</Text> : null}
        </View>
      )}
    </View>
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
