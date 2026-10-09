/**
 * Recharge — Mobile & DTH TV.
 *
 * Oct-2026, built exactly to the owner's brief:
 *
 *   Step 1  LIST VIEW of two services: Mobile Recharge · DTH TV Recharge
 *   Step 2  ONE LINE, TWO BOXES: State  then  Network   (both admin-managed)
 *   Step 3  Enter mobile number / subscriber ID
 *   Step 4  Plans grouped by subcategory → Pay online via Razorpay
 *
 * The old screen dumped every product side-by-side with no service, state or
 * network separation, which is unusable once more than one operator exists.
 *
 * State and Network are DATA (/api/recharge/options) with add/delete in the
 * admin panel — new circles and operators never need a code change.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Modal, Pressable, RefreshControl, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { notify } from "../src/notify";
import { openRazorpayCheckout, type RazorpayResult } from "../src/razorpay";
import { colors, radii, spacing, formatINR } from "../src/theme";

type Option = { id: string; name: string; slug: string; kind: string; group: string };
type Service = { key: "mobile" | "dth"; label: string; icon: any; description: string };
type Plan = {
  id: string; name: string; price: number; subcategory?: string;
  description?: string; validity?: string; data?: string;
};
type PlanGroup = { name: string; products: Plan[] };

export default function RechargeScreen() {
  const router = useRouter();
  const { user } = useAuth();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [services, setServices] = useState<Service[]>([]);
  const [options, setOptions] = useState<any>(null);

  const [service, setService] = useState<"mobile" | "dth" | null>(null);
  const [state, setState] = useState<Option | null>(null);
  const [network, setNetwork] = useState<Option | null>(null);
  const [account, setAccount] = useState("");

  const [picker, setPicker] = useState<"state" | "network" | null>(null);
  const [groups, setGroups] = useState<PlanGroup[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [paying, setPaying] = useState<string | null>(null);

  const loadOptions = useCallback(async () => {
    try {
      const { data } = await api.get("/recharge/options");
      setOptions(data);
      setServices(data.types || []);
    } catch (e) {
      notify("Couldn't load recharge", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadOptions(); }, [loadOptions]);

  const states: Option[] = useMemo(
    () => (service && options ? options[service]?.states || [] : []), [service, options],
  );
  const networks: Option[] = useMemo(
    () => (service && options ? options[service]?.networks || [] : []), [service, options],
  );

  // Auto-pick when there is only one choice — making someone tap a dropdown
  // with a single entry is pure friction.
  useEffect(() => {
    if (states.length === 1 && !state) setState(states[0]);
  }, [states, state]);

  const loadPlans = useCallback(async () => {
    if (!service || !state || !network) { setGroups([]); return; }
    setPlansLoading(true);
    try {
      const { data } = await api.get("/recharge/products", {
        params: { kind: service, state: state.slug, network: network.slug },
      });
      setGroups(data.groups || []);
    } catch {
      setGroups([]);
    } finally {
      setPlansLoading(false);
    }
  }, [service, state, network]);

  useEffect(() => { loadPlans(); }, [loadPlans]);

  const accountValid = service === "mobile"
    ? /^[6-9]\d{9}$/.test(account.replace(/\D+/g, ""))
    : account.trim().length >= 6;

  const onPay = async (plan: Plan) => {
    if (!accountValid) {
      notify(
        service === "mobile" ? "Enter a mobile number" : "Enter a subscriber ID",
        service === "mobile"
          ? "We need the 10-digit number you want to recharge."
          : "We need the DTH subscriber / customer ID.",
      );
      return;
    }
    setPaying(plan.id);
    try {
      const { data: start } = await api.post<{
        payment_id: string; razorpay_order_id: string; amount_paise: number;
        key_id: string; is_mock: boolean; description?: string;
        prefill?: { name?: string; email?: string; contact?: string };
      }>("/recharge/payment/start", {
        kind: service,
        product_id: plan.id,
        account: account.replace(/\s+/g, ""),
        state: state?.slug,
        network: network?.slug,
      });

      let result: RazorpayResult;
      if (start.is_mock) {
        // Preview/sandbox — simulate the gateway so the whole flow still
        // runs end to end without live keys.
        await new Promise((r) => setTimeout(r, 1000));
        result = {
          ok: true,
          paymentId: `pay_MOCK_${Math.random().toString(36).slice(2, 14)}`,
          orderId: start.razorpay_order_id,
          signature: `sig_MOCK_${Math.random().toString(36).slice(2, 20)}`,
        };
      } else {
        result = await openRazorpayCheckout({
          orderId: start.razorpay_order_id,
          amountPaise: start.amount_paise,
          keyId: start.key_id,
          name: "Slangcart",
          description: start.description || plan.name,
          prefill: {
            name: start.prefill?.name || user?.name,
            email: start.prefill?.email || (user as any)?.email,
            contact: start.prefill?.contact || account,
          },
          themeColor: colors.primary,
        });
      }

      if (!result.ok) {
        notify("Payment cancelled", result.error || "You can try again any time.");
        return;
      }
      const { data: done } = await api.post("/recharge/payment/verify", {
        payment_id: start.payment_id,
        razorpay_order_id: result.orderId,
        razorpay_payment_id: result.paymentId,
        razorpay_signature: result.signature,
      });
      notify(
        "Recharge booked",
        `${formatINR(done.amount)} for ${done.account} — you'll get a confirmation shortly.`,
      );
      setAccount("");
    } catch (e) {
      notify("Recharge failed", formatApiError(e));
    } finally {
      setPaying(null);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  const currentService = services.find((s) => s.key === service);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => (service ? (setService(null), setGroups([]), setNetwork(null)) : router.back())}
          style={styles.backBtn}
          testID="recharge-back"
        >
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerTitle}>
            {currentService ? currentService.label : "Recharge"}
          </Text>
          {currentService ? (
            <Text style={styles.headerSub} numberOfLines={1}>{currentService.description}</Text>
          ) : null}
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 40 }}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadOptions(); }} tintColor={colors.primary} />
        }
      >
        {/* ─── STEP 1 — service LIST view ─── */}
        {!service ? (
          <>
            <Text style={styles.stepLabel}>CHOOSE A SERVICE</Text>
            {services.map((s) => (
              <TouchableOpacity
                key={s.key}
                onPress={() => { setService(s.key); setState(null); setNetwork(null); setGroups([]); }}
                style={styles.serviceRow}
                testID={`recharge-service-${s.key}`}
                activeOpacity={0.85}
              >
                <View style={styles.serviceIcon}>
                  <Feather name={s.icon} size={20} color={colors.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.serviceName}>{s.label}</Text>
                  <Text style={styles.serviceDesc} numberOfLines={2}>{s.description}</Text>
                </View>
                <Feather name="chevron-right" size={18} color={colors.textMuted} />
              </TouchableOpacity>
            ))}
          </>
        ) : (
          <>
            {/* ─── STEP 2 — ONE LINE, TWO BOXES: State then Network ─── */}
            <Text style={styles.stepLabel}>STATE &amp; NETWORK</Text>
            <View style={styles.selectRow}>
              <TouchableOpacity
                onPress={() => setPicker("state")}
                style={styles.selectBox}
                testID="recharge-pick-state"
                activeOpacity={0.85}
              >
                <Text style={styles.selectLabel}>STATE</Text>
                <View style={styles.selectValueRow}>
                  <Text style={[styles.selectValue, !state && styles.selectPlaceholder]} numberOfLines={1}>
                    {state?.name || "Select state"}
                  </Text>
                  <Feather name="chevron-down" size={15} color={colors.textMuted} />
                </View>
              </TouchableOpacity>

              <TouchableOpacity
                onPress={() => setPicker("network")}
                style={styles.selectBox}
                testID="recharge-pick-network"
                activeOpacity={0.85}
              >
                <Text style={styles.selectLabel}>NETWORK</Text>
                <View style={styles.selectValueRow}>
                  <Text style={[styles.selectValue, !network && styles.selectPlaceholder]} numberOfLines={1}>
                    {network?.name || "Select network"}
                  </Text>
                  <Feather name="chevron-down" size={15} color={colors.textMuted} />
                </View>
              </TouchableOpacity>
            </View>

            {/* ─── STEP 3 — the number to recharge ─── */}
            <Text style={styles.stepLabel}>
              {service === "mobile" ? "MOBILE NUMBER" : "SUBSCRIBER / CUSTOMER ID"}
            </Text>
            <View style={styles.accountRow}>
              {service === "mobile" ? (
                <View style={styles.cc}><Text style={styles.ccText}>+91</Text></View>
              ) : (
                <Feather name="tv" size={16} color={colors.textMuted} />
              )}
              <TextInput
                value={account}
                onChangeText={(v) => setAccount(
                  service === "mobile" ? v.replace(/\D+/g, "").slice(0, 10) : v.slice(0, 24),
                )}
                placeholder={service === "mobile" ? "9876543210" : "e.g. 3001234567"}
                placeholderTextColor={colors.textMuted}
                keyboardType={service === "mobile" ? "number-pad" : "default"}
                style={styles.accountInput}
                testID="recharge-account"
              />
              {accountValid ? (
                <Feather name="check-circle" size={17} color={colors.success} />
              ) : null}
            </View>

            {/* ─── STEP 4 — plans, grouped by subcategory ─── */}
            {!state || !network ? (
              <View style={styles.hint} testID="recharge-hint">
                <Feather name="arrow-up" size={14} color={colors.textMuted} />
                <Text style={styles.hintText}>
                  Pick your state and network above to see the available plans.
                </Text>
              </View>
            ) : plansLoading ? (
              <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
            ) : groups.length === 0 ? (
              <View style={styles.hint}>
                <Feather name="inbox" size={14} color={colors.textMuted} />
                <Text style={styles.hintText}>
                  No {network.name} plans for {state.name} yet. Pull down to refresh.
                </Text>
              </View>
            ) : (
              groups.map((g) => (
                <View key={g.name} style={{ marginTop: 18 }}>
                  <Text style={styles.groupTitle}>{g.name}</Text>
                  {g.products.map((p) => (
                    <View key={p.id} style={styles.planRow} testID={`recharge-plan-${p.id}`}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.planAmount}>{formatINR(p.price)}</Text>
                        <Text style={styles.planName} numberOfLines={2}>{p.name}</Text>
                      </View>
                      <TouchableOpacity
                        onPress={() => onPay(p)}
                        disabled={paying !== null || !accountValid}
                        style={[
                          styles.payBtn,
                          (paying !== null || !accountValid) && styles.payBtnOff,
                        ]}
                        testID={`recharge-pay-${p.id}`}
                      >
                        {paying === p.id ? (
                          <ActivityIndicator size="small" color={colors.primaryFg} />
                        ) : (
                          <Text style={[styles.payBtnText, !accountValid && { color: colors.textMuted }]}>
                            Pay online
                          </Text>
                        )}
                      </TouchableOpacity>
                    </View>
                  ))}
                </View>
              ))
            )}
          </>
        )}
      </ScrollView>

      {/* State / Network picker */}
      <Modal visible={picker !== null} transparent animationType="slide" onRequestClose={() => setPicker(null)}>
        <Pressable style={styles.backdrop} onPress={() => setPicker(null)} />
        <View style={styles.sheet} testID="recharge-picker-sheet">
          <View style={styles.grab} />
          <Text style={styles.sheetTitle}>
            {picker === "state" ? "Select state" : "Select network"}
          </Text>
          <ScrollView style={{ maxHeight: 360 }}>
            {(picker === "state" ? states : networks).map((o) => {
              const on = (picker === "state" ? state?.id : network?.id) === o.id;
              return (
                <TouchableOpacity
                  key={o.id}
                  onPress={() => {
                    if (picker === "state") setState(o); else setNetwork(o);
                    setPicker(null);
                  }}
                  style={[styles.optRow, on && styles.optRowOn]}
                  testID={`recharge-opt-${o.slug}`}
                >
                  <Text style={[styles.optText, on && { color: colors.primary, fontWeight: "900" }]}>
                    {o.name}
                  </Text>
                  {on ? <Feather name="check" size={16} color={colors.primary} /> : null}
                </TouchableOpacity>
              );
            })}
            {(picker === "state" ? states : networks).length === 0 ? (
              <Text style={styles.optEmpty}>
                Nothing added yet. An admin can add options from Admin → Recharge.
              </Text>
            ) : null}
          </ScrollView>
          <TouchableOpacity onPress={() => setPicker(null)} style={styles.sheetClose}>
            <Text style={styles.sheetCloseText}>Close</Text>
          </TouchableOpacity>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { paddingVertical: 36, alignItems: "center" },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 11,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  backBtn: { padding: 4 },
  headerTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  headerSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 1 },
  stepLabel: {
    fontSize: 10, fontWeight: "900", letterSpacing: 1.1,
    color: colors.textMuted, marginBottom: 9, marginTop: 14,
  },

  // Step 1 — list view
  serviceRow: {
    flexDirection: "row", alignItems: "center", gap: 13,
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border,
    padding: 14, marginBottom: 10,
  },
  serviceIcon: {
    width: 44, height: 44, borderRadius: 12,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  serviceName: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  serviceDesc: { fontSize: 11.5, lineHeight: 16, color: colors.textMuted, marginTop: 2 },

  // Step 2 — ONE LINE, TWO BOXES
  selectRow: { flexDirection: "row", gap: 10 },
  selectBox: {
    flex: 1, backgroundColor: colors.surface,
    borderRadius: radii.input, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 12, paddingVertical: 10, minHeight: 58,
    justifyContent: "center",
  },
  selectLabel: {
    fontSize: 8.5, fontWeight: "900", letterSpacing: 0.9,
    color: colors.textMuted, marginBottom: 4,
  },
  selectValueRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  selectValue: { flex: 1, fontSize: 13, fontWeight: "800", color: colors.textMain },
  selectPlaceholder: { color: colors.textMuted, fontWeight: "600" },

  // Step 3 — account
  accountRow: {
    flexDirection: "row", alignItems: "center", gap: 9,
    backgroundColor: colors.surface, borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 12, minHeight: 52,
  },
  cc: { paddingRight: 9, borderRightWidth: 1, borderRightColor: colors.border },
  ccText: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  accountInput: {
    flex: 1, fontSize: 16, fontWeight: "700", color: colors.textMain,
    paddingVertical: 13, letterSpacing: 1,
    ...Platform.select({ web: { outlineStyle: "none" } as any, default: {} }),
  },

  // Step 4 — plans
  hint: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceMuted, borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.border, borderStyle: "dashed",
    padding: 13, marginTop: 18,
  },
  hintText: { flex: 1, fontSize: 12, lineHeight: 17, color: colors.textMuted, fontWeight: "600" },
  groupTitle: {
    fontSize: 13.5, fontWeight: "900", color: colors.textMain,
    marginBottom: 9, letterSpacing: -0.2,
  },
  planRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surface, borderRadius: radii.input,
    borderWidth: 1, borderColor: colors.border,
    padding: 13, marginBottom: 8,
  },
  planAmount: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  planName: { fontSize: 11.5, lineHeight: 16, color: colors.textMuted, marginTop: 2, fontWeight: "600" },
  payBtn: {
    backgroundColor: colors.primary, paddingHorizontal: 16,
    minHeight: 40, minWidth: 96, borderRadius: 999,
    alignItems: "center", justifyContent: "center",
  },
  payBtnOff: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  payBtnText: { fontSize: 12.5, fontWeight: "900", color: colors.primaryFg },

  // Picker sheet
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: 18, paddingTop: 10, paddingBottom: 24,
  },
  grab: {
    alignSelf: "center", width: 44, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginBottom: 14,
  },
  sheetTitle: { fontSize: 16, fontWeight: "900", color: colors.textMain, marginBottom: 10 },
  optRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 14, paddingHorizontal: 12, borderRadius: 11,
    borderWidth: 1, borderColor: colors.border, marginBottom: 7,
    backgroundColor: colors.surface,
  },
  optRowOn: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  optText: { flex: 1, fontSize: 14, fontWeight: "700", color: colors.textMain },
  optEmpty: {
    fontSize: 12.5, lineHeight: 18, color: colors.textMuted,
    textAlign: "center", paddingVertical: 24,
  },
  sheetClose: { alignItems: "center", paddingVertical: 14, marginTop: 4 },
  sheetCloseText: { fontSize: 13, fontWeight: "800", color: colors.textMuted },
});
