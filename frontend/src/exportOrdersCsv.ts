/**
 * exportOrdersCsv — client-side CSV export for admin + vendor Orders
 * screens (Sept 2026).
 *
 * Owner spec:
 *   > "Add download option to the Vendor and Admin order Status. In that
 *    excel — User Name, Mobile, Product Name, Amount, Stage, Vendor
 *    Name, Vendor Mail, Vendor Mobile."
 *
 * Design decisions:
 *   1. CSV, not XLSX.  Excel/Numbers/Sheets all open CSV natively; a
 *      full XLSX writer would add ~250KB of bundle for zero UX gain.
 *   2. One row PER-LINE-ITEM.  A 3-item order becomes 3 CSV rows sharing
 *      the same order-id/user/vendor/stage.  This lets an ops person
 *      pivot on product name without collapsing sub-totals.
 *   3. UTF-8 with BOM prefix so Excel on Windows recognises the encoding
 *      and doesn't corrupt ₹ symbols.
 *   4. Save + share flow:
 *        - Native: FileSystem.writeAsStringAsync → Sharing.shareAsync.
 *        - Web: fall back to a Blob + `<a download>` link, no expo deps.
 */
import { Platform } from "react-native";

// Public shape — small enough to type inline rather than import a bloated
// Order type from every consumer.
export type ExportOrderLike = {
  id: string;
  user_id?: string;
  created_at?: string;
  total?: number;
  status: string;
  items: Array<{ name?: string; price?: number; qty?: number }>;
  buyer_name?: string; buyer_email?: string; buyer_phone?: string;
  vendor_id?: string; vendor_name?: string; vendor_email?: string; vendor_phone?: string;
};

const COLUMNS = [
  "Order ID",
  "Order Date",
  "User Name",
  "User Email",
  "User Mobile",
  "Product Name",
  "Unit Price",
  "Qty",
  "Line Total",
  "Order Total",
  "Order Stage",
  "Vendor Name",
  "Vendor Email",
  "Vendor Mobile",
] as const;

/** RFC 4180 escaping — wrap in quotes if the cell contains ",", '"' or newline. */
function csvCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n") || s.includes("\r")) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

function ordersToCsv(orders: ExportOrderLike[]): string {
  const rows: string[] = [];
  rows.push(COLUMNS.join(","));
  for (const o of orders) {
    const date = o.created_at ? new Date(o.created_at).toLocaleString() : "";
    const buyerName = o.buyer_name || "";
    const buyerEmail = o.buyer_email || "";
    const buyerPhone = o.buyer_phone || "";
    const vendorName = o.vendor_name || "";
    const vendorEmail = o.vendor_email || "";
    const vendorPhone = o.vendor_phone || "";
    const stage = (o.status || "").toUpperCase();
    const orderTotal = o.total ?? 0;
    const items = Array.isArray(o.items) && o.items.length > 0 ? o.items : [{ name: "-", price: 0, qty: 1 }];
    for (const it of items) {
      const unit = Number(it.price || 0);
      const qty = Number(it.qty || 1);
      const line = unit * qty;
      rows.push([
        o.id,
        date,
        buyerName,
        buyerEmail,
        buyerPhone,
        it.name || "-",
        unit.toFixed(2),
        qty,
        line.toFixed(2),
        orderTotal,
        stage,
        vendorName,
        vendorEmail,
        vendorPhone,
      ].map(csvCell).join(","));
    }
  }
  return rows.join("\r\n");
}

/**
 * Build the CSV, then either share it via the native sharing sheet
 * (iOS/Android) or trigger a browser download (web).
 */
export async function downloadOrdersCsv(
  orders: ExportOrderLike[],
  opts: { title: string; scope: "admin" | "vendor" },
): Promise<void> {
  const csv = "\uFEFF" + ordersToCsv(orders); // UTF-8 BOM for Excel
  const safeTitle = opts.title.replace(/[^\w-]+/g, "-").slice(0, 60);
  const fname = `${safeTitle}-${new Date().toISOString().slice(0, 10)}.csv`;

  if (Platform.OS === "web") {
    // Web path — dynamic imports would break Metro, use DOM APIs directly.
    // @ts-ignore — DOM globals only exist on web.
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    // @ts-ignore
    const url = URL.createObjectURL(blob);
    // @ts-ignore
    const a = document.createElement("a");
    a.href = url;
    a.download = fname;
    // @ts-ignore
    document.body.appendChild(a);
    a.click();
    // @ts-ignore
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return;
  }

  // Native path — require the expo bridges lazily so metro doesn't ship
  // them to the web bundle.  Try the legacy shim first (SDK 54+ moved
  // `writeAsStringAsync` + `cacheDirectory` to /legacy while migration
  // continues); fall back to the root import on older SDKs.
  let FileSystem: any;
  try {
    FileSystem = await import("expo-file-system/legacy");
  } catch {
    FileSystem = await import("expo-file-system");
  }
  const Sharing = await import("expo-sharing");
  const cacheDir = FileSystem.cacheDirectory || FileSystem.Paths?.cache?.uri || "";
  if (!cacheDir || typeof FileSystem.writeAsStringAsync !== "function") {
    throw new Error("expo-file-system API mismatch — cannot write CSV to cache.");
  }
  const fileUri = `${cacheDir}${fname}`;
  await FileSystem.writeAsStringAsync(fileUri, csv, {
    encoding: FileSystem.EncodingType?.UTF8 || "utf8",
  });
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(fileUri, {
      mimeType: "text/csv",
      dialogTitle: `Export orders (${opts.scope})`,
      UTI: "public.comma-separated-values-text",
    });
  }
}
