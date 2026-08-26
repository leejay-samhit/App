/**
 * useShopCart — one cart controller for every product grid in the shop.
 *
 * Jun 2026. Extracted from the category screen so search results, the home
 * category grid and the category screen all add to cart the same way. Before
 * this, the home/search grid rendered a card with NO add button at all — you
 * had to open the product page to buy anything.
 *
 * Adds are optimistic: the local qty bumps first so the tap feels instant,
 * then reconciles against the server. A failure rolls the number back so the
 * UI never lies about what's in the cart.
 *
 * Decrements go through POST /cart/adjust (delta: -1) because /cart/add
 * rejects qty <= 0; the server deletes the row when qty reaches 0.
 */
import { useCallback, useEffect, useState } from "react";
import { Alert } from "react-native";

import { api, formatApiError } from "./api";

type MinimalProduct = { id: string; name: string };

export function useShopCart() {
  const [cartCount, setCartCount] = useState(0);
  const [cartQty, setCartQty] = useState<Record<string, number>>({});
  const [addedFlash, setAddedFlash] = useState("");

  const refresh = useCallback(async () => {
    try {
      const r = await api.get<any>("/cart");
      const items = r.data?.items || [];
      setCartCount(items.reduce((a: number, it: any) => a + (Number(it.qty) || 1), 0));
      const qmap: Record<string, number> = {};
      items.forEach((it: any) => {
        const pid = it.product_id || it?.product?.id;
        if (pid) qmap[pid] = Number(it.qty) || 0;
      });
      setCartQty(qmap);
    } catch {/* silent — the badge is cosmetic */}
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const addToCart = useCallback(async (p: MinimalProduct) => {
    const prev = cartQty[p.id] || 0;
    setCartQty((m) => ({ ...m, [p.id]: prev + 1 }));
    setCartCount((c) => c + 1);
    try {
      await api.post("/cart/add", { product_id: p.id, qty: 1 });
      setAddedFlash(`Added • ${p.name.slice(0, 32)}`);
      setTimeout(() => setAddedFlash(""), 1600);
      refresh();
    } catch (e) {
      setCartQty((m) => ({ ...m, [p.id]: prev }));
      setCartCount((c) => Math.max(0, c - 1));
      Alert.alert("Couldn't add", formatApiError(e));
    }
  }, [cartQty, refresh]);

  const decrement = useCallback(async (p: MinimalProduct) => {
    const prev = cartQty[p.id] || 0;
    if (prev <= 0) return;
    setCartQty((m) => ({ ...m, [p.id]: prev - 1 }));
    setCartCount((c) => Math.max(0, c - 1));
    try {
      await api.post("/cart/adjust", { product_id: p.id, delta: -1 });
      refresh();
    } catch (e) {
      setCartQty((m) => ({ ...m, [p.id]: prev }));
      setCartCount((c) => c + 1);
      Alert.alert("Couldn't update", formatApiError(e));
    }
  }, [cartQty, refresh]);

  return { cartCount, cartQty, addedFlash, refresh, addToCart, decrement };
}
