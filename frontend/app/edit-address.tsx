// Edit address screen — lets the authenticated user update their
// delivery / contact address (street, city, state, pincode). KYC docs are
// separate; this only updates address fields used for order delivery and
// service area matching.
import { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

export default function EditAddress() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [pincode, setPincode] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    setAddress(((user as any).address as string) || "");
    setCity(((user as any).city as string) || "");
    setState(((user as any).state as string) || "");
    setPincode(((user as any).pincode as string) || "");
  }, [user]);

  const onSave = async () => {
    if (pincode && !/^\d{4,10}$/.test(pincode.trim())) {
      return Alert.alert("Heads up", "Pincode must be numeric (4-10 digits).");
    }
    setSaving(true);
    try {
      await api.patch("/users/me/address", {
        address: address.trim(),
        city: city.trim(),
        state: state.trim(),
        pincode: pincode.trim(),
      });
      try { await refresh(); } catch {}
      Alert.alert("Saved", "Your address has been updated.", [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={s.header}>
          <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={s.title}>Edit Address</Text>
          <View style={{ width: 40 }} />
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
          <View style={s.hintBox}>
            <Feather name="info" size={14} color={colors.primary} />
            <Text style={s.hintText}>
              We use this address for order delivery and to match you with nearby
              service providers. Update anytime.
            </Text>
          </View>

          <Text style={s.label}>STREET ADDRESS</Text>
          <TextInput
            style={[s.input, { minHeight: 80, textAlignVertical: "top" }]}
            value={address}
            onChangeText={setAddress}
            placeholder="House number, street, locality"
            placeholderTextColor={colors.textMuted}
            multiline
            maxLength={300}
            testID="addr-street"
          />

          <Text style={s.label}>CITY</Text>
          <TextInput
            style={s.input}
            value={city}
            onChangeText={setCity}
            placeholder="e.g. Hyderabad"
            placeholderTextColor={colors.textMuted}
            maxLength={80}
            testID="addr-city"
          />

          <Text style={s.label}>STATE</Text>
          <TextInput
            style={s.input}
            value={state}
            onChangeText={setState}
            placeholder="e.g. Telangana"
            placeholderTextColor={colors.textMuted}
            maxLength={80}
            testID="addr-state"
          />

          <Text style={s.label}>PINCODE</Text>
          <TextInput
            style={s.input}
            value={pincode}
            onChangeText={(v) => setPincode(v.replace(/[^0-9]/g, "").slice(0, 10))}
            placeholder="6 digits"
            placeholderTextColor={colors.textMuted}
            keyboardType="numeric"
            maxLength={10}
            testID="addr-pincode"
          />

          <TouchableOpacity
            onPress={onSave}
            disabled={saving}
            style={[s.saveBtn, saving && { opacity: 0.6 }]}
            testID="addr-save"
          >
            {saving ? <ActivityIndicator color="#fff" /> : (
              <>
                <Feather name="check" size={16} color="#fff" />
                <Text style={s.saveText}>{"  "}Save address</Text>
              </>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  hintBox: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: colors.brand100,
    borderRadius: radii.card, padding: 12,
  },
  hintText: { flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 18 },
  label: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 18, marginBottom: 8 },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 13,
    fontSize: 14, color: colors.textMain,
  },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary, borderRadius: radii.button,
    paddingVertical: 14, marginTop: 28,
  },
  saveText: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
