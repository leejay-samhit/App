/**
 * Personal Information (Jun-2027).
 *
 * Profile used to carry three separate rows — Mobile number, KYC Verification
 * and My Address. They are all "who you are" information, so they live here
 * as three clearly separated sections of one screen.
 *
 * Nothing about the underlying data changed: the number is still changed
 * through the WhatsApp-code flow (/change-mobile), KYC still uses the existing
 * documents screen (/kyc) and the address still saves through the existing
 * PATCH /users/me/address. The account id never changes, so wallet, orders,
 * KYC records and chat history stay exactly where they are.
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";

type KycStatus = "none" | "pending" | "approved" | "rejected";
type Kyc = {
  status: KycStatus;
  full_name?: string | null;
  aadhaar?: string | null;
  pan?: string | null;
  reject_reason?: string | null;
  submitted_at?: string | null;
};

const KYC_LOOK: Record<KycStatus, { label: string; color: string; hint: string; cta: string }> = {
  none: {
    label: "Not submitted", color: colors.textMuted,
    hint: "Verify your identity once to unlock payouts and higher limits.",
    cta: "Start verification",
  },
  pending: {
    label: "Under review", color: colors.warning,
    hint: "Our team is checking your documents. This usually takes a day.",
    cta: "View my documents",
  },
  approved: {
    label: "Verified", color: colors.success,
    hint: "Your identity is verified.",
    cta: "View my documents",
  },
  rejected: {
    label: "Needs correction", color: colors.error,
    hint: "Something didn't match. Please correct it and send it again.",
    cta: "Fix and resubmit",
  },
};

const mask = (v?: string | null, keep = 4) => {
  const s = (v || "").replace(/\s/g, "");
  if (!s) return "";
  return s.length <= keep ? s : `${"•".repeat(Math.max(0, s.length - keep))}${s.slice(-keep)}`;
};

/** Declared OUTSIDE the screen: a component defined inside a render would be
 *  a new type on every keystroke, which unmounts the TextInput and loses the
 *  keyboard mid-word. */
function Field(props: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; keyboardType?: any; maxLength?: number; testID?: string;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{props.label}</Text>
      <TextInput
        style={styles.input}
        value={props.value}
        onChangeText={props.onChange}
        placeholder={props.placeholder}
        placeholderTextColor={colors.textMuted}
        keyboardType={props.keyboardType}
        maxLength={props.maxLength}
        testID={props.testID}
      />
    </View>
  );
}

export default function PersonalInfoScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth() as any;

  const [kyc, setKyc] = useState<Kyc | null>(null);
  const [loadingKyc, setLoadingKyc] = useState(true);

  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [pincode, setPincode] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const loadKyc = useCallback(async () => {
    try {
      const { data } = await api.get<Kyc>("/users/me/kyc");
      setKyc(data);
    } catch {
      setKyc(null);            // never block the screen on the KYC read
    } finally {
      setLoadingKyc(false);
    }
  }, []);

  // Coming back from /change-mobile or /kyc must show the new state.
  useFocusEffect(useCallback(() => { loadKyc(); refresh?.(); }, [loadKyc, refresh]));

  useEffect(() => {
    if (!user || dirty) return;
    setAddress(((user as any).address as string) || "");
    setCity(((user as any).city as string) || "");
    setState(((user as any).state as string) || "");
    setPincode(((user as any).pincode as string) || "");
  }, [user, dirty]);

  const phone = (user as any)?.phone || "";
  const phoneVerified = !!(user as any)?.phone_verified;
  const status: KycStatus = (kyc?.status as KycStatus) || "none";
  const look = KYC_LOOK[status];

  const saveAddress = async () => {
    if (pincode && !/^\d{4,10}$/.test(pincode.trim())) {
      return Alert.alert("Check the pincode", "A pincode is 4–10 digits.");
    }
    setSaving(true);
    try {
      await api.patch("/users/me/address", {
        address: address.trim(), city: city.trim(),
        state: state.trim(), pincode: pincode.trim(),
      });
      await refresh?.();
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      Alert.alert("Could not save", formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="personal-info-back">
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Personal Information</Text>
        <View style={styles.backBtn} />
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.body}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {/* ─────────── A · MOBILE NUMBER ─────────── */}
          <Text style={styles.sectionLabel}>MOBILE NUMBER</Text>
          <View style={styles.card} testID="personal-info-mobile">
            <View style={styles.cardRow}>
              <View style={styles.iconWrap}>
                <Feather name="smartphone" size={18} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.value}>{phone ? `+91 ${phone}` : "Not added yet"}</Text>
                <Text style={styles.caption}>
                  {phone
                    ? "Orders, deliveries and your WhatsApp code use this number."
                    : "Add a number so orders and deliveries can reach you."}
                </Text>
              </View>
            </View>
            <View
              style={[styles.badge, { backgroundColor: phoneVerified ? colors.success : colors.warning }]}
              testID="personal-info-phone-status"
            >
              <Feather name={phoneVerified ? "check" : "alert-circle"} size={11} color="#FFFFFF" />
              <Text style={styles.badgeText}>{phoneVerified ? "VERIFIED" : "NOT VERIFIED"}</Text>
            </View>
            <TouchableOpacity
              onPress={() => router.push("/change-mobile" as any)}
              style={styles.actionBtn}
              testID="personal-info-change-mobile"
            >
              <Feather name="edit-2" size={14} color={colors.primary} />
              <Text style={styles.actionText}>{phone ? "Change mobile number" : "Add mobile number"}</Text>
            </TouchableOpacity>
            <Text style={styles.footnote}>
              A WhatsApp code confirms the new number before it is saved. Your account, wallet and
              order history stay exactly as they are.
            </Text>
          </View>

          {/* ─────────── B · KYC VERIFICATION ─────────── */}
          <Text style={styles.sectionLabel}>KYC VERIFICATION</Text>
          <View style={styles.card} testID="personal-info-kyc">
            {loadingKyc ? (
              <ActivityIndicator color={colors.primary} />
            ) : (
              <>
                <View style={styles.cardRow}>
                  <View style={styles.iconWrap}>
                    <Feather name="shield" size={18} color={colors.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.value}>{look.label}</Text>
                    <Text style={styles.caption}>{look.hint}</Text>
                  </View>
                </View>
                <View
                  style={[styles.badge, { backgroundColor: look.color }]}
                  testID="personal-info-kyc-status"
                >
                  <Text style={styles.badgeText}>{look.label.toUpperCase()}</Text>
                </View>
                {status === "rejected" && kyc?.reject_reason ? (
                  <Text style={styles.reject}>Reason: {kyc.reject_reason}</Text>
                ) : null}
                {kyc?.full_name || kyc?.aadhaar || kyc?.pan ? (
                  <View style={styles.detailBox}>
                    {kyc?.full_name ? (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailKey}>Name</Text>
                        <Text style={styles.detailVal}>{kyc.full_name}</Text>
                      </View>
                    ) : null}
                    {kyc?.aadhaar ? (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailKey}>Aadhaar</Text>
                        <Text style={styles.detailVal}>{mask(kyc.aadhaar)}</Text>
                      </View>
                    ) : null}
                    {kyc?.pan ? (
                      <View style={styles.detailRow}>
                        <Text style={styles.detailKey}>PAN</Text>
                        <Text style={styles.detailVal}>{mask(kyc.pan)}</Text>
                      </View>
                    ) : null}
                  </View>
                ) : null}
                <TouchableOpacity
                  onPress={() => router.push("/kyc")}
                  style={styles.actionBtn}
                  testID="personal-info-open-kyc"
                >
                  <Feather name="file-text" size={14} color={colors.primary} />
                  <Text style={styles.actionText}>{look.cta}</Text>
                </TouchableOpacity>
              </>
            )}
          </View>

          {/* ─────────── C · MY ADDRESS ─────────── */}
          <Text style={styles.sectionLabel}>MY ADDRESS</Text>
          <View style={styles.card} testID="personal-info-address">
            <View style={styles.cardRow}>
              <View style={styles.iconWrap}>
                <Feather name="map-pin" size={18} color={colors.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.value}>
                  {address || city ? [address, city, state, pincode].filter(Boolean).join(", ") : "No address saved"}
                </Text>
                <Text style={styles.caption}>Used for delivery and to match you with nearby shops.</Text>
              </View>
            </View>
            <Field
              label="House / street"
              value={address}
              onChange={(v) => { setAddress(v); setDirty(true); }}
              placeholder="Flat, building, street"
              testID="personal-info-address-input"
            />
            <View style={styles.row2}>
              <View style={{ flex: 1 }}>
                <Field label="City" value={city} onChange={(v) => { setCity(v); setDirty(true); }} placeholder="City" testID="personal-info-city-input" />
              </View>
              <View style={{ flex: 1 }}>
                <Field label="State" value={state} onChange={(v) => { setState(v); setDirty(true); }} placeholder="State" testID="personal-info-state-input" />
              </View>
            </View>
            <Field
              label="Pincode"
              value={pincode}
              onChange={(v) => { setPincode(v); setDirty(true); }}
              placeholder="6-digit pincode"
              keyboardType="number-pad"
              maxLength={10}
              testID="personal-info-pincode-input"
            />
            <TouchableOpacity
              onPress={saveAddress}
              disabled={saving || !dirty}
              style={[styles.saveBtn, (saving || !dirty) && { opacity: 0.5 }]}
              testID="personal-info-save-address"
            >
              {saving
                ? <ActivityIndicator color={colors.primaryFg} size="small" />
                : <Feather name="check" size={15} color={colors.primaryFg} />}
              <Text style={styles.saveText}>{saved ? "Saved" : "Save address"}</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.screen, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  backBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  body: { padding: spacing.screen, paddingBottom: 48 },
  sectionLabel: {
    fontSize: 10.5, fontWeight: "800", letterSpacing: 1.1,
    color: colors.textMuted, marginBottom: 8, marginTop: 8,
  },
  card: {
    backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1,
    borderColor: colors.border, padding: 14, marginBottom: 16, gap: 10,
  },
  cardRow: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
  iconWrap: {
    width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted,
  },
  value: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginBottom: 2 },
  caption: { fontSize: 12, color: colors.textMuted, lineHeight: 17 },
  badge: {
    alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 9, paddingVertical: 4, borderRadius: 999,
  },
  badgeText: { fontSize: 9.5, fontWeight: "800", color: "#FFFFFF", letterSpacing: 0.6 },
  actionBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 46, borderRadius: radii.button, borderWidth: 1.5, borderColor: colors.primary,
  },
  actionText: { fontSize: 13.5, fontWeight: "800", color: colors.primary },
  footnote: { fontSize: 11, color: colors.textMuted, lineHeight: 16 },
  reject: { fontSize: 12, color: colors.error, lineHeight: 17 },
  detailBox: {
    backgroundColor: colors.surfaceMuted, borderRadius: radii.card, padding: 10, gap: 6,
  },
  detailRow: { flexDirection: "row", justifyContent: "space-between", gap: 12 },
  detailKey: { fontSize: 11.5, color: colors.textMuted, fontWeight: "700" },
  detailVal: { fontSize: 12.5, color: colors.textMain, fontWeight: "700", flexShrink: 1, textAlign: "right" },
  field: { gap: 6 },
  fieldLabel: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.input,
    paddingHorizontal: 12, minHeight: 46, fontSize: 14.5, color: colors.textMain,
    backgroundColor: colors.background,
  },
  row2: { flexDirection: "row", gap: 10 },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.primary, borderRadius: radii.button, minHeight: 48, marginTop: 2,
  },
  saveText: { fontSize: 14, fontWeight: "800", color: colors.primaryFg },
});
