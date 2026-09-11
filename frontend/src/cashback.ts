/**
 * Cashback + delivery display helpers.
 *
 * Display only. Every rupee that actually moves is calculated by the
 * backend (`core/cashback.py` / `core/delivery_charges.py`) — these helpers
 * exist so the product card, product page and cart all show the SAME number
 * the server will later pay.
 */
import { useEffect, useState } from "react";
import { api } from "./api";

export type ShopMoneyConfig = {
  max_cashback_pct: number;
  default_cashback_pct: number;
  cashback_enabled: boolean;
  delivery_charge_enabled: boolean;
  delivery_charge_flat: number;
  delivery_free_threshold: number;
  delivery_cart_max: number;
};

export const DEFAULT_CONFIG: ShopMoneyConfig = {
  max_cashback_pct: 10,
  default_cashback_pct: 0,
  cashback_enabled: true,
  delivery_charge_enabled: true,
  delivery_charge_flat: 0,
  delivery_free_threshold: 0,
  delivery_cart_max: 0,
};

let cached: ShopMoneyConfig | null = null;

/** Platform ceiling — mirrored from the backend so the UI can never offer
 *  a value the server would reject. */
export const MAX_CASHBACK_PCT = 10;

export function clampCashbackPct(value: any, max = MAX_CASHBACK_PCT): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.round(Math.min(n, max) * 100) / 100;
}

/** THE formula, mirrored: amount × pct ÷ 100. */
export function cashbackAmount(amount: any, pct: any, max = MAX_CASHBACK_PCT): number {
  const base = Number(amount);
  if (!Number.isFinite(base) || base <= 0) return 0;
  return Math.round(((base * clampCashbackPct(pct, max)) / 100) * 100) / 100;
}

/** Effective cashback % for a product: the vendor's value, else the admin
 *  default. Clamped both ways. */
export function effectiveCashbackPct(product: any, cfg: ShopMoneyConfig): number {
  if (!cfg.cashback_enabled) return 0;
  const raw = product?.cashback_pct;
  const value = raw === null || raw === undefined || raw === "" ? cfg.default_cashback_pct : raw;
  return clampCashbackPct(value, cfg.max_cashback_pct);
}

export function useShopMoneyConfig(): ShopMoneyConfig {
  const [cfg, setCfg] = useState<ShopMoneyConfig>(cached || DEFAULT_CONFIG);
  useEffect(() => {
    if (cached) return;
    let alive = true;
    api
      .get<ShopMoneyConfig>("/cashback-config")
      .then(({ data }) => {
        cached = { ...DEFAULT_CONFIG, ...data };
        if (alive) setCfg(cached);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return cfg;
}
