// Shared order progress tracker (Oct 2026).
//
// ONE tracker for the customer order card and the seller order card, so the
// two can never drift. Fixes the old alignment problems:
//   * connector lines are drawn BEHIND the dots at a fixed height, so the
//     row stays on one baseline whatever the label length
//   * "Cancelled" is no longer squeezed into the happy path — a cancelled
//     order renders its own single-chip state instead of 6 cramped circles
//   * every label gets the same width, centred under its dot
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors } from "./theme";

export const FLOW = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"] as const;
export const FLOW_LABEL: Record<string, string> = {
  placed: "Placed",
  confirmed: "Confirmed",
  shipped: "Shipped",
  out_for_delivery: "On the way",
  delivered: "Delivered",
};

export function OrderTimeline({
  status,
  testID,
}: {
  status: string;
  testID?: string;
}) {
  const cancelled = status === "cancelled";
  const returned = status === "returned" || status === "refunded";
  if (cancelled || returned) {
    return (
      <View
        style={[s.endState, cancelled ? s.endCancel : s.endReturn]}
        testID={testID}
      >
        <Feather
          name={cancelled ? "x-circle" : "corner-up-left"}
          size={14}
          color={cancelled ? colors.error : colors.warning}
        />
        <Text style={[s.endText, { color: cancelled ? colors.error : "#92400E" }]}>
          {cancelled ? "Order cancelled" : status === "refunded" ? "Returned · refunded" : "Returned"}
        </Text>
      </View>
    );
  }
  const activeIdx = Math.max(0, FLOW.indexOf(status as any));
  return (
    <View style={s.wrap} testID={testID}>
      {/* connector rail, drawn once behind the dots */}
      <View style={s.railTrack} />
      <View style={[s.railFill, { width: `${(activeIdx / (FLOW.length - 1)) * 100}%` }]} />
      <View style={s.row}>
        {FLOW.map((step, i) => {
          const done = i <= activeIdx;
          return (
            <View key={step} style={s.step}>
              <View style={[s.dot, done && s.dotOn]}>
                {done ? <Feather name="check" size={10} color={colors.primaryFg} /> : null}
              </View>
              <Text
                style={[s.label, done && s.labelOn]}
                numberOfLines={2}
              >
                {FLOW_LABEL[step]}
              </Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const DOT = 22;
const s = StyleSheet.create({
  wrap: { marginTop: 4, marginBottom: 2 },
  // The rail sits at the vertical centre of the dot row.
  railTrack: {
    position: "absolute", left: "10%", right: "10%", top: DOT / 2 - 1,
    height: 2, backgroundColor: colors.border, borderRadius: 1,
  },
  railFill: {
    position: "absolute", left: "10%", top: DOT / 2 - 1,
    height: 2, backgroundColor: colors.primary, borderRadius: 1,
    maxWidth: "80%",
  },
  row: { flexDirection: "row", alignItems: "flex-start" },
  step: { flex: 1, alignItems: "center", gap: 6 },
  dot: {
    width: DOT, height: DOT, borderRadius: DOT / 2,
    borderWidth: 2, borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
  },
  dotOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  label: {
    fontSize: 9.5, lineHeight: 12, textAlign: "center",
    fontWeight: "700", color: colors.textMuted,
  },
  labelOn: { color: colors.textMain, fontWeight: "800" },
  endState: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: 12, marginTop: 4,
  },
  endCancel: { backgroundColor: "#FEE2E2" },
  endReturn: { backgroundColor: "#FEF3C7" },
  endText: { fontSize: 12.5, fontWeight: "800" },
});
