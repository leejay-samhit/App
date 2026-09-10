/**
 * Chat Records — SUPER-ADMIN-ONLY read-only chat audit (Sep 2026).
 *
 * Owner requirement: an admin must be able to read every Slang-Connect
 * conversation, including messages a user deleted, and download the whole
 * conversation as one .txt file if it ever has to be produced to a court.
 *
 * This screen is deliberately READ ONLY — there is no reply box. Admin
 * messaging lives in the other group of Admin → Chat ("Message users").
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, Modal, Image, Alert, RefreshControl,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { api, formatApiError } from "./api";
import { downloadText } from "./download";
import { colors, radii, spacing } from "./theme";

type Party = {
  id: string; name: string; email: string; phone: string;
  referral_code: string; role: string;
};

type ThreadRow = {
  id: string;
  participants: Party[];
  message_count: number;
  deleted_count: number;
  media_count: number;
  last_message_at?: string | null;
  last_preview?: string;
  is_announcement?: boolean;
  flag_count?: number;
};

type FlagRow = {
  id: string;
  thread_id: string;
  message_id?: string | null;
  kind: "message" | "blocked_attempt";
  categories: string[];
  words: string[];
  text: string;
  status: "open" | "reviewed";
  created_at_ist: string;
  reviewed_by?: string | null;
  sender: Party;
  participants: Party[];
};

type AuditMessage = {
  id: string;
  sender_id: string;
  sender_name: string;
  text: string;
  has_image: boolean;
  deleted: boolean;
  recovered: boolean;
  unrecoverable: boolean;
  edited: boolean;
  reply_to_id?: string | null;
  created_at_ist: string;
  deleted_at_ist?: string | null;
  flag_categories: string[];
  flag_words: string[];
};

const fmtWhen = (iso?: string | null) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return "—"; }
};

type RecordsView = "threads" | "flagged";

export default function ChatRecords() {
  const [view, setView] = useState<RecordsView>("threads");
  const [flags, setFlags] = useState<FlagRow[]>([]);
  const [openFlagCount, setOpenFlagCount] = useState(0);
  const [flagStatus, setFlagStatus] = useState<"open" | "reviewed">("open");
  const [flagsLoading, setFlagsLoading] = useState(false);
  const [rows, setRows] = useState<ThreadRow[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [openThread, setOpenThread] = useState<ThreadRow | null>(null);
  const [messages, setMessages] = useState<AuditMessage[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [photo, setPhoto] = useState<{ uri: string; deleted: boolean } | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);

  const load = useCallback(async (q: string) => {
    try {
      const { data } = await api.get<{ threads: ThreadRow[]; total: number }>(
        "/admin/chat-audit/threads",
        { params: { q: q.trim(), limit: 80 } },
      );
      setRows(data?.threads || []);
      setTotal(data?.total || 0);
    } catch (e) {
      Alert.alert("Couldn't load chat records", formatApiError(e));
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  const loadFlags = useCallback(async (status: "open" | "reviewed") => {
    setFlagsLoading(true);
    try {
      const { data } = await api.get<{ flags: FlagRow[]; open_count: number }>(
        "/admin/chat-audit/flags", { params: { status, limit: 150 } },
      );
      setFlags(data?.flags || []);
      setOpenFlagCount(data?.open_count || 0);
    } catch (e) {
      Alert.alert("Couldn't load flagged chats", formatApiError(e));
    } finally { setFlagsLoading(false); }
  }, []);

  useEffect(() => { load(""); loadFlags("open"); }, [load, loadFlags]);

  const markReviewed = async (f: FlagRow) => {
    try {
      await api.post(`/admin/chat-audit/flags/${f.id}/review`);
      setFlags((prev) => prev.filter((x) => x.id !== f.id));
      setOpenFlagCount((n) => Math.max(0, n - 1));
      load(query);
    } catch (e) { Alert.alert("Couldn't update", formatApiError(e)); }
  };

  const openFlagThread = async (f: FlagRow) => {
    const existing = rows.find((r) => r.id === f.thread_id);
    await openTranscript(existing || {
      id: f.thread_id,
      participants: f.participants,
      message_count: 0, deleted_count: 0, media_count: 0,
    });
  };

  const openTranscript = async (t: ThreadRow) => {
    setOpenThread(t);
    setMessages([]);
    setMsgLoading(true);
    try {
      const { data } = await api.get<{ messages: AuditMessage[] }>(
        `/admin/chat-audit/threads/${t.id}/messages`,
      );
      setMessages(data?.messages || []);
    } catch (e) {
      Alert.alert("Couldn't open conversation", formatApiError(e));
    } finally { setMsgLoading(false); }
  };

  const viewPhoto = async (m: AuditMessage) => {
    setPhotoBusy(true);
    try {
      const { data } = await api.get<{ data_url: string }>(
        `/admin/chat-audit/messages/${m.id}/image-data`,
      );
      if (data?.data_url) setPhoto({ uri: data.data_url, deleted: m.deleted });
    } catch (e) {
      Alert.alert("Couldn't load the photo", formatApiError(e));
    } finally { setPhotoBusy(false); }
  };

  const exportThread = async (t: ThreadRow) => {
    setExporting(true);
    try {
      const { data } = await api.get<{ filename: string; content: string }>(
        `/admin/chat-audit/threads/${t.id}/export`,
      );
      await downloadText({ filename: data.filename, content: data.content, mimeType: "text/plain" });
    } catch (e) {
      Alert.alert("Export failed", formatApiError(e));
    } finally { setExporting(false); }
  };

  const exportUser = async (p: Party) => {
    setExporting(true);
    try {
      const { data } = await api.get<{ filename: string; content: string; thread_count: number }>(
        `/admin/chat-audit/users/${p.id}/export`,
      );
      await downloadText({ filename: data.filename, content: data.content, mimeType: "text/plain" });
    } catch (e) {
      Alert.alert("Export failed", formatApiError(e));
    } finally { setExporting(false); }
  };

  const askExportUser = (t: ThreadRow) => {
    const [a, b] = t.participants;
    Alert.alert(
      "Download every chat of…",
      "Pick whose full chat history you need.",
      [
        { text: "Cancel", style: "cancel" },
        ...(a ? [{ text: a.name, onPress: () => exportUser(a) }] : []),
        ...(b ? [{ text: b.name, onPress: () => exportUser(b) }] : []),
      ],
    );
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>;
  }

  return (
    <View style={{ flex: 1 }}>
      <View style={styles.viewTabs}>
        <TouchableOpacity
          onPress={() => setView("threads")}
          style={[styles.viewTab, view === "threads" && styles.viewTabActive]}
          testID="chat-records-view-threads"
        >
          <Text style={[styles.viewTabText, view === "threads" && styles.viewTabTextActive]}>Conversations</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => { setView("flagged"); loadFlags(flagStatus); }}
          style={[styles.viewTab, view === "flagged" && styles.viewTabActive]}
          testID="chat-records-view-flagged"
        >
          <Feather name="alert-triangle" size={12} color={view === "flagged" ? colors.primaryFg : "#B42318"} />
          <Text style={[styles.viewTabText, view === "flagged" && styles.viewTabTextActive]}>
            Flagged{openFlagCount ? ` (${openFlagCount})` : ""}
          </Text>
        </TouchableOpacity>
      </View>

      {view === "flagged" ? (
        <FlaggedList
          flags={flags}
          loading={flagsLoading}
          status={flagStatus}
          onStatus={(s) => { setFlagStatus(s); loadFlags(s); }}
          onOpen={openFlagThread}
          onReview={markReviewed}
        />
      ) : (
      <View style={{ flex: 1 }}>
      <View style={styles.searchWrap}>
        <Feather name="search" size={15} color={colors.textMuted} />
        <TextInput
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={() => load(query)}
          placeholder="Search by name, email, phone or referral code"
          placeholderTextColor={colors.textMuted}
          style={styles.searchInput}
          returnKeyType="search"
          testID="chat-records-search"
        />
        {query ? (
          <TouchableOpacity onPress={() => { setQuery(""); load(""); }} hitSlop={10}>
            <Feather name="x-circle" size={16} color={colors.textMuted} />
          </TouchableOpacity>
        ) : null}
      </View>

      <View style={styles.notice}>
        <Feather name="shield" size={13} color={colors.primary} />
        <Text style={styles.noticeText}>
          Read-only legal record. Deleted messages are shown too. Every open and
          download is written to the admin audit log.
        </Text>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(query); }} tintColor={colors.primary} />}
      >
        <Text style={styles.countLine}>{total} conversation{total === 1 ? "" : "s"} on record</Text>
        {rows.length === 0 ? (
          <Text style={styles.empty}>No conversations match that search.</Text>
        ) : rows.map((t) => {
          const [a, b] = t.participants;
          return (
            <TouchableOpacity
              key={t.id}
              style={styles.card}
              onPress={() => openTranscript(t)}
              testID={`chat-record-${t.id}`}
            >
              <View style={styles.cardTop}>
                <Text style={styles.pairText} numberOfLines={1}>
                  {(a?.name || "Deleted user")}  ⇄  {(b?.name || "Deleted user")}
                </Text>
                <Feather name="chevron-right" size={18} color={colors.textMuted} />
              </View>
              <Text style={styles.metaText} numberOfLines={1}>
                {a?.email || "no email"} · {b?.email || "no email"}
              </Text>
              {t.last_preview ? (
                <Text style={styles.preview} numberOfLines={1}>{t.last_preview}</Text>
              ) : null}
              <View style={styles.chipRow}>
                <View style={styles.chip}><Text style={styles.chipText}>{t.message_count} messages</Text></View>
                {t.deleted_count > 0 ? (
                  <View style={[styles.chip, styles.chipWarn]}>
                    <Text style={[styles.chipText, styles.chipWarnText]}>{t.deleted_count} deleted</Text>
                  </View>
                ) : null}
                {t.media_count > 0 ? (
                  <View style={styles.chip}><Text style={styles.chipText}>{t.media_count} photos</Text></View>
                ) : null}
                {(t.flag_count || 0) > 0 ? (
                  <View style={[styles.chip, styles.chipWarn]}>
                    <Text style={[styles.chipText, styles.chipWarnText]}>⚠ {t.flag_count} to review</Text>
                  </View>
                ) : null}
                <Text style={styles.whenText}>{fmtWhen(t.last_message_at)}</Text>
              </View>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
      </View>
      )}

      {/* ── Transcript ─────────────────────────────────────────────── */}
      <Modal visible={!!openThread} animationType="slide" onRequestClose={() => setOpenThread(null)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setOpenThread(null)} style={styles.iconBtn} testID="chat-record-close">
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <View style={{ flex: 1 }}>
              <Text style={styles.modalTitle} numberOfLines={1}>
                {openThread?.participants?.[0]?.name} ⇄ {openThread?.participants?.[1]?.name}
              </Text>
              <Text style={styles.modalSub}>Read-only record · {messages.length} messages</Text>
            </View>
          </View>

          <View style={styles.partyBox}>
            {(openThread?.participants || []).map((p, i) => (
              <Text key={p.id || i} style={styles.partyLine} numberOfLines={2}>
                <Text style={{ fontWeight: "900" }}>{String.fromCharCode(65 + i)}) {p.name}</Text>
                {"  "}{p.email || "no email"} · {p.phone || "no phone"} · {p.role}
              </Text>
            ))}
          </View>

          {msgLoading ? (
            <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
          ) : (
            <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 120 }}>
              {messages.map((m, idx) => {
                const mine = m.sender_id === openThread?.participants?.[0]?.id;
                return (
                  <View key={m.id} style={[styles.bubbleWrap, mine ? styles.leftWrap : styles.rightWrap]}>
                    <Text style={styles.bubbleMeta}>
                      #{idx + 1} · {m.sender_name} · {m.created_at_ist}
                    </Text>
                    <View style={[styles.bubble, mine ? styles.bubbleLeft : styles.bubbleRight, m.deleted && styles.bubbleDeleted]}>
                      {m.deleted ? (
                        <View style={styles.deletedTag}>
                          <Feather name="trash-2" size={11} color="#B42318" />
                          <Text style={styles.deletedTagText}>
                            DELETED {m.deleted_at_ist ? `· ${m.deleted_at_ist}` : ""}
                            {m.recovered ? " · recovered" : " · content not recoverable"}
                          </Text>
                        </View>
                      ) : null}
                      {m.flag_categories?.length ? (
                        <View style={styles.flagTag}>
                          <Feather name="alert-triangle" size={11} color="#B54708" />
                          <Text style={styles.flagTagText}>
                            {m.flag_categories.join(" + ").toUpperCase()} · {m.flag_words.join(", ")}
                          </Text>
                        </View>
                      ) : null}
                      {m.text ? <Text style={styles.bubbleText}>{m.text}</Text> : null}
                      {!m.text && !m.has_image ? <Text style={styles.bubbleFaint}>(empty message)</Text> : null}
                      {m.has_image ? (
                        <TouchableOpacity style={styles.photoBtn} onPress={() => viewPhoto(m)} testID={`chat-record-photo-${m.id}`}>
                          <Feather name="image" size={13} color={colors.primary} />
                          <Text style={styles.photoBtnText}>{photoBusy ? "Loading photo…" : "Photo — tap to view"}</Text>
                        </TouchableOpacity>
                      ) : null}
                      {m.edited ? <Text style={styles.bubbleFaint}>edited</Text> : null}
                    </View>
                  </View>
                );
              })}
              {messages.length === 0 ? <Text style={styles.empty}>No messages in this conversation.</Text> : null}
            </ScrollView>
          )}

          <View style={styles.actionBar}>
            <TouchableOpacity
              style={[styles.primaryBtn, exporting && { opacity: 0.6 }]}
              disabled={exporting}
              onPress={() => openThread && exportThread(openThread)}
              testID="chat-record-export-thread"
            >
              <Feather name="download" size={15} color={colors.primaryFg} />
              <Text style={styles.primaryBtnText}>{exporting ? "Preparing…" : "Download this chat (.txt)"}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.secondaryBtn}
              disabled={exporting}
              onPress={() => openThread && askExportUser(openThread)}
              testID="chat-record-export-user"
            >
              <Feather name="user" size={15} color={colors.primary} />
              <Text style={styles.secondaryBtnText}>All chats of a user</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* ── Photo viewer ───────────────────────────────────────────── */}
      <Modal visible={!!photo} transparent animationType="fade" onRequestClose={() => setPhoto(null)}>
        <View style={styles.photoRoot}>
          <TouchableOpacity style={styles.photoClose} onPress={() => setPhoto(null)} testID="chat-record-photo-close">
            <Feather name="x" size={22} color="#fff" />
          </TouchableOpacity>
          {photo?.deleted ? <Text style={styles.photoDeleted}>This photo was deleted by the sender</Text> : null}
          {photo ? <Image source={{ uri: photo.uri }} style={styles.photoImg} resizeMode="contain" /> : null}
        </View>
      </Modal>
    </View>
  );
}

/**
 * Review queue — every chat that matched an abusive or scam word, newest
 * first. `blocked_attempt` rows are messages the send filter refused to
 * deliver: the other user never saw them, but the attempt is the signal.
 */
function FlaggedList({
  flags, loading, status, onStatus, onOpen, onReview,
}: {
  flags: FlagRow[];
  loading: boolean;
  status: "open" | "reviewed";
  onStatus: (s: "open" | "reviewed") => void;
  onOpen: (f: FlagRow) => void;
  onReview: (f: FlagRow) => void;
}) {
  return (
    <View style={{ flex: 1 }}>
      <View style={styles.filterRow}>
        {(["open", "reviewed"] as const).map((s) => (
          <TouchableOpacity
            key={s}
            onPress={() => onStatus(s)}
            style={[styles.filterPill, status === s && styles.filterPillActive]}
            testID={`chat-flags-${s}`}
          >
            <Text style={[styles.filterPillText, status === s && { color: colors.primaryFg }]}>
              {s === "open" ? "To review" : "Reviewed"}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
          {flags.length === 0 ? (
            <Text style={styles.empty}>
              {status === "open" ? "Nothing to review — no chat matched an abusive or scam word." : "Nothing reviewed yet."}
            </Text>
          ) : flags.map((f) => (
            <View key={f.id} style={[styles.card, styles.flagCard]} testID={`chat-flag-${f.id}`}>
              <View style={styles.chipRow}>
                {f.categories.map((c) => (
                  <View key={c} style={[styles.chip, c === "abuse" ? styles.chipWarn : styles.chipScam]}>
                    <Text style={[styles.chipText, c === "abuse" ? styles.chipWarnText : styles.chipScamText]}>
                      {c.toUpperCase()}
                    </Text>
                  </View>
                ))}
                {f.kind === "blocked_attempt" ? (
                  <View style={styles.chip}><Text style={styles.chipText}>BLOCKED — not delivered</Text></View>
                ) : null}
                <Text style={styles.whenText}>{f.created_at_ist}</Text>
              </View>
              <Text style={styles.flagSender} numberOfLines={1}>
                {f.sender.name} · {f.sender.email || "no email"} · {f.sender.phone || "no phone"}
              </Text>
              <Text style={styles.flagPair} numberOfLines={1}>
                in chat: {f.participants.map((p) => p.name).join("  ⇄  ") || "unknown"}
              </Text>
              <Text style={styles.flagText}>{f.text}</Text>
              <Text style={styles.flagWords}>matched: {f.words.join(", ")}</Text>
              {f.status === "reviewed" && f.reviewed_by ? (
                <Text style={styles.flagWords}>reviewed by {f.reviewed_by}</Text>
              ) : null}
              <View style={styles.flagActions}>
                <TouchableOpacity style={styles.flagOpenBtn} onPress={() => onOpen(f)} testID={`chat-flag-open-${f.id}`}>
                  <Feather name="message-square" size={13} color={colors.primary} />
                  <Text style={styles.flagOpenText}>Open chat</Text>
                </TouchableOpacity>
                {f.status === "open" ? (
                  <TouchableOpacity style={styles.flagDoneBtn} onPress={() => onReview(f)} testID={`chat-flag-review-${f.id}`}>
                    <Feather name="check" size={13} color={colors.primaryFg} />
                    <Text style={styles.flagDoneText}>Mark reviewed</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  viewTabs: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.screen, paddingTop: 6 },
  viewTab: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 40, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  viewTabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  viewTabText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  viewTabTextActive: { color: colors.primaryFg },
  filterRow: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.screen, paddingTop: 10 },
  filterPill: { paddingHorizontal: 14, height: 36, borderRadius: 999, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  filterPillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  filterPillText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  flagCard: { borderColor: "#F9DBD8" },
  flagSender: { fontSize: 13, fontWeight: "800", color: colors.textMain, marginTop: 8 },
  flagPair: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  flagText: { fontSize: 13, color: colors.textMain, marginTop: 8, lineHeight: 19 },
  flagWords: { fontSize: 11, color: "#B54708", fontWeight: "800", marginTop: 6 },
  flagActions: { flexDirection: "row", gap: 8, marginTop: 12 },
  flagOpenBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 14, minHeight: 44, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  flagOpenText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  flagDoneBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 44, borderRadius: 999, backgroundColor: colors.primary },
  flagDoneText: { fontSize: 12, fontWeight: "900", color: colors.primaryFg },
  chipScam: { backgroundColor: "#FFFAEB", borderColor: "#FEDF89" },
  chipScamText: { color: "#B54708" },
  flagTag: { flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 6 },
  flagTagText: { flex: 1, fontSize: 10, fontWeight: "900", color: "#B54708" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 40 },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: spacing.screen, marginTop: 10, paddingHorizontal: 12, height: 44, borderRadius: radii.button, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  searchInput: { flex: 1, fontSize: 13, color: colors.textMain },
  notice: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: spacing.screen, marginTop: 10, padding: 10, borderRadius: 12, backgroundColor: colors.brand100, borderWidth: 1, borderColor: colors.border },
  noticeText: { flex: 1, fontSize: 11, color: colors.textMain, lineHeight: 15, fontWeight: "600" },
  countLine: { fontSize: 11, fontWeight: "900", letterSpacing: 0.8, color: colors.textMuted, marginBottom: 10, textTransform: "uppercase" },
  empty: { fontSize: 13, color: colors.textMuted, textAlign: "center", marginTop: 24 },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, padding: 14, marginBottom: 10, minHeight: 48 },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  pairText: { flex: 1, fontSize: 14, fontWeight: "800", color: colors.textMain },
  metaText: { fontSize: 11, color: colors.textMuted, marginTop: 3 },
  preview: { fontSize: 12, color: colors.textMain, marginTop: 6 },
  chipRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginTop: 10 },
  chip: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  chipText: { fontSize: 10, fontWeight: "800", color: colors.textMain },
  chipWarn: { backgroundColor: "#FEF3F2", borderColor: "#F9DBD8" },
  chipWarnText: { color: "#B42318" },
  whenText: { fontSize: 10, color: colors.textMuted, marginLeft: "auto", fontWeight: "700" },

  modalRoot: { flex: 1, backgroundColor: colors.background },
  modalHeader: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 10, paddingTop: 44, paddingBottom: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  modalTitle: { fontSize: 15, fontWeight: "900", color: colors.textMain },
  modalSub: { fontSize: 11, color: colors.textMuted, fontWeight: "700", marginTop: 2 },
  partyBox: { paddingHorizontal: spacing.screen, paddingVertical: 10, gap: 4, backgroundColor: colors.surfaceMuted },
  partyLine: { fontSize: 11, color: colors.textMain, lineHeight: 16 },

  bubbleWrap: { marginBottom: 14, maxWidth: "92%" },
  leftWrap: { alignSelf: "flex-start" },
  rightWrap: { alignSelf: "flex-end" },
  bubbleMeta: { fontSize: 10, color: colors.textMuted, fontWeight: "700", marginBottom: 3 },
  bubble: { padding: 10, borderRadius: 12, borderWidth: 1 },
  bubbleLeft: { backgroundColor: colors.surface, borderColor: colors.border },
  bubbleRight: { backgroundColor: colors.brand100, borderColor: colors.border },
  bubbleDeleted: { borderColor: "#F9DBD8", backgroundColor: "#FFF9F8" },
  bubbleText: { fontSize: 13, color: colors.textMain, lineHeight: 19 },
  bubbleFaint: { fontSize: 11, color: colors.textMuted, marginTop: 4, fontStyle: "italic" },
  deletedTag: { flexDirection: "row", alignItems: "center", gap: 5, marginBottom: 6 },
  deletedTagText: { fontSize: 10, fontWeight: "900", color: "#B42318" },
  photoBtn: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, paddingVertical: 8, paddingHorizontal: 10, borderRadius: 10, backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, minHeight: 44 },
  photoBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },

  actionBar: { position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", gap: 8, padding: 12, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  primaryBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.primary, borderRadius: 999, paddingVertical: 13, minHeight: 48 },
  primaryBtnText: { fontSize: 12, fontWeight: "900", color: colors.primaryFg },
  secondaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, minHeight: 48 },
  secondaryBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },

  photoRoot: { flex: 1, backgroundColor: "rgba(0,0,0,0.92)", alignItems: "center", justifyContent: "center" },
  photoClose: { position: "absolute", top: 48, right: 18, width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.15)" },
  photoDeleted: { position: "absolute", top: 58, left: 18, fontSize: 11, fontWeight: "900", color: "#FDA29B" },
  photoImg: { width: "92%", height: "70%" },
});
