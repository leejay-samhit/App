import { Platform, Alert } from "react-native";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import { api } from "./api";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;

/** Download/share PDF invoice for a transaction. */
export async function downloadInvoicePdf(txnId: string, invoiceNo?: string): Promise<void> {
  const filename = `${(invoiceNo || `invoice-${txnId.slice(0, 8)}`).replace(/[^a-zA-Z0-9._-]/g, "-")}.pdf`;
  try {
    const res = await api.get(`/transactions/${txnId}/invoice.pdf`, {
      responseType: "arraybuffer",
    });
    if (Platform.OS === "web") {
      // Browser download path
      const blob = new Blob([res.data], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      return;
    }
    // Native: write to cache & share
    const buffer = res.data as ArrayBuffer;
    const b64 = arrayBufferToBase64(buffer);
    const fileUri = `${FileSystem.cacheDirectory}${filename}`;
    await FileSystem.writeAsStringAsync(fileUri, b64, {
      encoding: FileSystem.EncodingType.Base64,
    });
    if (await Sharing.isAvailableAsync()) {
      await Sharing.shareAsync(fileUri, {
        mimeType: "application/pdf",
        dialogTitle: "Save invoice",
        UTI: "com.adobe.pdf",
      });
    } else {
      Alert.alert("Saved", `Invoice saved to ${fileUri}`);
    }
  } catch (e: any) {
    const detail = e?.response?.status === 400 ? "No invoice available for this transaction type."
      : e?.message || "Could not download invoice";
    Alert.alert("Invoice error", detail);
  }
}

/** Returns the URL for the HTML invoice with the user's auth token in the
 * Authorization header — caller should fetch the body with `api.get()` and
 * render in a WebView. (Direct browser URL won't carry the bearer token.) */
export async function fetchInvoiceHtml(txnId: string): Promise<string> {
  const res = await api.get(`/transactions/${txnId}/invoice`, {
    transformResponse: [(d) => d], // keep as raw HTML string
  });
  return res.data as string;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunk)) as any);
  }
  // btoa is available on web; on RN, Buffer or polyfill
  if (typeof btoa !== "undefined") return btoa(binary);
  // RN fallback — hermes has global.btoa, but if not, use Buffer:
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { Buffer } = require("buffer");
  return Buffer.from(binary, "binary").toString("base64");
}

export const INVOICE_BASE_URL = `${BASE}/api/transactions`;
