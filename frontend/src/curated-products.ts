// Nov 2026 — Products an admin curated into a Shop Layout block belong to that
// block only. Every plain browse grid (shop home + category screens) hides them
// so the same product isn't listed twice on one screen.
import { useEffect, useState } from "react";
import { api } from "./api";

export function useCuratedProductIds(pincode?: string, refreshTick?: number) {
  const [ids, setIds] = useState<Set<string>>(new Set());
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get<{ items: string[] }>("/shop-layout/curated-product-ids", {
          params: pincode ? { pincode } : {},
        });
        if (!cancelled) setIds(new Set(data?.items || []));
      } catch {
        // Browsing must never break because this cosmetic filter failed.
      }
    })();
    return () => { cancelled = true; };
  }, [pincode, refreshTick]);
  return ids;
}
