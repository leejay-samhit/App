// Delivery Partner — apply form (Sep-2026).
// Mirrors the vendor apply flow: delivery radius, pincodes, vehicle, docs.
// A rider is NOT a seller — the server refuses the application if the account
// is already a vendor or service provider.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { Stack, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { SubscriptionLocked } from "../../src/subscription";
import { colors, spacing, radii } from "../../src/theme";

const VEHICLES = ["bike", "scooter", "cycle", "car", "van"];

export default function DeliveryApply() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [loading, setLoading] = useState(true);
  const [state, setState] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const [fullName, setFullName] = useState(user?.name || "");
  const [phone, setPhone] = useState((user as any)?.phone || "");
  const [vehicle, setVehicle] = useState("bike");
  const [vehicleNo, setVehicleNo] = useState("");
  const [radius, setRadius] = useState("5");
  const [pincodes, setPincodes] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [address, setAddress] = useState("");

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/delivery-partner/me");
      setState(data);
    } catch { setState(null); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    setErr("");
    if (fullName.trim().length < 3) { setErr("Enter your full name"); return; }
    if (phone.trim().length < 10) { setErr("Enter a valid 10-digit phone number"); return; }
    const pins = pincodes.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean);
    if (pins.length === 0) { setErr("Add at least one pincode you can deliver to"); return; }
    setSaving(true);
    try {
      await api.post("/delivery-partner/apply", {
        full_name: fullName.trim(),
        phone: phone.trim(),
        vehicle_type: vehicle,
        vehicle_number: vehicleNo.trim(),
        delivery_radius_km: Number(radius) || 5,
        pincodes: pins,
        city: city.trim(),
        state: stateName.trim(),
        address: address.trim(),
      });
      await refresh();
      Alert.alert(
        "Application sent",
        "Admin will review your details and map the shops you deliver for.",
        [{ text: "OK", onPress: () => router.back() }],
      );
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setSaving(false); }
  };

  const status = state?.status || "none";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="dp-apply-back">
          <Feather name="chevron-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Become a delivery partner</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      ) : !user?.registration_paid ? (
        <View style={{ padding: 16 }}>
          <SubscriptionLocked feature="Delivering orders" />
        </View>
      ) : status === "pending" ? (
        <View style={styles.pad}>
          <View style={styles.infoCard}>
            <Feather name="clock" size={18} color={colors.warning} />
            <Text style={styles.infoText}>
              Your application is under review. You&apos;ll be notified once admin approves it
              and maps the shops you deliver for.
            </Text>
          </View>
        </View>
      ) : status === "approved" ? (
        <View style={styles.pad}>
          <View style={styles.infoCard}>
            <Feather name="check-circle" size={18} color={colors.success} />
            <Text style={styles.infoText}>You&apos;re an approved delivery partner.</Text>
          </View>
          <TouchableOpacity
            style={styles.primaryBtn}
            onPress={() => router.replace("/delivery/dashboard" as any)}
            testID="dp-open-dashboard"
          >
            <Text style={styles.primaryBtnText}>Open my dashboard</Text>
          </TouchableOpacity>
        </View>
      ) : !state?.can_apply ? (
        <View style={styles.pad}>
          <View style={styles.infoCard}>
            <Feather name="info" size={18} color={colors.textMuted} />
            <Text style={styles.infoText}>
              {state?.blocked_reason || "Your account is not eligible to apply yet."}
            </Text>
          </View>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.pad} keyboardShouldPersistTaps="handled">
          <Text style={styles.lead}>
            Deliver orders for the shops admin maps to you. You collect cash on COD orders and
            pay it in from your dashboard — there is no per-delivery fee.
          </Text>

          <Text style={styles.label}>FULL NAME</Text>
          <TextInput style={styles.input} value={fullName} onChangeText={setFullName}
            placeholder="As on your ID" placeholderTextColor={colors.textMuted} testID="dp-name" />

          <Text style={styles.label}>PHONE</Text>
          <TextInput style={styles.input} value={phone} onChangeText={setPhone}
            keyboardType="phone-pad" placeholder="10-digit mobile"
            placeholderTextColor={colors.textMuted} testID="dp-phone" />

          <Text style={styles.label}>VEHICLE</Text>
          <View style={styles.chipRow}>
            {VEHICLES.map((v) => (
              <TouchableOpacity key={v} onPress={() => setVehicle(v)}
                style={[styles.chip, vehicle === v && styles.chipOn]} testID={`dp-vehicle-${v}`}>
                <Text style={[styles.chipText, vehicle === v && styles.chipTextOn]}>
                  {v.charAt(0).toUpperCase() + v.slice(1)}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.label}>VEHICLE NUMBER</Text>
          <TextInput style={styles.input} value={vehicleNo} onChangeText={setVehicleNo}
            placeholder="e.g. AP 09 XX 1234" placeholderTextColor={colors.textMuted}
            autoCapitalize="characters" testID="dp-vehicle-no" />

          <Text style={styles.label}>DELIVERY RADIUS (KM)</Text>
          <TextInput style={styles.input} value={radius} onChangeText={setRadius}
            keyboardType="numeric" placeholder="5" placeholderTextColor={colors.textMuted}
            testID="dp-radius" />

          <Text style={styles.label}>PINCODES YOU COVER</Text>
          <TextInput style={[styles.input, { height: 74, textAlignVertical: "top" }]}
            value={pincodes} onChangeText={setPincodes} multiline
            placeholder="517641, 517644, 517645" placeholderTextColor={colors.textMuted}
            testID="dp-pincodes" />
          <Text style={styles.hint}>Separate with commas or spaces</Text>

          <Text style={styles.label}>CITY</Text>
          <TextInput style={styles.input} value={city} onChangeText={setCity}
            placeholder="City" placeholderTextColor={colors.textMuted} testID="dp-city" />

          <Text style={styles.label}>STATE</Text>
          <TextInput style={styles.input} value={stateName} onChangeText={setStateName}
            placeholder="State" placeholderTextColor={colors.textMuted} testID="dp-state" />

          <Text style={styles.label}>ADDRESS</Text>
          <TextInput style={[styles.input, { height: 74, textAlignVertical: "top" }]}
            value={address} onChangeText={setAddress} multiline
            placeholder="Where you're based" placeholderTextColor={colors.textMuted}
            testID="dp-address" />

          {err ? <Text style={styles.err}>{err}</Text> : null}
          <TouchableOpacity style={[styles.primaryBtn, saving && { opacity: 0.6 }]}
            onPress={submit} disabled={saving} testID="dp-submit">
            {saving ? <ActivityIndicator color={colors.primaryFg} />
              : <Text style={styles.primaryBtnText}>Send application</Text>}
          </TouchableOpacity>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 8, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 17, fontWeight: "800", color: colors.textMain, flex: 1 },
  pad: { padding: spacing.screen, paddingBottom: 60 },
  lead: { fontSize: 13, color: colors.textMuted, fontWeight: "600", lineHeight: 19, marginBottom: 18 },
  label: { fontSize: 10, letterSpacing: 1.1, fontWeight: "900", color: colors.textMuted, marginTop: 14, marginBottom: 6 },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 13, paddingVertical: 12,
    fontSize: 14, color: colors.textMain, minHeight: 46,
  },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 5, fontWeight: "600" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, minHeight: 44,
    justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  chipTextOn: { color: colors.primaryFg },
  primaryBtn: {
    marginTop: 24, backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 15, alignItems: "center", minHeight: 48, justifyContent: "center",
  },
  primaryBtnText: { color: colors.primaryFg, fontSize: 15, fontWeight: "800" },
  err: { color: "#B3261E", fontSize: 13, fontWeight: "700", marginTop: 14 },
  infoCard: {
    flexDirection: "row", gap: 10, alignItems: "flex-start",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.card, padding: 14,
  },
  infoText: { flex: 1, fontSize: 13, color: colors.textMain, fontWeight: "600", lineHeight: 19 },
});
