import { useState, useEffect, useCallback } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Alert,
  RefreshControl,
  Image,
  Modal,
  Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "../../src/api";
import { useAuth } from "../../src/auth";
import { colors, radii, spacing } from "../../src/theme";
import { ConfirmDialog } from "../../src/confirm-dialog";
import { GradientCard } from "../../src/gradient-card";
import { useBackToInitialTab } from "../../src/use-double-tap-exit";

export default function ProfileScreen() {
  useBackToInitialTab();
  const {
    user,
    logout,
    refresh,
    biometricAvailable,
    biometricReady,
    enableBiometric,
    disableBiometric,
  } = useAuth();
  const router = useRouter();
  const [upi, setUpi] = useState("");
  const [bank, setBank] = useState("");
  const [ifsc, setIfsc] = useState("");
  const [holder, setHolder] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [bioBusy, setBioBusy] = useState(false);
  // Profile picture upload state — both for picking + viewing.
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarPreviewOpen, setAvatarPreviewOpen] = useState(false);
  const profileImage = (user as any)?.profile_image || null;

  // Pick an image from the gallery → downscale & compress → POST as base64
  // data URI. The compression step keeps payloads well under our 1 MB
  // server cap and reduces upload time on slow connections.
  const onPickAvatar = useCallback(async () => {
    try {
      // Ask for gallery permission (camera-roll). We don't request camera
      // here — gallery is enough for a single profile picture.
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert(
          "Photo access needed",
          "Please allow photo access from settings so you can pick a profile picture.",
        );
        return;
      }
      const r = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.9,
      });
      if (r.canceled || !r.assets?.length) return;
      setAvatarUploading(true);
      // Downscale to 720x720 max + JPEG-recompress @ 0.7 quality so the
      // base64 payload stays under our 1 MB cap.
      const manipulated = await ImageManipulator.manipulateAsync(
        r.assets[0].uri,
        [{ resize: { width: 720, height: 720 } }],
        { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true },
      );
      const dataUrl = `data:image/jpeg;base64,${manipulated.base64}`;
      await api.post("/users/me/profile-image", { image_data_url: dataUrl });
      await refresh();
    } catch (e: any) {
      Alert.alert("Couldn't update photo", formatApiError(e));
    } finally {
      setAvatarUploading(false);
    }
  }, [refresh]);

  const onRemoveAvatar = useCallback(() => {
    Alert.alert("Remove profile photo?", "Your avatar will fall back to the first letter of your name.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Remove",
        style: "destructive",
        onPress: async () => {
          try {
            setAvatarUploading(true);
            await api.delete("/users/me/profile-image");
            await refresh();
          } catch (e: any) {
            Alert.alert("Couldn't remove photo", formatApiError(e));
          } finally {
            setAvatarUploading(false);
          }
        },
      },
    ]);
  }, [refresh]);

  // Nov-2026 — fingerprint changes are confirmed in a compact in-app dialog
  // instead of the stock OS alert, and the result is reported the same way.
  const [bioDialog, setBioDialog] = useState<null | "enable" | "disable" | "done-on" | "done-off" | "error">(null);
  const [bioError, setBioError] = useState("");

  const onToggleBiometric = useCallback(() => {
    setBioDialog(biometricReady ? "disable" : "enable");
  }, [biometricReady]);

  const applyBiometricChange = useCallback(async () => {
    const turningOn = bioDialog === "enable";
    setBioBusy(true);
    try {
      if (turningOn) await enableBiometric();
      else await disableBiometric();
      setBioDialog(turningOn ? "done-on" : "done-off");
    } catch (e: any) {
      setBioError(e?.message || "Your device did not confirm the change.");
      setBioDialog("error");
    } finally {
      setBioBusy(false);
    }
  }, [bioDialog, enableBiometric, disableBiometric]);

  // ── Profile-picture privacy (June 2026) ─────────────────────────────
  // Normal users can choose: everyone / accepted_requests.
  // Service Providers + Vendors are locked to "everyone" by the backend.
  const [privacyVis, setPrivacyVis] = useState<string>(((user as any)?.profile_visibility) || "everyone");
  const [privacyLocked, setPrivacyLocked] = useState<boolean>(false);
  // Sep-2026 — an approved delivery partner is a rider, never a seller, so
  // the vendor / service-provider entries are hidden for him.
  const isApprovedDP = !!(user as any)?.is_delivery_partner_approved;
  // Oct-2026 — only people we actually pay out to see PAYOUT DETAILS:
  // approved sellers, delivery partners and admins. A shopper's wallet is
  // spent inside the app, so bank/UPI fields only confuse them.
  const canPayout = !!(
    ((user as any)?.is_vendor && (user as any)?.is_vendor_approved)
    || (user as any)?.is_delivery_partner
    || (user as any)?.role === "admin"
  );
  const [privacySaving, setPrivacySaving] = useState<string | null>(null);
  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/users/me/privacy");
        setPrivacyVis(r.data?.profile_visibility || "everyone");
        setPrivacyLocked(!!r.data?.locked);
      } catch {}
    })();
  }, [user?.id]);
  const onSetPrivacy = useCallback(async (level: "everyone" | "accepted_requests") => {
    if (privacyLocked || level === privacyVis) return;
    setPrivacySaving(level);
    try {
      const r = await api.patch("/users/me/privacy", { profile_visibility: level });
      setPrivacyVis(r.data?.profile_visibility || level);
    } catch (e: any) {
      Alert.alert("Couldn't update", e?.response?.data?.detail || "Try again.");
    } finally {
      setPrivacySaving(null);
    }
  }, [privacyLocked, privacyVis]);

  useEffect(() => {
    setUpi(user?.upi_id || "");
    setBank(user?.bank_account || "");
    setIfsc(user?.ifsc || "");
    setHolder(user?.account_holder || "");
  }, [user]);

  const onSave = async () => {
    setSaving(true);
    setMsg("");
    try {
      await api.post("/users/me/bank", {
        upi_id: upi.trim() || null,
        bank_account: bank.trim() || null,
        ifsc: ifsc.trim() || null,
        account_holder: holder.trim() || null,
      });
      await refresh();
      setMsg("Saved successfully");
    } catch (e) {
      setMsg(formatApiError(e));
    } finally {
      setSaving(false);
    }
  };

  const onLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try { await refresh(); } finally { setRefreshing(false); }
  }, [refresh]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <ScrollView
          contentContainerStyle={styles.container}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
        >
          <GradientCard variant="royal" style={{ marginBottom: spacing.cardPad, padding: 24 }}>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              {/* Avatar: tap to view full size, long-press / camera icon to upload.
                  When `profile_image` is set we render the actual photo; else
                  we fall back to the first-letter circle so the layout never
                  collapses. */}
              {/* June 2026 — avatar UX: TAP always opens the picker (so users
                  immediately understand they can change their photo). LONG-PRESS
                  on an existing photo opens the full-screen preview (zoom).
                  Previously tapping opened the preview, which made the upload
                  affordance invisible. */}
              <View style={{ position: "relative", marginRight: 16 }}>
                <TouchableOpacity
                  activeOpacity={0.8}
                  onPress={onPickAvatar}
                  onLongPress={profileImage ? () => setAvatarPreviewOpen(true) : undefined}
                  style={{ width: 64, height: 64, borderRadius: 32, backgroundColor: "rgba(255,255,255,0.2)", alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "rgba(255,255,255,0.4)", overflow: "hidden" }}
                  testID="profile-avatar"
                >
                  {avatarUploading ? (
                    <ActivityIndicator color="#fff" />
                  ) : profileImage ? (
                    <Image source={{ uri: profileImage }} style={{ width: "100%", height: "100%" }} resizeMode="cover" />
                  ) : (
                    <Text style={{ fontSize: 28, fontWeight: "800", color: "#fff" }}>{(user?.name || "U").charAt(0).toUpperCase()}</Text>
                  )}
                </TouchableOpacity>
                {/* Camera badge — pure visual cue that the avatar is editable. */}
                {!avatarUploading ? (
                  <View
                    pointerEvents="none"
                    style={{
                      position: "absolute",
                      right: -2, bottom: -2,
                      width: 22, height: 22, borderRadius: 11,
                      backgroundColor: "#FFFFFF",
                      alignItems: "center", justifyContent: "center",
                      borderWidth: 2, borderColor: colors.primary,
                    }}
                  >
                    <Feather name="camera" size={11} color={colors.primary} />
                  </View>
                ) : null}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.7)", fontWeight: "700" }}>PROFILE</Text>
                <Text style={{ fontSize: 22, fontWeight: "800", color: "#fff", letterSpacing: -0.5, marginTop: 4 }} numberOfLines={1}>{user?.name}</Text>
                <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.85)", marginTop: 2 }} numberOfLines={1}>{user?.email}</Text>
                <TouchableOpacity
                  onPress={onPickAvatar}
                  style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, alignSelf: "flex-start", backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8 }}
                  testID="profile-avatar-edit"
                >
                  <Feather name="camera" size={12} color="#fff" />
                  <Text style={{ fontSize: 11, color: "#fff", fontWeight: "800", letterSpacing: 0.3 }}>
                    {profileImage ? "CHANGE PHOTO" : "ADD PHOTO"}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
            <View style={{ flexDirection: "row", marginTop: 16, gap: 8 }}>
              {(user as any)?.is_vendor && (
                <View style={{ backgroundColor: "rgba(255,255,255,0.18)", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, justifyContent: "center" }}>
                  <Text style={{ fontSize: 11, fontWeight: "700", color: "#fff", letterSpacing: 0.5 }}>🛍️ VENDOR</Text>
                </View>
              )}
            </View>
          </GradientCard>

          {/* ───── ACCOUNT GROUP ───── */}
          <Text style={styles.groupLabel}>ACCOUNT</Text>
          <View style={styles.groupCard}>
            <TouchableOpacity onPress={() => router.push("/personal-info" as any)} style={styles.rowItem} testID="profile-personal-info-link">
              <View style={[styles.kycDot, { backgroundColor: ((user as any)?.phone_verified && (user as any)?.kyc_status === "approved") ? colors.success : colors.warning }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Personal Information</Text>
                <Text style={styles.kycSub}>MOBILE NUMBER · KYC VERIFICATION · ADDRESS</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/tickets" as any)} style={styles.rowItem} testID="profile-tickets-link">
              <View style={[styles.kycDot, { backgroundColor: colors.primary }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Support &amp; Help</Text>
                <Text style={styles.kycSub}>RAISE A TICKET · MY CONVERSATIONS</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/account-deletion" as any)} style={styles.rowItem} testID="profile-delete-account-link">
              <View style={[styles.kycDot, { backgroundColor: colors.error }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Delete my account</Text>
                <Text style={styles.kycSub}>REQUEST REMOVAL · REVIEWED BY OUR TEAM</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/login-history" as any)} style={styles.rowItem} testID="profile-login-history-link">
              <View style={[styles.kycDot, { backgroundColor: "#8B5CF6" }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Login activity</Text>
                <Text style={styles.kycSub}>DEVICES SIGNED IN · SIGN OTHERS OUT</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/notification-settings" as any)} style={styles.rowItem} testID="profile-notifications-link">
              <View style={[styles.kycDot, { backgroundColor: "#F59E0B" }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Notifications</Text>
                <Text style={styles.kycSub}>ORDERS · CHATS · OFFERS</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity onPress={() => router.push("/more" as any)} style={styles.rowItem} testID="profile-more-link">
              <View style={[styles.kycDot, { backgroundColor: colors.textMuted }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>More</Text>
                <Text style={styles.kycSub}>ABOUT · CONTACT · LEGAL &amp; POLICIES</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          </View>

          {/* ───── SELL ON SLANGCART GROUP ─────
              Sep-2026 — an APPROVED delivery partner is a rider, not a
              seller: the "Become a Vendor" / "Become a Service Provider"
              entries are hidden for him (owner's rule) and replaced by a
              link to his delivery dashboard. */}
          {isApprovedDP ? (
            <>
              <Text style={styles.groupLabel}>DELIVERY</Text>
              <View style={styles.groupCard}>
                <TouchableOpacity
                  onPress={() => router.push("/delivery/dashboard" as any)}
                  style={styles.rowItem}
                  testID="profile-delivery-link"
                >
                  <View style={[styles.kycDot, { backgroundColor: colors.success }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.kycTitle}>Delivery Partner</Text>
                    <Text style={styles.kycSub}>APPROVED · TAP TO OPEN DASHBOARD</Text>
                  </View>
                  <Feather name="chevron-right" size={18} color={colors.textMuted} />
                </TouchableOpacity>
              </View>
            </>
          ) : (
          <>
          <Text style={styles.groupLabel}>SELL ON SLANGCART</Text>
          <View style={styles.groupCard}>
            <TouchableOpacity
              onPress={() => router.push("/delivery/apply" as any)}
              style={styles.rowItem}
              testID="profile-delivery-apply-link"
            >
              {(() => {
                const st = (user as any)?.dp_status as string | undefined;
                const dot = st === "pending" ? colors.warning
                  : st === "rejected" ? "#B3261E" : "#94A3B8";
                return <View style={[styles.kycDot, { backgroundColor: dot }]} />;
              })()}
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>Become a Delivery Partner</Text>
                <Text style={styles.kycSub}>
                  {(user as any)?.dp_status === "pending" ? "APPLICATION UNDER REVIEW"
                    : (user as any)?.dp_status === "rejected" ? "APPLY AGAIN"
                    : "DELIVER ORDERS IN YOUR AREA"}
                </Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            <TouchableOpacity
              onPress={() => {
                const u: any = user;
                const isApprovedVendor = !!(u?.is_vendor_approved || (u?.is_vendor && u?.vendor_status === "approved"));
                router.push((isApprovedVendor ? "/vendor/dashboard" : "/vendor/apply") as any);
              }}
              style={styles.rowItem}
              testID="profile-vendor-link"
            >
              {(() => {
                const u: any = user;
                const isApprovedVendor = !!(u?.is_vendor_approved || (u?.is_vendor && u?.vendor_status === "approved"));
                const st = u?.vendor_status as string | null | undefined;
                const dot = isApprovedVendor ? colors.success
                  : st === "pending" ? colors.warning
                  : st === "suspended" ? "#B3261E"
                  : "#94A3B8";
                return <View style={[styles.kycDot, { backgroundColor: dot }]} />;
              })()}
              <View style={{ flex: 1 }}>
                {(() => {
                  const u: any = user;
                  const isApprovedVendor = !!(u?.is_vendor_approved || (u?.is_vendor && u?.vendor_status === "approved"));
                  const businessName = u?.vendor_business_name || u?.shop_name;
                  return (
                    <>
                      <Text style={styles.kycTitle}>
                        {isApprovedVendor ? (businessName ? `Vendor · ${businessName}` : "Vendor Panel") : "Become a Vendor"}
                      </Text>
                      <Text style={styles.kycSub}>
                        {isApprovedVendor ? "APPROVED · TAP TO OPEN DASHBOARD" : (u?.vendor_status ? String(u.vendor_status).toUpperCase() : "SELL ON OUR PLATFORM")}
                      </Text>
                    </>
                  );
                })()}
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.rowDivider} />
            {/* Service Provider entry — moved here from the Services tab banner.
                Reads the canonical `service_status` + `is_service_provider` fields
                set by the apply/approve/reject backend flows. */}
            <TouchableOpacity
              onPress={() => router.push("/services/apply" as any)}
              style={styles.rowItem}
              testID="profile-service-provider-link"
            >
              {(() => {
                const isProv = !!(user as any)?.is_service_provider;
                const st = (user as any)?.service_status as string | null | undefined;
                const dotColor = isProv ? colors.success
                  : st === "pending"  ? colors.warning
                  : st === "rejected" ? "#B3261E"
                  : "#94A3B8";
                return <View style={[styles.kycDot, { backgroundColor: dotColor }]} />;
              })()}
              <View style={{ flex: 1 }}>
                <Text style={styles.kycTitle}>
                  {(user as any)?.is_service_provider ? "You're a Service Provider" : "Become a Service Provider"}
                </Text>
                <Text style={styles.kycSub}>
                  {(user as any)?.is_service_provider ? "TAP TO UPDATE OR VIEW BOOKINGS"
                    : (user as any)?.service_status === "pending" ? "APPLICATION UNDER REVIEW"
                    : (user as any)?.service_status === "rejected" ? "APPLY AGAIN"
                    : "LIST YOUR SERVICE"}
                </Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            {/* Provider availability — only relevant when already an approved service provider. */}
            {(user as any)?.is_service_provider ? (
              <>
                <View style={styles.rowDivider} />
                <TouchableOpacity
                  onPress={() => router.push("/service-availability" as any)}
                  style={styles.rowItem}
                  testID="profile-availability-link"
                >
                  {(() => {
                    const av = (user as any)?.availability_status || "available";
                    const c = av === "available" ? "#16A34A" : av === "busy" ? "#F59E0B" : "#9CA3AF";
                    return <View style={[styles.kycDot, { backgroundColor: c }]} />;
                  })()}
                  <View style={{ flex: 1 }}>
                    <Text style={styles.kycTitle}>My Availability</Text>
                    <Text style={styles.kycSub}>
                      {((user as any)?.availability_status || "available").toUpperCase()} — TAP TO CHANGE
                    </Text>
                  </View>
                  <Feather name="chevron-right" size={18} color={colors.textMuted} />
                </TouchableOpacity>
              </>
            ) : null}
          </View>
          </>
          )}

          {/* ───── PRIVACY GROUP (June 2026) ─────
              Lets normal users restrict who can see their profile picture.
              Service Providers + Vendors are server-locked to "Everyone"
              so customers can identify them — we surface a friendly notice
              instead of the options. */}
          <Text style={styles.groupLabel}>PRIVACY</Text>
          <View style={[styles.payoutCard, { paddingVertical: 14 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <Feather name="eye" size={14} color={colors.primary} />
              <Text style={styles.kycTitle}>Profile picture visibility</Text>
            </View>
            {privacyLocked ? (
              <View style={{ backgroundColor: colors.brand100, padding: 12, borderRadius: 10, marginTop: 6 }}>
                <Text style={{ fontSize: 12, color: colors.primary, fontWeight: "700", marginBottom: 4 }}>
                  ALWAYS VISIBLE
                </Text>
                <Text style={{ fontSize: 12, color: colors.textMain, lineHeight: 18 }}>
                  Your profile picture is always visible to everyone so customers can easily identify and contact you.
                </Text>
              </View>
            ) : (
              <View style={{ marginTop: 8, gap: 6 }}>
                {([
                  { value: "everyone",          label: "Everyone",                  sub: "All app users can see your photo.", icon: "globe" },
                  { value: "accepted_requests", label: "Accepted Message Requests", sub: "Only chats you've accepted.",       icon: "message-square" },
                ] as const).map((opt) => {
                  const active = privacyVis === opt.value;
                  const saving = privacySaving === opt.value;
                  return (
                    <TouchableOpacity
                      key={opt.value}
                      onPress={() => onSetPrivacy(opt.value)}
                      disabled={!!privacySaving}
                      activeOpacity={0.85}
                      style={{
                        flexDirection: "row", alignItems: "center", gap: 12,
                        padding: 12, borderRadius: 10,
                        borderWidth: 1,
                        borderColor: active ? colors.primary : colors.border,
                        backgroundColor: active ? colors.brand100 : colors.surface,
                      }}
                      testID={`privacy-${opt.value}`}
                    >
                      <View style={{ width: 20, height: 20, borderRadius: 10, borderWidth: 2, borderColor: active ? colors.primary : colors.border, alignItems: "center", justifyContent: "center" }}>
                        {active ? <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: colors.primary }} /> : null}
                      </View>
                      <Feather name={opt.icon as any} size={16} color={active ? colors.primary : colors.textMuted} />
                      <View style={{ flex: 1 }}>
                        <Text style={{ fontSize: 13, fontWeight: "700", color: colors.textMain }}>{opt.label}</Text>
                        <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 1 }}>{opt.sub}</Text>
                      </View>
                      {saving ? <ActivityIndicator size="small" color={colors.primary} /> : null}
                    </TouchableOpacity>
                  );
                })}
                <Text style={{ fontSize: 10, color: colors.textMuted, marginTop: 4, lineHeight: 16 }}>
                  When hidden, others will see your default avatar with your initial. Service providers and vendors are always public.
                </Text>
              </View>
            )}
          </View>

          {canPayout ? (
          <>
          <Text style={styles.groupLabel}>PAYOUT DETAILS</Text>
          <View style={styles.payoutCard}>
            <Text style={styles.helperText}>Add UPI or bank details to enable withdrawals.</Text>

            <View style={styles.formGroup}>
              <Text style={styles.label}>UPI ID</Text>
              <TextInput testID="profile-upi" value={upi} onChangeText={setUpi} placeholder="name@upi" placeholderTextColor={colors.textMuted} autoCapitalize="none" style={styles.input} />
            </View>
            <View style={styles.formGroup}>
              <Text style={styles.label}>Bank account number</Text>
              <TextInput testID="profile-bank" value={bank} onChangeText={setBank} placeholder="XXXXXXXXXX" placeholderTextColor={colors.textMuted} keyboardType="numeric" style={styles.input} />
            </View>
            <View style={styles.formGroup}>
              <Text style={styles.label}>IFSC code</Text>
              <TextInput testID="profile-ifsc" value={ifsc} onChangeText={(t) => setIfsc(t.toUpperCase())} placeholder="HDFC0000123" placeholderTextColor={colors.textMuted} autoCapitalize="characters" style={styles.input} />
            </View>
            <View style={styles.formGroup}>
              <Text style={styles.label}>Account holder name</Text>
              <TextInput testID="profile-holder" value={holder} onChangeText={setHolder} placeholder="As per bank record" placeholderTextColor={colors.textMuted} style={styles.input} />
            </View>

            {msg ? <Text style={[styles.msg, { color: msg === "Saved successfully" ? colors.success : "#B3261E" }]} testID="profile-msg">{msg}</Text> : null}

            <TouchableOpacity onPress={onSave} disabled={saving} style={[styles.saveBtn, saving && { opacity: 0.7 }]} testID="profile-save">
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : <Text style={styles.saveBtnText}>Save details</Text>}
            </TouchableOpacity>
          </View>
          </>
          ) : null}

          {/* Fingerprint / Biometric login card — only on supported devices */}
          {biometricAvailable ? (
            <View style={styles.bioCard}>
              <View style={styles.bioCardHead}>
                <View style={styles.bioIcon}>
                  <Feather name={biometricReady ? "shield" : "unlock"} size={18} color={colors.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.bioCardTitle}>
                    {biometricReady ? "Fingerprint login enabled" : "Fingerprint login"}
                  </Text>
                  <Text style={styles.bioCardSub}>
                    {biometricReady
                      ? "Tap your fingerprint to sign in next time — no password needed."
                      : "Skip typing your password — sign in with your phone's fingerprint or Face ID."}
                  </Text>
                </View>
              </View>
              <TouchableOpacity
                onPress={onToggleBiometric}
                disabled={bioBusy}
                style={[styles.bioToggleBtn, biometricReady && styles.bioToggleBtnOff, bioBusy && { opacity: 0.6 }]}
                testID="profile-toggle-biometric"
              >
                {bioBusy ? (
                  <ActivityIndicator size="small" color={biometricReady ? "#B3261E" : colors.primaryFg} />
                ) : (
                  <Text style={[styles.bioToggleBtnText, biometricReady && { color: "#B3261E" }]}>
                    {biometricReady ? "Disable Fingerprint Login" : "Enable Fingerprint Login"}
                  </Text>
                )}
              </TouchableOpacity>
            </View>
          ) : null}

          <TouchableOpacity onPress={onLogout} style={styles.logoutBtn} testID="profile-logout">
            <Feather name="log-out" size={16} color="#B3261E" />
            <Text style={styles.logoutText}>Logout</Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>

      <ConfirmDialog
        visible={bioDialog === "enable" || bioDialog === "disable"}
        icon="shield"
        title={bioDialog === "disable" ? "Turn off fingerprint login?" : "Use your fingerprint to sign in?"}
        body={bioDialog === "disable"
          ? "You will need your password the next time you sign in."
          : "Your fingerprint stays on this device. We only store a signed key, never the fingerprint itself."}
        confirmLabel={bioDialog === "disable" ? "Turn off" : "Turn on"}
        cancelLabel="Not now"
        destructive={bioDialog === "disable"}
        busy={bioBusy}
        onConfirm={applyBiometricChange}
        onCancel={() => setBioDialog(null)}
        testID="profile-biometric-dialog"
      />

      <ConfirmDialog
        visible={bioDialog === "done-on" || bioDialog === "done-off" || bioDialog === "error"}
        icon={bioDialog === "error" ? "alert-triangle" : bioDialog === "done-on" ? "check-circle" : "unlock"}
        iconTint={bioDialog === "error" ? colors.error : bioDialog === "done-on" ? colors.success : colors.textMuted}
        title={bioDialog === "error"
          ? "Could not update fingerprint login"
          : bioDialog === "done-on" ? "Fingerprint login is on" : "Fingerprint login is off"}
        body={bioDialog === "error"
          ? bioError
          : bioDialog === "done-on"
            ? "Tap \u201CSign in with fingerprint\u201D next time you open Slangcart."
            : "Sign in with your email and password from now on."}
        confirmLabel="Got it"
        cancelLabel="Close"
        onConfirm={() => setBioDialog(null)}
        onCancel={() => setBioDialog(null)}
        testID="profile-biometric-result"
      />

      {/* Full-screen avatar preview — opens when user taps their photo.
          Same UX pattern used for chat images so it feels familiar. */}
      <Modal
        visible={avatarPreviewOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setAvatarPreviewOpen(false)}
        statusBarTranslucent
      >
        <Pressable
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.94)", alignItems: "center", justifyContent: "center" }}
          onPress={() => setAvatarPreviewOpen(false)}
          testID="profile-avatar-preview-backdrop"
        >
          {profileImage ? (
            <Image source={{ uri: profileImage }} style={{ width: "100%", height: "100%" }} resizeMode="contain" />
          ) : null}
          <TouchableOpacity
            onPress={() => setAvatarPreviewOpen(false)}
            style={{ position: "absolute", top: 50, right: 18, width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(255,255,255,0.18)", alignItems: "center", justifyContent: "center" }}
            testID="profile-avatar-preview-close"
          >
            <Feather name="x" size={24} color="#FFFFFF" />
          </TouchableOpacity>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  container: { padding: spacing.screen, paddingBottom: 60 },
  overline: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginBottom: 8 },
  h1: { fontSize: 30, fontWeight: "800", color: colors.textMain, letterSpacing: -1 },
  subtitle: { fontSize: 14, color: colors.textMuted, marginTop: 4, marginBottom: 20 },
  codeCard: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.primary, borderRadius: radii.card, padding: 20, marginBottom: 28 },
  codeLabel: { color: "rgba(255,255,255,0.7)", fontSize: 10, letterSpacing: 2, fontWeight: "700" },
  code: { color: colors.primaryFg, fontSize: 26, fontWeight: "800", letterSpacing: 3, marginTop: 4 },
  kycCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 16, borderRadius: 16, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, marginBottom: 28 },
  // ─── Phase 2B UX polish: grouped settings list ───
  // Section labels above logical groups (ACCOUNT, SELL ON SLANGCART).
  groupLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: spacing.sectionGap, marginBottom: 10, paddingHorizontal: 4 },
  // Group container: white card holding several rows separated by hairlines.
  // Replaces the previous pattern where each row was its own card with
  // marginBottom: 28 — created a "stranded" disconnected feel.
  groupCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, overflow: "hidden" },
  // Single row inside a groupCard.
  rowItem: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: spacing.cardPad, paddingVertical: 14 },
  // Hairline divider between rows in the same group.
  rowDivider: { height: StyleSheet.hairlineWidth, backgroundColor: colors.border, marginLeft: spacing.cardPad + 22 /* dot + gap */ },
  kycDot: { width: 10, height: 10, borderRadius: 5 },
  kycTitle: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  kycSub: { fontSize: 11, color: colors.textMuted, marginTop: 2, letterSpacing: 1, fontWeight: "700" },
  sectionLabel: { fontSize: 11, letterSpacing: 2, color: colors.textMuted, fontWeight: "700", marginTop: spacing.sectionGap, marginBottom: 6 },
  // White card wrapping the entire payout-details form so it visually
  // belongs to the same group as the section label above (matches the
  // groupCard pattern used by ACCOUNT / SELL ON SLANGCART).
  payoutCard: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 16, padding: spacing.cardPad },
  helperText: { fontSize: 13, color: colors.textMuted, marginBottom: 16 },
  formGroup: { marginBottom: 14 },
  label: { fontSize: 12, color: colors.textMuted, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 15, color: colors.textMain },
  msg: { fontSize: 13, marginTop: 8 },
  saveBtn: { backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 16, alignItems: "center", marginTop: 16 },
  saveBtnText: { color: colors.primaryFg, fontWeight: "700", fontSize: 15 },
  // Logout: subtle outlined button instead of naked text — clearer affordance
  // and visually anchors the bottom of the screen.
  logoutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: spacing.sectionGap, marginBottom: 8, paddingVertical: 14, borderRadius: radii.button, borderWidth: 1, borderColor: "#F2B8B5", backgroundColor: "#FFF6F5" },
  // Fingerprint / Biometric card
  bioCard: {
    marginTop: spacing.sectionGap,
    padding: 16,
    borderRadius: radii.card,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bioCardHead: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  bioIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  bioCardTitle: { fontSize: 15, fontWeight: "800", color: colors.textMain, marginBottom: 2 },
  bioCardSub: { fontSize: 12, color: colors.textMuted, lineHeight: 17 },
  bioToggleBtn: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: radii.button,
    backgroundColor: colors.primary,
    alignItems: "center",
  },
  bioToggleBtnOff: { backgroundColor: "#FFF6F5", borderWidth: 1, borderColor: "#F2B8B5" },
  bioToggleBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14, letterSpacing: 0.3 },
  logoutText: { color: "#B3261E", fontSize: 14, fontWeight: "700" },
});
