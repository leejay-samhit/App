/**
 * ONE location-capture engine for the whole app (Sep 2026).
 *
 * The customer "Deliver to" picker used the server's Nominatim reverse
 * geocode at neighbourhood zoom, which very often returned NO pincode (so
 * the shop couldn't match any vendor) and sometimes returned a postcode that
 * doesn't exist in India Post data (the owner saw 517500). The vendor
 * delivery-zone / profile map, meanwhile, used the device geocoder and got
 * pincode + city + state + full address reliably.
 *
 * This helper does BOTH and then validates through `GET /api/geo/resolve`,
 * which only ever hands back a pincode that exists in our catalogue. Both
 * screens now call it, so the two maps can't disagree again.
 */
import * as Location from "expo-location";
import { Alert, Linking, Platform } from "react-native";

import { api } from "./api";

export type CapturedPlace = {
  lat: number;
  lng: number;
  /** Verified 6-digit pincode, or "" when we couldn't confirm one. */
  pincode: string;
  /** The pincode the geocoder suggested but our catalogue rejected. */
  rejectedPincode: string;
  city: string;
  district: string;
  state: string;
  address: string;
  /** Ready-to-print "Area, State · 517644" (pincode omitted when unverified). */
  label: string;
};

/** Ask for foreground location, honouring the "don't ask again" state. */
export async function ensureLocationPermission(): Promise<boolean> {
  if (Platform.OS === "web") {
    if (typeof navigator === "undefined" || !navigator.geolocation) return false;
    return true;
  }
  const current = await Location.getForegroundPermissionsAsync();
  if (current.status === "granted") return true;
  if (!current.canAskAgain) {
    Alert.alert(
      "Location is blocked",
      "Turn on location for Slangcart in Settings so we can find shops that deliver to you.",
      [{ text: "Not now" }, { text: "Open Settings", onPress: () => Linking.openSettings() }],
    );
    return false;
  }
  const asked = await Location.requestForegroundPermissionsAsync();
  if (asked.status === "granted") return true;
  if (!asked.canAskAgain) {
    Alert.alert(
      "Location is blocked",
      "Turn on location for Slangcart in Settings so we can find shops that deliver to you.",
      [{ text: "Not now" }, { text: "Open Settings", onPress: () => Linking.openSettings() }],
    );
  }
  return false;
}

async function readCoords(): Promise<{ lat: number; lng: number } | null> {
  if (Platform.OS === "web") {
    if (typeof navigator === "undefined" || !navigator.geolocation) return null;
    return await new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
        () => resolve(null),
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
      );
    });
  }
  const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
  return { lat: pos.coords.latitude, lng: pos.coords.longitude };
}

/**
 * Capture the device's place. Returns null when permission was refused or
 * GPS is unavailable (the caller shows its own empty state).
 */
export async function captureCurrentPlace(): Promise<CapturedPlace | null> {
  const ok = await ensureLocationPermission();
  if (!ok) return null;
  const coords = await readCoords();
  if (!coords) return null;

  // Device geocoder first — this is the one that reliably yields a pincode.
  let devicePin = "";
  let city = "";
  let district = "";
  let state = "";
  let address = "";
  if (Platform.OS !== "web") {
    try {
      const rev = await Location.reverseGeocodeAsync({ latitude: coords.lat, longitude: coords.lng });
      const r0 = rev?.[0];
      if (r0) {
        devicePin = ((r0 as any).postalCode || "").replace(/\D/g, "").slice(0, 6);
        city = r0.city || r0.name || "";
        district = r0.subregion || r0.district || "";
        state = r0.region || "";
        address = [r0.name, r0.street, r0.district, r0.city, r0.postalCode].filter(Boolean).join(", ");
      }
    } catch { /* server resolve below still fills the gaps */ }
  }

  try {
    const { data } = await api.get<any>("/geo/resolve", {
      params: { lat: coords.lat, lng: coords.lng, pincode: devicePin },
    });
    return {
      lat: coords.lat,
      lng: coords.lng,
      pincode: data?.pincode || "",
      rejectedPincode: data?.rejected_pincode || "",
      city: data?.city || city,
      district: data?.district || district,
      state: data?.state || state,
      address: address || data?.address || "",
      label: data?.label || [city, state].filter(Boolean).join(", "),
    };
  } catch {
    // Server unreachable — fall back to whatever the device told us. The
    // pincode stays UNVERIFIED, so we only keep it when the device (not
    // Nominatim) produced it.
    return {
      lat: coords.lat,
      lng: coords.lng,
      pincode: devicePin,
      rejectedPincode: "",
      city, district, state, address,
      label: [city || district, state].filter(Boolean).join(", ") ||
        `Near ${coords.lat.toFixed(2)}, ${coords.lng.toFixed(2)}`,
    };
  }
}
