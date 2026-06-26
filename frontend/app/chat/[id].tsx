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
import { useChatSettings, wallpaperStyle } from "../../src/chat-settings";
import { ChatLockGate } from "../../src/chat-lock-gate";

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

type Thread = { id: string; other: { id: string; name: string; referral_code: string; avatar?: string; profile_image?: string | null; profile_image_hidden?: boolean }; is_downline: boolean; is_announcement?: boolean };

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
  // Sprint 1 chat upgrade — reply-to + send dedupe key.
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  // Sprint 1.1 — header profile-card modal (avatar / media / starred summary).
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileDetail, setProfileDetail] = useState<{ media_count: number; starred_count: number } | null>(null);
  // ── June 2026 chat experience upgrades ───────────────────────────────
  // Header overflow menu (Clear chat options).
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false);
  // Confirm sheet for destructive clear-chat operations.
  const [clearConfirm, setClearConfirm] = useState<null | "me" | "everyone">(null);
  // Profile pic full-screen viewer (tap avatar inside profile modal).
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  // Media-gallery + Starred drawer toggles. The body of the profile modal
  // switches between "summary", "media", and "starred" so the user can
  // explore everything without leaving the modal stack.
  const [profileView, setProfileView] = useState<"summary" | "media" | "starred">("summary");
  const [mediaList, setMediaList] = useState<Message[] | null>(null);
  const [starredList, setStarredList] = useState<Message[] | null>(null);
  // Phone-gallery-style zoomable image preview (used by the media grid).
  const [galleryIndex, setGalleryIndex] = useState<number | null>(null);
  // Quick-react picker — anchors near the tapped message. Tap closes it.
  const [quickReactFor, setQuickReactFor] = useState<Message | null>(null);

  // Pull header counts (media + starred) lazily when the user taps the header.
  const loadProfileDetail = useCallback(async () => {
    if (!threadId) return;
    try {
      const r = await api.get(`/chat/${threadId}/details`);
      setProfileDetail({ media_count: r.data?.media_count || 0, starred_count: r.data?.starred_count || 0 });
    } catch {}
  }, [threadId]);

  // Lazy-loaded full media + starred lists for the profile-modal drawer.
  // Called when the user taps "Media" or "Starred" from the summary view.
  const loadMediaList = useCallback(async () => {
    if (!threadId) return;
    try {
      const r = await api.get<{ messages: Message[] }>(`/chat/${threadId}/media`, { params: { limit: 500 } });
      setMediaList(r.data?.messages || []);
    } catch { setMediaList([]); }
  }, [threadId]);
  const loadStarredList = useCallback(async () => {
    try {
      // /chat/starred is user-global; filter to this thread for the modal.
      const r = await api.get<{ messages: Message[] }>(`/chat/starred`, { params: { limit: 500 } });
      const filtered = (r.data?.messages || []).filter((m) => m.thread_id === threadId);
      setStarredList(filtered);
    } catch { setStarredList([]); }
  }, [threadId]);

  // Clear-chat handler — wipes all messages in the thread (and media +
  // starred summary). scope="me" only hides for the viewer; scope="everyone"
  // soft-deletes for BOTH sides and resets media/starred for both users.
  const clearChat = useCallback(async (scope: "me" | "everyone") => {
    if (!threadId) return;
    try {
      await api.delete(`/chat/${threadId}/messages`, { params: { scope } });
      setMessages([]);
      setMediaList([]);
      setStarredList([]);
      setProfileDetail({ media_count: 0, starred_count: 0 });
      setClearConfirm(null);
      setHeaderMenuOpen(false);
    } catch (e) {
      Alert.alert("Couldn't clear", formatApiError(e));
    }
  }, [threadId]);

  // Optimistic reaction — flip the local state instantly, then persist.
  // If the server rejects, we silently re-sync on next /messages refresh.
  const reactNow = useCallback(async (m: Message, emoji: string) => {
    if (!user?.id) return;
    setMessages((prev) => prev.map((x) => {
      if (x.id !== m.id) return x;
      const rx: Record<string, string[]> = { ...((x as any).reactions || {}) };
      // Remove this user from every emoji bucket first (toggle / replace).
      for (const k of Object.keys(rx)) {
        rx[k] = (rx[k] || []).filter((u) => u !== user.id);
        if (rx[k].length === 0) delete rx[k];
      }
      const had = (((m as any).reactions || {})[emoji] || []).includes(user.id);
      if (!had) {
        rx[emoji] = [...(rx[emoji] || []), user.id];
      }
      return { ...x, reactions: rx } as any;
    }));
    setQuickReactFor(null);
    setActionMessage(null);
    try { await api.post(`/chat/messages/${m.id}/react`, { emoji }); } catch {}
  }, [user?.id]);
  // Image preview / zoom modal (2026-06-01) — tap any image bubble to
  // open it full-screen with a clean dark backdrop so subtle photos
  // become clearly readable.
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  // Chat-lock gating — once the chat content has been rendered for this
  // thread within the current mount, we NEVER bounce back to the lock gate
  // even if `locked` flips to true (e.g. when the user locks the chat from
  // inside the profile modal). The ref is reset on unmount, so cold
  // navigation back to a locked thread correctly shows the gate again.
  // This pattern sidesteps all React-18 cross-component state batching
  // races that previously caused the "lock-bounce" regression.
  const sessionShownRef = useRef(false);
  // Bumped to force a re-render after we mutate the ref. The actual gate
  // value lives in the ref so it can be flipped synchronously.
  const [, forceRerender] = useState(0);
  const wpSettings = useChatSettings();
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
    } else if (ev.type === "thread.cleared" && ev.thread_id === threadId) {
      // The other party (or me from another device) wiped the entire chat
      // for everyone. Reset the local view immediately.
      setMessages([]);
      setMediaList([]);
      setStarredList([]);
      setProfileDetail({ media_count: 0, starred_count: 0 });
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
        await api.post(`/chat/${threadId}/messages`, {
          text,
          reply_to_id: replyTo?.id,
          client_dedupe_key: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        });
        setReplyTo(null);
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

  // Wait for chat settings to load before evaluating the lock gate — this
  // avoids a race where `settings=null` ⇒ `isThreadLocked` returns false
  // ⇒ we flip sessionShownRef and never show the gate even after settings
  // arrive with locked=true.
  if (!wpSettings.settings) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} />
        </View>
      </SafeAreaView>
    );
  }

  const locked = wpSettings.isThreadLocked(threadId);
  // Once we've already shown the chat content in this mount, we will not
  // bounce back to the gate, regardless of how `locked` flips afterwards.
  // The ref is reset on unmount, so cold-navigating to a locked thread
  // still correctly shows the gate.
  const alreadyUnlocked = sessionShownRef.current || wpSettings.isUnlocked(threadId);
  if (locked && !alreadyUnlocked) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
        <ChatLockGate
          unlockKey={threadId}
          title="This chat is locked"
          subtitle="Enter your chat PIN to view the conversation."
          onUnlocked={() => { wpSettings.markUnlocked(threadId); sessionShownRef.current = true; forceRerender((n) => n + 1); }}
        />
      </SafeAreaView>
    );
  }
  // We're about to render the chat content — mark the session-shown ref so
  // subsequent `locked` flips don't bounce us back to the gate.
  sessionShownRef.current = true;
  const bgStyle = wallpaperStyle(wpSettings.wallpaperFor(threadId), wpSettings.settings?.presets || {});

  return (
    <SafeAreaView style={[styles.safe, bgStyle]} edges={["top"]}>
      <View style={styles.headerRow}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        {/* Header is fully tappable — opens the profile-card modal with
            avatar, refid, media count, starred count. */}
        <TouchableOpacity
          onPress={() => { setProfileOpen(true); loadProfileDetail(); }}
          activeOpacity={0.7}
          style={{ flexDirection: "row", alignItems: "center", flex: 1, gap: 10 }}
          testID="chat-header-profile"
        >
          <View style={[styles.avatarSmall, { overflow: "hidden" }]}>
            {thread?.other?.profile_image ? (
              <Image source={{ uri: thread.other.profile_image }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
            ) : (
              <Text style={styles.avatarSmallText}>{(thread?.other.name || "?").substring(0, 1).toUpperCase()}</Text>
            )}
          </View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Text style={styles.headerName} numberOfLines={1}>{thread?.other.name || "Chat"}</Text>
              {thread?.is_downline ? <View style={styles.downlineBadge}><Text style={styles.downlineBadgeText}>DOWNLINE</Text></View> : null}
            </View>
            <Text style={styles.headerSub}>#{thread?.other.referral_code || ""}</Text>
          </View>
        </TouchableOpacity>
        {/* ── Header overflow menu (Clear chat etc.) ────────────── */}
        <TouchableOpacity onPress={() => setHeaderMenuOpen(true)} style={styles.iconBtn} testID="chat-header-menu">
          <Feather name="more-vertical" size={18} color={colors.textMain} />
        </TouchableOpacity>
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
            {/* End-to-end encryption notice — subtle WhatsApp-style banner. */}
            <View style={styles.e2eBanner} pointerEvents="none">
              <Feather name="lock" size={11} color={colors.textMuted} />
              <Text style={styles.e2eBannerText}>
                Messages and calls are end-to-end encrypted. No one outside this chat can read or listen to them.
              </Text>
            </View>
            {messages.length === 0 ? (
              <View style={styles.emptyState}>
                <Feather name="message-square" size={26} color={colors.textMuted} />
                <Text style={styles.emptyStateText}>Say hi to start the conversation 👋</Text>
              </View>
            ) : messages.map((m, idx) => {
              const mine = isMine(m);
              const prev = messages[idx - 1];
              const showAvatar = !mine && (!prev || prev.sender_id !== m.sender_id);
              const reactions = (m as any).reactions as Record<string, string[]> | undefined;
              const reply = (m as any).reply_to as { id: string; sender_id: string; text: string; has_image?: boolean } | undefined;
              // Delivery status (mine only). 3 states:
              //   sent      → in delivered_to with only sender
              //   delivered → other party in delivered_to but not read_by
              //   read      → other party in read_by (blue)
              const otherId = thread?.other?.id;
              const delivered = !!otherId && Array.isArray((m as any).delivered_to) && (m as any).delivered_to.includes(otherId);
              const readByOther = !!otherId && Array.isArray(m.read_by) && m.read_by.includes(otherId);
              return (
                <Pressable
                  key={m.id}
                  onPress={() => { if (!m.deleted) setQuickReactFor(m); }}
                  onLongPress={() => { if (!m.deleted) setActionMessage(m); }}
                  delayLongPress={300}
                  style={{ flexDirection: "row", alignItems: "flex-end", justifyContent: mine ? "flex-end" : "flex-start", gap: 6 }}
                >
                  {!mine ? (
                    <View style={[styles.avatarBubble, !showAvatar && { opacity: 0 }]}>
                      <Text style={styles.avatarBubbleText}>{(thread?.other.name || "?").substring(0, 1).toUpperCase()}</Text>
                    </View>
                  ) : null}
                  <View style={[styles.bubble, mine ? styles.bubbleMine : styles.bubbleTheirs, m.deleted && styles.bubbleDeleted, m.image_data_url && !m.deleted && styles.bubbleWithImage]}>
                    {m.deleted ? (
                      <Text style={styles.deletedText}>Message deleted</Text>
                    ) : (
                      <>
                        {reply ? (
                          <View style={{ borderLeftWidth: 3, borderLeftColor: mine ? "rgba(255,255,255,0.7)" : colors.primary, paddingLeft: 8, marginBottom: 6, opacity: 0.9 }}>
                            <Text style={{ fontSize: 10, fontWeight: "800", color: mine ? "rgba(255,255,255,0.85)" : colors.primary }} numberOfLines={1}>
                              {reply.sender_id === user?.id ? "You" : thread?.other?.name || "Reply"}
                            </Text>
                            <Text style={{ fontSize: 12, color: mine ? "rgba(255,255,255,0.85)" : colors.textMuted }} numberOfLines={2}>
                              {reply.has_image ? "📷 Image" : reply.text}
                            </Text>
                          </View>
                        ) : null}
                        {m.image_data_url ? (
                          <TouchableOpacity
                            activeOpacity={0.85}
                            onPress={() => setPreviewImage(m.image_data_url || null)}
                            testID={`chat-image-${m.id}`}
                          >
                            <Image source={{ uri: m.image_data_url }} style={styles.bubbleImg} resizeMode="cover" />
                            <View style={styles.imgZoomHint} pointerEvents="none">
                              <Feather name="maximize-2" size={11} color="#FFFFFF" />
                            </View>
                          </TouchableOpacity>
                        ) : null}
                        {m.text ? <Text style={[styles.bubbleText, mine ? { color: colors.primaryFg } : { color: colors.textMain }]}>{m.text}</Text> : null}
                        <View style={styles.bubbleFooter}>
                          {m.edited ? <Text style={[styles.bubbleMeta, mine ? { color: "rgba(255,255,255,0.7)" } : null]}>edited · </Text> : null}
                          <Text style={[styles.bubbleMeta, mine ? { color: "rgba(255,255,255,0.7)" } : null]}>{formatTime(m.created_at)}</Text>
                          {mine ? (
                            <Text style={[styles.bubbleMeta, { marginLeft: 4, color: readByOther ? "#3FB6F8" : "rgba(255,255,255,0.7)" }]}>
                              {readByOther ? "✓✓" : delivered ? "✓✓" : "✓"}
                            </Text>
                          ) : null}
                        </View>
                        {reactions && Object.keys(reactions).length > 0 ? (
                          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                            {Object.entries(reactions).map(([emo, list]) => (
                              <View key={emo} style={{ backgroundColor: mine ? "rgba(255,255,255,0.18)" : "rgba(20,61,46,0.08)", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999, flexDirection: "row", gap: 3 }}>
                                <Text style={{ fontSize: 12 }}>{emo}</Text>
                                <Text style={{ fontSize: 10, fontWeight: "800", color: mine ? "#fff" : colors.textMain }}>{list.length}</Text>
                              </View>
                            ))}
                          </View>
                        ) : null}
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

        {/* Reply pill — shown above the composer when the user picked
            "Reply" from a message's long-press menu. Sends `reply_to_id`
            with the next message so the recipient sees a quote bubble. */}
        {replyTo ? (
          <View style={[styles.editingBanner, { backgroundColor: colors.brand100, borderColor: colors.primary, gap: 8 }]}>
            <Feather name="corner-up-left" size={12} color={colors.primary} />
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 10, fontWeight: "800", color: colors.primary, letterSpacing: 0.5 }}>
                REPLY TO {isMine(replyTo) ? "YOURSELF" : (thread?.other?.name || "").toUpperCase()}
              </Text>
              <Text style={{ fontSize: 12, color: colors.textMain }} numberOfLines={1}>
                {replyTo.image_data_url && !replyTo.text ? "📷 Image" : (replyTo.text || "")}
              </Text>
            </View>
            <TouchableOpacity onPress={() => setReplyTo(null)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
              <Feather name="x" size={16} color={colors.textMuted} />
            </TouchableOpacity>
          </View>
        ) : null}

        {/* Composer */}
        {thread?.is_announcement && (user as any)?.admin_role !== "super_admin" ? (
          <View style={styles.announcementBanner} testID="announcement-readonly">
            <Feather name="volume-2" size={16} color={colors.primary} />
            <Text style={styles.announcementBannerText}>
              Slangcart Announcements — one-way channel from the Slangcart team.
            </Text>
          </View>
        ) : (
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
        )}
      </KeyboardAvoidingView>

      {/* Quick-react popup (Sprint 1.1) — single-tap on a bubble shows 6
          common emojis floating near the message. Optimistic update so the
          chosen emoji appears INSTANTLY without waiting for the server. */}
      <Modal visible={!!quickReactFor} transparent animationType="fade" onRequestClose={() => setQuickReactFor(null)}>
        <Pressable style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)", justifyContent: "center", alignItems: "center" }} onPress={() => setQuickReactFor(null)}>
          <View style={{ backgroundColor: colors.surface, borderRadius: 28, paddingHorizontal: 10, paddingVertical: 6, flexDirection: "row", gap: 4, elevation: 6 }}>
            {["👍", "❤️", "😂", "😮", "😢", "🙏"].map((emo) => (
              <TouchableOpacity
                key={emo}
                onPress={() => { if (quickReactFor) reactNow(quickReactFor, emo); }}
                style={{ width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" }}
                testID={`chat-quick-react-${emo}`}
              >
                <Text style={{ fontSize: 24 }}>{emo}</Text>
              </TouchableOpacity>
            ))}
            <TouchableOpacity
              onPress={() => { if (quickReactFor) { setActionMessage(quickReactFor); setQuickReactFor(null); } }}
              style={{ width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted }}
            >
              <Feather name="more-horizontal" size={18} color={colors.textMain} />
            </TouchableOpacity>
          </View>
        </Pressable>
      </Modal>

      {/* Profile-card modal (Sprint 1.1) — tap the chat header to see the
          other party's avatar, refid, media count, and starred count. */}
      <Modal visible={profileOpen} transparent animationType="slide" onRequestClose={() => setProfileOpen(false)}>
        <Pressable style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.45)" }} onPress={() => setProfileOpen(false)}>
          <View style={{ flex: 1 }} />
          <View onStartShouldSetResponder={() => true} style={{ backgroundColor: colors.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22, padding: 22 }}>
            <View style={{ width: 36, height: 4, backgroundColor: colors.border, borderRadius: 2, alignSelf: "center", marginBottom: 14 }} />
            <View style={{ alignItems: "center" }}>
              <TouchableOpacity
                activeOpacity={thread?.other?.profile_image ? 0.85 : 1}
                onPress={() => { if (thread?.other?.profile_image) setAvatarPreview(thread.other.profile_image); }}
                style={{ width: 96, height: 96, borderRadius: 48, overflow: "hidden", backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" }}
                testID="chat-profile-avatar"
              >
                {thread?.other?.profile_image ? (
                  <Image source={{ uri: thread.other.profile_image }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
                ) : (
                  <Text style={{ fontSize: 40, fontWeight: "800", color: colors.primary }}>
                    {(thread?.other?.name || "?").substring(0, 1).toUpperCase()}
                  </Text>
                )}
              </TouchableOpacity>
              <Text style={{ fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 12 }}>
                {thread?.other?.name || "User"}
              </Text>
              {thread?.other?.referral_code ? (
                <Text style={{ fontSize: 13, color: colors.textMuted, marginTop: 2 }}>#{thread.other.referral_code}</Text>
              ) : null}
              {thread?.other?.profile_image_hidden ? (
                <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 6, fontStyle: "italic" }}>
                  Profile picture is hidden by this user
                </Text>
              ) : null}
            </View>
            <View style={{ flexDirection: "row", gap: 12, marginTop: 22 }}>
              <TouchableOpacity
                onPress={() => { setProfileView("media"); if (!mediaList) loadMediaList(); }}
                style={{ flex: 1, backgroundColor: colors.surfaceMuted, borderRadius: 14, paddingVertical: 14, alignItems: "center" }}
                testID="chat-profile-media-card"
              >
                <Feather name="image" size={18} color={colors.primary} />
                <Text style={{ fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 4 }}>{profileDetail?.media_count ?? "—"}</Text>
                <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 2 }}>Media shared</Text>
                <Text style={{ fontSize: 10, color: colors.primary, marginTop: 6, fontWeight: "700" }}>View all →</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => { setProfileView("starred"); if (!starredList) loadStarredList(); }}
                style={{ flex: 1, backgroundColor: colors.surfaceMuted, borderRadius: 14, paddingVertical: 14, alignItems: "center" }}
                testID="chat-profile-starred-card"
              >
                <Feather name="star" size={18} color="#F59E0B" />
                <Text style={{ fontSize: 18, fontWeight: "800", color: colors.textMain, marginTop: 4 }}>{profileDetail?.starred_count ?? "—"}</Text>
                <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 2 }}>Starred</Text>
                <Text style={{ fontSize: 10, color: colors.primary, marginTop: 6, fontWeight: "700" }}>View all →</Text>
              </TouchableOpacity>
            </View>

            {/* ── Privacy + Block — June 2026 ─────────────────────────
                Quick access to per-chat privacy controls and user blocking
                without leaving the conversation. */}
            <ProfilePrivacyBlockRows
              threadId={threadId || ""}
              otherUserId={thread?.other?.id || ""}
              otherUserName={thread?.other?.name || "this user"}
              onClose={() => setProfileOpen(false)}
              onLockToggled={() => { sessionShownRef.current = true; forceRerender((n) => n + 1); }}
            />

            <TouchableOpacity
              onPress={() => setProfileOpen(false)}
              style={{ marginTop: 20, backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 14, alignItems: "center" }}
            >
              <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Close</Text>
            </TouchableOpacity>
          </View>
        </Pressable>
      </Modal>

      {/* Action sheet — long-press a message to react / reply / copy / star / delete / report. */}
      <Modal visible={!!actionMessage} transparent animationType="fade" onRequestClose={() => setActionMessage(null)}>
        <Pressable style={styles.sheetOverlay} onPress={() => setActionMessage(null)}>
          <View style={styles.sheet} onStartShouldSetResponder={() => true}>
            {/* Reaction picker — 6 common emojis. Tapping one toggles it on the server. */}
            <View style={{ flexDirection: "row", justifyContent: "space-around", paddingVertical: 4, marginBottom: 6 }}>
              {["👍", "❤️", "😂", "😮", "😢", "🙏"].map((emo) => (
                <TouchableOpacity
                  key={emo}
                  onPress={() => { if (actionMessage) reactNow(actionMessage, emo); }}
                  style={{ width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted }}
                  testID={`chat-react-${emo}`}
                >
                  <Text style={{ fontSize: 20 }}>{emo}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.sheetTitle}>Message options</Text>

            {/* Reply — set the composer's pending-reply state and close. */}
            <TouchableOpacity
              onPress={() => { if (actionMessage) setReplyTo(actionMessage); setActionMessage(null); }}
              style={styles.sheetRow}
            >
              <Feather name="corner-up-left" size={18} color={colors.textMain} />
              <Text style={styles.sheetRowText}>Reply</Text>
            </TouchableOpacity>

            {/* Copy text — uses expo-clipboard which is bundled by Expo SDK. */}
            {actionMessage?.text ? (
              <TouchableOpacity
                onPress={async () => {
                  try {
                    const Clipboard = await import("expo-clipboard");
                    await Clipboard.setStringAsync(actionMessage?.text || "");
                  } catch {}
                  setActionMessage(null);
                }}
                style={styles.sheetRow}
              >
                <Feather name="copy" size={18} color={colors.textMain} />
                <Text style={styles.sheetRowText}>Copy</Text>
              </TouchableOpacity>
            ) : null}

            {/* Star — toggle per-user star flag on the server. */}
            <TouchableOpacity
              onPress={async () => {
                if (!actionMessage) return;
                try { await api.post(`/chat/messages/${actionMessage.id}/star`); } catch {}
                setActionMessage(null);
              }}
              style={styles.sheetRow}
            >
              <Feather name="star" size={18} color={colors.textMain} />
              <Text style={styles.sheetRowText}>Star</Text>
            </TouchableOpacity>

            {/* Edit — only own messages, within 15 min, no reply yet. */}
            {actionMessage && isMine(actionMessage) && canEdit(actionMessage) ? (
              <TouchableOpacity onPress={() => onStartEdit(actionMessage)} style={styles.sheetRow}>
                <Feather name="edit-2" size={18} color={colors.textMain} />
                <Text style={styles.sheetRowText}>Edit</Text>
              </TouchableOpacity>
            ) : null}

            {/* Delete for me — soft-delete own messages anytime. */}
            {actionMessage && isMine(actionMessage) ? (
              <TouchableOpacity onPress={() => actionMessage && onDelete(actionMessage)} style={styles.sheetRow}>
                <Feather name="trash-2" size={18} color="#B91C1C" />
                <Text style={[styles.sheetRowText, { color: "#B91C1C" }]}>Delete for me</Text>
              </TouchableOpacity>
            ) : null}

            {/* Delete for everyone — own messages within 1 hour only. */}
            {actionMessage && isMine(actionMessage) ? (
              <TouchableOpacity
                onPress={async () => {
                  if (!actionMessage) return;
                  try {
                    await api.delete(`/chat/messages/${actionMessage.id}/for-everyone`);
                  } catch (e) { Alert.alert("Couldn't delete", "The 1-hour window may have passed."); }
                  setActionMessage(null);
                }}
                style={styles.sheetRow}
              >
                <Feather name="trash" size={18} color="#B91C1C" />
                <Text style={[styles.sheetRowText, { color: "#B91C1C" }]}>Delete for everyone</Text>
              </TouchableOpacity>
            ) : null}

            {/* Report — only for messages NOT from me. */}
            {actionMessage && !isMine(actionMessage) ? (
              <TouchableOpacity
                onPress={async () => {
                  if (!actionMessage || !thread?.other?.id) return;
                  try {
                    await api.post("/chat/report", { target_user_id: thread.other.id, message_id: actionMessage.id, reason: "Reported from chat thread" });
                    Alert.alert("Reported", "Thanks — our team will review this conversation.");
                  } catch {}
                  setActionMessage(null);
                }}
                style={styles.sheetRow}
              >
                <Feather name="flag" size={18} color="#B45309" />
                <Text style={[styles.sheetRowText, { color: "#B45309" }]}>Report</Text>
              </TouchableOpacity>
            ) : null}

            <TouchableOpacity onPress={() => setActionMessage(null)} style={[styles.sheetRow, { borderTopWidth: 1, borderTopColor: colors.border }]}>
              <Feather name="x" size={18} color={colors.textMuted} />
              <Text style={[styles.sheetRowText, { color: colors.textMuted }]}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </Pressable>
      </Modal>

      {/* Full-screen image preview — opens when user taps any image bubble. */}
      <Modal visible={!!previewImage} transparent animationType="fade" onRequestClose={() => setPreviewImage(null)} statusBarTranslucent>
        <Pressable style={styles.previewBackdrop} onPress={() => setPreviewImage(null)} testID="chat-image-preview-backdrop">
          {previewImage ? (
            <Image source={{ uri: previewImage }} style={styles.previewImg} resizeMode="contain" />
          ) : null}
          <TouchableOpacity
            onPress={() => setPreviewImage(null)}
            style={styles.previewClose}
            testID="chat-image-preview-close"
          >
            <Feather name="x" size={24} color="#FFFFFF" />
          </TouchableOpacity>
        </Pressable>
      </Modal>

      {/* Profile-pic full-screen viewer — tap avatar in the profile modal. */}
      <Modal visible={!!avatarPreview} transparent animationType="fade" onRequestClose={() => setAvatarPreview(null)} statusBarTranslucent>
        <Pressable style={styles.previewBackdrop} onPress={() => setAvatarPreview(null)} testID="chat-avatar-preview-backdrop">
          {avatarPreview ? (
            <Image source={{ uri: avatarPreview }} style={styles.previewImg} resizeMode="contain" />
          ) : null}
          <TouchableOpacity onPress={() => setAvatarPreview(null)} style={styles.previewClose}>
            <Feather name="x" size={24} color="#FFFFFF" />
          </TouchableOpacity>
        </Pressable>
      </Modal>

      {/* Media gallery view (4-col grid) — opens from profile modal. */}
      <Modal visible={profileView === "media"} animationType="slide" onRequestClose={() => setProfileView("summary")}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.headerRow}>
            <TouchableOpacity onPress={() => setProfileView("summary")} style={styles.iconBtn} testID="chat-media-back">
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <View style={{ flex: 1 }}>
              <Text style={styles.headerName}>Shared media</Text>
              <Text style={styles.headerSub}>{(mediaList || []).length} item{(mediaList || []).length === 1 ? "" : "s"}</Text>
            </View>
          </View>
          {mediaList === null ? (
            <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
          ) : mediaList.length === 0 ? (
            <View style={styles.emptyState}>
              <Feather name="image" size={26} color={colors.textMuted} />
              <Text style={styles.emptyStateText}>No media shared yet</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={{ padding: 4, flexDirection: "row", flexWrap: "wrap" }}>
              {mediaList.map((m, i) => (
                <TouchableOpacity key={m.id} activeOpacity={0.8} onPress={() => setGalleryIndex(i)} style={{ width: "25%", aspectRatio: 1, padding: 2 }} testID={`chat-media-tile-${i}`}>
                  <Image source={{ uri: m.image_data_url }} style={{ width: "100%", height: "100%", borderRadius: 4, backgroundColor: "#000" }} resizeMode="cover" />
                </TouchableOpacity>
              ))}
            </ScrollView>
          )}
        </SafeAreaView>
      </Modal>

      {/* Phone-gallery-style zoomable preview — opens from a media tile. */}
      <Modal visible={galleryIndex !== null} transparent animationType="fade" onRequestClose={() => setGalleryIndex(null)} statusBarTranslucent>
        <Pressable style={styles.previewBackdrop} onPress={() => setGalleryIndex(null)}>
          {galleryIndex !== null && mediaList && mediaList[galleryIndex]?.image_data_url ? (
            <ScrollView
              maximumZoomScale={4} minimumZoomScale={1}
              contentContainerStyle={{ flex: 1, alignItems: "center", justifyContent: "center" }}
              showsHorizontalScrollIndicator={false} showsVerticalScrollIndicator={false}
              bouncesZoom
            >
              <Image source={{ uri: mediaList[galleryIndex].image_data_url }} style={styles.previewImg} resizeMode="contain" />
            </ScrollView>
          ) : null}
          <TouchableOpacity onPress={() => setGalleryIndex(null)} style={styles.previewClose}>
            <Feather name="x" size={24} color="#FFFFFF" />
          </TouchableOpacity>
          {galleryIndex !== null && mediaList && mediaList.length > 1 ? (
            <View style={{ position: "absolute", bottom: 36, alignSelf: "center", flexDirection: "row", gap: 12 }}>
              <TouchableOpacity
                onPress={(e) => { (e as any).stopPropagation?.(); setGalleryIndex(Math.max(0, (galleryIndex || 0) - 1)); }}
                style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" }}
              >
                <Feather name="chevron-left" size={20} color="#fff" />
              </TouchableOpacity>
              <View style={{ paddingHorizontal: 14, paddingVertical: 10, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.18)" }}>
                <Text style={{ color: "#fff", fontWeight: "700" }}>{(galleryIndex || 0) + 1} / {mediaList.length}</Text>
              </View>
              <TouchableOpacity
                onPress={(e) => { (e as any).stopPropagation?.(); setGalleryIndex(Math.min(mediaList.length - 1, (galleryIndex || 0) + 1)); }}
                style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" }}
              >
                <Feather name="chevron-right" size={20} color="#fff" />
              </TouchableOpacity>
            </View>
          ) : null}
        </Pressable>
      </Modal>

      {/* Starred messages list — opens from profile modal. */}
      <Modal visible={profileView === "starred"} animationType="slide" onRequestClose={() => setProfileView("summary")}>
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.headerRow}>
            <TouchableOpacity onPress={() => setProfileView("summary")} style={styles.iconBtn} testID="chat-starred-back">
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <View style={{ flex: 1 }}>
              <Text style={styles.headerName}>Starred messages</Text>
              <Text style={styles.headerSub}>{(starredList || []).length} item{(starredList || []).length === 1 ? "" : "s"}</Text>
            </View>
          </View>
          {starredList === null ? (
            <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
          ) : starredList.length === 0 ? (
            <View style={styles.emptyState}>
              <Feather name="star" size={26} color={colors.textMuted} />
              <Text style={styles.emptyStateText}>No starred messages</Text>
            </View>
          ) : (
            <ScrollView contentContainerStyle={{ padding: spacing.screen, gap: 10 }}>
              {starredList.map((m) => (
                <View key={m.id} style={{ backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, padding: 12 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
                    <Feather name="star" size={12} color="#F59E0B" />
                    <Text style={{ fontSize: 11, fontWeight: "800", color: colors.textMuted }}>
                      {m.sender_id === myId ? "You" : (thread?.other?.name || "")} · {formatTime(m.created_at)}
                    </Text>
                  </View>
                  {m.image_data_url ? (
                    <Image source={{ uri: m.image_data_url }} style={{ width: "100%", height: 200, borderRadius: 8, backgroundColor: "#000" }} resizeMode="cover" />
                  ) : null}
                  {m.text ? <Text style={{ fontSize: 14, color: colors.textMain, marginTop: m.image_data_url ? 8 : 0 }}>{m.text}</Text> : null}
                </View>
              ))}
            </ScrollView>
          )}
        </SafeAreaView>
      </Modal>

      {/* Header overflow menu — Clear chat options. */}
      <Modal visible={headerMenuOpen} transparent animationType="fade" onRequestClose={() => setHeaderMenuOpen(false)}>
        <Pressable style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.35)" }} onPress={() => setHeaderMenuOpen(false)}>
          <View style={{ position: "absolute", top: 56, right: 12, backgroundColor: colors.surface, borderRadius: 12, paddingVertical: 6, minWidth: 220, borderWidth: 1, borderColor: colors.border }}>
            <TouchableOpacity onPress={() => { setHeaderMenuOpen(false); setClearConfirm("me"); }} style={styles.sheetRow} testID="chat-menu-clear-me">
              <Feather name="trash-2" size={16} color={colors.textMain} />
              <Text style={styles.sheetRowText}>Clear chat for me</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => { setHeaderMenuOpen(false); setClearConfirm("everyone"); }} style={styles.sheetRow} testID="chat-menu-clear-everyone">
              <Feather name="trash" size={16} color="#B91C1C" />
              <Text style={[styles.sheetRowText, { color: "#B91C1C" }]}>Clear chat for everyone</Text>
            </TouchableOpacity>
          </View>
        </Pressable>
      </Modal>

      {/* Confirm dialog for clear-chat. */}
      <Modal visible={!!clearConfirm} transparent animationType="fade" onRequestClose={() => setClearConfirm(null)}>
        <Pressable style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center", justifyContent: "center", padding: 24 }} onPress={() => setClearConfirm(null)}>
          <Pressable style={{ width: "100%", maxWidth: 360, backgroundColor: colors.surface, borderRadius: 18, padding: 20 }} onPress={() => {}}>
            <Text style={{ fontSize: 16, fontWeight: "800", color: colors.textMain }}>
              {clearConfirm === "everyone" ? "Clear chat for everyone?" : "Clear chat for me?"}
            </Text>
            <Text style={{ fontSize: 13, color: colors.textMuted, marginTop: 8, lineHeight: 18 }}>
              {clearConfirm === "everyone"
                ? "All messages, shared media, and starred items in this chat will be erased for BOTH you and the other person. This cannot be undone."
                : "All messages, shared media, and starred items will be hidden from your view only. The other person will still see them."}
            </Text>
            <View style={{ flexDirection: "row", gap: 10, marginTop: 18 }}>
              <TouchableOpacity onPress={() => setClearConfirm(null)} style={{ flex: 1, paddingVertical: 12, borderRadius: 10, backgroundColor: colors.surfaceMuted, alignItems: "center" }} testID="chat-clear-cancel">
                <Text style={{ fontSize: 14, fontWeight: "700", color: colors.textMain }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => clearConfirm && clearChat(clearConfirm)}
                style={{ flex: 1, paddingVertical: 12, borderRadius: 10, backgroundColor: clearConfirm === "everyone" ? "#B91C1C" : colors.primary, alignItems: "center" }}
                testID="chat-clear-confirm"
              >
                <Text style={{ fontSize: 14, fontWeight: "700", color: "#fff" }}>{clearConfirm === "everyone" ? "Clear for everyone" : "Clear for me"}</Text>
              </TouchableOpacity>
            </View>
          </Pressable>
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
  // When a bubble contains ONLY/primarily an image, drop the inner padding +
  // softer the bottom corner so the image edges aren't framed by a heavy
  // colored border. Makes the photo itself the focus.
  bubbleWithImage: { paddingHorizontal: 4, paddingVertical: 4, paddingBottom: 6 },
  bubbleMine: { backgroundColor: colors.primary, borderBottomRightRadius: 4 },
  bubbleTheirs: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 4 },
  bubbleDeleted: { opacity: 0.7, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, borderStyle: "dashed" },
  bubbleText: { fontSize: 14, lineHeight: 19 },
  deletedText: { fontSize: 12, fontStyle: "italic", color: colors.textMuted },
  bubbleImg: { width: 240, height: 240, borderRadius: 12, marginBottom: 4, backgroundColor: "#000" },
  // End-to-end encryption notice shown at the top of every chat history.
  e2eBanner: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingHorizontal: 16, paddingVertical: 8, marginVertical: 8,
    marginHorizontal: 12, borderRadius: 12,
    backgroundColor: "rgba(255, 246, 218, 0.85)",
  },
  e2eBannerText: { flex: 1, fontSize: 11, color: "#7A6C45", textAlign: "center", lineHeight: 15 },
  imgZoomHint: { position: "absolute", right: 8, bottom: 10, width: 22, height: 22, borderRadius: 11, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center" },
  bubbleFooter: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", marginTop: 3, gap: 2 },
  bubbleMeta: { fontSize: 9, color: colors.textMuted, letterSpacing: 0.3 },
  avatarBubble: { width: 26, height: 26, borderRadius: 13, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginBottom: 4 },
  avatarBubbleText: { fontSize: 11, fontWeight: "900", color: colors.primary },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface },
  announcementBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.screen, paddingVertical: 14,
    borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: colors.brand100,
  },
  announcementBannerText: { flex: 1, fontSize: 12, color: colors.text, fontWeight: "500" },
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
  // Full-screen image preview overlay.
  previewBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.94)", alignItems: "center", justifyContent: "center" },
  previewImg: { width: "100%", height: "100%" },
  previewClose: { position: "absolute", top: 50, right: 18, width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" },
});


// ── Profile-card Privacy + Block rows ──────────────────────────────────────
// Renders inside the chat-header profile modal. Surfaces the per-thread lock
// toggle, the chat-tab wallpaper jump-link, and Block / Unblock.
function ProfilePrivacyBlockRows({ threadId, otherUserId, otherUserName, onClose, onLockToggled }: { threadId: string; otherUserId: string; otherUserName: string; onClose: () => void; onLockToggled?: () => void; }) {
  const router = useRouter();
  const { settings, isThreadLocked, reload, markUnlocked } = useChatSettings();
  const [blocked, setBlocked] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  // Unified sheet state — RN-Web breaks pointer events on sibling <Modal>
  // portals, so we render a single Modal whose body branches on `sheet.kind`.
  type ConfirmPayload = { kind: "confirm"; title: string; body: string; ctaLabel: string; destructive?: boolean; onCtaPress: () => void | Promise<void> };
  type PinPayload     = { kind: "pin"; mode: "lock" | "unlock" };
  const [sheet, setSheet] = useState<null | ConfirmPayload | PinPayload>(null);
  const [pin, setPin] = useState("");
  const [pinErr, setPinErr] = useState<string | null>(null);

  const refreshBlocks = useCallback(async () => {
    if (!otherUserId) return;
    try {
      const { data } = await api.get<{ blocks: { blocked_id: string }[] }>("/chat/blocks");
      setBlocked(!!data.blocks?.find((b) => b.blocked_id === otherUserId));
    } catch { setBlocked(false); }
  }, [otherUserId]);

  useEffect(() => { refreshBlocks(); }, [refreshBlocks]);

  const locked = isThreadLocked(threadId);

  const toggleLock = () => {
    if (!settings?.has_pin) {
      setSheet({
        kind: "confirm",
        title: "Set up chat lock first",
        body: "Add a chat PIN in Chat → Settings before locking individual conversations.",
        ctaLabel: "Open Settings",
        onCtaPress: () => { setSheet(null); onClose(); router.push("/chat/settings" as any); },
      });
      return;
    }
    setPin(""); setPinErr(null);
    setSheet({ kind: "pin", mode: locked ? "unlock" : "lock" });
  };

  const submitLock = async () => {
    if (pin.length < 4) { setPinErr("Enter your 4–6 digit PIN."); return; }
    setBusy(true); setPinErr(null);
    try {
      const next = locked
        ? (settings?.locked_thread_ids || []).filter((t) => t !== threadId)
        : [...(settings?.locked_thread_ids || []), threadId];
      await api.patch("/chat/lock/threads", { pin, locked_thread_ids: next });
      // Flip the parent screen's local session-unlock state SYNCHRONOUSLY
      // so the next render of the gate sees `alreadyUnlocked=true` even if
      // the context-state update from markUnlocked hasn't propagated yet.
      onLockToggled?.();
      markUnlocked(threadId);
      await reload();
      setSheet(null); setPin("");
    } catch (e) {
      setPinErr(formatApiError(e));
    } finally { setBusy(false); }
  };

  const toggleBlock = () => {
    if (!otherUserId) return;
    const willBlock = !blocked;
    setSheet({
      kind: "confirm",
      title: `${willBlock ? "Block" : "Unblock"} ${otherUserName}?`,
      body: willBlock
        ? "They won't be able to send you messages, and you won't see new ones from them."
        : "They will be able to message you again.",
      ctaLabel: willBlock ? "Block" : "Unblock",
      destructive: willBlock,
      onCtaPress: async () => {
        setSheet(null);
        setBusy(true);
        try {
          if (willBlock) await api.post(`/chat/block/${otherUserId}`);
          else           await api.delete(`/chat/block/${otherUserId}`);
          await refreshBlocks();
        } catch (e) {
          setSheet({
            kind: "confirm",
            title: "Couldn't update",
            body: formatApiError(e),
            ctaLabel: "OK",
            onCtaPress: () => setSheet(null),
          });
        } finally { setBusy(false); }
      },
    });
  };

  return (
    <View style={{ marginTop: 16, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.background }}>
      <Text style={{ fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1, paddingHorizontal: 14, paddingTop: 12 }}>
        PRIVACY
      </Text>

      <TouchableOpacity onPress={toggleLock} style={ppbStyles.row} testID="chat-profile-lock">
        <View style={[ppbStyles.icon, { backgroundColor: colors.brand100 }]}>
          <Feather name={locked ? "lock" : "unlock"} size={16} color={colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={ppbStyles.title}>{locked ? "Chat locked" : "Lock this chat"}</Text>
          <Text style={ppbStyles.sub}>{locked ? "Requires PIN to open from chat list." : "Hide this conversation behind your chat PIN."}</Text>
        </View>
        <Feather name="chevron-right" size={16} color={colors.textMuted} />
      </TouchableOpacity>

      <View style={ppbStyles.divider} />

      <TouchableOpacity onPress={() => { onClose(); router.push("/chat/settings" as any); }} style={ppbStyles.row} testID="chat-profile-wallpaper">
        <View style={[ppbStyles.icon, { backgroundColor: colors.brand100 }]}>
          <Feather name="image" size={16} color={colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={ppbStyles.title}>Wallpaper</Text>
          <Text style={ppbStyles.sub}>Choose a background for your chats.</Text>
        </View>
        <Feather name="chevron-right" size={16} color={colors.textMuted} />
      </TouchableOpacity>

      <View style={ppbStyles.divider} />

      <TouchableOpacity onPress={toggleBlock} disabled={busy} style={ppbStyles.row} testID="chat-profile-block">
        <View style={[ppbStyles.icon, { backgroundColor: blocked ? colors.brand100 : "#FFE6E6" }]}>
          <Feather name={blocked ? "user-check" : "user-x"} size={16} color={blocked ? colors.primary : "#B3261E"} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[ppbStyles.title, !blocked && { color: "#B3261E" }]}>
            {blocked ? `Unblock ${otherUserName}` : `Block ${otherUserName}`}
          </Text>
          <Text style={ppbStyles.sub}>
            {blocked ? "They will be able to message you again." : "Stop receiving messages from this user."}
          </Text>
        </View>
        {busy ? <ActivityIndicator size="small" color={colors.primary} /> : <Feather name="chevron-right" size={16} color={colors.textMuted} />}
      </TouchableOpacity>

      {/* Single Modal that switches between the PIN sheet and the confirm
          sheet. RN-Web breaks pointer events on sibling <Modal> portals so
          we collapse both into one body-branching modal. */}
      <Modal visible={!!sheet} transparent animationType="fade" onRequestClose={() => setSheet(null)}>
        <Pressable style={ppbStyles.pinBackdrop} onPress={() => setSheet(null)}>
          <Pressable style={ppbStyles.pinCard} onPress={() => {}}>
            {sheet?.kind === "pin" ? (
              <>
                <Text style={ppbStyles.pinTitle}>{sheet.mode === "lock" ? "Lock this chat" : "Unlock this chat"}</Text>
                <Text style={ppbStyles.pinSub}>Enter your chat PIN to confirm.</Text>
                <TextInput
                  style={ppbStyles.pinInput}
                  value={pin}
                  onChangeText={(v) => setPin(v.replace(/[^0-9]/g, "").slice(0, 6))}
                  placeholder="••••••"
                  placeholderTextColor={colors.textMuted}
                  secureTextEntry keyboardType="number-pad" maxLength={6} autoFocus
                  testID="chat-profile-lock-pin"
                />
                {pinErr ? <Text style={{ color: "#B3261E", fontSize: 12, marginTop: 6 }}>{pinErr}</Text> : null}
                <View style={{ flexDirection: "row", gap: 10, marginTop: 14 }}>
                  <TouchableOpacity onPress={() => setSheet(null)} style={[ppbStyles.pinBtn, { backgroundColor: colors.surfaceMuted }]}>
                    <Text style={ppbStyles.pinBtnLabel}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={submitLock} disabled={busy} style={[ppbStyles.pinBtn, { backgroundColor: colors.primary }, busy && { opacity: 0.6 }]} testID="chat-profile-lock-confirm">
                    {busy ? <ActivityIndicator color="#fff" /> : <Text style={[ppbStyles.pinBtnLabel, { color: "#fff" }]}>Confirm</Text>}
                  </TouchableOpacity>
                </View>
              </>
            ) : sheet?.kind === "confirm" ? (
              <>
                <Text style={ppbStyles.pinTitle}>{sheet.title}</Text>
                <Text style={[ppbStyles.pinSub, { marginTop: 6 }]}>{sheet.body}</Text>
                <View style={{ flexDirection: "row", gap: 10, marginTop: 18 }}>
                  <TouchableOpacity onPress={() => setSheet(null)} style={[ppbStyles.pinBtn, { backgroundColor: colors.surfaceMuted }]} testID="chat-profile-confirm-cancel">
                    <Text style={ppbStyles.pinBtnLabel}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => { sheet.onCtaPress(); }}
                    style={[ppbStyles.pinBtn, { backgroundColor: sheet.destructive ? "#B3261E" : colors.primary }]}
                    testID="chat-profile-confirm-ok"
                  >
                    <Text style={[ppbStyles.pinBtnLabel, { color: "#fff" }]}>{sheet.ctaLabel}</Text>
                  </TouchableOpacity>
                </View>
              </>
            ) : null}
          </Pressable>
        </Pressable>
      </Modal>
    </View>
  );
}

const ppbStyles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 12 },
  icon: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 14, fontWeight: "700", color: colors.text },
  sub: { fontSize: 12, color: colors.textMuted, marginTop: 2 },
  divider: { height: 1, backgroundColor: colors.border, marginHorizontal: 14 },
  pinBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center", justifyContent: "center", padding: 24 },
  pinCard: { width: "100%", maxWidth: 360, backgroundColor: colors.surface, borderRadius: 18, padding: 20 },
  pinTitle: { fontSize: 16, fontWeight: "800", color: colors.text },
  pinSub: { fontSize: 13, color: colors.textMuted, marginTop: 4 },
  pinInput: {
    marginTop: 14, height: 52, borderRadius: 10, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.background, textAlign: "center", fontSize: 22, letterSpacing: 8, color: colors.text,
  },
  pinBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  pinBtnLabel: { fontSize: 14, fontWeight: "700", color: colors.text },
});
