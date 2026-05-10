// PromoCarousel — swipeable hero banner with dot indicators on the Shop screen.
// Banners are managed by Admins (image, title, subtitle, CTA, linked product).
// Falls back to the default static "Save 70% on premium picks" card when the
// admin hasn't set any active banners.
import React, { useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Image,
  TouchableOpacity,
  StyleSheet,
  Dimensions,
  NativeSyntheticEvent,
  NativeScrollEvent,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api } from "./api";
import { colors, radii, spacing } from "./theme";

export type PromoBanner = {
  id: string;
  image_data_url: string;
  title?: string;
  subtitle?: string;
  cta_label?: string;
  product_id?: string | null;
  sort_order?: number;
  active?: boolean;
};

type Props = {
  /** Called when the user taps "Shop now". Receives the linked product id (or null). */
  onShopNow: (productId: string | null) => void;
};

export function PromoCarousel({ onShopNow }: Props) {
  const [banners, setBanners] = useState<PromoBanner[]>([]);
  const [page, setPage] = useState(0);
  const scrollRef = useRef<ScrollView | null>(null);
  // Width of the carousel — clamped so it never exceeds the readable column on web/tablet.
  const screenW = Math.min(Dimensions.get("window").width, 600) - 2 * spacing.screen;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ items: PromoBanner[] }>("/promo-banners");
        if (!cancelled) setBanners(res.data?.items || []);
      } catch {
        // Silent — fall back to the default banner below
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Auto-advance every 4s when more than one banner
  useEffect(() => {
    if (banners.length < 2) return;
    const id = setInterval(() => {
      setPage((p) => {
        const next = (p + 1) % banners.length;
        scrollRef.current?.scrollTo({ x: next * screenW, animated: true });
        return next;
      });
    }, 4000);
    return () => clearInterval(id);
  }, [banners.length, screenW]);

  const slides = banners.length > 0 ? banners : [DEFAULT_FALLBACK];

  const handleScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const i = Math.round(e.nativeEvent.contentOffset.x / screenW);
    if (i !== page) setPage(i);
  };

  return (
    <View style={styles.wrap}>
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={handleScroll}
        scrollEventThrottle={16}
        style={{ width: screenW }}
      >
        {slides.map((b) => (
          <View key={b.id} style={[styles.slide, { width: screenW }]}>
            {b.image_data_url ? (
              <Image
                source={{ uri: b.image_data_url }}
                style={styles.bgImage}
                resizeMode="cover"
              />
            ) : (
              // Default green hero blob fallback
              <View style={styles.bgFallback} />
            )}
            <View style={styles.overlay}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                {b.subtitle ? <Text style={styles.eyebrow}>{b.subtitle}</Text> : null}
                {b.title ? <Text style={styles.title}>{b.title}</Text> : null}
                <TouchableOpacity
                  style={styles.cta}
                  onPress={() => onShopNow(b.product_id || null)}
                  testID={`promo-shopnow-${b.id}`}
                >
                  <Text style={styles.ctaText}>{b.cta_label || "Shop now"}</Text>
                  <Feather name="arrow-right" size={14} color={colors.primaryFg} />
                </TouchableOpacity>
              </View>
              {!b.image_data_url ? (
                <View style={styles.blob}>
                  <Feather name="shopping-bag" size={56} color={colors.primary} />
                </View>
              ) : null}
            </View>
          </View>
        ))}
      </ScrollView>
      {/* Dots indicator */}
      {slides.length > 1 ? (
        <View style={styles.dotsRow}>
          {slides.map((_, i) => (
            <View key={i} style={[styles.dot, i === page && styles.dotActive]} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

const DEFAULT_FALLBACK: PromoBanner = {
  id: "__default__",
  image_data_url: "",
  title: "Save 70% on premium picks",
  subtitle: "Limited time",
  cta_label: "Shop now",
  product_id: null,
};

const styles = StyleSheet.create({
  wrap: { marginBottom: 16 },
  slide: {
    height: 152,
    borderRadius: radii.card,
    overflow: "hidden",
    position: "relative",
    backgroundColor: colors.brand100,
  },
  bgImage: { ...StyleSheet.absoluteFillObject },
  bgFallback: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.brand100,
  },
  overlay: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    padding: 18,
    backgroundColor: "rgba(255,255,255,0.0)",
  },
  eyebrow: { fontSize: 11, letterSpacing: 1.4, fontWeight: "800", color: colors.primary, textTransform: "uppercase" },
  title: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.6, marginTop: 4, marginBottom: 12 },
  cta: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.primary,
    alignSelf: "flex-start",
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 999,
  },
  ctaText: { color: colors.primaryFg, fontWeight: "800", fontSize: 12, letterSpacing: 0.2 },
  blob: {
    width: 100, height: 100, borderRadius: 50,
    backgroundColor: "rgba(255,255,255,0.5)",
    alignItems: "center", justifyContent: "center",
  },
  dotsRow: {
    flexDirection: "row", justifyContent: "center", alignItems: "center",
    marginTop: 10, gap: 6,
  },
  dot: {
    width: 6, height: 6, borderRadius: 3,
    backgroundColor: colors.border,
  },
  dotActive: {
    width: 18, backgroundColor: colors.primary,
  },
});
