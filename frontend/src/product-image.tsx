/**
 * ProductImage — THE image component for every product photo in the app.
 *
 * Jun 2026. Three separate bug reports ("images blank after some time",
 * "images blank everywhere in the Android APK", "restored Shopify images
 * missing") all shared one surface: a bare `<Image>` with no loading
 * state, no error state and no retry. When the URL failed — which it did
 * constantly, because product docs referenced expiring third-party CDNs —
 * the user saw an unexplained blank square and nothing else.
 *
 * This component fixes the *display* half of that:
 *   • a soft skeleton while the bytes are in flight
 *   • ONE automatic retry (cache-busted) for transient network blips,
 *     because a release APK otherwise caches the failure for the session
 *   • a neutral placeholder carrying the product name when the image is
 *     genuinely unavailable, so the card still reads as a real product
 *   • stable identity across scroll: the retry counter is keyed on the
 *     resolved URI, so recycling a row never shows a stale error
 *
 * A failure here can never affect the product name, price, Add button or
 * cart — it is contained entirely inside the image box.
 */
import React, { memo, useCallback, useEffect, useState } from "react";
import { View, Text, Image, StyleSheet, ActivityIndicator, StyleProp, ViewStyle, ImageStyle } from "react-native";
import { Feather } from "@expo/vector-icons";

import { resolveImageUrl } from "./api";
import { colors } from "./theme";

type Props = {
  /** Raw value straight off the product doc — may be relative, absolute,
   *  a base64 data URI, empty, null or (from a bad import) not a string. */
  uri?: unknown;
  /** Shown inside the placeholder when the image can't be displayed. */
  name?: string;
  style?: StyleProp<ImageStyle>;
  /** Wrapper style — use when the image fills a fixed-size box. */
  containerStyle?: StyleProp<ViewStyle>;
  resizeMode?: "cover" | "contain" | "center" | "stretch";
  /** Hide the name inside the placeholder (thumbnails in dense lists). */
  compact?: boolean;
  testID?: string;
};

function ProductImageBase({
  uri,
  name,
  style,
  containerStyle,
  resizeMode = "cover",
  compact = false,
  testID,
}: Props) {
  const resolved = resolveImageUrl(typeof uri === "string" ? uri : "");
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(!!resolved);

  // Reset whenever the row is recycled onto a different product.
  useEffect(() => {
    setAttempt(0);
    setFailed(false);
    setLoading(!!resolved);
  }, [resolved]);

  const onError = useCallback(() => {
    // One cache-busted retry covers the common case: a cold request that
    // timed out on a weak mobile connection. A second failure is treated
    // as genuine so we don't spin forever on a dead reference.
    if (attempt < 1) {
      setAttempt((a) => a + 1);
      return;
    }
    setLoading(false);
    setFailed(true);
  }, [attempt]);

  // Stable identities: react-native-web's <Image> re-runs its load effect
  // whenever these callbacks change, so inline arrows caused an infinite
  // onLoadStart -> setLoading loop ("Maximum update depth exceeded").
  const onLoadStart = useCallback(() => setLoading(true), []);
  const onLoad = useCallback(() => { setLoading(false); setFailed(false); }, []);

  if (!resolved || failed) {
    return (
      <View style={[styles.placeholder, style as any, containerStyle]} testID={testID ? `${testID}-placeholder` : undefined}>
        <Feather name="image" size={compact ? 14 : 20} color={colors.textMuted} />
        {!compact && name ? (
          <Text style={styles.placeholderText} numberOfLines={2}>{name}</Text>
        ) : null}
      </View>
    );
  }

  // Cache-buster ONLY on the retry pass — the first (and normally only)
  // request keeps the plain URL so the HTTP cache can serve it.
  const src = attempt > 0
    ? `${resolved}${resolved.includes("?") ? "&" : "?"}r=${attempt}`
    : resolved;

  return (
    <View style={[styles.wrap, containerStyle]}>
      <Image
        source={{ uri: src }}
        style={[style as any, styles.fill]}
        resizeMode={resizeMode}
        onLoadStart={onLoadStart}
        onLoad={onLoad}
        onError={onError}
        testID={testID}
      />
      {loading ? (
        <View style={styles.loader} pointerEvents="none">
          <ActivityIndicator size="small" color={colors.textMuted} />
        </View>
      ) : null}
    </View>
  );
}

export const ProductImage = memo(ProductImageBase);

const styles = StyleSheet.create({
  wrap: { position: "relative" },
  fill: { backgroundColor: colors.surfaceMuted },
  loader: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
  },
  placeholder: {
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingHorizontal: 8,
  },
  placeholderText: {
    fontSize: 10.5,
    color: colors.textMuted,
    textAlign: "center",
    fontWeight: "600",
  },
});
