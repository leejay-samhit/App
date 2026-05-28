// In-app receipt for a phone-reveal payment.
// Shown right after the customer pays + opens the dialer. Also reachable
// from "My phone reveals" history. Pure read-only view; mirrors what an
// e-invoice would carry (subtotal, GST, total, biller/customer details).
import { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Share,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { api, formatApiError } from "../../../src/api";
import { colors, radii, spacing, formatINR } from "../../../src/theme";

type Invoice = {
  id: string;
  invoice_no: string;
  user_name: string;
  user_email: string;
  provider_name: string;
  provider_phone: string;
  service_name?: string;
  service_category?: string;
  fee: number;
  gst_pct: number;
  gst_amount: number;
  total: number;
  biller_name?: string;
  biller_gst?: string;
  biller_address?: string;
  biller_city?: string;
  biller_state?: string;
  biller_pincode?: string;
  created_at: string;
};

export default function PhoneRevealInvoice() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [inv, setInv] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get<Invoice>(`/services/reveals/invoice/${id}`);
        setInv(data);
      } catch (e) {
        setError(formatApiError(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  const onShare = async () => {
    if (!inv) return;
    try {
      await Share.share({
        message:
          `Invoice ${inv.invoice_no}\n\n` +
          `${inv.biller_name || "NetworkPay"}\n\n` +
          `Service: Phone-reveal for ${inv.provider_name}\n` +
          `Fee: ${formatINR(inv.fee)}\n` +
          `GST (${inv.gst_pct}%): ${formatINR(inv.gst_amount)}\n` +
          `Total: ${formatINR(inv.total)}\n` +
          `Date: ${new Date(inv.created_at).toLocaleString()}`,
      });
    } catch {}
  };

  if (loading) {
    return <SafeAreaView style={s.safe}><View style={s.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }
  if (error || !inv) {
    return <SafeAreaView style={s.safe}><View style={s.center}><Text>{error || "Invoice not found"}</Text></View></SafeAreaView>;
  }

  const dt = new Date(inv.created_at);
  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} style={s.iconBtn}>
          <Feather name="arrow-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={s.headerTitle}>Tax Invoice</Text>
        <TouchableOpacity onPress={onShare} style={s.iconBtn}>
          <Feather name="share-2" size={20} color={colors.textMain} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}>
        <View style={s.card}>
          <Text style={s.bizName}>{inv.biller_name || "NetworkPay"}</Text>
          {inv.biller_address ? (
            <Text style={s.bizAddr}>
              {[inv.biller_address, inv.biller_city, inv.biller_state, inv.biller_pincode]
                .filter(Boolean).join(", ")}
            </Text>
          ) : null}
          {inv.biller_gst ? <Text style={s.bizGst}>GSTIN: {inv.biller_gst}</Text> : null}
        </View>

        <View style={[s.card, { flexDirection: "row", justifyContent: "space-between" }]}>
          <View>
            <Text style={s.metaLabel}>Invoice no.</Text>
            <Text style={s.metaValue}>{inv.invoice_no}</Text>
          </View>
          <View style={{ alignItems: "flex-end" }}>
            <Text style={s.metaLabel}>Date</Text>
            <Text style={s.metaValue}>{dt.toLocaleDateString()}</Text>
            <Text style={[s.metaLabel, { marginTop: 4 }]}>{dt.toLocaleTimeString()}</Text>
          </View>
        </View>

        <View style={s.card}>
          <Text style={s.sectionTitle}>BILLED TO</Text>
          <Text style={s.toName}>{inv.user_name}</Text>
          <Text style={s.toEmail}>{inv.user_email}</Text>
        </View>

        <View style={s.card}>
          <Text style={s.sectionTitle}>SERVICE</Text>
          <Text style={s.svcName}>Phone-reveal fee for service provider</Text>
          <Text style={s.svcMeta}>
            Provider: {inv.provider_name}
            {inv.service_name ? `  ·  ${inv.service_name}` : ""}
          </Text>
          {inv.service_category ? (
            <Text style={s.svcMeta}>Category: {inv.service_category}</Text>
          ) : null}
        </View>

        <View style={s.card}>
          <View style={s.row}>
            <Text style={s.rowLabel}>Subtotal</Text>
            <Text style={s.rowVal}>{formatINR(inv.fee)}</Text>
          </View>
          <View style={s.row}>
            <Text style={s.rowLabel}>GST @ {inv.gst_pct}%</Text>
            <Text style={s.rowVal}>{formatINR(inv.gst_amount)}</Text>
          </View>
          <View style={[s.row, s.totalRow]}>
            <Text style={s.totalLabel}>Total paid</Text>
            <Text style={s.totalVal}>{formatINR(inv.total)}</Text>
          </View>
          <View style={s.paidPill}>
            <Feather name="check" size={11} color="#fff" />
            <Text style={s.paidText}>{"  "}PAID FROM WALLET</Text>
          </View>
        </View>

        <Text style={s.footer}>
          This is a system-generated tax invoice. No signature required. {"\n"}
          For queries email support — keep this invoice for your records.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 8, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1, borderColor: colors.border,
  },
  bizName: { fontSize: 18, fontWeight: "900", color: colors.textMain },
  bizAddr: { fontSize: 11, color: colors.textMuted, marginTop: 4, lineHeight: 16 },
  bizGst: { fontSize: 11, color: colors.textMuted, marginTop: 4, fontWeight: "700" },
  metaLabel: { fontSize: 10, color: colors.textMuted, fontWeight: "800", letterSpacing: 1 },
  metaValue: { fontSize: 13, color: colors.textMain, fontWeight: "700", marginTop: 2 },
  sectionTitle: { fontSize: 10, color: colors.textMuted, fontWeight: "900", letterSpacing: 1, marginBottom: 8 },
  toName: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  toEmail: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  svcName: { fontSize: 14, color: colors.textMain, fontWeight: "700" },
  svcMeta: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6 },
  rowLabel: { fontSize: 13, color: colors.textMuted },
  rowVal: { fontSize: 13, color: colors.textMain, fontWeight: "700" },
  totalRow: {
    marginTop: 6, paddingTop: 10,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  totalLabel: { fontSize: 15, color: colors.textMain, fontWeight: "900" },
  totalVal: { fontSize: 18, color: colors.primary, fontWeight: "900" },
  paidPill: {
    alignSelf: "flex-start",
    flexDirection: "row", alignItems: "center",
    backgroundColor: "#16A34A",
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999, marginTop: 10,
  },
  paidText: { fontSize: 10, fontWeight: "900", color: "#fff", letterSpacing: 1 },
  footer: { fontSize: 10, color: colors.textMuted, textAlign: "center", marginTop: 14, lineHeight: 14 },
});
