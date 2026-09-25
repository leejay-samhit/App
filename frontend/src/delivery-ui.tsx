// Delivery Partner shared UI — one tab bar, one money card, one status pill.
// Kept in src/ (not app/) so it is a component, not a route.
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from "react-native";
import { Feather } from "@expo/vector-icons";
import { useRouter, usePathname } from "expo-router";
import { colors, radii, formatINR } from "./theme";

// Riders get FOUR destinations only — no Shop, no Services (owner's rule).
export const DP_TABS = [
  { key: "dashboard", label: "Dashboard", icon: "home", path: "/delivery/dashboard" },
  { key: "vendors", label: "My Shops", icon: "shopping-bag", path: "/delivery/vendors" },
  { key: "orders", label: "Orders", icon: "package", path: "/delivery/orders" },
  { key: "net-worth", label: "Money", icon: "trending-up", path: "/delivery/net-worth" },
] as const;

export function DPHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  const router = useRouter();
  return (
    <View style={s.header}>
      <View style={{ flex: 1 }}>
        <Text style={s.headerTitle}>{title}</Text>
        {subtitle ? <Text style={s.headerSub}>{subtitle}</Text> : null}
      </View>
      <TouchableOpacity
        onPress={() => router.push("/(tabs)/chat" as any)}
        style={s.iconBtn}
        testID="dp-chat"
      >
        <Feather name="message-circle" size={20} color={colors.textMain} />
      </TouchableOpacity>
      <TouchableOpacity
        onPress={() => router.push("/(tabs)/profile" as any)}
        style={s.iconBtn}
        testID="dp-profile"
      >
        <Feather name="user" size={20} color={colors.textMain} />
      </TouchableOpacity>
    </View>
  );
}

export function DPTabBar() {
  const router = useRouter();
  const path = usePathname() || "";
  return (
    <View style={s.tabBar}>
      {DP_TABS.map((t) => {
        const active = path.startsWith(t.path);
        return (
          <TouchableOpacity
            key={t.key}
            style={s.tab}
            onPress={() => router.replace(t.path as any)}
            testID={`dp-tab-${t.key}`}
          >
            <Feather
              name={t.icon as any}
              size={20}
              color={active ? colors.primary : colors.textMuted}
            />
            <Text style={[s.tabLabel, active && { color: colors.primary, fontWeight: "800" }]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

/** The rider's money card. Cash-in-hand is Slangcart's money he is holding —
 *  deliberately shown apart from his own wallet so the two never blur. */
export function DPMoneyCard({
  cashInHand, personalWallet, inSync, onPay,
}: {
  cashInHand: number; personalWallet: number; inSync: boolean; onPay?: () => void;
}) {
  return (
    <View style={s.money}>
      <Text style={s.moneyLabel}>CASH TO PAY SLANGCART</Text>
      <Text style={s.moneyValue} testID="dp-cash-in-hand">{formatINR(cashInHand)}</Text>
      <Text style={s.moneyHint}>
        {cashInHand > 0
          ? "Collected on COD deliveries · pay it in to clear your books"
          : "All clear — nothing pending"}
      </Text>
      <View style={s.moneyRow}>
        <View style={s.moneyChip}>
          <Text style={s.moneyChipLabel}>MY WALLET</Text>
          <Text style={s.moneyChipValue}>{formatINR(personalWallet)}</Text>
        </View>
        <View style={s.moneyChip}>
          <Text style={s.moneyChipLabel}>BOOKS</Text>
          <Text style={s.moneyChipValue}>{inSync ? "Balanced" : "Check"}</Text>
        </View>
      </View>
      {onPay && cashInHand > 0 ? (
        <TouchableOpacity style={s.payBtn} onPress={onPay} testID="dp-pay-admin">
          <Feather name="arrow-up-right" size={15} color={colors.primary} />
          <Text style={s.payBtnText}>Pay to Slangcart</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

export function DPStatusFilter({
  value, counts, onChange,
}: {
  value: string;
  counts: Record<string, number>;
  onChange: (v: string) => void;
}) {
  const OPTS = [
    { k: "all", label: "All" },
    { k: "placed", label: "New" },
    { k: "confirmed", label: "Confirmed" },
    { k: "shipped", label: "Shipped" },
    { k: "out_for_delivery", label: "On the way" },
    { k: "delivered", label: "Delivered" },
  ];
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.filterRow}>
      {OPTS.map((o) => {
        const on = value === o.k;
        const n = o.k === "all" ? 0 : counts[o.k] || 0;
        return (
          <TouchableOpacity
            key={o.k}
            onPress={() => onChange(o.k)}
            style={[s.filterChip, on && s.filterChipOn]}
            testID={`dp-filter-${o.k}`}
          >
            <Text style={[s.filterText, on && s.filterTextOn]}>
              {o.label}{n > 0 ? ` ${n}` : ""}
            </Text>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

export function DPEmpty({ icon, title, body }: { icon: string; title: string; body: string }) {
  return (
    <View style={s.empty}>
      <Feather name={icon as any} size={30} color={colors.textMuted} />
      <Text style={s.emptyTitle}>{title}</Text>
      <Text style={s.emptyBody}>{body}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 16, paddingTop: 6, paddingBottom: 10,
  },
  headerTitle: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  headerSub: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 2 },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  tabBar: {
    flexDirection: "row", borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: colors.surface, paddingTop: 8,
  },
  tab: { flex: 1, alignItems: "center", justifyContent: "center", gap: 3, minHeight: 48 },
  tabLabel: { fontSize: 11, fontWeight: "600", color: colors.textMuted },
  money: {
    backgroundColor: colors.primary, borderRadius: radii.card,
    padding: 16, marginHorizontal: 16, marginBottom: 16,
  },
  moneyLabel: { color: "rgba(255,255,255,0.9)", fontSize: 10, letterSpacing: 1.4, fontWeight: "900" },
  moneyValue: { color: "#fff", fontSize: 30, fontWeight: "900", marginTop: 4, letterSpacing: -1 },
  moneyHint: { color: "rgba(255,255,255,0.9)", fontSize: 11, fontWeight: "600", marginTop: 3 },
  moneyRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  moneyChip: {
    flex: 1, backgroundColor: "rgba(255,255,255,0.22)", borderRadius: 10,
    paddingVertical: 7, paddingHorizontal: 10,
  },
  moneyChipLabel: { color: "#fff", fontSize: 9, letterSpacing: 1, fontWeight: "900" },
  moneyChipValue: { color: "#fff", fontSize: 14, fontWeight: "800", marginTop: 1 },
  payBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#fff", borderRadius: 999, paddingVertical: 11, marginTop: 12, minHeight: 44,
  },
  payBtnText: { color: colors.primary, fontSize: 14, fontWeight: "800" },
  filterRow: { paddingHorizontal: 16, marginBottom: 12, flexGrow: 0 },
  filterChip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, marginRight: 8,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    minHeight: 36, justifyContent: "center",
  },
  filterChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  filterText: { fontSize: 12.5, fontWeight: "700", color: colors.textMain },
  filterTextOn: { color: colors.primaryFg },
  empty: { alignItems: "center", paddingVertical: 50, paddingHorizontal: 30, gap: 8 },
  emptyTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginTop: 6 },
  emptyBody: { fontSize: 13, color: colors.textMuted, fontWeight: "600", textAlign: "center", lineHeight: 19 },
});
