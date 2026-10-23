// Recharge pay-online — one flow, used by the Recharge screen AND the
// product hero card (Jun 2026 owner report).
//
// Why this file exists: `openRazorpayCheckout()` only works on web; on a
// phone it throws "On native, use buildRazorpayHtml() in a WebView and handle
// onMessage events" — which is exactly the error the owner hit when paying
// for a plan. The gateway has to be hosted in a WebView on native, and that
// plumbing (resolver ref + message mapping) is identical everywhere, so it
// lives here instead of being copy-pasted into a third screen.
//
// A recharge is NOT a shop order: nothing ships, so there is no cart, no
// address and no delivery step — just account number → pay → booked.
import React, { useRef, useState } from "react";
import {
  View, Text, StyleSheet, Modal, TouchableOpacity, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { WebView } from "react-native-webview";
import { api, formatApiError } from "./api";
import { notify } from "./notify";
import { openRazorpayCheckout, buildRazorpayHtml, type RazorpayResult } from "./razorpay";
import { colors, spacing, formatINR } from "./theme";

export type RechargePayArgs = {
  kind: "mobile" | "dth";
  productId: string;
  planName: string;
  account: string;
  state?: string | null;
  network?: string | null;
  // Jun 2026 — how much of the plan the Slangcart wallet should cover.
  // 0 = pay the whole thing online; a partial amount splits wallet + UPI.
  walletAmount?: number;
  prefill?: { name?: string; email?: string; contact?: string };
};

export function accountIsValid(kind: "mobile" | "dth", account: string): boolean {
  return kind === "mobile"
    ? /^[6-9]\d{9}$/.test((account || "").replace(/\D+/g, ""))
    : (account || "").trim().length >= 6;
}

export function useRechargePay(onDone?: () => void) {
  const [paying, setPaying] = useState<string | null>(null);
  const [rzpHtml, setRzpHtml] = useState("");
  const resolver = useRef<((r: RazorpayResult) => void) | null>(null);

  const openNative = (html: string) =>
    new Promise<RazorpayResult>((resolve) => {
      resolver.current = resolve;
      setRzpHtml(html);
    });

  // buildRazorpayHtml posts {type:"success"|"cancel"|"failed"|"error"}.
  const handleMessage = (raw: string) => {
    let data: any = {};
    try { data = JSON.parse(raw); } catch { data = {}; }
    const resolve = resolver.current;
    resolver.current = null;
    setRzpHtml("");
    if (!resolve) return;
    if (data.type === "success") {
      resolve({ ok: true, paymentId: data.payment_id, orderId: data.order_id, signature: data.signature });
    } else if (data.type === "cancel") {
      resolve({ ok: false, cancelled: true });
    } else {
      resolve({ ok: false, error: data.error || "Payment failed", code: data.code });
    }
  };

  const cancel = () => handleMessage('{"type":"cancel"}');

  const pay = async (args: RechargePayArgs): Promise<boolean> => {
    if (!accountIsValid(args.kind, args.account)) {
      notify(
        args.kind === "mobile" ? "Enter a mobile number" : "Enter a subscriber ID",
        args.kind === "mobile"
          ? "We need the 10-digit number you want to recharge."
          : "We need the DTH subscriber / customer ID.",
      );
      return false;
    }
    setPaying(args.productId);
    try {
      const { data: start } = await api.post<{
        payment_id: string; razorpay_order_id: string; amount_paise: number;
        key_id: string; is_mock: boolean; description?: string;
        prefill?: { name?: string; email?: string; contact?: string };
      }>("/recharge/payment/start", {
        kind: args.kind,
        product_id: args.productId,
        account: args.account.replace(/\s+/g, ""),
        state: args.state || undefined,
        network: args.network || undefined,
        wallet_amount: Math.max(0, Number(args.walletAmount || 0)),
      });

      let result: RazorpayResult;
      if (start.is_mock) {
        // Preview / sandbox — simulate the gateway so the booking still runs
        // end to end without live keys.
        await new Promise((r) => setTimeout(r, 900));
        result = {
          ok: true,
          paymentId: `pay_MOCK_${Math.random().toString(36).slice(2, 14)}`,
          orderId: start.razorpay_order_id,
          signature: `sig_MOCK_${Math.random().toString(36).slice(2, 20)}`,
        };
      } else {
        const opts = {
          orderId: start.razorpay_order_id,
          amountPaise: start.amount_paise,
          keyId: start.key_id,
          name: "Slangcart",
          description: start.description || args.planName,
          prefill: {
            name: start.prefill?.name || args.prefill?.name,
            email: start.prefill?.email || args.prefill?.email,
            contact: start.prefill?.contact || args.account,
          },
          themeColor: colors.primary,
        };
        result = Platform.OS === "web"
          ? await openRazorpayCheckout(opts)
          : await openNative(buildRazorpayHtml(opts));
      }

      if (!result.ok) {
        notify(
          result.cancelled ? "Payment cancelled" : "Payment failed",
          result.error || "You can try again any time.",
        );
        return false;
      }
      const { data: done } = await api.post<{ amount: number; account: string }>(
        "/recharge/payment/verify",
        {
          payment_id: start.payment_id,
          razorpay_order_id: result.orderId,
          razorpay_payment_id: result.paymentId,
          razorpay_signature: result.signature,
        },
      );
      notify(
        "Recharge booked",
        `${formatINR(done.amount)} for ${done.account} — you'll get a confirmation shortly.`,
      );
      onDone?.();
      return true;
    } catch (e) {
      notify("Recharge failed", formatApiError(e));
      return false;
    } finally {
      setPaying(null);
    }
  };

  /** Pay the WHOLE plan from the Slangcart wallet — no gateway at all. */
  const payFromWallet = async (args: RechargePayArgs): Promise<boolean> => {
    if (!accountIsValid(args.kind, args.account)) {
      notify(
        args.kind === "mobile" ? "Enter a mobile number" : "Enter a subscriber ID",
        "We need the number you want to recharge.",
      );
      return false;
    }
    setPaying(args.productId);
    try {
      const { data } = await api.post<{ amount: number; account: string; order_number?: string }>(
        "/recharge/pay/wallet",
        {
          kind: args.kind,
          product_id: args.productId,
          account: args.account.replace(/\s+/g, ""),
          state: args.state || undefined,
          network: args.network || undefined,
        },
      );
      notify(
        "Recharge booked",
        `${formatINR(data.amount)} paid from your wallet for ${data.account}.`,
      );
      onDone?.();
      return true;
    } catch (e) {
      notify("Recharge failed", formatApiError(e));
      return false;
    } finally {
      setPaying(null);
    }
  };

  return { pay, payFromWallet, paying, rzpHtml, handleMessage, cancel };
}

/** The gateway itself on native. Renders nothing until `html` is set. */
export function RazorpayWebViewModal({
  html, onMessage, onCancel,
}: {
  html: string;
  onMessage: (raw: string) => void;
  onCancel: () => void;
}) {
  return (
    <Modal visible={!!html} animationType="slide" onRequestClose={onCancel}>
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }}>
        <View style={s.head}>
          <TouchableOpacity onPress={onCancel} style={s.headBtn} hitSlop={10} testID="rzp-close">
            <Feather name="x" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={s.headTitle}>Secure payment</Text>
          <View style={{ width: 40 }} />
        </View>
        {html ? (
          <WebView
            originWhitelist={["*"]}
            source={{ html }}
            onMessage={(e) => onMessage(e.nativeEvent.data)}
            javaScriptEnabled
            domStorageEnabled
          />
        ) : null}
      </SafeAreaView>
    </Modal>
  );
}

const s = StyleSheet.create({
  head: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.md, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  headBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  headTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
});
