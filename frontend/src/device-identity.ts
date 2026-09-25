// Device identity helpers (Oct 2026) — serial numbers + IMEIs per unit.
//
// A product carries `serial_number` / `imei_1` / `imei_2` (unit #1, kept for
// backwards compatibility) plus `device_units[]`, one row per physical unit
// in stock. POS billing must find a product by ANY of those codes, so the
// matching logic lives here and is shared by mobile and web.

export type DeviceUnit = {
  serial_number?: string;
  imei_1?: string;
  imei_2?: string;
};

export type DeviceIdentityHolder = {
  serial_number?: string;
  imei_1?: string;
  imei_2?: string;
  device_units?: DeviceUnit[] | null;
};

const norm = (v: any) => String(v ?? "").trim();

/** Every serial / IMEI on a product, deduped, with a human label each. */
export function deviceCodes(p: DeviceIdentityHolder): { code: string; label: string }[] {
  const out: { code: string; label: string }[] = [];
  const seen = new Set<string>();
  const push = (code: string, label: string) => {
    const c = norm(code);
    if (!c) return;
    const key = c.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ code: c, label });
  };
  push(p.serial_number || "", "Serial");
  push(p.imei_1 || "", "IMEI-1");
  push(p.imei_2 || "", "IMEI-2");
  (p.device_units || []).forEach((u, i) => {
    push(u?.serial_number || "", `Unit ${i + 1} serial`);
    push(u?.imei_1 || "", `Unit ${i + 1} IMEI-1`);
    push(u?.imei_2 || "", `Unit ${i + 1} IMEI-2`);
  });
  return out;
}

/**
 * Does `query` match one of the product's device codes?
 * Returns the matched code + label so the UI can show WHY it matched.
 * Matching is case-insensitive and ignores spaces / dashes so a scanned
 * "1234-0987" still finds serial "12340987".
 */
export function matchDeviceCode(
  p: DeviceIdentityHolder,
  query: string,
): { code: string; label: string } | null {
  const q = norm(query).toLowerCase().replace(/[\s-]/g, "");
  if (!q) return null;
  for (const c of deviceCodes(p)) {
    if (c.code.toLowerCase().replace(/[\s-]/g, "").includes(q)) return c;
  }
  return null;
}

/** How many units carry at least one code — shown as "10 units tracked". */
export function trackedUnitCount(p: DeviceIdentityHolder): number {
  return (p.device_units || []).filter(
    (u) => norm(u?.serial_number) || norm(u?.imei_1) || norm(u?.imei_2),
  ).length;
}
