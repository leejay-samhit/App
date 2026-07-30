/**
 * Shared hook for reading the customer's active delivery location.
 *
 * The shop-home screen owns the WRITE side (GPS capture → AsyncStorage).
 * Everything else that needs to filter by delivery zone (category
 * pages, subcategory pages, checkout guards, etc.) just needs to READ
 * these values, so this hook keeps the keys in one place.
 *
 * Cached values are refreshed on mount and on `refresh()`.  The
 * component using this hook is expected to re-fetch its products when
 * `pincode`/`coords` change — the values are stable references so a
 * useEffect on them is safe.
 */
import { useCallback, useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export const DELIVERY_ADDR_KEY = "@app/deliveryAddress";
export const DELIVERY_PIN_KEY = "@app/deliveryPincode";
export const DELIVERY_COORDS_KEY = "@app/deliveryCoords";

export type DeliveryCoords = { lat: number; lng: number };

export type DeliveryLocation = {
  address: string;
  pincode: string;
  coords: DeliveryCoords | null;
  hasLocation: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
};

export function useDeliveryLocation(): DeliveryLocation {
  const [address, setAddress] = useState<string>("");
  const [pincode, setPincode] = useState<string>("");
  const [coords, setCoords] = useState<DeliveryCoords | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [a, p, c] = await Promise.all([
        AsyncStorage.getItem(DELIVERY_ADDR_KEY),
        AsyncStorage.getItem(DELIVERY_PIN_KEY),
        AsyncStorage.getItem(DELIVERY_COORDS_KEY),
      ]);
      if (a) setAddress(a);
      if (p) setPincode(p);
      if (c) {
        try {
          const parsed = JSON.parse(c);
          if (parsed && typeof parsed.lat === "number" && typeof parsed.lng === "number") {
            setCoords(parsed);
          }
        } catch { /* ignore */ }
      }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return {
    address,
    pincode,
    coords,
    hasLocation: !!(pincode || coords),
    loading,
    refresh,
  };
}
