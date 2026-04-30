// Razorpay Checkout launcher — works on Expo Web (native `Razorpay` JS) and falls back
// to a WebView-hosted HTML page on native (iOS / Android via react-native-webview).
//
// Usage:
//   import { openRazorpayCheckout } from "../src/razorpay";
//   const r = await openRazorpayCheckout({ orderId, amountPaise, keyId, name, desc, prefill, theme });
//   if (r.ok) { /* call /api/payment/verify with r.paymentId + r.signature */ }
//
// NOTE: signature is only returned for orders created via /orders endpoint; Razorpay returns
// `razorpay_signature` in the handler when the payment is linked to an order_id.

import { Platform } from "react-native";

export type RazorpayResult =
  | { ok: true; paymentId: string; orderId: string; signature: string }
  | { ok: false; cancelled?: boolean; error?: string; code?: string };

export type RazorpayOpts = {
  orderId: string;
  amountPaise: number;
  keyId: string;
  name: string;
  description: string;
  prefill?: { name?: string; email?: string; contact?: string };
  themeColor?: string;
};

const CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

// -------------- WEB implementation --------------
function ensureCheckoutScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof document === "undefined") return reject(new Error("No document"));
    if ((window as any).Razorpay) return resolve();
    const existing = document.querySelector(`script[src="${CHECKOUT_SRC}"]`) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Failed to load Razorpay script")));
      return;
    }
    const script = document.createElement("script");
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay script"));
    document.head.appendChild(script);
  });
}

async function openWeb(opts: RazorpayOpts): Promise<RazorpayResult> {
  await ensureCheckoutScript();
  return new Promise<RazorpayResult>((resolve) => {
    const rzp = new (window as any).Razorpay({
      key: opts.keyId,
      amount: opts.amountPaise,
      currency: "INR",
      name: opts.name,
      description: opts.description,
      order_id: opts.orderId,
      prefill: opts.prefill || {},
      theme: { color: opts.themeColor || "#0b5fff" },
      modal: {
        ondismiss: () => resolve({ ok: false, cancelled: true }),
      },
      handler: (resp: any) => {
        resolve({
          ok: true,
          paymentId: resp.razorpay_payment_id,
          orderId: resp.razorpay_order_id,
          signature: resp.razorpay_signature,
        });
      },
    });
    rzp.on("payment.failed", (resp: any) => {
      resolve({
        ok: false,
        error: resp?.error?.description || "Payment failed",
        code: resp?.error?.code,
      });
    });
    rzp.open();
  });
}

// -------------- NATIVE implementation --------------
// Returns the HTML string to be rendered inside a WebView. Caller listens to onMessage.
export function buildRazorpayHtml(opts: RazorpayOpts): string {
  const safe = (s: string) => (s || "").replace(/"/g, '\\"');
  const prefill = opts.prefill || {};
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1" />
<title>Payment</title>
<style>
  html,body{margin:0;padding:0;background:#f5f7fb;height:100%;display:flex;align-items:center;justify-content:center;font-family:-apple-system,BlinkMacSystemFont,Roboto,"Helvetica Neue",sans-serif;color:#333}
  .card{text-align:center;padding:24px}
  .spinner{width:32px;height:32px;border-radius:50%;border:3px solid #e5e7eb;border-top-color:#0b5fff;animation:spin 1s linear infinite;margin:0 auto 12px}
  @keyframes spin{to{transform:rotate(360deg)}}
  button{background:#0b5fff;color:#fff;border:0;padding:12px 20px;border-radius:8px;font-size:15px;font-weight:700;margin-top:12px}
</style>
<script src="${CHECKOUT_SRC}"></script>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <div>Opening Razorpay Checkout…</div>
    <button id="retry" style="display:none" onclick="openRZP()">Retry</button>
  </div>
<script>
  function post(obj){ try{ window.ReactNativeWebView.postMessage(JSON.stringify(obj)); }catch(e){} }
  var options = {
    key: "${safe(opts.keyId)}",
    amount: ${opts.amountPaise},
    currency: "INR",
    name: "${safe(opts.name)}",
    description: "${safe(opts.description)}",
    order_id: "${safe(opts.orderId)}",
    prefill: {
      name: "${safe(prefill.name || "")}",
      email: "${safe(prefill.email || "")}",
      contact: "${safe(prefill.contact || "")}"
    },
    theme: { color: "${safe(opts.themeColor || "#0b5fff")}" },
    modal: { ondismiss: function(){ post({type:"cancel"}); } },
    handler: function(r){
      post({type:"success", payment_id:r.razorpay_payment_id, order_id:r.razorpay_order_id, signature:r.razorpay_signature});
    }
  };
  function openRZP(){
    try {
      var rzp = new Razorpay(options);
      rzp.on('payment.failed', function(resp){
        post({type:"failed", error: (resp && resp.error && resp.error.description) || "Payment failed", code: (resp && resp.error && resp.error.code) || null});
      });
      rzp.open();
    } catch(e){ post({type:"error", error: String(e && e.message || e)}); document.getElementById('retry').style.display='inline-block'; }
  }
  window.addEventListener('load', function(){ setTimeout(openRZP, 250); });
</script>
</body>
</html>`;
}

// Web entry point. Native must render a WebView + call buildRazorpayHtml separately.
export async function openRazorpayCheckout(opts: RazorpayOpts): Promise<RazorpayResult> {
  if (Platform.OS === "web") return openWeb(opts);
  // Native callers should use <WebView source={{ html: buildRazorpayHtml(opts) }} onMessage={...} />
  throw new Error("On native, use buildRazorpayHtml() in a WebView and handle onMessage events.");
}
