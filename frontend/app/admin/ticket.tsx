import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, TextInput, TouchableOpacity, FlatList, KeyboardAvoidingView, Platform, Alert, ActivityIndicator, Image, ScrollView, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams, useFocusEffect } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";

type Msg = { id: string; ticket_id: string; sender_id: string; sender_type: "user" | "admin"; sender_name?: string; sender_email?: string; message: string; attachment_b64?: string | null; created_at: string };
type Ticket = { id: string; subject: string; category: string; priority: string; status: string; user_email?: string; user_name?: string; user_id?: string; assigned_to_email?: string | null; assigned_to?: string | null; message_count: number; created_at: string; updated_at: string };

const STATUSES = ["open", "in_progress", "resolved", "closed"];
const PRIORITIES = ["low", "normal", "high", "urgent"];
const STATUS_META: Record<string, { label: string; bg: string; fg: string }> = {
  open: { label: "Open", bg: "#FFF4E5", fg: "#7A4A0E" },
  in_progress: { label: "In progress", bg: "#E6F1FB", fg: "#1F5E9E" },
  resolved: { label: "Resolved", bg: "#E6F4EE", fg: "#1F6B44" },
  closed: { label: "Closed", bg: "#F1F3F5", fg: "#667085" },
};
const PRIO_COLOR: Record<string, string> = { low: "#667085", normal: "#1F5E9E", high: "#C2410C", urgent: "#B3261E" };

export default function AdminTicketDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sending, setSending] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [reply, setReply] = useState("");
  const [attach, setAttach] = useState<string | null>(null);
  const [actionsOpen, setActionsOpen] = useState(false);
  const listRef = useRef<FlatList<Msg>>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const { data } = await api.get<{ ticket: Ticket; messages: Msg[] }>(`/tickets/${id}`);
      setTicket(data.ticket); setMessages(data.messages || []);
    } catch (e) { Alert.alert("Couldn't load ticket", formatApiError(e)); }
    finally { setLoading(false); setRefreshing(false); }
  }, [id]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  useEffect(() => { setTimeout(() => listRef.current?.scrollToEnd({ animated: false }), 100); }, [messages.length]);

  const pickImage = async () => {
    try {
      const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (status !== "granted") return;
      const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.6, base64: true });
      if (res.canceled || !res.assets?.length) return;
      const a = res.assets[0];
      if (a.base64) setAttach(`data:image/jpeg;base64,${a.base64}`);
    } catch {}
  };

  const onSend = async () => {
    const m = reply.trim();
    if (!m && !attach) return;
    setSending(true);
    try {
      await api.post(`/tickets/${id}/reply`, { message: m, attachment_b64: attach });
      setReply(""); setAttach(null); await load();
    } catch (e) { Alert.alert("Couldn't send", formatApiError(e)); }
    finally { setSending(false); }
  };

  const setStatusTo = async (s: string) => {
    setActionBusy(true);
    try { await api.patch(`/admin/tickets/${id}`, { status: s }); setActionsOpen(false); await load(); }
    catch (e) { Alert.alert("Couldn't update", formatApiError(e)); }
    finally { setActionBusy(false); }
  };

  const setPriorityTo = async (p: string) => {
    setActionBusy(true);
    try { await api.patch(`/admin/tickets/${id}`, { priority: p }); setActionsOpen(false); await load(); }
    catch (e) { Alert.alert("Couldn't update", formatApiError(e)); }
    finally { setActionBusy(false); }
  };

  const assignToMe = async () => {
    if (!user) return;
    setActionBusy(true);
    try { await api.patch(`/admin/tickets/${id}`, { assigned_to: user.id }); setActionsOpen(false); await load(); }
    catch (e) { Alert.alert("Couldn't assign", formatApiError(e)); }
    finally { setActionBusy(false); }
  };

  const unassign = async () => {
    setActionBusy(true);
    try { await api.patch(`/admin/tickets/${id}`, { assigned_to: "" }); setActionsOpen(false); await load(); }
    catch (e) { Alert.alert("Couldn't unassign", formatApiError(e)); }
    finally { setActionBusy(false); }
  };

  if (loading) return <SafeAreaView style={styles.safe} edges={["top"]}><View style={styles.center}><ActivityIndicator size="large" color={colors.primary} /></View></SafeAreaView>;
  if (!ticket) return <SafeAreaView style={styles.safe} edges={["top"]}><View style={styles.center}><Text>Ticket not found</Text></View></SafeAreaView>;

  const st = STATUS_META[ticket.status] || STATUS_META.open;
  const canReply = ticket.status !== "closed";

  const renderMsg = ({ item }: { item: Msg }) => {
    const mine = item.sender_type === "admin";
    return (
      <View style={[styles.msgRow, mine ? styles.msgRowRight : styles.msgRowLeft]}>
        <View style={[styles.msgBubble, mine ? styles.msgBubbleAdmin : styles.msgBubbleUser]}>
          <Text style={styles.msgSender}>{item.sender_type === "admin" ? `${item.sender_name || "Support"} (Admin)` : (item.sender_name || item.sender_email || "User")}</Text>
          {item.attachment_b64 ? <Image source={{ uri: item.attachment_b64 }} style={styles.msgAttach} /> : null}
          {item.message ? <Text style={[styles.msgText, mine && { color: colors.primaryFg }]}>{item.message}</Text> : null}
          <Text style={[styles.msgTime, mine && { color: "rgba(255,255,255,0.7)" }]}>{new Date(item.created_at).toLocaleString()}</Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="admintix-back"><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={styles.title} numberOfLines={1}>{ticket.subject}</Text>
            <Text style={styles.headerSub} numberOfLines={1}>{ticket.user_name || ticket.user_email} · {ticket.category}</Text>
          </View>
          <TouchableOpacity onPress={() => setActionsOpen((v) => !v)} style={styles.iconBtn} testID="admintix-actions-toggle">
            <Feather name={actionsOpen ? "x" : "settings"} size={20} color={colors.textMain} />
          </TouchableOpacity>
        </View>

        <View style={styles.metaBar}>
          <View style={[styles.badge, { backgroundColor: st.bg }]}><Text style={[styles.badgeText, { color: st.fg }]}>{st.label}</Text></View>
          <View style={[styles.prioDot, { backgroundColor: PRIO_COLOR[ticket.priority] || "#667085" }]} />
          <Text style={styles.metaText}>{ticket.priority.toUpperCase()}</Text>
          <Text style={styles.metaText}>· {ticket.assigned_to_email || "unassigned"}</Text>
        </View>

        {actionsOpen && (
          <ScrollView style={{ flexGrow: 0 }} contentContainerStyle={styles.actionsPanel}>
            <Text style={styles.actionsLabel}>STATUS</Text>
            <View style={styles.actionsRow}>
              {STATUSES.map((s) => (
                <TouchableOpacity key={s} onPress={() => setStatusTo(s)} disabled={actionBusy} style={[styles.actionChip, ticket.status === s && styles.actionChipActive]} testID={`admintix-status-${s}`}>
                  <Text style={[styles.actionChipText, ticket.status === s && { color: colors.primaryFg }]}>{STATUS_META[s]?.label || s}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.actionsLabel}>PRIORITY</Text>
            <View style={styles.actionsRow}>
              {PRIORITIES.map((p) => (
                <TouchableOpacity key={p} onPress={() => setPriorityTo(p)} disabled={actionBusy} style={[styles.actionChip, ticket.priority === p && styles.actionChipActive]} testID={`admintix-prio-${p}`}>
                  <Text style={[styles.actionChipText, ticket.priority === p && { color: colors.primaryFg }]}>{p}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <Text style={styles.actionsLabel}>ASSIGN</Text>
            <View style={styles.actionsRow}>
              <TouchableOpacity onPress={assignToMe} disabled={actionBusy} style={styles.actionChip} testID="admintix-assign-me"><Text style={styles.actionChipText}>Assign to me</Text></TouchableOpacity>
              {ticket.assigned_to ? <TouchableOpacity onPress={unassign} disabled={actionBusy} style={styles.actionChip} testID="admintix-unassign"><Text style={styles.actionChipText}>Unassign</Text></TouchableOpacity> : null}
            </View>
          </ScrollView>
        )}

        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(it) => it.id}
          renderItem={renderMsg}
          contentContainerStyle={{ padding: spacing.screen, paddingBottom: 20 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        />

        {canReply && (
          <View style={styles.composer}>
            {attach && (<View style={styles.composerAttach}><Image source={{ uri: attach }} style={{ width: 56, height: 56, borderRadius: 8 }} /><TouchableOpacity onPress={() => setAttach(null)} style={styles.composerRemoveAttach}><Feather name="x" size={14} color="#fff" /></TouchableOpacity></View>)}
            <View style={styles.composerRow}>
              <TouchableOpacity onPress={pickImage} style={styles.composerIconBtn} testID="admintix-attach"><Feather name="paperclip" size={18} color={colors.textMuted} /></TouchableOpacity>
              <TextInput style={styles.composerInput} placeholder="Reply as support..." placeholderTextColor={colors.textMuted} value={reply} onChangeText={setReply} multiline testID="admintix-reply-input" />
              <TouchableOpacity onPress={onSend} disabled={sending || (!reply.trim() && !attach)} style={[styles.sendBtn, (sending || (!reply.trim() && !attach)) && { opacity: 0.5 }]} testID="admintix-send">
                {sending ? <ActivityIndicator color={colors.primaryFg} size="small" /> : <Feather name="send" size={18} color={colors.primaryFg} />}
              </TouchableOpacity>
            </View>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  headerSub: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  metaBar: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 8, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  badge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6 },
  badgeText: { fontSize: 10, fontWeight: "700" },
  metaText: { fontSize: 11, color: colors.textMuted, fontWeight: "600" },
  prioDot: { width: 8, height: 8, borderRadius: 4 },
  actionsPanel: { padding: spacing.screen, backgroundColor: "#FFFBEB", borderBottomWidth: 1, borderBottomColor: "#F4D77A" },
  actionsLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 10, marginBottom: 6 },
  actionsRow: { flexDirection: "row", gap: 6, flexWrap: "wrap" },
  actionChip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  actionChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  actionChipText: { fontSize: 11, fontWeight: "700", color: colors.textMain, textTransform: "capitalize" },
  msgRow: { marginBottom: 10, flexDirection: "row" },
  msgRowLeft: { justifyContent: "flex-start" },
  msgRowRight: { justifyContent: "flex-end" },
  msgBubble: { maxWidth: "82%", padding: 10, borderRadius: 14 },
  msgBubbleAdmin: { backgroundColor: colors.primary, borderBottomRightRadius: 4 },
  msgBubbleUser: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 4 },
  msgSender: { fontSize: 10, fontWeight: "800", color: colors.primary, marginBottom: 4, letterSpacing: 0.5 },
  msgText: { fontSize: 14, color: colors.textMain, lineHeight: 19 },
  msgAttach: { width: 180, height: 180, borderRadius: 10, marginBottom: 6 },
  msgTime: { fontSize: 10, color: colors.textMuted, marginTop: 4 },
  composer: { padding: spacing.screen, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.background },
  composerRow: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  composerIconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  composerInput: { flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 22, paddingHorizontal: 14, paddingVertical: 10, fontSize: 14, color: colors.textMain, maxHeight: 100 },
  sendBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  composerAttach: { position: "relative", alignSelf: "flex-start", marginBottom: 8 },
  composerRemoveAttach: { position: "absolute", top: -4, right: -4, width: 20, height: 20, borderRadius: 10, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center" },
});
