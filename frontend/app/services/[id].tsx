// Service provider profile / ID-card screen — opened when user taps a card
// in the services list. Shows photo, charge, rating, reviews + a CTA to book.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  TextInput,
  RefreshControl,
  Alert,
  Modal,
  Image,
  KeyboardAvoidingView,
  Platform,
  Linking,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialIcons } from "@expo/vector-icons";
import { useLocalSearchParams, router } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing, formatINR } from "../../src/theme";

type Review = {
  id: string;
  rating: number;
  comment?: string | null;
  reviewer_name?: string;
  created_at?: string;
};
type Provider = {
  id: string;
  name: string;
  phone?: string;
  email?: string;
  referral_code?: string;
  service_name?: string;
  service_category?: string;
  service_languages?: string[];
  service_pincode?: string;
  service_charge?: number;
  service_description?: string;
  service_approved_at?: string;
  profile_image?: string | null;
  kyc_status?: string | null;
  is_active?: boolean;
  // June 2026 — provider-controlled status (Available / Busy / Offline).
  availability_status?: "available" | "busy" | "offline" | null;
  rating_avg?: number;
  rating_count?: number;
  bookings_count?: number;
  contacted_count?: number;
  visit_charge?: number;
  can_review?: boolean;
  reviews?: Review[];
};

const LANG_LABEL: Record<string, string> = { en: "English", te: "Telugu", hi: "Hindi", ta: "Tamil" };

export default function ProviderProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const [p, setP] = useState<Provider | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [revealing, setRevealing] = useState(false);
  const [revealedPhone, setRevealedPhone] = useState<string | null>(null);
  const [chatOpening, setChatOpening] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`/services/${id}/profile`);
      setP(data);
    } catch (e) {
      Alert.alert("Failed to load", formatApiError(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id]);

  // Numbers are free since Nov-2026, so a provider the user already asked
  // about simply shows its number again without another round trip.
  useEffect(() => {
    (async () => {
      if (!user || !id) return;
      try {
        const { data } = await api.get("/services/reveal-config");
        if (data?.revealed_provider_ids?.includes(id)) {
          const prof = await api.get(`/services/${id}/profile`);
          setRevealedPhone(prof.data?.phone ?? null);
        }
      } catch {
        // non-fatal — endpoint may 401 on a stale token
      }
    })();
  }, [user, id]);

  useEffect(() => {
    load();
  }, [load]);

  const initials = useMemo(() => {
    const parts = (p?.name || "?").split(" ");
    return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
  }, [p?.name]);

  const submitReview = async () => {
    if (!user) {
      Alert.alert("Login required", "Please log in to leave a review.");
      return;
    }
    setSubmitting(true);
    try {
      await api.post(`/services/${id}/reviews`, { rating, comment: comment.trim() || null });
      setReviewOpen(false);
      setComment("");
      Alert.alert("Thanks!", "Your review was posted.");
      await load();
    } catch (e) {
      Alert.alert("Failed", formatApiError(e));
    } finally {
      setSubmitting(false);
    }
  };

  const handleReveal = async () => {
    if (!user) {
      Alert.alert("Login required", "Please log in to get the provider's phone number.");
      return;
    }
    if (!p) return;
    // Already fetched earlier → just open the dialer.
    if (revealedPhone) {
      Linking.openURL(`tel:${revealedPhone}`).catch(() => Alert.alert("Cannot open dialer"));
      return;
    }
    // Nov-2026 — getting the number is FREE: no fee sheet, no T&C gate, no
    // wallet debit. One tap fetches it and opens the dialer.
    setRevealing(true);
    try {
      const { data } = await api.post<{ provider_phone: string }>(
        `/services/${id}/reveal-phone`, { accept_terms: true },
      );
      setRevealedPhone(data.provider_phone);
      if (data.provider_phone) {
        setTimeout(() => {
          Linking.openURL(`tel:${data.provider_phone}`).catch(() => {});
        }, 300);
      }
    } catch (e) {
      Alert.alert("Couldn't get the number", formatApiError(e));
    } finally {
      setRevealing(false);
    }
  };

  /** Create/reuse the thread and navigate. Assumes access is allowed. */
  const openChatThread = async () => {
    if (!p?.id) return;
    setChatOpening(true);
    try {
      const r = await api.post<{ id: string }>("/chat/threads", { other_user_id: p.id });
      router.push(`/chat/${r.data.id}` as any);
    } catch (e) {
      Alert.alert("Couldn't open chat", formatApiError(e));
    } finally {
      setChatOpening(false);
    }
  };

  /** Nov-2026 — chatting with a provider is free; open the thread directly. */
  const openChat = async () => {
    if (!user) {
      Alert.alert("Login required", "Please log in to chat with this provider.");
      return;
    }
    openChatThread();
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }
  if (!p) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><Text>Not found.</Text></View></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={22} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.headerTitle}>Service Provider</Text>
        <View style={{ width: 40 }} />
      </View>

      <ScrollView
        contentContainerStyle={{ paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        {/* ID-card hero */}
        <View style={styles.heroCard}>
          <View style={styles.heroLeft}>
            {p.profile_image ? (
              <Image source={{ uri: p.profile_image }} style={styles.heroAvatar} />
            ) : (
              <View style={[styles.heroAvatar, { backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" }]}>
                <Text style={{ color: "#fff", fontWeight: "900", fontSize: 28 }}>{initials}</Text>
              </View>
            )}
            {(() => {
              const av = (p.availability_status || "available") as "available" | "busy" | "offline";
              const c = av === "available" ? "#16A34A" : av === "busy" ? "#F59E0B" : "#6B7280";
              return <View style={[styles.statusDot, { backgroundColor: c }]} />;
            })()}
          </View>
          <View style={styles.heroBody}>
            <Text style={styles.heroName} numberOfLines={2}>{p.name}</Text>
            <Text style={styles.heroService} numberOfLines={2}>{p.service_name || "—"}</Text>
            {p.service_category ? <Text style={styles.heroCategory}>{p.service_category}</Text> : null}
            {(() => {
              const av = (p.availability_status || "available") as "available" | "busy" | "offline";
              const meta = av === "available"
                ? { c: "#16A34A", bg: "#DCFCE7", t: "AVAILABLE NOW" }
                : av === "busy"
                ? { c: "#B45309", bg: "#FEF3C7", t: "BUSY · MAY DELAY" }
                : { c: "#374151", bg: "#E5E7EB", t: "OFFLINE" };
              return (
                <View style={{
                  alignSelf: "flex-start",
                  flexDirection: "row", alignItems: "center", gap: 4,
                  backgroundColor: meta.bg,
                  paddingHorizontal: 8, paddingVertical: 3,
                  borderRadius: 10,
                  marginTop: 6,
                }}>
                  <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: meta.c }} />
                  <Text style={{ fontSize: 10, fontWeight: "900", letterSpacing: 0.5, color: meta.c }}>
                    {meta.t}
                  </Text>
                </View>
              );
            })()}
            <View style={styles.ratingRow}>
              {[1,2,3,4,5].map((i) => (
                <Feather
                  key={i}
                  name={i <= Math.round(p.rating_avg || 0) ? "star" : "star"}
                  size={14}
                  color={i <= Math.round(p.rating_avg || 0) ? "#F59E0B" : colors.border}
                />
              ))}
              <Text style={styles.ratingText}>
                {(p.rating_avg || 0).toFixed(1)} <Text style={{ color: colors.textMuted, fontWeight: "600" }}>({p.rating_count || 0} reviews)</Text>
              </Text>
            </View>
            {p.kyc_status === "approved" ? (
              <View style={styles.kycChip}>
                <Feather name="shield" size={10} color="#0F766E" />
                <Text style={styles.kycChipText}>KYC VERIFIED</Text>
              </View>
            ) : null}
          </View>
        </View>

        {/* Key facts grid */}
        <View style={styles.factsRow}>
          <View style={styles.factCard}>
            <Feather name="map-pin" size={14} color={colors.primary} />
            <Text style={styles.factLabel}>Pincode</Text>
            <Text style={styles.factValue}>{p.service_pincode || "—"}</Text>
          </View>
          <View style={styles.factCard}>
            <MaterialIcons name="currency-rupee" size={16} color={colors.primary} />
            <Text style={styles.factLabel}>Visit charges</Text>
            <Text style={styles.factValue} testID="provider-visit-charge">
              {(p.visit_charge ?? p.service_charge) ? formatINR(p.visit_charge ?? p.service_charge ?? 0) : "On request"}
            </Text>
          </View>
          <View style={styles.factCard}>
            <Feather name="check-circle" size={14} color={colors.primary} />
            <Text style={styles.factLabel}>Contacted</Text>
            <Text style={styles.factValue} testID="provider-contacted-count">{p.contacted_count ?? p.bookings_count ?? 0}</Text>
          </View>
        </View>

        {(p.service_languages || []).length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>SPEAKS</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {(p.service_languages || []).map((l) => (
                <View key={l} style={styles.langChip}><Text style={styles.langChipText}>{LANG_LABEL[l] || l.toUpperCase()}</Text></View>
              ))}
            </View>
          </View>
        ) : null}

        {p.service_description ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>ABOUT</Text>
            <Text style={styles.aboutText}>{p.service_description}</Text>
          </View>
        ) : null}

        {/* Reviews section */}
        <View style={[styles.section, { marginBottom: 80 }]}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <Text style={styles.sectionTitle}>REVIEWS ({p.rating_count || 0})</Text>
            {user && (p.can_review || revealedPhone) ? (
              <TouchableOpacity onPress={() => setReviewOpen(true)} style={styles.writeBtn} testID="write-review-btn">
                <Feather name="edit-3" size={12} color={colors.primary} />
                <Text style={styles.writeBtnText}>Write review</Text>
              </TouchableOpacity>
            ) : user ? (
              <Text style={styles.writeHint} testID="review-hint">Get the number to review</Text>
            ) : null}
          </View>
          {(p.reviews || []).length === 0 ? (
            <View style={styles.emptyCard}>
              <Feather name="message-square" size={26} color={colors.textMuted} />
              <Text style={styles.emptyText}>No reviews yet. Be the first to share your experience.</Text>
            </View>
          ) : (
            (p.reviews || []).map((r) => (
              <View key={r.id} style={styles.reviewCard}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <View style={styles.reviewerAvatar}><Text style={styles.reviewerAvatarText}>{(r.reviewer_name || "C").charAt(0).toUpperCase()}</Text></View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.reviewerName}>{r.reviewer_name || "Customer"}</Text>
                    <View style={{ flexDirection: "row", gap: 1, marginTop: 2 }}>
                      {[1,2,3,4,5].map((i) => (
                        <Feather key={i} name="star" size={11} color={i <= r.rating ? "#F59E0B" : colors.border} />
                      ))}
                    </View>
                  </View>
                  {r.created_at ? <Text style={styles.reviewDate}>{new Date(r.created_at).toLocaleDateString()}</Text> : null}
                </View>
                {r.comment ? <Text style={styles.reviewComment}>{r.comment}</Text> : null}
              </View>
            ))
          )}
        </View>
      </ScrollView>

      {/* Sticky action bar — info line on top, two equal-width buttons below.
          Was a single row with a flexible price block plus two fixed-width
          pills, which overflowed and looked messy on small phones. */}
      <View style={[styles.ctaBar, { paddingBottom: Math.max(insets.bottom, 12) + 8 }]}>
        <View style={styles.ctaInfoRow}>
          {revealedPhone ? (
            <>
              <Feather name="phone-call" size={14} color={colors.primary} />
              <Text style={styles.ctaPhone} numberOfLines={1}>{revealedPhone}</Text>
            </>
          ) : (
            /* Nov-2026 — every customer gets the number free. */
            <>
              <Feather name="check-circle" size={14} color={colors.success} />
              <Text style={[styles.ctaPrice, { color: colors.success }]} numberOfLines={1}>FREE</Text>
              <Text style={styles.ctaSub} numberOfLines={1}>no charge to call or chat</Text>
            </>
          )}
        </View>
        <View style={styles.ctaBtnRow}>
          <TouchableOpacity
            onPress={handleReveal}
            disabled={revealing}
            style={[styles.ctaBtn, revealing && { opacity: 0.6 }]}
            testID="get-phone-btn"
          >
            {revealing
              ? <ActivityIndicator color="#fff" size="small" />
              : <Feather name={revealedPhone ? "phone-call" : "phone"} size={15} color="#fff" />}
            <Text style={styles.ctaBtnText} numberOfLines={1}>
              {revealing ? "Getting…" : revealedPhone ? "Call now" : "Get Phone Number"}
            </Text>
          </TouchableOpacity>
          {p?.id ? (
            <TouchableOpacity
              onPress={openChat}
              disabled={chatOpening}
              style={[styles.ctaBtn, { backgroundColor: "#16A34A" }, chatOpening && { opacity: 0.6 }]}
              testID="start-chat-btn"
            >
              {chatOpening
                ? <ActivityIndicator color="#fff" size="small" />
                : <Feather name="message-circle" size={15} color="#fff" />}
              <Text style={styles.ctaBtnText} numberOfLines={1}>{chatOpening ? "Opening…" : "Start Chat"}</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </View>

      {/* Review modal */}
      <Modal visible={reviewOpen} transparent animationType="slide" onRequestClose={() => setReviewOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
          <View style={styles.modalBg}>
            <View style={styles.modalSheet}>
              <View style={styles.modalHandle} />
              <Text style={styles.modalTitle}>Rate this provider</Text>
              <View style={{ flexDirection: "row", justifyContent: "center", gap: 6, marginTop: 12 }}>
                {[1,2,3,4,5].map((i) => (
                  <TouchableOpacity key={i} onPress={() => setRating(i)} testID={`rate-${i}`}>
                    <Feather name="star" size={36} color={i <= rating ? "#F59E0B" : colors.border} />
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.modalLabel}>Your comments (optional)</Text>
              <TextInput
                multiline
                value={comment}
                onChangeText={setComment}
                placeholder="Tell others about your experience…"
                placeholderTextColor={colors.textMuted}
                style={styles.modalInput}
                maxLength={1000}
                testID="review-comment"
              />
              <TouchableOpacity onPress={submitReview} disabled={submitting} style={[styles.modalBtn, submitting && { opacity: 0.6 }]} testID="submit-review">
                <Text style={styles.modalBtnText}>{submitting ? "Posting…" : "Post review"}</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => setReviewOpen(false)} style={{ paddingVertical: 10, alignItems: "center" }}>
                <Text style={{ color: colors.textMuted, fontWeight: "700" }}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain },
  heroCard: { flexDirection: "row", margin: spacing.screen, padding: 16, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, gap: 14 },
  heroLeft: { position: "relative" },
  heroAvatar: { width: 80, height: 80, borderRadius: 40, backgroundColor: colors.surfaceMuted },
  statusDot: { width: 14, height: 14, borderRadius: 7, position: "absolute", right: 0, bottom: 4, borderWidth: 2, borderColor: colors.surface },
  heroBody: { flex: 1, minWidth: 0 },
  heroName: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  heroService: { fontSize: 14, fontWeight: "700", color: colors.primary, marginTop: 2 },
  heroCategory: { fontSize: 11, color: colors.textMuted, marginTop: 2, fontWeight: "600", textTransform: "uppercase", letterSpacing: 0.5 },
  ratingRow: { flexDirection: "row", alignItems: "center", gap: 2, marginTop: 8 },
  ratingText: { fontSize: 12, fontWeight: "800", color: colors.textMain, marginLeft: 4 },
  kycChip: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: "#E6F8F1", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, marginTop: 8 },
  kycChipText: { fontSize: 9, fontWeight: "900", letterSpacing: 0.5, color: "#0F766E" },
  factsRow: { flexDirection: "row", gap: 8, marginHorizontal: spacing.screen, marginBottom: 12 },
  factCard: { flex: 1, padding: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, alignItems: "center", gap: 4 },
  factLabel: { fontSize: 9, color: colors.textMuted, fontWeight: "800", letterSpacing: 0.5 },
  factValue: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  section: { paddingHorizontal: spacing.screen, marginBottom: 12 },
  sectionTitle: { fontSize: 11, color: colors.textMuted, fontWeight: "900", letterSpacing: 1, marginBottom: 8 },
  aboutText: { fontSize: 14, color: colors.textMain, lineHeight: 20 },
  langChip: { backgroundColor: colors.surfaceMuted, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  langChipText: { fontSize: 11, fontWeight: "700", color: colors.textMain },
  writeBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: colors.brand100, borderRadius: 999 },
  writeHint: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  writeBtnText: { fontSize: 11, color: colors.primary, fontWeight: "800" },
  emptyCard: { paddingVertical: 24, alignItems: "center", gap: 6 },
  emptyText: { fontSize: 12, color: colors.textMuted, textAlign: "center" },
  reviewCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 12, marginBottom: 8 },
  reviewerAvatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  reviewerAvatarText: { color: "#fff", fontWeight: "900", fontSize: 13 },
  reviewerName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  reviewDate: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  reviewComment: { fontSize: 13, color: colors.textMain, marginTop: 8, lineHeight: 18 },
  ctaBar: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: spacing.screen, paddingTop: 10, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border, gap: 10 },
  ctaInfoRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  ctaPrice: { fontSize: 16, fontWeight: "900", color: colors.textMain },
  ctaPhone: { fontSize: 15, fontWeight: "900", color: colors.textMain, letterSpacing: 0.4 },
  ctaSub: { flex: 1, fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  ctaBtnRow: { flexDirection: "row", gap: 10 },
  ctaBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.primary, paddingHorizontal: 12, minHeight: 50, borderRadius: 999 },
  ctaBtnText: { color: "#fff", fontWeight: "900", fontSize: 13.5, letterSpacing: 0.2 },
  // Review modal
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.background, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 18, paddingTop: 8, paddingBottom: 24 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 12 },
  modalTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain, textAlign: "center" },
  modalLabel: { fontSize: 12, fontWeight: "800", color: colors.textMuted, marginTop: 16, marginBottom: 6, letterSpacing: 0.5 },
  modalInput: { borderWidth: 1, borderColor: colors.border, borderRadius: 12, padding: 12, minHeight: 90, textAlignVertical: "top", fontSize: 14, color: colors.textMain, backgroundColor: colors.surface },
  modalBtn: { backgroundColor: colors.primary, paddingVertical: 14, borderRadius: 999, alignItems: "center", marginTop: 14 },
  modalBtnText: { color: "#fff", fontWeight: "900", fontSize: 14, letterSpacing: 0.3 },
  // Get-Phone-Number flow
  revealHero: { alignItems: "center", marginBottom: 16 },
  revealHeroIcon: { width: 60, height: 60, borderRadius: 30, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center", marginBottom: 12 },
  revealSubtitle: { fontSize: 13, color: colors.textMuted, textAlign: "center", marginTop: 8, paddingHorizontal: 12, lineHeight: 19 },
  feeCard: { backgroundColor: colors.surfaceMuted, padding: 14, borderRadius: 14, marginVertical: 12 },
  feeRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 6 },
  feeLabel: { fontSize: 13, color: colors.textMain, fontWeight: "600" },
  feeValue: { fontSize: 13, color: colors.textMain, fontWeight: "800" },
  feeTotalRow: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: 4, paddingTop: 10 },
  feeTotalLabel: { fontSize: 14, color: colors.textMain, fontWeight: "900" },
  feeTotalValue: { fontSize: 16, color: colors.primary, fontWeight: "900" },
  tncRow: { flexDirection: "row", alignItems: "flex-start", gap: 10, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 12 },
  tncRowOn: { borderColor: colors.primary, backgroundColor: colors.brand100 },
  tncBox: { width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center", marginTop: 1, backgroundColor: colors.surface },
  tncBoxOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tncText: { flex: 1, fontSize: 12, color: colors.textMuted, lineHeight: 18 },
});
