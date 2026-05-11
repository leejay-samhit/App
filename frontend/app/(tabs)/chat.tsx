// Chat home — thread list (downline pinned on top), search by referral code,
// pending requests inbox. Real-time updates via WebSocket.
import { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl,
  ActivityIndicator, TextInput, Alert, Image, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { useChatSocket } from "../../src/use-chat-socket";

type UserBrief = { id: string; name: string; referral_code: string; avatar?: string };
type Thread = { id: string; other: UserBrief; is_downline: boolean; unread_count: number; last_message: any; last_message_at?: string };
type Request = { id: string; from_user_id: string; to_user_id: string; status: string; message: string; created_at: string; from?: UserBrief; to?: UserBrief };

export default function ChatListScreen() {
  const router = useRouter();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [requests, setRequests] = useState<{ incoming: Request[]; outgoing: Request[] }>({ incoming: [], outgoing: [] });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [searchResult, setSearchResult] = useState<any | null>(null);
  const [searching, setSearching] = useState(false);
  const [showRequestModal, setShowRequestModal] = useState(false);
  const [requestMessage, setRequestMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [tRes, rRes] = await Promise.all([
        api.get<{ threads: Thread[] }>("/chat/threads"),
        api.get<{ incoming: Request[]; outgoing: Request[] }>("/chat/requests"),
      ]);
      setThreads(tRes.data?.threads || []);
      setRequests({ incoming: rRes.data?.incoming || [], outgoing: rRes.data?.outgoing || [] });
    } catch (e) { /* ignore on focus refresh */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Realtime: refresh thread list on any chat event
  useChatSocket((ev) => {
    if (ev.type === "message.new" || ev.type === "request.new" || ev.type === "request.accepted" || ev.type === "request.rejected") {
      load();
    }
  });

  const onSearch = async () => {
    const code = search.trim().toUpperCase();
    if (!code) return;
    setSearching(true); setSearchResult(null);
    try {
      const r = await api.get<any>("/chat/search", { params: { code } });
      setSearchResult(r.data);
    } catch (e) {
      Alert.alert("Search failed", formatApiError(e));
    } finally { setSearching(false); }
  };

  const onSendRequest = async () => {
    if (!searchResult?.user?.id) return;
    try {
      await api.post("/chat/request", { to_user_id: searchResult.user.id, message: requestMessage.trim() });
      setShowRequestModal(false); setRequestMessage(""); setSearchResult(null); setSearch("");
      Alert.alert("Request sent", `Waiting for ${searchResult.user.name} to accept.`);
      load();
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
  };

  const onAcceptRequest = async (req: Request) => {
    try {
      const r = await api.post<{ thread_id: string }>(`/chat/request/${req.id}/accept`);
      load();
      if (r.data?.thread_id) router.push(`/chat/${r.data.thread_id}` as any);
    } catch (e) { Alert.alert("Failed", formatApiError(e)); }
  };

  const onRejectRequest = async (req: Request) => {
    try { await api.post(`/chat/request/${req.id}/reject`); load(); }
    catch (e) { Alert.alert("Failed", formatApiError(e)); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Chat</Text>
        {requests.incoming.length > 0 ? (
          <View style={styles.badge}><Text style={styles.badgeText}>{requests.incoming.length} new</Text></View>
        ) : null}
      </View>

      {/* Search by referral code */}
      <View style={styles.searchWrap}>
        <Feather name="search" size={16} color={colors.textMuted} />
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="Search by referral code (e.g. ABC123)"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="characters"
          maxLength={20}
          onSubmitEditing={onSearch}
        />
        {search ? (
          <TouchableOpacity onPress={() => { setSearch(""); setSearchResult(null); }} style={styles.searchClear}>
            <Feather name="x" size={14} color={colors.textMuted} />
          </TouchableOpacity>
        ) : null}
        <TouchableOpacity onPress={onSearch} disabled={searching || !search.trim()} style={[styles.searchBtn, (!search.trim() || searching) && { opacity: 0.5 }]}>
          {searching ? <ActivityIndicator size="small" color={colors.primaryFg} /> : <Text style={styles.searchBtnText}>Find</Text>}
        </TouchableOpacity>
      </View>

      {/* Search result card */}
      {searchResult ? (
        <View style={styles.searchCard}>
          <View style={styles.avatar}><Text style={styles.avatarText}>{(searchResult.user.name || "?").substring(0, 1).toUpperCase()}</Text></View>
          <View style={{ flex: 1 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Text style={styles.userName}>{searchResult.user.name}</Text>
              {searchResult.is_downline ? <View style={styles.downlineBadge}><Text style={styles.downlineBadgeText}>DOWNLINE</Text></View> : null}
            </View>
            <Text style={styles.userCode}>#{searchResult.user.referral_code}</Text>
          </View>
          {searchResult.relationship === "already_chatting" ? (
            <TouchableOpacity style={styles.primaryBtn} onPress={() => router.push(`/chat/${searchResult.thread_id}` as any)}>
              <Feather name="message-circle" size={14} color={colors.primaryFg} />
              <Text style={styles.primaryBtnText}>Open</Text>
            </TouchableOpacity>
          ) : searchResult.relationship === "request_pending" ? (
            <View style={styles.pendingBtn}><Text style={styles.pendingBtnText}>Pending…</Text></View>
          ) : (
            <TouchableOpacity style={styles.primaryBtn} onPress={() => setShowRequestModal(true)}>
              <Feather name="send" size={14} color={colors.primaryFg} />
              <Text style={styles.primaryBtnText}>Request</Text>
            </TouchableOpacity>
          )}
        </View>
      ) : null}

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.screen, paddingTop: 4, paddingBottom: 80 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        >
          {/* Incoming requests */}
          {requests.incoming.length > 0 ? (
            <View style={{ marginBottom: 16 }}>
              <Text style={styles.sectionLabel}>CHAT REQUESTS</Text>
              {requests.incoming.map((r) => (
                <View key={r.id} style={styles.requestCard}>
                  <View style={styles.avatar}><Text style={styles.avatarText}>{(r.from?.name || "?").substring(0, 1).toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.userName}>{r.from?.name || "Unknown"}</Text>
                    <Text style={styles.userCode}>wants to chat with you{r.message ? ` · \u201C${r.message}\u201D` : ""}</Text>
                  </View>
                  <TouchableOpacity onPress={() => onAcceptRequest(r)} style={[styles.miniBtn, { backgroundColor: colors.primary }]} testID={`req-accept-${r.id}`}>
                    <Feather name="check" size={14} color={colors.primaryFg} />
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => onRejectRequest(r)} style={[styles.miniBtn, { backgroundColor: "#FEE2E2" }]} testID={`req-reject-${r.id}`}>
                    <Feather name="x" size={14} color="#B91C1C" />
                  </TouchableOpacity>
                </View>
              ))}
            </View>
          ) : null}

          {/* Outgoing requests pending */}
          {requests.outgoing.length > 0 ? (
            <View style={{ marginBottom: 16 }}>
              <Text style={styles.sectionLabel}>SENT · WAITING</Text>
              {requests.outgoing.map((r) => (
                <View key={r.id} style={[styles.requestCard, { backgroundColor: colors.surfaceMuted }]}>
                  <View style={styles.avatar}><Text style={styles.avatarText}>{(r.to?.name || "?").substring(0, 1).toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.userName}>{r.to?.name || "Unknown"}</Text>
                    <Text style={styles.userCode}>Pending… #{r.to?.referral_code}</Text>
                  </View>
                </View>
              ))}
            </View>
          ) : null}

          {/* Threads */}
          <Text style={styles.sectionLabel}>YOUR CHATS</Text>
          {threads.length === 0 ? (
            <View style={styles.emptyCard}>
              <Feather name="message-square" size={28} color={colors.textMuted} />
              <Text style={styles.emptyText}>No chats yet</Text>
              <Text style={styles.emptySub}>Search a friend's referral code above to start a conversation.</Text>
            </View>
          ) : (
            threads.map((t) => (
              <TouchableOpacity key={t.id} style={styles.threadCard} activeOpacity={0.85} onPress={() => router.push(`/chat/${t.id}` as any)} testID={`thread-${t.id}`}>
                <View style={styles.avatar}><Text style={styles.avatarText}>{(t.other.name || "?").substring(0, 1).toUpperCase()}</Text></View>
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={styles.userName} numberOfLines={1}>{t.other.name}</Text>
                    {t.is_downline ? <View style={styles.downlineBadge}><Text style={styles.downlineBadgeText}>DOWNLINE</Text></View> : null}
                  </View>
                  <Text style={styles.lastMessage} numberOfLines={1}>
                    {t.last_message?.deleted ? <Text style={{ fontStyle: "italic" }}>Message deleted</Text> :
                      t.last_message?.image_data_url ? "📷 Photo" :
                      (t.last_message?.text || "No messages yet")}
                  </Text>
                </View>
                {t.unread_count > 0 ? (
                  <View style={styles.unreadBadge}><Text style={styles.unreadText}>{t.unread_count}</Text></View>
                ) : null}
              </TouchableOpacity>
            ))
          )}
        </ScrollView>
      )}

      {/* Send request modal */}
      <Modal visible={showRequestModal} transparent animationType="slide" onRequestClose={() => setShowRequestModal(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <TouchableOpacity onPress={() => setShowRequestModal(false)} style={styles.iconBtn}><Feather name="x" size={20} color={colors.textMain} /></TouchableOpacity>
              <Text style={styles.modalTitle}>Send chat request</Text>
              <TouchableOpacity onPress={onSendRequest} style={[styles.iconBtn, { backgroundColor: colors.primary, borderColor: colors.primary }]}>
                <Feather name="send" size={18} color={colors.primaryFg} />
              </TouchableOpacity>
            </View>
            <View style={{ padding: 20 }}>
              <Text style={styles.label}>To</Text>
              <View style={[styles.searchCard, { marginBottom: 12, padding: 12, marginHorizontal: 0 }]}>
                <View style={styles.avatar}><Text style={styles.avatarText}>{(searchResult?.user.name || "?").substring(0, 1).toUpperCase()}</Text></View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.userName}>{searchResult?.user.name}</Text>
                  <Text style={styles.userCode}>#{searchResult?.user.referral_code}</Text>
                </View>
              </View>
              <Text style={styles.label}>Add a note (optional)</Text>
              <TextInput style={[styles.input, { minHeight: 90, textAlignVertical: "top" }]} value={requestMessage} onChangeText={setRequestMessage} multiline placeholder="Hi! I'd like to chat about…" placeholderTextColor={colors.textMuted} maxLength={300} />
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 4, paddingBottom: 8 },
  title: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  badge: { backgroundColor: "#FEE2E2", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  badgeText: { fontSize: 11, fontWeight: "800", color: "#B91C1C" },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 8, marginHorizontal: spacing.screen, marginBottom: 12, backgroundColor: colors.surface, borderRadius: 999, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 14, paddingVertical: 4 },
  searchInput: { flex: 1, fontSize: 14, color: colors.textMain, paddingVertical: 8 },
  searchClear: { padding: 4 },
  searchBtn: { backgroundColor: colors.primary, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999 },
  searchBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  searchCard: { flexDirection: "row", alignItems: "center", gap: 12, marginHorizontal: spacing.screen, marginBottom: 12, backgroundColor: colors.surface, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: colors.border },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
  avatarText: { fontSize: 18, fontWeight: "900", color: colors.primary },
  userName: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  userCode: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  downlineBadge: { backgroundColor: "#DCFCE7", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999 },
  downlineBadgeText: { fontSize: 9, fontWeight: "900", color: "#065F46", letterSpacing: 0.6 },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.primary, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999 },
  primaryBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  pendingBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: "#FEF3C7" },
  pendingBtnText: { fontSize: 11, fontWeight: "800", color: "#92400E" },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  sectionLabel: { fontSize: 11, fontWeight: "800", letterSpacing: 1.4, color: colors.textMuted, marginBottom: 8 },
  requestCard: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  miniBtn: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  emptyCard: { backgroundColor: colors.surface, borderRadius: radii.card, padding: 28, alignItems: "center", borderWidth: 1, borderColor: colors.border, gap: 6 },
  emptyText: { fontSize: 14, fontWeight: "800", color: colors.textMain, marginTop: 6 },
  emptySub: { fontSize: 12, color: colors.textMuted, textAlign: "center" },
  threadCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  lastMessage: { fontSize: 12, color: colors.textMuted, marginTop: 3 },
  unreadBadge: { backgroundColor: colors.primary, minWidth: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center", paddingHorizontal: 6 },
  unreadText: { fontSize: 11, fontWeight: "900", color: colors.primaryFg },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  modalSheet: { flex: 1, marginTop: 80, backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingTop: 16, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  label: { fontSize: 11, fontWeight: "800", letterSpacing: 1.2, color: colors.textMuted, marginBottom: 6 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: colors.textMain },
});
