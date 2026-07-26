// Vendor · Request Edit — Nov 2026
//
// Approved vendors cannot edit their profile directly. This screen lets
// them submit a change request that admins review before applying it to
// their live profile.
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { LocationPicker, LocationValue } from "../../src/LocationPicker";

type MyStatus = { user?: any; application?: any };

export default function VendorRequestEdit() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<MyStatus | null>(null);
  // Editable fields — pre-filled with current vendor profile
  const [shopName, setShopName] = useState("");
  const [description, setDescription] = useState("");
  const [phone, setPhone] = useState("");
  const [gst, setGst] = useState("");
  const [pan, setPan] = useState("");
  const [bankName, setBankName] = useState("");
  const [bankAccount, setBankAccount] = useState("");
  const [bankIfsc, setBankIfsc] = useState("");
  const [note, setNote] = useState("");
  const [shopLocation, setShopLocation] = useState<LocationValue>({
    latitude: null, longitude: null, pincode: "", state: "",
    district: "", city: "", address: "",
  });
  const [deliveryRadiusKm, setDeliveryRadiusKm] = useState<number | "pincode">("pincode");
  const [pendingReq, setPendingReq] = useState<any>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get<MyStatus>("/vendor/me/status");
        setStatus(r.data);
        const u = (r.data?.user || {}) as any;
        const a = (r.data?.application || {}) as any;
        setShopName(u.shop_name || a.shop_name || "");
        setDescription(a.description || "");
        setPhone(u.phone || "");
        setGst(u.gst_number || a.gst_number || "");
        setPan(u.pan_number || a.pan_number || "");
        setBankName(u.bank_name || a.bank_name || "");
        setBankAccount(u.bank_account || a.bank_account || "");
        setBankIfsc(u.bank_ifsc || a.bank_ifsc || "");
        setShopLocation({
          latitude: (u.location?.coordinates?.[1]) ?? null,
          longitude: (u.location?.coordinates?.[0]) ?? null,
          pincode: u.pincode || a.pincode || "",
          state: u.state || a.state || "",
          district: u.district || a.district || "",
          city: u.city || a.city || "",
          address: u.store_address || a.store_address || "",
        });
        const km = u.delivery_radius_km ?? a.delivery_radius_km;
        setDeliveryRadiusKm(km || "pincode");
        // Check for existing pending request
        try {
          const mine = await api.get<{ items: any[] }>("/vendor/edit-requests/mine");
          const pending = (mine.data?.items || []).find((x: any) => x.status === "pending");
          setPendingReq(pending || null);
        } catch { /* ignore */ }
      } catch (e) {
        Alert.alert("Failed to load", formatApiError(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const onSubmit = async () => {
    if (pendingReq) {
      Alert.alert("Pending request", "You already have a pending edit request. Wait for admin review before submitting another.");
      return;
    }
    setSubmitting(true);
    try {
      const body: Record<string, any> = {
        shop_name: shopName.trim() || undefined,
        description: description.trim() || undefined,
        phone: phone.trim() || undefined,
        gst_number: gst.trim() || undefined,
        pan_number: pan.trim() || undefined,
        bank_name: bankName.trim() || undefined,
        bank_account: bankAccount.trim() || undefined,
        bank_ifsc: bankIfsc.trim() || undefined,
        pincode: shopLocation.pincode || undefined,
        state: shopLocation.state || undefined,
        district: shopLocation.district || undefined,
        city: shopLocation.city || undefined,
        store_address: shopLocation.address || undefined,
        delivery_radius_km: deliveryRadiusKm === "pincode" ? null : deliveryRadiusKm,
        delivery_radius_mode: deliveryRadiusKm === "pincode" ? "pincode" : "radius",
        location: (shopLocation.latitude !== null && shopLocation.longitude !== null)
          ? { type: "Point", coordinates: [shopLocation.longitude, shopLocation.latitude] }
          : undefined,
        note: note.trim() || undefined,
      };
      await api.post("/vendor/edit-requests", body);
      Alert.alert(
        "Edit request submitted",
        "Admin will review your changes. You'll see the update once approved.",
        [{ text: "OK", onPress: () => router.back() }],
      );
    } catch (e) { Alert.alert("Couldn't submit", formatApiError(e)); }
    finally { setSubmitting(false); }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
          <Text style={styles.title}>Request Vendor Edit</Text>
          <View style={{ width: 40 }} />
        </View>
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} keyboardShouldPersistTaps="handled">
          {pendingReq ? (
            <View style={[styles.card, { backgroundColor: "#FFF4E5" }]}>
              <Feather name="clock" size={22} color="#7A4A0E" />
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.cardTitle}>Pending request</Text>
                <Text style={styles.cardBody}>You submitted an edit request on {new Date(pendingReq.created_at).toLocaleDateString()}. Wait for admin to review it before submitting a new one.</Text>
              </View>
            </View>
          ) : (
            <View style={[styles.card, { backgroundColor: "#E6F1FB" }]}>
              <Feather name="info" size={22} color="#1F5E9E" />
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={styles.cardTitle}>Changes require admin approval</Text>
                <Text style={styles.cardBody}>Only fill the fields you want to change. Admin will apply approved changes to your live profile.</Text>
              </View>
            </View>
          )}

          <Text style={styles.section}>SHOP DETAILS</Text>
          <Text style={styles.label}>Shop name</Text>
          <TextInput style={styles.input} value={shopName} onChangeText={setShopName} placeholderTextColor={colors.textMuted} editable={!pendingReq} />
          <Text style={styles.label}>Description</Text>
          <TextInput style={[styles.input, styles.area]} value={description} onChangeText={setDescription} multiline textAlignVertical="top" placeholderTextColor={colors.textMuted} editable={!pendingReq} />
          <Text style={styles.label}>Phone</Text>
          <TextInput style={styles.input} value={phone} onChangeText={setPhone} keyboardType="phone-pad" placeholderTextColor={colors.textMuted} editable={!pendingReq} />

          <Text style={styles.section}>DOCUMENTS</Text>
          <Text style={styles.label}>GST number</Text>
          <TextInput style={styles.input} value={gst} onChangeText={setGst} autoCapitalize="characters" placeholderTextColor={colors.textMuted} editable={!pendingReq} />
          <Text style={styles.label}>PAN number</Text>
          <TextInput style={styles.input} value={pan} onChangeText={setPan} autoCapitalize="characters" placeholderTextColor={colors.textMuted} editable={!pendingReq} />

          <Text style={styles.section}>PAYOUT BANK ACCOUNT</Text>
          <Text style={styles.label}>Bank name</Text>
          <TextInput style={styles.input} value={bankName} onChangeText={setBankName} placeholderTextColor={colors.textMuted} editable={!pendingReq} />
          <Text style={styles.label}>Account number</Text>
          <TextInput style={styles.input} value={bankAccount} onChangeText={setBankAccount} keyboardType="number-pad" placeholderTextColor={colors.textMuted} editable={!pendingReq} />
          <Text style={styles.label}>IFSC code</Text>
          <TextInput style={styles.input} value={bankIfsc} onChangeText={setBankIfsc} autoCapitalize="characters" placeholderTextColor={colors.textMuted} editable={!pendingReq} />

          <LocationPicker
            value={shopLocation}
            onChange={setShopLocation}
            title="Shop location"
            hint="Tap 'Use current' to auto-fill via GPS, or edit the pincode manually."
            extraSlot={
              <View style={{ gap: 8 }}>
                <Text style={styles.label}>Delivery radius</Text>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                  {([2, 5, 10, 20, 50, "pincode"] as const).map((r) => {
                    const active = deliveryRadiusKm === r;
                    const label = r === "pincode" ? "Entire pincode" : `${r} km`;
                    return (
                      <TouchableOpacity key={String(r)} disabled={!!pendingReq} onPress={() => setDeliveryRadiusKm(r as any)} style={[styles.radiusChip, active && styles.radiusChipActive]}>
                        <Text style={[styles.radiusChipText, active && styles.radiusChipTextActive]}>{label}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              </View>
            }
          />

          <Text style={styles.label}>Reason / note for admin (optional)</Text>
          <TextInput style={[styles.input, styles.area]} value={note} onChangeText={setNote} multiline textAlignVertical="top" placeholder="Briefly explain the reason — helps admin approve faster." placeholderTextColor={colors.textMuted} editable={!pendingReq} />

          <TouchableOpacity
            onPress={onSubmit}
            disabled={submitting || !!pendingReq}
            style={[styles.primaryBtn, (submitting || pendingReq) && { opacity: 0.55 }]}
            testID="vendor-edit-submit"
          >
            {submitting ? <ActivityIndicator color={colors.primaryFg} /> : (
              <>
                <Feather name="send" size={16} color={colors.primaryFg} />
                <Text style={styles.primaryBtnText}>  Submit for approval</Text>
              </>
            )}
          </TouchableOpacity>
          <Text style={styles.note}>Only fields where you changed the value will be sent to admin.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  card: { flexDirection: "row", alignItems: "center", borderRadius: radii.card, padding: 14, marginBottom: 16 },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  cardBody: { fontSize: 12, color: colors.textMuted, marginTop: 3 },
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
});
