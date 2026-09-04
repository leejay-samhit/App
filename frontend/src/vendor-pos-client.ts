// /app/frontend/src/vendor-pos-client.ts
// ─────────────────────────────────────────────────────────────────────────────
// Thin axios wrapper for the vendor Cloud-POS backend (mirrors the same
// endpoints the web frontend uses — `network-pay-1` implemented these
// per SALES_BACKEND_SPEC.md on 29-Jun-2026). Full parity with the web
// vendor module so the mobile APK can ring up sales, view analytics,
// manage settings and reconcile cash from the phone.
// ─────────────────────────────────────────────────────────────────────────────
import { api } from "./api";

export type PosPaymentMode =
  | "cash" | "upi" | "debit" | "credit" | "netbank" | "wallet" | "credit_sale";
export type PosCustomerKind = "walkin" | "named";
export type PosSaleStatus = "completed" | "cancelled" | "refunded";

export type PosSettings = {
  vendor_id: string;
  invoice_prefix: string;
  invoice_pad: number;
  business_name: string;
  business_address: string;
  business_phone: string;
  business_email: string;
  business_gstin: string;
  default_gst_pct: number;
  gst_inclusive: boolean;
  opening_balance: number;
};

export type PosSaleItem = {
  product_id: string;
  name: string;
  hsn?: string | null;
  unit?: string;
  qty: number;
  price: number;
  discount?: string | null;   // "5%" or "50" (kept as string)
  gst_pct?: number;
  discount_amount?: number;
  taxable?: number;
  tax_amount?: number;
  line_total?: number;
  cost?: number;
  stock_before?: number;
};

export type PosPayment = {
  mode: PosPaymentMode;
  amount: number;
  reference?: string | null;
};

export type PosCustomer = {
  kind: PosCustomerKind;
  name: string;
  phone?: string | null;
  gstin?: string | null;
  address?: string | null;
  email?: string | null;
};

export type PosSaleTotals = {
  subtotal: number;
  gst_total: number;
  discount_total: number;
  bill_discount: number;
  round_off: number;
  grand_total: number;
  profit: number;
};

export type PosSale = {
  id: string;
  vendor_id: string;
  invoice_no: string;
  created_at: string;
  status: PosSaleStatus;
  cancelled_at?: string | null;
  refunded_at?: string | null;
  refund_reason?: string | null;
  customer: PosCustomer;
  gst_inclusive: boolean;
  totals: PosSaleTotals;
  notes: string;
  items: PosSaleItem[];
  payments: PosPayment[];
  client_id?: string | null;
};

export type PosSalesList = { total: number; limit: number; offset: number; items: PosSale[] };

export type PosDashboard = {
  today: { bills: number; turnover: number; gst: number; profit: number; items: number };
  month: { bills: number; turnover: number; gst: number; profit: number; items: number };
};

export type PosCashSummary = {
  date: string;
  by_mode: Record<string, { amount: number; count: number }>;
  opening_balance: number;
  expected_close: number;
  cash_received: number;
  /** Total across every payment mode for the day (all-mode turnover). */
  total_collected?: number;
  /** Completed bill count for the day. */
  bills?: number;
};

export type PosStatementRow = {
  id: string;
  invoice_no: string;
  created_at: string;
  customer: string;
  amount: number;
  running: number;
};

export type PosAnalyticsProduct = { product_id: string; name: string; qty: number; revenue: number; gst: number };
export type PosAnalytics = {
  days: number;
  daily: { date: string; turnover: number; profit: number; bills: number }[];
  top_sold: PosAnalyticsProduct[];
  top_revenue: PosAnalyticsProduct[];
  top_gst: PosAnalyticsProduct[];
  least_sold: PosAnalyticsProduct[];
};

export type PosCustomerRow = {
  id: string;
  vendor_id: string;
  name: string;
  phone?: string;
  email?: string;
  gstin?: string;
  address?: string;
  total_spend: number;
  bills_count: number;
  last_seen?: string;
};

// ─── Settings ───────────────────────────────────────────────────────
export const getPosSettings = async (): Promise<PosSettings> =>
  (await api.get<PosSettings>("/vendor/me/pos/settings")).data;

export const updatePosSettings = async (patch: Partial<PosSettings>): Promise<PosSettings> =>
  (await api.put<PosSettings>("/vendor/me/pos/settings", patch)).data;

// ─── Invoice counter ────────────────────────────────────────────────
export const peekInvoiceNo = async (): Promise<string> =>
  (await api.post<{ invoice_no: string }>("/vendor/me/pos/invoice/peek")).data.invoice_no;

export const consumeInvoiceNo = async (): Promise<string> =>
  (await api.post<{ invoice_no: string }>("/vendor/me/pos/invoice/consume")).data.invoice_no;

// ─── Sales ──────────────────────────────────────────────────────────
export type CreateSalePayload = {
  items: PosSaleItem[];
  payments: PosPayment[];
  customer?: PosCustomer;
  gst_inclusive?: boolean;
  bill_discount?: string | null;
  round_off?: boolean;
  notes?: string;
  invoice_no?: string;
  client_id?: string;
};

export const createSale = async (payload: CreateSalePayload): Promise<PosSale> =>
  (await api.post<PosSale>("/vendor/me/pos/sales", payload)).data;

export const listSales = async (params?: Record<string, any>): Promise<PosSalesList> =>
  (await api.get<PosSalesList>("/vendor/me/pos/sales", { params })).data;

export const getSale = async (id: string): Promise<PosSale> =>
  (await api.get<PosSale>(`/vendor/me/pos/sales/${id}`)).data;

export const cancelSale = async (id: string): Promise<PosSale> =>
  (await api.post<PosSale>(`/vendor/me/pos/sales/${id}/cancel`)).data;

export const refundSale = async (id: string, reason?: string): Promise<PosSale> =>
  (await api.post<PosSale>(`/vendor/me/pos/sales/${id}/refund`, { reason })).data;

// ─── Dashboard / Cash / Statement / Analytics ───────────────────────
/**
 * Local (device / IST) calendar date as `YYYY-MM-DD`.
 *
 * Jun 2026 fix — `new Date().toISOString().slice(0,10)` returns the **UTC**
 * date, so between 00:00 and 05:30 IST it reported YESTERDAY and the cash
 * summary for "today" came back empty.
 */
export function localDateStr(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export const getDashboard = async (): Promise<PosDashboard> =>
  (await api.get<PosDashboard>("/vendor/me/pos/dashboard")).data;

export const getCashSummary = async (date?: string): Promise<PosCashSummary> =>
  (await api.get<PosCashSummary>("/vendor/me/pos/cash-summary", { params: date ? { date } : {} })).data;

export const getStatement = async (from?: string, to?: string) =>
  (await api.get("/vendor/me/pos/statement", { params: { from, to } })).data as {
    total: number; running_balance: number; items: PosStatementRow[];
  };

export const getAnalytics = async (days = 30): Promise<PosAnalytics> =>
  (await api.get<PosAnalytics>("/vendor/me/pos/analytics", { params: { days } })).data;

// ─── Customers ──────────────────────────────────────────────────────
export const listCustomers = async (q?: string, limit = 50) =>
  (await api.get("/vendor/me/pos/customers", { params: { q, limit } })).data as {
    items: PosCustomerRow[]; total: number;
  };

export const upsertCustomer = async (c: Partial<PosCustomerRow>): Promise<PosCustomerRow> =>
  (await api.post<PosCustomerRow>("/vendor/me/pos/customers", c)).data;

export const patchCustomer = async (id: string, c: Partial<PosCustomerRow>): Promise<PosCustomerRow> =>
  (await api.patch<PosCustomerRow>(`/vendor/me/pos/customers/${id}`, c)).data;

// ─── Discount helpers (mirror server-side parsing) ──────────────────
export const parseDiscount = (raw: string | null | undefined, base: number): number => {
  if (!raw) return 0;
  const s = String(raw).trim();
  const asNum = s.endsWith("%") ? (parseFloat(s.slice(0, -1)) * base) / 100 : parseFloat(s);
  return Number.isFinite(asNum) ? Math.round(asNum * 100) / 100 : 0;
};

export const computeLineTotals = (
  it: PosSaleItem,
  gstInclusive: boolean,
) => {
  const gross = it.qty * it.price;
  const disc = parseDiscount(it.discount ?? null, gross);
  const beforeGst = Math.max(0, gross - disc);
  const gstPct = it.gst_pct ?? 0;
  let taxable: number, tax: number, line: number;
  if (gstInclusive) {
    taxable = gstPct > 0 ? beforeGst / (1 + gstPct / 100) : beforeGst;
    tax = beforeGst - taxable;
    line = beforeGst;
  } else {
    taxable = beforeGst;
    tax = (taxable * gstPct) / 100;
    line = taxable + tax;
  }
  const r2 = (v: number) => Math.round(v * 100) / 100;
  return {
    discount_amount: r2(disc),
    taxable: r2(taxable),
    tax_amount: r2(tax),
    line_total: r2(line),
  };
};

export const computeBillTotals = (
  items: PosSaleItem[],
  opts: { gst_inclusive?: boolean; bill_discount?: string | null; round_off?: boolean } = {},
): PosSaleTotals => {
  let subtotal = 0, gst = 0, discTotal = 0;
  for (const it of items) {
    const t = computeLineTotals(it, !!opts.gst_inclusive);
    it.discount_amount = t.discount_amount;
    it.taxable = t.taxable;
    it.tax_amount = t.tax_amount;
    it.line_total = t.line_total;
    subtotal += t.taxable;
    gst += t.tax_amount;
    discTotal += t.discount_amount;
  }
  const billDisc = parseDiscount(opts.bill_discount ?? null, subtotal + gst);
  const preRound = Math.max(0, subtotal + gst - billDisc);
  const grand = opts.round_off !== false ? Math.round(preRound) : preRound;
  const r2 = (v: number) => Math.round(v * 100) / 100;
  return {
    subtotal: r2(subtotal),
    gst_total: r2(gst),
    discount_total: r2(discTotal),
    bill_discount: r2(billDisc),
    round_off: opts.round_off !== false ? r2(grand - preRound) : 0,
    grand_total: r2(grand),
    profit: 0,
  };
};
