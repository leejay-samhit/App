import { useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { colors, radii, spacing } from "../../src/theme";

type Status = "done" | "partial" | "planned";

const STATUS_COLORS: Record<Status, string> = {
  done: colors.success,
  partial: colors.warning,
  planned: "#94A3B8",
};

const STATUS_LABELS: Record<Status, string> = {
  done: "DONE",
  partial: "PARTIAL",
  planned: "PLANNED",
};

type Item = { name: string; status: Status; note?: string };
type Section = { title: string; icon: string; subtitle?: string; items: Item[] };

const ROADMAP: Section[] = [
  {
    title: "User app — Authentication",
    icon: "lock",
    items: [
      { name: "Email + password login", status: "done" },
      { name: "Mobile OTP login", status: "planned", note: "Needs SMS gateway (Twilio)" },
      { name: "Social login (Google)", status: "planned" },
    ],
  },
  {
    title: "User app — Home & Browsing",
    icon: "home",
    items: [
      { name: "Banners & offers carousel", status: "planned" },
      { name: "Categories & subcategories", status: "planned" },
      { name: "Featured / trending products", status: "planned" },
      { name: "Filters (price, rating, brand)", status: "planned" },
      { name: "Search with suggestions", status: "planned" },
    ],
  },
  {
    title: "User app — Product details",
    icon: "package",
    items: [
      { name: "Image gallery", status: "partial", note: "Single hero image only" },
      { name: "Price + discount", status: "partial", note: "No discount engine yet" },
      { name: "Stock availability", status: "partial" },
      { name: "Description", status: "done" },
      { name: "Reviews & ratings", status: "planned" },
    ],
  },
  {
    title: "User app — Cart, Checkout & Payments",
    icon: "shopping-cart",
    items: [
      { name: "Add to cart", status: "done" },
      { name: "Wallet checkout", status: "done" },
      { name: "Apply coupon code", status: "planned" },
      { name: "Address selection", status: "planned" },
      { name: "UPI / Cards", status: "planned", note: "Needs Razorpay/Cashfree keys" },
      { name: "COD", status: "planned" },
    ],
  },
  {
    title: "User app — Orders",
    icon: "truck",
    items: [
      { name: "Order history", status: "done" },
      { name: "Order status tracking", status: "done" },
      { name: "Cancel / refund", status: "done" },
      { name: "Live delivery tracking", status: "planned" },
    ],
  },
  {
    title: "User app — Wallet & Referral",
    icon: "gift",
    items: [
      { name: "Wallet balance + txns", status: "done" },
      { name: "Use wallet for payments", status: "done" },
      { name: "Referral code + invite", status: "done" },
      { name: "Downline / network tree", status: "done" },
      { name: "Earnings tracking (multi-level)", status: "done" },
      { name: "Add money to wallet", status: "planned", note: "Needs payment gateway" },
      { name: "Cashback engine", status: "planned" },
    ],
  },
  {
    title: "User app — Recharge / Bills",
    icon: "phone",
    items: [
      { name: "Mobile / DTH recharge", status: "planned", note: "Needs Jolo / CyberPlat / Plan API" },
      { name: "Electricity / utility bills", status: "planned" },
    ],
  },
  {
    title: "Admin — Core",
    icon: "shield",
    items: [
      { name: "Dashboard with KPIs + charts", status: "done" },
      { name: "User management (CRUD, KYC, block, wallet)", status: "done" },
      { name: "Product management", status: "partial", note: "Add only; full CRUD pending" },
      { name: "Inventory control", status: "planned" },
      { name: "Order management with statuses", status: "done" },
      { name: "Wallet credit/debit/freeze", status: "done" },
      { name: "Transactions & manual refund", status: "done" },
      { name: "Audit log", status: "done" },
    ],
  },
  {
    title: "Admin — Referral / MLM",
    icon: "git-merge",
    items: [
      { name: "Commission structure setup", status: "done" },
      { name: "Level income settings", status: "done" },
      { name: "Bonus distribution", status: "done" },
      { name: "Manual bonus credit", status: "done", note: "via admin wallet adjust" },
    ],
  },
  {
    title: "Admin — Reports & Settings",
    icon: "bar-chart-2",
    items: [
      { name: "CSV exports (4 entities)", status: "done" },
      { name: "PDF / Excel reports", status: "planned" },
      { name: "Multi-admin RBAC", status: "done" },
      { name: "Payment gateway keys", status: "planned" },
      { name: "SMS / Email API config", status: "planned" },
      { name: "Maintenance mode", status: "planned" },
    ],
  },
  {
    title: "Vendor / Seller panel",
    icon: "briefcase",
    subtitle: "Future marketplace expansion (Amazon/Flipkart-style)",
    items: [
      { name: "Vendor registration", status: "planned" },
      { name: "Vendor product management", status: "planned" },
      { name: "Per-vendor order list", status: "planned" },
      { name: "Vendor earnings dashboard", status: "planned" },
      { name: "Vendor payout requests", status: "planned" },
    ],
  },
  {
    title: "Security & Notifications",
    icon: "alert-triangle",
    items: [
      { name: "JWT auth + bcrypt password hashing", status: "done" },
      { name: "Admin role permissions (RBAC)", status: "done" },
      { name: "In-app notifications", status: "done" },
      { name: "Push notifications", status: "planned", note: "Needs FCM + EAS dev build" },
      { name: "Bulk SMS / email", status: "planned" },
      { name: "Fraud detection (AI)", status: "planned" },
      { name: "OTP verification on payments", status: "planned" },
    ],
  },
];

export default function Roadmap() {
  const router = useRouter();
  const [filter, setFilter] = useState<Status | "all">("all");

  const total = ROADMAP.flatMap((s) => s.items);
  const counts = {
    done: total.filter((i) => i.status === "done").length,
    partial: total.filter((i) => i.status === "partial").length,
    planned: total.filter((i) => i.status === "planned").length,
  };
  const completion = Math.round((counts.done / total.length) * 100);

  const filtered = filter === "all" ? ROADMAP : ROADMAP.map((s) => ({
    ...s,
    items: s.items.filter((i) => i.status === filter),
  })).filter((s) => s.items.length > 0);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container} showsVerticalScrollIndicator={false}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="roadmap-back">
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={styles.title}>Product roadmap</Text>
          <View style={{ width: 40 }} />
        </View>

        <View style={styles.heroCard}>
          <Text style={styles.heroLabel}>OVERALL COMPLETION</Text>
          <Text style={styles.heroValue}>{completion}%</Text>
          <View style={styles.progressBar}>
            <View style={[styles.progressFill, { width: `${completion}%` }]} />
          </View>
          <View style={styles.heroRow}>
            <View style={styles.heroStat}>
              <View style={[styles.heroDot, { backgroundColor: colors.success }]} />
              <Text style={styles.heroStatLabel}>Done</Text>
              <Text style={styles.heroStatValue}>{counts.done}</Text>
            </View>
            <View style={styles.heroStat}>
              <View style={[styles.heroDot, { backgroundColor: colors.warning }]} />
              <Text style={styles.heroStatLabel}>Partial</Text>
              <Text style={styles.heroStatValue}>{counts.partial}</Text>
            </View>
            <View style={styles.heroStat}>
              <View style={[styles.heroDot, { backgroundColor: "rgba(255,255,255,0.5)" }]} />
              <Text style={styles.heroStatLabel}>Planned</Text>
              <Text style={styles.heroStatValue}>{counts.planned}</Text>
            </View>
          </View>
        </View>

        <View style={styles.tabs}>
          {(["all", "done", "partial", "planned"] as const).map((t) => (
            <TouchableOpacity key={t} onPress={() => setFilter(t)} style={[styles.tab, filter === t && styles.tabActive]} testID={`roadmap-filter-${t}`}>
              <Text style={[styles.tabText, filter === t && styles.tabTextActive]}>{t.toUpperCase()}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {filtered.map((s) => (
          <View key={s.title} style={styles.section}>
            <View style={styles.sectionHeader}>
              <View style={styles.sectionIcon}><Feather name={s.icon as any} size={16} color={colors.primary} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.sectionTitle}>{s.title}</Text>
                {s.subtitle ? <Text style={styles.sectionSubtitle}>{s.subtitle}</Text> : null}
              </View>
              <Text style={styles.sectionMeta}>{s.items.filter((i) => i.status === "done").length}/{s.items.length}</Text>
            </View>
            {s.items.map((it, idx) => (
              <View key={idx} style={styles.item} testID={`roadmap-item-${s.icon}-${idx}`}>
                <View style={[styles.itemDot, { backgroundColor: STATUS_COLORS[it.status] }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.itemName}>{it.name}</Text>
                  {it.note ? <Text style={styles.itemNote}>{it.note}</Text> : null}
                </View>
                <View style={[styles.itemPill, { backgroundColor: STATUS_COLORS[it.status] + "22", borderColor: STATUS_COLORS[it.status] }]}>
                  <Text style={[styles.itemPillText, { color: STATUS_COLORS[it.status] }]}>{STATUS_LABELS[it.status]}</Text>
                </View>
              </View>
            ))}
          </View>
        ))}

        <View style={styles.footer}>
          <Feather name="info" size={14} color={colors.textMuted} />
          <Text style={styles.footerText}>
            MVP first: User login · Product listing · Cart + checkout · Wallet · Referral. Then scale into recharge, vendor panel, and AI fraud detection.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  heroCard: { backgroundColor: colors.primary, borderRadius: radii.card, padding: 20, marginBottom: 16 },
  heroLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, letterSpacing: 2, fontWeight: "700" },
  heroValue: { color: colors.primaryFg, fontSize: 44, fontWeight: "800", letterSpacing: -1.5, marginTop: 4 },
  progressBar: { height: 6, backgroundColor: "rgba(255,255,255,0.15)", borderRadius: 99, overflow: "hidden", marginTop: 12 },
  progressFill: { height: "100%", backgroundColor: colors.accent, borderRadius: 99 },
  heroRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 18 },
  heroStat: { flexDirection: "row", alignItems: "center", gap: 6 },
  heroDot: { width: 8, height: 8, borderRadius: 4 },
  heroStatLabel: { color: "rgba(255,255,255,0.7)", fontSize: 11, fontWeight: "600" },
  heroStatValue: { color: colors.primaryFg, fontSize: 13, fontWeight: "800" },
  tabs: { flexDirection: "row", backgroundColor: colors.surfaceMuted, borderRadius: 99, padding: 4, gap: 4, marginBottom: 16 },
  tab: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: 99 },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.5 },
  tabTextActive: { color: colors.primaryFg },
  section: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 12 },
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: 12, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: colors.border, marginBottom: 8 },
  sectionIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  sectionTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  sectionSubtitle: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  sectionMeta: { fontSize: 12, fontWeight: "800", color: colors.primary, letterSpacing: 1 },
  item: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8 },
  itemDot: { width: 8, height: 8, borderRadius: 4 },
  itemName: { fontSize: 13, fontWeight: "600", color: colors.textMain },
  itemNote: { fontSize: 11, color: colors.textMuted, fontStyle: "italic", marginTop: 2 },
  itemPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, borderWidth: 1 },
  itemPillText: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  footer: { flexDirection: "row", alignItems: "flex-start", gap: 8, padding: 14, marginTop: 16, backgroundColor: colors.surfaceMuted, borderRadius: 14 },
  footerText: { fontSize: 11, color: colors.textMuted, flex: 1, lineHeight: 16 },
});
