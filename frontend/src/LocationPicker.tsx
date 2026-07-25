/**
 * LocationPicker — reusable "Use current location" card (Sept 2026).
 *
 * Owner spec (geospatial marketplace):
 *   Both vendor shop setup AND customer delivery address need the same
 *   "capture GPS + reverse-geocode → autofill pincode/state/district/city"
 *   flow.  This component wraps `expo-location`:
 *
 *     1. `Location.requestForegroundPermissionsAsync()` — per
 *        <handle_permissions_contract>, contextual and honours canAskAgain.
 *     2. `getCurrentPositionAsync({ accuracy: Balanced })` — one-shot fix.
 *     3. `reverseGeocodeAsync({lat, lng})` — on-device (no Google key).
 *     4. Returns a `LocationValue` payload up via `onChange` so the parent
 *        can persist it to the backend.
 *
 * Manual-edit friendly:
 *   Every field the geocode fills in remains editable — the auto-fill
 *   is a fast-start, not a lock.
 *
 * Fallback:
 *   If GPS is denied twice, we show a permanent "Open settings" link and
 *   let the user type pincode/state/district/city manually.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, TextInput, ActivityIndicator, Alert, Linking } from "react-native";
import { Feather } from "@expo/vector-icons";
import * as Location from "expo-location";
import { colors, radii, spacing } from "./theme";

export type LocationValue = {
  latitude: number | null;
  longitude: number | null;
  pincode: string;
  state: string;
  district: string;
  city: string;
  address: string;
};

export const EMPTY_LOCATION: LocationValue = {
  latitude: null, longitude: null,
  pincode: "", state: "", district: "", city: "", address: "",
};

type Props = {
  value: LocationValue;
  onChange: (next: LocationValue) => void;
  title?: string;
  hint?: string;
  // Optional — extra field shown between address and lat/lng, e.g.
  // vendor Delivery Radius selector.  Rendered as-is so the parent
  // controls its own state.
  extraSlot?: React.ReactNode;
};

const patch = (v: LocationValue, p: Partial<LocationValue>): LocationValue => ({ ...v, ...p });

export function LocationPicker({ value, onChange, title = "Location", hint, extraSlot }: Props) {
  const [busy, setBusy] = useState(false);
  const [permDenied, setPermDenied] = useState(false);

  const captureLocation = async () => {
    setBusy(true);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        setPermDenied(!perm.canAskAgain);
        if (!perm.canAskAgain) {
          Alert.alert(
            "Location permission blocked",
            "Enable location for this app in Settings so we can auto-fill your address.",
            [{ text: "Cancel" }, { text: "Open Settings", onPress: () => Linking.openSettings() }],
          );
        } else {
          Alert.alert("Location required", "Grant location permission to auto-fill your delivery address.");
        }
        return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const { latitude, longitude } = pos.coords;
      // Reverse-geocode on-device.  Returns 0..N candidates; the first
      // is usually the best. `postalCode` maps to pincode in India.
      let pincode = value.pincode;
      let state = value.state;
      let district = value.district;
      let city = value.city;
      let address = value.address;
      try {
        const rev = await Location.reverseGeocodeAsync({ latitude, longitude });
        if (rev && rev.length > 0) {
          const r0 = rev[0];
          pincode = r0.postalCode || pincode;
          state = r0.region || state;
          district = r0.subregion || r0.district || district;
          city = r0.city || r0.name || city;
          // Build a nice one-line address if we didn't already have one.
          const parts = [r0.name, r0.street, r0.district, r0.city, r0.postalCode].filter(Boolean);
          if (!address && parts.length > 0) address = parts.join(", ");
        }
      } catch { /* reverse geocode is best-effort */ }
      onChange({ latitude, longitude, pincode, state, district, city, address });
    } catch (e: any) {
      Alert.alert("Couldn't capture location", e?.message || "Please try again.");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={styles.iconWrap}><Feather name="map-pin" size={16} color={colors.primary} /></View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>{title}</Text>
          {hint ? <Text style={styles.hint}>{hint}</Text> : null}
        </View>
        <TouchableOpacity
          onPress={captureLocation}
          disabled={busy}
          style={[styles.captureBtn, busy && { opacity: 0.6 }]}
          testID="location-capture"
        >
          {busy
            ? <ActivityIndicator color={colors.primaryFg} size="small" />
            : <><Feather name="crosshair" size={13} color={colors.primaryFg} /><Text style={styles.captureBtnText}>Use current</Text></>}
        </TouchableOpacity>
      </View>

      {/* Lat/Lng readout — shown compactly to reassure the user we captured GPS. */}
      {(value.latitude !== null && value.longitude !== null) ? (
        <View style={styles.coordRow}>
          <Feather name="check" size={11} color={colors.success || "#16A34A"} />
          <Text style={styles.coordText}>
            GPS · {value.latitude.toFixed(5)}, {value.longitude.toFixed(5)}
          </Text>
        </View>
      ) : null}

      {/* Editable fields — auto-populated after capture, still user-editable. */}
      <View style={styles.formGrid}>
        <View style={styles.formCol}>
          <Text style={styles.label}>Pincode *</Text>
          <TextInput
            style={styles.input}
            value={value.pincode}
            onChangeText={(t) => onChange(patch(value, { pincode: t.replace(/\D/g, "").slice(0, 6) }))}
            keyboardType="number-pad"
            maxLength={6}
            placeholder="500001"
            placeholderTextColor={colors.textMuted}
            testID="location-pincode"
          />
        </View>
        <View style={styles.formCol}>
          <Text style={styles.label}>City</Text>
          <TextInput
            style={styles.input}
            value={value.city}
            onChangeText={(t) => onChange(patch(value, { city: t }))}
            placeholder="Hyderabad"
            placeholderTextColor={colors.textMuted}
            testID="location-city"
          />
        </View>
      </View>
      <View style={styles.formGrid}>
        <View style={styles.formCol}>
          <Text style={styles.label}>District</Text>
          <TextInput
            style={styles.input}
            value={value.district}
            onChangeText={(t) => onChange(patch(value, { district: t }))}
            placeholder="Hyderabad"
            placeholderTextColor={colors.textMuted}
            testID="location-district"
          />
        </View>
        <View style={styles.formCol}>
          <Text style={styles.label}>State</Text>
          <TextInput
            style={styles.input}
            value={value.state}
            onChangeText={(t) => onChange(patch(value, { state: t }))}
            placeholder="Telangana"
            placeholderTextColor={colors.textMuted}
            testID="location-state"
          />
        </View>
      </View>
      <Text style={styles.label}>Full address</Text>
      <TextInput
        style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
        value={value.address}
        onChangeText={(t) => onChange(patch(value, { address: t }))}
        placeholder="Door no, street, landmark"
        placeholderTextColor={colors.textMuted}
        multiline
        testID="location-address"
      />

      {extraSlot ? <View style={{ marginTop: 8 }}>{extraSlot}</View> : null}

      {permDenied ? (
        <TouchableOpacity onPress={() => Linking.openSettings()} style={styles.settingsRow} testID="location-open-settings">
          <Feather name="settings" size={12} color={colors.primary} />
          <Text style={styles.settingsText}>Open Settings to grant location permission</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginTop: spacing.md, gap: 4 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 4 },
  iconWrap: { width: 32, height: 32, borderRadius: 8, backgroundColor: colors.primary + "1A", alignItems: "center", justifyContent: "center" },
  title: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  captureBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.primary },
  captureBtnText: { fontSize: 11, fontWeight: "800", color: colors.primaryFg, letterSpacing: 0.2 },
  coordRow: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: (colors.success || "#16A34A") + "1A", paddingHorizontal: 8, paddingVertical: 5, borderRadius: 6, alignSelf: "flex-start", marginBottom: 8, marginTop: 4 },
  coordText: { fontSize: 10, color: colors.success || "#16A34A", fontWeight: "800", letterSpacing: 0.3 },
  formGrid: { flexDirection: "row", gap: 10, marginTop: 4 },
  formCol: { flex: 1 },
  label: { fontSize: 11, color: colors.textMuted, fontWeight: "700", letterSpacing: 0.3, marginTop: 6, marginBottom: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: colors.textMain, backgroundColor: colors.surface },
  settingsRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, paddingVertical: 6 },
  settingsText: { fontSize: 11, color: colors.primary, fontWeight: "700", textDecorationLine: "underline" },
});
