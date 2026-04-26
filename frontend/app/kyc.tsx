import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, ActivityIndicator,
  KeyboardAvoidingView, Platform, Image, Modal, ActionSheetIOS, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing } from "../src/theme";
import { pickFromLibrary, takePhoto } from "../src/imagePick";

type KYC = {
  status: "none" | "pending" | "approved" | "rejected";
  full_name?: string | null;
  aadhaar?: string | null;
  pan?: string | null;
  reject_reason?: string | null;
  submitted_at?: string | null;
  aadhaar_front?: string | null;
  aadhaar_back?: string | null;
  pan_image?: string | null;
  selfie?: string | null;
  has_aadhaar_front?: boolean;
  has_aadhaar_back?: boolean;
  has_pan_image?: boolean;
  has_selfie?: boolean;
};

const STATUS_COLORS: Record<string, string> = {
  none: "#94A3B8",
  pending: colors.warning,
  approved: colors.success,
  rejected: "#B3261E",
};

type Slot = {
  key: "aadhaar_front" | "aadhaar_back" | "pan_image" | "selfie";
  title: string;
  subtitle: string;
  icon: keyof typeof Feather.glyphMap;
};

const SLOTS: Slot[] = [
  { key: "aadhaar_front", title: "Aadhaar — Front", subtitle: "Photo or screenshot of front side", icon: "credit-card" },
  { key: "aadhaar_back", title: "Aadhaar — Back", subtitle: "Photo of the back side with address", icon: "credit-card" },
  { key: "pan_image", title: "PAN card", subtitle: "Clear photo of your PAN card", icon: "file-text" },
  { key: "selfie", title: "Selfie", subtitle: "A clear photo of your face", icon: "user" },
];

export default function UserKYC() {
  const router = useRouter();
  const [data, setData] = useState<KYC | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [fullName, setFullName] = useState("");
  const [aadhaar, setAadhaar] = useState("");
  const [pan, setPan] = useState("");
  const [msg, setMsg] = useState("");
  const [images, setImages] = useState<{ [k in Slot["key"]]?: string }>({});
  const [preview, setPreview] = useState<string | null>(null);
  const [pickerFor, setPickerFor] = useState<Slot["key"] | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<KYC>("/users/me/kyc");
      setData(data);
      setFullName(data.full_name || "");
      setAadhaar(data.aadhaar || "");
      setPan(data.pan || "");
      // pre-fill existing images so user can preview them
      setImages({
        aadhaar_front: data.aadhaar_front || undefined,
        aadhaar_back: data.aadhaar_back || undefined,
        pan_image: data.pan_image || undefined,
        selfie: data.selfie || undefined,
      });
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const choose = async (slot: Slot["key"], source: "camera" | "library") => {
    const fn = source === "camera" ? takePhoto : pickFromLibrary;
    try {
      const b64 = await fn();
      if (b64) setImages((p) => ({ ...p, [slot]: b64 }));
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not load image");
    }
  };

  const openSourcePicker = (slot: Slot["key"]) => {
    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        { options: ["Cancel", "Take Photo", "Choose from Library"], cancelButtonIndex: 0 },
        (idx) => {
          if (idx === 1) choose(slot, "camera");
          if (idx === 2) choose(slot, "library");
        }
      );
    } else {
      setPickerFor(slot);
    }
  };

  const removeImage = (slot: Slot["key"]) => setImages((p) => ({ ...p, [slot]: undefined }));

  const onSubmit = async () => {
    if (!fullName || aadhaar.length !== 12 || pan.length !== 10) return;
    // Require at least Aadhaar front + PAN + selfie on first submission (or when none stored).
    const requiredMissing: string[] = [];
    if (!images.aadhaar_front && !data?.has_aadhaar_front) requiredMissing.push("Aadhaar Front");
    if (!images.pan_image && !data?.has_pan_image) requiredMissing.push("PAN");
    if (!images.selfie && !data?.has_selfie) requiredMissing.push("Selfie");
    if (requiredMissing.length) {
      Alert.alert("Add documents", `Please add: ${requiredMissing.join(", ")}.`);
      return;
    }

    setMsg("");
    setSubmitting(true);
    try {
      // Send only newly picked images (data URLs) — server keeps existing ones if omitted.
      const isNew = (s: string | undefined) => !!s && s.startsWith("data:");
      await api.post("/users/me/kyc", {
        full_name: fullName.trim(),
        aadhaar: aadhaar.trim(),
        pan: pan.trim(),
        aadhaar_front: isNew(images.aadhaar_front) ? images.aadhaar_front : undefined,
        aadhaar_back: isNew(images.aadhaar_back) ? images.aadhaar_back : undefined,
        pan_image: isNew(images.pan_image) ? images.pan_image : undefined,
        selfie: isNew(images.selfie) ? images.selfie : undefined,
      });
      await load();
      setMsg("KYC submitted for review");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally { setSubmitting(false); }
  };

  if (loading || !data) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  const editable = data.status !== "approved" && data.status !== "pending";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="kyc-back">
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>KYC Verification</Text>
            <View style={{ width: 40 }} />
          </View>

          <View style={[styles.statusCard, { borderColor: STATUS_COLORS[data.status] }]}>
            <View style={[styles.statusIcon, { backgroundColor: STATUS_COLORS[data.status] }]}>
              <Feather
                name={data.status === "approved" ? "check" : data.status === "rejected" ? "x" : data.status === "pending" ? "clock" : "alert-circle"}
                size={20}
                color="#fff"
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.statusTitle}>
                {data.status === "approved" ? "Verified" : data.status === "pending" ? "Under review" : data.status === "rejected" ? "Rejected" : "Not submitted"}
              </Text>
              <Text style={styles.statusBody}>
                {data.status === "approved" && "Your identity has been verified. You can use all features."}
                {data.status === "pending" && "We're reviewing your KYC details. This usually takes 24 hours."}
                {data.status === "rejected" && (data.reject_reason || "Please review and resubmit.")}
                {data.status === "none" && "Submit your details and documents to verify your account."}
              </Text>
            </View>
          </View>

          <Text style={styles.sectionLabel}>YOUR DETAILS</Text>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>Full name (as per ID)</Text>
            <TextInput
              testID="kyc-fullname"
              value={fullName}
              onChangeText={setFullName}
              editable={editable}
              style={[styles.input, !editable && styles.inputDisabled]}
              placeholder="Enter full legal name"
              placeholderTextColor={colors.textMuted}
            />
          </View>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>Aadhaar number (12 digits)</Text>
            <TextInput
              testID="kyc-aadhaar"
              value={aadhaar}
              onChangeText={(t) => setAadhaar(t.replace(/\D/g, "").slice(0, 12))}
              editable={editable}
              keyboardType="numeric"
              style={[styles.input, !editable && styles.inputDisabled]}
              placeholder="XXXX XXXX XXXX"
              placeholderTextColor={colors.textMuted}
            />
          </View>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>PAN (10 characters)</Text>
            <TextInput
              testID="kyc-pan"
              value={pan}
              onChangeText={(t) => setPan(t.toUpperCase().slice(0, 10))}
              editable={editable}
              autoCapitalize="characters"
              style={[styles.input, !editable && styles.inputDisabled]}
              placeholder="ABCDE1234F"
              placeholderTextColor={colors.textMuted}
            />
          </View>

          <Text style={[styles.sectionLabel, { marginTop: 16 }]}>DOCUMENTS</Text>
          <Text style={styles.docHint}>Take clear, well-lit photos. Files are kept private and used only for verification.</Text>

          {SLOTS.map((slot) => {
            const uri = images[slot.key];
            return (
              <View key={slot.key} style={styles.slot}>
                <View style={styles.slotHeader}>
                  <View style={styles.slotIcon}><Feather name={slot.icon} size={16} color={colors.primary} /></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.slotTitle}>{slot.title}</Text>
                    <Text style={styles.slotSub}>{slot.subtitle}</Text>
                  </View>
                  {uri ? (
                    <View style={styles.slotBadge}><Feather name="check" size={12} color="#fff" /></View>
                  ) : null}
                </View>

                {uri ? (
                  <View style={styles.previewRow}>
                    <TouchableOpacity onPress={() => setPreview(uri)} style={styles.thumbWrap} testID={`kyc-img-${slot.key}-preview`}>
                      <Image source={{ uri }} style={styles.thumb} resizeMode="cover" />
                    </TouchableOpacity>
                    {editable && (
                      <View style={{ flex: 1, gap: 8 }}>
                        <TouchableOpacity onPress={() => openSourcePicker(slot.key)} style={styles.smallBtn} testID={`kyc-img-${slot.key}-replace`}>
                          <Feather name="refresh-ccw" size={14} color={colors.textMain} />
                          <Text style={styles.smallBtnText}>Replace</Text>
                        </TouchableOpacity>
                        <TouchableOpacity onPress={() => removeImage(slot.key)} style={[styles.smallBtn, { backgroundColor: "#FCE9E5" }]} testID={`kyc-img-${slot.key}-remove`}>
                          <Feather name="trash-2" size={14} color="#B3261E" />
                          <Text style={[styles.smallBtnText, { color: "#B3261E" }]}>Remove</Text>
                        </TouchableOpacity>
                      </View>
                    )}
                  </View>
                ) : editable ? (
                  <TouchableOpacity onPress={() => openSourcePicker(slot.key)} style={styles.uploadBox} testID={`kyc-img-${slot.key}-upload`}>
                    <Feather name="upload" size={18} color={colors.primary} />
                    <Text style={styles.uploadText}>Upload image</Text>
                    <Text style={styles.uploadHint}>Camera or photo library</Text>
                  </TouchableOpacity>
                ) : (
                  <View style={[styles.uploadBox, { opacity: 0.6 }]}>
                    <Feather name="lock" size={16} color={colors.textMuted} />
                    <Text style={[styles.uploadText, { color: colors.textMuted }]}>No file</Text>
                  </View>
                )}
              </View>
            );
          })}

          {msg ? <Text style={[styles.msg, { color: msg.includes("submit") ? colors.success : "#B3261E" }]} testID="kyc-msg">{msg}</Text> : null}

          {editable && (
            <TouchableOpacity
              onPress={onSubmit}
              disabled={submitting || !fullName || aadhaar.length !== 12 || pan.length !== 10}
              style={[styles.submitBtn, (submitting || !fullName || aadhaar.length !== 12 || pan.length !== 10) && { opacity: 0.5 }]}
              testID="kyc-submit"
            >
              {submitting ? <ActivityIndicator color={colors.primaryFg} /> : (
                <>
                  <Feather name="shield" size={16} color={colors.primaryFg} />
                  <Text style={styles.submitBtnText}>Submit for review</Text>
                </>
              )}
            </TouchableOpacity>
          )}

          <Text style={styles.note}>
            Your information is encrypted and used only for verification compliance. We do not share details with third parties.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>

      {/* Preview modal */}
      <Modal visible={!!preview} transparent animationType="fade" onRequestClose={() => setPreview(null)}>
        <View style={styles.previewOverlay}>
          <TouchableOpacity style={styles.previewClose} onPress={() => setPreview(null)} testID="kyc-preview-close">
            <Feather name="x" size={22} color="#fff" />
          </TouchableOpacity>
          {preview ? <Image source={{ uri: preview }} style={styles.previewImg} resizeMode="contain" /> : null}
        </View>
      </Modal>

      {/* Android source sheet */}
      <Modal visible={!!pickerFor} transparent animationType="slide" onRequestClose={() => setPickerFor(null)}>
        <View style={styles.sheetOverlay}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>Add photo</Text>
            <TouchableOpacity
              onPress={() => { const k = pickerFor; setPickerFor(null); if (k) choose(k, "camera"); }}
              style={styles.sheetBtn}
              testID="kyc-sheet-camera"
            >
              <Feather name="camera" size={18} color={colors.textMain} />
              <Text style={styles.sheetBtnText}>Take photo</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => { const k = pickerFor; setPickerFor(null); if (k) choose(k, "library"); }}
              style={styles.sheetBtn}
              testID="kyc-sheet-library"
            >
              <Feather name="image" size={18} color={colors.textMain} />
              <Text style={styles.sheetBtnText}>Choose from library</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => setPickerFor(null)} style={[styles.sheetBtn, { justifyContent: "center" }]}>
              <Text style={[styles.sheetBtnText, { color: colors.textMuted }]}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  statusCard: { flexDirection: "row", alignItems: "center", gap: 14, padding: 16, borderRadius: radii.card, borderWidth: 2, backgroundColor: colors.surface, marginBottom: 24 },
  statusIcon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  statusTitle: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  statusBody: { fontSize: 12, color: colors.textMuted, marginTop: 4 },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  field: { marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 14, fontSize: 15, color: colors.textMain },
  inputDisabled: { backgroundColor: colors.surfaceMuted, color: colors.textMuted },
  docHint: { fontSize: 12, color: colors.textMuted, marginBottom: 12, lineHeight: 18 },
  slot: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 12 },
  slotHeader: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  slotIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  slotTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  slotSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  slotBadge: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.success, alignItems: "center", justifyContent: "center" },
  uploadBox: { borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, borderRadius: radii.input, paddingVertical: 22, alignItems: "center", justifyContent: "center", gap: 4 },
  uploadText: { fontSize: 14, fontWeight: "700", color: colors.primary },
  uploadHint: { fontSize: 11, color: colors.textMuted },
  previewRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  thumbWrap: { width: 96, height: 64, borderRadius: 10, overflow: "hidden", backgroundColor: colors.surfaceMuted },
  thumb: { width: "100%", height: "100%" },
  smallBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surfaceMuted, paddingHorizontal: 12, paddingVertical: 10, borderRadius: radii.button, justifyContent: "center" },
  smallBtnText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  msg: { fontSize: 13, marginTop: 4, marginBottom: 8, textAlign: "center" },
  submitBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.primary, paddingVertical: 16, borderRadius: radii.button, marginTop: 8 },
  submitBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
  note: { fontSize: 11, color: colors.textMuted, marginTop: 16, textAlign: "center", lineHeight: 16 },
  previewOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.92)", alignItems: "center", justifyContent: "center" },
  previewImg: { width: "100%", height: "100%" },
  previewClose: { position: "absolute", top: 50, right: 20, width: 40, height: 40, borderRadius: 20, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", zIndex: 5 },
  sheetOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24, paddingBottom: 36, gap: 8 },
  sheetTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain, marginBottom: 6 },
  sheetBtn: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 14, paddingHorizontal: 16, backgroundColor: colors.surfaceMuted, borderRadius: radii.button },
  sheetBtnText: { fontSize: 15, fontWeight: "700", color: colors.textMain },
});
