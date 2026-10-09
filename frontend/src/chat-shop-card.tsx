/**
 * ChatShopCard — the seller's storefront, pinned at the top of the chat.
 *
 * Oct-2026. Tapping "Ask the Seller" used to drop the buyer into a bare
 * message thread with no idea which shop they were talking to.
 *
 * Layout note (rev 2): the first version squeezed the shop name, the owner
 * name and the location into ONE flex row next to the photo, so on a narrow
 * phone every line clipped mid-word ("Seller Name - Xys…"). The details now
 * live in their own full-width rows UNDER the photo+name header, where they
 * have the whole card to breathe, and nothing is truncated except a genuinely
 * long shop name (which gets two lines before it ellipsises).
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, Image, Linking, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { resolveImageUrl } from "./api";
import { colors, radii } from "./theme";

export type ShopCard = {
  vendor_id: string;
  shop_name: string;
  owner_name?: string;
  image_url?: string;
  location_label?: string;
  city?: string;
  state?: string;
  pincode?: string;
  lat?: number | null;
  lng?: number | null;
  map_url?: string | null;
  product_count?: number;
  delivery_radius_km?: number | null;
};

/** One full-width detail row — icon, label, value. Never clips the label. */
function DetailRow({ icon, label, value }: { icon: any; label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Feather name={icon} size={12} color={colors.textMuted} style={styles.detailIcon} />
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue} numberOfLines={2}>{value}</Text>
    </View>
  );
}

export function ChatShopCard({ shop }: { shop: ShopCard }) {
  const [open, setOpen] = useState(true);
  const img = shop.image_url ? resolveImageUrl(shop.image_url) : "";
  const hasMap = !!shop.map_url;

  const openDirections = () => {
    if (!shop.map_url) return;
    // Prefer the native maps scheme on a device so it lands in whichever app
    // the user actually has; the https URL is the universal fallback.
    if (Platform.OS !== "web" && shop.lat != null && shop.lng != null) {
      const scheme = Platform.OS === "ios"
        ? `maps://?daddr=${shop.lat},${shop.lng}&dirflg=d`
        : `geo:${shop.lat},${shop.lng}?q=${shop.lat},${shop.lng}(${encodeURIComponent(shop.shop_name)})`;
      Linking.openURL(scheme).catch(() => Linking.openURL(shop.map_url!));
      return;
    }
    Linking.openURL(shop.map_url);
  };

  if (!open) {
    return (
      <TouchableOpacity
        onPress={() => setOpen(true)}
        style={styles.strip}
        testID="chat-shop-strip"
        activeOpacity={0.8}
      >
        <Feather name="shopping-bag" size={13} color={colors.primary} />
        <Text style={styles.stripText} numberOfLines={1}>{shop.shop_name}</Text>
        <Text style={styles.stripHint}>Shop details</Text>
        <Feather name="chevron-down" size={15} color={colors.textMuted} />
      </TouchableOpacity>
    );
  }

  const location = shop.location_label && shop.location_label !== "Location not shared"
    ? shop.location_label
    : "";

  return (
    <View style={styles.card} testID="chat-shop-card">
      {/* ── Header: photo + shop name. Name gets 2 lines before it clips. ── */}
      <View style={styles.header}>
        {img ? (
          <Image source={{ uri: img }} style={styles.thumb} resizeMode="cover" />
        ) : (
          <View style={[styles.thumb, styles.thumbFallback]}>
            <Feather name="shopping-bag" size={20} color={colors.primary} />
          </View>
        )}

        <View style={styles.headerText}>
          <View style={styles.sellerTag}>
            <Feather name="check-circle" size={9} color={colors.primaryFg} />
            <Text style={styles.sellerTagText}>VERIFIED SELLER</Text>
          </View>
          <Text style={styles.name} numberOfLines={2}>{shop.shop_name}</Text>
        </View>

        <TouchableOpacity
          onPress={() => setOpen(false)}
          style={styles.collapse}
          testID="chat-shop-collapse"
          hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        >
          <Feather name="chevron-up" size={16} color={colors.textMuted} />
        </TouchableOpacity>
      </View>

      {/* ── Details: full-width rows, so nothing is half-visible ── */}
      <View style={styles.details}>
        {shop.owner_name ? (
          <DetailRow icon="user" label="Seller" value={shop.owner_name} />
        ) : null}
        <DetailRow
          icon="map-pin"
          label="Location"
          value={location || "Not shared by the seller yet"}
        />
        {shop.product_count ? (
          <DetailRow
            icon="package"
            label="Listed"
            value={`${shop.product_count} item${shop.product_count === 1 ? "" : "s"}${
              shop.delivery_radius_km ? ` · delivers up to ${shop.delivery_radius_km} km` : ""
            }`}
          />
        ) : null}
      </View>

      <TouchableOpacity
        onPress={openDirections}
        disabled={!hasMap}
        style={[styles.mapBtn, !hasMap && styles.mapBtnOff]}
        testID="chat-shop-directions"
        activeOpacity={0.85}
      >
        <Feather
          name="navigation"
          size={14}
          color={hasMap ? colors.primaryFg : colors.textMuted}
        />
        <Text style={[styles.mapBtnText, !hasMap && { color: colors.textMuted }]}>
          {hasMap ? "Open shop location & directions" : "Location not shared yet"}
        </Text>
        {hasMap ? (
          <Feather name="external-link" size={13} color={colors.primaryFg} />
        ) : null}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.brand100,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    paddingHorizontal: 14, paddingTop: 12, paddingBottom: 12,
  },
  header: { flexDirection: "row", alignItems: "flex-start", gap: 11 },
  thumb: {
    width: 46, height: 46, borderRadius: 12,
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1, borderColor: colors.border,
  },
  thumbFallback: { alignItems: "center", justifyContent: "center" },
  headerText: { flex: 1, paddingTop: 1 },
  sellerTag: {
    alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 3,
    backgroundColor: colors.primary,
    paddingHorizontal: 6, paddingVertical: 2.5,
    borderRadius: 999, marginBottom: 5,
  },
  sellerTagText: {
    fontSize: 8, fontWeight: "900", letterSpacing: 0.8, color: colors.primaryFg,
  },
  name: {
    fontSize: 15, lineHeight: 19, fontWeight: "900",
    color: colors.textMain, letterSpacing: -0.3,
  },
  collapse: { padding: 2, marginTop: 2 },
  details: {
    marginTop: 11, marginBottom: 11,
    backgroundColor: colors.surface,
    borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.border,
    paddingVertical: 4, paddingHorizontal: 10,
  },
  detailRow: {
    flexDirection: "row", alignItems: "flex-start",
    paddingVertical: 7, gap: 7,
  },
  detailIcon: { marginTop: 2, width: 13 },
  detailLabel: {
    width: 62, fontSize: 10.5, fontWeight: "900",
    letterSpacing: 0.3, color: colors.textMuted, marginTop: 1.5,
  },
  detailValue: {
    flex: 1, fontSize: 12.5, lineHeight: 17,
    fontWeight: "700", color: colors.textMain,
  },
  mapBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7,
    backgroundColor: colors.primary, minHeight: 44, borderRadius: 12,
    paddingHorizontal: 12,
  },
  mapBtnOff: {
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1, borderColor: colors.border,
  },
  mapBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 12.5 },
  strip: {
    flexDirection: "row", alignItems: "center", gap: 7,
    backgroundColor: colors.brand100,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    paddingHorizontal: 14, paddingVertical: 9,
  },
  stripText: { flex: 1, fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  stripHint: { fontSize: 10.5, fontWeight: "700", color: colors.textMuted },
});
