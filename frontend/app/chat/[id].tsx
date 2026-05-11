// Chat conversation screen — 1:1 messaging with text + image, edit (15min,
// only if not yet replied), soft-delete, real-time updates via WebSocket.
import { useEffect, useState, useCallback, useRef } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, KeyboardAvoidingView,
  Platform, Image, Alert, ActivityIndicator, Pressable, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";
import { useChatSocket } from "../../src/use-chat-socket";

type Message = {
  id: string;
  thread_id: string;
  sender_id: string;
  text: string;
  image_data_url?: string;
  deleted: boolean;
  edited: boolean;
  created_at: string;
  updated_at: string;
};

type Thread = { id: string; other: { id: string; name: string; referral_code: string; avatar?: string }; is_downline: boolean };

const EDIT_WINDOW_MIN = 15;

export default function ChatThreadScreen() {
  const router = useRouter();
  const { id: threadId } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const myId = user?.id || "";
  const [messages, setMessages] = useState<Message[]>([]);
  const [thread, setThread] = useState<Thread | null>(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [picking, setPicking] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<Message | null>(null);
  const scrollRef = useRef<ScrollView | null>(null);

  const load = useCallback(async () => {
    if (!threadId) return;
    try {
      const [tRes, mRes] = await Promise.all([
        api.get<{ threads: Thread[] }>("/chat/threads"),
        api.get<{ messages: Message[] }>(`/chat/${threadId}/messages`),
      ]);
      const list = tRes.data?.threads || [];
      const t = list.find((x) => x.id === threadId) || null;
      setThread(t);
      setMessages(mRes.data?.messages || []);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: false }), 50);
    } catch (e) { /* swallow */ }
    finally { setLoading(false); }
  }, [threadId]);

  useEffect(() => { load(); }, [load]);

  // Realtime updates
  useChatSocket((ev) => {
    if (!threadId) return;
    if (ev.type === "message.new" && ev.thread_id === threadId) {
      setMessages((prev) => [...prev.filter((m) => m.id !== ev.message.id), ev.message]);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
      // Mark as read silently
      api.get(`/chat/${threadId}/messages`, { params: { limit: 1 } }).catch(() => {});
    } else if (ev.type === "message.edited" && ev.thread_id === threadId) {
      setMessages((prev) => prev.map((m) => m.id === ev.message.id ? ev.message : m));
    } else if (ev.type === "message.deleted" && ev.thread_id === threadId) {
      setMessages((prev) => prev.map((m) => m.id === ev.message_id ? { ...m, deleted: true, text: "", image_data_url: "" } : m));
    }
  });

  const isMine = (m: Message) => m.sender_id === myId;

  const canEdit = (m: Message) => {
    if (!isMine(m) || m.deleted) return false;
    const age = Date.now() - new Date(m.created_at).getTime();
    if (age > EDIT_WINDOW_MIN * 60 * 1000) return false;
    // Has the other person replied AFTER this?
    const idx = messages.findIndex((x) => x.id === m.id);
    for (let i = idx + 1; i < messages.length; i++) {
      if (!isMine(messages[i]) && !messages[i].deleted) return false;
    }
    return true;
  };

  const onSend = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      if (editingId) {
        await api.patch(`/chat/messages/${editingId}`, { text });
        setEditingId(null);
      } else {
        await api.post(`/chat/${threadId}/messages`, { text });
      }
      setDraft("");
      // Optimistic local update will happen via WS event
    } catch (e) { Alert.alert("Send failed", formatApiError(e)); }
    finally { setSending(false); }
  };

  const onPickImage = async () => {
    setPicking(true);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) { Alert.alert("Permission needed", "Please allow photo library access."); return; }
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 0.7, allowsEditing: false,
      });
      if (!r.canceled && r.assets?.[0]?.uri) {
        const m = await ImageManipulator.manipulateAsync(
          r.assets[0].uri,
          [{ resize: { width: 1200 } }],
          { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true },
        );
        if (m.base64) {
          await api.post(`/chat/${threadId}/messages`, {
            text: "",
            image_data_url: `data:image/jpeg;base64,${m.base64}`,
          });
        }
      }
    } catch (e) { Alert.alert("Image send failed", formatApiError(e)); }
    finally { setPicking(false); }
  };

  const onDelete = async (m: Message) => {
    setActionMessage(null);
    try {
      await api.delete(`/chat/messages/${m.id}`);
    } catch (e) { Alert.alert("Delete failed", formatApiError(e)); }
  };

  const onStartEdit = (m: Message) => {
    setActionMessage(null);
    setEditingId(m.id);
    setDraft(m.text);
  };

  if (!threadId) return null;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <View style={styles.avatarSmall}>
          <Text style={styles.avatarSmallText}>{(thread?.other.name || "?").substring(0, 1).toUpperCase()}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={styles.headerName} numberOfLines={1}>{thread?.other.name || "Chat"}</Text>
            {thread?.is_downline ? <View style={styles.downlineBadge}><Text style={styles.downlineBadgeText}>DOWNLINE</Text></View> : null}
          </View>
          <Text style={styles.headerSub}>#{thread?.other.referral_code || ""}</Text>
        </View>
      </View>

      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={20}>
        {loading ? (
          <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
        ) : (
          <ScrollView
            ref={scrollRef}
            contentContainerStyle={{ padding: spacing.screen, gap: 6, paddingBottom: 12 }}
            onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: false })}
          >
            {messages.length === 0 ? (
              <View style={styles.emptyState}>
                <Feather name="message-square" size={26} color={colors.textMuted} />
                <Text style={styles.emptyStateText}>Say hi to start the conversation 👋</Text>
              </View>
            ) : messages.map((m, idx) => {
              const mine = isMine(m);
              const prev = messages[idx - 1];
              const showAvatar = !mine && (!prev || prev.sender_id !== m.sender_id);
              return (
                <Pressable key={m.id} onLongPress={() => { if (mine && !m.deleted) setActionMessage(m); }} style={{ flexDirection: "row", alignItems: "flex-end", justifyContent: mine ? "flex-end" : "flex-start", gap: 6 }}>
                  {!mine ? (
                    <View style={[styles.avatarBubble, !showAvatar && { opacity: 0 }]}>
                      <Text style={styles.avatarBubbleText}>{(thread?.other.name || "?").substring(0, 1).toUpperCase()}</Text>
                    </View>
                  ) : null}
                  <View style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleTheirs, m.deleted && styles.bubbleDeleted]}>
                    {m.deleted ? (
                      <Text style={styles.deletedText}>Message deleted</Text>
                    ) : (
                      <>
                        {m.image_data_url ? (
                          <Image source={{ uri: m.image_data_url }} style={styles.bubbleImg} resizeMode="cover" />
                        ) : null}
                        {m.text ? <Text style={[styles.bubbleText, mine ? { color: colors.primaryFg } : { color: colors.textMain }]}>{m.text}</Text> : null}
                        <View style={styles.bubbleFooter}>
                          {m.edited ? <Text style={[styles.bubbleMeta, mine ? { color: "rgba(255,255,255,0.7)" } : null]}>edited · </Text> : null}
                          <Text style={[styles.bubbleMeta, mine ? { color: "rgba(255,255,255,0.7)" } : null]}>{formatTime(m.created_at)}</Text>
                        </View>
                      </>
                    )}
                  </View>
                </Pressable>
              );
            })}
          </ScrollView>
        )}

        {/* Editing banner */}
        {editingId ? (
          <View style={styles.editingBanner}>
            <Feather name="edit-2" size={12} color={colors.primary} />
            <Text style={styles.editingText}>Editing message</Text>
            <TouchableOpacity onPress={() => { setEditingId(null); setDraft(""); }} style={{ marginLeft: "auto" }}>
              <Feather name="x" size={16} color={colors.textMuted} />
            </TouchableOpacity>
          </View>
        ) : null}

        {/* Composer */}
        <View style={styles.composer}>
          <TouchableOpacity onPress={onPickImage} disabled={picking || !!editingId} style={[styles.composerIcon, (picking || !!editingId) && { opacity: 0.4 }]} testID="composer-image">
            {picking ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="image" size={20} color={colors.primary} />}
          </TouchableOpacity>
          <TextInput
            style={styles.composerInput}
            value={draft}
            onChangeText={setDraft}
            placeholder={editingId ? "Edit your message…" : "Message…"}
            placeholderTextColor={colors.textMuted}
            multiline
            maxLength={4000}
            onSubmitEditing={onSend}
          />
          <TouchableOpacity onPress={onSend} disabled={!draft.trim() || sending} style={[styles.sendBtn, (!draft.trim() || sending) && { opacity: 0.4 }]} testID="composer-send">
            {sending ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <Feather name={editingId ? "check" : "send"} size={18} color={colors.primaryFg} />}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      {/* Action sheet for own messages (edit/delete) */}
      <Modal visible={!!actionMessage} transparent animationType="fade" onRequestClose={() => setActionMessage(null)}>
        <Pressable style={styles.sheetOverlay} onPress={() => setActionMessage(null)}>
          <View style={styles.sheet}>
            <Text style={styles.sheetTitle}>Message options</Text>
            {actionMessage && canEdit(actionMessage) ? (
              <TouchableOpacity onPress={() => onStartEdit(actionMessage)} style={styles.sheetRow}>
                <Feather name="edit-2" size={18} color={colors.textMain} />
                <Text style={styles.sheetRowText}>Edit</Text>
              </TouchableOpacity>
            ) : (
              <View style={styles.sheetRowDisabled}>
                <Feather name="edit-2" size={18} color={colors.textMuted} />
                <Text style={[styles.sheetRowText, { color: colors.textMuted }]}>Edit (15 min window, no reply)</Text>
              </View>
            )}
            <TouchableOpacity onPress={() => actionMessage && onDelete(actionMessage)} style={styles.sheetRow}>
              <Feather name="trash-2" size={18} color="#B91C1C" />
              <Text style={[styles.sheetRowText, { color: "#B91C1C" }]}>Delete</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => setActionMessage(null)} style={[styles.sheetRow, { borderTopWidth: 1, borderTopColor: colors.border }]}>
              <Feather name="x" size={18} color={colors.textMuted} />
              <Text style={[styles.sheetRowText, { color: colors.textMuted }]}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  avatarSmall: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  avatarSmallText: { fontSize: 14, fontWeight: "900", color: colors.primary },
  headerName: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  headerSub: { fontSize: 11, color: colors.textMuted, marginTop: 1 },
  downlineBadge: { backgroundColor: "#DCFCE7", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999 },
  downlineBadgeText: { fontSize: 9, fontWeight: "900", color: "#065F46", letterSpacing: 0.6 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyState: { alignItems: "center", paddingVertical: 40, gap: 6 },
  emptyStateText: { fontSize: 13, color: colors.textMuted },
  bubble: { maxWidth: "78%", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 16, marginVertical: 2 },
  bubbleMine: { backgroundColor: colors.primary, borderBottomRightRadius: 4 },
  bubbleTheirs: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 4 },
  bubbleDeleted: { opacity: 0.7, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, borderStyle: "dashed" },
  bubbleText: { fontSize: 14, lineHeight: 19 },
  deletedText: { fontSize: 12, fontStyle: "italic", color: colors.textMuted },
  bubbleImg: { width: 220, height: 220, borderRadius: 12, marginBottom: 4 },
  bubbleFooter: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", marginTop: 3, gap: 2 },
  bubbleMeta: { fontSize: 9, color: colors.textMuted, letterSpacing: 0.3 },
  avatarBubble: { width: 26, height: 26, borderRadius: 13, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginBottom: 4 },
  avatarBubbleText: { fontSize: 11, fontWeight: "900", color: colors.primary },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface },
  composerIcon: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  composerInput: { flex: 1, fontSize: 14, color: colors.textMain, backgroundColor: colors.surfaceMuted, borderRadius: 20, paddingHorizontal: 16, paddingVertical: 10, borderWidth: 1, borderColor: colors.border, maxHeight: 100 },
  sendBtn: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: colors.primary },
  editingBanner: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: spacing.screen, paddingVertical: 8, backgroundColor: colors.brand100, borderTopWidth: 1, borderTopColor: colors.border },
  editingText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  sheetOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingVertical: 12, paddingHorizontal: 16, paddingBottom: 24 },
  sheetTitle: { fontSize: 12, fontWeight: "800", letterSpacing: 1.4, color: colors.textMuted, marginBottom: 8, marginLeft: 4 },
  sheetRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12 },
  sheetRowDisabled: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12, opacity: 0.5 },
  sheetRowText: { fontSize: 14, fontWeight: "700", color: colors.textMain },
});
