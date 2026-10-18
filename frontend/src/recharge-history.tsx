// Recharge history rows + one-tap "Repeat" (Jun 2026 owner request).
//
// Shared by the Recharge screen (latest few) and /recharge-history (all of
// them) so the row, the money check and the repeat flow exist exactly once.
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, Image, ActivityIndicator, Alert } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii, formatINR } from "./theme";
import { useRechargePay, type RechargePayArgs } from "./recharge-pay";

export type RechargeRow = {
  id: string;
  kind: "mobile" | "dth" | string;
  product_id?: string;
  plan_name?: string;
  account: string;
  amount: number;
  status?: string;
  network?: string;
  network_name?: string;
  network_logo?: string | null;
  state?: string;
  created_at?: string;
  can_repeat?: boolean;
  current_price?: number | null;
  price_changed?: boolean;
  highlights?: { data?: string; validity?: string; calls?: string };
};

const STATUS_COLOR: Record<string, string> = {
  processing: "#B45309", success: "#15803D", completed: "#15803D", failed: "#B91C1C",
};

function when(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function RechargeHistoryRow({
  row, onRepeat, busy,
}: {
  row: RechargeRow;
  onRepeat: (row: RechargeRow) => void;
  busy: boolean;
}) {
  const tags = [row.highlights?.data, row.highlights?.validity, row.highlights?.calls]
    .filter(Boolean) as string[];
  return (
    <View style={s.row} testID={`recharge-history-${row.id}`}>
      <View style={s.logoWrap}>
        {row.network_logo ? (
          <Image source={{ uri: row.network_logo }} style={s.logo} resizeMode="cover" />
        ) : (
          <Feather name={row.kind === "dth" ? "tv" : "smartphone"} size={16} color={colors.primary} />
        )}
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <Text style={s.account} numberOfLines={1}>
          {row.account}
          {row.network_name ? <Text style={s.network}>{`  ·  ${row.network_name}`}</Text> : null}
        </Text>
        <Text style={s.plan} numberOfLines={1}>{row.plan_name || "Recharge"}</Text>
        {tags.length ? (
          <Text style={s.tags} numberOfLines={1}>{tags.join(" · ")}</Text>
        ) : null}
      </View>
      <View style={s.right}>
        <Text style={s.amount}>{formatINR(row.amount)}</Text>
        <Text style={[s.status, { color: STATUS_COLOR[row.status || ""] || colors.textMuted }]}>
          {(row.status || "").toUpperCase()}
          {row.created_at ? ` · ${when(row.created_at)}` : ""}
        </Text>
        {row.can_repeat ? (
          <TouchableOpacity
            onPress={() => onRepeat(row)}
            disabled={busy}
            style={[s.repeatBtn, busy && { opacity: 0.5 }]}
            testID={`recharge-repeat-${row.id}`}
          >
            {busy ? <ActivityIndicator size="small" color={colors.primaryFg} /> : (
              <>
                <Feather name="rotate-cw" size={12} color={colors.primaryFg} />
                <Text style={s.repeatText}>Repeat</Text>
              </>
            )}
          </TouchableOpacity>
        ) : (
          <Text style={s.gone}>Plan unavailable</Text>
        )}
      </View>
    </View>
  );
}

/** Repeat = pay the same plan for the same number again, after confirming a
 *  price change (the plan may have been re-priced since). */
export function useRepeatRecharge(onDone?: () => void) {
  const { pay, paying, rzpHtml, handleMessage, cancel } = useRechargePay(onDone);

  const repeat = (row: RechargeRow) => {
    const args: RechargePayArgs = {
      kind: (row.kind as any) || "mobile",
      productId: row.product_id || "",
      planName: row.plan_name || "Recharge",
      account: row.account,
      state: row.state,
      network: row.network,
    };
    if (!args.productId) return;
    const price = Number(row.current_price ?? row.amount);
    if (row.price_changed) {
      Alert.alert(
        "Price changed",
        `${row.plan_name} is now ${formatINR(price)} (you paid ${formatINR(row.amount)} last time). Continue?`,
        [
          { text: "Not now", style: "cancel" },
          { text: `Pay ${formatINR(price)}`, onPress: () => pay(args) },
        ],
      );
      return;
    }
    Alert.alert(
      "Repeat this recharge?",
      `${formatINR(price)} · ${row.plan_name} for ${row.account}`,
      [
        { text: "Cancel", style: "cancel" },
        { text: `Pay ${formatINR(price)}`, onPress: () => pay(args) },
      ],
    );
  };

  return { repeat, paying, rzpHtml, handleMessage, cancel };
}

const s = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 11,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, marginBottom: 8,
  },
  logoWrap: {
    width: 38, height: 38, borderRadius: 10, backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center", overflow: "hidden",
  },
  logo: { width: 38, height: 38 },
  account: { fontSize: 13.5, fontWeight: "900", color: colors.textMain },
  network: { fontSize: 11.5, fontWeight: "700", color: colors.textMuted },
  plan: { fontSize: 11.5, fontWeight: "600", color: colors.textMuted, marginTop: 2 },
  tags: { fontSize: 10.5, fontWeight: "800", color: colors.primary, marginTop: 3 },
  right: { width: 104, alignItems: "flex-end", gap: 4 },
  amount: { fontSize: 14, fontWeight: "900", color: colors.textMain, fontVariant: ["tabular-nums"] },
  status: { fontSize: 9, fontWeight: "900", letterSpacing: 0.3 },
  repeatBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5,
    minHeight: 32, paddingHorizontal: 10, borderRadius: 8, backgroundColor: colors.primary,
  },
  repeatText: { fontSize: 11.5, fontWeight: "900", color: colors.primaryFg },
  gone: { fontSize: 9.5, fontWeight: "700", color: colors.textMuted, textAlign: "right" },
});
