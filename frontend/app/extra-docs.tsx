import { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Image, Modal, Platform, Alert, ActionSheetIOS, KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../src/api";
import { colors, radii, spacing } from "../src/theme";
import { pickFromLibrary, takePhoto } from "../src/imagePick";

type Slot = {
  key: "cibil_report" | "bank_statement" | "income_proof" | "other";
  title: string;
  subtitle: string;
  icon: keyof typeof Feather.glyphMap;
};

const SLOTS: Slot[] = [
  { key: "cibil_report", title: "CIBIL Report", subtitle: "Recent CIBIL credit report (image or PDF screenshot)", icon: "trending-up" },
  { key: "bank_statement", title: "Bank Statement", subtitle: "Last 3 months bank statement", icon: "credit-card" },
  { key: "income_proof", title: "Income Proof", subtitle: "Salary slip, ITR, or income certificate", icon: "file-text" },
  { key: "other", title: "Other Document", subtitle: "Anything else admin requested (optional)", icon: "paperclip" },
];

type Status = {
  approval_status: string | null;
  reject_category: string | null;
  reject_reason: string | null;
  extra_docs: {
    cibil_report?: string | null;
    bank_statement?: string | null;
    income_proof?: string | null;
    other?: string | null;
    submitted_at?: string | null;
  };
};

export default function ExtraDocs() {
  const router = useRouter();
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [images, setImages] = useState<{ [k in Slot["key"]]?: string }>({});
  const [preview, setPreview] = useState<string | null>(null);
  const [pickerFor, setPickerFor] = useState<Slot["key"] | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Status>("/users/me/additional-docs");
      setStatus(data);
      setImages({
        cibil_report: data.extra_docs?.cibil_report || undefined,
        bank_statement: data.extra_docs?.bank_statement || undefined,
        income_proof: data.extra_docs?.income_proof || undefined,
        other: data.extra_docs?.other || undefined,
      });
    } catch {}
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const choose = async (slot: Slot["key"], source: "camera" | "library") => {
    try {
      const b64 = source === "camera" ? await takePhoto() : await pickFromLibrary();
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

  const onSubmit = async () => {
    const isNew = (s: string | undefined) => !!s && s.startsWith("data:");
    const newDocs = {
      cibil_report: isNew(images.cibil_report) ? images.cibil_report : undefined,
      bank_statement: isNew(images.bank_statement) ? images.bank_statement : undefined,
      income_proof: isNew(images.income_proof) ? images.income_proof : undefined,
      other: isNew(images.other) ? images.other : undefined,
    };
    if (!newDocs.cibil_report && !newDocs.bank_statement && !newDocs.income_proof && !newDocs.other) {
      Alert.alert("Add documents", "Please pick at least one document to submit.");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/users/me/additional-docs", newDocs);
      await load();
      Alert.alert("Submitted", "Your documents have been re-submitted for admin review.");
    } catch (e) {
      Alert.alert("Submit failed", formatApiError(e));
    } finally { setSubmitting(false); }
  };

  if (loading || !status) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  const isRejected = status.approval_status === "rejected";
  const isPending = status.approval_status === "pending";
  const isApproved = status.approval_status === "approved";

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>Additional documents</Text>
            <View style={{ width: 40 }} />
          </View>

          <View style={[styles.statusCard, {
            borderColor: isRejected ? "#B3261E" : isApproved ? colors.success : colors.warning,
            backgroundColor: isRejected ? "#FCE9E5" : isApproved ? "#E6F4EE" : "#FFF4E5",
          }]}>
            <Feather
              name={isRejected ? "alert-triangle" : isApproved ? "check-circle" : "clock"}
              size={20}
              color={isRejected ? "#B3261E" : isApproved ? colors.success : colors.warning}
            />
            <View style={{ flex: 1 }}>
              <Text style={styles.statusTitle}>
                {isRejected ? "Approval rejected" : isApproved ? "Account approved" : "Awaiting review"}
              </Text>
              <Text style={styles.statusSub}>
                {isRejected
                  ? `Reason: ${status.reject_reason || "Please upload additional documents."}`
                  : isApproved
                  ? "You have been approved. No further action needed."
                  : "Your documents are under admin review."}
              </Text>
            </View>
          </View>

          <Text style={styles.intro}>
            Upload the documents below to help us re-verify your account. After submission your account
            moves back to the review queue.
          </Text>

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
                  {uri ? <View style={styles.slotBadge}><Feather name="check" size={12} color="#fff" /></View> : null}
                </View>

                {uri ? (
                  <View style={styles.previewRow}>
                    <TouchableOpacity onPress={() => setPreview(uri)} style={styles.thumbWrap}>
                      <Image source={{ uri }} style={styles.thumb} resizeMode="cover" />
                    </TouchableOpacity>
                    <View style={{ flex: 1, gap: 8 }}>
                      <TouchableOpacity onPress={() => openSourcePicker(slot.key)} style={styles.smallBtn}>
                        <Feather name="refresh-ccw" size={14} color={colors.textMain} />
                        <Text style={styles.smallBtnText}>Replace</Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        onPress={() => setImages((p) => ({ ...p, [slot.key]: undefined }))}
                        style={[styles.smallBtn, { backgroundColor: "#FCE9E5" }]}
                      >
                        <Feather name="trash-2" size={14} color="#B3261E" />
                        <Text style={[styles.smallBtnText, { color: "#B3261E" }]}>Remove</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                ) : (
                  <TouchableOpacity onPress={() => openSourcePicker(slot.key)} style={styles.uploadBox}>
                    <Feather name="upload" size={18} color={colors.primary} />
                    <Text style={styles.uploadText}>Upload</Text>
                    <Text style={styles.uploadHint}>Camera or photo library</Text>
                  </TouchableOpacity>
                )}
              </View>
            );
          })}

          <TouchableOpacity
            onPress={onSubmit}
            disabled={submitting || isApproved}
            style={[styles.submitBtn, (submitting || isApproved) && { opacity: 0.5 }]}
            testID="extra-docs-submit"
          >
            {submitting ? <ActivityIndicator color={colors.primaryFg} /> : (
              <>
                <Feather name="send" size={16} color={colors.primaryFg} />
                <Text style={styles.submitBtnText}>{isPending ? "Update submission" : isRejected ? "Re-submit for review" : "Submit"}</Text>
              </>
            )}
          </TouchableOpacity>

          <Text style={styles.note}>
            All documents are encrypted and used only for compliance verification. We never share them
            with third parties.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>

      {/* Preview modal */}
      <Modal visible={!!preview} transparent animationType="fade" onRequestClose={() => setPreview(null)}>
        <View style={styles.previewOverlay}>
          <TouchableOpacity style={styles.previewClose} onPress={() => setPreview(null)}>
            <Feather name="x" size={22} color="#fff" />
          </TouchableOpacity>
          {preview ? <Image source={{ uri: preview }} style={styles.previewImg} resizeMode="contain" /> : null}
        </View>
      </Modal>

      {/* Android source sheet */}
      <Modal visible={!!pickerFor} transparent animationType="slide" onRequestClose={() => setPickerFor(null)}>
        <View style={styles.sheetOverlay}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>Add document</Text>
            <TouchableOpacity onPress={() => { const k = pickerFor; setPickerFor(null); if (k) choose(k, "camera"); }} style={styles.sheetBtn}>
              <Feather name="camera" size={18} color={colors.textMain} />
              <Text style={styles.sheetBtnText}>Take photo</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => { const k = pickerFor; setPickerFor(null); if (k) choose(k, "library"); }} style={styles.sheetBtn}>
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
  statusCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 14, borderWidth: 1, marginBottom: 16 },
  statusTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  statusSub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  intro: { fontSize: 12, color: colors.textMuted, marginBottom: 16, lineHeight: 18 },
  slot: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14, marginBottom: 12 },
  slotHeader: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  slotIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" },
  slotTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  slotSub: { fontSize: 11, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  slotBadge: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.success, alignItems: "center", justifyContent: "center" },
  uploadBox: { borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, borderRadius: radii.input, paddingVertical: 22, alignItems: "center", justifyContent: "center", gap: 4 },
  uploadText: { fontSize: 14, fontWeight: "700", color: colors.primary },
  uploadHint: { fontSize: 11, color: colors.textMuted },
  previewRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  thumbWrap: { width: 96, height: 64, borderRadius: 10, overflow: "hidden", backgroundColor: colors.surfaceMuted },
  thumb: { width: "100%", height: "100%" },
  smallBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surfaceMuted, paddingHorizontal: 12, paddingVertical: 10, borderRadius: radii.button, justifyContent: "center" },
  smallBtnText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
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
