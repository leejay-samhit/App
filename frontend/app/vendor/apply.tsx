import { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator, Alert, KeyboardAvoidingView, Platform, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";
import { TermsAcceptancePanel } from "../../src/TermsAcceptancePanel";
import { LocationPicker, LocationValue, EMPTY_LOCATION } from "../../src/LocationPicker";
import {
  fetchOnboardingTerms, buildAcceptedTerms,
  VENDOR_TERMS_FALLBACK, OnboardingTermsBlock,
} from "../../src/onboardingTerms";

type VendorStatus = {
  is_vendor: boolean;
  vendor_status: "none" | "pending" | "approved" | "rejected" | "suspended";
  shop_name?: string | null;
  application?: any;
};

export default function VendorApplyScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [info, setInfo] = useState<VendorStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [shopName, setShopName] = useState("");
  const [gst, setGst] = useState("");
  const [pan, setPan] = useState("");
  const [bankName, setBankName] = useState("");
  const [bankAccount, setBankAccount] = useState("");
  const [bankIfsc, setBankIfsc] = useState("");
  const [description, setDescription] = useState("");
  // Sept 2026 — Shop location for geospatial marketplace filter.  GPS +
  // reverse-geocode auto-fills pincode/state/district/city.  Delivery
  // radius picker is rendered inside the LocationPicker's extraSlot.
  const [shopLocation, setShopLocation] = useState<LocationValue>(EMPTY_LOCATION);
  const [deliveryRadiusKm, setDeliveryRadiusKm] = useState<number | "pincode">(5);
  const [deliveryAvailable, setDeliveryAvailable] = useState<boolean>(true);
  // Sept 2026 — T&C gate (mirror of web /become-vendor). First-time apply
  // MUST accept the Vendor Declaration & GST Compliance Agreement; the
  // block is admin-editable from web (/api/admin/settings.onboarding_terms.vendor)
  // and silently falls back to the baked-in v1.0.0 defaults.
  const [termsBlock, setTermsBlock] = useState<OnboardingTermsBlock>(VENDOR_TERMS_FALLBACK);
  const [acceptedTerms, setAcceptedTerms] = useState<boolean>(false);
  const [termsError, setTermsError] = useState<string | null>(null);

  // Fetch the CMS override once on mount so any admin edit on web reflects
  // in the mobile client immediately at next apply.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const t = await fetchOnboardingTerms();
        if (!cancelled) setTermsBlock(t.vendor);
      } catch { /* silent — fallback already in state */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<VendorStatus>("/vendor/me/status");
      setInfo(data);
      // Nov 2026 — Approved vendors STAY on this screen so they can see
      // their current profile and hit "Request Edit".  Previous version
      // auto-redirected them to /vendor/dashboard which hid the whole
      // approval-gated edit flow the user relies on to update delivery
      // radius or extra pincodes.
    } catch (e) { Alert.alert("Error", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onSubmit = async () => {
    if (shopName.trim().length < 3) { Alert.alert("Shop name is too short"); return; }
    // T&C gate — mirror of the web `canSubmit` check (first-time apply only).
    if (!acceptedTerms) {
      setTermsError("Please read and accept the Vendor T&C above to continue.");
      Alert.alert("Terms not accepted", "Scroll to the bottom of the Vendor Declaration and tick 'I Agree' before applying.");
      return;
    }
    setTermsError(null);
    setSubmitting(true);
    try {
      await api.post("/vendor/apply", {
        shop_name: shopName.trim(), gst_number: gst.trim(), pan_number: pan.trim(),
        bank_name: bankName.trim(), bank_account: bankAccount.trim(), bank_ifsc: bankIfsc.trim(),
        description: description.trim(),
        // Sept 2026 — Shop location + geospatial delivery config. The
        // production backend consumes these to (a) build a 2dsphere
        // index on `vendors.location`, (b) filter shop listings to only
        // those within `delivery_radius_km` of the customer, (c) block
        // orders at checkout when the customer address is outside the
        // radius.  Coords are null if the vendor skipped GPS capture.
        location: (shopLocation.latitude !== null && shopLocation.longitude !== null)
          ? { type: "Point", coordinates: [shopLocation.longitude, shopLocation.latitude] }
          : null,
        pincode: shopLocation.pincode || null,
        state: shopLocation.state || null,
        district: shopLocation.district || null,
        city: shopLocation.city || null,
        store_address: shopLocation.address || null,
        delivery_radius_km: deliveryRadiusKm === "pincode" ? null : deliveryRadiusKm,
        delivery_radius_mode: deliveryRadiusKm === "pincode" ? "pincode" : "radius",
        delivery_available: deliveryAvailable,
        // Audit-log block — backend is expected to persist this alongside
        // the application row so we can prove consent if a vendor disputes.
        accepted_terms: buildAcceptedTerms(termsBlock),
      });
      Alert.alert("Application submitted", "We'll notify you once an admin reviews it.");
      await load();
    } catch (e) { Alert.alert("Couldn't apply", formatApiError(e)); }
    finally { setSubmitting(false); }
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View></SafeAreaView>;
  }

  const status = info?.vendor_status || "none";
  const showForm = status === "none" || status === "rejected";
  const showPending = status === "pending";
  const showSuspended = status === "suspended";
  const lastApp = info?.application;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="vapply-back"><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
          <Text style={styles.title}>Become a Vendor</Text>
          <View style={{ width: 40 }} />
        </View>
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} keyboardShouldPersistTaps="handled" refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>
          {showPending && lastApp && (
            <View style={[styles.statusCard, { backgroundColor: "#FFF4E5" }]}>
              <MaterialCommunityIcons name="clock-outline" size={28} color="#7A4A0E" />
              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text style={[styles.statusTitle, { color: "#7A4A0E" }]}>Application under review</Text>
                <Text style={styles.statusBody}>Submitted on {new Date(lastApp.created_at).toLocaleDateString()} for shop “{lastApp.shop_name}”. We'll notify you once approved.</Text>
              </View>
            </View>
          )}
          {showSuspended && (
            <View style={[styles.statusCard, { backgroundColor: "#FCE9E5" }]}>
              <Feather name="alert-triangle" size={28} color="#B3261E" />
              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text style={[styles.statusTitle, { color: "#B3261E" }]}>Vendor account suspended</Text>
                <Text style={styles.statusBody}>Please contact support to resolve this.</Text>
              </View>
            </View>
          )}
          {status === "rejected" && lastApp && (
            <View style={[styles.statusCard, { backgroundColor: "#FCE9E5" }]}>
              <Feather name="x-circle" size={28} color="#B3261E" />
              <View style={{ flex: 1, marginLeft: 12 }}>
                <Text style={[styles.statusTitle, { color: "#B3261E" }]}>Previous application rejected</Text>
                <Text style={styles.statusBody}>{lastApp.rejection_reason || "Please update your details and re-submit."}</Text>
              </View>
            </View>
          )}

          {/* Nov 2026 — Approved vendors see a read-only profile summary
              and a "Request Edit" CTA that routes to the approval-gated
              edit form.  Direct editing is disabled per policy. */}
          {status === "approved" && info ? (
            <>
              <View style={[styles.statusCard, { backgroundColor: "#E7F6EC" }]}>
                <Feather name="check-circle" size={28} color="#0F7A3C" />
                <View style={{ flex: 1, marginLeft: 12 }}>
                  <Text style={[styles.statusTitle, { color: "#0F7A3C" }]}>You&apos;re an approved vendor</Text>
                  <Text style={styles.statusBody}>
                    Profile fields are locked to protect trust.  Tap &ldquo;Request Edit&rdquo; to submit changes for admin approval.
                  </Text>
                </View>
              </View>
              <Text style={styles.section}>CURRENT PROFILE</Text>
              {[
                ["Shop name", info.shop_name || info.application?.shop_name],
                ["Pincode", info.pincode || info.application?.pincode],
                ["City", info.city || info.application?.city],
                ["State", info.state || info.application?.state],
                ["Delivery radius", (info.delivery_radius_km ?? info.application?.delivery_radius_km) != null ? `${info.delivery_radius_km ?? info.application?.delivery_radius_km} km` : (info.delivery_radius_mode || info.application?.delivery_radius_mode) === "pincode" ? "Entire pincode" : "—"],
                ["Store address", info.store_address || info.application?.store_address],
                ["GST", info.gst_number || info.application?.gst_number],
                ["Bank", info.bank_name || info.application?.bank_name],
                ["Account", info.bank_account || info.application?.bank_account],
                ["IFSC", info.bank_ifsc || info.application?.bank_ifsc],
              ].map(([label, val]) => (
                <View key={String(label)} style={styles.roCell}>
                  <Text style={styles.roLabel}>{label}</Text>
                  <Text style={styles.roValue}>{val ? String(val) : "—"}</Text>
                </View>
              ))}
              <TouchableOpacity
                onPress={() => router.push("/vendor/request-edit" as any)}
                style={[styles.primaryBtn, { marginTop: 20 }]}
                testID="vapply-request-edit"
              >
                <Feather name="edit-3" size={16} color={colors.primaryFg} />
                <Text style={styles.primaryBtnText}>  Request an edit</Text>
              </TouchableOpacity>
              <Text style={styles.note}>Every change is reviewed by admin — expect 1&ndash;2 business days.</Text>
            </>
          ) : null}

          {showForm && (
            <>
              <View style={[styles.statusCard, { backgroundColor: "#E6F1FB" }]}>
                <Feather name="shopping-bag" size={28} color="#1F5E9E" />
                <View style={{ flex: 1, marginLeft: 12 }}>
                  <Text style={[styles.statusTitle, { color: "#1F5E9E" }]}>Sell on our platform</Text>
                  <Text style={styles.statusBody}>List your products, manage orders, earn 70% commission per sale.</Text>
                </View>
              </View>

              <Text style={styles.section}>SHOP DETAILS</Text>
              <Text style={styles.label}>Shop name *</Text>
              <TextInput style={styles.input} value={shopName} onChangeText={setShopName} placeholder="e.g. Anika's Boutique" placeholderTextColor={colors.textMuted} testID="vapply-shop" />
              <Text style={styles.label}>Description (optional)</Text>
              <TextInput style={[styles.input, styles.area]} value={description} onChangeText={setDescription} placeholder="What do you sell? Specialities, regions covered, etc." placeholderTextColor={colors.textMuted} multiline textAlignVertical="top" testID="vapply-desc" />

              <Text style={styles.section}>BUSINESS DOCUMENTS</Text>
              <Text style={styles.label}>GST number (optional)</Text>
              <TextInput style={styles.input} value={gst} onChangeText={setGst} placeholder="22AAAAA0000A1Z5" placeholderTextColor={colors.textMuted} autoCapitalize="characters" testID="vapply-gst" />
              <Text style={styles.label}>PAN number (optional)</Text>
              <TextInput style={styles.input} value={pan} onChangeText={setPan} placeholder="ABCDE1234F" placeholderTextColor={colors.textMuted} autoCapitalize="characters" testID="vapply-pan" />

              <Text style={styles.section}>PAYOUT BANK ACCOUNT</Text>
              <Text style={styles.label}>Bank name (optional)</Text>
              <TextInput style={styles.input} value={bankName} onChangeText={setBankName} placeholder="HDFC Bank" placeholderTextColor={colors.textMuted} testID="vapply-bank" />
              <Text style={styles.label}>Account number (optional)</Text>
              <TextInput style={styles.input} value={bankAccount} onChangeText={setBankAccount} placeholder="XXXX-XXXX-1234" placeholderTextColor={colors.textMuted} keyboardType="number-pad" testID="vapply-acct" />
              <Text style={styles.label}>IFSC code (optional)</Text>
              <TextInput style={styles.input} value={bankIfsc} onChangeText={setBankIfsc} placeholder="HDFC0001234" placeholderTextColor={colors.textMuted} autoCapitalize="characters" testID="vapply-ifsc" />

              {/* Sept 2026 — Shop location + delivery-radius picker. */}
              <LocationPicker
                value={shopLocation}
                onChange={setShopLocation}
                title="Shop location"
                hint="Tap 'Use current' to capture GPS + auto-fill pincode/state/district. Editable if auto-detect misses."
                extraSlot={
                  <View style={{ gap: 8 }}>
                    <Text style={styles.label}>Delivery radius *</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                      {([2, 5, 10, 20, 50, "pincode"] as const).map((r) => {
                        const active = deliveryRadiusKm === r;
                        const label = r === "pincode" ? "Entire pincode" : `${r} km`;
                        return (
                          <TouchableOpacity
                            key={String(r)}
                            onPress={() => setDeliveryRadiusKm(r)}
                            style={[styles.radiusChip, active && styles.radiusChipActive]}
                            testID={`vapply-radius-${r}`}
                          >
                            <Text style={[styles.radiusChipText, active && styles.radiusChipTextActive]}>{label}</Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>

                    <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                      {[true, false].map((v) => (
                        <TouchableOpacity
                          key={String(v)}
                          onPress={() => setDeliveryAvailable(v)}
                          style={[styles.radiusChip, deliveryAvailable === v && styles.radiusChipActive, { flex: 1 }]}
                          testID={`vapply-delivery-${v}`}
                        >
                          <Feather name={v ? "truck" : "x-circle"} size={12} color={deliveryAvailable === v ? colors.primaryFg : colors.textMain} />
                          <Text style={[styles.radiusChipText, deliveryAvailable === v && styles.radiusChipTextActive, { marginLeft: 4 }]}>
                            {v ? "Delivery available" : "Pickup only"}
                          </Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                  </View>
                }
              />

              {/* Sept 2026 — T&C acceptance gate. Mirrors /become-vendor
                  on web: user must scroll to bottom + tick "I Agree" to
                  enable the submit button. */}
              <TermsAcceptancePanel
                block={termsBlock}
                accepted={acceptedTerms}
                onChange={(v) => { setAcceptedTerms(v); if (v) setTermsError(null); }}
                errorHint={termsError}
              />

              <TouchableOpacity
                onPress={onSubmit}
                disabled={submitting || !acceptedTerms}
                style={[styles.primaryBtn, (submitting || !acceptedTerms) && { opacity: 0.55 }]}
                testID="vapply-submit"
              >
                {submitting ? <ActivityIndicator color={colors.primaryFg} /> : <><Feather name="send" size={16} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Submit application</Text></>}
              </TouchableOpacity>
              {!acceptedTerms ? (
                <Text style={[styles.note, { color: "#B3261E", fontWeight: "700" }]}>
                  Accept the Vendor T&amp;C above to enable the Apply button.
                </Text>
              ) : null}
              <Text style={styles.note}>You can sell after admin approval. Bank details can be updated later from settings.</Text>
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  statusCard: { flexDirection: "row", alignItems: "center", borderRadius: radii.card, padding: 16, marginBottom: 20 },
  statusTitle: { fontSize: 15, fontWeight: "800" },
  statusBody: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  section: { fontSize: 11, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 16, marginBottom: 8 },
  label: { fontSize: 12, color: colors.textMuted, marginTop: 12, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 14, color: colors.textMain },
  area: { minHeight: 90, paddingTop: 14 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 15, marginTop: 24 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  note: { fontSize: 11, color: colors.textMuted, textAlign: "center", marginTop: 12 },
  radiusChip: { flexDirection: "row", alignItems: "center", justifyContent: "center", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  radiusChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  radiusChipText: { fontSize: 11, fontWeight: "700", color: colors.textMain, letterSpacing: 0.2 },
  radiusChipTextActive: { color: colors.primaryFg },
  // Nov 2026 — read-only profile cell for approved vendors
  roCell: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 10, marginBottom: 8 },
  roLabel: { fontSize: 10, letterSpacing: 1, fontWeight: "800", color: colors.textMuted },
  roValue: { fontSize: 14, fontWeight: "700", color: colors.textMain, marginTop: 4 },
});
