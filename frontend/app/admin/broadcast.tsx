/**
 * Admin → Broadcast Announcement
 *
 * Super-admin-only screen to compose a one-way Slangcart announcement that
 * fans out to every approved user as both:
 *   • A pinned message in the user's "Slangcart Announcements" thread
 *     (chat list — the thread is automatically surfaced because the super
 *     admin is a participant).
 *   • A native push notification (delivered via the Emergent push relay
 *     once the app is built with google-services.json and EMERGENT_PUSH_KEY).
 *
 * Composer supports text + image (base64 / HTTPS link) + tap-to-open link.
 * Past broadcasts are listed below with delivered count so the admin can
 * see history at a glance.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, Alert,
  ActivityIndicator, Image, Platform, KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

type Audience = "all" | "providers" | "vendors" | "users";

type Broadcast = {
  id: string;
  title: string;
  message: string;
  image_data_url?: string;
  link_url?: string;
  audience: Audience;
  sent_by_name?: string;
  recipient_count: number;
  created_at: string;
};

const AUDIENCES: { key: Audience; label: string; hint: string }[] = [
  { key: "all",       label: "Everyone",        hint: "All approved users" },
  { key: "users",     label: "Network users",   hint: "Excludes vendors + providers" },
  { key: "providers", label: "Service providers", hint: "Approved providers only" },
  { key: "vendors",   label: "Vendors",         hint: "Approved vendors only" },
];

export default function AdminBroadcastScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuperAdmin = ((user as any)?.admin_role || "super_admin") === "super_admin";

  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const [audience, setAudience] = useState<Audience>("all");
  const [sending, setSending] = useState(false);
  const [testing, setTesting] = useState(false);
  const [history, setHistory] = useState<Broadcast[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);

  // Push self-test — one notification to the admin's own devices.
  const onTestPush = async () => {
    setTesting(true);
    try {
      const { data } = await api.post<{
        ok: boolean; relay: string; key_configured: boolean; hint: string;
        device_registration?: { status?: string; platform?: string; at?: string } | null;
      }>("/push/test", {
        title: "Slangcart test",
        message: "Push notifications are working on this device. 🎉",
      });
      const lines = [
        data.hint,
        "",
        `Relay: ${data.relay}`,
        `Push key on server: ${data.key_configured ? "live" : "not set yet"}`,
        `This account's device: ${data.device_registration?.status || "never registered"}`,
      ];
      Alert.alert(data.ok ? "Test sent" : "Test could not be delivered", lines.join("\n"));
    } catch (e) {
      Alert.alert("Couldn't send the test", formatApiError(e));
    } finally { setTesting(false); }
  };

  // Redirect non-super-admins back to the admin landing — defence in depth
  // (the API also enforces this).
  useEffect(() => {
    if (user && !isSuperAdmin) router.replace("/admin/home" as any);
  }, [user, isSuperAdmin, router]);

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const { data } = await api.get<{ broadcasts: Broadcast[] }>("/admin/broadcasts");
      setHistory(data.broadcasts || []);
    } catch (e) {
      // Non-fatal — just leave history empty.
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => { loadHistory(); }, []);

  const pickImage = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (perm.status !== "granted") {
        Alert.alert("Permission needed", "Photo library access is needed to attach an image.");
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.7,
        base64: true,
        allowsEditing: false,
      });
      if (result.canceled) return;
      const a = result.assets?.[0];
      if (!a?.base64) return;
      const mime = a.mimeType || "image/jpeg";
      setImageDataUrl(`data:${mime};base64,${a.base64}`);
    } catch (_e: any) {
      Alert.alert("Couldn't attach image", _e?.message || "Try again.");
    }
  };

  const onSend = () => {
    if (!title.trim()) {
      Alert.alert("Title required", "Add a short headline so users know what to expect.");
      return;
    }
    if (!message.trim()) {
      Alert.alert("Message required", "Compose at least one line of content.");
      return;
    }
    const aud = AUDIENCES.find((a) => a.key === audience);
    Alert.alert(
      "Send broadcast?",
      `This will deliver to ${aud?.label} as a push notification and a pinned message in their chat. Continue?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Send",
          style: "destructive",
          onPress: async () => {
            setSending(true);
            try {
              const payload: any = {
                title: title.trim(),
                message: message.trim(),
                audience,
              };
              if (linkUrl.trim()) payload.link_url = linkUrl.trim();
              if (imageDataUrl) payload.image_data_url = imageDataUrl;
              await api.post("/admin/broadcasts", payload);
              setTitle(""); setMessage(""); setLinkUrl(""); setImageDataUrl(null);
              await loadHistory();
              Alert.alert("Broadcast sent", "Your announcement is on its way.");
            } catch (e) {
              Alert.alert("Couldn't send", formatApiError(e));
            } finally {
              setSending(false);
            }
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>      <View style={styles.headerBar}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="broadcast-back">
          <Feather name="arrow-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Broadcast</Text>
          <Text style={styles.subtitle}>One-way announcement to every Slangcart user</Text>
        </View>
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">

          <Text style={styles.label}>Audience</Text>
          <View style={styles.audienceRow}>
            {AUDIENCES.map((a) => {
              const sel = audience === a.key;
              return (
                <TouchableOpacity
                  key={a.key}
                  onPress={() => setAudience(a.key)}
                  style={[styles.audiencePill, sel && styles.audiencePillActive]}
                  testID={`broadcast-aud-${a.key}`}
                >
                  <Text style={[styles.audienceLabel, sel && styles.audienceLabelActive]}>{a.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
          <Text style={styles.audienceHint}>{AUDIENCES.find((a) => a.key === audience)?.hint}</Text>

          <Text style={styles.label}>Title</Text>
          <TextInput
            style={styles.input}
            value={title}
            onChangeText={setTitle}
            placeholder="e.g. New refund policy live now"
            placeholderTextColor={colors.textMuted}
            maxLength={120}
            testID="broadcast-title"
          />

          <Text style={styles.label}>Message</Text>
          <TextInput
            style={[styles.input, styles.textarea]}
            value={message}
            onChangeText={setMessage}
            placeholder="Write the full announcement — supports multi-line."
            placeholderTextColor={colors.textMuted}
            multiline
            maxLength={2000}
            testID="broadcast-message"
          />
          <Text style={styles.counter}>{message.length}/2000</Text>

          <Text style={styles.label}>Tap-to-open link (optional)</Text>
          <TextInput
            style={styles.input}
            value={linkUrl}
            onChangeText={setLinkUrl}
            placeholder="https://… or /admin/route"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            testID="broadcast-link"
          />

          <Text style={styles.label}>Image (optional)</Text>
          {imageDataUrl ? (
            <View style={styles.imageWrap}>
              <Image source={{ uri: imageDataUrl }} style={styles.imagePreview} />
              <TouchableOpacity onPress={() => setImageDataUrl(null)} style={styles.imageRemove} testID="broadcast-image-remove">
                <Feather name="x" size={18} color="#fff" />
              </TouchableOpacity>
            </View>
          ) : (
            <TouchableOpacity onPress={pickImage} style={styles.imagePicker} testID="broadcast-image-pick">
              <Feather name="image" size={20} color={colors.primary} />
              <Text style={styles.imagePickerLabel}>Attach image</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity
            onPress={onSend}
            disabled={sending}
            style={[styles.sendBtn, sending && { opacity: 0.6 }]}
            testID="broadcast-send"
          >
            {sending ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Feather name="send" size={18} color="#fff" />
                <Text style={styles.sendBtnLabel}>Send announcement</Text>
              </>
            )}
          </TouchableOpacity>

          <View style={styles.divider} />

          {/* Jun 2026 — Push self-test. Sends ONE notification to the admin's
              own devices so they can confirm push works after publishing a
              build (it can't work in Expo Go / the web preview). */}
          <View style={styles.testBox}>
            <Text style={styles.testTitle}>Test push notification</Text>
            <Text style={styles.testHint}>
              Sends a single notification to your own phone. Works only in a
              published iOS / Android build — not in Expo Go or the web preview.
            </Text>
            <TouchableOpacity
              onPress={onTestPush}
              disabled={testing}
              style={[styles.testBtn, testing && { opacity: 0.6 }]}
              testID="broadcast-test-push"
            >
              {testing
                ? <ActivityIndicator color={colors.primary} size="small" />
                : <Feather name="bell" size={16} color={colors.primary} />}
              <Text style={styles.testBtnLabel}>Send test to my phone</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.divider} />

          <Text style={styles.historyHeader}>Past announcements</Text>
          {historyLoading ? (
            <ActivityIndicator color={colors.primary} style={{ marginTop: 16 }} />
          ) : history.length === 0 ? (
            <Text style={styles.historyEmpty}>No broadcasts sent yet.</Text>
          ) : (
            history.map((b) => (
              <View key={b.id} style={styles.historyCard} testID={`broadcast-history-${b.id}`}>
                <View style={styles.historyTop}>
                  <Text style={styles.historyTitle} numberOfLines={1}>{b.title}</Text>
                  <Text style={styles.historyCount}>{b.recipient_count}</Text>
                </View>
                <Text style={styles.historyMsg} numberOfLines={3}>{b.message}</Text>
                <View style={styles.historyBottom}>
                  <Text style={styles.historyMeta}>
                    {new Date(b.created_at).toLocaleString()} · {b.audience}
                  </Text>
                </View>
              </View>
            ))
          )}
          <View style={{ height: 32 }} />
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  headerBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 20 },
  h1: { fontSize: 22, fontWeight: "700", color: colors.textMain },
  subtitle: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  scroll: { padding: spacing.screen, paddingBottom: 48 },
  label: { fontSize: 13, fontWeight: "600", color: colors.textMain, marginTop: 16, marginBottom: 8 },
  audienceRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  audiencePill: {
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 20, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  audiencePillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  audienceLabel: { fontSize: 13, color: colors.textMain, fontWeight: "500" },
  audienceLabelActive: { color: "#fff" },
  audienceHint: { fontSize: 12, color: colors.textMuted, marginTop: 6 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radii.card,
    paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: colors.textMain,
    backgroundColor: colors.surface,
  },
  textarea: { minHeight: 110, textAlignVertical: "top" },
  counter: { fontSize: 11, color: colors.textMuted, marginTop: 4, textAlign: "right" },
  imagePicker: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 14, paddingHorizontal: 16,
    borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
    borderStyle: "dashed", backgroundColor: colors.surface,
  },
  imagePickerLabel: { fontSize: 14, color: colors.primary, fontWeight: "600" },
  imageWrap: { position: "relative", borderRadius: radii.card, overflow: "hidden" },
  imagePreview: { width: "100%", aspectRatio: 16 / 9, backgroundColor: colors.surfaceMuted },
  imageRemove: {
    position: "absolute", top: 8, right: 8,
    backgroundColor: "rgba(0,0,0,0.6)", borderRadius: 16,
    width: 32, height: 32, alignItems: "center", justifyContent: "center",
  },
  sendBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10,
    marginTop: 24, paddingVertical: 14, borderRadius: radii.card,
    backgroundColor: colors.primary,
  },
  sendBtnLabel: { color: "#fff", fontWeight: "700", fontSize: 15 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 28 },
  testBox: { backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 14 },
  testTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  testHint: { fontSize: 12, color: colors.textMuted, lineHeight: 17, marginTop: 4, marginBottom: 12 },
  testBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    minHeight: 46, borderRadius: 12, borderWidth: 1,
    borderColor: colors.primary, backgroundColor: colors.primary + "12",
  },
  testBtnLabel: { fontSize: 13.5, fontWeight: "800", color: colors.primary },

  historyHeader: { fontSize: 15, fontWeight: "700", color: colors.textMain },
  historyEmpty: { fontSize: 13, color: colors.textMuted, marginTop: 8 },
  historyCard: {
    marginTop: 12, padding: 14,
    borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  historyTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  historyTitle: { flex: 1, fontWeight: "700", color: colors.textMain, fontSize: 14 },
  historyCount: {
    fontSize: 12, color: colors.primary, fontWeight: "700",
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 12,
    backgroundColor: colors.brand100,
  },
  historyMsg: { fontSize: 13, color: colors.textMuted, marginTop: 6 },
  historyBottom: { marginTop: 8 },
  historyMeta: { fontSize: 11, color: colors.textMuted },
});
