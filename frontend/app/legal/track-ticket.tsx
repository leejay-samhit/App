// Public ticket tracker — anyone can look up tickets they raised using
// their email. PII inside the body is masked server-side so even if
// someone else guesses an email, they won't see private info. This screen
// also supports posting a follow-up reply to keep the conversation going
// without requiring sign-up.
import { useMemo, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TextInput, TouchableOpacity,
  KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Item = {
  id: string;
  subject: string;
  status: string;
  priority?: string;
  category?: string;
  guest_custom_category?: string | null;
  message_count: number;
  last_message_at?: string;
  last_message_by?: string;
  last_message_preview?: string;
  created_at?: string;
};

type Msg = {
  id: string;
  sender_type: "user" | "admin";
  sender_name: string;
  message: string;
  created_at: string;
};

const STATUS_COLOR: Record<string, { bg: string; fg: string }> = {
  open:         { bg: "#FEF3C7", fg: "#92400E" },
  in_progress:  { bg: "#DBEAFE", fg: "#1E40AF" },
  resolved:     { bg: "#D1FAE5", fg: "#065F46" },
  closed:       { bg: "#E5E7EB", fg: "#374151" },
};

export default function TrackTicket() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [items, setItems] = useState<Item[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [openTid, setOpenTid] = useState<string | null>(null);
  const [thread, setThread] = useState<{ messages: Msg[]; status: string } | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [reply, setReply] = useState("");
  const [replying, setReplying] = useState(false);

  const emailOk = useMemo(() => EMAIL_RE.test(email.trim()), [email]);

  const search = async () => {
    if (!emailOk) return;
    setLoading(true);
    setItems(null);
    setOpenTid(null);
    try {
      const { data } = await api.post<{ items: Item[] }>("/tickets/public/lookup", { email: email.trim() });
      setItems(data.items || []);
    } catch (e) {
      Alert.alert("Couldn't search", formatApiError(e));
    } finally {
      setLoading(false);
    }
  };

  const openThread = async (tid: string) => {
    setOpenTid(tid);
    setThread(null);
    setReply("");
    setThreadLoading(true);
    try {
      const { data } = await api.get<{ ticket: { status: string }; messages: Msg[] }>(
        `/tickets/public/${tid}?email=${encodeURIComponent(email.trim())}`,
      );
      setThread({ messages: data.messages, status: data.ticket.status });
    } catch (e) {
      Alert.alert("Couldn't load thread", formatApiError(e));
      setOpenTid(null);
    } finally {
      setThreadLoading(false);
    }
  };

  const sendReply = async () => {
    if (!openTid || !reply.trim() || replying) return;
    setReplying(true);
    try {
      await api.post(`/tickets/public/${openTid}/reply`, {
        email: email.trim(),
        message: reply.trim(),
      });
      setReply("");
      await openThread(openTid);
    } catch (e) {
      Alert.alert("Couldn't post reply", formatApiError(e));
    } finally {
      setReplying(false);
    }
  };

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={st.header}>
          <TouchableOpacity onPress={() => router.back()} style={st.iconBtn}>
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={st.title}>Track my ticket</Text>
          <View style={{ width: 40 }} />
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 120 }} keyboardShouldPersistTaps="handled">
          <View style={st.hintBox}>
            <Feather name="info" size={14} color={colors.primary} />
            <Text style={st.hintText}>
              Enter the email you used to raise the ticket. We'll show its status and
              any reply from our team. Sensitive details (phone, email, referral code,
              UTR) inside the conversation are hidden for privacy.
            </Text>
          </View>

          <Text style={st.label}>YOUR EMAIL</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput
              style={[st.input, { flex: 1 }, !emailOk && email.length > 0 && st.inputError]}
              placeholder="your.email@example.com"
              placeholderTextColor={colors.textMuted}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              testID="track-ticket-email"
              onSubmitEditing={search}
            />
            <TouchableOpacity
              onPress={search}
              disabled={!emailOk || loading}
              style={[st.searchBtn, (!emailOk || loading) && { opacity: 0.5 }]}
              testID="track-ticket-search"
            >
              {loading ? <ActivityIndicator color="#fff" /> : <Feather name="search" size={16} color="#fff" />}
            </TouchableOpacity>
          </View>

          {items !== null && items.length === 0 ? (
            <View style={st.emptyBox}>
              <Feather name="inbox" size={28} color={colors.textMuted} />
              <Text style={st.emptyTxt}>No tickets found for this email.</Text>
              <TouchableOpacity
                onPress={() => router.push("/legal/support-ticket" as any)}
                style={st.emptyBtn}
              >
                <Text style={st.emptyBtnText}>Raise a new ticket</Text>
              </TouchableOpacity>
            </View>
          ) : null}

          {(items || []).map((t) => {
            const c = STATUS_COLOR[t.status] || STATUS_COLOR.open;
            const isOpen = openTid === t.id;
            return (
              <View key={t.id} style={st.ticketCard}>
                <TouchableOpacity onPress={() => (isOpen ? setOpenTid(null) : openThread(t.id))}>
                  <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 10 }}>
                    <View style={{ flex: 1 }}>
                      <Text style={st.ticketSubject} numberOfLines={2}>{t.subject}</Text>
                      <Text style={st.ticketMeta}>
                        {t.guest_custom_category || t.category || "other"} · {t.message_count} message{t.message_count === 1 ? "" : "s"}
                      </Text>
                      {t.last_message_preview ? (
                        <Text style={st.ticketPreview} numberOfLines={2}>
                          {t.last_message_by === "admin" ? "Support: " : "You: "}{t.last_message_preview}
                        </Text>
                      ) : null}
                    </View>
                    <View style={[st.statusPill, { backgroundColor: c.bg }]}>
                      <Text style={[st.statusText, { color: c.fg }]}>{t.status.replace("_", " ")}</Text>
                    </View>
                  </View>
                  <Text style={st.viewToggle}>
                    {isOpen ? "▲ Hide messages" : "▼ View messages & reply"}
                  </Text>
                </TouchableOpacity>

                {isOpen ? (
                  <View style={st.threadBox}>
                    {threadLoading ? (
                      <ActivityIndicator color={colors.primary} />
                    ) : (
                      <>
                        {(thread?.messages || []).map((m) => (
                          <View
                            key={m.id}
                            style={[
                              st.bubble,
                              m.sender_type === "admin" ? st.bubbleAdmin : st.bubbleUser,
                            ]}
                          >
                            <Text style={st.bubbleSender}>{m.sender_name}</Text>
                            <Text style={st.bubbleText}>{m.message}</Text>
                            <Text style={st.bubbleDate}>
                              {new Date(m.created_at).toLocaleString()}
                            </Text>
                          </View>
                        ))}
                        {thread && thread.status !== "closed" ? (
                          <View style={st.replyRow}>
                            <TextInput
                              style={st.replyInput}
                              placeholder="Type your follow-up reply…"
                              placeholderTextColor={colors.textMuted}
                              value={reply}
                              onChangeText={setReply}
                              multiline
                            />
                            <TouchableOpacity
                              onPress={sendReply}
                              disabled={!reply.trim() || replying}
                              style={[st.replyBtn, (!reply.trim() || replying) && { opacity: 0.5 }]}
                            >
                              {replying ? (
                                <ActivityIndicator color="#fff" />
                              ) : (
                                <Feather name="send" size={16} color="#fff" />
                              )}
                            </TouchableOpacity>
                          </View>
                        ) : null}
                        {thread?.status === "closed" ? (
                          <Text style={st.closedNote}>This ticket is closed.</Text>
                        ) : null}
                      </>
                    )}
                  </View>
                ) : null}
              </View>
            );
          })}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.screen,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  hintBox: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: colors.brand100,
    borderRadius: radii.card,
    padding: 12, marginBottom: 8,
  },
  hintText: { flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 18 },
  label: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 16, marginBottom: 8 },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 13,
    fontSize: 14, color: colors.textMain,
  },
  inputError: { borderColor: "#D93025" },
  searchBtn: {
    width: 50, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary, borderRadius: radii.input,
  },
  emptyBox: { alignItems: "center", marginTop: 32, gap: 8 },
  emptyTxt: { fontSize: 13, color: colors.textMuted },
  emptyBtn: { marginTop: 8, paddingHorizontal: 20, paddingVertical: 11, backgroundColor: colors.primary, borderRadius: radii.button },
  emptyBtnText: { color: "#fff", fontWeight: "800", fontSize: 13 },
  ticketCard: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 14, padding: 14, marginTop: 12,
  },
  ticketSubject: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  ticketMeta: { fontSize: 11, color: colors.textMuted, marginTop: 4, fontWeight: "600" },
  ticketPreview: { fontSize: 12, color: colors.textMain, marginTop: 8, lineHeight: 16 },
  statusPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  statusText: { fontSize: 10, fontWeight: "900", letterSpacing: 0.6, textTransform: "uppercase" },
  viewToggle: { fontSize: 11, color: colors.primary, fontWeight: "800", marginTop: 10 },
  threadBox: { marginTop: 12, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 12 },
  bubble: { padding: 10, borderRadius: 12, marginBottom: 8, maxWidth: "90%" },
  bubbleUser: { backgroundColor: colors.brand100, alignSelf: "flex-end" },
  bubbleAdmin: { backgroundColor: colors.surfaceMuted, alignSelf: "flex-start" },
  bubbleSender: { fontSize: 10, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.5 },
  bubbleText: { fontSize: 13, color: colors.textMain, marginTop: 4, lineHeight: 18 },
  bubbleDate: { fontSize: 9, color: colors.textMuted, marginTop: 4, fontWeight: "600" },
  replyRow: { flexDirection: "row", gap: 8, marginTop: 8, alignItems: "flex-end" },
  replyInput: {
    flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 12, paddingVertical: 10,
    minHeight: 44, maxHeight: 120, fontSize: 13, color: colors.textMain,
  },
  replyBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radii.input, backgroundColor: colors.primary },
  closedNote: { fontSize: 12, color: colors.textMuted, textAlign: "center", fontStyle: "italic", marginTop: 10 },
});
